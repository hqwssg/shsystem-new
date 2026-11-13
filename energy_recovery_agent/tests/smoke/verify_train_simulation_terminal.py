"""Regression checks for terminal approach handling in the train simulator.

The Euler integrator can bring a train to zero speed a few metres before the
nominal endpoint.  This is a valid numerical boundary state, but it must not
remain stuck until ``max_time_s`` expires.  These cases reproduce the
direction/grade combinations that previously failed to arrive.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from train_simulator import (
    DavisCoefficients,
    RouteData,
    Segment,
    Station,
    TrainParameters,
    default_operating_conditions,
    run_train_simulation,
)


def _scenario(gradient_per_mille: float, direction: str, delta_t_s: int):
    """函数 _scenario：执行该模块中的相关处理逻辑。"""
    length_km = 10.0
    route = RouteData(
        total_length_km=length_km,
        max_speed_kmh=80.0,
        stations=[Station("A", 0.0), Station("B", length_km)],
        segments=[Segment(0.0, length_km, gradient_per_mille)],
        long_downhill_range_km=(0.0, 0.0),
        energy_transfer_ranges_km=[],
        signaling_system={},
        operating_conditions=default_operating_conditions(),
    )
    train = TrainParameters(
        name=f"terminal-{direction}-{gradient_per_mille}",
        mass_tons=1000.0,
        max_traction_kN=300.0,
        max_brake_kN=400.0,
        rotational_mass_factor=1.05,
        davis=DavisCoefficients(5.0, 0.1, 0.002),
        max_power_kW=3000.0,
        direction=direction,
    )
    return train, run_train_simulation(route, train, delta_t_s=delta_t_s)


def test_terminal_arrival_after_zero_speed_approach() -> None:
    # 两种情况此前都会在距终点约 2.003 米处停止，并在运行至 max_time_s 后抛出 RuntimeError。
    """函数 test_terminal_arrival_after_zero_speed_approach：执行该模块中的相关处理逻辑。"""
    for gradient, direction in ((5.0, "forward"), (-5.0, "reverse")):
        train, records = _scenario(gradient, direction, 1)
        if not records:
            raise AssertionError(f"{train.name} produced no simulation records")
        terminal_km = 10.0 if direction == "forward" else 0.0
        if abs(records[-1].position_km - terminal_km) > 1e-9:
            raise AssertionError(f"{train.name} did not reach the terminal")
        if records[-1].speed_mps != 0.0:
            raise AssertionError(f"{train.name} terminal state is not stopped")
        if records[-1].time_s >= 40_000:
            raise AssertionError(f"{train.name} arrived only at the max-time guard")

        positions = [record.position_km for record in records]
        if direction == "forward":
            monotonic = all(right >= left - 1e-12 for left, right in zip(positions, positions[1:]))
        else:
            monotonic = all(right <= left + 1e-12 for left, right in zip(positions, positions[1:]))
        if not monotonic:
            raise AssertionError(f"{train.name} position was not monotonic")
        if abs(positions[-1] - positions[-2]) * 1000.0 > 3.0 + 1e-9:
            raise AssertionError(f"{train.name} was teleported over the endpoint tolerance")


def test_terminal_arrival_is_stable_for_coarse_steps() -> None:
    # 使用仍受支持的较粗采样间隔和正负两种坡度，检查相同的边界逻辑。
    """函数 test_terminal_arrival_is_stable_for_coarse_steps：执行该模块中的相关处理逻辑。"""
    for gradient in (-5.0, 0.0, 5.0):
        for direction in ("forward", "reverse"):
            train, records = _scenario(gradient, direction, 10)
            terminal_km = 10.0 if direction == "forward" else 0.0
            if abs(records[-1].position_km - terminal_km) > 1e-9:
                raise AssertionError(f"{train.name} did not reach the terminal")
            if any(record.speed_mps < 0.0 for record in records):
                raise AssertionError(f"{train.name} reported a negative speed")


if __name__ == "__main__":
    test_terminal_arrival_after_zero_speed_approach()
    test_terminal_arrival_is_stable_for_coarse_steps()
    print("train simulation terminal handling passed")
