"""EKF / UKF 可解释模式切换（阶段 6）。

对应技术方案 §4.2.1.3「适配不同制动场景」：方案要求按场景在 EKF 与 UKF 之间
切换，但**未给出切换判据**。算法文档 §5.4 把判据定为六类可解释指标
（不得硬编码随机切换）：

===================================  ==========================  ==============
判据                                 物理含义                    触发方向
===================================  ==========================  ==============
模型残差（``|innovation|`` 滑动均值） 辨识模型与实际状态的偏离      残差大 → UKF
非线性指标（残差二阶差分 / 曲率）      残差本身的非线性程度          曲率大 → UKF
工况突变（速度变化率的导数 / jerk）    制动工况**发生切换**的剧烈程度  jerk 大 → UKF
电流变化率（``|di_L/dt|``）           变流器电感电流的动态强度      变化快 → UKF
坡度变化（``Δgradient_per_mille``）    线路条件的突变                突变 → UKF
制动功率突变（``|ΔP| / P``）          再生功率的阶跃                突变 → UKF
===================================  ==========================  ==============

**输出契约**：``filter_mode`` + ``switch_reason``（必填）。每一次决策都带一个
来自 :data:`SWITCH_REASONS` 的原因串，**不存在"无理由切换"**。

--------------------------------------------------------------------------
两处必须留痕的实现口径（偏离算法文档字面写法）
--------------------------------------------------------------------------

**（一）"速度变化率"改为"速度变化率的导数（jerk）"——显式偏离**

算法文档写的是「工况变化率（速度变化率）」。但按字面实现 ``|dv/dt|`` 是**退化**的：
制动过程中 ``|dv/dt|`` 恒等于减速度本身，整段制动里始终是 0.15–0.25 m/s²，
与"工况是否发生突变"无关。实测（``tools/calibrate_mode_selector.py``，
Scenario 1 短剖面，dt = 2e-4 s）该指标的稳态 p50 = p95 = p99 = 0.25 —— 也就是说
无论取什么阈值，它要么**恒触发**、要么**永不触发**，不可能区分稳态与突变。

因此本实现改用它的导数（jerk）``|d²v/dt²|``：等减速度段恒为 0，
只有工况**真的发生切换**（如 Scenario 2 的"减速段 → 恒速保持段"）才出现尖峰。
键名相应改为 ``speed_jerk``，原因串为 :data:`REASON_SPEED_JERK`。
**这是对算法文档的显式偏离，已记入文档回填清单，不是静默改写。**

**（二）所有判据统一取 ``metric_window`` 步的滑动均值**

开关型功率变换器的逐拍变化率**极尖**（实测电流变化率的稳态 p99 只有约
9e2 A/s，而最大值达 9.3e5 A/s，跨三个数量级）。逐拍瞬时值与绝对阈值比较会
"要么被尖峰反复误触发、要么把阈值抬到永远触发不了"。

因此六类判据**一律**先算瞬时指标、再取 ``metric_window`` 步滑动均值，阈值
与滑动均值比较。这是一条统一、可解释的口径：**判据度量的是"最近
``metric_window`` 步的平均工况激烈程度"，不是"某一拍的瞬时尖峰"。**

--------------------------------------------------------------------------
两个必须留痕的口径问题
--------------------------------------------------------------------------

**（一）方案没有给阈值 —— 本模块的阈值是 calibrated-from-simulation 的工程值**

方案只列了判据的**方向**（"残差大"、"变化快"），没给任何数值。
本模块的做法是：把所有指标**无量纲化**（残差按状态参考尺度归一、变化率按
秒归一、坡度用 ‰），然后取一组默认阈值，并用
``tools/calibrate_mode_selector.py`` 在阶段 1/2 的实际工况上实测各指标分布，
按「稳态留 2 倍以上裕度、突变场景能触发」标定。阈值随 ``ModeSelectorConfig``
可注入，标定依据写在配置字段的注释里。**这是 assumed 数据，不是方案原文。**

**（二）UKF 在本问题上与 EKF 逐项恒等（阶段 5 已证）**

RHONN 对可调权重是**仿射**的，无迹变换对仿射映射精确，因此
``P^yy = H·P·H^T + R``、``P^xy = P·H^T``，UKF 更新式与 EKF **逐项恒等**
（见 :mod:`regenerative_braking.identification.ukf` 与
``tests/test_ukf.py::test_ukf_matches_ekf_on_this_linear_in_weights_model``）。

这意味着：**在本模型上切换 EKF/UKF 不会改变权重轨迹**。本模块因此
**不假装切换能带来性能收益**——它的价值在于把方案要求的「按场景适配」变成
可复现、可审计的机制，并在阶段 9 用实测数据**检验**这一恒等性结论
（``tests/test_closed_loop.py::test_ekf_and_ukf_produce_identical_weight_trajectories``
断言两条路径的权重轨迹在同一激励下必须逐位一致，若将来 RHONN 结构改动导致
不再恒等，该测试会立刻失败）。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from .rhonn import RHONNError

# ---------------------------------------------------------------------------
# 原因串（闭集）
# ---------------------------------------------------------------------------

#: 保持 EKF：所有判据均未触发。
REASON_HOLD_EKF = "hold_ekf_criteria_clear"
#: 保持 UKF：所有判据均已回落（低于退出阈值）。
REASON_HOLD_UKF = "hold_ukf_criteria_clear"
#: 判据已满足但仍在最短驻留期内，不切换（防抖）。
REASON_DWELL = "hold_min_dwell"
#: 切回 EKF：判据全部回落且已满足最短驻留。
REASON_RETURN_EKF = "switch_to_ekf_criteria_clear"

#: 六类触发判据对应的原因串（键与 :class:`ModeDecision.triggered_criteria` 一致）。
REASON_RESIDUAL = "switch_to_ukf_residual"
REASON_NONLINEARITY = "switch_to_ukf_nonlinearity"
REASON_SPEED_JERK = "switch_to_ukf_speed_jerk"
REASON_CURRENT_RATE = "switch_to_ukf_current_rate"
REASON_GRADIENT_STEP = "switch_to_ukf_gradient_step"
REASON_POWER_STEP = "switch_to_ukf_power_step"

#: 六类判据的**固定优先级**。多个判据同时超阈时，取排在最前的一个作为
#: ``switch_reason``，其余记入 ``triggered_criteria``。顺序按「越靠前越直接
#: 反映辨识模型失效」排列：模型残差 > 非线性 > 工况/电流动态 > 线路/功率突变。
CRITERION_PRIORITY: Tuple[Tuple[str, str], ...] = (
    ("residual", REASON_RESIDUAL),
    ("nonlinearity", REASON_NONLINEARITY),
    ("current_rate", REASON_CURRENT_RATE),
    ("speed_jerk", REASON_SPEED_JERK),
    ("power_step", REASON_POWER_STEP),
    ("gradient_step", REASON_GRADIENT_STEP),
)

#: 全部可能出现的 ``switch_reason``（闭集，供测试逐一覆盖）。
SWITCH_REASONS: Tuple[str, ...] = (
    REASON_HOLD_EKF,
    REASON_HOLD_UKF,
    REASON_DWELL,
    REASON_RETURN_EKF,
    REASON_RESIDUAL,
    REASON_NONLINEARITY,
    REASON_SPEED_JERK,
    REASON_CURRENT_RATE,
    REASON_GRADIENT_STEP,
    REASON_POWER_STEP,
)

MODE_EKF = "ekf"
MODE_UKF = "ukf"
FILTER_MODES: Tuple[str, ...] = (MODE_EKF, MODE_UKF)

#: 方案问题编号 **28**（实现期自行发现，非方案正文问题）：切换判据的归一化尺度
#: ``ModeSelectorConfig.state_scale`` 与 ``RHONNConfig.state_scale`` 被声明为
#: 「同源」，却**没有任何代码强制**——两者的 dataclass 默认值恰好相同
#: （``(1400.0, 1500.0)``），于是默认路径看不出问题；一旦调用方自定义
#: ``RHONNConfig.state_scale``（例如按问题 16 的 ``(v_out, i_L)`` 量级取
#: ``(1100.0, 3000.0)``），判据仍在用旧尺度把同一份残差重新缩放，
#: 阈值标定的含义被静默换掉。裁定：该不变量由 ``OnlineIdentifier``
#: 在构造处强制（不一致直接报错），并由 ``build_online_identifier``
#: 在调用方未显式给出 ``mode`` 配置时按 RHONN 配置派生。
SCHEME_ISSUE_MODE_SCALE_NOT_SOURCED = 28


class ModeSelectorError(RHONNError):
    """模式切换配置或输入不合法。"""


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModeSelectorConfig:
    """模式切换判据配置。

    全部阈值均为 **assumed**（方案只给判据方向，未给数值），
    由 ``tools/calibrate_mode_selector.py`` 在实际工况上实测标定：
    稳态留 ≥2 倍裕度，突变/快变场景能稳定触发。详见模块 docstring。

    标定实测（Scenario 1 短剖面 10 km/h / 0.25 m/s²、Scenario 2 长大下坡，
    dt = 2e-4 s，``metric_window = 20``；稳态段取后 50%，启动段取前 5%；
    下表取**两条工况里的最差值**）：

    ==============  ==========  ==========  ============  ==========  ======
    判据             稳态 p99    稳态 max    突变/启动峰值   本配置阈值   裕度
    ==============  ==========  ==========  ============  ==========  ======
    residual        2.7e-02     1.3e-01     7.5e-01       4.0e-01     14.6x
    nonlinearity    2.5e-06     5.8e-02     1.7e-02       1.0e-03     397x
    speed_jerk      0           3.8e+01     3.8e+01       5.0e+00     ∞
    current_rate    1.8e+04     7.0e+05     7.0e+05       5.0e+04     2.7x
    gradient_step   0           0           0             2.0e+00     ∞
    power_step      6.7e-05     5.0e-02     2.8e-01       5.0e-01     7475x
    ==============  ==========  ==========  ============  ==========  ======

    裕度按「阈值 / 稳态 p99」计；``speed_jerk`` 与 ``gradient_step`` 的稳态
    p99 为 0（稳态下确实没有工况突变），裕度记作 ∞。

    .. note::
       ``nonlinearity`` 与 ``current_rate`` 的**稳态 max** 超过阈值，
       意味着稳态里偶发一次真实电流动态事件时会触发一次切换
       （实测 Scenario 1 在 k=35562 触发、k=35826 回落，共 264 步，
       占全长 0.5%）。这不是噪声误触发：同一时刻两者的滑动均值同时抬升，
       对应一次真实的电感电流换向。取 p99 而非 max 定阈值是有意的——
       若按 max 定阈值，这两类判据将永不触发，等于把它们从判据集里删掉。

    进入判据用 ``*_threshold``，退出判据用 ``*_threshold × exit_ratio``，
    两者之间形成迟滞带，避免在阈值附近反复切换。
    """

    #: 状态参考尺度，用于把电压/电流残差无量纲化。
    #:
    #: **必须与 ``RHONNConfig.state_scale`` 逐位相同**（同源）——判据比较的是
    #: ``‖e ⊘ state_scale‖`` 与阈值，而 ``e`` 正是 RHONN 的辨识误差；两侧用
    #: 不同的尺度会把阈值标定的含义悄悄换掉（阈值本身不动，残差却被重新缩放）。
    #:
    #: 本字段的默认值与 :class:`~regenerative_braking.identification.rhonn.RHONNConfig`
    #: 的默认值一致，但**默认值相同不等于同源**：调用方一旦自定义
    #: ``RHONNConfig.state_scale``，本字段不会跟着变。该不变量由
    #: :class:`~regenerative_braking.identification.online_identifier.OnlineIdentifier`
    #: 在构造处强制（方案问题 28）。
    state_scale: Tuple[float, float] = (1400.0, 1500.0)

    #: 六类判据统一的滑动均值窗口长度（采样步）。见模块 docstring 口径（二）。
    #: 取 1 表示不做滑动平均（逐拍瞬时值），仅用于调试与标定，不建议生产使用。
    metric_window: int = 20

    #: 模型残差：归一化残差范数的滑动均值超过该值即触发
    residual_threshold: float = 0.4
    #: 非线性指标：归一化残差二阶差分范数的滑动均值超过该值即触发
    curvature_threshold: float = 1.0e-3
    #: 工况突变（jerk）：速度变化率的导数的滑动均值 [m/s^3] 超过该值即触发
    speed_jerk_threshold: float = 5.0
    #: 电感电流变化率 [A/s]
    current_rate_threshold: float = 5.0e4
    #: 坡度单步变化 [‰]
    gradient_step_threshold: float = 2.0
    #: 制动功率单步相对变化（|ΔP| / max(P_prev, power_floor_w)）
    power_step_threshold: float = 0.5

    #: 功率相对变化的参考下限 [W]，避免 P≈0 时把噪声放大成"突变"
    power_floor_w: float = 1.0e5

    #: 退出阈值 = 进入阈值 × exit_ratio（迟滞）
    exit_ratio: float = 0.5

    #: 切换后的最短驻留步数（防抖）
    min_dwell_steps: int = 50

    #: 初始模式
    initial_mode: str = MODE_EKF

    #: 仅约束审计明细；全程计数独立保存。None 显式启用无界历史。
    history_limit: Optional[int] = 2000

    def __post_init__(self) -> None:
        if self.history_limit is not None and (isinstance(self.history_limit, bool)
                or not isinstance(self.history_limit, int) or self.history_limit <= 0):
            raise ModeSelectorError("history_limit 必须为正整数或 None")
        if len(self.state_scale) != 2:
            raise ModeSelectorError("state_scale 必须为 2 元组")
        for value in self.state_scale:
            if not np.isfinite(value) or value <= 0.0:
                raise ModeSelectorError(f"state_scale 每项必须为正有限值，实际含 {value!r}")
        if self.metric_window < 1:
            raise ModeSelectorError(
                "metric_window 必须 >= 1（取 1 表示不做滑动平均，即逐拍瞬时值）"
            )
        for name in (
            "residual_threshold",
            "curvature_threshold",
            "speed_jerk_threshold",
            "current_rate_threshold",
            "gradient_step_threshold",
            "power_step_threshold",
            "power_floor_w",
        ):
            value = getattr(self, name)
            if not np.isfinite(value) or value <= 0.0:
                raise ModeSelectorError(f"{name} 必须为正有限值，实际为 {value!r}")
        if not np.isfinite(self.exit_ratio) or not 0.0 < self.exit_ratio < 1.0:
            raise ModeSelectorError(f"exit_ratio 必须在 (0, 1) 内，实际为 {self.exit_ratio!r}")
        if self.min_dwell_steps < 0:
            raise ModeSelectorError("min_dwell_steps 必须为非负整数")
        if self.initial_mode not in FILTER_MODES:
            raise ModeSelectorError(
                f"initial_mode 必须是 {FILTER_MODES} 之一，实际为 {self.initial_mode!r}"
            )


#: 六类判据的键名（与 :data:`CRITERION_PRIORITY` 的键一致）。
CRITERION_KEYS: Tuple[str, ...] = tuple(name for name, _reason in CRITERION_PRIORITY)


# ---------------------------------------------------------------------------
# 输入 / 输出
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModeSample:
    """模式判据所需的单步输入（全部 SI）。

    ``innovation`` 是**上一拍**的辨识误差 ``e = x − x̂``；首拍没有历史预测时传
    ``None``，此时依赖残差的两类判据（residual / nonlinearity）本拍不参与判断
    ——这是有意的因果约束：滤波器还没跑过，就不该用它的残差去切滤波器。
    """

    time_s: float
    speed_mps: float
    requested_regen_power_w: float
    inductor_current_a: float
    gradient_per_mille: float = 0.0
    innovation: Optional[np.ndarray] = None

    def __post_init__(self) -> None:
        for name in (
            "time_s",
            "speed_mps",
            "requested_regen_power_w",
            "inductor_current_a",
            "gradient_per_mille",
        ):
            value = getattr(self, name)
            if not np.isfinite(value):
                raise ModeSelectorError(f"{name} 必须为有限值，实际为 {value!r}")
        if self.innovation is not None:
            arr = np.asarray(self.innovation, dtype=float)
            if arr.shape != (2,):
                raise ModeSelectorError(f"innovation 形状必须为 (2,)，实际为 {arr.shape}")
            if not np.all(np.isfinite(arr)):
                raise ModeSelectorError("innovation 必须全部为有限值")


@dataclass(frozen=True)
class ModeDecision:
    """一次模式决策的完整留痕。"""

    step_index: int
    time_s: float
    #: 本次决策后采用的滤波器模式
    filter_mode: str
    #: 是否发生了切换
    switched: bool
    #: **必填**：本次决策的原因（取自 :data:`SWITCH_REASONS`）
    switch_reason: str
    #: 本拍所有超阈（迟滞后）的判据名，按 :data:`CRITERION_PRIORITY` 顺序
    triggered_criteria: Tuple[str, ...] = ()
    #: 各判据的当前指标值（未触发或不可算时为 None）
    metrics: Mapping[str, Optional[float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.switch_reason:
            raise ModeSelectorError("switch_reason 为必填字段，不允许为空")
        if self.switch_reason not in SWITCH_REASONS:
            raise ModeSelectorError(
                f"switch_reason={self.switch_reason!r} 不在允许集合内；"
                "不允许出现无理由或自由文本的切换原因。"
            )
        if self.filter_mode not in FILTER_MODES:
            raise ModeSelectorError(f"filter_mode 必须是 {FILTER_MODES} 之一，实际为 {self.filter_mode!r}")

    def describe(self) -> str:
        """一行摘要，供落盘 / 日志。"""
        metrics = " ".join(
            f"{key}={'-' if value is None else format(value, '.4g')}"
            for key, value in self.metrics.items()
        )
        triggered = ",".join(self.triggered_criteria) or "-"
        return (
            f"k={self.step_index} mode={self.filter_mode} switched={self.switched} "
            f"reason={self.switch_reason} triggered=[{triggered}] {metrics}"
        )


# ---------------------------------------------------------------------------
# 选择器
# ---------------------------------------------------------------------------


class ModeSelector:
    """六类可解释判据驱动的 EKF/UKF 模式切换器。

    使用方式（每个采样步调用一次）::

        decision = selector.update(sample)
        # decision.filter_mode 即本步之后应当采用的滤波器

    时序说明：``update`` 消费的是**本拍已经观测到的量**，因此
    ``decision.filter_mode`` 生效于**下一拍**的滤波器选择。这与
    :meth:`ModeSelector.update` 的调用点无关，是调用方的责任；
    :class:`~regenerative_braking.identification.online_identifier.OnlineIdentifier`
    按这一约定接线。
    """

    name = "mode_selector"

    def __init__(self, config: Optional[ModeSelectorConfig] = None) -> None:
        self.config = config or ModeSelectorConfig()
        cfg = self.config

        self._state_scale = np.asarray(cfg.state_scale, dtype=float)
        #: 六类判据的滑动均值窗口（见模块 docstring 口径二）
        self._metric_windows: Dict[str, Deque[float]] = {
            key: deque(maxlen=cfg.metric_window) for key in CRITERION_KEYS
        }
        #: 非线性判据需要连续三拍残差才能算二阶差分
        self._residual_values: Deque[np.ndarray] = deque(maxlen=3)

        self._mode = cfg.initial_mode
        self._step_index = 0
        self._steps_since_switch = 0
        self._last_time_s: Optional[float] = None
        self._last_speed_mps: Optional[float] = None
        self._last_speed_rate: Optional[float] = None
        self._last_current_a: Optional[float] = None
        self._last_power_w: Optional[float] = None
        self._last_gradient: Optional[float] = None
        self._decisions: Deque[ModeDecision] = deque(maxlen=cfg.history_limit)
        self._switches: Deque[ModeDecision] = deque(maxlen=cfg.history_limit)
        self._reason_totals = {reason: 0 for reason in SWITCH_REASONS}
        self._switch_total = 0

    # -- 只读属性 -----------------------------------------------------------

    @property
    def current_mode(self) -> str:
        """当前生效的滤波器模式。"""
        return self._mode

    @property
    def step_index(self) -> int:
        return self._step_index

    @property
    def decisions(self) -> Tuple[ModeDecision, ...]:
        """最近 history_limit 拍决策；None 保留全部（只读快照）。"""
        return tuple(self._decisions)

    @property
    def last_decision(self) -> Optional[ModeDecision]:
        return self._decisions[-1] if self._decisions else None

    def reset(self) -> None:
        """回到初始模式并清空全部历史。"""
        for window in self._metric_windows.values():
            window.clear()
        self._residual_values.clear()
        self._mode = self.config.initial_mode
        self._step_index = 0
        self._steps_since_switch = 0
        self._last_time_s = None
        self._last_speed_mps = None
        self._last_speed_rate = None
        self._last_current_a = None
        self._last_power_w = None
        self._last_gradient = None
        self._decisions.clear()
        self._switches.clear()
        self._reason_totals = {reason: 0 for reason in SWITCH_REASONS}
        self._switch_total = 0

    # -- 指标 ---------------------------------------------------------------

    def _normalised_residual(self, innovation: np.ndarray) -> float:
        """归一化残差范数 ``‖e ⊘ state_scale‖``（无量纲）。"""
        return float(np.linalg.norm(np.asarray(innovation, dtype=float) / self._state_scale))

    def _curvature(self) -> Optional[float]:
        """残差的二阶差分范数（曲率）——非线性强弱的直接度量。

        只对**连续三拍都有残差**的窗口计算；不足三拍返回 ``None``。
        """
        if len(self._residual_values) < 3:
            return None
        first, second, third = self._residual_values
        second_difference = (third - 2.0 * second + first) / self._state_scale
        return float(np.linalg.norm(second_difference))

    @staticmethod
    def _rate(current: float, previous: Optional[float], dt: Optional[float]) -> Optional[float]:
        if previous is None or dt is None or dt <= 0.0:
            return None
        return abs(current - previous) / dt

    def _relative_power_step(self, current: float, previous: Optional[float]) -> Optional[float]:
        if previous is None:
            return None
        floor = self.config.power_floor_w
        return abs(current - previous) / max(abs(previous), floor)

    def _instantaneous_metrics(self, sample: ModeSample, dt: Optional[float]) -> Mapping[str, Optional[float]]:
        """本拍的**瞬时**指标（未做滑动平均）。"""
        if sample.innovation is not None:
            self._residual_values.append(np.asarray(sample.innovation, dtype=float))

        speed_rate = self._rate(sample.speed_mps, self._last_speed_mps, dt)
        jerk = self._rate(speed_rate, self._last_speed_rate, dt) if speed_rate is not None else None

        return {
            "residual": (
                None
                if sample.innovation is None
                else self._normalised_residual(np.asarray(sample.innovation, dtype=float))
            ),
            "nonlinearity": self._curvature(),
            "speed_jerk": jerk,
            "current_rate": self._rate(sample.inductor_current_a, self._last_current_a, dt),
            "gradient_step": (
                None
                if self._last_gradient is None
                else abs(sample.gradient_per_mille - self._last_gradient)
            ),
            "power_step": self._relative_power_step(
                sample.requested_regen_power_w, self._last_power_w
            ),
        }

    def compute_metrics(self, sample: ModeSample) -> Mapping[str, Optional[float]]:
        """算出本拍六类判据的**滑动均值**指标（不做阈值比较，便于标定与调试）。

        先算瞬时指标、再推入各自的 ``metric_window`` 步窗口，返回窗口均值；
        窗口为空（该指标本拍还没有任何有效样本）时返回 ``None``。
        见模块 docstring 口径（二）。
        """
        dt: Optional[float] = None
        if self._last_time_s is not None:
            delta = sample.time_s - self._last_time_s
            dt = delta if delta > 0.0 else None

        instantaneous = self._instantaneous_metrics(sample, dt)

        # 状态推进（必须在算完瞬时指标之后，保证"本拍指标"用本拍与上一拍比较）
        speed_rate = self._rate(sample.speed_mps, self._last_speed_mps, dt)
        self._last_time_s = float(sample.time_s)
        self._last_speed_mps = float(sample.speed_mps)
        self._last_speed_rate = speed_rate
        self._last_current_a = float(sample.inductor_current_a)
        self._last_power_w = float(sample.requested_regen_power_w)
        self._last_gradient = float(sample.gradient_per_mille)

        smoothed: Dict[str, Optional[float]] = {}
        for key, value in instantaneous.items():
            window = self._metric_windows[key]
            if value is not None:
                window.append(float(value))
            smoothed[key] = float(np.mean(window)) if window else None
        return smoothed

    # -- 决策 ---------------------------------------------------------------

    def _thresholds(self) -> Mapping[str, float]:
        return {
            "residual": self.config.residual_threshold,
            "nonlinearity": self.config.curvature_threshold,
            "speed_jerk": self.config.speed_jerk_threshold,
            "current_rate": self.config.current_rate_threshold,
            "gradient_step": self.config.gradient_step_threshold,
            "power_step": self.config.power_step_threshold,
        }

    def _is_triggered(self, name: str, value: Optional[float]) -> bool:
        """迟滞比较：进入用阈值，退出用 ``阈值 × exit_ratio``。

        当前已在 UKF 时，只有当指标**回落到退出阈值以下**才算"该判据已清除"，
        避免在阈值附近来回抖动。
        """
        if value is None:
            return False
        threshold = self._thresholds()[name]
        if self._mode == MODE_EKF:
            return value > threshold
        return value > threshold * self.config.exit_ratio

    def update(self, sample: ModeSample) -> ModeDecision:
        """消费一拍观测，返回**本拍之后**应采用的模式决策。"""
        metrics = self.compute_metrics(sample)
        triggered = tuple(
            name for name, _reason in CRITERION_PRIORITY if self._is_triggered(name, metrics[name])
        )

        previous_mode = self._mode
        reason: str

        if triggered:
            if self._mode == MODE_EKF:
                if self._steps_since_switch < self.config.min_dwell_steps:
                    reason = REASON_DWELL
                else:
                    self._mode = MODE_UKF
                    self._steps_since_switch = 0
                    reason = dict(CRITERION_PRIORITY)[triggered[0]]
            else:
                # 已在 UKF：判据仍在迟滞带内 → 保持，并沿用最初触发它的原因
                reason = REASON_HOLD_UKF
        else:
            if self._mode == MODE_UKF:
                if self._steps_since_switch < self.config.min_dwell_steps:
                    reason = REASON_DWELL
                else:
                    self._mode = MODE_EKF
                    self._steps_since_switch = 0
                    reason = REASON_RETURN_EKF
            else:
                reason = REASON_HOLD_EKF

        switched = self._mode != previous_mode
        decision = ModeDecision(
            step_index=self._step_index,
            time_s=float(sample.time_s),
            filter_mode=self._mode,
            switched=switched,
            switch_reason=reason,
            triggered_criteria=triggered,
            metrics=dict(metrics),
        )
        self._decisions.append(decision)
        self._reason_totals[decision.switch_reason] += 1
        if decision.switched:
            self._switches.append(decision)
            self._switch_total += 1

        # 指标的递归状态已在 compute_metrics 内推进（含 _last_* 与滑动窗口），
        # 这里只推进步序与驻留计数。
        self._step_index += 1
        self._steps_since_switch += 1
        return decision

    # -- 审计 ---------------------------------------------------------------

    def reason_counts(self) -> Mapping[str, int]:
        """各 ``switch_reason`` 出现的次数（供阶段 9 审计"是否存在无理由切换"）。"""
        return dict(self._reason_totals)

    def switch_log(self) -> Tuple[ModeDecision, ...]:
        """只保留真正发生切换的决策。"""
        return tuple(self._switches)

    def audit(self) -> Mapping[str, object]:
        """审计摘要：切换次数、原因分布、是否出现空原因。"""
        switches = self.switch_log()
        return {
            "steps": self._step_index,
            "final_mode": self._mode,
            "switch_count": self._switch_total,
            "history_limit": self.config.history_limit,
            "retained_decisions": len(self._decisions),
            "retained_switches": len(switches),
            "decision_log_truncated": self._step_index > len(self._decisions),
            "switch_log_truncated": self._switch_total > len(switches),
            "reason_counts": dict(self.reason_counts()),
            "switches": tuple(
                (decision.step_index, decision.filter_mode, decision.switch_reason)
                for decision in switches
            ),
        }


def assert_no_reasonless_switching(decisions: Sequence[ModeDecision]) -> None:
    """验收辅助：断言不存在"无理由切换"。

    每条决策都必须带非空 ``switch_reason``（构造时已强制），
    且**发生切换时**原因必须是一条真正的触发类原因，
    不允许用 ``hold_*`` / ``switch_to_ekf_*`` 之类掩盖。
    """
    hold_reasons = {REASON_HOLD_EKF, REASON_HOLD_UKF, REASON_DWELL}
    for decision in decisions:
        if not decision.switch_reason:
            raise ModeSelectorError(f"第 {decision.step_index} 拍出现空 switch_reason")
        if decision.switched and decision.filter_mode == MODE_UKF:
            if decision.switch_reason in hold_reasons or decision.switch_reason == REASON_RETURN_EKF:
                raise ModeSelectorError(
                    f"第 {decision.step_index} 拍切到 UKF，但原因 {decision.switch_reason!r} "
                    "不是触发类原因；不允许无理由切换。"
                )
        if decision.switched and decision.filter_mode == MODE_EKF:
            if decision.switch_reason != REASON_RETURN_EKF:
                raise ModeSelectorError(
                    f"第 {decision.step_index} 拍切回 EKF，原因应为 {REASON_RETURN_EKF!r}，"
                    f"实际为 {decision.switch_reason!r}"
                )
