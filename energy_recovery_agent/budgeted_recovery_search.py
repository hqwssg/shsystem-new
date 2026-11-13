"""可关闭的预算化搜索→已有逐车修复→精确补解试验管线。

不替换默认生产入口；所有可提交候选必须取得真实五场景完整评分。
"""
from dataclasses import asdict, replace
import time

from constraint_guided_search import BudgetedEvaluator, run_search, screen_schedule
from exact_resource_feasibility import solve_exact_resource_feasibility
from recovery_conflict_analysis import extract_recovery_conflict_analysis
from recovery_repair import _exact_base_template, repair_recovery_schedule
from recovery_work_budget import WorkBudgetReached, WorkPhaseReached
from rolling_optimizer import (GeneratedSchedule, candidate_selection_key, default_scenarios,
    generate_schedule, resource_feasibility_repair_templates, robust_evaluate_schedule, rolling_future_template)


def schedule_key(s):
    return (tuple(s.heavy_departures_s), tuple(s.empty_departures_s),
            s.template.flex_zone_hold_s, s.template.storage_preset_id)


def optimize_budgeted(base, domain, config, case, context, budget, *, combined,
                      departure_end_s, current_time_s=0, history=None, regular_full_limit=12,
                      repair_resource_limit=900, exact_adjustment_bound_s=600, new_train_ids=None):
    """同一预算覆盖引导预筛、完整评分、逐车修复、MILP与权威复核。

    departure_end_s是本次请求的最晚发车时刻，滚动用例须在执行窗内满足服务。
    返回的selected始终是真实完整评分，不将资源预筛代理当成生产结果。
    """
    scenarios = tuple(default_scenarios())
    locked_h = tuple(history.heavy_departures_s) if history else ()
    locked_e = tuple(history.empty_departures_s) if history else ()
    base = rolling_future_template(base, current_time_s, reject_past=True)
    required_h, required_e = len(locked_h) + base.heavy_count, len(locked_e) + base.empty_count
    if new_train_ids is not None:
        new_train_ids = tuple(tuple(ids) for ids in new_train_ids)
        if len(new_train_ids) != 2 or tuple(map(len, new_train_ids)) != (base.heavy_count, base.empty_count):
            raise ValueError("显式服务ID数量必须与本窗请求一致")
        existing = set(history.heavy_train_ids + history.empty_train_ids) if history else set()
        all_ids = new_train_ids[0] + new_train_ids[1]
        if len(set(all_ids)) != len(all_ids) or existing.intersection(all_ids):
            raise ValueError("服务ID不得重复或复用历史身份")
        for prefix, ids in zip(("H", "E"), new_train_ids):
            if any(not isinstance(i, str) or len(i) != 4 or i[0] != prefix or not i[1:].isdigit() or int(i[1:]) == 0 for i in ids):
                raise ValueError("服务ID必须是H001/E001格式并与类型对应")
    records, archive, stages = [], {}, []
    best_near = None
    latest = None

    def factory(t):
        t = rolling_future_template(t, current_time_s)
        if history:
            t = replace(t, flex_zone_hold_s=history.template.flex_zone_hold_s,
                        storage_preset_id=history.template.storage_preset_id)
        fresh = generate_schedule(t)
        rows = []
        for type_index, (prefix, past, old_ids, new_times) in enumerate((
            ("H", locked_h, history.heavy_train_ids if history else [], fresh.heavy_departures_s),
            ("E", locked_e, history.empty_train_ids if history else [], fresh.empty_departures_s))):
            next_id = max((int(i[1:]) for i in old_ids), default=0)
            ids = new_train_ids[type_index] if new_train_ids is not None else tuple(f"{prefix}{next_id + i + 1:03d}" for i in range(len(new_times)))
            rows.append(sorted([*zip(past, old_ids),
                                *zip(new_times, ids)]))
        s = GeneratedSchedule([v for v, _ in rows[0]], [v for v, _ in rows[1]], t,
                              [i for _, i in rows[0]], [i for _, i in rows[1]])
        budget.candidate(schedule_key(s))
        return s

    def valid(s):
        for times, required, locks in ((s.heavy_departures_s, required_h, locked_h),
                                       (s.empty_departures_s, required_e, locked_e)):
            if len(times) != required or len(set(times)) != required or not set(locks).issubset(times):
                return False
            if any(t < current_time_s and t not in locks for t in times):
                return False
            if any(t > departure_end_s and t not in locks for t in times):
                return False
        return True

    def score_schedule(s):
        nonlocal best_near, latest
        key = schedule_key(s)
        budget.candidate(key)
        if key in archive:
            return archive[key][1]
        budget.full(len(scenarios))
        rows = []
        score = robust_evaluate_schedule(
            s, scenarios, context.heavy_cache, context.empty_cache, context.settlement_system,
            context.route.signaling_system, resource_model=case.resource_model,
            storage_sections=context.storage_sections,
            min_depart_gap_s=case.resource_model.config.min_depart_headway_s,
            target_gap_s=round((base.heavy_headway_s + base.empty_headway_s) / 2),
            objective_mode="balanced", energy_scenario="storage_no_direct", objective_priority="energy_first",
            disturbance_from_time_s=current_time_s, locked_heavy_departures_s=locked_h,
            locked_empty_departures_s=locked_e, energy_from_time_s=current_time_s, scenario_score_sink=rows)
        population_ok = valid(s)
        if not population_ok:
            score = replace(score, feasible=False, constraint_violation=score.constraint_violation + 1.)
        record = dict(stage=budget.stage, schedule=asdict(s), score=asdict(score), service_time_guard=population_ok,
                      scenario_scores=[dict(name=a.name, core_for_feasibility=a.core_for_feasibility,
                                            **asdict(b)) for a, b in rows])
        records.append(record)
        archive[key] = (s, score, record)
        latest = s
        if best_near is None or candidate_selection_key(score) < candidate_selection_key(best_near[1]):
            best_near = (s, score, record)
        return score

    def screen(t):
        s = factory(t)
        result = screen_schedule(s, scenarios=scenarios, resource_model=case.resource_model,
            heavy_cache=context.heavy_cache, empty_cache=context.empty_cache,
            required_heavy_count=required_h, required_empty_count=required_e,
            min_depart_gap_s=case.resource_model.config.min_depart_headway_s,
            disturbance_from_time_s=current_time_s, locked_heavy_departures_s=locked_h,
            locked_empty_departures_s=locked_e, work_budget=budget)
        return result

    def selected():
        feasible = [item for item in archive.values() if item[1].feasible]
        return min(feasible, key=lambda item: candidate_selection_key(item[1])) if feasible else None

    evaluator = BudgetedEvaluator(domain, lambda t: score_schedule(factory(t)), screen, layered=combined,
        full_evaluation_budget=min(regular_full_limit, budget.full_limit), proposal_budget=len(domain), deadline=budget.deadline)
    try:
        with budget.phase("search"):
            search = run_search(base, config, evaluator, guided=combined, guide_probe_budget=len(domain))
            search.pop("selected")
            stages.append(dict(stage="search", **search))
    except WorkBudgetReached as exc:
        stages.append(dict(stage="search", stop_reason=str(exc)))

    # 固定阶段份额，防止高代价启发式耗尽全部资源额度后无法执行精确补解。
    if selected() is None:
        try:
            with budget.phase("per_train_repair", resource_limit=repair_resource_limit):
                if history is not None:
                    s = best_near[0] if best_near else factory(base)
                    analysis = extract_recovery_conflict_analysis(s, scenarios, case.resource_model,
                        context.heavy_cache, context.empty_cache, current_time_s=current_time_s,
                        locked_heavy_departures_s=locked_h, locked_empty_departures_s=locked_e, work_budget=budget)
                    repair = repair_recovery_schedule(s, analysis, scenarios, case.resource_model,
                        context.heavy_cache, context.empty_cache, current_time_s=current_time_s,
                        locked_heavy_departures_s=locked_h, locked_empty_departures_s=locked_e,
                        min_depart_gap_s=case.resource_model.config.min_depart_headway_s,
                        beam_width=6, work_budget=budget)
                    latest = repair.schedule
                    score_schedule(repair.schedule)
                    stages.append(dict(stage="per_train_repair", diagnostics=repair.to_dict()))
                else:
                    seeds, diagnostic = resource_feasibility_repair_templates(base, config, scenarios,
                        case.resource_model, context.heavy_cache, context.empty_cache, factory,
                        required_heavy_count=required_h, required_empty_count=required_e,
                        disturbance_from_time_s=current_time_s, max_seeds=1, exact_horizon_s=None, work_budget=budget)
                    stages.append(dict(stage="per_train_repair", diagnostics=diagnostic))
                    for t in seeds:
                        score_schedule(factory(t))
        except WorkBudgetReached as exc:
            stages.append(dict(stage="per_train_repair", stop_reason=str(exc),
                               phase_only=isinstance(exc, WorkPhaseReached)))
    if selected() is None:
        try:
            with budget.phase("exact_completion"):
                s = best_near[0] if best_near is not None and valid(best_near[0]) else factory(base)
                # 稳定ID来自合并运行图，不允许精确层重编号已经下发的列车。
                result = solve_exact_resource_feasibility(_exact_base_template(s), scenarios, case.resource_model,
                    context.heavy_cache, context.empty_cache, horizon_s=departure_end_s,
                    max_adjustment_s=exact_adjustment_bound_s, time_limit_s=budget.solver_limit_s,
                    include_multi_capacity_resources=True, disturbance_from_time_s=current_time_s,
                    locked_heavy_departures_s=locked_h, locked_empty_departures_s=locked_e, work_budget=budget)
                stages.append(dict(stage="exact_completion", status=result.status, proof=result.proof,
                                   adjustment_bound_s=exact_adjustment_bound_s, diagnostics=result.diagnostics))
                if result.feasible and result.schedule_template is not None:
                    raw = generate_schedule(result.schedule_template)
                    candidate = GeneratedSchedule(raw.heavy_departures_s, raw.empty_departures_s, raw.template,
                                                   s.heavy_train_ids, s.empty_train_ids)
                    score_schedule(candidate)
        except WorkBudgetReached as exc:
            stages.append(dict(stage="exact_completion", stop_reason=str(exc)))
    # 记录真实端到端计算耗时；不能只比较NSGA-II段或把失败组算成有效加速。
    return dict(selected=selected(), diagnostic_schedule=best_near[0] if best_near else factory_unbudgeted(base, history, new_train_ids),
                full_candidate_records=records, stages=stages, search_trace=evaluator.trace, budget=budget.snapshot())


def factory_unbudgeted(base, history, new_train_ids=None):
    """仅在计算预算耗尽且没有完整评分时重建不可提交的显示对象，不作评价或搜索。"""
    fresh = generate_schedule(base)
    if history is None and new_train_ids is None:
        return fresh
    history = history or GeneratedSchedule([], [], base)
    rows = []
    for type_index, (prefix, old_times, old_ids, times) in enumerate((
        ("H", history.heavy_departures_s, history.heavy_train_ids, fresh.heavy_departures_s),
        ("E", history.empty_departures_s, history.empty_train_ids, fresh.empty_departures_s))):
        n = max((int(i[1:]) for i in old_ids), default=0)
        ids = new_train_ids[type_index] if new_train_ids is not None else tuple(f"{prefix}{n+i+1:03d}" for i in range(len(times)))
        rows.append(sorted([*zip(old_times, old_ids), *zip(times, ids)]))
    return GeneratedSchedule([t for t, _ in rows[0]], [t for t, _ in rows[1]], base,
                             [i for _, i in rows[0]], [i for _, i in rows[1]])
