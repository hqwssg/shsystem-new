"""UKF 权重训练器（阶段 5）。

对应技术方案 §4.2.1.3（3）**RHONN 训练算法 —— UKF**。

方案原文只给了两式（编号 (36)(37)；证据图 ``fig_ukf_36_37.png``）::

    (36)  P_{i,k}^xy = Σ_{j=0}^{2L} η_j^c · ( X_{i,k}^j − x̂_{i,k}^- ) · ( Y_{i,k}^j − ŷ_{i,k}^- )^T

    (37)  e_{i,k}    = X_{i,k}^j − x̂_{i,k}^-

方案给出的符号说明::

    L                 状态维度（方案原文：「取 2，对应电压与电流」）   ← 方案问题 11
    η_j^c             采样权重（= 0.02）
    X_{i,k}^j         状态 sigma 点
    Y_{i,k}^j         输出 sigma 点
    x̂_{i,k}^-         状态预测均值
    ŷ_{i,k}^-         输出预测均值
    e_{i,k}           与 EKF 同名但含义不同                      ← 方案问题 6

--------------------------------------------------------------------------
编写人裁定（2026-09-25）：方案在此处的四处问题已给出正式口径
--------------------------------------------------------------------------

**问题 11 —— L 取 2 与滤波器的状态维度矛盾（本模块新发现）**

UKF 在此处的任务是**训练 RHONN 的权重**，因此滤波器的状态向量是权重 ``ω``，
不是被控对象的电压/电流。方案原文写「L 取 2，对应电压与电流」，
把**量测维度**当成了**滤波器状态维度**。

裁定：``L`` 是**滤波器状态维度 = 可调权重数**，本问题中 ``n_w = 20``
（问题 15 裁定后并联 10 + 串联 10，见 :mod:`rhonn`），故取 ``L = n_w = 20``，
sigma 点共 ``2L + 1 = 41`` 个。方案原文「L 取 2，对应电压与电流」把
**量测维度**当成了**滤波器状态维度**；若按字面取 ``L = 2``，
``P^xy`` 会落在 ``(2 × n_x)``，与 ``(n_w × n_w)`` 的 ``P`` 无法相容。
``tests/test_ukf.py::test_filter_state_dimension_is_the_weight_count`` 锁定此点。

**问题 4 —— UKF 缺少权重更新式（方案已自认）**

方案只给了 ``P^xy``（(36)）与 ``e``（(37)），缺三样：

* ``ω`` 的更新方程；
* 输出协方差 ``P^yy``；
* 均值权重 ``η_j^m``。

裁定：按标准无迹卡尔曼补全，作为正式口径::

    ŷ^-   = Σ_j η_j^m · Y^j                        输出预测均值
    P^yy  = Σ_j η_j^c · (Y^j − ŷ^-)(Y^j − ŷ^-)^T + R   输出（新息）协方差
    K     = P^xy · (P^yy)^(-1)                     卡尔曼增益
    ω    ← ω + η · K · (x_k − ŷ^-)                 权重更新式

理由：这三样是标准 UKF 的必要组成，方案缺了它们则 ``ω`` 无法更新、
``P^xy`` 无从使用；补全形式由无迹变换唯一确定，不含自由选择。
``η`` 沿用方案原值 ``0.01``（与 EKF 同值）。

**问题 6 —— 符号 e 一符两义**

EKF 中 ``e_{i,k} = x_k − x̂_k`` 是**量测空间**的辨识误差，维度 ``(n_x,) = (2,)``；
方案 (37) 里 ``e_{i,k} = X^j − x̂^-`` 是**权重空间**的 sigma 点偏差，维度 ``(L,) = (20,)``。
一符两义、维度都不同。

裁定：EKF 侧保留 ``e_{i,k}``；UKF 侧 sigma 点偏差的正式符号为
``e_j(i,k) = X_{i,k}^j − x̂_{i,k}^-``（**带 sigma 点下标 ``j``**），
代码字段名为 ``sigma_deviation``。同时统一 (36)(37) 的预测均值写法：
两式都用**带负号上标**的预测均值 ``x̂_{i,k}^-``、``ŷ_{i,k}^-``
（方案 (37) 漏写负号上标，属笔误）。

**问题 12 —— 采样权重 η_j^c = 0.02 与标准 UT 权重公式的关系未说明（本模块新发现）**

标准无迹变换中 ``η_j^m = η_j^c = 1 / (2(L + λ))``（``j ≥ 1``）。
方案给的 ``η_j^c = 0.02`` 意味着 ``L + λ = 1/(2×0.02) = 25``。由于方案把 ``L``
写成了 2（问题 11），这个数值无法与任何合理的 ``(L, α, κ)`` 组合对上；
但按裁定的 ``L = n_w = 20`` 反推可得 ``λ = 5``，**在标准公式下是自洽的**。

裁定：**直接采用方案给的 η_j^c = 0.02**，由它反解 ``λ``，
而不是另选一套权重——这样既不丢方案原值，又保持无迹变换的有效性::

    λ       = 1 / (2·η_j^c) − L  = 25 − 20 = 5     （由 η_j^c = 1/(2(L+λ)) 反解）
    η_0^m   = λ / (L + λ)        = 5 / 25 = 0.2    （= 1 − 2L·η_j^c，中心点均值权重）
    η_0^c   = η_0^m + (1 − α² + β)，取 α = 1、β = 2

``η_0^c`` 的修正项 ``(1 − α² + β) = β`` 是标准 UT 对高斯先验的偏置修正。
``η_j^c = 0.02`` 的合法性由 ``0 < η_j^c < 1/(2L)`` 约束
（等价于中心点均值权重为正），本类在 ``__post_init__`` 中校验。

--------------------------------------------------------------------------
一个重要的结构性事实：在本问题上 UKF 与 EKF 等价
--------------------------------------------------------------------------

RHONN 对可调权重 ``ω`` 是**线性**的（见
:meth:`RHONN.jacobian_wrt_tunable_weights` 的说明），
即量测方程 ``h(ω) = scale ⊙ (ω·φ_par + ω̄·φ_ser)`` 关于 ``ω`` 是**仿射**的。

无迹变换对仿射函数是**精确**的，于是

    P^yy = H·P·H^T + R,   P^xy = P·H^T

两者代入本类的更新式，与 :class:`~regenerative_braking.identification.ekf.EKF`
的更新式**逐项恒等**（见 :meth:`UKF.update` 的说明与
``tests/test_ukf.py::test_ukf_matches_ekf_on_this_linear_in_weights_model``）。

也就是说：**就权重训练而言，UKF 相对 EKF 不带来任何精度收益。**
方案把 EKF/UKF 按「非线性强弱」分工（阶段 6 的模式切换）在
**权重训练**这一环上没有依据；若该分工要成立，UKF 必须改为同时估计
被控对象状态（那时量测方程对状态才是非线性的）。

编写人裁定：**保留方案的双滤波器分工与模式切换（阶段 6）**，
并在文档中如实说明「在权重训练这一环上两者逐项恒等」这一结构性事实。
理由：① 恒等关系本身是可验证的正确性证据（两套独立推导给出同一结果）；
② 模式切换的工程价值在**鲁棒性**而非精度——两个滤波器的数值路径不同，
切换可在一条路径出现数值退化时提供替代；③ 若强行让 UKF 同时估计被控对象状态，
需新增状态维数、可观性论证与初始化口径，属于**方案未要求的扩展**，
不应由实现方擅自引入。该事实与裁定一并写入
``docs/regenerative_braking_algorithm.md`` §5.4 与
``docs/technical_scheme_code_mapping.md`` §A.3。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from .rhonn import RHONN, PredictionContext


class UKFError(ValueError):
    """UKF 配置或输入不合法。"""


#: 方案问题编号（与 `docs/technical_scheme_code_mapping.md` §A.3 对齐）
SCHEME_ISSUE_UKF_WEIGHT_UPDATE_MISSING = 4
SCHEME_ISSUE_SYMBOL_E_OVERLOADED = 6
SCHEME_ISSUE_FILTER_STATE_DIMENSION = 11  # L 取 2 与滤波器状态维度矛盾（本模块新发现）
SCHEME_ISSUE_SAMPLING_WEIGHT = 12  # η_j^c = 0.02 的由来未说明（本模块新发现）


@dataclass(frozen=True)
class UKFConfig:
    """UKF 数值配置。

    provenance::

        eta                        official    —— 方案原文训练步长 0.01
        sampling_weight            official    —— 方案原文 η_j^c = 0.02
        beta                       assumed     —— 高斯先验偏置修正的标准取值
        initial_covariance         assumed     —— 初始权重不确定度，无实测依据
        process_noise              assumed     —— 权重随机游走方差，无实测依据
        measurement_noise_*        assumed  —— R 的**定义**已裁定（问题 3：
                                     量测噪声协方差，n_x × n_x 对角阵），
                                     与 EKF 取同一套预设值；
                                     数值无实测依据，待量测设备精度资料到位后替换
    """

    #: 方案原文训练步长 η_i = 0.01
    eta: float = 0.01

    #: 方案原文采样权重 η_j^c = 0.02（j ≥ 1）—— 保留方案原值；
    #: 由它反解 λ = 5、η_0^m = 0.2（问题 12 裁定）
    sampling_weight: float = 0.02

    #: 标准 UT 对高斯先验的偏置修正项中的 β（α 固定取 1）
    beta: float = 2.0

    initial_covariance: float = 1.0
    process_noise: float = 1e-8

    measurement_noise_voltage_v: float = 5.0
    measurement_noise_current_a: float = 5.0

    def __post_init__(self) -> None:
        if not np.isfinite(self.eta) or self.eta <= 0.0:
            raise UKFError("eta 必须为正有限值")
        if not np.isfinite(self.sampling_weight) or self.sampling_weight <= 0.0:
            raise UKFError("sampling_weight 必须为正有限值")
        if not np.isfinite(self.beta):
            raise UKFError("beta 必须为有限值")
        if not np.isfinite(self.initial_covariance) or self.initial_covariance <= 0.0:
            raise UKFError("initial_covariance 必须为正有限值")
        if not np.isfinite(self.process_noise) or self.process_noise < 0.0:
            raise UKFError("process_noise 必须为非负有限值")
        for name, value in (
            ("measurement_noise_voltage_v", self.measurement_noise_voltage_v),
            ("measurement_noise_current_a", self.measurement_noise_current_a),
        ):
            if not np.isfinite(value) or value <= 0.0:
                raise UKFError(f"{name} 必须为正有限值")


@dataclass
class UKFUpdateRecord:
    """单步 UKF 更新的可记录量。"""

    #: x_k − ŷ^-（量测空间的辨识误差）
    innovation: np.ndarray
    #: K = P^xy · (P^yy)^(-1)
    kalman_gain: np.ndarray
    #: Δω = η · K · innovation
    parameter_update: np.ndarray
    #: P^xy —— 方案公式 (36)
    cross_covariance: np.ndarray
    #: P^yy —— 方案缺失，本实现按标准 UT 补全（问题 4）
    innovation_covariance: np.ndarray
    #: e_j(i,k) = X^j − x̂^- —— 方案公式 (37) 里被称作 e 的量。
    #: 问题 6 裁定：正式符号带 sigma 点下标 j，以避开与 EKF 辨识误差 e 的一符两义；
    #: 代码字段名沿用 sigma_deviation。
    sigma_deviation: np.ndarray
    covariance_trace: float
    covariance_min_eigenvalue: float


class UKF:
    """基于无迹卡尔曼滤波的 RHONN 权重训练器。

    滤波器状态向量是**可调权重** ``ω ∈ R^{n_w}``（``n_w = 20``，
    问题 15 裁定后并联 10 + 串联 10），
    量测是被控对象的实际状态 ``x_k ∈ R^{n_x}``（``n_x = 2``）。

    .. warning::
       方案原文写「L 取 2」，那是量测维度而非滤波器状态维度（问题 11）。
       本实现取 ``L = n_w``。

    .. note::
       在本问题上量测方程对 ``ω`` 是仿射的，无迹变换精确，
       因此本类与 :class:`~regenerative_braking.identification.ekf.EKF`
       给出**逐项恒等**的更新（见模块 docstring 末节）。
    """

    name = "ukf"

    def __init__(
        self,
        rhonn: RHONN,
        config: Optional[UKFConfig] = None,
        *,
        measurement_noise: Optional[Sequence[Sequence[float]]] = None,
    ) -> None:
        self.rhonn = rhonn
        self.config = config or UKFConfig()

        n_w = rhonn.n_tunable_weights
        n_x = rhonn.state_dim
        cfg = self.config

        # ---- 无迹变换权重（问题 4 / 问题 12 的裁定落地） ----
        # 由方案给的 η_j^c 反解 λ：η_j^c = 1/(2(L+λ))  ⟺  L + λ = 1/(2·η_j^c)
        self._lambda = 1.0 / (2.0 * cfg.sampling_weight) - n_w
        spread = n_w + self._lambda
        if spread <= 0.0:
            raise UKFError(
                f"sampling_weight={cfg.sampling_weight} 过大："
                f"要求 0 < sampling_weight < 1/(2L) = {1.0 / (2.0 * n_w):.6g}"
            )

        center_mean = self._lambda / spread  # η_0^m
        if center_mean < 0.0:
            raise UKFError(
                f"sampling_weight={cfg.sampling_weight} 使中心点均值权重为负："
                f"要求 sampling_weight < 1/(2L) = {1.0 / (2.0 * n_w):.6g}"
            )

        self._mean_weights = np.full(2 * n_w + 1, cfg.sampling_weight, dtype=float)
        self._mean_weights[0] = center_mean

        # α 固定取 1，故偏置修正项 (1 − α² + β) = β
        self._covariance_weights = self._mean_weights.copy()
        self._covariance_weights[0] = center_mean + cfg.beta

        self._spread_root = float(np.sqrt(spread))

        # ---- 量测噪声 R（与 EKF 同口径） ----
        if measurement_noise is None:
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
                raise UKFError("量测噪声维度与 state_dim 不一致")
        else:
            arr = np.asarray(measurement_noise, dtype=float)
            if arr.shape != (n_x, n_x):
                raise UKFError(f"measurement_noise 形状必须为 {(n_x, n_x)}，实际为 {arr.shape}")
            self._measurement_noise = arr.copy()

        self._covariance = np.eye(n_w) * cfg.initial_covariance

    # ------------------------------------------------------------------
    # 只读属性
    # ------------------------------------------------------------------

    @property
    def covariance(self) -> np.ndarray:
        """权重误差协方差矩阵 P 的副本。"""
        return self._covariance.copy()

    def adopt_covariance(self, covariance: Sequence[Sequence[float]]) -> None:
        """接管外部传入的权重误差协方差 P（供 EKF/UKF 模式切换使用）。

        与 :meth:`EKF.adopt_covariance` 同一契约：形状必须为
        ``(L, L)``（``L = n_parameters``，**不是**方案原文的 2），
        传入矩阵对称化后写入。因为 UKF 与 EKF 在本问题上逐项恒等，
        接管不会改变数值，只是让被切到的滤波器不带着初始 ``P`` 重新起步。
        """
        arr = np.asarray(covariance, dtype=float)
        expected = (self.n_parameters, self.n_parameters)
        if arr.shape != expected:
            raise UKFError(f"covariance 形状必须为 {expected}，实际为 {arr.shape}")
        if not np.all(np.isfinite(arr)):
            raise UKFError("covariance 必须全部为有限值")
        self._covariance = 0.5 * (arr + arr.T)

    @property
    def measurement_noise(self) -> np.ndarray:
        """量测噪声协方差矩阵 R 的副本。"""
        return self._measurement_noise.copy()

    def reconfigure(self, *, config: UKFConfig) -> None:
        """在运行前同步更新 ``eta``、Q 和 R，并重置协方差。"""
        if not isinstance(config, UKFConfig):
            raise UKFError("reconfigure需要UKFConfig")
        self.config = config
        self._measurement_noise = np.diag(np.asarray([
            config.measurement_noise_voltage_v**2,
            config.measurement_noise_current_a**2,
        ][:self.rhonn.state_dim], dtype=float))
        self.reset()

    @property
    def n_parameters(self) -> int:
        """滤波器状态维度 L —— 即可调权重数，**不是**方案原文的 2。"""
        return self.rhonn.n_tunable_weights

    @property
    def n_sigma_points(self) -> int:
        return 2 * self.n_parameters + 1

    @property
    def lambda_(self) -> float:
        """UT 的 λ —— 由方案 η_j^c 反解得到（问题 12）。"""
        return float(self._lambda)

    @property
    def mean_weights(self) -> np.ndarray:
        """η_j^m 的副本（方案缺失，问题 4）。"""
        return self._mean_weights.copy()

    @property
    def covariance_weights(self) -> np.ndarray:
        """η_j^c 的副本（方案原文值 0.02，问题 12）。"""
        return self._covariance_weights.copy()

    def reset(self) -> None:
        """重置协方差到初值（权重不动，由 RHONN 自己管理）。"""
        self._covariance = np.eye(self.n_parameters) * self.config.initial_covariance

    # ------------------------------------------------------------------
    # 无迹变换
    # ------------------------------------------------------------------

    def sigma_points(
        self, mean: Sequence[float], covariance: Sequence[Sequence[float]]
    ) -> np.ndarray:
        """生成 sigma 点，返回 shape ``(2L + 1, L)``。

        第 0 个为中心点，随后 ``L`` 个沿协方差平方根的正方向、
        再 ``L`` 个沿负方向（标准对称采样）。
        """
        mean_arr = np.asarray(mean, dtype=float)
        cov_arr = np.asarray(covariance, dtype=float)
        if mean_arr.shape != (self.n_parameters,):
            raise UKFError(f"mean 形状必须为 {(self.n_parameters,)}，实际为 {mean_arr.shape}")
        if cov_arr.shape != (self.n_parameters, self.n_parameters):
            raise UKFError(
                f"covariance 形状必须为 {(self.n_parameters, self.n_parameters)}，"
                f"实际为 {cov_arr.shape}"
            )

        scaled = (self.n_parameters + self._lambda) * cov_arr
        scaled = 0.5 * (scaled + scaled.T)
        try:
            root = np.linalg.cholesky(scaled)
        except np.linalg.LinAlgError:
            # 数值上偶发的非正定：加极小抖动后重试，抖动量随矩阵量级缩放
            jitter = 1e-12 * max(float(np.trace(scaled)) / self.n_parameters, 1e-300)
            root = np.linalg.cholesky(scaled + jitter * np.eye(self.n_parameters))

        points = np.empty((2 * self.n_parameters + 1, self.n_parameters), dtype=float)
        points[0] = mean_arr
        for i in range(self.n_parameters):
            points[1 + i] = mean_arr + root[:, i]
            points[1 + self.n_parameters + i] = mean_arr - root[:, i]
        return points

    def _measurement(self, weights: np.ndarray, context: PredictionContext) -> np.ndarray:
        """量测方程 h(ω) —— 给定权重、在给定预测上下文下的预测状态（物理量纲）。"""
        return self.rhonn.predict_with_weights(
            weights, context.state_actual, context.state_estimate_prev, context.control
        )

    # ------------------------------------------------------------------
    # 滤波一步
    # ------------------------------------------------------------------

    def update(
        self,
        state_actual: Sequence[float],
        predicted_state: Sequence[float],
        *,
        context: Optional[PredictionContext] = None,
    ) -> UKFUpdateRecord:
        """用一次新量测校正权重。

        ``predicted_state`` 是校正前对当前时刻的预测 x̂_k。
        ``context`` 是产生 x̂_k 那次预测的输入上下文；sigma 点必须在**该上下文**
        上传播，否则 ``ŷ^-`` 算的是「用当前状态预测当前状态」，与
        :meth:`EKF.update <regenerative_braking.identification.ekf.EKF.update>`
        的口径不一致。省略时退化为以当前量测构造上下文（固定权重路径非零时不可用）。

        在本问题上 ``h`` 对 ``ω`` 仿射，故本方法与
        :meth:`EKF.update <regenerative_braking.identification.ekf.EKF.update>` 等价::

            P^yy = H·P·H^T + R          （无迹变换对仿射函数精确）
            P^xy = P·H^T
            K    = P·H^T·(H·P·H^T + R)^(-1)

        协方差递推同样取与 η 自洽的形式（与 EKF 的问题 10 处理一致）::

            P ← P − η·(2 − η)·P^xy·(P^yy)^(-1)·(P^xy)^T + Q

        η = 1 时退化为标准 UKF 的 ``P ← P − K·P^yy·K^T + Q``。
        """
        cfg = self.config
        state = np.asarray(state_actual, dtype=float)
        if state.shape != (self.rhonn.state_dim,):
            raise UKFError(f"state_actual 形状必须为 {(self.rhonn.state_dim,)}，实际为 {state.shape}")

        predicted = np.asarray(predicted_state, dtype=float)
        if predicted.shape != (self.rhonn.state_dim,):
            raise UKFError(
                f"predicted_state 形状必须为 {(self.rhonn.state_dim,)}，实际为 {predicted.shape}"
            )

        context_supplied = context is not None
        if context is None:
            context = PredictionContext(
                state_actual=state,
                state_estimate_prev=predicted,
                control=np.zeros(self.rhonn.control_dim, dtype=float),
            )

        # 1) sigma 点与输出传播
        #    方案问题 15 修正后可调权重含并联 + 串联两条路径，
        #    故中心点取完整的参数向量 [W_par | W_ser]，而非仅并联块。
        points = self.sigma_points(self.rhonn.tunable_weight_matrix.ravel(), self._covariance)
        outputs = np.array([self._measurement(point, context) for point in points])  # (2L+1, n_x)

        # 2) 预测均值
        mean_state = self._mean_weights @ points          # x̂^- ∈ R^L
        mean_output = self._mean_weights @ outputs        # ŷ^-  ∈ R^{n_x}
        # 上下文正确时 mean_output 与 predicted_state 恒等（见 update 的说明）；
        # 这里做显式比较，避免上下文接错时静默走偏。
        # 省略 context 时无法比较（上下文按当前量测构造），故只在显式传入时校验。
        if context_supplied and not np.allclose(mean_output, predicted, rtol=1e-6, atol=1e-6):
            raise UKFError(
                "context 与 predicted_state 不自洽：UT 均值与上一时刻预测不一致，"
                f"mean_output={mean_output}, predicted_state={predicted}"
            )

        # 3) 偏差
        sigma_deviation = points - mean_state             # 方案 (37) 的「e」，本实现改名
        output_deviation = outputs - mean_output

        # 4) P^xy（方案 (36)）与 P^yy（方案缺失，问题 4）
        weighted_output_deviation = self._covariance_weights[:, None] * output_deviation
        cross_covariance = sigma_deviation.T @ weighted_output_deviation
        innovation_covariance = (
            output_deviation.T @ weighted_output_deviation + self._measurement_noise
        )

        # 5) 增益与权重更新
        innovation = state - mean_output
        kalman_gain = np.linalg.solve(innovation_covariance, cross_covariance.T).T
        parameter_update = cfg.eta * (kalman_gain @ innovation)
        self.rhonn.update_weights(parameter_update)

        # 6) 协方差递推（与 η 自洽，见 update 的说明）
        p_matrix = self._covariance
        correction = cross_covariance @ np.linalg.solve(
            innovation_covariance, cross_covariance.T
        )
        p_next = p_matrix - cfg.eta * (2.0 - cfg.eta) * correction
        p_next = 0.5 * (p_next + p_next.T) + cfg.process_noise * np.eye(self.n_parameters)
        self._covariance = p_next

        return UKFUpdateRecord(
            innovation=innovation.copy(),
            kalman_gain=kalman_gain.copy(),
            parameter_update=np.asarray(parameter_update, dtype=float).copy(),
            cross_covariance=cross_covariance.copy(),
            innovation_covariance=innovation_covariance.copy(),
            sigma_deviation=sigma_deviation.copy(),
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

        返回 ``(rhonn_step_record, ukf_update_record)``。
        首步没有历史预测、无法形成辨识误差，``ukf_update_record`` 为 ``None``。

        与 EKF 的 :meth:`~regenerative_braking.identification.ekf.EKF.step`
        保持同一时序：**先校正权重、再预测**。
        """
        predicted = self.rhonn.state_estimate
        context = self.rhonn.last_prediction_context

        update: Optional[UKFUpdateRecord] = None
        if predicted is not None:
            # sigma 点必须在产生 x̂_k 的那次预测的上下文上传播。
            update = self.update(state_actual, predicted, context=context)

        record = self.rhonn.step(state_actual, control, time_s=time_s)
        return record, update
