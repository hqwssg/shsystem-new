"""在专用PostgreSQL测试库中执行平台任务压力与故障注入。"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Callable, Sequence
from uuid import UUID, uuid4


ROOT = Path(__file__).resolve().parents[1]
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
from database.snapshots import snapshot_manifest


SCHEMA_VERSION = "1.0"
RESULT_TABLES = (
    "simulation_result_artifact",
    "simulation_result_kpi",
    "simulation_energy_time_slice",
    "simulation_timetable_running_arc",
    "simulation_power_arm_settlement",
    "simulation_optimization_candidate",
    "simulation_scenario_result",
    "simulation_rolling_control_event",
    "simulation_timetable_audit_summary",
    "simulation_optimization_decision",
)


def _percentile(values: Sequence[float], probability: float) -> float:
    """使用线性插值计算百分位。"""

    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _latency_summary(values_s: Sequence[float]) -> dict[str, float | int]:
    """汇总操作时延，报告值统一使用毫秒。"""

    values_ms = [value * 1000.0 for value in values_s]
    return {
        "count": len(values_ms),
        "min_ms": round(min(values_ms), 3) if values_ms else 0.0,
        "median_ms": round(statistics.median(values_ms), 3) if values_ms else 0.0,
        "p95_ms": round(_percentile(values_ms, 0.95), 3),
        "p99_ms": round(_percentile(values_ms, 0.99), 3),
        "max_ms": round(max(values_ms), 3) if values_ms else 0.0,
    }


def _connect_test_database(database_url: str):
    """只允许连接名称以_test结尾的隔离数据库。"""

    connection = connect_postgres(database_url)
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_setting('server_version_num')::integer")
        database_name, server_version_num = cursor.fetchone()
    if not str(database_name).endswith("_test"):
        connection.close()
        raise RuntimeError(
            f"压力与故障测试只允许连接名称以_test结尾的数据库，当前为{database_name!r}。"
        )
    return connection, str(database_name), int(server_version_num)


def _partition(total: int, worker_count: int) -> list[list[int]]:
    """按工作进程编号稳定划分操作序号。"""

    return [list(range(worker, total, worker_count)) for worker in range(worker_count)]


def _run_parallel(
    worker_count: int,
    callback: Callable[[int], Any],
) -> list[Any]:
    """并发运行固定数量的独立数据库连接任务。"""

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(callback, range(worker_count)))


def _force_lease_expired(connection, run_id: UUID) -> None:
    """故障注入：把指定测试任务的租约调整到过去。"""

    with transaction(connection):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE energy_recovery.simulation_run
                SET lease_expires_at = now() - interval '1 second'
                WHERE run_id = %s AND status IN ('validating', 'running')
                """,
                (run_id,),
            )
            if cursor.rowcount != 1:
                raise AssertionError(f"无法注入租约过期：{run_id}")


def _result_counts(connection, run_id: UUID) -> dict[str, int]:
    """统计一个任务在全部直接结果表中的残留行。"""

    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table in RESULT_TABLES:
            cursor.execute(
                f"SELECT count(*) FROM energy_recovery.{table} WHERE run_id = %s",
                (run_id,),
            )
            counts[table] = int(cursor.fetchone()[0])
    return counts


def _expect_lease_lost(callback: Callable[[], Any]) -> tuple[bool, str]:
    """确认旧工作进程操作被租约门禁拒绝。"""

    try:
        callback()
    except RunLeaseLostError as exc:
        return True, str(exc)
    except Exception as exc:
        return False, f"错误异常类型 {type(exc).__name__}: {exc}"
    return False, "操作未被拒绝"


def _fault_row(
    case_id: str,
    injection: str,
    expected: str,
    passed: bool,
    evidence: Any,
) -> dict[str, Any]:
    """形成统一故障测试记录。"""

    return {
        "case_id": case_id,
        "injection": injection,
        "expected_behavior": expected,
        "passed": bool(passed),
        "evidence_json": json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str),
    }


@dataclass
class StressContext:
    """本轮测试创建的数据版本及公共参数。"""

    project_id: UUID
    version_id: UUID
    token: str
    records: tuple[Any, ...]


def _create_run(
    repository: SimulationRepository,
    context: StressContext,
    key: str,
    *,
    strict_visualizations: bool = False,
) -> UUID:
    """创建统一的轻量运行图审查任务。"""

    return repository.create_run(
        project_id=context.project_id,
        version_id=context.version_id,
        run_type="timetable_audit",
        parameters={
            "timetable_relative_path": "platform/running_diagram.xlsx",
            "strict_visualizations": strict_visualizations,
        },
        requested_by="platform-stress-test",
        code_version="stress-fault-test",
        idempotency_key=key,
    )


def _run_pressure_phase(
    database_url: str,
    context: StressContext,
    *,
    task_count: int,
    worker_count: int,
    idempotency_burst: int,
    max_operation_p95_ms: float,
    min_claim_throughput_per_s: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """执行并发创建、幂等、领取、心跳和取消压力测试。"""

    samples: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    partitions = _partition(task_count, worker_count)

    def create_worker(worker_index: int) -> dict[str, Any]:
        connection, _name, _version = _connect_test_database(database_url)
        repository = SimulationRepository(connection)
        local_ids: list[str] = []
        local_samples: list[dict[str, Any]] = []
        local_errors: list[dict[str, Any]] = []
        try:
            for index in partitions[worker_index]:
                started = time.perf_counter()
                try:
                    run_id = _create_run(
                        repository, context, f"queue-{context.token}-{index:05d}"
                    )
                    local_ids.append(str(run_id))
                    status = "success"
                    error = ""
                except Exception as exc:
                    status = "error"
                    error = f"{type(exc).__name__}: {exc}"
                    local_errors.append({"phase": "create", "index": index, "error": error})
                local_samples.append({
                    "operation": "create", "worker": f"creator-{worker_index}",
                    "item_index": index, "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "status": status, "error": error,
                })
        finally:
            connection.close()
        return {"ids": local_ids, "samples": local_samples, "errors": local_errors}

    create_started = time.perf_counter()
    create_results = _run_parallel(worker_count, create_worker)
    create_wall_s = time.perf_counter() - create_started
    created_ids = [value for result in create_results for value in result["ids"]]
    samples.extend(value for result in create_results for value in result["samples"])
    errors.extend(value for result in create_results for value in result["errors"])

    shared_key = f"idem-burst-{context.token}"

    def idempotent_call(index: int, conflicting: bool = False) -> dict[str, Any]:
        connection, _name, _version = _connect_test_database(database_url)
        repository = SimulationRepository(connection)
        started = time.perf_counter()
        try:
            try:
                run_id = _create_run(
                    repository, context, shared_key,
                    strict_visualizations=conflicting,
                )
                return {
                    "run_id": str(run_id), "conflict": False,
                    "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "error": "",
                }
            except RunStateConflictError as exc:
                return {
                    "run_id": "", "conflict": True,
                    "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "error": str(exc),
                }
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=min(worker_count, idempotency_burst)) as executor:
        idempotent_results = list(executor.map(idempotent_call, range(idempotency_burst)))
    idempotent_ids = {item["run_id"] for item in idempotent_results if item["run_id"]}
    for index, item in enumerate(idempotent_results):
        samples.append({
            "operation": "idempotent_create", "worker": f"idem-{index}",
            "item_index": index, "latency_ms": item["latency_ms"],
            "status": "conflict" if item["conflict"] else "success", "error": item["error"],
        })

    conflict_count = max(4, min(idempotency_burst, worker_count))
    with ThreadPoolExecutor(max_workers=conflict_count) as executor:
        conflicting_results = list(
            executor.map(lambda index: idempotent_call(index, True), range(conflict_count))
        )
    for index, item in enumerate(conflicting_results):
        samples.append({
            "operation": "idempotency_conflict", "worker": f"conflict-{index}",
            "item_index": index, "latency_ms": item["latency_ms"],
            "status": "expected_conflict" if item["conflict"] else "unexpected_success",
            "error": item["error"],
        })

    expected_claim_count = task_count + 1

    def claim_worker(worker_index: int) -> dict[str, Any]:
        connection, _name, _version = _connect_test_database(database_url)
        repository = SimulationRepository(connection)
        local_jobs: list[dict[str, Any]] = []
        local_samples: list[dict[str, Any]] = []
        try:
            while True:
                started = time.perf_counter()
                job = repository.claim_next_run(
                    f"stress-worker-{worker_index}", lease_seconds=120
                )
                elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
                if job is None:
                    break
                local_jobs.append(job)
                local_samples.append({
                    "operation": "claim", "worker": f"stress-worker-{worker_index}",
                    "item_index": len(local_jobs) - 1, "latency_ms": elapsed_ms,
                    "status": "success", "error": "",
                })
        finally:
            connection.close()
        return {"jobs": local_jobs, "samples": local_samples}

    claim_started = time.perf_counter()
    claim_results = _run_parallel(worker_count, claim_worker)
    claim_wall_s = time.perf_counter() - claim_started
    claimed_jobs = [job for result in claim_results for job in result["jobs"]]
    samples.extend(value for result in claim_results for value in result["samples"])
    claimed_ids = [str(job["run_id"]) for job in claimed_jobs]
    foreign_claims = [
        run_id for run_id, job in zip(claimed_ids, claimed_jobs)
        if UUID(str(job["project_id"])) != context.project_id
    ]

    heartbeat_partitions = [claimed_jobs[index::worker_count] for index in range(worker_count)]

    def heartbeat_worker(worker_index: int) -> list[dict[str, Any]]:
        connection, _name, _version = _connect_test_database(database_url)
        repository = SimulationRepository(connection)
        local: list[dict[str, Any]] = []
        try:
            for index, job in enumerate(heartbeat_partitions[worker_index]):
                started = time.perf_counter()
                try:
                    repository.heartbeat_run(
                        job["run_id"], job["worker_id"], job["lease_token"], lease_seconds=120
                    )
                    status, error = "success", ""
                except Exception as exc:
                    status, error = "error", f"{type(exc).__name__}: {exc}"
                local.append({
                    "operation": "heartbeat", "worker": f"heartbeat-{worker_index}",
                    "item_index": index, "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "status": status, "error": error,
                })
        finally:
            connection.close()
        return local

    heartbeat_results = _run_parallel(worker_count, heartbeat_worker)
    samples.extend(value for result in heartbeat_results for value in result)

    def cancel_worker(worker_index: int) -> list[dict[str, Any]]:
        connection, _name, _version = _connect_test_database(database_url)
        repository = SimulationRepository(connection)
        local: list[dict[str, Any]] = []
        try:
            for index, job in enumerate(heartbeat_partitions[worker_index]):
                started = time.perf_counter()
                try:
                    cancelled = repository.cancel_run(job["run_id"], "stress_cleanup")
                    status, error = ("success" if cancelled else "unexpected_false"), ""
                except Exception as exc:
                    status, error = "error", f"{type(exc).__name__}: {exc}"
                local.append({
                    "operation": "cancel", "worker": f"cancel-{worker_index}",
                    "item_index": index, "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "status": status, "error": error,
                })
        finally:
            connection.close()
        return local

    cancel_results = _run_parallel(worker_count, cancel_worker)
    samples.extend(value for result in cancel_results for value in result)

    operation_latencies_s: dict[str, list[float]] = {}
    for sample in samples:
        operation_latencies_s.setdefault(sample["operation"], []).append(
            float(sample["latency_ms"]) / 1000.0
        )
        if sample["status"] in {"error", "unexpected_false", "unexpected_success"}:
            errors.append({
                "phase": sample["operation"], "item_index": sample["item_index"],
                "worker": sample["worker"], "error": sample["error"] or sample["status"],
            })

    connection, _name, _version = _connect_test_database(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, count(*), count(*) FILTER (WHERE lease_token IS NOT NULL)
                FROM energy_recovery.simulation_run
                WHERE project_id = %s GROUP BY status ORDER BY status
                """,
                (context.project_id,),
            )
            status_counts = {
                str(row[0]): {"count": int(row[1]), "active_lease_count": int(row[2])}
                for row in cursor.fetchall()
            }
            cursor.execute(
                """
                SELECT count(*) FROM (
                    SELECT run_id
                    FROM energy_recovery.simulation_run_state_event
                    WHERE run_id = ANY(%s)
                    GROUP BY run_id
                    HAVING array_agg(state_version ORDER BY state_version)
                           <> ARRAY[0,1,2]::bigint[]
                ) invalid
                """,
                ([UUID(value) for value in claimed_ids],),
            )
            invalid_event_sequences = int(cursor.fetchone()[0])
    finally:
        connection.close()

    latencies = {
        operation: _latency_summary(values)
        for operation, values in sorted(operation_latencies_s.items())
    }
    claim_throughput = len(claimed_jobs) / claim_wall_s if claim_wall_s > 0 else 0.0
    p95_passed = all(
        item["p95_ms"] <= max_operation_p95_ms
        for operation, item in latencies.items()
        if operation in {"create", "claim", "heartbeat", "cancel"}
    )
    checks = {
        "all_unique_tasks_created": len(created_ids) == task_count and len(set(created_ids)) == task_count,
        "idempotency_burst_single_run": len(idempotent_ids) == 1 and all(not item["conflict"] for item in idempotent_results),
        "conflicting_idempotency_rejected": all(item["conflict"] for item in conflicting_results),
        "all_tasks_claimed_once": len(claimed_ids) == expected_claim_count and len(set(claimed_ids)) == expected_claim_count,
        "no_foreign_queue_claims": not foreign_claims,
        "all_heartbeats_succeeded": sum(sample["operation"] == "heartbeat" and sample["status"] == "success" for sample in samples) == expected_claim_count,
        "all_cancellations_succeeded": sum(sample["operation"] == "cancel" and sample["status"] == "success" for sample in samples) == expected_claim_count,
        "cancelled_tasks_have_no_lease": status_counts == {"cancelled": {"count": expected_claim_count, "active_lease_count": 0}},
        "state_event_versions_complete": invalid_event_sequences == 0,
        "operation_errors_zero": not errors,
        "operation_p95_within_threshold": p95_passed,
        "claim_throughput_within_threshold": claim_throughput >= min_claim_throughput_per_s,
    }
    summary = {
        "passed": all(checks.values()),
        "configuration": {
            "task_count": task_count,
            "worker_count": worker_count,
            "idempotency_burst": idempotency_burst,
            "max_operation_p95_ms": max_operation_p95_ms,
            "min_claim_throughput_per_s": min_claim_throughput_per_s,
        },
        "checks": checks,
        "create_wall_s": round(create_wall_s, 6),
        "create_throughput_per_s": round(task_count / create_wall_s, 3) if create_wall_s else 0.0,
        "claim_wall_s": round(claim_wall_s, 6),
        "claim_throughput_per_s": round(claim_throughput, 3),
        "latencies": latencies,
        "claimed_worker_count": len({str(job["worker_id"]) for job in claimed_jobs}),
        "status_counts": status_counts,
        "error_count": len(errors),
    }
    return summary, samples, errors


def _run_fault_phase(
    database_url: str,
    context: StressContext,
    *,
    result_dir: Path,
) -> list[dict[str, Any]]:
    """执行崩溃、旧令牌、取消、最大重试和事务回滚故障注入。"""

    connection, _name, _version = _connect_test_database(database_url)
    repository = SimulationRepository(connection)
    manifest = snapshot_manifest(context.records)
    rows: list[dict[str, Any]] = []
    trigger_created = False
    try:
        crash_run = _create_run(repository, context, f"fault-crash-{context.token}")
        old_job = repository.claim_next_run("crashed-worker", lease_seconds=120)
        assert old_job and old_job["run_id"] == crash_run
        _force_lease_expired(connection, crash_run)
        recovered_counts = repository.requeue_expired_runs(max_attempts=3)
        new_job = repository.claim_next_run("replacement-worker", lease_seconds=120)
        crash_passed = (
            recovered_counts == {"requeued": 1, "failed": 0}
            and new_job is not None
            and new_job["run_id"] == crash_run
            and new_job["lease_token"] != old_job["lease_token"]
            and new_job["attempt_count"] == 2
        )
        rows.append(_fault_row(
            "PF-F01", "工作进程崩溃并令租约过期", "任务重新排队并由新令牌领取",
            crash_passed,
            {"recovery": recovered_counts, "old_attempt": old_job["attempt_count"], "new_attempt": new_job["attempt_count"] if new_job else None},
        ))

        stale_checks = {
            "heartbeat": _expect_lease_lost(lambda: repository.heartbeat_run(
                crash_run, old_job["worker_id"], old_job["lease_token"], lease_seconds=120
            )),
            "freeze_snapshot": _expect_lease_lost(lambda: repository.freeze_run_snapshot(
                crash_run, context.version_id, manifest,
                worker_id=old_job["worker_id"], lease_token=old_job["lease_token"],
            )),
            "mark_failed": _expect_lease_lost(lambda: repository.mark_failed(
                crash_run, "stale worker",
                worker_id=old_job["worker_id"], lease_token=old_job["lease_token"],
            )),
            "persist_result": _expect_lease_lost(lambda: repository.persist_result(
                crash_run, result_dir,
                worker_id=old_job["worker_id"], lease_token=old_job["lease_token"],
            )),
        }
        rows.append(_fault_row(
            "PF-F02", "旧工作进程迟到续租/冻结/失败/写结果", "四类操作全部被旧令牌门禁拒绝",
            all(value[0] for value in stale_checks.values()), stale_checks,
        ))
        assert new_job is not None
        repository.cancel_run(crash_run, "fault_case_finished")

        cancel_run = _create_run(repository, context, f"fault-cancel-{context.token}")
        cancel_job = repository.claim_next_run("cancelled-worker", lease_seconds=120)
        assert cancel_job and cancel_job["run_id"] == cancel_run
        cancelled = repository.cancel_run(cancel_run, "operator_cancelled_during_execution")
        cancelled_ops = {
            "heartbeat": _expect_lease_lost(lambda: repository.heartbeat_run(
                cancel_run, cancel_job["worker_id"], cancel_job["lease_token"], lease_seconds=120
            )),
            "mark_failed": _expect_lease_lost(lambda: repository.mark_failed(
                cancel_run, "late failure",
                worker_id=cancel_job["worker_id"], lease_token=cancel_job["lease_token"],
            )),
            "persist_result": _expect_lease_lost(lambda: repository.persist_result(
                cancel_run, result_dir,
                worker_id=cancel_job["worker_id"], lease_token=cancel_job["lease_token"],
            )),
        }
        cancel_state = repository.get_run(cancel_run)
        rows.append(_fault_row(
            "PF-F03", "活跃任务被平台取消", "租约立即失效，迟到操作不能覆盖cancelled终态",
            cancelled and cancel_state["status"] == "cancelled"
            and all(value[0] for value in cancelled_ops.values()),
            {"status": cancel_state["status"], "late_operations": cancelled_ops},
        ))

        retry_run = _create_run(repository, context, f"fault-max-retry-{context.token}")
        retry_evidence: list[dict[str, Any]] = []
        for attempt in range(1, 4):
            job = repository.claim_next_run(f"retry-worker-{attempt}", lease_seconds=120)
            assert job and job["run_id"] == retry_run
            _force_lease_expired(connection, retry_run)
            counts = repository.requeue_expired_runs(max_attempts=3)
            retry_evidence.append({
                "attempt": attempt,
                "attempt_count": job["attempt_count"],
                "recovery": counts,
                "status": repository.get_run(retry_run)["status"],
            })
        retry_state = repository.get_run(retry_run)
        retry_events = repository.load_run_state_events(retry_run)
        rows.append(_fault_row(
            "PF-F04", "任务连续三次崩溃", "前两次重排，第三次达到上限后失败且不再领取",
            [item["status"] for item in retry_evidence] == ["pending", "pending", "failed"]
            and retry_state["attempt_count"] == 3
            and retry_state["status"] == "failed"
            and repository.claim_next_run("retry-worker-4") is None
            and str(retry_events[-1]["reason"]) == "lease_expired_attempt_limit",
            {"attempts": retry_evidence, "final_error": retry_state["error_message"]},
        ))

        rollback_run = _create_run(repository, context, f"fault-rollback-{context.token}")
        rollback_job = repository.claim_next_run("rollback-worker", lease_seconds=120)
        assert rollback_job and rollback_job["run_id"] == rollback_run
        repository.freeze_run_snapshot(
            rollback_run, context.version_id, manifest,
            worker_id=rollback_job["worker_id"], lease_token=rollback_job["lease_token"],
        )
        with transaction(connection):
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE OR REPLACE FUNCTION energy_recovery.platform_stress_injected_failure()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                        RAISE EXCEPTION 'platform_stress_injected_projection_failure';
                    END
                    $$
                    """
                )
                cursor.execute(
                    """
                    CREATE TRIGGER platform_stress_injected_failure
                    BEFORE INSERT ON energy_recovery.simulation_timetable_audit_summary
                    FOR EACH ROW EXECUTE FUNCTION energy_recovery.platform_stress_injected_failure()
                    """
                )
        trigger_created = True
        rollback_error = ""
        try:
            repository.persist_result(
                rollback_run, result_dir,
                worker_id=rollback_job["worker_id"], lease_token=rollback_job["lease_token"],
            )
        except Exception as exc:
            rollback_error = f"{type(exc).__name__}: {exc}"
        rollback_counts = _result_counts(connection, rollback_run)
        rollback_state = repository.get_run(rollback_run)
        rows.append(_fault_row(
            "PF-F05", "结果投影在写入工件后中途抛错", "全部结果表回滚且任务保持running",
            "platform_stress_injected_projection_failure" in rollback_error
            and sum(rollback_counts.values()) == 0
            and rollback_state["status"] == "running"
            and rollback_state["result_sha256"] is None,
            {"error": rollback_error, "result_counts": rollback_counts, "status": rollback_state["status"]},
        ))
        with transaction(connection):
            with connection.cursor() as cursor:
                cursor.execute(
                    "DROP TRIGGER IF EXISTS platform_stress_injected_failure ON energy_recovery.simulation_timetable_audit_summary"
                )
                cursor.execute(
                    "DROP FUNCTION IF EXISTS energy_recovery.platform_stress_injected_failure()"
                )
        trigger_created = False
        repository.mark_failed(
            rollback_run, "expected injected projection failure",
            worker_id=rollback_job["worker_id"], lease_token=rollback_job["lease_token"],
        )

        event_checks: dict[str, Any] = {}
        for run_id, label in (
            (crash_run, "crash"),
            (cancel_run, "cancel"),
            (retry_run, "retry_limit"),
            (rollback_run, "rollback"),
        ):
            events = repository.load_run_state_events(run_id)
            versions = [int(item["state_version"]) for item in events]
            event_checks[label] = {
                "versions": versions,
                "unique_and_contiguous": versions == list(range(len(versions))),
                "final_status": repository.get_run(run_id)["status"],
            }
        rows.append(_fault_row(
            "PF-F06", "复合故障后的状态审计", "所有任务状态版本连续且终态符合各故障路径",
            all(item["unique_and_contiguous"] for item in event_checks.values())
            and {key: value["final_status"] for key, value in event_checks.items()}
            == {"crash": "cancelled", "cancel": "cancelled", "retry_limit": "failed", "rollback": "failed"},
            event_checks,
        ))
        return rows
    finally:
        if trigger_created:
            try:
                with transaction(connection):
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "DROP TRIGGER IF EXISTS platform_stress_injected_failure ON energy_recovery.simulation_timetable_audit_summary"
                        )
                        cursor.execute(
                            "DROP FUNCTION IF EXISTS energy_recovery.platform_stress_injected_failure()"
                        )
            except Exception:
                connection.rollback()
        connection.close()


def _write_outputs(
    output_dir: Path,
    summary: dict[str, Any],
    samples: list[dict[str, Any]],
    fault_rows: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> None:
    """写出报告、操作样本、故障矩阵和失败证据。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "platform_task_operation_samples.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(samples[0]))
        writer.writeheader()
        writer.writerows(samples)
    with (output_dir / "platform_task_fault_cases.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fault_rows[0]))
        writer.writeheader()
        writer.writerows(fault_rows)
    (output_dir / "platform_task_stress_fault_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "platform_task_stress_fault_failures.json").write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "failures": failures}, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    pressure = summary["pressure"]
    lines = [
        "# 平台任务压力与故障测试",
        "",
        f"结论：`{'PASS' if summary['passed'] else 'FAIL'}`。真实PostgreSQL测试库：`{summary['database']['name']}`，版本 {summary['database']['major_version']}。",
        "",
        "## 压力结果",
        "",
        f"- 并发创建：{pressure['configuration']['task_count']}项，{pressure['create_throughput_per_s']}项/秒。",
        f"- 并发领取：{pressure['claim_throughput_per_s']}项/秒，参与领取worker数 {pressure['claimed_worker_count']}。",
        f"- 幂等突发：{pressure['configuration']['idempotency_burst']}次同键请求归并为一个任务；异内容同键请求全部拒绝。",
        f"- 操作错误：{pressure['error_count']}；最终压力任务均为cancelled且无活动租约。",
        "",
        "| 操作 | 数量 | 中位/ms | P95/ms | P99/ms | 最大/ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for operation, item in pressure["latencies"].items():
        lines.append(
            f"| `{operation}` | {item['count']} | {item['median_ms']} | {item['p95_ms']} | {item['p99_ms']} | {item['max_ms']} |"
        )
    lines.extend([
        "",
        "## 故障注入矩阵",
        "",
        "| 编号 | 注入 | 预期行为 | 结果 |",
        "| --- | --- | --- | --- |",
    ])
    for row in fault_rows:
        lines.append(
            f"| `{row['case_id']}` | {row['injection']} | {row['expected_behavior']} | {'PASS' if row['passed'] else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## 解释边界",
        "",
        "- 本测试对真实PostgreSQL事务和多连接任务队列施压，但不执行耗时算法本体，因此不等于算法计算吞吐量。",
        "- 本机结果不是目标平台SLA；目标环境必须使用相同工具按实际并发量重跑。",
        "- 测试库名称必须以`_test`结尾，测试项目在结束后删除；报告不保存数据库连接串。",
    ])
    (output_dir / "PLATFORM_TASK_STRESS_FAULT_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def run_stress_fault_test(
    database_url: str,
    *,
    output_dir: Path,
    task_count: int = 120,
    worker_count: int = 12,
    idempotency_burst: int = 32,
    max_operation_p95_ms: float = 2000.0,
    min_claim_throughput_per_s: float = 10.0,
) -> dict[str, Any]:
    """执行完整压力和故障测试，并在结束时清理测试项目。"""

    for name, value in (
        ("task_count", task_count),
        ("worker_count", worker_count),
        ("idempotency_burst", idempotency_burst),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name}必须是正整数")
    if worker_count > task_count:
        raise ValueError("worker_count不能大于task_count")
    if max_operation_p95_ms <= 0 or min_claim_throughput_per_s <= 0:
        raise ValueError("性能阈值必须大于0")

    connection, database_name, server_version_num = _connect_test_database(database_url)
    project_id: UUID | None = None
    context: StressContext | None = None
    failures: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    fault_rows: list[dict[str, Any]] = []
    try:
        apply_migrations(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) FROM energy_recovery.simulation_run
                WHERE status IN ('pending', 'validating', 'running')
                """
            )
            active_before = int(cursor.fetchone()[0])
        if active_before:
            raise RuntimeError(
                f"测试库存在{active_before}个非终态任务，拒绝压力测试以免领取其他任务。"
            )

        repository = SimulationRepository(connection)
        token = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:8]
        imported = repository.import_dataset(
            ROOT / "data" / "real_shuohuang",
            project_code=f"platform-stress-{token}",
            project_name="平台任务压力与故障测试",
            route_name="测试线路",
            version_code="v1",
            data_status="planning_placeholder",
            source_note="自动压力测试，结束后删除数据库记录",
            extra_files={
                "platform/running_diagram.xlsx": ROOT / "data_templates" / "running_diagram_template.xlsx"
            },
        )
        project_id = UUID(str(imported["project_id"]))
        version_id = UUID(str(imported["version_id"]))
        context = StressContext(
            project_id=project_id,
            version_id=version_id,
            token=token,
            records=repository.load_version_files(version_id),
        )
        connection.close()

        pressure, samples, pressure_errors = _run_pressure_phase(
            database_url, context,
            task_count=task_count,
            worker_count=worker_count,
            idempotency_burst=idempotency_burst,
            max_operation_p95_ms=max_operation_p95_ms,
            min_claim_throughput_per_s=min_claim_throughput_per_s,
        )
        failures.extend(pressure_errors)
        fault_rows = _run_fault_phase(
            database_url, context, result_dir=ROOT / "outputs" / "timetable_energy_audit"
        )
        failures.extend(
            {"phase": "fault", "case_id": row["case_id"], "evidence_json": row["evidence_json"]}
            for row in fault_rows if not row["passed"]
        )
        summary = {
            "schema_version": SCHEMA_VERSION,
            "passed": pressure["passed"] and all(row["passed"] for row in fault_rows) and not failures,
            "database": {
                "name": database_name,
                "server_version_num": server_version_num,
                "major_version": server_version_num // 10000,
                "scope": "dedicated_test_database",
            },
            "pressure": pressure,
            "fault_injection": {
                "case_count": len(fault_rows),
                "passed_count": sum(bool(row["passed"]) for row in fault_rows),
                "failed_count": sum(not bool(row["passed"]) for row in fault_rows),
            },
            "cleanup": {"project_deleted": False},
            "limitations": [
                "不执行算法本体，测得的是平台任务状态机和数据库队列吞吐。",
                "本机测试结果不构成目标平台生产SLA。",
                "TLS、网络中断、数据库主备切换和备份恢复需在部署环境测试。",
            ],
            "outputs": {
                "report": "PLATFORM_TASK_STRESS_FAULT_REPORT.md",
                "summary": "platform_task_stress_fault_summary.json",
                "operation_samples": "platform_task_operation_samples.csv",
                "fault_cases": "platform_task_fault_cases.csv",
                "failures": "platform_task_stress_fault_failures.json",
            },
        }
    finally:
        if project_id is not None:
            cleanup_connection, _name, _version = _connect_test_database(database_url)
            try:
                with transaction(cleanup_connection):
                    with cleanup_connection.cursor() as cursor:
                        cursor.execute(
                            "DELETE FROM energy_recovery.simulation_run WHERE project_id = %s",
                            (project_id,),
                        )
                        cursor.execute(
                            "DELETE FROM energy_recovery.simulation_project_version WHERE project_id = %s",
                            (project_id,),
                        )
                        cursor.execute(
                            "DELETE FROM energy_recovery.simulation_project WHERE project_id = %s",
                            (project_id,),
                        )
                        cleanup_ok = cursor.rowcount == 1
            finally:
                cleanup_connection.close()
            if "summary" in locals():
                summary["cleanup"]["project_deleted"] = cleanup_ok
                if not cleanup_ok:
                    summary["passed"] = False
                    failures.append({"phase": "cleanup", "error": "测试项目未删除"})
        elif not connection.closed:
            connection.close()

    _write_outputs(Path(output_dir), summary, samples, fault_rows, failures)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("SIMULATION_TEST_DATABASE_URL"),
        help="专用测试数据库连接串，也可使用SIMULATION_TEST_DATABASE_URL。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs") / "platform_task_stress_fault_current",
    )
    parser.add_argument("--task-count", type=int, default=120)
    parser.add_argument("--worker-count", type=int, default=12)
    parser.add_argument("--idempotency-burst", type=int, default=32)
    parser.add_argument("--max-operation-p95-ms", type=float, default=2000.0)
    parser.add_argument("--min-claim-throughput-per-s", type=float, default=10.0)
    args = parser.parse_args(argv)
    if not args.database_url:
        raise RuntimeError("必须通过--database-url或SIMULATION_TEST_DATABASE_URL提供测试库连接串。")
    summary = run_stress_fault_test(
        args.database_url,
        output_dir=args.output_dir,
        task_count=args.task_count,
        worker_count=args.worker_count,
        idempotency_burst=args.idempotency_burst,
        max_operation_p95_ms=args.max_operation_p95_ms,
        min_claim_throughput_per_s=args.min_claim_throughput_per_s,
    )
    print(json.dumps({
        "passed": summary["passed"],
        "task_count": summary["pressure"]["configuration"]["task_count"],
        "claim_throughput_per_s": summary["pressure"]["claim_throughput_per_s"],
        "fault_cases": summary["fault_injection"],
        "report": str(args.output_dir / "PLATFORM_TASK_STRESS_FAULT_REPORT.md"),
    }, ensure_ascii=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
