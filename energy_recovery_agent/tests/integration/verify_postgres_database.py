"""在专用PostgreSQL测试库中验证迁移、导入、并发领取和幂等结果写回。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4
import os
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.postgres import (
    RunLeaseLostError,
    RunStateConflictError,
    SimulationRepository,
    apply_migrations,
    connect_postgres,
    transaction,
)


def _connect():
    dsn = os.environ.get("SIMULATION_TEST_DATABASE_URL")
    if not dsn:
        raise RuntimeError("未设置SIMULATION_TEST_DATABASE_URL，真实库集成测试未执行。")
    connection = connect_postgres(dsn)
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        database_name = str(cursor.fetchone()[0])
    if database_name != "carbon_emissions_test":
        connection.close()
        raise RuntimeError("集成测试只允许连接名为carbon_emissions_test的专用数据库。")
    return connection


def main() -> int:
    connection_a = _connect()
    connection_b = _connect()
    run_ids = []
    project_id = None
    version_id = None
    try:
        apply_migrations(connection_a)
        repository_a = SimulationRepository(connection_a)
        token = uuid4().hex[:12]
        imported = repository_a.import_dataset(
            ROOT / "data" / "real_shuohuang",
            project_code=f"database-integration-{token}",
            project_name="数据库集成测试",
            route_name="测试线路",
            version_code="v1",
            data_status="planning_placeholder",
            source_note="自动化测试，完成后清理",
            extra_files={
                "platform/running_diagram.xlsx": ROOT / "data_templates" / "running_diagram_template.xlsx"
            },
        )
        project_id = imported["project_id"]
        version_id = imported["version_id"]
        idempotent_parameters = {
            "timetable_relative_path": "platform/running_diagram.xlsx",
            "strict_visualizations": False,
        }
        idempotent_run = repository_a.create_run(
            project_id=project_id,
            version_id=version_id,
            run_type="timetable_audit",
            parameters=idempotent_parameters,
            requested_by="database-integration-test",
            idempotency_key=f"idem-{token}",
        )
        repeated_run = repository_a.create_run(
            project_id=project_id,
            version_id=version_id,
            run_type="timetable_audit",
            parameters=dict(reversed(list(idempotent_parameters.items()))),
            requested_by="database-integration-test",
            idempotency_key=f"idem-{token}",
        )
        assert repeated_run == idempotent_run
        run_ids.append(idempotent_run)
        try:
            repository_a.create_run(
                project_id=project_id,
                version_id=version_id,
                run_type="timetable_audit",
                parameters={
                    "timetable_relative_path": "platform/running_diagram.xlsx",
                    "strict_visualizations": True,
                },
                requested_by="database-integration-test",
                idempotency_key=f"idem-{token}",
            )
        except RunStateConflictError:
            pass
        else:
            raise AssertionError("同一幂等键下的不同请求必须被拒绝。")
        run_ids.append(repository_a.create_run(
            project_id=project_id,
            version_id=version_id,
            run_type="timetable_audit",
            parameters=idempotent_parameters,
            requested_by="database-integration-test",
            idempotency_key=f"second-{token}",
        ))

        repository_b = SimulationRepository(connection_b)
        claimed_a = repository_a.claim_next_run("integration-worker-a")
        claimed_b = repository_b.claim_next_run("integration-worker-b")
        assert claimed_a and claimed_b
        assert claimed_a["run_id"] != claimed_b["run_id"]
        assert claimed_a["lease_token"] != claimed_b["lease_token"]

        records = repository_a.load_version_files(version_id)
        assert any(item.relative_path == "platform/running_diagram.xlsx" for item in records)
        for claimed, repository in ((claimed_a, repository_a), (claimed_b, repository_b)):
            from database.snapshots import snapshot_manifest

            repository.freeze_run_snapshot(
                claimed["run_id"],
                version_id,
                snapshot_manifest(records),
                worker_id=claimed["worker_id"],
                lease_token=claimed["lease_token"],
            )
            repository.heartbeat_run(
                claimed["run_id"],
                claimed["worker_id"],
                claimed["lease_token"],
            )
        conflicting_manifest = dict(snapshot_manifest(records))
        conflicting_manifest["snapshot_sha256"] = "f" * 64
        try:
            repository_b.freeze_run_snapshot(
                claimed_b["run_id"],
                version_id,
                conflicting_manifest,
                worker_id=claimed_b["worker_id"],
                lease_token=claimed_b["lease_token"],
            )
        except RunStateConflictError:
            pass
        else:
            raise AssertionError("同一任务的不同输入快照必须被拒绝。")

        first = repository_a.persist_result(
            claimed_a["run_id"], ROOT / "outputs" / "timetable_energy_audit",
            worker_id=claimed_a["worker_id"],
            lease_token=claimed_a["lease_token"],
        )
        repeated = repository_a.persist_result(
            claimed_a["run_id"], ROOT / "outputs" / "timetable_energy_audit",
            worker_id=claimed_a["worker_id"],
            lease_token=claimed_a["lease_token"],
        )
        assert first["already_present"] is False
        assert repeated["already_present"] is True
        assert repository_a.get_run(claimed_a["run_id"])["status"] == "succeeded"

        # 令第二个租约过期并回收，再确认旧工作进程不能续租或写失败状态。
        with transaction(connection_a):
            with connection_a.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE energy_recovery.simulation_run
                    SET lease_expires_at = now() - interval '1 second'
                    WHERE run_id = %s
                    """,
                    (claimed_b["run_id"],),
                )
        recovered = repository_a.requeue_expired_runs(max_attempts=3)
        assert recovered["requeued"] == 1
        try:
            repository_b.heartbeat_run(
                claimed_b["run_id"],
                claimed_b["worker_id"],
                claimed_b["lease_token"],
            )
        except RunLeaseLostError:
            pass
        else:
            raise AssertionError("过期租约不能续期。")
        reclaimed = repository_b.claim_next_run("integration-worker-b")
        assert reclaimed and reclaimed["run_id"] == claimed_b["run_id"]
        assert reclaimed["lease_token"] != claimed_b["lease_token"]
        try:
            repository_a.mark_failed(
                claimed_b["run_id"],
                "旧工作进程迟到写回",
                worker_id=claimed_b["worker_id"],
                lease_token=claimed_b["lease_token"],
            )
        except RunLeaseLostError:
            pass
        else:
            raise AssertionError("旧租约不能覆盖重新领取后的任务。")

        cancelled = repository_a.cancel_run(
            reclaimed["run_id"], "integration_test_cancel"
        )
        assert cancelled is True
        assert repository_a.cancel_run(reclaimed["run_id"]) is False
        assert repository_a.get_run(reclaimed["run_id"])["status"] == "cancelled"

        events = repository_a.load_run_state_events(reclaimed["run_id"])
        assert events
        versions = [int(row["state_version"]) for row in events]
        assert versions == sorted(set(versions))
        assert str(events[-1]["to_status"]) == "cancelled"

        marker = f"rollback-{token}"
        try:
            with transaction(connection_a):
                with connection_a.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO energy_recovery.simulation_run_log
                            (run_id, level, event_code, message)
                        VALUES (%s, 'info', 'rollback_probe', %s)
                        """,
                        (claimed_b["run_id"], marker),
                    )
                    raise RuntimeError("触发回滚")
        except RuntimeError:
            pass
        with connection_a.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM energy_recovery.simulation_run_log WHERE run_id = %s AND message = %s",
                (claimed_b["run_id"], marker),
            )
            assert cursor.fetchone()[0] == 0

        print("postgres database integration: PASS")
        return 0
    finally:
        try:
            connection_a.rollback()
            with transaction(connection_a):
                with connection_a.cursor() as cursor:
                    if project_id is not None:
                        cursor.execute(
                            "DELETE FROM energy_recovery.simulation_run WHERE project_id = %s",
                            (project_id,),
                        )
                    if version_id is not None:
                        cursor.execute(
                            "DELETE FROM energy_recovery.simulation_project_version WHERE version_id = %s",
                            (version_id,),
                        )
                    if project_id is not None:
                        cursor.execute(
                            "DELETE FROM energy_recovery.simulation_project WHERE project_id = %s",
                            (project_id,),
                        )
        finally:
            connection_a.close()
            connection_b.close()


if __name__ == "__main__":
    raise SystemExit(main())
