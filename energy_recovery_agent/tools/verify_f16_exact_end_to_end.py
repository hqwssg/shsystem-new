"""核验F16精确资源种子是否完成端到端接入并通过核心稳健门禁。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Sequence
import argparse
import csv
import json


DEFAULT_OUTPUT_DIR = Path("paper/experiments/dispatch_exact_resource_f16_end_to_end")


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def verify(output_dir: Path) -> Dict[str, Any]:
    summary = _read_json(output_dir / "summary.json")
    search = _read_json(output_dir / "search_space_diagnostics.json")
    scenarios = _read_csv(output_dir / "selected_plan_scenario_diagnostics.csv")
    schedule = _read_csv(output_dir / "optimized_schedule.csv")
    timeline = _read_csv(output_dir / "energy_timeline.csv")

    repair = search["feasibility_repair"]
    exact = repair["exact_resource_feasibility"]
    optimized = summary["optimized"]
    population = search["window_service_population"]
    core_rows = [row for row in scenarios if row["core_for_feasibility"].lower() == "true"]
    diagnostic_rows = [row for row in scenarios if row["core_for_feasibility"].lower() != "true"]
    optimized_timeline = [row for row in timeline if row["case"] == "optimized"]
    soc_values = [float(row["soc_kwh"]) for row in optimized_timeline]
    capacity_kwh = float(
        summary["selected_storage_preset"]["optimized_battery"]["capacity_kwh"]
    )

    checks = {
        "exact_layer_triggered": exact["triggered"] is True,
        "exact_candidate_verified": exact["status"] == "feasible_verified",
        "heuristic_miss_distinguished": (
            repair["targeted_local_repair"]["resource_feasible_seed_count"] == 0
            and repair["feasibility_conclusion"] == "heuristic_search_missed_feasible_solution"
        ),
        "exact_seed_fully_evaluated": (
            repair["full_robust_evaluated_seed_count"] >= 1
            and repair["full_robust_feasible_seed_count"] >= 1
        ),
        "optimized_plan_feasible": optimized["feasible"] is True,
        "headway_feasible": optimized["headway_feasible"] is True,
        "signaling_feasible": optimized["signal_feasible"] is True,
        "resource_feasible": (
            optimized["resource_feasible"] is True
            and int(optimized["resource_conflict_count"]) == 0
        ),
        "flow_continuity_feasible": (
            optimized["flow_continuity_feasible"] is True
            and int(optimized["flow_continuity_violation_count"]) == 0
        ),
        "electrical_limits_feasible": (
            float(optimized["electrical_constraint_violation_kwh"]) == 0.0
            and float(optimized["traction_supply_excess_kwh"]) == 0.0
            and float(optimized["regen_absorption_excess_kwh"]) == 0.0
        ),
        "service_population_complete": (
            int(population["required_heavy_count"]) == 8
            and int(population["required_empty_count"]) == 8
            and int(population["selected_heavy_count"]) == 8
            and int(population["selected_empty_count"]) == 8
            and sum(row["train_type"] == "Heavy" for row in schedule) == 8
            and sum(row["train_type"] == "Empty" for row in schedule) == 8
        ),
        "all_core_scenarios_feasible": (
            len(core_rows) == 3
            and all(
                row["feasible"].lower() == "true"
                and row["blocking"].lower() == "false"
                and float(row["constraint_violation"]) == 0.0
                and int(row["resource_conflict_count"]) == 0
                and int(row["flow_continuity_violation_count"]) == 0
                for row in core_rows
            )
        ),
        "soc_physical_bounds_respected": (
            bool(soc_values)
            and min(soc_values) >= -1e-9
            and max(soc_values) <= capacity_kwh + 1e-9
        ),
        "terminal_soc_has_no_shortfall": float(optimized["final_soc_shortfall_kwh"]) == 0.0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "schema_version": "1.0",
        "output_dir": str(output_dir),
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "core_scenario_count": len(core_rows),
        "diagnostic_scenario_count": len(diagnostic_rows),
        "diagnostic_failure_scenarios": [
            row["scenario"] for row in diagnostic_rows if row["feasible"].lower() != "true"
        ],
        "full_robust_evaluated_seed_count": repair["full_robust_evaluated_seed_count"],
        "full_robust_feasible_seed_count": repair["full_robust_feasible_seed_count"],
        "final_soc_kwh": float(optimized["final_soc_kwh"]),
        "final_soc_deviation_kwh": float(optimized["final_soc_deviation_kwh"]),
        "soc_min_kwh": min(soc_values),
        "soc_max_kwh": max(soc_values),
        "storage_capacity_kwh": capacity_kwh,
        "note": (
            "终端SOC偏差是惩罚项而非硬可行性门禁；±300秒场景是非核心压力诊断。"
        ),
    }
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args(argv)
    result = verify(args.output_dir)
    result_path = args.result or args.output_dir / "f16_exact_end_to_end_verification.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
