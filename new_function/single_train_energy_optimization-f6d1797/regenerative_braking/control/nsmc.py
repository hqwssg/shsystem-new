"""NSMC 滑模控制器（阶段 7–8）。

对应技术方案 §4.2.1.3（2）**NSMC 滑模控制算法**。

方案原文（公式 (34)(35)；证据图 ``fig_nsmc_sliding_surface_and_lambda.png``、
``fig_nsmc_control_law_34.png``、``fig_nsmc_control_law_35.png``）::

    s(x_k)   = x_k − x_{ref,k}                      滑模面
    λ_k      = 0.9 + 0.1·e^(-0.1k)                  时变滑模面系数
    u_n      = −S_sc · s(x_k)                       稳定项（S_sc 为 Schur 矩阵）

    u(x_k,k) = ⎧ u_eq + u_n,                ‖u_eq + u_n‖ < u_0
               ⎩ u_0 · u_eq / ‖u_eq‖,       ‖u_eq + u_n‖ ≥ u_0        (34)(35)

    u_0 = 0.9                                        PWM 占空比上限

**原文只写 ``‖·‖`` 未指明范数**。问题 14(b) 统一了「分支条件与缩放方向用同一个
向量」；**问题 23（2026-09-26）统一了范数**——``u_0`` 是逐通道上限，故三处
（可达性判据 / 盒约束最小二乘 / 保方向饱和）一律走 :func:`actuator_norm`
（盒 = ∞ 范数），历史 2 球口径保留为 ``saturation_norm="l2_ball_legacy"``。

--------------------------------------------------------------------------
编写人裁定（2026-09-25）：方案在此处的四处缺口已全部给出正式口径
--------------------------------------------------------------------------

方案编写人已授权**由实现方以编写人身份直接裁定**。以下四条不再保留
「待确认」姿态，每条都写明**正式口径 / 推导依据 / 被否决读法与理由**。
``Pending*`` 哨兵类保留，仅供复现「未裁定前」的历史行为。

**问题 1（原「阻塞」）—— 等效控制量 u_eq 的定义式完全缺失**

方案正文写道「基于 RHONN 的状态估计值，计算等效控制量 ``u_eq`` 以抵消系统固有动态」，
按文意其后应给出定义式；但该位置实际排入的是最终控制律 (34)，
而 (35) 与 (34) **逐字相同**（已用源数据字节比对 + PDF 逐像素比对双重确认）。
全文 47 个公式对象中不存在任何 ``u_eq`` 的定义式。

裁定（正式定义式，见 :class:`StandardEquivalentControl`）::

    x̂_{k+1} = g(x_k, x̂_k, u_k) ≈ g(x_k, x̂_k, 0) + B·u_k ,   B = ∂g/∂u
    s_{k+1} = λ_{k+1}·(x̂_{k+1} − x_ref) = 0
      ⟹  u_eq = B⁺ · ( x_ref − g(x_k, x̂_k, 0) )

``B⁺`` 取 Moore–Penrose 伪逆（``B`` 为 2×2，在串联路径饱和或工作点病态时可能近奇异，
伪逆比直接求逆稳健）。物理含义：**抵消系统固有动态**——先算零控制下系统自己的走向
``g(x_k, x̂_k, 0)``，再取使下一步落到 ``x_ref`` 的输入。

**被否决的读法**：方案正文的语气暗示的写法是
``u_eq = −(∂s/∂x·B)^(−1)·(∂s/∂x·f̂)``。因 ``s = x − x_ref`` 故 ``∂s/∂x = I``，
该式化为 ``u_eq = −B^(−1)·f̂``，它把下一步状态驱到 **0** 而不是驱到 ``x_ref``。
否决理由：① 方案自己定义的滑模面是 ``s = x − x_ref``，等效控制的定义就是
「使 ``s_{k+1} = 0``」，即驱到 ``x_ref``；把状态驱到原点会使跟踪任务在
``x_ref ≠ 0`` 时产生稳态偏差，与「跟踪型控制器」的定位自相矛盾；
② 两种写法**恰好相差一个 ``x_ref`` 项**，因此这不是两种等价写法，而是一处实质笔误。

**问题 5（原「中」）—— 时变系数 λ_k 被声明却未被任何公式使用**

裁定：``λ_k`` **乘入滑模面**，``s(x_k, k) = λ_k·(x_k − x_{ref,k})``；
``k`` 为**采样步序号**（正文注「``k`` 为采样步长」为笔误，否则 ``λ_k`` 是常数、与「时变」矛盾）。
推导与取舍见 :mod:`regenerative_braking.tracking`。
:class:`NSMCConfig` 的 ``apply_lambda_k`` 默认 **True**，即默认施加。

**问题 13（原「高」）—— 参考状态 x_{ref,k} 的构造式未给出**

裁定：正式构造式为

    v_ref   = clip( v_out , V_out,min , V_out,max )
    P_abs   = min( P_req , P_avail , P_conv )
    i_L,ref = clip( P_abs / v_out , 0 , i_L,max )

其中 ``P_req`` 来自制动曲线、``P_avail`` 来自 SOC 与包络——即正文所说的
「由列车制动曲线与储能系统 SOC 共同确定」。实现见
:class:`~regenerative_braking.tracking.RegenerativeReferenceState`，
原 ``absorption_fraction`` 经验系数已删除。推导与被否决读法见
:mod:`regenerative_braking.tracking`。

**问题 14（原「高」）—— 控制律 (34)(35) 两处不一致**

* **(a) 量纲不一致。** ``u_n = −S_sc·s`` 里的 ``s`` 分量是电压 (V) / 电流 (A)，
  所以 ``u_n`` 带 V/A 量纲，却与无量纲的 ``u_0 = 0.9`` 直接比较。
  实测（标称工况 ``x_k = (1100 V, 0 A)``、``x_ref = (1100 V, 211.3 A)``）::

      s   = (0, −211.26)   [V, A]
      u_n = (0, +147.89)   ‖u_n‖ ≈ 147.9  ≫  u_0 = 0.9

  后果是第二支**恒成立**、``u_n`` 被完全丢弃，控制器退化为 bang-bang。
  裁定：``u_n = −S_sc·(s / x_scale)``，``x_scale`` 取状态量的**标幺基准**
  （见 :data:`DEFAULT_STATE_SCALE`），使 ``u_n`` 无量纲。
  被否决读法：``scheme_literal``（照原文、量纲不一致）保留在候选表中，
  状态标为 ``REJECTED_SCHEME_READING``，仅供「未修正」回归对比。

* **(b) 分支条件与缩放方向不是同一个向量。** 原文分支条件用 ``‖u_eq + u_n‖``，
  缩放方向却用 ``u_eq`` 的模（``u_0·u_eq/‖u_eq‖``）。
  裁定：两处统一取 ``u_eq + u_n``，即

      ‖u_eq + u_n‖ < u_0  →  u_eq + u_n
      ‖u_eq + u_n‖ ≥ u_0  →  u_0 · (u_eq + u_n) / ‖u_eq + u_n‖

  这是标准的**保方向饱和**（direction-preserving saturation，DPS）：
  在 ``‖u_eq+u_n‖ = u_0`` 处连续，且饱和后仍保留 ``u_n`` 的**方向贡献**。
  被否决读法：照原文取 ``u_0·u_eq/‖u_eq‖``——它与自己的分支条件不自洽，
  且一旦越限就把 ``u_n`` 从输出里彻底剔除，使滑模稳定项只在未越限的
  极小区域内起作用（在本对象的量级下该区域实际为空集）。

**问题 15 / 16（原「阻塞」，实现期新发现）—— 控制通道结构缺陷**

* **问题 15**：``u`` 原先只出现在**固定权重**项 ``ω̄`` 里，``∂x̂/∂u`` 结构性不含
  可调权重，在线辨识改不动它（实测 ``max|Δω| = 130.4``、``max|Δ预测| = 168789.9``，
  而 ``max|ΔB| = 0.0``），``B`` 符号纯随机，形成「``u ≡ 0`` ⟹ 通道无激励 ⟹
  ``B`` 永远不可辨识」的自锁。
  裁定：``u`` 同时进入**并联（可调）与串联（可调）两段权重**，
  ``n_tunable_weights`` 由 8 增至 20；控制通道**符号**由物理先验
  ``sign(B) = [[+,−],[+,+]]`` 经参数投影施加。
  详见 :mod:`regenerative_braking.identification.rhonn`。
* **问题 16**：``i_out = (v_out − v_oc)/R_int`` 让两个状态分量代数相关，
  对象的 ``B`` 恒为秩 1（``det ≡ 0``），``u_eq`` 无法独立跟踪双目标。
  裁定：状态向量由 ``(v_out, i_out)`` 改为 ``(v_out, i_L)``（``i_L`` 为变流器
  原生独立状态量），``B`` 不再结构性奇异；本模块 ``compute()`` 已按新坐标取
  ``observation.inductor_current_a``，参考量第二分量亦为电感电流参考。

**问题 19 / 20（实现期新发现）—— ``u_eq`` 的两处口径缺陷导致闭环自锁**

主算法在 ``s1_flat_braking`` / ``s2_long_downhill`` 上实测只回收到 ``0.035 kWh``、
``duty_saturation_ratio = 0.98``（``d1`` 98% 的拍贴 0），只有常值占空比基线的 ``1/87``。
逐拍轨迹（``tools/probe_main_algorithm_nsmc_trace.py``，28519 拍）与跨修订二分
（``tools/bisect_regression_probe.py``）定位到 ``u_eq`` 的两处缺陷：

* **问题 19 —— ``B`` 只在标称点精确。** 问题 18 的增益先验把 ``B_target`` 钉在
  ``i_L = 3000 A``（额定）上，而 ``B_target`` 是**状态相关**的
  （``∂v_out/∂d2 = −i_L·dt/C_out``）。实际起点 ``i_L = 0`` 处 RHONN 给出的
  ``∂v_out/∂d2 = +40.90``，物理要求 ``−30.0``——**符号相反**。
  裁定：``B`` 改由变流器平均模型的解析小信号增益**按当前工作点逐拍重算**
  （见 :class:`~regenerative_braking.identification.rhonn.ControlChannelModel`），
  来源可在 :attr:`StandardEquivalentControl.last_input_matrix_source` 审计。
* **问题 20 —— 「一步死拍」在不可达时退化为错误方向。** 被控对象是两时间尺度系统
  （``∂v_out/∂d1 ∝ dt²`` 是二阶小量，``∂i_L/∂d1 = v_in·dt/L`` 是一阶量），
  「一步把 ``i_L`` 从 0 送到额定」物理上不可达。此时最小二乘解退化：``d1`` 分量
  被解成荒谬的大数、``d2`` 被交叉项拖成负值，保方向饱和后得到
  ``d1 = 0.5486 < v_out/v_in = 0.684`` ⟹ ``di_L/dt < 0`` ⟹ ``i_L`` 被续流二极管
  截断在 0 ⟹ 通道无激励 ⟹ 辨识更不准——**自锁**。
  裁定：先算无约束解，``‖u_free‖_∞ ≤ u_0``（一步可达）时直接采用；
  越界时改用**可达域内最速下降** ``u_eq = −u_0·sign(Bᵀ·(x̂_k − x_ref))``
  （Utkin 意义下的一步最优）。零控制预测 ``g(·, 0)`` 同时改由变流器模型的解析
  零控制增量给出，不再依赖未收敛的辨识外推。

修正效果（s1/s2，全分辨率）：回收能量 ``0.000 / 0.081 → 1.235 / 0.875 kWh``，
``d1`` 贴轨占比 ``0.98 → 0.06``。残余的「能量只有基线 29%」由问题 21
（``x_ref`` 的电压分量口径）解释，见 :mod:`regenerative_braking.tracking`。

.. note::
   问题 20 的最速下降分支是**纯方向性**的（``sign``），因此 ``λ_k`` 的幅值作用
   在该分支下不显著——``‖u_eq‖`` 已撑满控制预算，``u_n`` 的方向贡献被保方向饱和
   淹没。这在物理上是合理的（到达阶段本就该用满控制），但检验「``λ_k`` 被施加」
   必须在**可达**工况下进行（见 ``tests/test_nsmc.py``）。

--------------------------------------------------------------------------
问题 35（2026-11-08，实现期新发现）：零控制预测少一半二阶项 ⟹ 稳态电压偏置
--------------------------------------------------------------------------

一步死拍控制**没有积分作用**：``u_eq = B⁺(x_ref − g(·,0))`` 是对模型的直接求逆，
所以模型漂移的误差 ``e`` 会成为**永久**稳态偏差 ``x_∞ = x_ref − e``。

``ControlChannelModel.zero_control_delta`` 对 ``Δv_out`` 用矩形法（整拍内 ``i_L``
视为常数），而 ``B[0][0] = (1−d2)·v_in·dt²/(2LC)`` 用的却是三角积分（``d1`` 抬升
``i_L`` 贡献的电荷）。缺的那一半是 ``A₀·dt²/(2C)``，``A₀ = −(v_out+R_L·i_L)/L``。

``dt²`` 因子本应让它成为二阶小量，但稳态下 ``d1·v_in/L ≈ −A₀``（``d1`` 抬升 ``i_L``
的速率恰被自然衰减抵消），两者同量级、符号相反。储能母线
``dP/dv = (2v−V_oc)/R_int ≈ 58 kW/V`` 负责放大：

* ``dt = 1e-4``（交付口径）：漏项 ⟹ 母线低 ``0.5 V`` ⟹ ``33 kW`` ⟹
  ``P_acc/P_ref = 0.984`` ⟹ **对传统 SMC 落后 1.6%**；
* ``dt = 2e-4``：漏项 ⟹ 母线低 ``2.1 V`` ⟹ ``124 kW`` ⟹ ``0.938`` ⟹ 落后 6.2%。

同一个缺陷按 ``dt²`` 缩小，交付口径看到的是 1.6%。它还让 ``d2`` 停在 ``0.061``
而非方案 ``modes.regen_charge`` 要求的 0。补齐后 ``P_acc/P_ref = 1.00000``、
``v_out`` 逐位等于 ``v_ref``、``d2 = 0``，且回收能量对 ``dt`` 不再敏感
（1e-4/2e-4/5e-4：4.2156/4.2156/4.2159 kWh）。

--------------------------------------------------------------------------
阶段定位
--------------------------------------------------------------------------

方案已给全的部分（滑模面、``λ_k``、``u_n``、饱和律、``u_0``）完整实现并逐项测试；
方案缺失的三处（``u_eq`` 定义式、``x_ref`` 构造式、``λ_k`` 作用位置）与
量纲不一致的一处（问题 14）已由编写人裁定为正式口径；
控制通道结构缺陷（问题 15 / 16 / 19）与 ``u_eq`` 的可达性缺陷（问题 20）
已按物理与文献修正。
控制器遵守既有的 :class:`~regenerative_braking.simulation.controllers.RegenController`
协议，从而与 baseline 共用同一套观测/输出口径，避免阶段 8 接线时口径漂移。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, Tuple, runtime_checkable

import numpy as np

from ..dynamics.dc_dc_converter import DutyLimits
from ..identification.rhonn import (
    DEFAULT_SAMPLE_TIME_S,
    PENDING_SCHEME_CONFIRMATION,
    RHONN,
)
from ..simulation.controllers import (
    ControllerCommand,
    ControllerError,
    ControllerObservation,
)
# 方案级跟踪口径统一放在 `regenerative_braking.tracking`，由 baseline 与主算法
# 共用，避免口径漂移。这里再导出一遍，使 §C.4 契约里的名字（sliding_surface /
# lambda_k / SchurStabilisingMatrix / 参考量提供者）仍可从本模块取用。
from ..tracking import (  # noqa: F401  (re-export)
    FIXED_BY_IMPLEMENTATION,
    REJECTED_SCHEME_READING,
    SCHEME_AUTHORED,
    SCHEME_ISSUE_EQUIVALENT_CONTROL_MISSING,
    SCHEME_ISSUE_LAMBDA_PLACEMENT,
    SCHEME_SCHUR_EIGENVALUE_RANGE,
    SCHEME_U0,
    BusTrackingReference,
    PendingReferenceState,
    PendingSchemeConfirmationError,
    ReferenceStateProvider,
    RegenerativeReferenceState,
    SchurStabilisingMatrix,
    TrackingError,
    lambda_k,
    sliding_surface,
)
from .control_law_candidates import (  # noqa: F401  (re-export)
    CANDIDATE_CAVEAT,
    CANDIDATE_STATUS,
    CONTROL_LAW_CANDIDATES,
    DEFAULT_CANDIDATE_KEY,
    ControlLawCandidate,
    StabilisingTermRequest,
    candidate_by_key,
    candidate_keys,
    candidate_table,
)


class NSMCError(TrackingError, ControllerError):
    """NSMC 配置或输入不合法。

    同时继承 :class:`~regenerative_braking.tracking.TrackingError`（跟踪口径）
    与 :class:`~regenerative_braking.simulation.controllers.ControllerError`（控制器层），
    这样调用方无论按哪一层捕获都能拦住。
    """


#: 状态向量 ``(v_out, i_L)`` 的**标幺基准** ``(V, A)``（问题 14(a) 裁定）。
#:
#: 取值即 ``data/single_train/dc_dc_parameters.json`` 的额定值：
#: ``1100 V`` = ``output_voltage_nominal_v``（储能侧母线额定电压）、
#: ``3000 A`` = ``max_output_current_a``（电感/输出电流硬上限）。
#:
#: 为什么用**标幺基准**而不是窗口半宽：状态第二分量就是 ``i_L``，
#: 其满量程是电流上限 ``3000 A``；第一分量的满量程是母线额定电压 ``1100 V``。
#: 标幺化（per-unit）使无量纲滑模面在「状态偏离一个额定值」时约为 1，
#: 这是电力电子控制的标准做法，也让 ``x_scale`` 完全由已有额定量决定、
#: 不引入任何自由参数。此前的 ``(300 V, 3000 A)`` 把**输入侧**电压窗口半宽
#: 用在了**输出侧**状态分量上，属坐标错配，已随本次裁定改正。
DEFAULT_STATE_SCALE: Tuple[float, float] = (1100.0, 3000.0)

#: 方案问题编号 **27**（实现期自行发现，非方案正文问题）：占空比上限 ``u_0``
#: 在三个地方各存一份、构造时**不做一致性校验**，因此可以静默分叉：
#:
#: ====================================  ==========================================
#: ``NSMCConfig.u_0``                    保方向饱和（``saturate_direction_preserving``）
#:                                      与 ``note`` 里的 ``saturated`` 判据
#: ``StandardEquivalentControl.u_0``     可达性判据（``‖u_eq‖_∞ ≤ u_0``）与
#:                                      盒约束最小二乘的盒半径
#: ``DutyLimits.u0_max``                 最终逐通道限幅（``clamp_with_u0``）
#: ====================================  ==========================================
#:
#: 实测（2026-09-26，``tools/probe_wiring_consistency.py``）：经
#: ``ClosedLoopController`` 装配时，``nsmc_config.u_0`` **不会**透传到
#: ``StandardEquivalentControl`` ——``NSMCConfig(u_0=0.5)`` 下饱和律用 ``0.5``、
#: 可达性判据却仍用 ``0.9``，两个 ``u_0`` 分叉。默认路径（``u_0 = 0.9``）三处
#: 恰好一致，故交付数字不受影响，但这是项目纪律禁止的**静默口径分叉**。
#:
#: 裁定：① ``NSMC`` 自建 ``u_eq`` 时透传 ``config.u_0``（原有行为，保持）；
#: ② ``ClosedLoopController`` 自建 ``NSMC`` 时把 ``nsmc_config.u_0`` 透传给它
#: 自建的 ``StandardEquivalentControl``；③ ``NSMC.__init__`` 在调用方**显式**
#: 给出 ``limits`` 时校验 ``limits.u0_max == config.u_0``，不一致直接报错
#: （不允许静默选一个）。
SCHEME_ISSUE_DUTY_CEILING_SPLIT = 27


# ---------------------------------------------------------------------------
# 方案已给全的部分 + 问题 14(b) 裁定：保方向饱和
# ---------------------------------------------------------------------------

#: 执行器可行域用的是**盒**（∞ 范数）——正式口径（问题 23 裁定）。
#:
#: ``u_0`` 是**逐通道**的占空比上限（见 :meth:`DutyLimits.clamp_with_u0`：
#: 每个分量独立截断到 ``[min_duty, min(max_duty, u_0)]``），故可行域是
#: ``[-u_0, u_0]^n``。2 球 ``‖u‖_2 ≤ u_0`` 是它的**真子集**。
SATURATION_NORM_BOX = "box"

#: 2 球（``‖u‖_2``）——问题 14(b) 落地时的历史口径，**仅供回归对比**。
SATURATION_NORM_BALL_LEGACY = "l2_ball_legacy"

#: 全部饱和范数口径。
SATURATION_NORMS: Tuple[str, ...] = (
    SATURATION_NORM_BOX,
    SATURATION_NORM_BALL_LEGACY,
)


def actuator_norm(vector: Sequence[float]) -> float:
    """执行器可行域的范数：**盒**（∞ 范数），即最大分量绝对值。

    这是「控制量是否越出执行器可行域」的**唯一口径**，可达性判据
    （:meth:`StandardEquivalentControl.__call__`）、盒约束最小二乘
    （:func:`box_constrained_least_squares`）与保方向饱和
    （:func:`saturate_direction_preserving`）都走本函数，避免三处各用一套范数。

    为什么是盒而不是 2 球（问题 23）
    --------------------------------
    ``u_0`` 是逐通道的占空比上限，物理可行域是盒 ``[-u_0, u_0]^n``。
    2 球是盒的**真子集**，用 2 球做饱和会把本可用的控制权限丢掉：
    ``v = (0.7, 0.7)`` 在盒内（``‖v‖_∞ = 0.7 ≤ 0.9``），
    但 ``‖v‖_2 = 0.99 > 0.9`` ⟹ 旧口径会把它错误地缩放到 ``(0.636, 0.636)``。
    """
    values = np.asarray(vector, dtype=float)
    if values.size == 0:
        return 0.0
    return float(np.max(np.abs(values)))


def saturate_direction_preserving(
    u_eq: Sequence[float],
    u_n: Sequence[float],
    u_0: float = SCHEME_U0,
    norm: str = SATURATION_NORM_BOX,
) -> np.ndarray:
    """**保方向**向量饱和律（公式 (34)(35)，问题 14(b) + 问题 23 裁定后）。

    正式口径（``norm = "box"``，即 :data:`SATURATION_NORM_BOX`）::

        ‖u_eq + u_n‖_∞ <  u_0  →  u_eq + u_n
        ‖u_eq + u_n‖_∞ ≥  u_0  →  u_0 · (u_eq + u_n) / ‖u_eq + u_n‖_∞

    未越限时直接输出 ``u_eq + u_n``；越限时按**同一个向量** ``u_eq + u_n``
    的方向径向缩放到盒 ``[-u_0, u_0]^n`` 的边界上，从而在限幅（避免 IGBT 过流）
    的同时保持控制方向不变、抑制抖振。

    .. note::
       **问题 14(b)**：方案原文的分支条件用 ``‖u_eq + u_n‖``、缩放方向却用
       ``u_eq`` 的模（``u_0 · u_eq / ‖u_eq‖``）——两者不是同一个向量，且一旦越限
       就把 ``u_n`` 从输出里完全剔除，使滑模稳定项在越限区失效。裁定：
       **两处统一取 ``u_eq + u_n``**。照原文的读法已标为
       ``REJECTED_SCHEME_READING``，仅作回归对比。

    .. note::
       **问题 23（2026-09-26）**：范数口径。方案原文只写 ``‖·‖`` 未指明范数，
       问题 14(b) 落地时按 2 范数实现；但 ``u_0`` 是**逐通道**的占空比上限
       （:meth:`DutyLimits.clamp_with_u0` 对每个分量独立截断），物理可行域是**盒**，
       而 2 球是盒的真子集 ⟹ 用 2 球做饱和会**丢掉本可用的控制权限**，且与
       可达性判据（``‖u_eq‖_∞ ≤ u_0``）和盒约束最小二乘（``‖u‖_∞ ≤ u_0``）
       用的**不是同一个球**。裁定：三处统一走 :func:`actuator_norm`（盒）。
       历史口径保留为 ``norm = "l2_ball_legacy"`` 供逐位回归对比。

    径向缩放的两种口径差多少（``v = u_eq + u_n``，``‖v‖_∞ > u_0``）::

        2 球：  u_0 · v / ‖v‖_2      ⟹  ∞ 范数 = u_0·‖v‖_∞/‖v‖_2  <  u_0   （偏小）
        盒：    u_0 · v / ‖v‖_∞      ⟹  ∞ 范数 = u_0                        （正好贴界）

    两者在 ∞ 范数下的差最大可达 ``u_0``（``v`` 单分量主导时），
    实测三场景触发时最大差 ``0.1897``（见算法文档 §5.11）。
    """
    equivalent = np.asarray(u_eq, dtype=float)
    robust = np.asarray(u_n, dtype=float)
    if equivalent.shape != robust.shape:
        raise NSMCError(f"u_eq 与 u_n 形状必须一致，实际为 {equivalent.shape} 与 {robust.shape}")
    if not (np.all(np.isfinite(equivalent)) and np.all(np.isfinite(robust))):
        raise NSMCError("u_eq 与 u_n 必须全部为有限值")
    if not np.isfinite(u_0) or u_0 <= 0.0:
        raise NSMCError(f"u_0 必须为正有限值，实际为 {u_0!r}")
    if norm == SATURATION_NORM_BOX:
        measure = actuator_norm
    elif norm == SATURATION_NORM_BALL_LEGACY:
        measure = lambda vector: float(np.linalg.norm(vector))  # noqa: E731
    else:
        raise NSMCError(f"未知的饱和范数口径 {norm!r}，可用项：{SATURATION_NORMS}")

    combined = equivalent + robust
    combined_norm = measure(combined)
    if combined_norm < u_0:
        return combined
    if combined_norm <= 1e-12:
        # 两个分量都为零时方向无定义，按最保守做法输出零控制，
        # 交由上层的占空比限幅兜底。
        return np.zeros_like(combined)
    return (u_0 / combined_norm) * combined


# ---------------------------------------------------------------------------
# 问题 20 裁定（2026-09-25 修订）：一步不可达时的支路
# ---------------------------------------------------------------------------

#: 一步不可达时用**盒约束最小二乘**（问题 20 的修订口径，2026-09-25）。
#:
#: ``u_eq = argmin_{‖u‖_∞ ≤ u_0} ‖ (x_ref − g(x_k, x̂_k, 0)) − B·u ‖²``
#: 见 :func:`box_constrained_least_squares`。
BOX_LEAST_SQUARES_FALLBACK = "box_least_squares"

# 非负占空比求解的显式实验分支，保留默认策略供消融；不得仅凭可行域
# 形式合理就认定它改善能量，必须经过同对象全分辨率门禁。
PHYSICAL_BOX_LEAST_SQUARES_FALLBACK = "physical_box_least_squares"

#: **被否决读法**：``u_eq = −u_0·sign(Bᵀ·(x̂_k − x_ref))``（问题 20 的原始裁定）。
#:
#: 保留它只有一个用途——让「未修订」的历史行为仍可复现、可回归对比。
#: 否决理由见 :class:`StandardEquivalentControl` 的 note（问题 22）。
BANG_BANG_FALLBACK = "bang_bang"

#: 全部 ``u_eq`` 不可达支路读法。
REACHABILITY_FALLBACKS: Tuple[str, ...] = (
    BOX_LEAST_SQUARES_FALLBACK,
    BANG_BANG_FALLBACK,
    PHYSICAL_BOX_LEAST_SQUARES_FALLBACK,
)


def box_constrained_least_squares(
    matrix: np.ndarray, target: np.ndarray, limit: float
) -> np.ndarray:
    """``argmin_{‖u‖_∞ ≤ limit} ‖matrix·u − target‖²``（盒约束最小二乘，精确解）。

    为什么需要它（问题 20 的修订，2026-09-25）
    ------------------------------------------
    等效控制的无约束解 ``u_free = B⁺·(x_ref − g)`` 要求**一步**把状态送到
    ``x_ref``。被控对象是两时间尺度系统，该目标常常超出执行器可达域
    （``‖u_free‖_∞ > u_0``）。越界时必须给一个**盒内**的解，而选哪个解
    决定了控制律是否连续：

    * 原裁定（问题 20，2026-09-25 早期）取 ``−u_0·sign(Bᵀ·(x̂_k − x_ref))``。
      它最小化的是 ``ΔV ≈ sᵀλBu``（**一阶近似**，线性泛函，盒上最优在顶点），
      且 ``sign()`` 对状态**不连续**。细步长下不可达几乎每拍成立，
      该不连续退化为持续抖振，并形成正反馈（抖振 → 跟踪变差 → 误差变大 →
      更常不可达 → 更多抖振）。实测族 R：``dt = 5e-5`` 时可达占比 ``0%``、
      控制总变差涨 ``17000`` 倍、占空比贴轨 ``33%``、回收能量跨度 ``42%``。
    * 本函数取**与无约束解同一个目标** ``‖s_{k+1}‖²``（现口径的 ``u_free``
      正是令其为 0 的解），只是把约束**精确**施加。它是严格凸二次规划的解，
      因此对 ``target`` **连续**；且 ``‖u_free‖_∞ ≤ limit`` 时与无约束最小二乘
      **逐位相同**，故是「只改支路、不改定义式」的连续延拓。

    实测（族 R / ``s1`` / ``s2``，``tools/probe_u_eq_dt_invariant_form.py``）：
    能量跨度 ``41~42% → 5.8%``（单调，Richardson 外推阶 ≈ ``1.9``，
    外推达成率 ≈ ``100.04%``）；控制总变差降 ``4`` 个数量级；贴轨 ``→ 0.0000%``；
    而在交付默认步长 ``dt = 2e-4`` 下与旧支路差 ``≤ 0.0033%``。

    实现
    ----
    维数只有 2，直接枚举「哪些分量贴界、贴哪一侧」（``3^n`` 个活跃集），
    剔除不可行者后取残差最小者即可，不需要通用 QP 求解器。

    Args:
        matrix: ``B = ∂g/∂u``，形状 ``(m, n)``。
        target: 目标增量 ``x_ref − g(x_k, x̂_k, 0)``，形状 ``(m,)``。
        limit: 盒半径 ``u_0``（``|u_i| ≤ limit``）。

    Returns:
        形状 ``(n,)`` 的盒内解。``matrix`` 数值退化时返回全零（原点恒可行）。
    """

    matrix = np.asarray(matrix, dtype=float)
    target = np.asarray(target, dtype=float)
    limit = float(limit)
    if matrix.ndim != 2 or target.shape != (matrix.shape[0],):
        raise NSMCError(
            f"盒约束最小二乘的形状不匹配：matrix {matrix.shape}、target {target.shape}"
        )
    if not (np.all(np.isfinite(matrix)) and np.all(np.isfinite(target))):
        raise NSMCError("盒约束最小二乘的输入必须全部为有限值")
    if not np.isfinite(limit) or limit <= 0.0:
        raise NSMCError(f"盒半径必须为正有限值，实际为 {limit!r}")

    count = matrix.shape[1]
    best_solution: Optional[np.ndarray] = None
    best_cost = float("inf")
    for pattern in itertools.product((-1, 0, 1), repeat=count):
        candidate = np.zeros(count, dtype=float)
        free = []
        for index, side in enumerate(pattern):
            if side == 0:
                free.append(index)
            else:
                candidate[index] = side * limit
        if free:
            residual = target - matrix @ candidate
            solution, *_ = np.linalg.lstsq(matrix[:, free], residual, rcond=None)
            candidate[free] = np.asarray(solution, dtype=float)
        # 只接受真正落在盒内的候选：贴界面上的最小二乘解可能越界，属不可行。
        if np.any(np.abs(candidate) > limit * (1.0 + 1e-12)):
            continue
        candidate = np.clip(candidate, -limit, limit)
        cost = float(np.sum((matrix @ candidate - target) ** 2))
        if cost < best_cost:
            best_cost, best_solution = cost, candidate

    if best_solution is None:  # 数值退化时的兜底：原点永远可行
        return np.zeros(count, dtype=float)
    return best_solution


# ---------------------------------------------------------------------------
# 问题 1 裁定：等效控制量 u_eq 的正式定义式
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NsmcContext:
    """一次控制计算的全部输入，供参考量/等效控制提供者使用。"""

    observation: ControllerObservation
    #: 实际状态量测 (v_out, i_L)
    state_actual: np.ndarray
    #: RHONN 的状态估计 x̂_k（辨识层未接入时退化为量测值）
    state_estimate: np.ndarray
    #: 参考状态 x_ref —— 由参考量提供者给出
    reference: np.ndarray
    #: 采样步序号 k
    step_index: int


@runtime_checkable
class EquivalentControlProvider(Protocol):
    """等效控制量提供者：``u_eq`` 的定义式（方案问题 1，已裁定）。"""

    data_status: str

    def __call__(self, context: NsmcContext) -> np.ndarray:  # pragma: no cover
        ...


class PendingEquivalentControl:
    """**历史哨兵**：问题 1 裁定前用于「不允许静默代拟 ``u_eq``」的占位实现。

    正式定义式已由 :class:`StandardEquivalentControl` 给出，本类**不再作为默认**。
    保留它只有一个用途：让「未修正」的历史行为仍可复现、可回归对比——
    显式注入本类时，一调用即抛 :class:`PendingSchemeConfirmationError`。
    """

    data_status = PENDING_SCHEME_CONFIRMATION

    def __call__(self, context: NsmcContext) -> np.ndarray:
        raise PendingSchemeConfirmationError(
            f"方案问题 {SCHEME_ISSUE_EQUIVALENT_CONTROL_MISSING}："
            "等效控制量 u_eq 的定义式未在方案原文中给出。"
            "编写人已于 2026-09-25 裁定正式定义式（见 StandardEquivalentControl），"
            "本哨兵仅用于复现「未修正」的历史行为；正常路径请勿注入本类。"
        )


class StandardEquivalentControl:
    """``u_eq`` 的**正式定义式**（方案问题 1 裁定，``data_status = SCHEME_AUTHORED``）。

    方案只说 ``u_eq`` 用来「抵消系统固有动态」。编写人裁定：按离散滑模控制的
    **标准等效控制律**落地，并把下面的推导作为正式定义式::

        x̂_{k+1} = g(x_k, x̂_k, u_k) ≈ g(x_k, x̂_k, 0) + B · u_k
        s_{k+1} = λ_{k+1}·( x̂_{k+1} − x_ref ) = 0
          ⟹  u_eq = B⁺ · ( x_ref − g(x_k, x̂_k, 0) )

    其中 ``B = ∂g/∂u``（:meth:`RHONN.jacobian_wrt_control`），
    ``B⁺`` 取 Moore–Penrose 伪逆——``B`` 为 2×2 但可能退化
    （串联路径饱和、工作点病态时），伪逆比直接求逆稳健。

    ``λ_{k+1}`` 是标量且非零，在 ``s_{k+1} = 0`` 中可约去，故定义式不含 ``λ``。

    .. note::
       **问题 19 裁定（2026-09-25）—— ``B`` 按当前工作点求值**：
       上式里的 ``B`` 曾经取 :meth:`RHONN.jacobian_wrt_control`（辨识模型的 Jacobian）。
       但问题 18 的增益先验只把 ``B`` 钉在**一个标称点**上，而 ``B_target`` 是
       **状态相关**的（``∂v_out/∂d2 = −i_L·dt/C_out``、``∂i_L/∂d2 = v_out·dt/L``）。
       标称点取的是额定 ``i_L = 3000 A``，实际起点却是 ``i_L = 0``；实测该点上
       RHONN 的 ``∂v_out/∂d2`` 符号与物理相反（``+40.90`` vs ``−30.0``），
       于是 ``B⁺·residual`` 的 ``d1`` 分量变负、被保方向饱和截为 0，
       ``i_L`` 恒为 0、控制通道无激励、模型更不准——**自锁**。
       故现在由 :meth:`_input_matrix` 按当前 ``(v_out, i_L, v_in)`` 用变流器平均模型的
       解析小信号增益重算 ``B``；没有增益先验时才退回 RHONN 的 Jacobian。
       来源可通过 :attr:`last_input_matrix_source` 审计。

    .. note::
       **问题 20 裁定（2026-09-25 早期）—— 一步不可达时改走「可达域内最速下降」**：
       上式要求 ``s_{k+1} = 0``，即**一步**把状态送到 ``x_ref``。但被控对象是
       两时间尺度系统：``∂v_out/∂d1 ∝ dt²/(L·C_out)`` 是二阶小量，而
       ``∂i_L/∂d1 = v_in·dt/L`` 是一阶量。于是「让 ``i_L`` 从 0 一步涨到额定」
       解出的 ``d1`` 远超 ``u_0``——**一步目标在物理上不可达**。

       不可达时最小二乘会退化：它优先满足灵敏度大的通道，把另一个通道的
       ``d1`` 分量交成**荒谬的大数**，再由保方向饱和按该方向缩放，最终给出
       一个方向完全错误的占空比。实测 ``s1_flat_braking`` 第 0 拍::

           x_ref = (1100 V, 2910 A)   x_k = (1100 V, 0 A)
           u_eq  = (49.55, −65.04)    ‖u_eq‖ = 81.8 ≫ u_0 = 0.9
           保方向饱和 → (0.5486, −0.7134) → d2 截为 0
           d1 = 0.5486 < v_out/v_in = 0.684  ⟹  di_L/dt < 0

       于是 ``i_L`` 被续流二极管截断在 0、控制通道无激励、辨识更不准——**自锁**。

       当时的裁定是：越界时改用**可达域内使滑模面收缩最快**的控制量
       ``u_eq = −u_0 · sign( Bᵀ · (x̂_k − x_ref) )``。

    .. note::
       **问题 20 修订（2026-09-25，问题 22 的处置）—— 支路改为盒约束最小二乘**：

       上述 bang-bang 支路解决了一拍的自锁，却引入了新的、更隐蔽的缺陷：
       ``sign()`` 对状态**不连续**，而「一步是否可达」的判据
       ``‖u_free‖_∞ ≤ u_0`` 里 ``u_0`` 是常数、``u_free ∝ 1/dt``，
       于是**同一个工作点、同一个参考量，仅因 ``dt`` 不同就切到性质完全不同的
       分支**。``dt`` 细到一定程度后可达占比掉到 ``0%``，控制器每拍都走 bang-bang，
       形成正反馈：抖振 → 跟踪变差 → 误差变大 → 更常判不可达 → 更多抖振。
       实测（族 R / ``s1`` / ``s2``，``dt = 5e-5``）：控制总变差
       ``17001 / 70669 / 49606``、占空比贴轨 ``33.3% / 34.7% / 34.1%``、
       回收能量跨度 ``42.41% / 41.48% / 40.87%``（非单调，``5e-5`` 处反向）。

       修订后的支路改为 :func:`box_constrained_least_squares`::

           u_eq = argmin_{‖u‖_∞ ≤ u_0} ‖ (x_ref − g(x_k, x̂_k, 0)) − B·u ‖²

       理由：**目标函数与无约束口径一致**——``u_free`` 正是令
       ``‖s_{k+1}‖²`` 为 0 的解，越界时对它做盒约束下的精确最小化就是同一控制律
       的**连续延拓**；而 bang-bang 最小化的是另一套目标（一阶近似
       ``ΔV ≈ sᵀλBu``，线性泛函，盒上最优在顶点）。盒约束最小二乘是严格凸 QP 的
       解，故对状态连续；``‖u_free‖_∞ ≤ u_0`` 时与 ``u_free`` **逐位相同**
       （可达时完全不改变行为）。

       实测修订效果（``tools/probe_u_eq_dt_invariant_form.py``，三场景）：
       能量跨度 ``41~42% → 5.81/5.82/5.82%`` 且**单调**（Richardson 外推阶 ≈ ``1.9``，
       外推达成率 ``100.06% / 100.04% / 100.04%``）；``dt = 5e-5`` 达成率
       ``56.6~57.6% → 99.6%``；控制总变差 ``→ 0.819/0.820/0.869``；
       贴轨 ``→ 0.0000%``（三场景全零）；可达占比 ``0% → 99.9%``。
       **在交付默认步长 ``dt = 2e-4`` 下与旧支路差 ``0.0033% / 0.0012% / 0.0017%``**
       （该步长可达占比本就 ``99.9%``，支路几乎不触发）。

       ``reachability_fallback=BANG_BANG_FALLBACK`` 可复现修订前的行为，
       仅供回归对比与消融实验，**不作为任何工程结论的依据**。

    .. note::
       **被否决的读法**：方案正文语气暗示的 ``u_eq = −(∂s/∂x·B)^(−1)(∂s/∂x·f̂)``。
       因 ``s = x − x_ref`` 故 ``∂s/∂x = I``，该式化为 ``u_eq = −B^(−1)·f̂``，
       它把下一步状态驱到 **0** 而不是驱到 ``x_ref``。否决理由：
       ① 方案自己定义 ``s = x − x_ref``，等效控制的定义就是使 ``s_{k+1} = 0``；
       ② 驱到原点会在 ``x_ref ≠ 0`` 时引入稳态偏差，与跟踪型控制器的定位矛盾；
       ③ 两式恰好相差一个 ``x_ref`` 项，属实质笔误而非等价写法。

       2026-09-25 补充实测：该读法在「``f̂`` 取连续时间漂移」的解释下等价于
       ``u_eq = B⁺·(x_k − g)``（把 ``x_ref`` 换成 ``x_k``）。实测它在
       ``dt = 2e-4`` 下 ``u_eq`` 中位数为 ``0``（92% 的拍 ``≈ 1e-13``），
       回收能量只剩同口径最好基线的 ``2.27% / 0.62% / 0.85%``（族 R / ``s1`` / ``s2``）
       ——因为本被控对象零控制下的固有动态≈0，「抵消固有动态」本身不产生控制量。
       故上述否决理由**被实测反向支持**，原裁定维持。
    """

    data_status = SCHEME_AUTHORED

    def __init__(
        self,
        rhonn: RHONN,
        *,
        use_state_dependent_gain: bool = True,
        sample_time_s: float = DEFAULT_SAMPLE_TIME_S,
        u_0: float = SCHEME_U0,
        reachability_fallback: str = BOX_LEAST_SQUARES_FALLBACK,
    ) -> None:
        self.rhonn = rhonn
        #: 是否用「按当前工作点重算的变流器小信号增益」作为输入矩阵 ``B``
        #: （问题 19 裁定）。置 ``False`` 可复现「用 RHONN 的 Jacobian」的旧行为，
        #: 便于回归对照——该旧行为实测在 ``i_L = 0`` 处 ``∂v_out/∂d2`` 符号相反，
        #: 会把 ``u_eq`` 的 ``d1`` 分量带成负值并导致自锁。
        self.use_state_dependent_gain = bool(use_state_dependent_gain)
        dt = float(sample_time_s)
        if not np.isfinite(dt) or dt <= 0.0:
            raise NSMCError(f"sample_time_s 必须为正有限值，实际为 {sample_time_s!r}")
        #: 采样步长 ``dt``（s）。**必须与仿真的真实步长一致**：``B`` 与
        #: 零控制增量都是 ``dt`` 阶量，用错步长会按比例带偏 ``u_eq`` 且不报错。
        self.sample_time_s = dt
        limit = float(u_0)
        if not np.isfinite(limit) or limit <= 0.0:
            raise NSMCError(f"u_0 必须为正有限值，实际为 {u_0!r}")
        #: 占空比上限 ``u_0``（与 :class:`NSMCConfig` 同一个数）。
        #: 用于判定「一步是否可达」（问题 20 修订）。
        self.u_0 = limit
        fallback = str(reachability_fallback)
        if fallback not in REACHABILITY_FALLBACKS:
            raise NSMCError(
                f"reachability_fallback 必须为 {REACHABILITY_FALLBACKS} 之一，"
                f"实际为 {reachability_fallback!r}"
            )
        #: 一步不可达时的支路读法（问题 20 修订，2026-09-25）。
        #: 默认 ``box_least_squares`` 即**修订后口径**；
        #: ``bang_bang`` 为**被否决读法**，保留仅供回归对比。
        self.reachability_fallback = fallback
        if fallback == PHYSICAL_BOX_LEAST_SQUARES_FALLBACK:
            self.data_status = "derived"
        self._last_input_matrix_source = "rhonn_jacobian"
        self._last_drift_source = "rhonn_predict"
        self._last_reachable = True

    @property
    def last_input_matrix_source(self) -> str:
        """上一次计算所用的输入矩阵来源。

        ``"converter_small_signal"`` = 按当前 ``(v_out, i_L)`` 重算的变流器增益；
        ``"rhonn_jacobian"`` = 退回到 RHONN 的 ``∂x̂/∂u``。
        """
        return self._last_input_matrix_source

    @property
    def last_drift_source(self) -> str:
        """上一次计算所用的零控制预测来源（问题 20 裁定）。

        ``"converter_zero_control"`` = 变流器平均模型的解析零控制增量；
        ``"rhonn_predict"`` = 退回到未收敛的辨识模型外推。
        """
        return self._last_drift_source

    @property
    def last_equivalent_control_was_reachable(self) -> bool:
        """上一次 ``u_eq`` 是否落在可达域内（``‖u_eq‖_∞ ≤ u_0``）。

        ``False`` 表示该拍走了「一步不可达」的支路（问题 20 修订后的口径：
        盒约束最小二乘；``reachability_fallback=BANG_BANG_FALLBACK`` 时为
        修订前的 bang-bang）。
        """
        return self._last_reachable

    def _input_matrix(self, context: NsmcContext) -> np.ndarray:
        """``u_eq`` 用的输入矩阵 ``B``（问题 19 裁定）。

        ``B_target`` 是**状态相关**的，而问题 18 的增益先验只在**一个标称点**上精确
        （标称 ``i_L`` 取的是额定值）。实测在 ``s2_long_downhill`` 的实际起点
        ``i_L = 0`` 处，RHONN 给出的 ``∂v_out/∂d2`` 符号与物理相反，``u_eq`` 的 ``d1``
        分量因此变负、被保方向饱和截为 0，闭环自锁（见 ``ControlChannelModel``）。

        故本方法优先按**当前工作点**重算变流器小信号增益作为 ``B``；只有在没有
        增益先验（或显式关闭）时才退回 RHONN 的 Jacobian。
        """
        prior = self.rhonn.config.control_channel_gain_prior
        if self.use_state_dependent_gain and prior is not None and prior.model is not None:
            matrix = prior.target_b_at(
                output_voltage_v=float(context.state_actual[0]),
                inductor_current_a=float(context.state_actual[1]),
                input_voltage_v=float(context.observation.input_voltage_v),
            )
            self._last_input_matrix_source = "converter_small_signal"
            return np.asarray(matrix, dtype=float)
        self._last_input_matrix_source = "rhonn_jacobian"
        return self.rhonn.jacobian_wrt_control(
            context.state_estimate, np.zeros(self.rhonn.control_dim, dtype=float)
        )

    def _zero_control_prediction(self, context: NsmcContext) -> np.ndarray:
        """零控制一步预测 ``g(x_k, x̂_k, 0)``（问题 20 裁定）。

        优先用**变流器平均模型的解析增量**（:meth:`ControlChannelModel.zero_control_delta`）：
        它只依赖被控对象的已知参数与可观测量，**不依赖辨识是否收敛**。
        没有增益先验时才退回 :meth:`RHONN.predict`——那是未收敛的辨识模型外推，
        实测会在闭环起点给出与物理不符的漂移。

        .. important::
           **方案问题 35（2026-11-08）—— 这里的漂移必须与 ``B`` 用同一套积分格式。**
           一步死拍控制没有积分作用，模型漂移的误差会**原样**变成稳态偏差
           （``x_∞ = x_ref − 漂移误差``）。``zero_control_delta`` 原先对 ``Δv_out``
           用矩形法（``i_L`` 在整拍内视为常数），而 ``B[0][0]`` 是三角积分
           （``d1`` 抬升 ``i_L`` 的那块三角形），二者缺了一半。

           这半边值随 ``dt²`` 缩小，但**不是**可以忽略的小量：储能母线
           ``dP/dv = 58 kW/V``，于是 ``dt = 1e-4`` 时 ``0.5 V`` 就对应 ``33 kW``
           （``P_acc/P_ref = 0.984``，正是「落后传统 SMC 1.6%」的来源），
           ``dt = 2e-4`` 时 ``2.1 V`` 对应 ``124 kW``（``0.938``）。
           同时 ``d2`` 会停在 ``0.061``（旁路 6% 电感电流）而不是方案
           ``modes.regen_charge`` 要求的 0。补齐后 ``P_acc/P_ref = 1.00000``、
           ``d2 = 0``、回收能量对 ``dt`` 不再敏感。
        """
        prior = self.rhonn.config.control_channel_gain_prior
        if self.use_state_dependent_gain and prior is not None and prior.model is not None:
            delta = prior.zero_control_delta(
                output_voltage_v=float(context.state_actual[0]),
                inductor_current_a=float(context.state_actual[1]),
                sink_current_a=float(
                    getattr(context.observation, "output_current_a", 0.0)
                ),
            )
            self._last_drift_source = "converter_zero_control"
            return np.asarray(context.state_actual, dtype=float) + np.asarray(
                delta, dtype=float
            )
        self._last_drift_source = "rhonn_predict"
        zero_control = np.zeros(self.rhonn.control_dim, dtype=float)
        return self.rhonn.predict(
            context.state_actual, context.state_estimate, zero_control
        )

    def __call__(self, context: NsmcContext) -> np.ndarray:
        """算出本拍的 ``u_eq``（问题 1 / 19 / 20 裁定）。

        ``‖u_free‖_∞ ≤ u_0`` 时返回标准等效控制 ``B⁺·(x_ref − g(·,0))``；
        越界（一步不可达）时按 :attr:`reachability_fallback` 取支路：

        * ``box_least_squares``（**修订后默认**）——
          ``argmin_{‖u‖_∞ ≤ u_0} ‖(x_ref − g) − B·u‖²``，与无约束口径同目标、
          对状态连续；
        * ``bang_bang``（**被否决读法**，仅供回归）——
          ``−u_0·sign(Bᵀ·(x̂_k − x_ref))``。
        """
        b_matrix = self._input_matrix(context)
        drift = self._zero_control_prediction(context)
        residual = np.asarray(context.reference, dtype=float) - np.asarray(
            drift, dtype=float
        )
        solution, *_ = np.linalg.lstsq(b_matrix, residual, rcond=None)
        solution = np.asarray(solution, dtype=float)
        if self.reachability_fallback == PHYSICAL_BOX_LEAST_SQUARES_FALLBACK:
            self._last_reachable = bool(np.all(solution >= 0.0) and np.all(solution <= self.u_0))
            if self._last_reachable:
                return solution
            center = np.full(b_matrix.shape[1], self.u_0 / 2.0)
            return center + box_constrained_least_squares(
                b_matrix, residual - b_matrix @ center, self.u_0 / 2.0
            )
        if actuator_norm(solution) <= self.u_0:
            self._last_reachable = True
            return solution
        # 一步不可达（问题 20）：目标超出可达域。无约束解会退化成
        # 「灵敏度大的通道吃满、另一个通道交出荒谬大数」，不能直接用。
        self._last_reachable = False
        if self.reachability_fallback == BOX_LEAST_SQUARES_FALLBACK:
            # 修订口径：与无约束解**同一个目标**在盒约束下的精确最小化。
            # 对状态连续，消除 bang-bang 的 sign() 不连续引起的抖振正反馈。
            return box_constrained_least_squares(b_matrix, residual, self.u_0)
        # 被否决读法（问题 20 原始裁定）：可达域内使滑模面收缩最快，
        # 但 sign() 对状态不连续。仅用于复现修订前行为。
        surface = np.asarray(context.state_estimate, dtype=float) - np.asarray(
            context.reference, dtype=float
        )
        gradient = b_matrix.T @ surface
        return -self.u_0 * np.sign(gradient)

    def map_state_to_control_space(
        self, context: NsmcContext, state_vector: Sequence[float]
    ) -> np.ndarray:
        """``B⁺ · state_vector``：把状态空间的量映射到控制空间（占空比）。

        供控制律候选 D（``state_space_jacobian``）使用——它的含义是
        「稳定项在状态空间里写，最后用与 ``u_eq`` **同一个**输入矩阵落到占空比」，
        因此量纲自动对齐，不需要方案再补一个归一化常数。

        ``B⁺`` 同样取 Moore–Penrose 伪逆，与 :meth:`__call__` 保持同一口径。
        """

        vector = np.asarray(state_vector, dtype=float)
        if vector.shape != (self.rhonn.state_dim,):
            raise NSMCError(
                f"待映射向量形状必须为 ({self.rhonn.state_dim},)，实际为 {vector.shape}"
            )
        solution, *_ = np.linalg.lstsq(self._input_matrix(context), vector, rcond=None)
        return np.asarray(solution, dtype=float)


#: 兼容别名：正式实现类的更直白名称。
EquivalentControl = StandardEquivalentControl


# ---------------------------------------------------------------------------
# 控制器
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NSMCConfig:
    """NSMC 数值配置。"""

    #: 方案原文的占空比上限 u_0
    u_0: float = SCHEME_U0

    #: Schur 稳定矩阵的对角特征值（方案只给区间 [0.6, 0.8]，裁定取中点）
    schur_eigenvalue: float = 0.7

    #: **是否把 λ_k 乘入滑模面**（问题 5 裁定：默认施加）。
    #: 置 False 可复现「λ_k 只记录不施加」的未修正行为，仅作回归对比。
    apply_lambda_k: bool = True

    #: 控制律候选（问题 14(a)）。默认 ``normalised_surface`` 即**正式口径**
    #: （量纲自洽）；``scheme_literal`` 已标为被否决读法，仅供回归对比。
    law_candidate: str = DEFAULT_CANDIDATE_KEY

    #: ``normalised_surface`` 候选用的状态**标幺基准** ``(V, A)``。
    #:
    #: 正式口径：取 ``data/single_train/dc_dc_parameters.json`` 的额定值
    #: ``(output_voltage_nominal_v, max_output_current_a) = (1100 V, 3000 A)``。
    #: 见 :data:`DEFAULT_STATE_SCALE` 的说明。
    state_scale: Tuple[float, float] = DEFAULT_STATE_SCALE

    #: **饱和律的范数口径**（问题 23 裁定：默认 ``"box"`` = 盒/∞ 范数）。
    #:
    #: ``u_0`` 是逐通道的占空比上限，物理可行域是盒；2 球是盒的真子集，
    #: 用它做饱和会丢掉本可用的控制权限，且与可达性判据 / 盒约束最小二乘
    #: 用的不是同一个球。历史口径保留为 ``"l2_ball_legacy"``，仅供逐位回归对比。
    saturation_norm: str = SATURATION_NORM_BOX

    #: 控制指令一阶平滑系数。``1`` 表示不平滑；小于 1 时对实际 PWM
    #: 指令做指数平滑，且辨识器消费平滑后的实际控制量。仅在显式鲁棒 profile
    #: 中启用，用于抑制测量噪声引起的执行器抖振。
    command_smoothing_alpha: float = 1.0

    def __post_init__(self) -> None:
        if not np.isfinite(self.u_0) or not 0.0 < self.u_0 <= 1.0:
            raise NSMCError(f"u_0 必须在 (0, 1] 内，实际为 {self.u_0!r}")
        if self.saturation_norm not in SATURATION_NORMS:
            raise NSMCError(
                f"未知的饱和范数口径 {self.saturation_norm!r}，可用项：{SATURATION_NORMS}"
            )
        if not np.isfinite(self.command_smoothing_alpha) or not 0.0 < self.command_smoothing_alpha <= 1.0:
            raise NSMCError(
                "command_smoothing_alpha 必须在 (0, 1] 内，"
                f"实际为 {self.command_smoothing_alpha!r}"
            )
        low, high = SCHEME_SCHUR_EIGENVALUE_RANGE
        if not np.isfinite(self.schur_eigenvalue) or not low <= self.schur_eigenvalue <= high:
            raise NSMCError(
                f"schur_eigenvalue 必须落在方案区间 [{low}, {high}] 内，"
                f"实际为 {self.schur_eigenvalue!r}"
            )
        candidate_by_key(self.law_candidate)  # 未知 key 在此报错并列出可用项
        scale = tuple(float(item) for item in self.state_scale)
        if len(scale) != 2 or not all(np.isfinite(item) and item > 0.0 for item in scale):
            raise NSMCError(f"state_scale 必须为两个正有限值，实际为 {self.state_scale!r}")
        object.__setattr__(self, "state_scale", scale)


class NSMC:
    """NSMC 滑模控制器（方案 §4.2.1.3（2））。

    遵守 :class:`~regenerative_braking.simulation.controllers.RegenController` 协议，
    与 baseline 共用同一套观测/输出口径。

    方案已给全的部分（滑模面、``λ_k``、``u_n``、饱和律、``u_0``）完整实现；
    方案缺失/不一致的部分（``u_eq`` 定义式、``x_ref`` 构造式、``λ_k`` 作用位置、
    (34)(35) 量纲与饱和方向）已由编写人裁定为**正式口径**，默认即采用。
    ``Pending*`` 哨兵类保留，显式注入可复现「未裁定前」的行为。

    ``state_estimate`` 的来源：接入 ``rhonn`` 时取 RHONN 的状态估计
    （方案「基于 RHONN 的状态估计值」的要求）；未接入时退化为量测值，
    便于在辨识层尚未接线时先跑通控制回路。
    """

    name = "nsmc"

    def __init__(
        self,
        *,
        rhonn: Optional[RHONN] = None,
        reference_model: Optional[ReferenceStateProvider] = None,
        equivalent_control: Optional[EquivalentControlProvider] = None,
        limits: Optional[DutyLimits] = None,
        config: Optional[NSMCConfig] = None,
        sample_time_s: Optional[float] = None,
    ) -> None:
        self.rhonn = rhonn
        self.config = config or NSMCConfig()
        #: 采样步长 ``dt``（s）。只用于装配默认的 ``u_eq`` 提供者（问题 19/20）：
        #: ``B`` 与零控制增量都是 ``dt`` 阶量，必须用仿真的真实步长。
        self.sample_time_s = (
            DEFAULT_SAMPLE_TIME_S if sample_time_s is None else float(sample_time_s)
        )
        self.limits = limits or DutyLimits(u0_max=self.config.u_0)
        # 问题 27：``u_0`` 的**单一来源**校验。调用方显式给了 ``limits`` 时，
        # 饱和律用 ``config.u_0``、最终逐通道限幅用 ``limits.u0_max``——
        # 两者不是同一个数时控制器的行为自相矛盾（饱和到 0.5 却被限幅到 0.9，
        # 或反过来把已经饱和的结果再截一刀），且**不会报任何错**。
        # 默认路径两处都是 ``SCHEME_U0 = 0.9``，故只在显式不一致时拒绝。
        if limits is not None and abs(self.limits.u0_max - self.config.u_0) > 1e-12:
            raise NSMCError(
                f"方案问题 {SCHEME_ISSUE_DUTY_CEILING_SPLIT}：占空比上限有两个来源且不一致——"
                f"NSMCConfig.u_0 = {self.config.u_0!r}（保方向饱和与 note 判据用），"
                f"DutyLimits.u0_max = {self.limits.u0_max!r}（最终限幅 clamp_with_u0 用）。"
                "同一个物理量只允许一个来源：请让二者相等，"
                "或只给其中一个（另一个会按它派生）。"
            )
        self.schur = SchurStabilisingMatrix(
            eigenvalue=self.config.schur_eigenvalue,
            dimension=2 if rhonn is None else rhonn.state_dim,
        )

        # 问题 13 裁定：x_ref 正式构造式，默认即用（无需显式注入）。
        if reference_model is not None:
            self.reference_model: ReferenceStateProvider = reference_model
        else:
            self.reference_model = RegenerativeReferenceState()

        # 问题 1 裁定：u_eq 正式定义式。它需要 B = ∂g/∂u，因此必须有 RHONN
        # （或调用方显式注入一个能提供 B 的替代实现）。缺 RHONN 时**在构造处
        # 就报错**，而不是等到 compute() 才失败——早失败、错误信息更明确。
        if equivalent_control is not None:
            self.equivalent_control: EquivalentControlProvider = equivalent_control
        elif rhonn is not None:
            self.equivalent_control = StandardEquivalentControl(
                rhonn, sample_time_s=self.sample_time_s, u_0=self.config.u_0
            )
        else:
            raise NSMCError(
                "无法确定 u_eq：等效控制量需要控制通道矩阵 B = ∂g/∂u，"
                "因此必须传入 rhonn，或显式注入一个 equivalent_control 提供者"
                "（如 StandardEquivalentControl）。"
            )

        # 控制律候选（问题 14(a)）。默认即正式口径（量纲自洽）。
        self.law_candidate: ControlLawCandidate = candidate_by_key(self.config.law_candidate)
        if self.law_candidate.requires_mapper and not hasattr(
            self.equivalent_control, "map_state_to_control_space"
        ):
            raise NSMCError(
                f"控制律候选 {self.law_candidate.key!r} 需要 u_eq 提供者给出 B⁺ 映射，"
                f"但 {type(self.equivalent_control).__name__} 不提供"
                "（StandardEquivalentControl 提供，PendingEquivalentControl 不提供）。"
            )

        self._step_index = 0
        self._last_command: Optional[ControllerCommand] = None
        self.storage_charge_exit_steps = 0
        self.negative_pwm_request_steps = 0

    # ------------------------------------------------------------------
    # 协议实现
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """清空采样步计数与上一拍输出。"""
        self._step_index = 0
        self._last_command = None
        self.storage_charge_exit_steps = 0
        self.negative_pwm_request_steps = 0
        if self.rhonn is not None:
            self.rhonn.reset()

    def accept_applied_command(self, command: ControllerCommand) -> None:
        """采样间 BMS 退出后同步平滑器实际命令；不推进离散控制拍。"""
        command.validate(self.limits)
        self._last_command = command

    @property
    def step_index(self) -> int:
        """当前采样步序号 ``k``。"""
        return self._step_index

    @property
    def last_command(self) -> Optional[ControllerCommand]:
        return self._last_command

    def compute(self, observation: ControllerObservation) -> ControllerCommand:
        """算出一拍控制量。

        流程：量测/估计 → 参考量 → **乘 λ_k 的滑模面** → 稳定项 → 等效控制 →
        保方向饱和 → 占空比限幅。默认即采用正式口径（问题 1/5/13/14/15/16）；
        仅当**显式注入** ``Pending*`` 哨兵时才会抛
        :class:`PendingSchemeConfirmationError`。
        """
        k = self._step_index
        # 状态向量 = (v_out, i_L)：互相独立（问题 16 裁定）。
        # i_L 是变流器的独立状态量，替代了原先与 v_out 代数相关的 i_out。
        state_actual = np.asarray(
            [observation.output_voltage_v, observation.inductor_current_a], dtype=float
        )
        if not np.all(np.isfinite(state_actual)):
            raise NSMCError(f"量测状态必须为有限值，实际为 {state_actual!r}")

        # SOC 满载/储能拒充是执行许可，不是状态跟踪误差。两开关归零停止
        # 从输入母线取能；已有电感能经模型的续流通道进入输出电容，新增
        # 再生功率由既有牵引网通道承接。必须绕过平滑，辨识器仍消费实际零指令。
        if observation.storage_charge_power_limit_w == 0.0:
            command = ControllerCommand(0.0, 0.0, note=f"NSMC k={k} storage_charge_unavailable").validate(self.limits)
            self._step_index += 1
            self.storage_charge_exit_steps += 1
            self._last_command = command
            return command

        state_estimate = self._resolve_state_estimate(state_actual)

        # 问题 13 裁定：x_ref 正式构造式（默认 RegenerativeReferenceState）。
        reference = np.asarray(self.reference_model(observation), dtype=float)
        if reference.shape != state_estimate.shape:
            raise NSMCError(
                f"参考量形状必须为 {state_estimate.shape}，实际为 {reference.shape}"
            )

        # 问题 5 裁定：s(x_k,k) = λ_k·(x_k − x_ref)。默认施加 λ_k；
        # 置 apply_lambda_k=False 可复现「只记录不施加」的未修正行为。
        lam = lambda_k(k) if self.config.apply_lambda_k else 1.0
        surface = sliding_surface(state_estimate, reference, lam=lam)

        context = NsmcContext(
            observation=observation,
            state_actual=state_actual,
            state_estimate=state_estimate,
            reference=reference,
            step_index=k,
        )
        # 问题 1 裁定：u_eq = B⁺·(x_ref − g(x_k, x̂_k, 0))（默认提供者即正式实现）
        equivalent_term = np.asarray(self.equivalent_control(context), dtype=float)
        if equivalent_term.shape != surface.shape:
            raise NSMCError(
                f"u_eq 形状必须为 {surface.shape}，实际为 {equivalent_term.shape}"
            )

        # 问题 14(a)：u_n 的形式由候选决定（默认 normalised_surface = 正式口径）
        request = StabilisingTermRequest(
            surface=surface,
            schur=self.schur,
            state_scale=self.config.state_scale,
            mapper=(
                (lambda vector: self.equivalent_control.map_state_to_control_space(context, vector))
                if self.law_candidate.requires_mapper
                else None
            ),
        )
        robust_term = np.asarray(self.law_candidate.stabilising_term(request), dtype=float)
        if robust_term.shape != surface.shape:
            raise NSMCError(
                f"u_n 形状必须为 {surface.shape}，实际为 {robust_term.shape}"
            )

        raw = saturate_direction_preserving(
            equivalent_term, robust_term, self.config.u_0, self.config.saturation_norm
        )
        self.negative_pwm_request_steps += int(np.any(raw < 0.0))
        # 保方向饱和律已保证控制量落在盒 [-u_0, u_0] 内（问题 23）；
        # 再经 clamp_with_u0 落到 PWM 硬边界，负占空比（T2 反向通道）截断为 0。
        command = ControllerCommand(
            duty_cycle_T1=self.limits.clamp_with_u0(raw[0]),
            duty_cycle_T2=self.limits.clamp_with_u0(raw[1] if raw.size > 1 else 0.0),
            note=self._build_note(k, lam, equivalent_term, robust_term, raw),
        ).validate(self.limits)

        # 鲁棒 profile 的显式一阶执行器平滑。凸组合仍在同一占空比可行域内，
        # 且 ``self._last_command`` 是上一拍已执行指令；因此闭环辨识器在外层
        # ClosedLoopController 中会消费与被控对象一致的平滑控制量。
        alpha = self._resolve_smoothing_alpha(observation)
        if self._last_command is not None and alpha < 1.0:
            command = ControllerCommand(
                duty_cycle_T1=alpha * command.duty_cycle_T1
                + (1.0 - alpha) * self._last_command.duty_cycle_T1,
                duty_cycle_T2=alpha * command.duty_cycle_T2
                + (1.0 - alpha) * self._last_command.duty_cycle_T2,
                note=command.note + f" smoothing_alpha={alpha:.6g}",
            ).validate(self.limits)

        self._step_index += 1
        self._last_command = command
        return command

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _resolve_smoothing_alpha(self, observation: ControllerObservation) -> float:
        """默认逐位保留固定平滑；显式研究子类可使用过去信息调度。"""
        return self.config.command_smoothing_alpha

    def _resolve_state_estimate(self, state_actual: np.ndarray) -> np.ndarray:
        """取状态估计值：优先 RHONN，未接入时退化为量测值。"""
        if self.rhonn is None:
            return state_actual
        estimate = self.rhonn.state_estimate
        if estimate is None:
            return state_actual
        return np.asarray(estimate, dtype=float)

    def _build_note(
        self,
        k: int,
        lam: float,
        equivalent_term: np.ndarray,
        robust_term: np.ndarray,
        saturated: np.ndarray,
    ) -> str:
        """把本拍的诊断量写进 ``note``，含 λ_k 的施加状态与控制律候选。

        ``|u_eq+u_n|`` 与 ``saturated`` **必须用与饱和律同一个范数口径**
        （问题 23）——否则 note 会在「是否饱和」上与控制器实际行为不一致，
        而 note 正是审计与回归的取证入口。
        """
        combined = equivalent_term + robust_term
        if self.config.saturation_norm == SATURATION_NORM_BOX:
            combined_norm = actuator_norm(combined)
            norm_label = "inf"
        else:
            combined_norm = float(np.linalg.norm(combined))
            norm_label = "l2"
        limited = combined_norm >= self.config.u_0
        applied = "施加" if self.config.apply_lambda_k else "未施加"
        # ``note`` 只承载审计文本，不参与控制计算。这里避免每拍调用
        # ``numpy.array2string``，该调用在长仿真中会反复进入 arrayprint
        # 格式化栈，控制量和诊断字段保持不变。
        if saturated.ndim == 1:
            saturated_text = "[" + " ".join(f"{float(value): .6f}" for value in saturated) + "]"
        else:  # pragma: no cover - 当前执行器为一维控制向量，保留通用诊断回退
            saturated_text = np.array2string(saturated, precision=6)
        return (
            f"nsmc k={k} lambda_k={lam:.6f}({applied}/方案问题"
            f"{SCHEME_ISSUE_LAMBDA_PLACEMENT}) "
            f"law_candidate={self.law_candidate.key} "
            f"u_eq_status={self.equivalent_control.data_status} "
            f"x_ref_status={self.reference_model.data_status} "
            f"|u_eq+u_n|_{norm_label}={combined_norm:.6f} u_0={self.config.u_0} "
            f"saturation_norm={self.config.saturation_norm} "
            f"saturated={limited} u={saturated_text}"
        )
