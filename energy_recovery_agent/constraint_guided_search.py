"""可关闭的约束引导/分层评价试验层，不改变生产评分或默认求解入口。"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
import time
from typing import Callable, Sequence

from resource_constraints import check_schedule_resources, normalized_resource_constraint_violation
from rolling_optimizer import (
    GeneratedSchedule, ScheduleScore, ScheduleTemplate, TemplateSearchConfig,
    apply_scenario, candidate_selection_key, nsga2_template_search, template_key,
)
from scheduler_nsga2 import headway_violation_seconds


@dataclass(frozen=True)
class StructuralScreen:
    """只证明某些候选不可行；通过预筛不代表信号、电气或SOC已通过。"""
    rejected: bool
    violation_lower_bound: float
    blocking_scenarios: tuple[str, ...] = ()
    reason: str = "needs_full_evaluation"

    def __post_init__(self):
        if type(self.rejected) is not bool or not math.isfinite(self.violation_lower_bound) or self.violation_lower_bound < 0:
            raise ValueError("无效的结构预筛结果")
        if self.rejected != (self.violation_lower_bound > 1e-9):
            raise ValueError("预筛拒绝必须有严格正的必要约束违反证据")


def screen_schedule(schedule: GeneratedSchedule, *, scenarios, resource_model,
                    heavy_cache, empty_cache, required_heavy_count: int,
                    required_empty_count: int, min_depart_gap_s: int,
                    disturbance_from_time_s: int | None = None,
                    locked_heavy_departures_s=(), locked_empty_departures_s=(), work_budget=None) -> StructuralScreen:
    """复用生产资源检查器，只检查明确作为硬门禁的核心场景。"""
    service_violation = abs(len(schedule.heavy_departures_s) - required_heavy_count) + abs(
        len(schedule.empty_departures_s) - required_empty_count)
    if service_violation:
        return StructuralScreen(True, float(service_violation), reason="service_population")
    scenarios = tuple(scenarios)
    core = [scenario for scenario in scenarios if scenario.core_for_feasibility]
    # 与完整评价器的无显式核心场景回退规则一致。
    core = core or list(scenarios)
    if not core:
        raise ValueError("预筛不能在没有扰动场景时判定")
    violations = []
    blocking = []
    # 与完整评价共用滚动起点和承诺锁定语义；迭代器在多场景之间不可耗尽。
    locked_heavy = tuple(locked_heavy_departures_s)
    locked_empty = tuple(locked_empty_departures_s)
    for scenario in core:
        disturbed = apply_scenario(
            schedule, scenario, disturbance_from_time_s=disturbance_from_time_s,
            locked_heavy_departures_s=locked_heavy,
            locked_empty_departures_s=locked_empty)
        headway = (headway_violation_seconds(sorted(disturbed.heavy_departures_s), min_gap_s=min_depart_gap_s)
                   + headway_violation_seconds(sorted(disturbed.empty_departures_s), min_gap_s=min_depart_gap_s))
        violation = headway / max(1.0, float(min_depart_gap_s))
        if resource_model is not None:
            if work_budget is not None:
                work_budget.resource()
            result = check_schedule_resources(disturbed, resource_model, heavy_cache, empty_cache)
            violation += normalized_resource_constraint_violation(result, max(1.0, float(min_depart_gap_s)))
            violation += len(result.flow_continuity_violations)
        violations.append(violation)
        if violation > 1e-9:
            blocking.append(scenario.name)
    bound = max(violations, default=0.0)
    return StructuralScreen(bound > 1e-9, bound, tuple(blocking),
                            "core_structure" if blocking else "needs_full_evaluation")


class SearchBudgetReached(Exception):
    """预算终止不是模型不可行证明。"""


class BudgetedEvaluator:
    """内部约束代理仅用于搜索；对外候选档案只含完整评价结果。"""
    def __init__(self, domain: Sequence[ScheduleTemplate], full_evaluate: Callable,
                 screen: Callable, *, layered: bool, full_evaluation_budget: int,
                 proposal_budget: int, deadline: float):
        if (type(full_evaluation_budget) is not int or full_evaluation_budget <= 0 or
                type(proposal_budget) is not int or proposal_budget <= 0):
            raise ValueError("评价和候选预算必须是正整数")
        self.domain = {template_key(item): item for item in domain}
        if not self.domain:
            raise ValueError("候选域不能为空")
        self.full_evaluate = full_evaluate
        self.screen = screen
        self.layered = layered
        self.full_evaluation_budget = full_evaluation_budget
        self.proposal_budget = proposal_budget
        self.deadline = deadline
        self.proposed = set()
        self.screened = {}
        self.full_scores = {}
        self.proxy_scores = {}
        self.full_evaluation_count = 0
        self.cache_hits = 0
        self.screen_time_s = 0.0
        self.full_time_s = 0.0
        self.stop_reason = "search_completed"
        self.trace = []

    def _check(self, template):
        if time.perf_counter() >= self.deadline:
            raise SearchBudgetReached("wall_time_budget")
        key = template_key(template)
        if key not in self.domain:
            raise ValueError("候选越过冻结离散域")
        if key not in self.proposed:
            if len(self.proposed) >= self.proposal_budget:
                raise SearchBudgetReached("proposal_budget")
            self.proposed.add(key)
            self.trace.append({"template_key": list(key), "stage": "proposal"})
        return key

    def inspect(self, template):
        key = self._check(template)
        if key not in self.screened:
            started = time.perf_counter()
            result = self.screen(template)
            self.screen_time_s += time.perf_counter() - started
            if not isinstance(result, StructuralScreen):
                raise TypeError("预筛接口必须返回StructuralScreen")
            self.screened[key] = result
            self.trace.append({"template_key": list(key), "stage": "structural_screen",
                               "rejected": result.rejected, "violation_lower_bound": result.violation_lower_bound,
                               "blocking_scenarios": list(result.blocking_scenarios), "reason": result.reason})
        return self.screened[key]

    def __call__(self, template):
        key = self._check(template)
        if key in self.full_scores:
            self.cache_hits += 1
            return self.full_scores[key]
        if key in self.proxy_scores:
            self.cache_hits += 1
            return self.proxy_scores[key]
        if self.layered:
            result = self.inspect(template)
            if result.rejected:
                # 这不是完整评分：仅为NSGA-II保留靠近可行域的搜索方向。
                # 不放入full_scores，也不导出伪零能耗或伪可行候选。
                proxy = ScheduleScore(False, 0.0, 0.0, 0.0, 0.0, 1,
                                      constraint_violation=result.violation_lower_bound)
                self.proxy_scores[key] = proxy
                self.trace.append({"template_key": list(key), "stage": "screen_rejected",
                                   "full_evaluated": False})
                return proxy
        if self.full_evaluation_count >= self.full_evaluation_budget:
            raise SearchBudgetReached("full_evaluation_budget")
        self._check(template)  # 预筛耗时同样计入墙钟上限。
        self.full_evaluation_count += 1
        started = time.perf_counter()
        score = self.full_evaluate(template)
        self.full_time_s += time.perf_counter() - started
        if not isinstance(score, ScheduleScore):
            raise TypeError("完整评价必须返回生产ScheduleScore")
        self.full_scores[key] = score
        self.trace.append({"template_key": list(key), "stage": "full_evaluation", "full_evaluated": True,
                           "feasible": score.feasible, "selection_key": list(candidate_selection_key(score))})
        return score

    def best(self):
        feasible = [(self.domain[key], score) for key, score in self.full_scores.items() if score.feasible]
        return min(feasible, key=lambda item: candidate_selection_key(item[1])) if feasible else None


def run_search(base: ScheduleTemplate, config: TemplateSearchConfig, evaluator: BudgetedEvaluator,
               *, guided: bool, guide_probe_budget: int = 48, guide_seed_count: int = 2) -> dict:
    """四组均调用同一生产NSGA-II。引导仅改变起点，分层仅改变评价适配。"""
    if guide_probe_budget <= 0 or guide_seed_count <= 0:
        raise ValueError("引导扫描和种子预算必须为正")
    started = time.perf_counter()
    search_base = base
    guide_keys = []
    try:
        if guided:
            probes = list(evaluator.domain.values())
            # 固定种子打散同约束分数的平局，避免根据穷举标签选择特殊相位。
            rng = random.Random(config.seed)
            rng.shuffle(probes)
            ranked = [(template, evaluator.inspect(template))
                      for template in probes[:min(guide_probe_budget, evaluator.proposal_budget)]]
            ranked.sort(key=lambda pair: pair[1].violation_lower_bound)
            for template, result in ranked[:guide_seed_count]:
                guide_keys.append(list(template_key(template)))
                evaluator(template)
            fully_scored_guides = [(evaluator.domain[tuple(key)], evaluator.full_scores[tuple(key)])
                                   for key in guide_keys if tuple(key) in evaluator.full_scores]
            if fully_scored_guides:
                search_base = min(fully_scored_guides, key=lambda pair: candidate_selection_key(pair[1]))[0]
        nsga2_template_search(search_base, config, evaluator)
    except SearchBudgetReached as error:
        evaluator.stop_reason = str(error)
    best = evaluator.best()
    return {"search_wall_time_s": time.perf_counter() - started,
            "stop_reason": evaluator.stop_reason, "guide_seed_keys": guide_keys,
            "search_center_key": list(template_key(search_base)),
            "selected": best, "full_evaluation_count": evaluator.full_evaluation_count,
            "screen_count": len(evaluator.screened), "screen_rejection_count": len(evaluator.proxy_scores),
            "proposal_count": len(evaluator.proposed), "cache_hits": evaluator.cache_hits,
            "screen_time_s": evaluator.screen_time_s, "full_evaluation_time_s": evaluator.full_time_s}
