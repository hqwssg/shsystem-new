"""RHONN 系统辨识器（阶段 3）。

对应技术方案 §4.2.1.3（1）**RHONN 系统辨识算法**。

方案原文状态方程（未编号；证据图 ``fig_rhonn_state_equation.png``）::

    x̂_{i,k+1} = ω_{i,k}^T · φ_i(x_k) + ω̄_{i,k}^T · φ_i(x_k, u_k)

方案给出的符号定义（§A.2.1）::

    x̂_{i,k+1}        第 i 个神经元的状态估计值
    x_k = [x_1,x_2]^T 系统实际状态向量
    u_k               控制输入（T1 / T2 的 PWM 占空比）
    ω_{i,k}           可调突触权重
    ω̄_{i,k}           固定权重
    φ_i(·)            基函数，S(·) = tanh(αx + β)

实现必须保留的三个结构特征（评审会逐项检查，见
``docs/technical_scheme_code_mapping.md`` §C.3 的硬约束）:

1. **递归项** —— 当前估计依赖上一时刻估计，不是纯前馈；
2. **高阶 tanh 基函数** —— 只用 tanh，不得换成 ReLU 等其他激活；
3. **串联-并联双路径** —— 同时吃「实际状态」与「上一时刻估计」。

--------------------------------------------------------------------------
已按方案编写人授权自行修正的五处（问题 9 / 15 / 16 / 18 / 8）
--------------------------------------------------------------------------

**问题 15（真·主阻塞项）—— ``B = ∂g/∂u`` 不可辨识 ⟹ 已修正**

方案原文把控制输入 ``u`` 只放在**固定权重**项 ``ω̄`` 里，于是
``∂x̂/∂u`` 结构性不含可调权重，在线辨识改不动 ``B``（实测
``max|Δω| = 130.4``、``max|Δ预测| = 168789.9``，而 ``max|ΔB| = 0.0``），
``B`` 的对角符号纯随机（12 个种子中 3 个全负）→ ``u_eq`` 方向被带反 →
占空比被 PWM 截断为 0 → 控制通道永不被激励 → 自锁。

修正依据（RHONN 标准形式，见 Neurocomputing 322 (2018) 13–21 的
串联-并联表示；MDPI Appl. Sci. 11(3):1154 (2021) §3.1 明确
「synaptic weights calculated online by the EKF algorithm」）：
**标准 RHONN 的全部突触权重都是可调并由滤波器在线训练的，不存在
「固定权重分支」**。故本实现把串联路径权重 ``ω̄`` 一并并入可调参数向量::

    ω_tunable = [ W_par | W_ser ]  ∈ R^{state_dim × (n_par + n_ser)}
    n_tunable_weights = 2 × (4 + 6) = 20

于是 ``∂x̂/∂u = diag(state_scale) · W_ser · ∂φ_ser/∂u`` **含可调权重**，
在线辨识可以校正 ``B``；``tests/test_control_channel.py`` 用
``max|ΔB| > 0`` 钉住这一点。

**问题 15 的符号自锁 —— 用「控制通道符号先验」打破**

仅让 ``B`` 可辨识还不够：``u ≡ 0`` 时控制通道没有激励，
``B`` 的符号无从由数据确定（缺乏持续激励）。故本实现在**初始化**阶段
按被控对象的已知小信号模型给 ``B`` 定符号，再由在线辨识细化——
这是神经网络辨识里标准的「用已知模型热启动」做法。

先验由变流器模型（:mod:`regenerative_braking.dynamics.dc_dc_converter`）直接推出::

    ∂i_L/∂d1 = v_in / L      > 0
    ∂i_L/∂d2 = v_out / L     > 0
    ∂v_out/∂d2 = −i_L / C_out < 0
    ∂v_out/∂d1 > 0            （buck：v_out = d1·v_in；数值微分实测 +0.7254）

即 ``B`` 的目标符号为 ``[[+1, −1], [+1, +1]]``（状态向量为 ``(v_out, i_L)``）。
provenance = **derived**（由已知变流器模型推出），不是实测、不是假定。

实现方式是**只翻转符号、不改幅度**：对第 ``(n, m)`` 个通道，若标称点的
``B[n, m]`` 与先验异号，则把 ``W_ser`` 中**仅影响该通道**的两列
（``m = 0`` 时是第 2、4 列，``m = 1`` 时是第 3、5 列，见
:data:`SERIES_COLUMNS_BY_CONTROL_CHANNEL`）**一起**取反。该操作等价于把
``B[n, m]`` 整体取反，故**标称点**的符号必定正确，从而打破自锁；闭环里
一旦控制器把 ``u`` 动起来，数据会把 ``B`` 拉向真值。
实测全部随机种子闭环都能回收到非零能量（见 ``tests/test_closed_loop.py``）。

.. note::
   该翻转**不保证**其它工作点的符号——两个串联列可以合法地异号（部分抵消），
   ``B[n, m]`` 在两者系数比例变化时仍可能变号。实测 120 个随机种子 × 6 工作点
   × 6 控制，**72 个种子（60%）**在标称点之外至少一处越界。

   逐列翻到同号虽可证明任意工作点都对齐（实测 0/120 越界），但会放大 ``|B|``
   （异号抵消消失），把联合闭环推进**数值混沌**区间：对协方差施加 1 ULP
   （``1e-16``）扰动，回收能量相对变化从 ``1.9e-10`` 恶化到 ``6.6%``，
   并使 EKF/UKF 闭环一致性哨兵
   （``tests/test_validation.py::test_family7_filter_variants_agree_with_the_switching_controller``）
   失败。**主行为优先**，故保留整组方案，并把这一权衡记录在此。

若需要在线持续约束（例如 ``u`` 长期恒定的低激励工况），可置
``RHONNConfig.enforce_control_channel_sign = True``；但那是一次不连续反射，
会打断在线辨识并破坏 **UKF ≡ EKF** 等价，故**默认关闭**（详见 :class:`RHONNConfig`）。

``RHONNConfig.control_channel_sign_prior = None`` 可关闭该先验，
用于回归对比「未修正」的行为。

**问题 18（已裁定）—— 符号先验只钉住符号，``B`` 的幅值仍失真 ⟹ 补全为增益先验**

符号先验把 ``B`` 的**符号**钉住，却没管**幅值**。实测（族 7 闭环，``dt = 4e-4``）::

    ∂i_L/∂d1   被控对象真值 1231.4    辨识值中位数  253    （0.21×）
    ∂i_L/∂d2   被控对象真值 ~897      辨识值中位数  134    （0.30×）

后果链是**结构性**的，不依赖具体工况：

1. ``u_eq = B⁺·(x_ref − g)`` 里的 ``B⁺`` 被放大 ``≈ 5×``；
2. 于是 ``‖u_eq‖`` 达 ``1.5 ~ 1e3``，恒 ``≫ u_0 = 0.9``；
3. 保方向饱和（问题 14b 裁定）每拍触发，``‖u_n‖ ≈ 0.42`` 被完全淹没，
   滑模稳定项形同虚设；
4. 闭环被推进 ``i_L = 1.5×`` 额定、``v_out`` 越窗（``1615.5 V > 1500 V``）。

**裁定**：把「用已知模型热启动」补全到**幅值**。目标 ``B`` 由变流器平均模型的
小信号增益直接给出（:class:`ControlChannelGainPrior`），全部取自项目已有参数，
**无自由参数**::

    B_target = [[ (1−d2)·v_in·dt² / (2·L·C_out),   −i_L·dt / C_out ],
                [ v_in·dt / L,                      v_out·dt / L   ]]

行 = ``(v_out, i_L)``，列 = ``(d1, d2)``；``dt`` 取**该次仿真的采样步长**。

第一行第一列的 ``dt²`` 项是本表中唯一的二阶项，原因是 ``d1`` 在一步 ODE 里
**不出现**于 ``dv_out`` 方程（``dv_out/dt = ((1−d2)·i_L − i_sink)/C_out``），
它的一阶增益结构性为 0；若取 0，符号先验（要求 ``∂v_out/∂d1 > 0``）就会与幅值
先验在该通道上冲突——因为符号先验翻转的是**整列**权重（列 2、4 一起取反），
会把同列的 ``∂i_L/∂d1`` 一起翻反。故取 RK4 的二阶耦合项 ``A·B·dt²/2``，
它恒为正、且完全由模型参数决定。

.. note::
   实测残差（``dt = 4e-4``、标称点 ``(v_out, i_L, v_in) = (1100, 3000, 1500)``）::

       ∂v_out/∂d1  目标 12.0   真值  9.06   （同量级，符号正确）
       ∂v_out/∂d2  目标 −60.0  真值 −13.7   （同量级，符号正确）
       ∂i_L/∂d1    目标 1200   真值 1231.4 （2.5%）
       ∂i_L/∂d2    目标 880    真值 ~897   （2%）

   主导项（``i_L`` 行）在 3% 以内；``v_out`` 行的 ``d2`` 列偏大，是因为
   存储母线的 ``∂i_sink/∂v_out`` 耦合未纳入（它需要储能内阻，属被控对象侧参数）。
   热启动只是一次**初值**，在线辨识随后会把它拉向真值，故不做二阶以上拟合。

实施效果（族 7，``dt = 4e-4``，实测）::

    i_L 峰值   4498 A → 1004 A   （1.50× 额定 → 0.33× 额定）
    v_out 峰值 1615.5 V → 1120.1 V（越窗 → 窗内）
    回收能量   0.0600 kWh → 0.0347 kWh（激进工况退回到保守工况的代价）

**问题 16（阻塞）—— 状态向量冗余 ⟹ 已修正为 ``(v_out, i_L)``**

方案的状态向量 ``(v_out, i_out)`` 两个分量代数相关
（``i_out = (v_out − v_oc)/R_int``），使对象的 ``B`` 恒为秩 1
（实测两个工作点 ``det = 0.0``、``rank = 1``、两行比值恒 ``1/R_int = 20.000``），
``u_eq`` 无法独立跟踪双目标。

修正：状态向量取 **互相独立** 的 ``(v_out, i_L)``——电感电流是变流器的
独立状态量（``DCConverterState.inductor_current_a``，ODE 中
``L·di_L/dt = d1·v_in − (1−d2)·v_out − R_L·i_L``），
``B`` 由此可满秩。本模块只消费状态向量、不解释其物理含义，
故改动落在接线层（``simulation/closed_loop.py``）与参考量口径
（``tracking.BusTrackingReference``）。

**问题 9 —— 基函数措辞**

方案符号说明写「线性基函数，S(·) = tanh(αx + β)」，「线性」与 ``tanh``
自相矛盾。按文献（同上）与方案自己给出的公式，正确措辞是
**「非线性（双曲正切）高阶基函数」**。本实现按 tanh 落地，措辞已统一。

**问题 8 —— 串联路径的投影与尺度**

方案公式两项都写作 ``φ_i(x_k)`` 与 ``φ_i(x_k, u_k)``（都用实际状态），
但网络命名为「串联-并联」；「串联」按 Narendra 型结构应**用估计值构成递归**。
方案未给出串联路径的投影矩阵与控制尺度，本实现显式定义并导出::

    并联路径 φ_par(x_k)      = tanh(α · P_par · (x_k ⊘ state_scale) + β)      ∈ R^4
    串联路径 φ_ser(x̂_k, u_k) = tanh(α · P_ser · ([x̂_k, u_k] ⊘ [state_scale, control_scale]) + β)  ∈ R^6

``P_par`` / ``P_ser`` 即 :data:`PARALLEL_PROJECTIONS` / :data:`SERIES_PROJECTIONS`，
``state_scale`` / ``control_scale`` 即 :class:`RHONNConfig` 的同名字段。

--------------------------------------------------------------------------
基函数输入必须归一化
--------------------------------------------------------------------------

tanh 的输入若不归一化，电压量级（~1400 V）会直接让 tanh 饱和到 ±1，
网络丧失分辨力。本实现用固定参考尺度把状态与控制缩放到 O(1) 再进 tanh。
参考尺度取自阶段 1/2 仿真时序的中心量级，属 derived 数据，不是实测值。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Sequence, Tuple

import numpy as np


class RHONNError(ValueError):
    """RHONN 配置或输入不合法。"""


#: 需要方案编写人确认的实现口径标记。
#: 代码与文档中出现该标记的位置，一律表示「本处不是方案原文，是按标准形式落地」。
PENDING_SCHEME_CONFIRMATION = "PENDING_SCHEME_CONFIRMATION"


#: 方案问题编号（与 `docs/technical_scheme_code_mapping.md` §A.3 对齐）。
SCHEME_ISSUE_SERIES_PATH = 8  # 串联路径在方案公式中缺失（本模块新发现）
SCHEME_ISSUE_BASIS_WORDING = 9  # 「线性基函数」与 tanh 形式自相矛盾（措辞）
SCHEME_ISSUE_CONTROL_CHANNEL_UNIDENTIFIABLE = 15  # B 与可调权重无关（已修正）
SCHEME_ISSUE_STATE_VECTOR_REDUNDANT = 16  # (v_out, i_out) 代数相关（已修正）
SCHEME_ISSUE_CONTROL_CHANNEL_MAGNITUDE = 18  # 符号先验只钉符号，B 幅值失真（已补全）
SCHEME_ISSUE_CONTROL_CHANNEL_STATE_DEPENDENCE = 19  # B_target 状态相关，先验只在标称点精确（已补全）
SCHEME_ISSUE_EQUIVALENT_CONTROL_UNREACHABLE = 20  # u_eq 一步死拍在不可达时退化为错误方向（已补全）
#: 零控制预测的电压增量少一半二阶项，``u_eq`` 因此凭空多出一份电压增益
#: （2026-11-08 实现期新发现，已修正）。见 :meth:`ControlChannelModel.zero_control_delta`。
SCHEME_ISSUE_ZERO_CONTROL_SECOND_ORDER = 35

#: 方案问题修正状态（供审计与文档透传）
SCHEME_FIX_STATUS = {
    SCHEME_ISSUE_SERIES_PATH: "fixed_by_implementation",
    SCHEME_ISSUE_BASIS_WORDING: "fixed_by_implementation",
    SCHEME_ISSUE_CONTROL_CHANNEL_UNIDENTIFIABLE: "fixed_by_implementation",
    SCHEME_ISSUE_STATE_VECTOR_REDUNDANT: "fixed_by_implementation",
    SCHEME_ISSUE_CONTROL_CHANNEL_MAGNITUDE: "fixed_by_implementation",
    SCHEME_ISSUE_CONTROL_CHANNEL_STATE_DEPENDENCE: "fixed_by_implementation",
    SCHEME_ISSUE_EQUIVALENT_CONTROL_UNREACHABLE: "fixed_by_implementation",
    SCHEME_ISSUE_ZERO_CONTROL_SECOND_ORDER: "fixed_by_implementation",
}

# --------------------------------------------------------------------------
# 固定投影方向：tanh 作用在状态的固定线性投影上，构成非线性基函数向量。
# 含单变量项与交叉项，使网络输出是状态的非线性（高阶）函数。
# --------------------------------------------------------------------------

#: 并联路径投影（输入 x_k ∈ R^2）—— 单变量 + 交叉
PARALLEL_PROJECTIONS: Tuple[Tuple[float, ...], ...] = (
    (1.0, 0.0),   # x_1
    (0.0, 1.0),   # x_2
    (1.0, 1.0),   # x_1 + x_2
    (1.0, -1.0),  # x_1 - x_2
)

#: 串联路径投影（输入 [x̂_k, u_k] ∈ R^4）—— 状态单变量 + 控制单变量 + 状态控制交叉
SERIES_PROJECTIONS: Tuple[Tuple[float, ...], ...] = (
    (1.0, 0.0, 0.0, 0.0),  # x̂_1
    (0.0, 1.0, 0.0, 0.0),  # x̂_2
    (0.0, 0.0, 1.0, 0.0),  # u_1          ← 只影响 B 的第 0 列
    (0.0, 0.0, 0.0, 1.0),  # u_2          ← 只影响 B 的第 1 列
    (1.0, 0.0, 1.0, 0.0),  # x̂_1 + u_1    ← 只影响 B 的第 0 列
    (0.0, 1.0, 0.0, 1.0),  # x̂_2 + u_2    ← 只影响 B 的第 1 列
)

#: 各控制通道对应的串联投影列索引（用于控制通道符号先验的定点翻转）。
#: 依据：``SERIES_PROJECTIONS`` 中只有这些行的**控制分量**非零，
#: 故翻转这些列的权重只会改变对应那一列 ``B[:, m]``，不串扰另一列。
#: 两列**一起**取反 ⟹ ``B[:, m]`` 整体取反 ⟹ 标称点符号必定正确
#: （但其它工作点不保证，见 :meth:`RHONN._align_control_channel_sign`）。
SERIES_COLUMNS_BY_CONTROL_CHANNEL: Tuple[Tuple[int, ...], ...] = (
    (2, 4),  # m = 0（T1）：u_1 与 x̂_1+u_1
    (3, 5),  # m = 1（T2）：u_2 与 x̂_2+u_2
)

#: 控制通道符号先验 —— ``B = ∂x̂/∂u`` 的目标符号（状态向量 ``(v_out, i_L)``）。
#:
#: provenance = **derived**：由变流器 ODE 直接推出，不是实测、不是假定::
#:
#:     ∂v_out/∂d1 > 0   buck 关系 v_out = d1·v_in（数值微分实测 +0.7254）
#:     ∂v_out/∂d2 < 0   因 dv_out/dt = ((1−d2)·i_L − i_sink) / C_out
#:     ∂i_L/∂d1  > 0    因 di_L/dt = (d1·v_in − (1−d2)·v_out − R_L·i_L) / L
#:     ∂i_L/∂d2  > 0    同上
#:
#: 只用于**初始化定符号**，不约束在线辨识的取值（辨识仍可自由改变 B 的幅值与符号，
#: 只是从正确的符号出发，从而打破「占空比为 0 ⟹ 通道无激励 ⟹ B 不可辨识」的自锁）。
CONTROL_CHANNEL_SIGN_PRIOR: Tuple[Tuple[int, ...], ...] = (
    (+1, -1),  # 第 0 个状态分量 v_out：∂v_out/∂d1 > 0、∂v_out/∂d2 < 0
    (+1, +1),  # 第 1 个状态分量 i_L  ：∂i_L/∂d1  > 0、∂i_L/∂d2  > 0
)

#: 状态向量语义（供接线层与文档核对；本模块不解释物理含义）
STATE_LABELS: Tuple[str, ...] = ("v_out", "i_L")

#: 控制通道增益先验的**默认标称占空比**（derived，不是自由参数）::
#:
#:     d1 = 0.5   PWM 硬边界 [duty_limit.min, duty_limit.max] = [0, 1] 的中点
#:     d2 = 0.0   dc_dc_parameters.json 的 ``modes.regen_charge`` 明确「T1 为主控，T2 置 0」
DEFAULT_NOMINAL_DUTY: Tuple[float, float] = (0.5, 0.0)

#: 控制通道增益先验的默认采样步长（s）。
#:
#: 该值必须与**实际仿真步长**一致——``B = ∂x̂/∂u`` 是**一步**灵敏度，其幅值正比于 ``dt``。
#: 默认值取验证套件的默认步长（``tools/run_validation_suite.py --dt`` 默认 ``2e-4``）。
#: 装配层（:func:`~regenerative_braking.simulation.closed_loop.build_closed_loop_controller`）
#: 会把真实 ``dt`` 透传进来；未透传时才落到本默认值，并在 ``audit()`` 中可见。
DEFAULT_SAMPLE_TIME_S: float = 2.0e-4


@dataclass(frozen=True)
class ControlChannelModel:
    """重算控制通道 ``B_target`` 所需的最小模型信息（问题 19 裁定，2026-09-25）。

    为什么需要它
    ------------
    问题 18 的增益先验把 ``B_target`` 钉在**一个标称点**上（``from_converter_params``
    取 ``i_L = max_output_current_a``，即额定 3000 A）。但 ``B_target`` 是**状态相关**的::

        ∂v_out/∂d2 = −i_L·dt / C_out       ← 与 i_L 成正比
        ∂i_L/∂d2   =  v_out·dt / L         ← 与 v_out 成正比

    实测（``s2_long_downhill`` 第 0 拍，``tools/probe_u_eq_drift.py``）：实际起点是
    ``i_L = 0``，而先验的标称点是 ``i_L = 3000 A``。于是

    * 先验目标 ``B_target[0, 1] = −30.0``（正确符号）
    * RHONN 在实际工作点给出的 ``B[0, 1] = +40.90``（**符号相反**）

    ``B`` 的符号错一处，``u_eq = B⁺·residual`` 的 ``d1`` 分量就被带成负值 →
    保方向饱和后 ``d1`` 被截为 0 → ``i_L`` 恒为 0 → 控制通道无激励 → 模型更不准 →
    自锁。这正是符号先验自己文档里记录的「只在标称点保证符号、其它工作点实测
    60% 越界」的缺陷在闭环上的后果。

    本类把 ``B_target`` 的求值从「标称点」推广到「**逐拍当前工作点**」：
    在 ``(v_out, i_L)`` 处直接按同一个解析式重算。全部输入仍取自
    ``dc_dc_parameters.json`` 与可观测量，**无自由参数**。
    """

    #: 电感 ``L``（H）。
    inductance_h: float
    #: 输出侧电容 ``C_out``（F）。
    output_capacitance_f: float
    #: 设计标称输入（直流母线）电压 ``v_in``（V）—— 观测不可用时的回退值。
    input_voltage_v: float
    #: 电感等效串联电阻 ``R_L``（Ω）—— **不参与** ``B_target``（小信号增益里没有它），
    #: 只用于 :meth:`zero_control_delta` 的零控制预测。允许为 0。
    inductor_resistance_ohm: float = 0.0
    #: 重算时用的占空比 ``(d1, d2)``，默认取 :data:`DEFAULT_NOMINAL_DUTY`。
    duty_cycle: Tuple[float, float] = DEFAULT_NOMINAL_DUTY

    def __post_init__(self) -> None:
        for name in ("inductance_h", "output_capacitance_f", "input_voltage_v"):
            value = float(getattr(self, name))
            if not np.isfinite(value) or value <= 0.0:
                raise RHONNError(f"ControlChannelModel.{name} 必须为正有限值，实际为 {value!r}")
        r_l = float(self.inductor_resistance_ohm)
        if not np.isfinite(r_l) or r_l < 0.0:
            raise RHONNError(
                f"ControlChannelModel.inductor_resistance_ohm 必须为非负有限值，实际为 {r_l!r}"
            )
        if len(self.duty_cycle) != 2:
            raise RHONNError(f"ControlChannelModel.duty_cycle 必须为二元组，实际为 {self.duty_cycle!r}")

    def target_b_at(
        self,
        *,
        output_voltage_v: float,
        inductor_current_a: float,
        input_voltage_v: Optional[float] = None,
        sample_time_s: float,
        duty_cycle: Optional[Sequence[float]] = None,
    ) -> np.ndarray:
        """在当前工作点重算 ``B_target``（与 :meth:`ControlChannelGainPrior.from_converter_gains`
        用**同一个**解析式，只是把标称点换成当前点）。

        Args:
            output_voltage_v: 当前 ``v_out``（V）。
            inductor_current_a: 当前 ``i_L``（A）—— 允许为 0（``∂v_out/∂d2`` 随之归零，
                这是物理正确的：``i_L = 0`` 时改变 ``d2`` 不影响母线电压）。
            input_voltage_v: 当前 ``v_in``（V）；省略时用本对象的标称值。
            sample_time_s: 仿真步长 ``dt``（s）。
            duty_cycle: 当前占空比；省略时用本对象的默认值。

        .. important::
           ``B[0][0] = (1−d2)·v_in·dt²/(2LC)`` 是**电容电荷的三角积分项**，
           ``d1`` 在这一拍里把 ``i_L`` 从 ``i_L`` 抬到 ``i_L + ∂i_L/∂d1·d1``，
           多出来的电荷是这块三角形。它与
           :meth:`zero_control_delta` 里的 ``A₀·dt²/(2C)`` **成对存在**：
           后者是「没有控制时 ``i_L`` 自己衰减」贡献的同一块三角形。
           只取其一 ⟹ ``u_eq`` 的模型内部不自洽 ⟹ 一步死拍留下稳态电压偏差
           （方案问题 35，2026-11-08）。
        """
        dt = float(sample_time_s)
        if not np.isfinite(dt) or dt <= 0.0:
            raise RHONNError(f"sample_time_s 必须为正有限值，实际为 {sample_time_s!r}")
        v_out = float(output_voltage_v)
        if not np.isfinite(v_out) or v_out <= 0.0:
            raise RHONNError(f"output_voltage_v 必须为正有限值，实际为 {output_voltage_v!r}")
        i_l = float(inductor_current_a)
        if not np.isfinite(i_l) or i_l < 0.0:
            # i_L 是电感电流，物理上非负；负值只可能来自数值噪声，钳到 0。
            i_l = max(i_l, 0.0)
        v_in = float(self.input_voltage_v if input_voltage_v is None else input_voltage_v)
        if not np.isfinite(v_in) or v_in <= 0.0:
            v_in = float(self.input_voltage_v)
        duty = tuple(float(v) for v in (duty_cycle if duty_cycle is not None else self.duty_cycle))
        if len(duty) != 2:
            raise RHONNError(f"duty_cycle 必须为二元组，实际为 {duty!r}")
        _, d2 = duty

        l_h = float(self.inductance_h)
        c_out = float(self.output_capacitance_f)
        return np.asarray(
            [
                [(1.0 - d2) * v_in * dt * dt / (2.0 * l_h * c_out), -i_l * dt / c_out],
                [v_in * dt / l_h, v_out * dt / l_h],
            ],
            dtype=float,
        )

    def zero_control_delta(
        self,
        *,
        output_voltage_v: float,
        inductor_current_a: float,
        sample_time_s: float,
        sink_current_a: float = 0.0,
    ) -> np.ndarray:
        """**零控制**（``d1 = d2 = 0``）下的一步状态增量 ``Δx = g(x, x̂, 0) − x``。

        与 :meth:`target_b_at` 同源——两者都直接取自变流器平均模型的解析式
        （``dc_dc_converter._derivatives``）::

            di_L/dt   = ( d1·v_in − (1−d2)·v_out − R_L·i_L ) / L
            dv_out/dt = ( (1−d2)·i_L − i_sink ) / C_out

        取 ``d1 = d2 = 0`` 即得 ``di_L/dt = −(v_out + R_L·i_L)/L``、
        ``dv_out/dt = (i_L − i_sink)/C_out``。

        求值口径：**积分形式，不是矩形法**（2026-11-08 修正，见下）
        ------------------------------------------------------
        ``i_L`` 在这一拍内**不是常数**（零控制下它按 ``A₀ = −(v_out+R_L·i_L)/L``
        线性衰减），故 ``Δv_out`` 必须对 ``i_L(t) = i_L + A₀·t`` 积分::

            Δv_out = ∫₀^dt ( i_L(t) − i_sink ) dt / C_out
                   = ( i_L − i_sink )·dt / C_out  +  A₀·dt² / (2·C_out)
                     └─────── 一阶项（矩形）──────┘  └── 二阶项（三角）──┘

        二阶项与 ``∂v_out/∂d1 = (1−d2)·v_in·dt²/(2LC)``（:meth:`target_b_at`）
        **是同一个积分结构的两半**：前者是「漂移让 i_L 自己变化」贡献的电荷，
        后者是「``d1`` 让 i_L 变化」贡献的电荷。只取后者会在 ``u_eq`` 里凭空
        多出一份电压增益。

        为什么漏掉它不是二阶小量（2026-11-08）
        ----------------------------------------
        直觉上 ``dt²`` 因子让二阶项可忽略，但稳态下::

            d1·v_in/L  ≈  −A₀      （``d1`` 抬升 i_L 的速率恰被 i_L 的自然衰减抵消）

        二者**大小几乎相等、符号相反**：补偿项 ``A₀·dt²/(2C)`` 与被漏掉的
        ``(dt²/2C)·(v_in·d1/L)`` 同量级，相加后本应≈0。只保留后者 ⟹ ``u_eq``
        以为 ``d1`` 每拍能抬高约 ``2.1 V``（``dt = 2e-4``），实际抬不动 ⟹
        一步死拍反解出的 ``d2`` 偏大 ⟹ 稳态母线比参考**低 2.1 V**、``d2`` 停在
        ``0.061``（旁路 6% 电感电流）。

        后果被储能母线的刚性放大：``P = v·(v − V_oc)/R_int``、
        ``dP/dv = (2v − V_oc)/R_int ≈ 58 kW/V``。于是

        ========== =============== ================= ==================
        ``dt``     电压缺口         功率缺口           对 SMC 的能量差
        ========== =============== ================= ==================
        ``1e-4``   ``0.5 V``       ``33 kW``（0.984） ``1.6%``
        ``2e-4``   ``2.1 V``       ``124 kW``（0.938）``6.2%``
        ========== =============== ================= ==================

        交付口径 ``dt = 1e-4``，所以对外看得到的只有 1.6%——但那不是「控制律
        稍差一点」，而是同一个缺陷按 ``dt²`` 缩小的结果。1+1 编组（可回收
        ~3.5 MW > 储能 2 MW）之所以让这个缺口**第一次在能量上可见**，是因为
        1 台机车时上限不绑定、参考量幅值小，同样的电压偏差对应的功率差被
        「精确填满需求侧参考」的收益盖住了。

        补上二阶项后实测 ``P_acc/P_ref = 1.00000``、``v_out`` 逐位等于
        ``v_ref``、``d2`` 回落到 ``0.00000``（即方案 ``modes.regen_charge``
        的「T2 置 0」），且能量对 ``dt`` 不再敏感（1e-4/2e-4/5e-4：
        4.2156/4.2156/4.2159 kWh）。见
        ``tools/probe_zero_control_second_order.py``。

        为什么需要它
        ------------
        ``u_eq = B⁺·(x_ref − g(x_k, x̂_k, 0))`` 里的 ``g(·, 0)`` 原本取
        :meth:`RHONN.predict`——即**未收敛的辨识模型**的零控制外推。辨识尚未收敛时
        该外推不可信，而它恰好是 ``u_eq`` 的**唯一**驱动项，于是一个失真的漂移
        会被 ``B⁺`` 放大成荒谬的 ``u_eq``（实测 ``s1_flat_braking`` 第 0 拍：
        ``u_eq = (49.5, −65.0)``，``‖u_eq‖ = 81.8 ≫ u_0 = 0.9``）。
        本方法改用**已知的被控对象模型**给出零控制预测，不依赖辨识收敛。

        一步死拍控制**没有积分作用**，模型漂移的误差会**原样变成稳态偏差**
        （``x_∞ = x_ref − 漂移误差``），所以这里必须把模型算准——这也是本轮把
        积分口径补齐的动机。

        ``i_L`` 的一步结果按**续流二极管的单向性**截到非负
        （``i_L < 0`` 时由二极管截断并保持），与被控对象 ``_derivatives`` 里
        ``i_l_coupled`` 的处理一致。二阶项用**截断后**的 ``Δi_L``，保证「二极管
        截断后 i_L 不再变化 ⟹ 不再向电容充电」这一物理事实不被绕过。

        Args:
            output_voltage_v: 当前 ``v_out``（V）。
            inductor_current_a: 当前 ``i_L``（A）。
            sample_time_s: 仿真步长 ``dt``（s）。
            sink_current_a: 储能侧吸收电流（A）。它是**外部边界**而非控制通道，
                给不出时取 0——保守做法：零控制下 ``i_L = 0`` 时 ``v_out`` 的变化
                只由 sink 引起，控制器无法通过占空比影响它。
        """
        dt = float(sample_time_s)
        if not np.isfinite(dt) or dt <= 0.0:
            raise RHONNError(f"sample_time_s 必须为正有限值，实际为 {sample_time_s!r}")
        v_out = float(output_voltage_v)
        if not np.isfinite(v_out) or v_out <= 0.0:
            raise RHONNError(f"output_voltage_v 必须为正有限值，实际为 {output_voltage_v!r}")
        i_l = float(inductor_current_a)
        if not np.isfinite(i_l):
            raise RHONNError(f"inductor_current_a 必须为有限值，实际为 {inductor_current_a!r}")
        i_sink = float(sink_current_a)
        if not np.isfinite(i_sink):
            i_sink = 0.0

        l_h = float(self.inductance_h)
        c_out = float(self.output_capacitance_f)
        r_l = float(self.inductor_resistance_ohm)

        di_l_dt = -(v_out + r_l * i_l) / l_h
        # 二极管单向性：i_L 一步后为负则由二极管截断并保持，故增量被截到 −i_L。
        delta_i_l = max(-i_l, di_l_dt * dt)
        # 电容电荷 = ∫i_L dt − i_sink·dt = (i_L + Δi_L/2)·dt − i_sink·dt。
        # 第二项就是 2026-11-08 修正补上的三角积分项；用截断后的 Δi_L，
        # 二极管截断后不再有额外电荷进入电容。
        delta_v_out = (max(i_l, 0.0) - i_sink) * dt / c_out + 0.5 * delta_i_l * dt / c_out
        return np.asarray([delta_v_out, delta_i_l], dtype=float)


@dataclass(frozen=True)
class ControlChannelGainPrior:
    """控制通道增益先验：``B = ∂x̂/∂u`` 的**幅值**目标（方案问题 18 裁定）。

    方案问题 15 的符号先验只把 ``B`` 的**符号**钉住，没有约束**幅值**。实测
    （族 7 闭环，``dt = 4e-4``）辨识出的 ``∂i_L/∂d1`` 只有被控对象真值的 ``0.21×``，
    于是 ``u_eq = B⁺(x_ref − g)`` 被放大 ``≈ 5×``、恒 ``≫ u_0``，保方向饱和每拍触发、
    ``u_n`` 被淹没，闭环被推到 ``i_L = 1.5×`` 额定、``v_out`` 越窗。

    本类给出 ``B`` 的目标幅值，由变流器平均模型的**小信号增益**直接推出
    （provenance = **derived**，无自由参数）::

        B_target = [[ (1−d2)·v_in·dt² / (2·L·C_out),   −i_L·dt / C_out ],
                    [ v_in·dt / L,                      v_out·dt / L   ]]

    行 = 状态向量 ``(v_out, i_L)``，列 = 控制 ``(d1, d2)``。前三个元素是一阶增益
    （``dt`` 阶），``∂v_out/∂d1`` 是唯一的二阶项——因为 ``d1`` 在一阶意义下
    **不出现**于 ``dv_out`` 方程（``dv_out/dt = ((1−d2)·i_L − i_sink)/C_out``），
    取二阶 RK4 耦合项 ``A·B·dt²/2`` 是为了让该通道有一个**正的、由模型推出**的幅值；
    若取 0，符号先验（要求 ``∂v_out/∂d1 > 0``）会与幅值先验冲突：符号先验翻转的是
    **整列**权重（列 2、4 一起取反），会把同列的 ``∂i_L/∂d1`` 一起翻反。

    .. note::
       热启动只是**初值**：在线辨识随后仍会自由地改 ``B`` 的幅值与符号
       （问题 15 修正后 ``B`` 含可调权重）。本类不约束任何在线更新。
    """

    #: 目标 ``B`` 矩阵（``state_dim × control_dim``），单位与 ``∂x̂/∂u`` 相同。
    target_b: Tuple[Tuple[float, ...], ...]
    #: 目标成立的标称状态（与 :data:`STATE_LABELS` 同坐标）。
    nominal_state: Tuple[float, ...]
    #: 目标成立的标称控制（占空比）。
    nominal_control: Tuple[float, ...]
    #: 计算 ``B_target`` 时所用的采样步长（s）。
    sample_time_s: float
    #: 数据状态标记（本类恒为 derived：由已知模型推出）。
    data_status: str = "derived"
    #: 推导来源说明。
    provenance: str = ""
    #: 重算 ``B_target`` 所需的模型信息（问题 19 裁定）。为 ``None`` 时只能使用
    #: ``target_b``（标称点值），:meth:`target_b_at` 会抛错——这保证「想按当前工作点
    #: 求值」的调用方不会静默拿到标称点值。
    model: Optional[ControlChannelModel] = None

    def target_b_at(
        self,
        *,
        output_voltage_v: float,
        inductor_current_a: float,
        input_voltage_v: Optional[float] = None,
        duty_cycle: Optional[Sequence[float]] = None,
    ) -> np.ndarray:
        """在**当前工作点**重算目标 ``B``（问题 19 裁定）。

        ``B_target`` 是状态相关的（``∂v_out/∂d2 = −i_L·dt/C_out``、
        ``∂i_L/∂d2 = v_out·dt/L``），而 :attr:`target_b` 只在 :attr:`nominal_state`
        处精确。等效控制需要**当前点**的 ``B``，否则符号可能相反——见
        :class:`ControlChannelModel` 的说明。
        """
        if self.model is None:
            raise RHONNError(
                "本 ControlChannelGainPrior 未携带 model，无法按当前工作点重算 B_target；"
                "请用 from_converter_gains / from_converter_params 构造。"
            )
        return self.model.target_b_at(
            output_voltage_v=output_voltage_v,
            inductor_current_a=inductor_current_a,
            input_voltage_v=input_voltage_v,
            sample_time_s=self.sample_time_s,
            duty_cycle=duty_cycle,
        )

    def zero_control_delta(
        self,
        *,
        output_voltage_v: float,
        inductor_current_a: float,
        sink_current_a: float = 0.0,
    ) -> np.ndarray:
        """零控制一步状态增量（问题 20 / 35 裁定）。

        转发到 :meth:`ControlChannelModel.zero_control_delta`，步长取
        :attr:`sample_time_s`——与 :meth:`target_b_at` 用的是**同一个** ``dt``。
        注意「同一个 ``dt``」只是量纲对齐的必要条件，**不充分**：
        ``Δv_out`` 还必须是同一套**积分格式**（矩形 + 三角），少了三角项会让
        ``u_eq`` 凭空多出 ``2.1 V`` 的电压增益（问题 35，2026-11-08）。
        """
        if self.model is None:
            raise RHONNError(
                "本 ControlChannelGainPrior 未携带 model，无法给出零控制预测；"
                "请用 from_converter_gains / from_converter_params 构造。"
            )
        return self.model.zero_control_delta(
            output_voltage_v=output_voltage_v,
            inductor_current_a=inductor_current_a,
            sample_time_s=self.sample_time_s,
            sink_current_a=sink_current_a,
        )

    def __post_init__(self) -> None:
        target = np.asarray(self.target_b, dtype=float)
        if target.ndim != 2 or target.shape[0] < 1 or target.shape[1] < 1:
            raise RHONNError("ControlChannelGainPrior.target_b 必须是二维非空矩阵")
        if not np.all(np.isfinite(target)):
            raise RHONNError("ControlChannelGainPrior.target_b 必须全部为有限值")
        if len(self.nominal_state) != target.shape[0]:
            raise RHONNError(
                "ControlChannelGainPrior.nominal_state 长度必须等于 target_b 的行数，"
                f"实际为 {len(self.nominal_state)} vs {target.shape[0]}"
            )
        if len(self.nominal_control) != target.shape[1]:
            raise RHONNError(
                "ControlChannelGainPrior.nominal_control 长度必须等于 target_b 的列数，"
                f"实际为 {len(self.nominal_control)} vs {target.shape[1]}"
            )
        for name, values in (
            ("nominal_state", self.nominal_state),
            ("nominal_control", self.nominal_control),
        ):
            if not np.all(np.isfinite(np.asarray(values, dtype=float))):
                raise RHONNError(f"ControlChannelGainPrior.{name} 必须全部为有限值")
        if not np.isfinite(self.sample_time_s) or self.sample_time_s <= 0.0:
            raise RHONNError(
                f"ControlChannelGainPrior.sample_time_s 必须为正有限值，实际为 {self.sample_time_s!r}"
            )

    @classmethod
    def from_converter_gains(
        cls,
        *,
        inductance_h: float,
        output_capacitance_f: float,
        input_voltage_v: float,
        output_voltage_v: float,
        inductor_current_a: float,
        sample_time_s: float,
        inductor_resistance_ohm: float = 0.0,
        duty_cycle: Optional[Sequence[float]] = None,
        provenance: str = "",
    ) -> "ControlChannelGainPrior":
        """按变流器平均模型的一步小信号增益构造目标 ``B``。

        参数全部取自项目已有的被控对象参数文件（``dc_dc_parameters.json``），
        **无自由参数**；``duty_cycle`` 省略时取 :data:`DEFAULT_NOMINAL_DUTY`。

        Args:
            inductance_h: 电感 ``L``（H）。
            output_capacitance_f: 输出侧电容 ``C_out``（F）。
            input_voltage_v: 标称输入（直流母线）电压 ``v_in``（V）。
            output_voltage_v: 标称输出（储能侧）电压 ``v_out``（V）。
            inductor_current_a: 标称电感电流 ``i_L``（A）。
            sample_time_s: 采样步长 ``dt``（s）。
            inductor_resistance_ohm: 电感等效串联电阻 ``R_L``（Ω）。**不参与** ``B``
                （小信号增益里没有它），只透传给 :meth:`ControlChannelModel.zero_control_delta`
                的零控制预测。允许为 0。
            duty_cycle: 标称占空比 ``(d1, d2)``。
            provenance: 覆盖默认推导说明。
        """
        for name, value in (
            ("inductance_h", inductance_h),
            ("output_capacitance_f", output_capacitance_f),
            ("input_voltage_v", input_voltage_v),
            ("output_voltage_v", output_voltage_v),
            ("inductor_current_a", inductor_current_a),
            ("sample_time_s", sample_time_s),
        ):
            value = float(value)
            if not np.isfinite(value) or value <= 0.0:
                raise RHONNError(f"{name} 必须为正有限值，实际为 {value!r}")
        r_l = float(inductor_resistance_ohm)
        if not np.isfinite(r_l) or r_l < 0.0:
            raise RHONNError(f"inductor_resistance_ohm 必须为非负有限值，实际为 {r_l!r}")

        duty = tuple(float(v) for v in (duty_cycle if duty_cycle is not None else DEFAULT_NOMINAL_DUTY))
        if len(duty) != 2:
            raise RHONNError(f"duty_cycle 必须为二元组，实际为 {duty!r}")
        d1, d2 = duty

        l_h = float(inductance_h)
        c_out = float(output_capacitance_f)
        v_in = float(input_voltage_v)
        v_out = float(output_voltage_v)
        i_l = float(inductor_current_a)
        dt = float(sample_time_s)

        # 一阶（dt 阶）小信号增益 —— 由 dc_dc_converter._derivatives 直接读出:
        #   di_L/dt = (d1·v_in − (1−d2)·v_out − R_L·i_L) / L
        #   dv_out/dt = ((1−d2)·i_L − i_sink) / C_out
        di_l_dd1 = v_in * dt / l_h
        di_l_dd2 = v_out * dt / l_h
        dv_out_dd2 = -i_l * dt / c_out
        # ∂v_out/∂d1：一阶为 0（d1 不出现在 dv_out 方程），取 RK4 二阶耦合项
        # (1−d2)·v_in·dt²/(2·L·C_out) —— 恒为正，与符号先验一致。
        dv_out_dd1 = (1.0 - d2) * v_in * dt * dt / (2.0 * l_h * c_out)

        target = (
            (dv_out_dd1, dv_out_dd2),
            (di_l_dd1, di_l_dd2),
        )
        return cls(
            target_b=target,
            nominal_state=(v_out, i_l),
            nominal_control=duty,
            sample_time_s=dt,
            model=ControlChannelModel(
                inductance_h=l_h,
                output_capacitance_f=c_out,
                input_voltage_v=v_in,
                inductor_resistance_ohm=r_l,
                duty_cycle=duty,
            ),
            provenance=provenance
            or (
                "由 dc_dc_converter._derivatives 的一步小信号增益推出："
                "∂i_L/∂d1 = v_in·dt/L、∂i_L/∂d2 = v_out·dt/L、∂v_out/∂d2 = −i_L·dt/C_out、"
                "∂v_out/∂d1 = (1−d2)·v_in·dt²/(2·L·C_out)（唯一二阶项，见类说明）"
            ),
        )

    @classmethod
    def from_converter_params(
        cls,
        params,
        sample_time_s: float,
        *,
        duty_cycle: Optional[Sequence[float]] = None,
    ) -> "ControlChannelGainPrior":
        """从被控对象的参数对象取标称点，保证控制器与对象同源。

        ``params`` 是 :class:`~regenerative_braking.dynamics.dc_dc_converter.DCConverterParameters`
        （只按属性名鸭子类型使用，不导入该类，避免循环依赖——与
        :meth:`~regenerative_braking.tracking.RegenerativeReferenceState.from_converter_params`
        同一纪律）。
        """
        return cls.from_converter_gains(
            inductance_h=params.inductance_h,
            output_capacitance_f=params.output_capacitance_f,
            input_voltage_v=params.input_voltage_nominal_v,
            output_voltage_v=params.output_voltage_nominal_v,
            inductor_current_a=params.max_output_current_a,
            sample_time_s=sample_time_s,
            inductor_resistance_ohm=getattr(params, "inductor_resistance_ohm", 0.0),
            duty_cycle=duty_cycle,
        )


@dataclass(frozen=True)
class RHONNConfig:
    """RHONN 结构与数值配置。"""

    state_dim: int = 2
    control_dim: int = 2

    #: 基函数 S(·) = tanh(α·z + β)
    alpha: float = 1.0
    beta: float = 0.0

    #: 归一化参考尺度（derived：阶段 1/2 仿真时序的中心量级）
    #: 状态向量为 ``(v_out, i_L)``，故第 2 项是**电感电流**尺度（不是输出电流）。
    state_scale: Tuple[float, ...] = (1400.0, 1500.0)
    control_scale: Tuple[float, ...] = (1.0, 1.0)

    #: 可调权重的确定性初始化幅度与种子（保证可复现）
    weight_init_scale: float = 0.1
    seed: int = 20260924

    #: 控制通道符号先验（方案问题 15 的自锁打破机制）。
    #:
    #: 在**初始化**阶段按被控对象的已知小信号模型给 ``B`` 定符号，
    #: 从而打破「``u_eq`` 方向被带反 ⟹ 占空比截断为 0 ⟹ 通道无激励 ⟹ ``B`` 不可辨识」
    #: 的自锁。置 ``None`` 可关闭，退回「符号由随机初值决定」的未修正行为。
    control_channel_sign_prior: Optional[Tuple[Tuple[int, ...], ...]] = CONTROL_CHANNEL_SIGN_PRIOR

    #: 是否把上述符号作为**参数投影**在每次权重更新后持续施加。
    #:
    #: **默认关闭**（编写人授权自行修正时实测的结论）：
    #:
    #: * 控制通道的**持续激励**在闭环里通常是有保证的——控制器一旦把 ``u`` 动起来，
    #:   数据就会把 ``B`` 拉向真值，符号不必靠外部约束维持；
    #: * 该投影是一次**不连续反射**（整列权重取反），实测会
    #:   ① 打断 EKF/UKF 的平滑收敛（辨识误差从 1.4% 恶化到 16%、``η ≥ 0.05`` 时发散）；
    #:   ② 破坏 **UKF ≡ EKF** 的结构性等价（微小数值差在翻转边界被放大）；
    #:   ③ 且只保证**标称点**的符号，其它工作点仍有约 20% 越界。
    #:
    #: 置 ``True`` 可作为「低激励工况」（如 ``u`` 长期恒定）的可选加固，但需接受上述代价。
    enforce_control_channel_sign: bool = False

    #: 控制通道**增益**先验（方案问题 18 裁定）：``B`` 的幅值目标。
    #:
    #: 符号先验只钉住符号，不约束幅值；实测辨识出的 ``∂i_L/∂d1`` 只有真值的 ``0.21×``，
    #: 使 ``u_eq`` 被放大 ``≈5×``、保方向饱和恒触发。本字段把「用已知模型热启动」
    #: 补全到幅值（见 :class:`ControlChannelGainPrior`）。
    #:
    #: **默认 ``None``**：本模块不自行猜采样步长。装配层
    #: （:func:`~regenerative_braking.simulation.closed_loop.build_closed_loop_controller`）
    #: 会用真实 ``dt`` 与变流器参数构造一个先验注入；直接构造 ``RHONNConfig()``
    #: 的调用方（单元测试、回归对比）默认退回「仅符号先验」的旧行为。
    control_channel_gain_prior: Optional[ControlChannelGainPrior] = None

    #: 是否在增益先验热启动时**同时**把标称工作点的输出钉住（``x̂(nominal) = nominal_state``）。
    #:
    #: **默认关闭**（实测否决，记录如下，勿轻易打开）：
    #:
    #: 直觉上「只对齐 ``B`` 不管输出」会让网络在标称点上预测出与真值相差
    #: 上千伏/上千安的值（实测 ``x̂(nominal) = (51 V, 1344 A)`` vs 真值
    #: ``(1100 V, 3000 A)``），似乎应当补上。但 ``W_par`` 不出现在 ``B`` 里，
    #: 补上这一步在数学上完全可行（``ΔW_par = outer(d, φ_par)/‖φ_par‖²``，
    #: 两个方程可分别精确求解，残差 ``~1e-16``）。
    #:
    #: 实测结果（族 7，``dt=4e-4``，三路径对照）::
    #:
    #:     只对齐 B      相对偏差 2.45e-1   i_L 峰值 0.37× 额定  v_out 1120.1 V（窗内）
    #:     再对齐输出     相对偏差 1.68       i_L 峰值 1.22× 额定  v_out 1536.6 V（越窗）
    #:
    #: 即：输出对齐把固定 EKF / 固定 UKF 两条路径推出了**物理包络**，是净损失。
    #: 机制（假说，未单独验证）：``x̂(nominal) = nominal_state`` 是在标称点上强加一个
    #: **不动点**，而真实被控对象在标称点并不停住（储能持续充电、``v_out`` 持续漂移）；
    #: 于是该约束在工况偏离标称后变成系统性偏差，滤波器必须反过来对抗它。
    #: 保留本开关是为了让上述实测可复现、可重测，不作为推荐配置。
    gain_prior_align_nominal_output: bool = False

    def __post_init__(self) -> None:
        if self.state_dim < 1 or self.control_dim < 1:
            raise RHONNError("state_dim 与 control_dim 必须为正")
        if not np.isfinite(self.alpha) or self.alpha <= 0.0:
            raise RHONNError("alpha 必须为正有限值")
        if not np.isfinite(self.beta):
            raise RHONNError("beta 必须为有限值")
        if len(self.state_scale) != self.state_dim:
            raise RHONNError("state_scale 长度必须等于 state_dim")
        if len(self.control_scale) != self.control_dim:
            raise RHONNError("control_scale 长度必须等于 control_dim")
        for name, scale in (("state_scale", self.state_scale), ("control_scale", self.control_scale)):
            for value in scale:
                if not np.isfinite(value) or value <= 0.0:
                    raise RHONNError(f"{name} 的每一项都必须为正有限值，实际含 {value!r}")
        if not np.isfinite(self.weight_init_scale) or self.weight_init_scale < 0.0:
            raise RHONNError("weight_init_scale 必须为非负有限值")
        prior = self.control_channel_sign_prior
        if prior is not None:
            if len(prior) != self.state_dim:
                raise RHONNError(
                    f"control_channel_sign_prior 行数必须等于 state_dim，实际为 {len(prior)}"
                )
            for row in prior:
                if len(row) != self.control_dim:
                    raise RHONNError(
                        "control_channel_sign_prior 每行长度必须等于 control_dim，"
                        f"实际为 {len(row)}"
                    )
                for sign in row:
                    if int(sign) not in (-1, 1):
                        raise RHONNError(
                            f"control_channel_sign_prior 的每一项必须是 +1 或 -1，实际含 {sign!r}"
                        )
        gain_prior = self.control_channel_gain_prior
        if gain_prior is not None:
            target = np.asarray(gain_prior.target_b, dtype=float)
            if target.shape != (self.state_dim, self.control_dim):
                raise RHONNError(
                    "control_channel_gain_prior.target_b 形状必须为 "
                    f"{(self.state_dim, self.control_dim)}，实际为 {target.shape}"
                )
            if len(gain_prior.nominal_state) != self.state_dim:
                raise RHONNError(
                    "control_channel_gain_prior.nominal_state 长度必须等于 state_dim，"
                    f"实际为 {len(gain_prior.nominal_state)}"
                )
            if len(gain_prior.nominal_control) != self.control_dim:
                raise RHONNError(
                    "control_channel_gain_prior.nominal_control 长度必须等于 control_dim，"
                    f"实际为 {len(gain_prior.nominal_control)}"
                )


@dataclass
class RHONNStepRecord:
    """单步递归的可记录量（对应方案的输出契约字段）。"""

    time_s: float
    state_actual: np.ndarray
    state_estimate: np.ndarray
    prediction_error: np.ndarray
    control: np.ndarray
    weights: np.ndarray


@dataclass(frozen=True)
class PredictionContext:
    """产生某一次预测时的输入上下文。

    滤波器（EKF/UKF）在校正权重时必须知道这次预测是在**哪个状态点**上算出来的。

    方案里 ``e_{i,k} = x_{i,k} − x̂_{i,k}``，而 ``x̂_{i,k}`` 是 k−1 时刻由
    ``x_{k−1}`` 产生的；因此 ``H = ∂x̂_{i,k}/∂ω`` 应在 ``x_{k−1}`` 处取值，
    而**不是**在当前量测 ``x_k`` 处。把这三元组显式带出来，
    滤波器才不会在动态工况下误用「晚一步」的雅可比。

    在静止工况下 ``x_{k−1} ≈ x_k``，两者数值接近；但制动起始、电流突变等
    动态工况下差异不可忽略，故不做隐式近似。
    """

    state_actual: np.ndarray
    state_estimate_prev: np.ndarray
    control: np.ndarray


class RHONN:
    """串联-并联离散递归高阶神经网络（方案 §4.2.1.3（1））。

    结构::

        φ_par(x_k)      = tanh(α · P_par · (x_k ⊘ state_scale) + β)             ∈ R^4
        φ_ser(x̂_k, u_k) = tanh(α · P_ser · ([x̂_k, u_k] ⊘ scale) + β)            ∈ R^6

        x̂_{k+1} = W_par · φ_par(x_k) + W_ser · φ_ser(x̂_k, u_k)

    **两条路径的权重都是可调的**（方案问题 15 已修正）：它们被拼成一个
    参数向量 ``[W_par | W_ser]``（形状 ``state_dim × (n_par + n_ser)``）
    交给 EKF/UKF 在线训练，``n_tunable_weights = 2 × 10 = 20``。
    方案原文的 ``ω̄``（固定权重）在标准 RHONN 里不存在——见模块 docstring。

    对可调权重而言本网络是线性的，因此 ``jacobian_wrt_tunable_weights``
    就是基函数本身的稀疏展开——这正是方案中 ``H = ∂x/∂ω``（状态对权重的
    导数矩阵）的确切含义。

    状态向量语义为 ``(v_out, i_L)``（方案问题 16 已修正），见
    :data:`STATE_LABELS`；本类只按维度消费，不解释物理含义。
    """

    name = "rhonn"

    def __init__(
        self,
        config: Optional[RHONNConfig] = None,
        *,
        weights: Optional[Sequence[Sequence[float]]] = None,
        series_weights: Optional[Sequence[Sequence[float]]] = None,
        fixed_weights: Optional[Sequence[Sequence[float]]] = None,
    ) -> None:
        self.config = config or RHONNConfig()
        cfg = self.config

        n_par = len(PARALLEL_PROJECTIONS)
        n_ser = len(SERIES_PROJECTIONS)

        self._parallel_projections = np.asarray(PARALLEL_PROJECTIONS, dtype=float)
        self._series_projections = np.asarray(SERIES_PROJECTIONS, dtype=float)

        if self._parallel_projections.shape[1] != cfg.state_dim:
            raise RHONNError("并联投影维度与 state_dim 不一致")
        if self._series_projections.shape[1] != cfg.state_dim + cfg.control_dim:
            raise RHONNError("串联投影维度与 state_dim + control_dim 不一致")

        if fixed_weights is not None:
            if series_weights is not None:
                raise RHONNError("series_weights 与 fixed_weights 不能同时给出（fixed_weights 是旧名）")
            # 旧名兼容：``fixed_weights`` 现在只是「串联路径权重的初值」，
            # 该路径的权重已并入可调参数向量，会被 EKF/UKF 在线更新。
            series_weights = fixed_weights

        rng = np.random.default_rng(cfg.seed)

        if weights is None:
            self._weights = rng.normal(0.0, cfg.weight_init_scale, size=(cfg.state_dim, n_par))
        else:
            self._weights = self._as_weight_matrix(weights, (cfg.state_dim, n_par), "weights")

        if series_weights is None:
            self._series_weights = rng.normal(
                0.0, cfg.weight_init_scale, size=(cfg.state_dim, n_ser)
            )
        else:
            self._series_weights = self._as_weight_matrix(
                series_weights, (cfg.state_dim, n_ser), "series_weights"
            )

        self._state_scale = np.asarray(cfg.state_scale, dtype=float)
        self._control_scale = np.asarray(cfg.control_scale, dtype=float)

        self._state_estimate: Optional[np.ndarray] = None
        self._prediction_error: Optional[np.ndarray] = None
        self._last_prediction_context: Optional[PredictionContext] = None
        self._sign_prior_flips: Tuple[Tuple[bool, ...], ...] = tuple(
            tuple(False for _ in range(cfg.control_dim)) for _ in range(cfg.state_dim)
        )
        self._gain_prior_residual: float = float("nan")
        self._nominal_output_residual: float = float("nan")

        # 顺序不可颠倒：先按已知模型把 B 的**幅值**热启动到目标（问题 18），
        # 再对齐**符号**（问题 15）。目标 B 的符号本就与符号先验一致，
        # 故第二步在正常路径上是空操作；但若调用方显式关掉增益先验，
        # 第二步仍是打破「u ≡ 0 ⟹ 通道无激励 ⟹ B 不可辨识」自锁的唯一机制。
        self._gain_prior_residual = self._apply_control_channel_gain_prior()
        self._apply_control_channel_sign_prior()

    # ------------------------------------------------------------------
    # 控制通道先验（问题 15 的符号自锁打破 + 问题 18 的幅值热启动）
    # ------------------------------------------------------------------

    def _nominal_context(self) -> Tuple[np.ndarray, np.ndarray]:
        """先验（符号 / 增益）所用的标称工作点。

        有增益先验时返回先验自带的标称点（``nominal_state`` / ``nominal_control``）——
        符号对齐与幅值热启动必须在**同一个**点上评估，否则两者会互相打架
        （符号先验翻转整列权重，会把幅值热启动在同列另一行上刚建立的符号翻反）。
        没有增益先验时退回「网络工作点中心」（状态与控制都取 0），与修正前一致。

        也用作 :meth:`jacobian_wrt_tunable_weights` 省略输入时的默认取值点。
        """
        prior = self.config.control_channel_gain_prior
        if prior is not None:
            return (
                np.asarray(prior.nominal_state, dtype=float).copy(),
                np.asarray(prior.nominal_control, dtype=float).copy(),
            )
        return (
            np.zeros(self.config.state_dim, dtype=float),
            np.zeros(self.config.control_dim, dtype=float),
        )

    # ------------------------------------------------------------------
    # 控制通道增益先验（方案问题 18 的幅值热启动）
    # ------------------------------------------------------------------

    def _apply_control_channel_gain_prior(self) -> float:
        """按 :class:`ControlChannelGainPrior` 把 ``B`` 的**幅值**热启动到目标值。

        做法（最小范数解，不引入任何自由参数）::

            B = diag(state_scale) · W_ser · ∂φ_ser/∂u
            ⇒ 需要   W_ser · ∂φ_ser/∂u = B_target ⊘ state_scale
            ⇒ ΔW_ser = (desired − W_ser·∂φ_ser/∂u) · pinv(∂φ_ser/∂u)

        ``∂φ_ser/∂u`` 是 ``n_ser × control_dim`` 的矩阵，其两列在
        :data:`SERIES_PROJECTIONS` 下**线性无关**（列 0 只在第 2、4 行非零，
        列 1 只在第 3、5 行非零），故该方程有解、且 ``pinv`` 给出最小范数解——
        即「在改动最小的前提下把 ``B`` 调到目标」。

        返回热启动后 ``B`` 相对目标的残差（``‖B−B_target‖ / ‖B_target‖``），
        供 :meth:`audit` 与测试核对；无先验时返回 ``nan``。

        .. note::
           本操作只在**初始化**阶段做一次，不进入 :meth:`update_weights`，
           因此不构成对在线辨识的持续约束（与
           :attr:`RHONNConfig.enforce_control_channel_sign` 默认关闭的理由一致）。
        """
        prior = self.config.control_channel_gain_prior
        if prior is None:
            self._nominal_output_residual = float("nan")
            return float("nan")

        state_nom = np.asarray(prior.nominal_state, dtype=float)
        control_nom = np.asarray(prior.nominal_control, dtype=float)
        target = np.asarray(prior.target_b, dtype=float)

        # 幅值热启动：只用串联路径权重（B = ∂x̂/∂u 只经串联路径）
        phi_ser = self.series_basis(state_nom, control_nom)
        dphi = self.config.alpha * (1.0 - phi_ser**2)  # tanh 的导数
        control_projections = self._series_projections[:, self.config.state_dim :]
        dphi_du = (dphi[:, None] * control_projections) / self._control_scale

        desired = target / self._state_scale[:, None]
        current = self._series_weights @ dphi_du
        self._series_weights = self._series_weights + (desired - current) @ np.linalg.pinv(dphi_du)

        # 可选加固（默认关闭）：把标称工作点的**输出**也钉住。
        # 见 RHONNConfig.gain_prior_align_nominal_output 的实测否决记录。
        if self.config.gain_prior_align_nominal_output:
            phi_par = self.parallel_basis(state_nom)
            d = state_nom / self._state_scale - self._series_weights @ phi_ser
            norm_sq = float(phi_par @ phi_par)
            if norm_sq > 0.0:
                self._weights = self._weights + np.outer(d, phi_par) / norm_sq

        predicted = self.predict(state_nom, state_nom, control_nom)
        self._nominal_output_residual = float(
            np.linalg.norm(predicted - state_nom) / max(np.linalg.norm(state_nom), 1e-30)
        )
        achieved = self.jacobian_wrt_control(state_nom, control_nom)
        scale = float(np.linalg.norm(target))
        if scale <= 0.0:
            return float("nan")
        return float(np.linalg.norm(achieved - target) / scale)

    def _align_control_channel_sign(self) -> np.ndarray:
        """把 ``B`` 在**标称点**的符号对齐到 :data:`CONTROL_CHANNEL_SIGN_PRIOR`。

        做法：对第 ``(n, m)`` 个通道，若标称点 ``B[n, m]`` 与先验异号，
        就把 ``W_ser`` 中**仅影响该通道**的那两列**一起**取反
        （``m = 0`` 时是第 2、4 列，``m = 1`` 时是第 3、5 列，见
        :data:`SERIES_COLUMNS_BY_CONTROL_CHANNEL`）。只改符号、不改幅度。

        **保证范围（重要，勿过度声明）**：两列一起取反等价于把
        ``B[n, m]`` **整体**取反（因为 ``B[n, m] = scale[n]/control_scale[m] · α · Σ_j W[n, j] · (1 − φ_j²)``，
        两个系数 ``(1 − φ_j²) > 0`` 同号），故对齐后**标称点**的符号必定正确。
        但**不保证**其它工作点：两个串联列可以合法地**异号**（部分抵消），
        此时加权和的符号会随两者的系数比例变化而翻转。实测 120 个随机种子
        × 6 工作点 × 6 控制，有 **72 个种子**（60%）在标称点之外至少一处越界。

        .. note::
           曾试过**逐列**翻到同号（可证明任意工作点都对齐，实测 0/120 越界），
           但那样会放大 ``|B|``（异号抵消消失），把联合闭环推进**数值混沌**区间：
           对协方差施加 1 ULP（``1e-16``）扰动，回收能量的相对变化从整组方案的
           ``1.9e-10`` 恶化到 ``6.6%``，并直接使
           ``test_family7_filter_variants_agree_with_the_switching_controller``
           （EKF/UKF 闭环一致性哨兵）失败。**主行为优先**，故保留整组方案。
           若将来闭环鲁棒性改善，可重新评估逐列方案。

        对齐只在**初始化**阶段做一次；随后 ``u`` 一旦动起来，在线辨识会把
        ``B`` 拉向真值（问题 15 修正后 ``B`` 含可调权重）。
        """
        prior = self.config.control_channel_sign_prior
        flips = np.zeros((self.config.state_dim, self.config.control_dim), dtype=bool)
        if prior is None:
            return flips

        state_nom, control_nom = self._nominal_context()
        b_matrix = self.jacobian_wrt_control(state_nom, control_nom)

        for n in range(self.config.state_dim):
            for m in range(self.config.control_dim):
                target = float(prior[n][m])
                current = float(b_matrix[n, m])
                # current == 0 时符号未定义：先验要求非零，此处也翻转一次，
                # 使该通道获得一个确定（而非随机）的符号。
                if current == 0.0 or np.sign(current) != target:
                    for j in SERIES_COLUMNS_BY_CONTROL_CHANNEL[m]:
                        self._series_weights[n, j] = -self._series_weights[n, j]
                    flips[n, m] = True
        return flips

    def _apply_control_channel_sign_prior(self) -> None:
        """初始化阶段施加符号先验，并记录哪些通道被翻转过。"""
        flips = self._align_control_channel_sign()
        self._sign_prior_flips = tuple(tuple(bool(v) for v in row) for row in flips)

    @property
    def sign_prior_flips(self) -> Tuple[Tuple[bool, ...], ...]:
        """初始化时被符号先验翻转过的通道（``True`` 表示该通道被翻转过）。"""
        return self._sign_prior_flips

    @property
    def gain_prior_residual(self) -> float:
        """增益先验热启动后 ``B`` 相对目标的残差（``‖B−B_target‖ / ‖B_target‖``）。

        无增益先验时为 ``nan``。正常路径上该值应为 ``O(1e-16)``——``∂φ_ser/∂u``
        的两列线性无关，方程有精确解；若显著大于 0，说明
        :data:`SERIES_PROJECTIONS` 或 ``state_scale`` / ``control_scale`` 被改坏了。
        """
        return float(self._gain_prior_residual)

    @property
    def nominal_output_residual(self) -> float:
        """增益先验热启动后「标称工作点预测」的相对残差。

        ``‖x̂(nominal) − nominal_state‖ / ‖nominal_state‖``；无先验时为 ``nan``。
        该值同样应为 ``O(1e-16)``——``W_par`` 与 ``B`` 解耦，两个方程可分别精确求解。
        它是 ① 的必要配套：只调 ``B`` 而不管输出，会让网络在标称点上预测出
        与真值相差上千伏/上千安的值（见 :meth:`_apply_control_channel_gain_prior`）。
        """
        return float(self._nominal_output_residual)

    def set_control_channel_gain_prior(
        self, prior: Optional[ControlChannelGainPrior]
    ) -> float:
        """**运行前**注入（或替换）控制通道增益先验，并立即按它热启动 ``B`` 的幅值。

        装配层在「已经拿到辨识器实例、但还没开始辨识」的场景需要这个入口：
        :class:`~regenerative_braking.simulation.closed_loop.ClosedLoopController`
        既可以接一个现成的辨识器，也可以自己装配一个，两条路径都要能用同一套先验。

        本方法只允许在**尚未产生任何预测**时调用——一旦滤波器已经按旧权重
        更新过协方差，突然平移权重会破坏 ``P`` 与权重的自洽性（``P`` 是**权重误差**
        的协方差，权重跳变后它不再描述同一件事）。若已开始辨识则直接报错，
        不静默接受。

        返回热启动残差（无先验时为 ``nan``）。
        """
        if self._state_estimate is not None or self._prediction_error is not None:
            raise RHONNError(
                "控制通道增益先验只能在辨识开始前注入：本 RHONN 已经产生过预测，"
                "此时平移权重会使 EKF/UKF 的协方差 P 不再描述同一组权重的误差。"
                "请在装配辨识器时（build_online_identifier 的 rhonn 配置）给出先验。"
            )
        if prior is not None:
            target = np.asarray(prior.target_b, dtype=float)
            if target.shape != (self.config.state_dim, self.config.control_dim):
                raise RHONNError(
                    "control_channel_gain_prior.target_b 形状必须为 "
                    f"{(self.config.state_dim, self.config.control_dim)}，实际为 {target.shape}"
                )
        self.config = replace(self.config, control_channel_gain_prior=prior)
        self._gain_prior_residual = self._apply_control_channel_gain_prior()
        self._apply_control_channel_sign_prior()
        return self._gain_prior_residual

    # ------------------------------------------------------------------
    # 维度与状态
    # ------------------------------------------------------------------

    @staticmethod
    def _as_weight_matrix(values: Sequence[Sequence[float]], shape: Tuple[int, int], name: str) -> np.ndarray:
        arr = np.asarray(values, dtype=float)
        if arr.shape != shape:
            raise RHONNError(f"{name} 形状必须为 {shape}，实际为 {arr.shape}")
        if not np.all(np.isfinite(arr)):
            raise RHONNError(f"{name} 必须全部为有限值")
        return arr.copy()

    @property
    def state_dim(self) -> int:
        return self.config.state_dim

    @property
    def control_dim(self) -> int:
        return self.config.control_dim

    @property
    def n_tunable_weights(self) -> int:
        """可调权重总数（= 方案中 EKF/UKF 的参数向量维度）。

        方案问题 15 修正后，两条路径的权重都进可调参数向量，
        故为 ``state_dim × (n_parallel_basis + n_series_basis) = 2 × 10 = 20``
        （修正前只有并联路径，为 8）。
        """
        return int(self._weights.size + self._series_weights.size)

    @property
    def n_parallel_weights(self) -> int:
        """并联路径可调权重数。"""
        return int(self._weights.size)

    @property
    def n_series_weights(self) -> int:
        """串联路径可调权重数（方案问题 15 修正后并入可调参数向量）。"""
        return int(self._series_weights.size)

    @property
    def n_fixed_weights(self) -> int:
        """**恒为 0**：标准 RHONN 不存在固定权重分支（方案问题 15 修正）。"""
        return 0

    @property
    def weights(self) -> np.ndarray:
        """并联路径权重 ``W_par`` 的副本（shape = (state_dim, n_parallel_basis)）。"""
        return self._weights.copy()

    @property
    def series_weights(self) -> np.ndarray:
        """串联路径权重 ``W_ser`` 的副本（shape = (state_dim, n_series_basis)）。

        .. note::
           这是**可调权重**（方案问题 15 修正前它是固定权重 ``ω̄``）。
        """
        return self._series_weights.copy()

    @property
    def fixed_weights(self) -> np.ndarray:
        """旧名兼容：等价于 :attr:`series_weights`（**已是可调权重**）。

        .. deprecated::
           方案原文的「固定权重 ω̄」在标准 RHONN 里不存在（方案问题 15），
           本属性只为兼容既有调用点而保留，新代码请用 :attr:`series_weights`。
        """
        return self.series_weights

    @property
    def tunable_weight_matrix(self) -> np.ndarray:
        """可调权重矩阵 ``[W_par | W_ser]`` 的副本（shape = (state_dim, n_par + n_ser)）。"""
        return np.concatenate([self._weights, self._series_weights], axis=1)

    @property
    def state_estimate(self) -> Optional[np.ndarray]:
        """上一时刻状态估计；未调用过 step/predict 时为 None。"""
        return None if self._state_estimate is None else self._state_estimate.copy()

    @property
    def prediction_error(self) -> Optional[np.ndarray]:
        """最近一次 step 的在线预测误差 e = x_actual - x̂。"""
        return None if self._prediction_error is None else self._prediction_error.copy()

    @property
    def last_prediction_context(self) -> Optional[PredictionContext]:
        """产生 :attr:`state_estimate` 的那次预测的输入上下文。

        滤波器据此在**正确的状态点**上取雅可比 / 传播 sigma 点，见
        :class:`PredictionContext`。
        """
        return self._last_prediction_context

    def reset(self) -> None:
        """清空递归状态（权重保留，供新一轮仿真复用同一辨识器）。"""
        self._state_estimate = None
        self._prediction_error = None
        self._last_prediction_context = None

    # ------------------------------------------------------------------
    # 基函数
    # ------------------------------------------------------------------

    def _normalise(self, values: np.ndarray, scale: np.ndarray, name: str) -> np.ndarray:
        arr = np.asarray(values, dtype=float)
        if arr.shape != scale.shape:
            raise RHONNError(f"{name} 形状必须为 {scale.shape}，实际为 {arr.shape}")
        if not np.all(np.isfinite(arr)):
            raise RHONNError(f"{name} 必须全部为有限值")
        return arr / scale

    def parallel_basis(self, state_actual: Sequence[float]) -> np.ndarray:
        """并联路径基函数 φ_par(x_k)，输入为**实际状态**。"""
        z = self._normalise(state_actual, self._state_scale, "state_actual")
        return np.tanh(self.config.alpha * (self._parallel_projections @ z) + self.config.beta)

    def series_basis(
        self, state_estimate_prev: Sequence[float], control: Sequence[float]
    ) -> np.ndarray:
        """串联路径基函数 φ_ser(x̂_k, u_k)，输入为**上一时刻估计 + 当前控制**。

        投影矩阵 :data:`SERIES_PROJECTIONS`、状态尺度 ``state_scale``、
        控制尺度 ``control_scale`` 均为本实现显式定义（方案问题 8 已修正，
        见模块 docstring）。
        """
        z_state = self._normalise(state_estimate_prev, self._state_scale, "state_estimate_prev")
        z_ctrl = self._normalise(control, self._control_scale, "control")
        z = np.concatenate([z_state, z_ctrl])
        return np.tanh(self.config.alpha * (self._series_projections @ z) + self.config.beta)

    # ------------------------------------------------------------------
    # 前向
    # ------------------------------------------------------------------

    def predict(
        self,
        state_actual: Sequence[float],
        state_estimate_prev: Sequence[float],
        control: Sequence[float],
    ) -> np.ndarray:
        """单步预测 x̂_{i,k+1}（物理量纲）。

        网络在**无量纲空间**内工作，输出再乘回参考尺度::

            ŷ        = W_par · φ_par(x_k) + W_ser · φ_ser(x̂_k, u_k)
            x̂_{k+1}  = state_scale ⊙ ŷ

        输入归一化与输出反归一化用的是同一套参考尺度，因此这是一个恒等的坐标
        变换，不改变方案公式 ``x̂ = ω^T φ + ω̄^T φ`` 的形式与结构。
        它解决的是一个纯数值问题：φ ∈ [-1, 1] 而状态是 ~1400 V / ~1500 A，
        若不缩放，权重必须被推到 ~10³ 量级才能输出物理量，
        初始权重（O(0.1)）到真值的距离过大，在线收敛会被严重拖慢。

        三个输入缺一不可——这是「串联-并联」结构的接口表达：
        ``state_actual`` 走并联路径，``state_estimate_prev`` 走串联路径。
        若实现退化为普通 MLP（只用实际状态），本接口会直接失去意义。
        """
        phi_par = self.parallel_basis(state_actual)
        phi_ser = self.series_basis(state_estimate_prev, control)
        normalised_output = self._weights @ phi_par + self._series_weights @ phi_ser
        return self._state_scale * normalised_output

    def _split_parameter_vector(self, weights: Sequence[float]) -> np.ndarray:
        """把展平的参数向量 ``[W_par | W_ser]`` 还原成 ``(state_dim, n_par + n_ser)``。"""
        arr = np.asarray(weights, dtype=float)
        if arr.size != self.n_tunable_weights:
            raise RHONNError(
                f"weights 元素数必须为 {self.n_tunable_weights}，实际为 {arr.size}"
            )
        if not np.all(np.isfinite(arr)):
            raise RHONNError("weights 必须全部为有限值")
        return arr.reshape(self.tunable_weight_matrix.shape)

    def predict_with_weights(
        self,
        weights: Sequence[Sequence[float]] | Sequence[float],
        state_actual: Sequence[float],
        state_estimate_prev: Sequence[float],
        control: Sequence[float],
    ) -> np.ndarray:
        """用**给定的**可调权重做一次预测，不写入网络内部状态。

        供 UKF 传播 sigma 点使用：每个 sigma 点是一组候选权重，
        需要在**不改变网络当前权重**的前提下算出对应的预测输出。
        这就是方案中量测方程 ``h(ω)`` 的实现。

        ``weights`` 可以是展平的 ``(n_tunable_weights,)``，也可以是
        ``(state_dim, n_par + n_ser)`` 矩阵；前半段是 ``W_par``、后半段是 ``W_ser``。
        """
        w_matrix = self._split_parameter_vector(weights)
        n_par = self._weights.shape[1]
        phi_par = self.parallel_basis(state_actual)
        phi_ser = self.series_basis(state_estimate_prev, control)
        normalised_output = w_matrix[:, :n_par] @ phi_par + w_matrix[:, n_par:] @ phi_ser
        return self._state_scale * normalised_output

    def jacobian_wrt_tunable_weights(
        self,
        state_actual: Sequence[float],
        state_estimate_prev: Optional[Sequence[float]] = None,
        control: Optional[Sequence[float]] = None,
    ) -> np.ndarray:
        """∂x̂/∂ω，即方案中的 H(i,k)（状态对权重的导数矩阵）。

        返回 shape ``(state_dim, n_tunable_weights)``。权重按 row-major 展平：
        索引 ``n * n_col + j`` 对应 ``[W_par | W_ser][n, j]``。

        因为 ``x̂_n = scale_n · Σ_j W[n, j] · φ_j``，故该雅可比是基函数的
        稀疏展开、每行带一个 ``state_scale`` 因子：第 n 行只在
        ``[n*n_col, (n+1)*n_col)`` 区间非零，该区间前半段填 ``φ_par``、
        后半段填 ``φ_ser``。

        .. note::
           方案问题 15 修正后，串联路径的基函数也进入本雅可比
           （修正前只展开并联路径，故 ``n_tunable_weights`` 为 8，现为 20）。
           因此本方法需要 ``φ_ser`` 的两个输入；省略时按标称点（全零）取值，
           与 :meth:`_nominal_context` 一致。调用方（EKF）应传
           ``PredictionContext`` 里的三元组，使 H 在**产生该预测的状态点**上取值。
        """
        phi_par = self.parallel_basis(state_actual)
        n_par = phi_par.size

        if state_estimate_prev is None or control is None:
            nominal_state, nominal_control = self._nominal_context()
            prev = nominal_state if state_estimate_prev is None else state_estimate_prev
            ctrl = nominal_control if control is None else control
        else:
            prev, ctrl = state_estimate_prev, control
        phi_ser = self.series_basis(prev, ctrl)
        n_ser = phi_ser.size

        n_col = n_par + n_ser
        jac = np.zeros((self.config.state_dim, self.config.state_dim * n_col), dtype=float)
        for n in range(self.config.state_dim):
            base = n * n_col
            jac[n, base : base + n_par] = self._state_scale[n] * phi_par
            jac[n, base + n_par : base + n_col] = self._state_scale[n] * phi_ser
        return jac

    def jacobian_wrt_control(
        self, state_estimate_prev: Sequence[float], control: Sequence[float]
    ) -> np.ndarray:
        """∂x̂/∂u，即辨识模型对控制输入的灵敏度矩阵 B。

        返回 shape ``(state_dim, control_dim)``。供滑模控制器构造等效控制量
        ``u_eq`` 使用（见 :mod:`regenerative_braking.control.nsmc`）。

        ``B = diag(state_scale) · W_ser · ∂φ_ser/∂u``，其中 ``W_ser`` 是
        **可调权重**（方案问题 15 修正）——这正是 ``B`` 能被在线辨识校正的前提；
        ``∂φ_ser/∂u`` 是 tanh 导数与串联投影中控制分量的逐元素乘积。
        """
        phi_ser = self.series_basis(state_estimate_prev, control)
        dphi = self.config.alpha * (1.0 - phi_ser**2)  # tanh 的导数
        control_projections = self._series_projections[:, self.config.state_dim :]
        dphi_du = (dphi[:, None] * control_projections) / self._control_scale
        return self._state_scale[:, None] * (self._series_weights @ dphi_du)

    # ------------------------------------------------------------------
    # 权重更新（供 EKF / UKF 调用）
    # ------------------------------------------------------------------

    def update_weights(self, parameter_update: Sequence[float]) -> np.ndarray:
        """按增量更新可调权重 ``[W_par | W_ser] ← [W_par | W_ser] + ΔW``。

        ``parameter_update`` 可以是展平的 ``(n_tunable_weights,)``，
        也可以是 ``(state_dim, n_par + n_ser)`` 矩阵（EKF/UKF 的自然形状）。

        返回更新后的可调权重矩阵副本。
        """
        arr = np.asarray(parameter_update, dtype=float)
        if arr.size != self.n_tunable_weights:
            raise RHONNError(
                f"parameter_update 元素数必须为 {self.n_tunable_weights}，实际为 {arr.size}"
            )
        if not np.all(np.isfinite(arr)):
            raise RHONNError("parameter_update 必须全部为有限值")
        delta = arr.reshape(self.tunable_weight_matrix.shape)
        n_par = self._weights.shape[1]
        self._weights = self._weights + delta[:, :n_par]
        self._series_weights = self._series_weights + delta[:, n_par:]

        # 参数投影：把 B 的符号保持在已知的物理一侧（见
        # RHONNConfig.enforce_control_channel_sign 的说明）。
        # 只翻转符号、不改幅度，故不改变本次更新的步长。
        if self.config.enforce_control_channel_sign:
            self._align_control_channel_sign()

        return self.tunable_weight_matrix

    # ------------------------------------------------------------------
    # 递归一步（仿真循环用）
    # ------------------------------------------------------------------

    def _as_state(self, values: Sequence[float], name: str) -> np.ndarray:
        """校验并转为状态向量（不做缩放）。"""
        arr = np.asarray(values, dtype=float)
        if arr.shape != self._state_scale.shape:
            raise RHONNError(f"{name} 形状必须为 {self._state_scale.shape}，实际为 {arr.shape}")
        if not np.all(np.isfinite(arr)):
            raise RHONNError(f"{name} 必须全部为有限值")
        return arr

    def step(
        self,
        state_actual: Sequence[float],
        control: Sequence[float],
        *,
        time_s: float = 0.0,
    ) -> RHONNStepRecord:
        """推进一个采样步。

        时序与方案的 ``x̂_{i,k+1} = f(x_k, u_k)`` 一致::

            进入时 self._state_estimate 保存的是上一时刻对**本时刻**的预测 x̂_k
              1. 在线误差  e_k = x_k - x̂_k        （首步无历史预测，e_k = 0）
              2. 新预测    x̂_{k+1} = f(x_k, x̂_k, u_k)
              3. 递归项更新为 x̂_{k+1}

        递归项（串联路径的输入）取的是**上一时刻的预测**，而不是实际状态——
        这正是「串联」的含义：用估计值构成递归回路。
        """
        actual = self._as_state(state_actual, "state_actual")

        prev_prediction = self._state_estimate
        if prev_prediction is None:
            # 首步没有历史预测，误差未定义（恒为 0），递归项用实际状态初始化
            prev_prediction = actual

        control_arr = np.asarray(control, dtype=float).copy()
        error = actual - prev_prediction
        estimate = self.predict(actual, prev_prediction, control_arr)

        self._state_estimate = estimate
        self._prediction_error = error
        # 记录本次预测的输入上下文：下一次 step 的滤波器要在这三点上
        # 取雅可比 / 传播 sigma 点，见 PredictionContext。
        self._last_prediction_context = PredictionContext(
            state_actual=actual.copy(),
            state_estimate_prev=np.asarray(prev_prediction, dtype=float).copy(),
            control=control_arr,
        )

        return RHONNStepRecord(
            time_s=float(time_s),
            state_actual=actual.copy(),
            state_estimate=estimate.copy(),
            prediction_error=error.copy(),
            control=control_arr.copy(),
            weights=self.tunable_weight_matrix,
        )
