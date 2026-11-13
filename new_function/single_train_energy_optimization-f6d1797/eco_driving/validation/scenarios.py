"""eco-driving 第一批可复现场景。"""

from __future__ import annotations

from dataclasses import replace

from ..models import EcoDrivingScenario, RunConstraints


def default_scenarios() -> tuple[EcoDrivingScenario, ...]:
    base = RunConstraints(target_speed_mps=18.0, terminal_speed_mps=0.0, runtime_tolerance_s=10.0)
    return (
        EcoDrivingScenario(0.0, 2.0, 10.0, constraints=base, description="平直/基准区段"),
        EcoDrivingScenario(2.0, 4.0, 10.0, constraints=base, description="连续下坡区段"),
        EcoDrivingScenario(4.0, 6.0, 10.0, constraints=base, description="连续上坡区段"),
        EcoDrivingScenario(6.0, 8.0, 10.0, constraints=base, description="坡度变化区段"),
        EcoDrivingScenario(8.0, 10.0, 10.0, constraints=replace(base, target_speed_mps=12.0), description="限速约束区段"),
    )
