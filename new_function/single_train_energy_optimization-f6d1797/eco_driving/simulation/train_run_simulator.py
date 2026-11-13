"""基于距离区段的单列车运行仿真。"""

from __future__ import annotations

import math
from typing import Callable, Optional

from ..dynamics.energy_model import EnergyLedger, regen_wheel_force_n
from ..dynamics.train_longitudinal_model import LongitudinalState, integrate_step
from ..models import ControlMode, EcoDrivingResult, EcoDrivingScenario, ProfileSample


ActionPolicy = Callable[[LongitudinalState, float, Optional[float], float], tuple[ControlMode, float]]

#: 静止且无位移的连续步数上限；超过即判定停滞并终止仿真。
STALL_STEP_LIMIT = 600


def simulate(
    scenario: EcoDrivingScenario,
    profile,
    policy: ActionPolicy,
    dt: float = 1.0,
    regen_efficiency: float = 0.85,
    traction_limit_n: Optional[float] = None,
    max_steps: int = 200000,
) -> EcoDrivingResult:
    if not math.isfinite(dt) or dt <= 0.0:
        raise ValueError("dt 必须为正有限值")
    if not math.isfinite(regen_efficiency) or not 0.0 <= regen_efficiency <= 1.0:
        raise ValueError("regen_efficiency 必须在 [0, 1] 内且为有限值")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
        raise ValueError("max_steps 必须为正")
    state = LongitudinalState(0.0, 0.0, scenario.initial_speed_mps)
    ledger = EnergyLedger()
    samples: list[ProfileSample] = []
    reached_end = False
    stalled_steps = 0
    for _ in range(max_steps):
        position_km = scenario.start_km + state.position_m / 1000.0
        if position_km >= scenario.end_km - 1.0e-9:
            reached_end = True
            break
        segment = policy.segment_at(position_km + 1.0e-9)
        if segment is None:
            segment = policy.segment_at(position_km)
        if segment is None:
            return EcoDrivingResult(
                tuple(samples), scenario.data_status,
                metadata={
                    "energy": ledger.as_dict(),
                    "steps": len(samples),
                    "reached_end": False,
                    "boundary_error": f"线路位置 {position_km:.6f} km 不在共享线路范围",
                },
            )
        gradient = segment.gradient_per_mille if segment else 0.0
        curve = segment.curve_radius_m if segment else None
        limit = segment.speed_limit_kmh / 3.6 if segment and segment.speed_limit_kmh else None
        remaining_m = scenario.length_m - state.position_m
        mode, level = policy(state, gradient, limit, remaining_m)
        next_state, balance = integrate_step(
            profile, state, mode, level, dt, gradient, curve,
            scenario.constraints.max_acceleration_mps2,
            scenario.constraints.max_deceleration_mps2,
            traction_limit_n,
            boundary_position_m=min(scenario.length_m, (segment.end_km - scenario.start_km) * 1000.0) if segment else scenario.length_m,
        )
        step_dt = next_state.time_s - state.time_s
        average_speed = (state.speed_mps + next_state.speed_mps) * 0.5
        traction_power = balance.traction_force_n * average_speed
        braking_power = balance.braking_force_n * average_speed
        regen_power = regen_wheel_force_n(profile, balance.braking_force_n, average_speed) * average_speed
        ledger.add_step(traction_power, braking_power, step_dt, regen_efficiency, regen_power_w=regen_power)
        samples.append(ProfileSample(
            position_m=state.position_m,
            time_s=state.time_s,
            speed_mps=state.speed_mps,
            gradient_per_mille=gradient,
            curve_radius_m=curve,
            speed_limit_mps=limit,
            acceleration_mps2=balance.acceleration_mps2,
            mode=mode,
            traction_force_n=balance.traction_force_n,
            braking_force_n=balance.braking_force_n,
            traction_power_w=traction_power,
            braking_power_w=braking_power,
            cumulative_traction_energy_j=ledger.traction_energy_j,
            cumulative_mechanical_braking_energy_j=ledger.mechanical_braking_energy_j,
            cumulative_regenerative_energy_j=ledger.captured_regenerative_energy_j,
            cumulative_net_energy_j=ledger.net_energy_j,
        ))
        state = next_state
        if (
            state.speed_mps <= 0.0
            and state.position_m <= samples[-1].position_m + 1.0e-9
            and state.position_m < scenario.length_m
        ):
            stalled_steps += 1
            if stalled_steps >= STALL_STEP_LIMIT:
                # 列车静止且连续多步无位移：策略/动力学已陷入停滞。继续空转只会
                # 生成数十万个静止样本并掩盖问题，显式报告未到达终点。
                return EcoDrivingResult(
                    tuple(samples), scenario.data_status,
                    metadata={
                        "energy": ledger.as_dict(),
                        "steps": len(samples),
                        "reached_end": False,
                        "stalled": True,
                        "stall_position_m": state.position_m,
                    },
                )
        else:
            stalled_steps = 0
        if state.position_m >= scenario.length_m:
            reached_end = True
            if samples:
                last = samples[-1]
                samples.append(ProfileSample(
                    position_m=scenario.length_m,
                    time_s=state.time_s,
                    speed_mps=state.speed_mps,
                    gradient_per_mille=last.gradient_per_mille,
                    curve_radius_m=last.curve_radius_m,
                    speed_limit_mps=last.speed_limit_mps,
                    acceleration_mps2=0.0,
                    mode=ControlMode.COAST,
                    traction_force_n=0.0,
                    braking_force_n=0.0,
                    traction_power_w=0.0,
                    braking_power_w=0.0,
                    cumulative_traction_energy_j=ledger.traction_energy_j,
                    cumulative_mechanical_braking_energy_j=ledger.mechanical_braking_energy_j,
                    cumulative_regenerative_energy_j=ledger.captured_regenerative_energy_j,
                    cumulative_net_energy_j=ledger.net_energy_j,
                ))
            break
    return EcoDrivingResult(
        tuple(samples), scenario.data_status,
        metadata={"energy": ledger.as_dict(), "steps": len(samples), "reached_end": reached_end},
    )
