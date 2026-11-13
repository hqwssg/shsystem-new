"""可解释的经验操纵 baseline。"""

from __future__ import annotations

import math
from dataclasses import replace

from ..models import ControlMode, EcoDrivingScenario
from ..simulation.train_run_simulator import simulate


class BaselinePolicy:
    def __init__(self, railway, scenario: EcoDrivingScenario, safety_margin_m: float = 20.0):
        self.railway = railway
        self.scenario = scenario
        self.target_speed = scenario.constraints.target_speed_mps
        if self.target_speed is None and scenario.constraints.target_runtime_s is not None and scenario.constraints.target_runtime_s > 0.0:
            avg_req_mps = scenario.length_m / scenario.constraints.target_runtime_s
            self.target_speed = min(22.22, avg_req_mps * 1.08)
        if not math.isfinite(safety_margin_m) or safety_margin_m < 0.0:
            raise ValueError("safety_margin_m 必须为非负有限值")
        self.safety_margin_m = float(safety_margin_m)

    def segment_at(self, position_km):
        return self.railway.segment_at(position_km)

    def _lookahead_limit(self, position_m: float, current_limit):
        """返回前方更低限速及到它的距离，用于提前制动。

        只比较当前场景范围内存在且更低的限速；当前限速为 None（无限制）时不触发前瞻。
        ``current_limit`` 为 None 时返回 (None, inf)，不做前瞻减速。
        """

        if current_limit is None:
            return None, float("inf")
        segments = getattr(self.railway, "segments", ())
        best_limit = None
        best_distance = float("inf")
        for segment in segments:
            limit_mps = segment.speed_limit_kmh / 3.6 if segment.speed_limit_kmh else None
            if limit_mps is None or limit_mps >= current_limit - 1e-9:
                continue
            start_m = (segment.start_km - self.scenario.start_km) * 1000.0
            if start_m < position_m - 1e-6 or start_m > self.scenario.length_m + 1e-6:
                # 已进入该段或超出当前运行终点；当前段内越限由逐采样点校验兜底，
                # 这里只处理当前场景内“前方尚未进入”的更低限速段。
                continue
            distance = start_m - position_m
            if distance < best_distance:
                best_distance = distance
                best_limit = limit_mps
        return best_limit, best_distance

    def __call__(self, state, gradient, speed_limit, remaining_m):
        limit_mps = speed_limit if speed_limit is not None else 22.22
        target = self.target_speed or limit_mps
        target = min(target, max(0.5, limit_mps - 0.3))
        # 前方限速更低时，仅在进入前瞻制动距离窗口后再压低目标速度并提前减速，
        # 避免刚发车就把全程目标速度锁死在远方限速，也避免过晚制动而越限。
        next_limit, next_distance = self._lookahead_limit(state.position_m, speed_limit)
        if next_limit is not None and next_limit < target - 1e-9:
            approach_distance = (
                max(0.0, max(state.speed_mps, target) ** 2 - next_limit ** 2) / (2.0 * 0.15)
                + self.safety_margin_m
            )
            if next_distance <= approach_distance:
                target = next_limit
                brake_distance = (
                    max(0.0, state.speed_mps ** 2 - next_limit ** 2) / (2.0 * 0.15)
                    + self.safety_margin_m
                )
                if state.speed_mps > next_limit and next_distance <= brake_distance:
                    return ControlMode.BRAKE, 1.0
        if state.speed_mps <= 0.2 and remaining_m > 0.0:
            return ControlMode.TRACTION, 0.25
        # 重载列车实际制动减速度通常明显低于约束上限；采用保守的
        # 0.15 m/s² 制动距离估计，避免“理论上来得及、实际到站超速”。
        stopping_distance = state.speed_mps ** 2 / (2.0 * 0.15) if state.speed_mps > 0.0 else 0.0
        if remaining_m <= max(20.0, stopping_distance + self.safety_margin_m):
            if state.speed_mps > 0.42:
                return ControlMode.BRAKE, 1.0
            if gradient < 0.0 and state.speed_mps > 0.35:
                return ControlMode.BRAKE, 0.20
            return ControlMode.COAST, 0.0
        # 下坡或超速硬保护：距离公布限速不足 0.1 m/s 时立即上闸，防止自由惰行超速
        if speed_limit is not None and state.speed_mps >= speed_limit - 0.1:
            return ControlMode.BRAKE, min(1.0, max(0.5, (state.speed_mps - (speed_limit - 0.3)) / 0.8))
        if state.speed_mps < target - 0.8:
            return ControlMode.TRACTION, min(1.0, max(0.25, (target - state.speed_mps) / 3.0))
        if state.speed_mps > target + 0.5:
            return ControlMode.BRAKE, min(1.0, (state.speed_mps - target) / 2.0)
        return ControlMode.COAST, 0.0


def run_baseline(
    scenario: EcoDrivingScenario,
    railway,
    profile,
    dt: float = 1.0,
    traction_limit_n=None,
    regen_efficiency: float = 0.85,
    safety_margin_m: float = 20.0,
):
    result = simulate(
        scenario, profile, BaselinePolicy(railway, scenario, safety_margin_m=safety_margin_m),
        dt=dt, traction_limit_n=traction_limit_n,
        regen_efficiency=regen_efficiency,
    )
    violations: list[str] = []
    if not bool(result.metadata.get("reached_end", False)):
        violations.append("未到达终点")
    for index, sample in enumerate(result.samples):
        if sample.speed_limit_mps is not None and sample.speed_mps > sample.speed_limit_mps + 1e-6:
            violations.append(f"第 {index} 点超过限速")
            break
    target = scenario.constraints.target_runtime_s
    if target is not None and abs(result.runtime_s - target) > scenario.constraints.runtime_tolerance_s:
        violations.append(
            f"运行时分超限: actual={result.runtime_s:.3f}s target={target:.3f}s "
            f"tol={scenario.constraints.runtime_tolerance_s:.3f}s"
        )
    if abs(result.final_speed_mps - scenario.constraints.terminal_speed_mps) > 0.5:
        violations.append(
            f"终点速度超限: actual={result.final_speed_mps:.3f}m/s "
            f"target={scenario.constraints.terminal_speed_mps:.3f}m/s"
        )
    metadata = dict(result.metadata)
    metadata.update({
        "feasible_candidate": not violations,
        "constraint_violations": tuple(violations),
        "safety_margin_m": float(safety_margin_m),
    })
    return replace(result, metadata=metadata)
