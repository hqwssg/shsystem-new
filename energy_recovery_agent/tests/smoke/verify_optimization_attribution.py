"""验证优化收益归因、候选去留、瓶颈和归因边界。"""

from __future__ import annotations

from pathlib import Path
import csv
import json
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optimization_attribution import write_optimization_attribution
from timetable_optimizer import decide_optimization_action
from tools.generate_optimization_attribution import generate


EXPECTED_FILES = {
    "OPTIMIZATION_ATTRIBUTION_REPORT.md",
    "optimization_attribution_summary.json",
    "optimization_kpi_attribution.csv",
    "optimization_candidate_decisions.csv",
    "optimization_candidate_funnel.csv",
    "optimization_bottlenecks.csv",
    "optimization_dimension_attribution.csv",
}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _assert_bundle(root: Path) -> dict:
    missing = sorted(name for name in EXPECTED_FILES if not (root / name).is_file())
    assert not missing, missing
    summary = json.loads((root / "optimization_attribution_summary.json").read_text(encoding="utf-8"))
    assert summary["schema_version"] == "1.0"
    assert summary["outputs"]["summary"] == "optimization_attribution_summary.json"
    assert summary["counts"]["candidate_rows"] > 0
    assert "NaN" not in json.dumps(summary)
    funnel = _rows(root / "optimization_candidate_funnel.csv")
    totals = {int(row["input_count"]) for row in funnel}
    assert len(totals) == 1, funnel
    return summary


def verify_timetable(root: Path) -> None:
    candidate_rows = [
        {"candidate_id": "B", "action_type": "baseline", "max_shift_min": 0, "total_adjustment_min": 0, "constraint_violation": 0, "feasible": True},
        {"candidate_id": "C1", "action_type": "shift", "max_shift_min": 5, "total_adjustment_min": 10, "constraint_violation": 0, "feasible": True},
        {"candidate_id": "C2", "action_type": "shift", "max_shift_min": 5, "total_adjustment_min": 10, "basic_constraint_violation": 2, "constraint_violation": 2, "feasible": False},
    ]
    scenario_rows = [
        {"candidate_id": "B", "scenario_id": "storage_no_direct", "effective_regen_loss_kwh_est": 100, "grid_kwh_est": 200, "wasted_kwh_est": 90, "storage_absorbed_kwh_est": 10, "storage_discharged_kwh_est": 8, "final_soc_kwh_est": 2, "constraint_violation": 0},
        {"candidate_id": "C1", "scenario_id": "storage_no_direct", "effective_regen_loss_kwh_est": 90, "grid_kwh_est": 180, "wasted_kwh_est": 80, "storage_absorbed_kwh_est": 20, "storage_discharged_kwh_est": 18, "final_soc_kwh_est": 2, "constraint_violation": 0},
        {"candidate_id": "C2", "scenario_id": "storage_no_direct", "effective_regen_loss_kwh_est": 70, "grid_kwh_est": 160, "wasted_kwh_est": 60, "storage_absorbed_kwh_est": 30, "storage_discharged_kwh_est": 28, "final_soc_kwh_est": 2, "constraint_violation": 2},
    ]
    issue_rows = [
        {"candidate_id": "B", "issue_type": "section_without_storage", "power_arm_id": "PA-1", "estimated_wasted_kwh": 5, "electrical_excess_kwh": 0},
        {"candidate_id": "C1", "issue_type": "storage_capacity_or_power_limit", "power_arm_id": "PA-2", "estimated_wasted_kwh": 2, "electrical_excess_kwh": 0},
    ]
    result = write_optimization_attribution(
        root,
        workflow="timetable_optimization",
        summary={"optimization_decision": {"action": "optimize", "reason": "material_energy_improvement_found", "selected_candidate_id": "C1"}},
        candidate_rows=candidate_rows,
        pareto_rows=[{"candidate_id": "C1"}],
        scenario_rows=scenario_rows,
        issue_rows=issue_rows,
        baseline_schedule_rows=[{"train_id": "T1", "depart_time_s": 100, "arrival_time_s": 200}],
        optimized_schedule_rows=[{"train_id": "T1", "depart_time_s": 130, "arrival_time_s": 230}],
    )
    assert result["decision"]["action"] == "optimize"
    assert result["attribution_scope"]["dispatch_only_attribution_allowed"] is True
    decisions = {row["candidate_id"]: row for row in _rows(root / "optimization_candidate_decisions.csv")}
    assert decisions["C1"]["status"] == "selected"
    assert decisions["C2"]["status"] == "rejected_infeasible"
    metrics = {row["metric"]: row for row in _rows(root / "optimization_kpi_attribution.csv")}
    assert float(metrics["grid_kwh"]["improvement"]) == 20.0
    assert metrics["final_soc_kwh"]["benefit_direction"] == "neutral"
    dimensions = _rows(root / "optimization_dimension_attribution.csv")
    assert any(row["dimension_id"] == "T1" and row["optimized_minus_baseline"] == "30.0" for row in dimensions)
    _assert_bundle(root)

    candidate_rows[0].update(constraint_violation=1, feasible=False)
    scenario_rows[0]["constraint_violation"] = 1
    decision = decide_optimization_action(candidate_rows, scenario_rows)
    assert decision == {
        "action": "no_feasible_solution",
        "reason": "baseline_infeasible",
        "selected_candidate_id": "",
        "baseline_candidate_id": "B",
    }
    diagnostic = root / "infeasible_baseline"
    write_optimization_attribution(
        diagnostic,
        workflow="timetable_optimization",
        summary={"optimization_decision": decision},
        candidate_rows=candidate_rows,
        scenario_rows=scenario_rows,
        pareto_rows=[{"candidate_id": "C1"}],
    )
    decisions = {row["candidate_id"]: row for row in _rows(diagnostic / "optimization_candidate_decisions.csv")}
    assert decisions["B"]["baseline"] == "True" and decisions["B"]["selected"] == "False"
    assert decisions["C1"]["status"] == "diagnostic_only"
    assert decisions["C1"]["material_energy_improvement"] == "False"
    metrics = {row["metric"]: row for row in _rows(diagnostic / "optimization_kpi_attribution.csv")}
    assert float(metrics["grid_kwh"]["baseline"]) == 200.0
    assert metrics["grid_kwh"]["optimized"] == metrics["grid_kwh"]["improvement"] == ""
    assert metrics["grid_kwh"]["dispatch_only_attribution_allowed"] == "False"


def verify_dispatch(root: Path, *, storage_changed: bool) -> None:
    baseline_storage = "S1"
    selected_storage = "S2" if storage_changed else "S1"
    result = write_optimization_attribution(
        root,
        workflow="dispatch",
        summary={
            "baseline": {"effective_regen_loss_kwh": 50, "energy_term": 150, "grid_kwh": 100, "wasted_kwh": 45, "battery_charge_limited_kwh": 8, "constraint_violation": 0, "final_soc_by_storage_kwh": {"ESS-1": 10}},
            "optimized": {"effective_regen_loss_kwh": 40, "energy_term": 120, "grid_kwh": 80, "wasted_kwh": 35, "battery_charge_limited_kwh": 2, "constraint_violation": 0, "final_soc_by_storage_kwh": {"ESS-1": 12}},
            "selected_storage_preset": {"baseline_preset_id": baseline_storage, "optimized_preset_id": selected_storage},
            "optimizer_diagnostics": {"returned_candidate_core_robust_feasible": True},
        },
        candidate_rows=[
            {"candidate_id": "D1", "rank": 1, "feasible": True, "storage_preset_id": selected_storage, "energy_scenario_objective": 120, "grid_kwh": 80, "wasted_kwh": 35, "constraint_violation": 0},
            {"candidate_id": "D2", "rank": 2, "feasible": False, "storage_preset_id": baseline_storage, "energy_scenario_objective": 110, "grid_kwh": 70, "wasted_kwh": 30, "constraint_violation": 1},
        ],
        pareto_rows=[{"candidate_id": "D1"}],
        scenario_rows=[{"scenario": "stress", "core_for_feasibility": False, "feasible": False, "blocking": False, "resource_conflict_count": 1, "constraint_violation": 0.5, "conflict_summary": "throat conflict"}],
        timeline_rows=[
            {"case": "baseline", "time_s": 0, "grid_kW": 100, "wasted_kW": 50, "battery_charge_kW": 20, "battery_discharge_kW": 10},
            {"case": "baseline", "time_s": 10, "grid_kW": 100, "wasted_kW": 50, "battery_charge_kW": 20, "battery_discharge_kW": 10},
            {"case": "optimized", "time_s": 0, "grid_kW": 80, "wasted_kW": 40, "battery_charge_kW": 25, "battery_discharge_kW": 15},
            {"case": "optimized", "time_s": 10, "grid_kW": 80, "wasted_kW": 40, "battery_charge_kW": 25, "battery_discharge_kW": 15},
        ],
        baseline_schedule_rows=[{"train_id": "H1", "depart_time_s": 0, "arrival_time_s": 100}],
        optimized_schedule_rows=[{"train_id": "H1", "depart_time_s": 30, "arrival_time_s": 130}],
        baseline_arc_rows=[{"train_id": "H1", "start_km": 0, "end_km": 10, "energy_kwh": 20, "capacity_resource_id": "section:A", "storage_section_id": "ESS-1"}],
        optimized_arc_rows=[{"train_id": "H1", "start_km": 0, "end_km": 10, "energy_kwh": 18, "capacity_resource_id": "section:A", "storage_section_id": "ESS-1"}],
    )
    expected_action = "keep_baseline" if storage_changed else "optimize"
    assert result["decision"]["action"] == expected_action
    if storage_changed:
        assert result["decision"]["reason"] == "storage_preset_changed_requires_fixed_storage_recheck"
    assert result["attribution_scope"]["dispatch_only_attribution_allowed"] is (not storage_changed)
    dimensions = _rows(root / "optimization_dimension_attribution.csv")
    assert any(row["attribution_quality"] == "not_identifiable_without_counterfactual_recalculation" for row in dimensions)
    assert any(row["dimension_type"] == "time_window" and row["metric"] == "grid_kwh" and float(row["improvement"]) > 0 for row in dimensions)
    assert any(row["dimension_type"] == "storage_device" and row["dimension_id"] == "ESS-1" for row in dimensions)
    assert any(row["dimension_type"] == "section_physical_energy" for row in dimensions)
    bottlenecks = _rows(root / "optimization_bottlenecks.csv")
    assert any(row["scope"] == "selected_candidate_non_core_stress" and row["blocking"] == "False" for row in bottlenecks)
    _assert_bundle(root)
    dimension_bytes = (root / "optimization_dimension_attribution.csv").read_bytes()
    reused = generate(root, "dispatch")
    assert reused["decision"] == result["decision"]
    assert (root / "optimization_dimension_attribution.csv").read_bytes() == dimension_bytes


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="optimization_attribution_") as temp_dir:
        root = Path(temp_dir)
        verify_timetable(root / "timetable")
        verify_dispatch(root / "dispatch_fixed", storage_changed=False)
        verify_dispatch(root / "dispatch_joint", storage_changed=True)
    print("optimization attribution verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
