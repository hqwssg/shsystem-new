"""牵引电机再生制动模型：机械再生功率 -> 直流侧电功率。

职责边界：

    * 本模块只负责「电机侧」的再生能力包络与效率换算；
    * 不承担变流器动态（见 dc_dc_converter.py）与储能动态（见 storage_model.py）。

再生制动包络（恒转矩 + 恒功率）：

    v <  v_base:  F_regen_max(v) = max_regen_force_n              （恒转矩区）
    v >= v_base:  F_regen_max(v) = max_regen_power_w / v          （恒功率区）
    v_base = max_regen_power_w / max_regen_force_n

数据状态：包络与效率均为 assumed / placeholder，无实测特性曲线。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .train_braking_model import _finite, _non_negative


class MotorModelError(ValueError):
    """电机参数或输入不合法。"""


@dataclass(frozen=True)
class DCLinkWindow:
    min_v: float
    nominal_v: float
    max_v: float

    def __post_init__(self) -> None:
        for name in ("min_v", "nominal_v", "max_v"):
            _non_negative(getattr(self, name), f"dc_link.{name}")
        if not self.min_v < self.nominal_v < self.max_v:
            raise MotorModelError("直流母线电压窗口必须满足 min_v < nominal_v < max_v")

    def clamp(self, voltage_v: float) -> float:
        return min(max(voltage_v, self.min_v), self.max_v)


#: 方案问题 26（本模块新发现）：``RegenEfficiencyModel.peak_load_ratio`` 曾被
#: **声明但从未消费**——它出现在 ``motor_parameters.json``（``0.75``）、dataclass 字段与
#: ``from_parameters`` 读取处，而 :meth:`RegenEfficiencyModel.efficiency` 的公式里没有它。
#: 后果：JSON 中 ``peak: 0.9`` 与 ``peak_load_ratio: 0.75`` 并排，读者会合理推断
#: 「效率在 75% 负载处取峰值」，而实际曲线在 ``load_ratio = 1.0`` 才取峰值——属于
#: 项目纪律禁止的「静默选一种解释而不留痕」。修复：让该参数真正进入公式（把负载率
#: 归一化到峰值负载点），并把占位值定为 ``1.0``，使曲线与历史文档口径**逐位一致**
#: （``peak_load_ratio = 1.0`` 时归一化退化为恒等）。
SCHEME_ISSUE_UNUSED_PEAK_LOAD_RATIO = 26


@dataclass(frozen=True)
class RegenEfficiencyModel:
    """可解释的解析效率近似（非实测效率云图）。

    负载率先按 ``peak_load_ratio`` 归一化，使效率在 ``load_ratio = peak_load_ratio``
    处达到峰值、之上不再变化（工程上等价于「效率随负载升到额定点后走平」）：

        r   = min(load_ratio, peak_load_ratio) / peak_load_ratio
        eta = peak - low_load_penalty * (1 - r)^2
                  - low_speed_penalty * max(0, (v_ref - v) / v_ref)^2

    结果截断到 ``[0.05, peak]``。

    当前占位值 ``peak_load_ratio = 1.0``（见 :data:`SCHEME_ISSUE_UNUSED_PEAK_LOAD_RATIO`）
    使 ``r ≡ load_ratio``，公式**退化为**与历史文档逐位一致的单调形式
    ``eta = peak - low_load_penalty * (1 - load_ratio)^2``；
    取更小的值即把峰值前移到部分负载，供实测效率云图到位后标定。
    """

    peak: float
    peak_load_ratio: float
    low_load_penalty: float
    low_speed_penalty: float
    low_speed_reference_m_per_s: float

    def __post_init__(self) -> None:
        peak = _finite(self.peak, "regen_efficiency.peak")
        if not 0.0 < peak <= 1.0:
            raise MotorModelError("regen_efficiency.peak 必须在 (0, 1] 内")
        peak_load_ratio = _finite(self.peak_load_ratio, "regen_efficiency.peak_load_ratio")
        if not 0.0 < peak_load_ratio <= 1.0:
            raise MotorModelError("regen_efficiency.peak_load_ratio 必须在 (0, 1] 内")
        _non_negative(self.low_load_penalty, "low_load_penalty")
        _non_negative(self.low_speed_penalty, "low_speed_penalty")
        _non_negative(self.low_speed_reference_m_per_s, "low_speed_reference_m_per_s")

    def efficiency(self, load_ratio: float, speed_mps: float) -> float:
        ratio = min(max(_finite(load_ratio, "load_ratio"), 0.0), 1.0)
        # 负载率归一化到峰值负载点：peak_load_ratio = 1.0 时 r ≡ ratio（历史口径）。
        r = min(ratio, self.peak_load_ratio) / self.peak_load_ratio
        value = self.peak - self.low_load_penalty * (1.0 - r) ** 2
        if self.low_speed_reference_m_per_s > 0.0:
            deficit = max(0.0, (self.low_speed_reference_m_per_s - speed_mps) / self.low_speed_reference_m_per_s)
            value -= self.low_speed_penalty * deficit**2
        return min(max(value, 0.05), self.peak)


@dataclass(frozen=True)
class MotorParameters:
    max_regen_power_w: float
    max_regen_force_n: float
    min_regen_speed_m_per_s: float
    base_speed_m_per_s: float
    efficiency: RegenEfficiencyModel
    dc_link: DCLinkWindow
    overvoltage_derate_start_v: float
    overvoltage_derate_end_v: float
    data_status: str = "unknown"
    provenance: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _non_negative(self.max_regen_power_w, "max_regen_power_w")
        _non_negative(self.max_regen_force_n, "max_regen_force_n")
        _non_negative(self.min_regen_speed_m_per_s, "min_regen_speed_m_per_s")
        if self.max_regen_power_w <= 0.0 or self.max_regen_force_n <= 0.0:
            raise MotorModelError("再生功率与再生力上限必须为正")
        if self.base_speed_m_per_s <= 0.0:
            raise MotorModelError("base_speed_m_per_s 必须为正")
        if not self.overvoltage_derate_start_v < self.overvoltage_derate_end_v:
            raise MotorModelError("必须满足 overvoltage_derate_start_v < overvoltage_derate_end_v")

    def regen_force_limit_n(self, speed_mps: float) -> float:
        """给定速度下的再生制动力包络（N）。"""

        speed = max(0.0, speed_mps)
        if speed < self.min_regen_speed_m_per_s:
            return 0.0
        if speed <= self.base_speed_m_per_s:
            return self.max_regen_force_n
        return self.max_regen_power_w / speed

    def dc_link_derating(self, dc_link_voltage_v: float) -> float:
        """直流母线过压时的再生能力衰减系数（∈[0, 1]）。

        物理机制：母线电压超过阈值后，牵引传动为保护 IGBT 与直流环节会主动
        降低再生（电）制动投入比例，不足的制动力转由摩擦制动承担。
        这是真实系统存在的过压保护行为，不是人为的数值技巧。
        """

        voltage = _finite(dc_link_voltage_v, "dc_link_voltage_v")
        if voltage <= self.overvoltage_derate_start_v:
            return 1.0
        span = self.overvoltage_derate_end_v - self.overvoltage_derate_start_v
        ratio = (voltage - self.overvoltage_derate_start_v) / span
        return max(0.0, 1.0 - min(ratio, 1.0))

    @classmethod
    def from_parameters(cls, payload: Mapping[str, Any]) -> "MotorParameters":
        max_power = _finite(payload.get("max_regen_power_w"), "max_regen_power_w")
        max_force = _finite(payload.get("max_regen_force_n"), "max_regen_force_n")
        base = payload.get("base_speed_m_per_s")
        base_speed = _finite(base, "base_speed_m_per_s") if base is not None else max_power / max_force

        eff_raw = payload.get("regen_efficiency") or {}
        dc_raw = payload.get("dc_link_voltage_window") or {}

        derate_start = payload.get("overvoltage_derate_start_v")
        derate_end = payload.get("overvoltage_derate_end_v")
        if derate_start is None:
            derate_start = 1.02 * float(dc_raw.get("nominal_v"))
        if derate_end is None:
            derate_end = float(dc_raw.get("max_v"))

        return cls(
            max_regen_power_w=max_power,
            max_regen_force_n=max_force,
            min_regen_speed_m_per_s=_finite(payload.get("min_regen_speed_m_per_s", 0.0), "min_regen_speed_m_per_s"),
            base_speed_m_per_s=base_speed,
            efficiency=RegenEfficiencyModel(
                peak=_finite(eff_raw.get("peak"), "regen_efficiency.peak"),
                peak_load_ratio=_finite(
                    eff_raw.get("peak_load_ratio", 1.0), "regen_efficiency.peak_load_ratio"
                ),
                low_load_penalty=_finite(eff_raw.get("low_load_penalty", 0.0), "regen_efficiency.low_load_penalty"),
                low_speed_penalty=_finite(eff_raw.get("low_speed_penalty", 0.0), "regen_efficiency.low_speed_penalty"),
                low_speed_reference_m_per_s=_finite(
                    eff_raw.get("low_speed_reference_m_per_s", 0.0),
                    "regen_efficiency.low_speed_reference_m_per_s",
                ),
            ),
            dc_link=DCLinkWindow(
                min_v=_finite(dc_raw.get("min_v"), "dc_link_voltage_window.min_v"),
                nominal_v=_finite(dc_raw.get("nominal_v"), "dc_link_voltage_window.nominal_v"),
                max_v=_finite(dc_raw.get("max_v"), "dc_link_voltage_window.max_v"),
            ),
            overvoltage_derate_start_v=_finite(derate_start, "overvoltage_derate_start_v"),
            overvoltage_derate_end_v=_finite(derate_end, "overvoltage_derate_end_v"),
            data_status=str(payload.get("data_status", "unknown")),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass(frozen=True)
class MotorRegenResult:
    """电机侧再生制动分解结果。"""

    wheel_regen_force_n: float
    wheel_regen_power_w: float
    envelope_force_limit_n: float
    envelope_power_limit_w: float
    rejected_force_n: float
    rejected_power_w: float
    friction_force_n: float
    friction_power_w: float
    efficiency: float
    load_ratio: float
    electrical_power_w: float
    dc_current_a: float
    dc_link_derating: float
    limited_by: str

    @property
    def active(self) -> bool:
        return self.wheel_regen_power_w > 0.0


def convert_wheel_regen(
    motor: MotorParameters,
    wheel_regen_force_n: float,
    wheel_regen_power_w: float,
    total_brake_force_n: float,
    total_brake_power_w: float,
    speed_mps: float,
    dc_link_voltage_v: Optional[float] = None,
) -> MotorRegenResult:
    """把列车侧给出的再生制动力/功率，按电机包络与效率折算到直流侧。

    被包络削减掉的再生功率不会消失，而是转入摩擦制动（friction_* 字段），
    从而保证「机械制动总功率 = 再生 + 摩擦」。

    .. note::
       **上述恒等式的前提是输入自洽**，即 ``wheel_regen_power_w ≤ total_brake_power_w``
       （等价地 ``|wheel_regen_force_n| ≤ total_brake_force_n``）。
       若调用方传入 ``再生功率 > 机械制动总功率`` 这种自相矛盾的组合，
       ``friction_power`` 会因 ``max(0, ...)`` 截断为 0，恒等式不再成立
       （本函数**不**对越界的 ``wheel_regen_*`` 做二次夹取，也不报错）。

       生产路径始终满足该前提：:func:`~regenerative_braking.dynamics.train_braking_model.evaluate_braking`
       按 ``regen_wheel_force_n = min(brake_force_n, …)`` 构造输入，因此
       ``regen_wheel_power_w = regen_wheel_force_n · v ≤ brake_force_n · v = mechanical_braking_power_w``。
       实测（``tools/probe_robustness_sweep.py``，4000 个随机工况）契约内最大守恒残差
       ``7.45e-09 W``（相对 ``~1e-14``）。
    """

    speed = max(0.0, speed_mps)
    envelope_force_limit = motor.regen_force_limit_n(speed)
    envelope_power_limit = envelope_force_limit * speed

    raw_voltage = dc_link_voltage_v if dc_link_voltage_v is not None else motor.dc_link.nominal_v
    voltage = motor.dc_link.clamp(raw_voltage)
    derating = motor.dc_link_derating(raw_voltage)
    effective_power_limit = envelope_power_limit * derating

    limited_by = "none"
    if speed < motor.min_regen_speed_m_per_s:
        limited_by = "low_speed"
    elif derating < 1.0 - 1e-9:
        limited_by = "dc_link_overvoltage"
    elif envelope_force_limit + 1e-9 < abs(wheel_regen_force_n):
        limited_by = "envelope"

    wheel_force = min(abs(wheel_regen_force_n), envelope_force_limit)
    if speed > 0.0:
        wheel_force = min(wheel_force, effective_power_limit / speed)
    else:
        wheel_force = 0.0
    wheel_power = min(max(0.0, wheel_regen_power_w), effective_power_limit, wheel_force * speed)

    rejected_force = max(0.0, abs(wheel_regen_force_n) - wheel_force)
    rejected_power = max(0.0, max(0.0, wheel_regen_power_w) - wheel_power)

    friction_force = max(0.0, total_brake_force_n - wheel_force)
    friction_power = max(0.0, total_brake_power_w - wheel_power)

    load_ratio = wheel_power / motor.max_regen_power_w if motor.max_regen_power_w > 0.0 else 0.0
    efficiency = motor.efficiency.efficiency(load_ratio, speed) if wheel_power > 0.0 else 0.0
    electrical_power = wheel_power * efficiency
    dc_current = electrical_power / voltage if voltage > 0.0 else 0.0

    return MotorRegenResult(
        wheel_regen_force_n=wheel_force,
        wheel_regen_power_w=wheel_power,
        envelope_force_limit_n=envelope_force_limit,
        envelope_power_limit_w=envelope_power_limit,
        rejected_force_n=rejected_force,
        rejected_power_w=rejected_power,
        friction_force_n=friction_force,
        friction_power_w=friction_power,
        efficiency=efficiency,
        load_ratio=min(max(load_ratio, 0.0), 1.0),
        electrical_power_w=electrical_power,
        dc_current_a=dc_current,
        dc_link_derating=derating,
        limited_by=limited_by,
    )


def regen_envelope_curve(motor: MotorParameters, speeds_mps: list) -> list:
    """给定速度序列的再生功率包络，便于验证与画图。"""

    curve = []
    for speed in speeds_mps:
        force = motor.regen_force_limit_n(speed)
        curve.append(
            {
                "speed_mps": speed,
                "speed_kmh": speed * 3.6,
                "force_limit_n": force,
                "power_limit_w": force * max(0.0, speed),
            }
        )
    return curve
