"""储能规划第三轮：重优化敏感性、稳定区间与独立质量门禁。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence
import csv
import json
import math
import shutil

from storage_planning_contract import load_storage_planning_bundle
from storage_planning_mixed import build_storage_planning_mixed_inputs
from storage_planning_mvp import run_storage_planning_mvp


DEFAULT_SENSITIVITY_CASES: tuple[dict[str, Any], ...] = (
    {"case_code": "base", "case_name": "当前混合参数"},
    {"case_code": "transport_low", "case_name": "重空质量降低10%", "overrides": {"heavy_mass_factor": 0.9, "empty_mass_factor": 0.9}},
    {"case_code": "transport_high", "case_name": "重空质量提高10%", "overrides": {"heavy_mass_factor": 1.1, "empty_mass_factor": 1.1}},
    {"case_code": "grid_price_low", "case_name": "电价降低20%", "grid_price_factor": 0.8},
    {"case_code": "grid_price_high", "case_name": "电价提高20%", "grid_price_factor": 1.2},
    {"case_code": "storage_capex_low", "case_name": "储能投资降低30%", "storage_cost_factor": 0.7},
    {"case_code": "storage_capex_high", "case_name": "储能投资提高30%", "storage_cost_factor": 1.3},
    {"case_code": "storage_efficiency_low", "case_name": "储能效率系数降低10%", "overrides": {"storage_efficiency_factor": 0.9}},
    {"case_code": "regen_capability_low", "case_name": "制动能力降低10%", "overrides": {"brake_power_factor": 0.9}},
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _copy_base_inputs(base: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for source in base.iterdir():
        if source.is_file():
            shutil.copy2(source, target / source.name)


def _apply_case(input_dir: Path, case: Mapping[str, Any]) -> None:
    scenario_path = input_dir / "storage_planning_scenarios.json"
    scenarios = json.loads(scenario_path.read_text(encoding="utf-8"))
    grid_factor = float(case.get("grid_price_factor", 1.0))
    overrides = dict(case.get("overrides", {}))
    for scenario in scenarios["scenarios"]:
        scenario["grid_price_per_kwh"] = float(scenario["grid_price_per_kwh"]) * grid_factor
        existing = dict(scenario.get("parameter_overrides", {}))
        for key, factor in overrides.items():
            existing[key] = float(existing.get(key, 1.0)) * float(factor)
        scenario["parameter_overrides"] = existing
        scenario["source_note"] = (
            str(scenario.get("source_note", ""))
            + f"；可信度敏感性案例 {case['case_code']}。"
        )
    scenarios["scenario_set_code"] = f"{scenarios['scenario_set_code']}__{case['case_code']}"
    scenario_path.write_text(json.dumps(scenarios, ensure_ascii=False, indent=2), encoding="utf-8")

    cost_factor = float(case.get("storage_cost_factor", 1.0))
    if not math.isclose(cost_factor, 1.0):
        site_path = input_dir / "storage_candidate_sites.csv"
        site_rows = _read_csv(site_path)
        with site_path.open("r", encoding="utf-8-sig", newline="") as handle:
            fields = list(csv.DictReader(handle).fieldnames or ())
        for row in site_rows:
            row["fixed_site_cost_cny"] = str(float(row["fixed_site_cost_cny"]) * cost_factor)
        _write_csv(site_path, site_rows, fields)

        technology_path = input_dir / "storage_technologies.csv"
        technology_rows = _read_csv(technology_path)
        with technology_path.open("r", encoding="utf-8-sig", newline="") as handle:
            fields = list(csv.DictReader(handle).fieldnames or ())
        for row in technology_rows:
            for field in (
                "fixed_device_cost_cny", "cost_per_kwh_cny",
                "charge_power_cost_per_kw_cny", "discharge_power_cost_per_kw_cny",
            ):
                row[field] = str(float(row[field]) * cost_factor)
        _write_csv(technology_path, technology_rows, fields)


def audit_storage_planning_result(input_dir: Path, result_dir: Path) -> dict[str, Any]:
    """独立核对搜索完整性、决策语义、数据等级和关键结果表。"""

    bundle = load_storage_planning_bundle(input_dir)
    summary = json.loads((result_dir / "storage_planning_summary.json").read_text(encoding="utf-8"))
    candidates = _read_csv(result_dir / "storage_plan_candidates.csv")
    scenario_rows = _read_csv(result_dir / "storage_plan_scenario_results.csv")
    lifecycle_rows = _read_csv(result_dir / "storage_plan_lifecycle.csv")
    plan_ids = [row["plan_id"] for row in candidates]
    selected_id = summary["selected_plan"]["plan_id"]
    selected_rows = [row for row in candidates if row["plan_id"] == selected_id]
    build_rows = [row for row in candidates if int(float(row["site_count"])) > 0]
    eligible_builds = [
        row for row in build_rows
        if row["within_budget"] == "True" and row["core_feasible"] == "True"
        and row["meets_business_thresholds"] == "True"
    ]
    gates = {
        "search_complete": summary["declared_search_domain"]["complete_for_declared_domain"] is True,
        "candidate_count_matches": len(candidates) == summary["declared_search_domain"]["evaluated_plan_count"],
        "candidate_ids_unique": len(plan_ids) == len(set(plan_ids)),
        "selected_plan_exists_once": len(selected_rows) == 1,
        "scenario_matrix_complete": len(scenario_rows) == len(candidates) * len(bundle.scenarios),
        "lifecycle_rows_cover_devices": len(lifecycle_rows) == sum(int(float(row["site_count"])) for row in build_rows),
        "placeholder_cannot_be_formal": not summary["formal_engineering_conclusion_allowed"] if bundle.recommendation_level != "formal_engineering" else True,
        "recommendation_level_matches_input": summary["recommendation_level"] == bundle.recommendation_level,
        "numeric_energy_nonnegative": all(
            float(row[field]) >= -1e-9
            for row in scenario_rows
            for field in ("grid_kwh", "wasted_kwh", "storage_charge_kwh", "storage_discharge_kwh", "self_discharge_loss_kwh")
        ),
        "decision_semantics_consistent": (
            summary["decision"] == "recommend_build" and bool(eligible_builds) and selected_id != "NO_BUILD"
        ) or (
            summary["decision"] == "keep_no_build" and not eligible_builds and selected_id == "NO_BUILD"
        ) or summary["decision"] == "no_feasible_plan",
    }
    failures = sorted(name for name, passed in gates.items() if not passed)
    return {
        "passed": not failures,
        "gate_count": len(gates),
        "passed_gate_count": sum(bool(value) for value in gates.values()),
        "failed_gates": failures,
        "gates": gates,
    }


def _stability_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    decisions = [str(row["decision"]) for row in rows]
    selected_sites = [str(row["selected_sites"]) or "NO_BUILD" for row in rows]
    alternatives = [str(row["best_alternative_sites"]) for row in rows if row.get("best_alternative_sites")]
    decision_stable = len(set(decisions)) == 1
    selected_stable = len(set(selected_sites)) == 1
    alternative_stable = bool(alternatives) and len(set(alternatives)) == 1
    grade = "high" if decision_stable and selected_stable and alternative_stable else "medium" if decision_stable else "low"
    capacities = [float(row["best_alternative_capacity_kwh"]) for row in rows if row.get("best_alternative_sites")]
    charge_powers = [float(row["best_alternative_charge_power_kw"]) for row in rows if row.get("best_alternative_sites")]
    discharge_powers = [float(row["best_alternative_discharge_power_kw"]) for row in rows if row.get("best_alternative_sites")]
    savings = [float(row["best_alternative_annual_saving_cny"]) for row in rows if row.get("best_alternative_sites")]
    return {
        "stability_grade": grade,
        "decision_stable": decision_stable,
        "selected_site_stable": selected_stable,
        "best_alternative_site_stable": alternative_stable,
        "decision_counts": dict(sorted(Counter(decisions).items())),
        "selected_site_counts": dict(sorted(Counter(selected_sites).items())),
        "best_alternative_site_counts": dict(sorted(Counter(alternatives).items())),
        "best_alternative_capacity_kwh_range": [min(capacities), max(capacities)] if capacities else None,
        "best_alternative_charge_power_kw_range": [min(charge_powers), max(charge_powers)] if charge_powers else None,
        "best_alternative_discharge_power_kw_range": [min(discharge_powers), max(discharge_powers)] if discharge_powers else None,
        "best_alternative_annual_saving_cny_range": [min(savings), max(savings)] if savings else None,
    }


def run_storage_planning_credibility(
    data_dir: Path | str,
    timetable_path: Path | str,
    output_dir: Path | str,
    *,
    cases: Sequence[Mapping[str, Any]] = DEFAULT_SENSITIVITY_CASES,
    settlement_step_s: int = 300,
) -> dict[str, Any]:
    """对每个参数案例重新优化，汇总稳定性并执行独立质量门禁。"""

    output_root = Path(output_dir).resolve()
    base_inputs = output_root / "base_inputs"
    build_storage_planning_mixed_inputs(data_dir, timetable_path, base_inputs)
    run_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for case in cases:
        case_code = str(case["case_code"])
        input_dir = output_root / "case_inputs" / case_code
        result_dir = output_root / "case_results" / case_code
        _copy_base_inputs(base_inputs, input_dir)
        _apply_case(input_dir, case)
        summary = run_storage_planning_mvp(
            input_dir,
            data_dir,
            result_dir,
            max_levels_per_dimension=2,
            settlement_step_s=settlement_step_s,
            search_mode="coarse",
        )
        audit = audit_storage_planning_result(input_dir, result_dir)
        alternative = summary.get("best_feasible_build_alternative") or {}
        alternative_scenarios = [
            row for row in _read_csv(result_dir / "storage_plan_scenario_results.csv")
            if row["plan_id"] == alternative.get("plan_id")
        ]
        worst_grid_row = max(alternative_scenarios, key=lambda row: float(row["grid_kwh"]), default={})
        explanation = summary["decision_explanation"]
        run_rows.append({
            "case_code": case_code,
            "case_name": case.get("case_name", case_code),
            "case_definition_json": json.dumps(dict(case), ensure_ascii=False, sort_keys=True),
            "decision": summary["decision"],
            "selected_sites": summary["selected_plan"]["site_codes"],
            "selected_capacity_kwh": summary["selected_plan"]["total_capacity_kwh"],
            "best_alternative_sites": alternative.get("site_codes", ""),
            "best_alternative_capacity_kwh": alternative.get("total_capacity_kwh", 0.0),
            "best_alternative_charge_power_kw": alternative.get("total_charge_power_kw", 0.0),
            "best_alternative_discharge_power_kw": alternative.get("total_discharge_power_kw", 0.0),
            "best_alternative_annual_saving_cny": alternative.get("annual_saving_vs_no_build_cny", 0.0),
            "best_alternative_grid_reduction_kwh_per_year": alternative.get("grid_reduction_vs_no_build_kwh_per_year", 0.0),
            "best_alternative_all_scenarios_feasible": bool(alternative_scenarios) and all(row["feasible"] == "True" for row in alternative_scenarios),
            "best_alternative_worst_grid_scenario": worst_grid_row.get("scenario_code", ""),
            "best_alternative_worst_grid_kwh": worst_grid_row.get("grid_kwh", ""),
            "build_candidate_count": explanation["build_candidate_count"],
            "core_feasible_count": explanation["core_feasible_count"],
            "business_threshold_pass_count": explanation["business_threshold_pass_count"],
            "rejection_reason_counts_json": json.dumps(explanation["rejection_reason_counts"], ensure_ascii=False, sort_keys=True),
            "recommendation_level": summary["recommendation_level"],
            "quality_gate_passed": audit["passed"],
        })
        audit_rows.append({
            "case_code": case_code,
            "passed": audit["passed"],
            "passed_gate_count": audit["passed_gate_count"],
            "gate_count": audit["gate_count"],
            "failed_gates": ";".join(audit["failed_gates"]),
        })

    stability = _stability_summary(run_rows)
    all_gates_passed = all(bool(row["passed"]) for row in audit_rows)
    summary = {
        "schema_version": "1.0",
        "module": "storage_planning_credibility_round3",
        "case_count": len(run_rows),
        "all_quality_gates_passed": all_gates_passed,
        "stability": stability,
        "base_decision_explanation": next(
            (
                json.loads(row["rejection_reason_counts_json"])
                for row in run_rows if row["case_code"] == "base"
            ),
            {},
        ),
        "recommendation_level": "planning_sensitivity",
        "formal_engineering_conclusion_allowed": False,
        "limitations": [
            "敏感性范围是本地声明的离散参数案例，不是连续不确定性证明。",
            "混合数据含规划占位值，稳定性只说明当前假设范围内的软件推荐一致性。",
            "正式工程结论仍需现场数据、专业接入条件和独立校准。",
        ],
    }
    _write_csv(output_root / "sensitivity_runs.csv", run_rows, list(run_rows[0]) if run_rows else ["case_code"])
    _write_csv(output_root / "quality_gate_results.csv", audit_rows, list(audit_rows[0]) if audit_rows else ["case_code"])
    (output_root / "credibility_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report = [
        "# 储能规划第三轮可信度报告",
        "",
        f"- 参数案例：{len(run_rows)}",
        f"- 全部质量门禁通过：{all_gates_passed}",
        f"- 推荐稳定等级：`{stability['stability_grade']}`",
        f"- 决策分布：`{stability['decision_counts']}`",
        f"- 最佳建设备选位置分布：`{stability['best_alternative_site_counts']}`",
        f"- 最佳备选容量区间：`{stability['best_alternative_capacity_kwh_range']}` kWh",
        f"- 最佳备选最大充电功率区间：`{stability['best_alternative_charge_power_kw_range']}` kW",
        f"- 最佳备选最大放电功率区间：`{stability['best_alternative_discharge_power_kw_range']}` kW",
        f"- 最佳备选年节省区间：`{stability['best_alternative_annual_saving_cny_range']}` 元",
        f"- 基准案例否决原因计数：`{summary['base_decision_explanation']}`",
        "",
        "本报告属于 planning_sensitivity，不是正式工程结论。各案例详情和门禁见同目录 CSV。",
    ]
    (output_root / "credibility_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


__all__ = [
    "DEFAULT_SENSITIVITY_CASES",
    "audit_storage_planning_result",
    "run_storage_planning_credibility",
]
