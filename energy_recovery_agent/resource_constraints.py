"""运行图的站场、区间、闭塞和追踪间隔约束检查；不负责能量计算。"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

from scheduler_nsga2 import PowerSeriesCache


def _whole_number(value: Any, field_name: str, *, minimum: int | None = None) -> int:
    """函数 _whole_number：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}") from exc
    if not math.isfinite(number) or not number.is_integer() or (
        minimum is not None and number < minimum
    ):
        constraint = f" greater than or equal to {minimum}" if minimum is not None else ""
        raise ValueError(
            f"{field_name} must be a finite whole number{constraint}, got {value!r}"
        )
    return int(number)


@dataclass(frozen=True)
class ResourceConfig:
    """Configurable virtual station/section resource model."""

    station_track_capacity: int = 2
    terminal_track_capacity: int = 4
    throat_capacity: int = 1
    station_occupancy_s: int = 180
    throat_occupancy_s: int = 90
    section_release_margin_s: int = 30
    section_capacity_spacing_km: float = 8.0
    single_line_ranges_km: Tuple[Tuple[float, float], ...] = ()
    min_depart_headway_s: int = 300
    min_depart_headway_source: str = ""
    min_overlap_s: int = 1
    conflict_limit: int = 50
    initial_heavy_flow_count: int = 1000
    initial_empty_flow_count: int = 1000
    enforce_flow_continuity: bool = True

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        positive_whole_fields = (
            "station_track_capacity",
            "terminal_track_capacity",
            "throat_capacity",
            "station_occupancy_s",
            "throat_occupancy_s",
            "conflict_limit",
        )
        non_negative_whole_fields = (
            "section_release_margin_s",
            "min_depart_headway_s",
            "min_overlap_s",
            "initial_heavy_flow_count",
            "initial_empty_flow_count",
        )
        for field_name in positive_whole_fields + non_negative_whole_fields:
            raw_value = getattr(self, field_name)
            if isinstance(raw_value, bool):
                raise ValueError(f"{field_name} must be a finite whole number, got {raw_value!r}")
            try:
                number = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field_name} must be a finite whole number, got {raw_value!r}") from exc
            minimum = 1.0 if field_name in positive_whole_fields else 0.0
            if not math.isfinite(number) or not number.is_integer() or number < minimum:
                qualifier = "positive" if minimum > 0.0 else "non-negative"
                raise ValueError(
                    f"{field_name} must be a finite {qualifier} whole number, got {raw_value!r}"
                )
            object.__setattr__(self, field_name, int(number))

        if isinstance(self.section_capacity_spacing_km, bool):
            raise ValueError(
                "section_capacity_spacing_km must be a finite positive number, "
                f"got {self.section_capacity_spacing_km!r}"
            )
        try:
            spacing = float(self.section_capacity_spacing_km)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "section_capacity_spacing_km must be a finite positive number, "
                f"got {self.section_capacity_spacing_km!r}"
            ) from exc
        if not math.isfinite(spacing) or spacing <= 0.0:
            raise ValueError(
                "section_capacity_spacing_km must be a finite positive number, "
                f"got {self.section_capacity_spacing_km!r}"
            )
        object.__setattr__(self, "section_capacity_spacing_km", spacing)

        normalized_ranges = []
        for raw_range in self.single_line_ranges_km:
            try:
                start_km, end_km = raw_range
                if isinstance(start_km, bool) or isinstance(end_km, bool):
                    raise ValueError
                start_km = float(start_km)
                end_km = float(end_km)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"single_line_ranges_km contains an invalid range: {raw_range!r}") from exc
            if (
                not math.isfinite(start_km)
                or not math.isfinite(end_km)
                or start_km < 0.0
                or end_km < 0.0
                or start_km == end_km
            ):
                raise ValueError(f"single_line_ranges_km contains an invalid range: {raw_range!r}")
            normalized_ranges.append((min(start_km, end_km), max(start_km, end_km)))
        if type(self.enforce_flow_continuity) is not bool:
            raise ValueError("enforce_flow_continuity must be a boolean")
        object.__setattr__(self, "single_line_ranges_km", tuple(normalized_ranges))


@dataclass(frozen=True)
class ResourceUnavailability:
    """资源在绝对时间窗内不可用；与列车占用相交即形成阻断冲突。"""

    event_id: str
    resource_id: str
    resource_type: str
    start_time_s: int
    end_time_s: int
    reason: str = ""

    def __post_init__(self) -> None:
        event_id = str(self.event_id).strip()
        resource_id = str(self.resource_id).strip()
        resource_type = str(self.resource_type).strip()
        if not event_id or not resource_id:
            raise ValueError("资源封锁的event_id和resource_id不能为空。")
        if resource_type not in {"signaling_block", "segment", "section", "station_track", "throat", "station_throat"}:
            raise ValueError(f"未知资源封锁类型：{resource_type!r}")
        start_s = _whole_number(self.start_time_s, "start_time_s", minimum=0)
        end_s = _whole_number(self.end_time_s, "end_time_s", minimum=0)
        if end_s <= start_s:
            raise ValueError("资源封锁时间窗必须非空。")
        aliases = {"segment": "section", "signaling_block": "section", "throat": "station_throat"}
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "resource_type", aliases.get(resource_type, resource_type))
        object.__setattr__(self, "start_time_s", start_s)
        object.__setattr__(self, "end_time_s", end_s)


@dataclass(frozen=True)
class ResourceModel:
    """Derived resources for a route."""

    stations: Tuple[Any, ...]
    config: ResourceConfig
    station_track_capacities: Dict[str, int] = field(default_factory=dict)
    station_throat_capacities: Dict[str, int] = field(default_factory=dict)
    station_occupancy_s: Dict[str, int] = field(default_factory=dict)
    station_occupancy_sources: Dict[str, str] = field(default_factory=dict)
    station_operation_min_times_s: Dict[str, int] = field(default_factory=dict)
    station_operation_sources: Dict[str, str] = field(default_factory=dict)
    station_operation_details: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    station_operation_assignments: Tuple[Dict[str, Any], ...] = ()
    unavailabilities: Tuple[ResourceUnavailability, ...] = ()

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        stations = tuple(self.stations)
        station_names = {str(getattr(station, "name", "")) for station in stations}
        object.__setattr__(self, "stations", stations)
        object.__setattr__(self, "unavailabilities", tuple(self.unavailabilities))

        for field_name in ("station_track_capacities", "station_throat_capacities"):
            raw_map = getattr(self, field_name)
            normalized = {
                str(key): _whole_number(value, f"{field_name}[{key!r}]", minimum=1)
                for key, value in raw_map.items()
            }
            object.__setattr__(self, field_name, normalized)

        for field_name in ("station_occupancy_s", "station_operation_min_times_s"):
            raw_map = getattr(self, field_name)
            normalized = {
                str(key): _whole_number(value, f"{field_name}[{key!r}]", minimum=1)
                for key, value in raw_map.items()
            }
            object.__setattr__(self, field_name, normalized)

        object.__setattr__(
            self,
            "station_occupancy_sources",
            {str(key): str(value) for key, value in self.station_occupancy_sources.items()},
        )
        object.__setattr__(
            self,
            "station_operation_sources",
            {str(key): str(value) for key, value in self.station_operation_sources.items()},
        )

        normalized_details: Dict[str, Dict[str, Any]] = {}
        duration_fields = ("spotting_s", "loading_unloading_s", "pickup_s", "total_s")
        for key, raw_detail in self.station_operation_details.items():
            detail = dict(raw_detail)
            for duration_field in duration_fields:
                if duration_field in detail:
                    detail[duration_field] = _whole_number(
                        detail[duration_field],
                        f"station_operation_details[{key!r}].{duration_field}",
                        minimum=0,
                    )
            normalized_details[str(key)] = detail
        object.__setattr__(self, "station_operation_details", normalized_details)

        allowed_train_types = {"", "Heavy", "Empty"}
        allowed_directions = {"", "forward", "reverse"}
        allowed_applies_to = {"all", "any", "origin", "start", "destination", "terminal", "end"}
        normalized_assignments = []
        for index, raw_assignment in enumerate(self.station_operation_assignments):
            assignment = dict(raw_assignment)
            station_name = str(assignment.get("station_name") or "")
            train_type = str(assignment.get("train_type") or "").strip()
            direction = str(assignment.get("direction") or "").strip()
            applies_to = str(assignment.get("applies_to") or "all").strip().lower()
            if not station_name or station_name not in station_names:
                raise ValueError(
                    f"station_operation_assignments[{index}].station_name is unknown: {station_name!r}"
                )
            if train_type not in allowed_train_types:
                raise ValueError(
                    f"station_operation_assignments[{index}].train_type is invalid: {train_type!r}"
                )
            if direction not in allowed_directions:
                raise ValueError(
                    f"station_operation_assignments[{index}].direction is invalid: {direction!r}"
                )
            if applies_to not in allowed_applies_to:
                raise ValueError(
                    f"station_operation_assignments[{index}].applies_to is invalid: {applies_to!r}"
                )
            assignment["station_name"] = station_name
            assignment["train_type"] = train_type
            assignment["direction"] = direction
            assignment["applies_to"] = applies_to
            assignment["min_occupancy_s"] = _whole_number(
                assignment.get("min_occupancy_s", 0),
                f"station_operation_assignments[{index}].min_occupancy_s",
                minimum=0,
            )
            normalized_assignments.append(assignment)
        object.__setattr__(self, "station_operation_assignments", tuple(normalized_assignments))


@dataclass(frozen=True)
class TrainRun:
    """类 TrainRun：执行该模块中的相关处理逻辑。"""
    train_id: str
    train_type: str
    direction: str
    depart_time_s: int
    cache: PowerSeriesCache
    storage_hold_s: int = 0


@dataclass(frozen=True)
class ResourceInterval:
    """类 ResourceInterval：执行该模块中的相关处理逻辑。"""
    resource_id: str
    resource_name: str
    resource_type: str
    capacity: int
    train_id: str
    train_type: str
    direction: str
    start_time_s: float
    end_time_s: float
    start_km: float
    end_km: float
    detail: str


@dataclass(frozen=True)
class ConflictExplanation:
    """类 ConflictExplanation：执行该模块中的相关处理逻辑。"""
    conflict_type: str
    severity: str
    resource_id: str
    resource_name: str
    train_a: str
    train_b: str
    train_a_type: str
    train_b_type: str
    overlap_start_s: float
    overlap_end_s: float
    overlap_duration_s: float
    location_km: str
    message: str
    suggestion: str


@dataclass(frozen=True)
class ResourceCheckResult:
    """类 ResourceCheckResult：执行该模块中的相关处理逻辑。"""
    feasible: bool
    conflicts: List[ConflictExplanation]
    intervals: List[ResourceInterval]
    overlap_violation_s: float = 0.0
    flow_continuity_feasible: bool = True
    flow_continuity_violations: List[Dict[str, object]] = field(default_factory=list)
    flow_continuity_events: List[Dict[str, object]] = field(default_factory=list)

    @property
    def conflict_count(self) -> int:
        """函数 conflict_count：执行该模块中的相关处理逻辑。"""
        return len(self.conflicts)


def build_default_resource_model(route, config: Optional[ResourceConfig] = None) -> ResourceModel:
    """Build a station/section resource model from current virtual route stations."""

    stations = tuple(sorted(route.stations, key=lambda station: station.position_km))
    return ResourceModel(stations=stations, config=config or ResourceConfig())


def _capacity_from_map(capacity_map: Dict[str, int], station: Any) -> Optional[int]:
    """函数 _capacity_from_map：执行该模块中的相关处理逻辑。"""
    for key in (getattr(station, "name", ""), str(getattr(station, "position_km", ""))):
        if key in capacity_map:
            return capacity_map[key]
    return None


def _station_track_capacity(model: ResourceModel, station_idx: int, station: Any) -> int:
    """函数 _station_track_capacity：执行该模块中的相关处理逻辑。"""
    station_capacity = _capacity_from_map(model.station_track_capacities, station)
    if station_capacity is not None:
        return station_capacity
    is_terminal = station_idx == 0 or station_idx == len(model.stations) - 1
    return model.config.terminal_track_capacity if is_terminal else model.config.station_track_capacity


def _station_throat_capacity(model: ResourceModel, station: Any) -> int:
    """函数 _station_throat_capacity：执行该模块中的相关处理逻辑。"""
    station_capacity = _capacity_from_map(model.station_throat_capacities, station)
    if station_capacity is not None:
        return station_capacity
    return model.config.throat_capacity


def _station_occupancy_s(model: ResourceModel, station: Any) -> int:
    """函数 _station_occupancy_s：执行该模块中的相关处理逻辑。"""
    for key in (getattr(station, "name", ""), str(getattr(station, "position_km", ""))):
        if key in model.station_occupancy_s:
            return model.station_occupancy_s[key]
    return model.config.station_occupancy_s


def _is_origin_station(run: TrainRun, station_idx: int, station_count: int) -> bool:
    """函数 _is_origin_station：执行该模块中的相关处理逻辑。"""
    if run.direction == "reverse":
        return station_idx == station_count - 1
    return station_idx == 0


def _is_destination_station(run: TrainRun, station_idx: int, station_count: int) -> bool:
    """函数 _is_destination_station：执行该模块中的相关处理逻辑。"""
    if run.direction == "reverse":
        return station_idx == 0
    return station_idx == station_count - 1


def _assignment_applies_to_station(
    assignment: Dict[str, Any],
    run: TrainRun,
    station_name: str,
    station_idx: int,
    station_count: int,
) -> bool:
    """函数 _assignment_applies_to_station：执行该模块中的相关处理逻辑。"""
    if assignment.get("station_name") != station_name:
        return False
    train_type = str(assignment.get("train_type") or "").strip()
    if train_type and train_type != run.train_type:
        return False
    direction = str(assignment.get("direction") or "").strip()
    if direction and direction != run.direction:
        return False

    applies_to = str(assignment.get("applies_to") or "all").strip().lower()
    if applies_to in {"all", "any"}:
        return True
    if applies_to in {"origin", "start"}:
        return _is_origin_station(run, station_idx, station_count)
    if applies_to in {"destination", "terminal", "end"}:
        return _is_destination_station(run, station_idx, station_count)
    return False


def _station_operation_interval(
    model: ResourceModel,
    run: TrainRun,
    station: Any,
    station_idx: int,
    station_count: int,
    time_s: float,
) -> Optional[Tuple[float, float, str]]:
    """函数 _station_operation_interval：执行该模块中的相关处理逻辑。"""
    station_name = getattr(station, "name", "")
    for assignment in model.station_operation_assignments:
        if not _assignment_applies_to_station(assignment, run, station_name, station_idx, station_count):
            continue
        operation_s = int(assignment.get("min_occupancy_s") or 0)
        if operation_s <= 0:
            operation_s = int(model.station_operation_min_times_s.get(station_name, 0))
        if operation_s <= 0:
            continue

        applies_to = str(assignment.get("applies_to") or "all").strip().lower()
        source = str(assignment.get("source") or model.station_operation_sources.get(station_name, "technical operation"))
        if applies_to in {"origin", "start"}:
            return max(0.0, time_s - operation_s), time_s, source
        if applies_to in {"destination", "terminal", "end"}:
            return time_s, time_s + operation_s, source
        return time_s, time_s + operation_s, source
    return None


def _in_range(position_km: float, start_km: float, end_km: float) -> bool:
    """函数 _in_range：执行该模块中的相关处理逻辑。"""
    lo = min(start_km, end_km)
    hi = max(start_km, end_km)
    return lo <= position_km <= hi


def _section_is_single_line(config: ResourceConfig, start_km: float, end_km: float) -> bool:
    """函数 _section_is_single_line：执行该模块中的相关处理逻辑。"""
    section_start_km = min(start_km, end_km)
    section_end_km = max(start_km, end_km)
    for range_start_km, range_end_km in config.single_line_ranges_km:
        overlap_start_km = max(section_start_km, range_start_km)
        overlap_end_km = min(section_end_km, range_end_km)
        # 若站间资源有任意正长度部分落在配置的单线范围内，则视为共享资源。
        # 仅在车站边界处相接，不会使该区段成为单线区段。
        if overlap_end_km - overlap_start_km > 1e-9:
            return True
    return False


def _section_capacity(config: ResourceConfig, start_km: float, end_km: float) -> int:
    """函数 _section_capacity：执行该模块中的相关处理逻辑。"""
    if _section_is_single_line(config, start_km, end_km):
        return 1
    length_km = abs(end_km - start_km)
    spacing = config.section_capacity_spacing_km
    return max(1, int(math.ceil(length_km / spacing)))


def _trajectory_for_departure(cache: PowerSeriesCache, depart_time_s: int) -> PowerSeriesCache:
    """函数 _trajectory_for_departure：执行该模块中的相关处理逻辑。"""
    return cache._trajectory_for_departure(_whole_number(depart_time_s, "depart_time_s"))


def crossing_elapsed_time_s(
    cache: PowerSeriesCache,
    target_km: float,
    depart_time_s: int,
) -> Optional[float]:
    """Return elapsed time when the train head crosses a route mileage."""

    depart_s = _whole_number(depart_time_s, "depart_time_s")
    cache_departure_s = depart_s if cache.time_dependent_conditions else cache.start_time_s
    cache_key = (cache_departure_s, float(target_km))
    elapsed_cache = cache._crossing_elapsed_cache
    if cache_key in elapsed_cache:
        cached = elapsed_cache[cache_key]
        return None if cached is None else float(cached)

    trajectory = _trajectory_for_departure(cache, depart_s)
    if not trajectory.positions_km:
        elapsed_cache[cache_key] = None
        return None

    positions = trajectory.positions_km
    times = trajectory.times
    direction = trajectory.direction
    tolerance_km = 0.05

    if direction == "forward":
        if target_km <= positions[0] + tolerance_km:
            result = float(times[0])
            elapsed_cache[cache_key] = result
            return result
        if target_km >= positions[-1] - tolerance_km:
            result = float(times[-1])
            elapsed_cache[cache_key] = result
            return result
        for idx in range(1, len(positions)):
            prev_pos = positions[idx - 1]
            cur_pos = positions[idx]
            if prev_pos <= target_km <= cur_pos:
                span = max(1e-9, cur_pos - prev_pos)
                ratio = (target_km - prev_pos) / span
                result = times[idx - 1] + ratio * (times[idx] - times[idx - 1])
                elapsed_cache[cache_key] = result
                return result
    else:
        if target_km >= positions[0] - tolerance_km:
            result = float(times[0])
            elapsed_cache[cache_key] = result
            return result
        if target_km <= positions[-1] + tolerance_km:
            result = float(times[-1])
            elapsed_cache[cache_key] = result
            return result
        for idx in range(1, len(positions)):
            prev_pos = positions[idx - 1]
            cur_pos = positions[idx]
            if prev_pos >= target_km >= cur_pos:
                span = max(1e-9, prev_pos - cur_pos)
                ratio = (prev_pos - target_km) / span
                result = times[idx - 1] + ratio * (times[idx] - times[idx - 1])
                elapsed_cache[cache_key] = result
                return result
    elapsed_cache[cache_key] = None
    return None


def crossing_time_s(cache: PowerSeriesCache, target_km: float, depart_time_s: int) -> Optional[float]:
    """函数 crossing_time_s：执行该模块中的相关处理逻辑。"""
    elapsed = crossing_elapsed_time_s(cache, target_km, depart_time_s)
    if elapsed is None:
        return None
    return depart_time_s + elapsed


def post_departure_operation_delay_events(
    cache: PowerSeriesCache,
    depart_time_s: int,
    train_type: str,
    model: ResourceModel,
) -> Tuple[Tuple[float, int], ...]:
    """Return trajectory-elapsed thresholds and downstream operation delays."""

    depart_s = _whole_number(depart_time_s, "depart_time_s", minimum=0)
    run = TrainRun(
        train_id="energy_timeline",
        train_type=str(train_type),
        direction=cache.direction,
        depart_time_s=depart_s,
        cache=cache,
    )
    stations = tuple(getattr(model, "stations", ()))
    station_count = len(stations)
    events: Dict[float, int] = {}
    for station_idx, station in enumerate(stations):
        elapsed_s = crossing_elapsed_time_s(cache, float(station.position_km), depart_s)
        if elapsed_s is None:
            continue
        operation_interval = _station_operation_interval(
            model,
            run,
            station,
            station_idx,
            station_count,
            0.0,
        )
        if operation_interval is None:
            continue
        # 起点/始发分配在发车时结束，因此不会增加发车后的延误；其他分配会使后续所有样本延后。
        delay_s = max(0, int(round(operation_interval[1])))
        if delay_s > 0:
            threshold = float(elapsed_s)
            events[threshold] = events.get(threshold, 0) + delay_s
    return tuple(sorted(events.items()))


def _run_station_timings(
    run: TrainRun,
    model: ResourceModel,
) -> Dict[int, Tuple[float, float]]:
    """Return arrival and post-operation release times in running order."""

    stations = list(model.stations)
    station_indices = (
        range(len(stations) - 1, -1, -1)
        if run.direction == "reverse"
        else range(len(stations))
    )
    cumulative_operation_delay_s = 0.0
    storage_entry_elapsed_s = run.cache.first_storage_entry_elapsed_s(run.depart_time_s)
    timings: Dict[int, Tuple[float, float]] = {}
    for station_idx in station_indices:
        station = stations[station_idx]
        base_time_s = crossing_time_s(
            run.cache,
            station.position_km,
            run.depart_time_s,
        )
        if base_time_s is None:
            continue
        storage_hold_delay_s = (
            run.storage_hold_s
            if storage_entry_elapsed_s is not None
            and base_time_s >= run.depart_time_s + storage_entry_elapsed_s
            else 0
        )
        arrival_time_s = (
            base_time_s + cumulative_operation_delay_s + storage_hold_delay_s
        )
        operation_interval = _station_operation_interval(
            model,
            run,
            station,
            station_idx,
            len(stations),
            arrival_time_s,
        )
        release_time_s = (
            arrival_time_s
            if operation_interval is None
            else max(arrival_time_s, operation_interval[1])
        )
        timings[station_idx] = (arrival_time_s, release_time_s)
        cumulative_operation_delay_s += release_time_s - arrival_time_s
    return timings


def _timing_cache_key(run: TrainRun) -> Tuple[object, ...]:
    """构造一次资源检查内可复用的列车站点时刻键。"""

    return (
        run.train_id,
        run.train_type,
        run.direction,
        run.depart_time_s,
        run.storage_hold_s,
        id(run.cache),
    )


def _station_timings_for_run(
    run: TrainRun,
    model: ResourceModel,
    timing_cache: Optional[Dict[Tuple[object, ...], Dict[int, Tuple[float, float]]]],
) -> Dict[int, Tuple[float, float]]:
    """读取或计算列车站点时刻，避免同一次资源检查重复扫轨迹。"""

    if timing_cache is None:
        return _run_station_timings(run, model)
    key = _timing_cache_key(run)
    cached = timing_cache.get(key)
    if cached is None:
        cached = _run_station_timings(run, model)
        timing_cache[key] = cached
    return cached


def _train_runs(schedule, heavy_cache: PowerSeriesCache, empty_cache: PowerSeriesCache) -> List[TrainRun]:
    """函数 _train_runs：执行该模块中的相关处理逻辑。"""
    runs: List[TrainRun] = []
    schedule_template = getattr(schedule, "template", None)
    empty_storage_hold_s = _whole_number(
        getattr(schedule_template, "flex_zone_hold_s", 0),
        "template.flex_zone_hold_s",
        minimum=0,
    )
    heavy_rows = zip(schedule.heavy_departures_s, getattr(schedule, "heavy_train_ids", ()))
    if not getattr(schedule, "heavy_train_ids", ()):
        heavy_rows = ((time_s, f"H{idx:03d}") for idx, time_s in enumerate(sorted(schedule.heavy_departures_s), start=1))
    for depart_time_s, train_id in heavy_rows:
        runs.append(
            TrainRun(
                train_id=train_id,
                train_type="Heavy",
                direction=heavy_cache.direction,
                depart_time_s=_whole_number(depart_time_s, "departure time", minimum=0),
                cache=heavy_cache,
                storage_hold_s=0,
            )
        )
    empty_rows = zip(schedule.empty_departures_s, getattr(schedule, "empty_train_ids", ()))
    if not getattr(schedule, "empty_train_ids", ()):
        empty_rows = ((time_s, f"E{idx:03d}") for idx, time_s in enumerate(sorted(schedule.empty_departures_s), start=1))
    for depart_time_s, train_id in empty_rows:
        runs.append(
            TrainRun(
                train_id=train_id,
                train_type="Empty",
                direction=empty_cache.direction,
                depart_time_s=_whole_number(depart_time_s, "departure time", minimum=0),
                cache=empty_cache,
                storage_hold_s=empty_storage_hold_s,
            )
        )
    return runs


def _tail_clearance_s(train_length_km: float, section_length_km: float, head_travel_s: float) -> float:
    """函数 _tail_clearance_s：执行该模块中的相关处理逻辑。"""
    if section_length_km <= 0.0 or head_travel_s <= 0.0:
        return 0.0
    average_speed_km_s = section_length_km / head_travel_s
    return train_length_km / max(1e-6, average_speed_km_s)


def build_resource_intervals(
    schedule,
    model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    interval_cache: Optional[
        Dict[Tuple[int, int, str, str, str, int, int], Tuple[ResourceInterval, ...]]
    ] = None,
    timing_cache: Optional[Dict[Tuple[object, ...], Dict[int, Tuple[float, float]]]] = None,
) -> List[ResourceInterval]:
    """展开运行图资源区间，并可在一次求解内复用未变化列车的区间。"""

    intervals: List[ResourceInterval] = []
    stations = list(model.stations)
    config = model.config

    for run in _train_runs(schedule, heavy_cache, empty_cache):
        cache_key = (
            id(model),
            id(run.cache),
            run.train_id,
            run.train_type,
            run.direction,
            run.depart_time_s,
            run.storage_hold_s,
        )
        if interval_cache is not None:
            cached = interval_cache.get(cache_key)
            if cached is not None:
                intervals.extend(cached)
                continue
        train_interval_start = len(intervals)
        station_timings = _station_timings_for_run(run, model, timing_cache)
        for station_idx, station in enumerate(stations):
            timing = station_timings.get(station_idx)
            if timing is None:
                continue
            time_s, release_time_s = timing

            track_capacity = _station_track_capacity(model, station_idx, station)
            throat_capacity = _station_throat_capacity(model, station)
            operation_interval = _station_operation_interval(
                model,
                run,
                station,
                station_idx,
                len(stations),
                time_s,
            )
            if operation_interval is None:
                half_station_s = _station_occupancy_s(model, station) / 2.0
                station_start_s = max(0.0, time_s - half_station_s)
                station_end_s = time_s + half_station_s
                station_detail = f"{run.train_id} occupies station track at {station.name}"
            else:
                station_start_s, station_end_s, operation_source = operation_interval
                station_detail = (
                    f"{run.train_id} occupies station track at {station.name} "
                    f"for technical operation ({operation_source})"
                )
            half_throat_s = config.throat_occupancy_s / 2.0
            intervals.append(
                ResourceInterval(
                    resource_id=f"station:{station_idx}",
                    resource_name=station.name,
                    resource_type="station_track",
                    capacity=track_capacity,
                    train_id=run.train_id,
                    train_type=run.train_type,
                    direction=run.direction,
                    start_time_s=station_start_s,
                    end_time_s=station_end_s,
                    start_km=station.position_km,
                    end_km=station.position_km,
                    detail=station_detail,
                )
            )

            intervals.append(
                ResourceInterval(
                    resource_id=f"throat:{station_idx}",
                    resource_name=f"{station.name} throat",
                    resource_type="station_throat",
                    capacity=throat_capacity,
                    train_id=run.train_id,
                    train_type=run.train_type,
                    direction=run.direction,
                    start_time_s=max(0.0, time_s - half_throat_s),
                    end_time_s=time_s + half_throat_s,
                    start_km=station.position_km,
                    end_km=station.position_km,
                    detail=f"{run.train_id} locks throat route at {station.name}",
                )
            )

        for section_idx in range(len(stations) - 1):
            left_station = stations[section_idx]
            right_station = stations[section_idx + 1]
            left_timing = station_timings.get(section_idx)
            right_timing = station_timings.get(section_idx + 1)
            if left_timing is None or right_timing is None:
                continue
            left_time, left_release_time = left_timing
            right_time, right_release_time = right_timing

            if run.direction == "forward":
                enter_time_s = left_release_time
                head_exit_time_s = right_time
            else:
                enter_time_s = right_release_time
                head_exit_time_s = left_time
            if head_exit_time_s <= enter_time_s:
                continue

            section_length_km = abs(right_station.position_km - left_station.position_km)
            base_left_time_s = crossing_time_s(
                run.cache,
                left_station.position_km,
                run.depart_time_s,
            )
            base_right_time_s = crossing_time_s(
                run.cache,
                right_station.position_km,
                run.depart_time_s,
            )
            base_head_travel_s = (
                abs(base_right_time_s - base_left_time_s)
                if base_left_time_s is not None and base_right_time_s is not None
                else head_exit_time_s - enter_time_s
            )
            tail_clear_s = _tail_clearance_s(
                run.cache.train_length_km,
                section_length_km,
                base_head_travel_s,
            )
            single_line = _section_is_single_line(
                config,
                left_station.position_km,
                right_station.position_km,
            )
            direction_label = "shared" if single_line else run.direction
            intervals.append(
                ResourceInterval(
                    resource_id=f"section:{section_idx}:{direction_label}",
                    resource_name=f"{left_station.name} - {right_station.name}",
                    resource_type="section",
                    capacity=_section_capacity(config, left_station.position_km, right_station.position_km),
                    train_id=run.train_id,
                    train_type=run.train_type,
                    direction=run.direction,
                    start_time_s=enter_time_s,
                    end_time_s=head_exit_time_s + tail_clear_s + config.section_release_margin_s,
                    start_km=left_station.position_km,
                    end_km=right_station.position_km,
                    detail=f"{run.train_id} occupies section {left_station.name} - {right_station.name}",
                )
            )

        if interval_cache is not None:
            interval_cache[cache_key] = tuple(intervals[train_interval_start:])

    # 在构造时先规范化起止颠倒的占用窗口，使后续冲突检测获得有序区间，
    # 同时通过规范化副本的详细标记保留原始异常。
    normalized = [_normalize_resource_interval(interval) for interval in intervals]
    return sorted(normalized, key=lambda item: (item.start_time_s, item.resource_id, item.train_id))


def _nearest_resource_station_index(model: ResourceModel, station_name: str, station_km: float) -> Optional[int]:
    """函数 _nearest_resource_station_index：执行该模块中的相关处理逻辑。"""
    for idx, station in enumerate(model.stations):
        if str(getattr(station, "name", "")) == str(station_name):
            return idx
    if not model.stations:
        return None
    nearest_idx = min(
        range(len(model.stations)),
        key=lambda idx: abs(float(getattr(model.stations[idx], "position_km", 0.0)) - float(station_km)),
    )
    nearest_km = float(getattr(model.stations[nearest_idx], "position_km", 0.0))
    return nearest_idx if abs(nearest_km - float(station_km)) <= 0.1 else None


def _timetable_train_length_km(train: Any) -> float:
    """函数 _timetable_train_length_km：执行该模块中的相关处理逻辑。"""
    wagon_count = getattr(train, "wagon_count", None)
    if wagon_count is not None and int(wagon_count) > 0:
        return max(0.1, int(wagon_count) * 0.0121 + 0.05)
    return 2.7 if str(getattr(train, "train_type", "")).lower() in {"empty", "light"} else 2.6


def build_timetable_resource_intervals(timetable: Any, model: ResourceModel) -> List[ResourceInterval]:
    """Expand exact timetable stop times into station, throat and section occupancy."""

    trains = {str(train.train_id): train for train in timetable.trains}
    stops_by_train: Dict[str, List[Any]] = {}
    for stop in timetable.stops:
        stops_by_train.setdefault(str(stop.train_id), []).append(stop)
    intervals: List[ResourceInterval] = []
    config = model.config

    for train_id, raw_stops in stops_by_train.items():
        train = trains.get(train_id)
        if train is None:
            continue
        train_type = str(getattr(train, "train_type", ""))
        direction = str(getattr(train, "direction", ""))
        stops = sorted(raw_stops, key=lambda item: int(item.seq))
        crossings: Dict[int, Tuple[float, float]] = {}

        for stop in stops:
            station_idx = _nearest_resource_station_index(model, stop.station_name, stop.station_km)
            if station_idx is not None:
                crossings[station_idx] = (float(stop.arrival_time_s), float(stop.departure_time_s))

        for left_stop, right_stop in zip(stops[:-1], stops[1:]):
            start_km = float(left_stop.station_km)
            end_km = float(right_stop.station_km)
            distance_km = abs(end_km - start_km)
            run_start_s = float(left_stop.departure_time_s)
            run_end_s = float(right_stop.arrival_time_s)
            if distance_km <= 0.0 or run_end_s <= run_start_s:
                continue
            low_km, high_km = sorted((start_km, end_km))
            for station_idx, station in enumerate(model.stations):
                station_km = float(getattr(station, "position_km", 0.0))
                if not (low_km < station_km < high_km) or station_idx in crossings:
                    continue
                ratio = abs(station_km - start_km) / distance_km
                crossing_s = run_start_s + ratio * (run_end_s - run_start_s)
                crossings[station_idx] = (crossing_s, crossing_s)

        for station_idx, (arrival_s, departure_s) in sorted(crossings.items()):
            station = model.stations[station_idx]
            station_km = float(getattr(station, "position_km", 0.0))
            station_name = str(getattr(station, "name", station_idx))
            if departure_s > arrival_s:
                station_start_s, station_end_s = arrival_s, departure_s
            else:
                half_station_s = _station_occupancy_s(model, station) / 2.0
                station_start_s = max(0.0, arrival_s - half_station_s)
                station_end_s = arrival_s + half_station_s
            intervals.append(
                ResourceInterval(
                    resource_id=f"station:{station_idx}",
                    resource_name=station_name,
                    resource_type="station_track",
                    capacity=_station_track_capacity(model, station_idx, station),
                    train_id=train_id,
                    train_type=train_type,
                    direction=direction,
                    start_time_s=station_start_s,
                    end_time_s=station_end_s,
                    start_km=station_km,
                    end_km=station_km,
                    detail=f"{train_id} occupies station track from canonical timetable times",
                )
            )
            half_throat_s = config.throat_occupancy_s / 2.0
            throat_windows: List[Tuple[float, float]] = []
            for event_s in sorted({arrival_s, departure_s}):
                window = (max(0.0, event_s - half_throat_s), event_s + half_throat_s)
                if throat_windows and window[0] <= throat_windows[-1][1]:
                    throat_windows[-1] = (throat_windows[-1][0], max(throat_windows[-1][1], window[1]))
                else:
                    throat_windows.append(window)
            for throat_start_s, throat_end_s in throat_windows:
                intervals.append(
                    ResourceInterval(
                        resource_id=f"throat:{station_idx}",
                        resource_name=f"{station_name} throat",
                        resource_type="station_throat",
                        capacity=_station_throat_capacity(model, station),
                        train_id=train_id,
                        train_type=train_type,
                        direction=direction,
                        start_time_s=throat_start_s,
                        end_time_s=throat_end_s,
                        start_km=station_km,
                        end_km=station_km,
                        detail=f"{train_id} locks station throat from canonical timetable times",
                    )
                )

        train_length_km = _timetable_train_length_km(train)
        for section_idx in range(len(model.stations) - 1):
            if section_idx not in crossings or section_idx + 1 not in crossings:
                continue
            left_station = model.stations[section_idx]
            right_station = model.stations[section_idx + 1]
            left_arrival_s, left_departure_s = crossings[section_idx]
            right_arrival_s, right_departure_s = crossings[section_idx + 1]
            if direction == "reverse":
                enter_time_s, head_exit_time_s = right_departure_s, left_arrival_s
            else:
                enter_time_s, head_exit_time_s = left_departure_s, right_arrival_s
            if head_exit_time_s <= enter_time_s:
                continue
            left_km = float(getattr(left_station, "position_km", 0.0))
            right_km = float(getattr(right_station, "position_km", 0.0))
            section_length_km = abs(right_km - left_km)
            tail_clear_s = _tail_clearance_s(train_length_km, section_length_km, head_exit_time_s - enter_time_s)
            single_line = _section_is_single_line(config, left_km, right_km)
            direction_label = "shared" if single_line else direction
            intervals.append(
                ResourceInterval(
                    resource_id=f"section:{section_idx}:{direction_label}",
                    resource_name=f"{getattr(left_station, 'name', section_idx)} - {getattr(right_station, 'name', section_idx + 1)}",
                    resource_type="section",
                    capacity=_section_capacity(config, left_km, right_km),
                    train_id=train_id,
                    train_type=train_type,
                    direction=direction,
                    start_time_s=enter_time_s,
                    end_time_s=head_exit_time_s + tail_clear_s + config.section_release_margin_s,
                    start_km=left_km,
                    end_km=right_km,
                    detail=f"{train_id} occupies section from canonical timetable times",
                )
            )

    return sorted(intervals, key=lambda item: (item.start_time_s, item.resource_id, item.train_id))


def check_timetable_resources(timetable: Any, model: ResourceModel) -> ResourceCheckResult:
    """函数 check_timetable_resources：执行该模块中的相关处理逻辑。"""
    intervals = build_timetable_resource_intervals(timetable, model)
    capacity_conflicts = detect_resource_conflicts(intervals, model.config)
    overtaking_conflicts = detect_timetable_overtaking_conflicts(timetable, model)
    conflicts = (capacity_conflicts + overtaking_conflicts)[: model.config.conflict_limit]
    overlap_violation_s = resource_capacity_overlap_violation_s(intervals, model.config) + sum(
        conflict.overlap_duration_s for conflict in overtaking_conflicts
    )
    return ResourceCheckResult(
        feasible=not conflicts and overlap_violation_s <= 0.0,
        conflicts=conflicts,
        intervals=intervals,
        overlap_violation_s=round(overlap_violation_s, 6),
    )


def _overlap(a: ResourceInterval, b: ResourceInterval) -> Tuple[float, float, float]:
    """函数 _overlap：执行该模块中的相关处理逻辑。"""
    start = max(a.start_time_s, b.start_time_s)
    end = min(a.end_time_s, b.end_time_s)
    return start, end, max(0.0, end - start)


def _conflict_type(resource_type: str, a: ResourceInterval, b: ResourceInterval) -> str:
    """函数 _conflict_type：执行该模块中的相关处理逻辑。"""
    if resource_type == "station_track":
        return "station_track_capacity_conflict"
    if resource_type == "station_throat":
        return "throat_route_conflict"
    if resource_type == "section" and a.direction != b.direction:
        return "opposing_section_conflict"
    if resource_type == "section":
        return "section_capacity_conflict"
    return "resource_capacity_conflict"


def _suggestion(conflict_type: str, overlap_s: float, b: ResourceInterval) -> str:
    """函数 _suggestion：执行该模块中的相关处理逻辑。"""
    delay_s = int(overlap_s + 60)
    if conflict_type == "opposing_section_conflict":
        return f"Arrange a meet/pass at a station or delay {b.train_id} by at least {delay_s}s."
    if conflict_type == "station_track_capacity_conflict":
        return f"Assign another arrival/departure track or delay {b.train_id} by about {delay_s}s."
    if conflict_type == "throat_route_conflict":
        return f"Separate throat routes; delay {b.train_id} by about {delay_s}s or choose another route."
    if conflict_type == "overtaking_without_passing_track":
        return "Add an overtaking/pass plan or delay the later train before the shared section."
    return f"Increase headway or delay {b.train_id} by about {delay_s}s."


def _make_conflict(a: ResourceInterval, b: ResourceInterval, conflict_type: str) -> ConflictExplanation:
    """函数 _make_conflict：执行该模块中的相关处理逻辑。"""
    overlap_start_s, overlap_end_s, overlap_duration_s = _overlap(a, b)
    location = (
        f"{a.start_km:.1f} km"
        if abs(a.start_km - a.end_km) < 1e-6
        else f"{min(a.start_km, a.end_km):.1f}-{max(a.start_km, a.end_km):.1f} km"
    )
    message = (
        f"{a.train_id} and {b.train_id} overlap on {a.resource_name} "
        f"for {overlap_duration_s:.1f}s."
    )
    return ConflictExplanation(
        conflict_type=conflict_type,
        severity="blocking",
        resource_id=a.resource_id,
        resource_name=a.resource_name,
        train_a=a.train_id,
        train_b=b.train_id,
        train_a_type=a.train_type,
        train_b_type=b.train_type,
        overlap_start_s=round(overlap_start_s, 3),
        overlap_end_s=round(overlap_end_s, 3),
        overlap_duration_s=round(overlap_duration_s, 3),
        location_km=location,
        message=message,
        suggestion=_suggestion(conflict_type, overlap_duration_s, b),
    )


def detect_timetable_overtaking_conflicts(
    timetable: Any,
    model: ResourceModel,
) -> List[ConflictExplanation]:
    """Detect same-direction order reversals in canonical timetable times.

    A timetable may have enough nominal section capacity for two trains while
    still placing the later train ahead of the earlier train. Unless an
    explicit passing/meet operation is modeled, that order reversal is a
    blocking conflict.
    """

    trains = {str(train.train_id): train for train in timetable.trains}
    by_train: Dict[str, List[Any]] = {}
    for stop in timetable.stops:
        by_train.setdefault(str(stop.train_id), []).append(stop)

    train_stations: Dict[str, Dict[str, Tuple[float, float, float, str]]] = {}
    for train_id, raw_stops in by_train.items():
        train = trains.get(train_id)
        if train is None:
            continue
        station_map: Dict[str, Tuple[float, float, float, str]] = {}
        for stop in sorted(raw_stops, key=lambda item: int(item.seq)):
            station_name = str(getattr(stop, "station_name", ""))
            station_km = float(getattr(stop, "station_km", 0.0))
            key = station_name or f"km:{station_km:.6f}"
            station_map[key] = (
                station_km,
                float(getattr(stop, "arrival_time_s", 0.0)),
                float(getattr(stop, "departure_time_s", 0.0)),
                station_name or key,
            )
        train_stations[train_id] = station_map

    conflicts: List[ConflictExplanation] = []
    train_ids = sorted(train_stations)
    for left_index, left_id in enumerate(train_ids):
        left_train = trains.get(left_id)
        if left_train is None:
            continue
        left_direction = str(getattr(left_train, "direction", ""))
        if not left_direction:
            continue
        for right_id in train_ids[left_index + 1 :]:
            right_train = trains.get(right_id)
            if right_train is None or str(getattr(right_train, "direction", "")) != left_direction:
                continue
            shared_keys = set(train_stations[left_id]) & set(train_stations[right_id])
            shared = []
            for key in shared_keys:
                left_point = train_stations[left_id][key]
                right_point = train_stations[right_id][key]
                shared.append((min(left_point[0], right_point[0]), key, left_point, right_point))
            shared.sort(key=lambda item: item[0], reverse=left_direction == "reverse")
            if len(shared) < 2:
                continue

            previous_sign = 0
            reversal = None
            for shared_index, (_km, key, left_point, right_point) in enumerate(shared):
                # 后车越过停车列车后，可能在下一站前恢复原到达顺序；因此还要比较中间站发车顺序。
                # 终点释放顺序不再影响后续运行顺序。
                phases = [("arrival", left_point[1], right_point[1])]
                if shared_index < len(shared) - 1:
                    phases.append(("departure", left_point[2], right_point[2]))
                for phase, left_time_s, right_time_s in phases:
                    delta_s = left_time_s - right_time_s
                    sign = 1 if delta_s > 1e-6 else -1 if delta_s < -1e-6 else 0
                    if sign == 0:
                        continue
                    if previous_sign and sign != previous_sign:
                        reversal = (
                            key,
                            left_point,
                            right_point,
                            delta_s,
                            phase,
                            left_time_s,
                            right_time_s,
                        )
                        break
                    previous_sign = sign
                if reversal is not None:
                    break
            if reversal is None:
                continue

            key, left_point, right_point, delta_s, phase, left_time_s, right_time_s = reversal
            location_km = left_point[0]
            overlap_start = min(left_time_s, right_time_s)
            overlap_end = max(left_time_s, right_time_s)
            overlap_duration = max(1.0, overlap_end - overlap_start)
            station_name = left_point[3]
            earlier_train = left_id if delta_s < 0 else right_id
            later_train = right_id if delta_s < 0 else left_id
            conflicts.append(
                ConflictExplanation(
                    conflict_type="overtaking_without_passing_track",
                    severity="blocking",
                    resource_id=f"overtake:{left_direction}:{left_id}:{right_id}",
                    resource_name=f"{left_direction} running order near {station_name}",
                    train_a=left_id,
                    train_b=right_id,
                    train_a_type=str(getattr(left_train, "train_type", "")),
                    train_b_type=str(getattr(right_train, "train_type", "")),
                    overlap_start_s=round(overlap_start, 3),
                    overlap_end_s=round(overlap_end, 3),
                    overlap_duration_s=round(overlap_duration, 3),
                    location_km=f"{location_km:.1f} km",
                    message=(
                        f"{earlier_train} and {later_train} reverse running order at {station_name} "
                        f"during {phase}; "
                        "no passing operation is represented in the timetable."
                    ),
                    suggestion=(
                        f"Add a confirmed passing/overtaking plan at {station_name}, or retime {later_train} "
                        "so the original same-direction order is preserved."
                    ),
                )
            )

    return conflicts


def _normalize_resource_interval(interval: ResourceInterval) -> ResourceInterval:
    """Ensure start_time_s <= end_time_s without dropping the occupation window."""

    if interval.end_time_s >= interval.start_time_s:
        return interval
    return ResourceInterval(
        resource_id=interval.resource_id,
        resource_name=interval.resource_name,
        resource_type=interval.resource_type,
        capacity=interval.capacity,
        train_id=interval.train_id,
        train_type=interval.train_type,
        direction=interval.direction,
        start_time_s=interval.end_time_s,
        end_time_s=interval.start_time_s,
        start_km=interval.start_km,
        end_km=interval.end_km,
        detail=(interval.detail + "; normalized inverted time window").strip("; "),
    )


def _resource_interval_validation(
    interval: ResourceInterval,
) -> Tuple[bool, str, float, float, float, float]:
    """函数 _resource_interval_validation：执行该模块中的相关处理逻辑。"""
    raw_numeric_values = (
        interval.start_time_s,
        interval.end_time_s,
        interval.capacity,
        interval.start_km,
        interval.end_km,
    )
    if any(isinstance(value, bool) for value in raw_numeric_values):
        return False, "boolean used as a numeric interval value", 0.0, 0.0, 0.0, 0.0
    try:
        start_time_s = float(interval.start_time_s)
        end_time_s = float(interval.end_time_s)
        capacity = float(interval.capacity)
        start_km = float(interval.start_km)
        end_km = float(interval.end_km)
    except (TypeError, ValueError):
        return False, "non-numeric interval value", 0.0, 0.0, 0.0, 0.0
    if not math.isfinite(start_time_s) or not math.isfinite(end_time_s):
        return False, "non-finite occupation time", start_time_s, end_time_s, start_km, end_km
    if end_time_s == start_time_s:
        return False, "zero-duration occupation", start_time_s, end_time_s, start_km, end_km
    if end_time_s < start_time_s:
        return False, "inverted occupation time", start_time_s, end_time_s, start_km, end_km
    if not math.isfinite(capacity) or not capacity.is_integer() or capacity < 1.0:
        return (
            False,
            f"invalid capacity={interval.capacity!r}",
            start_time_s,
            end_time_s,
            start_km,
            end_km,
        )
    if not math.isfinite(start_km) or not math.isfinite(end_km):
        return False, "non-finite location", start_time_s, end_time_s, start_km, end_km
    return True, "", start_time_s, end_time_s, start_km, end_km


def detect_invalid_resource_intervals(
    intervals: Iterable[ResourceInterval],
) -> List[ConflictExplanation]:
    """Flag inverted or zero-length resource occupations from upstream builders."""

    invalid: List[ConflictExplanation] = []
    for interval in intervals:
        valid, reason, start_time_s, end_time_s, start_km, end_km = _resource_interval_validation(
            interval
        )
        if valid:
            continue
        finite_window = math.isfinite(start_time_s) and math.isfinite(end_time_s)
        overlap_start_s = min(start_time_s, end_time_s) if finite_window else 0.0
        overlap_end_s = max(start_time_s, end_time_s) if finite_window else 0.0
        finite_location = math.isfinite(start_km) and math.isfinite(end_km)
        if finite_location:
            location_km = (
                f"{start_km:.1f} km"
                if abs(start_km - end_km) < 1e-6
                else f"{min(start_km, end_km):.1f}-{max(start_km, end_km):.1f} km"
            )
        else:
            location_km = "unknown"
        invalid.append(
            ConflictExplanation(
                conflict_type="invalid_resource_interval",
                severity="blocking",
                resource_id=interval.resource_id,
                resource_name=interval.resource_name,
                train_a=interval.train_id,
                train_b=interval.train_id,
                train_a_type=interval.train_type,
                train_b_type=interval.train_type,
                overlap_start_s=round(overlap_start_s, 3),
                overlap_end_s=round(overlap_end_s, 3),
                overlap_duration_s=round(overlap_end_s - overlap_start_s, 3),
                location_km=location_km,
                message=(
                    f"{interval.train_id} has an invalid occupation on {interval.resource_name}: "
                    f"{reason}; start_time_s={interval.start_time_s}, end_time_s={interval.end_time_s}."
                ),
                suggestion=(
                    "Fix upstream interval construction so start_time_s < end_time_s before conflict detection."
                ),
            )
        )
    return invalid


def _analyze_resource_intervals(
    intervals: Iterable[ResourceInterval],
) -> Tuple[List[ConflictExplanation], Dict[str, List[ResourceInterval]], float]:
    """一次完成区间校验和资源分组，供完整资源检查复用。"""

    invalid_conflicts: List[ConflictExplanation] = []
    grouped: Dict[str, List[ResourceInterval]] = {}
    invalid_overlap_s = 0.0
    for interval in intervals:
        valid, reason, start_time_s, end_time_s, start_km, end_km = _resource_interval_validation(
            interval
        )
        if not valid:
            finite_window = math.isfinite(start_time_s) and math.isfinite(end_time_s)
            overlap_start_s = min(start_time_s, end_time_s) if finite_window else 0.0
            overlap_end_s = max(start_time_s, end_time_s) if finite_window else 0.0
            finite_location = math.isfinite(start_km) and math.isfinite(end_km)
            if finite_location:
                location_km = (
                    f"{start_km:.1f} km"
                    if abs(start_km - end_km) < 1e-6
                    else f"{min(start_km, end_km):.1f}-{max(start_km, end_km):.1f} km"
                )
            else:
                location_km = "unknown"
            invalid_conflicts.append(
                ConflictExplanation(
                    conflict_type="invalid_resource_interval",
                    severity="blocking",
                    resource_id=interval.resource_id,
                    resource_name=interval.resource_name,
                    train_a=interval.train_id,
                    train_b=interval.train_id,
                    train_a_type=interval.train_type,
                    train_b_type=interval.train_type,
                    overlap_start_s=round(overlap_start_s, 3),
                    overlap_end_s=round(overlap_end_s, 3),
                    overlap_duration_s=round(overlap_end_s - overlap_start_s, 3),
                    location_km=location_km,
                    message=(
                        f"{interval.train_id} has an invalid occupation on {interval.resource_name}: "
                        f"{reason}; start_time_s={interval.start_time_s}, end_time_s={interval.end_time_s}."
                    ),
                    suggestion=(
                        "Fix upstream interval construction so start_time_s < end_time_s before conflict detection."
                    ),
                )
            )
            invalid_overlap_s += overlap_end_s - overlap_start_s
            continue
        normalized = _normalize_resource_interval(interval)
        grouped.setdefault(normalized.resource_id, []).append(normalized)
    return invalid_conflicts, grouped, invalid_overlap_s


def _detect_resource_conflicts_from_groups(
    invalid_conflicts: List[ConflictExplanation],
    grouped: Dict[str, List[ResourceInterval]],
    config: ResourceConfig,
) -> List[ConflictExplanation]:
    """基于已校验分组生成容量冲突，保持公开接口的排序和截断规则。"""

    conflicts = list(invalid_conflicts)
    if len(conflicts) >= config.conflict_limit:
        return conflicts[: config.conflict_limit]

    for resource_id, items in grouped.items():
        sorted_items = sorted(items, key=lambda item: (item.start_time_s, item.end_time_s))
        active: List[ResourceInterval] = []
        for item in sorted_items:
            active = [
                existing
                for existing in active
                if existing.end_time_s - item.start_time_s > config.min_overlap_s
            ]
            if len(active) >= item.capacity:
                for existing in active:
                    overlap_start_s, overlap_end_s, overlap_duration_s = _overlap(existing, item)
                    if overlap_duration_s <= config.min_overlap_s:
                        continue
                    conflicts.append(
                        _make_conflict(
                            existing,
                            item,
                            _conflict_type(item.resource_type, existing, item),
                        )
                    )
                    if len(conflicts) >= config.conflict_limit:
                        return conflicts
            active.append(item)

    return conflicts


def detect_resource_conflicts(intervals: Iterable[ResourceInterval], config: ResourceConfig) -> List[ConflictExplanation]:
    """Detect capacity conflicts and return explanations."""

    invalid_conflicts, grouped, _invalid_overlap_s = _analyze_resource_intervals(intervals)
    return _detect_resource_conflicts_from_groups(invalid_conflicts, grouped, config)


def _resource_capacity_overlap_from_groups(
    grouped: Dict[str, List[ResourceInterval]],
    config: ResourceConfig,
    invalid_overlap_s: float,
) -> float:
    """基于已校验分组累计超容量占用时间。"""

    total_violation_s = invalid_overlap_s
    for items in grouped.values():
        # 资源构造器对同一资源的每次占用使用同一个容量；取最严格值，避免低估混合异常输入。
        capacity = min(int(item.capacity) for item in items)
        event_deltas: Dict[float, int] = {}
        for item in items:
            event_deltas[item.start_time_s] = event_deltas.get(item.start_time_s, 0) + 1
            event_deltas[item.end_time_s] = event_deltas.get(item.end_time_s, 0) - 1

        active_count = 0
        previous_time: Optional[float] = None
        episode_start: Optional[float] = None
        episode_excess_s = 0.0
        for event_time in sorted(event_deltas):
            if previous_time is not None and event_time > previous_time:
                if active_count > capacity:
                    if episode_start is None:
                        episode_start = previous_time
                    episode_excess_s += (
                        active_count - capacity
                    ) * (event_time - previous_time)
            active_count += event_deltas[event_time]
            if episode_start is not None and active_count <= capacity:
                if event_time - episode_start > config.min_overlap_s:
                    total_violation_s += episode_excess_s
                episode_start = None
                episode_excess_s = 0.0
            previous_time = event_time

    return round(total_violation_s, 6)


def resource_capacity_overlap_violation_s(
    intervals: Iterable[ResourceInterval],
    config: ResourceConfig,
) -> float:
    """Return excess resource-occupancy seconds without pairwise double counting.

    Conflict explanations are pair-oriented for readability. Summing their
    overlap durations is not a valid capacity-violation magnitude when a
    resource can hold more than one train: one short over-capacity episode can
    appear in several otherwise permissible train pairs. This sweep integrates
    ``max(0, occupancy - capacity)`` once per resource instead.
    """

    _invalid_conflicts, grouped, invalid_overlap_s = _analyze_resource_intervals(intervals)
    return _resource_capacity_overlap_from_groups(grouped, config, invalid_overlap_s)


def normalized_resource_constraint_violation(
    result: ResourceCheckResult,
    scale_s: float,
) -> float:
    """Normalize overlap while keeping zero-duration resource errors infeasible."""

    if isinstance(scale_s, bool):
        raise ValueError(f"scale_s must be a finite positive number, got {scale_s!r}")
    try:
        scale = float(scale_s)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"scale_s must be a finite positive number, got {scale_s!r}"
        ) from exc
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError(f"scale_s must be a finite positive number, got {scale_s!r}")
    overlap_violation_s = float(
        getattr(
            result,
            "overlap_violation_s",
            sum(conflict.overlap_duration_s for conflict in result.conflicts),
        )
    )
    normalized = overlap_violation_s / scale
    if result.conflicts and normalized <= 0.0:
        # 无效的零时长区间即使没有正的连续占用时长，也必须作为阻断性问题处理。
        return 1.0
    return normalized


def detect_overtaking_conflicts(
    schedule,
    model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    timing_cache: Optional[Dict[Tuple[object, ...], Dict[int, Tuple[float, float]]]] = None,
) -> List[ConflictExplanation]:
    """Detect same-direction order reversals without an explicit passing plan."""

    conflicts: List[ConflictExplanation] = []
    config = model.config
    runs = _train_runs(schedule, heavy_cache, empty_cache)
    for direction in ["forward", "reverse"]:
        direction_runs = sorted(
            [run for run in runs if run.direction == direction],
            key=lambda run: run.depart_time_s,
        )
        for prev, cur in zip(direction_runs[:-1], direction_runs[1:]):
            prev_timings = _station_timings_for_run(prev, model, timing_cache)
            cur_timings = _station_timings_for_run(cur, model, timing_cache)
            station_indices = (
                range(len(model.stations) - 2, -1, -1)
                if direction == "reverse"
                else range(1, len(model.stations))
            )
            for station_idx in station_indices:
                prev_timing = prev_timings.get(station_idx)
                cur_timing = cur_timings.get(station_idx)
                if prev_timing is None or cur_timing is None:
                    continue
                phase_times = [("arrival", prev_timing[0], cur_timing[0])]
                terminal_index = len(model.stations) - 1 if direction == "forward" else 0
                if station_idx != terminal_index:
                    phase_times.append(("departure", prev_timing[1], cur_timing[1]))
                reversal = next(
                    (
                        (phase, prev_time_s, cur_time_s)
                        for phase, prev_time_s, cur_time_s in phase_times
                        if cur_time_s + config.min_overlap_s < prev_time_s
                    ),
                    None,
                )
                if reversal is None:
                    continue
                phase, prev_event_time_s, cur_event_time_s = reversal
                station = model.stations[station_idx]
                dummy_a = ResourceInterval(
                    resource_id=f"overtake:{direction}:station:{station_idx}",
                    resource_name=f"{direction} running order at {station.name}",
                    resource_type="overtaking",
                    capacity=1,
                    train_id=prev.train_id,
                    train_type=prev.train_type,
                    direction=prev.direction,
                    start_time_s=cur_event_time_s,
                    end_time_s=prev_event_time_s,
                    start_km=float(station.position_km),
                    end_km=float(station.position_km),
                    detail=f"running order reversal during {phase}",
                )
                dummy_b = ResourceInterval(
                    resource_id=f"overtake:{direction}:station:{station_idx}",
                    resource_name=f"{direction} running order at {station.name}",
                    resource_type="overtaking",
                    capacity=1,
                    train_id=cur.train_id,
                    train_type=cur.train_type,
                    direction=cur.direction,
                    start_time_s=cur_event_time_s,
                    end_time_s=prev_event_time_s,
                    start_km=float(station.position_km),
                    end_km=float(station.position_km),
                    detail=f"running order reversal during {phase}",
                )
                conflicts.append(_make_conflict(dummy_a, dummy_b, "overtaking_without_passing_track"))
                break
    return conflicts


def _operation_detail_for_run(
    model: ResourceModel,
    run: TrainRun,
    station: Any,
    station_idx: int,
    station_count: int,
) -> Optional[Dict[str, Any]]:
    """函数 _operation_detail_for_run：执行该模块中的相关处理逻辑。"""
    station_name = getattr(station, "name", "")
    for assignment in model.station_operation_assignments:
        if not _assignment_applies_to_station(assignment, run, station_name, station_idx, station_count):
            continue
        detail = dict(model.station_operation_details.get(station_name, {}))
        detail.setdefault("station_name", station_name)
        detail.setdefault("operation_type", "technical_operation")
        detail["assignment"] = dict(assignment)
        return detail
    return None


def _operation_type_contains(detail: Optional[Dict[str, Any]], text: str) -> bool:
    """函数 _operation_type_contains：执行该模块中的相关处理逻辑。"""
    if not detail:
        return False
    return text in str(detail.get("operation_type") or "")


def build_flow_continuity_events(
    schedule,
    model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    timing_cache: Optional[Dict[Tuple[object, ...], Dict[int, Tuple[float, float]]]] = None,
) -> List[Dict[str, object]]:
    """Build chronological heavy/empty stock events from terminal operations."""

    events: List[Dict[str, object]] = []
    stations = list(model.stations)
    station_count = len(stations)

    for run in _train_runs(schedule, heavy_cache, empty_cache):
        station_timings = _station_timings_for_run(run, model, timing_cache)
        if run.train_type == "Heavy":
            events.append(
                {
                    "time_s": float(run.depart_time_s),
                    "event_type": "heavy_departure",
                    "flow_type": "Heavy",
                    "delta": -1,
                    "train_id": run.train_id,
                    "station_name": getattr(stations[0], "name", ""),
                    "message": "Heavy departure consumes one loaded train flow unit.",
                }
            )
        elif run.train_type == "Empty":
            events.append(
                {
                    "time_s": float(run.depart_time_s),
                    "event_type": "empty_departure",
                    "flow_type": "Empty",
                    "delta": -1,
                    "train_id": run.train_id,
                    "station_name": getattr(stations[-1], "name", ""),
                    "message": "Empty departure consumes one empty train flow unit.",
                }
            )

        for station_idx, station in enumerate(stations):
            timing = station_timings.get(station_idx)
            if timing is None:
                continue
            time_s = timing[0]
            detail = _operation_detail_for_run(model, run, station, station_idx, station_count)
            if detail is None:
                continue
            operation_interval = _station_operation_interval(model, run, station, station_idx, station_count, time_s)
            operation_end_s = operation_interval[1] if operation_interval is not None else time_s
            if run.train_type == "Heavy" and _operation_type_contains(detail, "卸"):
                events.append(
                    {
                        "time_s": float(operation_end_s),
                        "event_type": "empty_formed_after_unloading",
                        "flow_type": "Empty",
                        "delta": 1,
                        "train_id": run.train_id,
                        "station_name": getattr(station, "name", ""),
                        "message": "Heavy arrival and unloading forms one empty train flow unit.",
                    }
                )
            if run.train_type == "Empty" and _operation_type_contains(detail, "装"):
                events.append(
                    {
                        "time_s": float(operation_end_s),
                        "event_type": "heavy_formed_after_loading",
                        "flow_type": "Heavy",
                        "delta": 1,
                        "train_id": run.train_id,
                        "station_name": getattr(station, "name", ""),
                        "message": "Empty arrival and loading forms one loaded train flow unit.",
                    }
                )

    return sorted(
        events,
        key=lambda item: (
            float(item["time_s"]),
            0 if int(item["delta"]) > 0 else 1,
            str(item["event_type"]),
            str(item["train_id"]),
        ),
    )


def check_flow_continuity(
    schedule,
    model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    timing_cache: Optional[Dict[Tuple[object, ...], Dict[int, Tuple[float, float]]]] = None,
) -> Tuple[bool, List[Dict[str, object]], List[Dict[str, object]]]:
    """Check heavy-empty-heavy rolling-stock flow continuity."""

    events = build_flow_continuity_events(
        schedule, model, heavy_cache, empty_cache, timing_cache
    )
    if not model.config.enforce_flow_continuity:
        return True, [], events

    stock = {
        "Heavy": int(model.config.initial_heavy_flow_count),
        "Empty": int(model.config.initial_empty_flow_count),
    }
    violations: List[Dict[str, object]] = []
    for event in events:
        flow_type = str(event["flow_type"])
        stock[flow_type] = stock.get(flow_type, 0) + int(event["delta"])
        event["stock_after"] = stock[flow_type]
        if stock[flow_type] < 0:
            violations.append(
                {
                    "time_s": round(float(event["time_s"]), 3),
                    "event_type": event["event_type"],
                    "flow_type": flow_type,
                    "train_id": event["train_id"],
                    "station_name": event["station_name"],
                    "stock_after": stock[flow_type],
                    "message": (
                        f"{event['train_id']} requires a {flow_type} flow unit before one is available."
                    ),
                    "suggestion": (
                        "Increase initial flow stock, delay this departure, or add an earlier upstream "
                        "unloading/loading completion event."
                    ),
                }
            )
    return not violations, violations, events


def check_schedule_resources(
    schedule,
    model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    interval_cache: Optional[
        Dict[Tuple[int, int, str, str, str, int, int], Tuple[ResourceInterval, ...]]
    ] = None,
) -> ResourceCheckResult:
    """函数 check_schedule_resources：执行该模块中的相关处理逻辑。"""
    timing_cache: Dict[Tuple[object, ...], Dict[int, Tuple[float, float]]] = {}
    intervals = build_resource_intervals(
        schedule,
        model,
        heavy_cache,
        empty_cache,
        interval_cache,
        timing_cache,
    )
    invalid_conflicts, resource_groups, invalid_overlap_s = _analyze_resource_intervals(intervals)
    capacity_conflicts = _detect_resource_conflicts_from_groups(
        invalid_conflicts,
        resource_groups,
        model.config,
    )
    outage_conflicts: List[ConflictExplanation] = []
    outage_overlap_s = 0.0
    for outage in model.unavailabilities:
        for interval in intervals:
            if interval.resource_type != outage.resource_type:
                continue
            resource_matches = interval.resource_id == outage.resource_id
            if outage.resource_type == "section" and interval.resource_id.startswith(outage.resource_id + ":"):
                resource_matches = True
            if not resource_matches:
                continue
            overlap_start_s = max(interval.start_time_s, outage.start_time_s)
            overlap_end_s = min(interval.end_time_s, outage.end_time_s)
            overlap_s = max(0.0, overlap_end_s - overlap_start_s)
            if overlap_s < model.config.min_overlap_s:
                continue
            outage_overlap_s += overlap_s
            outage_conflicts.append(ConflictExplanation(
                conflict_type="resource_unavailable_conflict",
                severity="blocking",
                resource_id=interval.resource_id,
                resource_name=interval.resource_name,
                train_a=interval.train_id,
                train_b=f"OUTAGE:{outage.event_id}",
                train_a_type=interval.train_type,
                train_b_type="ResourceOutage",
                overlap_start_s=round(overlap_start_s, 3),
                overlap_end_s=round(overlap_end_s, 3),
                overlap_duration_s=round(overlap_s, 3),
                location_km=(
                    f"{interval.start_km:.1f} km"
                    if abs(interval.start_km - interval.end_km) < 1e-6
                    else f"{min(interval.start_km, interval.end_km):.1f}-{max(interval.start_km, interval.end_km):.1f} km"
                ),
                message=f"{interval.train_id}在资源封锁窗口占用{interval.resource_name}。",
                suggestion="将列车调整到封锁窗口之外，或由运营人员撤销/缩短封锁。",
            ))
    overtaking_conflicts = detect_overtaking_conflicts(
        schedule, model, heavy_cache, empty_cache, timing_cache
    )
    conflicts = (capacity_conflicts + outage_conflicts + overtaking_conflicts)[: model.config.conflict_limit]
    overlap_violation_s = _resource_capacity_overlap_from_groups(
        resource_groups,
        model.config,
        invalid_overlap_s,
    ) + sum(
        conflict.overlap_duration_s for conflict in overtaking_conflicts
    ) + outage_overlap_s
    flow_feasible, flow_violations, flow_events = check_flow_continuity(
        schedule,
        model,
        heavy_cache,
        empty_cache,
        timing_cache,
    )
    return ResourceCheckResult(
        feasible=not conflicts and overlap_violation_s <= 0.0 and flow_feasible,
        conflicts=conflicts,
        intervals=intervals,
        overlap_violation_s=round(overlap_violation_s, 6),
        flow_continuity_feasible=flow_feasible,
        flow_continuity_violations=flow_violations,
        flow_continuity_events=flow_events,
    )


def conflicts_to_rows(conflicts: Iterable[ConflictExplanation]) -> List[Dict[str, object]]:
    """函数 conflicts_to_rows：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, object]] = []
    for conflict in conflicts:
        rows.append(
            {
                "conflict_type": conflict.conflict_type,
                "severity": conflict.severity,
                "resource_id": conflict.resource_id,
                "resource_name": conflict.resource_name,
                "train_a": conflict.train_a,
                "train_b": conflict.train_b,
                "train_a_type": conflict.train_a_type,
                "train_b_type": conflict.train_b_type,
                "overlap_start_s": conflict.overlap_start_s,
                "overlap_end_s": conflict.overlap_end_s,
                "overlap_duration_s": conflict.overlap_duration_s,
                "location_km": conflict.location_km,
                "message": conflict.message,
                "suggestion": conflict.suggestion,
            }
        )
    return rows
