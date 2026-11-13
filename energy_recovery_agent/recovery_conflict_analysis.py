"""扰动恢复第一阶段：提取资源冲突链并划分锁定与可调整列车。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from resource_constraints import ResourceModel, check_schedule_resources
from rolling_optimizer import (
    DisturbanceScenario,
    GeneratedSchedule,
    apply_scenario,
)
from scheduler_nsga2 import PowerSeriesCache


@dataclass(frozen=True)
class RecoveryTrain:
    """恢复分析中的一列车及其决策边界。"""

    train_id: str
    train_type: str
    departure_index: int
    departure_time_s: int
    locked: bool
    adjustable: bool
    lock_reason: str


@dataclass(frozen=True)
class RecoveryConflict:
    """一个核心扰动场景下的冲突实例。"""

    scenario: str
    conflict_type: str
    resource_id: str
    resource_name: str
    train_a: str
    train_b: str
    overlap_start_s: float
    overlap_end_s: float
    overlap_duration_s: float
    location_km: str
    train_a_locked: bool
    train_b_locked: bool
    adjustable_train_ids: Tuple[str, ...]
    repairability: str


@dataclass(frozen=True)
class RecoveryConflictChain:
    """由共享列车连接起来的一组冲突。"""

    chain_id: str
    train_ids: Tuple[str, ...]
    locked_train_ids: Tuple[str, ...]
    adjustable_train_ids: Tuple[str, ...]
    scenario_names: Tuple[str, ...]
    resource_ids: Tuple[str, ...]
    conflict_types: Tuple[str, ...]
    conflict_ids: Tuple[str, ...]
    conflict_count: int
    total_overlap_s: float
    first_conflict_time_s: float
    last_conflict_time_s: float
    repairability: str


@dataclass(frozen=True)
class RecoveryAdjustmentCandidate:
    """按冲突负担排序的未来列车修复候选。"""

    priority_rank: int
    train_id: str
    train_type: str
    departure_index: int
    departure_time_s: int
    chain_ids: Tuple[str, ...]
    conflict_count: int
    locked_counterpart_conflict_count: int
    total_overlap_s: float
    earliest_conflict_time_s: float


@dataclass(frozen=True)
class RecoveryConflictAnalysis:
    """可由后续局部修复器直接消费的恢复分析结果。"""

    current_time_s: int
    trains: Tuple[RecoveryTrain, ...]
    conflicts: Tuple[RecoveryConflict, ...]
    chains: Tuple[RecoveryConflictChain, ...]
    adjustment_candidates: Tuple[RecoveryAdjustmentCandidate, ...]
    all_adjustable_train_ids: Tuple[str, ...]
    conflict_related_adjustable_train_ids: Tuple[str, ...]
    locked_train_ids: Tuple[str, ...]
    locked_only_conflict_count: int
    repairable_chain_count: int
    partially_blocked_chain_count: int
    blocked_chain_count: int

    def to_dict(self) -> Dict[str, Any]:
        """转换为稳定、可序列化的字典。"""

        return asdict(self)


def _train_catalog(
    schedule: GeneratedSchedule,
    current_time_s: int,
    locked_heavy_departures_s: Iterable[int],
    locked_empty_departures_s: Iterable[int],
) -> Tuple[RecoveryTrain, ...]:
    """按资源检查器相同的 H/E 编号规则建立列车目录。"""

    locked_heavy = {int(value) for value in locked_heavy_departures_s}
    locked_empty = {int(value) for value in locked_empty_departures_s}
    trains: List[RecoveryTrain] = []
    for prefix, train_type, departures, train_ids, explicit_locks in (
        ("H", "Heavy", schedule.heavy_departures_s, schedule.heavy_train_ids, locked_heavy),
        ("E", "Empty", schedule.empty_departures_s, schedule.empty_train_ids, locked_empty),
    ):
        for index, (departure_s, train_id) in enumerate(zip(departures, train_ids)):
            departure = int(departure_s)
            explicitly_locked = departure in explicit_locks
            already_started = departure < int(current_time_s)
            locked = explicitly_locked or already_started
            reason = (
                "explicitly_locked"
                if explicitly_locked
                else "already_departed"
                if already_started
                else "uncommitted_future"
            )
            trains.append(
                RecoveryTrain(
                    train_id=train_id,
                    train_type=train_type,
                    departure_index=index,
                    departure_time_s=departure,
                    locked=locked,
                    adjustable=not locked,
                    lock_reason=reason,
                )
            )
    return tuple(trains)


def _conflict_components(conflicts: Sequence[RecoveryConflict]) -> List[Tuple[str, ...]]:
    """将冲突边转换为列车图的确定性连通分量。"""

    adjacency: Dict[str, set[str]] = {}
    for conflict in conflicts:
        adjacency.setdefault(conflict.train_a, set()).add(conflict.train_b)
        adjacency.setdefault(conflict.train_b, set()).add(conflict.train_a)
    unseen = set(adjacency)
    components: List[Tuple[str, ...]] = []
    while unseen:
        root = min(unseen)
        stack = [root]
        unseen.remove(root)
        component: List[str] = []
        while stack:
            train_id = stack.pop()
            component.append(train_id)
            for neighbor in sorted(adjacency.get(train_id, ())):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        components.append(tuple(sorted(component)))
    return sorted(components, key=lambda item: item)


def extract_recovery_conflict_analysis(
    schedule: GeneratedSchedule,
    scenarios: Iterable[DisturbanceScenario],
    resource_model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    *,
    current_time_s: int,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
    core_only: bool = True,
    work_budget=None,
) -> RecoveryConflictAnalysis:
    """提取各核心扰动场景的冲突，并形成冲突链和可调整列车优先集合。"""

    current_time = int(current_time_s)
    trains = _train_catalog(
        schedule,
        current_time,
        locked_heavy_departures_s,
        locked_empty_departures_s,
    )
    train_by_id = {train.train_id: train for train in trains}
    selected_scenarios = [
        scenario
        for scenario in scenarios
        if not core_only or bool(scenario.core_for_feasibility)
    ]
    if not selected_scenarios:
        raise ValueError("恢复冲突分析至少需要一个待检查场景。")

    conflicts: List[RecoveryConflict] = []
    for scenario in selected_scenarios:
        if work_budget is not None:
            work_budget.resource()
        disturbed = apply_scenario(
            schedule,
            scenario,
            disturbance_from_time_s=current_time,
            locked_heavy_departures_s=locked_heavy_departures_s,
            locked_empty_departures_s=locked_empty_departures_s,
        )
        checked = check_schedule_resources(
            disturbed,
            resource_model,
            heavy_cache,
            empty_cache,
        )
        for conflict in checked.conflicts:
            train_a = train_by_id.get(str(conflict.train_a))
            train_b = train_by_id.get(str(conflict.train_b))
            if str(conflict.conflict_type) == "resource_unavailable_conflict":
                affected_train = train_a or train_b
                if affected_train is None:
                    raise ValueError(
                        "资源封锁冲突未引用运行图列车："
                        f"{conflict.train_a!r}, {conflict.train_b!r}"
                    )
                train_a = train_b = affected_train
            if train_a is None or train_b is None:
                raise ValueError(
                    "资源冲突引用了运行图中不存在的列车: "
                    f"{conflict.train_a!r}, {conflict.train_b!r}"
                )
            adjustable = tuple(dict.fromkeys(
                train.train_id
                for train in (train_a, train_b)
                if train.adjustable
            ))
            repairability = (
                "directly_adjustable"
                if adjustable
                else "locked_only_requires_operational_intervention"
            )
            conflicts.append(
                RecoveryConflict(
                    scenario=scenario.name,
                    conflict_type=str(conflict.conflict_type),
                    resource_id=str(conflict.resource_id),
                    resource_name=str(conflict.resource_name),
                    train_a=train_a.train_id,
                    train_b=train_b.train_id,
                    overlap_start_s=float(conflict.overlap_start_s),
                    overlap_end_s=float(conflict.overlap_end_s),
                    overlap_duration_s=float(conflict.overlap_duration_s),
                    location_km=str(conflict.location_km),
                    train_a_locked=train_a.locked,
                    train_b_locked=train_b.locked,
                    adjustable_train_ids=adjustable,
                    repairability=repairability,
                )
            )

        for violation in checked.flow_continuity_violations:
            train_id = str(violation.get("train_id") or "")
            train = train_by_id.get(train_id)
            if train is None:
                continue
            event_time = float(violation.get("time_s") or current_time)
            adjustable = (train_id,) if train.adjustable else ()
            conflicts.append(
                RecoveryConflict(
                    scenario=scenario.name,
                    conflict_type="flow_continuity_violation",
                    resource_id=f"flow:{violation.get('flow_type', '')}",
                    resource_name=str(violation.get("station_name") or "flow continuity"),
                    train_a=train_id,
                    train_b=train_id,
                    overlap_start_s=event_time,
                    overlap_end_s=event_time,
                    overlap_duration_s=0.0,
                    location_km="",
                    train_a_locked=train.locked,
                    train_b_locked=train.locked,
                    adjustable_train_ids=adjustable,
                    repairability=(
                        "directly_adjustable"
                        if adjustable
                        else "locked_only_requires_operational_intervention"
                    ),
                )
            )

    conflicts.sort(
        key=lambda item: (
            item.overlap_start_s,
            item.scenario,
            item.resource_id,
            item.train_a,
            item.train_b,
        )
    )
    chains: List[RecoveryConflictChain] = []
    for index, train_ids in enumerate(_conflict_components(conflicts), start=1):
        train_set = set(train_ids)
        indexed_chain_conflicts = [
            (conflict_index, conflict)
            for conflict_index, conflict in enumerate(conflicts, start=1)
            if conflict.train_a in train_set or conflict.train_b in train_set
        ]
        chain_conflicts = [conflict for _index, conflict in indexed_chain_conflicts]
        locked_ids = tuple(
            train_id for train_id in train_ids if train_by_id[train_id].locked
        )
        adjustable_ids = tuple(
            sorted(
                (train_id for train_id in train_ids if train_by_id[train_id].adjustable),
                key=lambda train_id: (
                    -sum(
                        conflict.overlap_duration_s
                        for conflict in chain_conflicts
                        if train_id in {conflict.train_a, conflict.train_b}
                    ),
                    train_by_id[train_id].departure_time_s,
                    train_id,
                ),
            )
        )
        locked_only_in_chain = sum(
            not conflict.adjustable_train_ids for conflict in chain_conflicts
        )
        if locked_only_in_chain == 0:
            repairability = "repairable_by_future_departure_adjustment"
        elif locked_only_in_chain == len(chain_conflicts):
            repairability = "blocked_by_locked_history"
        else:
            repairability = "partially_blocked_by_locked_history"
        chains.append(
            RecoveryConflictChain(
                chain_id=f"RC{index:03d}",
                train_ids=train_ids,
                locked_train_ids=locked_ids,
                adjustable_train_ids=adjustable_ids,
                scenario_names=tuple(sorted({item.scenario for item in chain_conflicts})),
                resource_ids=tuple(sorted({item.resource_id for item in chain_conflicts})),
                conflict_types=tuple(sorted({item.conflict_type for item in chain_conflicts})),
                conflict_ids=tuple(
                    f"CF{conflict_index:03d}"
                    for conflict_index, _conflict in indexed_chain_conflicts
                ),
                conflict_count=len(chain_conflicts),
                total_overlap_s=round(
                    sum(item.overlap_duration_s for item in chain_conflicts), 6
                ),
                first_conflict_time_s=min(
                    item.overlap_start_s for item in chain_conflicts
                ),
                last_conflict_time_s=max(
                    item.overlap_end_s for item in chain_conflicts
                ),
                repairability=repairability,
            )
        )

    all_adjustable = tuple(
        train.train_id for train in trains if train.adjustable
    )
    candidate_metrics = []
    for train in trains:
        if not train.adjustable:
            continue
        related_conflicts = [
            conflict
            for conflict in conflicts
            if train.train_id in {conflict.train_a, conflict.train_b}
        ]
        if not related_conflicts:
            continue
        locked_counterpart_count = 0
        for conflict in related_conflicts:
            counterpart_ids = (
                {conflict.train_a, conflict.train_b} - {train.train_id}
            )
            if any(train_by_id[item].locked for item in counterpart_ids):
                locked_counterpart_count += 1
        chain_ids = tuple(
            chain.chain_id
            for chain in chains
            if train.train_id in chain.train_ids
        )
        candidate_metrics.append(
            (
                -locked_counterpart_count,
                -sum(conflict.overlap_duration_s for conflict in related_conflicts),
                min(conflict.overlap_start_s for conflict in related_conflicts),
                train.departure_time_s,
                train.train_id,
                train,
                chain_ids,
                related_conflicts,
                locked_counterpart_count,
            )
        )
    candidate_metrics.sort(key=lambda item: item[:5])
    adjustment_candidates = tuple(
        RecoveryAdjustmentCandidate(
            priority_rank=rank,
            train_id=train.train_id,
            train_type=train.train_type,
            departure_index=train.departure_index,
            departure_time_s=train.departure_time_s,
            chain_ids=chain_ids,
            conflict_count=len(related_conflicts),
            locked_counterpart_conflict_count=locked_counterpart_count,
            total_overlap_s=round(
                sum(conflict.overlap_duration_s for conflict in related_conflicts), 6
            ),
            earliest_conflict_time_s=min(
                conflict.overlap_start_s for conflict in related_conflicts
            ),
        )
        for rank, (
            _locked_sort,
            _overlap_sort,
            _time_sort,
            _departure_sort,
            _id_sort,
            train,
            chain_ids,
            related_conflicts,
            locked_counterpart_count,
        ) in enumerate(candidate_metrics, start=1)
    )
    conflict_adjustable = tuple(
        candidate.train_id for candidate in adjustment_candidates
    )
    locked_ids = tuple(train.train_id for train in trains if train.locked)
    locked_only_count = sum(
        conflict.repairability == "locked_only_requires_operational_intervention"
        for conflict in conflicts
    )
    return RecoveryConflictAnalysis(
        current_time_s=current_time,
        trains=trains,
        conflicts=tuple(conflicts),
        chains=tuple(chains),
        adjustment_candidates=adjustment_candidates,
        all_adjustable_train_ids=all_adjustable,
        conflict_related_adjustable_train_ids=conflict_adjustable,
        locked_train_ids=locked_ids,
        locked_only_conflict_count=locked_only_count,
        repairable_chain_count=sum(
            chain.repairability == "repairable_by_future_departure_adjustment"
            for chain in chains
        ),
        partially_blocked_chain_count=sum(
            chain.repairability == "partially_blocked_by_locked_history"
            for chain in chains
        ),
        blocked_chain_count=sum(
            chain.repairability == "blocked_by_locked_history"
            for chain in chains
        ),
    )
