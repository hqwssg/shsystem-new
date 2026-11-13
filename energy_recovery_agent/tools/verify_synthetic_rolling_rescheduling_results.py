"""独立核验合成状态驱动多轮滚动重调度实验产物。"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence
import argparse
import csv
import json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "paper" / "experiments" / "E15_synthetic_rolling_rescheduling"


def verify(output_dir: Path) -> dict:
    """检查文件完整性、逐轮状态连续性和汇总门禁一致性。"""

    required = (
        "benchmark_summary.json",
        "rolling_cycles.csv",
        "recovery_conflicts.csv",
        "recovery_conflict_chains.csv",
        "recovery_adjustable_trains.csv",
        "recovery_adjustment_candidates.csv",
        "recovery_conflict_analysis.json",
        "recovery_repair_decisions.csv",
        "recovery_repair_scenarios.csv",
        "recovery_repair_results.json",
        "exact_recovery_decisions.csv",
        "exact_recovery_results.json",
        "rolling_state_timeline.png",
        "SYNTHETIC_ROLLING_RESCHEDULING_REPORT.md",
    )
    missing = [name for name in required if not (output_dir / name).exists()]
    summary = json.loads((output_dir / "benchmark_summary.json").read_text(encoding="utf-8")) if not missing else {}
    with (output_dir / "rolling_cycles.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle)) if not missing else []
    cycle_count = int(summary.get("cycle_count", 0))
    row_count_matches = len(rows) == cycle_count and cycle_count >= 2
    times = [int(row["current_time_s"]) for row in rows] if rows else []
    execute_window_s = int(summary.get("execute_window_s", 0))
    time_progression = times == [index * execute_window_s for index in range(cycle_count)]
    soc_continuity = all(
        abs(float(rows[index]["initial_soc_kwh"]) - float(rows[index - 1]["executed_final_soc_kwh"])) <= 1e-6
        for index in range(1, len(rows))
    )
    def json_int_list(row, field):
        return [int(value) for value in json.loads(row[field])]

    def csv_bool(value):
        return str(value).strip().lower() == "true"

    execution_state_matches_observation = all(
        json_int_list(row, "realized_heavy_departures_s")
        == [
            value
            if value in set(json_int_list(row, "locked_heavy_before"))
            or value < int(row["current_time_s"])
            else value + int(row["observed_heavy_delay_s"])
            for value in json_int_list(row, "planned_heavy_departures_s")
        ]
        and json_int_list(row, "realized_empty_departures_s")
        == [
            value
            if value in set(json_int_list(row, "locked_empty_before"))
            or value < int(row["current_time_s"])
            else value + int(row["observed_empty_delay_s"])
            for value in json_int_list(row, "planned_empty_departures_s")
        ]
        and row.get("execution_scenario") == "normal"
        for row in rows
    )
    realized_departures_committed = all(
        set(json_int_list(rows[index - 1], "executable_heavy_departures_s")).issubset(
            json_int_list(rows[index], "locked_heavy_before")
        )
        and set(json_int_list(rows[index - 1], "executable_empty_departures_s")).issubset(
            json_int_list(rows[index], "locked_empty_before")
        )
        for index in range(1, len(rows))
    )
    commit_statuses_valid = all(
        row.get("commit_status") in {
            "committed_robust_feasible",
            "withheld_infeasible",
            "committed_infeasible_experiment_only",
        }
        for row in rows
    )
    commit_feasibility_consistent = all(
        csv_bool(row.get("core_robust_feasible", "false"))
        == csv_bool(row["robust_feasible"])
        and (
            (csv_bool(row["robust_feasible"]) and row["commit_status"] == "committed_robust_feasible")
            or (
                not csv_bool(row["robust_feasible"])
                and row["commit_status"] in {
                    "withheld_infeasible",
                    "committed_infeasible_experiment_only",
                }
            )
        )
        for row in rows
    )
    production_infeasible_decisions_withheld = all(
        csv_bool(row["robust_feasible"])
        or bool(summary.get("allow_infeasible_commit_for_experiment"))
        or (
            row["commit_status"] == "withheld_infeasible"
            and set(json_int_list(row, "executable_heavy_departures_s")).issubset(
                json_int_list(row, "locked_heavy_before")
            )
            and set(json_int_list(row, "executable_empty_departures_s")).issubset(
                json_int_list(row, "locked_empty_before")
            )
        )
        for row in rows
    )
    settlement_uses_committed_schedule = all(
        json_int_list(row, "settled_heavy_departures_s")
        == json_int_list(row, "committed_heavy_departures_s")
        and json_int_list(row, "settled_empty_departures_s")
        == json_int_list(row, "committed_empty_departures_s")
        for row in rows
    )
    valid_safety_states = {
        "normal",
        "recovered_automatically",
        "recovered_after_observation",
        "waiting_for_observation",
        "manual_intervention_required",
        "experiment_only",
    }
    safety_states_valid = all(
        row.get("safety_state") in valid_safety_states for row in rows
    )
    safety_policy = summary.get("safety_policy") or {}
    max_attempts = 1 + int(safety_policy.get("max_retries_per_cycle", -1))
    safety_retry_bounded = max_attempts >= 1 and all(
        1 <= int(row.get("safety_attempt_count", 0)) <= max_attempts
        for row in rows
    )
    withheld_cycles_have_safe_action = all(
        row.get("commit_status") != "withheld_infeasible"
        or (
            row.get("safety_state") in {
                "waiting_for_observation",
                "manual_intervention_required",
            }
            and str(row.get("safety_action", "")).startswith(
                "hold_new_departures"
            )
        )
        for row in rows
    )
    safety_transitions_complete = all(
        isinstance(json.loads(row.get("safety_transition") or "{}"), dict)
        and json.loads(row.get("safety_transition") or "{}").get("state")
        == row.get("safety_state")
        and len(json.loads(row.get("safety_transition") or "{}").get("attempts", []))
        == int(row.get("safety_attempt_count", 0))
        for row in rows
    )
    strongest_cycle_index = int(summary.get("strongest_disturbance_cycle_index", -1))
    strong_recovery_gate_valid = (
        0 <= strongest_cycle_index < len(rows)
        and any(csv_bool(row["robust_feasible"]) for row in rows[strongest_cycle_index:])
        and bool(summary.get("strongest_disturbance_cycle_robust_feasible"))
        == csv_bool(rows[strongest_cycle_index]["robust_feasible"])
        and bool(summary.get("final_recovery_cycle_robust_feasible"))
        == csv_bool(rows[-1]["robust_feasible"])
    )
    gates_match = bool(summary) and summary.get("all_gates_passed") == all(
        bool(value) for value in summary.get("gates", {}).values()
    )
    analyses = json.loads(
        (output_dir / "recovery_conflict_analysis.json").read_text(encoding="utf-8")
    ) if not missing else []
    analysis_count_matches = len(analyses) == cycle_count
    conflict_classification_complete = all(
        conflict.get("repairability") in {
            "directly_adjustable",
            "locked_only_requires_operational_intervention",
        }
        for analysis in analyses
        for conflict in analysis.get("conflicts", [])
    )
    chain_members_resolve = all(
        set(chain.get("train_ids", [])).issubset(
            {train.get("train_id") for train in analysis.get("trains", [])}
        )
        for analysis in analyses
        for chain in analysis.get("chains", [])
    )
    candidate_ranks_contiguous = all(
        [candidate.get("priority_rank") for candidate in analysis.get("adjustment_candidates", [])]
        == list(range(1, len(analysis.get("adjustment_candidates", [])) + 1))
        for analysis in analyses
    )
    conflict_ids_resolve_once = all(
        sorted(
            conflict_id
            for chain in analysis.get("chains", [])
            for conflict_id in chain.get("conflict_ids", [])
        )
        == [
            f"CF{index:03d}"
            for index in range(1, len(analysis.get("conflicts", [])) + 1)
        ]
        for analysis in analyses
    )
    candidate_chain_ids_resolve = all(
        set(candidate.get("chain_ids", [])).issubset(
            {chain.get("chain_id") for chain in analysis.get("chains", [])}
        )
        for analysis in analyses
        for candidate in analysis.get("adjustment_candidates", [])
    )
    chain_classification_totals_match = bool(summary) and (
        int(summary.get("total_conflict_chain_count", -1))
        == sum(len(analysis.get("chains", [])) for analysis in analyses)
        and int(summary.get("total_repairable_chain_count", -1))
        == sum(
            chain.get("repairability") == "repairable_by_future_departure_adjustment"
            for analysis in analyses
            for chain in analysis.get("chains", [])
        )
        and int(summary.get("total_partially_blocked_chain_count", -1))
        == sum(
            chain.get("repairability") == "partially_blocked_by_locked_history"
            for analysis in analyses
            for chain in analysis.get("chains", [])
        )
        and int(summary.get("total_blocked_chain_count", -1))
        == sum(
            chain.get("repairability") == "blocked_by_locked_history"
            for analysis in analyses
            for chain in analysis.get("chains", [])
        )
    )
    repair_results = json.loads(
        (output_dir / "recovery_repair_results.json").read_text(encoding="utf-8")
    ) if not missing else []
    repair_count_matches = len(repair_results) == cycle_count
    repair_locked_history_preserved = all(
        not item.get("triggered") or bool(item.get("locked_departures_preserved"))
        for item in repair_results
    )
    adopted_repairs_have_decisions = all(
        not item.get("adopted") or bool(item.get("decisions"))
        for item in repair_results
    )
    repair_decisions_within_allowed_set = all(
        {decision.get("train_id") for decision in item.get("decisions", [])}.issubset(
            set(item.get("allowed_train_ids", []))
        )
        for item in repair_results
    )
    repair_statuses_valid = all(
        item.get("status") in {
            "not_applicable",
            "disabled",
            "not_required",
            "fully_repaired",
            "partially_repaired_locked_residual",
            "partially_improved_unresolved",
            "repair_failed",
        }
        for item in repair_results
    )
    exact_results = json.loads(
        (output_dir / "exact_recovery_results.json").read_text(encoding="utf-8")
    ) if not missing else []
    exact_count_matches = len(exact_results) == cycle_count
    exact_locked_history_preserved = all(
        item.get("status") in {"not_applicable", "disabled"}
        or bool(item.get("locked_departures_preserved"))
        for item in exact_results
    )
    exact_decisions_within_scope = all(
        {decision.get("train_id") for decision in item.get("decisions", [])}.issubset(
            set(item.get("scope_train_ids", []))
        )
        for item in exact_results
    )
    adopted_exact_results_verified = all(
        not item.get("adopted")
        or (
            bool(item.get("exact_resource_feasible"))
            and bool(item.get("full_robust_feasible"))
            and bool(item.get("decisions"))
        )
        for item in exact_results
    )
    locked_blockers_require_intervention = all(
        item.get("status") != "blocked_by_locked_history"
        or bool(item.get("operational_intervention_required"))
        for item in exact_results
    )
    if not missing:
        with (output_dir / "exact_recovery_decisions.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            exact_decision_header = tuple(csv.DictReader(handle).fieldnames or ())
    else:
        exact_decision_header = ()
    exact_decision_schema_present = exact_decision_header == (
        "cycle_index",
        "status",
        "proof",
        "adopted",
        "train_id",
        "train_type",
        "departure_index",
        "original_departure_s",
        "repaired_departure_s",
        "adjustment_s",
    )
    checks = {
        "required_files_present": not missing,
        "row_count_matches": row_count_matches,
        "time_progression": time_progression,
        "soc_continuity": soc_continuity,
        "execution_state_matches_observation": execution_state_matches_observation,
        "realized_departures_committed": realized_departures_committed,
        "commit_statuses_valid": commit_statuses_valid,
        "commit_feasibility_consistent": commit_feasibility_consistent,
        "production_infeasible_decisions_withheld": production_infeasible_decisions_withheld,
        "settlement_uses_committed_schedule": settlement_uses_committed_schedule,
        "safety_states_valid": safety_states_valid,
        "safety_retry_bounded": safety_retry_bounded,
        "withheld_cycles_have_safe_action": withheld_cycles_have_safe_action,
        "safety_transitions_complete": safety_transitions_complete,
        "strong_recovery_gate_valid": strong_recovery_gate_valid,
        "summary_gates_consistent": gates_match,
        "benchmark_gates_passed": bool(summary.get("all_gates_passed")),
        "analysis_count_matches": analysis_count_matches,
        "conflict_classification_complete": conflict_classification_complete,
        "chain_members_resolve": chain_members_resolve,
        "candidate_ranks_contiguous": candidate_ranks_contiguous,
        "conflict_ids_resolve_once": conflict_ids_resolve_once,
        "candidate_chain_ids_resolve": candidate_chain_ids_resolve,
        "chain_classification_totals_match": chain_classification_totals_match,
        "repair_count_matches": repair_count_matches,
        "repair_locked_history_preserved": repair_locked_history_preserved,
        "adopted_repairs_have_decisions": adopted_repairs_have_decisions,
        "repair_decisions_within_allowed_set": repair_decisions_within_allowed_set,
        "repair_statuses_valid": repair_statuses_valid,
        "exact_count_matches": exact_count_matches,
        "exact_locked_history_preserved": exact_locked_history_preserved,
        "exact_decisions_within_scope": exact_decisions_within_scope,
        "adopted_exact_results_verified": adopted_exact_results_verified,
        "locked_blockers_require_intervention": locked_blockers_require_intervention,
        "exact_decision_schema_present": exact_decision_schema_present,
    }
    result = {"valid": all(checks.values()), "checks": checks, "missing_files": missing}
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
