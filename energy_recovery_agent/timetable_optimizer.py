# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
import argparse
import csv
import json
import math
import random
import warnings

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover - 是否可用取决于运行环境。
    plt = None
    MATPLOTLIB_IMPORT_ERROR = str(exc)
else:
    MATPLOTLIB_IMPORT_ERROR = ""

from timetable_input import (
    CanonicalTimetable,
    TimetableStop,
    format_s_as_hhmmss,
    load_canonical_timetable,
)
from timetable_energy_audit import (
    DEFAULT_POWER_ARM_XLSX,
    EnergyEvent,
    ELECTRICAL_CONSTRAINT_TOLERANCE_KWH,
    build_energy_events,
    build_timetable_running_arcs,
    evaluate_scenario_time_slices,
    load_storage_efficiency,
    load_power_sections,
    _configure_report_font,
    _effective_time_step_s,
    _timetable_arc_candidate,
)
from heavy_empty_network_optimizer import energy_time_slice_rows, load_infrastructure_profile
from data_ingestion import load_real_data_bundle, load_storage_device_parameters
from train_simulator import StorageDeviceParameters
from resource_constraints import (
    check_timetable_resources,
    normalized_resource_constraint_violation,
)
from optimization_attribution import write_optimization_attribution


DEFAULT_OUTPUT_DIR = Path("outputs") / "timetable_optimizer_nsga2"
DEFAULT_RESOURCE_DATA_DIR = Path("data") / "real_shuohuang"
DEFAULT_HEADWAY_MIN = 15
ACTIVE_SCENARIO_ID = "storage_no_direct"
OBJECTIVE_KEYS = ("effective_regen_loss_kwh_est", "grid_kwh_est", "total_adjustment_min")
OBJECTIVE_TOLERANCES = {
    "effective_regen_loss_kwh_est": 0.01,
    "grid_kwh_est": 0.01,
    "total_adjustment_min": 0.01,
}
CONSTRAINT_TOLERANCE = ELECTRICAL_CONSTRAINT_TOLERANCE_KWH
ENERGY_ISSUE_FIELDS = [
    "candidate_id",
    "scenario_id",
    "issue_id",
    "issue_type",
    "severity",
    "power_arm_id",
    "time_window_start",
    "time_window_end",
    "estimated_wasted_kwh",
    "electrical_excess_kwh",
    "reason",
    "source",
]
ISSUE_DETAIL_PREVIEW_LIMIT = 20


OPTIMIZER_FIGURE_LABELS = {
    "optimization_progress": "优化进度",
    "pareto_front": "帕累托前沿",
    "candidate_adjustments": "候选方案调整对比",
    "scenario_scores": "场景评分",
    "scenario_score_comparison": "场景评分对比",
    "evolution_progress": "演化进度",
}


OPTIMIZER_MODE_LABELS = {
    "rule": "规则法",
    "nsga2": "NSGA-II 多目标遗传算法",
}


OPTIMIZER_ACTION_LABELS = {
    "baseline": "基线方案",
    "train_departure_shift": "列车发车时移",
    "dwell_extension": "停站延长",
    "retime_for_energy_overlap": "按能量重排时刻",
    "nsga2_genome": "NSGA-II 基因方案",
}


OPTIMIZER_SCENARIO_LABELS = {
    "storage_no_direct": "储能（无直接利用）",
    "partial_route": "部分线路",
    "device_soc_imbalance": "设备荷电状态不平衡",
    "electrical_limit_probe": "电气限制探测",
    "formal_ten_second_graph": "正式十秒时间图",
}


def _optimizer_display_label(mapping: Dict[str, str], value: object) -> str:
    """将内部代码转换为报告显示文本，内部接口值保持不变。"""
    text = str(value)
    return mapping.get(text, text)


def _optimizer_scenario_label(value: object) -> str:
    """将场景内部编码转换为优化报告中的中文显示名。"""
    scenario_id = str(value)
    return OPTIMIZER_SCENARIO_LABELS.get(scenario_id, scenario_id)


def _timetable_resource_model(resource_data_dir: str = str(DEFAULT_RESOURCE_DATA_DIR)):
    """Load the current resource model for one data directory."""
    return load_real_data_bundle(Path(resource_data_dir)).resource_model


@dataclass(frozen=True)
class CandidatePlan:
    """类 CandidatePlan：执行该模块中的相关处理逻辑。"""
    candidate_id: str
    parent_id: str
    action_type: str
    description: str
    timetable: CanonicalTimetable
    max_shift_min: float
    total_adjustment_min: float
    delay_min: float
    constraint_warnings: Tuple[str, ...]
    constraint_violation: float


@dataclass(frozen=True)
class TimetableGenome:
    """类 TimetableGenome：执行该模块中的相关处理逻辑。"""
    train_offsets_min: Tuple[Tuple[str, int], ...]
    dwell_extensions_min: Tuple[Tuple[str, int, int], ...]

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        seen_train_ids: set[str] = set()
        for train_id, value in self.train_offsets_min:
            if not str(train_id).strip() or train_id in seen_train_ids:
                raise ValueError("train_offsets_min must contain unique non-blank train IDs")
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("train offset genes must be integer minutes")
            seen_train_ids.add(train_id)
        seen_dwell_keys: set[Tuple[str, int]] = set()
        for train_id, seq, value in self.dwell_extensions_min:
            key = (train_id, seq)
            if not str(train_id).strip() or key in seen_dwell_keys:
                raise ValueError("dwell_extensions_min must contain unique non-blank train/seq keys")
            if isinstance(seq, bool) or not isinstance(seq, int) or seq <= 0:
                raise ValueError("dwell extension seq values must be positive integers")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("dwell extension genes must be non-negative integer minutes")
            seen_dwell_keys.add(key)


@dataclass
class EvaluatedIndividual:
    """类 EvaluatedIndividual：执行该模块中的相关处理逻辑。"""
    genome: TimetableGenome
    candidate: CandidatePlan
    objectives: Dict[str, float]
    rank: int = 0
    crowding_distance: float = 0.0


def _write_csv(path: Path, rows: Iterable[Dict[str, object]], fieldnames: Optional[List[str]] = None) -> None:
    """函数 _write_csv：执行该模块中的相关处理逻辑。"""
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        if not fieldnames:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _as_float(value: object, default: float = 0.0, *, field_name: str = "value") -> float:
    """函数 _as_float：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number, got {value!r}")
    try:
        if value is None or value == "":
            number = float(default)
        else:
            number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number, got {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be a finite number, got {value!r}")
    return number


def _required_float(values: Dict[str, object], key: str) -> float:
    """函数 _required_float：执行该模块中的相关处理逻辑。"""
    if key not in values or values[key] is None or values[key] == "":
        raise ValueError(f"{key} is required")
    return _as_float(values[key], field_name=key)


def _whole_setting(value: object, field_name: str, *, minimum: int) -> int:
    """函数 _whole_setting：执行该模块中的相关处理逻辑。"""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}") from exc
    if not math.isfinite(number) or not number.is_integer() or number < minimum:
        raise ValueError(
            f"{field_name} must be a finite whole number greater than or equal to {minimum}, got {value!r}"
        )
    return int(number)


def _probability_setting(value: object, field_name: str) -> float:
    """函数 _probability_setting：执行该模块中的相关处理逻辑。"""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite and between 0 and 1, got {value!r}") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1, got {value!r}")
    return number


def _validate_nsga_settings(
    *,
    max_shift_min: object,
    step_min: object,
    max_dwell_extension_min: object,
    population_size: object,
    generations: object,
    crossover_rate: object,
    mutation_rate: object,
    seed: object,
) -> Tuple[int, int, int, int, int, float, float, int]:
    """函数 _validate_nsga_settings：执行该模块中的相关处理逻辑。"""
    return (
        _whole_setting(max_shift_min, "max_shift_min", minimum=0),
        _whole_setting(step_min, "step_min", minimum=1),
        _whole_setting(max_dwell_extension_min, "max_dwell_extension_min", minimum=0),
        _whole_setting(population_size, "population_size", minimum=1),
        _whole_setting(generations, "generations", minimum=0),
        _probability_setting(crossover_rate, "crossover_rate"),
        _probability_setting(mutation_rate, "mutation_rate"),
        _whole_setting(seed, "seed", minimum=-2**63),
    )


def _stops_by_train(timetable: CanonicalTimetable) -> Dict[str, List[TimetableStop]]:
    """函数 _stops_by_train：执行该模块中的相关处理逻辑。"""
    grouped: Dict[str, List[TimetableStop]] = {}
    for stop in timetable.stops:
        grouped.setdefault(stop.train_id, []).append(stop)
    return {train_id: sorted(stops, key=lambda item: item.seq) for train_id, stops in grouped.items()}


def _clone_with_stops(timetable: CanonicalTimetable, stops: List[TimetableStop]) -> CanonicalTimetable:
    """函数 _clone_with_stops：执行该模块中的相关处理逻辑。"""
    return CanonicalTimetable(
        trains=timetable.trains,
        stops=tuple(sorted(stops, key=lambda item: (item.train_id, item.seq))),
        scenarios=timetable.scenarios,
        constraints=timetable.constraints,
        metadata=dict(timetable.metadata),
        validation_report=timetable.validation_report,
    )


def _with_active_scenarios(timetable: CanonicalTimetable) -> CanonicalTimetable:
    """函数 _with_active_scenarios：执行该模块中的相关处理逻辑。"""
    scenarios = tuple(scenario for scenario in timetable.scenarios if scenario.scenario_id == ACTIVE_SCENARIO_ID)
    if scenarios:
        return replace(timetable, scenarios=scenarios)
    return timetable


def shift_train(timetable: CanonicalTimetable, train_id: str, shift_s: int) -> CanonicalTimetable:
    """函数 shift_train：执行该模块中的相关处理逻辑。"""
    train_stops = [stop for stop in timetable.stops if stop.train_id == train_id]
    if not train_stops:
        return timetable
    earliest_time_s = min(
        min(stop.arrival_time_s, stop.departure_time_s)
        for stop in train_stops
    )
    # 限制整列车的统一偏移，不逐个截断时间戳。逐站截断会压缩午夜附近的停站/运行弧段，
    # 可能抹去其能量，但候选仍能通过时间单调性校验。
    effective_shift_s = max(shift_s, -earliest_time_s)
    stops = []
    for stop in timetable.stops:
        if stop.train_id == train_id:
            stops.append(
                replace(
                    stop,
                    arrival_time_s=stop.arrival_time_s + effective_shift_s,
                    departure_time_s=stop.departure_time_s + effective_shift_s,
                )
            )
        else:
            stops.append(stop)
    return _clone_with_stops(timetable, stops)


def extend_dwell_from_stop(timetable: CanonicalTimetable, train_id: str, seq: int, extension_s: int) -> CanonicalTimetable:
    """函数 extend_dwell_from_stop：执行该模块中的相关处理逻辑。"""
    stops = []
    for stop in timetable.stops:
        if stop.train_id != train_id:
            stops.append(stop)
            continue
        if stop.seq < seq:
            stops.append(stop)
        elif stop.seq == seq:
            stops.append(replace(stop, departure_time_s=stop.departure_time_s + extension_s))
        else:
            stops.append(
                replace(
                    stop,
                    arrival_time_s=stop.arrival_time_s + extension_s,
                    departure_time_s=stop.departure_time_s + extension_s,
                )
            )
    return _clone_with_stops(timetable, stops)


def _baseline_lookup(timetable: CanonicalTimetable) -> Dict[Tuple[str, int], TimetableStop]:
    """函数 _baseline_lookup：执行该模块中的相关处理逻辑。"""
    return {(stop.train_id, stop.seq): stop for stop in timetable.stops}


def adjustment_metrics(baseline: CanonicalTimetable, candidate: CanonicalTimetable) -> Tuple[float, float, float]:
    """函数 adjustment_metrics：执行该模块中的相关处理逻辑。"""
    base = _baseline_lookup(baseline)
    max_abs_s = 0
    total_abs_s = 0
    final_delay_s = 0
    by_train = _stops_by_train(candidate)
    base_by_train = _stops_by_train(baseline)
    for stop in candidate.stops:
        original = base.get((stop.train_id, stop.seq))
        if original is None:
            continue
        arr_delta = stop.arrival_time_s - original.arrival_time_s
        dep_delta = stop.departure_time_s - original.departure_time_s
        max_abs_s = max(max_abs_s, abs(arr_delta), abs(dep_delta))
        total_abs_s += abs(arr_delta) + abs(dep_delta)
    for train_id, stops in by_train.items():
        if train_id not in base_by_train or not stops or not base_by_train[train_id]:
            continue
        final_delay_s += max(0, stops[-1].arrival_time_s - base_by_train[train_id][-1].arrival_time_s)
    return round(max_abs_s / 60.0, 3), round(total_abs_s / 60.0, 3), round(final_delay_s / 60.0, 3)


def validate_candidate(timetable: CanonicalTimetable, headway_min: int) -> Tuple[bool, Tuple[str, ...]]:
    """函数 validate_candidate：执行该模块中的相关处理逻辑。"""
    warnings: List[str] = []
    trains = {train.train_id: train for train in timetable.trains}
    by_train = _stops_by_train(timetable)
    for train_id, stops in by_train.items():
        previous_departure: Optional[int] = None
        previous_km: Optional[float] = None
        direction = trains[train_id].direction if train_id in trains else ""
        for stop in stops:
            if stop.departure_time_s < stop.arrival_time_s:
                warnings.append(f"{train_id} seq {stop.seq}: departure before arrival")
            if previous_departure is not None and stop.arrival_time_s < previous_departure:
                warnings.append(f"{train_id} seq {stop.seq}: non-monotonic time")
            if previous_km is not None:
                if stop.station_km != previous_km and stop.arrival_time_s == previous_departure:
                    warnings.append(f"列车 {train_id} 第 {stop.seq} 站与前站里程不同，跨站运行时长必须大于零。")
                if direction == "forward" and stop.station_km < previous_km:
                    warnings.append(f"{train_id}: forward km decreases")
                if direction == "reverse" and stop.station_km > previous_km:
                    warnings.append(f"{train_id}: reverse km increases")
            previous_departure = stop.departure_time_s
            previous_km = stop.station_km

    origins: List[Tuple[str, str, int]] = []
    for train_id, stops in by_train.items():
        if not stops or train_id not in trains:
            continue
        origins.append((train_id, trains[train_id].direction, stops[0].departure_time_s))
    for idx, left in enumerate(origins):
        for right in origins[idx + 1 :]:
            if left[1] != right[1]:
                continue
            gap_min = abs(left[2] - right[2]) / 60.0
            if gap_min < headway_min:
                warnings.append(f"{left[0]} and {right[0]} same-direction departure headway {gap_min:.1f} min < {headway_min} min")
    return not warnings, tuple(warnings)


def candidate_constraint_violation(timetable: CanonicalTimetable, headway_min: int) -> float:
    """Continuous timetable violation magnitude used by constrained NSGA-II."""

    trains = {train.train_id: train for train in timetable.trains}
    by_train = _stops_by_train(timetable)
    violation = 0.0
    for train_id, stops in by_train.items():
        previous_departure: Optional[int] = None
        previous_km: Optional[float] = None
        direction = trains[train_id].direction if train_id in trains else ""
        for stop in stops:
            violation += max(0.0, float(stop.arrival_time_s - stop.departure_time_s)) / 60.0
            if previous_departure is not None:
                violation += max(0.0, float(previous_departure - stop.arrival_time_s)) / 60.0
            if previous_km is not None:
                if stop.station_km != previous_km and stop.arrival_time_s == previous_departure:
                    violation += 1.0 / 60.0
                if direction == "forward":
                    violation += max(0.0, previous_km - stop.station_km)
                elif direction == "reverse":
                    violation += max(0.0, stop.station_km - previous_km)
            previous_departure = stop.departure_time_s
            previous_km = stop.station_km

    origins: List[Tuple[str, str, int]] = []
    for train_id, stops in by_train.items():
        if stops and train_id in trains:
            origins.append((train_id, trains[train_id].direction, stops[0].departure_time_s))
    for idx, left in enumerate(origins):
        for right in origins[idx + 1 :]:
            if left[1] != right[1]:
                continue
            gap_min = abs(left[2] - right[2]) / 60.0
            violation += max(0.0, float(headway_min) - gap_min) / max(1.0, float(headway_min))
    return violation


def _headway_from_constraints(timetable: CanonicalTimetable) -> int:
    """函数 _headway_from_constraints：执行该模块中的相关处理逻辑。"""
    values = []
    for row in timetable.constraints:
        constraint_type = str(
            row.get("constraint_type") or row.get("type") or row.get("name") or ""
        ).strip()
        text = constraint_type.lower()
        if not ("headway" in text or "追踪" in constraint_type or "间隔" in constraint_type):
            continue
        raw = row.get("value")
        try:
            number = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Headway constraint value must be a positive integer minute value, got {raw!r}") from exc
        if not math.isfinite(number) or not number.is_integer() or number <= 0.0:
            raise ValueError(f"Headway constraint value must be a positive integer minute value, got {raw!r}")
        unit = str(row.get("unit") or "").strip().lower()
        if unit and unit not in {"min", "minute", "minutes", "分钟"}:
            raise ValueError(f"Headway constraint unit must be minutes, got {row.get('unit')!r}")
        values.append(int(number))
    return max(values) if values else DEFAULT_HEADWAY_MIN


def _departure_headway_preflight(
    timetable: CanonicalTimetable,
    headway_min: int,
    max_shift_min: int,
    max_dwell_extension_min: int,
) -> Dict[str, object]:
    """按当前同向始发口径检查时移预算能否消除最短发车间隔。"""
    departures: Dict[str, List[TimetableStop]] = {}
    by_train = _stops_by_train(timetable)
    for train in timetable.trains:
        stops = by_train.get(train.train_id)
        if stops:
            departures.setdefault(train.direction, []).append(stops[0])
    required_gap_s = headway_min * 60
    pair_budget_s = (2 * max_shift_min + max_dwell_extension_min) * 60
    blockers = []
    for direction, stops in sorted(departures.items()):
        ordered = sorted(stops, key=lambda stop: (stop.departure_time_s, stop.train_id))
        for left, right in zip(ordered, ordered[1:]):
            gap_s = right.departure_time_s - left.departure_time_s
            remaining_gap_s = required_gap_s - gap_s - pair_budget_s
            if remaining_gap_s > 0:
                blockers.append({
                    "direction": direction,
                    "first_train_id": left.train_id,
                    "second_train_id": right.train_id,
                    "first_departure_station": left.station_name,
                    "second_departure_station": right.station_name,
                    "observed_gap_s": gap_s,
                    "remaining_gap_shortfall_s": remaining_gap_s,
                })
    return {
        "status": "infeasible_within_adjustment_bounds" if blockers else "no_pairwise_obstruction",
        "scope": "same_direction_departure",
        "minimum_gap_s": required_gap_s,
        "max_departure_separation_increase_s": pair_budget_s,
        "blocking_pair_count": len(blockers),
        "blocking_pairs": blockers,
    }


def _round_to_step_s(value_s: float, step_min: int) -> int:
    """函数 _round_to_step_s：执行该模块中的相关处理逻辑。"""
    step_s = max(60, step_min * 60)
    return int(round(value_s / step_s) * step_s)


def generate_event_guided_candidates(
    baseline: CanonicalTimetable,
    power_sections,
    max_shift_min: int,
    step_min: int,
    limit: int,
) -> List[Tuple[str, str, CanonicalTimetable]]:
    """函数 generate_event_guided_candidates：执行该模块中的相关处理逻辑。"""
    events = build_energy_events(baseline, power_sections)
    generation_events = [event for event in events if event.event_type == "generation"]
    consumption_events = [event for event in events if event.event_type == "consumption"]
    candidates: List[Tuple[str, str, CanonicalTimetable]] = []
    seen: set[Tuple[str, int]] = set()
    max_shift_s = max_shift_min * 60
    for generation in generation_events:
        nearest: Optional[EnergyEvent] = None
        nearest_gap = 10**12
        for consumption in consumption_events:
            gen_mid = (generation.start_time_s + generation.end_time_s) / 2.0
            con_mid = (consumption.start_time_s + consumption.end_time_s) / 2.0
            section_penalty = 0 if generation.section_id == consumption.section_id else 24 * 3600
            gap = abs(gen_mid - con_mid) + section_penalty
            if gap < nearest_gap:
                nearest = consumption
                nearest_gap = gap
        if nearest is None:
            continue
        gen_mid = (generation.start_time_s + generation.end_time_s) / 2.0
        con_mid = (nearest.start_time_s + nearest.end_time_s) / 2.0
        shift_s = _round_to_step_s(gen_mid - con_mid, step_min)
        shift_s = max(-max_shift_s, min(max_shift_s, shift_s))
        if shift_s == 0:
            continue
        key = (nearest.train_id, shift_s)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            (
                "retime_for_energy_overlap",
                f"将列车 {nearest.train_id} 向再生事件 {generation.event_id} 调整 {shift_s / 60:.0f} 分钟；"
                "有条件时优先保持同一供电臂。",
                shift_train(baseline, nearest.train_id, shift_s),
            )
        )
        if len(candidates) >= limit:
            break
    return candidates


def generate_candidates(
    baseline: CanonicalTimetable,
    power_sections,
    max_shift_min: int,
    step_min: int,
    max_dwell_extension_min: int,
    max_candidates: int,
) -> List[CandidatePlan]:
    """函数 generate_candidates：执行该模块中的相关处理逻辑。"""
    headway_min = _headway_from_constraints(baseline)
    raw: List[Tuple[str, str, CanonicalTimetable]] = [("baseline", "用户原始运行图。", baseline)]
    shifts = [shift for shift in range(-max_shift_min, max_shift_min + 1, step_min) if shift != 0]
    for train in baseline.trains:
        for shift_min in shifts:
            raw.append(
                (
                    "train_departure_shift",
                    f"将列车 {train.train_id} 的全部停站时刻调整 {shift_min} 分钟。",
                    shift_train(baseline, train.train_id, shift_min * 60),
                )
            )

    dwell_steps = [value for value in range(step_min, max_dwell_extension_min + 1, step_min)]
    for train_id, stops in _stops_by_train(baseline).items():
        for stop in stops[:-1]:
            dwell_s = stop.departure_time_s - stop.arrival_time_s
            if dwell_s <= 0 and stop.stop_type == "pass":
                continue
            for extension_min in dwell_steps:
                raw.append(
                    (
                        "dwell_extension",
                        f"将列车 {train_id} 在 {stop.station_name}（序号 {stop.seq}）的停站时间延长 {extension_min} 分钟。",
                        extend_dwell_from_stop(baseline, train_id, stop.seq, extension_min * 60),
                    )
                )

    if max_shift_min > 0:
        raw.extend(
            generate_event_guided_candidates(
                baseline,
                power_sections,
                max_shift_min=max_shift_min,
                step_min=step_min,
                limit=max(0, max_candidates - len(raw)),
            )
        )

    candidates: List[CandidatePlan] = []
    seen_signature: set[Tuple[Tuple[str, int, int, int], ...]] = set()
    for action_type, description, timetable in raw:
        signature = tuple((stop.train_id, stop.seq, stop.arrival_time_s, stop.departure_time_s) for stop in sorted(timetable.stops, key=lambda item: (item.train_id, item.seq)))
        if signature in seen_signature:
            continue
        seen_signature.add(signature)
        feasible, warnings = validate_candidate(timetable, headway_min)
        if not feasible and action_type != "baseline":
            continue
        max_shift, total_adjustment, delay = adjustment_metrics(baseline, timetable)
        candidates.append(
            CandidatePlan(
                candidate_id=f"C{len(candidates):04d}",
                parent_id="",
                action_type=action_type,
                description=description,
                timetable=timetable,
                max_shift_min=max_shift,
                total_adjustment_min=total_adjustment,
                delay_min=delay,
                constraint_warnings=warnings,
                constraint_violation=candidate_constraint_violation(timetable, headway_min),
            )
        )
        if len(candidates) >= max_candidates:
            break
    return candidates


def _genome_signature(genome: TimetableGenome) -> Tuple[Tuple[Tuple[str, int], ...], Tuple[Tuple[str, int, int], ...]]:
    """函数 _genome_signature：执行该模块中的相关处理逻辑。"""
    return (tuple(sorted(genome.train_offsets_min)), tuple(sorted(genome.dwell_extensions_min)))


def _offset_map(genome: TimetableGenome) -> Dict[str, int]:
    """函数 _offset_map：执行该模块中的相关处理逻辑。"""
    return dict(genome.train_offsets_min)


def _dwell_map(genome: TimetableGenome) -> Dict[Tuple[str, int], int]:
    """函数 _dwell_map：执行该模块中的相关处理逻辑。"""
    return {(train_id, seq): value for train_id, seq, value in genome.dwell_extensions_min}


def _adjustable_dwell_stops(baseline: CanonicalTimetable) -> List[TimetableStop]:
    """函数 _adjustable_dwell_stops：执行该模块中的相关处理逻辑。"""
    return [
        stop
        for stops in _stops_by_train(baseline).values()
        for stop in stops[:-1]
    ]


def baseline_genome(baseline: CanonicalTimetable) -> TimetableGenome:
    """函数 baseline_genome：执行该模块中的相关处理逻辑。"""
    return TimetableGenome(
        train_offsets_min=tuple((train.train_id, 0) for train in baseline.trains),
        dwell_extensions_min=tuple((stop.train_id, stop.seq, 0) for stop in _adjustable_dwell_stops(baseline)),
    )


def random_genome(
    baseline: CanonicalTimetable,
    rng: random.Random,
    max_shift_min: int,
    step_min: int,
    max_dwell_extension_min: int,
) -> TimetableGenome:
    """函数 random_genome：执行该模块中的相关处理逻辑。"""
    step = max(1, step_min)
    shift_values = list(range(-max_shift_min, max_shift_min + 1, step))
    dwell_values = list(range(0, max_dwell_extension_min + 1, step))
    return TimetableGenome(
        train_offsets_min=tuple((train.train_id, rng.choice(shift_values)) for train in baseline.trains),
        dwell_extensions_min=tuple(
            (stop.train_id, stop.seq, rng.choice(dwell_values))
            for stop in _adjustable_dwell_stops(baseline)
        ),
    )


def decode_genome_to_timetable(baseline: CanonicalTimetable, genome: TimetableGenome) -> CanonicalTimetable:
    """函数 decode_genome_to_timetable：执行该模块中的相关处理逻辑。"""
    offsets = _offset_map(genome)
    dwell_extensions = _dwell_map(genome)
    by_train = _stops_by_train(baseline)
    new_stops: List[TimetableStop] = []
    for train_id, stops in by_train.items():
        requested_offset_s = offsets.get(train_id, 0) * 60
        earliest_time_s = min(
            min(stop.arrival_time_s, stop.departure_time_s)
            for stop in stops
        )
        offset_s = max(requested_offset_s, -earliest_time_s)
        cumulative_extension_s = 0
        for stop in stops:
            arrival_s = stop.arrival_time_s + offset_s + cumulative_extension_s
            departure_s = stop.departure_time_s + offset_s + cumulative_extension_s
            extension_s = dwell_extensions.get((train_id, stop.seq), 0) * 60
            if extension_s:
                departure_s += extension_s
                cumulative_extension_s += extension_s
            new_stops.append(replace(stop, arrival_time_s=arrival_s, departure_time_s=departure_s))
    return _clone_with_stops(baseline, new_stops)


def genome_description(genome: TimetableGenome) -> str:
    """函数 genome_description：执行该模块中的相关处理逻辑。"""
    offsets = [f"{train_id}:{value:+d}m" for train_id, value in genome.train_offsets_min if value]
    dwells = [f"{train_id}#{seq}:+{value}m" for train_id, seq, value in genome.dwell_extensions_min if value]
    parts = []
    if offsets:
        parts.append("发车时移：" + "、".join(offsets[:6]))
    if dwells:
        parts.append("停站延长：" + "、".join(dwells[:6]))
    if not parts:
        return "NSGA-II 基线基因方案。"
    return "NSGA-II 基因方案：" + "；".join(parts)


def genome_to_candidate(
    baseline: CanonicalTimetable,
    genome: TimetableGenome,
    candidate_id: str,
    headway_min: int,
) -> CandidatePlan:
    """函数 genome_to_candidate：执行该模块中的相关处理逻辑。"""
    timetable = decode_genome_to_timetable(baseline, genome)
    _feasible, warnings = validate_candidate(timetable, headway_min)
    max_shift, total_adjustment, delay = adjustment_metrics(baseline, timetable)
    return CandidatePlan(
        candidate_id=candidate_id,
        parent_id="nsga2",
        action_type="nsga2_genome",
        description=genome_description(genome),
        timetable=timetable,
        max_shift_min=max_shift,
        total_adjustment_min=total_adjustment,
        delay_min=delay,
        constraint_warnings=warnings,
        constraint_violation=candidate_constraint_violation(timetable, headway_min),
    )


def crossover_genomes(left: TimetableGenome, right: TimetableGenome, rng: random.Random) -> TimetableGenome:
    """函数 crossover_genomes：执行该模块中的相关处理逻辑。"""
    left_offsets = _offset_map(left)
    right_offsets = _offset_map(right)
    left_dwells = _dwell_map(left)
    right_dwells = _dwell_map(right)
    train_ids = sorted(set(left_offsets) | set(right_offsets))
    dwell_keys = sorted(set(left_dwells) | set(right_dwells))
    offsets = tuple((train_id, left_offsets.get(train_id, 0) if rng.random() < 0.5 else right_offsets.get(train_id, 0)) for train_id in train_ids)
    dwells = tuple(
        (train_id, seq, left_dwells.get((train_id, seq), 0) if rng.random() < 0.5 else right_dwells.get((train_id, seq), 0))
        for train_id, seq in dwell_keys
    )
    return TimetableGenome(offsets, dwells)


def mutate_genome(
    genome: TimetableGenome,
    rng: random.Random,
    max_shift_min: int,
    step_min: int,
    max_dwell_extension_min: int,
    mutation_rate: float,
) -> TimetableGenome:
    """函数 mutate_genome：执行该模块中的相关处理逻辑。"""
    step = max(1, step_min)
    offsets = []
    for train_id, value in genome.train_offsets_min:
        if rng.random() < mutation_rate:
            value += rng.choice((-step, step))
            value = max(-max_shift_min, min(max_shift_min, value))
        offsets.append((train_id, value))
    dwells = []
    for train_id, seq, value in genome.dwell_extensions_min:
        if rng.random() < mutation_rate:
            value += rng.choice((-step, step))
            value = max(0, min(max_dwell_extension_min, value))
        dwells.append((train_id, seq, value))
    return TimetableGenome(tuple(offsets), tuple(dwells))


def _candidate_objectives(candidate: CandidatePlan, scenario_rows: List[Dict[str, object]]) -> Dict[str, float]:
    """函数 _candidate_objectives：执行该模块中的相关处理逻辑。"""
    rows = [row for row in scenario_rows if row["candidate_id"] == candidate.candidate_id]
    if not rows:
        return {
            "effective_regen_loss_kwh_est": 1e12,
            "grid_kwh_est": 1e12,
            "total_adjustment_min": _as_float(
                candidate.total_adjustment_min, field_name="total_adjustment_min"
            ),
            "constraint_violation": max(
                1.0, _as_float(candidate.constraint_violation, field_name="constraint_violation")
            ),
        }
    return {
        "effective_regen_loss_kwh_est": max(
            _required_float(row, "effective_regen_loss_kwh_est") for row in rows
        ),
        "grid_kwh_est": sum(_required_float(row, "grid_kwh_est") for row in rows) / len(rows),
        "total_adjustment_min": _as_float(
            candidate.total_adjustment_min, field_name="total_adjustment_min"
        ),
        "constraint_violation": max(_required_float(row, "constraint_violation") for row in rows),
    }


def _effective_objective_value(key: str, value: float) -> int:
    """函数 _effective_objective_value：执行该模块中的相关处理逻辑。"""
    tolerance = OBJECTIVE_TOLERANCES[key]
    return int(round(float(value) / tolerance))


def _effective_objective_tuple(values: Dict[str, object]) -> Tuple[int, ...]:
    """函数 _effective_objective_tuple：执行该模块中的相关处理逻辑。"""
    return tuple(
        _effective_objective_value(key, _required_float(values, key))
        for key in OBJECTIVE_KEYS
    )


def _crowding_value(key: str, objectives: Dict[str, float]) -> float:
    """函数 _crowding_value：执行该模块中的相关处理逻辑。"""
    if key == "constraint_violation":
        return _required_float(objectives, key)
    return float(_effective_objective_value(key, _required_float(objectives, key)))


def _dominates_objectives(left: Dict[str, float], right: Dict[str, float]) -> bool:
    """函数 _dominates_objectives：执行该模块中的相关处理逻辑。"""
    left_violation = _required_float(left, "constraint_violation")
    right_violation = _required_float(right, "constraint_violation")
    left_feasible = left_violation <= CONSTRAINT_TOLERANCE
    right_feasible = right_violation <= CONSTRAINT_TOLERANCE
    if left_feasible != right_feasible:
        return left_feasible
    if not left_feasible:
        return left_violation < right_violation
    left_effective = _effective_objective_tuple(left)
    right_effective = _effective_objective_tuple(right)
    le_all = all(left_value <= right_value for left_value, right_value in zip(left_effective, right_effective))
    lt_any = any(left_value < right_value for left_value, right_value in zip(left_effective, right_effective))
    return le_all and lt_any


def non_dominated_fronts(individuals: List[EvaluatedIndividual]) -> List[List[EvaluatedIndividual]]:
    """函数 non_dominated_fronts：执行该模块中的相关处理逻辑。"""
    dominates: Dict[int, List[int]] = {idx: [] for idx in range(len(individuals))}
    domination_count: Dict[int, int] = {idx: 0 for idx in range(len(individuals))}
    fronts: List[List[int]] = [[]]
    for i, left in enumerate(individuals):
        for j, right in enumerate(individuals):
            if i == j:
                continue
            if _dominates_objectives(left.objectives, right.objectives):
                dominates[i].append(j)
            elif _dominates_objectives(right.objectives, left.objectives):
                domination_count[i] += 1
        if domination_count[i] == 0:
            left.rank = 0
            fronts[0].append(i)
    current = 0
    while current < len(fronts) and fronts[current]:
        next_front: List[int] = []
        for i in fronts[current]:
            for j in dominates[i]:
                domination_count[j] -= 1
                if domination_count[j] == 0:
                    individuals[j].rank = current + 1
                    next_front.append(j)
        current += 1
        if next_front:
            fronts.append(next_front)
    return [[individuals[idx] for idx in front] for front in fronts if front]


def assign_crowding_distance(front: List[EvaluatedIndividual]) -> None:
    """函数 assign_crowding_distance：执行该模块中的相关处理逻辑。"""
    if not front:
        return
    for individual in front:
        individual.crowding_distance = 0.0
    if len(front) <= 2:
        for individual in front:
            individual.crowding_distance = math.inf
        return
    all_feasible = all(
        _required_float(individual.objectives, "constraint_violation") <= CONSTRAINT_TOLERANCE
        for individual in front
    )
    active_keys = OBJECTIVE_KEYS if all_feasible else ("constraint_violation", *OBJECTIVE_KEYS)
    for key in active_keys:
        front.sort(key=lambda item: _crowding_value(key, item.objectives))
        front[0].crowding_distance = math.inf
        front[-1].crowding_distance = math.inf
        min_value = _crowding_value(key, front[0].objectives)
        max_value = _crowding_value(key, front[-1].objectives)
        if max_value == min_value:
            continue
        for idx in range(1, len(front) - 1):
            if math.isinf(front[idx].crowding_distance):
                continue
            next_value = _crowding_value(key, front[idx + 1].objectives)
            previous_value = _crowding_value(key, front[idx - 1].objectives)
            front[idx].crowding_distance += (next_value - previous_value) / (max_value - min_value)


def select_next_generation(individuals: List[EvaluatedIndividual], population_size: int) -> List[EvaluatedIndividual]:
    """函数 select_next_generation：执行该模块中的相关处理逻辑。"""
    selected: List[EvaluatedIndividual] = []
    for front in non_dominated_fronts(individuals):
        assign_crowding_distance(front)
        if len(selected) + len(front) <= population_size:
            selected.extend(front)
            continue
        selected.extend(sorted(front, key=lambda item: item.crowding_distance, reverse=True)[: population_size - len(selected)])
        break
    return sorted(selected, key=lambda item: (item.rank, -item.crowding_distance))


def tournament_select(population: List[EvaluatedIndividual], rng: random.Random) -> EvaluatedIndividual:
    """函数 tournament_select：执行该模块中的相关处理逻辑。"""
    if len(population) == 1:
        return population[0]
    left, right = rng.sample(population, 2)
    if left.rank != right.rank:
        return left if left.rank < right.rank else right
    return left if left.crowding_distance >= right.crowding_distance else right


def evaluate_genome_population(
    baseline: CanonicalTimetable,
    genomes: List[TimetableGenome],
    generation: int,
    headway_min: int,
    power_sections,
    resource_model=None,
    infrastructure=None,
    default_storage_efficiency: Optional[float] = None,
    storage_device_parameters: Sequence[StorageDeviceParameters] = (),
) -> Tuple[List[EvaluatedIndividual], List[Dict[str, object]], List[Dict[str, object]]]:
    """函数 evaluate_genome_population：执行该模块中的相关处理逻辑。"""
    candidates = [
        genome_to_candidate(baseline, genome, f"N{generation:03d}_{idx:04d}", headway_min)
        for idx, genome in enumerate(genomes)
    ]
    candidate_rows, scenario_rows = evaluate_candidates(
        candidates,
        power_sections,
        resource_model=resource_model,
        infrastructure=infrastructure,
        default_storage_efficiency=default_storage_efficiency,
        storage_device_parameters=storage_device_parameters,
    )
    evaluated = [
        EvaluatedIndividual(
            genome=genomes[idx],
            candidate=candidate,
            objectives=_candidate_objectives(candidate, scenario_rows),
        )
        for idx, candidate in enumerate(candidates)
    ]
    return evaluated, candidate_rows, scenario_rows


def _generation_log_row(generation: int, individuals: List[EvaluatedIndividual]) -> Dict[str, object]:
    """函数 _generation_log_row：执行该模块中的相关处理逻辑。"""
    fronts = non_dominated_fronts(individuals)
    pareto = fronts[0] if fronts else []
    return {
        "generation": generation,
        "population_size": len(individuals),
        "pareto_count": len(pareto),
        "best_effective_regen_loss_kwh": round(
            min((item.objectives["effective_regen_loss_kwh_est"] for item in individuals), default=0.0),
            6,
        ),
        "best_grid_kwh": round(min((item.objectives["grid_kwh_est"] for item in individuals), default=0.0), 6),
        "min_adjustment_min": round(min((item.objectives["total_adjustment_min"] for item in individuals), default=0.0), 6),
        "min_constraint_violation": round(min((item.objectives["constraint_violation"] for item in individuals), default=0.0), 6),
        "avg_constraint_penalty": round(sum(item.objectives["constraint_violation"] for item in individuals) / max(1, len(individuals)), 6),
        "feasible_count": sum(item.objectives["constraint_violation"] <= CONSTRAINT_TOLERANCE for item in individuals),
    }


def nsga_population_rows(individuals: List[EvaluatedIndividual]) -> List[Dict[str, object]]:
    """函数 nsga_population_rows：执行该模块中的相关处理逻辑。"""
    rows = []
    for item in sorted(individuals, key=lambda individual: (individual.rank, -individual.crowding_distance, individual.candidate.candidate_id)):
        row: Dict[str, object] = {
            "candidate_id": item.candidate.candidate_id,
            "rank": item.rank,
            "crowding_distance": "inf" if math.isinf(item.crowding_distance) else round(item.crowding_distance, 6),
            "action_type": item.candidate.action_type,
            "description": item.candidate.description,
            "max_shift_min": item.candidate.max_shift_min,
            "total_adjustment_min": item.candidate.total_adjustment_min,
            "delay_min": item.candidate.delay_min,
            "constraint_warning_count": len(item.candidate.constraint_warnings),
            "constraint_violation": round(item.candidate.constraint_violation, 6),
            "constraint_warnings": "; ".join(item.candidate.constraint_warnings),
            "genome_train_offsets_min": json.dumps(dict(item.genome.train_offsets_min), ensure_ascii=False),
            "genome_dwell_extensions_min": json.dumps({f"{train_id}#{seq}": value for train_id, seq, value in item.genome.dwell_extensions_min}, ensure_ascii=False),
        }
        row.update({key: round(value, 6) for key, value in item.objectives.items()})
        rows.append(row)
    return rows


def _plot_evolution_progress(path: Path, generation_log: List[Dict[str, object]]) -> Optional[Path]:
    """函数 _plot_evolution_progress：执行该模块中的相关处理逻辑。"""
    if plt is None or not generation_log:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    generations = [_as_float(row.get("generation")) for row in generation_log]
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    axes[0].plot(
        generations,
        [_as_float(row.get("best_effective_regen_loss_kwh")) for row in generation_log],
        label="最佳有效再生损失（千瓦时）",
        linewidth=1.8,
    )
    axes[0].plot(generations, [_as_float(row.get("best_grid_kwh")) for row in generation_log], label="最佳电网供能（千瓦时）", linewidth=1.8)
    axes[0].set_ylabel("能量（千瓦时）")
    axes[0].grid(True, alpha=0.25)
    axes[0].legend(loc="best")
    axes[1].plot(generations, [_as_float(row.get("pareto_count")) for row in generation_log], label="帕累托方案数", linewidth=1.8)
    axes[1].plot(generations, [_as_float(row.get("min_adjustment_min")) for row in generation_log], label="最小调整量（分钟）", linewidth=1.8)
    axes[1].plot(generations, [_as_float(row.get("avg_constraint_penalty")) for row in generation_log], label="平均约束惩罚", linewidth=1.8)
    axes[1].set_xlabel("迭代代数")
    axes[1].set_ylabel("数量/分钟")
    axes[1].grid(True, alpha=0.25)
    axes[1].legend(loc="best")
    fig.suptitle("NSGA-II 演化进度")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _visualization_failure(key: str, exc: BaseException) -> Dict[str, str]:
    """函数 _visualization_failure：执行该模块中的相关处理逻辑。"""
    return {
        "figure": key,
        "error_type": type(exc).__name__,
        "message": str(exc) or repr(exc),
    }


def _record_visualization_failure(
    errors: List[Dict[str, str]],
    key: str,
    exc: BaseException,
    strict: bool,
) -> None:
    """函数 _record_visualization_failure：执行该模块中的相关处理逻辑。"""
    failure = _visualization_failure(key, exc)
    errors.append(failure)
    if plt is not None:
        plt.close("all")
    message = f"可视化“{key}”失败：{failure['error_type']}：{failure['message']}"
    warnings.warn(message, RuntimeWarning, stacklevel=2)
    if strict:
        raise RuntimeError(message) from exc


def _write_visualization_diagnostics(
    output_dir: Path,
    figure_outputs: Dict[str, str],
    errors: List[Dict[str, str]],
) -> Path:
    """函数 _write_visualization_diagnostics：执行该模块中的相关处理逻辑。"""
    path = output_dir / "visualization_diagnostics.json"
    status = "complete" if not errors else ("partial" if figure_outputs else "failed")
    payload = {
        "status": status,
        "generated_count": len(figure_outputs),
        "error_count": len(errors),
        "figures": figure_outputs,
        "errors": errors,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_nsga_visualizations(
    output_dir: Path,
    generation_log: List[Dict[str, object]],
    figure_outputs: Dict[str, str],
    visualization_errors: List[Dict[str, str]],
    strict: bool = False,
) -> Dict[str, str]:
    """函数 _write_nsga_visualizations：执行该模块中的相关处理逻辑。"""
    figures = dict(figure_outputs)
    _configure_report_font()
    try:
        path = _plot_evolution_progress(output_dir / "figures" / "evolution_progress.png", generation_log)
    except Exception as exc:
        _record_visualization_failure(visualization_errors, "evolution_progress", exc, strict)
        path = None
    if path is not None:
        figures["evolution_progress"] = str(path)
    return figures


def evaluate_candidates(
    candidates: List[CandidatePlan],
    power_sections,
    resource_model=None,
    infrastructure=None,
    default_storage_efficiency: Optional[float] = None,
    storage_device_parameters: Sequence[StorageDeviceParameters] = (),
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """函数 evaluate_candidates：执行该模块中的相关处理逻辑。"""
    candidate_rows: List[Dict[str, object]] = []
    scenario_rows: List[Dict[str, object]] = []
    if infrastructure is None:
        infrastructure = load_infrastructure_profile()
    power_limits = {
        section.section_id: section.electrical_limit
        for section in power_sections
    }
    if resource_model is None:
        resource_model = _timetable_resource_model()
    for candidate in candidates:
        running_arcs = build_timetable_running_arcs(candidate.timetable, infrastructure)
        arc_candidate = _timetable_arc_candidate(running_arcs)
        resource_check = check_timetable_resources(candidate.timetable, resource_model)
        resource_overlap_s = float(
            getattr(
                resource_check,
                "overlap_violation_s",
                sum(conflict.overlap_duration_s for conflict in resource_check.conflicts),
            )
        )
        resource_violation = normalized_resource_constraint_violation(
            resource_check,
            max(1.0, float(resource_model.config.min_depart_headway_s)),
        )
        base_constraint_violation = candidate.constraint_violation + resource_violation
        scenario_electrical_violations: List[float] = []
        conflict_types = sorted({conflict.conflict_type for conflict in resource_check.conflicts})
        conflict_details = "; ".join(
            f"{conflict.conflict_type}:{conflict.resource_id}:{conflict.overlap_duration_s:.1f}s"
            for conflict in resource_check.conflicts
        )
        for scenario in candidate.timetable.scenarios:
            time_slices = energy_time_slice_rows(arc_candidate, _effective_time_step_s(scenario))
            _, issues, summary = evaluate_scenario_time_slices(
                time_slices,
                scenario,
                power_limits,
                default_storage_efficiency=default_storage_efficiency,
                storage_device_parameters=storage_device_parameters,
            )
            electrical_violation = _as_float(summary.get("electrical_constraint_violation_kwh"))
            scenario_electrical_violations.append(electrical_violation)
            total_constraint_violation = base_constraint_violation + electrical_violation
            issue_details = [
                {
                    "issue_id": issue.get("issue_id", ""),
                    "issue_type": issue.get("issue_type", ""),
                    "severity": issue.get("severity", ""),
                    "power_arm_id": issue.get("power_arm_id", ""),
                    "time_window_start": issue.get("time_window_start", ""),
                    "time_window_end": issue.get("time_window_end", ""),
                    "estimated_wasted_kwh": issue.get("estimated_wasted_kwh", 0.0),
                    "electrical_excess_kwh": issue.get("electrical_excess_kwh", 0.0),
                    "reason": issue.get("reason", ""),
                    "source": issue.get("source", ""),
                }
                for issue in issues
            ]
            row = {
                "candidate_id": candidate.candidate_id,
                "action_type": candidate.action_type,
                "description": candidate.description,
                "scenario_id": scenario.scenario_id,
                "wasted_kwh_est": summary["wasted_kwh"],
                "effective_regen_loss_kwh_est": summary["effective_regen_loss_kwh"],
                "direct_used_kwh_est": summary["direct_used_kwh"],
                "storage_absorbed_kwh_est": summary["storage_absorbed_kwh"],
                "storage_discharged_kwh_est": summary.get("storage_discharged_kwh", 0.0),
                "storage_efficiency": summary.get("storage_efficiency", default_storage_efficiency),
                "final_soc_kwh_est": summary.get("final_soc_kwh", 0.0),
                "grid_kwh_est": summary["grid_kwh"],
                "issue_count": summary["issue_count"],
                "issue_types": ";".join(sorted({str(issue["issue_type"]) for issue in issue_details})),
                "issue_details_json": json.dumps(issue_details, ensure_ascii=False),
                "energy_event_count": len(time_slices),
                "running_arc_count": len(running_arcs),
                "settlement_window_count": summary["settlement_window_count"],
                "max_shift_min": candidate.max_shift_min,
                "total_adjustment_min": candidate.total_adjustment_min,
                "delay_min": candidate.delay_min,
                "constraint_warning_count": len(candidate.constraint_warnings),
                "basic_constraint_violation": candidate.constraint_violation,
                "resource_constraint_violation": resource_violation,
                "electrical_constraint_violation_kwh": electrical_violation,
                "resource_conflict_count": resource_check.conflict_count,
                "resource_overlap_violation_s": round(resource_overlap_s, 6),
                "resource_conflict_types": ";".join(conflict_types),
                "resource_conflict_details": conflict_details,
                "constraint_violation": total_constraint_violation,
                "feasible": total_constraint_violation <= CONSTRAINT_TOLERANCE,
            }
            scenario_rows.append(row)
        candidate_electrical_violation = max(scenario_electrical_violations, default=0.0)
        total_constraint_violation = base_constraint_violation + candidate_electrical_violation
        candidate_rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "action_type": candidate.action_type,
                "description": candidate.description,
                "max_shift_min": candidate.max_shift_min,
                "total_adjustment_min": candidate.total_adjustment_min,
                "delay_min": candidate.delay_min,
                "constraint_warning_count": len(candidate.constraint_warnings),
                "constraint_warnings": "; ".join(candidate.constraint_warnings),
                "basic_constraint_violation": candidate.constraint_violation,
                "resource_constraint_violation": resource_violation,
                "electrical_constraint_violation_kwh": candidate_electrical_violation,
                "resource_conflict_count": resource_check.conflict_count,
                "resource_overlap_violation_s": round(resource_overlap_s, 6),
                "resource_conflict_types": ";".join(conflict_types),
                "resource_conflict_details": conflict_details,
                "constraint_violation": total_constraint_violation,
                "feasible": total_constraint_violation <= CONSTRAINT_TOLERANCE,
            }
        )
    return candidate_rows, scenario_rows


def candidate_energy_issue_rows(scenario_rows: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    """函数 candidate_energy_issue_rows：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, object]] = []
    for scenario_row in scenario_rows:
        raw_details = scenario_row.get("issue_details_json", "[]")
        try:
            details = json.loads(str(raw_details))
        except (TypeError, ValueError, json.JSONDecodeError):
            details = []
        for issue in details if isinstance(details, list) else []:
            if not isinstance(issue, dict):
                continue
            rows.append(
                {
                    "candidate_id": scenario_row.get("candidate_id", ""),
                    "scenario_id": scenario_row.get("scenario_id", ""),
                    **issue,
                }
            )
    return rows


def scenario_summary_rows(
    scenario_rows: Iterable[Dict[str, object]],
) -> List[Dict[str, object]]:
    """Bound verbose issue JSON in summary CSVs while retaining aggregate KPIs.

    The complete normalized issue list is exported separately to
    ``candidate_energy_issues.csv``.  Ten-second settlement can create thousands
    of issues per candidate, so duplicating all of them into one CSV cell makes
    otherwise valid output unreadable by Python's standard CSV field limit.
    """

    compact_rows: List[Dict[str, object]] = []
    for row in scenario_rows:
        raw_details = row.get("issue_details_json", "[]")
        try:
            details = json.loads(str(raw_details))
        except (TypeError, ValueError, json.JSONDecodeError):
            details = []
        if not isinstance(details, list):
            details = []
        preview = details[:ISSUE_DETAIL_PREVIEW_LIMIT]
        compact_rows.append(
            {
                **row,
                "issue_details_json": json.dumps(preview, ensure_ascii=False),
                "issue_detail_preview_count": len(preview),
                "issue_detail_omitted_count": max(0, len(details) - len(preview)),
            }
        )
    return compact_rows


def _dominates(left: Dict[str, object], right: Dict[str, object]) -> bool:
    """函数 _dominates：执行该模块中的相关处理逻辑。"""
    left_violation = _required_float(left, "constraint_violation")
    right_violation = _required_float(right, "constraint_violation")
    left_feasible = left_violation <= CONSTRAINT_TOLERANCE
    right_feasible = right_violation <= CONSTRAINT_TOLERANCE
    if left_feasible != right_feasible:
        return left_feasible
    if not left_feasible:
        return left_violation < right_violation
    left_effective = _effective_objective_tuple(left)
    right_effective = _effective_objective_tuple(right)
    le_all = all(left_value <= right_value for left_value, right_value in zip(left_effective, right_effective))
    lt_any = any(left_value < right_value for left_value, right_value in zip(left_effective, right_effective))
    return le_all and lt_any


def pareto_rows(scenario_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """函数 pareto_rows：执行该模块中的相关处理逻辑。"""
    result: List[Dict[str, object]] = []
    by_scenario: Dict[str, List[Dict[str, object]]] = {}
    for row in scenario_rows:
        by_scenario.setdefault(str(row["scenario_id"]), []).append(row)
    for scenario_id, rows in by_scenario.items():
        feasible_rows = [
            row
            for row in rows
            if _required_float(row, "constraint_violation") <= CONSTRAINT_TOLERANCE
        ]
        front = [
            row
            for row in feasible_rows
            if not any(_dominates(other, row) for other in feasible_rows if other is not row)
        ]
        seen_objectives: set[Tuple[float, ...]] = set()
        for row in sorted(front, key=lambda item: (_effective_objective_tuple(item), str(item.get("candidate_id", "")))):
            objective_key = _effective_objective_tuple(row)
            if objective_key in seen_objectives:
                continue
            seen_objectives.add(objective_key)
            result.append({**row, "pareto_scenario_id": scenario_id})
    return sorted(
        result,
        key=lambda item: (
            str(item["scenario_id"]),
            float(item["effective_regen_loss_kwh_est"]),
            float(item["total_adjustment_min"]),
        ),
    )


def decide_optimization_action(
    candidate_rows: List[Dict[str, object]],
    scenario_rows: List[Dict[str, object]],
    *,
    scenario_id: str = ACTIVE_SCENARIO_ID,
) -> Dict[str, object]:
    """根据基线和候选结果决定采用优化方案还是保留原运行图。"""
    baseline_rows = [
        row for row in candidate_rows
        if str(row.get("action_type", "")) == "baseline"
        or (
            abs(_as_float(row.get("total_adjustment_min"))) <= OBJECTIVE_TOLERANCES["total_adjustment_min"]
            and abs(_as_float(row.get("max_shift_min"))) <= OBJECTIVE_TOLERANCES["total_adjustment_min"]
        )
    ]
    baseline = baseline_rows[0] if baseline_rows else None
    if baseline is None:
        return {"action": "keep_baseline", "reason": "baseline_result_missing", "selected_candidate_id": ""}
    baseline_id = str(baseline.get("candidate_id", ""))
    active = [
        row for row in scenario_rows
        if str(row.get("scenario_id", "")) == scenario_id
        and _as_float(row.get("constraint_violation")) <= CONSTRAINT_TOLERANCE
    ]
    base_active = [
        row for row in scenario_rows
        if str(row.get("scenario_id", "")) == scenario_id
        and str(row.get("candidate_id", "")) == baseline_id
    ]
    if not base_active:
        return {"action": "keep_baseline", "reason": "baseline_energy_result_missing", "selected_candidate_id": baseline_id}
    if (
        _as_float(baseline.get("constraint_violation")) > CONSTRAINT_TOLERANCE
        or any(_as_float(row.get("constraint_violation")) > CONSTRAINT_TOLERANCE for row in base_active)
    ):
        return {
            "action": "no_feasible_solution",
            "reason": "baseline_infeasible",
            "selected_candidate_id": "",
            "baseline_candidate_id": baseline_id,
        }
    base_loss = max(_as_float(row.get("effective_regen_loss_kwh_est")) for row in base_active)
    base_grid = sum(_as_float(row.get("grid_kwh_est")) for row in base_active) / len(base_active)
    improvements = []
    for row in active:
        candidate_id = str(row.get("candidate_id", ""))
        if candidate_id == baseline_id:
            continue
        loss = max(_as_float(item.get("effective_regen_loss_kwh_est")) for item in active if str(item.get("candidate_id", "")) == candidate_id)
        same_candidate = [item for item in active if str(item.get("candidate_id", "")) == candidate_id]
        grid = sum(_as_float(item.get("grid_kwh_est")) for item in same_candidate) / len(same_candidate)
        loss_gain = base_loss - loss
        grid_gain = base_grid - grid
        if (loss_gain > OBJECTIVE_TOLERANCES["effective_regen_loss_kwh_est"] or grid_gain > OBJECTIVE_TOLERANCES["grid_kwh_est"]) and loss_gain >= -OBJECTIVE_TOLERANCES["effective_regen_loss_kwh_est"] and grid_gain >= -OBJECTIVE_TOLERANCES["grid_kwh_est"]:
            improvements.append((loss_gain + grid_gain, candidate_id, loss_gain, grid_gain))
    if not improvements:
        return {"action": "keep_baseline", "reason": "no_material_energy_improvement", "selected_candidate_id": baseline_id, "baseline_effective_regen_loss_kwh": base_loss, "baseline_grid_kwh": base_grid}
    _, selected_id, loss_gain, grid_gain = max(improvements)
    return {"action": "optimize", "reason": "material_energy_improvement_found", "selected_candidate_id": selected_id, "baseline_effective_regen_loss_kwh": base_loss, "baseline_grid_kwh": base_grid, "effective_regen_loss_improvement_kwh": loss_gain, "grid_improvement_kwh": grid_gain}


def explain_candidate_rows(
    candidate_rows: List[Dict[str, object]],
    scenario_rows: List[Dict[str, object]],
    pareto: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    """Create a compact, human-readable explanation for every candidate.

    This does not alter ranking.  It exposes the decision role, dominant
    constraint/energy bottleneck, and the trade-off that made a candidate
    Pareto or non-Pareto.
    """
    pareto_ids = {str(row.get("candidate_id", "")) for row in pareto}
    by_candidate: Dict[str, List[Dict[str, object]]] = {}
    for row in scenario_rows:
        by_candidate.setdefault(str(row.get("candidate_id", "")), []).append(row)
    feasible = [
        row for row in candidate_rows
        if _as_float(row.get("constraint_violation")) <= CONSTRAINT_TOLERANCE
    ]
    best_feasible_id = ""
    if feasible:
        best_feasible_id = str(min(
            feasible,
            key=lambda row: (
                _as_float(row.get("electrical_constraint_violation_kwh")),
                _as_float(row.get("total_adjustment_min")),
                str(row.get("candidate_id", "")),
            ),
        ).get("candidate_id", ""))
    output: List[Dict[str, object]] = []
    for row in candidate_rows:
        candidate_id = str(row.get("candidate_id", ""))
        violations = {
            "basic_timetable": _as_float(row.get("basic_constraint_violation")),
            "resource": _as_float(row.get("resource_constraint_violation")),
            "electrical": _as_float(row.get("electrical_constraint_violation_kwh")),
        }
        dominant_name, dominant_value = max(violations.items(), key=lambda item: item[1])
        scenarios = by_candidate.get(candidate_id, [])
        worst_issue_count = max((_as_float(item.get("issue_count")) for item in scenarios), default=0.0)
        worst_wasted = max((_as_float(item.get("wasted_kwh_est")) for item in scenarios), default=0.0)
        if candidate_id in pareto_ids:
            role = "pareto_alternative"
            reason = "在能量损失与运行图调整之间形成可行的非支配权衡"
        elif _as_float(row.get("constraint_violation")) > CONSTRAINT_TOLERANCE:
            role = "infeasible_diagnostic"
            reason = f"不可行；主要约束违反={dominant_name}:{dominant_value:.6g}"
        elif candidate_id == best_feasible_id:
            role = "best_feasible_reference"
            reason = "在电气约束违反最小的候选中，调整量最小的可行参考方案"
        else:
            role = "feasible_dominated"
            reason = "方案可行，但在当前目标容差下被支配或吸引力较低"
        output.append({
            "candidate_id": candidate_id,
            "decision_role": role,
            "explanation": reason,
            "feasible": bool(row.get("feasible", False)),
            "dominant_constraint": dominant_name if dominant_value > CONSTRAINT_TOLERANCE else "none",
            "dominant_constraint_value": round(dominant_value, 6),
            "max_scenario_issue_count": int(worst_issue_count),
            "max_scenario_wasted_kwh_est": round(worst_wasted, 6),
            "pareto_member": candidate_id in pareto_ids,
            "action_type": row.get("action_type", ""),
            "description": row.get("description", ""),
            "total_adjustment_min": row.get("total_adjustment_min", 0.0),
            "constraint_violation": row.get("constraint_violation", 0.0),
        })
    return output


def timetable_rows(timetable: CanonicalTimetable) -> List[Dict[str, object]]:
    """函数 timetable_rows：执行该模块中的相关处理逻辑。"""
    rows = []
    for stop in sorted(timetable.stops, key=lambda item: (item.train_id, item.seq)):
        rows.append(
            {
                "train_id": stop.train_id,
                "seq": stop.seq,
                "station_name": stop.station_name,
                "station_km": stop.station_km,
                "arrival_time": format_s_as_hhmmss(stop.arrival_time_s),
                "departure_time": format_s_as_hhmmss(stop.departure_time_s),
                "stop_type": stop.stop_type,
                "track": stop.track,
                "operation_type": stop.operation_type,
                "note": stop.note,
            }
        )
    return rows


def write_optimizer_report(
    path: Path,
    candidate_count: int,
    scenario_rows: List[Dict[str, object]],
    pareto: List[Dict[str, object]],
    figure_outputs: Optional[Dict[str, str]] = None,
    visualization_errors: Optional[List[Dict[str, str]]] = None,
    optimizer_mode: str = "rule",
    headway_preflight: Optional[Dict[str, object]] = None,
) -> None:
    """函数 write_optimizer_report：执行该模块中的相关处理逻辑。"""
    lines = [
        "# 运行图候选方案优化报告",
        "",
        f"- 优化模式：{_optimizer_display_label(OPTIMIZER_MODE_LABELS, optimizer_mode)}",
        f"- 候选方案数量：{candidate_count}",
        f"- 场景评分记录数：{len(scenario_rows)}",
        f"- 帕累托候选方案数量：{len(pareto)}",
        "",
        "## 帕累托候选方案",
        "",
        "| 候选方案 | 场景 | 有效再生损失估计（千瓦时） | 浪费能量估计（千瓦时） | 问题数 | 最大时移（分钟） | 总调整量（分钟） | 延误（分钟） | 动作 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in pareto[:30]:
        lines.append(
            "| {candidate_id} | {scenario_id} | {effective_regen_loss_kwh_est} | {wasted_kwh_est} | {issue_count} | {max_shift_min} | {total_adjustment_min} | {delay_min} | {action_type} |".format(
                candidate_id=row.get("candidate_id", ""),
                scenario_id=_optimizer_scenario_label(row.get("scenario_id", "")),
                effective_regen_loss_kwh_est=row.get("effective_regen_loss_kwh_est", 0),
                wasted_kwh_est=row.get("wasted_kwh_est", 0),
                issue_count=row.get("issue_count", 0),
                max_shift_min=row.get("max_shift_min", 0),
                total_adjustment_min=row.get("total_adjustment_min", 0),
                delay_min=row.get("delay_min", 0),
                action_type=_optimizer_display_label(OPTIMIZER_ACTION_LABELS, row.get("action_type", "")),
            )
        )
    if figure_outputs:
        lines.extend(["", "## 图表", ""])
        for label, figure_path in figure_outputs.items():
            lines.append(f"- {OPTIMIZER_FIGURE_LABELS.get(label, label)}：`{figure_path}`")
    if visualization_errors:
        lines.extend(["", "## 可视化失败", ""])
        for failure in visualization_errors:
            lines.append(
                f"- {OPTIMIZER_FIGURE_LABELS.get(str(failure.get('figure', '')), failure.get('figure', ''))}："
                f"{failure.get('error_type', '')}：{failure.get('message', '')}"
            )
    if headway_preflight and headway_preflight["blocking_pair_count"]:
        lines.extend([
            "",
            "## 始发间隔预检",
            "",
            f"当前同向最小始发间隔为 {headway_preflight['minimum_gap_s']} 秒。",
            f"允许的时移和始发站停调整最多可拉开两车 {headway_preflight['max_departure_separation_increase_s']} 秒。",
            f"共有 {headway_preflight['blocking_pair_count']} 对相邻同向列车在该范围内仍无法满足约束。",
            "本轮只评价基线供诊断，详细车次和缺口见优化摘要。",
        ])
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- `rule` 模式为规则生成的候选方案模型；`nsga2` 模式为多目标遗传优化原型。",
            "- 候选动作包括全列车时移、停站延长和基于事件的时刻重排。",
            "- 硬约束检查包括停站顺序、运行方向、时间单调性、到发时刻一致性、同向发车间隔、站场股道容量、咽喉并发和区段占用。",
            "- 帕累托比较采用业务容差：有效再生损失/电网能耗为 0.01 千瓦时，运行图调整量为 0.01 分钟；更小差异视为数值噪声。",
            "- 每个候选方案的详细能量问题输出在 `candidate_energy_issues.csv`。",
            "- 站场股道容量优先采用已审核或 PDF 提取的数量；咽喉、进路锁闭和信号闭塞容量在正式数据确认前仍明确标记为启发式默认值。",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _scenario_color_map(scenario_ids: List[str]) -> Dict[str, object]:
    """函数 _scenario_color_map：执行该模块中的相关处理逻辑。"""
    if plt is None:
        return {}
    cmap = plt.get_cmap("tab10")
    return {scenario_id: cmap(idx % 10) for idx, scenario_id in enumerate(sorted(set(scenario_ids)))}


def _plot_pareto_front(path: Path, scenario_rows: List[Dict[str, object]], pareto: List[Dict[str, object]]) -> Optional[Path]:
    """函数 _plot_pareto_front：执行该模块中的相关处理逻辑。"""
    if plt is None or not scenario_rows:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    scenario_ids = [str(row.get("scenario_id", "")) for row in scenario_rows]
    colors = _scenario_color_map(scenario_ids)
    pareto_keys = {(str(row.get("candidate_id", "")), str(row.get("scenario_id", ""))) for row in pareto}
    fig, ax = plt.subplots(figsize=(10, 6))
    for scenario_id in sorted(set(scenario_ids)):
        rows = [row for row in scenario_rows if str(row.get("scenario_id", "")) == scenario_id]
        ax.scatter(
            [_as_float(row.get("total_adjustment_min")) for row in rows],
            [_as_float(row.get("effective_regen_loss_kwh_est")) for row in rows],
            s=[40 + 18 * _as_float(row.get("issue_count")) for row in rows],
            alpha=0.45,
            color=colors.get(scenario_id),
            label=_optimizer_scenario_label(scenario_id),
        )
    pareto_rows_local = [row for row in scenario_rows if (str(row.get("candidate_id", "")), str(row.get("scenario_id", ""))) in pareto_keys]
    if pareto_rows_local:
        ax.scatter(
            [_as_float(row.get("total_adjustment_min")) for row in pareto_rows_local],
            [_as_float(row.get("effective_regen_loss_kwh_est")) for row in pareto_rows_local],
            s=120,
            facecolors="none",
            edgecolors="black",
            linewidths=1.6,
            label="帕累托方案",
        )
    ax.set_title("候选方案帕累托权衡")
    ax.set_xlabel("总调整量（分钟）")
    ax.set_ylabel("有效再生损失（千瓦时）")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _plot_candidate_adjustments(path: Path, candidate_rows: List[Dict[str, object]]) -> Optional[Path]:
    """函数 _plot_candidate_adjustments：执行该模块中的相关处理逻辑。"""
    if plt is None or not candidate_rows:
        return None
    rows = sorted(candidate_rows, key=lambda row: _as_float(row.get("total_adjustment_min")))[:20]
    labels = [str(row.get("candidate_id", "")) for row in rows]
    total_adjustment = [_as_float(row.get("total_adjustment_min")) for row in rows]
    max_shift = [_as_float(row.get("max_shift_min")) for row in rows]
    delay = [_as_float(row.get("delay_min")) for row in rows]
    x = list(range(len(rows)))
    width = 0.25
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar([i - width for i in x], total_adjustment, width=width, label="总调整量")
    ax.bar(x, max_shift, width=width, label="最大时移")
    ax.bar([i + width for i in x], delay, width=width, label="延误")
    ax.set_title("候选方案调整量对比")
    ax.set_ylabel("分钟")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _plot_scenario_scores(path: Path, scenario_rows: List[Dict[str, object]]) -> Optional[Path]:
    """函数 _plot_scenario_scores：执行该模块中的相关处理逻辑。"""
    if plt is None or not scenario_rows:
        return None
    scenario_ids = sorted({str(row.get("scenario_id", "")) for row in scenario_rows})
    metrics = [
        ("effective_regen_loss_kwh_est", "有效再生损失"),
        ("wasted_kwh_est", "浪费能量"),
        ("direct_used_kwh_est", "直接利用"),
        ("storage_absorbed_kwh_est", "储能吸收"),
        ("grid_kwh_est", "电网供能"),
    ]
    aggregates: Dict[str, Dict[str, float]] = {}
    for scenario_id in scenario_ids:
        rows = [row for row in scenario_rows if str(row.get("scenario_id", "")) == scenario_id]
        aggregates[scenario_id] = {
            key: sum(_as_float(row.get(key)) for row in rows) / max(1, len(rows))
            for key, _label in metrics
        }
    x = list(range(len(scenario_ids)))
    width = 0.18
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 6))
    for idx, (key, label) in enumerate(metrics):
        offset = (idx - (len(metrics) - 1) / 2) * width
        ax.bar([item + offset for item in x], [aggregates[s][key] for s in scenario_ids], width=width, label=label)
    ax.set_title("各场景候选方案平均评分")
    ax.set_ylabel("能量（千瓦时）")
    ax.set_xticks(x)
    ax.set_xticklabels([_optimizer_scenario_label(item) for item in scenario_ids], rotation=18, ha="right")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def write_optimizer_visualizations(
    output_dir: Path,
    candidate_rows: List[Dict[str, object]],
    scenario_rows: List[Dict[str, object]],
    pareto: List[Dict[str, object]],
    strict: bool = False,
) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
    """函数 write_optimizer_visualizations：执行该模块中的相关处理逻辑。"""
    visual_dir = output_dir / "figures"
    outputs: Dict[str, str] = {}
    errors: List[Dict[str, str]] = []
    if plt is None:
        exc = RuntimeError(f"Matplotlib is unavailable: {MATPLOTLIB_IMPORT_ERROR or 'import failed'}")
        _record_visualization_failure(errors, "matplotlib", exc, strict)
        return outputs, errors
    _configure_report_font()
    plotters = [
        ("pareto_front", lambda: _plot_pareto_front(visual_dir / "pareto_front.png", scenario_rows, pareto)),
        ("candidate_adjustments", lambda: _plot_candidate_adjustments(visual_dir / "candidate_adjustments.png", candidate_rows)),
        ("scenario_score_comparison", lambda: _plot_scenario_scores(visual_dir / "scenario_score_comparison.png", scenario_rows)),
    ]
    for key, plotter in plotters:
        try:
            result = plotter()
        except Exception as exc:
            _record_visualization_failure(errors, key, exc, strict)
            result = None
        if result is not None:
            outputs[key] = str(result)
    return outputs, errors


def _unique_genomes(genomes: Iterable[TimetableGenome], limit: int) -> List[TimetableGenome]:
    """函数 _unique_genomes：执行该模块中的相关处理逻辑。"""
    result: List[TimetableGenome] = []
    seen: set[Tuple[Tuple[Tuple[str, int], ...], Tuple[Tuple[str, int, int], ...]]] = set()
    for genome in genomes:
        signature = _genome_signature(genome)
        if signature in seen:
            continue
        seen.add(signature)
        result.append(genome)
        if len(result) >= limit:
            break
    return result


def initial_nsga_population(
    baseline: CanonicalTimetable,
    population_size: int,
    rng: random.Random,
    max_shift_min: int,
    step_min: int,
    max_dwell_extension_min: int,
) -> List[TimetableGenome]:
    """函数 initial_nsga_population：执行该模块中的相关处理逻辑。"""
    genomes: List[TimetableGenome] = [baseline_genome(baseline)]
    attempts = 0
    while len(_unique_genomes(genomes, population_size)) < population_size and attempts < population_size * 40:
        genomes.append(random_genome(baseline, rng, max_shift_min, step_min, max_dwell_extension_min))
        attempts += 1
    return _unique_genomes(genomes, population_size)


def make_offspring(
    selected: List[EvaluatedIndividual],
    population_size: int,
    rng: random.Random,
    max_shift_min: int,
    step_min: int,
    max_dwell_extension_min: int,
    crossover_rate: float,
    mutation_rate: float,
) -> List[TimetableGenome]:
    """函数 make_offspring：执行该模块中的相关处理逻辑。"""
    if not selected:
        return []
    offspring: List[TimetableGenome] = []
    seen = {_genome_signature(item.genome) for item in selected}
    attempts = 0
    while len(offspring) < population_size and attempts < population_size * 60:
        attempts += 1
        if len(selected) >= 2 and rng.random() < crossover_rate:
            left = tournament_select(selected, rng).genome
            right = tournament_select(selected, rng).genome
            child = crossover_genomes(left, right, rng)
        else:
            child = tournament_select(selected, rng).genome
        child = mutate_genome(child, rng, max_shift_min, step_min, max_dwell_extension_min, mutation_rate)
        signature = _genome_signature(child)
        if signature in seen:
            continue
        seen.add(signature)
        offspring.append(child)
    while len(offspring) < population_size:
        base = rng.choice(selected).genome
        offspring.append(mutate_genome(base, rng, max_shift_min, step_min, max_dwell_extension_min, mutation_rate=1.0))
    return offspring


def optimize_timetable_nsga2(
    baseline: CanonicalTimetable,
    output_dir: Path,
    power_sections,
    max_shift_min: int,
    step_min: int,
    max_dwell_extension_min: int,
    population_size: int,
    generations: int,
    crossover_rate: float,
    mutation_rate: float,
    seed: int,
    resource_model=None,
    infrastructure=None,
    default_storage_efficiency: Optional[float] = None,
    storage_device_parameters: Sequence[StorageDeviceParameters] = (),
    strict_visualizations: bool = False,
) -> Dict[str, object]:
    """函数 optimize_timetable_nsga2：执行该模块中的相关处理逻辑。"""
    (
        max_shift_min,
        step_min,
        max_dwell_extension_min,
        population_size,
        generations,
        crossover_rate,
        mutation_rate,
        seed,
    ) = _validate_nsga_settings(
        max_shift_min=max_shift_min,
        step_min=step_min,
        max_dwell_extension_min=max_dwell_extension_min,
        population_size=population_size,
        generations=generations,
        crossover_rate=crossover_rate,
        mutation_rate=mutation_rate,
        seed=seed,
    )
    rng = random.Random(seed)
    headway_min = _headway_from_constraints(baseline)
    headway_preflight = _departure_headway_preflight(baseline, headway_min, max_shift_min, max_dwell_extension_min)
    search_blocked = bool(headway_preflight["blocking_pair_count"])
    effective_generations = 0 if search_blocked else generations
    population = [baseline_genome(baseline)] if search_blocked else initial_nsga_population(
        baseline,
        population_size=population_size,
        rng=rng,
        max_shift_min=max_shift_min,
        step_min=step_min,
        max_dwell_extension_min=max_dwell_extension_min,
    )
    evaluated, initial_candidate_rows, initial_scenario_rows = evaluate_genome_population(
        baseline,
        population,
        0,
        headway_min,
        power_sections,
        resource_model=resource_model,
        infrastructure=infrastructure,
        default_storage_efficiency=default_storage_efficiency,
        storage_device_parameters=storage_device_parameters,
    )
    baseline_reference = evaluated[0].candidate
    baseline_row = initial_candidate_rows[0]
    baseline_scores = [
        row for row in initial_scenario_rows if row["candidate_id"] == baseline_reference.candidate_id
    ]
    del initial_candidate_rows, initial_scenario_rows
    generation_log: List[Dict[str, object]] = []
    selected: List[EvaluatedIndividual] = []
    for generation in range(effective_generations + 1):
        selected = select_next_generation(evaluated, population_size)
        generation_log.append(_generation_log_row(generation, selected))
        if generation >= effective_generations:
            break
        offspring = make_offspring(
            selected,
            population_size=population_size,
            rng=rng,
            max_shift_min=max_shift_min,
            step_min=step_min,
            max_dwell_extension_min=max_dwell_extension_min,
            crossover_rate=crossover_rate,
            mutation_rate=mutation_rate,
        )
        offspring_eval, _offspring_candidate_rows, _offspring_scenario_rows = evaluate_genome_population(
            baseline,
            offspring,
            generation + 1,
            headway_min,
            power_sections,
            resource_model=resource_model,
            infrastructure=infrastructure,
            default_storage_efficiency=default_storage_efficiency,
            storage_device_parameters=storage_device_parameters,
        )
        evaluated = selected + offspring_eval

    final_genomes = [item.genome for item in selected]
    final_candidates = [
        genome_to_candidate(baseline, genome, f"G{idx:04d}", headway_min)
        for idx, genome in enumerate(final_genomes)
    ]
    if search_blocked:
        baseline_id = final_candidates[0].candidate_id
        candidate_rows = [{**baseline_row, "candidate_id": baseline_id}]
        scenario_rows = [{**row, "candidate_id": baseline_id} for row in baseline_scores]
    else:
        candidate_rows, scenario_rows = evaluate_candidates(
            final_candidates,
            power_sections,
            resource_model=resource_model,
            infrastructure=infrastructure,
            default_storage_efficiency=default_storage_efficiency,
            storage_device_parameters=storage_device_parameters,
        )
    final_candidate_by_id = {candidate.candidate_id: candidate for candidate in final_candidates}
    final_evaluated = [
        EvaluatedIndividual(
            genome=final_genomes[idx],
            candidate=candidate,
            objectives=_candidate_objectives(candidate, scenario_rows),
            rank=selected[idx].rank if idx < len(selected) else 0,
            crowding_distance=selected[idx].crowding_distance if idx < len(selected) else 0.0,
        )
        for idx, candidate in enumerate(final_candidates)
    ]
    selected_final = select_next_generation(final_evaluated, population_size)
    # 基线参与比较，无论它是否留在末代种群。复用首代评分，避免额外结算。
    if population[0] not in final_genomes:
        reference_id = f"G{len(final_candidates):04d}"
        reference = replace(baseline_reference, candidate_id=reference_id, action_type="baseline")
        final_candidate_by_id[reference_id] = reference
        final_candidates.append(reference)
        candidate_rows.append({**baseline_row, "candidate_id": reference_id, "action_type": "baseline"})
        scenario_rows.extend(
            {**row, "candidate_id": reference_id, "action_type": "baseline"}
            for row in baseline_scores
        )
    energy_issue_rows = candidate_energy_issue_rows(scenario_rows)
    scenario_rows = scenario_summary_rows(scenario_rows)
    decision = decide_optimization_action(candidate_rows, scenario_rows)
    pareto = pareto_rows(scenario_rows)
    explanation_rows = explain_candidate_rows(candidate_rows, scenario_rows, pareto)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "candidate_summary.csv", candidate_rows)
    _write_csv(output_dir / "candidate_scenario_scores.csv", scenario_rows)
    _write_csv(
        output_dir / "candidate_energy_issues.csv",
        energy_issue_rows,
        ENERGY_ISSUE_FIELDS,
    )
    _write_csv(output_dir / "pareto_candidates.csv", pareto)
    _write_csv(output_dir / "candidate_explanations.csv", explanation_rows)
    _write_csv(output_dir / "generation_log.csv", generation_log)
    _write_csv(output_dir / "final_population.csv", nsga_population_rows(selected_final))
    figure_outputs, visualization_errors = write_optimizer_visualizations(
        output_dir, candidate_rows, scenario_rows, pareto, strict=strict_visualizations
    )
    figure_outputs = _write_nsga_visualizations(
        output_dir,
        generation_log,
        figure_outputs,
        visualization_errors,
        strict=strict_visualizations,
    )
    visualization_diagnostics = _write_visualization_diagnostics(
        output_dir, figure_outputs, visualization_errors
    )
    write_optimizer_report(
        output_dir / "TIMETABLE_OPTIMIZATION_REPORT.md",
        len(final_candidates),
        scenario_rows,
        pareto,
        figure_outputs,
        visualization_errors,
        optimizer_mode="nsga2",
        headway_preflight=headway_preflight,
    )

    timetable_dir = output_dir / "candidate_timetables"
    timetable_dir.mkdir(parents=True, exist_ok=True)
    for stale_candidate in timetable_dir.glob("*.csv"):
        stale_candidate.unlink()
    for row in pareto[:20]:
        candidate = final_candidate_by_id[str(row["candidate_id"])]
        _write_csv(timetable_dir / f"{candidate.candidate_id}_{row['scenario_id']}.csv", timetable_rows(candidate.timetable))

    summary = {
        "valid": True,
        "optimizer_mode": "nsga2",
        "visualization_status": "complete" if not visualization_errors else ("partial" if figure_outputs else "failed"),
        "visualization_error_count": len(visualization_errors),
        "candidate_count": len(final_candidates),
        "scenario_score_count": len(scenario_rows),
        "pareto_count": len(pareto),
        "optimization_decision": decision,
        "headway_preflight": headway_preflight,
        "feasible_candidate_count": sum(
            _as_float(row.get("constraint_violation")) <= CONSTRAINT_TOLERANCE
            for row in candidate_rows
        ),
        "resource_conflict_candidate_count": sum(
            int(_as_float(row.get("resource_conflict_count"))) > 0
            for row in candidate_rows
        ),
        "population_size": population_size,
        "generations": generations,
        "executed_generations": effective_generations,
        "seed": seed,
        "objective_tolerances": dict(OBJECTIVE_TOLERANCES),
        "outputs": {
            "report": str(output_dir / "TIMETABLE_OPTIMIZATION_REPORT.md"),
            "candidate_summary": str(output_dir / "candidate_summary.csv"),
            "candidate_scenario_scores": str(output_dir / "candidate_scenario_scores.csv"),
            "candidate_energy_issues": str(output_dir / "candidate_energy_issues.csv"),
            "pareto_candidates": str(output_dir / "pareto_candidates.csv"),
            "candidate_explanations": str(output_dir / "candidate_explanations.csv"),
            "generation_log": str(output_dir / "generation_log.csv"),
            "final_population": str(output_dir / "final_population.csv"),
            "candidate_timetables": str(timetable_dir),
            "figures": figure_outputs,
            "visualization_diagnostics": str(visualization_diagnostics),
            "visualization_error_count": len(visualization_errors),
        },
    }
    selected_candidate_id = str(decision.get("selected_candidate_id", ""))
    selected_candidate = final_candidate_by_id.get(selected_candidate_id)
    attribution = write_optimization_attribution(
        output_dir,
        workflow="timetable_optimization",
        summary=summary,
        candidate_rows=candidate_rows,
        pareto_rows=pareto,
        scenario_rows=scenario_rows,
        issue_rows=energy_issue_rows,
        baseline_schedule_rows=timetable_rows(baseline),
        optimized_schedule_rows=(
            timetable_rows(selected_candidate.timetable)
            if selected_candidate is not None
            else timetable_rows(baseline)
        ),
    )
    summary["optimization_attribution"] = attribution
    summary["outputs"]["optimization_attribution_report"] = str(
        output_dir / "OPTIMIZATION_ATTRIBUTION_REPORT.md"
    )
    summary["outputs"]["optimization_attribution_summary"] = str(
        output_dir / "optimization_attribution_summary.json"
    )
    for name in (
        "optimization_kpi_attribution",
        "optimization_candidate_decisions",
        "optimization_candidate_funnel",
        "optimization_bottlenecks",
        "optimization_dimension_attribution",
    ):
        summary["outputs"][name] = str(output_dir / f"{name}.csv")
    return summary


def optimize_timetable(
    input_path: Path,
    output_dir: Path,
    power_arm_path: Optional[Path] = None,
    max_shift_min: int = 30,
    step_min: int = 5,
    max_dwell_extension_min: int = 15,
    max_candidates: int = 120,
    mode: str = "rule",
    population_size: int = 60,
    generations: int = 30,
    crossover_rate: float = 0.8,
    mutation_rate: float = 0.12,
    seed: int = 42,
    resource_data_dir: Path = DEFAULT_RESOURCE_DATA_DIR,
    strict_visualizations: bool = False,
) -> Dict[str, object]:
    """函数 optimize_timetable：执行该模块中的相关处理逻辑。"""
    mode = str(mode).strip().lower()
    if mode not in {"rule", "nsga2"}:
        raise ValueError(f"Unsupported optimization mode: {mode!r}")
    max_shift_min = _whole_setting(max_shift_min, "max_shift_min", minimum=0)
    step_min = _whole_setting(step_min, "step_min", minimum=1)
    max_dwell_extension_min = _whole_setting(
        max_dwell_extension_min, "max_dwell_extension_min", minimum=0
    )
    max_candidates = _whole_setting(max_candidates, "max_candidates", minimum=1)
    if mode == "nsga2":
        (
            max_shift_min,
            step_min,
            max_dwell_extension_min,
            population_size,
            generations,
            crossover_rate,
            mutation_rate,
            seed,
        ) = _validate_nsga_settings(
            max_shift_min=max_shift_min,
            step_min=step_min,
            max_dwell_extension_min=max_dwell_extension_min,
            population_size=population_size,
            generations=generations,
            crossover_rate=crossover_rate,
            mutation_rate=mutation_rate,
            seed=seed,
        )
    baseline = _with_active_scenarios(load_canonical_timetable(input_path))
    if not baseline.validation_report.is_valid:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "valid": False,
            "error": "Input timetable validation failed.",
            "validation": baseline.validation_report.summary(),
        }
        (output_dir / "optimizer_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
    # 优化器目标针对批准的 storage_no_direct 场景定义。没有该场景的运行图不能作为有效的零分优化，
    # 否则会跳过全部能量和电气约束评价，却输出看似可行的候选。
    if not baseline.scenarios:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "valid": False,
            "error_code": "missing_active_energy_scenario",
            "error": (
                "Input timetable must contain the storage_no_direct energy scenario "
                "for optimization; no energy scores were computed."
            ),
            "input_path": str(input_path),
            "validation": baseline.validation_report.summary(),
        }
        (output_dir / "optimizer_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary

    resource_data_dir = Path(resource_data_dir)
    power_arm_path = (
        Path(power_arm_path)
        if power_arm_path is not None
        else resource_data_dir / DEFAULT_POWER_ARM_XLSX.name
    )
    try:
        power_sections = load_power_sections(power_arm_path)
    except (OSError, ValueError, csv.Error) as exc:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "valid": False,
            "error_code": "invalid_power_arm_data",
            "error": f"Power-arm data could not be loaded: {exc}",
            "input_path": str(input_path),
            "power_arm_path": str(power_arm_path),
        }
        (output_dir / "optimizer_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary
    if not power_sections:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "valid": False,
            "error_code": "missing_or_empty_power_arm_data",
            "error": "Power-arm data is required and must contain at least one valid mainline section.",
            "input_path": str(input_path),
            "power_arm_path": str(power_arm_path),
            "power_section_count": 0,
        }
        (output_dir / "optimizer_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary

    resource_model = _timetable_resource_model(str(resource_data_dir))
    infrastructure = load_infrastructure_profile(resource_data_dir)
    storage_efficiency = load_storage_efficiency(resource_data_dir)
    storage_device_parameters = load_storage_device_parameters(resource_data_dir)
    storage_parameter_rows = [asdict(item) for item in storage_device_parameters]
    if mode == "nsga2":
        summary = optimize_timetable_nsga2(
            baseline,
            output_dir,
            power_sections,
            max_shift_min=max_shift_min,
            step_min=step_min,
            max_dwell_extension_min=max_dwell_extension_min,
            population_size=population_size,
            generations=generations,
            crossover_rate=crossover_rate,
            mutation_rate=mutation_rate,
            seed=seed,
            resource_model=resource_model,
            infrastructure=infrastructure,
            default_storage_efficiency=storage_efficiency,
            storage_device_parameters=storage_device_parameters,
            strict_visualizations=strict_visualizations,
        )
        summary["input_path"] = str(input_path)
        summary["resource_data_dir"] = str(resource_data_dir)
        summary["storage_efficiency"] = storage_efficiency
        summary["storage_device_parameters"] = storage_parameter_rows
        (output_dir / "optimizer_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    headway_preflight = _departure_headway_preflight(
        baseline, _headway_from_constraints(baseline), max_shift_min, max_dwell_extension_min
    )
    search_blocked = bool(headway_preflight["blocking_pair_count"])
    candidates = generate_candidates(
        baseline,
        power_sections,
        max_shift_min=0 if search_blocked else max_shift_min,
        step_min=step_min,
        max_dwell_extension_min=0 if search_blocked else max_dwell_extension_min,
        max_candidates=1 if search_blocked else max_candidates,
    )
    candidate_rows, scenario_rows = evaluate_candidates(
        candidates,
        power_sections,
        resource_model=resource_model,
        infrastructure=infrastructure,
        default_storage_efficiency=storage_efficiency,
        storage_device_parameters=storage_device_parameters,
    )
    energy_issue_rows = candidate_energy_issue_rows(scenario_rows)
    scenario_rows = scenario_summary_rows(scenario_rows)
    decision = decide_optimization_action(candidate_rows, scenario_rows)
    pareto = pareto_rows(scenario_rows)
    explanation_rows = explain_candidate_rows(candidate_rows, scenario_rows, pareto)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "candidate_summary.csv", candidate_rows)
    _write_csv(output_dir / "candidate_scenario_scores.csv", scenario_rows)
    _write_csv(
        output_dir / "candidate_energy_issues.csv",
        energy_issue_rows,
        ENERGY_ISSUE_FIELDS,
    )
    _write_csv(output_dir / "pareto_candidates.csv", pareto)
    _write_csv(output_dir / "candidate_explanations.csv", explanation_rows)
    figure_outputs, visualization_errors = write_optimizer_visualizations(
        output_dir, candidate_rows, scenario_rows, pareto, strict=strict_visualizations
    )
    visualization_diagnostics = _write_visualization_diagnostics(
        output_dir, figure_outputs, visualization_errors
    )
    write_optimizer_report(
        output_dir / "TIMETABLE_OPTIMIZATION_REPORT.md",
        len(candidates),
        scenario_rows,
        pareto,
        figure_outputs,
        visualization_errors,
        optimizer_mode="rule",
        headway_preflight=headway_preflight,
    )

    timetable_dir = output_dir / "candidate_timetables"
    timetable_dir.mkdir(parents=True, exist_ok=True)
    for stale_candidate in timetable_dir.glob("*.csv"):
        stale_candidate.unlink()
    for row in pareto[:20]:
        candidate = next(item for item in candidates if item.candidate_id == row["candidate_id"])
        _write_csv(timetable_dir / f"{candidate.candidate_id}_{row['scenario_id']}.csv", timetable_rows(candidate.timetable))

    summary = {
        "valid": True,
        "optimizer_mode": "rule",
        "visualization_status": "complete" if not visualization_errors else ("partial" if figure_outputs else "failed"),
        "visualization_error_count": len(visualization_errors),
        "input_path": str(input_path),
        "resource_data_dir": str(resource_data_dir),
        "storage_efficiency": storage_efficiency,
        "storage_device_parameters": storage_parameter_rows,
        "candidate_count": len(candidates),
        "scenario_score_count": len(scenario_rows),
        "pareto_count": len(pareto),
        "optimization_decision": decision,
        "headway_preflight": headway_preflight,
        "outputs": {
            "report": str(output_dir / "TIMETABLE_OPTIMIZATION_REPORT.md"),
            "candidate_summary": str(output_dir / "candidate_summary.csv"),
            "candidate_scenario_scores": str(output_dir / "candidate_scenario_scores.csv"),
            "candidate_energy_issues": str(output_dir / "candidate_energy_issues.csv"),
            "pareto_candidates": str(output_dir / "pareto_candidates.csv"),
            "candidate_explanations": str(output_dir / "candidate_explanations.csv"),
            "candidate_timetables": str(timetable_dir),
            "figures": figure_outputs,
            "visualization_diagnostics": str(visualization_diagnostics),
            "visualization_error_count": len(visualization_errors),
        },
    }
    selected_candidate_id = str(decision.get("selected_candidate_id", ""))
    selected_candidate = next(
        (item for item in candidates if item.candidate_id == selected_candidate_id),
        None,
    )
    attribution = write_optimization_attribution(
        output_dir,
        workflow="timetable_optimization",
        summary=summary,
        candidate_rows=candidate_rows,
        pareto_rows=pareto,
        scenario_rows=scenario_rows,
        issue_rows=energy_issue_rows,
        baseline_schedule_rows=timetable_rows(baseline),
        optimized_schedule_rows=(
            timetable_rows(selected_candidate.timetable)
            if selected_candidate is not None
            else timetable_rows(baseline)
        ),
    )
    summary["optimization_attribution"] = attribution
    summary["outputs"]["optimization_attribution_report"] = str(
        output_dir / "OPTIMIZATION_ATTRIBUTION_REPORT.md"
    )
    summary["outputs"]["optimization_attribution_summary"] = str(
        output_dir / "optimization_attribution_summary.json"
    )
    for name in (
        "optimization_kpi_attribution",
        "optimization_candidate_decisions",
        "optimization_candidate_funnel",
        "optimization_bottlenecks",
        "optimization_dimension_attribution",
    ):
        summary["outputs"][name] = str(output_dir / f"{name}.csv")
    (output_dir / "optimizer_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Generate candidate timetable optimizations and Pareto options.")
    parser.add_argument("input_path", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--power-arm-path", type=Path, default=None)
    parser.add_argument(
        "--data-dir",
        "--resource-data-dir",
        dest="resource_data_dir",
        type=Path,
        default=DEFAULT_RESOURCE_DATA_DIR,
    )
    parser.add_argument("--mode", choices=("rule", "nsga2"), default="rule")
    parser.add_argument("--max-shift-min", type=int, default=30)
    parser.add_argument("--step-min", type=int, default=5)
    parser.add_argument("--max-dwell-extension-min", type=int, default=15)
    parser.add_argument("--max-candidates", type=int, default=120)
    parser.add_argument("--population-size", type=int, default=60)
    parser.add_argument("--generations", type=int, default=30)
    parser.add_argument("--crossover-rate", type=float, default=0.8)
    parser.add_argument("--mutation-rate", type=float, default=0.12)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--strict-visualizations",
        action="store_true",
        help="Fail the optimization if any expected chart cannot be generated.",
    )
    args = parser.parse_args()

    summary = optimize_timetable(
        args.input_path,
        args.output_dir,
        power_arm_path=args.power_arm_path,
        max_shift_min=args.max_shift_min,
        step_min=args.step_min,
        max_dwell_extension_min=args.max_dwell_extension_min,
        max_candidates=args.max_candidates,
        mode=args.mode,
        population_size=args.population_size,
        generations=args.generations,
        crossover_rate=args.crossover_rate,
        mutation_rate=args.mutation_rate,
        seed=args.seed,
        resource_data_dir=args.resource_data_dir,
        strict_visualizations=args.strict_visualizations,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary.get("valid", False):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
