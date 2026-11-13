"""验证提交门禁后的有限重试、等待、人工升级与幂等复用。"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rolling_optimizer import (
    GeneratedSchedule,
    RollingCycleObservation,
    RollingOptimizationResult,
    RollingSafetyController,
    RollingSafetyPolicy,
    RollingWindowState,
    ScheduleScore,
    ScheduleTemplate,
    TemplateSearchConfig,
    gate_rolling_execution_commit,
    run_mpc_cycles,
)


BASE_TEMPLATE = ScheduleTemplate(900, 900, 300, 1, 1)


def _result(state: RollingWindowState, feasible: bool) -> RollingOptimizationResult:
    schedule = GeneratedSchedule(
        heavy_departures_s=[state.current_time_s],
        empty_departures_s=[state.current_time_s + 100],
        template=BASE_TEMPLATE,
    )
    scenario_rows = (
        {
            "scenario": "normal",
            "core_for_feasibility": True,
            "feasible": feasible,
            "constraint_violation": 0.0 if feasible else 1.0,
            "resource_conflict_count": 0 if feasible else 1,
            "resource_overlap_violation_s": 0.0 if feasible else 60.0,
        },
    )
    decision = gate_rolling_execution_commit(
        schedule,
        scenario_rows,
        current_time_s=state.current_time_s,
        execute_window_s=600,
        locked_heavy_departures_s=state.locked_heavy_departures_s,
        locked_empty_departures_s=state.locked_empty_departures_s,
    )
    return RollingOptimizationResult(
        schedule=schedule,
        execution_schedule=schedule,
        committed_execution_schedule=decision.committed_execution_schedule,
        score=ScheduleScore(feasible, 1.0, 0.0, 1.0, 0.0, 1),
        executable_heavy_departures_s=decision.executable_heavy_departures_s,
        executable_empty_departures_s=decision.executable_empty_departures_s,
        core_robust_feasible=decision.core_robust_feasible,
        commit_status=decision.commit_status,
        operational_intervention_required=(
            decision.operational_intervention_required
        ),
        selected_scenario_diagnostics=scenario_rows,
    )


class SequenceOptimizer:
    """按给定序列返回可行性结果并记录每次求解配置。"""

    default_storage_preset_id = ""

    def __init__(self, feasibility_sequence: list[bool]) -> None:
        self.feasibility_sequence = list(feasibility_sequence)
        self.calls: list[dict] = []

    def optimize_once(self, state, _base_template, **kwargs):
        self.calls.append({"state": state, **kwargs})
        index = min(len(self.calls) - 1, len(self.feasibility_sequence) - 1)
        return _result(state, self.feasibility_sequence[index])


def main() -> int:
    base_config = TemplateSearchConfig(
        population_size=2,
        generations=1,
        elite_count=1,
    )
    policy = RollingSafetyPolicy(
        max_retries_per_cycle=1,
        retry_horizon_multiplier=1.5,
        retry_population_multiplier=2.0,
        retry_generation_increment=1,
    )

    retry_optimizer = SequenceOptimizer([False, True])
    retry_controller = RollingSafetyController(policy)
    recovered = retry_controller.optimize_cycle(
        retry_optimizer,  # type: ignore[arg-type]
        RollingWindowState(0, [], []),
        BASE_TEMPLATE,
        horizon_s=1200,
        execute_window_s=600,
        search_config=base_config,
        enable_recovery=False,
        allow_infeasible_commit_for_experiment=False,
    )
    assert recovered.safety_state == "recovered_automatically"
    assert recovered.safety_attempt_count == 2
    assert recovered.commit_status == "committed_robust_feasible"
    assert retry_optimizer.calls[1]["horizon_s"] == 1800
    assert retry_optimizer.calls[1]["search_config"].population_size == 4
    assert retry_optimizer.calls[1]["search_config"].generations == 2
    assert retry_optimizer.calls[1]["enable_recovery"] is True
    retry_transition = recovered.search_diagnostics["safety_state_machine"]
    assert retry_transition["attempts"][0]["failed_core_scenarios"]
    assert retry_transition["attempts"][0]["withheld_heavy_departures_s"] == [0]
    assert retry_transition["failed_core_scenarios"][0]["attempt_index"] == 0

    # 完全相同请求复用结果，不重复调用求解器。
    duplicate = retry_controller.optimize_cycle(
        retry_optimizer,  # type: ignore[arg-type]
        RollingWindowState(0, [], []),
        BASE_TEMPLATE,
        horizon_s=1200,
        execute_window_s=600,
        search_config=base_config,
        enable_recovery=False,
        allow_infeasible_commit_for_experiment=False,
    )
    assert duplicate is recovered
    assert len(retry_optimizer.calls) == 2

    # 连续两轮均不可行时，从等待新观测升级为要求调度员处置；扣留对象不能进入锁定历史。
    blocked_optimizer = SequenceOptimizer([False, False])
    blocked_results = run_mpc_cycles(
        blocked_optimizer,  # type: ignore[arg-type]
        RollingWindowState(0, [], []),
        BASE_TEMPLATE,
        cycles=2,
        horizon_s=1200,
        execute_window_s=600,
        search_config=base_config,
        safety_policy=RollingSafetyPolicy(enable_automatic_retry=False),
        observation_provider=lambda _index, _state, _previous: RollingCycleObservation(),
    )
    assert [item.safety_state for item in blocked_results] == [
        "waiting_for_observation",
        "manual_intervention_required",
    ]
    assert blocked_results[0].safety_action == (
        "hold_new_departures_and_reoptimize_on_new_observation"
    )
    assert blocked_results[1].operational_intervention_required
    assert blocked_optimizer.calls[1]["state"].locked_heavy_departures_s == []
    assert blocked_optimizer.calls[1]["state"].locked_empty_departures_s == []
    transition = blocked_results[1].search_diagnostics["safety_state_machine"]
    assert transition["withheld_heavy_departures_s"] == [600]
    assert transition["withheld_empty_departures_s"] == [700]
    assert transition["failed_core_scenarios"][0]["resource_conflict_count"] == 1

    # 首轮扣留后，现场观测发生变化且下一轮可行时明确标记为观测后恢复。
    observation_optimizer = SequenceOptimizer([False, True])
    observation_controller = RollingSafetyController(
        RollingSafetyPolicy(enable_automatic_retry=False)
    )
    first = observation_controller.optimize_cycle(
        observation_optimizer,  # type: ignore[arg-type]
        RollingWindowState(0, [], [], observed_heavy_delay_s=120),
        BASE_TEMPLATE,
        horizon_s=1200,
        execute_window_s=600,
        search_config=base_config,
        enable_recovery=True,
        allow_infeasible_commit_for_experiment=False,
    )
    second = observation_controller.optimize_cycle(
        observation_optimizer,  # type: ignore[arg-type]
        RollingWindowState(600, [], [], observed_heavy_delay_s=0),
        BASE_TEMPLATE,
        horizon_s=1200,
        execute_window_s=600,
        search_config=base_config,
        enable_recovery=True,
        allow_infeasible_commit_for_experiment=False,
    )
    assert first.safety_state == "waiting_for_observation"
    assert second.safety_state == "recovered_after_observation"
    assert second.safety_transition_history[0]["observation_changed"] is True

    for kwargs, expected_field in (
        ({"max_retries_per_cycle": -1}, "max_retries_per_cycle"),
        ({"retry_horizon_multiplier": 0.5}, "retry_horizon_multiplier"),
        ({"manual_after_consecutive_withheld": 0}, "manual_after_consecutive_withheld"),
    ):
        try:
            RollingSafetyPolicy(**kwargs)
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"非法安全策略未被拒绝：{kwargs!r}")

    print("rolling safety degradation state machine smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
