"""跟踪口径：baseline 与主算法共用的一套定义（方案 §4.2.1.3（2））。

本模块存在的唯一理由，是把**方案级的跟踪口径**从实现层里拎出来，
让 baseline 控制器与主算法（NSMC）**共用同一套定义**，避免口径漂移——
这是 `simulation/scenario_runner.py::default_baseline_cases` 明确声明的纪律。

本模块**不依赖包内任何其他模块**，因此 `simulation/` 与 `control/` 两侧
都可以安全导入，不会形成循环依赖。

正式口径（编写人裁定版，2026-09-25）::

    s(x_k, k) = λ_k · ( x_k − x_{ref,k} )      滑模面（含时变系数，问题 5 裁定）
    λ_k       = 0.9 + 0.1·e^(-0.1k)            时变滑模面系数，k 为采样步序号
    u_0       = 0.9                            PWM 占空比上限

    x_{ref,k} = ( v_ref, i_L,ref )             参考状态（问题 13 裁定）
        v_ref     = clip( v_out , V_out,min , V_out,max )
        P_abs     = min( P_req , P_avail , P_conv )
        i_L,ref   = clip( P_abs / v_out , 0 , i_L,max )

--------------------------------------------------------------------------
编写人裁定（2026-09-25）：本模块此前登记的三处「显式待填点」已全部落地
--------------------------------------------------------------------------

本模块原先登记问题 5 / 13（以及 14 / 15 / 16）为「待编写人确认」。
方案编写人已授权**由实现方以编写人身份直接裁定**，因此本模块不再保留
「无静默默认值」的哨兵姿态：每一条都给出唯一正式口径，并在下文中写清
**推导依据、被否决的读法、以及被否决的理由**。

**问题 5（原「中」）—— λ_k 的作用位置**

原方案把 ``λ_k = 0.9 + 0.1·e^(-0.1k)`` 声明为「时变滑模面系数」，
却未出现在滑模面、``u_n`` 或控制律 (34)(35) 的任何一处；且正文注
「``k`` 为采样步长」，与「时变」自相矛盾（若 ``k`` 是常数步长，``λ_k`` 即常数）。

裁定：

* ``k`` 为**采样步序号**（``k = 0, 1, 2, …``），非步长；正文注解为笔误。
* ``λ_k`` **乘入滑模面**，即 ``s(x_k, k) = λ_k·(x_k − x_{ref,k})``。
  依据：方案对它的命名就是「滑模面系数」，乘入滑模面是唯一与命名自洽的位置；
  且 ``λ_0 = 1.0``（初期满增益、快速跟踪）→ ``λ_k ↓ 0.9``（后期降增益、精准维稳），
  与正文「初期快速跟踪、后期精准维稳」的表述方向一致。
* baseline 与主算法**共用**这一口径（都走 :func:`sliding_surface`），
  避免出现「主算法带 λ_k、baseline 不带」的口径漂移。

**问题 13（原「高」）—— 参考状态 x_{ref,k} 的构造式**

原方案只说「``x_{ref,k}`` 由**列车制动曲线与储能系统 SOC 共同确定**」，未给公式。
``x_ref`` 是所有跟踪型控制器的唯一外部指令来源，直接决定滑模面。

裁定（正式构造式，见 :class:`RegenerativeReferenceState`）::

    v_ref   = clip( v_out , V_out,min , V_out,max )          ① 电压分量：窗口内就地保持
    P_req   = 制动曲线给出的再生功率请求（观测量 requested_regen_power_w）
    P_avail = SOC 与变流器包络共同允许的可用功率（观测量 available_regen_power_w）
    P_conv  = v_out · i_L,max · η                             ② 变流器/电感电流容量上限
    P_abs   = min( P_req , P_avail , P_conv )                 ③ 可吸收功率
    i_L,ref = clip( P_abs / v_out , 0 , i_L,max )             ④ 电流分量：电感电流参考

.. warning::
   **③ 的三个项名与代码实际接线的关系（问题 34 修正，2026-09-26）**——
   上面这行是**方案原文**的写法，其项名容易被读成「三条互相独立的约束」。
   实际接线（:meth:`RegenerativeReferenceState.absorbable_power_terms`）是：

   =========== ==================================================================== ============
   项          实际内容（以代码为准）                                                  侧别
   =========== ==================================================================== ============
   ``P_req``   ``observation.requested_regen_power_w`` = ``motor_result.electrical_power_w``， 直流母线侧
               **已经是「过包络、过效率」之后的电机电功率**——不是制动曲线的原始请求       （电功率）
   ``P_avail`` ``observation.available_regen_power_w`` = ``envelope_power_limit_w ×   轮端（机械）
               dc_link_derating``，即 ``convert_wheel_regen`` 的 ``effective_power_limit``，
               **只含电机包络，不含 SOC、不含变流器容量**
   ``P_conv``  ``v_out · i_L,max · η``，变流器/电感电流容量                                直流母线侧
   =========== ==================================================================== ============

   三点必须写清，否则读的人会误以为 ③ 在「三条独立约束」下取小：

   1. **``P_avail`` 在 ``min()`` 中恒不可能成为紧约束**。``P_req`` 与 ``P_avail``
      来自**同一次** ``convert_wheel_regen`` 调用，且 ``P_req = wheel_power·η``
      而 ``P_avail = effective_power_limit ≥ wheel_power``，因此

          ``P_avail / P_req ≥ 1/η ≥ 1``（``η ≤ 1``；实测 ``η_max = 0.9``）

      实测 9 个官方场景 ``P_avail < P_req`` 的拍数**恒为 0**，
      ``min(P_avail/P_req) = 1.1111 = 1/0.9 = 1/η_max``。
      它与 ``P_conv`` 一样，是「当前量级下不构成约束、列出以保物理完整」的项。
   2. **``P_avail`` 的侧别与 ``P_req``/``P_conv`` 不同**（轮端机械 vs 直流母线电）。
      这不是问题 33 那样的「跨链错配」，因为它是**代数支配**的（见第 1 点），
      永远进不了 ``min()`` 的结果；但它确实是**同一个 ``min()`` 里混了两种侧别**。
   3. **承载 SOC 约束的不是 ``P_avail``，而是问题 21 新增的 ``max_charge_power_w`` 项**
      （:attr:`RegenerativeReferenceState.storage_max_charge_power_w`）。
      ``P_avail`` 与 SOC 无关——``convert_wheel_regen`` 的函数签名里
      **没有任何 storage / SOC 参数**。

   🟥 2026-10-07 更正：上述固定额定功率项本身也不含 SOC 余量，旧“承载
   SOC 约束”的广泛表述不成立。生产路径现把 ``storage_charge_power_limit_w``
   （同拍储能/BMS 许可）与额定充电功率取小，再放入第四约束项；未提供
   许可的历史调用方显式保持 ``None``，不能据此声称具备 SOC 退出保护。

   这**不是**行为缺陷：把 ``P_req`` 取成「已过包络的电功率」与方案原文
   「原始请求 × 独立包络约束」在数学上**恒等**——
   ``min(raw_req_wheel, envelope)·η ≡ min(raw_req_wheel·η, envelope·η)``——
   故交付数字零影响。修的是**文档与项名对不上代码**这件事本身。

推导 ④（``i_L,ref = P_abs / v_out``）：buck 稳态有 ``v_out = d1·v_in``；
输入侧电流 ``i_src = P_in/v_in = P_abs/(η·v_in)``；稳态电荷平衡 ``d1·i_L = η·i_src``。
三式联立得

    i_L = η·i_src / d1 = (P_abs / v_in) / (v_out / v_in) = P_abs / v_out

**效率 η 恰好相消**——这正是 ④ 不含 η 的原因，也是它不需要任何经验标定系数的原因。

对 ① 的说明：电压分量在窗口内**就地保持**，即 ``s[0] ≡ 0``、电压通道不产生跟踪误差；
只有 ``v_out`` 越出储能侧电压窗口时才回拉。这不是「浪费一个通道」，而是
**窗口保护**职责——变流器的主功率目标由电流通道承担。这也正面回答了问题 16：
正因为电压分量只做保护、功率目标全在电流通道，电流分量才**必须是独立状态量**
（``i_L``），不能是与 ``v_out`` 代数相关的 ``i_out``。

**被否决的读法**：原实现用 ``absorption_fraction = 0.1`` 这个**经验标定常数**
把「变流器容量相对再生功率的占比」写死。该读法被否决，理由：
① 它不是方案原文，也不是设计选型结果，只是为了让对比表有分辨力而反推出来的数；
② 它把两条**真实**约束（储能可吸收功率上限 ``max_charge_power_w``、变流器电流容量
``i_L,max``）混成一个无量纲系数，掩盖了真正的物理边界
（🟥 原文此处写作「SOC 可用功率 ``P_avail``、变流器电流容量 ``i_L,max``」，
问题 34 修正：``P_avail`` 是**轮端电机包络**、与 SOC 无关，见上方 warning）；
③ 正式口径用 ③+④ 直接给出这两个约束，不需要任何自由参数。

**问题 16（原「阻塞」，本模块新发现）—— 状态向量冗余**

原方案的 ``u_eq`` 要在 2 维状态空间把 ``x = (v_out, i_out)`` 驱到 ``x_ref``，
但储能侧这两个分量**不独立**——输出电流由储能母线代数决定::

    i_out = (v_out − v_oc) / R_int        ⟹  ∂i_out/∂u = (1/R_int)·∂v_out/∂u

于是对象的 ``B = ∂(v_out, i_out)/∂u`` **恒为秩 1**。对变流器单步映射做数值微分实测
（两个工作点）::

    标称   ∂v_out/∂d1 = +0.7254   ∂v_out/∂d2 = −0.2503   det = 0.0  rank = 1
    大电流 ∂v_out/∂d1 = +0.7252   ∂v_out/∂d2 = −3.1757   det = 0.0  rank = 1
    两行的比值恒为 1/R_int = 20.000（与 R_int = 0.05 Ω 一致）

后果：``B⁺`` 只能把残差投影到 1 维行空间上，``u_eq`` 最小范数解**无法独立跟踪
两个分量**；方案要求的 ``v_out`` 与 ``i_out`` 双目标跟踪在给定状态定义下不可达。

裁定：状态向量由 ``(v_out, i_out)`` 改为 ``(v_out, i_L)``。
``i_L`` 是变流器 :class:`~regenerative_braking.dynamics.dc_dc_converter.DCConverterState`
的**原生独立状态量**，与 ``v_out`` 无代数约束，于是 ``B = ∂(v_out, i_L)/∂u``
不再结构性奇异（数值微分实测 ``det B ≠ 0``、``rank = 2``）。
相应地，参考量第二分量的语义由「输出电流参考」改为**电感电流参考**（见 ④）。

**问题 15（原「阻塞」，本模块新发现）—— 控制通道 ``B = ∂g/∂u`` 不可辨识**

``u`` 原先只出现在**固定权重**项 ``ω̄`` 里，于是 ``∂x̂/∂u`` 结构性不含可调权重，
在线辨识无法校正它（实测 ``max|Δω| = 130.4``、``max|Δ预测| = 168789.9``，
而 ``max|ΔB| = 0.0``），``B`` 的符号纯随机，形成「``u ≡ 0`` ⟹ 通道无激励 ⟹ ``B`` 永远不可辨识」的自锁。

裁定：``u`` 同时进入**并联（可调）与串联（可调）两段权重**，使 ``∂x̂/∂u``
结构性含可调权重（文献依据：Neurocomputing 322 (2018) 13–21；MDPI Appl. Sci.
11(3):1154 (2021) §3.1 —— RHONN 全部突触权重由 EKF 在线整定），
``n_tunable_weights`` 由 8 增至 20；控制通道**符号**由物理先验
``sign(B) = [[+,−],[+,+]]`` 经参数投影施加。详见
:mod:`regenerative_braking.identification.rhonn`。

--------------------------------------------------------------------------
问题 30（原「高」，本模块新发现）—— x_ref 的装配路径多来源
--------------------------------------------------------------------------

``RegenerativeReferenceState`` 有三个可达装配口径，走哪一条取决于调用方
「恰好传了哪些可选参数」，而三者之间**没有任何一致性校验**：

==============================  ============================================
装配口径                         触发条件
==============================  ============================================
``storage_matched``（问题 21）   同时给出变流器与储能参数
``legacy_voltage_hold``          只给变流器参数
``defaults``                     两个都不给（用本模块兜底常量）
==============================  ============================================

后果（实测，``dt = 2e-4``）：

* ``simulation/scenario_runner.py::default_baseline_cases``（阶段 1/2 入口）
  走 ``legacy_voltage_hold``，而 ``validation/baselines.py::_reference``
  （阶段 9 套件）走 ``storage_matched`` ⟹ ``pi`` / ``pid`` / ``traditional_smc``
  三个标签在两条入口下**不是同一个控制器**：``pid`` 回收能量差 ``0.28%``、
  ``i_L`` 峰值 ``3118 → 1821 A``、``v_out`` 峰值 ``1731 → 1149 V``。
* ``tools/export_cross_project.py``（阶段 11 交付物）走 ``defaults``
  ⟹ 导出的主算法能量桶来自一个用**硬编码默认参考量**装配的控制器。

裁定：``x_ref`` **只允许一条生产装配路径** —— :func:`build_reference_state`
（两个参数都必需，缺失即报错）。另两条降级为**显式 legacy / defaults**，
并通过 :attr:`RegenerativeReferenceState.assembly_path` 与
``ClosedLoopController.audit()`` 暴露给下游审计。

--------------------------------------------------------------------------
口径状态标记
--------------------------------------------------------------------------

本模块用三个常量标注「这处口径的可信度来源」：

============================  ================================================
常量                          含义
============================  ================================================
``SCHEME_AUTHORED``           方案编写人已裁定的**正式口径**（本文件下半部分）
``FIXED_BY_IMPLEMENTATION``   实现层已落地，但方案正文尚未回填
``REJECTED_SCHEME_READING``   方案原文的该读法已被**明确否决**，仅供回归复现
``PENDING_SCHEME_CONFIRMATION`` 历史标记，保留仅为兼容既有审计链路
============================  ================================================

注意 ``PENDING_SCHEME_CONFIRMATION`` 已**不再用于任何默认路径**：
所有原先带该标记的默认实现都已升级为 ``SCHEME_AUTHORED``，
该常量只在下游审计字段（``manifest.json``）中作为「历史遗留项」保留。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Sequence, Tuple, runtime_checkable

import math

import numpy as np


class TrackingError(ValueError):
    """跟踪口径的配置或输入不合法。"""


class PendingSchemeConfirmationError(TrackingError):
    """使用了已被正式口径取代的历史哨兵实现。

    本异常在 2026-09-25 编写人裁定之前用于「方案缺口不允许静默代拟」的纪律。
    裁定之后所有默认路径都已改为正式口径，本异常**只在显式注入
    :class:`PendingReferenceState` 这类历史哨兵时**才会抛出，
    用途是让「未修正」的历史行为仍可复现、可回归对比。
    """


# ---------------------------------------------------------------------------
# 口径状态标记
# ---------------------------------------------------------------------------

#: 方案编写人已裁定的**正式口径**（2026-09-25 编写人授权自行修改）。
SCHEME_AUTHORED = "scheme_authored"

#: 实现层已按编写人授权落地，但方案正文尚未回填。
FIXED_BY_IMPLEMENTATION = "fixed_by_implementation"

#: 方案原文的该读法已被编写人**明确否决**，保留仅为可复现的回归对比。
REJECTED_SCHEME_READING = "rejected_scheme_reading"

#: 历史标记：仍待编写人确认。已不用于任何默认路径，仅兼容既有审计链路。
PENDING_SCHEME_CONFIRMATION = "PENDING_SCHEME_CONFIRMATION"


#: 方案问题编号（与 `docs/technical_scheme_code_mapping.md` §A.3 对齐）
SCHEME_ISSUE_EQUIVALENT_CONTROL_MISSING = 1
SCHEME_ISSUE_LAMBDA_PLACEMENT = 5
SCHEME_ISSUE_REFERENCE_STATE_UNSPECIFIED = 13  # x_ref 构造式未给出（本模块新发现）
SCHEME_ISSUE_CONTROL_LAW_DIMENSION = 14  # (34)(35) 量纲不一致（本模块新发现）
SCHEME_ISSUE_CONTROL_CHANNEL_UNIDENTIFIABLE = 15  # B = ∂g/∂u 与可调权重无关（本模块新发现）
SCHEME_ISSUE_STATE_VECTOR_REDUNDANT = 16  # (v_out, i_out) 代数相关 ⟹ B 恒奇异（本模块新发现）
SCHEME_ISSUE_REFERENCE_VOLTAGE_HOLD = 21  # x_ref 的电压分量「就地保持」使 d2 被迫旁路（本模块新发现）

#: 方案问题编号 **30**（实现期自行发现，非方案正文问题）：``x_ref`` 的**装配路径多来源**。
#:
#: ``RegenerativeReferenceState`` 有三个可达的装配口径，而它们**没有任何一致性校验**，
#: 走哪一条完全取决于调用方「恰好传了哪些可选参数」：
#:
#: ==================================  ============================================
#: 装配口径                              触发条件
#: ==================================  ============================================
#: ``storage_matched``（问题 21 正式）   同时给出变流器与储能参数
#: ``legacy_voltage_hold``（21 修正前）  只给变流器参数
#: ``defaults``（纯模块常量）            两个都不给
#: ==================================  ============================================
#:
#: 实测后果（``dt = 2e-4``，族 1 同参数短剖面）：
#:
#: * ``simulation/scenario_runner.py::default_baseline_cases`` 走 ``legacy_voltage_hold``，
#:   而 ``validation/baselines.py::_reference`` 走 ``storage_matched``——
#:   于是 ``pi`` / ``pid`` / ``traditional_smc`` 三个标签在 ``run_project.py``
#:   （阶段 1/2 入口）与 ``tools/run_validation_suite.py``（阶段 9 套件）下
#:   **不是同一个控制器**：``pid`` 回收能量差 ``0.28%``、``i_L`` 峰值差 ``1297 A``
#:   （``3118 → 1821 A``）、``v_out`` 峰值差 ``582 V``。
#: * ``tools/export_cross_project.py``（阶段 11 交付物）走 ``defaults``，
#:   即主算法能量桶来自一个用**硬编码默认参考量**装配的控制器。
#:
#: 修复：``x_ref`` 只允许一条生产装配路径（:func:`build_reference_state`），
#: 另两条降级为显式 legacy / defaults 并在 :attr:`RegenerativeReferenceState.assembly_path`
#: 与 ``ClosedLoopController.audit()`` 中暴露，杜绝「传参不同 ⟹ 控制器不同」。
SCHEME_ISSUE_REFERENCE_ASSEMBLY_SPLIT = 30

#: 方案问题编号 **33**（实现期自行发现）：**``tracking`` 指标组的「参考功率」取错对象**。
#:
#: 控制器的参考功率是 ③ 的**储能侧可吸收功率**
#: ``P_abs = min(P_req, P_avail, P_conv, max_charge_power_w)``，
#: 而 ``SimulationResult.to_scenario_metrics()`` 给 ``build_scenario_metrics`` 的
#: ``reference_power`` 实参是 ``arrays.regen_wheel_power_w``——**轮端**可用再生功率。
#: 两者跨「电机 → 变流器 → 储能」整条链，比值 ``max|act| / max|ref|`` 实测
#: 仅 ``0.069``（官方 s1；跨场景 ``0.066 ~ 0.092``），于是「误差」被结构性缺口主导，
#: 三项跟踪指标退化：
#:
#: * ``tracking_rmse`` 全部控制器 ``19.30 ~ 20.52 MW``，
#:   而回收 ``0.000 kWh`` 的 ``uncontrolled_zero_duty`` 只比主算法差 ``5.9%``
#:   ⟹ ``comparison.py`` 中 ``prefer="lower"`` 的这项对比**丧失分辨力**；
#: * ``overshoot`` **恒 ``0.0000``**（``tracking_metrics`` 用 max-to-max 口径
#:   ``max(0, max(act) − max(ref)) / mean|ref|``；修复前 ``max(ref)`` 是轮端
#:   ``28.8 MW`` 而 ``max(act)`` 被储能硬上限截在 ``2.0 MW`` ⟹ 分子恒为 0）；
#: * ``settling_time`` **恒 ``None``**（稳态带 ``0.05·mean|ref| ≈ 1.06 MW``，
#:   而 ``|error| ≈ 19 MW`` 恒超出，永远进不了带内）。
#:
#: 这与问题 25（``duty_saturation_ratio`` 恒报 ``0.0000`` 而 ``96.48%`` 的拍贴轨）
#: 是同一形态：**指标说了假话**。
#:
#: 修复：把 ③ 抽成公开方法 :meth:`RegenerativeReferenceState.absorbable_power`
#: （``__call__`` 调它，**不新增第二处公式**），由仿真器逐步记录成
#: ``SimulationArrays.reference_power_w``，指标层的 ``reference_power`` 改取该列。
#: 这样参考量与实测量同处储能侧，``tracking_*`` 才真正度量「控制器跟踪得怎样」。
#:
#: 之所以能让**所有**控制器共用同一个参考：``P_abs`` 只依赖 ``observation`` 与
#: 装配时给定的硬件参数，**与「谁在控制」无关**——它是**被控对象属性**。
SCHEME_ISSUE_TRACKING_REFERENCE_CROSS_CHAIN = 33

#: 方案问题编号 **34**（实现期自行发现）：**③ 的 ``P_avail`` 是结构性死约束，
#: 且文档对 ``P_req`` / ``P_avail`` 的语义描述与代码接线不符**。
#:
#: 形态与问题 25 / 33 同族（**公式说了假话**），但**零数值影响**——这既是它长期
#: 存活的原因，也是它值得登记的理由：
#:
#: * 模块 docstring 的 ③ 把三项写成「三条独立约束」，并称 ``P_avail`` 是
#:   「SOC 与变流器包络共同允许的可用功率」。**实际** ``P_avail`` =
#:   ``observation.available_regen_power_w`` = ``envelope_power_limit_w × dc_link_derating``
#:   ——只含**电机轮端包络**，既不含 SOC、也不含变流器容量
#:   （``convert_wheel_regen`` 的函数签名里没有任何 storage / SOC 参数）。
#:   SOC 约束实际由问题 21 新增的 ``max_charge_power_w`` 项承担；
#:   变流器容量由 ``P_conv`` 项承担。
#: * 文档称 ``P_req`` 是「制动曲线给出的再生功率请求」。**实际**
#:   ``requested_regen_power_w = motor_result.electrical_power_w`` 已经是
#:   **过包络、过效率**之后的直流母线侧电功率。
#: * 由此 ``P_avail`` 与 ``P_req`` **同源**（同一次 ``convert_wheel_regen``），
#:   且 ``P_avail / P_req ≥ 1/η ≥ 1`` ⟹ ``P_avail`` 在 ``min()`` 中
#:   **恒不可能成为紧约束**。实测 9 个官方场景 ``P_avail < P_req`` 的拍数恒为 ``0``，
#:   ``min(P_avail/P_req) = 1.1111 = 1/0.9 = 1/η_max``。
#: * **同一形态还有第二处**：``validation/baselines.py::IdealUpperBoundController``
#:   的 ``target = min(requested_regen_power_w, available_regen_power_w)``，
#:   注释称第二项是「变流器可用」——同样名不符实，且同样恒被 ``requested`` 支配
#:   （``min(requested, available) ≡ requested``）。上界参照因此**完全不含变流器容量**。
#:
#: 之所以**零影响**：``P_req`` 取「已过包络的电功率」与方案原文「原始请求 ×
#: 独立包络约束」在数学上**恒等**——``min(raw_req_wheel, envelope)·η
#: ≡ min(raw_req_wheel·η, envelope·η)``。故不修改行为，只修**文档与项名**，
#: 并加回归守卫钉住「``P_avail`` 不可能成为紧约束」这一结构性事实。
#:
#: 修复：把四项约束抽成唯一入口 :meth:`RegenerativeReferenceState.absorbable_power_terms`
#: （探针/测试不再手抄 ``P_conv`` 公式，改从该入口读真实项值），
#: 并在 docstring 中按上表逐项写清「实际内容 / 侧别」。
SCHEME_ISSUE_AVAILABLE_POWER_SEMANTICS = 34

#: 装配口径标识：问题 21 裁定的正式口径（电压分量「储能吸收匹配」+ 储能功率上限）。
ASSEMBLY_STORAGE_MATCHED = "storage_matched"
#: 装配口径标识：问题 21 修正**前**的历史口径（电压分量「窗口内就地保持」）。
ASSEMBLY_LEGACY_VOLTAGE_HOLD = "legacy_voltage_hold"
#: 装配口径标识：未给任何被控对象参数，纯用本模块的兜底常量。
ASSEMBLY_DEFAULTS = "defaults"

#: 允许的装配口径集合（``assembly_path`` 的取值域）
ASSEMBLY_PATHS: Tuple[str, ...] = (
    ASSEMBLY_STORAGE_MATCHED,
    ASSEMBLY_LEGACY_VOLTAGE_HOLD,
    ASSEMBLY_DEFAULTS,
)

#: 方案原文给出的 PWM 占空比上限 u_0
SCHEME_U0 = 0.9

#: 方案原文给出的 Schur 矩阵特征值范围
SCHEME_SCHUR_EIGENVALUE_RANGE = (0.6, 0.8)

#: 方案原文给出的时变滑模面系数（问题 5 裁定：乘入滑模面）
SCHEME_LAMBDA_DECAY = 0.1
SCHEME_LAMBDA_FLOOR = 0.9


# ---------------------------------------------------------------------------
# 方案已给全的部分 + 问题 5 裁定：λ_k 乘入滑模面
# ---------------------------------------------------------------------------


def lambda_k(k: int) -> float:
    """时变滑模面系数 ``λ_k = 0.9 + 0.1·e^(-0.1k)``（方案原文）。

    ``k`` 取**采样步序号**（``k = 0, 1, 2, …``）。方案正文写作「``k`` 为采样步长」，
    与「时变」自相矛盾——若 ``k`` 是常数步长 ``dt``，``λ_k`` 就是常数。
    编写人裁定（问题 5）：**``k`` 为采样步序号**，正文注解为笔误。

    ``λ_0 = 1.0``，``k → ∞`` 时趋于 ``0.9``，对应正文「初期快速跟踪、后期精准维稳」。

    本系数由 :func:`sliding_surface` 乘入滑模面，主算法与 baseline 共用。
    """
    if not isinstance(k, (int, np.integer)) or k < 0:
        raise TrackingError(f"k 必须为非负整数采样步序号，实际为 {k!r}")
    return SCHEME_LAMBDA_FLOOR + SCHEME_LAMBDA_DECAY * float(np.exp(-SCHEME_LAMBDA_DECAY * int(k)))


def sliding_surface(
    state_estimate: Sequence[float],
    reference: Sequence[float],
    lam: float = 1.0,
) -> np.ndarray:
    """滑模面 / 跟踪误差 ``s(x_k, k) = λ_k·(x_k − x_{ref,k})``。

    Args:
        state_estimate: 状态估计 ``x_k``（RHONN 接入时为其输出，否则为量测值）。
        reference: 参考状态 ``x_{ref,k}``（见 :class:`RegenerativeReferenceState`）。
        lam: 时变滑模面系数 ``λ_k``，默认 ``1.0``（即不含时变系数）。

            调用方**应显式传入** :func:`lambda_k` 的当前值；``1.0`` 的默认值
            只服务于「需要纯跟踪误差 ``x_k − x_ref``」的场合（例如诊断脚本里
            单独观察误差本身），不作为控制路径的默认口径。

    NSMC 用它构造稳定项 ``u_n``；传统 SMC baseline 用它构造切换项 ``sign(s)``；
    PI/PID baseline 用它构造标量跟踪误差。三者共用本函数，正是为了口径一致——
    问题 5 裁定后，``λ_k`` 的乘入也一并共用，不会出现「主算法带、baseline 不带」。
    """
    state = np.asarray(state_estimate, dtype=float)
    target = np.asarray(reference, dtype=float)
    if state.shape != target.shape:
        raise TrackingError(f"状态与参考量形状必须一致，实际为 {state.shape} 与 {target.shape}")
    if state.ndim != 1:
        raise TrackingError("状态与参考量必须是一维向量")
    if not (np.all(np.isfinite(state)) and np.all(np.isfinite(target))):
        raise TrackingError("状态与参考量必须全部为有限值")
    if not np.isfinite(lam):
        raise TrackingError(f"λ_k 必须为有限值，实际为 {lam!r}")
    return float(lam) * (state - target)


# ---------------------------------------------------------------------------
# 问题 13 裁定：参考状态 x_{ref,k} 的正式构造式
# ---------------------------------------------------------------------------


@runtime_checkable
class ReferenceStateProvider(Protocol):
    """参考状态提供者：``x_{ref,k}`` 的构造方式（方案问题 13，已裁定）。

    入参是控制器的观测量（:class:`~regenerative_braking.simulation.controllers.ControllerObservation`），
    这里只按属性名鸭子类型使用，不导入该类，以免形成循环依赖。
    """

    data_status: str

    def __call__(self, observation) -> np.ndarray:  # pragma: no cover
        ...


#: 储能侧电压窗口与电感电流上限的**兜底默认值**（与 `data/single_train/dc_dc_parameters.json`
#: 当前值一致）。正常装配路径应经 :meth:`RegenerativeReferenceState.from_converter_params`
#: 从同一个参数对象取，避免控制器与被控对象各用一套数。
DEFAULT_VOLTAGE_WINDOW_V = (600.0, 1500.0)
DEFAULT_INDUCTOR_CURRENT_LIMIT_A = 3000.0

# 第 4 项实验：参数装配与参考策略分开审计。反馈策略由电流误差推导，
# 不是技术方案原文，也不读取扰动后的真实内阻。
REFERENCE_STORAGE_MATCHED = "storage_matched"
REFERENCE_CURRENT_FEEDBACK = "storage_current_feedback"
REFERENCE_GUARDED_CURRENT_FEEDBACK = "storage_guarded_current_feedback"
REFERENCE_STRATEGIES = (REFERENCE_STORAGE_MATCHED, REFERENCE_CURRENT_FEEDBACK, REFERENCE_GUARDED_CURRENT_FEEDBACK)
# 声明的研究内阻范围上界，与既有 R<=2.5 倍扰动范围一致；不是硬件规格。
DEFAULT_FEEDBACK_RESISTANCE_UPPER_FACTOR = 2.5


class RegenerativeReferenceState:
    """``x_{ref,k}`` 的**正式构造式**（方案问题 13 裁定，``data_status = SCHEME_AUTHORED``）。

    构造式（推导见模块 docstring）::

        P_conv  = v_out · i_L,max · η                             ② 变流器/电感电流容量
        P_abs   = min( P_req , P_avail , P_conv , P_storage )      ③ 可吸收功率
        v_ref   = clip( (V_oc + √(V_oc² + 4·P_abs·R_int)) / 2 ,
                        V_out,min , V_out,max )                    ① 电压分量：储能吸收匹配
        i_L,ref = clip( P_abs / v_ref , 0 , i_L,max )             ④ 电流分量：电感电流参考

    其中 ``P_req`` 来自**列车制动曲线**（观测量 ``requested_regen_power_w``），
    ``P_avail`` 来自**电机侧包络**（观测量 ``available_regen_power_w``），
    ``P_storage`` 是**储能最大充电功率**（``storage_parameters.json`` 的
    ``max_charge_power_w``，本项目中是 **real** 数据）——三者加上变流器容量
    共同确定可吸收功率，正是方案正文「由列车制动曲线与储能系统 SOC 共同确定」的落地。

    .. note::
       **问题 21 裁定（2026-09-25）—— 电压分量改「储能吸收匹配」，③ 补上储能功率上限**。

       ① 原先取「窗口内就地保持」（``v_ref = clip(v_out, …)``）。这在物理上不可实现：
       储能侧吸收电流受内阻限制 ``i_sink = (v_out − V_oc)/R_int``，而稳态必须满足
       ``(1−d2)·i_L = i_sink``。把 ``v_out`` 钉在当前值就钉住了 ``i_sink``，
       于是 ``d2`` 只能旁路掉多余的 ``i_L``。实测 ``s1_flat_braking``::

          v_out = 1110 V ⇒ i_sink = 500 A，而 i_L,ref = 2910 A
          ⇒ d2 ≈ 0.84（旁路 84%），回收能量只有 1.23 kWh（基线 4.44）

       ③ 原先**没有**储能功率上限，而 ``available_regen_power_w`` 是**电机侧**包络。
       实测 ``P_abs = 3.23 MW`` 而储能 ``max_charge_power_w = 2 MW``
       ⇒ ``i_L`` 峰值冲到 3443 A（超额定 15%）、``d2`` 仍需旁路 40%。

       修正后：``P_abs`` 补上 ``P_storage``，``v_ref`` 由
       ``v_out·(v_out − V_oc) = P_abs·R_int`` 反解。效果（s1/s2，全分辨率）::

          i_L 峰值   3443 / 3493 A  →  2246 / 2278 A   （回到额定内）🟥 修订前
          d2   p50   0.40           →  0.10            （回到方案 modes.regen_charge 的「T2 置 0」）🟥 修订前
          v_out 峰值 1157 / 1166 V  →  1133 / 1134 V   （窗口内）🟥 修订前
          回收能量   4.44 / 3.17    →  4.17 / 2.97 kWh （-6.2%，因精确跟踪内阻段而非顶到功率上限）

       🟥 上面「修正后」列是**问题 22 修订前**（旧 bang-bang 支路）的读数。
       2026-09-26 问题 22 落地（问题 20 支路改盒约束最小二乘）后复测为
       ``i_L`` 峰值 ``2233 / 2232 A``、``d2`` p50 ``0.0608``、``v_out`` 峰值
       ``1133 / 1133 V``、回收能量 ``4.1674 / 2.9711 kWh``。
       （原记 ``d2`` p50 = ``0.10`` 与算法文档 §5.9.4 的 ``0.0608`` 本就不一致，
       本次复测支持 ``0.0608``。）

       🟥 **再修订（问题 23，同日）**：饱和律范数口径由 2 球统一到**盒**（∞ 范数）后，
       上述读数再变一次：``i_L`` 峰值 ``2255 / 2255 A``、回收能量
       ``4.1676 / 2.9713 kWh``（4 位小数），``v_out`` 峰值 ``1133 / 1133 V`` 与
       ``d2`` p50 ``0.0608`` 不变。见算法文档 §5.11。

       ``V_oc`` / ``R_int`` 在本项目是 **placeholder**，故本口径的幅值依赖它们；
       稳健的只有结构（``d2 → 0``、``i_L → i_sink``）。见
       ``docs/regenerative_braking_algorithm.md`` §5.9。

    第二分量是**电感电流参考**，与状态向量 ``x = (v_out, i_L)`` 同坐标（问题 16 裁定）。
    问题 21 修正后电压分量不再「就地保持」，因此滑模面两个分量通常都非零：
    ``s = λ_k·(v_out − v_ref, i_L − i_L,ref)``，控制目标是「按可吸收功率回收，
    同时把储能侧电压维持在能吸收该功率的水平」。

    .. note::
       ``P_conv`` 在本项目的量级下**不构成约束**（``1100 V × 3000 A ≈ 3.3 MW``
       远大于制动曲线请求的再生功率），列出它是为了让 ③ 的物理完整性不依赖量级巧合：
       若将来更换更大功率的牵引系统，该约束会自动接管。

    .. note::
       效率 η 在 ④ 中**恰好相消**（推导见模块 docstring），因此本类不引入 η 参数。

    provenance: **derived** —— ①②④ 由变流器平均模型与储能「开路电压 + 内阻」
    二参数模型的稳态关系、以及 ``dc_dc_parameters.json`` / ``storage_parameters.json``
    的额定量推导，不是实测标定值，也不是方案原文。其中储能电压与内阻当前是
    **placeholder**，故本口径的**幅值**依赖 placeholder，只有**结构**稳健。
    """

    data_status = SCHEME_AUTHORED

    def __init__(
        self,
        *,
        voltage_window_v: Optional[Tuple[float, float]] = None,
        inductor_current_limit_a: float = DEFAULT_INDUCTOR_CURRENT_LIMIT_A,
        efficiency: float = 1.0,
        storage_open_circuit_voltage_v: Optional[float] = None,
        storage_internal_resistance_ohm: Optional[float] = None,
        storage_max_charge_power_w: Optional[float] = None,
        assembly: str = ASSEMBLY_DEFAULTS,
        strategy: str = REFERENCE_STORAGE_MATCHED,
        feedback_resistance_upper_factor: Optional[float] = None,
    ) -> None:
        if strategy not in REFERENCE_STRATEGIES:
            raise TrackingError(f"未知参考策略 {strategy!r}，允许：{REFERENCE_STRATEGIES}")
        if strategy in (REFERENCE_CURRENT_FEEDBACK, REFERENCE_GUARDED_CURRENT_FEEDBACK) and (
            storage_open_circuit_voltage_v is None or storage_internal_resistance_ohm is None
        ):
            raise TrackingError("储能电流反馈参考要求完整储能电压与内阻参数")
        self.strategy = strategy
        if strategy == REFERENCE_GUARDED_CURRENT_FEEDBACK:
            factor = DEFAULT_FEEDBACK_RESISTANCE_UPPER_FACTOR if feedback_resistance_upper_factor is None else feedback_resistance_upper_factor
            if isinstance(factor, (bool, np.bool_)) or not np.isfinite(factor) or factor < 1.0:
                raise TrackingError("反馈内阻范围上界必须为有限数且>=1，不能为布尔值")
            self.feedback_resistance_upper_factor: Optional[float] = float(factor)
            self.feedback_envelope_status: Optional[str] = "assumed"
        else:
            if feedback_resistance_upper_factor is not None:
                raise TrackingError("反馈内阻范围仅能用于保护反馈策略，不能静默忽略")
            self.feedback_resistance_upper_factor = None
            self.feedback_envelope_status = None
        if strategy in (REFERENCE_CURRENT_FEEDBACK, REFERENCE_GUARDED_CURRENT_FEEDBACK):
            self.data_status = "derived"
        if assembly not in ASSEMBLY_PATHS:
            raise TrackingError(
                f"未知的装配口径 {assembly!r}，允许：{', '.join(ASSEMBLY_PATHS)}"
            )
        self._assembly_path = assembly
        window = (
            DEFAULT_VOLTAGE_WINDOW_V if voltage_window_v is None else tuple(voltage_window_v)
        )
        if len(window) != 2:
            raise TrackingError(f"voltage_window_v 必须为 (min, max)，实际为 {voltage_window_v!r}")
        low, high = (float(item) for item in window)
        if not (np.isfinite(low) and np.isfinite(high)) or low <= 0.0 or high <= low:
            raise TrackingError(
                f"voltage_window_v 必须满足 0 < min < max，实际为 {(low, high)!r}"
            )
        if not np.isfinite(inductor_current_limit_a) or inductor_current_limit_a <= 0.0:
            raise TrackingError(
                f"inductor_current_limit_a 必须为正有限值，实际为 {inductor_current_limit_a!r}"
            )
        if not np.isfinite(efficiency) or not 0.0 < efficiency <= 1.0:
            raise TrackingError(f"efficiency 必须在 (0, 1] 内，实际为 {efficiency!r}")
        self.voltage_window_v = (low, high)
        self.inductor_current_limit_a = float(inductor_current_limit_a)
        self.efficiency = float(efficiency)

        # 问题 21：储能侧「开路电压 + 内阻」二参数模型。两个都给齐时才启用
        # 「储能吸收匹配电压」口径；缺任一个都退回「就地保持」（历史口径）。
        pair = (storage_open_circuit_voltage_v, storage_internal_resistance_ohm)
        if (pair[0] is None) != (pair[1] is None):
            raise TrackingError(
                "storage_open_circuit_voltage_v 与 storage_internal_resistance_ohm "
                f"必须同时给出或同时省略，实际为 {pair!r}"
            )
        if pair[0] is None:
            self.storage_open_circuit_voltage_v: Optional[float] = None
            self.storage_internal_resistance_ohm: Optional[float] = None
        else:
            v_oc = float(pair[0])
            r_int = float(pair[1])
            if not np.isfinite(v_oc) or v_oc <= 0.0:
                raise TrackingError(
                    f"storage_open_circuit_voltage_v 必须为正有限值，实际为 {v_oc!r}"
                )
            if not np.isfinite(r_int) or r_int <= 0.0:
                raise TrackingError(
                    f"storage_internal_resistance_ohm 必须为正有限值，实际为 {r_int!r}"
                )
            self.storage_open_circuit_voltage_v = v_oc
            self.storage_internal_resistance_ohm = r_int

        # 储能最大充电功率（问题 21 的第二半）：这是**硬约束**，
        # 缺了它 ③ 算出的 P_abs 会超过储能实际吸收能力，多余的电流只能靠 d2 旁路。
        #
        # 问题 33（2026-09-26）：校验由 ``cap > 0`` 放宽为 ``cap >= 0``。
        # 原因是「无储能」是一个**合法被控对象**，而它恰好要求 ``cap = 0``：
        # ``validation/perturbation.py::disable_storage`` 把 ``max_charge_power_w``
        # 置 0（容量仍在，只是不允许功率流入），基线 ``no_storage_zero_duty``
        # 走的就是这条被控对象扰动。语义上 ``None`` = 「未给定上限」（默认装配路径），
        # ``0.0`` = 「上限就是 0」（物理上一点都吸不了），两者必须可区分，
        # 而 ``0.0`` 本身完全可解释：``P_abs = 0`` ⟹ ``i_L,ref = 0``、
        # ``v_out,ref = V_oc``（``i_sink = 0``），正是「仅回网」的稳态。
        # 修复前这条校验会抛错，只是**恰好在旧接线里没被触发**——控制器侧
        # 只对闭环控制器构造参考模型，而 ``no_storage_zero_duty`` 用的是
        # ``ZeroDutyController``（哑控制器），从不构造；问题 33 让**仿真器**
        # 也逐步记录参考量之后，这条隐藏的过严校验才被暴露出来。
        if storage_max_charge_power_w is None:
            self.storage_max_charge_power_w: Optional[float] = None
        else:
            cap = float(storage_max_charge_power_w)
            if not np.isfinite(cap) or cap < 0.0:
                raise TrackingError(
                    f"storage_max_charge_power_w 必须为非负有限值（None 表示不限），实际为 {cap!r}"
                )
            # 归一化 ``-0.0``：``min(x, -0.0)`` 会返回 ``-0.0``，
            # 让负零漏进指标列（``-0.0`` 虽与 ``0.0`` 相等，但不该出现在功率列里）。
            self.storage_max_charge_power_w = 0.0 if cap == 0.0 else cap

    @property
    def assembly_path(self) -> str:
        """本实例的 ``x_ref`` 装配口径（方案问题 30 的审计字段）。

        取值见 :data:`ASSEMBLY_PATHS`。``ClosedLoopController.audit()`` 与
        ``ScenarioMetrics`` 的旁路审计都透传该字段，使「这次的 ``x_ref`` 是
        按哪条路径装的」可被下游核对——问题 30 的成因正是这条信息**无处可见**，
        于是「同标签两个控制器」在两张表里长期并存而无人发现。
        """

        return self._assembly_path

    @classmethod
    def from_converter_params(cls, params) -> "RegenerativeReferenceState":
        """**历史口径**（问题 21 修正前）：只取变流器参数，电压分量「窗口内就地保持」。

        .. warning::
           本方法**不是**生产装配路径，且**不允许**新增生产调用点（方案问题 30）。
           它只保留给两类用途：

           1. 复现问题 21 修正**前**的行为（回归对比）；
           2. 诊断脚本显式观察「就地保持」与「储能吸收匹配」的差异。

           生产路径（阶段 1/2 入口、阶段 9 套件、阶段 11 导出、主算法装配）
           一律走 :func:`build_reference_state`。走本方法时
           :attr:`assembly_path` 为 :data:`ASSEMBLY_LEGACY_VOLTAGE_HOLD`。

        ``params`` 是 :class:`~regenerative_braking.dynamics.dc_dc_converter.DCConverterParameters`
        （只按属性名鸭子类型使用，不导入该类，避免循环依赖）。

        本方法**不带**储能参数，因此也没有储能功率上限 ``P_storage``——
        这正是问题 21 实测到的缺陷：``i_L`` 峰值冲到 3443 A（超额定 15%）、
        ``d2`` 需旁路 40%。要启用「储能吸收匹配电压」请用
        :meth:`from_converter_and_storage_params`。
        """
        return cls(
            voltage_window_v=(params.output_voltage_min_v, params.output_voltage_max_v),
            inductor_current_limit_a=params.max_output_current_a,
            efficiency=params.efficiency,
            assembly=ASSEMBLY_LEGACY_VOLTAGE_HOLD,
        )

    @classmethod
    def from_converter_and_storage_params(
        cls, converter_params, storage_params, *, strategy: str = REFERENCE_STORAGE_MATCHED,
        feedback_resistance_upper_factor: Optional[float] = None,
    ) -> "RegenerativeReferenceState":
        """问题 21 裁定的正式口径（电压分量「储能吸收匹配」+ 储能功率上限）。

        .. warning::
           本方法是正式口径的**实现**，但**不是**推荐的生产调用点（方案问题 30）。
           生产路径请统一调用 :func:`build_reference_state`，它是唯一的装配入口，
           会在参数缺失时报错而不是静默退化。

        ``storage_params`` 提供储能侧「开路电压 + 内阻」，使电压分量可以按
        「储能吸收匹配」求值，从而让方案 ``modes.regen_charge`` 要求的
        ``d2 = 0`` 真正可行。两个参数对象都只按属性名鸭子类型使用。

        .. warning::
           本项目的 ``nominal_voltage_v`` / ``internal_resistance_ohm`` 当前是
           **placeholder**（见 ``data/single_train/storage_parameters.json`` 的
           ``field_data_status``）。故本口径的**幅值**依赖 placeholder，
           只有**结构**（``d2 → 0``、``i_L → i_sink``）是稳健的。见
           ``docs/regenerative_braking_algorithm.md`` §5.9。
        """
        return cls(
            voltage_window_v=(
                converter_params.output_voltage_min_v,
                converter_params.output_voltage_max_v,
            ),
            inductor_current_limit_a=converter_params.max_output_current_a,
            efficiency=converter_params.efficiency,
            storage_open_circuit_voltage_v=storage_params.nominal_voltage_v,
            storage_internal_resistance_ohm=storage_params.internal_resistance_ohm,
            storage_max_charge_power_w=storage_params.max_charge_power_w,
            assembly=ASSEMBLY_STORAGE_MATCHED,
            strategy=strategy,
            feedback_resistance_upper_factor=feedback_resistance_upper_factor,
        )

    def absorbable_power_terms(self, observation) -> Dict[str, float]:
        """③ 的**四个约束项**，按名称返回（问题 34 抽出的唯一入口）。

        定义（见模块 docstring ③，项名沿用方案原文）：

            P_storage,k = min(max_charge_power_w, storage_charge_power_limit_w)
            P_abs = min(P_req, P_avail, P_conv, P_storage,k)

        第四项字典键保持 ``max_charge_power_w`` 以兼容探针，值已包含本拍许可。
        任一未提供的上限按 ``inf`` 处理；生产仿真总是提供本拍许可。

        返回的键名与「实际内容」的对应关系（**以代码为准**，问题 34 修正）：

        ========================== ===================================================
        键                          实际内容
        ========================== ===================================================
        ``"P_req"``                ``max(0, requested_regen_power_w)``——
                                   **已过包络、过效率**的直流母线侧电机电功率
        ``"P_avail"``              ``max(0, available_regen_power_w)``——
                                   **轮端机械**电机包络，**不含 SOC、不含变流器容量**
        ``"P_conv"``               ``v_out · i_L,max · η``——变流器/电感电流容量
        ``"max_charge_power_w"``   额定吸收上限与同拍储能充电许可的较小值；
                                   两者均未提供才为 ``inf``（``None`` 不是 0）
        ========================== ===================================================

        .. important::
           ``P_avail`` **结构性不可能**成为 ``min()`` 的紧约束。``P_req`` 与
           ``P_avail`` 来自同一次 ``convert_wheel_regen``，且
           ``P_req = wheel_power·η``、``P_avail = effective_power_limit ≥ wheel_power``，
           因此 ``P_avail / P_req ≥ 1/η ≥ 1``。实测 9 个官方场景
           ``P_avail < P_req`` 的拍数恒为 ``0``。它与 ``P_conv`` 一样，
           是「当前量级下不构成约束、列出以保物理完整」的项。

        .. note::
           本方法是**唯一**给出四项公式的地方：:meth:`absorbable_power` 对它取
           ``min``，``__call__`` 调 :meth:`absorbable_power`。探针与测试**不要**
           自己手抄 ``P_conv = v_out·i_L,max·η`` 之类的表达式，否则一旦公式变更
           它们会静默地量错对象（这正是问题 34 的成因之一）。
        """

        voltage = float(observation.output_voltage_v)
        if not np.isfinite(voltage) or voltage <= 0.0:
            raise TrackingError(f"母线电压必须为正有限值，实际为 {voltage!r}")

        requested = max(0.0, float(observation.requested_regen_power_w))
        available = max(0.0, float(observation.available_regen_power_w))
        # 变流器/电感电流容量上限（当前量级下不构成约束，列出以保物理完整）
        converter_capacity = voltage * self.inductor_current_limit_a * self.efficiency
        # 额定值不能代替 SOC 余量；生产观测的许可与 ODE 的 sink 边界同源。
        cap = self.storage_max_charge_power_w
        runtime_cap = getattr(observation, "storage_charge_power_limit_w", None)
        if runtime_cap is not None and (not np.isfinite(runtime_cap) or runtime_cap < 0.0):
            raise TrackingError("储能本拍充电功率许可必须为非负有限值")
        effective_cap = min(math.inf if cap is None else float(cap),
                            math.inf if runtime_cap is None else float(runtime_cap))
        return {
            "P_req": float(requested),
            "P_avail": float(available),
            "P_conv": float(converter_capacity),
            # 问题 33：``None`` = 「未给定上限」⟹ ``inf``，``min`` 会忽略它。
            # 注意与 ``0.0`` 区分：``0.0`` 是「上限就是 0」（无储能被控对象）。
            "max_charge_power_w": effective_cap,
        }

    def absorbable_power(self, observation) -> float:
        """③ 可吸收功率 ``P_abs`` —— 控制器的**参考功率**（方案问题 33 抽出的公开入口）。

        定义（见模块 docstring ③）：

            P_abs = min(P_req, P_avail, P_conv, max_charge_power_w)

        四项的实际内容与侧别见 :meth:`absorbable_power_terms` 的表格——
        **不要**按项名望文生义（问题 34：``P_avail`` 不是「SOC 可用功率」，
        ``P_req`` 也不是制动曲线的原始请求）。

        .. important::
           这是**被控对象属性**，不是控制器属性。``P_abs`` 只依赖 ``observation``
           与装配时给定的硬件参数（``inductor_current_limit_a`` / ``efficiency`` /
           ``storage_max_charge_power_w``），**与「谁在控制」无关**。因此仿真器可以
           逐步记录它，作为 ``tracking_*`` 指标组的参考功率，全部控制器共用同一列——
           这也是问题 33 的修复前提（此前指标拿的是**轮端**可用功率，
           与储能侧的实测量跨了整条变换链）。

           :meth:`__call__` 内部调用本方法，**不重复公式**。
        """

        # 问题 21 的第二半（2026-09-25）：③ 原先**没有**储能吸收能力的硬上限，
        # 而 ``available_regen_power_w`` 是**电机侧（轮端）**包络，不是储能侧能力。
        # 实测 s1：P_abs = 3.23 MW，而储能 max_charge_power_w = 2 MW
        # ⟹ i_L,ref = 2910 A 而实际只能吸收 1729 A ⟹ 多余的 1181 A 靠 d2 = 0.4 旁路，
        # 且 i_L 峰值冲到 3443 A（超额定 15%）。补上该上限后 P_abs = 2 MW，
        # d2 → 0、i_L → i_sink，回收能量不变（本就受储能功率上限约束）。
        #
        # 问题 34（2026-09-26）：四项公式已抽到 :meth:`absorbable_power_terms`，
        # 本方法只取 ``min``——**不重复任何项公式**。``max_charge_power_w`` 为
        # ``None`` 时该入口返回 ``inf``，故这里无需再分支（原实现有 ``if ... is not None``
        # 分支，属于同一语义的第二处实现）。
        return float(min(self.absorbable_power_terms(observation).values()))

    def __call__(self, observation) -> np.ndarray:
        voltage = float(observation.output_voltage_v)
        if not np.isfinite(voltage) or voltage <= 0.0:
            raise TrackingError(f"母线电压必须为正有限值，实际为 {voltage!r}")

        low, high = self.voltage_window_v

        # ③ 可吸收功率（问题 33：公式已抽到 :meth:`absorbable_power`，此处不重复）
        absorbable_power = self.absorbable_power(observation)

        # ① 电压分量（问题 21 裁定，2026-09-25）
        #
        # 「窗口内就地保持」在物理上是不可实现的：储能侧吸收电流受内阻限制
        #   i_sink = (v_out − V_oc) / R_int
        # 而稳态必须满足 (1−d2)·i_L = i_sink。v_out 被钉在当前值 ⇒ i_sink 被钉住
        # ⇒ d2 只能旁路掉多余的 i_L，实际回收功率远小于 ③ 算出的 P_abs。
        # 实测 s1：v_out = 1110 V ⇒ i_sink = 500 A，而 i_L,ref = 2910 A
        # ⇒ d2 ≈ 0.84，回收能量只有 1.23 kWh（基线 4.44）。
        #
        # 反过来解：要让储能吸收 P_abs，需要 v_out·(v_out − V_oc) = P_abs·R_int，
        # 即 v_out = (V_oc + sqrt(V_oc² + 4·P_abs·R_int)) / 2。取该值为电压参考，
        # 于是 d2 → 0、i_L → i_sink，与方案 modes.regen_charge 的「T2 置 0」自洽。
        if self.strategy in (REFERENCE_CURRENT_FEEDBACK, REFERENCE_GUARDED_CURRENT_FEEDBACK) and absorbable_power > 0.0:
            # 局部电流匹配：i* = P*/v_meas，Δv = R_nom·(i* − i_sink,meas)。
            # 固定点满足 v_ref=v_meas ⇒ i_sink=P*/v_meas，故不要求真实 R=R_nom。
            # R_nom 只是局部修正尺度；I/V 均来自控制器可见量测，无真值旁路。
            sink_current = float(observation.output_current_a)
            if not np.isfinite(sink_current) or sink_current < 0.0:
                raise TrackingError("储能电流反馈要求非负有限输出电流")
            matched = voltage + float(self.storage_internal_resistance_ohm) * (
                absorbable_power / voltage - sink_current
            )
            if self.strategy == REFERENCE_GUARDED_CURRENT_FEEDBACK:
                # 功率饱和时，偏低电流使正误差永不消失。仅下界会把反馈
                # 一路推向硬件电压上轨；按声明的内阻范围约束参考，停止漂移。
                # 仍允许范围内增加 R 的精确功率固定点，无真实 R/功率旁路。
                lower, upper = self.feedback_voltage_bounds(absorbable_power)
                matched = min(max(matched, lower), upper)
            voltage_reference = float(min(max(matched, low), high))
        elif self.storage_open_circuit_voltage_v is not None:
            matched = self._storage_matched_voltage(absorbable_power)
            voltage_reference = float(min(max(matched, low), high))
        else:
            # 历史口径（问题 21 修正前）：窗口内就地保持，越窗才回拉
            voltage_reference = float(min(max(voltage, low), high))

        # ④ 电感电流参考（buck 稳态联立，效率恰好相消）。
        # 分母用 voltage_reference 而不是量测电压——问题 21 修正后两者不再相等。
        inductor_current_reference = absorbable_power / max(voltage_reference, 1e-9)
        inductor_current_reference = float(
            min(max(inductor_current_reference, 0.0), self.inductor_current_limit_a)
        )
        return np.asarray([voltage_reference, inductor_current_reference], dtype=float)

    def feedback_voltage_bounds(self, power: float) -> Tuple[float, float]:
        """同功率 I-V 参考范围；不代表真实状态的不变集或传感器误差估计。

        R 上界是显式 assumed 参数。超出所声明 R 范围时可能无法达到功率
        目标，不能依据此参考限幅宣称任意对象/量测下的瞬态安全。
        """
        if self.feedback_resistance_upper_factor is None:
            raise TrackingError("只有保护反馈策略具有内阻范围电压边界")
        if not np.isfinite(power) or power < 0.0:
            raise TrackingError("反馈边界的功率必须为非负有限值")
        low, high = self.voltage_window_v
        lower = self._storage_matched_voltage(power)
        upper = self._storage_matched_voltage(power, self.feedback_resistance_upper_factor)
        return float(min(max(lower, low), high)), float(min(max(upper, low), high))

    def _storage_matched_voltage(self, power: float, resistance_factor: float = 1.0) -> float:
        """同一标称 I-V 匹配式，供正式参考与反馈下界共用（尚未窗口限幅）。"""
        v_oc = float(self.storage_open_circuit_voltage_v)
        r_int = float(self.storage_internal_resistance_ohm) * resistance_factor
        return 0.5 * (v_oc + float(np.sqrt(v_oc * v_oc + 4.0 * power * r_int)))


#: 兼容别名：正式实现类的旧名（历史代码/文档里叫 ``BusTrackingReference``）。
BusTrackingReference = RegenerativeReferenceState


def build_reference_state(
    converter_params, storage_params, *, strategy: str = REFERENCE_STORAGE_MATCHED,
    feedback_resistance_upper_factor: Optional[float] = None,
) -> RegenerativeReferenceState:
    """``x_ref`` 的**唯一**生产装配入口（方案问题 30 裁定）。

    为什么需要这个函数而不是直接调 classmethod：``RegenerativeReferenceState``
    原先有三个可达装配口径，走哪一条取决于调用方「恰好传了哪些可选参数」，
    而三者之间**没有任何一致性校验**。结果实测出现「同一个 baseline 标签在两条
    入口下是两个不同控制器」（见 :data:`SCHEME_ISSUE_REFERENCE_ASSEMBLY_SPLIT`）。

    本函数的契约：

    * ``converter_params`` 与 ``storage_params`` **都必须给出**，缺任一个即
      :class:`TrackingError`——不允许静默退化到历史口径或模块默认值；
    * 内部固定走问题 21 裁定的正式口径
      （:meth:`RegenerativeReferenceState.from_converter_and_storage_params`）；
    * 返回实例的 :attr:`RegenerativeReferenceState.assembly_path` 必为
      :data:`ASSEMBLY_STORAGE_MATCHED`。

    两个参数对象都只按属性名鸭子类型使用（``converter_params`` 需带
    ``output_voltage_min_v`` / ``output_voltage_max_v`` / ``max_output_current_a`` /
    ``efficiency``；``storage_params`` 需带 ``nominal_voltage_v`` /
    ``internal_resistance_ohm`` / ``max_charge_power_w``），因此本模块仍然
    **不依赖包内任何其他模块**。
    """

    if converter_params is None or storage_params is None:
        raise TrackingError(
            f"方案问题 {SCHEME_ISSUE_REFERENCE_ASSEMBLY_SPLIT}："
            "x_ref 的生产装配路径要求同时给出 converter_params 与 storage_params，"
            f"实际为 converter_params={type(converter_params).__name__ if converter_params is not None else None}、"
            f"storage_params={type(storage_params).__name__ if storage_params is not None else None}。"
            "只给一个会静默退化到问题 21 修正前的历史口径（电压分量「窗口内就地保持」、"
            "无储能功率上限），两个都不给则退化为本模块的兜底常量——"
            "三条路径给出三个不同的控制器，而标签完全一样。"
            "若确需复现历史行为，请显式调用 "
            "RegenerativeReferenceState.from_converter_params（assembly_path="
            f"{ASSEMBLY_LEGACY_VOLTAGE_HOLD!r}）或直接构造（assembly_path="
            f"{ASSEMBLY_DEFAULTS!r}），不要经由本函数。"
        )
    return RegenerativeReferenceState.from_converter_and_storage_params(
        converter_params, storage_params, strategy=strategy,
        feedback_resistance_upper_factor=feedback_resistance_upper_factor,
    )


class PendingReferenceState:
    """**历史哨兵**：问题 13 裁定前用于「不允许静默代拟 ``x_ref``」的占位实现。

    正式口径已由 :class:`RegenerativeReferenceState` 给出，本类**不再作为默认**。
    保留它只有一个用途：让「未修正」的历史行为仍可复现、可回归对比——
    显式注入本类时，一调用即抛 :class:`PendingSchemeConfirmationError`。
    """

    data_status = PENDING_SCHEME_CONFIRMATION

    def __call__(self, observation) -> np.ndarray:
        raise PendingSchemeConfirmationError(
            f"方案问题 {SCHEME_ISSUE_REFERENCE_STATE_UNSPECIFIED}："
            "参考状态 x_{ref,k} 的构造式未在方案原文中给出。"
            "编写人已于 2026-09-25 裁定正式构造式（见 RegenerativeReferenceState），"
            "本哨兵仅用于复现「未修正」的历史行为；"
            "正常路径请勿注入本类。"
        )


@dataclass(frozen=True)
class SchurStabilisingMatrix:
    """稳定项 ``u_n = −S_sc · s`` 的 ``S_sc``（方案要求特征值 ∈ [0.6, 0.8]）。

    方案只给了特征值范围，没给矩阵本身。编写人裁定（问题 5 / 14 组）：
    取**对角阵** ``S_sc = diag(σ, σ)``，其特征值即 ``σ``；``σ`` 取区间中点 ``0.7``。

    依据：① 对角取法是特征值最容易核对的形式，能直接满足方案的验收条件；
    ② ``S_sc`` 只通过 ``u_n`` 的幅值起作用，``u_n`` 在问题 14 裁定后已无量纲，
    因此不需要非对角结构来做通道解耦；③ 取区间中点使 ``σ`` 到两个边界的余量相等，
    在「响应快」与「抖振小」之间取中，不引入任何未声明的最优化。

    provenance: **assumed → 编写人裁定** —— 方案未给出 ``S_sc`` 的具体形式，
    本取法已在 2026-09-25 由编写人确认为正式口径（``SCHEME_AUTHORED``）。
    """

    eigenvalue: float = 0.7
    dimension: int = 2

    def __post_init__(self) -> None:
        low, high = SCHEME_SCHUR_EIGENVALUE_RANGE
        if not np.isfinite(self.eigenvalue) or not low <= self.eigenvalue <= high:
            raise TrackingError(
                f"Schur 特征值必须落在方案给定区间 [{low}, {high}] 内，实际为 {self.eigenvalue!r}"
            )
        if self.dimension < 1:
            raise TrackingError("dimension 必须为正")

    @property
    def matrix(self) -> np.ndarray:
        """``S_sc`` 的副本。"""
        return np.eye(self.dimension) * self.eigenvalue

    @property
    def eigenvalues(self) -> np.ndarray:
        """``S_sc`` 的特征值（供验收核对是否落在 [0.6, 0.8]）。"""
        return np.linalg.eigvalsh(self.matrix)

    def stabilising_term(self, surface: Sequence[float]) -> np.ndarray:
        """``u_n = −S_sc · s(x_k, k)``（方案原文）。"""
        return -(self.matrix @ np.asarray(surface, dtype=float))
