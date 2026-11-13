# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import resource_constraints as resource_module
from data_ingestion import load_real_data_bundle
from power_arm_electrical_limits import StorageSectionInterval
from resource_constraints import (
    ResourceConfig,
    ResourceModel,
    build_resource_intervals,
    check_schedule_resources,
    detect_overtaking_conflicts,
)
from rolling_optimizer import GeneratedSchedule, ScheduleTemplate, generate_schedule
from scheduler_nsga2 import PowerSeriesCache
from time_space_network import (
    _whole_departure_time,
    build_time_space_network,
    network_arc_rows,
    network_node_rows,
    network_path_rows,
)


def _lightweight_cache(train, direction: str) -> PowerSeriesCache:
    """函数 _lightweight_cache：执行该模块中的相关处理逻辑。"""
    times = list(range(0, 3601, 60))
    if direction == "forward":
        positions = [583.003 * idx / (len(times) - 1) for idx, _ in enumerate(times)]
    else:
        positions = [583.003 * (1.0 - idx / (len(times) - 1)) for idx, _ in enumerate(times)]
    powers = [3500.0 if idx < len(times) // 2 else -1200.0 for idx, _ in enumerate(times)]
    return PowerSeriesCache(
        times=times,
        powers_kW=powers,
        energy_transfer_ratios=[0.0 if power >= 0 else 0.65 for power in powers],
        power_arm_ids=["smoke_power_arm"] * len(times),
        positions_km=positions,
        speeds_mps=[20.0] * len(times),
        train_length_km=train.length_km,
        direction=direction,
        adhesion_coefficients=[0.28] * len(times),
        speed_limits_mps=[33.3] * len(times),
        brake_decelerations_mps2=[0.3] * len(times),
    )


def _verify_intermediate_operation_delay(direction: str) -> None:
    """函数 _verify_intermediate_operation_delay：执行该模块中的相关处理逻辑。"""
    stations = tuple(
        SimpleNamespace(name=f"S{index}", position_km=float(index))
        for index in range(3)
    )
    positions = [0.0, 1.0, 2.0] if direction == "forward" else [2.0, 1.0, 0.0]
    cache = PowerSeriesCache(
        times=[0, 10, 20],
        powers_kW=[100.0, 200.0, 0.0],
        energy_transfer_ratios=[0.0, 0.0, 0.0],
        power_arm_ids=["", "", ""],
        positions_km=positions,
        speeds_mps=[1.0, 1.0, 0.0],
        train_length_km=0.1,
        direction=direction,
        adhesion_coefficients=[0.28, 0.28, 0.28],
        speed_limits_mps=[33.3, 33.3, 33.3],
        brake_decelerations_mps2=[0.3, 0.3, 0.3],
    )
    model = ResourceModel(
        stations=stations,
        config=ResourceConfig(),
        station_operation_assignments=(
            {"station_name": "S1", "applies_to": "all", "min_occupancy_s": 20},
        ),
    )
    schedule = GeneratedSchedule(
        heavy_departures_s=[0],
        empty_departures_s=[],
        template=ScheduleTemplate(100, 100, 0, 1, 0),
    )
    network = build_time_space_network(schedule, model, cache, cache, storage_sections=())
    if any(arc.end_time_s < arc.start_time_s for arc in network.arcs):
        raise AssertionError("intermediate operation produced a backward time-space arc")
    outbound = next(
        arc
        for arc in network.arcs
        if arc.arc_type == "running"
        and abs(arc.start_km - 1.0) < 1e-9
    )
    if (outbound.start_time_s, outbound.end_time_s) != (30.0, 40.0):
        raise AssertionError(f"operation delay was not propagated downstream: {outbound}")

    resource_intervals = build_resource_intervals(schedule, model, cache, cache)
    outbound_resource_id = (
        "section:1:forward" if direction == "forward" else "section:0:reverse"
    )
    outbound_interval = next(
        interval
        for interval in resource_intervals
        if interval.resource_id == outbound_resource_id
    )
    if outbound_interval.start_time_s != 30.0:
        raise AssertionError(
            f"resource section entered before operation completion: {outbound_interval}"
        )

    overtaking_model = ResourceModel(
        stations=stations,
        config=ResourceConfig(),
        station_operation_assignments=(
            {
                "station_name": "S1",
                "train_type": "Heavy",
                "applies_to": "all",
                "min_occupancy_s": 20,
            },
        ),
    )
    overtaking_schedule = GeneratedSchedule(
        heavy_departures_s=[0],
        empty_departures_s=[5],
        template=ScheduleTemplate(100, 100, 0, 1, 1),
    )
    overtaking = detect_overtaking_conflicts(
        overtaking_schedule,
        overtaking_model,
        cache,
        cache,
    )
    if not any(conflict.conflict_type == "overtaking_without_passing_track" for conflict in overtaking):
        raise AssertionError("overtaking detector ignored an intermediate operation delay")

    shared_model = replace(
        model,
        # 仅覆盖被测区段的边缘；只检查中点会漏掉这段具有正长度的单线重叠。
        config=replace(
            model.config,
            single_line_ranges_km=(
                ((1.0, 1.1),) if direction == "forward" else ((0.0, 0.1),)
            ),
        ),
    )
    shared_network = build_time_space_network(
        schedule,
        shared_model,
        cache,
        cache,
        storage_sections=(),
    )
    expected_section_index = 1 if direction == "forward" else 0
    if not any(
        arc.arc_type == "running"
        and arc.capacity_resource_id == f"section:{expected_section_index}:shared"
        for arc in shared_network.arcs
    ):
        raise AssertionError("single-line network arc did not use the shared resource ID")

    terminal_model = ResourceModel(
        stations=stations,
        config=ResourceConfig(),
        station_operation_assignments=(
            {
                "station_name": stations[-1].name if direction == "forward" else stations[0].name,
                "applies_to": "all",
                "min_occupancy_s": 60,
            },
        ),
    )
    terminal_network = build_time_space_network(
        schedule,
        terminal_model,
        cache,
        cache,
        storage_sections=(),
    )
    terminal_path = terminal_network.train_paths[0]
    if terminal_path.arrival_time_s != 20.0:
        raise AssertionError(
            f"terminal technical work changed the mainline arrival time: {terminal_path}"
        )
    if terminal_path.completion_time_s != 80.0:
        raise AssertionError(
            f"terminal technical-work completion was not retained separately: {terminal_path}"
        )
    terminal_row = network_path_rows(terminal_network)[0]
    if terminal_row["arrival_time_s"] != 20.0 or terminal_row["completion_time_s"] != 80.0:
        raise AssertionError(f"time-space path export conflated arrival and completion: {terminal_row}")


def _verify_intermediate_overtaking_is_detected() -> None:
    """函数 _verify_intermediate_overtaking_is_detected：执行该模块中的相关处理逻辑。"""
    stations = tuple(
        SimpleNamespace(name=f"S{index}", position_km=float(index))
        for index in range(3)
    )
    base_kwargs = {
        "times": [0, 10, 20],
        "powers_kW": [0.0, 0.0, 0.0],
        "energy_transfer_ratios": [0.0, 0.0, 0.0],
        "power_arm_ids": ["", "", ""],
        "speeds_mps": [1.0, 1.0, 0.0],
        "train_length_km": 0.1,
        "direction": "forward",
        "adhesion_coefficients": [0.28, 0.28, 0.28],
        "speed_limits_mps": [33.3, 33.3, 33.3],
        "brake_decelerations_mps2": [0.3, 0.3, 0.3],
    }
    earlier_train = PowerSeriesCache(
        **base_kwargs,
        positions_km=[0.0, 0.5, 2.0],
    )
    later_train = PowerSeriesCache(
        **base_kwargs,
        positions_km=[0.0, 1.5, 2.0],
    )
    schedule = GeneratedSchedule(
        heavy_departures_s=[0],
        empty_departures_s=[5],
        template=ScheduleTemplate(100, 100, 5, 1, 1),
    )
    conflicts = detect_overtaking_conflicts(
        schedule,
        ResourceModel(stations=stations, config=ResourceConfig()),
        earlier_train,
        later_train,
    )
    if not conflicts:
        raise AssertionError(
            "intermediate overtaking was missed because terminal order was restored"
        )
    if conflicts[0].location_km != "1.0 km":
        raise AssertionError(conflicts[0])


def _verify_station_departure_reversal_is_detected() -> None:
    """函数 _verify_station_departure_reversal_is_detected：执行该模块中的相关处理逻辑。"""
    stations = tuple(
        SimpleNamespace(name=f"S{index}", position_km=float(index))
        for index in range(3)
    )
    common = {
        "powers_kW": [0.0, 0.0, 0.0],
        "energy_transfer_ratios": [0.0, 0.0, 0.0],
        "power_arm_ids": ["", "", ""],
        "positions_km": [0.0, 1.0, 2.0],
        "speeds_mps": [1.0, 1.0, 0.0],
        "train_length_km": 0.1,
        "direction": "forward",
        "adhesion_coefficients": [0.28, 0.28, 0.28],
        "speed_limits_mps": [33.3, 33.3, 33.3],
        "brake_decelerations_mps2": [0.3, 0.3, 0.3],
    }
    earlier_train = PowerSeriesCache(times=[0, 10, 20], **common)
    later_train = PowerSeriesCache(times=[0, 15, 40], **common)
    model = ResourceModel(
        stations=stations,
        config=ResourceConfig(),
        station_operation_assignments=(
            {
                "station_name": "S1",
                "train_type": "Heavy",
                "applies_to": "all",
                "min_occupancy_s": 20,
            },
        ),
    )
    schedule = GeneratedSchedule(
        heavy_departures_s=[0],
        empty_departures_s=[5],
        template=ScheduleTemplate(100, 100, 5, 1, 1),
    )
    conflicts = detect_overtaking_conflicts(
        schedule,
        model,
        earlier_train,
        later_train,
    )
    if not conflicts or conflicts[0].location_km != "1.0 km":
        raise AssertionError(
            "Station departure-order reversal was missed when terminal arrival order was restored"
        )


def _verify_storage_hold_propagates_to_resources() -> None:
    """函数 _verify_storage_hold_propagates_to_resources：执行该模块中的相关处理逻辑。"""
    stations = (
        SimpleNamespace(name="S0", position_km=0.0),
        SimpleNamespace(name="S1", position_km=2.0),
    )
    cache = PowerSeriesCache(
        times=[0, 10, 20],
        powers_kW=[0.0, 100.0, 0.0],
        energy_transfer_ratios=[0.0, 1.0, 1.0],
        power_arm_ids=["A", "A", "A"],
        positions_km=[0.0, 1.0, 2.0],
        speeds_mps=[1.0, 1.0, 0.0],
        train_length_km=0.1,
        direction="forward",
        adhesion_coefficients=[0.28, 0.28, 0.28],
        speed_limits_mps=[33.3, 33.3, 33.3],
        brake_decelerations_mps2=[0.3, 0.3, 0.3],
        storage_section_ids=["", "STORAGE", "STORAGE"],
        power_allocation_ratios=[
            {("A", ""): 1.0},
            {("A", "STORAGE"): 1.0},
            {("A", "STORAGE"): 1.0},
        ],
    )
    model = ResourceModel(stations=stations, config=ResourceConfig())
    base_schedule = GeneratedSchedule(
        heavy_departures_s=[],
        empty_departures_s=[0],
        template=ScheduleTemplate(100, 100, 0, 0, 1, flex_zone_hold_s=0),
    )
    held_schedule = GeneratedSchedule(
        heavy_departures_s=[],
        empty_departures_s=[0],
        template=ScheduleTemplate(100, 100, 0, 0, 1, flex_zone_hold_s=5),
    )
    base_network = build_time_space_network(
        base_schedule,
        model,
        cache,
        cache,
        storage_sections=(),
    )
    held_network = build_time_space_network(
        held_schedule,
        model,
        cache,
        cache,
        storage_sections=(),
    )
    if held_network.train_paths[0].arrival_time_s - base_network.train_paths[0].arrival_time_s != 5.0:
        raise AssertionError("storage hold did not delay the time-space path")
    base_section = next(
        item for item in build_resource_intervals(base_schedule, model, cache, cache)
        if item.resource_type == "section"
    )
    held_section = next(
        item for item in build_resource_intervals(held_schedule, model, cache, cache)
        if item.resource_type == "section"
    )
    if held_section.end_time_s - base_section.end_time_s != 5.0:
        raise AssertionError("storage hold did not extend downstream resource occupancy")


def _verify_departure_specific_trajectory_drives_arc_energy() -> None:
    """函数 _verify_departure_specific_trajectory_drives_arc_energy：执行该模块中的相关处理逻辑。"""
    stations = (
        SimpleNamespace(name="S0", position_km=0.0),
        SimpleNamespace(name="S1", position_km=1.0),
    )
    common = {
        "times": [0, 10],
        "energy_transfer_ratios": [0.0, 0.0],
        "power_arm_ids": ["A", "A"],
        "positions_km": [0.0, 1.0],
        "speeds_mps": [1.0, 0.0],
        "train_length_km": 0.1,
        "direction": "forward",
        "adhesion_coefficients": [0.28, 0.28],
        "speed_limits_mps": [33.3, 33.3],
        "brake_decelerations_mps2": [0.3, 0.3],
    }
    base_cache = PowerSeriesCache(
        powers_kW=[100.0, 0.0],
        time_dependent_conditions=True,
        **common,
    )
    departure_cache = PowerSeriesCache(
        powers_kW=[300.0, 0.0],
        **common,
    )
    schedule = GeneratedSchedule(
        heavy_departures_s=[100],
        empty_departures_s=[],
        template=ScheduleTemplate(100, 100, 0, 1, 0),
    )
    original_resolver = PowerSeriesCache._trajectory_for_departure

    def resolve(cache, depart_time_s):
        """函数 resolve：执行该模块中的相关处理逻辑。"""
        if cache is base_cache and depart_time_s == 100:
            return departure_cache
        return original_resolver(cache, depart_time_s)

    with patch.object(PowerSeriesCache, "_trajectory_for_departure", resolve):
        network = build_time_space_network(
            schedule,
            ResourceModel(stations=stations, config=ResourceConfig()),
            base_cache,
            base_cache,
            storage_sections=(),
        )
    running_energy_kwh = sum(
        arc.energy_kwh for arc in network.arcs if arc.arc_type == "running"
    )
    expected_kwh = 300.0 * 10.0 / 3600.0
    if abs(running_energy_kwh - expected_kwh) > 1e-12:
        raise AssertionError(
            "time-space arc energy ignored the departure-specific trajectory: "
            f"{running_energy_kwh} vs {expected_kwh}"
        )


def _verify_resource_interval_cache_reuses_only_unchanged_trains(
    model,
    heavy_cache,
    empty_cache,
) -> None:
    """缓存结果必须等价，且发车变化时只能失效对应列车。"""

    schedule = generate_schedule(ScheduleTemplate(600, 600, 300, 2, 2))
    interval_cache = {}
    original_builder = resource_module._run_station_timings
    with patch.object(
        resource_module,
        "_run_station_timings",
        wraps=original_builder,
    ) as timing_builder:
        first = build_resource_intervals(
            schedule,
            model,
            heavy_cache,
            empty_cache,
            interval_cache,
        )
        first_call_count = timing_builder.call_count
        second = build_resource_intervals(
            schedule,
            model,
            heavy_cache,
            empty_cache,
            interval_cache,
        )
        second_call_count = timing_builder.call_count
        changed_schedule = replace(
            schedule,
            heavy_departures_s=[schedule.heavy_departures_s[0] + 30, schedule.heavy_departures_s[1]],
        )
        changed_cached = build_resource_intervals(
            changed_schedule,
            model,
            heavy_cache,
            empty_cache,
            interval_cache,
        )
        changed_call_count = timing_builder.call_count

    changed_uncached = build_resource_intervals(
        changed_schedule,
        model,
        heavy_cache,
        empty_cache,
    )
    if first != second or changed_cached != changed_uncached:
        raise AssertionError("资源区间缓存改变了区间内容或排序")
    if first_call_count != 4 or second_call_count != first_call_count:
        raise AssertionError("相同运行图没有完整复用四列车资源区间")
    if changed_call_count != first_call_count + 1:
        raise AssertionError("单列车发车变化未按列车粒度失效缓存")


def _verify_resource_check_reuses_station_timings(
    model,
    heavy_cache,
    empty_cache,
) -> None:
    """完整资源检查的三个子流程必须共用每列车一次的站点时刻计算。"""

    schedule = generate_schedule(ScheduleTemplate(600, 600, 300, 2, 2))
    original_builder = resource_module._run_station_timings
    with patch.object(
        resource_module,
        "_run_station_timings",
        wraps=original_builder,
    ) as timing_builder:
        result = check_schedule_resources(
            schedule,
            model,
            heavy_cache,
            empty_cache,
        )
    if not result.intervals:
        raise AssertionError("完整资源检查没有生成资源区间")
    if timing_builder.call_count != 4:
        raise AssertionError(
            "资源区间、越行和流连续性检查重复计算了列车站点时刻："
            f"实际调用 {timing_builder.call_count} 次，期望 4 次"
        )


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    try:
        _whole_departure_time(True)
    except ValueError:
        pass
    else:
        raise AssertionError("boolean departure time was accepted as one second")
    _verify_intermediate_operation_delay("forward")
    _verify_intermediate_operation_delay("reverse")
    _verify_intermediate_overtaking_is_detected()
    _verify_station_departure_reversal_is_detected()
    _verify_storage_hold_propagates_to_resources()
    _verify_departure_specific_trajectory_drives_arc_energy()
    bundle = load_real_data_bundle(Path("data") / "real_shuohuang")
    heavy_cache = _lightweight_cache(bundle.trains["Heavy"], "forward")
    empty_cache = _lightweight_cache(bundle.trains["Empty"], "reverse")
    schedule = generate_schedule(
        ScheduleTemplate(
            heavy_headway_s=bundle.resource_model.config.min_depart_headway_s,
            empty_headway_s=bundle.resource_model.config.min_depart_headway_s,
            heavy_empty_phase_s=bundle.resource_model.config.min_depart_headway_s,
            heavy_count=1,
            empty_count=1,
        )
    )
    _verify_resource_interval_cache_reuses_only_unchanged_trains(
        bundle.resource_model,
        heavy_cache,
        empty_cache,
    )
    _verify_resource_check_reuses_station_timings(
        bundle.resource_model,
        heavy_cache,
        empty_cache,
    )

    network = build_time_space_network(schedule, bundle.resource_model, heavy_cache, empty_cache)
    assert network.node_count > 0
    assert network.arc_count > 0
    assert len(network.train_paths) == 2
    assert any(arc.arc_type == "running" for arc in network.arcs)
    arc_types = network.arc_type_counts()
    assert any(arc_type in arc_types for arc_type in ("loading", "unloading", "loading_unloading"))
    assert "spotting" in arc_types
    assert "pickup" in arc_types
    assert "virtual_trainset" in arc_types
    assert "dismantling" in arc_types
    running_arcs = [arc for arc in network.arcs if arc.arc_type == "running"]
    for boundary_km in (145.0, 164.0, 200.7):
        assert any(
            abs(arc.start_km - boundary_km) < 1e-6 or abs(arc.end_km - boundary_km) < 1e-6
            for arc in running_arcs
        ), f"storage boundary K{boundary_km:g} was not used to split running arcs"
    assert any(arc.storage_section_id.startswith("storage_section_1") for arc in running_arcs)
    assert any(arc.storage_section_id.startswith("storage_section_2") for arc in running_arcs)
    assert all(
        not (min(arc.start_km, arc.end_km) < boundary_km < max(arc.start_km, arc.end_km))
        for arc in running_arcs
        for boundary_km in (145.0, 164.0, 200.7)
    )
    assert len(network_node_rows(network)) == network.node_count
    assert len(network_arc_rows(network)) == network.arc_count
    assert len(network_path_rows(network)) == len(network.train_paths)

    custom_boundaries = (111.1, 123.4)
    custom_network = build_time_space_network(
        schedule,
        bundle.resource_model,
        heavy_cache,
        empty_cache,
        (StorageSectionInterval("CUSTOM_STORAGE", *custom_boundaries),),
    )
    custom_running_arcs = [arc for arc in custom_network.arcs if arc.arc_type == "running"]
    for boundary_km in custom_boundaries:
        assert any(
            abs(arc.start_km - boundary_km) < 1e-6 or abs(arc.end_km - boundary_km) < 1e-6
            for arc in custom_running_arcs
        )
    assert any(arc.storage_section_id == "CUSTOM_STORAGE" for arc in custom_running_arcs)
    assert all(
        not any(abs(value - legacy) < 1e-6 for legacy in (145.0, 164.0, 200.7))
        for arc in custom_running_arcs
        for value in (arc.start_km, arc.end_km)
    )

    print("time-space network verification passed")
    print("nodes:", network.node_count)
    print("arcs:", network.arc_count)
    print("arc types:", network.arc_type_counts())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
