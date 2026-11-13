"""验证场景用的物理/观测扰动构件（阶段 9）。

三类扰动，全部以**显式、可复现、可审计**的方式实现，不修改任何被扰动模块的内部逻辑：

============================  ==============================  ==================
扰动                           实现方式                        用于哪些场景
============================  ==============================  ==================
载重变化                       替换 ``TrainBrakingProfile``     §9-3 载重变化
参数扰动                       替换变流器/储能参数对象           §9-6 参数扰动
观测噪声                       在控制器**外面**包一层扰动器       §9-8 测量噪声
模型失配                       被控对象用扰动参数、              §9-9 模型失配
                               控制器/辨识器仍用标称参数
============================  ==============================  ==================

关键约定：**扰动只作用在被控对象（plant）或控制器可见的观测量上，
不改变控制器/辨识器自身的参数**——除非该场景明确声明要做模型失配。
这样"标称模型 vs 真实对象"的差异才是可测量的，而不是被悄悄抹平。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, replace
from typing import Optional, Tuple

import numpy as np

from ..dynamics.dc_dc_converter import DCConverterParameters
from ..dynamics.storage_model import StorageParameters
from ..dynamics.train_braking_model import TrainBrakingProfile
from ..simulation.controllers import (
    ControllerCommand,
    ControllerObservation,
    RegenController,
)


class PerturbationError(ValueError):
    """扰动定义不合法。"""


# ---------------------------------------------------------------------------
# 被控对象扰动
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlantOverride:
    """对被控对象（plant）的替换。

    ``None`` 表示"该组件保持标称"。全部为 ``None`` 时等价于不扰动。
    """

    train: Optional[TrainBrakingProfile] = None
    converter_params: Optional[DCConverterParameters] = None
    storage_params: Optional[StorageParameters] = None
    description: str = ""
    data_status: str = "simulation"

    @property
    def is_noop(self) -> bool:
        return (
            self.train is None
            and self.converter_params is None
            and self.storage_params is None
        )


def scale_mass(
    train: TrainBrakingProfile,
    factor: float,
    *,
    label: str = "",
) -> TrainBrakingProfile:
    """按比例缩放列车质量（载重变化场景）。

    .. warning::
       只缩放 ``mass_kg``，**不缩放** ``max_brake_force_n``。这不是疏漏：
       共享数据里 ``max_brake_kN = 6200`` 自述为"工程虚拟预设"，
       没有随载重变化的依据；凭空按质量比例放大它是伪造。
       后果是重车可达减速度下降（本函数不隐藏这一点，
       :func:`regenerative_braking.simulation.profiles` 的可达性校验会如实报错），
       因此载重变化场景必须相应下调请求减速度。
    """

    if not np.isfinite(factor) or factor <= 0.0:
        raise PerturbationError(f"质量缩放系数必须为正有限值，实际为 {factor!r}")
    return replace(train, mass_kg=train.mass_kg * factor, name=f"{train.name}[{label or f'{factor:.2f}x'}]")


def scale_converter_parameter(
    params: DCConverterParameters,
    field: str,
    factor: float,
) -> DCConverterParameters:
    """按比例缩放变流器的某个标量参数（参数扰动场景）。"""

    if not hasattr(params, field):
        raise PerturbationError(f"变流器参数没有字段 {field!r}")
    current = getattr(params, field)
    if not isinstance(current, (int, float)) or isinstance(current, bool):
        raise PerturbationError(f"字段 {field!r} 不是标量，无法按比例缩放")
    if not np.isfinite(factor) or factor <= 0.0:
        raise PerturbationError(f"缩放系数必须为正有限值，实际为 {factor!r}")
    return replace(params, **{field: float(current) * factor})


def scale_storage_parameter(
    params: StorageParameters,
    field: str,
    factor: float,
) -> StorageParameters:
    """按比例缩放储能的某个标量参数（参数扰动场景）。"""

    if not hasattr(params, field):
        raise PerturbationError(f"储能参数没有字段 {field!r}")
    current = getattr(params, field)
    if not isinstance(current, (int, float)) or isinstance(current, bool):
        raise PerturbationError(f"字段 {field!r} 不是标量，无法按比例缩放")
    if not np.isfinite(factor) or factor <= 0.0:
        raise PerturbationError(f"缩放系数必须为正有限值，实际为 {factor!r}")
    return replace(params, **{field: float(current) * factor})


def set_storage_soc_initial(
    params: StorageParameters, soc_initial: float
) -> StorageParameters:
    """设置储能初始 SOC（SOC 接近上限场景）。"""

    if not np.isfinite(soc_initial):
        raise PerturbationError(f"soc_initial 必须为有限值，实际为 {soc_initial!r}")
    if not params.soc_min <= soc_initial <= params.soc_max:
        raise PerturbationError(
            f"soc_initial={soc_initial!r} 必须落在 [{params.soc_min}, {params.soc_max}] 内"
        )
    return replace(params, soc_initial=float(soc_initial))


def disable_storage(params: StorageParameters) -> StorageParameters:
    """把储能置为"不可充放"（无储能 / 仅回网场景）。

    做法是把充放电功率上限置 0，而**不**去改容量——容量仍在，只是不允许功率流入。
    这样 ``StorageBusRequest.available_charge_power_w`` 归零，
    变流器 sink 电流随之归零，全部再生能量只能回网，与"无储能"的物理行为一致。
    """

    return replace(
        params,
        max_charge_power_w=0.0,
        max_discharge_power_w=0.0,
        data_status=f"{params.data_status}+storage_disabled",
    )


# ---------------------------------------------------------------------------
# 观测噪声
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObservationNoise:
    """控制器可见观测量的加性/相对噪声定义。

    噪声模型（对每个通道独立采样）::

        量测值 = 真值 + relative_std · |真值| · z1 + absolute_std · z2

    其中 ``z1, z2 ~ N(0, 1)``。用相对项捕捉与量级成比例的误差，
    用绝对项给接近零的量（如占空比 0 时的输出电流）一个噪声底，
    避免相对项在小量上退化为 0。

    ``seed`` 固定 → 同一场景可复现。``reset()`` 会把随机数发生器复位，
    因此同一控制器实例重复运行同一场景得到逐位一致的结果。
    """

    relative_std: float = 0.0
    absolute_std_v: float = 0.0
    absolute_std_a: float = 0.0
    soc_std: float = 0.0
    speed_std: float = 0.0
    seed: int = 20260925

    def __post_init__(self) -> None:
        for name in ("relative_std", "absolute_std_v", "absolute_std_a", "soc_std", "speed_std"):
            value = getattr(self, name)
            if not np.isfinite(value) or value < 0.0:
                raise PerturbationError(f"{name} 必须为非负有限值，实际为 {value!r}")

    @property
    def is_noop(self) -> bool:
        return (
            self.relative_std == 0.0
            and self.absolute_std_v == 0.0
            and self.absolute_std_a == 0.0
            and self.soc_std == 0.0
            and self.speed_std == 0.0
        )

    def describe(self) -> str:
        return (
            f"rel={self.relative_std:.3%} "
            f"abs_v={self.absolute_std_v:.3g}V abs_a={self.absolute_std_a:.3g}A "
            f"soc_std={self.soc_std:.4g} speed_std={self.speed_std:.4g}"
        )


def _noisy(value: float, relative_std: float, absolute_std: float, rng) -> float:
    noise = relative_std * abs(value) * rng.standard_normal()
    if absolute_std > 0.0:
        noise += absolute_std * rng.standard_normal()
    return float(value + noise)


class NoisyObservationController:
    """在控制器**外面**加一层观测噪声的装饰器。

    为什么放在外面而不是改仿真器：仿真器内部构造 ``ControllerObservation``，
    从外面装饰可以做到**一行不改仿真器主体**，与阶段 8 的做法一致；
    同时噪声对"控制"和"辨识"同时生效——因为两者读的都是同一个观测对象，
    这正是"测量噪声影响辨识鲁棒性"的真实语义。

    ``name`` 透传内层控制器并追加噪声标签，使对比表的行标识可区分。
    """

    def __init__(self, controller: RegenController, noise: ObservationNoise) -> None:
        if noise.is_noop:
            raise PerturbationError("噪声参数全为 0 时不需要装饰器，请直接使用原控制器")
        self.inner = controller
        self.noise = noise
        self._rng = np.random.default_rng(noise.seed)

    @property
    def name(self) -> str:
        return f"{self.inner.name}+noise"

    def reset(self) -> None:
        self._rng = np.random.default_rng(self.noise.seed)
        self.inner.reset()

    @property
    def sample_time_s(self):
        return getattr(self.inner, "sample_time_s", None)

    def accept_applied_command(self, command):
        notify = getattr(self.inner, "accept_applied_command", None)
        if notify is not None:
            notify(command)

    def compute(self, observation: ControllerObservation) -> ControllerCommand:
        return self.inner.compute(self.perturb(observation))

    def perturb(self, observation: ControllerObservation) -> ControllerObservation:
        """把噪声叠加到观测量上（公开出来便于测试逐项核对）。"""

        noise = self.noise
        rng = self._rng
        return replace(
            observation,
            speed_mps=max(
                0.0,
                _noisy(observation.speed_mps, noise.relative_std, noise.speed_std, rng),
            ),
            input_voltage_v=max(
                1.0,
                _noisy(observation.input_voltage_v, noise.relative_std, noise.absolute_std_v, rng),
            ),
            output_voltage_v=max(
                1.0,
                _noisy(observation.output_voltage_v, noise.relative_std, noise.absolute_std_v, rng),
            ),
            inductor_current_a=max(
                0.0,
                _noisy(observation.inductor_current_a, noise.relative_std, noise.absolute_std_a, rng),
            ),
            output_current_a=max(
                0.0,
                _noisy(observation.output_current_a, noise.relative_std, noise.absolute_std_a, rng),
            ),
            soc=float(np.clip(observation.soc + noise.soc_std * rng.standard_normal(), 0.0, 1.0)),
        )


# ---------------------------------------------------------------------------
# 组合
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PerturbationBundle:
    """一个验证场景携带的全部扰动。"""

    plant: Optional[PlantOverride] = None
    noise: Optional[ObservationNoise] = None
    #: True = 控制器/辨识器仍按标称参数装配（模型失配场景）
    controller_uses_nominal: bool = True

    @property
    def is_noop(self) -> bool:
        plant_noop = self.plant is None or self.plant.is_noop
        noise_noop = self.noise is None or self.noise.is_noop
        return plant_noop and noise_noop

    def describe(self) -> Tuple[str, ...]:
        notes = []
        if self.plant is not None and not self.plant.is_noop:
            notes.append(self.plant.description or "被控对象已扰动")
        if self.noise is not None and not self.noise.is_noop:
            notes.append(f"观测噪声：{self.noise.describe()}")
        if notes and not self.controller_uses_nominal:
            notes.append("控制器/辨识器同时使用扰动后的参数")
        return tuple(notes)


def apply_plant_override(bundle, override: Optional[PlantOverride]):
    """把 :class:`PlantOverride` 应用到 :class:`ComponentBundle` 上。

    ``bundle`` 是 :class:`regenerative_braking.simulation.scenario_runner.ComponentBundle`，
    这里用 ``dataclasses.replace`` 返回**新实例**，不修改传入对象。
    """

    if override is None or override.is_noop:
        return bundle
    changes = {}
    if override.train is not None:
        changes["train"] = override.train
    if override.converter_params is not None:
        changes["converter_params"] = override.converter_params
    if override.storage_params is not None:
        changes["storage_params"] = override.storage_params
    status = dict(bundle.parameter_status)
    if override.train is not None:
        status["train_parameters"] = f"{override.train.data_status}+perturbed"
    if override.converter_params is not None:
        status["dc_dc_parameters"] = f"{override.converter_params.data_status}+perturbed"
    if override.storage_params is not None:
        status["storage_parameters"] = f"{override.storage_params.data_status}+perturbed"
    changes["parameter_status"] = status
    return dataclasses.replace(bundle, **changes)
