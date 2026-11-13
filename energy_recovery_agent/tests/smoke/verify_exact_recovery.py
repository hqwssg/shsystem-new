"""验证精确资源求解器接入扰动恢复流程的边界。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exact_resource_feasibility import ExactResourceFeasibilityResult
from recovery_conflict_analysis import extract_recovery_conflict_analysis
from recovery_repair import (
    ExactRecoveryResult,
    RecoveryRepairDecision,
    RecoveryRepairResult,
    solve_exact_recovery_schedule,
)
from resource_constraints import ConflictExplanation, ResourceCheckResult
from rolling_optimizer import (
    DisturbanceScenario,
    GeneratedSchedule,
    RollingOptimizer,
    RollingWindowState,
    ScheduleScore,
    ScheduleTemplate,
    TemplateSearchConfig,
    default_scenarios,
    generate_schedule,
)
from run_dispatch_case import load_case_inputs
from scheduler_nsga2 import build_power_cache


def _conflict(train_a: str, train_b: str):
    """构造一个确定性的资源冲突。"""

    return ConflictExplanation(
        conflict_type="opposing_section_conflict",
        severity="blocking",
        resource_id=f"section:{train_a}:{train_b}",
        resource_name="测试区间",
        train_a=train_a,
        train_b=train_b,
        train_a_type="Heavy" if train_a.startswith("H") else "Empty",
        train_b_type="Heavy" if train_b.startswith("H") else "Empty",
        overlap_start_s=700.0,
        overlap_end_s=760.0,
        overlap_duration_s=60.0,
        location_km="K100-K110",
        message="测试冲突",
        suggestion="执行精确恢复",
    )


def _analysis(schedule, conflicts):
    """通过第一阶段接口建立精确恢复输入。"""

    checked = ResourceCheckResult(False, list(conflicts), [], 60.0)
    with patch(
        "recovery_conflict_analysis.check_schedule_resources",
        return_value=checked,
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
    """检查全运行图重建、锁定边界、精确候选回映和异常降级。"""

    schedule = GeneratedSchedule(
        heavy_departures_s=[0, 600, 1200],
        empty_departures_s=[300, 900],
        template=ScheduleTemplate(600, 600, 300, 1, 1),
    )
    analysis = _analysis(schedule, [_conflict("H001", "H002")])
    captured = {}

    def fake_exact(base_template, _scenarios, *_args, **kwargs):
        captured["base_template"] = base_template
        captured["kwargs"] = kwargs
        rebuilt = generate_schedule(base_template)
        assert rebuilt.heavy_departures_s == [0, 600, 1200]
        assert rebuilt.empty_departures_s == [300, 900]
        heavy_adjustments = list(base_template.heavy_departure_adjustments_s)
        heavy_adjustments[1] += 120
        solved_template = replace(
            base_template,
            heavy_departure_adjustments_s=tuple(heavy_adjustments),
        )
        return ExactResourceFeasibilityResult(
            status="feasible_verified",
            proof="test_verified",
            schedule_template=solved_template,
            diagnostics={"quality_optimization": {"completed": True}},
        )

    with patch(
        "exact_resource_feasibility.solve_quality_optimized_resource_feasibility",
        side_effect=fake_exact,
    ) as solver:
        result = solve_exact_recovery_schedule(
            schedule,
            analysis,
            [DisturbanceScenario("normal")],
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            current_time_s=600,
            horizon_end_s=2400,
            locked_heavy_departures_s=[0],
            locked_empty_departures_s=[300],
        )
    assert solver.call_count == 1
    assert result.status == "feasible_verified"
    assert result.exact_resource_feasible
    assert result.locked_departures_preserved
    assert result.schedule is not None
    assert result.schedule.heavy_departures_s == [0, 720, 1200]
    assert [(item.train_id, item.adjustment_s) for item in result.decisions] == [
        ("H002", 120)
    ]
    assert set(result.scope_train_ids) == {"H002", "H003", "E002"}
    assert captured["kwargs"]["disturbance_from_time_s"] == 600
    assert captured["kwargs"]["locked_heavy_departures_s"] == (0,)
    assert captured["kwargs"]["locked_empty_departures_s"] == (300,)
    assert captured["kwargs"]["include_multi_capacity_resources"] is True

    blocked_analysis = _analysis(schedule, [_conflict("H001", "E001")])
    with patch(
        "exact_resource_feasibility.solve_quality_optimized_resource_feasibility"
    ) as blocked_solver:
        blocked = solve_exact_recovery_schedule(
            schedule,
            blocked_analysis,
            [DisturbanceScenario("normal")],
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            current_time_s=600,
            horizon_end_s=2400,
            locked_heavy_departures_s=[0],
            locked_empty_departures_s=[300],
        )
    blocked_solver.assert_not_called()
    assert blocked.status == "blocked_by_locked_history"
    assert blocked.operational_intervention_required
    assert blocked.schedule is None

    with patch(
        "exact_resource_feasibility.solve_quality_optimized_resource_feasibility",
        side_effect=RuntimeError("injected solver error"),
    ):
        failed = solve_exact_recovery_schedule(
            schedule,
            analysis,
            [DisturbanceScenario("normal")],
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            current_time_s=600,
            horizon_end_s=2400,
            locked_heavy_departures_s=[0],
            locked_empty_departures_s=[300],
        )
    assert failed.status == "solver_error"
    assert failed.diagnostics["error_type"] == "RuntimeError"
    assert failed.operational_intervention_required

    # 验证精确恢复不是孤立工具，而是常规搜索和局部修复均失败后的生产回退路径。
    class _Route:
        signaling_system = {"mode": "fixed_block"}

    class _ResourceConfig:
        min_depart_headway_s = 300

    class _ResourceModel:
        config = _ResourceConfig()

    def score(feasible: bool, violation: float) -> ScheduleScore:
        return ScheduleScore(
            feasible=feasible,
            total_cost=1.0,
            headway_deviation=0.0,
            worst_case_cost=1.0,
            worst_case_headway_deviation=0.0,
            scenario_count=5,
            constraint_violation=violation,
        )

    integration_optimizer = RollingOptimizer(
        _Route(),
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        resource_model=_ResourceModel(),  # type: ignore[arg-type]
    )
    integration_template = ScheduleTemplate(600, 600, 300, 1, 1)
    integration_local = RecoveryRepairResult(
        status="repair_failed",
        schedule=GeneratedSchedule([0, 600], [900], integration_template),
        decisions=(),
        baseline_scenarios=(),
        final_scenarios=(),
        allowed_train_ids=("H002",),
        locked_train_ids=("H001",),
        robust_resource_feasible=False,
        operational_intervention_required=True,
        locked_departures_preserved=True,
        evaluation_count=1,
        iteration_count=1,
        max_single_adjustment_s=0,
        total_adjustment_s=0,
        diagnostic="测试局部修复失败",
    )
    exact_schedule = GeneratedSchedule([0, 720], [900], integration_template)
    integration_exact = ExactRecoveryResult(
        status="feasible_verified",
        proof="test_exact_verified",
        schedule=exact_schedule,
        decisions=(
            RecoveryRepairDecision("H002", "Heavy", 1, 600, 720, 120),
        ),
        scope_train_ids=("H002", "E001"),
        locked_train_ids=("H001",),
        exact_resource_feasible=True,
        operational_intervention_required=False,
        locked_departures_preserved=True,
        diagnostics={"triggered": True},
    )

    def fake_robust(candidate, scenarios, *_args, scenario_score_sink=None, **_kwargs):
        candidate_score = score(candidate.heavy_departures_s == [0, 720], 0.0 if candidate.heavy_departures_s == [0, 720] else 10.0)
        if scenario_score_sink is not None:
            scenario_score_sink.extend((scenario, candidate_score) for scenario in scenarios)
        return candidate_score

    fake_analysis = SimpleNamespace(locked_only_conflict_count=0)
    with patch(
        "rolling_optimizer.robust_evaluate_schedule",
        side_effect=fake_robust,
    ), patch(
        "rolling_optimizer.evaluate_schedule",
        return_value=score(True, 0.0),
    ), patch(
        "rolling_optimizer.nsga2_template_search",
        side_effect=lambda base, _config, evaluate: [(base, evaluate(base))],
    ), patch(
        "rolling_optimizer.resource_feasibility_repair_templates",
        return_value=([], {"triggered": True}),
    ), patch(
        "recovery_conflict_analysis.extract_recovery_conflict_analysis",
        return_value=fake_analysis,
    ), patch(
        "recovery_repair.repair_recovery_schedule",
        return_value=integration_local,
    ), patch(
        "recovery_repair.solve_exact_recovery_schedule",
        return_value=integration_exact,
    ) as exact_recovery_call, patch(
        "rolling_optimizer.scenario_diagnostic_rows",
        return_value=({"scenario": "normal", "core_for_feasibility": True, "feasible": True},),
    ):
        integration_result = integration_optimizer.optimize_once(
            RollingWindowState(600, [0], []),
            integration_template,
            horizon_s=1800,
            execute_window_s=600,
            search_config=TemplateSearchConfig(
                method="nsga2",
                population_size=1,
                generations=1,
                elite_count=1,
                min_headway_s=300,
                max_headway_s=900,
                max_phase_s=900,
                enable_storage_preset_search=False,
            ),
        )
    assert exact_recovery_call.call_count == 1
    assert integration_result.schedule.heavy_departures_s == [0, 720]
    assert integration_result.score.feasible
    assert integration_result.search_diagnostics["exact_recovery"]["adopted"] is True
    assert integration_result.search_diagnostics["exact_recovery"]["full_robust_feasible"] is True
    assert integration_result.executable_heavy_departures_s == [720]

    def fake_nonfeasible_robust(candidate, scenarios, *_args, scenario_score_sink=None, **_kwargs):
        candidate_score = score(
            False,
            1.0 if candidate.heavy_departures_s == [0, 720] else 10.0,
        )
        if scenario_score_sink is not None:
            scenario_score_sink.extend((scenario, candidate_score) for scenario in scenarios)
        return candidate_score

    with patch(
        "rolling_optimizer.robust_evaluate_schedule",
        side_effect=fake_nonfeasible_robust,
    ), patch(
        "rolling_optimizer.evaluate_schedule",
        return_value=score(True, 0.0),
    ), patch(
        "rolling_optimizer.nsga2_template_search",
        side_effect=lambda base, _config, evaluate: [(base, evaluate(base))],
    ), patch(
        "rolling_optimizer.resource_feasibility_repair_templates",
        return_value=([], {"triggered": True}),
    ), patch(
        "recovery_conflict_analysis.extract_recovery_conflict_analysis",
        return_value=fake_analysis,
    ), patch(
        "recovery_repair.repair_recovery_schedule",
        return_value=integration_local,
    ), patch(
        "recovery_repair.solve_exact_recovery_schedule",
        return_value=integration_exact,
    ), patch(
        "rolling_optimizer.scenario_diagnostic_rows",
        return_value=({"scenario": "normal", "core_for_feasibility": True, "feasible": False},),
    ):
        rejected_exact_result = integration_optimizer.optimize_once(
            RollingWindowState(600, [0], []),
            integration_template,
            horizon_s=1800,
            execute_window_s=600,
            search_config=TemplateSearchConfig(
                method="nsga2",
                population_size=1,
                generations=1,
                elite_count=1,
                min_headway_s=300,
                max_headway_s=900,
                max_phase_s=900,
                enable_storage_preset_search=False,
            ),
        )
    assert rejected_exact_result.schedule.heavy_departures_s == [0, 600]
    assert rejected_exact_result.search_diagnostics["exact_recovery"]["adopted"] is False
    assert rejected_exact_result.search_diagnostics["exact_recovery"]["full_robust_feasible"] is False

    # 使用当前线路、车辆轨迹和HiGHS后端验证带锁定历史的真实精确模型，而不只验证接口mock。
    with TemporaryDirectory(prefix="exact_recovery_real_smoke_") as temp_name:
        case_inputs = load_case_inputs(ROOT / "data" / "real_shuohuang", Path(temp_name))
        real_heavy_cache = build_power_cache(
            case_inputs.trains["Heavy"],
            case_inputs.route,
            power_arm_interval_path=case_inputs.power_arm_path,
            storage_sections=case_inputs.storage_sections,
        )
        real_empty_cache = build_power_cache(
            case_inputs.trains["Empty"],
            case_inputs.route,
            power_arm_interval_path=case_inputs.power_arm_path,
            storage_sections=case_inputs.storage_sections,
        )
        real_template = ScheduleTemplate(3300, 2700, 2600, 2, 2)
        real_schedule = generate_schedule(real_template)
        real_scenarios = default_scenarios()
        real_analysis = extract_recovery_conflict_analysis(
            real_schedule,
            real_scenarios,
            case_inputs.resource_model,
            real_heavy_cache,
            real_empty_cache,
            current_time_s=600,
            locked_heavy_departures_s=[0],
        )
        assert real_analysis.locked_only_conflict_count == 0
        real_exact = solve_exact_recovery_schedule(
            real_schedule,
            real_analysis,
            real_scenarios,
            case_inputs.resource_model,
            real_heavy_cache,
            real_empty_cache,
            current_time_s=600,
            horizon_end_s=7200,
            locked_heavy_departures_s=[0],
            time_limit_s=30,
        )
    assert real_exact.status == "feasible_verified"
    assert real_exact.exact_resource_feasible
    assert real_exact.locked_departures_preserved
    assert real_exact.schedule is not None
    assert real_exact.schedule.heavy_departures_s[0] == 0

    print("exact recovery integration smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
