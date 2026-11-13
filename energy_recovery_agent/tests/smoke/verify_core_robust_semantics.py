# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rolling_optimizer import (
    DisturbanceScenario,
    GeneratedSchedule,
    ScheduleScore,
    ScheduleTemplate,
    explain_robust_scenarios,
    robust_evaluate_schedule,
    scenario_diagnostic_rows,
)


def _score(*, feasible: bool, violation: float = 0.0, conflicts: int = 0) -> ScheduleScore:
    """函数 _score：执行该模块中的相关处理逻辑。"""
    return ScheduleScore(
        feasible=feasible,
        total_cost=100.0,
        headway_deviation=0.0,
        worst_case_cost=100.0,
        worst_case_headway_deviation=0.0,
        scenario_count=1,
        resource_conflict_count=conflicts,
        constraint_violation=violation,
    )


def _evaluate_by_delay(schedule: GeneratedSchedule, *_args, **_kwargs) -> ScheduleScore:
    """函数 _evaluate_by_delay：执行该模块中的相关处理逻辑。"""
    delay_s = schedule.heavy_departures_s[0]
    if delay_s >= 300:
        return _score(feasible=False, violation=0.25, conflicts=4)
    return _score(feasible=True)


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    schedule = GeneratedSchedule(
        heavy_departures_s=[0],
        empty_departures_s=[],
        template=ScheduleTemplate(900, 900, 0, 1, 0),
    )
    scenarios = [
        DisturbanceScenario("normal"),
        DisturbanceScenario("heavy_delay_light", heavy_delay_s=120),
        DisturbanceScenario("heavy_delay", heavy_delay_s=300, core_for_feasibility=False),
    ]
    captured_scenario_scores = []
    with patch("rolling_optimizer.evaluate_schedule", side_effect=_evaluate_by_delay):
        aggregate = robust_evaluate_schedule(
            schedule,
            scenarios,
            heavy_cache=None,
            empty_cache=None,
            settlement_system=None,
            signaling_system={},
            scenario_score_sink=captured_scenario_scores,
        )
        rows = explain_robust_scenarios(
            schedule,
            scenarios,
            heavy_cache=None,
            empty_cache=None,
            settlement_system=None,
            signaling_system={},
        )
        cached_rows = scenario_diagnostic_rows(
            schedule,
            captured_scenario_scores,
            heavy_cache=None,
            empty_cache=None,
        )

    assert aggregate.feasible is True
    assert cached_rows == rows
    assert aggregate.constraint_violation == 0.0
    assert aggregate.resource_conflict_count == 0
    hard = next(row for row in rows if row["scenario"] == "heavy_delay")
    assert hard["core_for_feasibility"] is False
    assert hard["blocking"] is False
    assert hard["diagnostic_failure"] is True

    renamed_blocking = [
        DisturbanceScenario("baseline"),
        DisturbanceScenario("renamed_scenario", heavy_delay_s=300),
    ]
    with patch("rolling_optimizer.evaluate_schedule", side_effect=_evaluate_by_delay):
        renamed_aggregate = robust_evaluate_schedule(
            schedule,
            renamed_blocking,
            heavy_cache=None,
            empty_cache=None,
            settlement_system=None,
            signaling_system={},
        )
    assert renamed_aggregate.feasible is False
    assert renamed_aggregate.constraint_violation == 0.25
    print("core robust feasibility semantics passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
