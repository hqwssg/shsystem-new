"""扰动恢复第二阶段：在锁定历史之外局部修复资源冲突。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from recovery_conflict_analysis import RecoveryConflictAnalysis
from resource_constraints import ResourceModel, check_schedule_resources
from rolling_optimizer import (
    DisturbanceScenario,
    GeneratedSchedule,
    ScheduleTemplate,
    apply_scenario,
    generate_schedule,
)
from scheduler_nsga2 import PowerSeriesCache, headway_violation_seconds


@dataclass(frozen=True)
class RecoveryRepairDecision:
    """一列可调整列车的最终发车修复量。"""

    train_id: str
    train_type: str
    departure_index: int
    original_departure_s: int
    repaired_departure_s: int
    adjustment_s: int


@dataclass(frozen=True)
class RecoveryRepairScenarioResult:
    """一个核心扰动场景下的修复后资源状态。"""

    scenario: str
    conflict_count: int
    adjustable_conflict_count: int
    locked_only_conflict_count: int
    unexpected_conflict_count: int
    flow_violation_count: int
    adjustable_overlap_s: float
    total_overlap_s: float
    headway_violation_s: float


@dataclass(frozen=True)
class RecoveryRepairResult:
    """局部恢复修复结果及其可审计边界。"""

    status: str
    schedule: GeneratedSchedule
    decisions: Tuple[RecoveryRepairDecision, ...]
    baseline_scenarios: Tuple[RecoveryRepairScenarioResult, ...]
    final_scenarios: Tuple[RecoveryRepairScenarioResult, ...]
    allowed_train_ids: Tuple[str, ...]
    locked_train_ids: Tuple[str, ...]
    robust_resource_feasible: bool
    operational_intervention_required: bool
    locked_departures_preserved: bool
    evaluation_count: int
    iteration_count: int
    max_single_adjustment_s: int
    total_adjustment_s: int
    diagnostic: str

    def to_dict(self) -> Dict[str, Any]:
        """转换为可直接写入 JSON 的稳定结构。"""

        return asdict(self)


@dataclass(frozen=True)
class ExactRecoveryResult:
    """精确资源求解器在滚动恢复边界下的结果。"""

    status: str
    proof: str
    schedule: GeneratedSchedule | None
    decisions: Tuple[RecoveryRepairDecision, ...]
    scope_train_ids: Tuple[str, ...]
    locked_train_ids: Tuple[str, ...]
    exact_resource_feasible: bool
    operational_intervention_required: bool
    locked_departures_preserved: bool
    diagnostics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """转换为可持久化的诊断结构。"""

        return asdict(self)


@dataclass(frozen=True)
class _EvaluatedState:
    """搜索内部使用的调整向量及评价结果。"""

    adjustments: Tuple[int, ...]
    schedule: GeneratedSchedule
    scenarios: Tuple[RecoveryRepairScenarioResult, ...]
    profile: Tuple[float, ...]


def _exact_base_template(schedule: GeneratedSchedule) -> ScheduleTemplate:
    """构造能精确重建合并运行图的全列车模板。"""

    heavy = tuple(sorted(int(value) for value in schedule.heavy_departures_s))
    empty = tuple(sorted(int(value) for value in schedule.empty_departures_s))
    heavy_headway = max(1, int(schedule.template.heavy_headway_s))
    empty_headway = max(1, int(schedule.template.empty_headway_s))
    # 统一以绝对时间零点展开，再通过逐车调整量恢复当前合并运行图。
    # 这样模板不再遗漏滚动窗口之前已经提交的列车。
    base = ScheduleTemplate(
        heavy_headway_s=heavy_headway,
        empty_headway_s=empty_headway,
        heavy_empty_phase_s=0,
        heavy_count=len(heavy),
        empty_count=len(empty),
        start_time_s=0,
        flex_zone_hold_s=int(schedule.template.flex_zone_hold_s),
        storage_align_shift_s=0,
        storage_preset_id=str(schedule.template.storage_preset_id or ""),
        heavy_departure_adjustments_s=tuple(
            value - index * heavy_headway for index, value in enumerate(heavy)
        ),
        empty_departure_adjustments_s=tuple(
            value - index * empty_headway for index, value in enumerate(empty)
        ),
    )
    rebuilt = generate_schedule(base)
    if rebuilt.heavy_departures_s != list(heavy) or rebuilt.empty_departures_s != list(empty):
        raise ValueError("精确恢复模板未能无损重建当前合并运行图。")
    return base


def solve_exact_recovery_schedule(
    schedule: GeneratedSchedule,
    analysis: RecoveryConflictAnalysis,
    scenarios: Iterable[DisturbanceScenario],
    resource_model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    *,
    current_time_s: int,
    horizon_end_s: int,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
    min_depart_gap_s: int = 300,
    initial_adjustment_bound_s: int = 600,
    time_limit_s: float = 60.0,
) -> ExactRecoveryResult:
    """在锁定历史条件下，用MILP求解全部未执行列车的稳健资源可行时刻。"""

    locked_ids = tuple(train.train_id for train in analysis.trains if train.locked)
    scope_ids = tuple(train.train_id for train in analysis.trains if train.adjustable)
    if analysis.locked_only_conflict_count > 0:
        return ExactRecoveryResult(
            status="blocked_by_locked_history",
            proof="immutable_locked_conflict_from_authoritative_resource_checker",
            schedule=None,
            decisions=(),
            scope_train_ids=scope_ids,
            locked_train_ids=locked_ids,
            exact_resource_feasible=False,
            operational_intervention_required=True,
            locked_departures_preserved=True,
            diagnostics={
                "triggered": False,
                "locked_only_conflict_count": analysis.locked_only_conflict_count,
                "note": "锁定列车之间已存在冲突，调整未来列车不可能恢复整轮资源可行。",
            },
        )

    from exact_resource_feasibility import solve_quality_optimized_resource_feasibility

    base_template = _exact_base_template(schedule)
    try:
        exact = solve_quality_optimized_resource_feasibility(
            base_template,
            tuple(scenarios),
            resource_model,
            heavy_cache,
            empty_cache,
            horizon_s=int(horizon_end_s),
            initial_adjustment_bound_s=int(initial_adjustment_bound_s),
            time_limit_s=float(time_limit_s),
            min_depart_gap_s=int(min_depart_gap_s),
            disturbance_from_time_s=int(current_time_s),
            locked_heavy_departures_s=tuple(int(value) for value in locked_heavy_departures_s),
            locked_empty_departures_s=tuple(int(value) for value in locked_empty_departures_s),
            include_multi_capacity_resources=True,
        )
    except Exception as exc:
        return ExactRecoveryResult(
            status="solver_error",
            proof="none",
            schedule=None,
            decisions=(),
            scope_train_ids=scope_ids,
            locked_train_ids=locked_ids,
            exact_resource_feasible=False,
            operational_intervention_required=True,
            locked_departures_preserved=True,
            diagnostics={
                "triggered": True,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
    if exact.schedule_template is None:
        return ExactRecoveryResult(
            status=exact.status,
            proof=exact.proof,
            schedule=None,
            decisions=(),
            scope_train_ids=scope_ids,
            locked_train_ids=locked_ids,
            exact_resource_feasible=False,
            operational_intervention_required=True,
            locked_departures_preserved=True,
            diagnostics={"triggered": True, "model": dict(exact.diagnostics)},
        )

    solved_schedule = generate_schedule(exact.schedule_template)
    if (
        len(solved_schedule.heavy_departures_s) == len(schedule.heavy_train_ids)
        and len(solved_schedule.empty_departures_s) == len(schedule.empty_train_ids)
    ):
        solved_schedule = GeneratedSchedule(
            solved_schedule.heavy_departures_s,
            solved_schedule.empty_departures_s,
            solved_schedule.template,
            list(schedule.heavy_train_ids),
            list(schedule.empty_train_ids),
        )
    baseline_heavy = tuple(sorted(int(value) for value in schedule.heavy_departures_s))
    baseline_empty = tuple(sorted(int(value) for value in schedule.empty_departures_s))
    solved_heavy = tuple(int(value) for value in solved_schedule.heavy_departures_s)
    solved_empty = tuple(int(value) for value in solved_schedule.empty_departures_s)
    train_by_id = {train.train_id: train for train in analysis.trains}
    decisions: List[RecoveryRepairDecision] = []
    for train_type, baseline, solved, train_ids in (
        ("Heavy", baseline_heavy, solved_heavy, schedule.heavy_train_ids),
        ("Empty", baseline_empty, solved_empty, schedule.empty_train_ids),
    ):
        for index, (original, repaired) in enumerate(zip(baseline, solved)):
            train_id = train_ids[index]
            if original == repaired:
                continue
            decisions.append(
                RecoveryRepairDecision(
                    train_id=train_id,
                    train_type=train_type,
                    departure_index=index,
                    original_departure_s=original,
                    repaired_departure_s=repaired,
                    adjustment_s=repaired - original,
                )
            )
    locked_id_set = set(locked_ids)
    locked_preserved = all(
        item.train_id not in locked_id_set for item in decisions
    ) and all(item.train_id in train_by_id for item in decisions)
    feasible = exact.feasible and locked_preserved
    return ExactRecoveryResult(
        status=(exact.status if locked_preserved else "locked_history_changed_rejected"),
        proof=(exact.proof if locked_preserved else "none"),
        schedule=(solved_schedule if locked_preserved else None),
        decisions=tuple(decisions),
        scope_train_ids=scope_ids,
        locked_train_ids=locked_ids,
        exact_resource_feasible=feasible,
        operational_intervention_required=not feasible,
        locked_departures_preserved=locked_preserved,
        diagnostics={"triggered": True, "model": dict(exact.diagnostics)},
    )


def _train_id(prefix: str, index: int) -> str:
    """按资源检查器的排序编号规则生成列车编号。"""

    return f"{prefix}{index + 1:03d}"


def _conflict_participants(conflict: Any) -> Tuple[str, ...]:
    """提取冲突涉及的有效列车编号，兼容单车连续性问题。"""

    return tuple(
        sorted(
            {
                str(value)
                for value in (
                    getattr(conflict, "train_a", ""),
                    getattr(conflict, "train_b", ""),
                )
                if str(value)
            }
        )
    )


def repair_recovery_schedule(
    schedule: GeneratedSchedule,
    analysis: RecoveryConflictAnalysis,
    scenarios: Iterable[DisturbanceScenario],
    resource_model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    *,
    current_time_s: int,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
    min_depart_gap_s: int = 300,
    adjustment_step_s: int = 30,
    max_abs_adjustment_s: int = 600,
    beam_width: int = 32,
    work_budget=None,
) -> RecoveryRepairResult:
    """只移动冲突相关未来列车，按可行性、最大偏移和总偏移依次优化。"""

    current_time = int(current_time_s)
    step = int(adjustment_step_s)
    max_abs = int(max_abs_adjustment_s)
    width = int(beam_width)
    if step <= 0 or max_abs < 0 or width <= 0:
        raise ValueError("修复步长和搜索宽度必须为正数，最大调整量不能为负数。")
    selected_scenarios = tuple(item for item in scenarios if item.core_for_feasibility)
    if not selected_scenarios:
        raise ValueError("恢复修复至少需要一个核心扰动场景。")

    trains = {train.train_id: train for train in analysis.trains}
    allowed_ids = tuple(
        train_id
        for train_id in analysis.conflict_related_adjustable_train_ids
        if train_id in trains and trains[train_id].adjustable
    )
    locked_ids = tuple(train.train_id for train in analysis.trains if train.locked)
    locked_id_set = set(locked_ids)
    allowed_id_set = set(allowed_ids)
    baseline_heavy = tuple(sorted(int(value) for value in schedule.heavy_departures_s))
    baseline_empty = tuple(sorted(int(value) for value in schedule.empty_departures_s))
    locked_heavy = tuple(int(value) for value in locked_heavy_departures_s)
    locked_empty = tuple(int(value) for value in locked_empty_departures_s)
    resource_interval_cache = {}
    resource_check_cache = {}

    def resource_check_key(candidate: GeneratedSchedule) -> Tuple[object, ...]:
        """构造完整资源检查的等价键；资源模型和轨迹缓存在本次修复内固定。"""

        template = getattr(candidate, "template", None)
        return (
            tuple(int(value) for value in candidate.heavy_departures_s),
            tuple(int(value) for value in candidate.empty_departures_s),
            tuple(str(value) for value in candidate.heavy_train_ids),
            tuple(str(value) for value in candidate.empty_train_ids),
            int(getattr(template, "flex_zone_hold_s", 0)),
        )

    def build_schedule(adjustments: Sequence[int]) -> GeneratedSchedule | None:
        """把调整向量映射回运行图，并保持同方向列车编号顺序。"""

        heavy = list(baseline_heavy)
        empty = list(baseline_empty)
        for train_id, adjustment in zip(allowed_ids, adjustments):
            train = trains[train_id]
            target = heavy if train.train_type == "Heavy" else empty
            repaired = int(train.departure_time_s) + int(adjustment)
            if repaired < current_time:
                return None
            target[train.departure_index] = repaired
        if any(right <= left for left, right in zip(heavy[:-1], heavy[1:])):
            return None
        if any(right <= left for left, right in zip(empty[:-1], empty[1:])):
            return None
        return GeneratedSchedule(
            heavy, empty, schedule.template,
            list(schedule.heavy_train_ids), list(schedule.empty_train_ids),
        )

    def evaluate(adjustments: Tuple[int, ...]) -> _EvaluatedState | None:
        """在全部核心场景下评价一个局部调整向量。"""

        candidate = build_schedule(adjustments)
        if candidate is None:
            return None
        if work_budget is not None:
            work_budget.candidate((tuple(candidate.heavy_departures_s), tuple(candidate.empty_departures_s),
                                   candidate.template.flex_zone_hold_s, candidate.template.storage_preset_id))
        scenario_rows: List[RecoveryRepairScenarioResult] = []
        for scenario in selected_scenarios:
            disturbed = apply_scenario(
                candidate,
                scenario,
                disturbance_from_time_s=current_time,
                locked_heavy_departures_s=locked_heavy,
                locked_empty_departures_s=locked_empty,
            )
            checked_key = resource_check_key(disturbed)
            checked = resource_check_cache.get(checked_key)
            if checked is None:
                if work_budget is not None:
                    work_budget.resource()
                checked = check_schedule_resources(
                    disturbed,
                    resource_model,
                    heavy_cache,
                    empty_cache,
                    resource_interval_cache,
                )
                resource_check_cache[checked_key] = checked
            adjustable_count = 0
            locked_count = 0
            unexpected_count = 0
            adjustable_overlap = 0.0
            for conflict in checked.conflicts:
                participants = set(_conflict_participants(conflict))
                if participants & allowed_id_set:
                    adjustable_count += 1
                    adjustable_overlap += float(conflict.overlap_duration_s)
                elif participants and participants <= locked_id_set:
                    locked_count += 1
                else:
                    unexpected_count += 1
            for violation in checked.flow_continuity_violations:
                train_id = str(violation.get("train_id") or "")
                if train_id in allowed_id_set:
                    adjustable_count += 1
                elif train_id in locked_id_set:
                    locked_count += 1
                else:
                    unexpected_count += 1
            headway_violation = headway_violation_seconds(
                disturbed.heavy_departures_s, min_depart_gap_s
            ) + headway_violation_seconds(
                disturbed.empty_departures_s, min_depart_gap_s
            )
            scenario_rows.append(
                RecoveryRepairScenarioResult(
                    scenario=scenario.name,
                    conflict_count=len(checked.conflicts),
                    adjustable_conflict_count=adjustable_count,
                    locked_only_conflict_count=locked_count,
                    unexpected_conflict_count=unexpected_count,
                    flow_violation_count=len(checked.flow_continuity_violations),
                    adjustable_overlap_s=round(adjustable_overlap, 6),
                    total_overlap_s=round(float(checked.overlap_violation_s), 6),
                    headway_violation_s=round(headway_violation, 6),
                )
            )
        max_adjustment = max((abs(value) for value in adjustments), default=0)
        total_adjustment = sum(abs(value) for value in adjustments)
        profile = (
            float(sum(row.unexpected_conflict_count for row in scenario_rows)),
            float(sum(row.adjustable_conflict_count for row in scenario_rows)),
            float(sum(row.headway_violation_s for row in scenario_rows)),
            float(sum(row.adjustable_overlap_s for row in scenario_rows)),
            float(max_adjustment),
            float(total_adjustment),
            float(sum(row.locked_only_conflict_count for row in scenario_rows)),
        )
        return _EvaluatedState(adjustments, candidate, tuple(scenario_rows), profile)

    zero = tuple(0 for _ in allowed_ids)
    baseline_state = evaluate(zero)
    if baseline_state is None:
        raise ValueError("原始运行图无法按恢复分析中的列车编号重建。")
    evaluation_count = 1

    def is_recovered(state: _EvaluatedState) -> bool:
        """判断所有可调整及意外冲突是否清零。"""

        return all(
            row.adjustable_conflict_count == 0
            and row.unexpected_conflict_count == 0
            and row.headway_violation_s == 0.0
            for row in state.scenarios
        )

    best = baseline_state
    successful: List[_EvaluatedState] = []
    if is_recovered(baseline_state):
        successful.append(baseline_state)
    frontier = [baseline_state]
    visited = {zero}
    max_iterations = (max_abs + step - 1) // step
    completed_iterations = 0
    for iteration in range(1, max_iterations + 1):
        next_states: List[_EvaluatedState] = []
        for state in frontier:
            for index in range(len(allowed_ids)):
                for direction in (-1, 1):
                    values = list(state.adjustments)
                    values[index] += direction * step
                    if abs(values[index]) > max_abs:
                        continue
                    candidate_key = tuple(values)
                    if candidate_key in visited:
                        continue
                    visited.add(candidate_key)
                    evaluated = evaluate(candidate_key)
                    if evaluated is None:
                        continue
                    evaluation_count += 1
                    next_states.append(evaluated)
                    if evaluated.profile < best.profile:
                        best = evaluated
                    if is_recovered(evaluated):
                        successful.append(evaluated)
        completed_iterations = iteration
        if not next_states:
            break
        next_states.sort(key=lambda item: (item.profile, item.adjustments))
        frontier = next_states[:width]

    if successful:
        successful.sort(
            key=lambda item: (
                max((abs(value) for value in item.adjustments), default=0),
                sum(abs(value) for value in item.adjustments),
                item.adjustments,
            )
        )
        best = successful[0]

    decisions = tuple(
        RecoveryRepairDecision(
            train_id=train_id,
            train_type=trains[train_id].train_type,
            departure_index=trains[train_id].departure_index,
            original_departure_s=trains[train_id].departure_time_s,
            repaired_departure_s=(
                trains[train_id].departure_time_s + adjustment
            ),
            adjustment_s=adjustment,
        )
        for train_id, adjustment in zip(allowed_ids, best.adjustments)
        if adjustment != 0
    )
    has_locked_residual = any(
        row.locked_only_conflict_count > 0 for row in best.scenarios
    )
    recovered = is_recovered(best)
    if recovered and has_locked_residual:
        status = "partially_repaired_locked_residual"
        diagnostic = "可调整冲突已清除；剩余冲突仅涉及锁定历史，需要行车组织干预。"
    elif recovered:
        status = "not_required" if not decisions else "fully_repaired"
        diagnostic = "核心扰动场景中的资源冲突和追踪间隔违反均已清除。"
    elif decisions and best.profile < baseline_state.profile:
        status = "partially_improved_unresolved"
        diagnostic = (
            "局部调整降低了冲突或约束负担，但仍有未解除冲突，需要扩大恢复范围或运营干预。"
        )
    else:
        status = "repair_failed"
        diagnostic = "在允许的局部调整范围内未能改善全部可调整或新增冲突。"

    locked_preserved = all(
        best.schedule.heavy_departures_s[index] == baseline_heavy[index]
        for index in range(len(baseline_heavy))
        if _train_id("H", index) in locked_id_set
    ) and all(
        best.schedule.empty_departures_s[index] == baseline_empty[index]
        for index in range(len(baseline_empty))
        if _train_id("E", index) in locked_id_set
    )
    return RecoveryRepairResult(
        status=status,
        schedule=best.schedule,
        decisions=decisions,
        baseline_scenarios=baseline_state.scenarios,
        final_scenarios=best.scenarios,
        allowed_train_ids=allowed_ids,
        locked_train_ids=locked_ids,
        robust_resource_feasible=recovered and not has_locked_residual,
        operational_intervention_required=not (recovered and not has_locked_residual),
        locked_departures_preserved=locked_preserved,
        evaluation_count=evaluation_count,
        iteration_count=completed_iterations,
        max_single_adjustment_s=max(
            (abs(item.adjustment_s) for item in decisions), default=0
        ),
        total_adjustment_s=sum(abs(item.adjustment_s) for item in decisions),
        diagnostic=diagnostic,
    )
