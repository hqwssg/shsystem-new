"""eco-driving 的数据契约和轨迹数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Tuple


class ControlMode(str, Enum):
    TRACTION = "traction"
    COAST = "coast"
    BRAKE = "brake"


@dataclass(frozen=True)
class RunConstraints:
    target_runtime_s: Optional[float] = None
    runtime_tolerance_s: float = 5.0
    terminal_speed_mps: float = 0.0
    max_acceleration_mps2: float = 0.5
    max_deceleration_mps2: float = 0.8
    target_speed_mps: Optional[float] = None


@dataclass(frozen=True)
class EcoDrivingScenario:
    start_km: float
    end_km: float
    initial_speed_mps: float
    train_profile_id: str = "shuohuang_heavy_c80_placeholder"
    constraints: RunConstraints = field(default_factory=RunConstraints)
    data_status: str = "assumed"
    description: str = ""

    @property
    def length_m(self) -> float:
        return max(0.0, (self.end_km - self.start_km) * 1000.0)


@dataclass(frozen=True)
class ProfileSample:
    position_m: float
    time_s: float
    speed_mps: float
    gradient_per_mille: float
    curve_radius_m: Optional[float]
    speed_limit_mps: Optional[float]
    acceleration_mps2: float
    mode: ControlMode
    traction_force_n: float
    braking_force_n: float
    traction_power_w: float
    braking_power_w: float
    cumulative_traction_energy_j: float
    cumulative_mechanical_braking_energy_j: float
    cumulative_regenerative_energy_j: float
    cumulative_net_energy_j: float

    @property
    def speed_kmh(self) -> float:
        return self.speed_mps * 3.6


@dataclass(frozen=True)
class EcoDrivingResult:
    samples: Tuple[ProfileSample, ...]
    data_status: str
    disclaimer: str = "仿真结果，不作为工程结论"
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def runtime_s(self) -> float:
        return self.samples[-1].time_s if self.samples else 0.0

    @property
    def final_speed_mps(self) -> float:
        return self.samples[-1].speed_mps if self.samples else 0.0
