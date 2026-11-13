"""验证扰动后的局部恢复修复器。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from recovery_conflict_analysis import extract_recovery_conflict_analysis
from recovery_repair import repair_recovery_schedule
from resource_constraints import ConflictExplanation, ResourceCheckResult
from rolling_optimizer import DisturbanceScenario, GeneratedSchedule, ScheduleTemplate
from recovery_work_budget import RecoveryWorkBudget


def _conflict(train_a: str, train_b: str, duration_s: float = 120.0):
    """构造资源冲突测试对象。"""

    return ConflictExplanation(
        conflict_type="opposing_section_conflict",
        severity="blocking",
        resource_id=f"section:{train_a}:{train_b}",
        resource_name="测试区间",
        train_a=train_a,
        train_b=train_b,
        train_a_type="Heavy" if train_a.startswith("H") else "Empty",
        train_b_type="Heavy" if train_b.startswith("H") else "Empty",
        overlap_start_s=600.0,
        overlap_end_s=600.0 + duration_s,
        overlap_duration_s=duration_s,
        location_km="K100-K110",
        message="测试冲突",
        suggestion="调整未来列车",
    )


def _check(conflicts):
    """构造资源检查结果。"""

    return ResourceCheckResult(
        feasible=not conflicts,
        conflicts=list(conflicts),
        intervals=[],
        overlap_violation_s=sum(item.overlap_duration_s for item in conflicts),
    )


def _analysis(schedule, conflicts):
    """使用第一阶段接口生成修复器输入。"""

    with patch(
        "recovery_conflict_analysis.check_schedule_resources",
        return_value=_check(conflicts),
    ):
        return extract_recovery_conflict_analysis(
            schedule,
            [DisturbanceScenario("normal")],
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            current_time_s=600,
            locked_heavy_departures_s=[0],
            locked_empty_departures_s=[300],
        )


def main() -> int:
    """检查调整边界、最小偏移和部分恢复语义。"""

    schedule = GeneratedSchedule(
        heavy_departures_s=[0, 600, 1200],
        empty_departures_s=[300],
        template=ScheduleTemplate(600, 600, 300, 3, 1),
    )
    full_analysis = _analysis(schedule, [_conflict("H001", "H002")])

    def full_checker(candidate, *_args):
        conflicts = []
        if candidate.heavy_departures_s[1] < 720:
            conflicts.append(_conflict("H001", "H002"))
        return _check(conflicts)

    equivalent_scenarios = [
        DisturbanceScenario("normal"),
        DisturbanceScenario("normal_duplicate"),
    ]
    budget = RecoveryWorkBudget(full_limit=4, resource_limit=1000, candidate_limit=1000,
                                wall_limit_s=30, solver_limit_s=2)
    with patch(
        "recovery_repair.check_schedule_resources",
        side_effect=full_checker,
    ) as full_check_call:
        full = repair_recovery_schedule(
            schedule,
            full_analysis,
            equivalent_scenarios,
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            current_time_s=600,
            locked_heavy_departures_s=[0],
            locked_empty_departures_s=[300],
            adjustment_step_s=30,
            max_abs_adjustment_s=180,
            beam_width=16,
            work_budget=budget,
        )
    assert full.status == "fully_repaired"
    assert full.robust_resource_feasible
    assert full.locked_departures_preserved
    assert full.max_single_adjustment_s == 120
    assert full.total_adjustment_s == 120
    assert [(item.train_id, item.adjustment_s) for item in full.decisions] == [
        ("H002", 120)
    ]
    assert full.schedule.heavy_departures_s == [0, 720, 1200]
    assert full.schedule.empty_departures_s == [300]
    assert "H003" not in full.allowed_train_ids
    assert len(full.final_scenarios) == 2
    assert full_check_call.call_count == full.evaluation_count
    assert budget.resource_count == full_check_call.call_count  # 等价场景缓存命中不能虚增实际检查

    partial_analysis = _analysis(
        schedule,
        [_conflict("H001", "H002"), _conflict("E001", "E001", 30.0)],
    )

    def partial_checker(candidate, *_args):
        conflicts = [_conflict("E001", "E001", 30.0)]
        if candidate.heavy_departures_s[1] < 720:
            conflicts.append(_conflict("H001", "H002"))
        return _check(conflicts)

    with patch("recovery_repair.check_schedule_resources", side_effect=partial_checker):
        partial = repair_recovery_schedule(
            schedule,
            partial_analysis,
            [DisturbanceScenario("normal")],
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            current_time_s=600,
            locked_heavy_departures_s=[0],
            locked_empty_departures_s=[300],
            adjustment_step_s=30,
            max_abs_adjustment_s=180,
            beam_width=16,
        )
    assert partial.status == "partially_repaired_locked_residual"
    assert not partial.robust_resource_feasible
    assert partial.operational_intervention_required
    assert partial.final_scenarios[0].adjustable_conflict_count == 0
    assert partial.final_scenarios[0].locked_only_conflict_count == 1
    assert partial.schedule.heavy_departures_s == [0, 720, 1200]
    assert partial.locked_departures_preserved

    print("recovery local repair smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
