"""独立核验扰动恢复第五阶段消融实验产物。"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence
import argparse
import csv
import json
import math


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "paper" / "experiments" / "E15_recovery_ablation"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify(output_dir: Path) -> dict:
    """重算关键对照指标并检查分支配置、明细和汇总一致性。"""

    required = (
        "comparison_summary.json",
        "cycle_comparison.csv",
        "RECOVERY_ABLATION_REPORT.md",
        "without_recovery/benchmark_summary.json",
        "without_recovery/rolling_cycles.csv",
        "without_recovery/SYNTHETIC_ROLLING_RESCHEDULING_REPORT.md",
        "with_recovery/benchmark_summary.json",
        "with_recovery/rolling_cycles.csv",
        "with_recovery/SYNTHETIC_ROLLING_RESCHEDULING_REPORT.md",
    )
    missing = [name for name in required if not (output_dir / name).exists()]
    if missing:
        result = {"valid": False, "checks": {"required_files_present": False}, "missing_files": missing}
        return result
    comparison = _load_json(output_dir / "comparison_summary.json")
    no = _load_json(output_dir / "without_recovery" / "benchmark_summary.json")
    yes = _load_json(output_dir / "with_recovery" / "benchmark_summary.json")
    with (output_dir / "cycle_comparison.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    same_inputs = all(
        no.get(key) == yes.get(key)
        for key in (
            "cycle_count", "delay_sequence", "horizon_s", "execute_window_s",
            "storage_preset_id", "search_config",
            "allow_infeasible_commit_for_experiment",
        )
    )
    no_feasible = sum(bool(row["robust_feasible"]) for row in no["cycles"])
    yes_feasible = sum(bool(row["robust_feasible"]) for row in yes["cycles"])
    recovered = [
        int(left["cycle_index"])
        for left, right in zip(no["cycles"], yes["cycles"])
        if not bool(left["robust_feasible"]) and bool(right["robust_feasible"])
    ]
    no_conflicts = sum(int(row["resource_conflict_count"]) for row in no["cycles"])
    yes_conflicts = sum(int(row["resource_conflict_count"]) for row in yes["cycles"])
    no_core_conflicts = sum(int(row["recovery_conflict_count"]) for row in no["cycles"])
    yes_core_conflicts = sum(int(row["recovery_conflict_count"]) for row in yes["cycles"])
    no_violation = sum(float(row["constraint_violation"]) for row in no["cycles"])
    yes_violation = sum(float(row["constraint_violation"]) for row in yes["cycles"])
    energy_fields = (
        "executed_grid_kwh", "executed_wasted_kwh", "executed_charge_kwh",
        "executed_discharge_kwh",
    )
    energy_deltas_match = all(
        abs(
            float(comparison["delta_with_minus_without"][field])
            - (
                sum(float(row[field]) for row in yes["cycles"])
                - sum(float(row[field]) for row in no["cycles"])
            )
        ) <= 1e-6
        for field in energy_fields
    )
    checks = {
        "required_files_present": True,
        "branch_modes_correct": (
            no.get("recovery_enabled") is False
            and yes.get("recovery_enabled") is True
            and no.get("allow_infeasible_commit_for_experiment") is True
            and yes.get("allow_infeasible_commit_for_experiment") is True
        ),
        "same_exogenous_inputs": same_inputs,
        "cycle_rows_complete": len(rows) == len(no["cycles"]) == len(yes["cycles"]),
        "feasible_counts_recomputed": (
            int(comparison["without_recovery"]["robust_feasible_cycle_count"]) == no_feasible
            and int(comparison["with_recovery"]["robust_feasible_cycle_count"]) == yes_feasible
        ),
        "recovered_cycles_recomputed": comparison["recovered_cycle_indexes"] == recovered,
        "recovered_cycle_numbers_recomputed": comparison["recovered_cycle_numbers"] == [
            index + 1 for index in recovered
        ],
        "conflicts_recomputed": (
            int(comparison["without_recovery"]["total_resource_conflict_count"]) == no_conflicts
            and int(comparison["with_recovery"]["total_resource_conflict_count"]) == yes_conflicts
        ),
        "core_conflicts_recomputed": (
            int(comparison["without_recovery"]["total_core_scenario_conflict_count"]) == no_core_conflicts
            and int(comparison["with_recovery"]["total_core_scenario_conflict_count"]) == yes_core_conflicts
        ),
        "violations_recomputed": (
            abs(float(comparison["without_recovery"]["total_constraint_violation"]) - no_violation) <= 1e-6
            and abs(float(comparison["with_recovery"]["total_constraint_violation"]) - yes_violation) <= 1e-6
        ),
        "energy_deltas_recomputed": energy_deltas_match,
        "all_numeric_results_finite": all(
            math.isfinite(float(value))
            for metrics in (comparison["without_recovery"], comparison["with_recovery"])
            for key, value in metrics.items()
            if isinstance(value, (int, float))
        ),
        "comparison_gates_consistent": comparison.get("all_gates_passed") == all(
            bool(value) for value in comparison.get("gates", {}).values()
        ),
        "comparison_passed": bool(comparison.get("all_gates_passed")),
    }
    result = {"valid": all(checks.values()), "checks": checks, "missing_files": []}
    (output_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    result = verify(args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
