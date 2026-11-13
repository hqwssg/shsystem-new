# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from rolling_optimizer import (
    OBJECTIVE_PRIORITY_BALANCED,
    OBJECTIVE_PRIORITY_COST_FIRST,
    OBJECTIVE_PRIORITY_ENERGY_FIRST,
    ScheduleScore,
    candidate_selection_key,
    score_rank_value,
)
from train_simulator import BatteryStorageParameters


def _battery(**kwargs) -> BatteryStorageParameters:
    """函数 _battery：执行该模块中的相关处理逻辑。"""
    base = dict(
        capacity_kwh=100.0,
        round_trip_efficiency=0.9,
        depreciation_cost_per_kwh=0.25,
        grid_price_per_kwh=0.65,
        max_charge_power_kW=1000.0,
        max_discharge_power_kW=1000.0,
    )
    base.update(kwargs)
    return BatteryStorageParameters(**base)


def _limit() -> PowerArmElectricalLimit:
    """函数 _limit：执行该模块中的相关处理逻辑。"""
    return PowerArmElectricalLimit(
        storage_available=True,
        storage_section_id="S",
        max_traction_supply_kw=1e6,
        max_regen_absorption_kw=1e6,
    )


def test_settlement_cost_components_respond_to_weight_overrides() -> None:
    """函数 test_settlement_cost_components_respond_to_weight_overrides：执行该模块中的相关处理逻辑。"""
    series = [{0: (-500.0, 1.0, "A1", 10.0, "S"), 10: (400.0, 1.0, "A1", 10.0, "S")}]
    low_dep = EnergySettlementSystem(
        battery=_battery(depreciation_cost_per_kwh=0.05),
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={"A1": _limit()},
        initial_soc_kwh=0.0,
        wasted_energy_penalty_per_kwh=0.0,
    ).settle(series)
    high_dep = EnergySettlementSystem(
        battery=_battery(depreciation_cost_per_kwh=1.0),
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={"A1": _limit()},
        initial_soc_kwh=0.0,
        wasted_energy_penalty_per_kwh=0.0,
    ).settle(series)
    if not (high_dep.total_cost > low_dep.total_cost):
        raise AssertionError(
            f"higher depreciation should raise total_cost: low={low_dep.total_cost} high={high_dep.total_cost}"
        )

    no_waste = EnergySettlementSystem(
        battery=_battery(),
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={"A1": _limit()},
        initial_soc_kwh=0.0,
        wasted_energy_penalty_per_kwh=0.0,
    ).settle(series)
    with_waste = EnergySettlementSystem(
        battery=_battery(),
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={"A1": _limit()},
        initial_soc_kwh=0.0,
        wasted_energy_penalty_per_kwh=0.5,
    ).settle(series)
    if with_waste.total_cost < no_waste.total_cost - 1e-9:
        raise AssertionError(
            f"waste penalty should not lower total_cost: base={no_waste.total_cost} penalized={with_waste.total_cost}"
        )
    if with_waste.wasted_kwh > 1e-9 and with_waste.wasted_energy_penalty <= 0.0:
        raise AssertionError("expected positive wasted_energy_penalty when waste exists")


def _score(**kwargs) -> ScheduleScore:
    """函数 _score：执行该模块中的相关处理逻辑。"""
    base = dict(
        feasible=True,
        total_cost=100.0,
        headway_deviation=10.0,
        worst_case_cost=120.0,
        worst_case_headway_deviation=12.0,
        scenario_count=1,
        wasted_kwh=50.0,
        grid_kwh=40.0,
        battery_charge_kwh=10.0,
        battery_discharge_kwh=8.0,
        energy_scenario="storage_no_direct",
        objective_priority=OBJECTIVE_PRIORITY_ENERGY_FIRST,
    )
    base.update(kwargs)
    return ScheduleScore(**base)


def test_objective_priority_changes_selection_order() -> None:
    """函数 test_objective_priority_changes_selection_order：执行该模块中的相关处理逻辑。"""
    cheap_high_waste = _score(
        total_cost=10.0,
        wasted_kwh=200.0,
        grid_kwh=150.0,
        objective_priority=OBJECTIVE_PRIORITY_COST_FIRST,
    )
    expensive_low_waste = _score(
        total_cost=500.0,
        wasted_kwh=5.0,
        grid_kwh=5.0,
        objective_priority=OBJECTIVE_PRIORITY_COST_FIRST,
    )
    if candidate_selection_key(cheap_high_waste) >= candidate_selection_key(expensive_low_waste):
        raise AssertionError("cost_first should prefer lower total_cost")

    energy_a = _score(
        total_cost=10.0,
        wasted_kwh=200.0,
        grid_kwh=150.0,
        objective_priority=OBJECTIVE_PRIORITY_ENERGY_FIRST,
    )
    energy_b = _score(
        total_cost=500.0,
        wasted_kwh=5.0,
        grid_kwh=5.0,
        objective_priority=OBJECTIVE_PRIORITY_ENERGY_FIRST,
    )
    if candidate_selection_key(energy_b) >= candidate_selection_key(energy_a):
        raise AssertionError("energy_first should prefer lower wasted/grid even if cost is higher")

    balanced = _score(objective_priority=OBJECTIVE_PRIORITY_BALANCED)
    rank = score_rank_value(balanced)
    if not isinstance(rank, float):
        raise AssertionError(rank)


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    test_settlement_cost_components_respond_to_weight_overrides()
    test_objective_priority_changes_selection_order()
    print("objective weight alignment verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
