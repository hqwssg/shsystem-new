"""验证核心稳健不可行结果不会进入生产执行与锁定状态。"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rolling_optimizer import (
    GeneratedSchedule,
    ScheduleTemplate,
    gate_rolling_execution_commit,
)


def _schedule() -> GeneratedSchedule:
    return GeneratedSchedule(
        heavy_departures_s=[50, 150, 250],
        empty_departures_s=[60, 160, 260],
        template=ScheduleTemplate(100, 100, 10, 3, 3),
    )


def _diagnostics(feasible: bool) -> list[dict]:
    return [
        {"scenario": "normal", "core_for_feasibility": True, "feasible": feasible},
        {"scenario": "non_core_pressure", "core_for_feasibility": False, "feasible": False},
    ]


def main() -> int:
    first_cycle_withheld = gate_rolling_execution_commit(
        _schedule(),
        _diagnostics(False),
        current_time_s=0,
        execute_window_s=300,
    )
    assert first_cycle_withheld.commit_status == "withheld_infeasible"
    assert first_cycle_withheld.committed_execution_schedule.heavy_departures_s == []
    assert first_cycle_withheld.committed_execution_schedule.empty_departures_s == []
    assert first_cycle_withheld.executable_heavy_departures_s == []
    assert first_cycle_withheld.executable_empty_departures_s == []

    withheld = gate_rolling_execution_commit(
        _schedule(),
        _diagnostics(False),
        current_time_s=100,
        execute_window_s=200,
        locked_heavy_departures_s=[50, 150],
        locked_empty_departures_s=[60],
    )
    assert not withheld.core_robust_feasible
    assert withheld.commit_status == "withheld_infeasible"
    assert withheld.operational_intervention_required
    assert withheld.executable_heavy_departures_s == [150]
    assert withheld.executable_empty_departures_s == []
    assert withheld.committed_execution_schedule.heavy_departures_s == [50, 150]
    assert withheld.committed_execution_schedule.empty_departures_s == [60]

    no_core = gate_rolling_execution_commit(
        _schedule(),
        [{"scenario": "diagnostic_only", "core_for_feasibility": False, "feasible": True}],
        current_time_s=100,
        execute_window_s=200,
        locked_heavy_departures_s=[50], locked_empty_departures_s=[60],
    )
    assert no_core.commit_status == "withheld_infeasible"
    assert not no_core.executable_heavy_departures_s
    assert not no_core.executable_empty_departures_s

    committed = gate_rolling_execution_commit(
        _schedule(),
        _diagnostics(True),
        current_time_s=100,
        execute_window_s=200,
        locked_heavy_departures_s=[50], locked_empty_departures_s=[60],
    )
    assert committed.core_robust_feasible
    assert committed.commit_status == "committed_robust_feasible"
    assert not committed.operational_intervention_required
    assert committed.executable_heavy_departures_s == [150, 250]
    assert committed.executable_empty_departures_s == [160, 260]
    assert committed.committed_execution_schedule == _schedule()

    experimental = gate_rolling_execution_commit(
        _schedule(),
        _diagnostics(False),
        current_time_s=100,
        execute_window_s=200,
        locked_heavy_departures_s=[50], locked_empty_departures_s=[60],
        allow_infeasible_commit_for_experiment=True,
    )
    assert experimental.commit_status == "committed_infeasible_experiment_only"
    assert experimental.operational_intervention_required
    assert experimental.executable_heavy_departures_s == [150, 250]
    assert experimental.executable_empty_departures_s == [160, 260]

    try:
        gate_rolling_execution_commit(
            _schedule(),
            _diagnostics(True),
            current_time_s=100,
            execute_window_s=200,
            allow_infeasible_commit_for_experiment=1,  # type: ignore[arg-type]
        )
    except TypeError:
        pass
    else:
        raise AssertionError("非布尔实验覆盖参数未被拒绝")

    print("rolling infeasible commit gate smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
