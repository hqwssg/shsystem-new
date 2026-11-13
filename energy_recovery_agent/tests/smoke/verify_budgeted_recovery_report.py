"""独立账本核验器必须拒绝计数不符、免费诊断、重复候选和缺失场景。"""
from copy import deepcopy
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.verify_budgeted_recovery import ledger


def main():
    row = dict(budget=dict(full_count=1, full_limit=48, resource_count=5, resource_limit=1800,
        candidate_count=1, candidate_limit=2048, solver_calls=1, solver_time_s=.1, solver_limit_s=60,
        trace=[dict(event="candidate", stage="exact_completion", key=[[1000], [3760], 0, "test"]),
               dict(event="solver", stage="exact_completion", limit_s=60),
               dict(event="solver_finish", stage="exact_completion", elapsed_s=.1),
               dict(event="resource", stage="exact_completion", count=5),
               dict(event="full", stage="exact_completion", count=1)]),
        full_candidate_records=[dict(scenario_scores=[{} for _ in range(5)])])
    assert ledger(row)
    bad = deepcopy(row); bad["budget"]["resource_count"] += 1
    assert not ledger(bad)
    bad = deepcopy(row); bad["full_candidate_records"][0]["scenario_scores"].pop()
    assert not ledger(bad)
    bad = deepcopy(row); bad["budget"]["trace"].append(deepcopy(bad["budget"]["trace"][0])); bad["budget"]["candidate_count"] += 1
    assert not ledger(bad)
    bad = deepcopy(row); bad["budget"]["trace"].append(dict(event="resource", stage="per_train_repair", count=901)); bad["budget"]["resource_count"] += 901
    assert not ledger(bad)
    bad = deepcopy(row); bad["budget"]["solver_time_s"] = .01
    assert not ledger(bad)
    print("budgeted recovery report negative controls: PASS")

if __name__ == "__main__":
    main()
