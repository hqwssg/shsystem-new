"""验证恢复机制消融比较的计算口径。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.recovery_ablation_benchmark import compare_summaries


def _summary(*, recovery_enabled: bool, feasible: tuple[bool, bool]) -> dict:
    cycles = []
    for index, is_feasible in enumerate(feasible):
        cycles.append({
            "cycle_index": index,
            "observed_heavy_delay_s": 120 if index else 0,
            "observed_empty_delay_s": 0,
            "robust_feasible": is_feasible,
            "resource_conflict_count": 0 if is_feasible else 2,
            "recovery_conflict_count": 0 if is_feasible else 3,
            "constraint_violation": 0.0 if is_feasible else 30.0,
            "recovery_repair_status": "fully_repaired" if recovery_enabled and index else ("not_applicable" if recovery_enabled else "disabled"),
            "recovery_repair_adopted": recovery_enabled and index == 1,
            "recovery_repair_total_adjustment_s": 90 if recovery_enabled and index else 0,
            "executable_heavy_count": 1,
            "executable_empty_count": 1,
            "executed_grid_kwh": 100.0 + index,
            "executed_wasted_kwh": 20.0 - index,
            "executed_charge_kwh": 5.0,
            "executed_discharge_kwh": 3.0,
            "executed_final_soc_kwh": 50.0 + index,
        })
    gates = {key: True for key in (
        "all_cycles_completed", "observation_sequence_applied",
        "observations_reach_scenario_evaluation", "soc_continuity",
        "locked_history_monotonic", "realized_departures_committed_to_next_cycle",
        "execution_state_matches_observed_delays", "energy_window_moves_with_cycle",
        "feasible_cycles_have_executable_service",
        "infeasible_new_decisions_withheld_unless_experimental",
        "settlement_uses_committed_schedule", "soc_within_physical_bounds",
        "conflict_chains_fully_classified", "infeasible_cycles_have_extracted_conflicts",
    )}
    return {
        "data_status": "test",
        "cycle_count": 2,
        "delay_sequence": [[0, 0], [120, 0]],
        "horizon_s": 7200,
        "execute_window_s": 3300,
        "storage_preset_id": "fixed",
        "search_config": {"seed": 1},
        "allow_infeasible_commit_for_experiment": True,
        "recovery_enabled": recovery_enabled,
        "robust_feasible_cycle_count": sum(feasible),
        "robust_infeasible_cycle_count": 2 - sum(feasible),
        "recovery_repair_triggered_cycle_count": int(recovery_enabled),
        "exact_recovery_solver_triggered_cycle_count": 0,
        "recovery_repair_adopted_cycle_count": int(recovery_enabled),
        "exact_recovery_adopted_cycle_count": 0,
        "wall_time_s": 1.0,
        "gates": gates,
        "cycles": cycles,
    }


def main() -> int:
    without = _summary(recovery_enabled=False, feasible=(True, False))
    with_recovery = _summary(recovery_enabled=True, feasible=(True, True))
    with_recovery["cycles"][1]["resource_conflict_count"] = 0
    with_recovery["cycles"][1]["recovery_conflict_count"] = 0
    with_recovery["cycles"][1]["constraint_violation"] = 0.0
    result = compare_summaries(without, with_recovery)
    assert result["all_gates_passed"]
    assert result["recovered_cycle_indexes"] == [1]
    assert result["delta_with_minus_without"]["total_resource_conflict_count"] == -2.0
    assert result["delta_with_minus_without"]["total_core_scenario_conflict_count"] == -3.0
    assert result["directly_repaired_cycle_indexes"] == [1]
    assert result["with_recovery"]["total_recovery_adjustment_s"] == 90

    unfair = deepcopy(with_recovery)
    unfair["search_config"] = {"seed": 2}
    assert not compare_summaries(without, unfair)["gates"]["same_exogenous_inputs"]
    print("recovery ablation comparison smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
