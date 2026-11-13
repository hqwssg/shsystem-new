"""Regression for the documented zero-length point-mass train contract."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from operating_conditions import default_operating_conditions
from scheduler_nsga2 import build_power_cache, clear_power_cache_memo
from train_simulator import (
    DavisCoefficients,
    RouteData,
    Segment,
    Station,
    TrainParameters,
)


def test_zero_length_train_can_build_optimizer_cache() -> None:
    """函数 test_zero_length_train_can_build_optimizer_cache：执行该模块中的相关处理逻辑。"""
    route = RouteData(
        total_length_km=1.0,
        max_speed_kmh=80.0,
        stations=[Station("A", 0.0), Station("B", 1.0)],
        segments=[Segment(0.0, 1.0, 0.0)],
        long_downhill_range_km=(0.0, 0.0),
        energy_transfer_ranges_km=[],
        signaling_system={},
        operating_conditions=default_operating_conditions(),
    )
    train = TrainParameters(
        name="point-mass",
        mass_tons=1000.0,
        max_traction_kN=300.0,
        max_brake_kN=400.0,
        rotational_mass_factor=1.05,
        davis=DavisCoefficients(5.0, 0.1, 0.002),
        # 输入契约明确允许使用质点简化模型。
        length_km=0.0,
        longitudinal_segments=1,
        max_power_kW=3000.0,
    )
    clear_power_cache_memo()
    cache = build_power_cache(
        train,
        route,
        simulation_step_s=1,
        power_arm_interval_path=Path("outputs") / "missing_power_arm_intervals.csv",
        storage_sections=(),
    )
    if cache.train_length_km != 0.0:
        raise AssertionError(f"cache changed the configured train length: {cache.train_length_km}")
    if not cache.times or cache.times[-1] <= 0:
        raise AssertionError("zero-length train cache did not contain an arrival trajectory")
    if any(len(allocations) == 0 for allocations in cache.power_allocation_ratios):
        raise AssertionError("zero-length train cache lost its single longitudinal allocation")


if __name__ == "__main__":
    test_zero_length_train_can_build_optimizer_cache()
    print("zero-length train cache contract passed")
