"""验证资源可行性诊断不会把搜索失败、超时和模型无解混为一谈。"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rolling_optimizer import classify_resource_feasibility_conclusion


def main() -> int:
    cases = (
        ("model_infeasible", 0, 0, "model_proven_infeasible_in_explicit_domain"),
        ("model_infeasible", 1, 1, "heuristic_exact_model_inconsistency"),
        ("feasible_verified", 0, 1, "heuristic_search_missed_feasible_solution"),
        ("feasible_verified", 1, 1, "heuristic_solution_exactly_verified"),
        ("not_required", 1, 1, "heuristic_feasible_solution_available"),
        ("solver_limit_no_solution", 0, 0, "search_exhausted_but_model_feasibility_unknown"),
        ("solver_error", 0, 0, "search_exhausted_but_model_feasibility_unknown"),
        ("not_supported_for_locked_rolling_history", 0, 0, "search_exhausted_but_model_feasibility_unknown"),
    )
    for exact_status, heuristic_count, final_count, expected in cases:
        actual = classify_resource_feasibility_conclusion(
            exact_status=exact_status,
            heuristic_seed_count=heuristic_count,
            final_seed_count=final_count,
        )
        assert actual == expected, (exact_status, actual, expected)

    print("resource feasibility conclusions smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
