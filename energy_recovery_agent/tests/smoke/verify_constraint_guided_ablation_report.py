"""独立验收器须能发现篡改预算/候选，不能将记录正确误说成性能通过。"""

from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rolling_optimizer import ScheduleScore, candidate_selection_key
from tools.benchmark_constraint_guided_search import ARMS, acceptance, aggregate, key_text, write_json
from tools.verify_constraint_guided_search_results import verify_results


def main():
    score = ScheduleScore(True, 100.0, 0.0, 100.0, 0.0, 5, grid_kwh=100.0,
                          effective_regen_loss_kwh=20.0)
    rank = list(candidate_selection_key(score))
    exact = {"feasible": "true", "grid_kwh": "100", "wasted_kwh": "0", "total_cost": "100",
             "headway_deviation": "0", "constraint_violation": "0", "effective_regen_loss_kwh": "20",
             **{f"selection_key_{i}": str(value) for i, value in enumerate(rank)}}
    reference = {key_text([index]): exact for index in range(48)}
    with TemporaryDirectory() as directory:
        output = Path(directory)
        reference_dir = output / "reference"
        write_json(reference_dir / "benchmark_summary.json", {"fixture": True})
        write_json(reference_dir / "exact_candidates.csv", {"fixture": True})
        settings = {"data_dir": str(output), "scales": [1], "seeds": [11], "repeats": 1,
                    "full_budgets": [1], "proposal_budget": 48, "domain": {}, "wall_limit_s": 120}
        rows = []
        originals = {}
        for arm in ARMS:
            result_path = output / arm / "result.json"
            result = {"spec": {"full_budget": 1, "proposal_budget": 48, "domain": {}, "wall_limit_s": 120},
                      "full_evaluation_count": 1, "proposal_count": 1,
                      "full_candidate_records": [{"template_key": [0], "score": asdict(score),
                                                  "scenario_scores": [{"core": index < 3,
                                                                       "score": asdict(replace(score, scenario_count=1))}
                                                                      for index in range(5)]}],
                      "trace": [{"stage": "proposal", "template_key": [0]}],
                      "selected_template_key": [0], "selected_score": asdict(score),
                      "selected_selection_key": rank, "selected_is_full_evaluated": True,
                      "unscored_candidate_energy_values_exported": False}
            originals[arm] = result
            write_json(result_path, result)
            rows.append({"scale": 1, "seed": 11, "repeat": 0, "full_budget": 1, "arm": arm,
                         "heuristic_found_feasible": True, "selected_template_key": [0], "selected_selection_key": rank,
                         "stop_reason": "search_completed", "full_evaluation_count": 1, "proposal_count": 1,
                         "proposal_budget": 48,
                         "screen_count": 0, "screen_rejection_count": 0, "reference_scores_match": True,
                         "setup_wall_time_s": 0.1, "search_wall_time_s": 0.9, "screen_time_s": 0,
                         "full_evaluation_time_s": 0.8, "e2e_wall_time_s": 1.2, "result_file": str(result_path)})
        audit = [{"scale": 1, "candidate_count": 48, "rejected_count": 0, "false_rejection_count": 0}]
        write_json(output / "screen_audit/n2/screen_audit.json",
                   [{"template_key": [index], "rejected": False, "violation_lower_bound": 0} for index in range(48)])
        summary = {"completed": True, "settings": settings, "rows": rows, "screen_audit": audit,
                   "reference_dir": str(reference_dir),
                   "reference_summary_sha256": sha256((reference_dir / "benchmark_summary.json").read_bytes()).hexdigest(),
                   "reference_candidates_sha256": sha256((reference_dir / "exact_candidates.csv").read_bytes()).hexdigest(),
                   "provenance": {"unchanged_during_run": True}, "groups": aggregate(rows),
                   "acceptance": acceptance(rows, audit)}
        write_json(output / "benchmark_summary.json", summary)
        write_json(output / "benchmark_progress.json", {"status": "completed", "completed": 4, "total": 4})
        with patch("tools.verify_constraint_guided_search_results.load_reference", return_value=({}, {}, reference)):
            valid = verify_results(output)
            assert valid["passed"] and not valid["experimental_performance_acceptance_passed"]
            changed = deepcopy(originals["combined"])
            changed["selected_score"]["grid_kwh"] = 0
            write_json(output / "combined/result.json", changed)
            assert not verify_results(output)["passed"]
            write_json(output / "combined/result.json", originals["combined"])
            wrong_budget = deepcopy(summary)
            wrong_budget["rows"][0]["full_evaluation_count"] = 2
            write_json(output / "benchmark_summary.json", wrong_budget)
            assert not verify_results(output)["passed"]
    print("constraint-guided ablation independent verifier: PASS")


if __name__ == "__main__":
    main()
