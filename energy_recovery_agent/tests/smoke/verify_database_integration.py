# 模块功能说明：验证数据库DDL、输入快照、关系投影、结果投影和任务命令边界。

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import csv
import json
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.dataset_projection import project_dataset
from database.cli import build_parser as build_database_cli_parser
from database.result_projection import project_result_directory
from database.snapshots import collect_file_records, materialize_file_records, snapshot_manifest
from database.worker import (
    SolveBudgetExceededError,
    _subprocess_runner,
    _decode_subprocess_output,
    bind_database_storage_parameters,
    build_algorithm_command,
    execute_claimed_run,
    validate_run_parameters,
)
from database.solver_budget import (
    apply_parameter_overrides,
    budget_policy_summary,
    build_solve_attempts,
)
from database.postgres import SimulationRepository, run_request_sha256, transaction


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def verify_migrations() -> None:
    """确认映射中的物理表均由迁移创建，且不存在其他业务表前缀。"""

    migration_paths = sorted((ROOT / "database" / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
    assert [path.name[:3] for path in migration_paths] == [
        "001", "002", "003", "004", "005", "006", "007", "008", "009"
    ]
    sql = "\n".join(path.read_text(encoding="utf-8") for path in migration_paths)
    mapping = json.loads((ROOT / "database" / "io_mapping.json").read_text(encoding="utf-8"))
    database_contract = json.loads(
        (ROOT / "database" / "database_contract.json").read_text(encoding="utf-8")
    )
    platform_contract = json.loads(
        (ROOT / "database" / "platform_api_contract.json").read_text(encoding="utf-8")
    )
    assert mapping["database"] == "carbon_emissions"
    assert mapping["table_prefix"] == "simulation_"
    assert mapping["mapping_version"] == "1.14"
    assert mapping["run_lifecycle"]["state_event_table"] == "simulation_run_state_event"
    assert database_contract["contract_version"] == "1.10"
    assert platform_contract["contract_version"] == "1.14"
    replay_contract = platform_contract["operations"]["create_run"]["historical_disturbance_replay"]
    assert replay_contract["schema_version"] == "1.3"
    assert "directional_speed_restriction" in replay_contract
    attribution_outputs = {
        item["path"] for item in mapping["output_files"]
        if str(item.get("artifact_type", "")).startswith("optimization_attribution")
        or item.get("artifact_type") in {
            "optimization_kpi_attribution",
            "optimization_candidate_decision",
            "optimization_candidate_funnel",
            "optimization_bottleneck",
            "optimization_dimension_attribution",
        }
    }
    assert attribution_outputs == {
        "OPTIMIZATION_ATTRIBUTION_REPORT.md",
        "optimization_attribution_summary.json",
        "optimization_kpi_attribution.csv",
        "optimization_candidate_decisions.csv",
        "optimization_candidate_funnel.csv",
        "optimization_bottlenecks.csv",
        "optimization_dimension_attribution.csv",
    }
    assert "storage_devices" in mapping["run_parameters"]["rolling_rescheduling"]["optional"]
    assert "disturbance_history_relative_path" in (
        mapping["run_parameters"]["rolling_rescheduling"]["optional"]
    )
    replay_input = next(
        item for item in mapping["input_files"]
        if "historical_disturbance_replay" in item["path"]
    )
    assert replay_input["target"] == "simulation_dataset_file"
    replay_outputs = {
        item["path"] for item in mapping["output_files"]
        if item.get("artifact_type", "").startswith("replay_")
    }
    assert replay_outputs == {
        "disturbance_replay_manifest.json", "disturbance_replay_cycles.csv"
    }
    for section in ("input_files", "output_files"):
        for item in mapping[section]:
            targets = item.get("targets") or [item.get("target")]
            for target in targets:
                if target in (None, "simulation_dataset_file"):
                    continue
                assert f"energy_recovery.{target}" in sql, target
    for line in sql.splitlines():
        normalized = line.strip().lower()
        if normalized.startswith("create table"):
            table_name = normalized.split("energy_recovery.", 1)[1].split()[0]
            assert table_name.startswith("simulation_")
    assert "drop table" not in sql.lower()


def verify_snapshot_roundtrip() -> None:
    """证明数据库字节快照还原后与当前算法输入逐文件一致。"""

    source = ROOT / "data" / "real_shuohuang"
    records = collect_file_records(source)
    original_manifest = snapshot_manifest(records)
    with TemporaryDirectory(prefix="database_snapshot_smoke_") as temp_name:
        restored = Path(temp_name)
        restored_manifest = materialize_file_records(records, restored)
        replay_records = collect_file_records(restored)
    assert original_manifest == restored_manifest == snapshot_manifest(replay_records)
    assert original_manifest["file_count"] >= 20

    assert bind_database_storage_parameters(records, ()) == records
    # 已发布旧版本可能有从柔性供电区间误投影的设备行，回放时不得再次绑定。
    with (source / "energy_transfer_zones.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        obsolete_rows = tuple({"storage_section_id": row["zone_id"]} for row in csv.DictReader(handle))
    assert obsolete_rows and bind_database_storage_parameters(records, obsolete_rows) == records


def verify_dataset_projection() -> None:
    """确认平台常用基础数据已生成结构化关系投影。"""

    source = ROOT / "data" / "real_shuohuang"
    projected = project_dataset(uuid4(), source)
    assert len(projected["stations"]) >= 30
    assert len(projected["segments"]) >= 1000
    assert {item["train_type"] for item in projected["train_types"]} == {"heavy", "empty"}
    assert projected["storage_devices"] == []
    assert projected["power_arms"]
    assert all(item["data_status"] in {
        "official", "derived_from_official", "planning_placeholder", "synthetic"
    } for key in ("train_types", "storage_devices", "power_arms") for item in projected[key])
    assert projected["signaling_blocks"] == []


def verify_result_projection() -> None:
    """用最小结果目录验证候选、KPI、时间片、冲突和场景投影。"""

    with TemporaryDirectory(prefix="database_result_smoke_") as temp_name:
        root = Path(temp_name)
        summary = {
            "valid": True,
            "baseline": {"total_gen_kwh": 100, "wasted_kwh": 40, "grid_kwh": 80},
            "optimized": {"heavy_count": 1, "empty_count": 1, "time_space_arc_count": 2},
            "optimizer_diagnostics": {"returned_candidate_core_robust_feasible": True},
            "optimization_attribution": {"decision": {
                "action": "keep_baseline",
                "reason": "storage_preset_changed_requires_fixed_storage_recheck",
                "selected_candidate_id": "C001",
            }},
        }
        (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        _write_csv(root / "kpi_summary.csv", [{
            "case": "optimized", "feasible": "True", "total_gen_kwh": "100",
            "total_con_kwh": "70", "accepted_by_power_arm_kwh": "50",
            "recovered_energy_kwh": "45", "recovery_rate": "0.45",
            "direct_used_kwh": "0", "battery_charge_kwh": "50",
            "battery_discharge_kwh": "30", "wasted_kwh": "50", "grid_kwh": "40",
            "effective_regen_loss_kwh": "55", "final_soc_kwh": "10",
            "constraint_violation": "0", "resource_conflict_count": "0", "total_cost": "35",
        }])
        _write_csv(root / "ranked_candidates.csv", [{
            "candidate_id": "C001", "candidate_set": "pareto", "rank": "1",
            "feasible": "True", "constraint_violation": "0", "resource_conflict_count": "0",
            "heavy_departure_adjustments_s": "[0]", "empty_departure_adjustments_s": "[30]",
        }])
        _write_csv(root / "energy_timeline.csv", [
            {"case": "baseline", "time_s": "0", "direct_used_kW": "0", "battery_charge_kW": "360", "battery_discharge_kW": "0", "wasted_kW": "0", "grid_kW": "0", "soc_kwh": "1"},
            {"case": "baseline", "time_s": "10", "direct_used_kW": "0", "battery_charge_kW": "360", "battery_discharge_kW": "0", "wasted_kW": "0", "grid_kW": "0", "soc_kwh": "2"},
            {"case": "optimized", "time_s": "0", "direct_used_kW": "0", "battery_charge_kW": "0", "battery_discharge_kW": "360", "wasted_kW": "0", "grid_kW": "0", "soc_kwh": "1"},
        ])
        conflict_row = {
            "case": "baseline", "conflict_type": "throat_route_conflict", "severity": "blocking",
            "resource_id": "throat:1", "resource_name": "测试咽喉", "train_a": "H001", "train_b": "E001",
            "overlap_start_s": "10", "overlap_end_s": "20", "overlap_duration_s": "10",
            "message": "冲突", "suggestion": "错峰",
        }
        _write_csv(root / "resource_conflicts.csv", [
            {**conflict_row, "location_km": location}
            for location in ("1.0", "343.0 km", "343.0-345.0 km", "unknown", "NaN")
        ])
        _write_csv(root / "selected_plan_scenario_diagnostics.csv", [{
            "scenario": "normal", "core_for_feasibility": "True", "feasible": "True",
            "blocking": "False", "constraint_violation": "0", "resource_conflict_count": "0",
            "total_cost": "35", "grid_kwh": "40", "wasted_kwh": "50",
            "battery_charge_kwh": "50", "battery_discharge_kwh": "30",
            "final_soc_deviation_kwh": "10", "conflict_summary": "",
        }])
        projected = project_result_directory(uuid4(), root, settlement_step_s=10)
    assert len(projected["candidates"]) == 1
    assert len(projected["candidate_adjustments"]) == 2
    assert projected["candidate_adjustments"][1]["adjustment_s"] == 30
    assert len(projected["kpis"]) == 1
    assert len(projected["energy_slices"]) == 3
    assert all(item["slice_end_s"] > item["slice_start_s"] for item in projected["energy_slices"])
    assert abs(projected["energy_slices"][0]["battery_charge_kwh"] - 1.0) < 1e-9
    assert abs(projected["energy_slices"][0]["regen_kwh"] - 1.0) < 1e-9
    assert abs(projected["energy_slices"][0]["accepted_by_power_arm_kwh"] - 1.0) < 1e-9
    assert abs(projected["energy_slices"][2]["traction_kwh"] - 1.0) < 1e-9
    assert projected["energy_slices"][0]["constraint_violation_kwh"] == 0.0
    conflicts = projected["resource_conflicts"]
    assert [row["location_km"] for row in conflicts] == [1.0, 343.0, None, None, None]
    assert "343.0-345.0 km" in conflicts[2]["message"]
    assert len(projected["scenario_results"]) == 1
    assert projected["decision"]["action"] == "keep_baseline"
    assert projected["decision"]["reason"] == "storage_preset_changed_requires_fixed_storage_recheck"

    with TemporaryDirectory(prefix="database_rolling_result_smoke_") as temp_name:
        root = Path(temp_name)
        (root / "benchmark_summary.json").write_text(
            json.dumps({"schema_version": "1.5", "cycle_count": 1}),
            encoding="utf-8",
        )
        fingerprint = "a" * 64
        transition = {
            "state": "waiting_for_observation",
            "action": "hold_new_departures_and_reoptimize_on_new_observation",
            "request_fingerprint": fingerprint,
            "attempts": [{"attempt_index": 0}],
        }
        _write_csv(root / "rolling_cycles.csv", [{
            "cycle_index": "0",
            "current_time_s": "0",
            "commit_status": "withheld_infeasible",
            "safety_state": "waiting_for_observation",
            "safety_action": "hold_new_departures_and_reoptimize_on_new_observation",
            "core_robust_feasible": "False",
            "operational_intervention_required": "True",
            "safety_attempt_count": "1",
            "safety_transition": json.dumps(transition),
        }])
        rolling = project_result_directory(uuid4(), root)
    assert len(rolling["rolling_control_events"]) == 1
    assert rolling["rolling_control_events"][0]["request_fingerprint"] == fingerprint
    assert rolling["decision"]["action"] == "no_feasible_solution"
    assert rolling["decision"]["safety_action"].startswith("hold_new_departures")


def verify_storage_device_parameter_query() -> None:
    """确认仓储按版本读取全部算法静态字段并转为稳定快照结构。"""

    version_id = uuid4()

    class FakeCursor:
        def __init__(self):
            self.sql = ""
            self.parameters = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, parameters):
            self.sql = sql
            self.parameters = parameters

        def fetchall(self):
            return [(
                "S1", 150, 36, 18, 0.8, 0.9, 40, 20, 120,
                True, "official", "正式设备参数",
            )]

    cursor = FakeCursor()

    class FakeConnection:
        def cursor(self):
            return cursor

    rows = SimulationRepository(FakeConnection()).load_storage_device_parameters(version_id)
    assert cursor.parameters == (version_id,)
    assert "FROM energy_recovery.simulation_storage_device" in cursor.sql
    assert "ORDER BY storage_code" in cursor.sql
    assert rows == ({
        "storage_section_id": "S1",
        "capacity_kwh": 150.0,
        "max_charge_power_kw": 36.0,
        "max_discharge_power_kw": 18.0,
        "charge_efficiency": 0.8,
        "discharge_efficiency": 0.9,
        "initial_soc_kwh": 40.0,
        "min_soc_kwh": 20.0,
        "max_soc_kwh": 120.0,
        "available": True,
        "data_status": "official",
        "source_note": "正式设备参数",
    },)


def verify_current_output_formats() -> None:
    """存在工作区历史输出时，确认其命名仍受数据库结构化投影覆盖。"""

    audit_path = ROOT / "outputs" / "timetable_energy_audit"
    if (audit_path / "audit_summary.json").is_file():
        audit = project_result_directory(uuid4(), audit_path)
        assert audit["summary"]["train_count"] == 2
        assert len(audit["running_arcs"]) == audit["summary"]["running_arc_count"]
        assert len(audit["energy_slices"]) == audit["summary"]["time_slice_count"]
        assert len(audit["power_arm_settlements"]) == audit["summary"]["settlement_window_count"]
        assert len(audit["audit_issues"]) == audit["summary"]["issue_count"]
        assert len(audit["optimization_suggestions"]) == audit["summary"]["suggestion_count"]
        assert audit["decision"]["action"] == "keep_baseline"

    optimizer_path = ROOT / "outputs" / "timetable_optimizer_nsga2"
    if (optimizer_path / "optimizer_summary.json").is_file():
        optimizer = project_result_directory(uuid4(), optimizer_path)
        assert len(optimizer["candidates"]) == optimizer["summary"]["candidate_count"]
        assert len(optimizer["scenario_results"]) == optimizer["summary"]["scenario_score_count"]
        assert sum(item["pareto"] for item in optimizer["candidates"]) == optimizer["summary"]["pareto_count"]
        assert optimizer["decision"]["action"] == "keep_baseline"

    rolling_path = ROOT / "paper" / "experiments" / "E15_synthetic_rolling_rescheduling"
    if (rolling_path / "benchmark_summary.json").is_file():
        rolling = project_result_directory(uuid4(), rolling_path)
        assert len(rolling["rolling_control_events"]) == rolling["summary"]["cycle_count"]
        assert all(
            len(item["request_fingerprint"]) == 64
            for item in rolling["rolling_control_events"]
        )
    device_state_path = (
        ROOT / "paper" / "experiments" / "E15_storage_device_runtime_state"
    )
    if (device_state_path / "benchmark_summary.json").is_file():
        rolling = project_result_directory(uuid4(), device_state_path)
        assert rolling["rolling_control_events"]
        storage_runtime = rolling["rolling_control_events"][1]["event"]["storage_runtime"]
        assert len(storage_runtime["storage_device_states"]) == 2
        assert len(storage_runtime["storage_parameters_by_id"]) == 2
        assert set(storage_runtime["initial_soc_by_storage_kwh"]) == {
            "storage_section_1:K145-K164",
            "storage_section_2:K164-K200.7",
        }
    outage_path = ROOT / "paper" / "experiments" / "E15_storage_device_outage"
    if (outage_path / "benchmark_summary.json").is_file():
        rolling = project_result_directory(uuid4(), outage_path)
        storage_id = "storage_section_2:K164-K200.7"
        for event in rolling["rolling_control_events"]:
            storage_runtime = event["event"]["storage_runtime"]
            assert storage_runtime["executed_charge_by_storage_kwh"][storage_id] == 0.0
            assert storage_runtime["executed_discharge_by_storage_kwh"][storage_id] == 0.0
            assert storage_runtime["executed_final_soc_by_storage_kwh"][storage_id] == 2500.0


def verify_transaction_rollback() -> None:
    """确认仓储事务包装器在异常时回滚、成功时提交。"""

    class FakeConnection:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1


    connection = FakeConnection()
    with transaction(connection):
        pass
    assert (connection.commits, connection.rollbacks) == (1, 0)
    try:
        with transaction(connection):
            raise RuntimeError("模拟写入失败")
    except RuntimeError:
        pass
    else:
        raise AssertionError("事务异常必须向调用方传播。")
    assert (connection.commits, connection.rollbacks) == (1, 1)


def verify_concurrency_guards() -> None:
    """静态确认任务领取与结果写入均持有数据库行锁。"""

    source = (ROOT / "database" / "postgres.py").read_text(encoding="utf-8")
    assert "FOR UPDATE OF r SKIP LOCKED" in source
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "lease_expires_at > now()" in source
    assert "AND worker_id = %s AND lease_token = %s" in source
    assert "成功任务不能被不同结果覆盖" in source
    migration = (ROOT / "database" / "migrations" / "006_run_transaction_idempotency.sql").read_text(encoding="utf-8")
    assert "uq_simulation_run_idempotency_key" in migration
    assert "simulation_run_state_event" in migration
    assert "uq_simulation_run_event_version" in migration
    assert "simulation_run_transition_guard" in migration
    assert "state_version must increase by exactly one" in migration
    assert "ALTER COLUMN idempotency_key SET NOT NULL" in migration


def verify_request_idempotency_digest() -> None:
    """任务请求摘要必须稳定，并能识别同一幂等键下的内容变化。"""

    project_id = uuid4()
    version_id = uuid4()
    first = run_request_sha256(
        project_id, version_id, "dispatch", {"seed": 11, "heavy_count": 2},
        "platform", "working-tree",
    )
    reordered = run_request_sha256(
        project_id, version_id, "dispatch", {"heavy_count": 2, "seed": 11},
        "platform", "working-tree",
    )
    changed = run_request_sha256(
        project_id, version_id, "dispatch", {"heavy_count": 3, "seed": 11},
        "platform", "working-tree",
    )
    assert first == reordered
    assert len(first) == 64
    assert first != changed
    rolling_parameters = {
        "storage_devices": [
            {"storage_section_id": "S2", "soc_kwh": 20, "available": False},
            {"storage_section_id": "S1", "soc_kwh": 10, "available": True},
        ]
    }
    rolling_reordered = {
        "storage_devices": list(reversed(rolling_parameters["storage_devices"]))
    }
    rolling_first = run_request_sha256(
        project_id, version_id, "rolling_rescheduling", rolling_parameters,
        "platform", "working-tree",
    )
    rolling_second = run_request_sha256(
        project_id, version_id, "rolling_rescheduling", rolling_reordered,
        "platform", "working-tree",
    )
    rolling_changed = run_request_sha256(
        project_id,
        version_id,
        "rolling_rescheduling",
        {
            "storage_devices": [
                {"storage_section_id": "S1", "soc_kwh": 10, "available": False},
                {"storage_section_id": "S2", "soc_kwh": 20, "available": False},
            ]
        },
        "platform",
        "working-tree",
    )
    assert rolling_first == rolling_second
    assert rolling_first != rolling_changed


def verify_worker_adapter() -> None:
    """验证工作进程从数据库快照执行并回写结果，异常时标记失败。"""

    class Completed:
        returncode = 0
        stdout = "算法执行完成"
        stderr = ""

    class FakeRepository:
        def __init__(self):
            self.records = collect_file_records(ROOT / "data" / "real_shuohuang")
            self.storage_devices = project_dataset(
                version_id, ROOT / "data" / "real_shuohuang"
            )["storage_devices"]
            self.frozen = None
            self.persisted = None
            self.failed = None
            self.heartbeats = 0

        def load_version_files(self, version_id):
            return self.records

        def load_storage_device_parameters(self, loaded_version_id):
            return tuple({
                key: row[key]
                for key in (
                    "storage_code", "capacity_kwh", "max_charge_power_kw",
                    "max_discharge_power_kw", "charge_efficiency",
                    "discharge_efficiency", "initial_soc_kwh", "min_soc_kwh",
                    "max_soc_kwh", "available", "data_status", "source_note",
                )
            } | {"storage_section_id": row["storage_code"]} for row in self.storage_devices)

        def freeze_run_snapshot(self, run_id, version_id, manifest, **ownership):
            assert ownership["worker_id"] == "test-worker"
            assert ownership["lease_token"] == lease_token
            self.frozen = manifest

        def heartbeat_run(self, run_id, worker_id, token, lease_seconds=300):
            assert worker_id == "test-worker"
            assert token == lease_token
            self.heartbeats += 1

        def persist_result(self, run_id, output_dir, settlement_step_s=10, **ownership):
            assert ownership["worker_id"] == "test-worker"
            assert ownership["lease_token"] == lease_token
            self.persisted = project_result_directory(run_id, output_dir, settlement_step_s)
            return {"already_present": False}

        def mark_failed(self, run_id, message, **ownership):
            assert ownership["worker_id"] == "test-worker"
            assert ownership["lease_token"] == lease_token
            self.failed = message

    def successful_runner(command, cwd):
        data_dir = Path(command[command.index("--data-dir") + 1])
        assert not (data_dir / "storage_devices.json").exists()
        assert (data_dir / "battery.json").is_file()
        output_dir = Path(command[command.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "summary.json").write_text(
            json.dumps({"valid": True, "optimization_decision": {
                "action": "keep_baseline", "reason": "baseline_already_satisfactory"
            }}),
            encoding="utf-8",
        )
        return Completed()

    run_id = uuid4()
    version_id = uuid4()
    lease_token = uuid4()
    repository = FakeRepository()
    result = execute_claimed_run(repository, {
        "run_id": run_id,
        "version_id": version_id,
        "run_type": "dispatch",
        "parameters": {"heavy_count": 2, "empty_count": 2},
        "worker_id": "test-worker",
        "lease_token": lease_token,
    }, runner=successful_runner)
    assert result["status"] == "succeeded"
    assert repository.frozen["snapshot_sha256"]
    assert repository.persisted["decision"]["action"] == "keep_baseline"
    assert repository.failed is None
    assert repository.heartbeats == 3

    failed_repository = FakeRepository()

    def failed_runner(command, cwd):
        raise RuntimeError("模拟算法异常")

    try:
        execute_claimed_run(failed_repository, {
            "run_id": uuid4(), "version_id": uuid4(), "run_type": "dispatch",
            "parameters": {}, "worker_id": "test-worker", "lease_token": lease_token,
        }, runner=failed_runner)
    except RuntimeError:
        pass
    else:
        raise AssertionError("工作进程必须向调度层传播算法异常。")
    assert "模拟算法异常" in failed_repository.failed

    fallback_repository = FakeRepository()
    fallback_calls: list[list[str]] = []

    def timeout_then_succeed(command, cwd):
        fallback_calls.append(list(command))
        if len(fallback_calls) == 1:
            raise SolveBudgetExceededError(900)
        output_dir = Path(command[command.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "summary.json").write_text(
            json.dumps({"valid": True, "optimization_decision": {
                "action": "keep_baseline", "reason": "budget_fallback"
            }}),
            encoding="utf-8",
        )
        return Completed()

    fallback_result = execute_claimed_run(fallback_repository, {
        "run_id": uuid4(), "version_id": uuid4(), "run_type": "dispatch",
        "parameters": {"population_size": 12, "generations": 4},
        "worker_id": "test-worker", "lease_token": lease_token,
    }, runner=timeout_then_succeed)
    assert fallback_result["status"] == "succeeded"
    assert len(fallback_calls) == 2
    fallback_command = fallback_calls[1]
    assert fallback_command[fallback_command.index("--population-size") + 1] == "4"
    assert fallback_command[fallback_command.index("--generations") + 1] == "1"
    report_record = next(
        item for item in fallback_repository.persisted["artifacts"]
        if item.relative_path == "solver_resource_report.json"
    )
    report = json.loads(report_record.content.decode("utf-8"))
    assert report["final_status"] == "succeeded_degraded"
    assert report["timeout_is_infeasibility"] is False
    assert [item["status"] for item in report["attempts"]] == ["timeout", "succeeded"]


def verify_worker_heartbeat_abort() -> None:
    """续租失败必须终止仍在运行的算法子进程。"""

    heartbeat_calls = []

    def rejected_heartbeat():
        heartbeat_calls.append(time.monotonic())
        raise RuntimeError("模拟租约失效")

    started = time.monotonic()
    try:
        _subprocess_runner(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            ROOT,
            heartbeat=rejected_heartbeat,
            heartbeat_interval_s=1,
        )
    except RuntimeError as exc:
        assert "租约失效" in str(exc)
    else:
        raise AssertionError("心跳失败后子进程仍继续运行。")
    assert len(heartbeat_calls) == 1
    assert time.monotonic() - started < 6


def verify_worker_output_decoding() -> None:
    """Windows本地编码输出不能使任务读取线程崩溃。"""

    chinese = "运行图优化完成"
    assert _decode_subprocess_output(chinese.encode("utf-8")) == chinese
    assert _decode_subprocess_output(chinese.encode("gb18030")) == chinese
    completed = _subprocess_runner(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write('运行完成'.encode('gb18030'))"],
        ROOT,
        heartbeat_interval_s=2,
    )
    assert completed.returncode == 0
    assert completed.stdout == "运行完成"


def verify_solver_resource_budget() -> None:
    """验证预算档位、语义保护和子进程总墙钟超时。"""

    summary = budget_policy_summary()
    assert summary["default_profile"] == "standard"
    assert summary["semantic_guards"]["timeout_is_not_infeasible"] is True
    assert len(build_solve_attempts("timetable_audit", {}, "fine")) == 1
    assert len(build_solve_attempts("joint_parameter_robustness", {}, "fine")) == 1
    dispatch_attempts = build_solve_attempts(
        "dispatch", {"population_size": 12, "generations": 4}, "standard"
    )
    assert len(dispatch_attempts) == 2
    degraded = apply_parameter_overrides(
        {"population_size": 3, "generations": 2},
        dispatch_attempts[1].parameter_overrides,
    )
    assert degraded["population_size"] == 3
    assert degraded["generations"] == 1
    started = time.monotonic()
    try:
        _subprocess_runner(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            ROOT,
            heartbeat_interval_s=5,
            timeout_s=1,
        )
    except SolveBudgetExceededError as exc:
        assert exc.timeout_s == 1
    else:
        raise AssertionError("算法子进程超过墙钟预算后没有终止。")
    assert time.monotonic() - started < 6


def verify_command_boundary() -> None:
    """确认平台参数只能映射到已批准命令行字段。"""

    with TemporaryDirectory(prefix="database_command_smoke_") as temp_name:
        root = Path(temp_name)
        output = root / "out"
        parsed = build_database_cli_parser().parse_args([
            "create-run",
            "--project-code", "P",
            "--version-code", "V",
            "--run-type", "joint_parameter_robustness",
            "--parameters-json", '{"parameter_ranges_relative_path":"platform/joint.json"}',
            "--idempotency-key", "K",
        ])
        assert parsed.run_type == "joint_parameter_robustness"
        command = build_algorithm_command(
            "dispatch", {"heavy_count": 2, "empty_count": 2, "seed": 11},
            data_dir=root, output_dir=output,
        )
        assert "dispatch-case" in command
        assert command[command.index("--heavy-count") + 1] == "2"
        rolling_command = build_algorithm_command(
            "rolling_rescheduling",
            {
                "max_safety_retries": 0,
                "manual_after_withheld": 2,
                "disable_safety_retry": True,
                "storage_devices": [
                    {
                        "storage_section_id": "S1",
                        "soc_kwh": 20,
                        "available": False,
                        "max_charge_power_kw": 0,
                        "max_discharge_power_kw": 0,
                    }
                ],
            },
            data_dir=root,
            output_dir=output,
        )
        assert "benchmark-rolling-rescheduling" in rolling_command
        assert "--disable-safety-retry" in rolling_command
        assert rolling_command[rolling_command.index("--max-safety-retries") + 1] == "0"
        storage_payload = json.loads(
            rolling_command[rolling_command.index("--storage-devices-json") + 1]
        )
        assert storage_payload[0]["storage_section_id"] == "S1"
        joint_contract = root / "platform" / "joint.json"
        joint_contract.parent.mkdir(parents=True)
        joint_contract.write_text("{}", encoding="utf-8")
        joint_command = build_algorithm_command(
            "joint_parameter_robustness",
            {
                "parameter_ranges_relative_path": "platform/joint.json",
                "heavy_count": 2,
                "baseline_phase_s": 840,
            },
            data_dir=root,
            output_dir=output,
        )
        assert "benchmark-joint-parameter-robustness" in joint_command
        assert Path(joint_command[joint_command.index("--parameter-ranges") + 1]).resolve() == joint_contract.resolve()
        assert joint_command[joint_command.index("--phase-s") + 1] == "840"
        for invalid_storage in (
            [],
            [{"storage_section_id": "", "soc_kwh": 0}],
            [{"storage_section_id": "S1", "soc_kwh": -1}],
            [{"storage_section_id": "S1", "soc_kwh": 0, "unexpected": 1}],
            [
                {"storage_section_id": "S1", "soc_kwh": 0},
                {"storage_section_id": "S1", "soc_kwh": 1},
            ],
        ):
            try:
                validate_run_parameters(
                    "rolling_rescheduling", {"storage_devices": invalid_storage}
                )
            except ValueError:
                pass
            else:
                raise AssertionError(f"无效设备状态必须被拒绝：{invalid_storage}")
        try:
            build_algorithm_command(
                "dispatch", {"arbitrary_shell_argument": "bad"},
                data_dir=root, output_dir=output,
            )
        except ValueError as exc:
            assert "未批准参数" in str(exc)
        else:
            raise AssertionError("数据库任务必须拒绝未批准参数。")
        for invalid in (
            {"population_size": 0},
            {"mutation_rate": 1.1},
            {"objective_mode": "invalid"},
            {"disable_energy_observability": "false"},
            {"battery_capacity_kwh": 10000},
        ):
            try:
                validate_run_parameters("dispatch", invalid)
            except ValueError:
                pass
            else:
                raise AssertionError(f"无效参数必须被拒绝：{invalid}")
        try:
            validate_run_parameters("timetable_audit", {})
        except ValueError:
            pass
        else:
            raise AssertionError("运行图任务必须引用快照内文件。")


def verify_rolling_example_matches_frozen_battery() -> None:
    """滚动任务示例状态不能超过当前冻结输入的储能容量或功率。"""

    battery = json.loads((ROOT / "data" / "real_shuohuang" / "battery.json").read_text(encoding="utf-8"))
    parameters = json.loads(
        (ROOT / "database" / "examples" / "rolling_rescheduling_parameters.json").read_text(
            encoding="utf-8"
        )
    )
    devices = parameters["storage_devices"]
    assert devices
    assert sum(float(item["soc_kwh"]) for item in devices) <= float(battery["capacity_kwh"]) + 1e-9
    assert sum(float(item["max_charge_power_kw"]) for item in devices) <= float(
        battery["max_charge_power_kW"]
    ) + 1e-9
    # 正式放电功率尚未提供，当前冻结数据按零放电保守处理。
    assert sum(float(item["max_discharge_power_kw"]) for item in devices) <= float(
        battery.get("max_discharge_power_kW", 0.0)
    ) + 1e-9


def main() -> int:
    verify_migrations()
    verify_snapshot_roundtrip()
    verify_dataset_projection()
    verify_result_projection()
    verify_storage_device_parameter_query()
    verify_current_output_formats()
    verify_transaction_rollback()
    verify_concurrency_guards()
    verify_request_idempotency_digest()
    verify_worker_adapter()
    verify_worker_heartbeat_abort()
    verify_worker_output_decoding()
    verify_solver_resource_budget()
    verify_command_boundary()
    verify_rolling_example_matches_frozen_battery()
    print("database integration smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
