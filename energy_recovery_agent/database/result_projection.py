"""将现有算法输出投影为平台可查询的数据库记录。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, overload
from uuid import UUID, uuid5
import csv
import json
import math

from .snapshots import FileRecord, collect_file_records


NUMERIC_FIELDS = {
    "total_gen_kwh", "total_con_kwh", "accepted_by_power_arm_kwh",
    "recovered_energy_kwh", "recovery_rate", "direct_used_kwh",
    "battery_charge_kwh", "battery_discharge_kwh", "wasted_kwh", "grid_kwh",
    "effective_regen_loss_kwh", "final_soc_kwh", "constraint_violation", "total_cost",
}


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@overload
def _number(value: Any, default: float) -> float: ...


@overload
def _number(value: Any, default: None = None) -> float | None: ...


def _number(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    return float(value)


@overload
def _integer(value: Any, default: int) -> int: ...


@overload
def _integer(value: Any, default: None = None) -> int | None: ...


def _integer(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    return int(float(value))


def _clock_seconds(value: Any) -> int | None:
    if value in (None, ""):
        return None
    parts = str(value).split(":")
    if len(parts) != 3:
        return _integer(value)
    hours, minutes, seconds = (int(part) for part in parts)
    return hours * 3600 + minutes * 60 + seconds


def _boolean(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "是"}:
        return True
    if normalized in {"false", "0", "no", "否"}:
        return False
    raise ValueError(f"无法解析布尔值：{value!r}")


def _json_list(value: Any) -> list:
    if value in (None, ""):
        return []
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        raise ValueError("候选调整字段必须是JSON数组。")
    return parsed


def _candidate_uuid(run_id: UUID, source_code: str) -> UUID:
    return uuid5(run_id, f"candidate:{source_code}")


def _storage_planning_projection(run_id: UUID, output_dir: Path) -> dict[str, Any]:
    """将储能规划候选、设备、场景和最终决策投影为专用关系记录。"""

    summary_path = output_dir / "storage_planning_summary.json"
    if not summary_path.is_file():
        return {"plans": [], "devices": [], "scenarios": [], "decision": None}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    candidate_rows = _rows(output_dir / "storage_plan_candidates.csv")
    selected_code = str((summary.get("selected_plan") or {}).get("plan_id") or "")
    best_build_code = str((summary.get("best_feasible_build_alternative") or {}).get("plan_id") or "")
    plans = []
    plan_ids: dict[str, UUID] = {}
    ranked = sorted(candidate_rows, key=lambda row: (_number(row.get("annual_total_cost_cny"), 0.0), row.get("plan_id", "")))
    for rank, row in enumerate(ranked, start=1):
        code = str(row["plan_id"])
        plan_id = uuid5(run_id, f"storage-plan:{code}")
        plan_ids[code] = plan_id
        plans.append({
            "storage_plan_id": plan_id, "source_plan_code": code, "rank": rank,
            "selected": code == selected_code and summary.get("decision") != "no_feasible_plan",
            "feasible": _boolean(row.get("core_feasible")),
            "within_budget": _boolean(row.get("within_budget")),
            "meets_business_thresholds": _boolean(row.get("meets_business_thresholds")),
            "site_count": _integer(row.get("site_count"), 0), "site_codes": row.get("site_codes") or None,
            "total_capacity_kwh": _number(row.get("total_capacity_kwh"), 0.0),
            "total_charge_power_kw": _number(row.get("total_charge_power_kw"), 0.0),
            "total_discharge_power_kw": _number(row.get("total_discharge_power_kw"), 0.0),
            "capex_cny": _number(row.get("capex_cny"), 0.0),
            "annual_total_cost_cny": _number(row.get("annual_total_cost_cny"), 0.0),
            "annual_saving_vs_no_build_cny": _number(row.get("annual_saving_vs_no_build_cny")),
            "grid_reduction_vs_no_build_kwh_per_year": _number(row.get("grid_reduction_vs_no_build_kwh_per_year")),
            "rejection_reasons": row.get("rejection_reasons") or None, "metrics": row,
        })
    devices = []
    for row in _rows(output_dir / "storage_plan_devices.csv"):
        if row.get("plan_id") not in plan_ids:
            raise ValueError(f"储能规划设备引用未知方案：{row.get('plan_id')}")
        devices.append({
            "storage_plan_id": plan_ids[str(row["plan_id"])], "device_index": _integer(row.get("device_index"), 0),
            "site_code": row.get("site_code"), "technology_code": row.get("technology_code"),
            "capacity_kwh": _number(row.get("capacity_kwh"), 0.0),
            "charge_power_kw": _number(row.get("charge_power_kw"), 0.0),
            "discharge_power_kw": _number(row.get("discharge_power_kw"), 0.0),
            "capex_cny": _number(row.get("capex_cny"), 0.0), "device": row,
        })
    scenarios = []
    for row in _rows(output_dir / "storage_plan_scenario_results.csv"):
        if row.get("plan_id") not in plan_ids:
            raise ValueError(f"储能规划场景引用未知方案：{row.get('plan_id')}")
        scenarios.append({
            "storage_plan_id": plan_ids[str(row["plan_id"])], "scenario_code": row.get("scenario_code"),
            "core_for_feasibility": _boolean(row.get("core_for_feasibility")), "feasible": _boolean(row.get("feasible")),
            "grid_kwh": _number(row.get("grid_kwh")), "wasted_kwh": _number(row.get("wasted_kwh")),
            "storage_charge_kwh": _number(row.get("storage_charge_kwh")),
            "storage_discharge_kwh": _number(row.get("storage_discharge_kwh")),
            "final_soc_kwh": _number(row.get("final_soc_kwh")),
            "annual_operating_cost_cny": _number(row.get("annual_operating_cost_cny")), "result": row,
        })
    search = summary.get("declared_search_domain") or {}
    decision = {
        "decision": summary.get("decision", "keep_no_build"),
        "selected_storage_plan_id": plan_ids.get(selected_code), "best_build_storage_plan_id": plan_ids.get(best_build_code),
        "decision_reason": summary.get("decision_reason", "unspecified"),
        "recommendation_level": summary.get("recommendation_level", "planning_sensitivity"),
        "formal_engineering_conclusion_allowed": bool(summary.get("formal_engineering_conclusion_allowed", False)),
        "complete_for_declared_domain": bool(search.get("complete_for_declared_domain", False)), "decision_json": summary,
    }
    return {"plans": plans, "devices": devices, "scenarios": scenarios, "decision": decision}


def _rolling_control_projection(run_id: UUID, output_dir: Path) -> list[dict]:
    """把逐轮安全状态投影为可幂等写库的控制事件。"""

    projected = []
    for row in _rows(output_dir / "rolling_cycles.csv"):
        cycle_index = _integer(row.get("cycle_index"))
        if cycle_index is None:
            raise ValueError("滚动控制事件缺少cycle_index。")
        transition = json.loads(row.get("safety_transition") or "{}")
        if not isinstance(transition, dict):
            raise ValueError("safety_transition必须是JSON对象。")
        request_fingerprint = str(transition.get("request_fingerprint") or "")
        if len(request_fingerprint) != 64:
            raise ValueError("滚动控制事件缺少有效的request_fingerprint。")
        storage_runtime = {}
        for field_name, expected_type, empty_value in (
            ("storage_device_states", list, []),
            ("storage_parameters_by_id", dict, {}),
            ("initial_soc_by_storage_kwh", dict, {}),
            ("executed_final_soc_by_storage_kwh", dict, {}),
            ("executed_charge_by_storage_kwh", dict, {}),
            ("executed_discharge_by_storage_kwh", dict, {}),
            ("executed_wasted_by_storage_kwh", dict, {}),
        ):
            raw_value = row.get(field_name)
            parsed_value = json.loads(raw_value) if raw_value else empty_value
            if not isinstance(parsed_value, expected_type):
                raise ValueError(f"滚动控制事件字段{field_name}的JSON类型无效。")
            storage_runtime[field_name] = parsed_value
        event_payload = dict(transition)
        event_payload["storage_runtime"] = storage_runtime
        source_record_ids = json.loads(row.get("source_record_ids") or "[]")
        if not isinstance(source_record_ids, list) or not all(
            isinstance(item, str) and item.strip() for item in source_record_ids
        ):
            raise ValueError("滚动控制事件字段source_record_ids必须是字符串数组。")
        observed_train_delays = json.loads(row.get("observed_train_delays_s") or "{}")
        disturbance_events = json.loads(row.get("disturbance_events") or "[]")
        if not isinstance(observed_train_delays, dict):
            raise ValueError("滚动控制事件字段observed_train_delays_s必须是JSON对象。")
        if not isinstance(disturbance_events, list):
            raise ValueError("滚动控制事件字段disturbance_events必须是JSON数组。")
        event_payload["observation"] = {
            "observed_at": row.get("observed_at") or "",
            "source_record_ids": source_record_ids,
            "observed_heavy_delay_s": _integer(
                row.get("observed_heavy_delay_s"), 0
            ),
            "observed_empty_delay_s": _integer(
                row.get("observed_empty_delay_s"), 0
            ),
            "observed_train_delays_s": observed_train_delays,
            "disturbance_events": disturbance_events,
            "storage_states_provided": _boolean(
                row.get("storage_states_provided")
            ),
        }
        projected.append({
            "event_id": uuid5(run_id, f"rolling-control:{cycle_index}"),
            "cycle_index": cycle_index,
            "current_time_s": _integer(row.get("current_time_s"), 0),
            "commit_status": row.get("commit_status") or "withheld_infeasible",
            "safety_state": row.get("safety_state") or "manual_intervention_required",
            "safety_action": row.get("safety_action") or "hold_new_departures_and_request_dispatcher",
            "core_robust_feasible": _boolean(row.get("core_robust_feasible")),
            "operational_intervention_required": _boolean(
                row.get("operational_intervention_required")
            ),
            "attempt_count": _integer(row.get("safety_attempt_count"), 1),
            "request_fingerprint": request_fingerprint,
            "event": event_payload,
        })
    return projected


def _candidate_projection(run_id: UUID, output_dir: Path) -> tuple[list[dict], list[dict]]:
    source_rows = _rows(output_dir / "ranked_candidates.csv")
    if not source_rows:
        source_rows = _rows(output_dir / "candidate_scenario_scores.csv")
    if not source_rows:
        source_rows = _rows(output_dir / "pareto_candidates.csv")
    pareto_codes = {
        row.get("candidate_id") for row in _rows(output_dir / "pareto_candidates.csv")
    }
    candidates = []
    adjustments = []
    seen = set()
    for row in source_rows:
        source_code = str(row.get("candidate_id", "")).strip()
        if not source_code or source_code in seen:
            continue
        seen.add(source_code)
        candidate_id = _candidate_uuid(run_id, source_code)
        parameters = {
            key: row.get(key)
            for key in (
                "heavy_headway_s", "empty_headway_s", "heavy_empty_phase_s",
                "flex_zone_hold_s", "storage_align_shift_s", "heavy_count", "empty_count",
                "heavy_departures_s", "empty_departures_s",
            )
            if row.get(key) not in (None, "")
        }
        is_optimizer_candidate = "effective_regen_loss_kwh_est" in row
        candidates.append({
            "candidate_id": candidate_id,
            "source_candidate_code": source_code,
            "candidate_set": row.get("candidate_set") or ("pareto" if source_code in pareto_codes else "population"),
            "rank": _integer(row.get("rank")),
            "feasible": _boolean(row.get("feasible")),
            "pareto": (row.get("candidate_set") == "pareto" or source_code in pareto_codes),
            "energy_scenario": row.get("energy_scenario") or row.get("scenario_id") or row.get("pareto_scenario_id") or None,
            "storage_preset_id": row.get("storage_preset_id") or None,
            "objective_priority": row.get("objective_priority") or None,
            "objective_1": _number(row.get("objective_1_effective_regen_loss_kwh") or row.get("effective_regen_loss_kwh_est")),
            "objective_2": _number(row.get("objective_2_grid_kwh") or row.get("grid_kwh_est")),
            "objective_3": _number(row.get("objective_3_capacity_or_headway") or row.get("total_adjustment_min")),
            "constraint_violation": _number(row.get("constraint_violation"), 0.0),
            "total_cost": _number(row.get("total_cost")),
            "grid_kwh": _number(row.get("grid_kwh") or row.get("grid_kwh_est")),
            "wasted_kwh": _number(row.get("wasted_kwh") or row.get("wasted_kwh_est")),
            "recovered_energy_kwh": _number(row.get("recovered_energy_kwh")),
            "final_soc_kwh": _number(row.get("final_soc_kwh") or row.get("final_soc_kwh_est")),
            "resource_conflict_count": _integer(row.get("resource_conflict_count"), 0),
            "parameters": parameters,
            "metrics": dict(row),
        })
        if is_optimizer_candidate:
            parameters["action_type"] = row.get("action_type")
            parameters["description"] = row.get("description")
        for train_type, prefix in (("heavy", "H"), ("empty", "E")):
            values = _json_list(row.get(f"{train_type}_departure_adjustments_s"))
            for index, adjustment in enumerate(values, start=1):
                adjustments.append({
                    "candidate_id": candidate_id,
                    "train_id": f"{prefix}{index:03d}",
                    "train_type": train_type,
                    "sequence_no": index,
                    "adjustment_s": int(adjustment),
                })
    return candidates, adjustments


def _kpi_projection(output_dir: Path) -> list[dict]:
    projected = []
    for row in _rows(output_dir / "kpi_summary.csv"):
        metrics = dict(row)
        item = {
            "case_name": row.get("case") or "unknown",
            "feasible": _boolean(row.get("feasible")),
            "resource_conflict_count": _integer(row.get("resource_conflict_count"), 0),
            "metrics": metrics,
        }
        for field in NUMERIC_FIELDS:
            item[field] = _number(row.get(field))
        item["constraint_violation"] = item["constraint_violation"] or 0.0
        projected.append(item)
    return projected


def _energy_slices(output_dir: Path, settlement_step_s: int) -> list[dict]:
    audit_rows = _rows(output_dir / "timetable_energy_time_slices.csv")
    if audit_rows:
        return [{
            "case_name": row.get("scenario_id") or "unknown",
            "slice_start_s": _integer(row.get("time_window_start_s"), 0),
            "slice_end_s": _integer(row.get("time_window_end_s"), settlement_step_s),
            "power_arm_code": row.get("power_arm_id") or None,
            "storage_code": row.get("storage_section_id") or None,
            "traction_kwh": _number(row.get("traction_kwh"), 0.0),
            "regen_kwh": _number(row.get("regen_kwh"), 0.0),
            "accepted_by_power_arm_kwh": _number(
                row.get("accepted_by_power_arm_kwh"), 0.0
            ),
            "direct_used_kwh": 0.0,
            "battery_charge_kwh": 0.0,
            "battery_discharge_kwh": 0.0,
            "wasted_kwh": 0.0,
            "grid_kwh": 0.0,
            "soc_before_kwh": None,
            "soc_after_kwh": None,
            "constraint_violation_kwh": _number(
                row.get("constraint_violation_kwh"), 0.0
            ),
            "details": dict(row),
        } for row in audit_rows]
    source = _rows(output_dir / "energy_timeline.csv")
    projected = []
    cases: dict[str, list[dict[str, str]]] = {}
    for row in source:
        cases.setdefault(row.get("case") or "unknown", []).append(row)
    for case_name, case_rows in cases.items():
        case_rows.sort(key=lambda item: float(item["time_s"]))
        for index, row in enumerate(case_rows):
            start_s = int(float(row["time_s"]))
            if index + 1 < len(case_rows):
                end_s = int(float(case_rows[index + 1]["time_s"]))
            else:
                end_s = start_s + settlement_step_s
            if end_s <= start_s:
                raise ValueError(f"能量时间片非递增：{case_name} {start_s}->{end_s}")
            duration_h = (end_s - start_s) / 3600.0
            direct_kwh = float(row.get("direct_used_kW") or 0) * duration_h
            charge_kwh = float(row.get("battery_charge_kW") or 0) * duration_h
            discharge_kwh = float(row.get("battery_discharge_kW") or 0) * duration_h
            wasted_kwh = float(row.get("wasted_kW") or 0) * duration_h
            grid_kwh = float(row.get("grid_kW") or 0) * duration_h
            projected.append({
                "case_name": case_name,
                "slice_start_s": start_s,
                "slice_end_s": end_s,
                "traction_kwh": direct_kwh + discharge_kwh + grid_kwh,
                "regen_kwh": direct_kwh + charge_kwh + wasted_kwh,
                "accepted_by_power_arm_kwh": direct_kwh + charge_kwh,
                "direct_used_kwh": direct_kwh,
                "battery_charge_kwh": charge_kwh,
                "battery_discharge_kwh": discharge_kwh,
                "wasted_kwh": wasted_kwh,
                "grid_kwh": grid_kwh,
                "soc_before_kwh": None,
                "soc_after_kwh": _number(row.get("soc_kwh")),
                "constraint_violation_kwh": _number(
                    row.get("constraint_violation_kwh"), 0.0
                ),
                "details": dict(row),
            })
    return projected


def _arc_projection(output_dir: Path) -> list[dict]:
    projected = []
    source_rows = _rows(output_dir / "time_space_arcs.csv")
    if not source_rows:
        source_rows = _rows(output_dir / "timetable_running_arcs.csv")
    for row in source_rows:
        energy = _number(row.get("energy_kwh"), 0.0) or 0.0
        projected.append({
            "source_arc_id": row.get("arc_id") or None,
            "train_id": row.get("train_id") or "unknown",
            "train_type": row.get("train_type") or None,
            "direction": row.get("direction") or None,
            "from_station_code": row.get("start_station") or None,
            "to_station_code": row.get("end_station") or None,
            "arc_type": row.get("arc_type") or None,
            "start_time_s": _integer(row.get("start_time_s"), 0),
            "end_time_s": _integer(row.get("end_time_s"), 0),
            "start_km": _number(row.get("start_km")),
            "end_km": _number(row.get("end_km")),
            "traction_energy_kwh": max(0.0, energy),
            "regen_energy_kwh": max(0.0, -energy),
            "power_arm_code": row.get("power_arm_ids") or None,
            "storage_code": row.get("storage_section_id") or None,
            "details": dict(row),
        })
    return projected


def _conflict_projection(output_dir: Path) -> list[dict]:
    projected = []
    for row in _rows(output_dir / "resource_conflicts.csv"):
        location_text = (row.get("location_km") or "").strip()
        try:
            location_km = _number(location_text.removesuffix(" km"))
        except ValueError:
            location_km = None
        if location_km is not None and not math.isfinite(location_km):
            location_km = None
        message = row.get("message") or ""
        # 区间里程在原始CSV和提示中保留，数据库的单点里程留空。
        if location_km is None and location_text and location_text != "unknown":
            message = f"{message} 位置 {location_text}".strip()
        projected.append({
            "case_name": row.get("case") or None,
            "conflict_type": row.get("conflict_type") or "unknown",
            "severity": row.get("severity") or "blocking",
            "resource_code": row.get("resource_id") or None,
            "resource_name": row.get("resource_name") or None,
            "train_a": row.get("train_a") or None,
            "train_b": row.get("train_b") or None,
            "overlap_start_s": _number(row.get("overlap_start_s")),
            "overlap_end_s": _number(row.get("overlap_end_s")),
            "overlap_duration_s": _number(row.get("overlap_duration_s"), 0.0),
            "location_km": location_km,
            "message": message or None,
            "suggestion": row.get("suggestion") or None,
        })
    return projected


def _scenario_projection(run_id: UUID, output_dir: Path) -> list[dict]:
    projected = []
    source_rows = _rows(output_dir / "selected_plan_scenario_diagnostics.csv")
    if not source_rows:
        source_rows = _rows(output_dir / "scenario_summary.csv")
    if not source_rows:
        source_rows = _rows(output_dir / "candidate_scenario_scores.csv")
    for row in source_rows:
        candidate_code = row.get("candidate_id")
        projected.append({
            "candidate_id": _candidate_uuid(run_id, candidate_code) if candidate_code else None,
            "scenario_name": row.get("scenario") or row.get("scenario_id") or "unknown",
            "core_for_feasibility": _boolean(row.get("core_for_feasibility"), True),
            "feasible": _boolean(row.get("feasible"), row.get("assessment") != "invalid"),
            "blocking": _boolean(row.get("blocking"), False),
            "constraint_violation": _number(row.get("constraint_violation"), 0.0),
            "resource_conflict_count": _integer(row.get("resource_conflict_count"), 0),
            "total_cost": _number(row.get("total_cost")),
            "grid_kwh": _number(row.get("grid_kwh") or row.get("grid_kwh_est")),
            "wasted_kwh": _number(row.get("wasted_kwh") or row.get("wasted_kwh_est")),
            "battery_charge_kwh": _number(row.get("battery_charge_kwh") or row.get("storage_absorbed_kwh")),
            "battery_discharge_kwh": _number(row.get("battery_discharge_kwh") or row.get("storage_discharged_kwh")),
            "final_soc_deviation_kwh": _number(row.get("final_soc_deviation_kwh")),
            "conflict_summary": row.get("conflict_summary") or None,
            "details": dict(row),
        })
    return projected


def _power_arm_settlements(output_dir: Path) -> list[dict]:
    return [{
        "power_arm_code": row.get("power_arm_id") or "unknown",
        "window_start_s": _integer(row.get("time_window_start_s"), 0),
        "window_end_s": _integer(row.get("time_window_end_s"), 0),
        "traction_demand_kwh": _number(row.get("traction_kwh"), 0.0),
        "regen_input_kwh": _number(row.get("regen_kwh"), 0.0),
        "accepted_kwh": (_number(row.get("direct_used_kwh"), 0.0) or 0.0) + (_number(row.get("storage_absorbed_kwh"), 0.0) or 0.0),
        "charge_kwh": _number(row.get("storage_absorbed_kwh"), 0.0),
        "discharge_kwh": _number(row.get("storage_discharged_kwh"), 0.0),
        "wasted_kwh": _number(row.get("wasted_kwh"), 0.0),
        "grid_kwh": _number(row.get("grid_kwh"), 0.0),
        "max_traction_supply_kw": _number(row.get("max_traction_supply_kw")),
        "max_regen_absorption_kw": _number(row.get("max_regen_absorption_kw")),
        "electrical_constraint_violation_kwh": (
            (_number(row.get("traction_supply_excess_kwh"), 0.0) or 0.0)
            + (_number(row.get("regen_absorption_excess_kwh"), 0.0) or 0.0)
        ),
    } for row in _rows(output_dir / "timetable_power_arm_settlement.csv")]


def _audit_issues(run_id: UUID, output_dir: Path) -> list[dict]:
    projected = []
    for row in _rows(output_dir / "audit_issues.csv"):
        source_code = row.get("issue_id") or f"issue-{len(projected) + 1}"
        projected.append({
            "issue_id": uuid5(run_id, f"issue:{source_code}"),
            "source_issue_code": source_code,
            "issue_type": row.get("issue_type") or "unknown",
            "severity": row.get("severity") or "warning",
            "power_arm_code": row.get("power_arm_id") or None,
            "start_time_s": _clock_seconds(row.get("time_window_start")),
            "end_time_s": _clock_seconds(row.get("time_window_end")),
            "impact_kwh": _number(row.get("estimated_wasted_kwh")),
            "reason": row.get("reason") or "未提供原因",
            "details": dict(row),
        })
    return projected


def _optimization_suggestions(run_id: UUID, output_dir: Path, issues: list[dict]) -> list[dict]:
    issue_ids = {item["source_issue_code"]: item["issue_id"] for item in issues}
    projected = []
    for row in _rows(output_dir / "optimization_suggestions.csv"):
        source_code = row.get("suggestion_id") or f"suggestion-{len(projected) + 1}"
        projected.append({
            "suggestion_id": uuid5(run_id, f"suggestion:{source_code}"),
            "source_issue_id": issue_ids.get(row.get("source_issue_id", "")),
            "suggestion_type": row.get("source_issue_type") or "timetable_adjustment",
            "reason": row.get("action") or row.get("expected_effect") or "未提供建议",
        })
    return projected


def project_result_directory(run_id: UUID, output_dir: Path, settlement_step_s: int = 10) -> dict:
    """读取一个算法输出目录，返回可批量写库的标准化记录。"""

    root = Path(output_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"算法输出目录不存在：{root}")
    artifacts: tuple[FileRecord, ...] = collect_file_records(root)
    if (root / "shadow_summary.json").is_file():
        from rolling_shadow import validate_shadow_output
        shadow = validate_shadow_output(root)
        # 影子候选、轨迹和循环只进入无损工件；禁止投影到普通候选或滚动控制表。
        empty_keys = ("candidates", "candidate_adjustments", "kpis", "energy_slices", "running_arcs",
                      "resource_conflicts", "scenario_results", "power_arm_settlements", "audit_issues",
                      "optimization_suggestions", "rolling_control_events", "storage_plans", "storage_plan_devices",
                      "storage_plan_scenario_results")
        return {**{key: [] for key in empty_keys}, "summary":shadow, "artifacts":artifacts,
                "decision":shadow["optimization_decision"], "storage_plan_decision":None}
    summary_path = root / "summary.json"
    audit_summary_path = root / "audit_summary.json"
    optimizer_summary_path = root / "optimizer_summary.json"
    rolling_summary_path = root / "benchmark_summary.json"
    joint_robustness_summary_path = root / "joint_robustness_summary.json"
    summary = {}
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    elif audit_summary_path.is_file():
        summary = json.loads(audit_summary_path.read_text(encoding="utf-8"))
    elif optimizer_summary_path.is_file():
        summary = json.loads(optimizer_summary_path.read_text(encoding="utf-8"))
    elif rolling_summary_path.is_file():
        summary = json.loads(rolling_summary_path.read_text(encoding="utf-8"))
    elif joint_robustness_summary_path.is_file():
        summary = json.loads(joint_robustness_summary_path.read_text(encoding="utf-8"))
    if (root / "storage_planning_summary.json").is_file():
        summary = json.loads((root / "storage_planning_summary.json").read_text(encoding="utf-8"))
    candidates, adjustments = _candidate_projection(run_id, root)
    decision = summary.get("optimization_decision")
    attribution = summary.get("optimization_attribution")
    if not isinstance(decision, dict) and isinstance(attribution, dict):
        attributed_decision = attribution.get("decision")
        if isinstance(attributed_decision, dict):
            decision = dict(attributed_decision)
    if not isinstance(decision, dict):
        diagnostics = summary.get("optimizer_diagnostics", {})
        if diagnostics.get("returned_candidate_core_robust_feasible"):
            decision = {
                "action": "optimize",
                "reason": "core_robust_feasible_candidate_selected",
            }
        elif optimizer_summary_path.is_file() and candidates:
            selected = next((item for item in candidates if item["pareto"]), candidates[0])
            selected_code = selected["source_candidate_code"]
            decision = {
                "action": "keep_baseline" if selected_code == "G0000" else "optimize",
                "selected_candidate_id": selected_code,
                "reason": "pareto_baseline_is_best" if selected_code == "G0000" else "pareto_candidate_selected",
            }
        elif audit_summary_path.is_file():
            decision = {
                "action": "keep_baseline",
                "reason": "audit_only_no_optimization_requested",
            }
        else:
            decision = {
                "action": "no_feasible_solution",
                "reason": "no_core_robust_feasible_candidate",
            }
    issues = _audit_issues(run_id, root)
    storage_planning = _storage_planning_projection(run_id, root)
    rolling_control_events = _rolling_control_projection(run_id, root)
    if rolling_control_events:
        latest = rolling_control_events[-1]
        decision = {
            "action": (
                "no_feasible_solution"
                if latest["commit_status"] == "withheld_infeasible"
                else "optimize"
            ),
            "reason": latest["safety_state"],
            "commit_status": latest["commit_status"],
            "core_robust_feasible": latest["core_robust_feasible"],
            "operational_intervention_required": latest[
                "operational_intervention_required"
            ],
            "safety_action": latest["safety_action"],
        }
    return {
        "summary": summary,
        "artifacts": artifacts,
        "candidates": candidates,
        "candidate_adjustments": adjustments,
        "kpis": _kpi_projection(root),
        "energy_slices": _energy_slices(root, settlement_step_s),
        "running_arcs": _arc_projection(root),
        "resource_conflicts": _conflict_projection(root),
        "scenario_results": _scenario_projection(run_id, root),
        "power_arm_settlements": _power_arm_settlements(root),
        "audit_issues": issues,
        "optimization_suggestions": _optimization_suggestions(run_id, root, issues),
        "rolling_control_events": rolling_control_events,
        "decision": None if storage_planning["decision"] is not None else decision,
        "storage_plans": storage_planning["plans"],
        "storage_plan_devices": storage_planning["devices"],
        "storage_plan_scenarios": storage_planning["scenarios"],
        "storage_plan_decision": storage_planning["decision"],
    }
