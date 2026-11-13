"""阶段 9 baseline 目录（对应算法文档 §10.2 的 7 项 baseline 要求）。

共 **9 项**：8 项 baseline + 1 项主算法（optimized）。对照算法文档 §10.2 的清单：

============================  ====================================  ==============
文档 #                        本实现 label                          说明
============================  ====================================  ==============
1  无控制（全部回网）           ``uncontrolled_zero_duty``            占空比恒 0
2  固定占空比 d1=0.75          ``fixed_duty_d1_0.75``                刚过充电门槛
3  固定占空比 d1=0.85          ``fixed_duty_d1_0.85``                逼近 u0 上限
4  定常 PI / PID               ``pi`` / ``pid``                      与主算法共用跟踪口径
5  传统 SMC                    ``traditional_smc``                   无边界的 bang-bang
6  无储能（仅回网）             ``no_storage_zero_duty``              **被控对象级**扰动
7  理想控制器（上界参照）        ``ideal_upper_bound``                 无损耗 buck 理想占空比
—  主算法                      ``rhonn_nsmc``                        RHONN+EKF/UKF+NSMC 联合闭环
============================  ====================================  ==============

.. note::
  文档 #6「无储能（仅回网）」按**被控对象**实现，而不是再造一个控制器：
  储能充放电功率上限置 0（见 :func:`~regenerative_braking.validation.perturbation.disable_storage`），
  控制器仍是"占空比恒 0"。这样它在物理上确实等价于 #1，但**结果行是可验证的**：
  该行的 ``storage_accepted_energy`` 必须严格为 0 且 ``curtailed_energy`` 为 0。
  文档自己也标注了"部分等价于 #1"，本实现把这个等价关系显式写成断言而不是回避。

.. warning::
   ``ideal_upper_bound`` 用 ``ideal_buck_duty_for_power`` 给出的**无损 buck 理想占空比**
   （见 :func:`~regenerative_braking.simulation.controllers.ideal_buck_duty_for_power`），
   它忽略开关损耗、电感储能与母线动态。因此它是**能量回收率的上界参照**，
   不是"可实现的控制器"——若主算法的回收率超过它，说明口径有问题，必须查。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import numpy as np

from ..dynamics.dc_dc_converter import DutyLimits
from ..control.nsmc import NSMCConfig
from ..tracking import (
    REFERENCE_GUARDED_CURRENT_FEEDBACK,
    REFERENCE_STORAGE_MATCHED,
    REFERENCE_STRATEGIES,
)
from ..identification import (
    EKFConfig,
    MODE_EKF,
    MODE_UKF,
    ModeSelectorConfig,
    OnlineIdentifier,
    UKFConfig,
    build_online_identifier,
)
from ..simulation.closed_loop import (
    build_closed_loop_controller,
    with_control_channel_gain_prior,
)
from ..simulation.controllers import (
    ControllerCommand,
    ControllerError,
    ControllerObservation,
    FixedDutyController,
    PIController,
    PIDController,
    RegenController,
    TraditionalSMCController,
    ZeroDutyController,
    ideal_buck_duty_for_power,
)
from ..simulation.scenario_runner import ComponentBundle
from ..tracking import RegenerativeReferenceState, build_reference_state
from .perturbation import PlantOverride, disable_storage

#: 主算法 label
OPTIMIZED_LABEL = "rhonn_nsmc"

CONTROLLER_PROFILE_DEFAULT = "default"
CONTROLLER_PROFILE_BALANCED = "balanced"
CONTROLLER_PROFILE_ROBUST = "robust"
CONTROLLER_PROFILES = (
    CONTROLLER_PROFILE_DEFAULT,
    CONTROLLER_PROFILE_BALANCED,
    CONTROLLER_PROFILE_ROBUST,
)

# 三套 profile 共用同一套被控对象参考约束：储能吸收匹配电压、同拍
# BMS/SOC 充电许可，以及保护反馈的声明内阻上界。把数值放在 profile
# 装配表中，避免依赖 RegenerativeReferenceState 的隐式默认值。
PROFILE_GUARDED_REFERENCE_UPPER_FACTOR = {
    CONTROLLER_PROFILE_DEFAULT: 2.5,
    CONTROLLER_PROFILE_BALANCED: 2.5,
    CONTROLLER_PROFILE_ROBUST: 2.5,
}
PROFILE_ASSEMBLY_RULES = {
    profile: {
        "reference_assembly": "storage_matched",
        "guarded_reference_upper_factor": PROFILE_GUARDED_REFERENCE_UPPER_FACTOR[profile],
        "soc_permission": "same_tick_bms_charge_limit",
    }
    for profile in CONTROLLER_PROFILES
}

#: 主算法量测预滤波的**物理时间常数**（s）。只对 ``default`` profile 生效。
#:
#: 标定依据（``docs/measurement_prefilter_2026-11-07.md``，交付步长 ``dt = 1e-4``）：
#: 关闭时 s8 噪声族达成率 82.9%（1%）/ 66.6%（5%）；取 1.9 ms 后升到
#: 96.9% / 78.5%，其余 12 场景代价 −0.01%~−0.04%。
#: 用时间常数而不是每拍系数，是因为后者随步长改变滤波带宽（跨 Ts 不可比）。
PROFILE_MEASUREMENT_FILTER_TIME_CONSTANT_S = {
    CONTROLLER_PROFILE_DEFAULT: 1.9e-3,
    CONTROLLER_PROFILE_BALANCED: 0.0,
    CONTROLLER_PROFILE_ROBUST: 0.0,
}

#: 储能内阻在线估计的一阶低通时间常数（s）。只对 ``default`` profile 生效。
#:
#: 依据 ``docs/storage_resistance_identification_2026-11-07.md``：参考电压的
#: 「储能吸收匹配」式用的是装配内阻 ``R``，而对象真实吸收电流是
#: ``(v_out − V_oc)/R_真``，于是回收量 ∝ ``R_装配/R_真``——实测 1.5/2/3 倍内阻时
#: 净再生 4.03 → 2.71/2.04/1.36 kWh；在线估计后三种情形全部回到 4.02~4.03 kWh。
#: ``0`` = 关闭（历史口径），研究用 balanced/robust 保持关闭。
PROFILE_STORAGE_RESISTANCE_TIME_CONSTANT_S = {
    CONTROLLER_PROFILE_DEFAULT: 0.2,
    CONTROLLER_PROFILE_BALANCED: 0.0,
    CONTROLLER_PROFILE_ROBUST: 0.0,
}

_BALANCED_SCHUR = 0.7
_BALANCED_ETA = 0.005
_BALANCED_METRIC_WINDOW = 30
_BALANCED_MIN_DWELL_STEPS = 60

_ROBUST_SCHUR = 0.6
_ROBUST_ETA = 0.01
_ROBUST_METRIC_WINDOW = 30
_ROBUST_MIN_DWELL_STEPS = 60
_ROBUST_COMMAND_SMOOTHING_ALPHA = 0.5

#: 用来"锁死"滤波器模式的阈值（让模式切换永不发生）
_FIXED_MODE_THRESHOLD = 1.0e12


class IdealDutyController:
    """理想控制器（能量回收率上界参照）。

    占空比直接取"把**可用**再生功率全部送进储能"的无损 buck 理想值，
    并对 PWM 硬边界做保方向饱和。它不建模任何动态，因此结果偏乐观。
    """

    name = "ideal_upper_bound"

    def __init__(
        self,
        limits: Optional[DutyLimits] = None,
        *,
        efficiency: float = 1.0,
    ) -> None:
        self.limits = limits or DutyLimits()
        self.efficiency = float(efficiency)
        if not np.isfinite(self.efficiency) or not 0.0 < self.efficiency <= 1.0:
            raise ControllerError("efficiency 必须在 (0, 1] 内")
        self._step_index = 0

    def reset(self) -> None:
        self._step_index = 0

    def compute(self, observation: ControllerObservation) -> ControllerCommand:
        # 目标功率取「电机侧请求」与「电机包络」的较小者——上界参照也不能凭空造能量。
        #
        # 方案问题 34（2026-09-26）修正两处措辞与一处事实：
        # ① 原文注释把第二项写成「变流器可用」，**不对**——
        #    ``available_regen_power_w`` 是 ``convert_wheel_regen`` 输出的
        #    **轮端机械电机包络**（``envelope_power_limit_w × dc_link_derating``），
        #    既不含 SOC、也不含变流器容量。本控制器因此**完全不含变流器容量约束**
        #    （``P_conv = v_out·i_L,max·η`` 从未参与），这也是它「不建模任何动态、
        #    结果偏乐观」的一部分。
        # ② 这一项在本 ``min()`` 中**恒不可能**成为紧约束：两项同源且
        #    ``available ≥ requested / η ≥ requested``，故 ``min()`` 恒等于
        #    ``requested``（实测官方 9 个场景 ``available < requested`` 的拍数为 0）。
        #    保留它以与 ``tracking.py`` ③ 的项名一致，但**不要**以为它在起约束作用。
        target = min(
            max(0.0, observation.requested_regen_power_w),
            max(0.0, observation.available_regen_power_w),
        )
        duty = ideal_buck_duty_for_power(
            target_output_power_w=target,
            input_voltage_v=observation.input_voltage_v,
            output_voltage_v=observation.output_voltage_v,
            efficiency=self.efficiency,
        )
        duty = float(np.clip(duty, 0.0, self.limits.u0_max))
        self._step_index += 1
        return ControllerCommand(
            duty_cycle_T1=duty,
            duty_cycle_T2=0.0,
            note=f"ideal_upper_bound k={self._step_index} P_target={target:.6g} d1={duty:.6f}",
        ).validate(self.limits)


@dataclass(frozen=True)
class ValidationBaseline:
    """一项可运行的对比配置。"""

    label: str
    description: str
    build_controller: Callable[[ComponentBundle], RegenController]
    #: 该项自带的被控对象扰动工厂（如"无储能"需要 bundle 里的储能参数）
    build_plant_override: Optional[Callable[[ComponentBundle], Optional[PlantOverride]]] = None
    #: 需要**采样步长**才能正确装配的项（主算法与其滤波器对照项）。
    #:
    #: 主算法的辨识器要用真实 ``dt`` 构造控制通道增益先验（方案问题 18）——
    #: ``B = ∂x̂/∂u`` 是**一步**灵敏度，幅值正比于 ``dt``。没有这个入口时，
    #: 装配层只能落回默认步长，把幅值热启动按 ``dt`` 比例带偏，且不会自己报错。
    build_controller_with_dt: Optional[Callable[[ComponentBundle, float], RegenController]] = None
    #: 是否为主算法（对比表里作为 optimized 列）
    is_optimized: bool = False
    data_status: str = "simulation"
    notes: Tuple[str, ...] = ()

    def controller(
        self, bundle: ComponentBundle, *, sample_time_s: Optional[float] = None
    ) -> RegenController:
        """装配控制器；``sample_time_s`` 给定时优先走带步长的装配路径。"""
        if sample_time_s is not None and self.build_controller_with_dt is not None:
            return self.build_controller_with_dt(bundle, float(sample_time_s))
        return self.build_controller(bundle)

    def plant_override(self, bundle: ComponentBundle) -> Optional[PlantOverride]:
        if self.build_plant_override is None:
            return None
        return self.build_plant_override(bundle)


def _reference(bundle: ComponentBundle) -> RegenerativeReferenceState:
    """问题 13 / 21 / 30 裁定的正式参考量（**唯一**装配入口）。

    从被控对象的**同一**参数对象取窗口与电流上限（问题 13），并取储能侧的开路
    电压与内阻以启用「储能吸收匹配电压」（问题 21）——后者让方案
    ``modes.regen_charge`` 要求的 ``d2 = 0`` 真正可行。主算法与 PI/PID/SMC
    基线共用本函数，保证参考量口径一致。

    问题 30 修订（2026-09-26）：改为调用
    :func:`~regenerative_braking.tracking.build_reference_state`，
    使本函数与 ``simulation/scenario_runner.py::default_baseline_cases``
    **落到同一处实现**——此前两者分别调用两个 classmethod，
    于是同一标签在阶段 1/2 入口与阶段 9 套件下装配出两个不同控制器。
    """
    return build_reference_state(bundle.converter_params, bundle.storage_params)


def _fixed_mode_identifier(
    mode: str, bundle: ComponentBundle, sample_time_s: Optional[float]
) -> OnlineIdentifier:
    """构造一个滤波器模式被锁死的在线辨识器（族 7 的 EKF/UKF 对照用）。"""

    return build_online_identifier(
        rhonn=with_control_channel_gain_prior(
            None, bundle.converter_params, sample_time_s
        ),
        mode=ModeSelectorConfig(
            min_dwell_steps=10**9,
            initial_mode=mode,
            residual_threshold=_FIXED_MODE_THRESHOLD,
            curvature_threshold=_FIXED_MODE_THRESHOLD,
            speed_jerk_threshold=_FIXED_MODE_THRESHOLD,
            current_rate_threshold=_FIXED_MODE_THRESHOLD,
            gradient_step_threshold=_FIXED_MODE_THRESHOLD,
            power_step_threshold=_FIXED_MODE_THRESHOLD,
        ),
    )


def _fixed_filter_controller(
    bundle: ComponentBundle, mode: str, sample_time_s: Optional[float]
) -> RegenController:
    controller = build_closed_loop_controller(
        limits=bundle.converter_params.duty_limits,
        identifier=_fixed_mode_identifier(mode, bundle, sample_time_s),
        converter_params=bundle.converter_params,
        storage_params=bundle.storage_params,
        sample_time_s=sample_time_s,
    )
    return controller


def _profile_controller(
    bundle: ComponentBundle,
    profile: str,
    sample_time_s: Optional[float],
    reference_strategy: str = REFERENCE_STORAGE_MATCHED,
    reference_upper_factor: Optional[float] = None,
) -> RegenController:
    """按验证 profile 装配主算法；``default`` 保持既有默认路径。"""

    if profile not in CONTROLLER_PROFILES:
        raise ValueError(
            f"未知 controller profile {profile!r}；可用：{CONTROLLER_PROFILES}"
        )
    guarded_factor = None
    if reference_strategy == REFERENCE_GUARDED_CURRENT_FEEDBACK:
        guarded_factor = (
            PROFILE_ASSEMBLY_RULES[profile]["guarded_reference_upper_factor"]
            if reference_upper_factor is None else reference_upper_factor
        )
    if profile == CONTROLLER_PROFILE_DEFAULT:
        return build_closed_loop_controller(
            limits=_limits_for_bundle(bundle),
            converter_params=bundle.converter_params,
            storage_params=bundle.storage_params,
            sample_time_s=sample_time_s,
            reference_strategy=reference_strategy,
            measurement_filter_time_constant_s=PROFILE_MEASUREMENT_FILTER_TIME_CONSTANT_S[profile],
            storage_resistance_time_constant_s=PROFILE_STORAGE_RESISTANCE_TIME_CONSTANT_S[profile],
            feedback_resistance_upper_factor=guarded_factor,
            controller_profile=profile,
        )
    if profile == CONTROLLER_PROFILE_BALANCED:
        schur = _BALANCED_SCHUR
        eta = _BALANCED_ETA
        metric_window = _BALANCED_METRIC_WINDOW
        min_dwell_steps = _BALANCED_MIN_DWELL_STEPS
    else:
        schur = _ROBUST_SCHUR
        eta = _ROBUST_ETA
        metric_window = _ROBUST_METRIC_WINDOW
        min_dwell_steps = _ROBUST_MIN_DWELL_STEPS
    identifier = build_online_identifier(
        ekf=EKFConfig(eta=eta),
        ukf=UKFConfig(eta=eta),
        mode=ModeSelectorConfig(
            metric_window=metric_window,
            min_dwell_steps=min_dwell_steps,
        ),
    )
    return build_closed_loop_controller(
        limits=_limits_for_bundle(bundle),
        identifier=identifier,
        nsmc_config=NSMCConfig(
            schur_eigenvalue=schur,
            command_smoothing_alpha=(
                _ROBUST_COMMAND_SMOOTHING_ALPHA
                if profile == CONTROLLER_PROFILE_ROBUST
                else 1.0
            ),
        ),
        converter_params=bundle.converter_params,
        storage_params=bundle.storage_params,
        sample_time_s=sample_time_s,
        reference_strategy=reference_strategy,
        measurement_filter_time_constant_s=PROFILE_MEASUREMENT_FILTER_TIME_CONSTANT_S[profile],
        storage_resistance_time_constant_s=PROFILE_STORAGE_RESISTANCE_TIME_CONSTANT_S[profile],
        feedback_resistance_upper_factor=guarded_factor,
        controller_profile=profile,
    )


def _limits_for_bundle(bundle: ComponentBundle) -> DutyLimits:
    return bundle.converter_params.duty_limits


def baseline_catalog(
    controller_profile: str = CONTROLLER_PROFILE_DEFAULT,
    *, reference_strategy: str = REFERENCE_STORAGE_MATCHED,
    reference_upper_factor: Optional[float] = None,
) -> Tuple[ValidationBaseline, ...]:
    """全部 baseline（含主算法）。顺序即对比表行顺序。"""

    if reference_strategy not in REFERENCE_STRATEGIES:
        raise ValueError(f"未知参考策略 {reference_strategy!r}，允许：{REFERENCE_STRATEGIES}")
    if reference_upper_factor is not None:
        if (reference_strategy != REFERENCE_GUARDED_CURRENT_FEEDBACK or
            isinstance(reference_upper_factor, (bool, np.bool_)) or
            not np.isfinite(reference_upper_factor) or reference_upper_factor < 1):
            raise ValueError("参考内阻上界只允许保护策略显式配置有限且不小于1的倍率")
    if controller_profile not in CONTROLLER_PROFILES:
        raise ValueError(
            f"未知 controller profile {controller_profile!r}；可用：{CONTROLLER_PROFILES}"
        )

    def _limits(bundle: ComponentBundle) -> DutyLimits:
        return bundle.converter_params.duty_limits

    return (
        ValidationBaseline(
            label="uncontrolled_zero_duty",
            description="无控制：占空比恒 0，再生能量全部回网",
            build_controller=lambda bundle: ZeroDutyController(_limits(bundle)),
        ),
        ValidationBaseline(
            label="fixed_duty_d1_0.75",
            description="固定占空比 d1=0.75（刚过充电门槛，轻载）",
            build_controller=lambda bundle: FixedDutyController(0.75, 0.0, _limits(bundle)),
        ),
        ValidationBaseline(
            label="fixed_duty_d1_0.85",
            description="固定占空比 d1=0.85（逼近 u0=0.9，受储能功率约束）",
            build_controller=lambda bundle: FixedDutyController(0.85, 0.0, _limits(bundle)),
        ),
        ValidationBaseline(
            label="pi",
            description="定常 PI（与主算法共用滑模面/参考量口径）",
            build_controller=lambda bundle: PIController(_reference(bundle), limits=_limits(bundle)),
        ),
        ValidationBaseline(
            label="pid",
            description="定常 PID（微分时间默认等于一个采样步长）",
            build_controller=lambda bundle: PIDController(_reference(bundle), limits=_limits(bundle)),
        ),
        ValidationBaseline(
            label="traditional_smc",
            description="传统滑模控制（无边界层，bang-bang）",
            build_controller=lambda bundle: TraditionalSMCController(
                _reference(bundle), limits=_limits(bundle)
            ),
        ),
        ValidationBaseline(
            label="ideal_upper_bound",
            description="理想控制器上界参照（无损 buck 理想占空比）",
            build_controller=lambda bundle: IdealDutyController(_limits(bundle)),
            notes=("忽略开关损耗与母线动态，是回收率的乐观上界",),
        ),
        ValidationBaseline(
            label="no_storage_zero_duty",
            description="无储能（仅回网）：储能充放电功率上限置 0 + 占空比恒 0",
            build_controller=lambda bundle: ZeroDutyController(_limits(bundle)),
            build_plant_override=make_no_storage_override,
            notes=("物理上等价于 uncontrolled_zero_duty，但结果行可验证（回收与弃能均为 0）",),
        ),
        ValidationBaseline(
            label=OPTIMIZED_LABEL,
            description=(
                "主算法：RHONN + EKF/UKF（可解释模式切换）+ NSMC 联合闭环；"
                f"参数 profile={controller_profile}；reference_strategy={reference_strategy}"
            ),
            build_controller=lambda bundle: _profile_controller(
                bundle, controller_profile, None, reference_strategy, reference_upper_factor
            ),
            build_controller_with_dt=lambda bundle, dt: _profile_controller(
                bundle, controller_profile, dt, reference_strategy, reference_upper_factor
            ),
            is_optimized=True,
            notes=("八条方案问题项的裁定结果在 audit() 中逐条显式标注",),
        ),
    )


def make_no_storage_override(bundle: ComponentBundle) -> PlantOverride:
    """为 ``no_storage_zero_duty`` 生成真实的被控对象扰动（需要 bundle）。"""

    return PlantOverride(
        storage_params=disable_storage(bundle.storage_params),
        description="储能充放电功率上限置 0（无储能，仅回网）",
    )


def filter_comparison_baselines() -> Tuple[ValidationBaseline, ...]:
    """族 7 专用的滤波器对照项：固定 EKF / 固定 UKF / 主算法（切换）。

    用途：验证"强非线性下 UKF 是否优于 EKF"这一方案假设。
    阶段 5 已证本问题上 UKF 与 EKF 逐项恒等，因此三项结果应当**完全一致**——
    这本身就是一条可执行的结论（见 ``tests/test_validation.py``）。
    """

    return (
        ValidationBaseline(
            label="rhonn_nsmc_fixed_ekf",
            description="主算法但滤波器锁死在 EKF（不做模式切换）",
            build_controller=lambda bundle: _fixed_filter_controller(bundle, MODE_EKF, None),
            build_controller_with_dt=lambda bundle, dt: _fixed_filter_controller(
                bundle, MODE_EKF, dt
            ),
            is_optimized=True,
            notes=("用于族 7 的 EKF/UKF 对照",),
        ),
        ValidationBaseline(
            label="rhonn_nsmc_fixed_ukf",
            description="主算法但滤波器锁死在 UKF（不做模式切换）",
            build_controller=lambda bundle: _fixed_filter_controller(bundle, MODE_UKF, None),
            build_controller_with_dt=lambda bundle, dt: _fixed_filter_controller(
                bundle, MODE_UKF, dt
            ),
            is_optimized=True,
            notes=("用于族 7 的 EKF/UKF 对照",),
        ),
    )


def baseline_labels(
    controller_profile: str = CONTROLLER_PROFILE_DEFAULT,
) -> Tuple[str, ...]:
    return tuple(item.label for item in baseline_catalog(controller_profile))


def baseline_by_label(
    label: str,
    controller_profile: str = CONTROLLER_PROFILE_DEFAULT,
) -> ValidationBaseline:
    for item in baseline_catalog(controller_profile):
        if item.label == label:
            return item
    raise KeyError(
        f"未知 baseline label：{label!r}；可用：{baseline_labels(controller_profile)}"
    )
