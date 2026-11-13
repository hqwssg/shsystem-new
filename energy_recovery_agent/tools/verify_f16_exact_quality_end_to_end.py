"""验证F16精确解的偏移质量最优性及完整评价回归。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Sequence
import argparse
import csv
import json


DEFAULT_NEW_DIR = Path("paper/experiments/dispatch_exact_resource_f16_quality/final_end_to_end")
DEFAULT_OLD_DIR = Path("paper/experiments/dispatch_exact_resource_f16_end_to_end")


def _json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _adjustments(candidate: Dict[str, str]) -> list[int]:
    return [
        *json.loads(candidate["heavy_departure_adjustments_s"]),
        *json.loads(candidate["empty_departure_adjustments_s"]),
    ]


def verify(new_dir: Path, old_dir: Path) -> Dict[str, Any]:
    new_summary = _json(new_dir / "summary.json")
    old_summary = _json(old_dir / "summary.json")
    search = _json(new_dir / "search_space_diagnostics.json")
    scenarios = _csv(new_dir / "selected_plan_scenario_diagnostics.csv")
    ranked = _csv(new_dir / "ranked_candidates.csv")
    timeline = _csv(new_dir / "energy_timeline.csv")

    repair = search["feasibility_repair"]
    exact = repair["exact_resource_feasibility"]
    quality = exact["model"]["quality_optimization"]
    optimized = new_summary["optimized"]
    old_optimized = old_summary["optimized"]
    first_feasible = next(row for row in ranked if row["feasible"].lower() == "true")
    adjustments = _adjustments(first_feasible)
    heavy_adjustments = json.loads(first_feasible["heavy_departure_adjustments_s"])
    empty_adjustments = json.loads(first_feasible["empty_departure_adjustments_s"])
    heavy_departures = json.loads(first_feasible["heavy_departures_s"])
    empty_departures = json.loads(first_feasible["empty_departures_s"])
    core_rows = [row for row in scenarios if row["core_for_feasibility"].lower() == "true"]
    diagnostic_failures = [
        row["scenario"]
        for row in scenarios
        if row["core_for_feasibility"].lower() != "true"
        and row["feasible"].lower() != "true"
    ]
    optimized_soc = [
        float(row["soc_kwh"])
        for row in timeline
        if row["case"] == "optimized"
    ]
    capacity = float(
        new_summary["selected_storage_preset"]["optimized_battery"]["capacity_kwh"]
    )
    actual_max = max(abs(value) for value in adjustments)
    actual_total = sum(abs(value) for value in adjustments)

    checks = {
        "original_timetable_is_quality_reference": (
            int(first_feasible["heavy_empty_phase_s"]) == 840
            and heavy_departures
            == [index * 1800 + value for index, value in enumerate(heavy_adjustments)]
            and empty_departures
            == [840 + index * 1800 + value for index, value in enumerate(empty_adjustments)]
        ),
        "lexicographic_quality_proof": (
            exact["status"] == "feasible_verified"
            and exact["proof"]
            == "highs_lexicographic_departure_adjustment_optimum_verified_by_authoritative_resource_checker"
        ),
        "minimum_maximum_adjustment_proven": (
            quality["minimum_maximum_adjustment_proven"] is True
            and quality["minimum_maximum_adjustment_s"] == 367
            and quality["lower_infeasible_adjustment_bound_s"] == 366
            and actual_max == 367
        ),
        "minimum_total_adjustment_proven": (
            quality["total_absolute_adjustment_optimal"] is True
            and quality["total_absolute_adjustment_s"] == 3000
            and actual_total == 3000
        ),
        "heuristic_miss_preserved": (
            repair["targeted_local_repair"]["resource_feasible_seed_count"] == 0
            and repair["feasibility_conclusion"] == "heuristic_search_missed_feasible_solution"
        ),
        "full_evaluation_passed": (
            repair["full_robust_evaluated_seed_count"] == 5
            and repair["full_robust_feasible_seed_count"] == 5
            and optimized["feasible"] is True
        ),
        "all_hard_constraints_passed": (
            optimized["headway_feasible"] is True
            and optimized["signal_feasible"] is True
            and optimized["resource_feasible"] is True
            and optimized["flow_continuity_feasible"] is True
            and optimized["resource_conflict_count"] == 0
            and optimized["electrical_constraint_violation_kwh"] == 0.0
            and optimized["traction_supply_excess_kwh"] == 0.0
            and optimized["regen_absorption_excess_kwh"] == 0.0
            and optimized["heavy_count"] == 8
            and optimized["empty_count"] == 8
        ),
        "all_core_scenarios_passed": (
            len(core_rows) == 3
            and all(
                row["feasible"].lower() == "true"
                and float(row["constraint_violation"]) == 0.0
                and int(row["resource_conflict_count"]) == 0
                for row in core_rows
            )
        ),
        "soc_physical_bounds_passed": (
            bool(optimized_soc)
            and min(optimized_soc) >= -1e-9
            and max(optimized_soc) <= capacity + 1e-9
            and optimized["final_soc_shortfall_kwh"] == 0.0
        ),
        "terminal_soc_deviation_improved": (
            optimized["final_soc_deviation_kwh"]
            < old_optimized["final_soc_deviation_kwh"]
        ),
        "core_terminal_soc_target_met": (
            optimized["final_soc_deviation_kwh"] == 0.0
            and all(float(row["final_soc_deviation_kwh"]) == 0.0 for row in core_rows)
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    old_adjustments = _adjustments(
        next(
            row
            for row in _csv(old_dir / "ranked_candidates.csv")
            if row["feasible"].lower() == "true"
        )
    )
    old_max = max(abs(value) for value in old_adjustments)
    old_total = sum(abs(value) for value in old_adjustments)
    old_soc = float(old_optimized["final_soc_deviation_kwh"])
    new_soc = float(optimized["final_soc_deviation_kwh"])
    return {
        "schema_version": "1.0",
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "adjustment_quality": {
            "old_maximum_absolute_adjustment_s": old_max,
            "new_maximum_absolute_adjustment_s": actual_max,
            "maximum_adjustment_reduction_pct": round((1 - actual_max / old_max) * 100, 6),
            "old_total_absolute_adjustment_s": old_total,
            "new_total_absolute_adjustment_s": actual_total,
            "total_adjustment_reduction_pct": round((1 - actual_total / old_total) * 100, 6),
        },
        "complete_evaluation": {
            "core_scenarios_passed": [row["scenario"] for row in core_rows],
            "diagnostic_failure_scenarios": diagnostic_failures,
            "old_final_soc_deviation_kwh": old_soc,
            "new_final_soc_deviation_kwh": new_soc,
            "final_soc_deviation_reduction_pct": round((1 - new_soc / old_soc) * 100, 6),
            "new_total_cost": float(optimized["total_cost"]),
            "new_grid_kwh": float(optimized["grid_kwh"]),
            "new_wasted_kwh": float(optimized["wasted_kwh"]),
        },
        "remaining_boundary": (
            "三个核心场景终端SOC目标已达到；±300秒场景是非核心压力诊断，仍不可行。"
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new-dir", type=Path, default=DEFAULT_NEW_DIR)
    parser.add_argument("--old-dir", type=Path, default=DEFAULT_OLD_DIR)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args(argv)
    result = verify(args.new_dir, args.old_dir)
    result_path = args.result or args.new_dir / "f16_exact_quality_verification.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
