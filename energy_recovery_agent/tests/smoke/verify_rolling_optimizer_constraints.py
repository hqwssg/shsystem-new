# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rolling_optimizer import (
    DisturbanceScenario,
    GeneratedSchedule,
    RollingOptimizer,
    RollingWindowState,
    ScheduleScore,
    ScheduleTemplate,
    TemplateSearchConfig,
    build_power_series,
    build_search_diagnostics,
    candidate_selection_key,
    dominates,
    effective_objective_tuple,
    evaluate_schedule,
    generate_schedule,
    pareto_template_front,
    run_mpc_cycles,
    apply_scenario,
    template_key,
    unique_templates,
)
from data_ingestion import DataValidationReport, _validate_route_metadata, load_real_data_bundle
from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit, StorageSectionInterval
from run_dispatch_case import (
    _candidate_schedule,
    _trajectory_plot_points,
    candidate_id_for_template,
    candidate_rows,
    train_rows,
)
from resource_constraints import ResourceConfig, ResourceModel
from scheduler_nsga2 import (
    PowerSeriesCache,
    TrainScheduleProblem,
    dynamic_safe_distance_km,
    headway_violation_seconds,
    normalize_and_pick_best,
    schedule_deviation,
    signal_violation_count,
    violates_fixed_block,
    violates_headway,
    violates_moving_block,
)
from unittest.mock import patch


def _score(**overrides) -> ScheduleScore:
    """函数 _score：执行该模块中的相关处理逻辑。"""
    values = {
        "feasible": True,
        "total_cost": 0.0,
        "headway_deviation": 100.0,
        "worst_case_cost": 0.0,
        "worst_case_headway_deviation": 100.0,
        "scenario_count": 1,
        "wasted_kwh": 1000.0,
        "grid_kwh": 2000.0,
    }
    values.update(overrides)
    return ScheduleScore(**values)


def main() -> int:
    # 调度入口必须在同一预测时域内评价基线和优化方案。独立覆盖该契约，避免依赖耗时的端到端搜索：
    # 模板可以包含超出当前时域的发车，但导出的基线运行图不能把这些后续列车泄漏到比较中。
    """函数 main：执行该模块中的相关处理逻辑。"""
    horizon_template = ScheduleTemplate(
        heavy_headway_s=600,
        empty_headway_s=900,
        heavy_empty_phase_s=300,
        heavy_count=8,
        empty_count=6,
    )
    full_schedule = generate_schedule(horizon_template)
    truncated_schedule = _candidate_schedule(
        horizon_template,
        current_time_s=0,
        horizon_s=1800,
    )
    if len(truncated_schedule.heavy_departures_s) != 4:
        raise AssertionError(
            "baseline horizon filter kept the wrong heavy-train population: "
            f"{truncated_schedule.heavy_departures_s}"
        )
    if len(truncated_schedule.empty_departures_s) != 2:
        raise AssertionError(
            "baseline horizon filter kept the wrong empty-train population: "
            f"{truncated_schedule.empty_departures_s}"
        )
    if len(truncated_schedule.heavy_departures_s) >= len(full_schedule.heavy_departures_s):
        raise AssertionError("horizon regression fixture did not exercise truncation")

    for overrides, expected_field in (
        ({"total_cost": float("nan")}, "total_cost"),
        ({"constraint_violation": float("inf")}, "constraint_violation"),
        ({"feasible": "false"}, "feasible"),
        ({"scenario_count": 1.5}, "scenario_count"),
        ({"objective_priority": "unknown"}, "objective_priority"),
    ):
        try:
            _score(**overrides)
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid rolling score was accepted: {overrides!r}")
    decisions = [list(range(10)), list(range(10, 20))]
    best_x, best_f1, best_f2 = normalize_and_pick_best(
        [(1.0, 10.0), (2.0, 0.0)],
        decisions,
    )
    assert best_x in decisions
    assert (best_f1, best_f2) in {(1.0, 10.0), (2.0, 0.0)}
    invalid_fronts = (
        ([], [], "must not be empty"),
        ([(1.0, 2.0)], [], "same length"),
        ([(float("nan"), 2.0)], [list(range(10))], "finite"),
        ([(1.0, 2.0)], [[0] * 9], "exactly 10"),
        ([(1.0, 2.0)], [[0] * 9 + [1.5]], "whole number"),
    )
    for objective_front, decision_front, expected_text in invalid_fronts:
        try:
            normalize_and_pick_best(objective_front, decision_front)
        except ValueError as exc:
            assert expected_text in str(exc)
        else:
            raise AssertionError("invalid Pareto front was accepted")

    cache_kwargs = {
        "times": [0, 10],
        "powers_kW": [0.0, 0.0],
        "energy_transfer_ratios": [0.0, 0.0],
        "power_arm_ids": ["", ""],
        "positions_km": [0.0, 1.0],
        "speeds_mps": [0.0, 0.0],
        "train_length_km": 1.0,
        "direction": "forward",
        "adhesion_coefficients": [0.28, 0.28],
        "speed_limits_mps": [33.3, 33.3],
        "brake_decelerations_mps2": [0.3, 0.3],
    }
    invalid_caches = (
        ({"powers_kW": [0.0]}, "length"),
        ({"times": [0, 0]}, "strictly increasing"),
        ({"energy_transfer_ratios": [0.0, float("nan")]}, "finite"),
        ({"train_length_km": True}, "train_length_km"),
        ({"start_time_s": True}, "start_time_s"),
        ({"direction": "sideways"}, "direction"),
    )
    for overrides, expected_text in invalid_caches:
        try:
            PowerSeriesCache(**{**cache_kwargs, **overrides})
        except ValueError as exc:
            assert expected_text in str(exc)
        else:
            raise AssertionError(f"invalid power cache was accepted: {overrides!r}")
    valid_cache = PowerSeriesCache(**cache_kwargs)
    normalized_cache = PowerSeriesCache(**{**cache_kwargs, "start_time_s": 1.0})
    assert type(normalized_cache.start_time_s) is int and normalized_cache.start_time_s == 1
    try:
        valid_cache.shifted(-1)
    except ValueError as exc:
        assert "depart_time_s" in str(exc)
    else:
        raise AssertionError("negative cache departure time was accepted")

    split_cache = PowerSeriesCache(
        times=[0, 10, 20],
        powers_kW=[10.0, 20.0, 30.0],
        energy_transfer_ratios=[0.0, 0.5, 0.0],
        power_arm_ids=["A", "A", "B"],
        positions_km=[0.0, 1.0, 2.0],
        speeds_mps=[1.0, 1.0, 1.0],
        train_length_km=1.0,
        direction="forward",
        adhesion_coefficients=[0.28, 0.28, 0.28],
        speed_limits_mps=[33.3, 33.3, 33.3],
        brake_decelerations_mps2=[0.3, 0.3, 0.3],
        power_allocation_ratios=[
            {("A", ""): 1.0},
            {("A", "S"): 0.5, ("B", ""): 0.5},
            {("B", ""): 1.0},
        ],
    )
    held_components = build_power_series(split_cache, [0], storage_hold_s=5)
    held_times = {
        (str(sample[2]), str(sample[4])): sorted(series)
        for series in held_components
        for sample in series.values()
    }
    if held_times != {("A", ""): [0], ("A", "S"): [15], ("B", ""): [15, 25]}:
        raise AssertionError(f"cross-section train components were shifted inconsistently: {held_times}")
    operation_held = build_power_series(
        split_cache,
        [0],
        storage_hold_s=5,
        operation_delay_events_by_departure={0: ((20.0, 7),)},
    )
    operation_held_times = {
        (str(sample[2]), str(sample[4])): sorted(series)
        for series in operation_held
        for sample in series.values()
    }
    if operation_held_times != {
        ("A", ""): [0],
        ("A", "S"): [15],
        ("B", ""): [15, 32],
    }:
        raise AssertionError(
            "storage hold triggered a downstream operation at the wrong base elapsed time: "
            f"{operation_held_times}"
        )

    # 延误边界可能落在仿真样本内部。必须在该边界切分样本，使延误区间不含牵引或再生功率，
    # 同时精确保留原始能量。
    mid_sample_delayed = build_power_series(
        split_cache,
        [0],
        operation_delay_events_by_departure={0: ((5.0, 7),)},
    )
    mid_sample_by_component = {
        (str(sample[2]), str(sample[4])): sorted(series.items())
        for series in mid_sample_delayed
        for sample in series.values()
    }
    expected_mid_sample = {
        ("A", ""): [(0, (10.0, 0.0, "A", 5.0, "")), (12, (10.0, 0.0, "A", 5.0, ""))],
        ("A", "S"): [(17, (10.0, 0.5, "A", 10.0, "S"))],
        ("B", ""): [(17, (10.0, 0.5, "B", 10.0, "")), (27, (30.0, 0.0, "B", 10.0, ""))],
    }
    if mid_sample_by_component != expected_mid_sample:
        raise AssertionError(
            "delay crossing a sample boundary was not split at the physical threshold: "
            f"{mid_sample_by_component}"
        )

    # 即使储能分配比例与可转移占用比例不同，组件切分也必须保留原始可转移比例。
    # 本例中 50% 功率分配给储能，但列车只有 25% 功率可转移；将储能组件比例提升为 1
    # 会重复计算可回收能量。
    ratio_probe = PowerSeriesCache(
        times=[0],
        powers_kW=[100.0],
        energy_transfer_ratios=[0.25],
        power_arm_ids=["A"],
        positions_km=[0.0],
        speeds_mps=[1.0],
        train_length_km=1.0,
        direction="forward",
        adhesion_coefficients=[0.28],
        speed_limits_mps=[33.3],
        brake_decelerations_mps2=[0.3],
        power_allocation_ratios=[{("A", "S"): 0.5, ("B", ""): 0.5}],
    )
    components = ratio_probe.base_series_components()
    eligible_component_energy = sum(
        abs(float(component[0][0])) * float(component[0][1])
        for component in components
    )
    if abs(eligible_component_energy - 25.0) > 1e-9:
        raise AssertionError(
            "component split promoted partial transfer eligibility: "
            f"expected 25 kW-equivalent, got {eligible_component_energy}"
        )
    original_energy = sum(
        float(sample[0]) * float(sample[3])
        for component in split_cache.base_series_components()
        for sample in component.values()
    )
    delayed_energy = sum(
        float(sample[0]) * float(sample[3])
        for component in mid_sample_delayed
        for sample in component.values()
    )
    if abs(delayed_energy - original_energy) > 1e-9:
        raise AssertionError(
            f"splitting a delayed sample changed total energy: {original_energy} -> {delayed_energy}"
        )

    # 多次延误（包括发生在后续样本内部的延误）必须累加，不能覆盖已偏移的时间戳或改变能量总量。
    multi_delayed = build_power_series(
        split_cache,
        [0],
        operation_delay_events_by_departure={0: ((5.0, 7), (22.0, 3))},
    )
    multi_b = next(
        component
        for component in multi_delayed
        if any(str(sample[2]) == "B" for sample in component.values())
    )
    if sorted(multi_b) != [17, 27, 32] or [multi_b[t][3] for t in sorted(multi_b)] != [10.0, 2.0, 8.0]:
        raise AssertionError(
            f"multiple delay events were not accumulated and split correctly: {multi_b}"
        )
    multi_energy = sum(
        float(sample[0]) * float(sample[3])
        for component in multi_delayed
        for sample in component.values()
    )
    if abs(multi_energy - original_energy) > 1e-9:
        raise AssertionError(
            f"multiple delay events changed total energy: {original_energy} -> {multi_energy}"
        )

    # 作业延误先于线路内储能停车施加。因此停车必须从延误后的储能入口时间戳开始，
    # 并整体移动所有组件，同时保留各组件时长。
    delayed_and_held = build_power_series(
        split_cache,
        [0],
        storage_hold_s=4,
        operation_delay_events_by_departure={0: ((5.0, 7),)},
    )
    delayed_and_held_times = {
        (str(sample[2]), str(sample[4])): sorted(series)
        for series in delayed_and_held
        for sample in series.values()
    }
    if delayed_and_held_times != {
        ("A", ""): [0, 12],
        ("A", "S"): [21],
        ("B", ""): [21, 31],
    }:
        raise AssertionError(
            "storage hold was not composed after operation delay: "
            f"{delayed_and_held_times}"
        )
    delayed_and_held_energy = sum(
        float(sample[0]) * float(sample[3])
        for component in delayed_and_held
        for sample in component.values()
    )
    if abs(delayed_and_held_energy - original_energy) > 1e-9:
        raise AssertionError(
            "operation delay plus storage hold changed total energy: "
            f"{original_energy} -> {delayed_and_held_energy}"
        )

    export_schedule = GeneratedSchedule(
        heavy_departures_s=[0],
        empty_departures_s=[],
        template=ScheduleTemplate(100, 100, 0, 1, 0),
    )
    export_evaluation = SimpleNamespace(label="operation", schedule=export_schedule)
    export_stations = tuple(
        SimpleNamespace(name=f"S{index}", position_km=float(index))
        for index in range(3)
    )
    intermediate_operation_model = ResourceModel(
        stations=export_stations,
        config=ResourceConfig(),
        station_operation_assignments=(
            {"station_name": "S1", "applies_to": "all", "min_occupancy_s": 7},
        ),
    )
    intermediate_row = train_rows(
        export_evaluation,
        split_cache,
        split_cache,
        intermediate_operation_model,
    )[0]
    if intermediate_row["arrival_time_s"] != 27 or intermediate_row["operation_delay_s"] != 7:
        raise AssertionError(
            f"schedule export ignored intermediate operation delay: {intermediate_row}"
        )
    operation_plot_times, _operation_plot_positions = _trajectory_plot_points(
        split_cache,
        0,
        operation_delay_events=((10.0, 7),),
    )
    if operation_plot_times != [0.0, 10.0, 17.0, 17.0, 27.0]:
        raise AssertionError(
            f"train diagram ignored intermediate operation delay: {operation_plot_times}"
        )
    terminal_operation_model = ResourceModel(
        stations=export_stations,
        config=ResourceConfig(),
        station_operation_assignments=(
            {"station_name": "S2", "applies_to": "all", "min_occupancy_s": 60},
        ),
    )
    terminal_row = train_rows(
        export_evaluation,
        split_cache,
        split_cache,
        terminal_operation_model,
    )[0]
    if terminal_row["arrival_time_s"] != 20 or terminal_row["operation_delay_s"] != 0:
        raise AssertionError(f"terminal operation changed train arrival time: {terminal_row}")
    zero_overlap_tag_cache = PowerSeriesCache(
        times=[0, 10, 20],
        powers_kW=[10.0, 20.0, 30.0],
        energy_transfer_ratios=[0.0, 0.0, 1.0],
        power_arm_ids=["A", "A", "A"],
        positions_km=[0.0, 1.0, 2.0],
        speeds_mps=[1.0, 1.0, 1.0],
        train_length_km=1.0,
        direction="forward",
        adhesion_coefficients=[0.28, 0.28, 0.28],
        speed_limits_mps=[33.3, 33.3, 33.3],
        brake_decelerations_mps2=[0.3, 0.3, 0.3],
        # 几何查询可能保留边界标签，但权威的列车车体重叠长度仍可能为零。
        storage_section_ids=["S", "S", "S"],
    )
    if zero_overlap_tag_cache.first_storage_entry_elapsed_s(0) != 20:
        raise AssertionError("zero-overlap storage tags triggered an early in-route hold")
    zero_overlap_held = build_power_series(
        zero_overlap_tag_cache,
        [0],
        storage_hold_s=5,
    )
    if [sorted(component) for component in zero_overlap_held] != [[0, 10, 25]]:
        raise AssertionError("storage hold and trajectory entry used different overlap rules")
    no_storage_cache = PowerSeriesCache(
        times=[0, 10, 20],
        powers_kW=[0.0, 0.0, 0.0],
        energy_transfer_ratios=[0.0, 0.0, 0.0],
        power_arm_ids=["A", "A", "A"],
        positions_km=[0.0, 1.0, 2.0],
        speeds_mps=[1.0, 1.0, 0.0],
        train_length_km=0.1,
        direction="forward",
        adhesion_coefficients=[0.28, 0.28, 0.28],
        speed_limits_mps=[33.3, 33.3, 33.3],
        brake_decelerations_mps2=[0.3, 0.3, 0.3],
        storage_section_ids=["", "", ""],
    )
    if no_storage_cache.state_at(21, depart_time_s=0, storage_hold_s=5) is not None:
        raise AssertionError("signal state invented a hold for a route without storage")
    if no_storage_cache.safety_state_at(21, depart_time_s=0, storage_hold_s=5) is not None:
        raise AssertionError("moving-block state invented a hold for a route without storage")
    signal_cache = PowerSeriesCache(
        times=[0, 10, 20],
        powers_kW=[0.0, 0.0, 0.0],
        energy_transfer_ratios=[0.0, 1.0, 1.0],
        power_arm_ids=["A", "A", "A"],
        positions_km=[0.0, 1.0, 2.0],
        speeds_mps=[1.0, 1.0, 0.0],
        train_length_km=0.1,
        direction="forward",
        adhesion_coefficients=[0.28, 0.28, 0.28],
        speed_limits_mps=[33.3, 33.3, 33.3],
        brake_decelerations_mps2=[0.3, 0.3, 0.3],
        storage_section_ids=["", "S", "S"],
        power_allocation_ratios=[
            {("A", ""): 1.0},
            {("A", "S"): 1.0},
            {("A", "S"): 1.0},
        ],
    )
    if violates_fixed_block(
        [0, 12],
        signal_cache,
        block_length_km=0.5,
        protection_blocks=0,
        check_step_s=1,
    ):
        raise AssertionError("unheld fixed-block probe was unexpectedly infeasible")
    if not violates_fixed_block(
        [0, 12],
        signal_cache,
        block_length_km=0.5,
        protection_blocks=0,
        check_step_s=1,
        storage_hold_s=5,
    ):
        raise AssertionError("storage hold was ignored by fixed-block protection")
    operation_events = {
        0: ((10.0, 5),),
        12: ((10.0, 5),),
    }
    if not violates_fixed_block(
        [0, 12],
        signal_cache,
        block_length_km=0.5,
        protection_blocks=0,
        check_step_s=1,
        operation_delay_events_by_departure=operation_events,
    ):
        raise AssertionError("mid-route operation delay was ignored by fixed-block protection")
    if not violates_moving_block(
        [0, 12],
        signal_cache,
        check_step_s=1,
        base_buffer_m=500.0,
        reaction_time_s=0.0,
        operation_delay_events_by_departure=operation_events,
    ):
        raise AssertionError("mid-route operation delay was ignored by moving-block protection")
    terminal_events = {
        0: ((20.0, 60),),
        12: ((20.0, 60),),
    }
    if violates_fixed_block(
        [0, 12],
        signal_cache,
        block_length_km=0.5,
        protection_blocks=0,
        check_step_s=1,
        operation_delay_events_by_departure=terminal_events,
    ):
        raise AssertionError("terminal operation incorrectly extended mainline signal occupancy")

    with patch("scheduler_nsga2.violates_fixed_block", return_value=True), patch(
        "scheduler_nsga2.violates_moving_block", return_value=False
    ):
        assert signal_violation_count([0, 1], None, {"mode": "fixed"}) == 1
        assert signal_violation_count([0, 1], None, {"mode": "fixed_block"}) == 1
    try:
        signal_violation_count([], None, {"mode": "hybrid", "check_step_s": -1})
    except ValueError as exc:
        assert "check_step_s" in str(exc)
    else:
        raise AssertionError("negative signal check step silently disabled safety checks")
    invalid_signal_configs = [
        ({"mode": "fixed", "check_step_s": True}, "check_step_s"),
        ({"mode": "fixed", "fixed_block_length_km": True}, "fixed_block_length_km"),
        ({"mode": "fixed", "fixed_block_protection_blocks": True}, "fixed_block_protection_blocks"),
        ({"mode": "moving", "moving_block_base_buffer_m": True}, "moving_block_base_buffer_m"),
        ({"mode": "fixed", "fixed_block_length_km": 0}, "fixed_block_length_km"),
        ({"mode": "fixed", "fixed_block_protection_blocks": 1.5}, "fixed_block_protection_blocks"),
        ({"mode": "moving", "moving_block_base_buffer_m": -1}, "moving_block_base_buffer_m"),
        ({"mode": "moving", "moving_block_reaction_time_s": -1}, "moving_block_reaction_time_s"),
        ({"mode": "moving", "moving_block_follower_service_decel_mps2": 0}, "decel"),
        ({"mode": "moving", "moving_block_lead_emergency_decel_mps2": float("nan")}, "decel"),
    ]
    for config, expected_field in invalid_signal_configs:
        try:
            signal_violation_count([], None, config)
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid signaling parameter was accepted: {config!r}")
    for invalid_setting in ("false", 1, None):
        try:
            TemplateSearchConfig(enable_storage_preset_search=invalid_setting)
        except ValueError as exc:
            assert "enable_storage_preset_search" in str(exc)
        else:
            raise AssertionError(f"non-boolean storage search setting was accepted: {invalid_setting!r}")
    for invalid_template in (
        ScheduleTemplate(1000, 1000, 0, 1.5, 1),
        ScheduleTemplate(1000, 1000, 0, 1, 1, storage_align_shift_s=0.5),
        ScheduleTemplate(1000, 1000, 0, 1, 1, start_time_s=True),
        ScheduleTemplate(1000, 1000, 0, 1, 1, start_time_s=-1),
    ):
        try:
            generate_schedule(invalid_template)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid schedule gene was silently truncated: {invalid_template!r}")
    try:
        dynamic_safe_distance_km(10.0, 10.0, reaction_time_s=-1.0)
    except ValueError as exc:
        assert "reaction_time_s" in str(exc)
    else:
        raise AssertionError("negative moving-block reaction time was accepted")

    for call, expected_field in (
        (lambda: violates_headway([0, 10], min_gap_s=-1), "min_gap_s"),
        (lambda: headway_violation_seconds([0, 10], min_gap_s=-1), "min_gap_s"),
        (lambda: schedule_deviation([0, 10], target_gap_s=-1), "target_gap_s"),
        (lambda: violates_headway([0, 10.5], min_gap_s=1), "departure time"),
        (lambda: violates_headway([-1, 10], min_gap_s=1), "departure time"),
    ):
        try:
            call()
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid timetable value was accepted by {call!r}")

    class _EndpointTrajectory:
        """类 _EndpointTrajectory：执行该模块中的相关处理逻辑。"""
        times = [0, 3]

    class _EndpointOnlyConflictCache:
        """类 _EndpointOnlyConflictCache：执行该模块中的相关处理逻辑。"""
        train_length_km = 0.0
        direction = "forward"

        def _trajectory_for_departure(self, _depart_time_s):
            """函数 _trajectory_for_departure：执行该模块中的相关处理逻辑。"""
            return _EndpointTrajectory()

        @staticmethod
        def _positions(elapsed_s, depart_time_s):
            """函数 _positions：执行该模块中的相关处理逻辑。"""
            global_time_s = elapsed_s + depart_time_s
            if global_time_s < 3:
                return 2.0 if depart_time_s == 0 else 0.0
            return 1.0

        def state_at(self, elapsed_s, depart_time_s=0):
            """函数 state_at：执行该模块中的相关处理逻辑。"""
            return self._positions(elapsed_s, depart_time_s), 0.0

        def safety_state_at(self, elapsed_s, depart_time_s=0):
            """函数 safety_state_at：执行该模块中的相关处理逻辑。"""
            return self._positions(elapsed_s, depart_time_s), 0.0, 1.0

    endpoint_cache = _EndpointOnlyConflictCache()
    assert violates_fixed_block(
        [0, 1], endpoint_cache, block_length_km=1.0, protection_blocks=0, check_step_s=5
    )
    assert violates_moving_block(
        [0, 1], endpoint_cache, check_step_s=5, base_buffer_m=500.0, reaction_time_s=0.0
    )

    report = DataValidationReport("synthetic")
    _validate_route_metadata(
        {
            "total_length_km": float("nan"),
            "max_speed_kmh": 100.0,
            "long_downhill_range_km": [0.0, 1.0],
            "signaling_system": {"mode": "fixed", "fixed_block_length_km": -2.0},
        },
        report,
    )
    assert any(issue.code == "invalid_number" and issue.field == "total_length_km" for issue in report.errors)
    assert any(
        issue.code == "invalid_signaling_parameter"
        and issue.field == "signaling_system.fixed_block_length_km"
        for issue in report.errors
    )

    farther = _score(
        feasible=False,
        constraint_violation=2.0,
        wasted_kwh=1.0,
        grid_kwh=1.0,
    )
    nearer = _score(
        feasible=False,
        constraint_violation=0.25,
        wasted_kwh=999999.0,
        grid_kwh=999999.0,
    )
    assert dominates(nearer, farther)
    assert not dominates(farther, nearer)

    tiny_nearer = _score(
        feasible=False,
        constraint_violation=1.1e-6,
        wasted_kwh=999.0,
        grid_kwh=999.0,
    )
    tiny_farther = _score(
        feasible=False,
        constraint_violation=1.4e-6,
        wasted_kwh=0.0,
        grid_kwh=0.0,
    )
    if candidate_selection_key(tiny_nearer) >= candidate_selection_key(tiny_farther):
        raise AssertionError("candidate selection rounded away a real constraint difference")

    template_a = ScheduleTemplate(900, 900, 300, 2, 2)
    template_b = ScheduleTemplate(900, 900, 600, 2, 2)
    template_c = ScheduleTemplate(1200, 1200, 600, 2, 2)
    different_count = ScheduleTemplate(900, 900, 300, 3, 2)
    different_start = ScheduleTemplate(900, 900, 300, 2, 2, start_time_s=60)
    assert candidate_id_for_template(template_a) == candidate_id_for_template(template_a)
    assert candidate_id_for_template(template_a) != candidate_id_for_template(template_b)
    assert candidate_id_for_template(template_a) != candidate_id_for_template(different_count)
    assert candidate_id_for_template(template_a) != candidate_id_for_template(different_start)
    assert len(unique_templates([template_a, different_count, different_start])) == 3
    duplicate_score = _score()
    tradeoff_score = _score(wasted_kwh=500.0, grid_kwh=2500.0)
    front = pareto_template_front(
        [
            (template_a, duplicate_score),
            (template_b, duplicate_score),
            (template_c, tradeoff_score),
        ]
    )
    assert len(front) == 2

    noise_a = _score(wasted_kwh=100.0004, grid_kwh=199.9996)
    noise_b = _score(wasted_kwh=99.9996, grid_kwh=200.0004)
    assert effective_objective_tuple(noise_a) == effective_objective_tuple(noise_b)
    noise_front = pareto_template_front([(template_a, noise_a), (template_b, noise_b)])
    assert len(noise_front) == 1

    bundle = load_real_data_bundle(Path("data") / "real_shuohuang")
    heavy_cache = PowerSeriesCache(
        times=[0, 3600],
        powers_kW=[100.0, 0.0],
        energy_transfer_ratios=[0.0, 0.0],
        power_arm_ids=["limited_arm", "limited_arm"],
        positions_km=[0.0, 1.0],
        speeds_mps=[1.0, 1.0],
        train_length_km=1.0,
        direction="forward",
        adhesion_coefficients=[0.28, 0.28],
        speed_limits_mps=[33.3, 33.3],
        brake_decelerations_mps2=[0.3, 0.3],
    )
    empty_cache = PowerSeriesCache(
        times=[0],
        powers_kW=[0.0],
        energy_transfer_ratios=[0.0],
        power_arm_ids=["limited_arm"],
        positions_km=[0.0],
        speeds_mps=[0.0],
        train_length_km=1.0,
        direction="reverse",
        adhesion_coefficients=[0.28],
        speed_limits_mps=[33.3],
        brake_decelerations_mps2=[0.3],
    )
    settlement_system = EnergySettlementSystem(
        bundle.battery,
        settlement_time_step_s=3600,
        allow_direct_use=False,
        allow_storage=False,
        power_arm_limits={
            "limited_arm": PowerArmElectricalLimit(
                max_traction_supply_kw=1.0,
                max_regen_absorption_kw=1.0,
            )
        },
    )
    problem = TrainScheduleProblem(bundle.route, heavy_cache, empty_cache, settlement_system)
    for decision_vector, expected_text in (
        ([0] * 9, "exactly 10"),
        ([0] * 9 + [1.5], "whole number"),
        ([0] * 9 + [10001], "10000"),
    ):
        try:
            problem._evaluate(decision_vector, {})
        except ValueError as exc:
            assert expected_text in str(exc)
        else:
            raise AssertionError(f"invalid schedule decision vector was accepted: {decision_vector!r}")
    schedule = GeneratedSchedule(
        heavy_departures_s=[0],
        empty_departures_s=[],
        template=ScheduleTemplate(3600, 3600, 0, 1, 0),
    )
    electrical_score = evaluate_schedule(
        schedule,
        heavy_cache,
        empty_cache,
        settlement_system,
        {"mode": "fixed_block"},
        min_depart_gap_s=0,
    )
    assert not electrical_score.feasible
    assert electrical_score.constraint_violation == 99.0
    assert electrical_score.electrical_constraint_violation_kwh == 99.0
    exported = candidate_rows(
        [(schedule.template, electrical_score)],
        current_time_s=0,
        horizon_s=3600,
        candidate_set="regression",
        energy_scenario="storage_no_direct",
    )[0]
    assert exported["traction_supply_excess_kwh"] == 99.0
    assert exported["electrical_constraint_violation_kwh"] == 99.0

    # 标称评价路径必须保留 storage_sections，使能量结算与主调度评价路径保持一致。
    captured = {}

    def _fake_build_time_space_network(schedule, resource_model, heavy_cache, empty_cache, storage_sections=None):
        """函数 _fake_build_time_space_network：执行该模块中的相关处理逻辑。"""
        captured["storage_sections"] = storage_sections

        class _Network:
            """类 _Network：执行该模块中的相关处理逻辑。"""
            node_count = 1
            arc_count = 1

        return _Network()

    class _ResourceCheck:
        """类 _ResourceCheck：执行该模块中的相关处理逻辑。"""
        conflict_count = 0
        conflicts = []
        flow_continuity_feasible = True
        flow_continuity_violations = []

    class _ResourceConfig:
        """类 _ResourceConfig：执行该模块中的相关处理逻辑。"""
        min_depart_headway_s = 0

    class _ResourceModel:
        """类 _ResourceModel：执行该模块中的相关处理逻辑。"""
        config = _ResourceConfig()

    with patch("rolling_optimizer.build_time_space_network", side_effect=_fake_build_time_space_network), patch(
        "rolling_optimizer.check_schedule_resources", return_value=_ResourceCheck()
    ):
        evaluate_schedule(
            schedule,
            heavy_cache,
            empty_cache,
            settlement_system,
            {"mode": "fixed_block"},
            resource_model=_ResourceModel(),
            storage_sections=(StorageSectionInterval("storage_probe", 0.0, 1.0, "forward"),),
            min_depart_gap_s=0,
        )
    assert captured.get("storage_sections") is not None
    assert len(tuple(captured["storage_sections"])) == 1
    assert tuple(captured["storage_sections"])[0].storage_section_id == "storage_probe"

    # optimize_once 必须使用调用方传入的 min_depart_gap_s 和 target_gap_s 评价候选，
    # 不能使用硬编码的资源间隔或默认目标间隔。
    captured_kwargs = {}

    def _fake_robust_evaluate_schedule(*args, **kwargs):
        """函数 _fake_robust_evaluate_schedule：执行该模块中的相关处理逻辑。"""
        captured_kwargs["schedule"] = args[0]
        captured_kwargs.update(kwargs)
        score = _score(
            feasible=True,
            total_cost=1.0,
            worst_case_cost=1.0,
            wasted_kwh=1.0,
            grid_kwh=1.0,
        )
        scenario_score_sink = kwargs.get("scenario_score_sink")
        if scenario_score_sink is not None:
            scenario_score_sink.extend((scenario, score) for scenario in args[1])
        return score

    class _Route:
        """类 _Route：执行该模块中的相关处理逻辑。"""
        signaling_system = {"mode": "fixed_block"}

    optimizer = RollingOptimizer(
        route=_Route(),
        heavy_cache=heavy_cache,
        empty_cache=empty_cache,
        settlement_system=settlement_system,
        resource_model=None,
        storage_sections=None,
    )
    base_template = ScheduleTemplate(3300, 2700, 2600, 3, 3)
    try:
        optimizer._context_for(
            replace(base_template, storage_preset_id="not_a_real_storage_preset")
        )
    except ValueError as exc:
        assert "Unknown storage_preset_id" in str(exc)
        assert "not_a_real_storage_preset" in str(exc)
    else:
        raise AssertionError(
            "unknown storage preset silently reused the default evaluation context"
        )
    with patch("rolling_optimizer.robust_evaluate_schedule", side_effect=_fake_robust_evaluate_schedule), patch(
        "rolling_optimizer.nsga2_template_search",
        side_effect=lambda base_template, search_config, evaluate_template: [
            (base_template, evaluate_template(base_template))
        ],
    ):
        result = optimizer.optimize_once(
            RollingWindowState(0, [0], []),
            base_template,
            horizon_s=7200,
            execute_window_s=600,
            search_config=TemplateSearchConfig(method="nsga2", population_size=1, generations=1),
            min_depart_gap_s=1234,
            target_gap_s=2345,
        )
    assert result.score.feasible is True
    assert captured_kwargs.get("min_depart_gap_s") == 1234
    assert captured_kwargs.get("target_gap_s") == 2345
    assert captured_kwargs.get("disturbance_from_time_s") == 0
    assert list(captured_kwargs.get("locked_heavy_departures_s") or []) == [0]
    assert list(captured_kwargs.get("locked_empty_departures_s") or []) == []
    assert captured_kwargs["schedule"].heavy_departures_s.count(0) == 1

    # 已观测晚点属于本轮实际执行状态：计划运行图保留名义时刻，执行运行图和提交清单使用实际时刻。
    realized_template = ScheduleTemplate(900, 900, 300, 1, 1)
    with patch(
        "rolling_optimizer.robust_evaluate_schedule",
        side_effect=_fake_robust_evaluate_schedule,
    ), patch(
        "rolling_optimizer.nsga2_template_search",
        side_effect=lambda template, _config, evaluate: [(template, evaluate(template))],
    ):
        realized_result = optimizer.optimize_once(
            RollingWindowState(
                0,
                [],
                [],
                observed_heavy_delay_s=120,
                observed_empty_delay_s=60,
            ),
            realized_template,
            horizon_s=1800,
            execute_window_s=600,
            search_config=TemplateSearchConfig(
                method="nsga2", population_size=1, generations=1
            ),
        )
    assert realized_result.schedule.heavy_departures_s == [0]
    assert realized_result.schedule.empty_departures_s == [300]
    assert realized_result.execution_schedule.heavy_departures_s == [120]
    assert realized_result.execution_schedule.empty_departures_s == [360]
    assert realized_result.commit_status == "committed_robust_feasible"
    assert realized_result.executable_heavy_departures_s == [120]
    assert realized_result.executable_empty_departures_s == [360]
    assert realized_result.search_diagnostics["execution_state"]["scenario"] == "normal"

    # 候选不能通过把请求列车推到预测时域之外来获得虚假的能量收益。基础计划在窗口内包含两列重车和两列空车；
    # 能量较低的延误候选只包含一列重车，因此必须判为不可行。
    population_base_template = ScheduleTemplate(600, 600, 300, 2, 2)
    population_dropped_template = ScheduleTemplate(2000, 2000, 1900, 2, 2)

    def _population_score(schedule, *_args, **_kwargs):
        """函数 _population_score：执行该模块中的相关处理逻辑。"""
        service_count = len(schedule.heavy_departures_s) + len(schedule.empty_departures_s)
        return _score(
            feasible=True,
            total_cost=float(service_count),
            worst_case_cost=float(service_count),
            wasted_kwh=float(service_count),
            grid_kwh=float(service_count),
        )

    with patch(
        "rolling_optimizer.robust_evaluate_schedule",
        side_effect=_population_score,
    ), patch(
        "rolling_optimizer.nsga2_template_search",
        side_effect=lambda _base, _config, evaluate_template: [
            (population_base_template, evaluate_template(population_base_template)),
            (population_dropped_template, evaluate_template(population_dropped_template)),
        ],
    ), patch("rolling_optimizer.explain_robust_scenarios", return_value=[]):
        population_result = optimizer.optimize_once(
            RollingWindowState(0, [], []),
            population_base_template,
            horizon_s=1800,
            execute_window_s=600,
            search_config=TemplateSearchConfig(method="nsga2", population_size=2, generations=1),
        )
    assert population_result.schedule.heavy_departures_s == [0, 600]
    assert population_result.schedule.empty_departures_s == [300, 900]
    dropped_score = next(
        score
        for template, score in population_result.ranked_candidates
        if template_key(template) == template_key(population_dropped_template)
    )
    assert dropped_score.feasible is False
    assert dropped_score.constraint_violation >= 3.0
    assert population_result.search_diagnostics["window_service_population"] == {
        "required_heavy_count": 2,
        "required_empty_count": 2,
        "selected_heavy_count": 2,
        "selected_empty_count": 2,
        "constraint": "candidate service population must match the base template within the prediction window",
    }

    # 候选生成前必须由滚动状态而不是过期模板起点限制储能偏移，否则在模板自身起点有效的模板，
    # 可能在当前活动窗口产生负发车时刻。
    stale_origin = ScheduleTemplate(
        900,
        900,
        0,
        1,
        1,
        start_time_s=1000,
        storage_align_shift_s=-1000,
    )
    with patch("rolling_optimizer.robust_evaluate_schedule", side_effect=_fake_robust_evaluate_schedule), patch(
        "rolling_optimizer.nsga2_template_search",
        side_effect=lambda base_template, search_config, evaluate_template: [
            (base_template, evaluate_template(base_template))
        ],
    ):
        normalized_result = optimizer.optimize_once(
            RollingWindowState(0, [], []),
            stale_origin,
            search_config=TemplateSearchConfig(method="nsga2", population_size=1, generations=1),
        )
    assert normalized_result.schedule.template.start_time_s == 0
    assert normalized_result.schedule.empty_departures_s == [0]

    string_state = RollingWindowState(
        current_time_s="0",
        locked_heavy_departures_s=["0"],
        locked_empty_departures_s=[],
        observed_heavy_delay_s="0",
        observed_empty_delay_s="0",
    )
    with patch("rolling_optimizer.robust_evaluate_schedule", side_effect=_fake_robust_evaluate_schedule), patch(
        "rolling_optimizer.explain_robust_scenarios", return_value=[]
    ), patch(
        "rolling_optimizer.nsga2_template_search",
        side_effect=lambda base_template, search_config, evaluate_template: [
            (base_template, evaluate_template(base_template))
        ],
    ):
        string_state_result = optimizer.optimize_once(
            string_state,
            base_template,
            search_config=TemplateSearchConfig(method="nsga2", population_size=1, generations=1),
        )
        cycle_results = run_mpc_cycles(
            optimizer,
            string_state,
            base_template,
            cycles=2,
            execute_window_s=600,
            search_config=TemplateSearchConfig(method="nsga2", population_size=1, generations=1),
        )
    assert string_state_result.schedule.template.start_time_s == 0
    assert string_state_result.schedule.heavy_departures_s.count(0) == 1
    assert len(cycle_results) == 2
    assert cycle_results[1].schedule.template.start_time_s == 600

    # 后续 MPC 周期不能移动已经执行的发车；延展也必须从第一列未来列车开始，
    # 不能从包含锁定历史的列表索引开始。
    rolling_schedule = GeneratedSchedule(
        heavy_departures_s=[0, 600, 900],
        empty_departures_s=[100, 700, 1000],
        template=base_template,
    )
    rolling_disturbed = apply_scenario(
        rolling_schedule,
        DisturbanceScenario(
            "future_only",
            heavy_delay_s=120,
            empty_delay_s=60,
            heavy_headway_stretch_s=30,
            empty_headway_stretch_s=20,
        ),
        disturbance_from_time_s=600,
        locked_heavy_departures_s=[600],
        locked_empty_departures_s=[700],
    )
    assert rolling_disturbed.heavy_departures_s == [0, 600, 1020]
    assert rolling_disturbed.empty_departures_s == [100, 700, 1060]

    # 锁定发车同时提交生成其历史能量的全轨迹策略。后续候选不能用另一个储能预设或空车停车策略重新评价该列车。
    committed_captures = []

    def _capture_committed_policy(schedule, *args, **kwargs):
        """函数 _capture_committed_policy：执行该模块中的相关处理逻辑。"""
        committed_captures.append(schedule.template)
        return _score(feasible=True, total_cost=1.0, worst_case_cost=1.0)

    competing_template = replace(
        base_template,
        flex_zone_hold_s=300,
        storage_preset_id="new_storage",
    )
    committed_state = RollingWindowState(
        current_time_s=600,
        locked_heavy_departures_s=[0],
        locked_empty_departures_s=[100],
        locked_empty_storage_hold_s=120,
        locked_storage_preset_id="installed_storage",
    )
    optimizer.storage_contexts["installed_storage"] = optimizer.storage_contexts[""]
    with patch(
        "rolling_optimizer.robust_evaluate_schedule",
        side_effect=_capture_committed_policy,
    ), patch(
        "rolling_optimizer.explain_robust_scenarios",
        return_value=[],
    ), patch(
        "rolling_optimizer.nsga2_template_search",
        side_effect=lambda _base, _config, evaluate_template: [
            (competing_template, evaluate_template(competing_template))
        ],
    ):
        committed_result = optimizer.optimize_once(
            committed_state,
            base_template,
            search_config=TemplateSearchConfig(
                method="nsga2",
                population_size=1,
                generations=1,
                enable_storage_preset_search=False,
            ),
        )
    assert committed_captures
    assert all(item.flex_zone_hold_s == 120 for item in committed_captures)
    assert all(item.storage_preset_id == "installed_storage" for item in committed_captures)
    assert committed_result.schedule.template.flex_zone_hold_s == 120
    assert committed_result.schedule.template.storage_preset_id == "installed_storage"
    assert all(
        template.flex_zone_hold_s == 120
        and template.storage_preset_id == "installed_storage"
        for template, _score_value in committed_result.ranked_candidates
    )

    # run_mpc_cycles 必须把第一轮可执行决策选定的策略带入下一滚动状态。
    class _PolicyProbeOptimizer:
        """类 _PolicyProbeOptimizer：执行该模块中的相关处理逻辑。"""
        default_storage_preset_id = "default_storage"

        def __init__(self):
            """函数 __init__：执行该模块中的相关处理逻辑。"""
            self.states = []

        def optimize_once(self, state, cycle_template, **_kwargs):
            """函数 optimize_once：执行该模块中的相关处理逻辑。"""
            self.states.append(state)
            selected = replace(
                cycle_template,
                start_time_s=state.current_time_s,
                flex_zone_hold_s=180,
                storage_preset_id="selected_storage",
            )
            schedule = GeneratedSchedule(
                heavy_departures_s=[state.current_time_s],
                empty_departures_s=[state.current_time_s],
                template=selected,
            )
            return SimpleNamespace(
                schedule=schedule,
                executable_heavy_departures_s=[state.current_time_s],
                executable_empty_departures_s=[state.current_time_s],
            )

    policy_probe = _PolicyProbeOptimizer()
    run_mpc_cycles(
        policy_probe,  # type: ignore[arg-type]
        RollingWindowState(0, [], []),
        base_template,
        cycles=2,
        execute_window_s=600,
    )
    assert policy_probe.states[1].locked_empty_storage_hold_s == 180
    assert policy_probe.states[1].locked_storage_preset_id == "selected_storage"

    for kwargs, expected_field in (
        ({"horizon_s": 0}, "horizon_s"),
        ({"execute_window_s": -1}, "execute_window_s"),
        ({"horizon_s": 600, "execute_window_s": 601}, "execute_window_s"),
    ):
        try:
            optimizer.optimize_once(
                RollingWindowState(0, [], []),
                base_template,
                search_config=TemplateSearchConfig(population_size=1, generations=1),
                **kwargs,
            )
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid rolling window was accepted: {kwargs!r}")

    for kwargs, expected_field in (
        ({"cycles": 0}, "cycles"),
        ({"horizon_s": 1.5}, "horizon_s"),
        ({"execute_window_s": 0}, "execute_window_s"),
        ({"horizon_s": 600, "execute_window_s": 601}, "execute_window_s"),
    ):
        try:
            run_mpc_cycles(
                optimizer,
                RollingWindowState(0, [], []),
                base_template,
                search_config=TemplateSearchConfig(population_size=1, generations=1),
                **kwargs,
            )
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid MPC configuration was accepted: {kwargs!r}")

    shifted = generate_schedule(ScheduleTemplate(3300, 2700, 2600, 3, 3, storage_align_shift_s=120))
    assert shifted.empty_departures_s == [2720, 5420, 8120]
    for invalid_template, expected_field in (
        (ScheduleTemplate(3300, 2700, 2600, -1, 3), "heavy_count"),
        (ScheduleTemplate(3300, 2700, 2600, 3, -1), "empty_count"),
    ):
        try:
            generate_schedule(invalid_template)
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"negative train count was silently accepted: {invalid_template}")
    diag = build_search_diagnostics(
        [
            (ScheduleTemplate(3300, 2700, 2600, 3, 3, storage_align_shift_s=0), _score(grid_kwh=10, wasted_kwh=20)),
            (ScheduleTemplate(3300, 2700, 2600, 3, 3, storage_align_shift_s=120), _score(grid_kwh=10, wasted_kwh=20)),
        ],
        TemplateSearchConfig(),
    )
    assert diag["storage_shift_span_s"] == 120
    assert diag["energy_flat"] is True

    print("rolling optimizer constraint-domination and Pareto dedup passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
