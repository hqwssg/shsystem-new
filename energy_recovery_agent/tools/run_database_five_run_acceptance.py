"""使用平台、工作进程和只读三个独立账号执行五类数据库任务验收。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence
import argparse
import json
import os
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.parameters import validate_run_parameters
from database.postgres import SimulationRepository, connect_postgres
from database.worker import run_one_pending
from tools.verify_database_five_run_e2e import verify


def _account_identity(connection: Any, expected_role: str) -> str:
    """确认连接账号只继承指定模块角色，并返回不含凭据的账号名。"""

    module_roles = (
        "simulation_migrator",
        "simulation_platform",
        "simulation_worker",
        "simulation_readonly",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_user, "
            "(SELECT rolcanlogin FROM pg_roles WHERE rolname=current_user), "
            "(SELECT rolsuper FROM pg_roles WHERE rolname=current_user), "
            + ", ".join(
                f"pg_has_role(current_user, '{role}', 'MEMBER')" for role in module_roles
            )
        )
        row = cursor.fetchone()
    memberships = dict(zip(module_roles, (bool(value) for value in row[3:])))
    if not bool(row[1]) or bool(row[2]):
        raise RuntimeError(f"{expected_role}必须由非超级用户LOGIN账号继承。")
    if memberships != {role: role == expected_role for role in module_roles}:
        raise RuntimeError(f"账号{row[0]}没有且仅继承{expected_role}。")
    return str(row[0])


def _load_manifest(path: Path) -> tuple[dict[str, Path], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    extra_files = {
        str(logical): (ROOT / str(local)).resolve()
        for logical, local in payload["dataset_extra_files"].items()
    }
    runs = []
    for item in payload["runs"]:
        parameters_path = (ROOT / str(item["parameters_file"])).resolve()
        parameters = json.loads(parameters_path.read_text(encoding="utf-8"))
        validate_run_parameters(str(item["run_type"]), parameters)
        runs.append({"run_type": str(item["run_type"]), "parameters": parameters})
    return extra_files, runs


def _pending_count(connection: Any) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM energy_recovery.simulation_run "
            "WHERE status IN ('pending', 'validating', 'running')"
        )
        return int(cursor.fetchone()[0])


def run_acceptance(
    *,
    platform_database_url: str,
    worker_database_url: str,
    readonly_database_url: str,
    project_code: str,
    project_name: str,
    route_name: str,
    version_code: str,
    code_version: str,
    source_dir: Path,
    manifest_path: Path,
    output_dir: Path,
    resource_profile: str,
) -> dict[str, Any]:
    """发布规划版本、逐项运行五类任务，并由只读账号完成结果验收。"""

    extra_files, run_specs = _load_manifest(manifest_path)
    source_dir = source_dir.resolve()
    with connect_postgres(platform_database_url) as platform_connection:
        platform_account = _account_identity(platform_connection, "simulation_platform")
        platform_repository = SimulationRepository(platform_connection)
        imported = platform_repository.import_dataset(
            source_dir,
            project_code=project_code,
            project_name=project_name,
            route_name=route_name,
            version_code=version_code,
            data_status="planning_placeholder",
            source_note="分角色数据库五类任务联调验收数据，不作为正式工程结论。",
            extra_files=extra_files,
        )

        with connect_postgres(worker_database_url) as worker_connection:
            worker_account = _account_identity(worker_connection, "simulation_worker")
            if _pending_count(worker_connection):
                raise RuntimeError(
                    "验收开始前数据库存在运行中或待处理任务；请使用隔离验收库或先清空任务队列。"
                )
            worker_repository = SimulationRepository(worker_connection)
            run_ids: dict[str, str] = {}
            for index, spec in enumerate(run_specs, start=1):
                run_type = spec["run_type"]
                project_id, version_id = platform_repository.resolve_version(
                    project_code, version_code
                )
                run_id = platform_repository.create_run(
                    project_id=project_id,
                    version_id=version_id,
                    run_type=run_type,
                    parameters=spec["parameters"],
                    requested_by="database-five-run-acceptance",
                    code_version=code_version,
                    idempotency_key=f"{version_code}-{run_type}-segregated-v1",
                )
                status = str(platform_repository.get_run(run_id)["status"])
                if status == "pending":
                    result = run_one_pending(
                        worker_repository,
                        f"five-run-acceptance-{index}",
                        lease_seconds=300,
                        heartbeat_interval_s=60,
                        resource_profile=resource_profile,
                    )
                    if result is None or str(result["run_id"]) != str(run_id):
                        raise RuntimeError(f"worker未领取预期任务：{run_type}/{run_id}")
                elif status != "succeeded":
                    raise RuntimeError(f"已有验收任务状态不可复用：{run_type}/{status}")
                final_status = str(platform_repository.get_run(run_id)["status"])
                if final_status != "succeeded":
                    raise RuntimeError(f"验收任务未成功：{run_type}/{final_status}")
                run_ids[run_type] = str(run_id)

    verified = verify(
        readonly_database_url,
        project_code=project_code,
        version_code=version_code,
        output_dir=output_dir,
    )
    summary = {
        "schema_version": "1.0",
        "accepted": bool(verified["accepted"]),
        "project_code": project_code,
        "version_code": version_code,
        "data_status": "planning_placeholder",
        "accounts": {
            "platform": platform_account,
            "worker": worker_account,
            "readonly": verified["audit_account"],
        },
        "role_segregation": {
            "dataset_and_run_creation": "simulation_platform",
            "algorithm_execution_and_result_write": "simulation_worker",
            "result_acceptance": "simulation_readonly",
        },
        "dataset_already_present": bool(imported["already_present"]),
        "run_ids": run_ids,
        "successful_run_count": int(verified["successful_run_count"]),
        "five_run_summary": "database_five_run_e2e_summary.json",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "segregated_account_acceptance_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform-database-url", default=os.environ.get("SIMULATION_PLATFORM_DATABASE_URL")
    )
    parser.add_argument(
        "--worker-database-url", default=os.environ.get("SIMULATION_DATABASE_URL")
    )
    parser.add_argument(
        "--readonly-database-url", default=os.environ.get("SIMULATION_READONLY_DATABASE_URL")
    )
    parser.add_argument("--project-code", default="shuohuang-energy-acceptance")
    parser.add_argument("--project-name", default="朔黄铁路数据库分角色联调验收")
    parser.add_argument("--route-name", default="朔黄铁路")
    parser.add_argument("--version-code", default="planning-2026-09-db-segregated-e2e")
    parser.add_argument("--code-version", default="2026.09.10.3")
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data/real_shuohuang")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "database/examples/five_run_acceptance_manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs/database_postgres_segregated_e2e_acceptance",
    )
    parser.add_argument(
        "--resource-profile", choices=("quick", "standard", "fine"), default="quick"
    )
    args = parser.parse_args(argv)
    missing = [
        name
        for name, value in (
            ("SIMULATION_PLATFORM_DATABASE_URL", args.platform_database_url),
            ("SIMULATION_DATABASE_URL", args.worker_database_url),
            ("SIMULATION_READONLY_DATABASE_URL", args.readonly_database_url),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"缺少分角色数据库连接：{', '.join(missing)}")
    summary = run_acceptance(
        platform_database_url=args.platform_database_url,
        worker_database_url=args.worker_database_url,
        readonly_database_url=args.readonly_database_url,
        project_code=args.project_code,
        project_name=args.project_name,
        route_name=args.route_name,
        version_code=args.version_code,
        code_version=args.code_version,
        source_dir=args.source_dir,
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        resource_profile=args.resource_profile,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
