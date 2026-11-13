"""共享预算不能透支；阶段额度不得吞掉留给后续精确层的预算。"""
from pathlib import Path
import sys
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from recovery_work_budget import RecoveryWorkBudget, WorkBudgetReached, WorkPhaseReached

def main():
    b = RecoveryWorkBudget(full_limit=2, resource_limit=12, candidate_limit=2, wall_limit_s=30, solver_limit_s=3)
    b.candidate((1,)); b.candidate((1,)); b.candidate((2,))
    assert len(b.candidates) == 2
    try:
        b.candidate((3,))
    except WorkBudgetReached:
        pass
    else:
        raise AssertionError("候选额度必须生效")
    with b.phase("repair", resource_limit=1):
        b.resource()
        try:
            b.resource()
        except WorkPhaseReached:
            pass
        else:
            raise AssertionError("阶段额度必须生效")
    b.full(5); b.full(5)
    assert b.full_count == 2 and b.resource_count == 11
    try:
        b.full(5)
    except WorkBudgetReached:
        pass
    else:
        raise AssertionError("完整评价额度必须生效")
    assert b.resource_count == 11
    assert b.begin_solver(10) <= 3
    b.finish_solver(2)
    assert b.begin_solver(10) <= 1
    b.finish_solver(1)
    try:
        b.begin_solver(1)
    except WorkBudgetReached:
        pass
    else:
        raise AssertionError("精确层多次调用必须累计耗时")
    with patch("recovery_work_budget.time.perf_counter", return_value=b.deadline + 1):
        try:
            b.resource()
        except WorkBudgetReached:
            pass
        else:
            raise AssertionError("墙钟预算必须覆盖修复和诊断")
    print("shared recovery work budget: PASS")

if __name__ == "__main__":
    main()
