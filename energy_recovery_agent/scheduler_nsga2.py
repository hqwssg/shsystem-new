# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple
import bisect
from collections import OrderedDict
import math
from threading import RLock

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.problem import ElementwiseProblem
    from pymoo.operators.crossover.sbx import SBX
    from pymoo.operators.mutation.pm import PM
    from pymoo.operators.repair.rounding import RoundingRepair
    from pymoo.operators.sampling.rnd import IntegerRandomSampling
    from pymoo.optimize import minimize
    from pymoo.termination import get_termination
except ImportError:  # pragma: no cover - 使用优化器时会输出明确提示。
    NSGA2 = None

    class ElementwiseProblem:  # type: ignore[no-redef]
        """Small evaluation-only fallback when optional pymoo is unavailable.

        Constraint and settlement smoke checks construct ``TrainScheduleProblem``
        directly even without running NSGA-II.  Falling back to ``object`` made
        its ``super().__init__(...)`` call fail with an unrelated TypeError.
        The fallback stores the problem metadata used by the local evaluator;
        :func:`main` still refuses to run the optimizer until pymoo is installed.
        """

        def __init__(self, **kwargs) -> None:
            """函数 __init__：执行该模块中的相关处理逻辑。"""
            for key, value in kwargs.items():
                setattr(self, key, value)

    SBX = None
    PM = None
    RoundingRepair = None
    IntegerRandomSampling = None
    minimize = None
    get_termination = None

from energy_settlement import EnergySettlementSystem, PowerSample
from operating_conditions import OPEN_ENDED_TIME_S, is_time_dependent
from power_arm_lookup import find_power_arm_id, load_power_arm_intervals
from power_arm_electrical_limits import (
    DEFAULT_POWER_ARM_INTERVAL_PATH,
    StorageSectionInterval,
    load_storage_section_intervals,
    power_arm_file_revision,
    storage_section_for_position,
)
from train_simulator import (
    TrainParameters,
    load_config,
    route_simulation_fingerprint,
    run_train_simulation,
    train_range_ratio,
    train_sample_positions,
)


# 模块级有界缓存，用于相同列车/线路/储能构建结果；通过 clear_power_cache_memo() 清空。
# 长时间运行的服务可能评价大量线路、天气、储能和步长组合，无界字典会永久保留所有完整轨迹。
_POWER_CACHE_MEMO_MAX_ENTRIES = 64
_POWER_CACHE_MEMO: "OrderedDict[tuple, PowerSeriesCache]" = OrderedDict()
_POWER_CACHE_MEMO_LOCK = RLock()
_POWER_CACHE_MEMO_HITS = 0
_POWER_CACHE_MEMO_MISSES = 0
_POWER_CACHE_MEMO_EVICTIONS = 0
_RAW_TRAJECTORY_MEMO_MAX_ENTRIES = 32
_RAW_TRAJECTORY_MEMO: "OrderedDict[tuple, tuple]" = OrderedDict()


def clear_power_cache_memo() -> None:
    """Drop memoized power caches (useful in tests and long multi-case suites)."""

    global _POWER_CACHE_MEMO_HITS, _POWER_CACHE_MEMO_MISSES, _POWER_CACHE_MEMO_EVICTIONS
    with _POWER_CACHE_MEMO_LOCK:
        _POWER_CACHE_MEMO.clear()
        _RAW_TRAJECTORY_MEMO.clear()
        _POWER_CACHE_MEMO_HITS = 0
        _POWER_CACHE_MEMO_MISSES = 0
        _POWER_CACHE_MEMO_EVICTIONS = 0


def power_cache_memo_stats() -> dict:
    """Return hit/miss counters for build_power_cache memoization."""

    with _POWER_CACHE_MEMO_LOCK:
        return {
            "entries": len(_POWER_CACHE_MEMO),
            "capacity": int(_POWER_CACHE_MEMO_MAX_ENTRIES),
            "hits": int(_POWER_CACHE_MEMO_HITS),
            "misses": int(_POWER_CACHE_MEMO_MISSES),
            "evictions": int(_POWER_CACHE_MEMO_EVICTIONS),
        }


def _power_cache_memo_get(key: tuple) -> Any | None:
    """Read a memo entry and promote it in the bounded LRU."""

    global _POWER_CACHE_MEMO_HITS
    with _POWER_CACHE_MEMO_LOCK:
        cached = _POWER_CACHE_MEMO.get(key)
        if cached is None:
            return None
        _POWER_CACHE_MEMO.move_to_end(key)
        _POWER_CACHE_MEMO_HITS += 1
        return cached


def _power_cache_memo_store(key: tuple, cache: "PowerSeriesCache") -> "PowerSeriesCache":
    """Store a cache entry, retaining the winner if another thread raced us."""

    global _POWER_CACHE_MEMO_EVICTIONS
    with _POWER_CACHE_MEMO_LOCK:
        existing = _POWER_CACHE_MEMO.get(key)
        if existing is not None:
            _POWER_CACHE_MEMO.move_to_end(key)
            return existing
        _POWER_CACHE_MEMO[key] = cache
        _POWER_CACHE_MEMO.move_to_end(key)
        while len(_POWER_CACHE_MEMO) > max(1, int(_POWER_CACHE_MEMO_MAX_ENTRIES)):
            _POWER_CACHE_MEMO.popitem(last=False)
            _POWER_CACHE_MEMO_EVICTIONS += 1
        return cache


def _raw_trajectory_key(
    train: TrainParameters,
    route,
    start_time_s: int,
    force_time_independent: bool,
    simulation_step_s: float,
) -> tuple:
    """构造不含储能区段的动力学轨迹缓存键。"""

    base_route = replace(route, energy_transfer_ranges_km=[])
    return _power_cache_memo_key(
        train,
        base_route,
        start_time_s,
        force_time_independent,
        simulation_step_s,
        None,
        (),
    )


def _raw_trajectory_get(key: tuple) -> tuple | None:
    with _POWER_CACHE_MEMO_LOCK:
        records = _RAW_TRAJECTORY_MEMO.get(key)
        if records is not None:
            _RAW_TRAJECTORY_MEMO.move_to_end(key)
        return records


def _raw_trajectory_store(key: tuple, records: tuple) -> tuple:
    with _POWER_CACHE_MEMO_LOCK:
        existing = _RAW_TRAJECTORY_MEMO.get(key)
        if existing is not None:
            _RAW_TRAJECTORY_MEMO.move_to_end(key)
            return existing
        _RAW_TRAJECTORY_MEMO[key] = records
        _RAW_TRAJECTORY_MEMO.move_to_end(key)
        while len(_RAW_TRAJECTORY_MEMO) > _RAW_TRAJECTORY_MEMO_MAX_ENTRIES:
            _RAW_TRAJECTORY_MEMO.popitem(last=False)
        return records


def _power_cache_memo_key(
    train: TrainParameters,
    route,
    start_time_s: int,
    force_time_independent: bool,
    simulation_step_s: float,
    power_arm_interval_path,
    storage_sections,
) -> tuple:
    """Stable key for identical trajectory rebuilds."""

    storage_key = tuple(
        (
            float(getattr(section, "start_km", 0.0)),
            float(getattr(section, "end_km", 0.0)),
            str(getattr(section, "section_id", "") or getattr(section, "storage_section_id", "") or ""),
            str(getattr(section, "direction", "") or ""),
        )
        for section in (tuple(storage_sections) if storage_sections is not None else ())
    )
    route_key = route_simulation_fingerprint(route)
    train_key = (
        str(getattr(train, "name", "") or ""),
        float(getattr(train, "mass_tons", 0.0) or 0.0),
        float(getattr(train, "max_traction_kN", 0.0) or 0.0),
        float(getattr(train, "max_brake_kN", 0.0) or 0.0),
        float(getattr(train, "rotational_mass_factor", 0.0) or 0.0),
        float(getattr(getattr(train, "davis", None), "a", 0.0) or 0.0),
        float(getattr(getattr(train, "davis", None), "b", 0.0) or 0.0),
        float(getattr(getattr(train, "davis", None), "c", 0.0) or 0.0),
        float(getattr(train, "length_km", 0.0) or 0.0),
        int(getattr(train, "longitudinal_segments", 1) or 1),
        str(getattr(train, "direction", "") or ""),
        float(getattr(train, "traction_adhesion_weight_fraction", 1.0) or 0.0),
        float(getattr(train, "brake_adhesion_weight_fraction", 1.0) or 0.0),
        float(getattr(train, "max_power_kW", 0.0) or 0.0),
        float(getattr(train, "power_scale", 1.0) or 1.0),
        str(getattr(train, "locomotive_type", "") or ""),
        int(getattr(train, "locomotive_count", 0) or 0),
        tuple(getattr(train, "locomotive_consist", ()) or ()),
        str(getattr(train, "freight_load_state", "") or ""),
        float(getattr(train, "vehicle_mass_tons", 0.0) or 0.0),
    )
    return (
        train_key,
        route_key,
        _whole_second_value(start_time_s, "start_time_s"),
        bool(force_time_independent),
        _positive_whole_seconds(simulation_step_s, "simulation_step_s"),
        power_arm_file_revision(
            power_arm_interval_path
            if power_arm_interval_path is not None
            else DEFAULT_POWER_ARM_INTERVAL_PATH
        ),
        storage_key,
    )


@dataclass(frozen=True)
class PowerSeriesCache:
    """Cache base trajectory and power series for a train type."""

    times: List[int]
    powers_kW: List[float]
    energy_transfer_ratios: List[float]
    power_arm_ids: List[str]
    positions_km: List[float]
    speeds_mps: List[float]
    train_length_km: float
    direction: str
    adhesion_coefficients: List[float]
    speed_limits_mps: List[float]
    brake_decelerations_mps2: List[float]
    storage_section_ids: List[str] = field(default_factory=list, compare=False, repr=False)
    power_allocation_ratios: List[Dict[Tuple[str, str], float]] = field(
        default_factory=list,
        compare=False,
        repr=False,
    )
    route: Any | None = None
    train: TrainParameters | None = None
    start_time_s: int = 0
    simulation_step_s: int = 5
    time_dependent_conditions: bool = False
    power_arm_interval_path: Path | None = field(default=None, compare=False, repr=False)
    storage_sections: Tuple[StorageSectionInterval, ...] = field(default_factory=tuple, compare=False, repr=False)
    _departure_cache: Dict[int, "PowerSeriesCache"] = field(default_factory=dict, compare=False, repr=False)
    _stable_condition_cache: Dict[str, "PowerSeriesCache"] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )
    _base_series_cache: Dict[int, Dict[int, PowerSample]] = field(default_factory=dict, compare=False, repr=False)
    _component_series_cache: Dict[int, List[Dict[int, PowerSample]]] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )
    # 资源检查会在大量相邻候选中重复查询相同站点的穿越时刻和储能首入时刻。
    # 时间相关工况使用发车时刻区分键；时间不变工况共享同一轨迹查询结果。
    _crossing_elapsed_cache: Dict[Tuple[int, float], int | float | None] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )
    _first_storage_entry_cache: Dict[int, int | None] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        if type(self.time_dependent_conditions) is not bool:
            raise ValueError("time_dependent_conditions must be a boolean")
        series_fields = (
            "powers_kW",
            "energy_transfer_ratios",
            "power_arm_ids",
            "positions_km",
            "speeds_mps",
            "adhesion_coefficients",
            "speed_limits_mps",
            "brake_decelerations_mps2",
        )
        expected_length = len(self.times)
        for field_name in series_fields:
            if len(getattr(self, field_name)) != expected_length:
                raise ValueError(
                    f"{field_name} length must match times length {expected_length}"
                )
        if self.storage_section_ids and len(self.storage_section_ids) != expected_length:
            raise ValueError(
                f"storage_section_ids length must be zero or match times length {expected_length}"
            )
        if self.power_allocation_ratios and len(self.power_allocation_ratios) != expected_length:
            raise ValueError(
                "power_allocation_ratios length must be zero or match times length "
                f"{expected_length}"
            )
        for index, allocations in enumerate(self.power_allocation_ratios):
            if not isinstance(allocations, dict) or not allocations:
                raise ValueError(f"power_allocation_ratios[{index}] must be a non-empty dictionary")
            total_ratio = 0.0
            for key, raw_ratio in allocations.items():
                if not isinstance(key, tuple) or len(key) != 2:
                    raise ValueError(
                        f"power_allocation_ratios[{index}] keys must be (power_arm_id, storage_section_id)"
                    )
                if isinstance(raw_ratio, bool):
                    raise ValueError(f"power_allocation_ratios[{index}] ratios must be finite and non-negative")
                ratio = float(raw_ratio)
                if not math.isfinite(ratio) or ratio < 0.0:
                    raise ValueError(f"power_allocation_ratios[{index}] ratios must be finite and non-negative")
                total_ratio += ratio
            if not math.isclose(total_ratio, 1.0, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError(
                    f"power_allocation_ratios[{index}] ratios must sum to 1, got {total_ratio}"
                )

        normalized_times = [_non_negative_whole_seconds(value, "cache time") for value in self.times]
        if any(right <= left for left, right in zip(normalized_times[:-1], normalized_times[1:])):
            raise ValueError("PowerSeriesCache times must be strictly increasing")
        if normalized_times != self.times:
            raise ValueError("PowerSeriesCache times must contain integer seconds")

        finite_fields = (
            "powers_kW",
            "energy_transfer_ratios",
            "positions_km",
            "speeds_mps",
            "adhesion_coefficients",
            "speed_limits_mps",
            "brake_decelerations_mps2",
        )
        for field_name in finite_fields:
            for value in getattr(self, field_name):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ValueError(f"{field_name} must contain only finite numeric values")
        if any(not 0.0 <= float(value) <= 1.0 for value in self.energy_transfer_ratios):
            raise ValueError("energy_transfer_ratios must be between 0 and 1")
        if any(float(value) < 0.0 for value in self.speeds_mps):
            raise ValueError("speeds_mps must be non-negative")
        if any(float(value) < 0.0 for value in self.speed_limits_mps):
            raise ValueError("speed_limits_mps must be non-negative")
        if any(float(value) <= 0.0 for value in self.adhesion_coefficients):
            raise ValueError("adhesion_coefficients must be positive")
        if any(float(value) <= 0.0 for value in self.brake_decelerations_mps2):
            raise ValueError("brake_decelerations_mps2 must be positive")
        if (
            isinstance(self.train_length_km, bool)
            or not isinstance(self.train_length_km, (int, float))
            or not math.isfinite(float(self.train_length_km))
            or float(self.train_length_km) < 0.0
        ):
            # ``TrainParameters`` 和数据导入契约允许在简化/虚拟场景中使用长度为零的质点列车。
            # 此时缓存只有一个纵向样本，在这里拒绝会导致直接仿真正常、但优化器失败。
            raise ValueError("train_length_km must be finite and non-negative")
        if self.direction not in {"forward", "reverse"}:
            raise ValueError("direction must be 'forward' or 'reverse'")
        object.__setattr__(
            self,
            "start_time_s",
            _non_negative_whole_seconds(self.start_time_s, "start_time_s"),
        )
        object.__setattr__(
            self,
            "simulation_step_s",
            _positive_whole_seconds(self.simulation_step_s, "simulation_step_s"),
        )

    def _trajectory_for_departure(self, depart_time_s: int) -> "PowerSeriesCache":
        """函数 _trajectory_for_departure：执行该模块中的相关处理逻辑。"""
        depart_time_s = _non_negative_whole_seconds(depart_time_s, "depart_time_s")
        if not self.time_dependent_conditions:
            return self
        if depart_time_s == self.start_time_s:
            return self
        if self.route is None or self.train is None:
            return self

        # 晚于最后一个工况起止边界后，所有时间规则的激活状态保持不变。
        # 此后不同发车时刻的轨迹可严格复用，避免恢复搜索对相邻时刻重复执行完整动力学仿真。
        conditions = self.route.operating_conditions
        transition_times = [
            boundary
            for collection in (
                conditions.weather_conditions,
                conditions.adhesion_zones,
                conditions.speed_restrictions,
            )
            for item in collection
            for boundary in (
                int(item.start_time_s) if int(item.start_time_s) > 0 else None,
                int(item.end_time_s) if int(item.end_time_s) < OPEN_ENDED_TIME_S else None,
            )
            if boundary is not None
        ]
        stable_cache_key = "after_last_condition_transition"
        after_last_transition = bool(transition_times) and depart_time_s > max(transition_times)
        if after_last_transition and stable_cache_key in self._stable_condition_cache:
            return self._stable_condition_cache[stable_cache_key]

        if depart_time_s not in self._departure_cache:
            self._departure_cache[depart_time_s] = build_power_cache(
                self.train,
                self.route,
                start_time_s=depart_time_s,
                force_time_independent=True,
                simulation_step_s=self.simulation_step_s,
                power_arm_interval_path=self.power_arm_interval_path,
                storage_sections=self.storage_sections,
            )
        if after_last_transition:
            self._stable_condition_cache[stable_cache_key] = self._departure_cache[depart_time_s]
        return self._departure_cache[depart_time_s]

    def base_series(self, sample_step_s: int = 1) -> Dict[int, PowerSample]:
        """Return the cached power series for settlement.

        ``sample_step_s`` is retained for call-site compatibility and cache keys.
        Samples are always emitted at the native simulator resolution because
        thinning signed traction/regen samples would cancel opposite powers and
        destroy recoverable-energy accounting. Settlement already re-bins by its
        own time step.
        """

        sample_step_s = _positive_whole_seconds(sample_step_s, "sample_step_s")
        if sample_step_s in self._base_series_cache:
            return self._base_series_cache[sample_step_s]

        base: Dict[int, PowerSample] = {}
        if not self.times:
            self._base_series_cache[sample_step_s] = base
            return base

        default_duration_s = 1.0
        if len(self.times) >= 2:
            # 优先使用轨迹步长，避免在时长为零时丢弃最后一个样本。
            default_duration_s = max(1.0, float(self.times[1] - self.times[0]))
        for index, (t, power_kW, ratio, power_arm_id) in enumerate(zip(
            self.times,
            self.powers_kW,
            self.energy_transfer_ratios,
            self.power_arm_ids,
        )):
            if index + 1 < len(self.times):
                duration_s = max(0.0, float(self.times[index + 1] - t))
            elif index > 0:
                duration_s = max(default_duration_s, float(t - self.times[index - 1]))
            else:
                duration_s = default_duration_s
            storage_section_id = self.storage_section_ids[index] if index < len(self.storage_section_ids) else ""
            # 占用比例是区间内比例的权威值。比例为零表示车体在储能几何范围外，
            # 即使车头标签在边界样本上仍被保留。
            if float(ratio) <= 0.0:
                storage_section_id = ""
            base[int(t)] = (power_kW, ratio, power_arm_id, duration_s, storage_section_id)

        self._base_series_cache[sample_step_s] = base
        return base


    def base_series_components(self, sample_step_s: int = 1) -> List[Dict[int, PowerSample]]:
        """Split each sample across occupied power arms and storage devices.

        A long train can span several electrical sections at once. The legacy
        single series assigns all power to the head position; component series
        preserve the same total power while allocating it by longitudinal
        sample fraction.
        """

        sample_step_s = _positive_whole_seconds(sample_step_s, "sample_step_s")
        if sample_step_s in self._component_series_cache:
            return self._component_series_cache[sample_step_s]
        if not self.power_allocation_ratios:
            components = [self.base_series(sample_step_s=sample_step_s)]
            self._component_series_cache[sample_step_s] = components
            return components

        series_by_component: Dict[Tuple[str, str], Dict[int, PowerSample]] = {}
        default_duration_s = 1.0
        if len(self.times) >= 2:
            default_duration_s = max(1.0, float(self.times[1] - self.times[0]))
        for index, (time_s, power_kW) in enumerate(zip(self.times, self.powers_kW)):
            if index + 1 < len(self.times):
                duration_s = max(0.0, float(self.times[index + 1] - time_s))
            elif index > 0:
                duration_s = max(default_duration_s, float(time_s - self.times[index - 1]))
            else:
                duration_s = default_duration_s
            for raw_key, fraction in self.power_allocation_ratios[index].items():
                power_arm_id = str(raw_key[0])
                storage_section_id = str(raw_key[1])
                if fraction <= 0.0:
                    continue
                series_by_component.setdefault(
                    (power_arm_id, storage_section_id), {}
                )[int(time_s)] = (
                    float(power_kW) * float(fraction),
                    # ``energy_transfer_ratio`` 表示列车功率中可柔性转移的比例。纵向组件切分必须保留该比例；
                    # 储能标签只表示可存储的范围，不能把部分可转移样本提升为 100% 转移。
                    # 否则当分配比例与转移比例不同时，储能组件会高估充电或直用能量。
                    float(self.energy_transfer_ratios[index]),
                    power_arm_id,
                    duration_s,
                    storage_section_id,
                )
        components = [
            series_by_component[key]
            for key in sorted(series_by_component)
            if series_by_component[key]
        ]
        self._component_series_cache[sample_step_s] = components
        return components



    def shifted(self, depart_time_s: int, sample_step_s: int = 1) -> Dict[int, PowerSample]:
        """函数 shifted：执行该模块中的相关处理逻辑。"""
        depart_time_s = _non_negative_whole_seconds(depart_time_s, "depart_time_s")
        trajectory = self._trajectory_for_departure(depart_time_s)
        return {
            depart_time_s + t: sample
            for t, sample in trajectory.base_series(sample_step_s=sample_step_s).items()
        }

    def shifted_components(
        self,
        depart_time_s: int,
        sample_step_s: int = 1,
    ) -> List[Dict[int, PowerSample]]:
        """函数 shifted_components：执行该模块中的相关处理逻辑。"""
        depart_time_s = _non_negative_whole_seconds(depart_time_s, "depart_time_s")
        trajectory = self._trajectory_for_departure(depart_time_s)
        return [
            {depart_time_s + time_s: sample for time_s, sample in series.items()}
            for series in trajectory.base_series_components(sample_step_s=sample_step_s)
        ]

    def first_storage_entry_elapsed_s(self, depart_time_s: int | None = None) -> int | None:
        """Return the first trajectory sample that overlaps configured storage."""

        requested_departure_s = _non_negative_whole_seconds(
            self.start_time_s if depart_time_s is None else depart_time_s,
            "depart_time_s",
        )
        cache_key = requested_departure_s if self.time_dependent_conditions else self.start_time_s
        if cache_key in self._first_storage_entry_cache:
            return self._first_storage_entry_cache[cache_key]
        trajectory = self._trajectory_for_departure(requested_departure_s)
        result: int | None = None
        for index, time_s in enumerate(trajectory.times):
            if trajectory.power_allocation_ratios:
                allocations = trajectory.power_allocation_ratios[index]
                if any(
                    str(storage_section_id).strip() and float(fraction) > 0.0
                    for (_power_arm_id, storage_section_id), fraction in allocations.items()
                ):
                    result = int(time_s)
                    break
            elif (
                index < len(trajectory.storage_section_ids)
                and str(trajectory.storage_section_ids[index]).strip()
                and index < len(trajectory.energy_transfer_ratios)
                and float(trajectory.energy_transfer_ratios[index]) > 0.0
            ):
                result = int(time_s)
                break
        self._first_storage_entry_cache[cache_key] = result
        return result

    def _elapsed_before_storage_hold(
        self,
        elapsed_time_s: int,
        depart_time_s: int | None,
        storage_hold_s: int,
    ) -> int:
        """函数 _elapsed_before_storage_hold：执行该模块中的相关处理逻辑。"""
        hold_s = _non_negative_whole_seconds(storage_hold_s, "storage_hold_s")
        elapsed_s = _non_negative_whole_seconds(elapsed_time_s, "elapsed_time_s")
        if hold_s <= 0:
            return elapsed_s
        entry_s = self.first_storage_entry_elapsed_s(depart_time_s)
        if entry_s is None or elapsed_s < entry_s:
            return elapsed_s
        if elapsed_s < entry_s + hold_s:
            return max(0, entry_s - 1)
        return elapsed_s - hold_s

    def state_at(
        self,
        elapsed_time_s: int,
        depart_time_s: int | None = None,
        storage_hold_s: int = 0,
    ) -> Tuple[float, float] | None:
        """Return head position and speed at elapsed time."""

        trajectory = self._trajectory_for_departure(self.start_time_s if depart_time_s is None else depart_time_s)
        hold_s = _non_negative_whole_seconds(storage_hold_s, "storage_hold_s")
        elapsed_s = _non_negative_whole_seconds(elapsed_time_s, "elapsed_time_s")
        entry_s = self.first_storage_entry_elapsed_s(depart_time_s)
        applied_hold_s = hold_s if entry_s is not None else 0
        if not trajectory.times or elapsed_s > trajectory.times[-1] + applied_hold_s:
            return None
        base_elapsed_s = self._elapsed_before_storage_hold(
            elapsed_s,
            depart_time_s,
            hold_s,
        )
        idx = bisect.bisect_right(trajectory.times, base_elapsed_s) - 1
        idx = max(0, min(idx, len(trajectory.times) - 1))
        is_holding = entry_s is not None and hold_s > 0 and entry_s <= elapsed_s < entry_s + hold_s
        speed_mps = 0.0 if is_holding else trajectory.speeds_mps[idx]
        return trajectory.positions_km[idx], speed_mps

    def safety_state_at(
        self,
        elapsed_time_s: int,
        depart_time_s: int | None = None,
        storage_hold_s: int = 0,
    ) -> Tuple[float, float, float] | None:
        """Return head position, speed, and adhesion-limited brake deceleration."""

        trajectory = self._trajectory_for_departure(self.start_time_s if depart_time_s is None else depart_time_s)
        hold_s = _non_negative_whole_seconds(storage_hold_s, "storage_hold_s")
        elapsed_s = _non_negative_whole_seconds(elapsed_time_s, "elapsed_time_s")
        entry_s = self.first_storage_entry_elapsed_s(depart_time_s)
        applied_hold_s = hold_s if entry_s is not None else 0
        if not trajectory.times or elapsed_s > trajectory.times[-1] + applied_hold_s:
            return None
        base_elapsed_s = self._elapsed_before_storage_hold(
            elapsed_s,
            depart_time_s,
            hold_s,
        )
        idx = bisect.bisect_right(trajectory.times, base_elapsed_s) - 1
        idx = max(0, min(idx, len(trajectory.times) - 1))
        brake_decel = trajectory.brake_decelerations_mps2[idx]
        is_holding = entry_s is not None and hold_s > 0 and entry_s <= elapsed_s < entry_s + hold_s
        speed_mps = 0.0 if is_holding else trajectory.speeds_mps[idx]
        return trajectory.positions_km[idx], speed_mps, max(0.05, brake_decel)


def build_power_cache(
    train: TrainParameters,
    route,
    start_time_s: int = 0,
    force_time_independent: bool = False,
    simulation_step_s: float = 5.0,
    power_arm_interval_path: Path | None = None,
    storage_sections: Iterable[StorageSectionInterval] | None = None,
) -> PowerSeriesCache:
    """Run the simulator once per train type and cache power series.

    Identical train/route/storage builds reuse a module-level memo to avoid
    redundant trajectory simulation when storage-preset search prebuilds many
    evaluation contexts that share geometry.
    """

    global _POWER_CACHE_MEMO_MISSES
    start_time_s = _non_negative_whole_seconds(start_time_s, "start_time_s")
    simulation_step_s = _positive_whole_seconds(simulation_step_s, "simulation_step_s")
    if type(force_time_independent) is not bool:
        raise ValueError("force_time_independent must be a boolean")
    if storage_sections is not None:
        storage_sections = tuple(storage_sections)
    memo_key = _power_cache_memo_key(
        train,
        route,
        start_time_s,
        force_time_independent,
        simulation_step_s,
        power_arm_interval_path,
        storage_sections,
    )
    cached = _power_cache_memo_get(memo_key)
    if cached is not None:
        return cached
    with _POWER_CACHE_MEMO_LOCK:
        _POWER_CACHE_MEMO_MISSES += 1

    raw_key = _raw_trajectory_key(
        train,
        route,
        start_time_s,
        force_time_independent,
        simulation_step_s,
    )
    raw_records = _raw_trajectory_get(raw_key)
    if raw_records is None:
        base_route = replace(route, energy_transfer_ranges_km=[])
        raw_records = _raw_trajectory_store(
            raw_key,
            tuple(run_train_simulation(base_route, train, start_time_s=start_time_s, delta_t_s=simulation_step_s)),
        )
    if route.energy_transfer_ranges_km:
        records = [
            replace(
                record,
                energy_transfer_ratio=train_range_ratio(
                    route,
                    train,
                    record.position_km,
                    route.energy_transfer_ranges_km,
                ),
            )
            for record in raw_records
        ]
    else:
        records = list(raw_records)
    times = [record.time_s for record in records]
    powers = [record.power_kW for record in records]
    ratios = [record.energy_transfer_ratio for record in records]
    positions = [record.position_km for record in records]
    intervals = load_power_arm_intervals(power_arm_interval_path) if power_arm_interval_path is not None else load_power_arm_intervals()
    selected_storage_sections = (
        tuple(storage_sections)
        if storage_sections is not None
        else load_storage_section_intervals(power_arm_interval_path) if power_arm_interval_path is not None
        else load_storage_section_intervals()
    )
    power_arm_ids = [find_power_arm_id(intervals, position, train.direction) for position in positions]
    storage_section_ids = [
        storage_section_for_position(position, selected_storage_sections, train.direction)
        for position in positions
    ]
    power_allocation_ratios: List[Dict[Tuple[str, str], float]] = []
    for record in records:
        sample_positions = train_sample_positions(route, train, record.position_km)
        counts: Dict[Tuple[str, str], int] = {}
        for sample_position in sample_positions:
            key = (
                find_power_arm_id(intervals, sample_position, train.direction),
                storage_section_for_position(
                    sample_position,
                    selected_storage_sections,
                    train.direction,
                ),
            )
            counts[key] = counts.get(key, 0) + 1
        sample_count = max(1, len(sample_positions))
        power_allocation_ratios.append(
            {key: count / sample_count for key, count in counts.items()}
        )
    speeds = [record.speed_mps for record in records]
    adhesion_coefficients = [record.adhesion_coefficient for record in records]
    speed_limits = [record.speed_limit_mps for record in records]
    brake_decelerations = [max(0.05, record.adhesion_limited_decel_mps2) for record in records]
    cache = PowerSeriesCache(
        times=times,
        powers_kW=powers,
        energy_transfer_ratios=ratios,
        power_arm_ids=power_arm_ids,
        positions_km=positions,
        speeds_mps=speeds,
        train_length_km=train.length_km,
        direction=train.direction,
        adhesion_coefficients=adhesion_coefficients,
        speed_limits_mps=speed_limits,
        brake_decelerations_mps2=brake_decelerations,
        storage_section_ids=storage_section_ids,
        power_allocation_ratios=power_allocation_ratios,
        route=route,
        train=train,
        start_time_s=start_time_s,
        simulation_step_s=simulation_step_s,
        time_dependent_conditions=False if force_time_independent else is_time_dependent(route.operating_conditions),
        power_arm_interval_path=power_arm_interval_path,
        storage_sections=selected_storage_sections,
    )
    return _power_cache_memo_store(memo_key, cache)


def schedule_deviation(times: List[int], target_gap_s: int = 1000) -> float:
    """Sum absolute deviation from target headway for a sorted schedule."""

    target_gap_s = _non_negative_whole_seconds(target_gap_s, "target_gap_s")
    sorted_times = _sorted_departure_times(times)
    if len(times) <= 1:
        return 0.0
    return sum(abs((b - a) - target_gap_s) for a, b in zip(sorted_times[:-1], sorted_times[1:]))


def _whole_second_value(value: Any, field_name: str) -> int:
    """函数 _whole_second_value：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}")
    return int(number)


def _non_negative_whole_seconds(value: Any, field_name: str) -> int:
    """函数 _non_negative_whole_seconds：执行该模块中的相关处理逻辑。"""
    number = _whole_second_value(value, field_name)
    if number < 0:
        raise ValueError(f"{field_name} must be non-negative, got {value!r}")
    return number


def _positive_whole_seconds(value: Any, field_name: str) -> int:
    """函数 _positive_whole_seconds：执行该模块中的相关处理逻辑。"""
    number = _whole_second_value(value, field_name)
    if number <= 0:
        raise ValueError(f"{field_name} must be positive, got {value!r}")
    return number


def _sorted_departure_times(times: Iterable[Any]) -> List[int]:
    """函数 _sorted_departure_times：执行该模块中的相关处理逻辑。"""
    return sorted(_non_negative_whole_seconds(value, "departure time") for value in times)


def _inclusive_sample_times(start_s: int, end_s: int, step_s: int) -> Iterable[int]:
    """Yield regular samples and always include the closed interval endpoint."""

    last_sample_s: int | None = None
    for sample_s in range(start_s, end_s + 1, step_s):
        last_sample_s = sample_s
        yield sample_s
    if last_sample_s != end_s:
        yield end_s


def _signal_state_at(
    cache: PowerSeriesCache,
    elapsed_time_s: int,
    depart_time_s: int,
    storage_hold_s: int,
    operation_delay_events: Iterable[Tuple[float, int]] = (),
    *,
    safety: bool,
):
    """函数 _signal_state_at：执行该模块中的相关处理逻辑。"""
    trajectory = cache._trajectory_for_departure(depart_time_s)
    holds = _prepared_signal_holds(
        trajectory,
        depart_time_s,
        storage_hold_s,
        operation_delay_events,
    )
    elapsed_before_holds, operation_held = _elapsed_before_prepared_signal_holds(
        elapsed_time_s,
        holds,
    )
    return _prepared_trajectory_state(
        trajectory,
        elapsed_before_holds,
        operation_held=operation_held,
        safety=safety,
        fallback_cache=cache,
        depart_time_s=depart_time_s,
    )


def _normalized_operation_delay_events(
    operation_delay_events: Iterable[Tuple[float, int]],
) -> Tuple[Tuple[float, int], ...]:
    """函数 _normalized_operation_delay_events：执行该模块中的相关处理逻辑。"""
    combined: Dict[float, int] = {}
    for raw_threshold_s, raw_delay_s in operation_delay_events:
        threshold_s = _finite_signaling_number(
            raw_threshold_s,
            "operation delay threshold",
        )
        if threshold_s < 0.0:
            raise ValueError("operation delay threshold must be non-negative")
        delay_s = _non_negative_whole_number(raw_delay_s, "operation delay")
        if delay_s > 0:
            combined[threshold_s] = combined.get(threshold_s, 0) + delay_s
    return tuple(sorted(combined.items()))


def _normalized_operation_delay_map(
    operation_delay_events_by_departure: Mapping[int, Iterable[Tuple[float, int]]] | None,
) -> Dict[int, Tuple[Tuple[float, int], ...]]:
    """函数 _normalized_operation_delay_map：执行该模块中的相关处理逻辑。"""
    if operation_delay_events_by_departure is None:
        return {}
    normalized: Dict[int, Tuple[Tuple[float, int], ...]] = {}
    for raw_departure_s, raw_events in operation_delay_events_by_departure.items():
        departure_s = _non_negative_whole_seconds(raw_departure_s, "operation departure time")
        normalized[departure_s] = _normalized_operation_delay_events(raw_events)
    return normalized


def _effective_signal_operation_events(
    trajectory: PowerSeriesCache,
    operation_delay_events: Iterable[Tuple[float, int]],
) -> Tuple[Tuple[float, int], ...]:
    """Keep only delays that affect downstream mainline movement."""

    events = _normalized_operation_delay_events(operation_delay_events)
    if not trajectory.times:
        return ()
    last_elapsed_s = float(trajectory.times[-1])
    return tuple((threshold_s, delay_s) for threshold_s, delay_s in events if threshold_s < last_elapsed_s - 1e-9)


def _prepared_signal_holds(
    trajectory: PowerSeriesCache,
    depart_time_s: int,
    storage_hold_s: int,
    operation_delay_events: Iterable[Tuple[float, int]],
) -> Tuple[Tuple[float, int, str], ...]:
    """为一列车一次性整理信号检查所需的停车事件。"""

    hold_s = _non_negative_whole_seconds(storage_hold_s, "storage_hold_s")
    events = _effective_signal_operation_events(trajectory, operation_delay_events)
    entry_s = (
        trajectory.first_storage_entry_elapsed_s(depart_time_s)
        if hold_s > 0
        else None
    )
    holds: List[Tuple[float, int, str]] = [
        (threshold_s, delay_s, "operation")
        for threshold_s, delay_s in events
    ]
    if hold_s > 0 and entry_s is not None:
        holds.append((float(entry_s), hold_s, "storage"))
    holds.sort(key=lambda item: (item[0], 0 if item[2] == "operation" else 1))
    return tuple(holds)


def _elapsed_before_prepared_signal_holds(
    elapsed_time_s: int,
    holds: Iterable[Tuple[float, int, str]],
) -> Tuple[int, bool]:
    """使用已整理的停车事件把可执行时间映射回基础轨迹时间。"""

    elapsed_s = _non_negative_whole_seconds(elapsed_time_s, "elapsed_time_s")
    cumulative_delay_s = 0
    for threshold_s, delay_s, hold_type in holds:
        executable_start_s = threshold_s + cumulative_delay_s
        if elapsed_s < executable_start_s:
            return max(0, int(math.floor(elapsed_s - cumulative_delay_s))), False
        if elapsed_s < executable_start_s + delay_s:
            held_elapsed_s = threshold_s if hold_type == "operation" else max(0.0, threshold_s - 1.0)
            return max(0, int(math.floor(held_elapsed_s))), True
        cumulative_delay_s += delay_s
    return max(0, int(math.floor(elapsed_s - cumulative_delay_s))), False


def _prepared_trajectory_state(
    trajectory: PowerSeriesCache,
    elapsed_time_s: int,
    *,
    operation_held: bool,
    safety: bool,
    fallback_cache=None,
    depart_time_s: int | None = None,
):
    """从已选定轨迹直接二分取样，避免在内层循环重复解析缓存和储能入口。"""

    if not trajectory.times or elapsed_time_s > trajectory.times[-1]:
        return None
    required_fields = ("positions_km", "speeds_mps")
    if safety:
        required_fields += ("brake_decelerations_mps2",)
    if any(not hasattr(trajectory, field_name) for field_name in required_fields):
        if fallback_cache is None:
            raise TypeError("trajectory does not expose indexed signaling state")
        if safety:
            state = fallback_cache.safety_state_at(
                elapsed_time_s,
                depart_time_s=depart_time_s,
            )
            if state is not None and operation_held:
                return state[0], 0.0, state[2]
            return state
        state = fallback_cache.state_at(
            elapsed_time_s,
            depart_time_s=depart_time_s,
        )
        if state is not None and operation_held:
            return state[0], 0.0
        return state
    idx = bisect.bisect_right(trajectory.times, elapsed_time_s) - 1
    idx = max(0, min(idx, len(trajectory.times) - 1))
    speed_mps = 0.0 if operation_held else trajectory.speeds_mps[idx]
    if safety:
        return (
            trajectory.positions_km[idx],
            speed_mps,
            max(0.05, trajectory.brake_decelerations_mps2[idx]),
        )
    return trajectory.positions_km[idx], speed_mps


def _elapsed_before_signal_holds(
    trajectory: PowerSeriesCache,
    elapsed_time_s: int,
    depart_time_s: int,
    storage_hold_s: int,
    operation_delay_events: Iterable[Tuple[float, int]],
) -> Tuple[int, bool]:
    """Map an executable elapsed time back to the cached trajectory clock."""

    holds = _prepared_signal_holds(
        trajectory,
        depart_time_s,
        storage_hold_s,
        operation_delay_events,
    )
    return _elapsed_before_prepared_signal_holds(elapsed_time_s, holds)


def violates_headway(times: List[int], min_gap_s: int = 300) -> bool:
    """Check minimum headway constraint for a sorted schedule."""

    min_gap_s = _non_negative_whole_seconds(min_gap_s, "min_gap_s")
    sorted_times = _sorted_departure_times(times)
    if len(sorted_times) <= 1:
        return False
    return any((b - a) < min_gap_s for a, b in zip(sorted_times[:-1], sorted_times[1:]))


def headway_violation_seconds(times: List[int], min_gap_s: int = 300) -> float:
    """Return the total same-direction headway deficit in seconds."""

    min_gap_s = _non_negative_whole_seconds(min_gap_s, "min_gap_s")
    sorted_times = _sorted_departure_times(times)
    return sum(max(0.0, float(min_gap_s - (right - left))) for left, right in zip(sorted_times[:-1], sorted_times[1:]))


def _normalized_signaling_mode(value: Any) -> str:
    """函数 _normalized_signaling_mode：执行该模块中的相关处理逻辑。"""
    mode = str(value or "hybrid").strip().lower()
    aliases = {
        "fixed": "fixed_block",
        "fixed_block": "fixed_block",
        "moving": "moving_block",
        "moving_block": "moving_block",
        "hybrid": "hybrid",
    }
    if mode not in aliases:
        raise ValueError(f"Unsupported signaling mode: {value!r}")
    return aliases[mode]


def _positive_check_step_s(value: Any) -> int:
    """函数 _positive_check_step_s：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"check_step_s must be a positive whole number, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"check_step_s must be a positive whole number, got {value!r}") from exc
    if not math.isfinite(number) or not number.is_integer() or number <= 0.0:
        raise ValueError(f"check_step_s must be a positive whole number, got {value!r}")
    return int(number)


def _finite_signaling_number(value: Any, field_name: str) -> float:
    """函数 _finite_signaling_number：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be finite, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite, got {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite, got {value!r}")
    return number


def _positive_signaling_number(value: Any, field_name: str) -> float:
    """函数 _positive_signaling_number：执行该模块中的相关处理逻辑。"""
    number = _finite_signaling_number(value, field_name)
    if number <= 0.0:
        raise ValueError(f"{field_name} must be positive, got {value!r}")
    return number


def _non_negative_signaling_number(value: Any, field_name: str) -> float:
    """函数 _non_negative_signaling_number：执行该模块中的相关处理逻辑。"""
    number = _finite_signaling_number(value, field_name)
    if number < 0.0:
        raise ValueError(f"{field_name} must be non-negative, got {value!r}")
    return number


def _non_negative_whole_number(value: Any, field_name: str) -> int:
    """函数 _non_negative_whole_number：执行该模块中的相关处理逻辑。"""
    number = _finite_signaling_number(value, field_name)
    if number < 0.0 or not number.is_integer():
        raise ValueError(f"{field_name} must be a non-negative whole number, got {value!r}")
    return int(number)


def _fixed_block_parameters(signaling_system: Dict[str, Any]) -> Tuple[float, int]:
    """函数 _fixed_block_parameters：执行该模块中的相关处理逻辑。"""
    return (
        _positive_signaling_number(
            signaling_system.get("fixed_block_length_km", 2.0),
            "fixed_block_length_km",
        ),
        _non_negative_whole_number(
            signaling_system.get("fixed_block_protection_blocks", 2),
            "fixed_block_protection_blocks",
        ),
    )


def _moving_block_parameters(signaling_system: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """函数 _moving_block_parameters：执行该模块中的相关处理逻辑。"""
    return (
        _non_negative_signaling_number(
            signaling_system.get("moving_block_base_buffer_m", 500.0),
            "moving_block_base_buffer_m",
        ),
        _non_negative_signaling_number(
            signaling_system.get("moving_block_reaction_time_s", 30.0),
            "moving_block_reaction_time_s",
        ),
        _positive_signaling_number(
            signaling_system.get("moving_block_follower_service_decel_mps2", 0.28),
            "moving_block_follower_service_decel_mps2",
        ),
        _positive_signaling_number(
            signaling_system.get("moving_block_lead_emergency_decel_mps2", 0.50),
            "moving_block_lead_emergency_decel_mps2",
        ),
    )


def signal_violation_count(
    depart_times: List[int],
    cache: PowerSeriesCache,
    signaling_system: Dict[str, Any],
    storage_hold_s: int = 0,
    operation_delay_events_by_departure: Mapping[int, Iterable[Tuple[float, int]]] | None = None,
) -> int:
    """Count violated configured signal-protection families."""

    mode = _normalized_signaling_mode(signaling_system.get("mode", "hybrid"))
    check_step_s = _positive_check_step_s(signaling_system.get("check_step_s", 5))
    storage_hold_s = _non_negative_whole_seconds(storage_hold_s, "storage_hold_s")
    depart_times = _sorted_departure_times(depart_times)
    operation_delay_map = _normalized_operation_delay_map(
        operation_delay_events_by_departure
    )
    count = 0
    if mode in ("fixed_block", "hybrid"):
        block_length_km, protection_blocks = _fixed_block_parameters(signaling_system)
        if violates_fixed_block(
            depart_times,
            cache,
            block_length_km=block_length_km,
            protection_blocks=protection_blocks,
            check_step_s=check_step_s,
            storage_hold_s=storage_hold_s,
            operation_delay_events_by_departure=operation_delay_map,
        ):
            count += 1
    if mode in ("moving_block", "hybrid"):
        base_buffer_m, reaction_time_s, follower_decel, lead_decel = _moving_block_parameters(
            signaling_system
        )
        if violates_moving_block(
            depart_times,
            cache,
            check_step_s=check_step_s,
            base_buffer_m=base_buffer_m,
            reaction_time_s=reaction_time_s,
            follower_service_decel_mps2=follower_decel,
            lead_emergency_decel_mps2=lead_decel,
            storage_hold_s=storage_hold_s,
            operation_delay_events_by_departure=operation_delay_map,
        ):
            count += 1
    return count


def dynamic_safe_distance_km(
    follower_speed_mps: float,
    lead_speed_mps: float,
    base_buffer_m: float = 500.0,
    reaction_time_s: float = 30.0,
    follower_service_decel_mps2: float = 0.28,
    lead_emergency_decel_mps2: float = 0.50,
) -> float:
    """Calculate dynamic clear distance required between lead tail and follower head."""

    follower_speed_mps = _non_negative_signaling_number(follower_speed_mps, "follower_speed_mps")
    lead_speed_mps = _non_negative_signaling_number(lead_speed_mps, "lead_speed_mps")
    base_buffer_m = _non_negative_signaling_number(base_buffer_m, "base_buffer_m")
    reaction_time_s = _non_negative_signaling_number(reaction_time_s, "reaction_time_s")
    follower_service_decel_mps2 = _positive_signaling_number(
        follower_service_decel_mps2, "follower_service_decel_mps2"
    )
    lead_emergency_decel_mps2 = _positive_signaling_number(
        lead_emergency_decel_mps2, "lead_emergency_decel_mps2"
    )
    follower_braking_m = follower_speed_mps**2 / (2.0 * follower_service_decel_mps2)
    lead_braking_m = lead_speed_mps**2 / (2.0 * lead_emergency_decel_mps2)
    reaction_m = follower_speed_mps * reaction_time_s
    required_m = base_buffer_m + reaction_m + max(0.0, follower_braking_m - lead_braking_m)
    return required_m / 1000.0


def tail_position_km(head_position_km: float, train_length_km: float, direction: str) -> float:
    """Return train tail position in route mileage coordinates."""

    if direction == "reverse":
        return head_position_km + train_length_km
    return head_position_km - train_length_km


def clear_distance_km(
    lead_head_km: float,
    follower_head_km: float,
    train_length_km: float,
    direction: str,
) -> float:
    """Return clear distance from lead tail to follower head along train direction."""

    lead_tail_km = tail_position_km(lead_head_km, train_length_km, direction)
    if direction == "reverse":
        return follower_head_km - lead_tail_km
    return lead_tail_km - follower_head_km


def violates_moving_block(
    depart_times: List[int],
    cache: PowerSeriesCache,
    check_step_s: int = 5,
    base_buffer_m: float = 500.0,
    reaction_time_s: float = 30.0,
    follower_service_decel_mps2: float = 0.28,
    lead_emergency_decel_mps2: float = 0.50,
    storage_hold_s: int = 0,
    operation_delay_events_by_departure: Mapping[int, Iterable[Tuple[float, int]]] | None = None,
) -> bool:
    """Check moving-block separation over the cached trajectory."""

    check_step_s = _positive_check_step_s(check_step_s)
    base_buffer_m = _non_negative_signaling_number(base_buffer_m, "moving_block_base_buffer_m")
    reaction_time_s = _non_negative_signaling_number(reaction_time_s, "moving_block_reaction_time_s")
    follower_service_decel_mps2 = _positive_signaling_number(
        follower_service_decel_mps2, "moving_block_follower_service_decel_mps2"
    )
    lead_emergency_decel_mps2 = _positive_signaling_number(
        lead_emergency_decel_mps2, "moving_block_lead_emergency_decel_mps2"
    )
    storage_hold_s = _non_negative_whole_seconds(storage_hold_s, "storage_hold_s")
    depart_times = _sorted_departure_times(depart_times)
    operation_delay_map = _normalized_operation_delay_map(
        operation_delay_events_by_departure
    )
    if len(depart_times) <= 1:
        return False

    sorted_times = depart_times
    for lead_depart_s, follower_depart_s in zip(sorted_times[:-1], sorted_times[1:]):
        lead_trajectory = cache._trajectory_for_departure(lead_depart_s)
        follower_trajectory = cache._trajectory_for_departure(follower_depart_s)
        lead_hold_s = 0
        follower_hold_s = 0
        if storage_hold_s > 0:
            lead_hold_s = (
                storage_hold_s
                if lead_trajectory.first_storage_entry_elapsed_s(lead_depart_s) is not None
                else 0
            )
            follower_hold_s = (
                storage_hold_s
                if follower_trajectory.first_storage_entry_elapsed_s(follower_depart_s) is not None
                else 0
            )
        lead_operation_events = _effective_signal_operation_events(
            lead_trajectory,
            operation_delay_map.get(lead_depart_s, ()),
        )
        follower_operation_events = _effective_signal_operation_events(
            follower_trajectory,
            operation_delay_map.get(follower_depart_s, ()),
        )
        lead_holds = _prepared_signal_holds(
            lead_trajectory,
            lead_depart_s,
            storage_hold_s,
            lead_operation_events,
        )
        follower_holds = _prepared_signal_holds(
            follower_trajectory,
            follower_depart_s,
            storage_hold_s,
            follower_operation_events,
        )
        lead_last_elapsed_s = (
            lead_trajectory.times[-1]
            + lead_hold_s
            + sum(delay_s for _threshold_s, delay_s in lead_operation_events)
        )
        follower_last_elapsed_s = (
            follower_trajectory.times[-1]
            + follower_hold_s
            + sum(delay_s for _threshold_s, delay_s in follower_operation_events)
        )
        overlap_start_s = follower_depart_s
        overlap_end_s = min(lead_depart_s + lead_last_elapsed_s, follower_depart_s + follower_last_elapsed_s)
        if overlap_start_s > overlap_end_s:
            continue

        for global_time_s in _inclusive_sample_times(
            overlap_start_s, overlap_end_s, check_step_s
        ):
            lead_elapsed_s, lead_operation_held = _elapsed_before_prepared_signal_holds(
                global_time_s - lead_depart_s,
                lead_holds,
            )
            follower_elapsed_s, follower_operation_held = _elapsed_before_prepared_signal_holds(
                global_time_s - follower_depart_s,
                follower_holds,
            )
            lead_state = _prepared_trajectory_state(
                lead_trajectory,
                lead_elapsed_s,
                operation_held=lead_operation_held,
                safety=True,
                fallback_cache=cache,
                depart_time_s=lead_depart_s,
            )
            follower_state = _prepared_trajectory_state(
                follower_trajectory,
                follower_elapsed_s,
                operation_held=follower_operation_held,
                safety=True,
                fallback_cache=cache,
                depart_time_s=follower_depart_s,
            )
            if lead_state is None or follower_state is None:
                continue

            lead_head_km, lead_speed_mps, lead_brake_decel_mps2 = lead_state
            follower_head_km, follower_speed_mps, follower_brake_decel_mps2 = follower_state
            clear_distance = clear_distance_km(
                lead_head_km,
                follower_head_km,
                cache.train_length_km,
                cache.direction,
            )
            required_distance_km = dynamic_safe_distance_km(
                follower_speed_mps,
                lead_speed_mps,
                base_buffer_m=base_buffer_m,
                reaction_time_s=reaction_time_s,
                follower_service_decel_mps2=min(follower_service_decel_mps2, follower_brake_decel_mps2),
                lead_emergency_decel_mps2=min(lead_emergency_decel_mps2, lead_brake_decel_mps2),
            )

            if clear_distance < required_distance_km:
                return True

    return False


def block_index(position_km: float, block_length_km: float) -> int:
    """Map mileage to a fixed-block index."""

    return int(max(0.0, position_km) // block_length_km)


def violates_fixed_block(
    depart_times: List[int],
    cache: PowerSeriesCache,
    block_length_km: float,
    protection_blocks: int,
    check_step_s: int = 5,
    storage_hold_s: int = 0,
    operation_delay_events_by_departure: Mapping[int, Iterable[Tuple[float, int]]] | None = None,
) -> bool:
    """Check fixed-block occupancy and protection blocks for same-direction trains."""

    check_step_s = _positive_check_step_s(check_step_s)
    block_length_km = _positive_signaling_number(block_length_km, "fixed_block_length_km")
    protection_blocks = _non_negative_whole_number(
        protection_blocks, "fixed_block_protection_blocks"
    )
    storage_hold_s = _non_negative_whole_seconds(storage_hold_s, "storage_hold_s")
    depart_times = _sorted_departure_times(depart_times)
    operation_delay_map = _normalized_operation_delay_map(
        operation_delay_events_by_departure
    )
    if len(depart_times) <= 1:
        return False

    sorted_times = depart_times

    for lead_depart_s, follower_depart_s in zip(sorted_times[:-1], sorted_times[1:]):
        lead_trajectory = cache._trajectory_for_departure(lead_depart_s)
        follower_trajectory = cache._trajectory_for_departure(follower_depart_s)
        lead_hold_s = 0
        follower_hold_s = 0
        if storage_hold_s > 0:
            lead_hold_s = (
                storage_hold_s
                if lead_trajectory.first_storage_entry_elapsed_s(lead_depart_s) is not None
                else 0
            )
            follower_hold_s = (
                storage_hold_s
                if follower_trajectory.first_storage_entry_elapsed_s(follower_depart_s) is not None
                else 0
            )
        lead_operation_events = _effective_signal_operation_events(
            lead_trajectory,
            operation_delay_map.get(lead_depart_s, ()),
        )
        follower_operation_events = _effective_signal_operation_events(
            follower_trajectory,
            operation_delay_map.get(follower_depart_s, ()),
        )
        lead_holds = _prepared_signal_holds(
            lead_trajectory,
            lead_depart_s,
            storage_hold_s,
            lead_operation_events,
        )
        follower_holds = _prepared_signal_holds(
            follower_trajectory,
            follower_depart_s,
            storage_hold_s,
            follower_operation_events,
        )
        lead_last_elapsed_s = (
            lead_trajectory.times[-1]
            + lead_hold_s
            + sum(delay_s for _threshold_s, delay_s in lead_operation_events)
        )
        follower_last_elapsed_s = (
            follower_trajectory.times[-1]
            + follower_hold_s
            + sum(delay_s for _threshold_s, delay_s in follower_operation_events)
        )
        overlap_start_s = follower_depart_s
        overlap_end_s = min(lead_depart_s + lead_last_elapsed_s, follower_depart_s + follower_last_elapsed_s)
        if overlap_start_s > overlap_end_s:
            continue

        for global_time_s in _inclusive_sample_times(
            overlap_start_s, overlap_end_s, check_step_s
        ):
            lead_elapsed_s, lead_operation_held = _elapsed_before_prepared_signal_holds(
                global_time_s - lead_depart_s,
                lead_holds,
            )
            follower_elapsed_s, follower_operation_held = _elapsed_before_prepared_signal_holds(
                global_time_s - follower_depart_s,
                follower_holds,
            )
            lead_state = _prepared_trajectory_state(
                lead_trajectory,
                lead_elapsed_s,
                operation_held=lead_operation_held,
                safety=False,
                fallback_cache=cache,
                depart_time_s=lead_depart_s,
            )
            follower_state = _prepared_trajectory_state(
                follower_trajectory,
                follower_elapsed_s,
                operation_held=follower_operation_held,
                safety=False,
                fallback_cache=cache,
                depart_time_s=follower_depart_s,
            )
            if lead_state is None or follower_state is None:
                continue

            lead_head_km, _lead_speed_mps = lead_state
            follower_head_km, _follower_speed_mps = follower_state
            lead_tail_km = tail_position_km(lead_head_km, cache.train_length_km, cache.direction)

            lead_tail_block = block_index(lead_tail_km, block_length_km)
            follower_head_block = block_index(follower_head_km, block_length_km)

            if cache.direction == "reverse":
                if follower_head_block <= lead_tail_block + protection_blocks:
                    return True
            else:
                if follower_head_block >= lead_tail_block - protection_blocks:
                    return True

    return False


def violates_signal_system(
    depart_times: List[int],
    cache: PowerSeriesCache,
    signaling_system: Dict[str, Any],
    storage_hold_s: int = 0,
    operation_delay_events_by_departure: Mapping[int, Iterable[Tuple[float, int]]] | None = None,
) -> bool:
    """Check configured fixed-block, moving-block, or hybrid signal protection."""

    mode = _normalized_signaling_mode(signaling_system.get("mode", "hybrid"))
    check_step_s = _positive_check_step_s(signaling_system.get("check_step_s", 5))
    storage_hold_s = _non_negative_whole_seconds(storage_hold_s, "storage_hold_s")
    depart_times = _sorted_departure_times(depart_times)
    operation_delay_map = _normalized_operation_delay_map(
        operation_delay_events_by_departure
    )

    if mode in ("fixed_block", "hybrid"):
        block_length_km, protection_blocks = _fixed_block_parameters(signaling_system)
        if violates_fixed_block(
            depart_times,
            cache,
            block_length_km=block_length_km,
            protection_blocks=protection_blocks,
            check_step_s=check_step_s,
            storage_hold_s=storage_hold_s,
            operation_delay_events_by_departure=operation_delay_map,
        ):
            return True

    if mode in ("moving_block", "hybrid"):
        base_buffer_m, reaction_time_s, follower_decel, lead_decel = _moving_block_parameters(
            signaling_system
        )
        if violates_moving_block(
            depart_times,
            cache,
            check_step_s=check_step_s,
            base_buffer_m=base_buffer_m,
            reaction_time_s=reaction_time_s,
            follower_service_decel_mps2=follower_decel,
            lead_emergency_decel_mps2=lead_decel,
            storage_hold_s=storage_hold_s,
            operation_delay_events_by_departure=operation_delay_map,
        ):
            return True

    return False


def violates_dynamic_spacing(
    depart_times: List[int],
    cache: PowerSeriesCache,
    check_step_s: int = 5,
) -> bool:
    """Backward-compatible wrapper for moving-block spacing checks."""

    return violates_moving_block(depart_times, cache, check_step_s=check_step_s)


def normalize_and_pick_best(front_f: List[Tuple[float, float]], front_x: List[List[int]]) -> Tuple[List[int], float, float]:
    """Pick the knee solution via min-max normalization and distance to origin."""

    if not front_f:
        raise ValueError("Pareto objective front must not be empty")
    if len(front_f) != len(front_x):
        raise ValueError("Pareto objective and decision fronts must have the same length")
    objectives: List[Tuple[float, float]] = []
    decisions: List[List[int]] = []
    for index, objective_row in enumerate(front_f):
        if len(objective_row) != 2:
            raise ValueError(f"Pareto objective row {index} must contain exactly two values")
        try:
            f1, f2 = float(objective_row[0]), float(objective_row[1])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Pareto objective row {index} must contain finite numbers") from exc
        if not math.isfinite(f1) or not math.isfinite(f2):
            raise ValueError(f"Pareto objective row {index} must contain finite numbers")
        objectives.append((f1, f2))

        decision_row = list(front_x[index])
        if len(decision_row) != 10:
            raise ValueError(f"Pareto decision row {index} must contain exactly 10 departures")
        decisions.append(
            [_non_negative_whole_seconds(value, "departure time") for value in decision_row]
        )

    f1_values = [f[0] for f in objectives]
    f2_values = [f[1] for f in objectives]
    f1_min, f1_max = min(f1_values), max(f1_values)
    f2_min, f2_max = min(f2_values), max(f2_values)

    best_idx = 0
    best_dist = float("inf")
    for idx, (f1, f2) in enumerate(objectives):
        n1 = 0.0 if f1_max == f1_min else (f1 - f1_min) / (f1_max - f1_min)
        n2 = 0.0 if f2_max == f2_min else (f2 - f2_min) / (f2_max - f2_min)
        dist = (n1**2 + n2**2) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best_idx = idx

    best_x = decisions[best_idx]
    best_f1, best_f2 = objectives[best_idx]
    return best_x, best_f1, best_f2


class TrainScheduleProblem(ElementwiseProblem):
    """NSGA-II problem definition for train departure scheduling."""

    def __init__(
        self,
        route,
        heavy_cache: PowerSeriesCache,
        empty_cache: PowerSeriesCache,
        settlement_system: EnergySettlementSystem,
    ) -> None:
        """函数 __init__：执行该模块中的相关处理逻辑。"""
        if not hasattr(route, "signaling_system") or not isinstance(route.signaling_system, dict):
            raise ValueError("route.signaling_system must be a dictionary")
        for cache_name, cache in (("heavy_cache", heavy_cache), ("empty_cache", empty_cache)):
            if not isinstance(cache, PowerSeriesCache):
                raise ValueError(f"{cache_name} must be a PowerSeriesCache")
            if not cache.times:
                raise ValueError(f"{cache_name} must contain at least one trajectory sample")
        if not hasattr(settlement_system, "settle") or not callable(settlement_system.settle):
            raise ValueError("settlement_system must provide a callable settle method")
        super().__init__(n_var=10, n_obj=2, n_constr=0, xl=0, xu=10000, vtype=int)
        self.route = route
        self.heavy_cache = heavy_cache
        self.empty_cache = empty_cache
        self.settlement_system = settlement_system

    def _evaluate(self, x, out, *args, **kwargs) -> None:
        """函数 _evaluate：执行该模块中的相关处理逻辑。"""
        decision_values = list(x)
        if len(decision_values) != 10:
            raise ValueError("schedule decision vector must contain exactly 10 departures")
        departures = [
            _non_negative_whole_seconds(value, "departure time")
            for value in decision_values
        ]
        if any(value > 10000 for value in departures):
            raise ValueError("departure times must not exceed the 10000 s problem bound")
        heavy_times = departures[:5]
        empty_times = departures[5:]

        if (
            violates_headway(heavy_times)
            or violates_headway(empty_times)
            or violates_signal_system(heavy_times, self.heavy_cache, self.route.signaling_system)
            or violates_signal_system(empty_times, self.empty_cache, self.route.signaling_system)
        ):
            out["F"] = [1e9, 1e9]
            return

        power_series_list: List[Dict[int, PowerSample]] = []
        for depart_time in heavy_times:
            power_series_list.extend(self.heavy_cache.shifted_components(depart_time))
        for depart_time in empty_times:
            power_series_list.extend(self.empty_cache.shifted_components(depart_time))

        result = self.settlement_system.settle(power_series_list)
        f1_cost = float(result.total_cost)
        if not math.isfinite(f1_cost):
            raise ValueError(f"settlement total_cost must be finite, got {result.total_cost!r}")

        f2_deviation = schedule_deviation(heavy_times) + schedule_deviation(empty_times)

        if not math.isfinite(f2_deviation):
            raise ValueError(f"schedule deviation must be finite, got {f2_deviation!r}")
        out["F"] = [f1_cost, f2_deviation]


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    if NSGA2 is None:
        raise ImportError("pymoo is required to run NSGA-II. Install with: pip install pymoo")

    config_path = Path("sandbox_config.json")
    if not config_path.exists():
        raise FileNotFoundError("sandbox_config.json not found. Run sandbox_data.py first.")

    route, trains, battery = load_config(config_path)
    heavy_train = trains.get("Heavy")
    empty_train = trains.get("Empty")
    if heavy_train is None or empty_train is None:
        raise ValueError("Missing train parameters in config.")

    heavy_cache = build_power_cache(heavy_train, route)
    empty_cache = build_power_cache(empty_train, route)

    system = EnergySettlementSystem(battery, route.energy_transfer_ranges_km, allow_direct_use=False, allow_storage=True)
    problem = TrainScheduleProblem(route, heavy_cache, empty_cache, system)

    algorithm = NSGA2(
        pop_size=40,
        sampling=IntegerRandomSampling(),
        crossover=SBX(prob=0.9, eta=15, repair=RoundingRepair()),
        mutation=PM(eta=20, repair=RoundingRepair()),
        eliminate_duplicates=True,
    )

    result = minimize(
        problem,
        algorithm,
        termination=get_termination("n_gen", 50),
        seed=42,
        save_history=False,
        verbose=True,
    )

    front_f = result.F.tolist()
    front_x = result.X.tolist()

    fig, ax = plt.subplots(1, 1, figsize=(7, 5))
    ax.scatter([f[1] for f in front_f], [f[0] for f in front_f], s=18, color="#1f77b4")
    ax.set_xlabel("F2 - Headway Deviation")
    ax.set_ylabel("F1 - Net Operating Cost")
    ax.set_title("Pareto Front")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig("pareto_front.png", dpi=150)
    plt.close(fig)

    best_x, best_f1, best_f2 = normalize_and_pick_best(front_f, front_x)
    best_heavy = sorted(best_x[:5])
    best_empty = sorted(best_x[5:])

    print("=== Best Compromise Schedule ===")
    print("Heavy departures (s):", best_heavy)
    print("Empty departures (s):", best_empty)
    print("F1 - Net Operating Cost:", round(best_f1, 2))
    print("F2 - Headway Deviation:", round(best_f2, 2))


if __name__ == "__main__":
    main()
