# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import csv
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data_ingestion import load_real_data_bundle
from run_dispatch_case import (
    ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    _trajectory_plot_points,
    apply_battery_scenario,
    make_settlement_system,
    plot_timetable,
    settle_schedule,
    train_rows,
)
from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from rolling_optimizer import GeneratedSchedule, ScheduleTemplate, evaluate_schedule, generate_schedule
from scheduler_nsga2 import PowerSeriesCache
from timetable_energy_audit import audit_timetable, _effective_time_step_s, evaluate_scenario_time_slices
from timetable_input import TimetableScenario
from train_simulator import BatteryStorageParameters
from unittest.mock import patch

import openpyxl


def _lightweight_cache(train, direction: str) -> PowerSeriesCache:
    """函数 _lightweight_cache：执行该模块中的相关处理逻辑。"""
    times = list(range(0, 3601, 60))
    if direction == "forward":
        positions = [583.003 * idx / (len(times) - 1) for idx, _ in enumerate(times)]
        powers = [3500.0] * len(times)
    else:
        positions = [583.003 * (1.0 - idx / (len(times) - 1)) for idx, _ in enumerate(times)]
        powers = [-1800.0] * len(times)
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


def _assert_energy_conservation() -> None:
    """函数 _assert_energy_conservation：执行该模块中的相关处理逻辑。"""
    bundle = load_real_data_bundle(Path("data") / "real_shuohuang")
    cache = _lightweight_cache(bundle.trains["Heavy"], "forward")
    system = make_settlement_system(
        bundle.battery,
        bundle.route,
        settlement_step_s=30,
        initial_soc_kwh=0.0,
        target_final_soc_kwh=None,
        final_soc_tolerance_kwh=0.0,
        final_soc_penalty_per_kwh=0.0,
        wasted_energy_penalty_per_kwh=0.0,
        energy_scenario=ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    )
    result = system.settle([cache.shifted(0, sample_step_s=30)])
    # 必须包含最后一个样本；末尾零时长样本曾造成能量少计。
    series = cache.base_series(sample_step_s=30)
    expected = sum(float(sample[0]) * float(sample[3]) / 3600.0 for sample in series.values())
    actual_net = result.total_con_kwh - result.total_gen_kwh
    if abs(actual_net - expected) > 1e-6:
        raise AssertionError(f"Energy integration mismatch: expected {expected}, got {actual_net}")


def _assert_cli_zero_efficiency_override_disables_storage() -> None:
    """函数 _assert_cli_zero_efficiency_override_disables_storage：执行该模块中的相关处理逻辑。"""
    base = BatteryStorageParameters(
        capacity_kwh=10.0,
        round_trip_efficiency=0.9,
        depreciation_cost_per_kwh=0.0,
        grid_price_per_kwh=0.0,
        max_charge_power_kW=10000.0,
        max_discharge_power_kW=10000.0,
    )
    disabled = apply_battery_scenario(
        base,
        capacity_kwh=None,
        max_charge_power_kW=None,
        max_discharge_power_kW=None,
        round_trip_efficiency=0.0,
    )
    if disabled.round_trip_efficiency != 0.0:
        raise AssertionError("CLI battery override did not preserve zero efficiency")
    system = EnergySettlementSystem(
        battery=disabled,
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={
            "A": PowerArmElectricalLimit(
                max_traction_supply_kw=10000.0,
                max_regen_absorption_kw=10000.0,
                storage_available=True,
                storage_section_id="S",
            )
        },
    )
    result = system.settle([{0: (-3600.0, 1.0, "A", 10.0, "S")}])
    if result.battery_charge_kwh != 0.0 or result.battery_discharge_kwh != 0.0:
        raise AssertionError(
            "zero-efficiency CLI override still exchanged energy with storage: "
            f"charge={result.battery_charge_kwh}, discharge={result.battery_discharge_kwh}"
        )
    if abs(result.wasted_kwh - 10.0) > 1e-9:
        raise AssertionError(
            f"zero-efficiency CLI override did not expose regen as waste: {result.wasted_kwh}"
        )




def _assert_storage_tags_work_without_limit_table() -> None:
    """Samples already tagged with storage sections must still charge.

    Electrical-limit lookup tables may be empty in unit tests or degraded
    call sites. Storage eligibility then comes from the sample tag itself.
    """

    bundle = load_real_data_bundle(Path("data") / "real_shuohuang")
    cache = PowerSeriesCache(
        times=[0, 10, 20, 30],
        powers_kW=[-3600.0, -3600.0, 1800.0, 0.0],
        energy_transfer_ratios=[1.0, 1.0, 1.0, 1.0],
        power_arm_ids=["arm_storage", "arm_storage", "arm_storage", "arm_storage"],
        positions_km=[150.0, 151.0, 152.0, 153.0],
        speeds_mps=[20.0, 20.0, 20.0, 20.0],
        train_length_km=1.0,
        direction="forward",
        adhesion_coefficients=[0.28, 0.28, 0.28, 0.28],
        speed_limits_mps=[33.3, 33.3, 33.3, 33.3],
        brake_decelerations_mps2=[0.3, 0.3, 0.3, 0.3],
        storage_section_ids=[
            "storage_section_1:K145-K164",
            "storage_section_1:K145-K164",
            "storage_section_1:K145-K164",
            "storage_section_1:K145-K164",
        ],
    )
    # The received document omits discharge power, so the operational bundle
    # intentionally uses 0 kW.  This unit test exercises bidirectional storage
    # mechanics and therefore applies the explicit planning assumption.
    bidirectional_battery = BatteryStorageParameters(
        capacity_kwh=bundle.battery.capacity_kwh,
        round_trip_efficiency=bundle.battery.round_trip_efficiency,
        depreciation_cost_per_kwh=bundle.battery.depreciation_cost_per_kwh,
        grid_price_per_kwh=bundle.battery.grid_price_per_kwh,
        max_charge_power_kW=bundle.battery.max_charge_power_kW,
        max_discharge_power_kW=2000.0,
        planning_assumption=True,
        note="测试储能双向行为所用显式放电功率假设。",
    )
    system = EnergySettlementSystem(
        bidirectional_battery,
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={},
    )
    result = system.settle([cache.shifted(0, sample_step_s=10)])
    if result.battery_charge_kwh <= 0.0:
        raise AssertionError(
            "Tagged storage samples produced no charge under empty power_arm_limits"
        )
    if abs(result.direct_used_kwh) > 1e-9:
        raise AssertionError("Direct use should remain disabled for storage_no_direct-like settle")
    if result.battery_discharge_kwh <= 0.0:
        raise AssertionError("Tagged storage samples should allow later discharge under empty limits")


def _assert_five_second_power_integration() -> None:
    """函数 _assert_five_second_power_integration：执行该模块中的相关处理逻辑。"""
    bundle = load_real_data_bundle(Path("data") / "real_shuohuang")
    cache = PowerSeriesCache(
        times=[0, 5, 10],
        powers_kW=[3600.0, -1800.0, 0.0],
        energy_transfer_ratios=[1.0, 1.0, 1.0],
        power_arm_ids=["", "", ""],
        positions_km=[0.0, 0.1, 0.2],
        speeds_mps=[20.0, 20.0, 20.0],
        train_length_km=1.0,
        direction="forward",
        adhesion_coefficients=[0.28, 0.28, 0.28],
        speed_limits_mps=[33.3, 33.3, 33.3],
        brake_decelerations_mps2=[0.3, 0.3, 0.3],
    )
    system = EnergySettlementSystem(
        bundle.battery,
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=False,
        power_arm_limits={},
    )
    result = system.settle([cache.shifted(0, sample_step_s=10)])
    expected_con_kwh = 3600.0 * 5.0 / 3600.0
    expected_gen_kwh = 1800.0 * 5.0 / 3600.0
    if abs(result.total_con_kwh - expected_con_kwh) > 1e-9:
        raise AssertionError(f"5-second traction integration mismatch: {result.total_con_kwh}")
    if abs(result.total_gen_kwh - expected_gen_kwh) > 1e-9:
        raise AssertionError(f"5-second regeneration integration mismatch: {result.total_gen_kwh}")
    if abs(result.total_gen_kwh - result.direct_used_kwh - result.battery_charge_kwh - result.wasted_kwh) > 1e-9:
        raise AssertionError("Regenerative-side energy conservation failed")
    if abs(result.total_con_kwh - result.direct_used_kwh - result.battery_discharge_kwh - result.grid_kwh) > 1e-9:
        raise AssertionError("Traction-side energy conservation failed")


def _assert_cross_bin_sample_splitting() -> None:
    """函数 _assert_cross_bin_sample_splitting：执行该模块中的相关处理逻辑。"""
    bundle = load_real_data_bundle(Path("data") / "real_shuohuang")
    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=100000.0,
        max_regen_absorption_kw=100000.0,
    )
    system = EnergySettlementSystem(
        bundle.battery,
        settlement_time_step_s=10,
        allow_direct_use=True,
        allow_storage=False,
        power_arm_limits={"arm_a": limit},
    )
    result = system.settle(
        [
            {8: (-3600.0, 1.0, "arm_a", 5.0, "")},
            {10: (3600.0, 1.0, "arm_a", 5.0, "")},
        ]
    )
    expected = {
        "total_gen_kwh": 5.0,
        "total_con_kwh": 5.0,
        "direct_used_kwh": 3.0,
        "wasted_kwh": 2.0,
        "grid_kwh": 2.0,
    }
    for name, expected_value in expected.items():
        actual = getattr(result, name)
        if abs(actual - expected_value) > 1e-9:
            raise AssertionError(f"Cross-bin sample split mismatch for {name}: {actual} != {expected_value}")


def _assert_storage_sections_are_independent() -> None:
    """函数 _assert_storage_sections_are_independent：执行该模块中的相关处理逻辑。"""
    bundle = load_real_data_bundle(Path("data") / "real_shuohuang")
    limits = {
        "arm_a": PowerArmElectricalLimit(
            max_traction_supply_kw=100000.0,
            max_regen_absorption_kw=100000.0,
            storage_available=True,
            storage_section_id="storage_section_1",
        ),
        "arm_b": PowerArmElectricalLimit(
            max_traction_supply_kw=100000.0,
            max_regen_absorption_kw=100000.0,
            storage_available=True,
            storage_section_id="storage_section_2",
        ),
    }
    system = EnergySettlementSystem(
        bundle.battery,
        settlement_time_step_s=1,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits=limits,
    )
    result = system.settle(
        [
            # energy_transfer_ratio 是进入储能区段的占用比例；完全位于某区段内时比例为 1.0，
            # 各储能区段保持相互独立。
            {0: (-3600.0, 1.0, "arm_a", 1.0, "storage_section_1")},
            {0: (3600.0, 1.0, "arm_b", 1.0, "storage_section_2")},
        ]
    )
    if result.battery_charge_kwh <= 0.0 or result.battery_discharge_kwh != 0.0 or result.grid_kwh <= 0.0:
        raise AssertionError("Energy was transferred between independent storage sections in one time slice")
    if result.final_soc_by_storage_kwh.get("storage_section_1", 0.0) <= 0.0:
        raise AssertionError("Storage section 1 SOC was not updated")
    if result.final_soc_by_storage_kwh.get("storage_section_2", 0.0) != 0.0:
        raise AssertionError("Storage section 2 incorrectly received SOC from section 1")
    expected_final_soc_kwh = (
        result.initial_soc_kwh
        + result.battery_charge_kwh * bundle.battery.round_trip_efficiency
        - result.battery_discharge_kwh
    )
    if abs(result.final_soc_kwh - expected_final_soc_kwh) > 1e-9:
        raise AssertionError("Storage SOC energy conservation failed")


def _assert_dispatch_and_timetable_settlement_match() -> None:
    """函数 _assert_dispatch_and_timetable_settlement_match：执行该模块中的相关处理逻辑。"""
    bundle = load_real_data_bundle(Path("data") / "real_shuohuang")
    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=100000.0,
        max_regen_absorption_kw=100000.0,
        storage_available=True,
        storage_section_id="storage_section_1",
    )
    limits = {"arm_a": limit}
    dispatch = EnergySettlementSystem(
        bundle.battery,
        settlement_time_step_s=3600,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits=limits,
    ).settle(
        [
            {
                0: (-3600.0, 1.0, "arm_a", 3600.0, "storage_section_1"),
                3600: (1800.0, 1.0, "arm_a", 3600.0, "storage_section_1"),
            }
        ]
    )
    scenario = TimetableScenario(
        scenario_id="storage_no_direct",
        direct_use_enabled=False,
        storage_enabled=True,
        storage_capacity_kwh=bundle.battery.capacity_kwh,
        storage_power_kw=bundle.battery.max_charge_power_kW,
        storage_charge_power_kw=bundle.battery.max_charge_power_kW,
        storage_discharge_power_kw=bundle.battery.max_discharge_power_kW,
        initial_soc_kwh=0.0,
        settlement_time_step_s=3600,
        transfer_scope="same_power_arm",
    )
    rows = [
        {
            "power_arm_id": "arm_a",
            "storage_section_id": "storage_section_1",
            "time_window_start_s": 0,
            "time_window_end_s": 3600,
            "traction_kwh": 0.0,
            "regen_kwh": 3600.0,
        },
        {
            "power_arm_id": "arm_a",
            "storage_section_id": "storage_section_1",
            "time_window_start_s": 3600,
            "time_window_end_s": 7200,
            "traction_kwh": 1800.0,
            "regen_kwh": 0.0,
        },
    ]
    _settlement_rows, _issues, timetable = evaluate_scenario_time_slices(rows, scenario, limits)
    comparisons = {
        "charge": (dispatch.battery_charge_kwh, timetable["storage_absorbed_kwh"]),
        "discharge": (dispatch.battery_discharge_kwh, timetable["storage_discharged_kwh"]),
        "wasted": (dispatch.wasted_kwh, timetable["wasted_kwh"]),
        "grid": (dispatch.grid_kwh, timetable["grid_kwh"]),
        "final_soc": (dispatch.final_soc_kwh, timetable["final_soc_kwh"]),
    }
    for name, (left, right) in comparisons.items():
        if abs(left - right) > 1e-6:
            raise AssertionError(f"Dispatch/timetable {name} mismatch: {left} != {right}")


def _assert_timetable_plot_uses_each_case_cache() -> None:
    """Baseline and optimized panels must not share the selected preset cache."""

    template = ScheduleTemplate(900, 900, 0, 1, 1)
    baseline = SimpleNamespace(
        label="baseline",
        schedule=GeneratedSchedule([0], [100], template),
    )
    optimized = SimpleNamespace(
        label="optimized",
        schedule=GeneratedSchedule([200], [300], template),
    )
    baseline_route = SimpleNamespace(energy_transfer_ranges_km=[(1.0, 2.0)])
    optimized_route = SimpleNamespace(energy_transfer_ranges_km=[(3.0, 4.0)])
    baseline_heavy = object()
    baseline_empty = object()
    optimized_heavy = object()
    optimized_empty = object()
    seen = []

    def _points(cache, depart_time_s, storage_hold_s=0):
        """函数 _points：执行该模块中的相关处理逻辑。"""
        seen.append((cache, depart_time_s, storage_hold_s))
        return [0, 1], [0.0, 1.0]

    with tempfile.TemporaryDirectory() as temp_dir, patch(
        "run_dispatch_case._trajectory_plot_points",
        side_effect=_points,
    ):
        plot_timetable(
            baseline,
            optimized,
            baseline_route,
            baseline_heavy,  # type: ignore[arg-type]
            baseline_empty,  # type: ignore[arg-type]
            Path(temp_dir) / "timetable.png",
            optimized_route=optimized_route,
            optimized_heavy_cache=optimized_heavy,  # type: ignore[arg-type]
            optimized_empty_cache=optimized_empty,  # type: ignore[arg-type]
        )
    assert [item[0] for item in seen] == [
        baseline_heavy,
        baseline_empty,
        optimized_heavy,
        optimized_empty,
    ]


def _assert_same_slice_storage_is_arm_order_invariant() -> None:
    """函数 _assert_same_slice_storage_is_arm_order_invariant：执行该模块中的相关处理逻辑。"""
    bundle = load_real_data_bundle(Path("data") / "real_shuohuang")
    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=100000.0,
        max_regen_absorption_kw=100000.0,
        storage_available=True,
        storage_section_id="shared_storage",
    )
    limits = {"arm_a": limit, "arm_z": limit}

    def dispatch_result(regen_arm: str, traction_arm: str):
        """函数 dispatch_result：执行该模块中的相关处理逻辑。"""
        system = EnergySettlementSystem(
            bundle.battery,
            settlement_time_step_s=3600,
            allow_direct_use=False,
            allow_storage=True,
            power_arm_limits=limits,
        )
        return system.settle(
            [
                {0: (-3600.0, 1.0, regen_arm, 3600.0, "shared_storage")},
                {0: (3600.0, 1.0, traction_arm, 3600.0, "shared_storage")},
            ]
        )

    left = dispatch_result("arm_a", "arm_z")
    right = dispatch_result("arm_z", "arm_a")
    for name in ("battery_charge_kwh", "battery_discharge_kwh", "wasted_kwh", "grid_kwh", "final_soc_kwh"):
        if abs(getattr(left, name) - getattr(right, name)) > 1e-9:
            raise AssertionError(f"Dispatch storage settlement depends on arm ordering: {name}")

    scenario = TimetableScenario(
        scenario_id="storage_no_direct",
        direct_use_enabled=False,
        storage_enabled=True,
        storage_capacity_kwh=bundle.battery.capacity_kwh,
        storage_power_kw=bundle.battery.max_charge_power_kW,
        initial_soc_kwh=0.0,
        settlement_time_step_s=3600,
        transfer_scope="same_power_arm",
        storage_efficiency=bundle.battery.round_trip_efficiency,
    )

    def timetable_result(regen_arm: str, traction_arm: str):
        """函数 timetable_result：执行该模块中的相关处理逻辑。"""
        rows = [
            {
                "power_arm_id": regen_arm,
                "storage_section_id": "shared_storage",
                "time_window_start_s": 0,
                "time_window_end_s": 3600,
                "traction_kwh": 0.0,
                "regen_kwh": 3600.0,
            },
            {
                "power_arm_id": traction_arm,
                "storage_section_id": "shared_storage",
                "time_window_start_s": 0,
                "time_window_end_s": 3600,
                "traction_kwh": 3600.0,
                "regen_kwh": 0.0,
            },
        ]
        return evaluate_scenario_time_slices(rows, scenario, limits)[2]

    timetable_left = timetable_result("arm_a", "arm_z")
    timetable_right = timetable_result("arm_z", "arm_a")
    for name in ("storage_absorbed_kwh", "storage_discharged_kwh", "wasted_kwh", "grid_kwh", "final_soc_kwh"):
        if abs(float(timetable_left[name]) - float(timetable_right[name])) > 1e-9:
            raise AssertionError(f"Timetable storage settlement depends on arm ordering: {name}")


def _assert_partial_route_uses_complete_storage_allocation() -> None:
    """函数 _assert_partial_route_uses_complete_storage_allocation：执行该模块中的相关处理逻辑。"""
    battery = BatteryStorageParameters(
        capacity_kwh=100.0,
        round_trip_efficiency=0.9,
        depreciation_cost_per_kwh=0.0,
        grid_price_per_kwh=0.0,
        max_charge_power_kW=1000.0,
        max_discharge_power_kW=1000.0,
    )
    limits = {
        "arm_1": PowerArmElectricalLimit(
            max_traction_supply_kw=1000.0,
            max_regen_absorption_kw=1000.0,
            storage_available=True,
            storage_section_id="S1",
        ),
        "arm_2": PowerArmElectricalLimit(
            max_traction_supply_kw=1000.0,
            max_regen_absorption_kw=1000.0,
            storage_available=True,
            storage_section_id="S2",
        ),
    }
    dispatch = EnergySettlementSystem(
        battery,
        settlement_time_step_s=3600,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits=limits,
    ).settle([{0: (-80.0, 1.0, "arm_1", 3600.0, "S1")}])
    scenario = TimetableScenario(
        scenario_id="partial_route",
        direct_use_enabled=False,
        storage_enabled=True,
        storage_capacity_kwh=100.0,
        storage_power_kw=1000.0,
        initial_soc_kwh=0.0,
        settlement_time_step_s=3600,
        transfer_scope="same_power_arm",
        storage_efficiency=0.9,
    )
    rows = [
        {
            "power_arm_id": "arm_1",
            "storage_section_id": "S1",
            "time_window_start_s": 0,
            "time_window_end_s": 3600,
            "traction_kwh": 0.0,
            "regen_kwh": 80.0,
        }
    ]
    timetable = evaluate_scenario_time_slices(rows, scenario, limits)[2]
    if abs(dispatch.battery_charge_kwh - float(timetable["storage_absorbed_kwh"])) > 1e-6:
        raise AssertionError("Partial-route timetable reassigned unused storage-section capacity")
    if timetable["final_soc_by_storage_kwh"] != {"S1": 50.0, "S2": 0.0}:
        raise AssertionError(f"Unexpected partial-route SOC allocation: {timetable['final_soc_by_storage_kwh']}")


def _assert_device_soc_imbalance_is_not_hidden_by_aggregate() -> None:
    """An equal aggregate SOC can still hide one depleted storage device."""

    limits = {
        "arm_s1": PowerArmElectricalLimit(
            max_traction_supply_kw=1000.0,
            max_regen_absorption_kw=1000.0,
            storage_available=True,
            storage_section_id="S1",
        ),
        "arm_s2": PowerArmElectricalLimit(
            max_traction_supply_kw=1000.0,
            max_regen_absorption_kw=1000.0,
            storage_available=True,
            storage_section_id="S2",
        ),
    }
    scenario = TimetableScenario(
        scenario_id="device_soc_imbalance",
        direct_use_enabled=False,
        storage_enabled=True,
        storage_capacity_kwh=100.0,
        storage_power_kw=1000.0,
        initial_soc_kwh=50.0,
        settlement_time_step_s=3600,
        transfer_scope="same_power_arm",
        storage_efficiency=1.0,
    )
    _rows, issues, summary = evaluate_scenario_time_slices(
        [
            {
                "power_arm_id": "arm_s1",
                "storage_section_id": "S1",
                "time_window_start_s": 0,
                "time_window_end_s": 3600,
                "traction_kwh": 0.0,
                "regen_kwh": 25.0,
            },
            {
                "power_arm_id": "arm_s2",
                "storage_section_id": "S2",
                "time_window_start_s": 3600,
                "time_window_end_s": 7200,
                "traction_kwh": 25.0,
                "regen_kwh": 0.0,
            },
        ],
        scenario,
        limits,
    )
    if issues:
        raise AssertionError(f"Unexpected electrical/energy issues: {issues}")
    if summary["final_soc_kwh"] != 50.0:
        raise AssertionError(summary["final_soc_kwh"])
    if summary["final_soc_deviation_kwh"] != 0.0:
        raise AssertionError("Aggregate SOC should remain unchanged in this fixture")
    if summary["final_soc_device_deviation_kwh"] != 50.0:
        raise AssertionError(summary["final_soc_device_deviation_kwh"])
    if summary["assessment"] != "needs_optimization":
        raise AssertionError("Device-level SOC depletion was hidden by aggregate assessment")


def _assert_electrical_excess_is_an_audit_issue() -> None:
    """函数 _assert_electrical_excess_is_an_audit_issue：执行该模块中的相关处理逻辑。"""
    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=1.0,
        max_regen_absorption_kw=1.0,
    )
    scenario = TimetableScenario(
        scenario_id="electrical_limit_probe",
        direct_use_enabled=False,
        storage_enabled=False,
        storage_capacity_kwh=0.0,
        storage_power_kw=0.0,
        initial_soc_kwh=0.0,
        settlement_time_step_s=3600,
        transfer_scope="same_power_arm",
    )
    rows = [
        {
            "power_arm_id": "limited_arm",
            "storage_section_id": "",
            "time_window_start_s": 0,
            "time_window_end_s": 3600,
            "traction_kwh": 100.0,
            "regen_kwh": 100.0,
        }
    ]
    settlement_rows, issues, summary = evaluate_scenario_time_slices(
        rows,
        scenario,
        {"limited_arm": limit},
    )
    assert settlement_rows[0]["traction_supply_excess_kwh"] == 99.0
    assert settlement_rows[0]["regen_absorption_excess_kwh"] == 99.0
    assert summary["electrical_constraint_violation_kwh"] == 198.0
    issue_types = {str(issue["issue_type"]) for issue in issues}
    assert "traction_supply_capacity_exceeded" in issue_types
    assert "regen_absorption_capacity_exceeded" in issue_types


def _assert_timetable_keeps_ten_second_settlement_step() -> None:
    """函数 _assert_timetable_keeps_ten_second_settlement_step：执行该模块中的相关处理逻辑。"""
    scenario = TimetableScenario(
        scenario_id="formal_ten_second_graph",
        direct_use_enabled=False,
        storage_enabled=True,
        storage_capacity_kwh=100.0,
        storage_power_kw=100.0,
        initial_soc_kwh=0.0,
        settlement_time_step_s=10,
        transfer_scope="same_power_arm",
    )
    if _effective_time_step_s(scenario) != 10:
        raise AssertionError("10-second running graph was silently widened")


def _assert_missing_timetable_scenario_uses_formal_ten_second_fallback() -> None:
    """Legacy inputs without a scenario must keep the formal 10-second audit bucket."""
    template = Path("data_templates") / "running_diagram_template.xlsx"
    with tempfile.TemporaryDirectory() as temp_name:
        input_path = Path(temp_name) / "missing_scenario.xlsx"
        workbook = openpyxl.load_workbook(template)
        workbook.remove(workbook["scenario"])
        workbook.save(input_path)
        output_dir = Path(temp_name) / "audit"
        summary = audit_timetable(
            input_path,
            output_dir,
            Path("data") / "real_shuohuang" / "power_arm_intervals.csv",
        )
        if not summary.get("valid"):
            raise AssertionError(summary)
        with (output_dir / "scenario_summary.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) != 1 or int(rows[0]["settlement_time_step_s"]) != 10:
            raise AssertionError(
                "missing scenario fallback did not use the formal 10-second bucket: "
                f"{rows}"
            )


def _assert_dispatch_settlement_applies_storage_hold() -> None:
    """Reported settlement must use the same held empty-train timeline as optimization."""

    def cache(powers, direction):
        """函数 cache：执行该模块中的相关处理逻辑。"""
        return PowerSeriesCache(
            times=[0, 10, 20],
            powers_kW=list(powers),
            energy_transfer_ratios=[1.0, 1.0, 1.0],
            power_arm_ids=["A", "A", "A"],
            positions_km=[0.0, 1.0, 2.0] if direction == "forward" else [2.0, 1.0, 0.0],
            speeds_mps=[1.0, 1.0, 0.0],
            train_length_km=0.1,
            direction=direction,
            adhesion_coefficients=[0.28, 0.28, 0.28],
            speed_limits_mps=[33.3, 33.3, 33.3],
            brake_decelerations_mps2=[0.3, 0.3, 0.3],
            storage_section_ids=["S", "S", "S"],
        )

    heavy_cache = cache([0.0, 3600.0, 0.0], "forward")
    empty_cache = cache([-3600.0, 0.0, 0.0], "reverse")
    battery = BatteryStorageParameters(
        capacity_kwh=100.0,
        round_trip_efficiency=1.0,
        depreciation_cost_per_kwh=0.0,
        grid_price_per_kwh=0.0,
        max_charge_power_kW=10000.0,
        max_discharge_power_kW=10000.0,
    )
    system = EnergySettlementSystem(
        battery,
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={
            "A": PowerArmElectricalLimit(
                max_traction_supply_kw=10000.0,
                max_regen_absorption_kw=10000.0,
                storage_available=True,
                storage_section_id="S",
            )
        },
    )
    schedule = GeneratedSchedule(
        heavy_departures_s=[0],
        empty_departures_s=[0],
        template=ScheduleTemplate(100, 100, 0, 1, 1, flex_zone_hold_s=10),
    )
    score = evaluate_schedule(
        schedule,
        heavy_cache,
        empty_cache,
        system,
        {"mode": "fixed_block"},
        min_depart_gap_s=0,
    )
    reported = settle_schedule(schedule, heavy_cache, empty_cache, system)
    if abs(reported.grid_kwh - score.grid_kwh) > 1e-9:
        raise AssertionError(
            "dispatch report ignored flex-zone hold: "
            f"reported grid={reported.grid_kwh}, optimized grid={score.grid_kwh}"
        )
    if abs(reported.final_soc_kwh - score.final_soc_kwh) > 1e-9:
        raise AssertionError(
            "dispatch report and optimizer used different storage timelines: "
            f"reported SOC={reported.final_soc_kwh}, optimized SOC={score.final_soc_kwh}"
        )
    if abs(reported.grid_kwh - 10.0) > 1e-9 or abs(reported.final_soc_kwh - 10.0) > 1e-9:
        raise AssertionError(reported)

    # 最终运行图导出和列车图必须使用完全一致的停车后轨迹；没有正储能重叠的线路不得停车。
    evaluation = type("Evaluation", (), {"label": "held", "schedule": schedule})()
    empty_row = next(row for row in train_rows(evaluation, heavy_cache, empty_cache) if row["train_type"] == "Empty")
    if empty_row["arrival_time_s"] != 30:
        raise AssertionError(f"schedule CSV ignored storage hold: {empty_row}")
    plot_times, _plot_positions = _trajectory_plot_points(empty_cache, 0, storage_hold_s=10)
    if plot_times != [0, 10, 10, 20, 30]:
        raise AssertionError(f"train diagram ignored storage hold: {plot_times}")

    no_storage_cache = PowerSeriesCache(
        times=[0, 10, 20],
        powers_kW=[0.0, 0.0, 0.0],
        energy_transfer_ratios=[0.0, 0.0, 0.0],
        power_arm_ids=["A", "A", "A"],
        positions_km=[2.0, 1.0, 0.0],
        speeds_mps=[1.0, 1.0, 0.0],
        train_length_km=0.1,
        direction="reverse",
        adhesion_coefficients=[0.28, 0.28, 0.28],
        speed_limits_mps=[33.3, 33.3, 33.3],
        brake_decelerations_mps2=[0.3, 0.3, 0.3],
        storage_section_ids=["", "", ""],
    )
    no_storage_row = next(
        row
        for row in train_rows(evaluation, heavy_cache, no_storage_cache)
        if row["train_type"] == "Empty"
    )
    if no_storage_row["arrival_time_s"] != 20:
        raise AssertionError(f"hold was applied to a train that never reaches storage: {no_storage_row}")
    no_storage_times, _ = _trajectory_plot_points(no_storage_cache, 0, storage_hold_s=10)
    if no_storage_times != [0, 10, 20]:
        raise AssertionError("train diagram invented a hold outside storage geometry")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
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

    settlement_system = make_settlement_system(
        bundle.battery,
        bundle.route,
        settlement_step_s=30,
        initial_soc_kwh=0.0,
        target_final_soc_kwh=None,
        final_soc_tolerance_kwh=0.0,
        final_soc_penalty_per_kwh=0.0,
        wasted_energy_penalty_per_kwh=0.0,
        energy_scenario=ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    )
    storage_no_direct = settle_schedule(schedule, heavy_cache, empty_cache, settlement_system)
    assert storage_no_direct.direct_used_kwh == 0.0
    assert storage_no_direct.battery_charge_kwh >= 0.0
    assert storage_no_direct.battery_discharge_kwh >= 0.0
    _assert_energy_conservation()
    _assert_cli_zero_efficiency_override_disables_storage()
    _assert_timetable_keeps_ten_second_settlement_step()
    _assert_missing_timetable_scenario_uses_formal_ten_second_fallback()
    _assert_dispatch_settlement_applies_storage_hold()
    _assert_storage_tags_work_without_limit_table()
    _assert_five_second_power_integration()
    _assert_cross_bin_sample_splitting()
    _assert_storage_sections_are_independent()
    _assert_dispatch_and_timetable_settlement_match()
    _assert_timetable_plot_uses_each_case_cache()
    _assert_same_slice_storage_is_arm_order_invariant()
    _assert_partial_route_uses_complete_storage_allocation()
    _assert_device_soc_imbalance_is_not_hidden_by_aggregate()
    _assert_electrical_excess_is_an_audit_issue()

    print("storage energy scenario verification passed")
    print(
        ENERGY_SCENARIO_STORAGE_NO_DIRECT,
        {
            "direct_used_kwh": round(storage_no_direct.direct_used_kwh, 3),
            "battery_charge_kwh": round(storage_no_direct.battery_charge_kwh, 3),
            "battery_discharge_kwh": round(storage_no_direct.battery_discharge_kwh, 3),
            "wasted_kwh": round(storage_no_direct.wasted_kwh, 3),
            "grid_kwh": round(storage_no_direct.grid_kwh, 3),
            "total_cost": round(storage_no_direct.total_cost, 3),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
