"""把列车运行过程转换为空间—时间网络表示，供调度约束和路径分析使用。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

from resource_constraints import ResourceModel, crossing_time_s
from scheduler_nsga2 import PowerSeriesCache
from power_arm_electrical_limits import (
    StorageSectionInterval,
    load_storage_section_intervals,
    storage_boundary_kms,
    storage_section_for_position,
)


def _whole_departure_time(value: Any) -> int:
    """函数 _whole_departure_time：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"departure time must be a finite whole number, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"departure time must be a finite whole number, got {value!r}") from exc
    if not math.isfinite(number) or not number.is_integer() or number < 0.0:
        raise ValueError(f"departure time must be a finite whole number, got {value!r}")
    return int(number)


@dataclass(frozen=True)
class TimeSpaceNode:
    """A time-space event node for one train at one location/state."""

    node_id: str
    train_id: str
    train_type: str
    direction: str
    station_name: str
    position_km: float
    time_s: float
    state: str


@dataclass(frozen=True)
class TimeSpaceArc:
    """A directed activity arc between two time-space nodes."""

    arc_id: str
    train_id: str
    train_type: str
    direction: str
    from_node_id: str
    to_node_id: str
    arc_type: str
    start_time_s: float
    end_time_s: float
    start_km: float
    end_km: float
    duration_s: float
    distance_km: float
    energy_kwh: float
    capacity_resource_id: str
    cost: float
    source: str
    storage_section_id: str = ""


@dataclass(frozen=True)
class TimeSpaceTrainPath:
    """类 TimeSpaceTrainPath：执行该模块中的相关处理逻辑。"""
    train_id: str
    train_type: str
    direction: str
    depart_time_s: int
    arrival_time_s: float
    completion_time_s: float
    node_ids: Tuple[str, ...]
    arc_ids: Tuple[str, ...]


@dataclass(frozen=True)
class TimeSpaceNetwork:
    """Node-arc representation of one dispatch schedule."""

    nodes: Tuple[TimeSpaceNode, ...]
    arcs: Tuple[TimeSpaceArc, ...]
    train_paths: Tuple[TimeSpaceTrainPath, ...]

    @property
    def node_count(self) -> int:
        """函数 node_count：执行该模块中的相关处理逻辑。"""
        return len(self.nodes)

    @property
    def arc_count(self) -> int:
        """函数 arc_count：执行该模块中的相关处理逻辑。"""
        return len(self.arcs)

    def arc_type_counts(self) -> Dict[str, int]:
        """函数 arc_type_counts：执行该模块中的相关处理逻辑。"""
        counts: Dict[str, int] = {}
        for arc in self.arcs:
            counts[arc.arc_type] = counts.get(arc.arc_type, 0) + 1
        return counts

    def total_energy_kwh_by_type(self) -> Dict[str, float]:
        """函数 total_energy_kwh_by_type：执行该模块中的相关处理逻辑。"""
        totals: Dict[str, float] = {}
        for arc in self.arcs:
            totals[arc.arc_type] = totals.get(arc.arc_type, 0.0) + arc.energy_kwh
        return totals


def _schedule_runs(schedule, heavy_cache: PowerSeriesCache, empty_cache: PowerSeriesCache) -> List[Tuple[str, str, int, PowerSeriesCache]]:
    """函数 _schedule_runs：执行该模块中的相关处理逻辑。"""
    runs: List[Tuple[str, str, int, PowerSeriesCache]] = []
    heavy_ids = list(getattr(schedule, "heavy_train_ids", ())) or [
        f"H{idx:03d}" for idx in range(1, len(schedule.heavy_departures_s) + 1)
    ]
    empty_ids = list(getattr(schedule, "empty_train_ids", ())) or [
        f"E{idx:03d}" for idx in range(1, len(schedule.empty_departures_s) + 1)
    ]
    for depart_time_s, train_id in zip(schedule.heavy_departures_s, heavy_ids):
        runs.append((train_id, "Heavy", _whole_departure_time(depart_time_s), heavy_cache))
    for depart_time_s, train_id in zip(schedule.empty_departures_s, empty_ids):
        runs.append((train_id, "Empty", _whole_departure_time(depart_time_s), empty_cache))
    return sorted(runs, key=lambda item: (item[2], item[0]))


def _stations_in_direction(stations: Iterable[Any], direction: str) -> List[Any]:
    """函数 _stations_in_direction：执行该模块中的相关处理逻辑。"""
    ordered = sorted(stations, key=lambda station: station.position_km)
    if direction == "reverse":
        return list(reversed(ordered))
    return ordered


def _operation_plan(
    model: ResourceModel,
    train_type: str,
    direction: str,
    station_name: str,
    station_idx: int,
    station_count: int,
) -> Optional[Dict[str, Any]]:
    """函数 _operation_plan：执行该模块中的相关处理逻辑。"""
    for assignment in model.station_operation_assignments:
        if str(assignment.get("station_name") or "") != station_name:
            continue
        assignment_train_type = str(assignment.get("train_type") or "").strip()
        if assignment_train_type and assignment_train_type != train_type:
            continue
        assignment_direction = str(assignment.get("direction") or "").strip()
        if assignment_direction and assignment_direction != direction:
            continue

        applies_to = str(assignment.get("applies_to") or "all").strip().lower()
        applies = applies_to in {"all", "any"}
        if applies_to in {"origin", "start"}:
            applies = station_idx == 0
        if applies_to in {"destination", "terminal", "end"}:
            applies = station_idx == station_count - 1
        if not applies:
            continue

        operation_s = int(assignment.get("min_occupancy_s") or 0)
        if operation_s <= 0:
            operation_s = int(model.station_operation_min_times_s.get(station_name, 0))
        if operation_s <= 0:
            continue
        source = str(assignment.get("source") or model.station_operation_sources.get(station_name, "technical operation"))
        detail = dict(model.station_operation_details.get(station_name, {}))
        detail.setdefault("station_name", station_name)
        detail.setdefault("operation_type", "technical_operation")
        detail.setdefault("source", source)
        detail["total_s"] = operation_s
        detail["assignment"] = dict(assignment)
        detail["applies_to"] = applies_to
        return detail
    return None


def _operation_activity_parts(plan: Dict[str, Any]) -> List[Tuple[str, int, str]]:
    """函数 _operation_activity_parts：执行该模块中的相关处理逻辑。"""
    operation_type = str(plan.get("operation_type") or "").lower()
    source = str(plan.get("source") or "technical_operation")
    total_s = int(plan.get("total_s") or 0)
    spotting_s = max(0, int(plan.get("spotting_s") or 0))
    loading_unloading_s = max(0, int(plan.get("loading_unloading_s") or 0))
    pickup_s = max(0, int(plan.get("pickup_s") or 0))

    activities: List[Tuple[str, int, str]] = []
    if spotting_s:
        activities.append(("spotting", spotting_s, source))
    if loading_unloading_s:
        if "卸" in operation_type:
            arc_type = "unloading"
        elif "装" in operation_type:
            arc_type = "loading"
        else:
            arc_type = "loading_unloading"
        activities.append((arc_type, loading_unloading_s, source))
    if pickup_s:
        activities.append(("pickup", pickup_s, source))

    used_s = sum(duration_s for _arc_type, duration_s, _source in activities)
    if total_s > used_s:
        activities.insert(0, ("waiting", total_s - used_s, source))
    if not activities and total_s > 0:
        activities.append(("technical_operation", total_s, source))
    return activities


def _post_operation_virtual_parts(plan: Dict[str, Any], train_type: str) -> List[Tuple[str, int, str]]:
    """函数 _post_operation_virtual_parts：执行该模块中的相关处理逻辑。"""
    source = str(plan.get("source") or "technical_operation")
    operation_type = str(plan.get("operation_type") or "")
    parts: List[Tuple[str, int, str]] = []
    if train_type == "Heavy" and ("卸" in operation_type or "装" in operation_type):
        parts.append(("dismantling", 0, source))
        parts.append(("virtual_trainset", 0, "virtual trainset continuity placeholder"))
    elif train_type == "Empty" and ("装" in operation_type or "卸" in operation_type):
        parts.append(("virtual_trainset", 0, "virtual trainset continuity placeholder"))
    return parts


def _arc_energy_between(cache: PowerSeriesCache, start_elapsed_s: float, end_elapsed_s: float) -> float:
    """函数 _arc_energy_between：执行该模块中的相关处理逻辑。"""
    if end_elapsed_s <= start_elapsed_s:
        return 0.0
    total_kwh = 0.0
    for index in range(max(0, len(cache.times) - 1)):
        sample_start_s = float(cache.times[index])
        sample_end_s = float(cache.times[index + 1])
        overlap_start_s = max(float(start_elapsed_s), sample_start_s)
        overlap_end_s = min(float(end_elapsed_s), sample_end_s)
        if overlap_end_s <= overlap_start_s:
            continue
        total_kwh += float(cache.powers_kW[index]) * (overlap_end_s - overlap_start_s) / 3600.0
    return total_kwh


def _storage_boundaries_between(
    start_km: float,
    end_km: float,
    storage_sections: Tuple[StorageSectionInterval, ...],
    direction: str,
) -> List[float]:
    """函数 _storage_boundaries_between：执行该模块中的相关处理逻辑。"""
    lower = min(float(start_km), float(end_km))
    upper = max(float(start_km), float(end_km))
    boundaries = {
        float(boundary)
        for boundary in storage_boundary_kms(storage_sections, direction)
        if lower < float(boundary) < upper
    }
    return sorted(boundaries, reverse=end_km < start_km)


def _storage_section_for_arc(
    start_km: float,
    end_km: float,
    storage_sections: Tuple[StorageSectionInterval, ...],
    direction: str,
) -> str:
    """函数 _storage_section_for_arc：执行该模块中的相关处理逻辑。"""
    if abs(float(end_km) - float(start_km)) <= 1e-9:
        return storage_section_for_position(float(start_km), storage_sections, direction)
    return storage_section_for_position(
        (float(start_km) + float(end_km)) / 2.0,
        storage_sections,
        direction,
    )


def build_time_space_network(
    schedule,
    resource_model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    storage_sections: Optional[Iterable[StorageSectionInterval]] = None,
) -> TimeSpaceNetwork:
    """Expand a dispatch schedule into a node-arc time-space network."""

    nodes: List[TimeSpaceNode] = []
    arcs: List[TimeSpaceArc] = []
    paths: List[TimeSpaceTrainPath] = []
    selected_storage_sections = (
        tuple(storage_sections)
        if storage_sections is not None
        else load_storage_section_intervals()
    )
    # 同车型多列车通常共享一条基础轨迹和相同站间边界。弧能量只取决于轨迹对象及
    # 轨迹内起止时刻，因此可在本次网络构建内严格复用，避免逐列车重复全轨迹积分。
    arc_energy_cache: Dict[Tuple[int, float, float], float] = {}

    schedule_template = getattr(schedule, "template", None)
    for train_id, train_type, depart_time_s, cache in _schedule_runs(schedule, heavy_cache, empty_cache):
        # 通过时刻已经为该发车解析了随时间变化的运行条件；弧段能量也必须使用同一条运行轨迹。
        departure_trajectory = cache._trajectory_for_departure(depart_time_s)
        direction = cache.direction
        storage_hold_s = (
            _whole_departure_time(getattr(schedule_template, "flex_zone_hold_s", 0))
            if train_type == "Empty"
            else 0
        )
        storage_entry_elapsed_s = cache.first_storage_entry_elapsed_s(depart_time_s)

        def storage_hold_delay(base_time_s: float) -> float:
            """函数 storage_hold_delay：执行该模块中的相关处理逻辑。"""
            if (
                storage_hold_s <= 0
                or storage_entry_elapsed_s is None
                or base_time_s < depart_time_s + storage_entry_elapsed_s
            ):
                return 0.0
            return float(storage_hold_s)

        stations = _stations_in_direction(resource_model.stations, direction)
        physical_stations = sorted(resource_model.stations, key=lambda item: item.position_km)
        physical_index_by_key = {
            (station.name, float(station.position_km)): idx
            for idx, station in enumerate(physical_stations)
        }
        station_count = len(stations)
        path_node_ids: List[str] = []
        path_arc_ids: List[str] = []

        source_id = f"{train_id}:source"
        origin = stations[0]
        nodes.append(
            TimeSpaceNode(
                node_id=source_id,
                train_id=train_id,
                train_type=train_type,
                direction=direction,
                station_name="SOURCE",
                position_km=origin.position_km,
                time_s=float(depart_time_s),
                state="source",
            )
        )
        path_node_ids.append(source_id)
        previous_node_id = source_id
        previous_time_s = float(depart_time_s)
        previous_km = float(origin.position_km)
        previous_physical_idx = physical_index_by_key.get((origin.name, float(origin.position_km)), 0)
        cumulative_operation_delay_s = 0.0
        terminal_arrival_time_s: float | None = None

        for station_idx, station in enumerate(stations):
            physical_idx = physical_index_by_key.get((station.name, float(station.position_km)), station_idx)
            base_crossing = crossing_time_s(
                cache,
                float(station.position_km),
                depart_time_s,
            )
            if base_crossing is None:
                continue
            crossing = (
                float(base_crossing)
                + cumulative_operation_delay_s
                + storage_hold_delay(float(base_crossing))
            )
            if station_idx == station_count - 1:
                terminal_arrival_time_s = float(crossing)

            operation_plan = _operation_plan(
                resource_model,
                train_type,
                direction,
                station.name,
                station_idx,
                station_count,
            )
            operation_s = int(operation_plan.get("total_s") or 0) if operation_plan is not None else 0
            arrive_node_id = f"{train_id}:n{station_idx:03d}:arrive"
            nodes.append(
                TimeSpaceNode(
                    node_id=arrive_node_id,
                    train_id=train_id,
                    train_type=train_type,
                    direction=direction,
                    station_name=station.name,
                    position_km=float(station.position_km),
                    time_s=float(crossing),
                    state="arrive" if operation_s else "pass",
                )
            )
            path_node_ids.append(arrive_node_id)

            if station_idx == 0:
                arc_type = "origin_departure"
                energy_kwh = 0.0
                source = "template_departure"
                arc_id = f"{train_id}:a{len(path_arc_ids):03d}:{arc_type}"
                arcs.append(
                    TimeSpaceArc(
                        arc_id=arc_id,
                        train_id=train_id,
                        train_type=train_type,
                        direction=direction,
                        from_node_id=previous_node_id,
                        to_node_id=arrive_node_id,
                        arc_type=arc_type,
                        start_time_s=previous_time_s,
                        end_time_s=float(crossing),
                        start_km=previous_km,
                        end_km=float(station.position_km),
                        duration_s=max(0.0, float(crossing) - previous_time_s),
                        distance_km=abs(float(station.position_km) - previous_km),
                        energy_kwh=energy_kwh,
                        capacity_resource_id=f"station:{physical_idx}",
                        cost=energy_kwh,
                        source=source,
                    )
                )
                path_arc_ids.append(arc_id)
            else:
                segment_points = _storage_boundaries_between(
                    previous_km,
                    float(station.position_km),
                    selected_storage_sections,
                    direction,
                )
                segment_points.append(float(station.position_km))
                segment_from_node_id = previous_node_id
                segment_start_time_s = previous_time_s
                segment_start_km = previous_km
                section_index = min(previous_physical_idx, physical_idx)
                section_start_km = min(previous_km, float(station.position_km))
                section_end_km = max(previous_km, float(station.position_km))
                is_single_line = any(
                    min(section_end_km, float(end_km))
                    - max(section_start_km, float(start_km))
                    > 1e-9
                    for start_km, end_km in resource_model.config.single_line_ranges_km
                )
                direction_label = "shared" if is_single_line else direction
                capacity_resource_id = f"section:{section_index}:{direction_label}"

                for segment_idx, segment_end_km in enumerate(segment_points):
                    is_station_endpoint = segment_idx == len(segment_points) - 1
                    if is_station_endpoint:
                        segment_to_node_id = arrive_node_id
                        segment_end_time_s = float(crossing)
                    else:
                        boundary_crossing_s = crossing_time_s(cache, segment_end_km, depart_time_s)
                        if boundary_crossing_s is None:
                            continue
                        segment_end_time_s = (
                            float(boundary_crossing_s)
                            + cumulative_operation_delay_s
                            + storage_hold_delay(float(boundary_crossing_s))
                        )
                        segment_to_node_id = (
                            f"{train_id}:storage-boundary:{segment_end_km:g}:"
                            f"{len(path_node_ids):03d}"
                        )
                        nodes.append(
                            TimeSpaceNode(
                                node_id=segment_to_node_id,
                                train_id=train_id,
                                train_type=train_type,
                                direction=direction,
                                station_name=f"STORAGE_BOUNDARY_K{segment_end_km:g}",
                                position_km=segment_end_km,
                                time_s=segment_end_time_s,
                                state="storage_boundary",
                            )
                        )
                        path_node_ids.append(segment_to_node_id)

                    base_segment_start_s = crossing_time_s(
                        cache,
                        segment_start_km,
                        depart_time_s,
                    )
                    base_segment_end_s = crossing_time_s(
                        cache,
                        segment_end_km,
                        depart_time_s,
                    )
                    start_elapsed_s = max(
                        0.0,
                        float(base_segment_start_s) - depart_time_s
                        if base_segment_start_s is not None
                        else 0.0,
                    )
                    end_elapsed_s = max(
                        0.0,
                        float(base_segment_end_s) - depart_time_s
                        if base_segment_end_s is not None
                        else start_elapsed_s,
                    )
                    energy_key = (
                        id(departure_trajectory),
                        start_elapsed_s,
                        end_elapsed_s,
                    )
                    if energy_key not in arc_energy_cache:
                        arc_energy_cache[energy_key] = _arc_energy_between(
                            departure_trajectory,
                            start_elapsed_s,
                            end_elapsed_s,
                        )
                    energy_kwh = arc_energy_cache[energy_key]
                    storage_section_id = _storage_section_for_arc(
                        segment_start_km,
                        segment_end_km,
                        selected_storage_sections,
                        direction,
                    )
                    arc_id = f"{train_id}:a{len(path_arc_ids):03d}:running"
                    arcs.append(
                        TimeSpaceArc(
                            arc_id=arc_id,
                            train_id=train_id,
                            train_type=train_type,
                            direction=direction,
                            from_node_id=segment_from_node_id,
                            to_node_id=segment_to_node_id,
                            arc_type="running",
                            start_time_s=segment_start_time_s,
                            end_time_s=segment_end_time_s,
                            start_km=segment_start_km,
                            end_km=segment_end_km,
                            duration_s=max(0.0, segment_end_time_s - segment_start_time_s),
                            distance_km=abs(segment_end_km - segment_start_km),
                            energy_kwh=energy_kwh,
                            capacity_resource_id=capacity_resource_id,
                            cost=energy_kwh,
                            source="simulated_trajectory_storage_split",
                            storage_section_id=storage_section_id,
                        )
                    )
                    path_arc_ids.append(arc_id)
                    segment_from_node_id = segment_to_node_id
                    segment_start_time_s = segment_end_time_s
                    segment_start_km = segment_end_km

            previous_node_id = arrive_node_id
            previous_time_s = float(crossing)
            previous_km = float(station.position_km)
            previous_physical_idx = physical_idx

            if operation_plan is not None and operation_s > 0:
                for activity_idx, (activity_type, duration_s, activity_source) in enumerate(
                    _operation_activity_parts(operation_plan),
                    start=1,
                ):
                    activity_node_id = f"{train_id}:n{station_idx:03d}:{activity_idx:02d}:{activity_type}"
                    activity_end_s = previous_time_s + float(duration_s)
                    nodes.append(
                        TimeSpaceNode(
                            node_id=activity_node_id,
                            train_id=train_id,
                            train_type=train_type,
                            direction=direction,
                            station_name=station.name,
                            position_km=float(station.position_km),
                            time_s=activity_end_s,
                            state=activity_type,
                        )
                    )
                    path_node_ids.append(activity_node_id)
                    arc_id = f"{train_id}:a{len(path_arc_ids):03d}:{activity_type}"
                    arcs.append(
                        TimeSpaceArc(
                            arc_id=arc_id,
                            train_id=train_id,
                            train_type=train_type,
                            direction=direction,
                            from_node_id=previous_node_id,
                            to_node_id=activity_node_id,
                            arc_type=activity_type,
                            start_time_s=previous_time_s,
                            end_time_s=activity_end_s,
                            start_km=float(station.position_km),
                            end_km=float(station.position_km),
                            duration_s=float(duration_s),
                            distance_km=0.0,
                            energy_kwh=0.0,
                            capacity_resource_id=f"station:{physical_idx}",
                            cost=0.0,
                            source=activity_source,
                        )
                    )
                    path_arc_ids.append(arc_id)
                    previous_node_id = activity_node_id
                    previous_time_s = activity_end_s

                for post_idx, (activity_type, duration_s, activity_source) in enumerate(
                    _post_operation_virtual_parts(operation_plan, train_type),
                    start=1,
                ):
                    activity_node_id = f"{train_id}:n{station_idx:03d}:post{post_idx:02d}:{activity_type}"
                    activity_end_s = previous_time_s + float(duration_s)
                    nodes.append(
                        TimeSpaceNode(
                            node_id=activity_node_id,
                            train_id=train_id,
                            train_type=train_type,
                            direction=direction,
                            station_name=station.name,
                            position_km=float(station.position_km),
                            time_s=activity_end_s,
                            state=activity_type,
                        )
                    )
                    path_node_ids.append(activity_node_id)
                    arc_id = f"{train_id}:a{len(path_arc_ids):03d}:{activity_type}"
                    arcs.append(
                        TimeSpaceArc(
                            arc_id=arc_id,
                            train_id=train_id,
                            train_type=train_type,
                            direction=direction,
                            from_node_id=previous_node_id,
                            to_node_id=activity_node_id,
                            arc_type=activity_type,
                            start_time_s=previous_time_s,
                            end_time_s=activity_end_s,
                            start_km=float(station.position_km),
                            end_km=float(station.position_km),
                            duration_s=float(duration_s),
                            distance_km=0.0,
                            energy_kwh=0.0,
                            capacity_resource_id=f"station:{physical_idx}",
                            cost=0.0,
                            source=activity_source,
                        )
                    )
                    path_arc_ids.append(arc_id)
                    previous_node_id = activity_node_id
                    previous_time_s = activity_end_s

                cumulative_operation_delay_s += float(operation_s)

        sink_id = f"{train_id}:sink"
        nodes.append(
            TimeSpaceNode(
                node_id=sink_id,
                train_id=train_id,
                train_type=train_type,
                direction=direction,
                station_name="SINK",
                position_km=previous_km,
                time_s=previous_time_s,
                state="sink",
            )
        )
        path_node_ids.append(sink_id)
        arc_id = f"{train_id}:a{len(path_arc_ids):03d}:sink"
        arcs.append(
            TimeSpaceArc(
                arc_id=arc_id,
                train_id=train_id,
                train_type=train_type,
                direction=direction,
                from_node_id=previous_node_id,
                to_node_id=sink_id,
                arc_type="sink",
                start_time_s=previous_time_s,
                end_time_s=previous_time_s,
                start_km=previous_km,
                end_km=previous_km,
                duration_s=0.0,
                distance_km=0.0,
                energy_kwh=0.0,
                capacity_resource_id="sink",
                cost=0.0,
                source="network_sink",
            )
        )
        path_arc_ids.append(arc_id)
        paths.append(
            TimeSpaceTrainPath(
                train_id=train_id,
                train_type=train_type,
                direction=direction,
                depart_time_s=depart_time_s,
                arrival_time_s=(
                    previous_time_s
                    if terminal_arrival_time_s is None
                    else terminal_arrival_time_s
                ),
                completion_time_s=previous_time_s,
                node_ids=tuple(path_node_ids),
                arc_ids=tuple(path_arc_ids),
            )
        )

    return TimeSpaceNetwork(nodes=tuple(nodes), arcs=tuple(arcs), train_paths=tuple(paths))


def network_node_rows(network: TimeSpaceNetwork) -> List[Dict[str, object]]:
    """函数 network_node_rows：执行该模块中的相关处理逻辑。"""
    return [
        {
            "node_id": node.node_id,
            "train_id": node.train_id,
            "train_type": node.train_type,
            "direction": node.direction,
            "station_name": node.station_name,
            "position_km": round(node.position_km, 6),
            "time_s": round(node.time_s, 3),
            "time_min": round(node.time_s / 60.0, 3),
            "state": node.state,
        }
        for node in network.nodes
    ]


def network_arc_rows(network: TimeSpaceNetwork) -> List[Dict[str, object]]:
    """函数 network_arc_rows：执行该模块中的相关处理逻辑。"""
    return [
        {
            "arc_id": arc.arc_id,
            "train_id": arc.train_id,
            "train_type": arc.train_type,
            "direction": arc.direction,
            "from_node_id": arc.from_node_id,
            "to_node_id": arc.to_node_id,
            "arc_type": arc.arc_type,
            "start_time_s": round(arc.start_time_s, 3),
            "end_time_s": round(arc.end_time_s, 3),
            "duration_s": round(arc.duration_s, 3),
            "start_km": round(arc.start_km, 6),
            "end_km": round(arc.end_km, 6),
            "distance_km": round(arc.distance_km, 6),
            "energy_kwh": round(arc.energy_kwh, 6),
            "capacity_resource_id": arc.capacity_resource_id,
            "storage_section_id": arc.storage_section_id,
            "cost": round(arc.cost, 6),
            "source": arc.source,
        }
        for arc in network.arcs
    ]


def network_path_rows(network: TimeSpaceNetwork) -> List[Dict[str, object]]:
    """函数 network_path_rows：执行该模块中的相关处理逻辑。"""
    return [
        {
            "train_id": path.train_id,
            "train_type": path.train_type,
            "direction": path.direction,
            "depart_time_s": path.depart_time_s,
            "arrival_time_s": round(path.arrival_time_s, 3),
            "run_time_s": round(path.arrival_time_s - path.depart_time_s, 3),
            "completion_time_s": round(path.completion_time_s, 3),
            "completion_duration_s": round(path.completion_time_s - path.depart_time_s, 3),
            "node_count": len(path.node_ids),
            "arc_count": len(path.arc_ids),
            "node_ids": ";".join(path.node_ids),
            "arc_ids": ";".join(path.arc_ids),
        }
        for path in network.train_paths
    ]


def network_summary(network: TimeSpaceNetwork) -> Dict[str, object]:
    """函数 network_summary：执行该模块中的相关处理逻辑。"""
    return {
        "node_count": network.node_count,
        "arc_count": network.arc_count,
        "train_path_count": len(network.train_paths),
        "arc_type_counts": network.arc_type_counts(),
        "total_energy_kwh_by_arc_type": {
            arc_type: round(value, 6)
            for arc_type, value in network.total_energy_kwh_by_type().items()
        },
    }
