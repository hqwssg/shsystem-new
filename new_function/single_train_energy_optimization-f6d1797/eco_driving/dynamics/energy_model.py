"""eco-driving 轨迹能量台账。"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class EnergyLedger:
    traction_energy_j: float = 0.0
    mechanical_braking_energy_j: float = 0.0
    available_regenerative_energy_j: float = 0.0
    captured_regenerative_energy_j: float = 0.0

    def add_step(
        self,
        traction_power_w: float,
        braking_power_w: float,
        dt: float,
        regen_efficiency: float = 0.85,
        regen_power_w: float | None = None,
    ) -> None:
        """累计一步能量。

        ``regen_power_w`` 为该步电制动（再生）轮周功率；给出时只有这部分
        制动功率可回收，其余为空气/踏面摩擦制动。缺省（None）保持旧口径：
        全部制动功率按效率计为可回收，仅供无机车电制动数据的旧调用使用。
        """

        values = (traction_power_w, braking_power_w, dt, regen_efficiency)
        if regen_power_w is not None:
            values = values + (regen_power_w,)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("能量台账输入必须为有限数值")
        if dt < 0.0:
            raise ValueError("能量台账 dt 不得为负")
        if not 0.0 <= regen_efficiency <= 1.0:
            raise ValueError("regen_efficiency 必须在 [0, 1] 内")
        self.traction_energy_j += max(0.0, traction_power_w) * dt
        braking = max(0.0, braking_power_w)
        mechanical = braking * dt
        self.mechanical_braking_energy_j += mechanical
        recoverable_power = braking if regen_power_w is None else min(braking, max(0.0, regen_power_w))
        available = recoverable_power * dt * max(0.0, min(1.0, regen_efficiency))
        self.available_regenerative_energy_j += available
        self.captured_regenerative_energy_j += available

    @property
    def net_energy_j(self) -> float:
        return self.traction_energy_j - self.captured_regenerative_energy_j

    def as_dict(self) -> dict[str, float]:
        return {
            "traction_energy_kwh": self.traction_energy_j / 3.6e6,
            "mechanical_braking_energy_kwh": self.mechanical_braking_energy_j / 3.6e6,
            "available_regenerative_energy_kwh": self.available_regenerative_energy_j / 3.6e6,
            "captured_regenerative_energy_kwh": self.captured_regenerative_energy_j / 3.6e6,
            "net_energy_kwh": self.net_energy_j / 3.6e6,
        }


def regen_wheel_force_n(profile, braking_force_n: float, speed_mps: float) -> float:
    """按机车电制动能力拆出制动力中的再生（电制动）部分。

    与 ``regenerative_braking.evaluate_braking`` 同一口径：电制动能力取共享编组
    曲线 ``force_limit_n(v)``（已含台数与级位），缺曲线时退化为
    ``max_regen_force_n × electrical_level``，并受 ``regen_fraction_cap`` 约束。
    空气制动部分不能计为可回收能量。
    """

    brake = max(0.0, float(braking_force_n))
    if brake <= 0.0:
        return 0.0
    curve = getattr(profile, "regen_force_curve", None)
    if curve is not None:
        capacity = curve.force_limit_n(max(0.0, float(speed_mps)))
    else:
        capacity = float(getattr(profile, "max_regen_force_n", brake)) * float(
            getattr(profile, "electrical_level", 1.0)
        )
    cap = float(getattr(profile, "regen_fraction_cap", 1.0))
    return max(0.0, min(brake, capacity, cap * brake))
