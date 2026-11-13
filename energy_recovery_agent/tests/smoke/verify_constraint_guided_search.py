"""约束试验层预算、代理隔离、场景语义与完整结果门禁的轻量回归。"""

from dataclasses import replace
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from constraint_guided_search import (
    BudgetedEvaluator, StructuralScreen, SearchBudgetReached, run_search, screen_schedule,
)
from rolling_optimizer import ScheduleScore, ScheduleTemplate, default_scenarios, generate_schedule, template_key
from tools.benchmark_constraint_guided_search import make_domain, make_config, compare_full_records


def main():
    settings = {"heavy_headways_s": [3000, 3300], "empty_headways_s": [2700, 3300],
                "phases_s": [2600, 2760], "holds_s": [0], "storage_shifts_s": [0],
                "storage_preset_id": "fixed"}
    base, domain = make_domain(2, settings)
    config = make_config(settings, 11)
    optimum = next(item for item in domain if item.heavy_headway_s == item.empty_headway_s == 3300 and item.heavy_empty_phase_s == 2760)

    def screen(template):
        reject = template != optimum
        return StructuralScreen(reject, 1.0 if reject else 0.0)

    def score(template):
        return ScheduleScore(template == optimum, 100.0, 0.0, 100.0, 0.0, 5,
                             constraint_violation=0.0 if template == optimum else 1.0)

    for guided in (False, True):
        for layered in (False, True):
            evaluator = BudgetedEvaluator(domain, score, screen, layered=layered,
                                          full_evaluation_budget=2, proposal_budget=8,
                                          deadline=time.perf_counter() + 10)
            result = run_search(base, config, evaluator, guided=guided, guide_probe_budget=8)
            assert result["full_evaluation_count"] <= 2 and result["proposal_count"] <= 8
            assert len(evaluator.full_scores) == evaluator.full_evaluation_count
            assert set(evaluator.full_scores).isdisjoint(evaluator.proxy_scores)
            if guided:
                assert result["selected"] is not None and result["selected"][0] == optimum
            if result["selected"]:
                assert template_key(result["selected"][0]) in evaluator.full_scores
    evaluator = BudgetedEvaluator(domain, score, screen, layered=True,
                                  full_evaluation_budget=1, proposal_budget=1, deadline=time.perf_counter() + 10)
    proxy = evaluator(base)
    assert proxy.feasible is False and not evaluator.full_scores and evaluator.best() is None
    try:
        evaluator(optimum)
    except SearchBudgetReached as error:
        assert str(error) == "proposal_budget"
    else:
        raise AssertionError("未限制预筛的候选数量")
    expired = BudgetedEvaluator(domain, score, screen, layered=False, full_evaluation_budget=1,
                                proposal_budget=8, deadline=time.perf_counter() - 1)
    result = run_search(base, config, expired, guided=True)
    assert result["stop_reason"] == "wall_time_budget" and result["selected"] is None
    # 完整评价失败的候选即使通过结构筛查，也不能被判为可行。
    blocked = BudgetedEvaluator([base], lambda _: replace(score(base), feasible=False),
                                lambda _: StructuralScreen(False, 0.0), layered=True,
                                full_evaluation_budget=1, proposal_budget=1, deadline=time.perf_counter() + 10)
    blocked(base)
    assert blocked.best() is None and blocked.full_evaluation_count == 1

    resource_result = SimpleNamespace(flow_continuity_violations=[])
    checked_names = []

    def fake_scenario(schedule, scenario, **kwargs):
        checked_names.append(scenario.name)
        return schedule

    arguments = dict(scenarios=default_scenarios(), resource_model=object(), heavy_cache=object(),
                     empty_cache=object(), required_heavy_count=2, required_empty_count=2, min_depart_gap_s=300)
    with patch("constraint_guided_search.apply_scenario", side_effect=fake_scenario), \
         patch("constraint_guided_search.check_schedule_resources", return_value=resource_result), \
         patch("constraint_guided_search.normalized_resource_constraint_violation", return_value=1.0):
        result = screen_schedule(generate_schedule(base), **arguments)
        assert result.rejected and result.violation_lower_bound == 1.0
        assert checked_names == ["normal", "heavy_delay_light", "empty_delay_light"]
        checked_names.clear()
        result = screen_schedule(generate_schedule(base), **{**arguments, "scenarios": [replace(default_scenarios()[0], core_for_feasibility=False)]})
        assert result.rejected and checked_names == ["normal"]
    service = screen_schedule(generate_schedule(base), **{**arguments, "required_heavy_count": 3})
    assert service.rejected and service.reason == "service_population"
    # 独立判分比较不允许把未计算记录或域外记录冒充完整一致。
    assert not compare_full_records([{"template_key": ["outside"], "score": {}}], {})
    print("constraint-guided/layered search gates: PASS")


if __name__ == "__main__":
    main()
