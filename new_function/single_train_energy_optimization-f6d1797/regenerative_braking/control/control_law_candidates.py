"""控制律候选：问题 14(a) 的**正式口径**与**被否决读法**，以及两条备选读法。

背景
----
方案公式 (34)(35) 的两支输出都是**占空比**（无量纲，上界 ``u_0 = 0.9``）::

    ‖u_eq + u_n‖ <  u_0  →  u_eq + u_n
    ‖u_eq + u_n‖ ≥  u_0  →  u_0 · u_eq / ‖u_eq‖

但稳定项 ``u_n = −S_sc · s(x_k)`` 里的 ``s = x_k − x_ref`` 分量是**电压 (V) 与电流 (A)**，
于是 ``u_n`` 带 V/A 量纲，与无量纲的 ``u_0`` 直接比较在量纲上不成立
（方案问题 14）。实测 ``‖u_n‖ ≈ 147.9 ≫ u_0 = 0.9``，第二支**恒成立**，
``u_n`` 被完全丢弃，控制器退化为 bang-bang。

编写人裁定（2026-09-25）
------------------------

**正式口径 = ``normalised_surface``**（``data_status = SCHEME_AUTHORED``）::

    u_n = −S_sc · ( s / x_scale )        x_scale = (1100 V, 3000 A)

``x_scale`` 取 ``dc_dc_parameters.json`` 的**标幺基准**
（``output_voltage_nominal_v``、``max_output_current_a``），
使 ``u_n`` 无量纲、与 ``u_0`` 可比，且**不引入任何自由参数**。

**被否决读法 = ``scheme_literal``**（``data_status = REJECTED_SCHEME_READING``）::

    u_n = −S_sc · s                      [V, A]

否决理由：① 与自己的分支条件 ``‖u_eq+u_n‖ ≥ u_0`` 量纲不匹配，使第二支恒成立；
② 结果是把滑模稳定项完全剔除，控制器退化为 bang-bang，
与「NSMC 是滑模控制器」这一定位矛盾。保留本候选仅为让「未修正」的行为可复现、
可做回归对比，**不作为任何工程结论的依据**。

另外两条读法（``equivalent_only`` / ``state_space_jacobian``）保留为
``ALTERNATIVE_NOT_ADOPTED``：它们都是量纲自洽的合法读法，只是在本次裁定中
未被选为正式口径，保留供敏感性对比与后续复核。

本模块的纪律
------------
* 每个候选都带 ``answers_issues``（它回答哪几条方案问题）、
  ``new_parameters``（它是否引入方案未给的新参数）、``data_status``。
* 候选只负责算出 ``u_n``；饱和律仍由 ``nsmc.saturate_direction_preserving``
  统一执行——**一次只改一处**，这样各候选之间的差异可归因到 ``u_n`` 的定义上。
* 候选**不改变默认值**：``DEFAULT_CANDIDATE_KEY`` 指向正式口径。

本模块**不处理**问题 1 / 5 / 13 / 15 / 16（已在别处裁定并落地）
--------------------------------------------------------------

问题 1（``u_eq`` 定义式）在 :class:`~regenerative_braking.control.nsmc.StandardEquivalentControl`；
问题 5（``λ_k`` 乘入滑模面）与问题 13（``x_ref`` 构造式）在
:mod:`regenerative_braking.tracking`；问题 15（``B`` 不可辨识）与
问题 16（状态向量冗余）在 :mod:`regenerative_braking.identification.rhonn` 与
:mod:`regenerative_braking.tracking`。本模块只负责 ``u_n`` 的读法。

本模块只依赖 :mod:`regenerative_braking.tracking`，不导入 ``nsmc``，
以免形成 ``nsmc → candidates → nsmc`` 的循环导入。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Sequence, Tuple

import numpy as np

from ..tracking import (
    REJECTED_SCHEME_READING,
    SCHEME_AUTHORED,
    SchurStabilisingMatrix,
    TrackingError,
)

#: 备选读法的状态标记：量纲自洽、但**未被选为正式口径**，保留供敏感性对比。
ALTERNATIVE_NOT_ADOPTED = "alternative_not_adopted"

#: 历史标记：裁定前所有候选的统一状态。保留仅为兼容既有审计链路。
CANDIDATE_STATUS = "PENDING_SCHEME_CONFIRMATION"

#: 原文照落候选的 key。问题 14(a) 裁定后它已被**明确否决**。
SCHEME_LITERAL_KEY = "scheme_literal"

#: 默认候选 = **正式口径**（``normalised_surface``，量纲自洽）。
DEFAULT_CANDIDATE_KEY = "normalised_surface"

CANDIDATE_CAVEAT = (
    "本表列出的是 u_n 的几种读法及其裁定状态："
    "normalised_surface 为编写人裁定的**正式口径**；"
    "scheme_literal 为**被否决读法**（保留仅供回归对比）；"
    "其余两条为量纲自洽但未采用的备选读法。"
)


@dataclass(frozen=True)
class StabilisingTermRequest:
    """算 ``u_n`` 所需的输入。

    Args:
        surface: 滑模面 ``s = λ_k·(x_k − x_ref)``（物理量纲：V / A）。
        schur: 稳定矩阵 ``S_sc``（方案只给特征值区间 [0.6, 0.8]）。
        state_scale: 候选 A 用的状态标幺基准 ``(V, A)``。
        mapper: 状态空间 → 控制空间的映射 ``B^+``（候选 D 用；由调用方按需提供）。
    """

    surface: np.ndarray
    schur: SchurStabilisingMatrix
    state_scale: Tuple[float, float]
    mapper: Optional[Callable[[np.ndarray], np.ndarray]] = None


@dataclass(frozen=True)
class ControlLawCandidate:
    """一种 ``u_n`` 的读法及其裁定状态。"""

    key: str
    label: str
    formula: str
    summary: str
    answers_issues: Tuple[int, ...]
    new_parameters: Optional[str]
    requires_mapper: bool
    stabilising_term: Callable[[StabilisingTermRequest], np.ndarray]
    data_status: str = ALTERNATIVE_NOT_ADOPTED

    @property
    def is_scheme_literal(self) -> bool:
        """本候选是否为**原文照落**（``scheme_literal``，已被否决）。"""
        return self.key == SCHEME_LITERAL_KEY


# ---------------------------------------------------------------------------
# 四种读法
# ---------------------------------------------------------------------------


def _term_scheme_literal(request: StabilisingTermRequest) -> np.ndarray:
    """候选 0：**原文照落**，``u_n = −S_sc·s`` 直接进比较（量纲不一致，已被否决）。"""

    return request.schur.stabilising_term(request.surface)


def _term_normalised_surface(request: StabilisingTermRequest) -> np.ndarray:
    """候选 A（**正式口径**）：``s`` 先按标幺基准归一化，``u_n`` 随即无量纲。

    ``u_n = −S_sc·(s / x_scale)``，``x_scale`` 取 ``dc_dc_parameters.json``
    的额定值 ``(1100 V, 3000 A)``。
    """

    scale = np.asarray(request.state_scale, dtype=float)
    if scale.shape != request.surface.shape:
        raise TrackingError(
            f"state_scale 形状 {scale.shape} 必须与滑模面 {request.surface.shape} 一致"
        )
    if not np.all(np.isfinite(scale)) or np.any(scale <= 0.0):
        raise TrackingError(f"state_scale 必须为正有限值，实际为 {request.state_scale!r}")
    return request.schur.stabilising_term(request.surface / scale)


def _term_equivalent_only(request: StabilisingTermRequest) -> np.ndarray:
    """候选 C（备选）：``u_n`` 不进幅值比较，饱和律只作用在 ``u_eq`` 上。

    依据是原文自身的线索——越限时的缩放方向写的是 ``u_0·u_eq/‖u_eq‖``，
    **不含** ``u_n``，说明作者心里的主控制量是 ``u_eq``。
    取 ``u_n ≡ 0`` 后 (34)(35) 自动退化为
    ``‖u_eq‖ < u_0 → u_eq``，否则 ``u_0·u_eq/‖u_eq‖``，量纲自洽且不引入新参数。

    代价：``u_n`` 完全不起作用，滑模稳定项被丢弃。故**未采用**为正式口径。
    """

    return np.zeros_like(request.surface)


def _term_state_space_via_jacobian(request: StabilisingTermRequest) -> np.ndarray:
    """候选 D（备选）：把稳定项经 ``B^+`` 映射到控制空间，``u_n = −B^+·S_sc·s``。

    整个控制律于是统一写在**状态空间**、最后经 ``B^+`` 落到占空比::

        u = B^+ · [ (x_ref − g(x, x̂, 0)) − S_sc · (x − x_ref) ]
          = u_eq − B^+ · S_sc · s

    ``s = 0`` 时退化为 ``u_eq``，与等效控制自洽；``B^+`` 已由 RHONN 的
    ``∂g/∂u`` 算出，**不引入新参数**。

    未采用的理由：``u_n`` 的符号完全依赖 RHONN 的 ``∂g/∂u``，在线辨识未收敛时
    方向可能不对；正式口径（``normalised_surface``）只依赖状态的标幺基准，
    对辨识收敛性不敏感，更适合作为默认。保留本候选供敏感性对比。
    """

    if request.mapper is None:
        raise TrackingError(
            "候选 D（state_space_jacobian）需要 B^+ 映射，但调用方未提供。"
            "该候选要求 u_eq 提供者能给出 ∂g/∂u（StandardEquivalentControl 可以，"
            "PendingEquivalentControl 不可以）。"
        )
    state_space_term = request.schur.stabilising_term(request.surface)
    mapped = np.asarray(request.mapper(state_space_term), dtype=float)
    if mapped.shape != request.surface.shape:
        raise TrackingError(
            f"B^+ 映射输出形状 {mapped.shape} 与滑模面 {request.surface.shape} 不一致"
        )
    return mapped


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------


CONTROL_LAW_CANDIDATES: Tuple[ControlLawCandidate, ...] = (
    ControlLawCandidate(
        key="scheme_literal",
        label="原文照落（**已被否决**，仅作回归对比）",
        formula="u_n = −S_sc·s        [V, A]",
        summary=(
            "照 (34)(35) 原文执行，u_n 带 V/A 量纲直接与无量纲 u_0 比较。"
            "实测 ‖u_n‖≈147.9 ≫ u_0=0.9，第二支恒成立、u_n 被丢弃，"
            "控制器退化为 bang-bang；阶段 9 全部 14 个场景回收 0 kWh。"
            "**编写人裁定：否决。** 与自身分支条件量纲不匹配，且把滑模稳定项"
            "完全剔除，与 NSMC 的定位矛盾。"
        ),
        answers_issues=(14,),
        new_parameters=None,
        requires_mapper=False,
        data_status=REJECTED_SCHEME_READING,
        stabilising_term=_term_scheme_literal,
    ),
    ControlLawCandidate(
        key="normalised_surface",
        label="滑模面按标幺基准归一化（**正式口径**）",
        formula="u_n = −S_sc·(s / x_scale)   [无量纲]",
        summary=(
            "把 s 按状态标幺基准归一化后再做稳定项，u_n 无量纲，与 u_0 可比。"
            "x_scale 取 dc_dc_parameters.json 的额定值（1100 V、3000 A），"
            "不新造参数。**这是编写人裁定的正式口径**："
            "原式 u_n = −S_sc·s 带 V/A 量纲却与无量纲的 u_0 = 0.9 直接比较，"
            "实测 ‖u_n‖≈147.9 ≫ u_0，饱和分支恒成立、u_n 被完全丢弃。"
        ),
        answers_issues=(14,),
        new_parameters="无自由参数：x_scale 直接取 dc_dc_parameters.json 的额定电压与电流上限",
        requires_mapper=False,
        data_status=SCHEME_AUTHORED,
        stabilising_term=_term_normalised_surface,
    ),
    ControlLawCandidate(
        key="equivalent_only",
        label="备选：饱和只按 u_eq（未采用）",
        formula="u_n ≡ 0 ；‖u_eq‖ < u_0 → u_eq，否则 u_0·u_eq/‖u_eq‖",
        summary=(
            "依据原文自身的线索：越限缩放方向写的是 u_0·u_eq/‖u_eq‖，不含 u_n。"
            "取 u_n ≡ 0 后量纲自洽、不引入新参数，但**滑模稳定项被完全丢弃**。"
        ),
        answers_issues=(14,),
        new_parameters=None,
        requires_mapper=False,
        data_status=ALTERNATIVE_NOT_ADOPTED,
        stabilising_term=_term_equivalent_only,
    ),
    ControlLawCandidate(
        key="state_space_jacobian",
        label="备选：稳定项经 B⁺ 映射到控制空间（未采用）",
        formula="u_n = −B⁺·S_sc·s   [占空比]；等价于 u = B⁺·[(x_ref − g) − S_sc·s]",
        summary=(
            "把整个控制律统一写在状态空间、最后经 B⁺ 落到占空比。"
            "s=0 时退化为 u_eq，量纲自洽且不引入新参数；"
            "代价是 u_n 的符号完全依赖 RHONN 的 ∂g/∂u，在线辨识未收敛时方向可能不对。"
        ),
        answers_issues=(1, 14),
        new_parameters=None,
        requires_mapper=True,
        data_status=ALTERNATIVE_NOT_ADOPTED,
        stabilising_term=_term_state_space_via_jacobian,
    ),
)

_BY_KEY: Dict[str, ControlLawCandidate] = {item.key: item for item in CONTROL_LAW_CANDIDATES}


def candidate_by_key(key: str) -> ControlLawCandidate:
    """按 key 取候选；未知 key 报错并列出全部可用 key。"""

    try:
        return _BY_KEY[key]
    except KeyError as exc:
        raise TrackingError(
            f"未知控制律候选 {key!r}。可用：{', '.join(_BY_KEY)}"
        ) from exc


def candidate_keys() -> Tuple[str, ...]:
    return tuple(_BY_KEY)


def candidate_table() -> Sequence[Tuple[str, str, Tuple[int, ...], Optional[str]]]:
    """``(key, label, answers_issues, new_parameters)`` 摘要表，供文档/CLI 使用。"""

    return tuple(
        (item.key, item.label, item.answers_issues, item.new_parameters)
        for item in CONTROL_LAW_CANDIDATES
    )
