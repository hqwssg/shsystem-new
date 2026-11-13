# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import os
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data_ingestion import load_real_data_bundle
import scheduler_nsga2 as optimizer_module
from scheduler_nsga2 import (
    _power_cache_memo_key,
    _power_cache_memo_get,
    _power_cache_memo_store,
    build_power_cache,
    clear_power_cache_memo,
    power_cache_memo_stats,
)
from power_arm_electrical_limits import (
    load_power_arm_electrical_limits,
    load_storage_section_intervals,
)
from resource_constraints import crossing_elapsed_time_s
from operating_conditions import OperatingConditions, WeatherCondition
from train_simulator import (
    DavisCoefficients,
    RouteData,
    Segment,
    Station,
    TrainParameters,
    TrainSimulator,
    get_segment,
)


def _power_arm_csv(max_kw: int, storage_id: str, storage_end_km: int) -> str:
    """函数 _power_arm_csv：执行该模块中的相关处理逻辑。"""
    return (
        "section_id,power_arm_id,road,direction,start_km,end_km,max_traction_supply_kw,"
        "max_regen_absorption_kw,max_grid_feedback_kw,storage_available,storage_section_id,"
        "storage_start_km,storage_end_km\n"
        f"A1,A1,shuohuang,down,0,10,{max_kw},100,100,true,{storage_id},0,{storage_end_km}\n"
    )


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    clear_power_cache_memo()
    # 进程级缓存有容量上限，避免反复修改场景或线路时永久保留所有完整轨迹。
    # 在构造真实轨迹前，先用轻量哨兵测试淘汰和 LRU 提升。
    old_capacity = optimizer_module._POWER_CACHE_MEMO_MAX_ENTRIES
    try:
        optimizer_module._POWER_CACHE_MEMO_MAX_ENTRIES = 2
        _power_cache_memo_store(("lru", 1), "cache-1")
        _power_cache_memo_store(("lru", 2), "cache-2")
        if _power_cache_memo_get(("lru", 1)) != "cache-1":
            raise AssertionError("LRU cache failed to return a stored entry")
        _power_cache_memo_store(("lru", 3), "cache-3")
        if _power_cache_memo_get(("lru", 2)) is not None:
            raise AssertionError("LRU cache did not evict the least-recently-used entry")
        if optimizer_module.power_cache_memo_stats()["evictions"] != 1:
            raise AssertionError("LRU eviction counter is incorrect")
    finally:
        optimizer_module._POWER_CACHE_MEMO_MAX_ENTRIES = old_capacity
        clear_power_cache_memo()

    bundle = load_real_data_bundle(Path("data/real_shuohuang"))
    heavy = bundle.trains["Heavy"]
    route = bundle.route
    power_arm_path = Path("data/real_shuohuang/power_arm_intervals.csv")
    first = build_power_cache(heavy, route, power_arm_interval_path=power_arm_path)
    stats_after_first = power_cache_memo_stats()
    second = build_power_cache(heavy, route, power_arm_interval_path=power_arm_path)
    stats_after_second = power_cache_memo_stats()
    if first is not second:
        raise AssertionError("expected memoized PowerSeriesCache identity reuse")
    if stats_after_first["misses"] < 1:
        raise AssertionError(stats_after_first)
    if stats_after_second["hits"] < 1:
        raise AssertionError(stats_after_second)

    # 时间不变轨迹的站点穿越和储能首入结果应跨发车时刻复用。
    first._crossing_elapsed_cache.clear()
    first_crossing = crossing_elapsed_time_s(first, 100.0, 0)
    shifted_crossing = crossing_elapsed_time_s(first, 100.0, 600)
    if first_crossing != shifted_crossing or len(first._crossing_elapsed_cache) != 1:
        raise AssertionError("time-independent crossing lookup was not reused")
    first._first_storage_entry_cache.clear()
    first_storage_entry = first.first_storage_entry_elapsed_s(0)
    shifted_storage_entry = first.first_storage_entry_elapsed_s(600)
    if first_storage_entry != shifted_storage_entry or len(first._first_storage_entry_cache) != 1:
        raise AssertionError("time-independent storage-entry lookup was not reused")

    mixed_allocations = [
        allocations
        for allocations in first.power_allocation_ratios
        if len(allocations) > 1
    ]
    if not mixed_allocations:
        raise AssertionError("real long-train cache did not expose any cross-section samples")
    component_series = first.base_series_components()
    base_series = first.base_series()
    for time_s, base_sample in base_series.items():
        component_power = sum(
            float(series[time_s][0])
            for series in component_series
            if time_s in series
        )
        if abs(component_power - float(base_sample[0])) > 1e-9:
            raise AssertionError(
                f"cross-section allocation changed power at {time_s}: "
                f"{component_power} vs {base_sample[0]}"
            )

    explicit_sections = load_storage_section_intervals(power_arm_path)
    generator_cache = build_power_cache(
        heavy,
        route,
        power_arm_interval_path=power_arm_path,
        storage_sections=(section for section in explicit_sections),
    )
    if generator_cache.storage_sections != tuple(explicit_sections):
        raise AssertionError("storage-section generator was consumed before cache construction")
    expected_storage_ids = {section.storage_section_id for section in explicit_sections}
    actual_storage_ids = {
        storage_id
        for allocations in generator_cache.power_allocation_ratios
        for _, storage_id in allocations
        if storage_id
    }
    if expected_storage_ids and not actual_storage_ids.intersection(expected_storage_ids):
        raise AssertionError("storage-section generator produced no storage allocations")

    time_dependent_route = RouteData(
        total_length_km=10.0,
        max_speed_kmh=80.0,
        stations=[Station("A", 0.0), Station("B", 10.0)],
        segments=[Segment(0.0, 10.0, 0.0)],
        long_downhill_range_km=(0.0, 0.0),
        energy_transfer_ranges_km=[],
        signaling_system={},
        operating_conditions=OperatingConditions(
            weather_conditions=[
                WeatherCondition(
                    "timed-rain",
                    start_time_s=60,
                    end_time_s=120,
                    affected_ranges_km=[(0.0, 10.0)],
                    rolling_resistance_multiplier=1.1,
                )
            ]
        ),
    )
    time_dependent_train = TrainParameters(
        name="time-step-cache",
        mass_tons=1000.0,
        max_traction_kN=300.0,
        max_brake_kN=400.0,
        rotational_mass_factor=1.05,
        davis=DavisCoefficients(5.0, 0.1, 0.002),
        length_km=1.0,
        longitudinal_segments=5,
        max_power_kW=3000.0,
    )
    ten_second_cache = build_power_cache(
        time_dependent_train,
        time_dependent_route,
        simulation_step_s=10,
    )
    shifted_trajectory = ten_second_cache._trajectory_for_departure(60)
    if ten_second_cache.simulation_step_s != 10 or shifted_trajectory.simulation_step_s != 10:
        raise AssertionError("time-dependent departure silently changed the configured simulation step")
    if any(
        right - left != 10
        for left, right in zip(shifted_trajectory.times[:-1], shifted_trajectory.times[1:])
    ):
        raise AssertionError("time-dependent trajectory samples do not preserve the 10-second step")
    ten_second_cache._crossing_elapsed_cache.clear()
    crossing_elapsed_time_s(ten_second_cache, 5.0, 0)
    crossing_elapsed_time_s(ten_second_cache, 5.0, 60)
    if len(ten_second_cache._crossing_elapsed_cache) != 2:
        raise AssertionError("time-dependent crossing lookup ignored departure time")
    ten_second_cache._first_storage_entry_cache.clear()
    ten_second_cache.first_storage_entry_elapsed_s(0)
    ten_second_cache.first_storage_entry_elapsed_s(60)
    if len(ten_second_cache._first_storage_entry_cache) != 2:
        raise AssertionError("time-dependent storage-entry lookup ignored departure time")

    # 最后一个时间工况边界之后，规则集合已经固定，后续发车应复用同一条精确轨迹。
    post_condition_trajectory = ten_second_cache._trajectory_for_departure(121)
    later_post_condition_trajectory = ten_second_cache._trajectory_for_departure(180)
    if post_condition_trajectory is not later_post_condition_trajectory:
        raise AssertionError("trajectory after the last condition transition was simulated repeatedly")

    changed_davis = replace(heavy, davis=replace(heavy.davis, c=heavy.davis.c * 2.0))
    common_key_args = (
        route,
        0,
        False,
        5.0,
        power_arm_path,
        None,
    )
    if _power_cache_memo_key(heavy, *common_key_args) == _power_cache_memo_key(
        changed_davis,
        *common_key_args,
    ):
        raise AssertionError("Davis coefficient changes must invalidate the power-series cache")

    for constructor, expected_field in (
        (lambda: replace(heavy, mass_tons=0), "mass_tons"),
        (lambda: replace(heavy, direction="sideways"), "direction"),
        (lambda: replace(heavy, longitudinal_segments=1.5), "longitudinal_segments"),
        (lambda: DavisCoefficients(1.0, float("nan"), 1.0), "davis.b"),
        (lambda: replace(route, total_length_km=0), "total_length_km"),
    ):
        try:
            constructor()
        except ValueError as exc:
            if expected_field not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid physical model was accepted: {expected_field}")

    original_segment = route.segments[0]
    original_route_key = _power_cache_memo_key(heavy, *common_key_args)
    get_segment(route, original_segment.start_km)
    changed_segment = replace(
        original_segment,
        gradient_per_mille=original_segment.gradient_per_mille + 1.0,
    )
    route.segments[0] = changed_segment
    try:
        changed_route_key = _power_cache_memo_key(heavy, *common_key_args)
        if original_route_key == changed_route_key:
            raise AssertionError("route segment changes must invalidate the power-series cache")
        TrainSimulator(route, heavy)
        if get_segment(route, changed_segment.start_km).gradient_per_mille != changed_segment.gradient_per_mille:
            raise AssertionError("route segment index returned stale geometry after in-place mutation")
    finally:
        route.segments[0] = original_segment

    for kwargs, expected_field in (
        ({"start_time_s": 0.5}, "start_time_s"),
        ({"simulation_step_s": 0}, "simulation_step_s"),
        ({"simulation_step_s": float("nan")}, "simulation_step_s"),
    ):
        try:
            build_power_cache(heavy, route, power_arm_interval_path=power_arm_path, **kwargs)
        except ValueError as exc:
            if expected_field not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid power-cache timing was accepted: {kwargs!r}")

    for kwargs, expected_field in (
        ({"start_time_s": float("inf")}, "start_time_s"),
        ({"delta_t_s": 0.5}, "delta_t_s"),
    ):
        try:
            TrainSimulator(route, heavy, **kwargs)
        except ValueError as exc:
            if expected_field not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid simulator timing was accepted: {kwargs!r}")

    simulator = TrainSimulator(route, heavy)
    for max_time_s, expected_exception in (
        (float("nan"), ValueError),
        (1, RuntimeError),
    ):
        try:
            simulator.run(max_time_s=max_time_s)
        except expected_exception as exc:
            if "max_time_s" not in str(exc) and "did not reach" not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid or truncated simulation was accepted: {max_time_s!r}")

    with tempfile.TemporaryDirectory() as temp_dir:
        mutable_path = Path(temp_dir) / "power_arm_intervals.csv"
        mutable_path.write_text(_power_arm_csv(100, "S1", 5), encoding="utf-8")
        first_limits = load_power_arm_electrical_limits(mutable_path)
        first_sections = load_storage_section_intervals(mutable_path)
        first_file_key = _power_cache_memo_key(
            heavy, route, 0, False, 5.0, mutable_path, None
        )
        first_limits.clear()
        if load_power_arm_electrical_limits(mutable_path)["A1"].max_traction_supply_kw != 100.0:
            raise AssertionError("caller mutation contaminated cached electrical limits")

        old_stat = mutable_path.stat()
        mutable_path.write_text(_power_arm_csv(250, "S2", 8), encoding="utf-8")
        if mutable_path.stat().st_size != old_stat.st_size:
            raise AssertionError("same-size cache invalidation fixture unexpectedly changed size")
        os.utime(mutable_path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        second_limits = load_power_arm_electrical_limits(mutable_path)
        second_sections = load_storage_section_intervals(mutable_path)
        second_file_key = _power_cache_memo_key(
            heavy, route, 0, False, 5.0, mutable_path, None
        )
        if second_limits["A1"].max_traction_supply_kw != 250.0:
            raise AssertionError("overwritten electrical-limit file returned stale cached data")
        if first_sections[0].storage_section_id == second_sections[0].storage_section_id:
            raise AssertionError("overwritten storage geometry returned stale cached data")
        if first_file_key == second_file_key:
            raise AssertionError("power-series cache key ignored a changed power-arm file")
    print("power cache reuse verification passed", stats_after_second)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
