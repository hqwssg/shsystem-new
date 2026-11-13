"""用混合整数规划精确判定重空列调度的核心稳健资源可行性。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple, cast
import math
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from resource_constraints import ResourceInterval, ResourceModel, build_resource_intervals, check_schedule_resources
from scheduler_nsga2 import PowerSeriesCache


@dataclass(frozen=True)
class ExactResourceFeasibilityResult:
    """精确资源模型的结论、可行运行图和可审计诊断。"""

    status: str
    proof: str
    schedule_template: Any | None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    @property
    def feasible(self) -> bool:
        return self.status == "feasible_verified"

    @property
    def proven_infeasible(self) -> bool:
        return self.status == "model_infeasible"


@dataclass(frozen=True)
class _Occupation:
    train_index: int
    train_id: str
    resource_id: str
    capacity: int
    start_offset_s: float
    end_offset_s: float


class _MilpBuilder:
    """构造稀疏线性整数模型，避免为零系数分配稠密矩阵。"""

    def __init__(self) -> None:
        self.cost: List[float] = []
        self.lower: List[float] = []
        self.upper: List[float] = []
        self.integrality: List[int] = []
        self.rows: List[Dict[int, float]] = []
        self.row_lower: List[float] = []
        self.row_upper: List[float] = []

    def variable(self, lower: float, upper: float, *, integer: bool, cost: float = 0.0) -> int:
        index = len(self.cost)
        self.cost.append(float(cost))
        self.lower.append(float(lower))
        self.upper.append(float(upper))
        self.integrality.append(1 if integer else 0)
        return index

    def constraint(
        self,
        coefficients: Mapping[int, float],
        *,
        lower: float = -math.inf,
        upper: float = math.inf,
    ) -> None:
        self.rows.append({index: float(value) for index, value in coefficients.items() if value})
        self.row_lower.append(float(lower))
        self.row_upper.append(float(upper))

    def scipy_inputs(self):
        row_indices: List[int] = []
        column_indices: List[int] = []
        values: List[float] = []
        for row_index, row in enumerate(self.rows):
            for column_index, value in row.items():
                row_indices.append(row_index)
                column_indices.append(column_index)
                values.append(value)
        matrix = coo_matrix(
            (values, (row_indices, column_indices)),
            shape=(len(self.rows), len(self.cost)),
        ).tocsr()
        return (
            np.asarray(self.cost),
            np.asarray(self.integrality),
            # SciPy 运行时支持数组边界；当前第三方类型存根仍把边界误标为标量。
            cast(Any, Bounds)(
                np.asarray(self.lower), np.asarray(self.upper)
            ),
            cast(Any, LinearConstraint)(
                matrix, np.asarray(self.row_lower), np.asarray(self.row_upper)
            ),
        )


def _single_train_profiles(
    base_template: Any,
    resource_model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
) -> Dict[str, Tuple[ResourceInterval, ...]]:
    """在远离零点裁剪的位置提取两类列车相对发车时刻的资源占用。"""

    from rolling_optimizer import GeneratedSchedule

    anchor_s = 100_000
    probe_template = replace(
        base_template,
        heavy_count=1,
        empty_count=1,
        start_time_s=anchor_s,
        heavy_departure_adjustments_s=(),
        empty_departure_adjustments_s=(),
        storage_align_shift_s=0,
    )
    profiles: Dict[str, Tuple[ResourceInterval, ...]] = {}
    for train_type, schedule in (
        ("Heavy", GeneratedSchedule([anchor_s], [], probe_template)),
        ("Empty", GeneratedSchedule([], [anchor_s], probe_template)),
    ):
        intervals = build_resource_intervals(schedule, resource_model, heavy_cache, empty_cache)
        profiles[train_type] = tuple(intervals)
    return profiles


def _connected_components(node_count: int, edges: Sequence[Tuple[int, int]]) -> List[List[int]]:
    adjacency = [set() for _ in range(node_count)]
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    components: List[List[int]] = []
    unseen = {index for index, links in enumerate(adjacency) if links}
    while unseen:
        root = min(unseen)
        stack = [root]
        component = []
        unseen.remove(root)
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbor in adjacency[node]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component))
    return components


def solve_exact_resource_feasibility(
    base_template: Any,
    scenarios: Iterable[Any],
    resource_model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    *,
    horizon_s: int,
    min_depart_gap_s: int | None = None,
    max_adjustment_s: int | None = None,
    time_limit_s: float = 300.0,
    objective_mode: str = "feasibility",
    include_multi_capacity_resources: bool = False,
    disturbance_from_time_s: int | None = None,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
    work_budget=None,
) -> ExactResourceFeasibilityResult:
    """在明确时域内求解整数秒发车时刻，并对全部核心场景验证资源可行性。

    `max_adjustment_s=None` 表示在整个 `[0, horizon_s]` 发车域内求解；给出该值时，
    结论只针对基线逐车正负调整范围。默认先解容量1资源构成的松弛模型：松弛无解
    可以严格推出完整模型无解；松弛解必须通过完整资源检查器后才能报告可行。
    """

    from rolling_optimizer import apply_scenario, generate_schedule

    if isinstance(horizon_s, bool) or int(horizon_s) <= 0:
        raise ValueError("horizon_s必须是正整数。")
    if max_adjustment_s is not None and int(max_adjustment_s) < 0:
        raise ValueError("max_adjustment_s不能小于0。")
    if not math.isfinite(float(time_limit_s)) or float(time_limit_s) <= 0:
        raise ValueError("time_limit_s必须是有限正数。")
    if objective_mode not in {"feasibility", "minimum_total_adjustment"}:
        raise ValueError("objective_mode必须是feasibility或minimum_total_adjustment。")
    core_scenarios = tuple(
        scenario for scenario in scenarios if bool(getattr(scenario, "core_for_feasibility", True))
    )
    if not core_scenarios:
        raise ValueError("精确资源模型至少需要一个核心场景。")

    base_schedule = generate_schedule(base_template)
    base_heavy = tuple(int(value) for value in base_schedule.heavy_departures_s)
    base_empty = tuple(int(value) for value in base_schedule.empty_departures_s)
    train_specs = [
        *(('Heavy', index, f'H{index + 1:03d}', value) for index, value in enumerate(base_heavy)),
        *(('Empty', index, f'E{index + 1:03d}', value) for index, value in enumerate(base_empty)),
    ]
    if not train_specs:
        raise ValueError("精确资源模型没有列车。")

    locked_heavy = {int(value) for value in locked_heavy_departures_s}
    locked_empty = {int(value) for value in locked_empty_departures_s}
    builder = _MilpBuilder()
    departure_variables: List[int] = []
    departure_bounds: List[Tuple[int, int]] = []
    locked_flags: List[bool] = []
    for train_type, _type_index, _train_id, base_time_s in train_specs:
        if max_adjustment_s is None:
            lower_s, upper_s = 0, int(horizon_s)
        else:
            lower_s = max(0, base_time_s - int(max_adjustment_s))
            upper_s = min(int(horizon_s), base_time_s + int(max_adjustment_s))
        locked = base_time_s in (locked_heavy if train_type == "Heavy" else locked_empty)
        if disturbance_from_time_s is not None and base_time_s < int(disturbance_from_time_s):
            locked = True
        locked_flags.append(locked)
        if locked:
            lower_s = upper_s = base_time_s
        elif disturbance_from_time_s is not None:
            lower_s = max(lower_s, int(disturbance_from_time_s))
        departure_bounds.append((lower_s, upper_s))
        departure_variables.append(builder.variable(lower_s, upper_s, integer=True))

    # 保持同类列车顺序并满足现有发车间隔约束，从而排除同向越行。
    minimum_gap = int(
        resource_model.config.min_depart_headway_s
        if min_depart_gap_s is None
        else min_depart_gap_s
    )
    for type_name in ("Heavy", "Empty"):
        indices = [index for index, spec in enumerate(train_specs) if spec[0] == type_name]
        for left, right in zip(indices[:-1], indices[1:]):
            builder.constraint(
                {departure_variables[right]: 1, departure_variables[left]: -1},
                lower=minimum_gap,
            )

    profiles = _single_train_profiles(base_template, resource_model, heavy_cache, empty_cache)
    model_statistics = {
        "scenario_count": len(core_scenarios),
        "resource_group_count": 0,
        "potential_overlap_pair_count": 0,
        "lane_assignment_variable_count": 0,
        "ordering_variable_count": 0,
        "fixed_order_constraint_count": 0,
        "resource_outage_disjunction_count": 0,
    }
    tolerance_s = float(resource_model.config.min_overlap_s)
    anchor_s = 100_000.0

    for scenario in core_scenarios:
        grouped: Dict[str, List[_Occupation]] = {}
        future_indices: Dict[int, int] = {}
        for train_type in ("Heavy", "Empty"):
            future_index = 0
            for train_index, spec in enumerate(train_specs):
                if spec[0] != train_type or locked_flags[train_index]:
                    continue
                future_indices[train_index] = future_index
                future_index += 1
        for train_index, (train_type, _type_index, train_id, _base_time_s) in enumerate(train_specs):
            delay_s = int(getattr(scenario, "heavy_delay_s" if train_type == "Heavy" else "empty_delay_s", 0))
            stretch_s = int(getattr(scenario, "heavy_headway_stretch_s" if train_type == "Heavy" else "empty_headway_stretch_s", 0))
            disturbance_s = (
                0
                if locked_flags[train_index]
                else delay_s + future_indices[train_index] * stretch_s
            )
            for interval in profiles[train_type]:
                grouped.setdefault(interval.resource_id, []).append(_Occupation(
                    train_index=train_index,
                    train_id=train_id,
                    resource_id=interval.resource_id,
                    capacity=int(interval.capacity),
                    start_offset_s=float(interval.start_time_s) - anchor_s + disturbance_s,
                    end_offset_s=float(interval.end_time_s) - anchor_s + disturbance_s,
                ))

        for resource_id, occupations in grouped.items():
            for outage in resource_model.unavailabilities:
                resource_matches = resource_id == outage.resource_id
                if outage.resource_type == "section" and resource_id.startswith(outage.resource_id + ":"):
                    resource_matches = True
                if not resource_matches:
                    continue
                for occupation in occupations:
                    departure = departure_variables[occupation.train_index]
                    lower_s, upper_s = departure_bounds[occupation.train_index]
                    # 发车变量为整数秒；使用零重叠边界，避免求解器把恰好等于
                    # min_overlap_s 的占用当作允许，而权威检查器会将其判为冲突。
                    allowed_overlap_s = 0.0
                    before_bound = outage.start_time_s - occupation.end_offset_s + allowed_overlap_s
                    after_bound = outage.end_time_s - occupation.start_offset_s - allowed_overlap_s
                    relax_before = max(0.0, upper_s - before_bound)
                    relax_after = max(0.0, after_bound - lower_s)
                    ordering = builder.variable(0, 1, integer=True)
                    builder.constraint(
                        {departure: 1, ordering: -relax_before},
                        upper=before_bound,
                    )
                    builder.constraint(
                        {departure: 1, ordering: -relax_after},
                        lower=after_bound - relax_after,
                    )
                    model_statistics["resource_outage_disjunction_count"] += 1
            capacity = min(item.capacity for item in occupations)
            if capacity > 1 and not include_multi_capacity_resources:
                continue
            edges: List[Tuple[int, int]] = []
            for left in range(len(occupations)):
                item_left = occupations[left]
                left_lb, left_ub = departure_bounds[item_left.train_index]
                for right in range(left + 1, len(occupations)):
                    item_right = occupations[right]
                    if item_left.train_index == item_right.train_index:
                        continue
                    right_lb, right_ub = departure_bounds[item_right.train_index]
                    left_always_before = (
                        left_ub + item_left.end_offset_s
                        <= right_lb + item_right.start_offset_s + tolerance_s
                    )
                    right_always_before = (
                        right_ub + item_right.end_offset_s
                        <= left_lb + item_left.start_offset_s + tolerance_s
                    )
                    if not left_always_before and not right_always_before:
                        edges.append((left, right))
            if not edges:
                continue
            model_statistics["resource_group_count"] += 1
            model_statistics["potential_overlap_pair_count"] += len(edges)
            edge_set = {tuple(sorted(edge)) for edge in edges}
            for component in _connected_components(len(occupations), edges):
                component_edges = [edge for edge in edges if edge[0] in component and edge[1] in component]
                if len(component) <= capacity:
                    continue
                assignment: Dict[Tuple[int, int], int] = {}
                if capacity > 1:
                    for item_index in component:
                        for lane in range(capacity):
                            assignment[(item_index, lane)] = builder.variable(0, 1, integer=True)
                            model_statistics["lane_assignment_variable_count"] += 1
                        builder.constraint(
                            {assignment[(item_index, lane)]: 1 for lane in range(capacity)},
                            lower=1,
                            upper=1,
                        )
                for left, right in component_edges:
                    if tuple(sorted((left, right))) not in edge_set:
                        continue
                    item_left = occupations[left]
                    item_right = occupations[right]
                    departure_left = departure_variables[item_left.train_index]
                    departure_right = departure_variables[item_right.train_index]
                    left_spec = train_specs[item_left.train_index]
                    right_spec = train_specs[item_right.train_index]
                    if capacity == 1 and left_spec[0] == right_spec[0]:
                        if left_spec[1] < right_spec[1]:
                            builder.constraint(
                                {departure_left: 1, departure_right: -1},
                                upper=(
                                    item_right.start_offset_s - item_left.end_offset_s
                                    + tolerance_s
                                ),
                            )
                        else:
                            builder.constraint(
                                {departure_right: 1, departure_left: -1},
                                upper=(
                                    item_left.start_offset_s - item_right.end_offset_s
                                    + tolerance_s
                                ),
                            )
                        model_statistics["fixed_order_constraint_count"] += 1
                        continue
                    lanes = range(capacity) if capacity > 1 else range(1)
                    for lane in lanes:
                        ordering = builder.variable(0, 1, integer=True)
                        model_statistics["ordering_variable_count"] += 1
                        maximum_left_violation = max(
                            0.0,
                            departure_bounds[item_left.train_index][1]
                            - departure_bounds[item_right.train_index][0]
                            + item_left.end_offset_s
                            - item_right.start_offset_s
                            - tolerance_s,
                        )
                        maximum_right_violation = max(
                            0.0,
                            departure_bounds[item_right.train_index][1]
                            - departure_bounds[item_left.train_index][0]
                            + item_right.end_offset_s
                            - item_left.start_offset_s
                            - tolerance_s,
                        )
                        if capacity == 1:
                            builder.constraint(
                                {departure_left: 1, departure_right: -1, ordering: maximum_left_violation},
                                upper=(
                                    item_right.start_offset_s - item_left.end_offset_s
                                    + tolerance_s + maximum_left_violation
                                ),
                            )
                            builder.constraint(
                                {departure_right: 1, departure_left: -1, ordering: -maximum_right_violation},
                                upper=item_left.start_offset_s - item_right.end_offset_s + tolerance_s,
                            )
                        else:
                            assign_left = assignment[(left, lane)]
                            assign_right = assignment[(right, lane)]
                            builder.constraint(
                                {
                                    departure_left: 1,
                                    departure_right: -1,
                                    ordering: maximum_left_violation,
                                    assign_left: maximum_left_violation,
                                    assign_right: maximum_left_violation,
                                },
                                upper=(
                                    item_right.start_offset_s - item_left.end_offset_s
                                    + tolerance_s + 3 * maximum_left_violation
                                ),
                            )
                            builder.constraint(
                                {
                                    departure_right: 1,
                                    departure_left: -1,
                                    ordering: -maximum_right_violation,
                                    assign_left: maximum_right_violation,
                                    assign_right: maximum_right_violation,
                                },
                                upper=(
                                    item_left.start_offset_s - item_right.end_offset_s
                                    + tolerance_s + 2 * maximum_right_violation
                                ),
                            )

    if objective_mode == "minimum_total_adjustment":
        # 在已确定的最大偏移边界内最小化总绝对偏移。偏差变量可连续，
        # 因发车时刻为整数且目标单调，最优偏差仍会落在整数秒。
        for train_index, (_train_type, _type_index, _train_id, base_time_s) in enumerate(train_specs):
            lower_s, upper_s = departure_bounds[train_index]
            maximum_deviation = max(abs(lower_s - base_time_s), abs(upper_s - base_time_s))
            deviation = builder.variable(0, maximum_deviation, integer=False, cost=1.0)
            departure = departure_variables[train_index]
            builder.constraint({departure: 1, deviation: -1}, upper=base_time_s)
            builder.constraint({departure: -1, deviation: -1}, upper=-base_time_s)

    cost, integrality, bounds, constraints = builder.scipy_inputs()
    if work_budget is not None:
        time_limit_s = work_budget.begin_solver(time_limit_s)
    solver_started = time.perf_counter()
    try:
        solved = milp(
            cost,
            integrality=integrality,
            bounds=bounds,
            constraints=constraints,
            options={"time_limit": float(time_limit_s), "mip_rel_gap": 0.0, "presolve": True},
        )
    finally:
        if work_budget is not None:
            work_budget.finish_solver(time.perf_counter() - solver_started)
    raw_mip_gap = getattr(solved, "mip_gap", None)
    diagnostics: Dict[str, Any] = {
        **model_statistics,
        "variable_count": len(builder.cost),
        "constraint_count": len(builder.rows),
        "solver_status_code": int(solved.status),
        "solver_message": str(solved.message),
        "solver_success": bool(solved.success),
        "mip_node_count": int(getattr(solved, "mip_node_count", 0) or 0),
        "mip_gap": None if raw_mip_gap is None else float(raw_mip_gap),
        "horizon_s": int(horizon_s),
        "max_adjustment_s": max_adjustment_s,
        "minimum_depart_gap_s": minimum_gap,
        "objective": (
            "minimum_total_absolute_departure_adjustment"
            if objective_mode == "minimum_total_adjustment"
            else "pure_feasibility_zero_objective"
        ),
        "model_scope": (
            "all_capacity_resources"
            if include_multi_capacity_resources
            else "unit_capacity_resource_relaxation_with_full_authoritative_verification"
        ),
        "core_scenarios": [str(getattr(scenario, "name", "unknown")) for scenario in core_scenarios],
    }
    if int(solved.status) == 2:
        return ExactResourceFeasibilityResult(
            status="model_infeasible",
            proof=(
                "highs_full_resource_milp_infeasibility_certificate"
                if include_multi_capacity_resources
                else "highs_unit_capacity_relaxation_infeasible_implies_full_model_infeasible"
            ),
            schedule_template=None,
            diagnostics=diagnostics,
        )
    if solved.x is None:
        return ExactResourceFeasibilityResult(
            status="solver_limit_no_solution" if int(solved.status) == 1 else "solver_error",
            proof="none",
            schedule_template=None,
            diagnostics=diagnostics,
        )

    solved_departures = [int(round(float(solved.x[index]))) for index in departure_variables]
    heavy_times = solved_departures[:len(base_heavy)]
    empty_times = solved_departures[len(base_heavy):]
    unadjusted = generate_schedule(replace(
        base_template,
        heavy_departure_adjustments_s=(),
        empty_departure_adjustments_s=(),
    ))
    solved_template = replace(
        base_template,
        heavy_departure_adjustments_s=tuple(
            value - base for value, base in zip(heavy_times, unadjusted.heavy_departures_s)
        ),
        empty_departure_adjustments_s=tuple(
            value - base for value, base in zip(empty_times, unadjusted.empty_departures_s)
        ),
    )
    solved_schedule = generate_schedule(solved_template)
    verification = []
    for scenario in core_scenarios:
        disturbed = apply_scenario(
            solved_schedule,
            scenario,
            disturbance_from_time_s=disturbance_from_time_s,
            locked_heavy_departures_s=locked_heavy,
            locked_empty_departures_s=locked_empty,
        )
        if work_budget is not None:
            work_budget.resource()
        checked = check_schedule_resources(disturbed, resource_model, heavy_cache, empty_cache)
        verification.append({
            "scenario": str(getattr(scenario, "name", "unknown")),
            "feasible": bool(checked.feasible),
            "conflict_count": int(checked.conflict_count),
            "overlap_violation_s": float(checked.overlap_violation_s),
            "flow_continuity_feasible": bool(checked.flow_continuity_feasible),
        })
    diagnostics["solved_heavy_departures_s"] = heavy_times
    diagnostics["solved_empty_departures_s"] = empty_times
    solved_adjustments = [
        value - spec[3]
        for value, spec in zip(solved_departures, train_specs)
    ]
    diagnostics["maximum_absolute_adjustment_s"] = max(
        (abs(value) for value in solved_adjustments),
        default=0,
    )
    diagnostics["total_absolute_adjustment_s"] = sum(
        abs(value) for value in solved_adjustments
    )
    diagnostics["authoritative_verification"] = verification
    if all(row["feasible"] for row in verification):
        return ExactResourceFeasibilityResult(
            status="feasible_verified",
            proof="highs_integer_solution_verified_by_authoritative_resource_checker",
            schedule_template=solved_template,
            diagnostics=diagnostics,
        )
    return ExactResourceFeasibilityResult(
        status="solver_candidate_rejected",
        proof="none",
        schedule_template=None,
        diagnostics=diagnostics,
    )


def solve_quality_optimized_resource_feasibility(
    base_template: Any,
    scenarios: Iterable[Any],
    resource_model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    *,
    horizon_s: int,
    initial_adjustment_bound_s: int = 600,
    time_limit_s: float = 300.0,
    **solver_kwargs: Any,
) -> ExactResourceFeasibilityResult:
    """按最小最大偏移、最小总偏移的顺序求解资源可行运行图。"""

    if isinstance(initial_adjustment_bound_s, bool) or int(initial_adjustment_bound_s) < 0:
        raise ValueError("initial_adjustment_bound_s不能小于0。")
    if not math.isfinite(float(time_limit_s)) or float(time_limit_s) <= 0:
        raise ValueError("time_limit_s必须是有限正数。")
    if "max_adjustment_s" in solver_kwargs or "objective_mode" in solver_kwargs:
        raise ValueError("质量求解器内部管理max_adjustment_s和objective_mode。")
    scenarios = tuple(scenarios)
    deadline = time.monotonic() + float(time_limit_s)
    probe_rows: List[Dict[str, Any]] = []

    def remaining_time() -> float:
        return max(0.01, deadline - time.monotonic())

    def probe(bound_s: int, objective_mode: str = "feasibility") -> ExactResourceFeasibilityResult:
        result = solve_exact_resource_feasibility(
            base_template,
            scenarios,
            resource_model,
            heavy_cache,
            empty_cache,
            horizon_s=horizon_s,
            max_adjustment_s=bound_s,
            time_limit_s=remaining_time(),
            objective_mode=objective_mode,
            **solver_kwargs,
        )
        probe_rows.append({
            "adjustment_bound_s": int(bound_s),
            "objective_mode": objective_mode,
            "status": result.status,
            "solver_status_code": result.diagnostics.get("solver_status_code"),
            "elapsed_remaining_s": round(remaining_time(), 6),
        })
        return result

    maximum_domain_bound = int(horizon_s)
    upper_bound = min(int(initial_adjustment_bound_s), maximum_domain_bound)
    upper_result = probe(upper_bound)
    while (
        upper_result.proven_infeasible
        and upper_bound < maximum_domain_bound
        and time.monotonic() < deadline
    ):
        upper_bound = min(maximum_domain_bound, max(upper_bound + 1, upper_bound * 2))
        upper_result = probe(upper_bound)
    if not upper_result.feasible:
        diagnostics = dict(upper_result.diagnostics)
        full_domain_infeasible = (
            upper_result.proven_infeasible
            and upper_bound == maximum_domain_bound
        )
        diagnostics["quality_optimization"] = {
            "completed": False,
            "reason": (
                "full_departure_domain_proven_infeasible"
                if full_domain_infeasible
                else "no_verified_feasible_upper_bound_within_time_limit"
            ),
            "probe_history": probe_rows,
        }
        return ExactResourceFeasibilityResult(
            status=("model_infeasible" if full_domain_infeasible else "solver_limit_no_solution"),
            proof=(upper_result.proof if full_domain_infeasible else "none"),
            schedule_template=None,
            diagnostics=diagnostics,
        )

    best_result = upper_result
    lower_infeasible_bound = -1
    while upper_bound - lower_infeasible_bound > 1 and time.monotonic() < deadline:
        midpoint = (lower_infeasible_bound + upper_bound) // 2
        midpoint_result = probe(midpoint)
        if midpoint_result.feasible:
            upper_bound = midpoint
            best_result = midpoint_result
        elif midpoint_result.proven_infeasible:
            lower_infeasible_bound = midpoint
        else:
            break

    minimum_bound_proven = upper_bound - lower_infeasible_bound == 1
    total_result = best_result
    total_adjustment_optimal = False
    if minimum_bound_proven and time.monotonic() < deadline:
        candidate = probe(upper_bound, objective_mode="minimum_total_adjustment")
        if candidate.feasible:
            total_result = candidate
            total_adjustment_optimal = int(candidate.diagnostics.get("solver_status_code", -1)) == 0

    diagnostics = dict(total_result.diagnostics)
    diagnostics["quality_optimization"] = {
        "completed": minimum_bound_proven and total_adjustment_optimal,
        "minimum_maximum_adjustment_proven": minimum_bound_proven,
        "minimum_maximum_adjustment_s": upper_bound,
        "lower_infeasible_adjustment_bound_s": lower_infeasible_bound,
        "total_absolute_adjustment_optimal": total_adjustment_optimal,
        "total_absolute_adjustment_s": diagnostics.get("total_absolute_adjustment_s"),
        "probe_history": probe_rows,
    }
    proof = (
        "highs_lexicographic_departure_adjustment_optimum_verified_by_authoritative_resource_checker"
        if minimum_bound_proven and total_adjustment_optimal
        else total_result.proof
    )
    return ExactResourceFeasibilityResult(
        status=total_result.status,
        proof=proof,
        schedule_template=total_result.schedule_template,
        diagnostics=diagnostics,
    )
