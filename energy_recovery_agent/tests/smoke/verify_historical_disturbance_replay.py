"""验证历史扰动合同、数据库任务边界和真实滚动组件回放链路。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.worker import build_algorithm_command, validate_run_parameters
from historical_disturbance_replay import (
    parse_historical_disturbance_replay,
)
from operating_conditions import OperatingConditions, TemporarySpeedRestriction, speed_limit_kmh_at
from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import DynamicPowerArmLimit, PowerArmElectricalLimit
from resource_constraints import ResourceUnavailability, build_default_resource_model, build_resource_intervals, check_schedule_resources
from scheduler_nsga2 import build_power_cache
from train_simulator import BatteryStorageParameters, load_config, train_speed_limit_mps
from recovery_conflict_analysis import extract_recovery_conflict_analysis
from exact_resource_feasibility import solve_exact_resource_feasibility
from tools.synthetic_rolling_rescheduling_benchmark import run_benchmark
from rolling_optimizer import (
    GeneratedSchedule,
    DynamicTrainAddition,
    DisturbanceScenario,
    RollingOptimizer,
    RollingWindowState,
    ScheduleTemplate,
    TemplateSearchConfig,
    apply_train_delay_observations,
    apply_dynamic_train_services,
)


TEMPLATE = ROOT / "data_templates" / "historical_disturbance_replay_template.json"


def _expect_invalid(payload, expected_text: str) -> None:
    try:
        parse_historical_disturbance_replay(payload)
    except ValueError as exc:
        assert expected_text in str(exc), str(exc)
    else:
        raise AssertionError(f"无效历史回放未被拒绝：{expected_text}")


def verify_contract_guards() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    replay = parse_historical_disturbance_replay(payload)
    assert replay.schema_version == "1.3"
    assert replay.execute_window_s == 3300
    assert len(replay.cycles) == 4
    assert replay.cycles[2].source_record_ids == (
        "example-record-0003", "example-record-0004"
    )
    assert replay.cycles[0].storage_states_provided is True
    assert len(replay.cycles[0].storage_device_states) == 2
    assert replay.cycles[0].events[0].event_type == "train_delay"
    assert replay.cycles[0].events[0].applicable is True
    assert replay.cycles[1].events[0].event_type == "temporary_speed_restriction"
    assert replay.cycles[1].events[0].applicable is True
    assert replay.cycles[1].events[0].payload["direction"] == "forward"
    assert replay.observations[0].observed_train_delays_s == (("H001", 30),)
    assert replay.preflight()["execution_allowed"] is True

    invalid = deepcopy(payload)
    invalid["unexpected"] = True
    _expect_invalid(invalid, "未批准字段")
    invalid = deepcopy(payload)
    invalid["cycles"][1]["cycle_index"] = 3
    _expect_invalid(invalid, "必须连续且从0开始")
    invalid = deepcopy(payload)
    invalid["cycles"][1]["current_time_s"] = 3299
    _expect_invalid(invalid, "匹配固定滚动窗口")
    invalid = deepcopy(payload)
    invalid["cycles"][1]["source_record_ids"] = ["example-record-0001"]
    _expect_invalid(invalid, "不能跨周期重复")
    invalid = deepcopy(payload)
    invalid["cycles"][1]["observed_at"] = "2026-01-01T00:55:00"
    _expect_invalid(invalid, "必须包含时区")
    invalid = deepcopy(payload)
    invalid["cycles"][1]["observed_at"] = "2025-12-31T23:00:00+08:00"
    _expect_invalid(invalid, "必须按周期严格递增")
    invalid = deepcopy(payload)
    invalid["cycles"][0]["events"].append(
        deepcopy(invalid["cycles"][0]["events"][0])
    )
    _expect_invalid(invalid, "event_id不能在同一周期重复")
    invalid = deepcopy(payload)
    invalid["cycles"][0]["observed_heavy_delay_s"] = 60
    _expect_invalid(invalid, "不能同时提供重车汇总晚点")

    executable = deepcopy(payload)
    for cycle in executable["cycles"]:
        cycle["events"] = []
    executable["cycles"][0]["events"] = [{
        "event_id": "cancel-001",
        "event_type": "train_cancelled",
        "entity_id": "H001",
        "payload": {"reason": "测试"},
    }]
    executable_replay = parse_historical_disturbance_replay(executable)
    assert not executable_replay.blocking_events
    assert executable_replay.preflight()["execution_allowed"] is True
    assert executable_replay.preflight()["events"][0]["status"] == "accepted"
    legacy = deepcopy(executable)
    legacy["schema_version"] = "1.1"
    legacy_replay = parse_historical_disturbance_replay(legacy)
    assert len(legacy_replay.blocking_events) == 1
    assert "升级到1.2" in legacy_replay.blocking_events[0].blocking_reason

    old_direction_contract = deepcopy(payload)
    old_direction_contract["schema_version"] = "1.2"
    old_replay = parse_historical_disturbance_replay(old_direction_contract)
    assert len(old_replay.blocking_events) == 1
    assert "升级到1.3" in old_replay.blocking_events[0].blocking_reason


def verify_train_delay_application_guards() -> None:
    template = ScheduleTemplate(100, 100, 50, 2, 0)
    schedule = GeneratedSchedule([0, 100], [], template)
    shifted = apply_train_delay_observations(
        schedule, (("H002", 20),), current_time_s=50,
        locked_heavy_departures_s=(0,),
    )
    assert shifted.heavy_departures_s == [0, 120]
    try:
        apply_train_delay_observations(
            schedule, (("H001", 20),), current_time_s=50,
            locked_heavy_departures_s=(0,),
        )
    except ValueError as exc:
        assert "不能改写" in str(exc), str(exc)
    else:
        raise AssertionError("逐列车晚点不能改写锁定历史。")
    for delays, expected_text in (
        ((("H002", 0), ("H003", 1)), "不存在"),
        ((("H001", 120),), "越序"),
    ):
        try:
            apply_train_delay_observations(
                schedule, delays, current_time_s=0,
            )
        except ValueError as exc:
            assert expected_text in str(exc), str(exc)
        else:
            raise AssertionError(f"非法逐列车晚点未被拒绝：{delays}")


def verify_extended_event_contracts() -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    for cycle in payload["cycles"]:
        cycle["events"] = []
    extended_events = [
        {
            "event_id": "cancel-001", "event_type": "train_cancelled",
            "entity_id": "H001", "payload": {"reason": "车辆故障"},
        },
        {
            "event_id": "add-001", "event_type": "train_added",
            "entity_id": "E003",
            "payload": {"train_type": "Empty", "departure_s": 4000},
        },
        {
            "event_id": "resource-001", "event_type": "resource_unavailable",
            "entity_id": "throat:2",
            "payload": {"resource_type": "throat", "start_time_s": 3000, "end_time_s": 5000},
        },
        {
            "event_id": "power-001", "event_type": "power_arm_limit",
            "entity_id": "arm-001",
            "payload": {"max_traction_supply_kw": 2000, "start_time_s": 3000, "end_time_s": 5000},
        },
        {
            "event_id": "speed-direction-001",
            "event_type": "temporary_speed_restriction",
            "entity_id": "TSR-DOWN-001",
            "payload": {
                "start_km": 10, "end_km": 20, "speed_limit_kmh": 60,
                "start_time_s": 3000, "end_time_s": 5000, "direction": "down",
            },
        },
    ]
    payload["cycles"][0]["events"] = extended_events
    replay = parse_historical_disturbance_replay(payload)
    assert not replay.blocking_events
    speed_event = next(event for event in replay.cycles[0].events if event.event_id == "speed-direction-001")
    assert speed_event.payload["direction"] == "forward"
    observation = replay.cycles[0].to_observation()
    assert observation.cancelled_train_ids == ("H001",)
    assert observation.added_trains[0] == DynamicTrainAddition("E003", "Empty", 4000)
    assert observation.resource_unavailabilities[0].resource_id == "throat:2"
    assert observation.dynamic_power_arm_limits[0].max_traction_supply_kw == 2000

    invalid = deepcopy(payload)
    invalid["cycles"][0]["events"][3]["payload"] = {
        "start_time_s": 3000, "end_time_s": 5000
    }
    _expect_invalid(invalid, "至少需要一个动态功率限值")
    invalid = deepcopy(payload)
    invalid["cycles"][0]["events"][2]["payload"]["resource_type"] = "unknown"
    _expect_invalid(invalid, "resource_type无效")
    invalid = deepcopy(payload)
    invalid["cycles"][0]["events"].append({
        "event_id": "cancel-delay-conflict",
        "event_type": "train_delay",
        "entity_id": "H001",
        "payload": {"delay_s": 10},
    })
    _expect_invalid(invalid, "不能同时取消并晚点")
    invalid = deepcopy(payload)
    invalid["cycles"][1]["events"] = [{
        "event_id": "stale-add",
        "event_type": "train_added",
        "entity_id": "H009",
        "payload": {"train_type": "Heavy", "departure_s": 1},
    }]
    _expect_invalid(invalid, "不能加开早于当前周期")

    invalid = deepcopy(payload)
    invalid["cycles"][0]["events"][4]["payload"]["direction"] = "sideways"
    _expect_invalid(invalid, "direction无效")


def verify_directional_speed_restriction_application() -> None:
    """证明单方向限速不会污染反方向列车，双向规则仍同时生效。"""

    profile = OperatingConditions(speed_restrictions=[
        TemporarySpeedRestriction("forward-only", 10, 20, 60, direction="down"),
        TemporarySpeedRestriction("reverse-only", 30, 40, 50, direction="up"),
        TemporarySpeedRestriction("both", 50, 60, 45, direction="all"),
    ])
    assert speed_limit_kmh_at(profile, 120, 15, 0, "forward") == 60
    assert speed_limit_kmh_at(profile, 120, 15, 0, "reverse") == 120
    assert speed_limit_kmh_at(profile, 120, 35, 0, "forward") == 120
    assert speed_limit_kmh_at(profile, 120, 35, 0, "reverse") == 50
    assert speed_limit_kmh_at(profile, 120, 55, 0, "forward") == 45
    assert speed_limit_kmh_at(profile, 120, 55, 0, "reverse") == 45

    route, trains, _battery = load_config(ROOT / "sandbox_config.json")
    route = replace(route, operating_conditions=profile)
    assert abs(train_speed_limit_mps(route, trains["Heavy"], 15, 0) * 3.6 - 60) < 1e-9
    assert abs(train_speed_limit_mps(route, trains["Empty"], 15, 0) * 3.6 - 120) < 1e-9


def verify_dynamic_event_execution() -> None:
    template = ScheduleTemplate(100, 100, 50, 2, 1)
    schedule = GeneratedSchedule([100, 200], [150], template)
    changed = apply_dynamic_train_services(
        schedule,
        ("H002",),
        (DynamicTrainAddition("E003", "Empty", 240),),
        current_time_s=50,
        locked_heavy_departures_s=(100,),
    )
    assert changed.heavy_train_ids == ["H001"]
    assert changed.heavy_departures_s == [100]
    assert changed.empty_train_ids == ["E001", "E003"]
    assert changed.empty_departures_s == [150, 240]
    try:
        apply_dynamic_train_services(
            schedule, ("H001",), (), current_time_s=50,
            locked_heavy_departures_s=(100,),
        )
    except ValueError as exc:
        assert "不能取消已执行或已锁定列车" in str(exc)
    else:
        raise AssertionError("取消事件不能改写锁定历史。")

    route, trains, _battery = load_config(ROOT / "sandbox_config.json")
    heavy_cache = build_power_cache(trains["Heavy"], route)
    empty_cache = build_power_cache(trains["Empty"], route)
    base_model = build_default_resource_model(route)
    probe = GeneratedSchedule([100], [], ScheduleTemplate(900, 900, 0, 1, 0))
    first_interval = build_resource_intervals(probe, base_model, heavy_cache, empty_cache)[0]
    outage = ResourceUnavailability(
        "outage-1", first_interval.resource_id, first_interval.resource_type,
        int(first_interval.start_time_s), int(first_interval.end_time_s) + 1,
    )
    outage_model = type(base_model)(
        **{**base_model.__dict__, "unavailabilities": (outage,)}
    )
    checked = check_schedule_resources(probe, outage_model, heavy_cache, empty_cache)
    assert any(item.conflict_type == "resource_unavailable_conflict" for item in checked.conflicts)
    analysis = extract_recovery_conflict_analysis(
        probe,
        (DisturbanceScenario("normal"),),
        outage_model,
        heavy_cache,
        empty_cache,
        current_time_s=0,
    )
    assert analysis.conflicts[0].train_a == analysis.conflicts[0].train_b == "H001"
    assert analysis.conflicts[0].adjustable_train_ids == ("H001",)
    exact = solve_exact_resource_feasibility(
        probe.template,
        (DisturbanceScenario("normal"),),
        outage_model,
        heavy_cache,
        empty_cache,
        horizon_s=1000,
        max_adjustment_s=500,
        time_limit_s=10,
    )
    assert exact.feasible is True, exact
    assert exact.diagnostics["resource_outage_disjunction_count"] > 0

    battery = BatteryStorageParameters(100, 0.9, 0, 1, 0, 0)
    static_limit = PowerArmElectricalLimit(max_traction_supply_kw=1000)
    dynamic_limit = DynamicPowerArmLimit(
        "limit-1", "arm-test", 10, 20, max_traction_supply_kw=100,
    )
    system = EnergySettlementSystem(
        battery, settlement_time_step_s=10, allow_storage=False,
        power_arm_limits={"arm-test": static_limit},
        dynamic_power_arm_limits=(dynamic_limit,),
    )
    result = system.settle([{0: (500, 1, "arm-test", 10), 10: (500, 1, "arm-test", 10)}])
    assert abs(result.traction_supply_excess_kwh - (400 * 10 / 3600)) < 1e-9
    edge_system = EnergySettlementSystem(
        battery, settlement_time_step_s=10, allow_storage=False,
        power_arm_limits={"arm-test": static_limit},
        dynamic_power_arm_limits=(
            DynamicPowerArmLimit("edge", "arm-test", 5, 15, max_traction_supply_kw=100),
            DynamicPowerArmLimit("no-relax", "arm-test", 0, 20, max_traction_supply_kw=2000),
        ),
    )
    edge_result = edge_system.settle([{0: (500, 1, "arm-test", 10), 10: (500, 1, "arm-test", 10)}])
    assert abs(edge_result.traction_supply_excess_kwh - (800 * 10 / 3600)) < 1e-9

    optimizer = RollingOptimizer(
        route,
        heavy_cache,
        empty_cache,
        EnergySettlementSystem(
            _battery,
            route.energy_transfer_ranges_km,
            settlement_time_step_s=10,
            allow_direct_use=False,
            allow_storage=True,
        ),
    )
    optimized = optimizer.optimize_once(
        RollingWindowState(
            0, [], [],
            cancelled_train_ids=("H002",),
            added_trains=(DynamicTrainAddition("E003", "Empty", 500),),
            dynamic_power_arm_limits=(dynamic_limit,),
        ),
        ScheduleTemplate(900, 900, 300, 2, 1),
        horizon_s=1800,
        execute_window_s=600,
        search_config=TemplateSearchConfig(
            population_size=2,
            generations=1,
            elite_count=1,
            min_headway_s=900,
            max_headway_s=900,
            max_phase_s=300,
            allowed_heavy_headways_s=(900,),
            allowed_empty_headways_s=(900,),
            allowed_phases_s=(300,),
            allowed_holds_s=(0,),
            allowed_storage_align_shifts_s=(0,),
        ),
        enable_recovery=False,
        allow_infeasible_commit_for_experiment=True,
    )
    execution_state = optimized.search_diagnostics["execution_state"]
    assert execution_state["planned_heavy_train_ids"] == ["H001"]
    assert execution_state["planned_empty_train_ids"] == ["E001", "E003"]
    assert execution_state["cancelled_train_ids"] == ["H002"]
    assert execution_state["dynamic_power_limit_ids"] == ["limit-1"]


def verify_database_command_boundary() -> None:
    with TemporaryDirectory(prefix="historical_replay_command_") as temp_name:
        data_dir = Path(temp_name)
        replay_path = data_dir / "platform" / "history.json"
        replay_path.parent.mkdir(parents=True)
        shutil.copyfile(TEMPLATE, replay_path)
        parameters = {"disturbance_history_relative_path": "platform/history.json"}
        validate_run_parameters("rolling_rescheduling", parameters)
        command = build_algorithm_command(
            "rolling_rescheduling", parameters,
            data_dir=data_dir, output_dir=data_dir / "output",
        )
        assert command[command.index("--disturbance-history") + 1] == str(replay_path.resolve())
        assert command[command.index("--disturbance-history-label") + 1] == "platform/history.json"

        for invalid in (
            {"disturbance_history_relative_path": ""},
            {
                "disturbance_history_relative_path": "platform/history.json",
                "storage_devices": [{"storage_section_id": "S1", "soc_kwh": 0}],
            },
        ):
            try:
                validate_run_parameters("rolling_rescheduling", invalid)
            except ValueError:
                pass
            else:
                raise AssertionError(f"冲突的数据库回放参数未被拒绝：{invalid}")
        try:
            build_algorithm_command(
                "rolling_rescheduling",
                {"disturbance_history_relative_path": "../outside.json"},
                data_dir=data_dir,
                output_dir=data_dir / "output",
            )
        except (ValueError, FileNotFoundError):
            pass
        else:
            raise AssertionError("历史回放路径不能逃逸冻结输入快照。")


def main() -> int:
    verify_contract_guards()
    verify_train_delay_application_guards()
    verify_extended_event_contracts()
    verify_directional_speed_restriction_application()
    verify_dynamic_event_execution()
    verify_database_command_boundary()
    print("historical disturbance replay verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
