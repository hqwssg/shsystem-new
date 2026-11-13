"""速度曲线的物理与运行约束检查。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from ..models import EcoDrivingResult, RunConstraints


@dataclass(frozen=True)
class ValidationReport:
    feasible: bool
    violations: tuple[str, ...]


def validate_profile(result: EcoDrivingResult, constraints: RunConstraints) -> ValidationReport:
    violations: list[str] = []
    constraint_values = (
        constraints.runtime_tolerance_s,
        constraints.terminal_speed_mps,
        constraints.max_acceleration_mps2,
        constraints.max_deceleration_mps2,
    )
    optional_constraint_values = (
        constraints.target_runtime_s,
        constraints.target_speed_mps,
    )
    if (
        not all(math.isfinite(value) and value >= 0.0 for value in constraint_values)
        or any(value is not None and (not math.isfinite(value) or value < 0.0) for value in optional_constraint_values)
    ):
        return ValidationReport(False, ("运行约束包含无效参数",))
    samples = result.samples
    if not samples:
        return ValidationReport(False, ("轨迹为空",))
    if not bool(result.metadata.get("reached_end", True)):
        violations.append("仿真未到达终点")
    previous = None
    for index, sample in enumerate(samples):
        finite_values = (
            sample.position_m,
            sample.time_s,
            sample.speed_mps,
            sample.acceleration_mps2,
        )
        if not all(math.isfinite(value) for value in finite_values):
            violations.append(f"第 {index} 点存在非有限状态量")
            continue
        if sample.speed_limit_mps is not None and (
            not math.isfinite(sample.speed_limit_mps) or sample.speed_limit_mps < 0.0
        ):
            violations.append(f"第 {index} 点限速无效")
        if sample.speed_mps < -1e-9:
            violations.append(f"第 {index} 点速度为负")
        if sample.speed_limit_mps is not None and sample.speed_mps > sample.speed_limit_mps + 1e-6:
            violations.append(f"第 {index} 点超过限速")
        acceleration = sample.acceleration_mps2
        if acceleration > constraints.max_acceleration_mps2 + 1e-6:
            violations.append(f"第 {index} 点加速度超限")
        elif acceleration < -constraints.max_deceleration_mps2 - 1e-6:
            violations.append(f"第 {index} 点减速度超限")
        if previous is not None:
            if sample.position_m < previous.position_m - 1e-9:
                violations.append(f"第 {index} 点位置倒退")
            interval = sample.time_s - previous.time_s
            if interval <= 1e-9:
                violations.append(f"第 {index} 点时间倒退")
            else:
                speed_delta = sample.speed_mps - previous.speed_mps
                allowed_delta = (
                    constraints.max_acceleration_mps2 * interval
                    if speed_delta >= 0.0
                    else constraints.max_deceleration_mps2 * interval
                )
                if abs(speed_delta) > allowed_delta + 1e-5:
                    violations.append(f"第 {index} 点速度跳变")
        previous = sample
    if constraints.target_runtime_s is not None and abs(result.runtime_s - constraints.target_runtime_s) > constraints.runtime_tolerance_s:
        violations.append("运行时分超出容差")
    if abs(result.final_speed_mps - constraints.terminal_speed_mps) > 0.5:
        violations.append("终点速度不满足约束")
    return ValidationReport(not violations, tuple(dict.fromkeys(violations)))
