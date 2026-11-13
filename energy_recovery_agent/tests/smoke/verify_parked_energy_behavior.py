# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from rolling_optimizer import (
    ENERGY_SCENARIO_DIRECT_WITH_STORAGE,
    ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    ScheduleScore,
    ScheduleTemplate,
    GeneratedSchedule,
    apply_storage_entry_hold,
    candidate_selection_key,
    energy_scenario_objective,
    evaluate_schedule,
    objective_tuple,
)
from scheduler_nsga2 import PowerSeriesCache
from train_simulator import BatteryStorageParameters
from train_simulator import load_config
from run_ablation_experiments import _relative_reduction_pct
from run_storage_energy_search import _rounded_reduction_pct, storage_preset_ranking_key


def _score(*, charge: float, discharge: float, wasted: float, grid: float, final_soc: float) -> ScheduleScore:
    """函数 _score：执行该模块中的相关处理逻辑。"""
    return ScheduleScore(
        feasible=True,
        total_cost=0.0,
        headway_deviation=0.0,
        worst_case_cost=0.0,
        worst_case_headway_deviation=0.0,
        scenario_count=1,
        capacity_margin_s=0.0,
        constraint_violation=0.0,
        headway_violation_s=0.0,
        signal_violation_count=0,
        resource_overlap_violation_s=0.0,
        traction_supply_excess_kwh=0.0,
        regen_absorption_excess_kwh=0.0,
        electrical_constraint_violation_kwh=0.0,
        resource_conflict_count=0,
        flow_continuity_feasible=True,
        flow_continuity_violation_count=0,
        time_space_node_count=0,
        time_space_arc_count=0,
        direct_used_kwh=0.0,
        battery_charge_kwh=charge,
        battery_discharge_kwh=discharge,
        wasted_kwh=wasted,
        grid_kwh=grid,
        final_soc_kwh=final_soc,
        final_soc_deviation_kwh=final_soc,
        objective_mode="balanced",
        energy_scenario=ENERGY_SCENARIO_STORAGE_NO_DIRECT,
        objective_priority="energy_first",
    )


def test_energy_term_counts_terminal_soc_once() -> None:
    """函数 test_energy_term_counts_terminal_soc_once：执行该模块中的相关处理逻辑。"""
    parked = _score(charge=10.0, discharge=2.0, wasted=0.0, grid=0.0, final_soc=8.0)
    used = _score(charge=10.0, discharge=8.0, wasted=0.0, grid=0.0, final_soc=2.0)
    parked_term = energy_scenario_objective(parked)
    used_term = energy_scenario_objective(used)
    assert abs(parked_term - 8.0) < 1e-9
    assert abs(used_term - 2.0) < 1e-9
    assert used_term < parked_term


def test_energy_first_does_not_prefer_charge_and_park() -> None:
    """函数 test_energy_first_does_not_prefer_charge_and_park：执行该模块中的相关处理逻辑。"""
    parked = replace(
        _score(charge=10.0, discharge=0.0, wasted=0.0, grid=10.0, final_soc=9.5),
        storage_efficiency=0.95,
    )
    rejected = _score(charge=0.0, discharge=0.0, wasted=10.0, grid=10.0, final_soc=0.0)
    assert energy_scenario_objective(parked) == energy_scenario_objective(rejected)
    assert candidate_selection_key(rejected) < candidate_selection_key(parked)


def test_legacy_storage_alias_uses_canonical_objectives() -> None:
    """函数 test_legacy_storage_alias_uses_canonical_objectives：执行该模块中的相关处理逻辑。"""
    canonical = _score(charge=10.0, discharge=1.0, wasted=0.0, grid=4.0, final_soc=9.0)
    legacy_alias = replace(canonical, energy_scenario=ENERGY_SCENARIO_DIRECT_WITH_STORAGE)
    assert energy_scenario_objective(legacy_alias) == energy_scenario_objective(canonical)
    assert objective_tuple(legacy_alias) == objective_tuple(canonical)
    assert candidate_selection_key(legacy_alias) == candidate_selection_key(canonical)


def test_schedule_score_positional_compatibility() -> None:
    """函数 test_schedule_score_positional_compatibility：执行该模块中的相关处理逻辑。"""
    score = ScheduleScore(
        True, 1.0, 2.0, 3.0, 4.0, 5,
        6, 7, 8, False, 9, 10.0,
        "capacity_tight", "cost_first", "direct_no_storage",
        11.0, 12.0, 13.0, 14.0, 15.0, 16.0,
        17.0, 18.0, 19, 20.0, 21.0, 22.0, 23.0,
    )
    assert score.constraint_violation == 17.0
    assert score.electrical_constraint_violation_kwh == 23.0
    assert score.final_soc_deviation_kwh == 0.0


def test_storage_preset_ranking_rejects_infeasible_and_parked_options() -> None:
    """函数 test_storage_preset_ranking_rejects_infeasible_and_parked_options：执行该模块中的相关处理逻辑。"""
    reused = {
        "feasible": True,
        "resource_conflict_count": 0,
        "effective_regen_loss_kwh": 10.0,
        "grid_kwh": 10.0,
        "total_cost": 10.0,
    }
    parked = {**reused, "effective_regen_loss_kwh": 19.0, "total_cost": 1.0}
    infeasible = {**reused, "feasible": False, "effective_regen_loss_kwh": 0.0}
    assert storage_preset_ranking_key(reused) < storage_preset_ranking_key(parked)
    assert storage_preset_ranking_key(reused) < storage_preset_ranking_key(infeasible)
    for invalid_row, expected_field in (
        ({**reused, "feasible": "false"}, "feasible"),
        ({**reused, "resource_conflict_count": True}, "resource_conflict_count"),
        ({**reused, "effective_regen_loss_kwh": float("nan")}, "effective_regen_loss_kwh"),
    ):
        try:
            storage_preset_ranking_key(invalid_row)
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid storage ranking row was accepted: {invalid_row!r}")


def test_storage_search_zero_baseline_reduction_is_undefined() -> None:
    """函数 test_storage_search_zero_baseline_reduction_is_undefined：执行该模块中的相关处理逻辑。"""
    assert _rounded_reduction_pct(0.0, 0.0) == 0.0
    assert _rounded_reduction_pct(0.0, 1.0) is None
    assert _rounded_reduction_pct(10.0, 8.0) == 20.0


def test_ablation_zero_baseline_reduction_is_undefined() -> None:
    """函数 test_ablation_zero_baseline_reduction_is_undefined：执行该模块中的相关处理逻辑。"""
    assert _relative_reduction_pct(0.0, 0.0) == 0.0
    assert _relative_reduction_pct(0.0, 1.0) is None
    assert _relative_reduction_pct(10.0, 8.0) == 20.0


def test_final_soc_penalty_discourages_parking() -> None:
    """函数 test_final_soc_penalty_discourages_parking：执行该模块中的相关处理逻辑。"""
    battery = BatteryStorageParameters(
        capacity_kwh=100.0,
        round_trip_efficiency=1.0,
        depreciation_cost_per_kwh=0.0,
        grid_price_per_kwh=0.0,
        max_charge_power_kW=1000.0,
        max_discharge_power_kW=1000.0,
    )
    system = EnergySettlementSystem(
        battery,
        settlement_time_step_s=10,
        initial_soc_kwh=0.0,
        target_final_soc_kwh=0.0,
        final_soc_tolerance_kwh=0.0,
        final_soc_penalty_per_kwh=0.05,
        wasted_energy_penalty_per_kwh=0.0,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={
            "A": PowerArmElectricalLimit(
                max_regen_absorption_kw=1e9,
                storage_available=True,
                storage_section_id="S",
            )
        },
    )
    series = {0: (-3600.0, 1.0, "A", 10.0, "S")}
    result = system.settle([series])
    assert result.battery_charge_kwh > 0.0
    assert result.final_soc_kwh > 0.0
    assert result.final_soc_penalty > 0.0
    assert abs(result.final_soc_penalty - result.final_soc_kwh * 0.05) < 1e-6


def test_missing_target_uses_initial_soc_for_energy_score() -> None:
    """函数 test_missing_target_uses_initial_soc_for_energy_score：执行该模块中的相关处理逻辑。"""
    route, _trains, _battery_config = load_config(ROOT / "sandbox_config.json")
    cache = PowerSeriesCache(
        times=[0],
        powers_kW=[-3600.0],
        energy_transfer_ratios=[1.0],
        power_arm_ids=["A"],
        positions_km=[150.0],
        speeds_mps=[1.0],
        train_length_km=1.0,
        direction="forward",
        adhesion_coefficients=[0.28],
        speed_limits_mps=[30.0],
        brake_decelerations_mps2=[0.3],
        storage_section_ids=["S"],
    )
    battery = BatteryStorageParameters(
        capacity_kwh=100.0,
        round_trip_efficiency=0.9,
        depreciation_cost_per_kwh=0.0,
        grid_price_per_kwh=0.0,
        max_charge_power_kW=10000.0,
        max_discharge_power_kW=10000.0,
    )
    settlement = EnergySettlementSystem(
        battery,
        settlement_time_step_s=10,
        target_final_soc_kwh=None,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={
            "A": PowerArmElectricalLimit(
                storage_available=True,
                storage_section_id="S",
                max_regen_absorption_kw=10000.0,
                max_traction_supply_kw=10000.0,
            )
        },
    )
    schedule = GeneratedSchedule(
        heavy_departures_s=[0],
        empty_departures_s=[],
        template=ScheduleTemplate(100, 100, 0, 1, 0),
    )
    score = evaluate_schedule(
        schedule,
        cache,
        cache,
        settlement,
        route.signaling_system,
        resource_model=None,
    )
    assert abs(score.final_soc_deviation_kwh - 0.9) < 1e-9
    assert abs(score.storage_efficiency - 0.9) < 1e-9
    assert abs(energy_scenario_objective(score) - 1.0) < 1e-9


def test_hold_preserves_sample_count() -> None:
    """函数 test_hold_preserves_sample_count：执行该模块中的相关处理逻辑。"""
    series = {
        0: (1.0, 0.0, "A", 1.0, ""),
        10: (2.0, 1.0, "A", 1.0, "S"),
        110: (3.0, 0.0, "A", 1.0, ""),
    }
    delayed = apply_storage_entry_hold(series, 100)
    assert len(delayed) == len(series)
    assert sorted(delayed) == [0, 110, 210]


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    test_energy_term_counts_terminal_soc_once()
    test_energy_first_does_not_prefer_charge_and_park()
    test_legacy_storage_alias_uses_canonical_objectives()
    test_schedule_score_positional_compatibility()
    test_storage_preset_ranking_rejects_infeasible_and_parked_options()
    test_storage_search_zero_baseline_reduction_is_undefined()
    test_ablation_zero_baseline_reduction_is_undefined()
    test_final_soc_penalty_discourages_parking()
    test_missing_target_uses_initial_soc_for_energy_score()
    test_hold_preserves_sample_count()
    print("parked energy behavior verification passed")


if __name__ == "__main__":
    main()
