"""牵引—惰行—制动的单列车纵向动力学。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from regenerative_braking.dynamics.train_braking_model import (
    TrainBrakingProfile,
    total_resistance_n,
)

from ..models import ControlMode


@dataclass(frozen=True)
class LongitudinalState:
    position_m: float
    time_s: float
    speed_mps: float


@dataclass(frozen=True)
class ForceBalance:
    traction_force_n: float
    braking_force_n: float
    resistance_force_n: float
    acceleration_mps2: float


def force_balance(
    profile: TrainBrakingProfile,
    state: LongitudinalState,
    mode: ControlMode,
    level: float,
    gradient_per_mille: float,
    curve_radius_m: Optional[float],
    max_acceleration_mps2: float = 0.5,
    max_deceleration_mps2: float = 0.8,
    traction_limit_n: Optional[float] = None,
) -> ForceBalance:
    if not all(math.isfinite(value) for value in (state.position_m, state.time_s, state.speed_mps)):
        raise ValueError("state 必须只包含有限数值")
    if state.speed_mps < 0.0:
        raise ValueError("state.speed_mps 不得为负")
    level = float(level)
    if not math.isfinite(level):
        raise ValueError("level 必须为有限数值")
    level = min(1.0, max(0.0, level))
    for name, value in (
        ("max_acceleration_mps2", max_acceleration_mps2),
        ("max_deceleration_mps2", max_deceleration_mps2),
    ):
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{name} 必须为非负有限值")
    if traction_limit_n is not None and (not math.isfinite(traction_limit_n) or traction_limit_n < 0.0):
        raise ValueError("traction_limit_n 必须为非负有限值")
    resistance = total_resistance_n(profile, state.speed_mps, gradient_per_mille, curve_radius_m)
    traction = 0.0
    if mode is ControlMode.TRACTION:
        # 牵引力的上限必须显式给定；缺省时误把制动力当作牵引上限会高估牵引力，
        # 产生物理上不可实现的加速度。这里宁可报错也不静默使用错误量。
        if traction_limit_n is None:
            raise ValueError("TRACTION 模式必须提供 traction_limit_n（列车牵引力上限）")
        traction = level * traction_limit_n
    braking = level * min(profile.max_brake_force_n, profile.adhesion.max_brake_force_n(profile.mass_kg)) if mode is ControlMode.BRAKE else 0.0
    # 约束通过调整当前控制通道的实际力实现，而不是只截断 acceleration。
    # 这样 F = m*a 与能量积分使用同一个物理状态，避免“状态减速度已经限幅、
    # 但制动力能量仍按未限幅制动力积分”的不一致。
    mass = profile.effective_mass_kg
    raw_acceleration = (traction - braking - resistance) / mass
    if mode is ControlMode.TRACTION and raw_acceleration > max_acceleration_mps2:
        traction = max(0.0, max_acceleration_mps2 * mass + braking + resistance)
    elif mode is ControlMode.BRAKE and raw_acceleration < -max_deceleration_mps2:
        braking = max(0.0, traction - resistance + max_deceleration_mps2 * mass)
    acceleration = (traction - braking - resistance) / mass
    return ForceBalance(traction, braking, resistance, acceleration)


def integrate_step(
    profile: TrainBrakingProfile,
    state: LongitudinalState,
    mode: ControlMode,
    level: float,
    dt: float,
    gradient_per_mille: float,
    curve_radius_m: Optional[float],
    max_acceleration_mps2: float = 0.5,
    max_deceleration_mps2: float = 0.8,
    traction_limit_n: Optional[float] = None,
    boundary_position_m: Optional[float] = None,
) -> tuple[LongitudinalState, ForceBalance]:
    if not math.isfinite(dt) or dt <= 0.0:
        raise ValueError("dt 必须为正有限值")
    if boundary_position_m is not None and not math.isfinite(boundary_position_m):
        raise ValueError("boundary_position_m 必须为有限值")
    balance = force_balance(
        profile, state, mode, level, gradient_per_mille, curve_radius_m,
        max_acceleration_mps2, max_deceleration_mps2, traction_limit_n,
    )
    acceleration = balance.acceleration_mps2
    if state.speed_mps <= 0.0 and acceleration < 0.0:
        balance = ForceBalance(balance.traction_force_n, 0.0, balance.resistance_force_n, 0.0)
        acceleration = 0.0
    # A stopped train cannot continue integrating braking work. End the interval
    # at the stopping event, rather than clamping speed after a full time step.
    if acceleration < 0.0 and state.speed_mps > 0.0:
        dt = min(dt, state.speed_mps / -acceleration)
    next_speed = max(0.0, state.speed_mps + acceleration * dt)
    distance = (state.speed_mps + next_speed) * 0.5 * dt
    if boundary_position_m is not None:
        remaining = boundary_position_m - state.position_m
        if remaining <= 1.0e-9:
            return state, balance
        if distance >= remaining:
            end_speed = math.sqrt(max(0.0, state.speed_mps**2 + 2.0 * acceleration * remaining))
            denominator = state.speed_mps + end_speed
            if denominator > 1.0e-12:
                dt = 2.0 * remaining / denominator
            next_speed = end_speed
            distance = remaining
    next_position = state.position_m + distance
    return LongitudinalState(next_position, state.time_s + dt, next_speed), balance
