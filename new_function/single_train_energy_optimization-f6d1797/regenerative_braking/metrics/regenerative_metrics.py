"""再生制动指标：能量台账、波动指标、跟踪性能、控制代价。

能量口径（严格定义，避免"效率"口径混乱）：

    mechanical_braking_energy   轮周机械制动能量            ∫ F_brake * v dt
    available_regenerative_energy 电机可回馈到直流母线的电能量 ∫ P_motor_electrical dt
    captured_energy             储能端实际吸收的能量        ∫ P_accepted dt
    storage_energy              储能净存入能量              ΔE_stored
    loss_energy                 旧“总损耗”：未存入储能能量  mechanical - storage_energy
    physical_dissipation_energy 模型显式耗散（不含回网）    friction + motor + converter + inductor + grid_source + storage loss
    storage_net_of_grid_import_energy 保守储能收益          storage_energy - grid_import

闭合关系（单元测试直接验证）：

    mechanical = friction_braking + motor_loss + conversion_loss + inductor_loss
                 + grid_source_loss + storage_loss + storage_energy
                 + curtailed + reactive_energy + grid_net_export

    regenerative_efficiency = captured_energy / available_regenerative_energy
    capture_ratio           = captured_energy / mechanical_braking_energy

其中 grid_export 为**真正到达牵引网**的再生能量（理想源端口径）；
母线侧送出的功率里还有一部分耗散在源阻抗 R_src 上，单列为 grid_source_loss，
不得混入 grid_export。占空比为 0 的"无控制"工况下，全部再生能量都走这条通道，
如实记录而不是凭空消失。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np


class MetricsError(ValueError):
    """指标输入不合法。"""


#: 式(72) 电流积分路径与「力 × 速度 × 效率」路径的允许相对偏差。
#:
#: 两条路径的输入完全独立：前者查标准附录 L 的 ``I_z(v)`` 电流表、乘接触网
#: 电压；后者走轮周再生力、电机效率与直流母线。10% 是「电/机/空制动划分
#: 与效率假设仍自洽」的工程判据——超过它说明至少有一处数据或假设不自洽，
#: 需要复查电制动曲线、电流表或电机效率，而不是继续调控制器。
REGEN_CURRENT_CHECK_TOLERANCE = 0.10


def _kwh(energy_j: float) -> float:
    return energy_j / 3.6e6


ENERGY_ACCOUNTING_DEFINITIONS = {
    "captured_energy": "储能端吸收能量，尚未扣除储能充电损耗；历史 headline 保留",
    "storage_energy": "储能净存入能量 ΔE，来自每步储能能量增量",
    "grid_import_energy": "牵引网理想源端回吸能量，不与回网能量相抵后隐藏",
    "storage_net_of_grid_import_energy": "ΔE 减全部电网回吸；保守预算，不能据此识别每份能量的来源",
    "physical_dissipation_energy": "模型显式耗散之和：摩擦制动+电机+变流器+电感+源阻抗+储能损耗；排除回网/弃能/电抗变化",
    "regenerative_chain_loss_energy": "physical_dissipation_energy 减摩擦制动耗散",
    "stored_plus_net_grid_export_energy": "净存入能量加净回网，牵引网有效利用程度需另行解释",
    "nonstored_energy": "机械制动能量减净存入能量；与旧 loss_energy 相同，包含回网，不能解释为发热耗散",
    "control_effort_tv": "记录样本上的占空比总变差，无量纲抖振指标；不是损耗能量，也不能推算开关损耗",
}


def energy_accounting(energies: Mapping[str, Any], *, unit: str = "kWh") -> Dict[str, float]:
    """由已有台账补齐节能口径，支持历史 CSV；不重积分或猜测缺失值。"""
    if unit not in ("kWh", "J"):
        raise MetricsError(f"不支持的能量单位：{unit}")
    names = ("mechanical_braking_energy", "storage_energy", "grid_import_energy", "grid_net_export_energy",
             "friction_braking_energy", "motor_loss_energy", "converter_loss_energy",
             "converter_inductor_loss_energy", "grid_source_loss_energy", "storage_loss_energy")
    try:
        values = {name: float(energies[f"{name}_{unit}"]) for name in names}
    except (KeyError, TypeError, ValueError) as error:
        raise MetricsError("能量口径统计缺少台账字段或字段无效") from error
    if not all(math.isfinite(value) for value in values.values()):
        raise MetricsError("能量口径统计含非有限值")
    if values["mechanical_braking_energy"] < 0:
        raise MetricsError("机械制动能量不能为负")
    friction = values["friction_braking_energy"]
    chain_loss = math.fsum(values[name] for name in names[5:])
    storage = values["storage_energy"]
    conservative = storage - values["grid_import_energy"]
    mechanical = values["mechanical_braking_energy"]
    return {
        f"physical_dissipation_energy_{unit}": friction + chain_loss,
        f"regenerative_chain_loss_energy_{unit}": chain_loss,
        f"storage_net_of_grid_import_energy_{unit}": conservative,
        f"stored_plus_net_grid_export_energy_{unit}": storage + values["grid_net_export_energy"],
        f"nonstored_energy_{unit}": mechanical - storage,
        "net_storage_capture_ratio": storage / mechanical if mechanical > 0 else 0.0,
        "storage_net_of_grid_import_ratio": conservative / mechanical if mechanical > 0 else 0.0,
    }


# ------------------------------------------------------------------
# 能量台账
# ------------------------------------------------------------------


@dataclass
class EnergyLedger:
    """逐步累积的能量台账（单位 J，输出时转 kWh）。"""

    mechanical_braking_energy_j: float = 0.0
    regen_wheel_energy_j: float = 0.0
    friction_braking_energy_j: float = 0.0
    motor_electrical_energy_j: float = 0.0
    converter_input_energy_j: float = 0.0
    converter_output_energy_j: float = 0.0
    converter_loss_energy_j: float = 0.0
    converter_inductor_loss_energy_j: float = 0.0
    storage_accepted_energy_j: float = 0.0
    storage_energy_delta_j: float = 0.0
    storage_loss_energy_j: float = 0.0
    curtailed_energy_j: float = 0.0
    grid_export_energy_j: float = 0.0
    grid_import_energy_j: float = 0.0
    grid_source_loss_energy_j: float = 0.0
    traction_energy_j: float = 0.0
    #: 标准式(72) 的电流积分路径：``Q_z = U_w·Σ(I_z·λ·dt)``。
    #: 这是**独立于「力 × 速度 × 效率」的第二条口径**，用于互校，不参与能量闭合。
    regen_current_energy_j: float = 0.0
    regen_current_charge_a_s: float = 0.0
    #: 本次校核用的牵引网电压（V）；0 表示未启用（数据缺失或无电流曲线）
    regen_current_reference_voltage_v: float = 0.0
    duration_s: float = 0.0

    # 状态类辅助量
    reactive_energy_start_j: float = 0.0
    reactive_energy_end_j: float = 0.0
    soc_start: Optional[float] = None
    soc_end: Optional[float] = None
    soc_min_seen: Optional[float] = None
    soc_max_seen: Optional[float] = None
    steps: int = 0

    # ---------- 累积 ----------
    def add_step(
        self,
        dt: float,
        *,
        mechanical_braking_power_w: float,
        regen_wheel_power_w: float,
        friction_braking_power_w: float,
        motor_electrical_power_w: float,
        converter_input_power_w: float,
        converter_output_power_w: float,
        converter_loss_w: float,
        converter_inductor_loss_w: float,
        storage_accepted_power_w: float,
        storage_energy_delta_j: float,
        storage_loss_j: float,
        curtailed_power_w: float,
        grid_export_power_w: float = 0.0,
        grid_import_power_w: float = 0.0,
        grid_source_loss_w: float = 0.0,
        traction_power_w: float = 0.0,
    ) -> None:
        self.mechanical_braking_energy_j += mechanical_braking_power_w * dt
        self.regen_wheel_energy_j += regen_wheel_power_w * dt
        self.friction_braking_energy_j += friction_braking_power_w * dt
        self.motor_electrical_energy_j += motor_electrical_power_w * dt
        self.converter_input_energy_j += converter_input_power_w * dt
        self.converter_output_energy_j += converter_output_power_w * dt
        self.converter_loss_energy_j += converter_loss_w * dt
        self.converter_inductor_loss_energy_j += converter_inductor_loss_w * dt
        self.storage_accepted_energy_j += storage_accepted_power_w * dt
        self.storage_energy_delta_j += storage_energy_delta_j
        self.storage_loss_energy_j += storage_loss_j
        self.curtailed_energy_j += max(0.0, curtailed_power_w) * dt
        self.grid_export_energy_j += max(0.0, grid_export_power_w) * dt
        self.grid_import_energy_j += max(0.0, grid_import_power_w) * dt
        self.grid_source_loss_energy_j += max(0.0, grid_source_loss_w) * dt
        self.traction_energy_j += traction_power_w * dt
        self.duration_s += dt
        self.steps += 1

    def observe_soc(self, soc: float) -> None:
        if self.soc_start is None:
            self.soc_start = soc
        self.soc_end = soc
        self.soc_min_seen = soc if self.soc_min_seen is None else min(self.soc_min_seen, soc)
        self.soc_max_seen = soc if self.soc_max_seen is None else max(self.soc_max_seen, soc)

    def observe_reactive_energy(self, energy_j: float, first: bool = False) -> None:
        if first:
            self.reactive_energy_start_j = energy_j
        self.reactive_energy_end_j = energy_j

    def observe_regen_current_step(self, power_w: float, voltage_v: float, dt: float) -> None:
        """记录一拍式(72) 电流积分路径的功率（W）与所用网压（V）。"""

        self.regen_current_energy_j += power_w * dt
        if voltage_v > 0.0:
            self.regen_current_charge_a_s += power_w / voltage_v * dt
            self.regen_current_reference_voltage_v = voltage_v

    # ---------- 派生量 ----------
    @property
    def motor_loss_energy_j(self) -> float:
        return max(0.0, self.regen_wheel_energy_j - self.motor_electrical_energy_j)

    @property
    def reactive_energy_delta_j(self) -> float:
        return self.reactive_energy_end_j - self.reactive_energy_start_j

    @property
    def loss_energy_j(self) -> float:
        """旧口径：未存入储能能量 = 机械制动能量 - 储能净存入能量。

        注意：这里把"回网能量"也归入未回收部分（未进入储能即视为未回收），
        此处扣除的是净存入能量；capture_ratio 使用吸收能量，二者不同。
        """

        return self.mechanical_braking_energy_j - self.storage_energy_delta_j

    @property
    def grid_net_export_energy_j(self) -> float:
        """牵引网侧净送出能量（回网 - 回吸，带符号）。"""

        return self.grid_export_energy_j - self.grid_import_energy_j

    @property
    def closure_residual_j(self) -> float:
        """能量闭合残差，应接近 0（仅积分误差量级）。

        注意用的是 grid_net_export（带符号），而不是 grid_export：
        制动尾段与启动瞬态会从电网侧回吸功率，这部分必须抵扣，
        否则台账会凭空出现等量缺口。
        """

        parts = (
            self.friction_braking_energy_j
            + self.motor_loss_energy_j
            + self.converter_loss_energy_j
            + self.converter_inductor_loss_energy_j
            + self.grid_source_loss_energy_j
            + self.storage_loss_energy_j
            + self.storage_energy_delta_j
            + self.reactive_energy_delta_j
            + self.curtailed_energy_j
            + self.grid_net_export_energy_j
        )
        return self.mechanical_braking_energy_j - parts

    @property
    def regenerative_efficiency(self) -> float:
        """再生链效率：储能接收的**再生电** ÷ 电机侧电功率。

        储能吸收里可能混有从母线回吸的电网电（``grid_import``）——那不是再生，
        必须扣除。低速工况下再生能力接近 0、控制器仍要求吸收时，若不扣，
        该比值会大于 1，看起来像"效率超过 100%"。

        无法区分来源时按「先归再生、超出部分归电网」的保守顺序处理：
        扣除回吸量后仍可能大于 1 的余量一律截到 1。
        """

        if self.motor_electrical_energy_j <= 0.0:
            return 0.0
        from_regen_j = self.storage_accepted_energy_j - max(self.grid_import_energy_j, 0.0)
        if from_regen_j <= 0.0:
            return 0.0
        return min(from_regen_j / self.motor_electrical_energy_j, 1.0)

    @property
    def capture_ratio(self) -> float:
        """机械制动能量中被储能回收的比例（同样扣除电网回吸部分）。"""

        if self.mechanical_braking_energy_j <= 0.0:
            return 0.0
        from_regen_j = self.storage_accepted_energy_j - max(self.grid_import_energy_j, 0.0)
        return max(from_regen_j, 0.0) / self.mechanical_braking_energy_j

    @property
    def regen_current_to_motor_ratio(self) -> Optional[float]:
        """式(72) 电流积分电量 ÷ 电机侧电能量。

        发电机侧电能量为 0（全程未再生）时无定义，返回 ``None`` 而不是 0——
        「没再生」和「两条路径对不上」是两件事，不能混成一个数。
        """

        if self.motor_electrical_energy_j <= 0.0:
            return None
        # 校核未启用（无电流表 / 无网压 / 全程未再生）时电压为 0——
        # 此时不能给出比值：0 会被误读成「两条路径差 100%」
        if self.regen_current_reference_voltage_v <= 0.0:
            return None
        return self.regen_current_energy_j / self.motor_electrical_energy_j

    @property
    def regen_current_deviation(self) -> Optional[float]:
        """两条路径的相对偏差（以「力 × 速度 × 效率」为基准）。"""

        ratio = self.regen_current_to_motor_ratio
        return None if ratio is None else ratio - 1.0

    @property
    def regen_current_implied_efficiency(self) -> Optional[float]:
        """标准电流表隐含的「轮周 → 网」平均效率 = ``Q_z / 轮周再生能量``。

        **与电机效率假设无关**：它只反映 ``B_d(v)``、``I_z(v)`` 两张标准表与
        ``U_w`` 之间是否自洽（分子查电流表乘网压，分母是轮周机械能）。因此当
        它与 :attr:`regen_current_to_motor_ratio` 一起看时，能把总偏差拆成
        「标准表自洽性」与「本模型的链上效率（含部分载荷惩罚）」两段：

            Q_z / 电机侧电能量 = 隐含效率 / 模型链上效率
        """

        wheel_j = self.regen_wheel_energy_j
        if wheel_j <= 0.0 or self.regen_current_energy_j <= 0.0:
            return None
        return self.regen_current_energy_j / wheel_j

    @property
    def regen_current_check_passed(self) -> Optional[bool]:
        """两条路径是否在 :data:`REGEN_CURRENT_CHECK_TOLERANCE` 内一致。"""

        deviation = self.regen_current_deviation
        if deviation is None:
            return None
        return abs(deviation) <= REGEN_CURRENT_CHECK_TOLERANCE

    def to_dict(self, kwh: bool = True) -> Dict[str, Any]:
        scale = (1.0 / 3.6e6) if kwh else 1.0
        unit = "kWh" if kwh else "J"
        payload = {
            "duration_s": self.duration_s,
            "steps": self.steps,
            f"mechanical_braking_energy_{unit}": self.mechanical_braking_energy_j * scale,
            f"available_regenerative_energy_{unit}": self.motor_electrical_energy_j * scale,
            f"captured_energy_{unit}": self.storage_accepted_energy_j * scale,
            f"storage_energy_{unit}": self.storage_energy_delta_j * scale,
            f"loss_energy_{unit}": self.loss_energy_j * scale,
            f"friction_braking_energy_{unit}": self.friction_braking_energy_j * scale,
            f"motor_loss_energy_{unit}": self.motor_loss_energy_j * scale,
            f"converter_loss_energy_{unit}": self.converter_loss_energy_j * scale,
            f"converter_inductor_loss_energy_{unit}": self.converter_inductor_loss_energy_j * scale,
            f"storage_loss_energy_{unit}": self.storage_loss_energy_j * scale,
            f"curtailed_energy_{unit}": self.curtailed_energy_j * scale,
            f"grid_export_energy_{unit}": self.grid_export_energy_j * scale,
            f"grid_import_energy_{unit}": self.grid_import_energy_j * scale,
            f"grid_net_export_energy_{unit}": self.grid_net_export_energy_j * scale,
            f"grid_source_loss_energy_{unit}": self.grid_source_loss_energy_j * scale,
            f"reactive_energy_delta_{unit}": self.reactive_energy_delta_j * scale,
            f"closure_residual_{unit}": self.closure_residual_j * scale,
            "regenerative_efficiency": self.regenerative_efficiency,
            "capture_ratio": self.capture_ratio,
            # 式(72) 电流积分路径（独立第二口径，只校核、不进闭合）
            f"regen_current_energy_{unit}": self.regen_current_energy_j * scale,
            "regen_current_charge_a_s": self.regen_current_charge_a_s,
            "regen_current_to_motor_ratio": self.regen_current_to_motor_ratio,
            "regen_current_implied_efficiency": self.regen_current_implied_efficiency,
            "regen_current_check_passed": self.regen_current_check_passed,
            "soc_start": self.soc_start,
            "soc_end": self.soc_end,
            "soc_min_seen": self.soc_min_seen,
            "soc_max_seen": self.soc_max_seen,
        }
        payload.update(energy_accounting(payload, unit=unit))
        return payload


# ------------------------------------------------------------------
# 信号级指标
# ------------------------------------------------------------------


def _as_array(values: Sequence[float], name: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or array.size == 0:
        raise MetricsError(f"{name} 必须是非空一维序列")
    if not np.all(np.isfinite(array)):
        raise MetricsError(f"{name} 含非有限值")
    return array


@dataclass(frozen=True)
class RippleMetrics:
    """波动指标。"""

    mean: float
    std: float
    peak_to_peak: float
    rms_about_mean: float
    relative_ripple: float

    def to_dict(self, prefix: str) -> Dict[str, float]:
        return {
            f"{prefix}_mean": self.mean,
            f"{prefix}_std": self.std,
            f"{prefix}_peak_to_peak": self.peak_to_peak,
            f"{prefix}_rms": self.rms_about_mean,
            f"{prefix}_relative_ripple": self.relative_ripple,
        }


def ripple_metrics(values: Sequence[float], name: str = "signal") -> RippleMetrics:
    """计算均值/标准差/峰峰值/相对波动率。"""

    array = _as_array(values, name)
    mean = float(np.mean(array))
    std = float(np.std(array, ddof=0))
    ptp = float(np.max(array) - np.min(array))
    rms = float(np.sqrt(np.mean((array - mean) ** 2)))
    denominator = abs(mean) if abs(mean) > 1e-12 else 1.0
    return RippleMetrics(
        mean=mean,
        std=std,
        peak_to_peak=ptp,
        rms_about_mean=rms,
        relative_ripple=rms / denominator,
    )


@dataclass(frozen=True)
class TrackingMetrics:
    """跟踪性能指标。"""

    rmse: float
    iae: float
    ise: float
    max_abs_error: float
    final_abs_error: float
    settling_time_s: Optional[float]
    overshoot_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tracking_rmse": self.rmse,
            "tracking_iae": self.iae,
            "tracking_ise": self.ise,
            "tracking_max_abs_error": self.max_abs_error,
            "tracking_final_abs_error": self.final_abs_error,
            "settling_time": self.settling_time_s,
            "overshoot": self.overshoot_ratio,
        }


def tracking_metrics(
    reference: Sequence[float],
    actual: Sequence[float],
    time_s: Sequence[float],
    band: float = 0.05,
    band_is_relative: bool = True,
) -> TrackingMetrics:
    """计算跟踪误差指标与调节时间。

    Args:
        band: 稳态带；band_is_relative=True 时按 |reference| 的均值折算相对带。
    """

    ref = _as_array(reference, "reference")
    act = _as_array(actual, "actual")
    t = _as_array(time_s, "time_s")
    if not (ref.size == act.size == t.size):
        raise MetricsError("reference / actual / time_s 长度必须一致")

    error = act - ref
    rmse = float(np.sqrt(np.mean(error**2)))
    iae = float(np.trapezoid(np.abs(error), t))
    ise = float(np.trapezoid(error**2, t))
    max_abs = float(np.max(np.abs(error)))
    final_abs = float(abs(error[-1]))

    ref_scale = abs(float(np.mean(ref)))
    tolerance = band * ref_scale if band_is_relative else band
    if tolerance <= 0.0:
        tolerance = band

    settling: Optional[float] = None
    inside = np.abs(error) <= tolerance
    for index in range(inside.size):
        if bool(np.all(inside[index:])):
            settling = float(t[index])
            break

    ref_abs_mean = abs(float(np.mean(ref)))
    if ref_abs_mean > 1e-12:
        overshoot = max(0.0, float(np.max(act)) - float(np.max(ref))) / ref_abs_mean
    else:
        overshoot = 0.0

    return TrackingMetrics(
        rmse=rmse,
        iae=iae,
        ise=ise,
        max_abs_error=max_abs,
        final_abs_error=final_abs,
        settling_time_s=settling,
        overshoot_ratio=overshoot,
    )


#: 方案问题 25（本模块新发现）：``duty_saturation_ratio`` 的「贴轨」判据曾写死 PWM
#: **物理硬边界** ``[0, 1]``，但闭环里控制器输出会先经 :meth:`DutyLimits.clamp_with_u0`
#: 落到 ``[min_duty, min(max_duty, u0_max)]``，技术方案 ``u0 = 0.9`` 生效时上界就是 ``0.9``。
#: 于是 ``d >= 1 - 1e-9`` **恒不成立**，上轨饱和被静默漏报（实测 ``s1_flat_braking`` 下
#: ``traditional_smc`` 有 ``96.48%`` 的拍顶在 ``0.9``、``pi`` 有 ``81.02%``、``pid`` 有
#: ``50.12%``，而该指标一律报 ``0.0000``，使 ``comparison.py`` 中 ``prefer="lower"`` 的
#: 这项对比**丧失分辨力**）。修复方式：判据按调用方给出的**实际生效执行器可行域**判定。
SCHEME_ISSUE_DUTY_SATURATION_RAIL = 25


def _executor_bound(value: float, name: str) -> float:
    """校验执行器可行域边界为有限实数。"""

    number = float(value)
    if not math.isfinite(number):
        raise MetricsError(f"{name} 必须为有限实数，实际为 {value!r}")
    return number


def control_effort(
    duty_series: Sequence[float],
    dt: float,
    *,
    lower_bound: float = 0.0,
    upper_bound: float = 1.0,
    tolerance: float = 1e-9,
) -> Dict[str, float]:
    """控制代价：总变差、绝对变化率积分、饱和比例。

    Args:
        lower_bound / upper_bound: 执行器**实际生效**的可行域上下界。默认
            ``[0.0, 1.0]`` 是 PWM 物理硬边界，仅在 ``apply_u0_limit=False`` 时成立；
            启用技术方案 ``u0`` 限幅时应传 ``min(max_duty, u0_max)``
            （见 :data:`SCHEME_ISSUE_DUTY_SATURATION_RAIL`，方案问题 25）。
        tolerance: 判定「贴轨」的容差，``d <= lower_bound + tolerance`` 或
            ``d >= upper_bound - tolerance`` 计为贴轨。

    Note:
        ``duty_saturation_ratio`` 只统计**传入的单个通道**。当前生产路径只传
        ``duty_cycle_T1``（主控制通道）；``duty_cycle_T2`` 不进该指标。
    """

    duties = _as_array(duty_series, "duty_series")
    if dt <= 0.0:
        raise MetricsError("dt 必须为正")

    lo = _executor_bound(lower_bound, "lower_bound")
    hi = _executor_bound(upper_bound, "upper_bound")
    if not lo < hi:
        raise MetricsError(f"执行器可行域必须满足 lower_bound < upper_bound，实际为 [{lo}, {hi}]")
    tol = _executor_bound(tolerance, "tolerance")
    if tol < 0.0:
        raise MetricsError(f"tolerance 必须非负，实际为 {tolerance!r}")

    if duties.size < 2:
        return {"control_effort_tv": 0.0, "control_effort_rate": 0.0, "duty_saturation_ratio": 0.0}

    deltas = np.abs(np.diff(duties))
    total_variation = float(np.sum(deltas))
    rate = total_variation / (dt * (duties.size - 1))
    saturated = np.logical_or(duties <= lo + tol, duties >= hi - tol)
    return {
        "control_effort_tv": total_variation,
        "control_effort_rate": rate,
        "duty_saturation_ratio": float(np.mean(saturated)),
    }


def converter_limit_ratios(
    input_power_w: Sequence[float],
    input_current_a: Sequence[float],
    *,
    power_rating_w: float,
    max_input_current_a: float,
    tolerance: float = 1e-9,
) -> Dict[str, float]:
    """变流器**越限拍占比**（方案问题 32 给额定值补的消费点）。

    Args:
        input_power_w: 变流器输入功率序列。生产路径取
            ``SimulationArrays.motor_electrical_power_w``——它严格等于
            ``DCConverterStepResult.input_power_w``，因为
            :meth:`~regenerative_braking.dynamics.dc_dc_converter.BidirectionalDCDCConverter.step`
            里 ``p_in = source_power``，而仿真器传的 ``source_power_w``
            就是 ``motor_result.electrical_power_w``。
        input_current_a: 变流器输入电流序列（``i_src = source_power / v_in``）。
        power_rating_w: 变流器额定功率 ``DCConverterParameters.power_rating_w``。
        max_input_current_a: 变流器额定输入电流
            ``DCConverterParameters.max_input_current_a``。
        tolerance: 判定越限的绝对容差。

    Returns:
        ``{"converter_over_rating_ratio": …, "converter_input_current_over_limit_ratio": …}``

    Note:
        与 :func:`control_effort` 的 ``duty_saturation_ratio`` 同一口径：
        统计的是**逐步记录**（``record_stride`` 抽样后）的样本，
        不是全分辨率。两条限值都只报告、不截断（超出的部分抬高母线电压
        经 ``i_grid`` 回网，是真实物理去向）。

        限值给 ``inf``（即"未提供"）时比例记为 ``0.0``；
        生产路径由 ``RegenerativeBrakingSimulator.run()`` 从变流器参数填入，
        不会落到该默认值（有回归测试守住）。
    """

    powers = np.abs(_as_array(input_power_w, "input_power_w"))
    currents = np.abs(_as_array(input_current_a, "input_current_a"))
    tol = _executor_bound(tolerance, "tolerance")
    if tol < 0.0:
        raise MetricsError(f"tolerance 必须非负，实际为 {tolerance!r}")
    rating = float(power_rating_w)
    current_limit = float(max_input_current_a)
    if math.isnan(rating) or rating <= 0.0:
        raise MetricsError(f"power_rating_w 必须为正（或 inf），实际为 {power_rating_w!r}")
    if math.isnan(current_limit) or current_limit <= 0.0:
        raise MetricsError(
            f"max_input_current_a 必须为正（或 inf），实际为 {max_input_current_a!r}"
        )
    return {
        "converter_over_rating_ratio": (
            0.0 if math.isinf(rating) else float(np.mean(powers > rating + tol))
        ),
        "converter_input_current_over_limit_ratio": (
            0.0 if math.isinf(current_limit) else float(np.mean(currents > current_limit + tol))
        ),
    }


# ------------------------------------------------------------------
# 场景级汇总
# ------------------------------------------------------------------


@dataclass
class ScenarioMetrics:
    """单个验证场景的完整输出（字段与项目要求的场景输出清单对齐）。"""

    scenario_id: str
    controller: str
    ledger: Mapping[str, Any]
    voltage_ripple: Mapping[str, float]
    current_ripple: Mapping[str, float]
    power_ripple: Mapping[str, float]
    tracking: Mapping[str, Any]
    control: Mapping[str, float]
    soc_variation: float
    filter_mode: str = "none"
    notes: List[str] = field(default_factory=list)
    extra: Dict[str, float] = field(default_factory=dict)

    def to_flat_dict(self) -> Dict[str, Any]:
        flat: Dict[str, Any] = {
            "scenario_id": self.scenario_id,
            "controller": self.controller,
            "filter_mode": self.filter_mode,
            "soc_variation": self.soc_variation,
        }
        flat.update(dict(self.ledger))
        flat.update(dict(self.voltage_ripple))
        flat.update(dict(self.current_ripple))
        flat.update(dict(self.power_ripple))
        flat.update(dict(self.tracking))
        flat.update(dict(self.control))
        flat.update(dict(self.extra))
        if self.notes:
            flat["notes"] = " | ".join(self.notes)
        return flat


def soc_variation(soc_values: Sequence[float]) -> float:
    """SOC 波动幅度（max - min）。"""

    array = _as_array(soc_values, "soc_values")
    return float(np.max(array) - np.min(array))


def build_scenario_metrics(
    scenario_id: str,
    controller: str,
    ledger: EnergyLedger,
    *,
    voltage_series: Sequence[float],
    current_series: Sequence[float],
    power_series: Sequence[float],
    reference_power: Sequence[float],
    time_s: Sequence[float],
    duty_series: Sequence[float],
    soc_series: Sequence[float],
    dt: float,
    filter_mode: str = "none",
    extra_ripple: Optional[Mapping[str, Sequence[float]]] = None,
    notes: Optional[List[str]] = None,
    duty_lower_bound: float = 0.0,
    duty_upper_bound: float = 1.0,
    extra_ratios: Optional[Mapping[str, float]] = None,
) -> ScenarioMetrics:
    """把逐步记录汇总成场景级指标。

    Args:
        voltage_series: 用于 voltage_ripple 的电压序列（本项目取储能侧母线电压）。
        current_series: 用于 current_ripple 的电流序列（本项目取储能侧电流）。
        extra_ripple: 额外波动组，键名作为前缀，例如 {"input_voltage": [...]}。
        duty_lower_bound / duty_upper_bound: 执行器实际生效的占空比可行域，
            透传给 :func:`control_effort`（见方案问题 25）。
        extra_ratios: 直接并入 ``extra`` 的**标量比例**（键名即列名），
            生产路径用 :func:`converter_limit_ratios` 的返回值填
            （见方案问题 32）。
    """

    tracking = tracking_metrics(reference_power, power_series, time_s)
    extra: Dict[str, float] = {}
    for key, values in (extra_ripple or {}).items():
        extra.update(ripple_metrics(values, key).to_dict(f"{key}_ripple"))
    for key, value in (extra_ratios or {}).items():
        number = float(value)
        if not math.isfinite(number):
            raise MetricsError(f"extra_ratios[{key!r}] 必须为有限实数，实际为 {value!r}")
        extra[key] = number

    return ScenarioMetrics(
        scenario_id=scenario_id,
        controller=controller,
        ledger=ledger.to_dict(kwh=True),
        voltage_ripple=ripple_metrics(voltage_series, "voltage").to_dict("voltage_ripple"),
        current_ripple=ripple_metrics(current_series, "current").to_dict("current_ripple"),
        power_ripple=ripple_metrics(power_series, "power").to_dict("power_ripple"),
        tracking=tracking.to_dict(),
        control=control_effort(
            duty_series,
            dt,
            lower_bound=duty_lower_bound,
            upper_bound=duty_upper_bound,
        ),
        soc_variation=soc_variation(soc_series),
        filter_mode=filter_mode,
        notes=list(notes or []),
        extra=extra,
    )
