# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import math
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from train_simulator import BatteryStorageParameters


def _battery(**kwargs) -> BatteryStorageParameters:
    """函数 _battery：执行该模块中的相关处理逻辑。"""
    base = dict(
        capacity_kwh=50.0,
        round_trip_efficiency=0.9,
        depreciation_cost_per_kwh=0.0,
        grid_price_per_kwh=0.0,
        max_charge_power_kW=500.0,
        max_discharge_power_kW=500.0,
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


def test_random_settlement_invariants(seed: int = 20260728, n: int = 40) -> None:
    """函数 test_random_settlement_invariants：执行该模块中的相关处理逻辑。"""
    rng = random.Random(seed)
    for i in range(n):
        cap = rng.uniform(1.0, 200.0)
        system = EnergySettlementSystem(
            battery=_battery(
                capacity_kwh=cap,
                round_trip_efficiency=rng.uniform(0.2, 1.0),
                max_charge_power_kW=rng.uniform(10.0, 2000.0),
                max_discharge_power_kW=rng.uniform(10.0, 2000.0),
            ),
            settlement_time_step_s=rng.choice([1, 5, 10, 30]),
            allow_direct_use=False,
            allow_storage=True,
            power_arm_limits={"A1": _limit()},
            initial_soc_kwh=rng.uniform(0.0, cap),
            wasted_energy_penalty_per_kwh=0.0,
        )
        series_list = []
        for _train in range(rng.randint(1, 3)):
            series = {}
            t = 0
            for _sample in range(rng.randint(1, 6)):
                power = rng.uniform(-800.0, 800.0)
                dur = float(rng.choice([1, 5, 10, 20]))
                series[t] = (power, rng.uniform(0.0, 1.0), "A1", dur, "S")
                t += int(dur)
            series_list.append(series)
        result = system.settle(series_list)
        values = [
            result.total_gen_kwh,
            result.total_con_kwh,
            result.direct_used_kwh,
            result.battery_charge_kwh,
            result.battery_discharge_kwh,
            result.wasted_kwh,
            result.grid_kwh,
            result.final_soc_kwh,
            result.total_cost,
        ]
        if any((not math.isfinite(v)) or v < -1e-9 for v in values):
            raise AssertionError(f"non-finite/negative at iter {i}: {values}")
        if result.final_soc_kwh - cap > 1e-6:
            raise AssertionError(f"soc>{cap}: {result.final_soc_kwh}")
        if result.direct_used_kwh > 1e-9:
            raise AssertionError(f"direct use enabled unexpectedly: {result.direct_used_kwh}")
        if result.battery_charge_kwh - result.total_gen_kwh > 1e-6:
            raise AssertionError(
                f"charge exceeds gen: charge={result.battery_charge_kwh} gen={result.total_gen_kwh}"
            )


def test_order_independence() -> None:
    """函数 test_order_independence：执行该模块中的相关处理逻辑。"""
    system = EnergySettlementSystem(
        battery=_battery(capacity_kwh=80.0, round_trip_efficiency=0.85),
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={"A1": _limit()},
        initial_soc_kwh=10.0,
    )
    a = {0: (-500.0, 1.0, "A1", 10.0, "S"), 10: (200.0, 0.5, "A1", 10.0, "S")}
    b = {0: (300.0, 1.0, "A1", 10.0, "S"), 10: (-100.0, 1.0, "A1", 10.0, "S")}
    c = {5: (-50.0, 0.2, "A1", 10.0, "S")}
    left = system.settle([a, b, c])
    right = system.settle([c, b, a])
    for key in (
        "battery_charge_kwh",
        "battery_discharge_kwh",
        "wasted_kwh",
        "grid_kwh",
        "final_soc_kwh",
        "total_cost",
    ):
        if abs(getattr(left, key) - getattr(right, key)) > 1e-9:
            raise AssertionError(f"order dependence on {key}: {getattr(left, key)} vs {getattr(right, key)}")


def test_illegal_inputs_rejected() -> None:
    """函数 test_illegal_inputs_rejected：执行该模块中的相关处理逻辑。"""
    system = EnergySettlementSystem(
        battery=_battery(),
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={"A1": _limit()},
    )
    cases = [
        [{0: (float("nan"), 1.0, "A1", 10.0, "S")}],
        [{0: (float("inf"), 1.0, "A1", 10.0, "S")}],
        [None],
        [{0: (-10.0,)}],
    ]
    for payload in cases:
        try:
            system.settle(payload)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            continue
        raise AssertionError(f"expected rejection for payload={payload!r}")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    test_random_settlement_invariants()
    test_order_independence()
    test_illegal_inputs_rejected()
    print("settlement invariant smoke verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
