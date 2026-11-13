# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
from dataclasses import replace
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import run_ablation_experiments
import run_extended_experiments
from operating_conditions import (
    OperatingConditions,
    TemporarySpeedRestriction,
    adverse_weather_operating_conditions,
    speed_limit_kmh_at,
)
from rolling_optimizer import GeneratedSchedule, ScheduleTemplate
from run_engineering_solver_experiments import power_series_for_schedule as engineering_series
from run_extended_experiments import power_series_for_schedule as extended_series
from scheduler_nsga2 import PowerSeriesCache
from train_simulator import BatteryStorageParameters


def _split_cache() -> PowerSeriesCache:
    """函数 _split_cache：执行该模块中的相关处理逻辑。"""
    return PowerSeriesCache(
        times=[0, 10],
        powers_kW=[100.0, -40.0],
        energy_transfer_ratios=[0.25, 0.5],
        power_arm_ids=["A", "A"],
        positions_km=[1.0, 2.0],
        speeds_mps=[1.0, 1.0],
        train_length_km=1.0,
        direction="forward",
        adhesion_coefficients=[0.28, 0.28],
        speed_limits_mps=[33.3, 33.3],
        brake_decelerations_mps2=[0.3, 0.3],
        power_allocation_ratios=[
            {("A", "S"): 0.25, ("B", ""): 0.75},
            {("A", "S"): 0.5, ("B", ""): 0.5},
        ],
    )


def _held_empty_cache() -> PowerSeriesCache:
    """函数 _held_empty_cache：执行该模块中的相关处理逻辑。"""
    return PowerSeriesCache(
        times=[0, 10],
        powers_kW=[-40.0, 0.0],
        energy_transfer_ratios=[1.0, 1.0],
        power_arm_ids=["A", "A"],
        positions_km=[2.0, 1.0],
        speeds_mps=[1.0, 0.0],
        train_length_km=0.1,
        direction="reverse",
        adhesion_coefficients=[0.28, 0.28],
        speed_limits_mps=[33.3, 33.3],
        brake_decelerations_mps2=[0.3, 0.3],
        storage_section_ids=["S", "S"],
    )


def _assert_split_series(series) -> None:
    """函数 _assert_split_series：执行该模块中的相关处理逻辑。"""
    if len(series) != 2:
        raise AssertionError(f"expected two electrical components, got {len(series)}")
    for time_s, expected_power_kw in ((7, 100.0), (17, -40.0)):
        actual_power_kw = sum(
            float(component[time_s][0])
            for component in series
            if time_s in component
        )
        if abs(actual_power_kw - expected_power_kw) > 1e-9:
            raise AssertionError(
                f"component split changed power at {time_s}: "
                f"{actual_power_kw} vs {expected_power_kw}"
            )
    component_ids = {
        (str(sample[2]), str(sample[4]))
        for component in series
        for sample in component.values()
    }
    if component_ids != {("A", "S"), ("B", "")}:
        raise AssertionError(f"unexpected electrical components: {component_ids}")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    cache = _split_cache()
    schedule = GeneratedSchedule(
        heavy_departures_s=[7],
        empty_departures_s=[],
        template=ScheduleTemplate(100, 100, 0, 1, 0),
    )

    _assert_split_series(engineering_series(schedule, cache, cache, sample_step_s=10))
    _assert_split_series(extended_series(schedule, cache, cache, sample_step_s=10))

    train_marker = object()
    route_marker = object()
    storage_marker = object()
    configured_cache = replace(
        cache,
        train=train_marker,
        simulation_step_s=10,
        power_arm_interval_path=Path("custom_power_arms.csv"),
        storage_sections=(storage_marker,),
    )
    with patch.object(
        run_extended_experiments,
        "build_power_cache",
        return_value=configured_cache,
    ) as rebuild_probe:
        rebuilt = run_extended_experiments._rebuild_cache_for_route(
            configured_cache,
            route_marker,
        )
    if rebuilt is not configured_cache:
        raise AssertionError("physical-scenario cache rebuild returned an unexpected cache")
    rebuild_probe.assert_called_once_with(
        train_marker,
        route_marker,
        simulation_step_s=10,
        power_arm_interval_path=Path("custom_power_arms.csv"),
        storage_sections=(storage_marker,),
    )

    base_conditions = OperatingConditions(
        speed_restrictions=[
            TemporarySpeedRestriction(
                "official-limit",
                0.0,
                300.0,
                75.0,
            )
        ]
    )
    adverse_conditions = adverse_weather_operating_conditions()
    merged_conditions = run_extended_experiments._merge_operating_conditions(
        base_conditions,
        adverse_conditions,
    )
    if len(merged_conditions.speed_restrictions) != (
        len(base_conditions.speed_restrictions)
        + len(adverse_conditions.speed_restrictions)
    ):
        raise AssertionError("adverse-weather scenario discarded baseline speed restrictions")
    merged_limit = speed_limit_kmh_at(merged_conditions, 120.0, 70.0, 3600)
    if abs(merged_limit - 75.0) > 1e-9:
        raise AssertionError(
            f"adverse-weather overlay relaxed the official 75 km/h limit to {merged_limit}"
        )

    held_schedule = GeneratedSchedule(
        heavy_departures_s=[],
        empty_departures_s=[7],
        template=ScheduleTemplate(100, 100, 0, 0, 1, flex_zone_hold_s=5),
    )
    held_cache = _held_empty_cache()
    for label, builder in (
        ("engineering", engineering_series),
        ("extended", extended_series),
    ):
        held_series = builder(held_schedule, held_cache, held_cache, sample_step_s=10)
        if [sorted(component) for component in held_series] != [[12, 22]]:
            raise AssertionError(f"{label} report ignored flex-zone hold: {held_series}")

    captured = {}
    settlement_result = object()

    class _SettlementProbe:
        """类 _SettlementProbe：执行该模块中的相关处理逻辑。"""
        def __init__(self, *args, **kwargs):
            """函数 __init__：执行该模块中的相关处理逻辑。"""
            pass

        def settle(self, series):
            """函数 settle：执行该模块中的相关处理逻辑。"""
            captured["series"] = series
            return settlement_result

    battery = BatteryStorageParameters(
        capacity_kwh=100.0,
        round_trip_efficiency=0.9,
        depreciation_cost_per_kwh=0.1,
        grid_price_per_kwh=0.5,
        max_charge_power_kW=50.0,
        max_discharge_power_kW=50.0,
    )
    with patch.object(run_ablation_experiments, "EnergySettlementSystem", _SettlementProbe):
        result = run_ablation_experiments.precise_settlement(
            schedule,
            cache,
            cache,
            battery,
            [],
        )
    if result is not settlement_result:
        raise AssertionError("ablation settlement did not return the settlement result")
    _assert_split_series(captured["series"])

    captured.clear()
    with patch.object(run_ablation_experiments, "EnergySettlementSystem", _SettlementProbe):
        run_ablation_experiments.precise_settlement(
            held_schedule,
            held_cache,
            held_cache,
            battery,
            [],
        )
    if [sorted(component) for component in captured["series"]] != [[12, 22]]:
        raise AssertionError("ablation report ignored flex-zone hold")

    print("experiment entry power-series splitting verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
