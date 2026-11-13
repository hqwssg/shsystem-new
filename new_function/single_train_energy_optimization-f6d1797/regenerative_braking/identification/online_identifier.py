"""在线辨识器（阶段 8 的辨识侧）：RHONN + EKF/UKF + 模式切换。

把阶段 3–6 的三件东西接成一个**在线**组件：

    RHONN（状态递归预测）  ←  EKF 或 UKF（权重校正）  ←  ModeSelector（选谁校正）

--------------------------------------------------------------------------
时序（必须与 :mod:`~regenerative_braking.simulation.regenerative_simulator` 对齐）
--------------------------------------------------------------------------

方案的状态方程是 ``x̂_{i,k+1} = f(x_k, x̂_k, u_k)``，即 ``x_k`` 与 ``u_k`` 同指标。
仿真单步里控制器先看到 ``x_k`` 再决定 ``u_k``，因此辨识必须在**控制器之后**执行：

    第 k 拍：  观测量测 x_k  →  控制器算 u_k  →  辨识更新 (x_k, u_k)  →  x̂_{k+1}

于是 ``x̂_k`` 在第 k−1 拍就已经算好，控制器用的正是「RHONN 的状态估计值」，
与方案 §4.2.1.3（2）「基于 RHONN 的状态估计值计算 ``u_eq``」一致。

**模式决策是因果的**：第 k 拍用第 k 拍观测到的残差去决定**第 k+1 拍**用哪个
滤波器。首拍没有历史预测、残差未定义，依赖残差的两类判据本拍不参与判断
（见 :class:`~regenerative_braking.identification.mode_selector.ModeSample`）。

--------------------------------------------------------------------------
切换时协方差如何接续
--------------------------------------------------------------------------

EKF 与 UKF **共享同一个 RHONN 实例**（权重是单一真相源），但各自持有自己的
权重误差协方差 ``P``。切换时若放任不管，被切到的那个滤波器会带着**初始** ``P``
重新开始，造成一次无物理依据的跳变。因此本模块在切换发生的那一拍把 ``P``
从旧滤波器**接管**过来（:meth:`EKF.adopt_covariance` / :meth:`UKF.adopt_covariance`）。

这一步在数学上是自洽的：两个滤波器估计的是同一组权重，
而阶段 5 已证 UKF 与 EKF 在本问题上逐项恒等，``P`` 本就应当一致。
若将来 RHONN 结构改动使二者不再恒等，接管仍然成立（都是同一个权重的
误差协方差），但恒等性断言会失败并提示重新评估分工依据。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Mapping, Optional, Tuple, Union

import numpy as np

from .ekf import EKF, EKFConfig, EKFUpdateRecord
from .mode_selector import (
    FILTER_MODES,
    MODE_EKF,
    SCHEME_ISSUE_MODE_SCALE_NOT_SOURCED,
    ModeDecision,
    ModeSample,
    ModeSelector,
    ModeSelectorConfig,
)
from .rhonn import RHONN, RHONNConfig, RHONNError, RHONNStepRecord
from .ukf import UKF, UKFConfig, UKFUpdateRecord

UpdateRecord = Union[EKFUpdateRecord, UKFUpdateRecord]


class OnlineIdentifierError(RHONNError):
    """在线辨识器配置或输入不合法。"""


@dataclass(frozen=True)
class IdentificationSample:
    """在线辨识一拍所需的全部输入（全部 SI）。

    ``state_actual`` 是 ``(v_out, i_out)`` 的实际量测，``control`` 是本拍
    **将要施加**的 ``(T1, T2)`` 占空比。其余字段只供模式切换判据使用。
    """

    time_s: float
    state_actual: np.ndarray
    control: np.ndarray
    speed_mps: float
    requested_regen_power_w: float
    inductor_current_a: float
    gradient_per_mille: float = 0.0


@dataclass(frozen=True)
class IdentificationRecord:
    """在线辨识一拍的完整留痕。"""

    step_index: int
    time_s: float

    #: 本拍实际采用的滤波器模式（由**上一拍**的模式决策确定）
    filter_mode: str
    #: 本拍的辨识误差 ``e_k = x_k − x̂_k``；首拍无历史预测时为 ``None``
    innovation: Optional[np.ndarray]
    #: 本拍校正前对当前时刻的预测 ``x̂_k``（即控制器刚刚用过的那个估计）
    prediction_used: Optional[np.ndarray]
    #: 本拍产生的新预测 ``x̂_{k+1}``
    predicted_next: np.ndarray
    #: 本拍实际施加的权重增量；首拍为 ``None``
    parameter_update: Optional[np.ndarray]
    covariance_trace: float
    covariance_min_eigenvalue: float

    #: 本拍消费观测后作出的模式决策（决定**下一拍**用哪个滤波器）
    decision: ModeDecision
    #: 本拍是否因模式切换而接管了协方差
    covariance_adopted: bool = False
    #: 归一化辨识误差 ``‖e_k ⊘ state_scale‖``（无量纲，便于跨量程比较）
    normalised_innovation: Optional[float] = None

    def describe(self) -> str:
        innovation = "-" if self.normalised_innovation is None else f"{self.normalised_innovation:.6g}"
        return (
            f"k={self.step_index} mode={self.filter_mode} "
            f"|e|/scale={innovation} tr(P)={self.covariance_trace:.6g} "
            f"| {self.decision.describe()}"
        )


@dataclass
class OnlineIdentifierConfig:
    """在线辨识器的组合配置与资源上限。"""

    rhonn: RHONNConfig = field(default_factory=RHONNConfig)
    ekf: EKFConfig = field(default_factory=EKFConfig)
    ukf: UKFConfig = field(default_factory=UKFConfig)
    mode: ModeSelectorConfig = field(default_factory=ModeSelectorConfig)

    #: 保留最近多少条辨识记录用于诊断（0 表示不保留，避免长跑占内存）
    history_limit: int = 2000

    #: 切换时是否把 P 从旧滤波器接管过来（见模块 docstring）
    adopt_covariance_on_switch: bool = True


class OnlineIdentifier:
    """RHONN + EKF/UKF + 可解释模式切换的在线辨识器。

    典型用法（每个采样步一次，**在控制器之后**）::

        record = identifier.update(sample)
        # record.predicted_next 即 x̂_{k+1}，下一拍控制器会用到的估计值
    """

    name = "online_identifier"

    def __init__(
        self,
        config: Optional[OnlineIdentifierConfig] = None,
        *,
        rhonn: Optional[RHONN] = None,
        ekf: Optional[EKF] = None,
        ukf: Optional[UKF] = None,
        mode_selector: Optional[ModeSelector] = None,
    ) -> None:
        self.config = config or OnlineIdentifierConfig()
        cfg = self.config

        self.rhonn = rhonn if rhonn is not None else RHONN(cfg.rhonn)
        self.ekf = ekf if ekf is not None else EKF(self.rhonn, cfg.ekf)
        self.ukf = ukf if ukf is not None else UKF(self.rhonn, cfg.ukf)
        self.mode_selector = mode_selector if mode_selector is not None else ModeSelector(cfg.mode)

        # 共享 RHONN 是单一真相源：两个滤波器的权重必须指向同一实例，
        # 否则切换会悄悄丢掉已学到的权重。
        for name, filter_ in (("ekf", self.ekf), ("ukf", self.ukf)):
            if filter_.rhonn is not self.rhonn:
                raise OnlineIdentifierError(
                    f"{name} 持有的 RHONN 与辨识器的 RHONN 不是同一实例；"
                    "切换滤波器时权重会丢失，因此不允许这样做。"
                )
        if self.ekf.n_parameters != self.ukf.n_parameters:
            raise OnlineIdentifierError("EKF 与 UKF 的参数维度不一致，无法共享协方差")

        # 问题 28：切换判据的归一化尺度必须与 RHONN 的**同一个数**。
        # 判据比较 ``‖e ⊘ state_scale‖`` 与阈值，而 ``e`` 就是 RHONN 的辨识误差；
        # 两侧尺度不同等于把阈值标定的含义悄悄换掉（阈值不动、残差被重缩放）。
        # 默认路径两处默认值恰好相同，所以这个分叉只在自定义 RHONN 尺度时出现，
        # 且**不会报任何错** —— 故在这里显式拒绝。
        rhonn_scale = tuple(float(v) for v in self.rhonn.config.state_scale)
        mode_scale = tuple(float(v) for v in self.mode_selector.config.state_scale)
        if len(rhonn_scale) != len(mode_scale) or any(
            abs(a - b) > 1e-12 for a, b in zip(rhonn_scale, mode_scale)
        ):
            raise OnlineIdentifierError(
                f"方案问题 {SCHEME_ISSUE_MODE_SCALE_NOT_SOURCED}：模式切换判据的归一化尺度"
                f"与 RHONN 的不同源——RHONNConfig.state_scale = {rhonn_scale}，"
                f"ModeSelectorConfig.state_scale = {mode_scale}。"
                "判据比较的是 RHONN 的辨识误差，两者必须逐位相同；"
                "请把 ModeSelectorConfig.state_scale 设为与 RHONNConfig 一致，"
                "或直接让 build_online_identifier 按 RHONN 配置派生（不传 mode= 即可）。"
            )

        self._step_index = 0
        self._records: Deque[IdentificationRecord] = deque(maxlen=max(0, cfg.history_limit))
        self._mode_step_counts = {mode: 0 for mode in FILTER_MODES}
        self._switch_count = 0

    # ------------------------------------------------------------------
    # 只读属性
    # ------------------------------------------------------------------

    @property
    def step_index(self) -> int:
        return self._step_index

    @property
    def filter_mode(self) -> str:
        """当前生效的滤波器模式（= 下一拍将采用的模式）。"""
        return self.mode_selector.current_mode

    @property
    def records(self) -> Tuple[IdentificationRecord, ...]:
        """最近若干条辨识记录（上限由 ``history_limit`` 决定）。"""
        return tuple(self._records)

    @property
    def last_record(self) -> Optional[IdentificationRecord]:
        return self._records[-1] if self._records else None

    @property
    def state_estimate(self) -> Optional[np.ndarray]:
        """当前的状态估计 ``x̂``（供控制器取用）。"""
        return self.rhonn.state_estimate

    @property
    def mode_step_counts(self) -> Mapping[str, int]:
        """各模式实际执行了多少拍（用于审计切换是否真的生效）。"""
        return dict(self._mode_step_counts)

    @property
    def switch_count(self) -> int:
        return self._switch_count

    def reset(self) -> None:
        """清空递归状态与模式历史；**权重保留**（跨航次复用同一辨识器）。"""
        self.rhonn.reset()
        self.ekf.reset()
        self.ukf.reset()
        self.mode_selector.reset()
        self._step_index = 0
        self._records.clear()
        self._mode_step_counts = {mode: 0 for mode in FILTER_MODES}
        self._switch_count = 0

    # ------------------------------------------------------------------
    # 单步
    # ------------------------------------------------------------------

    def _active_filter(self, mode: str):
        if mode == MODE_EKF:
            return self.ekf
        return self.ukf

    def _adopt_covariance(self, source_mode: str) -> bool:
        """把 P 从 ``source_mode`` 的滤波器接管到另一个滤波器。"""
        source = self._active_filter(source_mode)
        target = self.ukf if source_mode == MODE_EKF else self.ekf
        target.adopt_covariance(source.covariance)
        return True

    def update(self, sample: IdentificationSample) -> IdentificationRecord:
        """消费一拍观测，完成「校正权重 → 产生新预测 → 决定下一拍模式」。"""
        state = np.asarray(sample.state_actual, dtype=float)
        control = np.asarray(sample.control, dtype=float)
        if state.shape != (self.rhonn.state_dim,):
            raise OnlineIdentifierError(
                f"state_actual 形状必须为 {(self.rhonn.state_dim,)}，实际为 {state.shape}"
            )
        if control.shape != (self.rhonn.control_dim,):
            raise OnlineIdentifierError(
                f"control 形状必须为 {(self.rhonn.control_dim,)}，实际为 {control.shape}"
            )

        mode = self.mode_selector.current_mode
        active = self._active_filter(mode)

        # 校正前对当前时刻的预测 —— 控制器本拍刚刚用过的就是它
        prediction_used = self.rhonn.state_estimate

        rhonn_record, update_record = active.step(state, control, time_s=sample.time_s)
        if not isinstance(rhonn_record, RHONNStepRecord):  # pragma: no cover - 防御
            raise OnlineIdentifierError("滤波器返回的 RHONN 记录类型异常")

        innovation = None if update_record is None else np.asarray(update_record.innovation, dtype=float)
        parameter_update = (
            None if update_record is None else np.asarray(update_record.parameter_update, dtype=float)
        )
        covariance = active.covariance

        # 模式决策：用本拍观测到的量，决定**下一拍**用哪个滤波器（因果）
        decision = self.mode_selector.update(
            ModeSample(
                time_s=sample.time_s,
                speed_mps=sample.speed_mps,
                requested_regen_power_w=sample.requested_regen_power_w,
                inductor_current_a=sample.inductor_current_a,
                gradient_per_mille=sample.gradient_per_mille,
                innovation=innovation,
            )
        )

        covariance_adopted = False
        if decision.switched:
            self._switch_count += 1
            if self.config.adopt_covariance_on_switch:
                covariance_adopted = self._adopt_covariance(mode)

        normalised = None
        if innovation is not None:
            scale = np.asarray(self.rhonn.config.state_scale, dtype=float)
            normalised = float(np.linalg.norm(innovation / scale))

        record = IdentificationRecord(
            step_index=self._step_index,
            time_s=float(sample.time_s),
            filter_mode=mode,
            innovation=innovation,
            prediction_used=None if prediction_used is None else np.asarray(prediction_used, dtype=float),
            predicted_next=np.asarray(rhonn_record.state_estimate, dtype=float),
            parameter_update=parameter_update,
            covariance_trace=float(np.trace(covariance)),
            covariance_min_eigenvalue=float(np.min(np.linalg.eigvalsh(covariance))),
            decision=decision,
            covariance_adopted=covariance_adopted,
            normalised_innovation=normalised,
        )

        self._records.append(record)
        self._mode_step_counts[mode] = self._mode_step_counts.get(mode, 0) + 1
        self._step_index += 1
        return record

    # ------------------------------------------------------------------
    # 审计
    # ------------------------------------------------------------------

    def audit(self) -> Mapping[str, object]:
        """辨识层审计摘要：各模式执行拍数、切换次数、原因分布。"""
        audit = dict(self.mode_selector.audit())
        audit.update(
            {
                "steps": self._step_index,
                "mode_step_counts": dict(self._mode_step_counts),
                "switch_count": self._switch_count,
                "final_mode": self.filter_mode,
            }
        )
        return audit


def build_online_identifier(
    *,
    mode: Optional[ModeSelectorConfig] = None,
    rhonn: Optional[RHONNConfig] = None,
    ekf: Optional[EKFConfig] = None,
    ukf: Optional[UKFConfig] = None,
    history_limit: int = 2000,
    adopt_covariance_on_switch: bool = True,
) -> OnlineIdentifier:
    """按默认配置装配一个在线辨识器（供阶段 8/9 直接调用）。

    问题 28：``mode`` 省略时，切换判据的 ``state_scale`` 按 ``rhonn`` 配置**派生**，
    而不是各自取默认值——两个默认值恰好相同只是巧合，一旦调用方自定义
    ``RHONNConfig.state_scale`` 就会静默分叉。显式传入 ``mode`` 时保留调用方的选择，
    但 :class:`OnlineIdentifier` 会在构造处校验它与 RHONN 同源，不一致即报错。
    """
    resolved_rhonn = rhonn or RHONNConfig()
    resolved_mode = (
        ModeSelectorConfig(state_scale=tuple(resolved_rhonn.state_scale))
        if mode is None
        else mode
    )
    config = OnlineIdentifierConfig(
        rhonn=resolved_rhonn,
        ekf=ekf or EKFConfig(),
        ukf=ukf or UKFConfig(),
        mode=resolved_mode,
        history_limit=history_limit,
        adopt_covariance_on_switch=adopt_covariance_on_switch,
    )
    return OnlineIdentifier(config)
