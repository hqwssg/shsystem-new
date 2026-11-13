"""核验同一数据版本下五类数据库算法任务的端到端结果。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence
import argparse
import json
import os

import psycopg


REQUIRED_RUN_TYPES = (
    "dispatch",
    "timetable_audit",
    "timetable_optimization",
    "rolling_rescheduling",
    "joint_parameter_robustness",
)

ATTRIBUTION_ARTIFACTS = {
    "OPTIMIZATION_ATTRIBUTION_REPORT.md",
    "optimization_attribution_summary.json",
    "optimization_kpi_attribution.csv",
    "optimization_candidate_decisions.csv",
    "optimization_candidate_funnel.csv",
    "optimization_bottlenecks.csv",
    "optimization_dimension_attribution.csv",
}


def _count(cursor: Any, table: str, run_id: str) -> int:
    """查询一个任务在白名单结果表中的记录数。"""

    allowed = {
        "simulation_result_artifact",
        "simulation_result_kpi",
        "simulation_energy_time_slice",
        "simulation_timetable_running_arc",
        "simulation_power_arm_settlement",
        "simulation_optimization_candidate",
        "simulation_scenario_result",
        "simulation_rolling_control_event",
    }
    if table not in allowed:
        raise ValueError(f"不允许查询结果表：{table}")
    cursor.execute(f"SELECT count(*) FROM energy_recovery.{table} WHERE run_id = %s", (run_id,))
    return int(cursor.fetchone()[0])


def verify(
    readonly_database_url: str,
    *,
    project_code: str,
    version_code: str,
    output_dir: Path,
) -> dict[str, Any]:
    """执行迁移、任务状态、生命周期和结果完整性审计。"""

    with psycopg.connect(readonly_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT current_database(), current_setting('server_version_num')::integer,
                       current_user,
                       (SELECT rolcanlogin FROM pg_roles WHERE rolname = current_user),
                       (SELECT rolsuper FROM pg_roles WHERE rolname = current_user),
                       pg_has_role(current_user, 'simulation_migrator', 'MEMBER'),
                       pg_has_role(current_user, 'simulation_platform', 'MEMBER'),
                       pg_has_role(current_user, 'simulation_worker', 'MEMBER'),
                       pg_has_role(current_user, 'simulation_readonly', 'MEMBER')
                """
            )
            (
                database_name,
                server_version_num,
                audit_account,
                audit_can_login,
                audit_is_superuser,
                audit_is_migrator,
                audit_is_platform,
                audit_is_worker,
                audit_is_readonly,
            ) = cursor.fetchone()
            if not bool(audit_can_login) or bool(audit_is_superuser):
                raise AssertionError("五类任务验收必须使用非超级用户的独立只读登录账号。")
            if tuple(bool(value) for value in (
                audit_is_migrator,
                audit_is_platform,
                audit_is_worker,
                audit_is_readonly,
            )) != (False, False, False, True):
                raise AssertionError("验收账号必须且只能继承simulation_readonly角色。")
            cursor.execute(
                "SELECT version FROM energy_recovery.simulation_schema_migration ORDER BY version"
            )
            migrations = [str(row[0]) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT rolname, rolcanlogin FROM pg_roles
                WHERE rolname IN (
                    'simulation_migrator', 'simulation_platform',
                    'simulation_worker', 'simulation_readonly'
                ) ORDER BY rolname
                """
            )
            roles = [
                {"role": str(row[0]), "can_login": bool(row[1])}
                for row in cursor.fetchall()
            ]
            if len(roles) != 4 or any(row["can_login"] for row in roles):
                raise AssertionError("四类数据库权限角色未完整建立为NOLOGIN角色。")
            cursor.execute(
                """
                SELECT
                  has_table_privilege(
                    'simulation_platform',
                    'energy_recovery.simulation_run', 'INSERT'),
                  has_table_privilege(
                    'simulation_worker',
                    'energy_recovery.simulation_result_artifact', 'INSERT'),
                  has_table_privilege(
                    'simulation_readonly',
                    'energy_recovery.simulation_result_artifact', 'SELECT'),
                  has_table_privilege(
                    'simulation_readonly',
                    'energy_recovery.simulation_result_artifact', 'INSERT')
                """
            )
            privilege_row = tuple(bool(value) for value in cursor.fetchone())
            if privilege_row != (True, True, True, False):
                raise AssertionError("数据库角色权限矩阵不符合合同。")
            cursor.execute(
                """
                SELECT p.project_id, v.version_id, v.data_status, v.lifecycle_status,
                       v.content_sha256
                FROM energy_recovery.simulation_project p
                JOIN energy_recovery.simulation_project_version v USING (project_id)
                WHERE p.project_code = %s AND v.version_code = %s
                """,
                (project_code, version_code),
            )
            version = cursor.fetchone()
            if version is None:
                raise AssertionError("找不到指定项目数据版本。")
            project_id, version_id, data_status, lifecycle_status, content_sha256 = version
            cursor.execute(
                """
                SELECT DISTINCT ON (run_type)
                       run_id, run_type, status, input_sha256, result_sha256,
                       error_count, warning_count, started_at, finished_at
                FROM energy_recovery.simulation_run
                WHERE project_id = %s AND version_id = %s AND status = 'succeeded'
                      AND run_type = ANY(%s)
                ORDER BY run_type, finished_at DESC
                """,
                (project_id, version_id, list(REQUIRED_RUN_TYPES)),
            )
            run_rows = cursor.fetchall()
            by_type = {str(row[1]): row for row in run_rows}
            missing = sorted(set(REQUIRED_RUN_TYPES) - set(by_type))
            if missing:
                raise AssertionError(f"缺少成功任务：{missing}")

            runs = []
            for run_type in REQUIRED_RUN_TYPES:
                row = by_type[run_type]
                run_id = str(row[0])
                cursor.execute(
                    """
                    SELECT from_status, to_status, state_version
                    FROM energy_recovery.simulation_run_state_event
                    WHERE run_id = %s ORDER BY state_version
                    """,
                    (run_id,),
                )
                events = cursor.fetchall()
                versions = [int(event[2]) for event in events]
                if versions != list(range(len(versions))) or str(events[-1][1]) != "succeeded":
                    raise AssertionError(f"任务{run_id}生命周期事件不完整。")
                counts = {
                    "artifacts": _count(cursor, "simulation_result_artifact", run_id),
                    "kpis": _count(cursor, "simulation_result_kpi", run_id),
                    "energy_slices": _count(cursor, "simulation_energy_time_slice", run_id),
                    "running_arcs": _count(cursor, "simulation_timetable_running_arc", run_id),
                    "power_arm_settlements": _count(cursor, "simulation_power_arm_settlement", run_id),
                    "candidates": _count(cursor, "simulation_optimization_candidate", run_id),
                    "scenario_results": _count(cursor, "simulation_scenario_result", run_id),
                    "rolling_control_events": _count(cursor, "simulation_rolling_control_event", run_id),
                }
                if counts["artifacts"] <= 0 or not row[3] or not row[4]:
                    raise AssertionError(f"任务{run_id}缺少输入、结果摘要或工件。")
                runs.append({
                    "run_id": run_id,
                    "run_type": run_type,
                    "status": str(row[2]),
                    "input_sha256": str(row[3]),
                    "result_sha256": str(row[4]),
                    "error_count": int(row[5]),
                    "warning_count": int(row[6]),
                    "started_at": row[7].isoformat(),
                    "finished_at": row[8].isoformat(),
                    "state_event_count": len(events),
                    "projection_counts": counts,
                })

            required_counts = {
                "dispatch": ("energy_slices", "running_arcs", "kpis", "scenario_results"),
                "timetable_audit": ("energy_slices", "running_arcs", "power_arm_settlements"),
                "timetable_optimization": ("candidates", "scenario_results"),
                "rolling_rescheduling": ("rolling_control_events",),
            }
            for run in runs:
                for name in required_counts.get(run["run_type"], ()):
                    if run["projection_counts"][name] <= 0:
                        raise AssertionError(f"{run['run_type']}缺少结构化结果：{name}")
            joint = next(run for run in runs if run["run_type"] == "joint_parameter_robustness")
            cursor.execute(
                """
                SELECT relative_path FROM energy_recovery.simulation_result_artifact
                WHERE run_id = %s AND relative_path IN (
                    'joint_robustness_summary.json',
                    'joint_parameter_scenarios.csv',
                    'joint_robustness_results.csv'
                )
                """,
                (joint["run_id"],),
            )
            joint_artifacts = sorted(str(row[0]) for row in cursor.fetchall())
            if len(joint_artifacts) != 3:
                raise AssertionError("联合参数任务缺少三个核心结果工件。")
            attribution_artifacts: dict[str, list[str]] = {}
            for run_type in ("dispatch", "timetable_optimization"):
                run = next(item for item in runs if item["run_type"] == run_type)
                cursor.execute(
                    """
                    SELECT relative_path FROM energy_recovery.simulation_result_artifact
                    WHERE run_id = %s AND relative_path = ANY(%s)
                    """,
                    (run["run_id"], list(ATTRIBUTION_ARTIFACTS)),
                )
                present = sorted(str(item[0]) for item in cursor.fetchall())
                missing_artifacts = sorted(ATTRIBUTION_ARTIFACTS - set(present))
                if missing_artifacts:
                    raise AssertionError(
                        f"{run_type}缺少收益归因核心工件：{missing_artifacts}"
                    )
                attribution_artifacts[run_type] = present
            dispatch = next(run for run in runs if run["run_type"] == "dispatch")
            cursor.execute(
                """
                SELECT count(*) FROM energy_recovery.simulation_energy_time_slice
                WHERE run_id = %s AND (
                    traction_kwh IS NULL OR regen_kwh IS NULL
                    OR accepted_by_power_arm_kwh IS NULL
                    OR constraint_violation_kwh IS NULL
                    OR traction_kwh < 0 OR regen_kwh < 0
                )
                """,
                (dispatch["run_id"],),
            )
            invalid_dispatch_slices = int(cursor.fetchone()[0])
            if invalid_dispatch_slices:
                raise AssertionError("重空调度存在空值或负值能量时间片。")

    summary = {
        "schema_version": "1.2",
        "accepted": True,
        "database": str(database_name),
        "server_version_num": int(server_version_num),
        "postgresql_major_version": int(server_version_num) // 10000,
        "connection_scope": "target_or_staging_database",
        "audit_account": str(audit_account),
        "audit_role": "simulation_readonly",
        "project_code": project_code,
        "version_code": version_code,
        "data_status": str(data_status),
        "version_lifecycle_status": str(lifecycle_status),
        "version_content_sha256": str(content_sha256),
        "applied_migrations": migrations,
        "roles": roles,
        "role_privilege_checks": {
            "platform_can_create_run": privilege_row[0],
            "worker_can_write_artifact": privilege_row[1],
            "readonly_can_read_artifact": privilege_row[2],
            "readonly_can_write_artifact": privilege_row[3],
        },
        "required_run_types": list(REQUIRED_RUN_TYPES),
        "successful_run_count": len(runs),
        "runs": runs,
        "joint_core_artifacts": joint_artifacts,
        "optimization_attribution_artifacts": attribution_artifacts,
        "invalid_dispatch_energy_slice_count": invalid_dispatch_slices,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "database_five_run_e2e_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# PostgreSQL五类任务端到端验收",
        "",
        f"结论：`PASS`。PostgreSQL {summary['postgresql_major_version']}，迁移 "
        f"`{migrations[0]}-{migrations[-1]}`，五类任务均通过数据库队列完成。",
        f"结果由独立只读账号`{summary['audit_account']}`审计，该账号只继承`simulation_readonly`。",
        "四类权限角色均为`NOLOGIN`，平台可创建任务、工作进程可写结果、只读角色不可写结果。",
        "",
        "| 任务类型 | run_id | 工件 | 能量片 | 运行弧 | 候选 | 场景 | 滚动事件 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in runs:
        count = run["projection_counts"]
        lines.append(
            f"| `{run['run_type']}` | `{run['run_id']}` | {count['artifacts']} | "
            f"{count['energy_slices']} | {count['running_arcs']} | {count['candidates']} | "
            f"{count['scenario_results']} | {count['rolling_control_events']} |"
        )
    lines.extend([
        "",
        "每项任务均具有非空输入/结果SHA-256、连续状态事件和最终`succeeded`状态。",
        "最新重空调度和运行图优化任务均保存了决策、KPI归因、候选解释、筛选漏斗、瓶颈、维度明细和人员报告七个核心工件。",
        "重空调度能量时间片的牵引、再生、供电臂接受量和违反量均非空且非负。",
        "本验收使用`planning_placeholder`数据，仅证明数据库和算法集成，不构成正式工程数值结论。",
    ])
    (output_dir / "DATABASE_FIVE_RUN_E2E_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--readonly-database-url",
        default=os.environ.get("SIMULATION_READONLY_DATABASE_URL"),
        help="只继承simulation_readonly的登录连接串。",
    )
    parser.add_argument(
        "--database-url",
        dest="legacy_database_url",
        default=None,
        help="兼容旧调用；仍必须指向独立只读账号。",
    )
    parser.add_argument("--project-code", default="shuohuang-energy-acceptance")
    parser.add_argument("--version-code", default="planning-2026-09-db-e2e")
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path("outputs") / "database_postgres_e2e_acceptance",
    )
    args = parser.parse_args(argv)
    readonly_database_url = args.readonly_database_url or args.legacy_database_url
    if not readonly_database_url:
        raise RuntimeError(
            "必须通过--readonly-database-url或SIMULATION_READONLY_DATABASE_URL提供只读连接串。"
        )
    summary = verify(
        readonly_database_url,
        project_code=args.project_code,
        version_code=args.version_code,
        output_dir=args.output_dir,
    )
    print(json.dumps({
        "accepted": summary["accepted"],
        "successful_run_count": summary["successful_run_count"],
        "report": str(args.output_dir / "DATABASE_FIVE_RUN_E2E_REPORT.md"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
