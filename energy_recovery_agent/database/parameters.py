"""数据库任务参数白名单与不依赖算法运行时的基础校验。"""

from __future__ import annotations

from typing import Any, Mapping
import math


PARAMETER_FLAGS: dict[str, dict[str, str]] = {
    "storage_planning": {
        "planning_policy_code": "--planning-policy-code", "scenario_set_code": "--scenario-set-code",
        "search_mode": "--search-mode", "max_levels_per_dimension": "--max-levels-per-dimension",
        "settlement_step_s": "--settlement-step-s", "refinement_shortlist_size": "--refinement-shortlist-size",
    },
    "dispatch": {
        "energy_scenario": "--energy-scenario",
        "objective_mode": "--objective-mode",
        "objective_priority": "--objective-priority",
        "search_profile": "--search-profile",
        "search_method": "--search-method",
        "population_size": "--population-size",
        "generations": "--generations",
        "seed": "--seed",
        "heavy_count": "--heavy-count",
        "empty_count": "--empty-count",
        "baseline_phase_s": "--baseline-phase-s",
        "baseline_heavy_headway_s": "--baseline-heavy-headway-s",
        "baseline_empty_headway_s": "--baseline-empty-headway-s",
        "min_depart_gap_s": "--min-depart-gap-s",
        "horizon_s": "--horizon-s",
        "execute_window_s": "--execute-window-s",
        "settlement_step_s": "--settlement-step-s",
        "wasted_energy_penalty_per_kwh": "--wasted-energy-penalty-per-kwh",
        "search_min_headway_s": "--search-min-headway-s",
        "search_max_headway_s": "--search-max-headway-s",
        "search_max_phase_s": "--search-max-phase-s",
        "search_max_hold_s": "--search-max-hold-s",
        "search_max_storage_align_shift_s": "--search-max-storage-align-shift-s",
        "empty_mass_tons": "--empty-mass-tons",
    },
    "timetable_audit": {},
    "timetable_optimization": {
        "mode": "--mode",
        "max_shift_min": "--max-shift-min",
        "step_min": "--step-min",
        "max_dwell_extension_min": "--max-dwell-extension-min",
        "max_candidates": "--max-candidates",
        "population_size": "--population-size",
        "generations": "--generations",
        "crossover_rate": "--crossover-rate",
        "mutation_rate": "--mutation-rate",
        "seed": "--seed",
    },
    "rolling_rescheduling": {
        "population_size": "--population-size",
        "generations": "--generations",
        "seed": "--seed",
        "max_safety_retries": "--max-safety-retries",
        "manual_after_withheld": "--manual-after-withheld",
    },
    "joint_parameter_robustness": {
        "heavy_count": "--heavy-count",
        "empty_count": "--empty-count",
        "baseline_heavy_headway_s": "--heavy-headway-s",
        "baseline_empty_headway_s": "--empty-headway-s",
        "baseline_phase_s": "--phase-s",
        "settlement_step_s": "--settlement-step-s",
    },
}

BOOLEAN_FLAGS: dict[str, dict[str, str]] = {
    "storage_planning": {},
    "dispatch": {
        "disable_storage_preset_search": "--disable-storage-preset-search",
        "disable_energy_observability": "--disable-energy-observability",
    },
    "timetable_audit": {"strict_visualizations": "--strict-visualizations"},
    "timetable_optimization": {"strict_visualizations": "--strict-visualizations"},
    "rolling_rescheduling": {
        "disable_safety_retry": "--disable-safety-retry",
        "disable_recovery": "--disable-recovery",
    },
    "joint_parameter_robustness": {},
}

PARAMETER_CHOICES = {
    "search_mode": {"coarse", "coarse_to_fine", "exhaustive"},
    "energy_scenario": {"storage_no_direct", "auto"},
    "objective_mode": {"balanced", "capacity_surplus", "capacity_tight"},
    "objective_priority": {"energy_first", "cost_first", "balanced"},
    "search_profile": {"quick", "standard", "large"},
    "search_method": {"nsga2", "grid", "evolutionary"},
    "mode": {"rule", "nsga2"},
}
POSITIVE_PARAMETERS = {
    "max_levels_per_dimension", "refinement_shortlist_size",
    "population_size", "generations", "heavy_count", "empty_count", "horizon_s",
    "execute_window_s", "settlement_step_s", "max_candidates", "step_min",
    "manual_after_withheld",
}
NONNEGATIVE_PARAMETERS = {
    "seed", "baseline_phase_s", "baseline_heavy_headway_s", "baseline_empty_headway_s",
    "min_depart_gap_s", "wasted_energy_penalty_per_kwh", "search_min_headway_s",
    "search_max_headway_s", "search_max_phase_s", "search_max_hold_s",
    "search_max_storage_align_shift_s", "empty_mass_tons", "max_shift_min",
    "max_safety_retries", "max_dwell_extension_min",
}
RATIO_PARAMETERS = {"crossover_rate", "mutation_rate"}
WHOLE_NUMBER_PARAMETERS = {
    "max_levels_per_dimension", "refinement_shortlist_size",
    "population_size", "generations", "heavy_count", "empty_count", "horizon_s",
    "execute_window_s", "settlement_step_s", "max_candidates", "step_min",
    "manual_after_withheld", "seed", "baseline_phase_s", "baseline_heavy_headway_s",
    "baseline_empty_headway_s", "min_depart_gap_s", "search_min_headway_s",
    "search_max_headway_s", "search_max_phase_s", "search_max_hold_s",
    "search_max_storage_align_shift_s", "max_shift_min", "max_safety_retries",
    "max_dwell_extension_min",
}
LOGICAL_PATH_PARAMETERS = {
    "timetable_relative_path",
    "disturbance_history_relative_path",
    "parameter_ranges_relative_path",
}


def _finite_nonnegative(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"参数{field_name}必须是非负有限数值。")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"参数{field_name}必须是非负有限数值。") from exc
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"参数{field_name}必须是非负有限数值。")
    return numeric


def _validate_storage_devices(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("参数storage_devices必须是非空JSON对象数组。")
    allowed_fields = {
        "storage_section_id", "soc_kwh", "available",
        "max_charge_power_kw", "max_discharge_power_kw",
    }
    seen_ids: set[str] = set()
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise ValueError(f"storage_devices[{index}]必须是JSON对象。")
        unknown_fields = set(row) - allowed_fields
        if unknown_fields:
            raise ValueError(f"storage_devices[{index}]包含未批准字段：{sorted(unknown_fields)}")
        if "storage_section_id" not in row or "soc_kwh" not in row:
            raise ValueError(f"storage_devices[{index}]必须包含storage_section_id和soc_kwh。")
        storage_id = str(row["storage_section_id"]).strip()
        if not storage_id:
            raise ValueError(f"storage_devices[{index}].storage_section_id不能为空。")
        if len(storage_id) > 128:
            raise ValueError(f"storage_devices[{index}].storage_section_id长度不能超过128。")
        if storage_id in seen_ids:
            raise ValueError(f"storage_devices包含重复设备ID：{storage_id}")
        seen_ids.add(storage_id)
        _finite_nonnegative(row["soc_kwh"], f"storage_devices[{index}].soc_kwh")
        if "available" in row and type(row["available"]) is not bool:
            raise ValueError(f"storage_devices[{index}].available必须是布尔值。")
        for field_name in ("max_charge_power_kw", "max_discharge_power_kw"):
            if row.get(field_name) is not None:
                _finite_nonnegative(row[field_name], f"storage_devices[{index}].{field_name}")


def _validate_logical_path(value: Any, field_name: str) -> str:
    """拒绝绝对路径和目录穿越，使任务只能引用冻结快照内文件。"""

    if not isinstance(value, str):
        raise ValueError(f"参数{field_name}必须是相对逻辑路径字符串。")
    normalized = value.strip().replace("\\", "/")
    if not normalized:
        raise ValueError(f"参数{field_name}不能为空字符串。")
    if len(normalized) > 500:
        raise ValueError(f"参数{field_name}长度不能超过500。")
    path_parts = normalized.split("/")
    if normalized.startswith("/") or re_drive_prefix(normalized) or ".." in path_parts:
        raise ValueError(f"参数{field_name}必须位于冻结快照目录内。")
    return normalized


def re_drive_prefix(value: str) -> bool:
    """识别Windows盘符绝对路径，不依赖当前运行平台。"""

    return len(value) >= 2 and value[0].isalpha() and value[1] == ":"


def validate_run_parameters(run_type: str, parameters: Mapping[str, Any]) -> None:
    """在任务入队和执行前校验白名单、类型与基本数值边界。"""

    if not isinstance(parameters, Mapping):
        raise ValueError("任务参数必须是JSON对象。")
    if run_type not in PARAMETER_FLAGS:
        raise ValueError(f"不支持的数据库任务类型：{run_type}")
    allowed = set(PARAMETER_FLAGS[run_type]) | set(BOOLEAN_FLAGS[run_type])
    needs_timetable = run_type in {"timetable_audit", "timetable_optimization"}
    if needs_timetable:
        allowed.add("timetable_relative_path")
    if run_type == "rolling_rescheduling":
        allowed.update({"storage_devices", "disturbance_history_relative_path"})
    if run_type == "joint_parameter_robustness":
        allowed.add("parameter_ranges_relative_path")
    unknown = set(parameters) - allowed
    if unknown:
        raise ValueError(f"数据库任务包含未批准参数：{sorted(unknown)}")
    if needs_timetable and not str(parameters.get("timetable_relative_path", "")).strip():
        raise ValueError("运行图审查和优化任务必须提供timetable_relative_path。")
    if run_type == "rolling_rescheduling":
        replay_path = str(parameters.get("disturbance_history_relative_path", "")).strip()
        if "disturbance_history_relative_path" in parameters and not replay_path:
            raise ValueError("disturbance_history_relative_path不能为空字符串。")
        if replay_path and "storage_devices" in parameters:
            raise ValueError("历史扰动回放不能与独立的storage_devices运行时参数同时使用。")
    if run_type == "joint_parameter_robustness":
        ranges_path = str(parameters.get("parameter_ranges_relative_path", "")).strip()
        if not ranges_path:
            raise ValueError("联合参数稳健性任务必须提供parameter_ranges_relative_path。")
    for name in LOGICAL_PATH_PARAMETERS & set(parameters):
        _validate_logical_path(parameters[name], name)
    for name in BOOLEAN_FLAGS[run_type]:
        if name in parameters and not isinstance(parameters[name], bool):
            raise ValueError(f"参数{name}必须是布尔值。")
    for name, choices in PARAMETER_CHOICES.items():
        if name in parameters and str(parameters[name]) not in choices:
            raise ValueError(f"参数{name}不在允许枚举中：{sorted(choices)}")
    if run_type == "storage_planning":
        for name in ("planning_policy_code", "scenario_set_code"):
            value = parameters.get(name)
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ValueError(f"参数{name}必须为非空编码，最长128字符。")
        if float(parameters.get("max_levels_per_dimension", 2)) < 2:
            raise ValueError("每维档位数至少为2。")
    if "storage_devices" in parameters:
        _validate_storage_devices(parameters["storage_devices"])
    for name in (POSITIVE_PARAMETERS | NONNEGATIVE_PARAMETERS | RATIO_PARAMETERS) & set(parameters):
        value = parameters[name]
        if isinstance(value, bool):
            raise ValueError(f"参数{name}必须是数值。")
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"参数{name}必须是数值。") from exc
        if not math.isfinite(numeric):
            raise ValueError(f"参数{name}必须是有限数值。")
        if name in WHOLE_NUMBER_PARAMETERS and not numeric.is_integer():
            raise ValueError(f"参数{name}必须是整数。")
        if name in POSITIVE_PARAMETERS and numeric <= 0:
            raise ValueError(f"参数{name}必须大于0。")
        if name in NONNEGATIVE_PARAMETERS and numeric < 0:
            raise ValueError(f"参数{name}不能小于0。")
        if name in RATIO_PARAMETERS and not 0 <= numeric <= 1:
            raise ValueError(f"参数{name}必须位于0到1之间。")
