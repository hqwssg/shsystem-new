"""控制器接口与阶段 2 baseline 控制器。

实现 **基础 baseline**（方案 §4.1.2.4「结合历史数据对比分析」）：

    * :class:`ZeroDutyController` / :class:`FixedDutyController` —— 开环对照
    * :class:`PIController` / :class:`PIDController` —— 定常 PI / PID
    * :class:`TraditionalSMCController` —— 传统 SMC（不连续切换项）

主算法（RHONN + EKF/UKF + NSMC）在 :mod:`regenerative_braking.control.nsmc` 实现，
本模块只提供统一接口：

    compute(observation) -> ControllerCommand(duty_cycle_T1, duty_cycle_T2)

所有控制器输出必须落在 PWM 硬边界 [0, 1] 内；不物理的输出直接抛错，
不允许出现「不物理的 PWM 输出」。

--------------------------------------------------------------------------
与主算法共用跟踪口径
--------------------------------------------------------------------------

三个闭环 baseline 都用 :mod:`regenerative_braking.tracking` 里的**同一套**定义：
滑模面 ``s(x_k,k) = λ_k·(x_k − x_ref)``、时变系数 ``λ_k`` 与参考量提供者。
这是为了避免口径漂移——若 baseline 用自己的误差定义、主算法用另一套，
对比表的 delta 就没有意义。问题 5 裁定后 ``λ_k`` 的乘入也一并共用，
不会出现「主算法带 λ_k、baseline 不带」的不一致。

参考状态 ``x_{ref,k}`` 的构造式（方案问题 13）已由编写人裁定，见
:class:`~regenerative_braking.tracking.RegenerativeReferenceState`，
本模块默认即用它。第二分量是**电感电流参考**（问题 16 裁定后状态向量为
``(v_out, i_L)``），因此本模块的跟踪误差取观测量的 ``inductor_current_a``
——与参考量同坐标。此前取 ``output_current_a`` 是问题 16 修正后遗留的坐标错配，
已随本次裁定改正。

--------------------------------------------------------------------------
方案未规定 s → u 的映射，本模块的处理
--------------------------------------------------------------------------

方案给了向量滑模面 ``s ∈ R^2``（电压、电流）与向量控制 ``u ∈ R^2``（T1、T2），
但**没有给出两者的映射关系**。本模块的 baseline 统一取：

    T1 ← 电流分量 s[1]     （本变换器中 T1 是 buck 占空比，直接决定充电电流）
    T2 ← 0                （与 fixed_duty baseline 一致，单通道取能）

理由是同一模块内 fixed_duty baseline 的物理依据：``v_out ≈ d1·v_in``，
``d1`` 越过储能开路电压门槛后才产生充电电流。主算法 NSMC 不做这个降维，
它通过 ``S_sc`` 与 ``u_eq`` 使用完整的二维信息。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

import numpy as np

from ..dynamics.dc_dc_converter import DutyLimits
from ..tracking import (
    SCHEME_U0,
    ReferenceStateProvider,
    RegenerativeReferenceState,
    lambda_k,
    sliding_surface,
)


class ControllerError(ValueError):
    """控制器配置或输出不合法。"""


@dataclass(frozen=True)
class ControllerObservation:
    """控制器可见的观测量（全部 SI）。

    ``gradient_per_mille`` 是线路坡度（‰，上坡为正）。它不参与任何控制律，
    但**是阶段 6 模式切换判据之一**（坡度突变 → 切 UKF，见算法文档 §5.4），
    因此必须出现在观测量里，否则模式切换器拿不到这个输入。
    默认 0.0，便于不关心坡度的调用方与既有测试保持不变。

    .. warning::
       **两个功率观测量的语义必须按代码读，不要按名字读**（方案问题 34）：

       * ``requested_regen_power_w`` = ``motor_result.electrical_power_w``，
         是**直流母线侧**的电功率，且**已经过电机包络与效率折算**——
         它**不是**制动曲线给出的原始请求。
       * ``available_regen_power_w`` = ``envelope_power_limit_w × dc_link_derating``，
         是**轮端机械**的电机包络，**不含 SOC、不含变流器容量**
         （``convert_wheel_regen`` 的签名里没有任何 storage / SOC 参数）。

       两者侧别不同（电 vs 机械），但由同一次 ``convert_wheel_regen`` 产生，
       故 ``available ≥ requested / η ≥ requested`` **恒成立**——
       在 ``tracking.py`` ③ 与 :class:`~regenerative_braking.validation.baselines.IdealUpperBoundController`
       的 ``min()`` 中，``available`` **恒不可能**成为紧约束（实测官方场景
       ``available < requested`` 的拍数恒为 ``0``）。储能/SOC 约束由同拍
       ``storage_charge_power_limit_w`` 与参考模型的额定充电功率共同承担，
       变流器容量由 ``P_conv = v_out · i_L,max · η`` 承担。
    """

    time_s: float
    speed_mps: float
    input_voltage_v: float
    output_voltage_v: float
    inductor_current_a: float
    output_current_a: float
    soc: float
    #: 直流母线侧电机电功率，**已过包络与效率**（见类 docstring 的 warning）
    requested_regen_power_w: float
    #: 轮端机械电机包络，**不含 SOC / 变流器容量**（见类 docstring 的 warning）
    available_regen_power_w: float
    output_power_w: float
    gradient_per_mille: float = 0.0
    #: 储能/BMS 本拍充电功率许可（W，已含 SOC 余量）；不是电机再生包络。
    #: None 仅用于未提供该信号的历史调用方；生产仿真逐拍提供。
    storage_charge_power_limit_w: Optional[float] = None
    #: 电气采集接口明确报告本拍有效性；False 时主算法拒用陈旧量测并退出充电。
    #: 不由控制器猜测故障，不代表电压/电流偏置已被检测。
    electrical_measurement_valid: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.electrical_measurement_valid, bool):
            raise ControllerError("electrical_measurement_valid 必须为 bool")
        limit = self.storage_charge_power_limit_w
        if limit is not None and (not math.isfinite(limit) or limit < 0.0):
            raise ControllerError("storage_charge_power_limit_w 必须为非负有限值或 None")


@dataclass(frozen=True)
class ControllerCommand:
    """控制器输出：T1 / T2 PWM 占空比。"""

    duty_cycle_T1: float
    duty_cycle_T2: float
    note: str = ""

    def validate(self, limits: DutyLimits) -> "ControllerCommand":
        for name, value in (("duty_cycle_T1", self.duty_cycle_T1), ("duty_cycle_T2", self.duty_cycle_T2)):
            if not math.isfinite(value):
                raise ControllerError(f"{name} 必须为有限值，实际为 {value!r}")
            if not limits.min_duty - 1e-12 <= value <= limits.max_duty + 1e-12:
                raise ControllerError(
                    f"{name}={value!r} 越出 PWM 硬边界 [{limits.min_duty}, {limits.max_duty}]；"
                    "控制器必须自行限幅，不允许输出不物理的占空比。"
                )
        return self


@runtime_checkable
class RegenController(Protocol):
    """再生制动控制器协议。"""

    name: str

    def reset(self) -> None:  # pragma: no cover - 协议声明
        ...

    def compute(self, observation: ControllerObservation) -> ControllerCommand:  # pragma: no cover
        ...


class ZeroDutyController:
    """无控制 baseline：T1/T2 均为 0，变流器不取能。

    物理含义：再生能量全部经直流母线返回牵引网（记为 grid_export），
    储能不吸收任何能量。这是"不做能量回收"的对照基准。
    """

    name = "uncontrolled_zero_duty"

    def __init__(self, limits: Optional[DutyLimits] = None) -> None:
        self.limits = limits or DutyLimits()

    def reset(self) -> None:
        return None

    def compute(self, observation: ControllerObservation) -> ControllerCommand:
        return ControllerCommand(duty_cycle_T1=0.0, duty_cycle_T2=0.0, note="zero_duty").validate(self.limits)


class FixedDutyController:
    """固定占空比 baseline。

    用于标定"最朴素的能量回收方式"：占空比恒定，储能被动吸收，
    不做电压/电流/SOC 调节，因此会出现过充、过流与功率波动。
    """

    name = "fixed_duty"

    def __init__(self, duty_cycle_T1: float, duty_cycle_T2: float = 0.0, limits: Optional[DutyLimits] = None) -> None:
        self.limits = limits or DutyLimits()
        self.duty_cycle_T1 = float(duty_cycle_T1)
        self.duty_cycle_T2 = float(duty_cycle_T2)
        for name, value in (("duty_cycle_T1", self.duty_cycle_T1), ("duty_cycle_T2", self.duty_cycle_T2)):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ControllerError(f"{name} 必须在 [0, 1] 内，实际为 {value!r}")

    def reset(self) -> None:
        return None

    def compute(self, observation: ControllerObservation) -> ControllerCommand:
        return ControllerCommand(
            duty_cycle_T1=self.duty_cycle_T1,
            duty_cycle_T2=self.duty_cycle_T2,
            note="fixed_duty",
        ).validate(self.limits)


def ideal_buck_duty_for_power(
    target_output_power_w: float,
    input_voltage_v: float,
    output_voltage_v: float,
    efficiency: float = 1.0,
) -> float:
    """给定目标储能侧功率时，纯 buck 模式的理想占空比（供后续控制器参考）。

    由 P_out = eta * P_in 与 V_out = d * V_in 联立：

        I_out = P_out / V_out, I_in = P_in / V_in, d = I_out / I_in

    这里仅做量级估算，不作为控制律；真正的控制律由 NSMC 给出。
    """

    if input_voltage_v <= 0.0 or output_voltage_v <= 0.0:
        raise ControllerError("电压必须为正")
    if efficiency <= 0.0:
        raise ControllerError("efficiency 必须为正")
    target = max(0.0, target_output_power_w)
    d_voltage = min(max(output_voltage_v / input_voltage_v, 0.0), 1.0)
    if target <= 0.0:
        return 0.0
    p_in_required = target / efficiency
    if p_in_required <= 0.0:
        return 0.0
    i_in = p_in_required / input_voltage_v
    i_out = target / output_voltage_v
    d_current = i_out / i_in if i_in > 0.0 else d_voltage
    return min(max(0.5 * (d_voltage + d_current), 0.0), 1.0)


# ---------------------------------------------------------------------------
# 闭环 baseline：PI / PID / 传统 SMC
# ---------------------------------------------------------------------------

#: 标称占空比默认值。物理依据同 fixed_duty baseline：输出侧是
#: 「储能开路电压 1100 V + 内阻」的母线，buck 稳态近似 v_out ≈ d1·v_in
#: （v_in ≈ 1500 V），d1 < 0.733 时充电电流恒为 0。
DEFAULT_NOMINAL_DUTY = 0.8


class _TrackingBaseline:
    """闭环 baseline 的公共骨架：取跟踪误差 → 算占空比 → 限幅输出。

    只做三件事，具体控制律由子类给：

    1. 用共用的滑模面/参考量口径算出跟踪误差（电流分量，见模块 docstring）；
    2. 把子类给出的占空比夹到 PWM 硬边界与 u_0 之内；
    3. 记录 ``step_index`` 与 ``note``，便于与主算法对照。
    """

    #: 默认标称占空比
    nominal_duty = DEFAULT_NOMINAL_DUTY

    def __init__(
        self,
        reference_model: Optional[ReferenceStateProvider] = None,
        *,
        nominal_duty: float = DEFAULT_NOMINAL_DUTY,
        limits: Optional[DutyLimits] = None,
    ) -> None:
        self.limits = limits or DutyLimits(u0_max=SCHEME_U0)
        # 方案问题 13 裁定：x_ref 正式构造式（默认即用，无需显式注入）。
        self.reference_model: ReferenceStateProvider = (
            reference_model if reference_model is not None else RegenerativeReferenceState()
        )
        if not math.isfinite(nominal_duty) or not 0.0 <= nominal_duty <= 1.0:
            raise ControllerError(f"nominal_duty 必须在 [0, 1] 内，实际为 {nominal_duty!r}")
        self.nominal_duty = float(nominal_duty)

        self._step_index = 0
        self._last_time_s: Optional[float] = None
        self._dt = 1e-3
        self._last_command: Optional[ControllerCommand] = None

    # -- 协议 ---------------------------------------------------------------

    def reset(self) -> None:
        self._step_index = 0
        self._last_time_s = None
        self._dt = 1e-3
        self._last_command = None
        self._reset_internals()

    @property
    def step_index(self) -> int:
        return self._step_index

    @property
    def last_command(self) -> Optional[ControllerCommand]:
        return self._last_command

    # -- 子类钩子 -----------------------------------------------------------

    def _reset_internals(self) -> None:
        """清空子类自己的积分器/微分记忆。"""

    # -- 公共实现 -----------------------------------------------------------

    def _sampling_interval(self, observation: ControllerObservation) -> float:
        """采样间隔：由观测时间推进量得到。

        首步没有上一拍时间，或时间未推进（重复同一时刻的观测）时，
        退回上一次有效间隔；初始值为 1 ms，仅用于第一步的积分/微分。
        """
        current = float(observation.time_s)
        if self._last_time_s is not None:
            delta = current - self._last_time_s
            if math.isfinite(delta) and delta > 0.0:
                self._dt = delta
        self._last_time_s = current
        return self._dt

    def _tracking_error(self, observation: ControllerObservation) -> float:
        """跟踪误差 —— 共用滑模面的**电流分量**（见模块 docstring 的映射说明）。

        状态第二分量取 ``inductor_current_a``（``i_L``）：问题 16 裁定后状态向量为
        ``(v_out, i_L)``，参考量第二分量也是电感电流参考，两者同坐标。
        滑模面按问题 5 裁定乘入 ``λ_k``，与主算法共用同一口径。
        """
        state = np.asarray(
            [observation.output_voltage_v, observation.inductor_current_a], dtype=float
        )
        reference = np.asarray(self.reference_model(observation), dtype=float)
        surface = sliding_surface(state, reference, lam=lambda_k(self._step_index))
        return float(surface[1])

    def _emit(self, duty_cycle_T1: float, note: str) -> ControllerCommand:
        command = ControllerCommand(
            duty_cycle_T1=self.limits.clamp_with_u0(duty_cycle_T1),
            duty_cycle_T2=0.0,
            note=note,
        ).validate(self.limits)
        self._step_index += 1
        self._last_command = command
        return command

    def _provenance(self) -> str:
        return f"x_ref_status={self.reference_model.data_status}"


class PIController(_TrackingBaseline):
    """定常 PI baseline。

    控制律（在标称工作点上叠加 PI 修正）::

        e        = s[1] = i_out − i_ref                    共用滑模面的电流分量
        I       ← clip(I + e·dt, ±integral_limit)          抗积分饱和
        d_1      = nominal_duty − (kp·e + ki·I)

    取负号的原因：误差为正表示输出电流高于参考（充多了），应当**降低**占空比。

    ``kp`` / ``ki`` / ``integral_limit`` 为 **assumed** 量——方案未给 PI 参数，
    此处按「误差量级 ~100 A、占空比修正量级 ~0.1」估出的量级取值，
    不是整定结果，也未做参数扫描。
    """

    name = "pi"

    def __init__(
        self,
        reference_model: Optional[ReferenceStateProvider] = None,
        *,
        kp: float = 2e-3,
        ki: float = 1e-3,
        integral_limit: float = 1.0e4,
        nominal_duty: float = DEFAULT_NOMINAL_DUTY,
        limits: Optional[DutyLimits] = None,
    ) -> None:
        super().__init__(reference_model, nominal_duty=nominal_duty, limits=limits)
        for label, value in (("kp", kp), ("ki", ki)):
            if not math.isfinite(value) or value < 0.0:
                raise ControllerError(f"{label} 必须为非负有限值，实际为 {value!r}")
        if not math.isfinite(integral_limit) or integral_limit <= 0.0:
            raise ControllerError(f"integral_limit 必须为正有限值，实际为 {integral_limit!r}")
        self.kp = float(kp)
        self.ki = float(ki)
        self.integral_limit = float(integral_limit)
        self._integral = 0.0

    def _reset_internals(self) -> None:
        self._integral = 0.0

    @property
    def integral(self) -> float:
        return self._integral

    def compute(self, observation: ControllerObservation) -> ControllerCommand:
        dt = self._sampling_interval(observation)
        error = self._tracking_error(observation)

        self._integral = min(max(self._integral + error * dt, -self.integral_limit), self.integral_limit)
        duty = self.nominal_duty - (self.kp * error + self.ki * self._integral)

        return self._emit(
            duty,
            f"pi k={self._step_index} e={error:.6f} I={self._integral:.6f} "
            f"d1={duty:.6f} {self._provenance()}",
        )


class PIDController(PIController):
    """定常 PID baseline。

    在 :class:`PIController` 上增加微分项::

        d_1 = nominal_duty − (kp·e + ki·I + kd·(e − e_prev)/dt),   kd = kp · Td

    微分项用**后向差分**，增益按标准形式 ``kd = kp·Td`` 由**微分时间** ``Td`` 给出，
    而不是直接给 ``kd``。

    ----------------------------------------------------------------------
    为什么 ``Td`` 默认等于**一个采样步长**，而不是一个固定的秒数
    ----------------------------------------------------------------------

    离散后向差分 ``(e_k − e_{k−1})/dt`` 对频率 ``f`` 的幅频响应是
    ``|2·sin(π·f·dt)|/dt``：它**没有高频滚降**，在奈奎斯特频率处增益为 ``2/dt``。
    因此微分项在奈奎斯特处的等效占空比增益是

        kp · Td · (2/dt) ≈ 2 · kp · (Td/dt)

    也就是说，抖振强度由无量纲比值 ``Td/dt`` 决定，而不是由 ``Td`` 的绝对秒数决定。
    ``Td/dt ≫ 1`` 时微分项会盖过比例项：实测 ``Td = 5 ms``、``dt = 2e-4 s``
    （``Td/dt = 25``）时，观测电流上约 1 kHz 的闭环极限环被放大 25 倍，
    微分项幅值达到比例项的 30 倍，原始占空比摆到 ``−29.6 ~ +14.9``，
    限幅后就是 ``0 / 0.9`` 的 bang-bang 抖振。

    取 ``Td = dt`` 时该增益恰好退化为 ``kp``——微分项与比例项同量级，
    这才是离散实现能分辨的微分作用上限。故本类默认
    ``derivative_time_s = None``，含义是「一个采样步长」，运行时按实际 ``dt`` 解析；
    需要固定秒数时显式传入即可（但必须自行保证 ``Td ≲ dt``）。

    .. note::
       微分项**未加低通滤波**。一阶微分滤波 ``Tf = Td/N`` 只把高频增益限制到
       ``kp·N``，并不能消除 ``Td/dt`` 带来的放大——实测 ``N = 10`` 时抖振反而比
       不滤波更严重（占空比总变差从 1685 升到 4378）。因此这里不引入滤波器，
       而是直接把 ``Td`` 与采样步长绑定，理由更直接、也更容易复核。

    .. note::
       在本对象上 PID 相对 PI **收益有限**（实测捕获能量 13.1273 kWh，与 PI 相同）：
       观测电流含变流器开关纹波，而 ``Td`` 只能取到一个采样步长，微分信息基本被
       纹波淹没。这是 §4.1.2.4 历史数据对比分析的一条结论，不是实现缺陷。

    ``kp`` / ``ki`` / ``Td`` 同为 **assumed** 量。
    """

    name = "pid"

    def __init__(
        self,
        reference_model: Optional[ReferenceStateProvider] = None,
        *,
        kp: float = 2e-3,
        ki: float = 1e-3,
        derivative_time_s: Optional[float] = None,
        integral_limit: float = 1.0e4,
        nominal_duty: float = DEFAULT_NOMINAL_DUTY,
        limits: Optional[DutyLimits] = None,
    ) -> None:
        super().__init__(
            reference_model,
            kp=kp,
            ki=ki,
            integral_limit=integral_limit,
            nominal_duty=nominal_duty,
            limits=limits,
        )
        if derivative_time_s is not None and (
            not math.isfinite(derivative_time_s) or derivative_time_s < 0.0
        ):
            raise ControllerError(
                f"derivative_time_s 必须为非负有限值或 None，实际为 {derivative_time_s!r}"
            )
        self._derivative_time_s: Optional[float] = (
            None if derivative_time_s is None else float(derivative_time_s)
        )
        self._previous_error: Optional[float] = None

    @property
    def derivative_time_s(self) -> float:
        """微分时间 ``Td``；未显式指定时解析为当前采样步长 ``dt``。"""
        if self._derivative_time_s is not None:
            return self._derivative_time_s
        return self._dt

    @property
    def kd(self) -> float:
        """微分增益 ``kd = kp · Td``。"""
        return self.kp * self.derivative_time_s

    def _reset_internals(self) -> None:
        super()._reset_internals()
        self._previous_error = None

    @property
    def previous_error(self) -> Optional[float]:
        return self._previous_error

    def compute(self, observation: ControllerObservation) -> ControllerCommand:
        dt = self._sampling_interval(observation)
        error = self._tracking_error(observation)

        derivative = 0.0
        if self._previous_error is not None and dt > 0.0:
            derivative = (error - self._previous_error) / dt
        self._previous_error = error

        self._integral = min(max(self._integral + error * dt, -self.integral_limit), self.integral_limit)
        duty = self.nominal_duty - (
            self.kp * error + self.ki * self._integral + self.kd * derivative
        )

        return self._emit(
            duty,
            f"pid k={self._step_index} e={error:.6f} I={self._integral:.6f} "
            f"de={derivative:.6f} d1={duty:.6f} {self._provenance()}",
        )


class TraditionalSMCController(_TrackingBaseline):
    """传统 SMC baseline：定常滑模面 + **不连续**切换项。

    控制律::

        d_1 = nominal_duty − K_sw · sign(e)        e = s[1]

    这是经典的 bang-bang 滑模控制：切换项在 ``e = 0`` 两侧不连续，
    占空比在两个离散档位之间反复跳变，**抖振大**。
    它存在的意义就是给主算法 NSMC 当对照——方案的保方向饱和律 (34)(35)
    正是为了在限幅的同时抑制这种抖振。

    这里**不设边界层**（``sign`` 而非 ``sat``）：加了边界层就变成准滑模，
    就不再是「传统 SMC」这个对照基准了。

    ``K_sw`` 为 **assumed** 量。
    """

    name = "traditional_smc"

    def __init__(
        self,
        reference_model: Optional[ReferenceStateProvider] = None,
        *,
        switching_gain: float = 0.1,
        nominal_duty: float = DEFAULT_NOMINAL_DUTY,
        limits: Optional[DutyLimits] = None,
    ) -> None:
        super().__init__(reference_model, nominal_duty=nominal_duty, limits=limits)
        if not math.isfinite(switching_gain) or switching_gain < 0.0:
            raise ControllerError(f"switching_gain 必须为非负有限值，实际为 {switching_gain!r}")
        self.switching_gain = float(switching_gain)

    def compute(self, observation: ControllerObservation) -> ControllerCommand:
        error = self._tracking_error(observation)
        switching = math.copysign(self.switching_gain, error) if error != 0.0 else 0.0
        duty = self.nominal_duty - switching

        return self._emit(
            duty,
            f"traditional_smc k={self._step_index} e={error:.6f} "
            f"sign={0.0 if error == 0.0 else math.copysign(1.0, error):+.0f} "
            f"d1={duty:.6f} {self._provenance()}",
        )
