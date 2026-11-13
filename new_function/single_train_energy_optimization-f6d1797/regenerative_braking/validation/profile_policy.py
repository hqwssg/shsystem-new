"""运行前 profile 建议与合格记录回退；不诊断传感器、不在运行中切控制器。"""
from dataclasses import dataclass
import math

from .baselines import CONTROLLER_PROFILES, OPTIMIZED_LABEL, baseline_catalog


@dataclass(frozen=True)
class OperatingContext:
    # 来源必须为用户声明/采集接口统计；禁止传入仿真对象隐藏真值作为在线调度。
    noise_relative_std: float | None = None
    parameter_perturbation_declared: bool = False
    missing_measurements_reported: bool = False
    strong_nonlinearity_reported: bool = False
    historical_reproduction: bool = False

    def __post_init__(self):
        noise = self.noise_relative_std
        if noise is not None and (isinstance(noise, bool) or not math.isfinite(noise) or noise < 0):
            raise ValueError("噪声统计必须为非负有限数或None（未知）")
        for field in ("parameter_perturbation_declared", "missing_measurements_reported",
                      "strong_nonlinearity_reported", "historical_reproduction"):
            if not isinstance(getattr(self, field), bool):
                raise ValueError(f"{field}必须为bool")


@dataclass(frozen=True)
class ProfileRecommendation:
    profile: str | None
    preferred_profile: str
    reasons: tuple[str, ...]
    validation_required: bool
    fallback_used: bool = False


def recommend_profile(context, *, qualified_profiles=None):
    """qualified_profiles 只接受同场景/同对象/同周期已通过全部门禁的 profile。

    None 只生成建议，不能直接装配。空集合表示没有合格记录，返回禁用。
    balanced 失格时可回退到已合格 robust；压力条件下 robust 失格不降级。
    """
    if not isinstance(context, OperatingContext):
        raise ValueError("需要OperatingContext")
    stress = (context.noise_relative_std is None or context.noise_relative_std > .01 or
              context.parameter_perturbation_declared or context.missing_measurements_reported or
              context.strong_nonlinearity_reported)
    preferred = "default" if context.historical_reproduction else "robust" if stress else "balanced"
    reasons = ("historical_reproduction",) if context.historical_reproduction else (
        ("unknown_or_stress_conditions",) if stress else ("declared_nominal_conditions",))
    if qualified_profiles is None:
        return ProfileRecommendation(preferred, preferred, reasons, True)
    if isinstance(qualified_profiles, str):
        raise ValueError("合格profile必须为集合，不能是字符串")
    qualified = set(qualified_profiles)
    if qualified - set(CONTROLLER_PROFILES):
        raise ValueError("合格记录包含未知profile")
    if preferred in qualified:
        return ProfileRecommendation(preferred, preferred, reasons, False)
    if preferred == "balanced" and "robust" in qualified:
        return ProfileRecommendation("robust", preferred, (*reasons, "qualified_robust_fallback"), False, True)
    return ProfileRecommendation(None, preferred, (*reasons, "no_qualified_profile_for_conditions"), False)


def build_recommended_controller(bundle, sample_time_s, context, *, qualified_profiles):
    selection = recommend_profile(context, qualified_profiles=qualified_profiles)
    if selection.profile is None or selection.validation_required:
        raise ValueError("没有适用的合格profile；保持关闭，重新验证后装配")
    baseline = next(b for b in baseline_catalog(selection.profile) if b.label == OPTIMIZED_LABEL)
    return baseline.controller(bundle, sample_time_s=sample_time_s), selection
