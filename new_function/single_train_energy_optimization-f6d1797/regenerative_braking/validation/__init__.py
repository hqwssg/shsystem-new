"""阶段 9 验证套件：9 类场景 × 8 项 baseline + 主算法对比。

- :mod:`~regenerative_braking.validation.scenarios` —— 9 类验证场景（算法文档 §9）
- :mod:`~regenerative_braking.validation.baselines` —— 8 项 baseline + 主算法（§10.2）
- :mod:`~regenerative_braking.validation.perturbation` —— 载重/参数/噪声/失配扰动构件
- :mod:`~regenerative_braking.validation.comparison` —— ``baseline/optimized/delta/delta_percent``
- :mod:`~regenerative_braking.validation.suite` —— 矩阵运行与落盘

命令行入口见 ``tools/run_validation_suite.py``。

.. warning::
   全部输出为 ``仿真结果，不作为工程结论``。
   主算法携带三处方案待确认项（问题 1/5/13），确认前这些数字不得引用为工程结论。
"""

from .baselines import (
    CONTROLLER_PROFILE_BALANCED,
    CONTROLLER_PROFILE_DEFAULT,
    CONTROLLER_PROFILE_ROBUST,
    CONTROLLER_PROFILES,
    OPTIMIZED_LABEL,
    IdealDutyController,
    ValidationBaseline,
    baseline_by_label,
    baseline_catalog,
    baseline_labels,
    filter_comparison_baselines,
    make_no_storage_override,
)
from .comparison import (
    COMPARISON_METRICS,
    HEADLINE_METRIC,
    PERCENT_FLOOR,
    ComparisonMetric,
    build_comparison_rows,
    build_headline_rows,
    format_delta_percent,
    summarize_improvements,
)
from .perturbation import (
    NoisyObservationController,
    ObservationNoise,
    PerturbationBundle,
    PerturbationError,
    PlantOverride,
    apply_plant_override,
    disable_storage,
    scale_converter_parameter,
    scale_mass,
    scale_storage_parameter,
    set_storage_soc_initial,
)
from .scenarios import (
    ScenarioError,
    ScenarioProfileConfig,
    ValidationScenario,
    build_validation_scenarios,
    scenario_families,
    scenario_ids,
)
from .suite import (
    CAPTURE_FLOOR_KWH,
    CLOSURE_RELATIVE_TOLERANCE,
    MIN_CAPTURE_FRACTION_OF_BEST_BASELINE,
    MIN_MEAN_CAPTURE_FRACTION_OF_BEST_BASELINE,
    OptimizedDiagnosis,
    SuiteError,
    SuiteRunRecord,
    closure_exceedances,
    closure_worst_by_family,
    default_extra_optimized,
    diagnose_optimized_controllers,
    merge_plant_overrides,
    optimized_labels,
    run_validation_suite,
    write_suite_outputs,
)

__all__ = [
    "CAPTURE_FLOOR_KWH",
    "CLOSURE_RELATIVE_TOLERANCE",
    "COMPARISON_METRICS",
    "CONTROLLER_PROFILE_BALANCED",
    "CONTROLLER_PROFILE_DEFAULT",
    "CONTROLLER_PROFILE_ROBUST",
    "CONTROLLER_PROFILES",
    "ComparisonMetric",
    "HEADLINE_METRIC",
    "IdealDutyController",
    "MIN_CAPTURE_FRACTION_OF_BEST_BASELINE",
    "MIN_MEAN_CAPTURE_FRACTION_OF_BEST_BASELINE",
    "NoisyObservationController",
    "OPTIMIZED_LABEL",
    "ObservationNoise",
    "OptimizedDiagnosis",
    "PERCENT_FLOOR",
    "PerturbationBundle",
    "PerturbationError",
    "PlantOverride",
    "ScenarioError",
    "ScenarioProfileConfig",
    "SuiteError",
    "SuiteRunRecord",
    "ValidationBaseline",
    "ValidationScenario",
    "apply_plant_override",
    "baseline_by_label",
    "baseline_catalog",
    "baseline_labels",
    "build_comparison_rows",
    "build_headline_rows",
    "build_validation_scenarios",
    "closure_exceedances",
    "closure_worst_by_family",
    "default_extra_optimized",
    "diagnose_optimized_controllers",
    "disable_storage",
    "filter_comparison_baselines",
    "format_delta_percent",
    "make_no_storage_override",
    "merge_plant_overrides",
    "optimized_labels",
    "run_validation_suite",
    "scale_converter_parameter",
    "scale_mass",
    "scale_storage_parameter",
    "scenario_families",
    "scenario_ids",
    "set_storage_soc_initial",
    "summarize_improvements",
    "write_suite_outputs",
]
