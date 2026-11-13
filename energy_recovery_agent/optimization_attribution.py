"""为运行图优化和重空调度生成统一的收益归因与瓶颈解释。"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence
import csv
import json
import math


SCHEMA_VERSION = "1.0"
ACTIVE_SCENARIO = "storage_no_direct"
ENERGY_TOLERANCE_KWH = 0.01
CONSTRAINT_TOLERANCE = 1e-9

METRIC_SPECS = {
    "energy_term": ("kWh", "lower", "综合能量目标"),
    "effective_regen_loss_kwh": ("kWh", "lower", "有效再生损失"),
    "grid_kwh": ("kWh", "lower", "电网购电量"),
    "wasted_kwh": ("kWh", "lower", "未利用再生能量"),
    "recovered_energy_kwh": ("kWh", "higher", "有效回收能量"),
    "recovery_rate": ("ratio", "higher", "有效回收率"),
    "accepted_by_power_arm_kwh": ("kWh", "higher", "供电系统接纳量"),
    "battery_charge_kwh": ("kWh", "neutral", "储能输入量"),
    "battery_discharge_kwh": ("kWh", "neutral", "储能输出量"),
    "battery_charge_limited_kwh": ("kWh", "lower", "受限未充入量"),
    "battery_discharge_limited_kwh": ("kWh", "lower", "受限未放出量"),
    "traction_supply_excess_kwh": ("kWh", "lower", "牵引供电超限量"),
    "regen_absorption_excess_kwh": ("kWh", "lower", "再生吸收超限量"),
    "final_soc_deviation_kwh": ("kWh", "lower", "终端SOC偏差"),
    "final_soc_shortfall_kwh": ("kWh", "lower", "终端SOC短缺"),
    "final_soc_kwh": ("kWh", "neutral", "评价窗末SOC"),
    "parked_energy_kwh": ("kWh", "neutral", "评价窗末留存能量"),
    "total_cost": ("CNY", "lower", "综合成本"),
    "resource_conflict_count": ("count", "lower", "资源冲突数"),
    "flow_continuity_violation_count": ("count", "lower", "车流连续性违反数"),
    "constraint_violation": ("score", "lower", "约束违反度"),
}

# 报告正文中出现的内部枚举代码，统一显示为“中文（`code`）”，既便于阅读也保留可追溯的机器值。
REPORT_CODE_LABELS = {
    "keep_baseline": "保留原运行图",
    "optimize": "采用优化方案",
    "no_feasible_solution": "本轮未推荐可采用的方案",
    "baseline_infeasible": "基线未通过硬约束，暂不能验收节能收益",
    "feasibility_restored_energy_comparison_unavailable": "候选恢复可行性，基线能耗仅供诊断",
    "diagnostic_only": "仅供诊断",
    "no_material_energy_improvement": "无实质性能量改善",
    "storage_preset_changed_requires_fixed_storage_recheck": "储能预设发生变化，需在固定储能下复核",
    "fixed_storage_timetable_only": "仅固定储能下的运行图调整",
    "fixed_storage_dispatch_only": "仅固定储能下的调度调整",
    "joint_dispatch_and_storage_planning": "调度与储能规划联合变化",
    "all_candidates": "全部候选",
    "hard_feasible": "硬约束可行",
    "core_robust_feasible": "核心稳健可行",
    "active_scenario_feasible": "主场景可行",
    "fixed_storage_comparable": "与基线储能预设一致",
    "material_energy_improvement": "有实质能量改善",
    "pareto": "非支配候选",
    "selected": "最终选中",
    "section_without_storage": "供电臂未接入储能",
    "storage_capacity_or_power_limit": "储能容量或充电功率不足",
    "regen_without_traction_same_window": "同窗内无牵引需求",
    "regen_unusable_by_scenario": "场景未启用任何利用路径",
    "regen_exceeds_traction_same_window": "同窗再生电量大于牵引需求",
    "traction_supply_capacity_exceeded": "牵引供电能力超限",
    "regen_absorption_capacity_exceeded": "再生吸收能力超限",
    "regeneration_unusable": "再生电量无可用利用路径",
    "no_matching_traction_window": "无同供电范围牵引需求",
    "storage_limit": "储能容量或充电功率不足",
    "regeneration_leftover": "仍有剩余再生电量",
    "constraint_violation": "约束违反",
    "none": "无",
    "unknown": "未知",
}

REPORT_UNIT_LABELS = {
    "kWh": "千瓦时",
    "CNY": "元",
    "count": "个",
    "score": "评分",
    "ratio": "比例",
    "min": "分钟",
    "s": "秒",
}


def _display_code(value: Any) -> str:
    """将内部枚举代码显示为“中文（`code`）”，未收录的代码保留原值。"""
    code = str(value)
    if not code:
        return "—"
    label = REPORT_CODE_LABELS.get(code)
    return f"{label}（`{code}`）" if label else f"`{code}`"


def _display_flag(value: Any) -> str:
    """将布尔标识显示为中文。"""
    return "是" if bool(value) else "否"


def _display_unit(value: Any) -> str:
    """将机器单位显示为中文单位。"""
    unit = str(value)
    return REPORT_UNIT_LABELS.get(unit, unit)


def _number(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return float(default)
    if isinstance(value, bool):
        return float(value)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _optional_number(value: Any) -> float | None:
    number = _number(value, math.nan)
    return number if math.isfinite(number) else None


def _time_seconds(value: Any) -> float:
    """兼容数值秒和运行图HH:MM:SS时间。"""

    if isinstance(value, str) and ":" in value:
        parts = value.strip().split(":")
        if len(parts) == 3:
            try:
                hours, minutes, seconds = (float(part) for part in parts)
            except ValueError:
                return 0.0
            return hours * 3600.0 + minutes * 60.0 + seconds
    return _number(value)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _metric_rows(
    baseline: Mapping[str, Any],
    optimized: Mapping[str, Any],
    *,
    attribution_scope: str,
    attribution_allowed: bool,
    comparison_eligible: bool = True,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric, (unit, direction, label) in METRIC_SPECS.items():
        if metric not in baseline and metric not in optimized:
            continue
        base = _optional_number(baseline.get(metric))
        opt = _optional_number(optimized.get(metric))
        delta = opt - base if comparison_eligible and base is not None and opt is not None else None
        improvement = None if delta is None or direction == "neutral" else -delta if direction == "lower" else delta
        percent = None
        if improvement is not None and base is not None and abs(base) > 1e-12:
            percent = improvement / abs(base) * 100.0
        if delta is None:
            interpretation = "缺少可比较的评分，本轮未计算改善量。"
        elif direction == "neutral":
            interpretation = f"{label}变化仅作能量账本诊断，不单独代表收益。"
        elif improvement > ENERGY_TOLERANCE_KWH:
            interpretation = f"{label}改善。"
        elif improvement < -ENERGY_TOLERANCE_KWH:
            interpretation = f"{label}恶化。"
        else:
            interpretation = f"{label}在数值容差内无实质变化。"
        rows.append({
            "metric": metric,
            "metric_label": label,
            "unit": unit,
            "benefit_direction": direction,
            "baseline": round(base, 6) if base is not None else "",
            "optimized": round(opt, 6) if opt is not None else "",
            "optimized_minus_baseline": round(delta, 6) if delta is not None else "",
            "improvement": round(improvement, 6) if improvement is not None else "",
            "improvement_pct": round(percent, 6) if percent is not None else "",
            "attribution_scope": attribution_scope,
            "dispatch_only_attribution_allowed": attribution_allowed,
            "interpretation": interpretation,
        })
    return rows


def _timetable_candidate_details(
    candidate_rows: Sequence[Mapping[str, Any]],
    scenario_rows: Sequence[Mapping[str, Any]],
    pareto_rows: Sequence[Mapping[str, Any]],
    decision: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pareto_ids = {str(row.get("candidate_id", "")) for row in pareto_rows}
    baseline_candidates = [
        row for row in candidate_rows
        if str(row.get("action_type", "")) == "baseline"
        or (
            abs(_number(row.get("total_adjustment_min"))) <= ENERGY_TOLERANCE_KWH
            and abs(_number(row.get("max_shift_min"))) <= ENERGY_TOLERANCE_KWH
        )
    ]
    baseline_id = str(baseline_candidates[0].get("candidate_id", "")) if baseline_candidates else ""
    selected_id = str(decision.get("selected_candidate_id", ""))
    if not selected_id and decision.get("action") == "keep_baseline":
        selected_id = baseline_id
    active_by_id = {
        str(row.get("candidate_id", "")): row
        for row in scenario_rows
        if str(row.get("scenario_id", "")) == ACTIVE_SCENARIO
    }
    base_energy = active_by_id.get(baseline_id, {})
    baseline_comparable = bool(base_energy) and _number(base_energy.get("constraint_violation")) <= CONSTRAINT_TOLERANCE
    base_loss = _number(base_energy.get("effective_regen_loss_kwh_est"))
    base_grid = _number(base_energy.get("grid_kwh_est"))
    details: list[dict[str, Any]] = []
    for row in candidate_rows:
        candidate_id = str(row.get("candidate_id", ""))
        active = active_by_id.get(candidate_id)
        violation = _number(row.get("constraint_violation"))
        feasible = violation <= CONSTRAINT_TOLERANCE and _truth(row.get("feasible", True))
        active_feasible = active is not None and _number(active.get("constraint_violation")) <= CONSTRAINT_TOLERANCE
        loss_gain = base_loss - _number(active.get("effective_regen_loss_kwh_est")) if active else 0.0
        grid_gain = base_grid - _number(active.get("grid_kwh_est")) if active else 0.0
        material = (
            baseline_comparable
            and active_feasible
            and candidate_id != baseline_id
            and (loss_gain > ENERGY_TOLERANCE_KWH or grid_gain > ENERGY_TOLERANCE_KWH)
            and loss_gain >= -ENERGY_TOLERANCE_KWH
            and grid_gain >= -ENERGY_TOLERANCE_KWH
        )
        violations = {
            "basic_timetable": _number(row.get("basic_constraint_violation")),
            "resource": _number(row.get("resource_constraint_violation")),
            "electrical": _number(row.get("electrical_constraint_violation_kwh")),
        }
        dominant, dominant_value = max(violations.items(), key=lambda item: item[1])
        if candidate_id == selected_id:
            status, reason = "selected", str(decision.get("reason", "selected_by_optimizer"))
        elif not feasible:
            status, reason = "rejected_infeasible", f"dominant_constraint={dominant}"
        elif not active_feasible:
            status, reason = "rejected_active_scenario", "storage_no_direct场景缺失或不可行"
        elif candidate_id == baseline_id:
            status, reason = "baseline_reference", "基线用于同口径比较"
        elif not baseline_comparable:
            status, reason = "diagnostic_only", "基线缺少可行评分，暂不能比较节能收益"
        elif not material:
            status, reason = "rejected_no_material_improvement", "能量改善不足或伴随另一核心指标恶化"
        elif candidate_id in pareto_ids:
            status, reason = "pareto_alternative", "可行且非支配，但未被最终决策选中"
        else:
            status, reason = "rejected_dominated", "被其他可行候选支配或调整代价更高"
        details.append({
            "candidate_id": candidate_id,
            "status": status,
            "reason": reason,
            "selected": candidate_id == selected_id,
            "baseline": candidate_id == baseline_id,
            "feasible": feasible,
            "active_scenario_feasible": active_feasible,
            "pareto_member": candidate_id in pareto_ids,
            "material_energy_improvement": material,
            "effective_regen_loss_improvement_kwh": round(loss_gain, 6),
            "grid_improvement_kwh": round(grid_gain, 6),
            "total_adjustment_min": round(_number(row.get("total_adjustment_min")), 6),
            "dominant_constraint": dominant if dominant_value > CONSTRAINT_TOLERANCE else "none",
            "dominant_constraint_value": round(dominant_value, 6),
        })
    stages = [
        ("all_candidates", len(details), "全部已评价候选"),
        ("hard_feasible", sum(item["feasible"] for item in details), "通过基础、资源和电气硬约束"),
        ("active_scenario_feasible", sum(item["active_scenario_feasible"] for item in details), "通过storage_no_direct主场景"),
        ("material_energy_improvement", sum(item["material_energy_improvement"] for item in details), "相对基线有实质改善且另一核心指标未恶化"),
        ("pareto", sum(item["pareto_member"] for item in details), "进入非支配候选集"),
        ("selected", sum(item["selected"] for item in details), "优化决策最终选择"),
    ]
    funnel = []
    total = len(details)
    for stage, remaining, rule in stages:
        funnel.append({"stage": stage, "input_count": total, "remaining_count": remaining, "removed_count": max(0, total - remaining), "rule": rule})
    return details, funnel


def _dispatch_candidate_details(
    candidate_rows: Sequence[Mapping[str, Any]],
    pareto_rows: Sequence[Mapping[str, Any]],
    baseline: Mapping[str, Any],
    baseline_storage_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    pareto_ids = {str(row.get("candidate_id", "")) for row in pareto_rows}
    selected_id = str(candidate_rows[0].get("candidate_id", "")) if candidate_rows else ""
    has_effective_loss = "effective_regen_loss_kwh" in baseline
    base_loss = _number(baseline.get("effective_regen_loss_kwh", baseline.get("wasted_kwh")))
    base_grid = _number(baseline.get("grid_kwh"))
    baseline_feasible = _truth(baseline.get("feasible", True))
    details: list[dict[str, Any]] = []
    for row in candidate_rows:
        candidate_id = str(row.get("candidate_id", ""))
        feasible = _truth(row.get("feasible"))
        storage_id = str(row.get("storage_preset_id", ""))
        fixed_storage = not baseline_storage_id or storage_id == baseline_storage_id
        grid = _number(row.get("grid_kwh", row.get("objective_2_grid_kwh")))
        loss = (
            _number(row.get("energy_scenario_objective")) - grid
            if has_effective_loss and row.get("energy_scenario_objective") not in (None, "")
            else _number(row.get("wasted_kwh", row.get("objective_1_wasted_kwh")))
        )
        loss_gain = base_loss - loss
        grid_gain = base_grid - grid
        material = (
            baseline_feasible and feasible and fixed_storage
            and (loss_gain > ENERGY_TOLERANCE_KWH or grid_gain > ENERGY_TOLERANCE_KWH)
            and loss_gain >= -ENERGY_TOLERANCE_KWH and grid_gain >= -ENERGY_TOLERANCE_KWH
        )
        if candidate_id == selected_id:
            status, reason = "selected_by_optimizer", "候选排序第一；是否可采用仍取决于归因范围和稳健门禁"
        elif not feasible:
            status, reason = "rejected_infeasible", "未通过核心稳健可行性门禁"
        elif not fixed_storage:
            status, reason = "planning_alternative", "储能预设变化，不能作为纯调度收益候选"
        elif not material:
            status, reason = "rejected_no_material_improvement", "固定储能下没有形成无代价的实质能量改善"
        elif candidate_id in pareto_ids:
            status, reason = "pareto_alternative", "可行非支配候选，但排序未选中"
        else:
            status, reason = "rejected_dominated", "被更优候选支配或排序靠后"
        details.append({
            "candidate_id": candidate_id,
            "status": status,
            "reason": reason,
            "selected": candidate_id == selected_id,
            "baseline": False,
            "feasible": feasible,
            "active_scenario_feasible": feasible,
            "pareto_member": candidate_id in pareto_ids,
            "material_energy_improvement": material,
            "effective_regen_loss_improvement_kwh": round(loss_gain, 6) if baseline_feasible else "",
            "grid_improvement_kwh": round(grid_gain, 6) if baseline_feasible else "",
            "total_adjustment_min": round(_number(row.get("headway_deviation")) / 60.0, 6),
            "dominant_constraint": "constraint_violation" if _number(row.get("constraint_violation")) > CONSTRAINT_TOLERANCE else "none",
            "dominant_constraint_value": round(_number(row.get("constraint_violation")), 6),
            "storage_preset_id": storage_id,
            "fixed_storage_context": fixed_storage,
        })
    stages = [
        ("all_candidates", len(details), "全部已导出排序候选"),
        ("core_robust_feasible", sum(item["feasible"] for item in details), "通过核心稳健可行性门禁"),
        ("fixed_storage_comparable", sum(item["feasible"] and item["fixed_storage_context"] for item in details), "与基线使用相同储能预设"),
        ("material_energy_improvement", sum(item["material_energy_improvement"] for item in details), "固定储能下形成实质能量改善"),
        ("pareto", sum(item["pareto_member"] for item in details), "进入导出的非支配集合"),
        ("selected", sum(item["selected"] for item in details), "优化器返回候选"),
    ]
    funnel, total = [], len(details)
    for stage, remaining, rule in stages:
        funnel.append({"stage": stage, "input_count": total, "remaining_count": remaining, "removed_count": max(0, total - remaining), "rule": rule})
    return details, funnel, selected_id


def _issue_bottlenecks(
    issue_rows: Sequence[Mapping[str, Any]],
    target_ids: set[str],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in issue_rows:
        candidate_id = str(row.get("candidate_id", ""))
        if target_ids and candidate_id not in target_ids:
            continue
        key = (candidate_id, str(row.get("issue_type", "unknown")), str(row.get("power_arm_id", "")))
        item = grouped.setdefault(key, {"count": 0, "magnitude": 0.0, "electrical": 0.0})
        item["count"] += 1
        item["magnitude"] += _number(row.get("estimated_wasted_kwh"))
        item["electrical"] += _number(row.get("electrical_excess_kwh"))
    return [
        {
            "scope": candidate_id,
            "bottleneck_type": issue_type,
            "bottleneck_id": power_arm_id,
            "occurrence_count": values["count"],
            "magnitude": round(values["magnitude"] + values["electrical"], 6),
            "unit": "kWh",
            "blocking": values["electrical"] > CONSTRAINT_TOLERANCE,
            "evidence": "candidate_energy_issues",
        }
        for (candidate_id, issue_type, power_arm_id), values in grouped.items()
    ]


def _scenario_bottlenecks(scenario_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in scenario_rows:
        feasible = _truth(row.get("feasible", True))
        core = (
            _truth(row.get("core_for_feasibility"))
            if "core_for_feasibility" in row
            else _truth(row.get("blocking"))
        )
        blocking = core and not feasible
        conflicts = int(_number(row.get("resource_conflict_count")))
        violation = _number(row.get("constraint_violation"))
        if feasible and conflicts <= 0 and violation <= CONSTRAINT_TOLERANCE:
            continue
        rows.append({
            "scope": "selected_candidate_core" if core else "selected_candidate_non_core_stress",
            "bottleneck_type": "scenario_infeasibility" if core else "stress_scenario_diagnostic",
            "bottleneck_id": str(row.get("scenario", row.get("scenario_id", ""))),
            "occurrence_count": conflicts,
            "magnitude": round(violation, 6),
            "unit": "constraint_score",
            "blocking": blocking,
            "evidence": str(row.get("conflict_summary", "scenario_result")),
        })
    return rows


def _storage_dimensions(
    baseline: Mapping[str, Any],
    optimized: Mapping[str, Any],
) -> list[dict[str, Any]]:
    base = baseline.get("final_soc_by_storage_kwh") or {}
    opt = optimized.get("final_soc_by_storage_kwh") or {}
    if not isinstance(base, Mapping) or not isinstance(opt, Mapping):
        return []
    rows = []
    for storage_id in sorted(set(base) | set(opt)):
        before, after = _number(base.get(storage_id)), _number(opt.get(storage_id))
        rows.append({
            "dimension_type": "storage_device",
            "dimension_id": storage_id,
            "metric": "final_soc_kwh",
            "unit": "kWh",
            "baseline": round(before, 6),
            "optimized": round(after, 6),
            "optimized_minus_baseline": round(after - before, 6),
            "improvement": "",
            "attribution_quality": "direct_device_settlement",
            "note": "设备级终端SOC是直接账本结果，不单独代表节能收益。",
        })
    return rows


def _arc_dimensions(
    baseline_rows: Sequence[Mapping[str, Any]],
    optimized_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not baseline_rows or not optimized_rows:
        return []

    def aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str, str], float]:
        values: dict[tuple[str, str, str], float] = defaultdict(float)
        for row in rows:
            energy = _number(row.get("energy_kwh"))
            train_id = str(row.get("train_id", ""))
            section_id = (
                f"{row.get('start_station', '')}->{row.get('end_station', '')}"
                if row.get("start_station") or row.get("end_station")
                else f"K{row.get('start_km', '')}-K{row.get('end_km', '')}"
            )
            resource_id = str(row.get("power_arm_ids", row.get("capacity_resource_id", "")))
            storage_id = str(row.get("storage_section_id", ""))
            for dimension_type, dimension_id in (
                ("train_physical_energy", train_id),
                ("section_physical_energy", section_id),
                ("power_resource_physical_energy", resource_id),
                ("storage_section_physical_energy", storage_id),
            ):
                if dimension_id:
                    values[(dimension_type, dimension_id, "traction_energy_kwh")] += max(0.0, energy)
                    values[(dimension_type, dimension_id, "regen_energy_kwh")] += max(0.0, -energy)
        return values

    base, opt = aggregate(baseline_rows), aggregate(optimized_rows)
    output = []
    for key in sorted(set(base) | set(opt)):
        before, after = base.get(key, 0.0), opt.get(key, 0.0)
        dimension_type, dimension_id, metric = key
        output.append({
            "dimension_type": dimension_type,
            "dimension_id": dimension_id,
            "metric": metric,
            "unit": "kWh",
            "baseline": round(before, 6),
            "optimized": round(after, 6),
            "optimized_minus_baseline": round(after - before, 6),
            "improvement": "",
            "attribution_quality": "direct_physical_arc_energy",
            "note": "仅描述列车运行弧物理牵引/再生变化，不把共享储能结算收益分摊到该维度。",
        })
    return output


def _issue_dimensions(
    issue_rows: Sequence[Mapping[str, Any]],
    baseline_id: str,
    selected_id: str,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], float] = defaultdict(float)
    for row in issue_rows:
        candidate_id = str(row.get("candidate_id", ""))
        if candidate_id not in {baseline_id, selected_id}:
            continue
        power_arm_id = str(row.get("power_arm_id", ""))
        if power_arm_id:
            grouped[(candidate_id, power_arm_id)] += _number(row.get("estimated_wasted_kwh"))
    output = []
    for arm_id in sorted({key[1] for key in grouped}):
        before = grouped.get((baseline_id, arm_id), 0.0)
        after = grouped.get((selected_id, arm_id), 0.0)
        output.append({
            "dimension_type": "power_arm_energy_issue",
            "dimension_id": arm_id,
            "metric": "estimated_wasted_kwh",
            "unit": "kWh",
            "baseline": round(before, 6),
            "optimized": round(after, 6),
            "optimized_minus_baseline": round(after - before, 6),
            "improvement": round(before - after, 6),
            "attribution_quality": "issue_aggregate",
            "note": "由候选能量问题聚合，只表示该供电臂识别出的弃能问题变化。",
        })
    return output


def _constraint_bottlenecks(scope: str, metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    fields = {
        "battery_charge_limited_kwh": "storage_charge_power_or_capacity",
        "battery_discharge_limited_kwh": "storage_discharge_power_or_soc",
        "traction_supply_excess_kwh": "traction_supply_limit",
        "regen_absorption_excess_kwh": "regen_absorption_limit",
        "final_soc_deviation_kwh": "terminal_soc_deviation",
        "resource_conflict_count": "resource_conflict",
        "flow_continuity_violation_count": "flow_continuity",
    }
    rows = []
    for field, kind in fields.items():
        magnitude = _number(metrics.get(field))
        if magnitude <= CONSTRAINT_TOLERANCE:
            continue
        rows.append({
            "scope": scope,
            "bottleneck_type": kind,
            "bottleneck_id": field,
            "occurrence_count": int(magnitude) if field.endswith("count") else 1,
            "magnitude": round(magnitude, 6),
            "unit": "count" if field.endswith("count") else "kWh",
            "blocking": field.endswith("count") or "excess" in field,
            "evidence": "summary_kpi",
        })
    return rows


def _schedule_dimensions(
    baseline_rows: Sequence[Mapping[str, Any]],
    optimized_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
        grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get("train_id", ""))].append(row)
        result: dict[str, dict[str, float]] = {}
        for train_id, train_rows in grouped.items():
            ordered = sorted(train_rows, key=lambda row: _number(row.get("seq")))
            if len(ordered) == 1 and "depart_time_s" in ordered[0]:
                result[train_id] = {
                    "depart_time_s": _number(ordered[0].get("depart_time_s")),
                    "arrival_time_s": _number(ordered[0].get("arrival_time_s")),
                }
                continue
            departures = [_time_seconds(row.get("departure_time")) for row in ordered]
            arrivals = [_time_seconds(row.get("arrival_time")) for row in ordered]
            result[train_id] = {
                "depart_time_s": departures[0] if departures else 0.0,
                "arrival_time_s": arrivals[-1] if arrivals else 0.0,
                "total_dwell_s": sum(max(0.0, departure - arrival) for arrival, departure in zip(arrivals, departures)),
            }
        return result

    base = summarize(baseline_rows)
    opt = summarize(optimized_rows)
    rows = []
    for train_id in sorted(set(base) | set(opt)):
        left, right = base.get(train_id, {}), opt.get(train_id, {})
        for metric in ("depart_time_s", "arrival_time_s", "total_dwell_s"):
            if metric not in left and metric not in right:
                continue
            before, after = _number(left.get(metric)), _number(right.get(metric))
            rows.append({
                "dimension_type": "train",
                "dimension_id": train_id,
                "metric": metric,
                "unit": "s",
                "baseline": round(before, 6),
                "optimized": round(after, 6),
                "optimized_minus_baseline": round(after - before, 6),
                "improvement": "",
                "attribution_quality": "direct_schedule_change",
                "note": "时刻变化是直接决策，不等同于该列车独立贡献的共享储能收益。",
            })
    return rows


def _timeline_dimensions(timeline_rows: Sequence[Mapping[str, Any]], window_s: int = 900) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    sorted_rows = sorted(timeline_rows, key=lambda row: (str(row.get("case", "")), _number(row.get("time_s"))))
    by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in sorted_rows:
        by_case[str(row.get("case", ""))].append(row)
    for case, rows in by_case.items():
        times = [_number(row.get("time_s")) for row in rows]
        positive_steps = [b - a for a, b in zip(times, times[1:]) if b > a]
        step_s = min(positive_steps) if positive_steps else 10.0
        for row in rows:
            bucket = int(_number(row.get("time_s")) // window_s) * window_s
            for power_field, metric in (
                ("grid_kW", "grid_kwh"),
                ("wasted_kW", "wasted_kwh"),
                ("battery_charge_kW", "battery_charge_kwh"),
                ("battery_discharge_kW", "battery_discharge_kwh"),
            ):
                grouped[(case, bucket)][metric] += _number(row.get(power_field)) * step_s / 3600.0
    dimensions = []
    for bucket in sorted({key[1] for key in grouped}):
        base = grouped.get(("baseline", bucket), {})
        opt = grouped.get(("optimized", bucket), {})
        for metric in ("grid_kwh", "wasted_kwh", "battery_charge_kwh", "battery_discharge_kwh"):
            before, after = base.get(metric, 0.0), opt.get(metric, 0.0)
            direction = "lower" if metric in {"grid_kwh", "wasted_kwh"} else "neutral"
            improvement: Any = round(before - after, 6) if direction == "lower" else ""
            dimensions.append({
                "dimension_type": "time_window",
                "dimension_id": f"{bucket}-{bucket + window_s}",
                "metric": metric,
                "unit": "kWh",
                "baseline": round(before, 6),
                "optimized": round(after, 6),
                "optimized_minus_baseline": round(after - before, 6),
                "improvement": improvement,
                "attribution_quality": "direct_aggregate_settlement",
                "note": "按聚合功率时间线积分；共享储能效应未分摊到单车。",
            })
    return dimensions


def _report(
    workflow: str,
    scope: Mapping[str, Any],
    decision: Mapping[str, Any],
    metric_rows: Sequence[Mapping[str, Any]],
    funnel: Sequence[Mapping[str, Any]],
    bottlenecks: Sequence[Mapping[str, Any]],
    dimensions: Sequence[Mapping[str, Any]],
) -> str:
    title = "运行图优化" if workflow == "timetable_optimization" else "重空协同调度"
    lines = [
        f"# {title}收益归因与瓶颈解释报告", "",
        "## 1. 结论", "",
        f"- 解释性动作：{_display_code(decision.get('action', ''))}。",
        f"- 原因：{_display_code(decision.get('reason', ''))}。",
        f"- 选中候选：{_display_code(decision.get('selected_candidate_id') or '')}。",
        f"- 归因范围：{_display_code(scope.get('comparison_scope', ''))}。",
        f"- 是否允许归因为纯调度收益：{_display_flag(scope.get('dispatch_only_attribution_allowed', False))}。",
        f"- 口径说明：{scope.get('comparison_note', '')}", "",
        "## 2. 核心指标", "",
        "| 指标 | 基线 | 选中方案 | 原始差值 | 改善量 | 单位 |", "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in metric_rows:
        if row["metric"] not in {"energy_term", "effective_regen_loss_kwh", "grid_kwh", "wasted_kwh", "recovered_energy_kwh", "battery_charge_kwh", "battery_discharge_kwh", "final_soc_kwh", "final_soc_deviation_kwh", "total_cost"}:
            continue
        lines.append(f"| {row['metric_label']} | {row['baseline']} | {row['optimized']} | {row['optimized_minus_baseline']} | {row['improvement']} | {_display_unit(row['unit'])} |")
    lines.extend(["", "正的“改善量”统一表示变好；储能充放电和窗末留存属于中性账本项，不单独解释为节能。", "", "## 3. 候选筛选", "", "| 阶段 | 输入 | 保留 | 本阶段差额 | 规则 |", "| --- | ---: | ---: | ---: | --- |"])
    for row in funnel:
        lines.append(f"| {_display_code(row['stage'])} | {row['input_count']} | {row['remaining_count']} | {row['removed_count']} | {row['rule']} |")
    lines.extend(["", "每一阶段均相对于全部候选独立统计，集合不一定严格嵌套。", "", "## 4. 主要瓶颈", "", "| 范围 | 类型 | 标识 | 次数 | 量值 | 阻断 |", "| --- | --- | --- | ---: | ---: | --- |"])
    ranked_bottlenecks = sorted(bottlenecks, key=lambda row: (_truth(row.get("blocking")), _number(row.get("magnitude")), _number(row.get("occurrence_count"))), reverse=True)
    for row in ranked_bottlenecks[:20]:
        lines.append(f"| {row['scope']} | {_display_code(row['bottleneck_type'])} | {row['bottleneck_id']} | {row['occurrence_count']} | {row['magnitude']} {_display_unit(row['unit'])} | {_display_flag(row['blocking'])} |")
    if not ranked_bottlenecks:
        lines.append("| - | 无 | - | 0 | 0 | 否 |")
    lines.extend(["", "## 5. 归因边界", "", "- 共享供电臂和储能形成耦合能量账本，不能把系统级购电或弃能改善唯一分摊给某一列车。", "- 单车时刻变化可以直接说明，单车独立节能贡献只有在反事实重算后才能发布；当前报告不会按比例臆造。", "- 储能预设变化时，差值属于调度与储能规划联合变化，不能称为运行图单独节能。", "- 当前规划/占位数据下的数值只用于流程验证和候选比较，正式数据到位后必须重跑。", "", "## 6. 明细文件", "", "- `optimization_kpi_attribution.csv`：统一正向改善量和原始差值。", "- `optimization_candidate_decisions.csv`：每个候选的去留原因。", "- `optimization_candidate_funnel.csv`：候选经过各层门禁后的数量。", "- `optimization_bottlenecks.csv`：约束、能量问题和扰动场景瓶颈。", "- `optimization_dimension_attribution.csv`：列车时刻和时间窗等可识别维度变化。", "- `optimization_attribution_summary.json`：平台和数据库使用的机器可读摘要。", ""])
    return "\n".join(lines)


def write_optimization_attribution(
    output_dir: Path,
    *,
    workflow: str,
    summary: Mapping[str, Any],
    candidate_rows: Sequence[Mapping[str, Any]],
    pareto_rows: Sequence[Mapping[str, Any]],
    scenario_rows: Sequence[Mapping[str, Any]],
    issue_rows: Sequence[Mapping[str, Any]] = (),
    timeline_rows: Sequence[Mapping[str, Any]] = (),
    baseline_schedule_rows: Sequence[Mapping[str, Any]] = (),
    optimized_schedule_rows: Sequence[Mapping[str, Any]] = (),
    baseline_arc_rows: Sequence[Mapping[str, Any]] = (),
    optimized_arc_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """生成完整解释包并返回可嵌入主摘要的索引。"""

    output_dir = Path(output_dir)
    if workflow == "timetable_optimization":
        decision = dict(summary.get("optimization_decision") or {})
        candidate_details, funnel = _timetable_candidate_details(candidate_rows, scenario_rows, pareto_rows, decision)
        baseline_id = next((str(row["candidate_id"]) for row in candidate_details if row["baseline"]), "")
        selected_id = str(decision.get("selected_candidate_id", ""))
        if not selected_id and decision.get("action") == "keep_baseline":
            selected_id = baseline_id
        active = {str(row.get("candidate_id", "")): row for row in scenario_rows if str(row.get("scenario_id", "")) == ACTIVE_SCENARIO}
        base_raw, opt_raw = active.get(baseline_id, {}), active.get(selected_id, {})
        baseline_metrics = {
            "effective_regen_loss_kwh": base_raw.get("effective_regen_loss_kwh_est"),
            "grid_kwh": base_raw.get("grid_kwh_est"),
            "wasted_kwh": base_raw.get("wasted_kwh_est"),
            "battery_charge_kwh": base_raw.get("storage_absorbed_kwh_est"),
            "battery_discharge_kwh": base_raw.get("storage_discharged_kwh_est"),
            "final_soc_kwh": base_raw.get("final_soc_kwh_est"),
            "constraint_violation": base_raw.get("constraint_violation"),
            "resource_conflict_count": base_raw.get("resource_conflict_count"),
        }
        optimized_metrics = {
            "effective_regen_loss_kwh": opt_raw.get("effective_regen_loss_kwh_est"),
            "grid_kwh": opt_raw.get("grid_kwh_est"),
            "wasted_kwh": opt_raw.get("wasted_kwh_est"),
            "battery_charge_kwh": opt_raw.get("storage_absorbed_kwh_est"),
            "battery_discharge_kwh": opt_raw.get("storage_discharged_kwh_est"),
            "final_soc_kwh": opt_raw.get("final_soc_kwh_est"),
            "constraint_violation": opt_raw.get("constraint_violation"),
        }
        comparable = bool(base_raw and opt_raw)
        scope = {
            "comparison_scope": "fixed_storage_timetable_only",
            "dispatch_only_attribution_allowed": comparable,
            "comparison_note": (
                "基线和候选使用同一组储能设备参数，系统级差值可归因于运行图调整。"
                if comparable else "本轮缺少可用于比较的方案评分，保留基线诊断。"
            ),
        }
        bottlenecks = _issue_bottlenecks(issue_rows, {baseline_id, selected_id})
        bottlenecks += _constraint_bottlenecks("baseline", baseline_metrics)
        bottlenecks += _constraint_bottlenecks("selected_candidate", optimized_metrics)
        dimensions = []
        if comparable:
            dimensions = _schedule_dimensions(baseline_schedule_rows, optimized_schedule_rows)
            dimensions += _issue_dimensions(issue_rows, baseline_id, selected_id)
    elif workflow == "dispatch":
        baseline_metrics = dict(summary.get("baseline") or {})
        optimized_metrics = dict(summary.get("optimized") or {})
        selected_storage = summary.get("selected_storage_preset") or {}
        baseline_storage_id = str(selected_storage.get("baseline_preset_id", ""))
        optimized_storage_id = str(selected_storage.get("optimized_preset_id", ""))
        storage_changed = baseline_storage_id != optimized_storage_id
        diagnostics = summary.get("optimizer_diagnostics") or {}
        core_feasible = bool(diagnostics.get("returned_candidate_core_robust_feasible", diagnostics.get("returned_candidate_score_feasible", False)))
        energy_comparable = core_feasible and all(_truth(row.get("feasible", True)) for row in (baseline_metrics, optimized_metrics))
        scope = {
            "comparison_scope": "joint_dispatch_and_storage_planning" if storage_changed else "fixed_storage_dispatch_only",
            "dispatch_only_attribution_allowed": energy_comparable and not storage_changed,
            "energy_comparison_eligible": energy_comparable,
            "comparison_note": (
                "基线与选中方案使用不同储能预设，差值只能解释为联合规划变化；必须固定储能重算后才能发布纯调度收益。"
                if storage_changed else
                "基线与选中方案使用相同储能预设，系统级差值可归因于调度变化。"
            ),
        }
        if not energy_comparable:
            scope["comparison_note"] = "基线或候选未通过适用约束检查，保留诊断评分。"
        candidate_details, funnel, selected_id = _dispatch_candidate_details(candidate_rows, pareto_rows, baseline_metrics, baseline_storage_id)
        if not core_feasible or not _truth(optimized_metrics.get("feasible", True)):
            action, reason = "no_feasible_solution", "selected_candidate_failed_core_robust_gate"
        elif not energy_comparable:
            action, reason = "optimize", "feasibility_restored_energy_comparison_unavailable"
        elif storage_changed:
            action, reason = "keep_baseline", "storage_preset_changed_requires_fixed_storage_recheck"
        else:
            loss_gain = _number(baseline_metrics.get("effective_regen_loss_kwh")) - _number(optimized_metrics.get("effective_regen_loss_kwh"))
            grid_gain = _number(baseline_metrics.get("grid_kwh")) - _number(optimized_metrics.get("grid_kwh"))
            if (loss_gain > ENERGY_TOLERANCE_KWH or grid_gain > ENERGY_TOLERANCE_KWH) and loss_gain >= -ENERGY_TOLERANCE_KWH and grid_gain >= -ENERGY_TOLERANCE_KWH:
                action, reason = "optimize", "material_energy_improvement_found"
            else:
                action, reason = "keep_baseline", "no_material_energy_improvement"
        decision = {"action": action, "reason": reason, "selected_candidate_id": selected_id}
        bottlenecks = _scenario_bottlenecks(scenario_rows)
        bottlenecks += _constraint_bottlenecks("baseline", baseline_metrics)
        bottlenecks += _constraint_bottlenecks("selected_candidate", optimized_metrics)
        dimensions = _schedule_dimensions(baseline_schedule_rows, optimized_schedule_rows)
        dimensions += _timeline_dimensions(timeline_rows)
        dimensions += _storage_dimensions(baseline_metrics, optimized_metrics)
        dimensions += _arc_dimensions(baseline_arc_rows, optimized_arc_rows)
    else:
        raise ValueError(f"不支持的归因工作流：{workflow}")

    metric_rows = _metric_rows(
        baseline_metrics,
        optimized_metrics,
        attribution_scope=str(scope["comparison_scope"]),
        attribution_allowed=bool(scope["dispatch_only_attribution_allowed"]),
        comparison_eligible=bool(scope.get("energy_comparison_eligible", True)),
    )
    dimensions.append({
        "dimension_type": "limitation",
        "dimension_id": "per_train_shared_storage_benefit",
        "metric": "grid_and_regen_saving",
        "unit": "kWh",
        "baseline": "",
        "optimized": "",
        "optimized_minus_baseline": "",
        "improvement": "",
        "attribution_quality": "not_identifiable_without_counterfactual_recalculation",
        "note": "共享供电臂和储能耦合，禁止按比例把系统收益分摊到单车。",
    })

    metric_fields = ["metric", "metric_label", "unit", "benefit_direction", "baseline", "optimized", "optimized_minus_baseline", "improvement", "improvement_pct", "attribution_scope", "dispatch_only_attribution_allowed", "interpretation"]
    candidate_fields = ["candidate_id", "status", "reason", "selected", "baseline", "feasible", "active_scenario_feasible", "pareto_member", "material_energy_improvement", "effective_regen_loss_improvement_kwh", "grid_improvement_kwh", "total_adjustment_min", "dominant_constraint", "dominant_constraint_value", "storage_preset_id", "fixed_storage_context"]
    funnel_fields = ["stage", "input_count", "remaining_count", "removed_count", "rule"]
    bottleneck_fields = ["scope", "bottleneck_type", "bottleneck_id", "occurrence_count", "magnitude", "unit", "blocking", "evidence"]
    dimension_fields = ["dimension_type", "dimension_id", "metric", "unit", "baseline", "optimized", "optimized_minus_baseline", "improvement", "attribution_quality", "note"]
    _write_csv(output_dir / "optimization_kpi_attribution.csv", metric_rows, metric_fields)
    _write_csv(output_dir / "optimization_candidate_decisions.csv", candidate_details, candidate_fields)
    _write_csv(output_dir / "optimization_candidate_funnel.csv", funnel, funnel_fields)
    _write_csv(output_dir / "optimization_bottlenecks.csv", bottlenecks, bottleneck_fields)
    _write_csv(output_dir / "optimization_dimension_attribution.csv", dimensions, dimension_fields)
    report_path = output_dir / "OPTIMIZATION_ATTRIBUTION_REPORT.md"
    report_path.write_text(_report(workflow, scope, decision, metric_rows, funnel, bottlenecks, dimensions), encoding="utf-8")
    machine_summary = {
        "schema_version": SCHEMA_VERSION,
        "workflow": workflow,
        "decision": decision,
        "attribution_scope": scope,
        "counts": {
            "metric_rows": len(metric_rows),
            "candidate_rows": len(candidate_details),
            "funnel_rows": len(funnel),
            "bottleneck_rows": len(bottlenecks),
            "dimension_rows": len(dimensions),
        },
        "top_bottlenecks": sorted(bottlenecks, key=lambda row: (_truth(row.get("blocking")), _number(row.get("magnitude"))), reverse=True)[:10],
        "limitations": [
            "shared_storage_benefit_not_allocated_to_individual_trains",
            "storage_preset_changes_are_not_dispatch_only_savings",
            "planning_placeholder_results_are_not_formal_engineering_conclusions",
        ],
        "outputs": {
            "summary": "optimization_attribution_summary.json",
            "report": "OPTIMIZATION_ATTRIBUTION_REPORT.md",
            "kpi_attribution": "optimization_kpi_attribution.csv",
            "candidate_decisions": "optimization_candidate_decisions.csv",
            "candidate_funnel": "optimization_candidate_funnel.csv",
            "bottlenecks": "optimization_bottlenecks.csv",
            "dimension_attribution": "optimization_dimension_attribution.csv",
        },
    }
    summary_path = output_dir / "optimization_attribution_summary.json"
    summary_path.write_text(json.dumps(machine_summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return machine_summary
