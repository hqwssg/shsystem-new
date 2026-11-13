"""储能系统模型：SOC 约束 + 功率约束 + 能量守恒。

能量守恒关系（单元测试直接验证）：

    充电：ΔE_stored = eta_ch * ∫P_charge_terminal dt
    放电：ΔE_stored = -∫P_discharge_terminal dt / eta_dis

约束优先级（任一触发即削减功率，并记录 limit_reason）：

    1) 功率上限        charge_power_limit / discharge_power_limit
    2) SOC 上限        soc_max（充电余量）
    3) SOC 下限        soc_min（放电余量）

数据状态：容量 / 往返效率 / 最大充电功率为 real（来自共享 battery.json）；
最大放电功率为 assumed（原文件为 missing_conservative_zero）；
soc_min / soc_max / 额定电压为 assumed / placeholder。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional

from .train_braking_model import _finite, _non_negative


class StorageModelError(ValueError):
    """储能参数或输入不合法。"""


@dataclass(frozen=True)
class StorageParameters:
    capacity_j: float
    charge_efficiency: float
    discharge_efficiency: float
    soc_min: float
    soc_max: float
    soc_initial: float
    max_charge_power_w: float
    max_discharge_power_w: float
    nominal_voltage_v: float
    internal_resistance_ohm: float = 0.0
    data_status: str = "unknown"
    provenance: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        capacity = _finite(self.capacity_j, "capacity_j")
        if capacity <= 0.0:
            raise StorageModelError("capacity_j 必须为正")
        for name in ("charge_efficiency", "discharge_efficiency"):
            value = _finite(getattr(self, name), name)
            if not 0.0 < value <= 1.0:
                raise StorageModelError(f"{name} 必须在 (0, 1] 内，实际为 {value!r}")
        lo, hi = _finite(self.soc_min, "soc_min"), _finite(self.soc_max, "soc_max")
        if not 0.0 <= lo < hi <= 1.0:
            raise StorageModelError("必须满足 0 <= soc_min < soc_max <= 1")
        init = _finite(self.soc_initial, "soc_initial")
        if not lo <= init <= hi:
            raise StorageModelError(f"soc_initial 必须落在 [soc_min, soc_max] 内，实际为 {init!r}")
        _non_negative(self.max_charge_power_w, "max_charge_power_w")
        _non_negative(self.max_discharge_power_w, "max_discharge_power_w")
        nominal_voltage = _finite(self.nominal_voltage_v, "nominal_voltage_v")
        if nominal_voltage <= 0.0:
            raise StorageModelError("nominal_voltage_v 必须为正")
        internal_resistance = _finite(self.internal_resistance_ohm, "internal_resistance_ohm")
        if internal_resistance <= 0.0:
            raise StorageModelError("internal_resistance_ohm 必须为正")

    @property
    def capacity_kwh(self) -> float:
        return self.capacity_j / 3.6e6

    @property
    def round_trip_efficiency(self) -> float:
        return self.charge_efficiency * self.discharge_efficiency

    @classmethod
    def from_parameters(cls, payload: Mapping[str, Any]) -> "StorageParameters":
        capacity_j = payload.get("capacity_j")
        if capacity_j is None:
            capacity_kwh = _finite(payload.get("capacity_kwh"), "capacity_kwh")
            capacity_j = capacity_kwh * 3.6e6
        return cls(
            capacity_j=_finite(capacity_j, "capacity_j"),
            charge_efficiency=_finite(payload.get("charge_efficiency"), "charge_efficiency"),
            discharge_efficiency=_finite(payload.get("discharge_efficiency"), "discharge_efficiency"),
            soc_min=_finite(payload.get("soc_min"), "soc_min"),
            soc_max=_finite(payload.get("soc_max"), "soc_max"),
            soc_initial=_finite(payload.get("soc_initial", 0.5), "soc_initial"),
            max_charge_power_w=_finite(payload.get("max_charge_power_w"), "max_charge_power_w"),
            max_discharge_power_w=_finite(payload.get("max_discharge_power_w"), "max_discharge_power_w"),
            nominal_voltage_v=_finite(payload.get("nominal_voltage_v"), "nominal_voltage_v"),
            internal_resistance_ohm=_finite(payload.get("internal_resistance_ohm", 0.0), "internal_resistance_ohm"),
            data_status=str(payload.get("data_status", "unknown")),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class StorageState:
    soc: float
    energy_j: float

    @classmethod
    def from_soc(cls, soc: float, params: StorageParameters) -> "StorageState":
        return cls(soc=soc, energy_j=soc * params.capacity_j)


@dataclass(frozen=True)
class StorageStepResult:
    """单步储能结算结果（功率 W，能量 J）。"""

    soc_before: float
    soc_after: float
    energy_before_j: float
    energy_after_j: float

    requested_power_w: float
    accepted_power_w: float
    curtailed_power_w: float
    charge_power_w: float
    discharge_power_w: float

    stored_energy_delta_j: float
    loss_j: float
    limit_reason: str
    soc_saturated: bool

    @property
    def is_charging(self) -> bool:
        return self.charge_power_w > 0.0

    @property
    def is_discharging(self) -> bool:
        return self.discharge_power_w > 0.0


class StorageSystem:
    """储能系统（SOC 状态机 + 功率约束）。"""

    def __init__(self, params: StorageParameters, state: Optional[StorageState] = None) -> None:
        self.params = params
        self.state = state or StorageState.from_soc(params.soc_initial, params)

    # ---------- 可用功率 ----------
    def available_charge_power_w(self, dt: float) -> float:
        """考虑 SOC 上限与功率上限的**端口**可用充电功率。

        ``requested_power_w`` 是储能端口功率，而 SOC 增量只保留
        ``charge_efficiency``。因此端口功率上限必须满足
        ``eta_ch * P_port * dt <= E_headroom``；此前直接用
        ``E_headroom / dt`` 会在效率小于 1 时提前削减充电请求。
        """

        dt = _finite(dt, "dt")
        if dt <= 0.0:
            raise StorageModelError("dt 必须为正")
        headroom_j = max(0.0, (self.params.soc_max - self.state.soc) * self.params.capacity_j)
        headroom_power = headroom_j / (self.params.charge_efficiency * dt)
        return max(0.0, min(self.params.max_charge_power_w, headroom_power))

    def available_discharge_power_w(self, dt: float) -> float:
        """考虑 SOC 下限与功率上限的可用放电功率。"""

        dt = _finite(dt, "dt")
        if dt <= 0.0:
            raise StorageModelError("dt 必须为正")
        available_j = max(0.0, (self.state.soc - self.params.soc_min) * self.params.capacity_j)
        available_power = available_j * self.params.discharge_efficiency / dt
        return max(0.0, min(self.params.max_discharge_power_w, available_power))

    # ---------- 单步 ----------
    def step(self, requested_power_w: float, dt: float) -> StorageStepResult:
        """推进一个仿真步。

        Args:
            requested_power_w: 储能端请求功率，>0 为充电（吸收再生能量），<0 为放电。
            dt: 步长（s）。
        """

        dt = _finite(dt, "dt")
        if dt <= 0.0:
            raise StorageModelError("dt 必须为正")
        request = _finite(requested_power_w, "requested_power_w")

        params = self.params
        soc_before = self.state.soc
        energy_before = self.state.energy_j

        reason = "none"
        if request >= 0.0:
            limit = self.available_charge_power_w(dt)
            accepted = min(request, limit)
            if accepted + 1e-12 < request:
                # limit = min(max_charge_power_w, soc_headroom_power)：
                # 只有当 headroom 严格小于功率上限时，限制原因才是 SOC 触顶。
                reason = "soc_max_limit" if limit < params.max_charge_power_w - 1e-12 else "charge_power_limit"
            charge_power = accepted
            discharge_power = 0.0
            stored_delta = params.charge_efficiency * accepted * dt
            loss_j = (1.0 - params.charge_efficiency) * accepted * dt
        else:
            limit = self.available_discharge_power_w(dt)
            accepted = -min(-request, limit)
            if accepted > request + 1e-12:
                # 同上：limit = min(max_discharge_power_w, soc_headroom_power)。
                reason = "soc_min_limit" if limit < params.max_discharge_power_w - 1e-12 else "discharge_power_limit"
            charge_power = 0.0
            discharge_power = -accepted
            delivered_energy = discharge_power * dt
            stored_delta = -delivered_energy / params.discharge_efficiency
            loss_j = delivered_energy / params.discharge_efficiency - delivered_energy

        new_energy = energy_before + stored_delta
        # 数值上把 SOC 严格夹在 [soc_min, soc_max]（物理硬边界）
        new_energy = min(max(new_energy, params.soc_min * params.capacity_j), params.soc_max * params.capacity_j)
        new_soc = new_energy / params.capacity_j

        if not math.isfinite(new_soc):
            raise StorageModelError(f"SOC 更新出现非有限值：{new_soc!r}")

        self.state = StorageState(soc=new_soc, energy_j=new_energy)

        return StorageStepResult(
            soc_before=soc_before,
            soc_after=new_soc,
            energy_before_j=energy_before,
            energy_after_j=new_energy,
            requested_power_w=request,
            accepted_power_w=accepted,
            curtailed_power_w=request - accepted,
            charge_power_w=charge_power,
            discharge_power_w=discharge_power,
            stored_energy_delta_j=new_energy - energy_before,
            loss_j=loss_j,
            limit_reason=reason,
            soc_saturated=(new_soc <= params.soc_min + 1e-12) or (new_soc >= params.soc_max - 1e-12),
        )

    # ---------- 辅助 ----------
    def terminal_voltage_v(self, current_a: float) -> float:
        """储能端电压 = 额定电压 - 内阻压降（符号按电流方向）。"""

        return self.params.nominal_voltage_v - self.params.internal_resistance_ohm * current_a

    def reset(self, soc: Optional[float] = None) -> None:
        target = self.params.soc_initial if soc is None else soc
        if not self.params.soc_min <= target <= self.params.soc_max:
            raise StorageModelError(f"reset soc 超出 [soc_min, soc_max]：{target!r}")
        self.state = StorageState.from_soc(target, self.params)

    def snapshot(self) -> Mapping[str, float]:
        return {
            "soc": self.state.soc,
            "energy_j": self.state.energy_j,
            "energy_kwh": self.state.energy_j / 3.6e6,
            "soc_min": self.params.soc_min,
            "soc_max": self.params.soc_max,
        }


def soc_trajectory_is_bounded(soc_values: List[float], params: StorageParameters, tolerance: float = 1e-9) -> bool:
    """校验 SOC 轨迹始终落在 [soc_min, soc_max] 内。"""

    return all(params.soc_min - tolerance <= value <= params.soc_max + tolerance for value in soc_values)
