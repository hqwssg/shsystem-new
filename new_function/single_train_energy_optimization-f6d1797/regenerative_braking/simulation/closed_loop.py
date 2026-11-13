"""阶段 8 联合闭环：RHONN + EKF/UKF + 模式切换 + NSMC。

把辨识层（:mod:`regenerative_braking.identification.online_identifier`）与
控制器（:mod:`regenerative_braking.control.nsmc`）接成一个**复合控制器**，
实现既有的 :class:`~regenerative_braking.simulation.controllers.RegenController`
协议。这样接线的两个好处：

1. **仿真器主体一行不改**——阶段 1 已经验收过的能量台账、PWM 边界、SOC 约束
   全部原样复用，阶段 8 的验收判据「闭环能量台账仍闭合」因此是**同一套口径**，
   不需要为联合闭环另立标准；
2. 主算法与 baseline 共用同一个 ``run()`` 入口，阶段 9 的对比表天然可比。

--------------------------------------------------------------------------
单步时序（与方案的状态方程指标对齐）
--------------------------------------------------------------------------

::

    第 k 拍
      1. 控制器读观测量 x_k（来自 k−1 拍的变流器/储能状态）
      2. NSMC 用 x̂_k 与 x_k 算出 u_k          ← x̂_k 是 k−1 拍辨识出的预测
      3. 辨识器消费 (x_k, u_k) → 校正权重 → 产生 x̂_{k+1}
      4. 返回 u_k，仿真器施加到变流器

步骤 2 用的 ``x̂_k`` 正是方案 §4.2.1.3（2）说的「基于 RHONN 的状态估计值」。

--------------------------------------------------------------------------
本模块**同时携带八条方案问题待确认项**，全部已裁定，仍显式可见
--------------------------------------------------------------------------

联合闭环要能跑起来，就必须给方案的三处缺口（1 / 5 / 13）各填一个实现；
此外闭环跑通后暴露出第四处（14 量纲不一致）及其分支问题（14b），
再排查下去又暴露出第五处（15 控制通道 ``B`` 不可辨识 —— 本模块**曾**的
真·主阻塞项，现已解除）、第六处（16 状态向量冗余使 ``B`` 恒奇异）
与第七处（18 符号先验只钉符号、``B`` 幅值仍失真）。八条均已由编写人于
2026-09-25 裁定为正式口径。
本模块在 :meth:`ClosedLoopController.pending_scheme_items`
里逐条列出裁定结果与依据，便于审计：

问题 17 / 19 / 20 / 21 是**闭环长跑**之后才暴露的另外四条，落点不在本模块的
接线层，分别登记在 ``tests/test_validation.py``（17）、``identification/rhonn.py``
（19 / 20）与 ``tracking.py``（21）。它们是自锁解除后把回收能量从 ``0.035 kWh``
提到 🟥 ``4.1674 kWh``（``s1_flat_braking``）/ 🟥 ``2.9711 kWh``（``s2_long_downhill``）
（**问题 22 / 23 修订前**读数）的关键；本模块只在 ``nsmc_config`` / ``sample_time_s`` /
``storage_params`` 三处透传其所需上下文。问题 22（2026-09-26）与问题 23（2026-09-26）
落地后，当前交付值为 ``4.1676 kWh``（``s1``）/ ``2.9713 kWh``（``s2``），
见 ``docs/regenerative_braking_algorithm.md`` §5.10 / §5.11。

问题 22（主算法结果不随步长收敛）是问题 20 的**后果**，已于 2026-09-26 处置：
问题 20 的不可达支路由 ``−u_0·sign(Bᵀ·s)``（不连续）改为
``box_constrained_least_squares``（连续、可达时与无约束解逐位相同），
旧读法保留为 ``reachability_fallback="bang_bang"``。落地后全量重跑
（14 场景 × 128 次）基线逐位不变、交付场景差 ``≤ 0.0033%``；
详见 ``docs/regenerative_braking_algorithm.md`` §5.10.7 / §5.10.8。

============================  =======================================  ================================
方案问题                       编写人裁定                                依据 / 影响
============================  =======================================  ================================
1（原阻塞）``u_eq`` 定义式缺失   ``u_eq = B⁺·(x_ref − g(x, x̂, 0))``         由 ``s_{k+1} = 0`` 直接解出
5 ``λ_k`` 作用位置未说明        ``s = λ_k·(x − x_ref)``，默认施加           方案对它的命名即「滑模面系数」
13 ``x_ref`` 构造式未给出       ``RegenerativeReferenceState``               制动曲线请求 ∩ SOC 可用 ∩ 电流上限
14（新发现）(34)(35) 量纲不一致   ``u_n = −S_sc·(s/x_scale)``（标幺基准）      原文 u_n 被饱和分支完全丢弃
14b（新发现）分支条件与缩放方向不同向量 两处统一取 ``u_eq + u_n``（DPS）       原文越限时剔除 u_n，稳定项失效
15（新发现）``B = ∂g/∂u`` 不可辨识  串联权重并入可调向量 + 符号先验              B 随辨识变化、符号由物理确定
16（新发现）``(v_out, i_out)`` 冗余  状态向量改为 ``(v_out, i_L)``               B 不再结构性奇异
18（新发现）``B`` 幅值只有真值 ~1/5  控制通道**增益先验**（幅值热启动）            B 的幅值由变流器小信号增益定
============================  =======================================  ================================

问题 14 的量化后果（阶段 9 实测，**修正前**）：主算法在全部 14 个验证场景上回收
能量恒为 0.0000 kWh，与「不控」一致——**"优化算法"这一侧当时整体不可评估**。
诊断由 :func:`~regenerative_braking.validation.suite.diagnose_optimized_controllers`
产出并写进 ``manifest.json``。

**但问题 14 不是主阻塞项。** 把 ``u_n`` 换成量纲自洽的实现（``u_n ≡ 0``）之后
回收能量**仍是 0**。根因是问题 15：``NSMC`` 的 Jacobian 走固定随机权重路径，
与可调权重逐位无关（实测 ``max|B1−B0| = 0.0``），``B_diag`` 符号纯随机
（12 个种子中 3 个对角全负）⟹ ``u_eq`` 为负 ⟹ 占空比被截断为 0 ⟹ ``u ≡ 0``
⟹ 控制通道永远激励不到 ⟹ ``B`` 永远不可辨识（自锁）。四个控制律候选因此全部回收 0 kWh。

**裁定落地**：问题 15 让 ``u`` 进入**并联与串联两段可调权重**
（``∂x̂/∂u`` 结构性含可调权重，``B`` 随在线辨识变化），并按变流器 ODE
给出的物理先验 ``sign(B) = [[+,−],[+,+]]`` 在初始化时定符号，打破自锁；
问题 16 把状态向量改为互相独立的 ``(v_out, i_L)``（``i_L`` 是变流器原生状态量），
对象 ``B`` 由此满秩（数值微分实测 ``det ≠ 0``、``rank = 2``）。
裁定后闭环**真正回收非零能量**（见 ``test_closed_loop_actually_recovers_energy``）。

尽管如此，**联合闭环的全部数值结果仍是 `仿真结果，不作为工程结论`**，
因为被控对象的电力电子与储能参数本身仍是 placeholder。这一点写进 ``audit()``
的返回值，由阶段 9 透传到对比表。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Tuple

import numpy as np

from ..control.nsmc import NSMC, NSMCConfig, StandardEquivalentControl
from ..dynamics.dc_dc_converter import DCConverterParameters, DutyLimits
from ..identification.online_identifier import (
    IdentificationRecord,
    IdentificationSample,
    OnlineIdentifier,
    build_online_identifier,
)
from ..identification.storage_resistance import build_storage_resistance_estimator
from ..identification.rhonn import (
    DEFAULT_SAMPLE_TIME_S,
    PENDING_SCHEME_CONFIRMATION,
    RHONN,
    RHONNConfig,
    ControlChannelGainPrior,
)
from ..tracking import (
    SCHEME_ISSUE_REFERENCE_ASSEMBLY_SPLIT,
    RegenerativeReferenceState,
    REFERENCE_STORAGE_MATCHED,
    build_reference_state,
)
from .controllers import (
    ControllerCommand,
    ControllerError,
    ControllerObservation,
)
from .electrical_measurement_filter import ElectricalMeasurementFilter


def with_control_channel_gain_prior(
    rhonn_config: Optional[RHONNConfig],
    converter_params: Optional[DCConverterParameters],
    sample_time_s: Optional[float] = None,
    *,
    enabled: bool = True,
) -> Optional[RHONNConfig]:
    """把控制通道**增益**先验（方案问题 18）注入 RHONN 配置。

    ``B = ∂x̂/∂u`` 是**一步**灵敏度，其幅值正比于采样步长 ``dt``，因此目标 ``B``
    必须用真实步长算。本函数是该步长唯一的注入点：

    * 给了 ``converter_params`` → 用变流器参数与 ``dt`` 构造
      :class:`ControlChannelGainPrior`（``dt`` 省略时落到
      :data:`~regenerative_braking.identification.rhonn.DEFAULT_SAMPLE_TIME_S`，
      即验证套件默认步长 ``2e-4``，并在 :meth:`ClosedLoopController.audit` 中可见）；
    * 没给 ``converter_params``、或 ``enabled=False`` → 原样返回
      （退回「仅符号先验」的修正前行为，供回归对比）。

    调用方已自带先验时**不覆盖**（便于回归对比）。
    """
    if converter_params is None or not enabled:
        return rhonn_config
    base = rhonn_config or RHONNConfig()
    if base.control_channel_gain_prior is not None:
        return base
    dt = DEFAULT_SAMPLE_TIME_S if sample_time_s is None else float(sample_time_s)
    prior = ControlChannelGainPrior.from_converter_params(converter_params, dt)
    return replace(base, control_channel_gain_prior=prior)


@dataclass(frozen=True)
class PendingSchemeItem:
    """一处方案问题及其**编写人裁定结果**（历史字段名保留，语义已变为「裁定记录」）。"""

    #: 方案问题编号；"14b" 表示问题 14 的第二处不一致（分支条件与缩放方向不同向量）
    issue_number: "int | str"
    title: str
    substitute: str
    consequence: str


#: 联合闭环携带的八条方案问题项及其裁定（问题编号与映射文档 §A.3 / §A.4 / §A.5 对齐）。
#:
#: 注意范围：本表**只含 1 / 5 / 13 / 14 / "14b" / 15 / 16 / 18 八条**。
#: 问题 19 / 20 / 21 / 22 的裁定**不在本表**，其登记落点是
#: ``control/nsmc.py`` 的 ``StandardEquivalentControl`` 类 docstring 与
#: ``docs/regenerative_braking_algorithm.md`` §5.7–§5.10。
#: 问题 20 的支路已于 2026-09-26 由 bang-bang 修订为盒约束最小二乘
#: （问题 22 的处置），旧读法保留为 ``reachability_fallback="bang_bang"``。
CLOSED_LOOP_PENDING_ITEMS: Tuple[PendingSchemeItem, ...] = (
    PendingSchemeItem(
        issue_number=1,
        title="等效控制量 u_eq 的定义式在方案中完全缺失（公式 (34)(35) 逐字相同）",
        substitute="裁定：u_eq = B⁺·(x_ref − g(x_k, x̂_k, 0))，B = ∂g/∂u（StandardEquivalentControl，data_status=scheme_authored）",
        consequence=(
            "由 s_{k+1} = 0 直接解出，物理含义即「抵消系统固有动态」；"
            "方案语气暗示的 u_eq = −B^(−1)·f̂ 读法已否决（它把状态驱到 0 而非 x_ref，"
            "与 s = x − x_ref 自相矛盾）"
        ),
    ),
    PendingSchemeItem(
        issue_number=5,
        title="时变滑模面系数 λ_k 被声明却未被任何公式使用，作用位置未说明",
        substitute="裁定：s(x_k,k) = λ_k·(x_k − x_{ref,k})，λ_k = 0.9+0.1·e^(−0.1k)，k 为采样步序号；默认施加",
        consequence=(
            "方案对 λ_k 的命名即「滑模面系数」，乘入滑模面是唯一与命名自洽的位置；"
            "λ_0 = 1.0 → λ_k ↓ 0.9，与正文「初期快速跟踪、后期精准维稳」方向一致。"
            "baseline 与主算法共用（都走 sliding_surface），不产生口径漂移"
        ),
    ),
    PendingSchemeItem(
        issue_number=13,
        title="参考状态 x_{ref,k} 的构造式未给出（正文只说由制动曲线与 SOC 共同确定）",
        substitute=(
            "裁定：P_abs = min(P_req, P_avail, P_conv, P_storage)；"
            "v_ref = clip((V_oc + √(V_oc² + 4·P_abs·R_int))/2, V_min, V_max)；"
            "i_L,ref = clip(P_abs/v_ref, 0, i_L,max)"
        ),
        consequence=(
            "P_req 来自制动曲线、P_avail 来自 SOC 与包络——即正文所说「共同确定」。"
            "电流分量由 buck 稳态 v_out = d1·v_in 与 d1·i_L = η·i_src 联立推出，"
            "效率恰好相消，故不含任何经验标定系数；"
            "原 absorption_fraction = 0.1 经验系数已删除。"
            "电压分量经**问题 21** 二次修订：初版取「窗口内就地保持」v_ref = clip(v_out, …)，"
            "它把 i_sink = (v_out − V_oc)/R_int 一并钉死，迫使 d2 旁路掉多余 i_L；"
            "现行式由 v_out·(v_out − V_oc) = P_abs·R_int 反解，即「储能吸收该功率所需电压」，"
            "并补上储能功率上限 P_storage。幅值依赖 V_oc / R_int（本项目为 placeholder），"
            "结构（d2 → 0、i_L → i_sink）不依赖，见 docs/regenerative_braking_algorithm.md §5.9"
        ),
    ),
    PendingSchemeItem(
        issue_number=14,
        title="控制律 (34)(35) 量纲不一致：u_n = −S_sc·s 带 V/A 量纲，却与无量纲的 u_0 直接比较",
        substitute="裁定：u_n = −S_sc·(s/x_scale)，x_scale 取标幺基准 (1100 V, 3000 A)（normalised_surface，data_status=scheme_authored）",
        consequence=(
            "原文实测 ‖u_n‖ ≈ 147.9 ≫ u_0 = 0.9，饱和分支恒触发、u_n 被完全丢弃，"
            "控制器退化为 bang-bang；裁定后 u_n 无量纲、恢复作用。"
            "x_scale 直接取 dc_dc_parameters.json 的额定电压与电流上限，不引入自由参数；"
            "原 scheme_literal 读法已标为 rejected_scheme_reading，仅供回归对比"
        ),
    ),
    PendingSchemeItem(
        issue_number="14b",
        title="控制律 (34)(35) 分支条件与缩放方向不是同一个向量（越限时 u_n 被完全剔除）",
        substitute="裁定：两处统一取 u_eq + u_n，即保方向饱和（DPS）：越限时输出 u_0·(u_eq+u_n)/‖u_eq+u_n‖",
        consequence=(
            "原文分支条件用 ‖u_eq+u_n‖、缩放方向却用 u_eq 的模，二者不自洽；"
            "且一旦越限就把 u_n 从输出中剔除，使滑模稳定项在本对象的量级下实际失效。"
            "裁定式在 ‖u_eq+u_n‖ = u_0 处连续，并保留 u_n 的方向贡献"
        ),
    ),
    PendingSchemeItem(
        issue_number=15,
        title="控制通道 B = ∂g/∂u 不可辨识：Jacobian 只经固定随机权重路径，与可调权重逐位无关",
        substitute=(
            "裁定：串联路径权重并入可调向量（n_tunable_weights 8→20）"
            "+ 控制通道符号先验 sign(B)=[[+,-],[+,+]]"
        ),
        consequence=(
            "修正前实测 max|B1−B0| = 0.0（逐位不变）、B_diag 符号纯随机（12 个种子中 3 个对角全负）"
            "⟹ u_eq 为负 ⟹ 占空比被截断为 0 ⟹ u ≡ 0 ⟹ 自锁，四个控制律候选全部回收 0 kWh。"
            "裁定后 B 随在线辨识变化（实测 max|ΔB| = 113.4（40 拍）/ 281.9（400 拍）），"
            "符号由变流器 ODE 推出的物理先验确定，自锁被打破"
        ),
    ),
    PendingSchemeItem(
        issue_number=16,
        title="状态向量 (v_out, i_out) 代数相关，使 B = ∂(v_out,i_out)/∂u 恒为秩 1（det ≡ 0）",
        substitute="裁定：状态向量改为互相独立的 (v_out, i_L)（i_L 是变流器原生状态量）",
        consequence=(
            "修正前 i_out = (v_out − v_oc)/R_int ⟹ ∂i_out/∂u = (1/R_int)·∂v_out/∂u，"
            "两行比值恒为 1/R_int = 20.000、det ≡ 0、rank = 1，u_eq 无法独立跟踪双目标。"
            "裁定后对象 B = ∂(v_out,i_L)/∂u 满秩（实测 det = 234.7 / 1112.0、rank = 2），"
            "符号 ∂v_out/∂d1 > 0、∂v_out/∂d2 < 0、∂i_L/∂d1 > 0、∂i_L/∂d2 > 0"
        ),
    ),
    PendingSchemeItem(
        issue_number=18,
        title="控制通道符号先验只钉符号，B 的幅值仍只有被控对象真值的 ~1/5",
        substitute=(
            "裁定：补全「用已知模型热启动」到幅值——控制通道增益先验 "
            "B_target = [[(1−d2)·v_in·dt²/(2LC_out), −i_L·dt/C_out], "
            "[v_in·dt/L, v_out·dt/L]]，由变流器小信号增益给出，无自由参数"
        ),
        consequence=(
            "实测（族 7，dt=4e-4）∂i_L/∂d1 真值 1231.4 vs 辨识值 253（0.21×）、"
            "∂i_L/∂d2 真值 ~897 vs 134（0.30×）⟹ B⁺ 被放大 ≈5× ⟹ ‖u_eq‖ 达 1.5~1e3 ≫ u_0=0.9 "
            "⟹ 保方向饱和每拍触发、‖u_n‖≈0.42 被淹没（问题 14b 裁定形同虚设）⟹ "
            "i_L 被推到 1.50× 额定（4498 A）、v_out 越窗（1615.5 V）。"
            "裁定后 i_L 峰值 1004 A（0.33× 额定）、v_out 峰值 1120.1 V（窗内）；"
            "代价是回收能量 0.0600 → 0.0347 kWh（激进工况退回保守工况）"
        ),
    ),
)


class ClosedLoopError(ControllerError):
    """联合闭环配置或接线不合法。"""


class ClosedLoopController:
    """阶段 8 复合控制器：在线辨识 + NSMC。

    遵守 :class:`~regenerative_braking.simulation.controllers.RegenController` 协议，
    可直接交给 :meth:`RegenerativeBrakingSimulator.run` 使用。

    ``name`` 固定为 ``"rhonn_nsmc"``：滤波器模式（EKF/UKF）是**运行时**状态，
    不能进名字，否则同一控制器在不同拍会有不同标签，破坏对比表的行标识。
    每拍的滤波器模式由 :meth:`IdentificationRecord.filter_mode` 记录。
    """

    name = "rhonn_nsmc"

    def __init__(
        self,
        *,
        identifier: OnlineIdentifier,
        nsmc: Optional[NSMC] = None,
        limits: Optional[DutyLimits] = None,
        nsmc_config: Optional[NSMCConfig] = None,
        converter_params: Optional[DCConverterParameters] = None,
        storage_params: Optional[object] = None,
        sample_time_s: Optional[float] = None,
        reference_strategy: str = REFERENCE_STORAGE_MATCHED,
        measurement_filter_alpha: float = 1.0,
        measurement_filter_time_constant_s: float = 0.0,
        storage_resistance_time_constant_s: float = 0.0,
        storage_resistance_startup_time_constant_s: Optional[float] = None,
        storage_resistance_startup_duration_s: float = 0.0,
        feedback_resistance_upper_factor: Optional[float] = None,
        controller_profile: str = "custom",
    ) -> None:
        self.identifier = identifier
        self.limits = limits or DutyLimits()
        self.converter_params = converter_params
        self.storage_params = storage_params
        self.controller_profile = str(controller_profile)
        #: 采样步长 ``dt``（s）。透传给 ``u_eq`` 提供者：``B`` 与零控制增量都是
        #: ``dt`` 阶量，必须用仿真的真实步长（问题 19/20）。
        self.sample_time_s = (
            DEFAULT_SAMPLE_TIME_S if sample_time_s is None else float(sample_time_s)
        )
        # 量测预滤波：两种指定方式二选一。``time_constant_s > 0`` 优先——它表达的是
        # 物理带宽，换步长时不用重标；``alpha`` 只保留给历史脚本与消融实验。
        if measurement_filter_time_constant_s and measurement_filter_alpha != 1.0:
            raise ClosedLoopError(
                "量测预滤波的 alpha 与 time_constant_s 只能给一个："
                "前者是每拍系数（随步长变），后者是物理时间常数"
            )
        if measurement_filter_time_constant_s:
            self.measurement_filter = ElectricalMeasurementFilter.from_time_constant(
                time_constant_s=measurement_filter_time_constant_s,
                sample_time_s=self.sample_time_s,
            )
        else:
            self.measurement_filter = ElectricalMeasurementFilter(
                alpha=measurement_filter_alpha, sample_time_s=self.sample_time_s)

        # 储能内阻在线估计（2026-11-07）：参考电压用「储能吸收匹配」式求解时，
        # 式中 R 是**装配值**，而对象的真实吸收电流是 (v_out − V_oc)/R_真。
        # 于是回收量 ∝ R_装配/R_真：内阻一旦偏大就按 1/R 塌陷（2× 时实测
        # 4.03 → 2.04 kWh）。R 本来就能由同一拍量测反解，故在线估计后注入参考。
        # 0 = 关闭（历史口径），此时行为与未引入本模块逐位一致。
        self.storage_resistance_estimator = build_storage_resistance_estimator(
            storage_params=storage_params,
            converter_params=converter_params,
            time_constant_s=storage_resistance_time_constant_s,
            sample_time_s=self.sample_time_s,
            startup_time_constant_s=storage_resistance_startup_time_constant_s,
            startup_duration_s=storage_resistance_startup_duration_s,
        )
        #: 装配时的参考内阻，``reset()`` 用它把注入值还原，避免跨场景热启动。
        self._reference_resistance_ohm = (
            None if storage_params is None
            else float(storage_params.internal_resistance_ohm)
        )

        if nsmc is not None:
            if reference_strategy != REFERENCE_STORAGE_MATCHED:
                raise ClosedLoopError("显式传入 nsmc 时参考策略必须在其参考模型内配置")
            if feedback_resistance_upper_factor is not None:
                raise ClosedLoopError("显式传入 nsmc 时不能另行装配参考内阻上界")
            if nsmc.rhonn is not identifier.rhonn:
                raise ClosedLoopError(
                    "NSMC 持有的 RHONN 与辨识器的不是同一实例；"
                    "那样控制器会读到未训练的权重，不允许。"
                )
            self.nsmc = nsmc
        else:
            # 问题 13 裁定：x_ref 用正式构造式；有被控对象参数时从**同一**
            # 参数对象取电压窗口与电感电流上限，保证控制器与对象同源。
            # 问题 21 裁定：再取储能侧的开路电压与内阻，使电压分量走
            # 「储能吸收匹配」而非「就地保持」——后者会让 d2 被迫旁路。
            #
            # 问题 30 裁定（2026-09-26）：装配路径**只允许一条**。
            # 原先这里是三分支，走哪一条取决于调用方「恰好传了哪些可选参数」，
            # 三条路径给出三个不同的控制器而标签完全一样（实测 ``pid`` 在两条
            # 入口下回收能量差 0.28%、``i_L`` 峰值差 1297 A）。
            # 因此：
            #   * 只给一个参数 → **报错**，不替调用方选一条（不许静默退化）；
            #   * 两个都不给 → 允许（这是显式选择「纯默认装配」），但口径会在
            #     audit() 里以 assembly_path="defaults" 暴露出来。
            if (converter_params is None) != (storage_params is None):
                given = "converter_params" if converter_params is not None else "storage_params"
                missing = "storage_params" if converter_params is not None else "converter_params"
                raise ClosedLoopError(
                    f"方案问题 {SCHEME_ISSUE_REFERENCE_ASSEMBLY_SPLIT}："
                    f"x_ref 的装配路径不完整——只给了 {given}，缺 {missing}。"
                    "只给一个参数会静默退化到问题 21 修正前的历史口径"
                    "（电压分量「窗口内就地保持」、且没有储能功率上限 P_storage），"
                    "与同时给两个参数的正式口径给出**两个不同的控制器**。"
                    "请补齐两个参数（正式路径），或两个都不给"
                    "（显式选择纯默认装配，audit() 会标注 assembly_path=\"defaults\"）。"
                )
            if converter_params is not None:
                reference_model = build_reference_state(
                    converter_params, storage_params, strategy=reference_strategy,
                    feedback_resistance_upper_factor=feedback_resistance_upper_factor,
                )
            else:
                if feedback_resistance_upper_factor is not None:
                    raise ClosedLoopError(
                        "没有储能参数时不能装配反馈参考内阻上界"
                    )
                reference_model = RegenerativeReferenceState(strategy=reference_strategy)
            # 问题 27：``u_0`` 必须**先解析成一个数**再分发，否则
            # ``NSMCConfig.u_0``（饱和律）与 ``StandardEquivalentControl.u_0``
            # （可达性判据 + 盒约束最小二乘的盒半径）会各拿一份，
            # 调用方一改 ``nsmc_config.u_0`` 就静默分叉。
            # 这里不重复默认值：``NSMC`` 内部也是 ``config or NSMCConfig()``，
            # 故 ``resolved_nsmc_config`` 与 ``self.nsmc.config`` 必为同一个数。
            resolved_nsmc_config = nsmc_config if nsmc_config is not None else NSMCConfig()
            self.nsmc = NSMC(
                rhonn=identifier.rhonn,
                reference_model=reference_model,
                # 问题 1 裁定：u_eq 用正式定义式；问题 19/20 裁定要求把真实步长
                # 透传进去（B 与零控制增量都是 dt 阶量）；问题 27 裁定要求
                # ``u_0`` 与饱和律同源。
                equivalent_control=StandardEquivalentControl(
                    identifier.rhonn,
                    sample_time_s=self.sample_time_s,
                    u_0=resolved_nsmc_config.u_0,
                ),
                limits=self.limits,
                config=resolved_nsmc_config,
                sample_time_s=self.sample_time_s,
            )

        #: 问题 30：本次装配实际使用的 ``x_ref`` 口径（见
        #: :data:`~regenerative_braking.tracking.ASSEMBLY_PATHS`）。
        #: 透传给 :meth:`audit`，使「这次的 x_ref 是按哪条路径装的」可被下游核对——
        #: 该信息原先无处可见，正是「同标签两个控制器」能长期并存的原因。
        self.reference_assembly_path = self.nsmc.reference_model.assembly_path

        self._last_identification: Optional[IdentificationRecord] = None
        self._measurement_gap = False
        self._rejected_measurements = 0
        self._measurement_reanchors = 0
        #: ``reset()`` 被调用过几次。第 2 次起权重是**上一次运行学到的**（热启动），
        #: 读数会随之轻微漂移——仿真器据此在结果里显式标注，见 ``run()``。
        self._run_count = 0

    @property
    def run_count(self) -> int:
        """本实例已启动过多少次运行（``reset()`` 次数）。"""

        return self._run_count

    # ------------------------------------------------------------------
    # 协议实现
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """清空辨识递归、滤波器协方差与模式历史。**权重保留**。

        .. warning::
           权重保留意味着**同一个实例连续跑第二个场景时是热启动的**：第二个场景的
           前若干拍用上一场景学到的权重，读数与「新建控制器再跑」不同（实测同一场景
           重跑，净存入 1.023138811709 → 1.022264756990 kWh，差 0.085%）。

           生产路径（``validation/baselines.py`` 的工厂、``database/cli.py``、
           ``run_project.py``）**每次运行都新建控制器**，因此不受影响；自己写循环
           复用实例时请显式新建，否则结果依赖运行顺序。仿真器会把
           ``run_count > 1`` 的情况写进结果的 ``extra_notes``。
        """
        self._run_count += 1
        self.identifier.reset()
        self.nsmc.reset()
        self.measurement_filter.reset()
        if self.storage_resistance_estimator is not None:
            # 估计值必须回装配值：否则复用实例跑第二个场景时开局就带着上一场景的
            # 内阻结论，属于同一类「热启动依赖运行顺序」的缺陷。
            self.storage_resistance_estimator.reset()
            restore = self.nsmc.reference_model
            if (
                self._reference_resistance_ohm is not None
                and getattr(restore, "storage_internal_resistance_ohm", None) is not None
            ):
                restore.storage_internal_resistance_ohm = self._reference_resistance_ohm
        reset_reference = getattr(self.nsmc.reference_model, "reset", None)
        if reset_reference is not None:
            reset_reference()
        self._last_identification = None
        self._measurement_gap = False
        self._rejected_measurements = 0
        self._measurement_reanchors = 0

    def compute(self, observation: ControllerObservation) -> ControllerCommand:
        """一拍联合计算：先控制、后辨识（时序见模块 docstring）。"""
        observation = self.measurement_filter.apply(observation)
        if not observation.electrical_measurement_valid or observation.storage_charge_power_limit_w == 0:
            self._clear_reference_memory()
        if not observation.electrical_measurement_valid:
            # 未知真实电流时不继续取能；不把 last-valid 重复校正为新量测。
            # 权重/P/模式历史保留，递归预测在下一有效拍重新衔接。
            self._measurement_gap = True
            self._rejected_measurements += 1
            self._last_identification = None
            command = ControllerCommand(0.0, 0.0, note="invalid_electrical_measurement").validate(self.limits)
            self.nsmc.accept_applied_command(command)
            return command
        if self._measurement_gap:
            # RHONN 的旧预测只对应缺测首拍，不能和恢复拍形成创新。
            # reset 仅清递归上下文；不重置权重、P 或全程模式计数。
            self.identifier.rhonn.reset()
            self._measurement_gap = False
            self._measurement_reanchors += 1
        # 0) 内阻在线估计 → 注入参考（必须在 nsmc.compute 之前，否则本拍仍用旧值）
        self._apply_storage_resistance_estimate(observation)
        # 1) NSMC 用 x̂_k（k−1 拍的预测）与 x_k 算出 u_k
        command = self.nsmc.compute(observation)

        # 2) 辨识器消费 (x_k, u_k)，校正权重并产生 x̂_{k+1}
        #    状态向量 = (v_out, i_L)：互相独立（方案问题 16 已修正）。
        state_actual = np.asarray(
            [observation.output_voltage_v, observation.inductor_current_a], dtype=float
        )
        control = np.asarray([command.duty_cycle_T1, command.duty_cycle_T2], dtype=float)
        self._last_identification = self.identifier.update(
            IdentificationSample(
                time_s=float(observation.time_s),
                state_actual=state_actual,
                control=control,
                speed_mps=float(observation.speed_mps),
                requested_regen_power_w=float(observation.requested_regen_power_w),
                inductor_current_a=float(observation.inductor_current_a),
                gradient_per_mille=float(observation.gradient_per_mille),
            )
        )
        set_model_confidence = getattr(self.measurement_filter, "set_model_confidence", None)
        if set_model_confidence is not None:
            set_model_confidence(self._last_identification.normalised_innovation)
        accept_measurement_command = getattr(self.measurement_filter, "accept_applied_command", None)
        if accept_measurement_command is not None:
            accept_measurement_command(command)
        return command

    def _apply_storage_resistance_estimate(self, observation: ControllerObservation) -> None:
        """用本拍量测更新内阻估计，并把它写进参考模型的 R。

        只在参考策略为「储能吸收匹配」时注入：反馈策略里 ``R`` 是**局部修正尺度**
        （其固定点不要求 ``R`` 等于真值），换掉会改变那些研究 profile 的口径。
        估计器未就绪（还没有一次有效更新）时不写，行为与关闭时逐位一致。
        """

        estimator = self.storage_resistance_estimator
        if estimator is None:
            return
        estimator.update(observation.output_voltage_v, observation.output_current_a)
        model = self.nsmc.reference_model
        if getattr(model, "strategy", None) != REFERENCE_STORAGE_MATCHED:
            return
        if not estimator.ready:
            return
        if getattr(model, "storage_internal_resistance_ohm", None) is None:
            return
        model.storage_internal_resistance_ohm = estimator.value_ohm

    def accept_applied_command(self, command: ControllerCommand) -> None:
        """实际执行器在采样间被 BMS 关闭时同步控制记忆，不额外校正权重。"""
        self.nsmc.accept_applied_command(command)
        accept_measurement_command = getattr(self.measurement_filter, "accept_applied_command", None)
        if accept_measurement_command is not None:
            accept_measurement_command(command)
        if command.duty_cycle_T1 == command.duty_cycle_T2 == 0.0:
            self.measurement_filter.clear()
            self._clear_reference_memory()

    def _clear_reference_memory(self) -> None:
        clear = getattr(self.nsmc.reference_model, "clear", None)
        if clear is not None:
            clear()

    # ------------------------------------------------------------------
    # 诊断
    # ------------------------------------------------------------------

    @property
    def last_identification(self) -> Optional[IdentificationRecord]:
        return self._last_identification

    @property
    def filter_mode(self) -> str:
        """当前生效的滤波器模式。"""
        return self.identifier.filter_mode

    @property
    def rhonn(self) -> RHONN:
        return self.identifier.rhonn

    @property
    def pending_scheme_items(self) -> Tuple[PendingSchemeItem, ...]:
        """本控制器携带的方案待确认项（八条，见模块 docstring）。"""
        return CLOSED_LOOP_PENDING_ITEMS

    @property
    def control_channel_gain_prior(self) -> Optional[ControlChannelGainPrior]:
        """当前辨识器使用的控制通道增益先验（问题 18 裁定）；未注入时为 ``None``。"""
        return self.identifier.rhonn.config.control_channel_gain_prior

    def audit(self) -> Mapping[str, Any]:
        """联合闭环审计摘要，供阶段 9 的对比表与结果文件透传。"""
        identification = self.identifier.audit()
        prior = self.control_channel_gain_prior
        return {
            "controller": self.name,
            "controller_profile": self.controller_profile,
            "pending_scheme_confirmation": PENDING_SCHEME_CONFIRMATION,
            "pending_scheme_items": tuple(
                {
                    "issue": item.issue_number,
                    "title": item.title,
                    "substitute": item.substitute,
                    "consequence": item.consequence,
                }
                for item in self.pending_scheme_items
            ),
            "u_eq_status": self.nsmc.equivalent_control.data_status,
            "x_ref_status": self.nsmc.reference_model.data_status,
            "reference_strategy": getattr(self.nsmc.reference_model, "strategy", "custom"),
            "feedback_resistance_upper_factor": getattr(self.nsmc.reference_model, "feedback_resistance_upper_factor", None),
            "feedback_envelope_status": getattr(self.nsmc.reference_model, "feedback_envelope_status", None),
            "electrical_measurement_filter": self.measurement_filter.audit(),
            "storage_resistance_estimation": (
                self.storage_resistance_estimator.audit()
                if self.storage_resistance_estimator is not None else None
            ),
            "command_smoothing_schedule": (self.nsmc.smoothing_audit()
                if hasattr(self.nsmc, "smoothing_audit") else None),
            "dynamic_reference": (self.nsmc.reference_model.audit()
                if hasattr(self.nsmc.reference_model, "audit") else None),
            "reference_review_required": getattr(self.nsmc.reference_model, "strategy", "custom") != REFERENCE_STORAGE_MATCHED,
            "storage_charge_feedback": "逐拍使用储能或电池管理系统的充电功率许可；空值仅兼容历史调用",
            "storage_charge_exit_steps": self.nsmc.storage_charge_exit_steps,
            "rejected_electrical_measurements": self._rejected_measurements,
            "measurement_reanchors": self._measurement_reanchors,
            "missing_measurement_policy": "两路占空比归零，冻结网络权重与协方差；下次有效量测到达时重新锚定递归高阶神经网络",
            "negative_pwm_request_steps": self.nsmc.negative_pwm_request_steps,
            # 问题 30 裁定：x_ref 的**装配口径**。审计必须能回答「这次的 x_ref
            # 是走正式口径（storage_matched）还是历史口径（legacy_voltage_hold）
            # 还是纯默认（defaults）」——三者的电压分量与储能功率上限都不同，
            # 而它们给出的控制器标签完全一样。
            "x_ref_assembly_path": self.reference_assembly_path,
            # 问题 20 修订（2026-09-25）：一步不可达时的支路读法。
            # 审计必须能回答「这次的 u_eq 用的是盒约束最小二乘还是被否决的
            # bang-bang」——两者的步长行为完全不同（问题 22）。
            "reachability_fallback": getattr(
                self.nsmc.equivalent_control, "reachability_fallback", None
            ),
            # 问题 23 裁定：饱和律的范数口径。审计必须能回答「这次的饱和用的是
            # 盒（∞ 范数）还是历史的 2 球」——两者在越界拍上的输出不同，
            # 而它决定了「控制量是否真的贴着执行器可行域边界」。
            "saturation_norm": getattr(self.nsmc.config, "saturation_norm", None),
            # 问题 18 裁定：控制通道增益先验（幅值热启动）的可见性。
            # 审计必须能回答「这次仿真的 B 幅值是按哪个 dt 热启动的」——
            # 该值与仿真步长不一致会按比例带偏 B，且不会自己报错。
            "control_channel_gain_prior": None
            if prior is None
            else {
                "sample_time_s": prior.sample_time_s,
                "nominal_state": tuple(float(v) for v in prior.nominal_state),
                "nominal_control": tuple(float(v) for v in prior.nominal_control),
                "target_b": tuple(tuple(float(v) for v in row) for row in prior.target_b),
                "data_status": prior.data_status,
                "provenance": prior.provenance,
                "warm_start_residual": self.identifier.rhonn.gain_prior_residual,
                "nominal_output_residual": self.identifier.rhonn.nominal_output_residual,
                "sign_prior_flips": self.identifier.rhonn.sign_prior_flips,
            },
            "identification": identification,
        }


def build_closed_loop_controller(
    *,
    limits: Optional[DutyLimits] = None,
    rhonn_config: Optional[RHONNConfig] = None,
    identifier: Optional[OnlineIdentifier] = None,
    nsmc_config: Optional[NSMCConfig] = None,
    converter_params: Optional[DCConverterParameters] = None,
    storage_params: Optional[object] = None,
    sample_time_s: Optional[float] = None,
    apply_control_channel_gain_prior: bool = True,
    measurement_filter_time_constant_s: float = 0.0,
    measurement_filter_alpha: float = 1.0,
    storage_resistance_time_constant_s: float = 0.0,
    storage_resistance_startup_time_constant_s: Optional[float] = None,
    storage_resistance_startup_duration_s: float = 0.0,
    history_limit: int = 2000,
    reference_strategy: str = REFERENCE_STORAGE_MATCHED,
    feedback_resistance_upper_factor: Optional[float] = None,
    controller_profile: str = "custom",
) -> ClosedLoopController:
    """按默认配置装配一个联合闭环控制器（阶段 9 直接调用）。

    ``converter_params`` 传入被控对象的变流器参数对象时，参考量的电压窗口与
    电感电流上限即取自同一对象（问题 13 裁定），避免控制器与被控对象各用一套数。

    ``storage_params`` 传入储能参数对象时，参考量的电压分量改走**储能吸收匹配**
    （问题 21 裁定）：``v_ref`` 由 ``v_out·(v_out − V_oc) = P_abs·R_int`` 反解。
    **注意**：本项目的 ``nominal_voltage_v`` / ``internal_resistance_ohm`` 是
    placeholder，该口径的幅值依赖它们，只有结构（``d2 → 0``）是稳健的。

    .. warning::
       **问题 30 裁定（2026-09-26）—— 两个参数必须同时给或同时不给。**

       原先「只给 ``converter_params``」会**静默退回**「窗口内就地保持」的历史口径
       （问题 21 修正前，且没有储能功率上限 ``P_storage``），而调用方拿到的控制器
       标签与正式口径完全一样。现在这种调用直接抛
       :class:`ClosedLoopError`；两个都不给仍允许（显式选择纯默认装配），
       但口径会在 :meth:`ClosedLoopController.audit` 的
       ``x_ref_assembly_path`` 里暴露为 ``"defaults"``。

    ``sample_time_s`` 传该次仿真的**真实步长**时，会据此构造控制通道增益先验
    （问题 18 裁定）注入辨识器——``B = ∂x̂/∂u`` 是**一步**灵敏度，幅值正比于 ``dt``，
    用错步长会把幅值热启动按 ``dt`` 比例带偏。省略时落到
    :data:`~regenerative_braking.identification.rhonn.DEFAULT_SAMPLE_TIME_S`
    （验证套件默认步长），并可在 :meth:`ClosedLoopController.audit` 中核对。

    ``apply_control_channel_gain_prior=False`` 可显式关闭该先验，退回「仅符号先验」
    的修正前行为，供回归对比与消融实验使用。

    ``measurement_filter_time_constant_s > 0`` 启用因果量测预滤波（一阶 IIR，时间常数
    以秒给出）。默认 ``0`` = 关闭（历史口径）。它**只滤两个电压通道**（输入/输出母线），
    不滤电流、不碰功率请求、时间、SOC 与 BMS 许可；缺测/拒充/时间缺口会清记忆并在
    下一有效拍重锚。电流不进滤波集合的原因：电感电流是内环快速反馈，1.9 ms 滞后会把
    峰值推出额定（实测 i_L 峰值 2595 → 4032 A，额定 3000 A）。
    噪声族（s8）的标定见 ``docs/measurement_prefilter_2026-11-07.md``。
    """
    config_with_prior = with_control_channel_gain_prior(
        rhonn_config,
        converter_params,
        sample_time_s,
        enabled=apply_control_channel_gain_prior,
    )
    if identifier is None:
        identifier = build_online_identifier(
            rhonn=config_with_prior, history_limit=history_limit
        )
    elif converter_params is not None and apply_control_channel_gain_prior:
        # 调用方自带辨识器：在**辨识开始前**就地注入先验（RHONN 会拒绝晚注入）。
        dt = DEFAULT_SAMPLE_TIME_S if sample_time_s is None else float(sample_time_s)
        identifier.rhonn.set_control_channel_gain_prior(
            ControlChannelGainPrior.from_converter_params(converter_params, dt)
        )
    return ClosedLoopController(
        identifier=identifier,
        limits=limits,
        nsmc_config=nsmc_config,
        converter_params=converter_params,
        storage_params=storage_params,
        sample_time_s=sample_time_s,
        reference_strategy=reference_strategy,
        measurement_filter_time_constant_s=measurement_filter_time_constant_s,
        measurement_filter_alpha=measurement_filter_alpha,
        storage_resistance_time_constant_s=storage_resistance_time_constant_s,
        storage_resistance_startup_time_constant_s=storage_resistance_startup_time_constant_s,
        storage_resistance_startup_duration_s=storage_resistance_startup_duration_s,
        feedback_resistance_upper_factor=feedback_resistance_upper_factor,
        controller_profile=controller_profile,
    )
