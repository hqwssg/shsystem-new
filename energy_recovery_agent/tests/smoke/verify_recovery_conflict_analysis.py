"""验证扰动后冲突链和可调整列车集合提取。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from recovery_conflict_analysis import extract_recovery_conflict_analysis
from resource_constraints import ConflictExplanation, ResourceCheckResult
from rolling_optimizer import DisturbanceScenario, GeneratedSchedule, ScheduleTemplate


def _conflict(train_a: str, train_b: str, start_s: float, duration_s: float):
    """构造一个资源冲突测试对象。"""

    return ConflictExplanation(
        conflict_type="opposing_section_conflict",
        severity="blocking",
        resource_id=f"section:{train_a}:{train_b}",
        resource_name="测试区间",
        train_a=train_a,
        train_b=train_b,
        train_a_type="Heavy" if train_a.startswith("H") else "Empty",
        train_b_type="Heavy" if train_b.startswith("H") else "Empty",
        overlap_start_s=start_s,
        overlap_end_s=start_s + duration_s,
        overlap_duration_s=duration_s,
        location_km="K100-K110",
        message="测试冲突",
        suggestion="调整未来列车",
    )


def main() -> int:
    """检查冲突图连通分量、锁定边界和修复候选集合。"""

    schedule = GeneratedSchedule(
        heavy_departures_s=[0, 600, 1200],
        empty_departures_s=[300, 900],
        template=ScheduleTemplate(600, 600, 300, 3, 2),
    )
    first = ResourceCheckResult(
        feasible=False,
        conflicts=[
            _conflict("H001", "H002", 700.0, 30.0),
            _conflict("H002", "E002", 760.0, 60.0),
            _conflict("E001", "E001", 500.0, 20.0),
        ],
        intervals=[],
    )
    second = ResourceCheckResult(
        feasible=False,
        conflicts=[_conflict("H002", "E002", 800.0, 40.0)],
        intervals=[],
    )
    scenarios = [
        DisturbanceScenario("normal"),
        DisturbanceScenario("light_delay", heavy_delay_s=120),
        DisturbanceScenario("stress", heavy_delay_s=300, core_for_feasibility=False),
    ]
    with patch(
        "recovery_conflict_analysis.check_schedule_resources",
        side_effect=[first, second],
    ) as checker:
        analysis = extract_recovery_conflict_analysis(
            schedule,
            scenarios,
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            current_time_s=600,
            locked_heavy_departures_s=[0],
            locked_empty_departures_s=[300],
        )

    assert checker.call_count == 2
    assert analysis.all_adjustable_train_ids == ("H002", "H003", "E002")
    assert set(analysis.conflict_related_adjustable_train_ids) == {"H002", "E002"}
    assert [candidate.train_id for candidate in analysis.adjustment_candidates] == [
        "H002",
        "E002",
    ]
    assert [candidate.priority_rank for candidate in analysis.adjustment_candidates] == [1, 2]
    assert analysis.adjustment_candidates[0].locked_counterpart_conflict_count == 1
    assert analysis.locked_train_ids == ("H001", "E001")
    assert len(analysis.chains) == 2
    connected = next(chain for chain in analysis.chains if "H002" in chain.train_ids)
    assert analysis.adjustment_candidates[0].chain_ids == (connected.chain_id,)
    assert connected.train_ids == ("E002", "H001", "H002")
    assert connected.locked_train_ids == ("H001",)
    assert set(connected.adjustable_train_ids) == {"H002", "E002"}
    assert connected.conflict_count == 3
    assert len(connected.conflict_ids) == 3
    assert connected.total_overlap_s == 130.0
    assert connected.repairability == "repairable_by_future_departure_adjustment"
    blocked = next(chain for chain in analysis.chains if chain.train_ids == ("E001",))
    assert blocked.repairability == "blocked_by_locked_history"
    assert analysis.locked_only_conflict_count == 1
    assert analysis.repairable_chain_count == 1
    assert analysis.partially_blocked_chain_count == 0
    assert analysis.blocked_chain_count == 1
    assert all(conflict.scenario != "stress" for conflict in analysis.conflicts)

    partial_result = ResourceCheckResult(
        feasible=False,
        conflicts=[
            _conflict("E001", "E001", 500.0, 20.0),
            _conflict("E001", "E002", 700.0, 30.0),
        ],
        intervals=[],
    )
    with patch(
        "recovery_conflict_analysis.check_schedule_resources",
        return_value=partial_result,
    ):
        partial = extract_recovery_conflict_analysis(
            schedule,
            [DisturbanceScenario("normal")],
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            current_time_s=600,
            locked_heavy_departures_s=[0],
            locked_empty_departures_s=[300],
        )
    assert len(partial.chains) == 1
    assert partial.chains[0].repairability == "partially_blocked_by_locked_history"
    assert partial.repairable_chain_count == 0
    assert partial.partially_blocked_chain_count == 1
    assert partial.blocked_chain_count == 0

    print("recovery conflict analysis smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
