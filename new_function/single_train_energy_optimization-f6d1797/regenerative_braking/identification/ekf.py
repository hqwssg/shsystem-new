"""EKF 权重训练器（阶段 4）。

对应技术方案 §4.2.1.3（3）**RHONN 训练算法 —— EKF**。

方案原文公式（未编号；证据图 ``fig_ekf_weight_update.png``）::

    ω_{i,k+1} = ω_{i,k} + η_i · K_{i,k} · e_{i,k}

    e_{i,k} = x_{i,k} - x̂_{i,k}                    η_i = 0.01

    K_{i,k} = P_{i,k} · H_{i,k} · M_{i,k}

    M_{i,k} = ( R_{i,k} + H_{i,k}^T · P_{i,k} · H_{i,k} )^(-1)

方案给出的符号说明::

    e_{i,k}   辨识误差
    η_i       训练步长（= 0.01）
    K_{i,k}   卡尔曼增益
    P_{i,k}   误差协方差矩阵
    H_{i,k}   状态对权重的导数矩阵
    M_{i,k}   正文未单独命名，仅给出上式
    R_{i,k}   正文未定义                        ← 方案问题 3

--------------------------------------------------------------------------
编写人裁定（2026-09-25）：方案在此处的三处问题已给出正式口径
--------------------------------------------------------------------------

**问题 2 —— 卡尔曼增益量纲不闭合**

按方案自己的符号定义：``P`` 是权重协方差 ``(n_w × n_w)``，
``H = ∂x/∂ω`` 是 ``(n_x × n_w)``，``n_x = 2``（电压、电感电流），
``n_w`` 是 RHONN 可调权重数（问题 15 修正后为 20：两条路径各 10）。

于是方案写的 ``H^T · P · H`` 是 ``(n_w × n_x)·(n_w × n_w)·(n_x × n_w)`` ——
第一个乘法 ``H^T · P`` 要求 ``n_x == n_w``，**根本不成立**。
正确的量测协方差应当是 ``H · P · H^T`` → ``(n_x × n_x)``。

同时 ``K = P · H · M`` 里 ``P · H`` 是 ``(n_w × n_w)·(n_x × n_w)``，
同样要求 ``n_x == n_w``；应为 ``P · H^T``。

把这两处一并纠正后，方案的两式**同时闭合**，且正是标准卡尔曼形式::

    K = P · H^T · ( H · P · H^T + R )^(-1)        ← 对应方案的 K = P·H·M
    M = ( R + H · P · H^T )^(-1)                  ← 对应方案的 M 式

可见方案只错在 H 的转置位置，结构本身是对的。

裁定：按 ``K = P·H^T·(H·P·H^T + R)^(-1)`` 落地（``M = (R + H·P·H^T)^(-1)``）。
理由：这是唯一的维度闭合形式；方案原式 ``K = P·H·M``、``M = (R + H^T·P·H)^(-1)``
在 ``n_x ≠ n_w`` 时**无法相乘**（本项目 ``n_x = 2``、``n_w = 20``），
不是口径差异而是笔误。``H`` 的转置位置为唯一改动，结构本身照方案保留。

**问题 3 —— R 未定义**

裁定：``R`` 为**量测噪声协方差矩阵**，维度 ``(n_x × n_x)``，即 ``(2 × 2)``，
对角元为电压/电流量测的噪声方差 ``(σ_v², σ_i²)``，非对角元取 0
（电压与电流由独立传感器量测，无共模噪声来源）。

.. note::
   **定义**已正式化（``SCHEME_AUTHORED``）；**数值**仍无实测依据——
   方案未给量测设备精度，本实现按 ``σ_v = σ_i = 5``（对应 ±5 V / ±5 A 量级）
   预设，标 ``assumed``。数值替换不影响本式的正确性，
   见 :class:`EKFConfig` 的 provenance。

**问题 10 —— η 与协方差递推未配套给出（本模块新发现）**

方案给了 ``ω_{i,k+1} = ω_{i,k} + η_i·K_{i,k}·e_{i,k}``（η_i = 0.01），
但**没有给出协方差 P 的递推式**。这看起来是个小缺口，实际会决定算法能不能收敛。

若把 P 按标准 EKF 递推 ``P ← (I − K·H)·P + Q``（即隐含 η = 1），
就会出现**权重只走 η 比例、协方差却按 η = 1 收缩**的不自洽：
P 迅速塌缩 → K 迅速趋零 → 权重增量被卡死。
实测（多航次平稳工况辨识，见 ``tests/test_ekf.py``）::

    η = 0.01  标准递推 → 预测相对误差 26.5%     ← 方案原值几乎不收敛
    η = 1.00  标准递推 → 预测相对误差  0.5%

本实现取**与 η 自洽**的 Joseph 形式::

    P ← (I − η·K·H)·P·(I − η·K·H)^T + η²·K·R·K^T + Q

推导：令 ``ω̃ = ω_true − ω̂``，代入 ``ω̂ ← ω̂ + η·K·e`` 与 ``e = H·ω̃ + v`` 得
``ω̃ ← (I − η·K·H)·ω̃ − η·K·v``，故上式即误差协方差的精确递推。
η = 1 时退化为标准 EKF，对任意 η ∈ (0,1] 严格保持半正定。
改后收敛对 η **单调**（η 越小收敛越慢但始终收敛），方案原值 η = 0.01 可用::

    η = 0.01  本实现 → 预测相对误差 0.85%
    η = 0.05  本实现 → 预测相对误差 0.58%
    η = 1.00  本实现 → 预测相对误差 0.51%

裁定：采用上式。理由：它是**唯一**与方案自己给出的 ``ω`` 更新式（含 ``η``）
自洽的协方差递推——若按标准 EKF 递推（隐含 ``η = 1``），就会出现
「权重只走 ``η`` 比例、协方差却按 ``η = 1`` 收缩」的不自洽，实测 ``η = 0.01``
时预测相对误差达 26.5%（几乎不收敛）。上式在 ``η = 1`` 时退化为标准 EKF，
对任意 ``η ∈ (0,1]`` 严格保持半正定，且使收敛对 ``η`` 单调。
即：**方案原值 ``η_i = 0.01`` 保留不动，只补上与之配套的 P 递推式。**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from .rhonn import RHONN, PredictionContext


class EKFError(ValueError):
    """EKF 配置或输入不合法。"""


#: 方案问题编号（与 `docs/technical_scheme_code_mapping.md` §A.3 对齐）
SCHEME_ISSUE_GAIN_DIMENSION = 2
SCHEME_ISSUE_MEASUREMENT_NOISE_UNDEFINED = 3
SCHEME_ISSUE_COVARIANCE_RECURSION_MISSING = 10  # η 与 P 递推未配套（本模块新发现）


@dataclass(frozen=True)
class EKFConfig:
    """EKF 数值配置。

    provenance::

        eta                        official —— 方案原文给出的训练步长 0.01
        initial_covariance         assumed  —— 初始权重不确定度，无实测依据
        process_noise              assumed  —— 权重随机游走方差，无实测依据
        measurement_noise_*        assumed  —— R 的**定义**已裁定（问题 3：
                                    量测噪声协方差，n_x × n_x 对角阵），
                                    但数值无实测依据，按 ±5 V / ±5 A 量级预设，
                                    待量测设备精度资料到位后替换
    """

    #: 方案原文训练步长 η_i = 0.01（逐神经元可不同，本实现用统一值）
    #: —— 保留方案原值；配套的 P 递推式见模块 docstring 问题 10 的裁定
    eta: float = 0.01

    #: P 的初始对角值（表示初始权重不确定度）
    initial_covariance: float = 1.0

    #: 过程噪声 Q = process_noise · I，容许权重缓慢漂移
    process_noise: float = 1e-8

    #: 量测噪声标准差（电压 V / 电流 A）—— 问题 3 裁定的 R 由此构造
    measurement_noise_voltage_v: float = 5.0
    measurement_noise_current_a: float = 5.0

    def __post_init__(self) -> None:
        if not np.isfinite(self.eta) or self.eta <= 0.0:
            raise EKFError("eta 必须为正有限值")
        if not np.isfinite(self.initial_covariance) or self.initial_covariance <= 0.0:
            raise EKFError("initial_covariance 必须为正有限值")
        if not np.isfinite(self.process_noise) or self.process_noise < 0.0:
            raise EKFError("process_noise 必须为非负有限值")
        for name, value in (
            ("measurement_noise_voltage_v", self.measurement_noise_voltage_v),
            ("measurement_noise_current_a", self.measurement_noise_current_a),
        ):
            if not np.isfinite(value) or value <= 0.0:
                raise EKFError(f"{name} 必须为正有限值")


@dataclass
class EKFUpdateRecord:
    """单步 EKF 更新的可记录量。"""

    innovation: np.ndarray          # e = x - x̂（方案中的辨识误差）
    kalman_gain: np.ndarray         # K
    parameter_update: np.ndarray    # Δω = η · K · e
    covariance_trace: float
    covariance_min_eigenvalue: float


class EKF:
    """基于扩展卡尔曼滤波的 RHONN 权重训练器。

    对 RHONN 而言，量测方程 ``x = h(ω)`` 关于可调权重 ω 是**线性**的，
    因此 ``H`` 不依赖 ω（见 :meth:`RHONN.jacobian_wrt_tunable_weights`），
    滤波退化为线性卡尔曼滤波——这正是它在本问题上收敛良好的原因。

    .. note::
       ``e_{i,k}`` 在本类中表示**辨识误差**（状态空间，``(n_x,)``）。
       方案在 UKF 侧复用了同一符号表示 sigma 点偏差（样本空间，``(L,)``），
       即方案问题 6。裁定（问题 6）：EKF 侧保留 ``e_{i,k}``，
       UKF 侧的 sigma 点偏差正式符号为 ``e_j(i,k)``（带 sigma 点下标 ``j``），
       代码字段名为 ``sigma_deviation``。
    """

    name = "ekf"

    def __init__(
        self,
        rhonn: RHONN,
        config: Optional[EKFConfig] = None,
        *,
        measurement_noise: Optional[Sequence[Sequence[float]]] = None,
    ) -> None:
        self.rhonn = rhonn
        self.config = config or EKFConfig()

        n_w = rhonn.n_tunable_weights
        n_x = rhonn.state_dim

        if measurement_noise is None:
            cfg = self.config
            self._measurement_noise = np.diag(
                np.asarray(
                    [
                        cfg.measurement_noise_voltage_v**2,
                        cfg.measurement_noise_current_a**2,
                    ][:n_x],
                    dtype=float,
                )
            )
            if self._measurement_noise.shape != (n_x, n_x):
                raise EKFError("量测噪声维度与 state_dim 不一致")
        else:
            arr = np.asarray(measurement_noise, dtype=float)
            if arr.shape != (n_x, n_x):
                raise EKFError(f"measurement_noise 形状必须为 {(n_x, n_x)}，实际为 {arr.shape}")
            self._measurement_noise = arr.copy()

        self._covariance = np.eye(n_w) * self.config.initial_covariance

    # ------------------------------------------------------------------
    # 只读属性
    # ------------------------------------------------------------------

    @property
    def covariance(self) -> np.ndarray:
        """权重误差协方差矩阵 P 的副本。"""
        return self._covariance.copy()

    def adopt_covariance(self, covariance: Sequence[Sequence[float]]) -> None:
        """接管外部传入的权重误差协方差 P。

        供 EKF/UKF 模式切换使用（见
        :mod:`regenerative_braking.identification.online_identifier`）：
        两个滤波器估计的是同一组权重，切换时若各自带着自己的 ``P`` 重新开始，
        被切到的那个会从初始不确定度起步，造成一次无物理依据的跳变。

        传入矩阵会被对称化（``(P + P^T)/2``），因为后续递推本身只保证
        对称到浮点精度，而 ``eigvalsh`` 等下游使用要求严格对称。
        """
        arr = np.asarray(covariance, dtype=float)
        expected = (self.n_parameters, self.n_parameters)
        if arr.shape != expected:
            raise EKFError(f"covariance 形状必须为 {expected}，实际为 {arr.shape}")
        if not np.all(np.isfinite(arr)):
            raise EKFError("covariance 必须全部为有限值")
        self._covariance = 0.5 * (arr + arr.T)

    @property
    def measurement_noise(self) -> np.ndarray:
        """量测噪声协方差矩阵 R 的副本（方案问题 3 的落地值）。"""
        return self._measurement_noise.copy()

    def reconfigure(self, *, config: EKFConfig) -> None:
        """在运行前同步更新 ``eta``、Q 和 R，并重置协方差。"""
        if not isinstance(config, EKFConfig):
            raise EKFError("reconfigure需要EKFConfig")
        self.config = config
        self._measurement_noise = np.diag(np.asarray([
            config.measurement_noise_voltage_v**2,
            config.measurement_noise_current_a**2,
        ][:self.rhonn.state_dim], dtype=float))
        self.reset()

    @property
    def n_parameters(self) -> int:
        return self.rhonn.n_tunable_weights

    def reset(self) -> None:
        """重置协方差到初值（权重不动，由 RHONN 自己管理）。"""
        self._covariance = np.eye(self.n_parameters) * self.config.initial_covariance

    # ------------------------------------------------------------------
    # 滤波一步
    # ------------------------------------------------------------------

    def update(
        self,
        state_actual: Sequence[float],
        predicted_state: Sequence[float],
        *,
        context: Optional[PredictionContext] = None,
    ) -> EKFUpdateRecord:
        """用一次新量测校正权重。

        ``predicted_state`` 是**校正前**对当前时刻的预测 x̂_k
        （即 :attr:`RHONN.state_estimate`），辨识误差 ``e = x_k - x̂_k``。

        ``context`` 是产生 x̂_k 那次预测的输入上下文，雅可比 H 必须在该上下文
        的 ``state_actual``（即 ``x_{k−1}``）处取值——方案里 ``e_{i,k}`` 的
        ``x̂_{i,k}`` 正是由 ``x_{k−1}`` 产生的。省略 ``context`` 时会退化为在
        当前量测 ``x_k`` 处取值，**动态工况下会引入一步偏差**；
        :meth:`step` 始终传入正确的上下文。

        权重的实际写入通过 :meth:`RHONN.update_weights` 完成，
        因此 EKF 不持有权重副本——单一真相源留在 RHONN 上。
        """
        cfg = self.config
        state = np.asarray(state_actual, dtype=float)
        if state.shape != (self.rhonn.state_dim,):
            raise EKFError(f"state_actual 形状必须为 {(self.rhonn.state_dim,)}，实际为 {state.shape}")

        predicted = np.asarray(predicted_state, dtype=float)
        if predicted.shape != (self.rhonn.state_dim,):
            raise EKFError(
                f"predicted_state 形状必须为 {(self.rhonn.state_dim,)}，实际为 {predicted.shape}"
            )

        # 1) 量测雅可比 H = ∂x̂/∂ω，在**产生该预测的状态点**上取值。
        #    方案问题 15 修正后，可调权重含并联与串联两条路径，
        #    故 H 需要 φ_ser 的两个输入——从 context 取，缺省按标称点（全零）。
        regressor_state = state_actual if context is None else context.state_actual
        if context is None:
            h_matrix = self.rhonn.jacobian_wrt_tunable_weights(regressor_state)
        else:
            h_matrix = self.rhonn.jacobian_wrt_tunable_weights(
                regressor_state, context.state_estimate_prev, context.control
            )

        # 2) 辨识误差 e = x - x̂
        innovation = state - predicted

        # 3) M = (R + H·P·H^T)^(-1)，S 为量测协方差
        #    方案问题 2 裁定：方案写作 H^T·P·H，维度不闭合；此处按 H·P·H^T 落地。
        p_matrix = self._covariance
        s_matrix = h_matrix @ p_matrix @ h_matrix.T + self._measurement_noise

        # 4) K = P·H^T·M（用 solve 代替显式求逆，数值更稳）
        #    方案问题 2 裁定：方案写作 P·H·M；此处按 P·H^T·M 落地。
        kalman_gain = np.linalg.solve(s_matrix, (p_matrix @ h_matrix.T).T).T

        # 5) Δω = η · K · e   （方案原文的 η_i 训练步长）
        parameter_update = cfg.eta * (kalman_gain @ innovation)

        # 6) 权重写入
        self.rhonn.update_weights(parameter_update)

        # 7) 协方差递推 —— 必须与第 5 步的 η 缩放自洽（见模块 docstring「问题 10」）
        #    P ← (I - η·K·H)·P·(I - η·K·H)^T + η²·K·R·K^T + Q
        #    取 Joseph 形式：对任意 η ∈ (0,1] 都严格保持半正定，
        #    且 η = 1 时退化为标准 EKF 协方差递推。
        identity = np.eye(self.n_parameters)
        a_matrix = identity - cfg.eta * (kalman_gain @ h_matrix)
        p_next = (
            a_matrix @ p_matrix @ a_matrix.T
            + (cfg.eta**2) * (kalman_gain @ self._measurement_noise @ kalman_gain.T)
            + cfg.process_noise * identity
        )
        self._covariance = 0.5 * (p_next + p_next.T)

        return EKFUpdateRecord(
            innovation=innovation.copy(),
            kalman_gain=kalman_gain.copy(),
            parameter_update=np.asarray(parameter_update, dtype=float).copy(),
            covariance_trace=float(np.trace(self._covariance)),
            covariance_min_eigenvalue=float(np.min(np.linalg.eigvalsh(self._covariance))),
        )

    def step(
        self,
        state_actual: Sequence[float],
        control: Sequence[float],
        *,
        time_s: float = 0.0,
    ):
        """推进一个采样步：先用新量测校正权重，再产生新的状态预测。

        返回 ``(rhonn_step_record, ekf_update_record)``。
        首步没有历史预测、无法形成辨识误差，``ekf_update_record`` 为 ``None``。

        顺序很重要——**先校正权重、再预测**，使新预测用上刚更新的权重，
        这正是 EKF 相对离线训练的价值所在。
        """
        predicted = self.rhonn.state_estimate
        context = self.rhonn.last_prediction_context

        update: Optional[EKFUpdateRecord] = None
        if predicted is not None:
            # context 描述的是产生 x̂_k 的那次预测；雅可比必须在 x_{k−1} 处取值。
            update = self.update(state_actual, predicted, context=context)

        record = self.rhonn.step(state_actual, control, time_s=time_s)
        return record, update
