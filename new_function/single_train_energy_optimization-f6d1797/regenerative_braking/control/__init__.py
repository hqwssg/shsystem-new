"""控制层（阶段 7–8）。

- 阶段 7：:mod:`~regenerative_braking.control.nsmc` —— NSMC 滑模控制器
- 阶段 7：:mod:`~regenerative_braking.control.control_law_candidates` —— ``u_n`` 的读法与裁定状态
"""

from .control_law_candidates import (
    ALTERNATIVE_NOT_ADOPTED,
    DEFAULT_CANDIDATE_KEY,
    REJECTED_SCHEME_READING,
)
from .nsmc import (
    BANG_BANG_FALLBACK,
    BOX_LEAST_SQUARES_FALLBACK,
    DEFAULT_STATE_SCALE,
    REACHABILITY_FALLBACKS,
    SATURATION_NORM_BALL_LEGACY,
    SATURATION_NORM_BOX,
    SATURATION_NORMS,
    SCHEME_AUTHORED,
    BusTrackingReference,
    EquivalentControl,
    NSMC,
    NSMCConfig,
    NSMCError,
    NsmcContext,
    PendingEquivalentControl,
    PendingReferenceState,
    PendingSchemeConfirmationError,
    RegenerativeReferenceState,
    SchurStabilisingMatrix,
    StandardEquivalentControl,
    actuator_norm,
    box_constrained_least_squares,
    lambda_k,
    saturate_direction_preserving,
    sliding_surface,
)

__all__ = [
    "ALTERNATIVE_NOT_ADOPTED",
    "BANG_BANG_FALLBACK",
    "BOX_LEAST_SQUARES_FALLBACK",
    "BusTrackingReference",
    "DEFAULT_CANDIDATE_KEY",
    "DEFAULT_STATE_SCALE",
    "EquivalentControl",
    "NSMC",
    "NSMCConfig",
    "NSMCError",
    "NsmcContext",
    "PendingEquivalentControl",
    "PendingReferenceState",
    "PendingSchemeConfirmationError",
    "REACHABILITY_FALLBACKS",
    "REJECTED_SCHEME_READING",
    "RegenerativeReferenceState",
    "SATURATION_NORM_BALL_LEGACY",
    "SATURATION_NORM_BOX",
    "SATURATION_NORMS",
    "SCHEME_AUTHORED",
    "SchurStabilisingMatrix",
    "StandardEquivalentControl",
    "actuator_norm",
    "box_constrained_least_squares",
    "lambda_k",
    "saturate_direction_preserving",
    "sliding_surface",
]
