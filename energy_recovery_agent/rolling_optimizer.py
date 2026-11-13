# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Protocol, Tuple, cast
import hashlib
import json
import math
import random
from bisect import bisect_right
from energy_settlement import (
    EnergySettlementSystem,
    PowerSample,
    StorageDeviceRuntimeState,
    normalize_storage_runtime_states,
    storage_no_direct_effective_loss_kwh,
)
from power_arm_electrical_limits import DynamicPowerArmLimit, StorageSectionInterval
from resource_constraints import (
    ResourceModel,
    ResourceUnavailability,
    check_schedule_resources,
    normalized_resource_constraint_violation,
    post_departure_operation_delay_events,
)
from scheduler_nsga2 import (
    PowerSeriesCache,
    build_power_cache,
    headway_violation_seconds,
    schedule_deviation,
    signal_violation_count,)
from time_space_network import build_time_space_network
from train_simulator import load_config
OBJECTIVE_MODE_BALANCED = "balanced"
OBJECTIVE_MODE_CAPACITY_SURPLUS = "capacity_surplus"
OBJECTIVE_MODE_CAPACITY_TIGHT = "capacity_tight"
ENERGY_SCENARIO_DIRECT_NO_STORAGE = "direct_no_storage"
ENERGY_SCENARIO_STORAGE_NO_DIRECT = "storage_no_direct"
ENERGY_SCENARIO_DIRECT_WITH_STORAGE = "direct_with_storage"
OBJECTIVE_PRIORITY_ENERGY_FIRST = "energy_first"
OBJECTIVE_PRIORITY_COST_FIRST = "cost_first"
OBJECTIVE_PRIORITY_BALANCED = "balanced"
OBJECTIVE_TOLERANCES = (0.01, 0.01, 0.01)


def _validated_whole_seconds(value, field_name: str, *, positive: bool = False) -> int:
    """函数 _validated_whole_seconds：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}") from exc
    minimum = 1.0 if positive else 0.0
    if not math.isfinite(number) or not number.is_integer() or number < minimum:
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{field_name} must be a finite {qualifier} whole number, got {value!r}")
    return int(number)


def _validated_whole_number(value, field_name: str) -> int:
    """函数 _validated_whole_number：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"{field_name} must be a finite whole number, got {value!r}")
    return int(number)

# 命名搜索规模配置，用于收敛诊断和命令行默认值。
SEARCH_PROFILE_PRESETS = {
    "quick": {"population_size": 8, "generations": 3, "elite_count": 3, "note": "Fast smoke / iteration profile."},
    "standard": {"population_size": 12, "generations": 4, "elite_count": 4, "note": "Default project dispatch profile."},
    "large": {"population_size": 24, "generations": 8, "elite_count": 6, "note": "Recommended when energy_flat or core_robust_feasible_count is low."},
}

@dataclass(frozen=True)
class ScheduleTemplate:
    """Low-dimensional timetable template.    Instead of optimizing every train departure independently, this template    describes a pattern that can generate many departures.    """
    heavy_headway_s: int
    empty_headway_s: int
    heavy_empty_phase_s: int
    heavy_count: int
    empty_count: int
    start_time_s: int = 0
    # 空车首次进入储能区段时的线路内停车时间（对能量敏感的基因）。
    flex_zone_hold_s: int = 0
    # 细粒度储能对齐基因：额外调整空车发车时间，用于探索再生/储能时序和咽喉缓冲，
    # 不改变粗粒度追踪间隔模式。
    storage_align_shift_s: int = 0
    # 虚拟储能规划基因。空字符串表示基线/当前储能环境。
    # 储能正式参数尚未取得，因此该基因只搜索可编辑的规划预设。
    storage_preset_id: str = ""
    # 仅由冲突驱动修复器写入的逐列车发车微调；空元组表示保持均匀模板。
    # 普通遗传搜索不变异这些字段，避免无约束地扩大搜索维度。
    heavy_departure_adjustments_s: Tuple[int, ...] = ()
    empty_departure_adjustments_s: Tuple[int, ...] = ()


TemplateKey = Tuple[Any, ...]
ScenarioScore = Tuple["DisturbanceScenario", "ScheduleScore"]

@dataclass(frozen=True)
class GeneratedSchedule:
    """Expanded train departures generated from a schedule template."""
    heavy_departures_s: List[int]
    empty_departures_s: List[int]
    template: ScheduleTemplate
    heavy_train_ids: List[str] = field(default_factory=list)
    empty_train_ids: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        def normalize(prefix: str, times: Iterable[int], ids: Iterable[str]) -> tuple[List[int], List[str]]:
            departures = [_validated_whole_seconds(value, "departure time") for value in times]
            raw_ids = [str(value).strip().upper() for value in ids]
            if not raw_ids:
                raw_ids = [f"{prefix}{index:03d}" for index in range(1, len(departures) + 1)]
            if len(raw_ids) != len(departures) or len(set(raw_ids)) != len(raw_ids):
                raise ValueError(f"{prefix}方向列车ID必须与发车时刻一一对应且唯一。")
            for train_id in raw_ids:
                if len(train_id) != 4 or train_id[0] != prefix or not train_id[1:].isdigit():
                    raise ValueError(f"无效列车ID：{train_id!r}")
            pairs = sorted(zip(departures, raw_ids), key=lambda item: (item[0], item[1]))
            return [item[0] for item in pairs], [item[1] for item in pairs]

        heavy_times, heavy_ids = normalize("H", self.heavy_departures_s, self.heavy_train_ids)
        empty_times, empty_ids = normalize("E", self.empty_departures_s, self.empty_train_ids)
        object.__setattr__(self, "heavy_departures_s", heavy_times)
        object.__setattr__(self, "empty_departures_s", empty_times)
        object.__setattr__(self, "heavy_train_ids", heavy_ids)
        object.__setattr__(self, "empty_train_ids", empty_ids)


@dataclass(frozen=True)
class DynamicTrainAddition:
    """滚动窗口内由外部确认加开的固定发车任务。"""

    train_id: str
    train_type: str
    departure_s: int

    def __post_init__(self) -> None:
        train_id = str(self.train_id).strip().upper()
        train_type = str(self.train_type).strip()
        prefix = "H" if train_type == "Heavy" else "E" if train_type == "Empty" else ""
        if not prefix or len(train_id) != 4 or train_id[0] != prefix or not train_id[1:].isdigit():
            raise ValueError("加开列车ID必须与Heavy/Empty类型一致并使用H001/E001格式。")
        object.__setattr__(self, "train_id", train_id)
        object.__setattr__(self, "train_type", train_type)
        object.__setattr__(self, "departure_s", _validated_whole_seconds(self.departure_s, "departure_s"))

@dataclass(frozen=True)
class DisturbanceScenario:
    """A lightweight operation disturbance scenario."""
    name: str
    heavy_delay_s: int = 0
    empty_delay_s: int = 0
    heavy_headway_stretch_s: int = 0
    empty_headway_stretch_s: int = 0
    cost_multiplier: float = 1.0
    core_for_feasibility: bool = True

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        if type(self.core_for_feasibility) is not bool:
            raise ValueError("core_for_feasibility must be a boolean")
        for field_name in (
            "heavy_delay_s",
            "empty_delay_s",
            "heavy_headway_stretch_s",
            "empty_headway_stretch_s",
        ):
            raw_value = getattr(self, field_name)
            if isinstance(raw_value, bool):
                raise ValueError(f"{field_name} must be a finite whole number, got {raw_value!r}")
            number = float(raw_value)
            if not math.isfinite(number) or not number.is_integer() or number < 0.0:
                raise ValueError(f"{field_name} must be a finite whole number, got {raw_value!r}")
            object.__setattr__(self, field_name, int(number))
        if isinstance(self.cost_multiplier, bool):
            raise ValueError(f"cost_multiplier must be finite and non-negative, got {self.cost_multiplier!r}")
        multiplier = float(self.cost_multiplier)
        if not math.isfinite(multiplier) or multiplier < 0.0:
            raise ValueError(
                f"cost_multiplier must be finite and non-negative, got {self.cost_multiplier!r}"
            )
        object.__setattr__(self, "cost_multiplier", multiplier)

@dataclass(frozen=True)
class ScheduleScore:
    """Multi-objective score for a generated schedule."""
    feasible: bool
    total_cost: float
    headway_deviation: float
    worst_case_cost: float
    worst_case_headway_deviation: float
    scenario_count: int
    time_space_node_count: int = 0
    time_space_arc_count: int = 0
    resource_conflict_count: int = 0
    flow_continuity_feasible: bool = True
    flow_continuity_violation_count: int = 0
    capacity_margin_s: float = 0.0
    objective_mode: str = OBJECTIVE_MODE_BALANCED
    objective_priority: str = OBJECTIVE_PRIORITY_ENERGY_FIRST
    energy_scenario: str = ENERGY_SCENARIO_STORAGE_NO_DIRECT
    direct_used_kwh: float = 0.0
    battery_charge_kwh: float = 0.0
    battery_discharge_kwh: float = 0.0
    wasted_kwh: float = 0.0
    grid_kwh: float = 0.0
    final_soc_kwh: float = 0.0
    constraint_violation: float = 0.0
    headway_violation_s: float = 0.0
    signal_violation_count: int = 0
    resource_overlap_violation_s: float = 0.0
    traction_supply_excess_kwh: float = 0.0
    regen_absorption_excess_kwh: float = 0.0
    electrical_constraint_violation_kwh: float = 0.0
    # 追加字段，保持旧调用方使用的位置参数构造顺序不变。
    final_soc_deviation_kwh: float = 0.0
    storage_efficiency: float = 1.0
    final_soc_shortfall_kwh: float = 0.0
    # 每次评价得到的派生能量损失。稳健汇总必须按场景平均该值，不能由平均后的充放电流重新计算，
    # 因为可再利用再生能量的截断关系是非线性的。
    effective_regen_loss_kwh: float | None = None

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        if type(self.feasible) is not bool:
            raise ValueError("feasible must be a boolean")
        if type(self.flow_continuity_feasible) is not bool:
            raise ValueError("flow_continuity_feasible must be a boolean")
        positive_whole_fields = ("scenario_count",)
        non_negative_whole_fields = (
            "time_space_node_count",
            "time_space_arc_count",
            "resource_conflict_count",
            "flow_continuity_violation_count",
            "signal_violation_count",
        )
        for field_name in positive_whole_fields + non_negative_whole_fields:
            minimum = 1 if field_name in positive_whole_fields else 0
            object.__setattr__(
                self,
                field_name,
                _validated_whole_seconds(getattr(self, field_name), field_name, positive=minimum == 1),
            )
        non_negative_fields = (
            "total_cost",
            "headway_deviation",
            "worst_case_cost",
            "worst_case_headway_deviation",
            "capacity_margin_s",
            "direct_used_kwh",
            "battery_charge_kwh",
            "battery_discharge_kwh",
            "wasted_kwh",
            "grid_kwh",
            "final_soc_kwh",
            "constraint_violation",
            "headway_violation_s",
            "resource_overlap_violation_s",
            "traction_supply_excess_kwh",
            "regen_absorption_excess_kwh",
            "electrical_constraint_violation_kwh",
            "final_soc_deviation_kwh",
            "storage_efficiency",
            "final_soc_shortfall_kwh",
        )
        for field_name in non_negative_fields:
            raw_value = getattr(self, field_name)
            if isinstance(raw_value, bool):
                raise ValueError(f"{field_name} must be a finite non-negative number")
            try:
                number = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field_name} must be a finite non-negative number") from exc
            if not math.isfinite(number) or number < 0.0:
                raise ValueError(f"{field_name} must be a finite non-negative number")
            object.__setattr__(self, field_name, number)
        if self.effective_regen_loss_kwh is None:
            # 兼容旧调用方：旧调用方构造评分时可能没有提供派生指标。
            effective_loss = storage_no_direct_effective_loss_kwh(
                self.wasted_kwh,
                self.battery_charge_kwh,
                self.battery_discharge_kwh,
                self.final_soc_deviation_kwh,
                self.storage_efficiency,
                self.final_soc_shortfall_kwh,
            )
        else:
            raw_effective_loss = self.effective_regen_loss_kwh
            if isinstance(raw_effective_loss, bool):
                raise ValueError("effective_regen_loss_kwh must be a finite non-negative number")
            try:
                effective_loss = float(raw_effective_loss)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "effective_regen_loss_kwh must be a finite non-negative number"
                ) from exc
            if not math.isfinite(effective_loss) or effective_loss < 0.0:
                raise ValueError("effective_regen_loss_kwh must be a finite non-negative number")
        object.__setattr__(self, "effective_regen_loss_kwh", float(effective_loss))
        if self.storage_efficiency > 1.0:
            raise ValueError("storage_efficiency must be at most 1")
        if self.objective_mode not in {
            OBJECTIVE_MODE_BALANCED,
            OBJECTIVE_MODE_CAPACITY_SURPLUS,
            OBJECTIVE_MODE_CAPACITY_TIGHT,
        }:
            raise ValueError(f"Unsupported objective_mode: {self.objective_mode!r}")
        if self.objective_priority not in {
            OBJECTIVE_PRIORITY_ENERGY_FIRST,
            OBJECTIVE_PRIORITY_COST_FIRST,
            OBJECTIVE_PRIORITY_BALANCED,
        }:
            raise ValueError(f"Unsupported objective_priority: {self.objective_priority!r}")
        if self.energy_scenario not in {
            ENERGY_SCENARIO_DIRECT_NO_STORAGE,
            ENERGY_SCENARIO_STORAGE_NO_DIRECT,
            ENERGY_SCENARIO_DIRECT_WITH_STORAGE,
        }:
            raise ValueError(f"Unsupported energy_scenario: {self.energy_scenario!r}")

@dataclass(frozen=True)
class TemplateSearchConfig:
    """Configuration for low-dimensional template search."""
    method: str = "nsga2"
    population_size: int = 16
    generations: int = 5
    elite_count: int = 4
    mutation_probability: float = 0.45
    headway_mutation_s: int = 300
    phase_mutation_s: int = 300
    hold_mutation_s: int = 180
    storage_shift_mutation_s: int = 300
    min_headway_s: int = 300
    max_headway_s: int = 4200
    max_phase_s: int = 5400
    max_hold_s: int = 900
    max_storage_align_shift_s: int = 1200
    parallel_workers: int = 1
    seed: int = 42
    # 将可编辑的虚拟储能预设（容量、功率、覆盖范围）作为能量基因搜索。
    enable_storage_preset_search: bool = True
    storage_preset_ids: Tuple[str, ...] = ()
    storage_preset_mutation_probability: float = 0.55
    # 小规模最优性基准可指定离散候选域。生产配置保持空元组，沿用原连续整数边界。
    allowed_heavy_headways_s: Tuple[int, ...] = ()
    allowed_empty_headways_s: Tuple[int, ...] = ()
    allowed_phases_s: Tuple[int, ...] = ()
    allowed_holds_s: Tuple[int, ...] = ()
    allowed_storage_align_shifts_s: Tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        method = str(self.method).strip().lower()
        if method not in {"nsga2", "grid", "evolutionary"}:
            raise ValueError(f"Unsupported template search method: {self.method!r}")
        object.__setattr__(self, "method", method)

        positive_whole_fields = ("population_size", "generations", "elite_count", "parallel_workers")
        non_negative_whole_fields = (
            "headway_mutation_s",
            "phase_mutation_s",
            "hold_mutation_s",
            "storage_shift_mutation_s",
            "min_headway_s",
            "max_headway_s",
            "max_phase_s",
            "max_hold_s",
            "max_storage_align_shift_s",
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
        if self.max_headway_s < self.min_headway_s:
            raise ValueError("max_headway_s must be greater than or equal to min_headway_s")

        for field_name in ("mutation_probability", "storage_preset_mutation_probability"):
            raw_value = getattr(self, field_name)
            if isinstance(raw_value, bool):
                raise ValueError(f"{field_name} must be finite and between 0 and 1")
            try:
                probability = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field_name} must be finite and between 0 and 1") from exc
            if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                raise ValueError(f"{field_name} must be finite and between 0 and 1")
            object.__setattr__(self, field_name, probability)

        if isinstance(self.seed, bool):
            raise ValueError(f"seed must be a finite whole number, got {self.seed!r}")
        try:
            seed = float(self.seed)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"seed must be a finite whole number, got {self.seed!r}") from exc
        if not math.isfinite(seed) or not seed.is_integer():
            raise ValueError(f"seed must be a finite whole number, got {self.seed!r}")
        object.__setattr__(self, "seed", int(seed))
        if type(self.enable_storage_preset_search) is not bool:
            raise ValueError("enable_storage_preset_search must be a boolean")
        object.__setattr__(self, "storage_preset_ids", tuple(str(item) for item in self.storage_preset_ids))

        discrete_domains = {
            "allowed_heavy_headways_s": (self.min_headway_s, self.max_headway_s),
            "allowed_empty_headways_s": (self.min_headway_s, self.max_headway_s),
            "allowed_phases_s": (0, self.max_phase_s),
            "allowed_holds_s": (0, self.max_hold_s),
            "allowed_storage_align_shifts_s": (
                -self.max_storage_align_shift_s,
                self.max_storage_align_shift_s,
            ),
        }
        for field_name, (minimum, maximum) in discrete_domains.items():
            normalized = []
            for raw_value in getattr(self, field_name):
                if isinstance(raw_value, bool):
                    raise ValueError(f"{field_name} must contain finite whole numbers")
                try:
                    number = float(raw_value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"{field_name} must contain finite whole numbers"
                    ) from exc
                if not math.isfinite(number) or not number.is_integer():
                    raise ValueError(f"{field_name} must contain finite whole numbers")
                value = int(number)
                if not minimum <= value <= maximum:
                    raise ValueError(
                        f"{field_name} value {value} is outside [{minimum}, {maximum}]"
                    )
                normalized.append(value)
            object.__setattr__(self, field_name, tuple(sorted(set(normalized))))

def _normalize_observed_train_delays(
    values: Iterable[Tuple[str, int]],
) -> Tuple[Tuple[str, int], ...]:
    """规范化逐列车晚点并拒绝未知编号、重复列车和负值。"""

    normalized: Dict[str, int] = {}
    for index, item in enumerate(values):
        if isinstance(item, (str, bytes)):
            raise ValueError(f"observed_train_delays_s[{index}]必须是二元组。")
        try:
            train_id, raw_delay_s = item
        except (TypeError, ValueError) as exc:
            raise ValueError(f"observed_train_delays_s[{index}]必须是二元组。") from exc
        train_id = str(train_id).strip().upper()
        if (
            len(train_id) != 4
            or train_id[0] not in {"H", "E"}
            or not train_id[1:].isdigit()
            or int(train_id[1:]) <= 0
        ):
            raise ValueError(f"无效逐列车编号：{train_id!r}，应使用H001或E001格式。")
        if train_id in normalized:
            raise ValueError(f"逐列车晚点编号重复：{train_id}")
        normalized[train_id] = _validated_whole_seconds(
            raw_delay_s, f"observed_train_delays_s[{train_id}]"
        )
    return tuple(sorted(normalized.items()))


def _normalize_dynamic_event_state(instance: Any) -> None:
    cancelled = tuple(str(value).strip().upper() for value in instance.cancelled_train_ids)
    if len(set(cancelled)) != len(cancelled):
        raise ValueError("cancelled_train_ids不能重复。")
    for train_id in cancelled:
        _normalize_observed_train_delays(((train_id, 0),))
    additions = tuple(instance.added_trains)
    if any(not isinstance(item, DynamicTrainAddition) for item in additions):
        raise TypeError("added_trains必须只包含DynamicTrainAddition。")
    addition_ids = [item.train_id for item in additions]
    if len(set(addition_ids)) != len(addition_ids):
        raise ValueError("added_trains列车ID不能重复。")
    if set(cancelled).intersection(addition_ids):
        raise ValueError("同一动态状态不能同时取消并加开同一列车。")
    outages = tuple(instance.resource_unavailabilities)
    if any(not isinstance(item, ResourceUnavailability) for item in outages):
        raise TypeError("resource_unavailabilities必须只包含ResourceUnavailability。")
    power_limits = tuple(instance.dynamic_power_arm_limits)
    if any(not isinstance(item, DynamicPowerArmLimit) for item in power_limits):
        raise TypeError("dynamic_power_arm_limits必须只包含DynamicPowerArmLimit。")
    object.__setattr__(instance, "cancelled_train_ids", tuple(sorted(cancelled)))
    object.__setattr__(instance, "added_trains", additions)
    object.__setattr__(instance, "resource_unavailabilities", outages)
    object.__setattr__(instance, "dynamic_power_arm_limits", power_limits)


@dataclass(frozen=True)
class RollingWindowState:
    """Current online state for MPC-style rolling optimization."""
    current_time_s: int
    locked_heavy_departures_s: List[int]
    locked_empty_departures_s: List[int]
    observed_heavy_delay_s: int = 0
    observed_empty_delay_s: int = 0
    # 按H001/E001稳定编号记录的逐列车晚点；仅允许作用于尚未锁定的未来发车。
    observed_train_delays_s: Tuple[Tuple[str, int], ...] = ()
    # 当前滚动窗口起点的储能总 SOC；None 表示沿用结算器静态初值。
    storage_soc_kwh: float | None = None
    # 新接口按设备携带 SOC、可用状态和临时功率上限；显式提供后不得再使用汇总 SOC。
    storage_device_states: Tuple[StorageDeviceRuntimeState, ...] = ()
    cancelled_train_ids: Tuple[str, ...] = ()
    added_trains: Tuple[DynamicTrainAddition, ...] = ()
    resource_unavailabilities: Tuple[ResourceUnavailability, ...] = ()
    dynamic_power_arm_limits: Tuple[DynamicPowerArmLimit, ...] = ()
    # 这些模板基因影响已锁定列车的完整运行轨迹和结算，不只是发车时刻。
    # 保留早期 MPC 决策已提交的策略，防止后续周期改写历史停车、储能几何范围或由此产生的 SOC。
    locked_empty_storage_hold_s: int | None = None
    locked_storage_preset_id: str = ""

    def __post_init__(self) -> None:
        normalized = normalize_storage_runtime_states(self.storage_device_states)
        if self.storage_soc_kwh is not None and normalized:
            raise ValueError(
                "storage_soc_kwh and storage_device_states cannot be supplied together"
            )
        object.__setattr__(
            self,
            "storage_device_states",
            tuple(normalized[key] for key in sorted(normalized)),
        )
        object.__setattr__(
            self,
            "observed_train_delays_s",
            _normalize_observed_train_delays(self.observed_train_delays_s),
        )
        _normalize_dynamic_event_state(self)


@dataclass(frozen=True)
class RollingCycleObservation:
    """一个滚动周期开始前由现场状态或合成测试注入的观测。"""

    observed_heavy_delay_s: int = 0
    observed_empty_delay_s: int = 0
    observed_train_delays_s: Tuple[Tuple[str, int], ...] = ()
    storage_soc_kwh: float | None = None
    storage_device_states: Tuple[StorageDeviceRuntimeState, ...] = ()
    cancelled_train_ids: Tuple[str, ...] = ()
    added_trains: Tuple[DynamicTrainAddition, ...] = ()
    resource_unavailabilities: Tuple[ResourceUnavailability, ...] = ()
    dynamic_power_arm_limits: Tuple[DynamicPowerArmLimit, ...] = ()

    def __post_init__(self) -> None:
        normalized = normalize_storage_runtime_states(self.storage_device_states)
        if self.storage_soc_kwh is not None and normalized:
            raise ValueError(
                "storage_soc_kwh and storage_device_states cannot be supplied together"
            )
        object.__setattr__(
            self,
            "storage_device_states",
            tuple(normalized[key] for key in sorted(normalized)),
        )
        object.__setattr__(
            self,
            "observed_train_delays_s",
            _normalize_observed_train_delays(self.observed_train_delays_s),
        )
        _normalize_dynamic_event_state(self)

@dataclass(frozen=True)
class RollingOptimizationResult:
    """Chosen rolling-window plan and the portion to execute now."""
    schedule: GeneratedSchedule
    # 叠加本轮已观测晚点后的正常场景候选运行图；不可行时仅用于诊断。
    execution_schedule: GeneratedSchedule
    # 通过提交门禁后实际生效的运行图；SOC结算只能使用该状态。
    committed_execution_schedule: GeneratedSchedule
    score: ScheduleScore
    executable_heavy_departures_s: List[int]
    executable_empty_departures_s: List[int]
    core_robust_feasible: bool
    commit_status: str
    operational_intervention_required: bool
    # 提交门禁后的生产控制状态；用于平台决定执行、等待或升级人工处置。
    safety_state: str = "normal"
    safety_action: str = "execute_committed_schedule"
    safety_attempt_count: int = 1
    safety_transition_history: Tuple[Dict, ...] = ()
    ranked_candidates: Tuple[Tuple[ScheduleTemplate, ScheduleScore], ...] = ()
    pareto_candidates: Tuple[Tuple[ScheduleTemplate, ScheduleScore], ...] = ()
    candidate_count: int = 0
    feasible_candidate_count: int = 0
    diagnostic: str = ""
    search_diagnostics: Dict = field(default_factory=dict)
    selected_scenario_diagnostics: Tuple[Dict, ...] = ()
    # 仅供同一次运行的后处理复用，避免报告阶段重新执行全部扰动场景。
    candidate_scenario_scores: Dict[TemplateKey, Tuple[ScenarioScore, ...]] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )


@dataclass(frozen=True)
class RollingCommitDecision:
    """滚动候选经过核心稳健门禁后的可执行提交结果。"""

    committed_execution_schedule: GeneratedSchedule
    executable_heavy_departures_s: List[int]
    executable_empty_departures_s: List[int]
    core_robust_feasible: bool
    commit_status: str
    operational_intervention_required: bool
    reason: str


@dataclass(frozen=True)
class RollingSafetyPolicy:
    """不可行提交后的有界重试、等待和人工升级策略。"""

    enable_automatic_retry: bool = True
    max_retries_per_cycle: int = 1
    retry_horizon_multiplier: float = 1.5
    retry_population_multiplier: float = 2.0
    retry_generation_increment: int = 1
    max_horizon_s: int = 21600
    max_population_size: int = 48
    max_generations: int = 12
    manual_after_consecutive_withheld: int = 2
    escalate_recovery_on_retry: bool = True

    def __post_init__(self) -> None:
        """拒绝可能造成无限重试或无界资源消耗的策略。"""

        for field_name in ("enable_automatic_retry", "escalate_recovery_on_retry"):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"{field_name} must be a boolean")
        for field_name, minimum in (
            ("max_retries_per_cycle", 0),
            ("retry_generation_increment", 0),
            ("max_horizon_s", 1),
            ("max_population_size", 1),
            ("max_generations", 1),
            ("manual_after_consecutive_withheld", 1),
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{field_name} must be an integer >= {minimum}")
        for field_name in ("retry_horizon_multiplier", "retry_population_multiplier"):
            value = float(getattr(self, field_name))
            if not math.isfinite(value) or value < 1.0:
                raise ValueError(f"{field_name} must be finite and >= 1.0")


def _rolling_observation_fingerprint(state: RollingWindowState) -> str:
    """形成不含滚动时钟的观测摘要，用于判断现场状态是否发生变化。"""

    payload = {
        "observed_heavy_delay_s": state.observed_heavy_delay_s,
        "observed_empty_delay_s": state.observed_empty_delay_s,
        "observed_train_delays_s": list(state.observed_train_delays_s),
        "storage_soc_kwh": state.storage_soc_kwh,
        "storage_device_states": [
            {
                "storage_section_id": item.storage_section_id,
                "soc_kwh": item.soc_kwh,
                "available": item.available,
                "max_charge_power_kw": item.max_charge_power_kw,
                "max_discharge_power_kw": item.max_discharge_power_kw,
            }
            for item in state.storage_device_states
        ],
        "locked_heavy_departures_s": list(state.locked_heavy_departures_s),
        "locked_empty_departures_s": list(state.locked_empty_departures_s),
        "cancelled_train_ids": list(state.cancelled_train_ids),
        "added_trains": [
            {
                "train_id": t.train_id,
                "train_type": t.train_type,
                "departure_s": t.departure_s,
            }
            for t in state.added_trains
        ],
        "resource_unavailabilities": [
            {
                "event_id": r.event_id,
                "resource_id": r.resource_id,
                "resource_type": r.resource_type,
                "start_time_s": r.start_time_s,
                "end_time_s": r.end_time_s,
            }
            for r in state.resource_unavailabilities
        ],
        "dynamic_power_arm_limits": [
            {
                "event_id": p.event_id,
                "power_arm_id": p.power_arm_id,
                "start_time_s": p.start_time_s,
                "end_time_s": p.end_time_s,
                "max_traction_supply_kw": p.max_traction_supply_kw,
                "max_regen_absorption_kw": p.max_regen_absorption_kw,
                "max_grid_feedback_kw": p.max_grid_feedback_kw,
            }
            for p in state.dynamic_power_arm_limits
        ],
        "locked_empty_storage_hold_s": state.locked_empty_storage_hold_s,
        "locked_storage_preset_id": state.locked_storage_preset_id,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _rolling_request_fingerprint(
    state: RollingWindowState,
    base_template: ScheduleTemplate,
    *,
    horizon_s: int,
    execute_window_s: int,
    search_config: TemplateSearchConfig | None,
    enable_recovery: bool,
    allow_infeasible_commit_for_experiment: bool,
) -> str:
    """形成完整求解请求摘要，同一请求只执行一次。"""

    payload = {
        "state": state,
        "base_template": base_template,
        "horizon_s": horizon_s,
        "execute_window_s": execute_window_s,
        "search_config": search_config,
        "enable_recovery": enable_recovery,
        "allow_infeasible_commit_for_experiment": allow_infeasible_commit_for_experiment,
    }
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def _expanded_retry_config(
    search_config: TemplateSearchConfig | None,
    policy: RollingSafetyPolicy,
    retry_index: int,
) -> TemplateSearchConfig:
    """在策略上限内逐级扩大搜索预算。"""

    base = search_config or TemplateSearchConfig()
    factor = policy.retry_population_multiplier ** retry_index
    population_size = min(
        policy.max_population_size,
        max(base.population_size, int(math.ceil(base.population_size * factor))),
    )
    generations = min(
        policy.max_generations,
        base.generations + policy.retry_generation_increment * retry_index,
    )
    return replace(
        base,
        population_size=population_size,
        generations=generations,
        elite_count=min(base.elite_count, population_size),
    )


def gate_rolling_execution_commit(
    execution_schedule: GeneratedSchedule,
    selected_scenario_diagnostics: Iterable[Dict],
    *,
    current_time_s: int,
    execute_window_s: int,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
    allow_infeasible_commit_for_experiment: bool = False,
    candidate_feasible: bool = True,
) -> RollingCommitDecision:
    """只提交通过全部核心场景的新增发车；实验覆盖必须显式开启。"""

    if not isinstance(allow_infeasible_commit_for_experiment, bool):
        raise TypeError("allow_infeasible_commit_for_experiment must be a boolean")
    if type(candidate_feasible) is not bool:
        raise TypeError("candidate_feasible must be a boolean")
    current_time_s = _validated_whole_seconds(current_time_s, "current_time_s")
    execute_window_s = _validated_whole_seconds(
        execute_window_s, "execute_window_s", positive=True
    )
    locked_heavy = {
        _validated_whole_seconds(value, "locked_heavy_departures_s")
        for value in locked_heavy_departures_s
    }
    locked_empty = {
        _validated_whole_seconds(value, "locked_empty_departures_s")
        for value in locked_empty_departures_s
    }
    if (not locked_heavy.issubset(execution_schedule.heavy_departures_s)
            or not locked_empty.issubset(execution_schedule.empty_departures_s)):
        raise ValueError("提交候选遗漏或移动了已锁定列车，拒绝提交")
    # 过去时刻不是历史真实性证明，只有调用方给出的锁定状态才有权确认历史。
    invalid_history = any(t < current_time_s and t not in locked_heavy
                          for t in execution_schedule.heavy_departures_s) or any(
        t < current_time_s and t not in locked_empty for t in execution_schedule.empty_departures_s)
    core_rows = [
        row for row in selected_scenario_diagnostics
        if bool(row.get("core_for_feasibility"))
    ]
    core_robust_feasible = candidate_feasible and not invalid_history and bool(core_rows) and all(
        bool(row.get("feasible")) for row in core_rows
    )
    execute_until_s = current_time_s + execute_window_s
    proposed_heavy = [
        t for t in execution_schedule.heavy_departures_s
        if current_time_s <= t < execute_until_s
    ]
    proposed_empty = [
        t for t in execution_schedule.empty_departures_s
        if current_time_s <= t < execute_until_s
    ]
    if not invalid_history and (core_robust_feasible or allow_infeasible_commit_for_experiment):
        experimental = not core_robust_feasible
        return RollingCommitDecision(
            committed_execution_schedule=execution_schedule,
            executable_heavy_departures_s=proposed_heavy,
            executable_empty_departures_s=proposed_empty,
            core_robust_feasible=core_robust_feasible,
            commit_status=(
                "committed_infeasible_experiment_only"
                if experimental
                else "committed_robust_feasible"
            ),
            operational_intervention_required=experimental,
            reason=(
                "实验覆盖已显式允许提交核心稳健不可行候选；该结果不得用于生产执行。"
                if experimental
                else "所选运行图通过全部核心稳健场景，允许提交执行窗口内决策。"
            ),
        )

    # 已发生或显式锁定的列车仍属于真实执行状态；只扣留本轮尚未提交的新发车。
    committed_heavy = [
        (t, train_id)
        for t, train_id in zip(execution_schedule.heavy_departures_s, execution_schedule.heavy_train_ids)
        if t in locked_heavy
    ]
    committed_empty = [
        (t, train_id)
        for t, train_id in zip(execution_schedule.empty_departures_s, execution_schedule.empty_train_ids)
        if t in locked_empty
    ]
    committed_schedule = GeneratedSchedule(
        heavy_departures_s=[item[0] for item in committed_heavy],
        empty_departures_s=[item[0] for item in committed_empty],
        template=execution_schedule.template,
        heavy_train_ids=[item[1] for item in committed_heavy],
        empty_train_ids=[item[1] for item in committed_empty],
    )
    return RollingCommitDecision(
        committed_execution_schedule=committed_schedule,
        executable_heavy_departures_s=[t for t in proposed_heavy if t in locked_heavy],
        executable_empty_departures_s=[t for t in proposed_empty if t in locked_empty],
        core_robust_feasible=False,
        commit_status="withheld_infeasible",
        operational_intervention_required=True,
        reason=("候选包含未经锁定状态确认的过去发车；即使实验覆盖也不得创造执行历史。" if invalid_history else
            "所选运行图未通过全部核心稳健场景；新增决策已扣留，"
            "仅保留已发生或显式锁定列车并要求运营干预。"
        ),
    )

def generate_schedule(template: ScheduleTemplate) -> GeneratedSchedule:
    """Expand a low-dimensional template into individual departures.    ``storage_align_shift_s`` remains a pure departure-phase gene.    ``flex_zone_hold_s`` is intentionally *not* applied here as another global    empty-train departure shift; it is applied later as an in-route hold at the    first storage-section entry so the gene can change energy timing, not only    feasibility.    """
    heavy_headway_s = _validated_whole_seconds(
        template.heavy_headway_s, "template.heavy_headway_s", positive=True
    )
    empty_headway_s = _validated_whole_seconds(
        template.empty_headway_s, "template.empty_headway_s", positive=True
    )
    phase_s = _validated_whole_seconds(
        template.heavy_empty_phase_s, "template.heavy_empty_phase_s"
    )
    start_time_s = _validated_whole_seconds(template.start_time_s, "template.start_time_s")
    _validated_whole_seconds(template.flex_zone_hold_s, "template.flex_zone_hold_s")
    storage_shift_s = _validated_whole_number(
        template.storage_align_shift_s, "template.storage_align_shift_s"
    )
    heavy_count = _validated_whole_seconds(
        template.heavy_count,
        "template.heavy_count",
    )
    empty_count = _validated_whole_seconds(
        template.empty_count,
        "template.empty_count",
    )
    heavy_departures = [
        start_time_s + idx * heavy_headway_s
        for idx in range(heavy_count)
    ]
    empty_departures = [
        start_time_s + phase_s + idx * empty_headway_s
        for idx in range(empty_count)
    ]
    if storage_shift_s:
        empty_departures = [t + storage_shift_s for t in empty_departures]
    if empty_departures and empty_departures[0] < 0:
        raise ValueError(
            "template.storage_align_shift_s makes the first empty-train departure negative"
        )
    def apply_adjustments(
        departures: List[int],
        raw_adjustments: Iterable[int],
        field_name: str,
    ) -> List[int]:
        """校验并应用冲突修复器生成的逐列车发车微调。"""

        adjustments = tuple(
            _validated_whole_number(value, field_name)
            for value in raw_adjustments
        )
        if not adjustments:
            return departures
        if len(adjustments) != len(departures):
            raise ValueError(f"{field_name} length must match the train count")
        adjusted = [time_s + delta_s for time_s, delta_s in zip(departures, adjustments)]
        if any(time_s < 0 for time_s in adjusted):
            raise ValueError(f"{field_name} makes a departure negative")
        if any(right <= left for left, right in zip(adjusted[:-1], adjusted[1:])):
            raise ValueError(f"{field_name} must preserve train departure order")
        return adjusted

    heavy_departures = apply_adjustments(
        heavy_departures,
        template.heavy_departure_adjustments_s,
        "template.heavy_departure_adjustments_s",
    )
    empty_departures = apply_adjustments(
        empty_departures,
        template.empty_departure_adjustments_s,
        "template.empty_departure_adjustments_s",
    )
    return GeneratedSchedule(
        heavy_departures_s=heavy_departures,
        empty_departures_s=empty_departures,
        template=template,
        heavy_train_ids=[f"H{index:03d}" for index in range(1, len(heavy_departures) + 1)],
        empty_train_ids=[f"E{index:03d}" for index in range(1, len(empty_departures) + 1)],
    )


class RollingTimeBoundaryError(ValueError):
    """新服务不能以过去时刻作为请求输入；已执行历史必须通过锁定状态提供。"""


def rolling_future_template(template: ScheduleTemplate, current_time_s: int, *,
                            reject_past: bool = False) -> ScheduleTemplate:
    """保持新列车数量和同类间隔，将搜索/修复的越界时间平移至窗口起点。

    输入基线用reject_past拒绝非法请求；候选限幅后使用实际模板重新完整评价。
    不过滤列车、不移动另行合并的锁定历史，也不裁剪逐车间隔。
    """
    current = _validated_whole_seconds(current_time_s, "current_time_s")
    phase = _validated_whole_seconds(template.heavy_empty_phase_s, "heavy_empty_phase_s")
    shift = _validated_whole_number(template.storage_align_shift_s, "storage_align_shift_s")
    changes: Dict[str, Any] = {"start_time_s": current}
    safe_shift = max(shift, -(current + phase))  # generate_schedule的调整前绝对时间下界。
    if safe_shift != shift:
        changes["storage_align_shift_s"] = safe_shift
    for prefix, offset in (("heavy", 0), ("empty", phase + shift)):
        count = _validated_whole_seconds(getattr(template, f"{prefix}_count"), f"{prefix}_count")
        raw = tuple(_validated_whole_number(v, f"{prefix}_departure_adjustments_s")
                    for v in getattr(template, f"{prefix}_departure_adjustments_s"))
        if raw and len(raw) != count:
            raise ValueError(f"{prefix}_departure_adjustments_s length must match the train count")
        first = offset + (raw[0] if raw else 0)
        if count and first < 0 and reject_past:
            raise RollingTimeBoundaryError(f"{prefix}新列车早于滚动起点；历史列车必须通过锁定状态提供")
        correction = max(0, -first) if count else 0
        if prefix == "empty":
            correction += shift - safe_shift
        if count and correction:
            changes[f"{prefix}_departure_adjustments_s"] = tuple(v + correction for v in (raw or (0,) * count))
    normalized = replace(template, **changes)
    generate_schedule(normalized)  # 仍校验数量、绝对时间、逐车顺序，不能用限幅掩盖乱序输入。
    return normalized


def apply_dynamic_train_services(
    schedule: GeneratedSchedule,
    cancelled_train_ids: Iterable[str],
    added_trains: Iterable[DynamicTrainAddition],
    *,
    current_time_s: int,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
) -> GeneratedSchedule:
    """执行已确认的取消和加车事件，并保护已执行/已锁定历史。"""

    current_s = _validated_whole_seconds(current_time_s, "current_time_s")
    cancelled = {str(value).strip().upper() for value in cancelled_train_ids}
    additions = tuple(added_trains)
    all_ids = set(schedule.heavy_train_ids) | set(schedule.empty_train_ids)
    unknown = sorted(cancelled - all_ids)
    if unknown:
        raise ValueError(f"取消事件引用了当前运行图不存在的列车：{unknown}")
    locked_by_type = {
        "Heavy": {_validated_whole_seconds(value, "locked_heavy_departures_s") for value in locked_heavy_departures_s},
        "Empty": {_validated_whole_seconds(value, "locked_empty_departures_s") for value in locked_empty_departures_s},
    }

    def retained(train_type: str, times: List[int], ids: List[str]) -> list[tuple[int, str]]:
        rows = []
        for time_s, train_id in zip(times, ids):
            if train_id in cancelled:
                if time_s < current_s or time_s in locked_by_type[train_type]:
                    raise ValueError(f"不能取消已执行或已锁定列车：{train_id}")
                continue
            rows.append((time_s, train_id))
        return rows

    heavy = retained("Heavy", schedule.heavy_departures_s, schedule.heavy_train_ids)
    empty_ = retained("Empty", schedule.empty_departures_s, schedule.empty_train_ids)
    effective_ids = {train_id for _time_s, train_id in heavy + empty_}
    for addition in additions:
        if addition.train_id in effective_ids:
            raise ValueError(f"加开列车ID与现有列车重复：{addition.train_id}")
        if addition.departure_s < current_s:
            raise ValueError(f"加开列车不能写入已执行历史：{addition.train_id}")
        target = heavy if addition.train_type == "Heavy" else empty_
        target.append((addition.departure_s, addition.train_id))
        effective_ids.add(addition.train_id)
    heavy.sort()
    empty_.sort()
    return GeneratedSchedule(
        [time_s for time_s, _train_id in heavy],
        [time_s for time_s, _train_id in empty_],
        schedule.template,
        [train_id for _time_s, train_id in heavy],
        [train_id for _time_s, train_id in empty_],
    )

def apply_storage_entry_hold(
    series: Dict[int, PowerSample],
    hold_s: int,) -> Dict[int, PowerSample]:
    """Delay all samples after the first storage-section entry by ``hold_s``.    This approximates a controlled hold near the storage-equipped zone so empty    and heavy regenerative/traction windows can realign. It is a planning gene,    not a claim that field operations currently use this exact hold rule.    """
    hold_s = _validated_whole_seconds(hold_s, "hold_s")
    if hold_s <= 0 or not series:
        return series
    hold_start: int | None = None
    for time_s in sorted(series):
        sample = series[time_s]
        storage_section_id = ""
        if isinstance(sample, tuple) and len(sample) >= 5:
            storage_section_id = str(sample[4] or "")
        if storage_section_id.strip():
            hold_start = int(time_s)
            break
    if hold_start is None:
        return series
    delayed: Dict[int, PowerSample] = {}
    for time_s, sample in series.items():
        if int(time_s) >= hold_start:
            delayed[int(time_s) + hold_s] = sample
        else:
            delayed[int(time_s)] = sample
    return delayed

def apply_scenario(
    schedule: GeneratedSchedule,
    scenario: DisturbanceScenario,
    disturbance_from_time_s: int | None = None,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
) -> GeneratedSchedule:
    """Apply departure/headway perturbations without rewriting locked history.

    When a rolling-window origin or explicit locked departures are supplied,
    those committed decisions remain unchanged.  Headway stretching is indexed
    only over the still-disturbable future departures.
    """

    disturbance_from = (
        None
        if disturbance_from_time_s is None
        else _validated_whole_seconds(
            disturbance_from_time_s,
            "disturbance_from_time_s",
        )
    )

    locked_heavy = {
        _validated_whole_seconds(value, "locked_heavy_departures_s")
        for value in locked_heavy_departures_s
    }
    locked_empty = {
        _validated_whole_seconds(value, "locked_empty_departures_s")
        for value in locked_empty_departures_s
    }

    def disturbed_times(
        times: Iterable[int],
        delay_s: int,
        stretch_s: int,
        locked_times: set[int],
    ) -> List[int]:
        """函数 disturbed_times：执行该模块中的相关处理逻辑。"""
        result: List[int] = []
        future_idx = 0
        for raw_time_s in times:
            time_s = _validated_whole_seconds(raw_time_s, "departure time")
            if time_s in locked_times or (
                disturbance_from is not None and time_s < disturbance_from
            ):
                result.append(time_s)
                continue
            result.append(time_s + delay_s + future_idx * stretch_s)
            future_idx += 1
        return result

    heavy = disturbed_times(
        schedule.heavy_departures_s,
        scenario.heavy_delay_s,
        scenario.heavy_headway_stretch_s,
        locked_heavy,
    )
    empty = disturbed_times(
        schedule.empty_departures_s,
        scenario.empty_delay_s,
        scenario.empty_headway_stretch_s,
        locked_empty,
    )
    return GeneratedSchedule(
        heavy_departures_s=heavy,
        empty_departures_s=empty,
        template=schedule.template,
        heavy_train_ids=list(schedule.heavy_train_ids),
        empty_train_ids=list(schedule.empty_train_ids),
    )


def apply_train_delay_observations(
    schedule: GeneratedSchedule,
    train_delays_s: Iterable[Tuple[str, int]],
    *,
    current_time_s: int,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
) -> GeneratedSchedule:
    """按稳定序号将晚点施加到未来列车，并禁止改写历史或造成列车越序。"""

    normalized = dict(_normalize_observed_train_delays(train_delays_s))
    current_time_s = _validated_whole_seconds(current_time_s, "current_time_s")
    locked_by_prefix = {
        "H": {_validated_whole_seconds(value, "locked_heavy_departures_s") for value in locked_heavy_departures_s},
        "E": {_validated_whole_seconds(value, "locked_empty_departures_s") for value in locked_empty_departures_s},
    }

    def apply(prefix: str, departures: Iterable[int], train_ids: Iterable[str]) -> List[int]:
        pairs = list(zip(departures, train_ids))
        known_ids = {train_id for _time_s, train_id in pairs}
        unknown = sorted(train_id for train_id in normalized if train_id.startswith(prefix) and train_id not in known_ids)
        if unknown:
            raise ValueError(f"逐列车晚点引用了当前预测窗口不存在的列车：{unknown}")
        adjusted = []
        for time_s, train_id in pairs:
            delay_s = normalized.get(train_id, 0)
            if delay_s and (time_s in locked_by_prefix[prefix] or time_s < current_time_s):
                raise ValueError(f"逐列车晚点不能改写已执行或已锁定列车：{train_id}")
            adjusted.append(time_s + delay_s)
        if any(right <= left for left, right in zip(adjusted[:-1], adjusted[1:])):
            raise ValueError(f"逐列车晚点导致{prefix}方向列车越序，当前模型不允许自动重编号。")
        return adjusted

    heavy = apply("H", schedule.heavy_departures_s, schedule.heavy_train_ids)
    empty_ = apply("E", schedule.empty_departures_s, schedule.empty_train_ids)
    return GeneratedSchedule(
        heavy_departures_s=heavy,
        empty_departures_s=empty_,
        template=schedule.template,
        heavy_train_ids=list(schedule.heavy_train_ids),
        empty_train_ids=list(schedule.empty_train_ids),
    )

def build_power_series(
    cache: PowerSeriesCache,
    depart_times_s: Iterable[int],
    sample_step_s: int = 1,
    storage_hold_s: int = 0,
    operation_delay_events_by_departure: Mapping[int, Iterable[Tuple[float, int]]] | None = None,
) -> List[Dict[int, PowerSample]]:
    """Build shifted power series for all trains of one direction/type.

    Operation and storage holds are applied to the trajectory clock, not to
    whole samples.  A station crossing can fall between simulator samples;
    shifting only the first sample *after* the threshold leaves the tail of
    the preceding sample active during the hold and creates a false energy
    overlap.  ``_shift_component_for_events`` splits such samples at the
    nearest executable second before applying the delay.
    """

    def _shift_component_for_events(
        component: Dict[int, PowerSample],
        depart_time_s: int,
        events: Iterable[Tuple[float, int]],
    ) -> Dict[int, PowerSample]:
        """函数 _shift_component_for_events：执行该模块中的相关处理逻辑。"""
        normalized_events: Dict[int, int] = {}
        for raw_threshold_s, raw_delay_s in events:
            threshold_s = float(raw_threshold_s)
            if not math.isfinite(threshold_s) or threshold_s < 0.0:
                raise ValueError("operation/storage delay threshold must be finite and non-negative")
            delay_s = _validated_whole_seconds(raw_delay_s, "operation/storage delay")
            if delay_s <= 0:
                continue
        # 结算样本按整数秒索引。事件时间向上取整，避免在实际通过前施加停车，
        # 同时将误差控制在一秒以内，并保留停车期间的真实零功率间隔。
            threshold_key = int(math.ceil(threshold_s - 1e-9))
            normalized_events[threshold_key] = normalized_events.get(threshold_key, 0) + delay_s
        if not normalized_events or not component:
            return dict(component)

        event_points = sorted(normalized_events.items())
        output: Dict[int, PowerSample] = {}
        event_thresholds = [threshold_s for threshold_s, _delay_s in event_points]
        cumulative_delays: List[int] = []
        running_delay = 0
        for _threshold_s, delay_s in event_points:
            running_delay += delay_s
            cumulative_delays.append(running_delay)

        ordered_items = sorted(component.items(), key=lambda item: int(item[0]))
        for index, (raw_start_s, sample) in enumerate(ordered_items):
            start_s = int(raw_start_s)
            if isinstance(sample, (tuple, list)) and len(sample) >= 4:
                raw_duration_s = sample[3]
            elif index + 1 < len(ordered_items):
                raw_duration_s = int(ordered_items[index + 1][0]) - start_s
            else:
                raw_duration_s = 1
            duration_s = float(raw_duration_s)
            if not math.isfinite(duration_s) or duration_s < 0.0:
                raise ValueError("power sample duration must be finite and non-negative")
            if duration_s <= 1e-12:
                continue
            base_start_rel = float(start_s - depart_time_s)
            base_end_rel = base_start_rel + duration_s
            split_points = [base_start_rel]
            split_points.extend(
                float(threshold_s)
                for threshold_s, _delay_s in event_points
                if base_start_rel + 1e-9 < threshold_s < base_end_rel - 1e-9
            )
            split_points.append(base_end_rel)
            split_points = sorted(set(split_points))
            for left_rel, right_rel in zip(split_points[:-1], split_points[1:]):
                part_duration_s = right_rel - left_rel
                if part_duration_s <= 1e-12:
                    continue
                event_index = bisect_right(event_thresholds, left_rel + 1e-9) - 1
                cumulative_delay_s = cumulative_delays[event_index] if event_index >= 0 else 0
                shifted_start_s = int(round(depart_time_s + left_rel + cumulative_delay_s))
                if isinstance(sample, (tuple, list)) and len(sample) >= 4:
                    sample_parts = tuple(sample[:3]) + (part_duration_s,) + tuple(sample[4:])
                else:
                    sample_parts = tuple(sample) + (part_duration_s,)
                if shifted_start_s in output:
                    raise ValueError(
                        "operation/storage delay produced colliding power-sample timestamps"
                    )
                output[shifted_start_s] = cast(PowerSample, sample_parts)
        return output

    hold_s = _validated_whole_number(storage_hold_s, "storage_hold_s")
    if hold_s < 0:
        raise ValueError(f"storage_hold_s must be non-negative, got {storage_hold_s!r}")
    series: List[Dict[int, PowerSample]] = []
    for depart_time_s in depart_times_s:
        depart_time_s = _validated_whole_number(depart_time_s, "departure time")
        components = cache.shifted_components(
            depart_time_s,
            sample_step_s=sample_step_s,
        )
        operation_events = []
        if operation_delay_events_by_departure is not None:
            for threshold_s, delay_s in operation_delay_events_by_departure.get(depart_time_s, ()):
                threshold = float(threshold_s)
                if not math.isfinite(threshold) or threshold < 0.0:
                    raise ValueError("operation delay threshold must be finite and non-negative")
                delay = _validated_whole_seconds(delay_s, "operation delay")
                if delay > 0:
                    operation_events.append((threshold, delay))
        if operation_events:
            components = [
                _shift_component_for_events(component, depart_time_s, operation_events)
                for component in components
            ]
        if hold_s > 0:
            storage_entry_times = [
                int(time_s)
                for component in components
                for time_s, sample in component.items()
                if len(sample) >= 5 and str(sample[4]).strip()
            ]
            if storage_entry_times:
                hold_start = min(storage_entry_times)
                components = [
                    _shift_component_for_events(
                        component,
                        depart_time_s,
                        ((float(hold_start - depart_time_s), hold_s),),
                    )
                    for component in components
                ]
        series.extend(components)
    return series


def clip_power_series_to_window(
    power_series_list: Iterable[Dict[int, PowerSample]],
    *,
    from_time_s: int | None = None,
    until_time_s: int | None = None,
    default_duration_s: int = 1,
) -> List[Dict[int, PowerSample]]:
    """按绝对时间窗裁剪功率样本，并保留跨越边界样本的有效时长。"""

    lower = None if from_time_s is None else _validated_whole_seconds(
        from_time_s, "from_time_s"
    )
    upper = None if until_time_s is None else _validated_whole_seconds(
        until_time_s, "until_time_s"
    )
    duration_default = _validated_whole_seconds(
        default_duration_s, "default_duration_s", positive=True
    )
    if lower is not None and upper is not None and upper < lower:
        raise ValueError("until_time_s must not be earlier than from_time_s")
    clipped: List[Dict[int, PowerSample]] = []
    for series in power_series_list:
        output: Dict[int, PowerSample] = {}
        for raw_start_s, sample in series.items():
            start_s = _validated_whole_seconds(raw_start_s, "power sample time")
            raw_duration = sample[3] if len(sample) >= 4 else duration_default
            duration_s = float(raw_duration)
            if not math.isfinite(duration_s) or duration_s <= 0.0:
                raise ValueError("power sample duration must be finite and positive")
            end_s = start_s + duration_s
            clipped_start = max(float(start_s), float(lower)) if lower is not None else float(start_s)
            clipped_end = min(end_s, float(upper)) if upper is not None else end_s
            if clipped_end <= clipped_start:
                continue
            timestamp = int(round(clipped_start))
            parts = tuple(sample)
            if len(parts) >= 4:
                parts = parts[:3] + (clipped_end - clipped_start,) + parts[4:]
            else:
                parts = parts + (clipped_end - clipped_start,)
            output[timestamp] = cast(PowerSample, parts)
        if output:
            clipped.append(output)
    return clipped

def evaluate_schedule(
    schedule: GeneratedSchedule,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    settlement_system: EnergySettlementSystem,
    signaling_system: Dict,
    resource_model: ResourceModel | None = None,
    storage_sections: Iterable[StorageSectionInterval] | None = None,
    target_gap_s: int = 1000,
    min_depart_gap_s: int = 300,
    objective_mode: str = OBJECTIVE_MODE_BALANCED,
    energy_scenario: str = ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    objective_priority: str = OBJECTIVE_PRIORITY_ENERGY_FIRST,
    energy_from_time_s: int | None = None,
    energy_until_time_s: int | None = None,
) -> ScheduleScore:
    """Evaluate one expanded schedule against safety and energy objectives."""
    min_depart_gap_s = _validated_whole_seconds(min_depart_gap_s, "min_depart_gap_s")
    target_gap_s = _validated_whole_seconds(target_gap_s, "target_gap_s")
    storage_hold_s = _validated_whole_seconds(
        getattr(schedule.template, "flex_zone_hold_s", 0),
        "template.flex_zone_hold_s",
    )
    heavy_times = sorted(schedule.heavy_departures_s)
    empty_times = sorted(schedule.empty_departures_s)
    heavy_operation_events = None
    empty_operation_events = None
    if resource_model is not None:
        heavy_operation_events = {
            depart_time_s: post_departure_operation_delay_events(
                heavy_cache,
                depart_time_s,
                "Heavy",
                resource_model,
            )
            for depart_time_s in heavy_times
        }
        empty_operation_events = {
            depart_time_s: post_departure_operation_delay_events(
                empty_cache,
                depart_time_s,
                "Empty",
                resource_model,
            )
            for depart_time_s in empty_times
        }
    headway_violation_s = (
        headway_violation_seconds(heavy_times, min_gap_s=min_depart_gap_s)
        + headway_violation_seconds(empty_times, min_gap_s=min_depart_gap_s)
    )
    signal_violations = (
        signal_violation_count(
            heavy_times,
            heavy_cache,
            signaling_system,
            operation_delay_events_by_departure=heavy_operation_events,
        )
        + signal_violation_count(
            empty_times,
            empty_cache,
            signaling_system,
            storage_hold_s=storage_hold_s,
            operation_delay_events_by_departure=empty_operation_events,
        )
    )
    if resource_model is not None:
        network = build_time_space_network(
            schedule,
            resource_model,
            heavy_cache,
            empty_cache,
            storage_sections=storage_sections,
        )
    else:
        network = None
    resource_conflict_count = 0
    resource_overlap_violation_s = 0.0
    resource_constraint_violation = 0.0
    flow_continuity_feasible = True
    flow_continuity_violation_count = 0
    if resource_model is not None:
        resource_check = check_schedule_resources(schedule, resource_model, heavy_cache, empty_cache)
        resource_conflict_count = resource_check.conflict_count
        resource_overlap_violation_s = float(
            getattr(
                resource_check,
                "overlap_violation_s",
                sum(conflict.overlap_duration_s for conflict in resource_check.conflicts),
            )
        )
        resource_constraint_violation = normalized_resource_constraint_violation(
            resource_check,
            max(1.0, float(min_depart_gap_s)),
        )
        flow_continuity_feasible = resource_check.flow_continuity_feasible
        flow_continuity_violation_count = len(resource_check.flow_continuity_violations)
    network_violation = 0.0 if network is None or (network.node_count > 0 and network.arc_count > 0) else 1.0
    structural_constraint_violation = (
        headway_violation_s / max(1.0, float(min_depart_gap_s))
        + float(signal_violations)
        + resource_constraint_violation
        + float(flow_continuity_violation_count)
        + network_violation
    )
    power_series_list: List[Dict[int, PowerSample]] = []
    sample_step_s = settlement_system.settlement_time_step_s
    power_series_list.extend(
        build_power_series(
            heavy_cache,
            heavy_times,
            sample_step_s=sample_step_s,
            operation_delay_events_by_departure=heavy_operation_events,
        )
    )
    empty_series_list = build_power_series(
        empty_cache,
        empty_times,
        sample_step_s=sample_step_s,
        storage_hold_s=storage_hold_s,
        operation_delay_events_by_departure=empty_operation_events,
    )
    power_series_list.extend(empty_series_list)
    if energy_from_time_s is not None or energy_until_time_s is not None:
        power_series_list = clip_power_series_to_window(
            power_series_list,
            from_time_s=energy_from_time_s,
            until_time_s=energy_until_time_s,
            default_duration_s=sample_step_s,
        )
    result = settlement_system.settle(power_series_list)
    electrical_constraint_violation_kwh = (
        result.traction_supply_excess_kwh + result.regen_absorption_excess_kwh
    )
    constraint_violation = structural_constraint_violation + electrical_constraint_violation_kwh
    feasible = constraint_violation <= 1e-9
    deviation = schedule_deviation(heavy_times, target_gap_s) + schedule_deviation(empty_times, target_gap_s)
    capacity_margin_s = (
        sum(max(0, gap - min_depart_gap_s) for gap in (b - a for a, b in zip(heavy_times[:-1], heavy_times[1:])))
        + sum(max(0, gap - min_depart_gap_s) for gap in (b - a for a, b in zip(empty_times[:-1], empty_times[1:])))
    )
    if result.target_final_soc_kwh is None:
        delta_soc_kwh = result.final_soc_kwh - result.initial_soc_kwh
        final_soc_shortfall_kwh = max(
            0.0,
            -delta_soc_kwh - settlement_system.final_soc_tolerance_kwh,
        )
        final_soc_excess_kwh = max(
            0.0,
            delta_soc_kwh - settlement_system.final_soc_tolerance_kwh,
        )
        final_soc_deviation_kwh = final_soc_shortfall_kwh + final_soc_excess_kwh
    else:
        final_soc_shortfall_kwh = result.final_soc_shortfall_kwh
        final_soc_deviation_kwh = result.final_soc_shortfall_kwh + result.final_soc_excess_kwh
    return ScheduleScore(
        feasible=feasible,
        total_cost=result.total_cost,
        headway_deviation=deviation,
        worst_case_cost=result.total_cost,
        worst_case_headway_deviation=deviation,
        scenario_count=1,
        time_space_node_count=network.node_count if network is not None else 0,
        time_space_arc_count=network.arc_count if network is not None else 0,
        resource_conflict_count=resource_conflict_count,
        flow_continuity_feasible=flow_continuity_feasible,
        flow_continuity_violation_count=flow_continuity_violation_count,
        capacity_margin_s=capacity_margin_s,
        objective_mode=objective_mode,
                energy_scenario=energy_scenario,
        objective_priority=objective_priority,
        direct_used_kwh=result.direct_used_kwh,
        battery_charge_kwh=result.battery_charge_kwh,
        battery_discharge_kwh=result.battery_discharge_kwh,
        wasted_kwh=result.wasted_kwh,
        grid_kwh=result.grid_kwh,
        final_soc_kwh=result.final_soc_kwh,
        final_soc_deviation_kwh=final_soc_deviation_kwh,
        storage_efficiency=settlement_system.round_trip_efficiency,
        final_soc_shortfall_kwh=final_soc_shortfall_kwh,
        effective_regen_loss_kwh=getattr(
            result,
            "effective_regen_loss_kwh",
            storage_no_direct_effective_loss_kwh(
                result.wasted_kwh,
                result.battery_charge_kwh,
                result.battery_discharge_kwh,
                final_soc_deviation_kwh,
                settlement_system.round_trip_efficiency,
                final_soc_shortfall_kwh,
            ),
        ),
        constraint_violation=constraint_violation,
        headway_violation_s=headway_violation_s,
        signal_violation_count=signal_violations,
        resource_overlap_violation_s=resource_overlap_violation_s,
        traction_supply_excess_kwh=result.traction_supply_excess_kwh,
        regen_absorption_excess_kwh=result.regen_absorption_excess_kwh,
        electrical_constraint_violation_kwh=electrical_constraint_violation_kwh,
    )

def _scenario_is_core_robust(scenario: DisturbanceScenario) -> bool:
    """Return the explicit feasibility role without depending on scenario names."""

    return bool(scenario.core_for_feasibility)


def _effective_regen_loss(score: ScheduleScore) -> float:
    """读取评分构造后必定完成归一化的有效再生损失。"""

    value = score.effective_regen_loss_kwh
    if value is None:
        raise RuntimeError("评分中的有效再生损失未完成初始化")
    return value


def robust_evaluate_schedule(
    schedule: GeneratedSchedule,
    scenarios: List[DisturbanceScenario],
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    settlement_system: EnergySettlementSystem,
    signaling_system: Dict,
    resource_model: ResourceModel | None = None,
    storage_sections: Iterable[StorageSectionInterval] | None = None,
    min_depart_gap_s: int = 300,
    target_gap_s: int = 1000,
    objective_mode: str = OBJECTIVE_MODE_BALANCED,
    energy_scenario: str = ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    objective_priority: str = OBJECTIVE_PRIORITY_ENERGY_FIRST,
    disturbance_from_time_s: int | None = None,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
    scenario_score_sink: List[ScenarioScore] | None = None,
    energy_from_time_s: int | None = None,
    energy_until_time_s: int | None = None,
) -> ScheduleScore:
    """Evaluate a schedule over disturbance scenarios and keep worst-case terms."""
    if not scenarios:
        raise ValueError("robust_evaluate_schedule requires at least one disturbance scenario")
    scenario_scores: List[ScheduleScore] = []
    core_flags: List[bool] = []
    for scenario in scenarios:
        disturbed = apply_scenario(
            schedule,
            scenario,
            disturbance_from_time_s=disturbance_from_time_s,
            locked_heavy_departures_s=locked_heavy_departures_s,
            locked_empty_departures_s=locked_empty_departures_s,
        )
        score = evaluate_schedule(
            disturbed,
            heavy_cache,
            empty_cache,
            settlement_system,
            signaling_system,
            resource_model=resource_model,
            storage_sections=storage_sections,
            min_depart_gap_s=min_depart_gap_s,
            target_gap_s=target_gap_s,
            objective_mode=objective_mode,
            energy_scenario=energy_scenario,
            objective_priority=objective_priority,
            energy_from_time_s=energy_from_time_s,
            energy_until_time_s=energy_until_time_s,
        )
        adjusted_score = replace(
            score,
            total_cost=score.total_cost * scenario.cost_multiplier,
            worst_case_cost=score.total_cost * scenario.cost_multiplier,
        )
        scenario_scores.append(adjusted_score)
        if scenario_score_sink is not None:
            # 诊断输出沿用未乘场景成本系数的单场景结果，与既有 explain 接口一致。
            scenario_score_sink.append((scenario, score))
        core_flags.append(_scenario_is_core_robust(scenario))
    core_scores = [
        score
        for score, is_core in zip(scenario_scores, core_flags)
        if is_core
    ]
    if not core_scores:
        # 调用方只提供诊断信息时，避免把缺少实际约束检查的结果误判为可行。
        core_scores = scenario_scores
    feasible = all(score.feasible for score in core_scores)
    average_cost = sum(score.total_cost for score in scenario_scores) / len(scenario_scores)
    average_deviation = sum(score.headway_deviation for score in scenario_scores) / len(scenario_scores)
    worst_cost = max(score.total_cost for score in scenario_scores)
    worst_deviation = max(score.headway_deviation for score in scenario_scores)
    return ScheduleScore(
        feasible=feasible,
        total_cost=average_cost,
        headway_deviation=average_deviation,
        worst_case_cost=worst_cost,
        worst_case_headway_deviation=worst_deviation,
        scenario_count=len(scenario_scores),
        time_space_node_count=max((score.time_space_node_count for score in scenario_scores), default=0),
        time_space_arc_count=max((score.time_space_arc_count for score in scenario_scores), default=0),
        resource_conflict_count=max((score.resource_conflict_count for score in core_scores), default=0),
        flow_continuity_feasible=all(score.flow_continuity_feasible for score in core_scores),
        flow_continuity_violation_count=max((score.flow_continuity_violation_count for score in core_scores), default=0),
        capacity_margin_s=sum(score.capacity_margin_s for score in scenario_scores) / len(scenario_scores),
        objective_mode=objective_mode,
        objective_priority=objective_priority,
        energy_scenario=energy_scenario,
        direct_used_kwh=sum(score.direct_used_kwh for score in scenario_scores) / len(scenario_scores),
        battery_charge_kwh=sum(score.battery_charge_kwh for score in scenario_scores) / len(scenario_scores),
        battery_discharge_kwh=sum(score.battery_discharge_kwh for score in scenario_scores) / len(scenario_scores),
        wasted_kwh=sum(score.wasted_kwh for score in scenario_scores) / len(scenario_scores),
        grid_kwh=sum(score.grid_kwh for score in scenario_scores) / len(scenario_scores),
        final_soc_kwh=sum(score.final_soc_kwh for score in scenario_scores) / len(scenario_scores),
        final_soc_deviation_kwh=sum(score.final_soc_deviation_kwh for score in scenario_scores) / len(scenario_scores),
        storage_efficiency=sum(score.storage_efficiency for score in scenario_scores) / len(scenario_scores),
        final_soc_shortfall_kwh=sum(score.final_soc_shortfall_kwh for score in scenario_scores) / len(scenario_scores),
        # 平均已经按场景评价得到的损失。若由平均后的充放电流重新计算，不同场景可能相互抵消，
        # 从而低估被拒绝的再生能量。
        effective_regen_loss_kwh=sum(
            _effective_regen_loss(score) for score in scenario_scores
        ) / len(scenario_scores),
        constraint_violation=max((score.constraint_violation for score in core_scores), default=0.0),
        headway_violation_s=max((score.headway_violation_s for score in core_scores), default=0.0),
        signal_violation_count=max((score.signal_violation_count for score in core_scores), default=0),
        resource_overlap_violation_s=max((score.resource_overlap_violation_s for score in core_scores), default=0.0),
        traction_supply_excess_kwh=max(
            (score.traction_supply_excess_kwh for score in core_scores),
            default=0.0,
        ),
        regen_absorption_excess_kwh=max(
            (score.regen_absorption_excess_kwh for score in core_scores),
            default=0.0,
        ),
        electrical_constraint_violation_kwh=max(
            (score.electrical_constraint_violation_kwh for score in core_scores),
            default=0.0,
        ),
    )

def capacity_pressure_objective(score: ScheduleScore) -> float:
    """Scenario-specific capacity term minimized by the optimizer."""
    if score.objective_mode == OBJECTIVE_MODE_CAPACITY_SURPLUS:
        return -score.capacity_margin_s
    if score.objective_mode == OBJECTIVE_MODE_CAPACITY_TIGHT:
        return score.capacity_margin_s
    return score.worst_case_headway_deviation

def energy_scenario_objective(score: ScheduleScore) -> float:
    """Energy-scenario-specific term minimized by the optimizer."""
    if score.energy_scenario == ENERGY_SCENARIO_DIRECT_NO_STORAGE:
        return score.wasted_kwh + score.grid_kwh - 0.35 * score.direct_used_kwh
    if score.energy_scenario in {
        ENERGY_SCENARIO_STORAGE_NO_DIRECT,
        ENERGY_SCENARIO_DIRECT_WITH_STORAGE,
    }:
        # 将被拒绝能量和终端 SOC 不平衡各计一次。SOC 超额按储能效率换算为输入侧能量；
        # SOC 不足抵销释放初始库存带来的电网收益。direct_with_storage 是旧版运行时别名。
        return score.grid_kwh + _effective_regen_loss(score)
    return score.wasted_kwh + score.grid_kwh

def score_rank_value(score: ScheduleScore) -> float:
    """Scalar ranking used by the heuristic optimizer.    `objective_priority` aligns the scalar rank with business goals:    - energy_first: minimize wasted/grid first (default for storage_no_direct)    - cost_first: minimize settlement total_cost first    - balanced: blend energy and cost terms    """
    if not score.feasible:
        # 在比较成本前，优先选择冲突更少、约束违反量更低的候选。
        return (
            1e12
            + 1e9 * score.constraint_violation
            + 1e6 * score.resource_conflict_count
            + 1e3 * score.resource_overlap_violation_s
            + score.total_cost
        )
    pressure = capacity_pressure_objective(score)
    energy_term = energy_scenario_objective(score)
    priority = str(getattr(score, "objective_priority", "") or OBJECTIVE_PRIORITY_ENERGY_FIRST)
    if priority == OBJECTIVE_PRIORITY_COST_FIRST:
        return (
            1.0 * score.total_cost
            + 0.35 * score.worst_case_cost
            + 0.10 * energy_term
            + 0.05 * score.headway_deviation
            + 0.02 * pressure
            - 0.01 * score.capacity_margin_s
        )
    if priority == OBJECTIVE_PRIORITY_BALANCED:
        return (
            0.55 * energy_term
            + 0.35 * score.total_cost
            + 0.10 * score.worst_case_cost
            + 0.05 * score.headway_deviation
            + 0.02 * pressure
            - 0.005 * score.capacity_margin_s
        )
    # energy_first（默认）：在 storage_no_direct 场景下，将成本和追踪间隔作为次级
    # 判据，避免储能折旧掩盖弃电量和电网购电量更低的方案。
    if score.energy_scenario == ENERGY_SCENARIO_STORAGE_NO_DIRECT:
        return (
            1.0 * energy_term
            + 0.05 * score.total_cost
            + 0.02 * score.worst_case_cost
            + 0.01 * score.headway_deviation
            + 0.01 * pressure
            - 0.001 * score.capacity_margin_s
        )
    return (
        score.total_cost
        + 0.45 * score.worst_case_cost
        + 0.15 * score.headway_deviation
        + 0.05 * pressure
        + 0.15 * energy_term
        - 0.01 * score.capacity_margin_s
    )

def candidate_selection_key(score: ScheduleScore) -> Tuple[float, float, float, float, float, float]:
    """Joint selection key: robust feasibility first, then business priority.    Core robust feasibility is already encoded in `score.feasible`. Among    robust-feasible candidates, order by `objective_priority`:    - energy_first: wasted/grid before total cost    - cost_first: total cost before wasted/grid    - balanced: rank value first, then energy, then cost    """
    feasible_rank = 0.0 if score.feasible else 1.0
        # 保留约束违反量的完整精度。不可行候选必须先按距离可行域的远近排序，
        # 再比较业务目标。
    violation = score.constraint_violation
    energy = round(energy_scenario_objective(score), 3)
    final_soc_deviation = round(score.final_soc_deviation_kwh, 3)
    wasted = round(score.wasted_kwh, 3)
    grid = round(score.grid_kwh, 3)
    cost = round(score.total_cost, 3)
    rank = score_rank_value(score)
    priority = str(getattr(score, "objective_priority", "") or OBJECTIVE_PRIORITY_ENERGY_FIRST)
    if priority == OBJECTIVE_PRIORITY_COST_FIRST:
        return (feasible_rank, violation, cost, wasted, grid, rank)
    if priority == OBJECTIVE_PRIORITY_BALANCED:
        return (feasible_rank, violation, rank, wasted, grid, cost)
    return (feasible_rank, violation, energy, final_soc_deviation, grid, cost)

def objective_tuple(score: ScheduleScore) -> Tuple[float, float, float]:
    """Independent physical objectives minimized by the template NSGA-II."""
    if score.energy_scenario in {
        ENERGY_SCENARIO_STORAGE_NO_DIRECT,
        ENERGY_SCENARIO_DIRECT_WITH_STORAGE,
    }:
        effective_regen_loss = _effective_regen_loss(score)
        return effective_regen_loss, score.grid_kwh, capacity_pressure_objective(score)
    return score.wasted_kwh, score.grid_kwh, capacity_pressure_objective(score)

def effective_objective_tuple(score: ScheduleScore) -> Tuple[int, int, int]:
    """Quantize physical objectives so numerical noise does not create Pareto options."""
    objectives = objective_tuple(score)
    return (
        int(round(objectives[0] / OBJECTIVE_TOLERANCES[0])),
        int(round(objectives[1] / OBJECTIVE_TOLERANCES[1])),
        int(round(objectives[2] / OBJECTIVE_TOLERANCES[2])),
    )

def dominates(left: ScheduleScore, right: ScheduleScore) -> bool:
    """Deb constraint-domination followed by Pareto objective domination."""
    if left.feasible != right.feasible:
        return left.feasible
    if not left.feasible:
        return left.constraint_violation < right.constraint_violation
    left_objectives = effective_objective_tuple(left)
    right_objectives = effective_objective_tuple(right)
    no_worse = all(a <= b for a, b in zip(left_objectives, right_objectives))
    strictly_better = any(a < b for a, b in zip(left_objectives, right_objectives))
    return no_worse and strictly_better

def non_dominated_sort(
    evaluated_templates: List[Tuple[ScheduleTemplate, ScheduleScore]],) -> List[List[Tuple[ScheduleTemplate, ScheduleScore]]]:
    """Fast non-dominated sorting for a small candidate population."""
    domination_counts = [0 for _item in evaluated_templates]
    dominated_sets: List[List[int]] = [[] for _item in evaluated_templates]
    fronts: List[List[int]] = [[]]
    for idx, (_template, score) in enumerate(evaluated_templates):
        for other_idx, (_other_template, other_score) in enumerate(evaluated_templates):
            if idx == other_idx:
                continue
            if dominates(score, other_score):
                dominated_sets[idx].append(other_idx)
            elif dominates(other_score, score):
                domination_counts[idx] += 1
        if domination_counts[idx] == 0:
            fronts[0].append(idx)
    current_front = 0
    while current_front < len(fronts) and fronts[current_front]:
        next_front: List[int] = []
        for idx in fronts[current_front]:
            for dominated_idx in dominated_sets[idx]:
                domination_counts[dominated_idx] -= 1
                if domination_counts[dominated_idx] == 0:
                    next_front.append(dominated_idx)
        current_front += 1
        if next_front:
            fronts.append(next_front)
    return [[evaluated_templates[idx] for idx in front] for front in fronts if front]

def crowding_distances(
    front: List[Tuple[ScheduleTemplate, ScheduleScore]],) -> Dict[TemplateKey, float]:
    """Calculate NSGA-II crowding distance for one front."""
    distances: Dict[TemplateKey, float] = {
        template_key(template): 0.0 for template, _score in front
    }
    if len(front) <= 2:
        for template, _score in front:
            distances[template_key(template)] = float("inf")
        return distances
    objective_count = 3
    for obj_idx in range(objective_count):
        sorted_front = sorted(front, key=lambda item: effective_objective_tuple(item[1])[obj_idx])
        first_key = template_key(sorted_front[0][0])
        last_key = template_key(sorted_front[-1][0])
        distances[first_key] = float("inf")
        distances[last_key] = float("inf")
        min_value = effective_objective_tuple(sorted_front[0][1])[obj_idx]
        max_value = effective_objective_tuple(sorted_front[-1][1])[obj_idx]
        if max_value == min_value:
            continue
        for idx in range(1, len(sorted_front) - 1):
            prev_value = effective_objective_tuple(sorted_front[idx - 1][1])[obj_idx]
            next_value = effective_objective_tuple(sorted_front[idx + 1][1])[obj_idx]
            key = template_key(sorted_front[idx][0])
            if distances[key] != float("inf"):
                distances[key] += (next_value - prev_value) / (max_value - min_value)
    return distances

def template_key(template: ScheduleTemplate) -> TemplateKey:
    """Complete schedule-template key used for caching and deduplication."""
    return (
        template.heavy_headway_s,
        template.empty_headway_s,
        template.heavy_empty_phase_s,
        template.heavy_count,
        template.empty_count,
        template.start_time_s,
        template.flex_zone_hold_s,
        template.storage_align_shift_s,
        str(getattr(template, "storage_preset_id", "") or ""),
        tuple(getattr(template, "heavy_departure_adjustments_s", ()) or ()),
        tuple(getattr(template, "empty_departure_adjustments_s", ()) or ()),
    )

def describe_template(template: ScheduleTemplate) -> str:
    """Return a compact human-readable strategy description."""
    preset = str(getattr(template, "storage_preset_id", "") or "") or "baseline_storage"
    return (
        f"heavy_headway={template.heavy_headway_s}s, "
        f"empty_headway={template.empty_headway_s}s, "
        f"phase={template.heavy_empty_phase_s}s, "
        f"hold={template.flex_zone_hold_s}s, "
        f"storage_shift={template.storage_align_shift_s}s, "
        f"storage_preset={preset}, "
        f"heavy_adjustments={tuple(template.heavy_departure_adjustments_s)}, "
        f"empty_adjustments={tuple(template.empty_departure_adjustments_s)}"
    )

def candidate_templates(
    base_template: ScheduleTemplate,
    headway_offsets_s: Iterable[int] = (-300, -120, 0, 120, 300),
    phase_offsets_s: Iterable[int] = (-600, -300, -180, 0, 180, 300, 600),
    hold_options_s: Iterable[int] = (0, 120, 300),
    storage_shift_options_s: Iterable[int] = (0, 120, -120, 300, -300, 600, -600),) -> List[ScheduleTemplate]:
    """Generate a compact candidate set around an expert/template plan."""
    candidates: List[ScheduleTemplate] = []
    seen: set[Tuple[int, int, int, int, int, str]] = set()
    for heavy_delta in headway_offsets_s:
        for empty_delta in headway_offsets_s:
            for phase_delta in phase_offsets_s:
                for hold_s in hold_options_s:
                    for storage_shift in storage_shift_options_s:
                        heavy_headway = max(300, base_template.heavy_headway_s + heavy_delta)
                        empty_headway = max(300, base_template.empty_headway_s + empty_delta)
                        phase = max(0, base_template.heavy_empty_phase_s + phase_delta)
                        # 相对储能偏移不能把第一列空车发车时间移到非负规划时域之前。
                        safe_storage_shift = max(
                            -(base_template.start_time_s + phase),
                            int(storage_shift),
                        )
                        preset_id = str(getattr(base_template, "storage_preset_id", "") or "")
                        key = (heavy_headway, empty_headway, phase, int(hold_s), safe_storage_shift, preset_id)
                        if key in seen:
                            continue
                        seen.add(key)
                        candidates.append(
                            replace(
                                base_template,
                                heavy_headway_s=heavy_headway,
                                empty_headway_s=empty_headway,
                                heavy_empty_phase_s=phase,
                                flex_zone_hold_s=int(hold_s),
                                storage_align_shift_s=safe_storage_shift,
                                storage_preset_id=preset_id,
                            )
                        )
    return candidates

def landable_storage_force_templates(
    base_template: ScheduleTemplate,
    config: TemplateSearchConfig,
    max_seeds_per_preset: int = 6,) -> List[ScheduleTemplate]:
    """Force-evaluate landable storage presets on known light-robust schedule shapes.    Population truncation can drop high-capacity / hybrid presets. Explicitly    re-evaluate a compact preset x robust-seed grid so joint selection can see    every landable storage gene under robust schedule pockets.    """
    if not (config.enable_storage_preset_search and config.storage_preset_ids):
        return []
    forced: List[ScheduleTemplate] = []
    for preset_id in config.storage_preset_ids:
        preset = str(preset_id)
        forced.append(clamp_template(replace(base_template, storage_preset_id=preset), config))
        for seed in known_light_robust_seed_templates(replace(base_template, storage_preset_id=preset))[:max_seeds_per_preset]:
            forced.append(clamp_template(seed, config))
        # 同时保留少量缓冲形状，增加相位和储能偏移的多样性。
        for seed in robust_buffer_seed_templates(replace(base_template, storage_preset_id=preset))[:3]:
            forced.append(clamp_template(seed, config))
    return unique_templates(forced)

def known_light_robust_seed_templates(base_template: ScheduleTemplate) -> List[ScheduleTemplate]:
    """High-priority seeds that previously survived +120s light delays on the current case.    Source: resource-only sweep under the synthetic H/E template family. These are    planning seeds for robustness search while an official timetable is unavailable.    """
    preset_id = str(getattr(base_template, "storage_preset_id", "") or "")
    # (heavy, empty, phase, storage_shift, hold)
    # 只保留经过完整资源约束和核心稳健评价重新验证的种子（正常、重车加 120 秒、空车加 120 秒）。
    # 严格加 300 秒情形仅用于诊断。
    known = [
        (3300, 3300, 1800, 900, 0),
    ]
    seeds: List[ScheduleTemplate] = []
    for heavy, empty, phase, shift, hold in known:
        seeds.append(
            replace(
                base_template,
                heavy_headway_s=int(heavy),
                empty_headway_s=int(empty),
                heavy_empty_phase_s=int(phase),
                flex_zone_hold_s=int(hold),
                storage_align_shift_s=int(shift),
                storage_preset_id=preset_id,
            )
        )
    return seeds

def robust_buffer_seed_templates(base_template: ScheduleTemplate) -> List[ScheduleTemplate]:
    """Seed templates biased toward throat-conflict buffers and storage alignment.    These are not claimed optimal; they expand the search away from the narrow    local neighborhood that previously produced only nominal-feasible plans.    Empirical resource-only sweeps on the current Shuohuang case found light-robust    (+120s) pockets near equal headways around 2700s with phase/storage-shift    buffers; those neighborhoods are therefore seeded explicitly.    """
    seeds: List[ScheduleTemplate] = list(known_light_robust_seed_templates(base_template))
    headway_pairs = [
        (base_template.heavy_headway_s, base_template.empty_headway_s),
        (max(2400, base_template.heavy_headway_s - 300), max(2400, base_template.empty_headway_s + 300)),
        (max(2400, base_template.heavy_headway_s + 300), max(2400, base_template.empty_headway_s + 300)),
        (2700, 2700),
        (2700, 2550),
        (2850, 2700),
        (3000, 2700),
        (3000, 3000),
        (3300, 3000),
        (3600, 3000),
        (3600, 3300),
    ]
    phases = sorted(
        {
            max(0, phase)
            for phase in (
                list(base_template.heavy_empty_phase_s + delta for delta in (-900, -600, -300, -150, 0, 150, 300, 450, 600, 900))
                + [1800, 1900, 2000, 2100, 2200, 2300, 2400, 2500, 2600, 2700, 2800, 2900, 3000, 3100]
            )
        }
    )
    holds = (0, 120, 240, 360)
    storage_shifts = (0, -300, 300, -600, 600, -900, 900)
    seen: set[Tuple[int, int, int, int, int, str]] = set()
    for heavy_headway, empty_headway in headway_pairs:
        for phase in phases:
            for hold_s in holds:
                for storage_shift in storage_shifts:
                    preset_id = str(getattr(base_template, "storage_preset_id", "") or "")
                    key = (int(heavy_headway), int(empty_headway), int(phase), int(hold_s), int(storage_shift), preset_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    seeds.append(
                        replace(
                            base_template,
                            heavy_headway_s=int(heavy_headway),
                            empty_headway_s=int(empty_headway),
                            heavy_empty_phase_s=int(phase),
                            flex_zone_hold_s=int(hold_s),
                            storage_align_shift_s=int(storage_shift),
                            storage_preset_id=preset_id,
                        )
                    )
    return seeds


def resource_feasibility_repair_templates(
    base_template: ScheduleTemplate,
    config: TemplateSearchConfig,
    scenarios: Iterable[DisturbanceScenario],
    resource_model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    schedule_factory: Callable[[ScheduleTemplate], GeneratedSchedule],
    *,
    required_heavy_count: int,
    required_empty_count: int,
    disturbance_from_time_s: int | None = None,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
    offset_step_s: int = 60,
    max_seeds: int = 1,
    exact_horizon_s: int | None = None,
    exact_time_limit_s: float = 300.0,
    work_budget=None,
) -> Tuple[List[ScheduleTemplate], Dict]:
    """先细扫全局相位，再按实际冲突列车对执行局部错峰修复。"""

    if offset_step_s <= 0 or max_seeds <= 0:
        raise ValueError("offset_step_s and max_seeds must be positive")
    locked_heavy_departures_s = tuple(int(value) for value in locked_heavy_departures_s)
    locked_empty_departures_s = tuple(int(value) for value in locked_empty_departures_s)
    effective_offset_step_s = (
        min(offset_step_s, 30)
        if max(required_heavy_count, required_empty_count) >= 6
        else offset_step_s
    )
    core_scenarios = [scenario for scenario in scenarios if _scenario_is_core_robust(scenario)]
    if not core_scenarios:
        return [], {
            "triggered": True,
            "evaluated_template_count": 0,
            "resource_feasible_seed_count": 0,
            "note": "No core disturbance scenarios were available for feasibility repair.",
        }

    known_pairs = [
        (seed.heavy_headway_s, seed.empty_headway_s)
        for seed in known_light_robust_seed_templates(base_template)
    ]
    equal_headway_pairs = [
        (headway_s, headway_s)
        for headway_s in range(
            config.min_headway_s,
            config.max_headway_s + 1,
            max(1, min(300, config.max_headway_s - config.min_headway_s or 300)),
        )
    ]
    headway_pairs = list(dict.fromkeys([
        *known_pairs,
        *equal_headway_pairs,
        (base_template.heavy_headway_s, base_template.empty_headway_s),
        (base_template.heavy_headway_s, base_template.heavy_headway_s),
        (base_template.empty_headway_s, base_template.empty_headway_s),
    ]))
    center_offset_s = max(
        0,
        int(base_template.heavy_empty_phase_s + base_template.storage_align_shift_s),
    )
    if max(required_heavy_count, required_empty_count) >= 6:
        # 12列车及以上若对每个全局相位执行三场景全线路检查，修复成本会超过主搜索。
        # 先用围绕当前相位的稀疏锚点定位低冲突区域，再交给局部错峰束搜索。
        candidate_offsets = sorted({
            max(0, min(config.max_phase_s, center_offset_s + delta_s))
            for delta_s in (-1200, -900, -750, -600, -300, 0, 300, 600, 750, 900, 1200)
        } | {0, config.max_phase_s})
        global_scan_strategy = "sparse_phase_anchors_then_conflict_driven_local_repair"
    else:
        candidate_offsets = list(range(0, config.max_phase_s + 1, effective_offset_step_s))
        global_scan_strategy = "exhaustive_phase_grid"
    candidate_offsets.sort(key=lambda value: (abs(value - center_offset_s), value))
    preset_id = str(getattr(base_template, "storage_preset_id", "") or "")
    seeds: List[ScheduleTemplate] = []
    evaluated_count = 0
    rejected_population_count = 0
    blocking_scenario_counts: Dict[str, int] = {
        scenario.name: 0 for scenario in core_scenarios
    }
    near_candidates: List[Tuple[Tuple[int, int, float], ScheduleTemplate]] = []

    for heavy_headway_s, empty_headway_s in headway_pairs:
        for offset_s in candidate_offsets:
            template = clamp_template(
                replace(
                    base_template,
                    heavy_headway_s=heavy_headway_s,
                    empty_headway_s=empty_headway_s,
                    heavy_empty_phase_s=offset_s,
                    storage_align_shift_s=0,
                    storage_preset_id=preset_id,
                ),
                config,
            )
            candidate = schedule_factory(template)
            if (
                len(candidate.heavy_departures_s) != required_heavy_count
                or len(candidate.empty_departures_s) != required_empty_count
            ):
                rejected_population_count += 1
                continue
            evaluated_count += 1
            blocking_count = 0
            total_conflict_count = 0
            total_overlap_s = 0.0
            for scenario in core_scenarios:
                if work_budget is not None:
                    work_budget.resource()
                disturbed = apply_scenario(
                    candidate,
                    scenario,
                    disturbance_from_time_s=disturbance_from_time_s,
                    locked_heavy_departures_s=locked_heavy_departures_s,
                    locked_empty_departures_s=locked_empty_departures_s,
                )
                result = check_schedule_resources(
                    disturbed,
                    resource_model,
                    heavy_cache,
                    empty_cache,
                )
                if not result.feasible:
                    blocking_count += 1
                    blocking_scenario_counts[scenario.name] += 1
                total_conflict_count += int(getattr(result, "conflict_count", 0))
                total_overlap_s += float(getattr(result, "overlap_violation_s", 0.0))
            near_candidates.append((
                (blocking_count, total_conflict_count, total_overlap_s),
                template,
            ))
            if blocking_count == 0:
                seeds.append(template)
                if len(seeds) >= max_seeds:
                    break
        if len(seeds) >= max_seeds:
            break

    targeted_diagnostics: Dict[str, Any] = {
        "triggered": False,
        "evaluated_template_count": 0,
        "resource_feasible_seed_count": 0,
        "repair_level": (
            "level_2_16_plus"
            if int(required_heavy_count) + int(required_empty_count) >= 16
            else "level_1_under_16"
        ),
        "total_train_count": int(required_heavy_count) + int(required_empty_count),
    }
    if not seeds and near_candidates:
        near_candidates.sort(key=lambda item: (item[0], template_key(item[1])))
        total_train_count = int(required_heavy_count) + int(required_empty_count)
        if total_train_count >= 16:
            # 16列车及以上的窄可行路径需要更细步长和更深累计搜索；
            # 单列车调整上限与束宽保持第一级修复不变，避免无依据扩大邻域。
            targeted_repair_parameters = {
                "adjustment_step_s": 30,
                "max_absolute_adjustment_s": 600,
                "max_iterations": 16,
                "beam_width": 6,
            }
            repair_level = "level_2_16_plus"
        else:
            targeted_repair_parameters = {
                "adjustment_step_s": 60,
                "max_absolute_adjustment_s": 600,
                "max_iterations": 8,
                "beam_width": 6,
            }
            repair_level = "level_1_under_16"
        targeted_seeds, targeted_diagnostics = targeted_resource_feasibility_repair_templates(
            [template for _score, template in near_candidates[:4]],
            core_scenarios,
            resource_model,
            heavy_cache,
            empty_cache,
            schedule_factory,
            required_heavy_count=required_heavy_count,
            required_empty_count=required_empty_count,
            disturbance_from_time_s=disturbance_from_time_s,
            locked_heavy_departures_s=locked_heavy_departures_s,
            locked_empty_departures_s=locked_empty_departures_s,
            **targeted_repair_parameters,
            max_seeds=max_seeds,
            work_budget=work_budget,
        )
        targeted_diagnostics["repair_level"] = repair_level
        targeted_diagnostics["total_train_count"] = total_train_count
        seeds.extend(targeted_seeds)

    heuristic_seed_count_before_exact = len(seeds)
    exact_diagnostics: Dict[str, Any] = {
        "triggered": False,
        "status": "not_required",
        "proof": "none",
    }
    total_train_count = int(required_heavy_count) + int(required_empty_count)
    exact_full_window_supported = (
        not locked_heavy_departures_s
        and not locked_empty_departures_s
        and disturbance_from_time_s in {None, 0}
    )
    if (
        total_train_count >= 16
        and exact_horizon_s is not None
        and near_candidates
        and exact_full_window_supported
    ):
        # 精确层在启发式之后运行：有种子时固定该方案验证；无种子时在完整发车时域求解。
        # 局部导入避免exact_resource_feasibility反向复用调度数据结构时产生模块循环。
        from exact_resource_feasibility import (
            solve_exact_resource_feasibility,
            solve_quality_optimized_resource_feasibility,
        )

        # 验证已有启发式种子时固定该种子；启发式无解时以窗口原运行图为质量参照。
        # 不能使用“最接近的启发式模板”作为偏移基准，否则相位变化会被隐藏在模板字段中。
        exact_base = seeds[0] if seeds else base_template
        exact_common_arguments = {
            "horizon_s": int(exact_horizon_s),
            "time_limit_s": float(exact_time_limit_s),
            "disturbance_from_time_s": disturbance_from_time_s,
            "locked_heavy_departures_s": locked_heavy_departures_s,
            "locked_empty_departures_s": locked_empty_departures_s,
            "work_budget": work_budget,
        }
        if seeds:
            exact_result = solve_exact_resource_feasibility(
                exact_base,
                core_scenarios,
                resource_model,
                heavy_cache,
                empty_cache,
                max_adjustment_s=0,
                **exact_common_arguments,
            )
        else:
            exact_result = solve_quality_optimized_resource_feasibility(
                exact_base,
                core_scenarios,
                resource_model,
                heavy_cache,
                empty_cache,
                initial_adjustment_bound_s=int(
                    targeted_diagnostics.get("max_absolute_adjustment_s", 600)
                ),
                **exact_common_arguments,
            )
        exact_diagnostics = {
            "triggered": True,
            "status": exact_result.status,
            "proof": exact_result.proof,
            "model": dict(exact_result.diagnostics),
        }
        if exact_result.schedule_template is not None:
            exact_diagnostics["schedule_template"] = describe_template(
                exact_result.schedule_template
            )
            exact_diagnostics["heavy_departure_adjustments_s"] = list(
                exact_result.schedule_template.heavy_departure_adjustments_s
            )
            exact_diagnostics["empty_departure_adjustments_s"] = list(
                exact_result.schedule_template.empty_departure_adjustments_s
            )
        if not seeds and exact_result.feasible and exact_result.schedule_template is not None:
            seeds.append(exact_result.schedule_template)
    elif total_train_count >= 16 and exact_horizon_s is not None and near_candidates:
        exact_diagnostics = {
            "triggered": False,
            "status": "not_supported_for_locked_rolling_history",
            "proof": "none",
            "note": (
                "精确层未对缺少历史列车的滚动窗口建模；本窗口继续使用完整资源检查器，"
                "不输出模型不可行证明。"
            ),
        }

    feasibility_conclusion = classify_resource_feasibility_conclusion(
        exact_status=str(exact_diagnostics["status"]),
        heuristic_seed_count=heuristic_seed_count_before_exact,
        final_seed_count=len(seeds),
    )

    return unique_templates(seeds), {
        "triggered": True,
        "offset_step_s": effective_offset_step_s,
        "global_scan_strategy": global_scan_strategy,
        "global_offset_candidate_count": len(candidate_offsets),
        "evaluated_template_count": evaluated_count,
        "rejected_service_population_count": rejected_population_count,
        "resource_feasible_seed_count": len(seeds),
        "blocking_scenario_counts": blocking_scenario_counts,
        "seed_templates": [describe_template(seed) for seed in seeds],
        "best_global_templates": [
            {
                "score": score,
                "template": describe_template(template),
            }
            for score, template in sorted(
                near_candidates,
                key=lambda item: (item[0], template_key(item[1])),
            )[:4]
        ],
        "targeted_local_repair": targeted_diagnostics,
        "targeted_repair_level": targeted_diagnostics.get("repair_level"),
        "exact_resource_feasibility": exact_diagnostics,
        "feasibility_conclusion": feasibility_conclusion,
        "note": (
            "Resource-feasible seeds still require full robust energy, electrical, signaling, "
            "and service-population evaluation."
        ),
    }


def classify_resource_feasibility_conclusion(
    *,
    exact_status: str,
    heuristic_seed_count: int,
    final_seed_count: int,
) -> str:
    """把启发式与精确层结果归并为互斥、可解释的可行性结论。"""

    if exact_status == "model_infeasible" and int(heuristic_seed_count) > 0:
        return "heuristic_exact_model_inconsistency"
    if exact_status == "model_infeasible":
        return "model_proven_infeasible_in_explicit_domain"
    if exact_status == "feasible_verified" and int(heuristic_seed_count) == 0:
        return "heuristic_search_missed_feasible_solution"
    if exact_status == "feasible_verified":
        return "heuristic_solution_exactly_verified"
    if int(final_seed_count) > 0:
        return "heuristic_feasible_solution_available"
    return "search_exhausted_but_model_feasibility_unknown"


def _template_with_train_adjustment(
    template: ScheduleTemplate,
    train_id: str,
    delta_s: int,
    *,
    max_absolute_adjustment_s: int,
    locked_heavy_count: int = 0,
    locked_empty_count: int = 0,
) -> ScheduleTemplate | None:
    """在保持列车顺序的前提下，对指定重车或空车追加局部发车微调。"""

    normalized_id = str(train_id).strip().upper()
    if len(normalized_id) < 2 or normalized_id[0] not in {"H", "E"}:
        return None
    try:
        index = int(normalized_id[1:]) - 1
    except ValueError:
        return None
    is_heavy = normalized_id[0] == "H"
    locked_count = locked_heavy_count if is_heavy else locked_empty_count
    effective_index = index - locked_count
    count = int(template.heavy_count if is_heavy else template.empty_count)
    if effective_index < 0 or effective_index >= count:
        return None
    field_name = (
        "heavy_departure_adjustments_s"
        if is_heavy
        else "empty_departure_adjustments_s"
    )
    current = tuple(getattr(template, field_name, ()) or (0,) * count)
    adjusted_value = current[effective_index] + int(delta_s)
    if abs(adjusted_value) > int(max_absolute_adjustment_s):
        return None
    updated: list[int] = list(current)
    updated[effective_index] = adjusted_value
    candidate = replace(template, **{field_name: tuple(updated)})
    try:
        generate_schedule(candidate)
    except ValueError:
        return None
    return candidate


def targeted_resource_feasibility_repair_templates(
    initial_templates: Iterable[ScheduleTemplate],
    scenarios: Iterable[DisturbanceScenario],
    resource_model: ResourceModel,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    schedule_factory: Callable[[ScheduleTemplate], GeneratedSchedule],
    *,
    required_heavy_count: int,
    required_empty_count: int,
    disturbance_from_time_s: int | None = None,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
    adjustment_step_s: int = 60,
    max_absolute_adjustment_s: int = 600,
    max_iterations: int = 8,
    beam_width: int = 6,
    max_seeds: int = 1,
    work_budget=None,
) -> Tuple[List[ScheduleTemplate], Dict]:
    """按阻塞冲突涉及的列车构造局部错峰邻域，并以束搜索寻找稳健资源可行种子。"""

    if min(adjustment_step_s, max_absolute_adjustment_s, max_iterations, beam_width, max_seeds) <= 0:
        raise ValueError("targeted repair limits must be positive")
    core_scenarios = tuple(
        scenario for scenario in scenarios if _scenario_is_core_robust(scenario)
    )
    profile_cache: Dict[TemplateKey, Tuple[Tuple[int, int, float, int], Tuple[Any, ...]]] = {}
    templates_by_key: Dict[TemplateKey, ScheduleTemplate] = {}

    def profile(template: ScheduleTemplate) -> Tuple[Tuple[int, int, float, int], Tuple[Any, ...]]:
        key = template_key(template)
        templates_by_key[key] = template
        cached = profile_cache.get(key)
        if cached is not None:
            return cached
        candidate = schedule_factory(template)
        if (
            len(candidate.heavy_departures_s) != required_heavy_count
            or len(candidate.empty_departures_s) != required_empty_count
        ):
            result = ((len(core_scenarios) + 1, 10**9, float("inf"), 10**9), ())
            profile_cache[key] = result
            return result
        conflicts: List[Any] = []
        blocking_count = 0
        total_conflicts = 0
        total_overlap_s = 0.0
        for scenario in core_scenarios:
            if work_budget is not None:
                work_budget.resource()
            disturbed = apply_scenario(
                candidate,
                scenario,
                disturbance_from_time_s=disturbance_from_time_s,
                locked_heavy_departures_s=locked_heavy_departures_s,
                locked_empty_departures_s=locked_empty_departures_s,
            )
            checked = check_schedule_resources(
                disturbed,
                resource_model,
                heavy_cache,
                empty_cache,
            )
            if not checked.feasible:
                blocking_count += 1
            scenario_conflicts = tuple(getattr(checked, "conflicts", ()) or ())
            conflicts.extend(scenario_conflicts)
            scenario_conflict_count = int(
                getattr(checked, "conflict_count", len(scenario_conflicts))
            )
            scenario_overlap_s = float(getattr(checked, "overlap_violation_s", 0.0))
            total_conflicts += scenario_conflict_count
            total_overlap_s += scenario_overlap_s
        adjustment_magnitude = sum(
            abs(value)
            for value in (
                tuple(template.heavy_departure_adjustments_s)
                + tuple(template.empty_departure_adjustments_s)
            )
        )
        result = (
            (blocking_count, total_conflicts, round(total_overlap_s, 6), adjustment_magnitude),
            tuple(conflicts),
        )
        profile_cache[key] = result
        return result

    def scenario_details(template: ScheduleTemplate) -> Tuple[Dict[str, Any], ...]:
        """仅为最终排名靠前的候选生成可读冲突明细，避免拖慢候选搜索。"""
        candidate = schedule_factory(template)
        if (
            len(candidate.heavy_departures_s) != required_heavy_count
            or len(candidate.empty_departures_s) != required_empty_count
        ):
            return ()
        details: List[Dict[str, Any]] = []
        for scenario in core_scenarios:
            if work_budget is not None:
                work_budget.resource()
            disturbed = apply_scenario(
                candidate,
                scenario,
                disturbance_from_time_s=disturbance_from_time_s,
                locked_heavy_departures_s=locked_heavy_departures_s,
                locked_empty_departures_s=locked_empty_departures_s,
            )
            checked = check_schedule_resources(
                disturbed,
                resource_model,
                heavy_cache,
                empty_cache,
            )
            scenario_conflicts = tuple(getattr(checked, "conflicts", ()) or ())
            details.append({
                "scenario": scenario.name,
                "feasible": bool(checked.feasible),
                "conflict_count": int(
                    getattr(checked, "conflict_count", len(scenario_conflicts))
                ),
                "overlap_violation_s": round(
                    float(getattr(checked, "overlap_violation_s", 0.0)), 6
                ),
                "conflicts": [
                    {
                        "conflict_type": str(getattr(conflict, "conflict_type", "")),
                        "resource_id": str(getattr(conflict, "resource_id", "")),
                        "resource_name": str(getattr(conflict, "resource_name", "")),
                        "train_a": str(getattr(conflict, "train_a", "")),
                        "train_b": str(getattr(conflict, "train_b", "")),
                        "overlap_start_s": float(getattr(conflict, "overlap_start_s", 0.0)),
                        "overlap_end_s": float(getattr(conflict, "overlap_end_s", 0.0)),
                        "overlap_duration_s": float(
                            getattr(conflict, "overlap_duration_s", 0.0)
                        ),
                    }
                    for conflict in scenario_conflicts
                ],
            })
        return tuple(details)

    beam = unique_templates(initial_templates)
    beam.sort(key=lambda template: (profile(template)[0], template_key(template)))
    beam = beam[:beam_width]
    best_initial_score = profile(beam[0])[0] if beam else None
    feasible_seeds: List[ScheduleTemplate] = []
    visited = {template_key(template) for template in beam}
    iterations_completed = 0

    for iteration in range(max_iterations + 1):
        iterations_completed = iteration
        for template in beam:
            if profile(template)[0][0] == 0:
                feasible_seeds.append(template)
                if len(feasible_seeds) >= max_seeds:
                    break
        if feasible_seeds or iteration >= max_iterations:
            break
        neighbors: List[ScheduleTemplate] = []
        locked_h_count = len(tuple(locked_heavy_departures_s))
        locked_e_count = len(tuple(locked_empty_departures_s))
        for template in beam:
            _score, conflicts = profile(template)
            for conflict in conflicts[:6]:
                overlap_s = max(0.0, float(getattr(conflict, "overlap_duration_s", 0.0)))
                recommended_s = min(
                    3 * adjustment_step_s,
                    max(adjustment_step_s, int(math.ceil(overlap_s / adjustment_step_s) + 1) * adjustment_step_s),
                )
                for train_id, direction in (
                    (getattr(conflict, "train_a", ""), -1),
                    (getattr(conflict, "train_b", ""), 1),
                    (getattr(conflict, "train_a", ""), 1),
                    (getattr(conflict, "train_b", ""), -1),
                ):
                    neighbor = _template_with_train_adjustment(
                        template,
                        train_id,
                        direction * recommended_s,
                        max_absolute_adjustment_s=max_absolute_adjustment_s,
                        locked_heavy_count=locked_h_count,
                        locked_empty_count=locked_e_count,
                    )
                    if neighbor is None or template_key(neighbor) in visited:
                        continue
                    visited.add(template_key(neighbor))
                    neighbors.append(neighbor)
        if not neighbors:
            break
        neighbors.sort(key=lambda template: (profile(template)[0], template_key(template)))
        beam = neighbors[:beam_width]

    ranked_seen = sorted(
        ((value[0], key) for key, value in profile_cache.items()),
        key=lambda item: (item[0], item[1]),
    )
    best_ranked_templates = []
    for score, key in ranked_seen[:max(6, beam_width)]:
        template = templates_by_key[key]
        best_ranked_templates.append({
            "score": score,
            "template": describe_template(template),
            "heavy_departure_adjustments_s": list(
                template.heavy_departure_adjustments_s
            ),
            "empty_departure_adjustments_s": list(
                template.empty_departure_adjustments_s
            ),
            "scenario_details": list(scenario_details(template)),
        })
    return unique_templates(feasible_seeds), {
        "triggered": True,
        "repair_level": (
            "level_2_16_plus"
            if int(required_heavy_count) + int(required_empty_count) >= 16
            else "level_1_under_16"
        ),
        "total_train_count": int(required_heavy_count) + int(required_empty_count),
        "adjustment_step_s": adjustment_step_s,
        "max_absolute_adjustment_s": max_absolute_adjustment_s,
        "max_iterations": max_iterations,
        "beam_width": beam_width,
        "iterations_completed": iterations_completed,
        "evaluated_template_count": len(profile_cache),
        "resource_feasible_seed_count": len(feasible_seeds),
        "best_initial_score": best_initial_score,
        "best_final_score": ranked_seen[0][0] if ranked_seen else None,
        "best_ranked_templates": best_ranked_templates,
        "seed_templates": [describe_template(seed) for seed in feasible_seeds],
        "note": (
            "Local adjustments are conflict-driven repair decisions. Seeds still require the "
            "full robust energy, electrical, signaling, and service-population evaluation."
        ),
    }

def _nearest_allowed_value(value: int, allowed_values: Tuple[int, ...]) -> int:
    """将测试候选吸附到声明的离散域；等距时取较小值以保证确定性。"""

    if not allowed_values:
        return value
    return min(allowed_values, key=lambda allowed: (abs(allowed - value), allowed))


def clamp_template(template: ScheduleTemplate, config: TemplateSearchConfig) -> ScheduleTemplate:
    """Clamp a template to practical search bounds."""
    preset_ids = [str(item) for item in (config.storage_preset_ids or ()) if str(item)]
    preset_id = str(getattr(template, "storage_preset_id", "") or "")
    if config.enable_storage_preset_search and preset_ids:
        if preset_id not in preset_ids:
            preset_id = preset_ids[0]
    elif not config.enable_storage_preset_search:
        preset_id = preset_ids[0] if preset_ids else ""
    phase_s = max(
        0,
        min(
            config.max_phase_s,
            _validated_whole_number(
                template.heavy_empty_phase_s,
                "template.heavy_empty_phase_s",
            ),
        ),
    )
    phase_s = _nearest_allowed_value(phase_s, config.allowed_phases_s)
    start_time_s = max(
        0,
        _validated_whole_number(template.start_time_s, "template.start_time_s"),
    )
    storage_shift_s = max(
        -min(config.max_storage_align_shift_s, start_time_s + phase_s),
        min(
            config.max_storage_align_shift_s,
            _validated_whole_number(
                template.storage_align_shift_s,
                "template.storage_align_shift_s",
            ),
        ),
    )
    allowed_storage_shifts = tuple(
        value
        for value in config.allowed_storage_align_shifts_s
        if value >= -(start_time_s + phase_s)
    )
    storage_shift_s = _nearest_allowed_value(storage_shift_s, allowed_storage_shifts)
    heavy_adjustments = tuple(
        _validated_whole_number(value, "template.heavy_departure_adjustments_s")
        for value in (template.heavy_departure_adjustments_s or ())
    )
    empty_adjustments = tuple(
        _validated_whole_number(value, "template.empty_departure_adjustments_s")
        for value in (template.empty_departure_adjustments_s or ())
    )
    if heavy_adjustments and len(heavy_adjustments) != int(template.heavy_count):
        raise ValueError("heavy departure adjustment count must match heavy_count")
    if empty_adjustments and len(empty_adjustments) != int(template.empty_count):
        raise ValueError("empty departure adjustment count must match empty_count")
    return replace(
        template,
        heavy_headway_s=_nearest_allowed_value(
            max(
                config.min_headway_s,
                min(config.max_headway_s, _validated_whole_number(template.heavy_headway_s, "template.heavy_headway_s")),
            ),
            config.allowed_heavy_headways_s,
        ),
        empty_headway_s=_nearest_allowed_value(
            max(
                config.min_headway_s,
                min(config.max_headway_s, _validated_whole_number(template.empty_headway_s, "template.empty_headway_s")),
            ),
            config.allowed_empty_headways_s,
        ),
        heavy_empty_phase_s=phase_s,
        # 数量是输入需求，不是变异基因。负数必须校验失败，不能变成看似能效很高的零服务计划。
        heavy_count=_validated_whole_seconds(template.heavy_count, "template.heavy_count"),
        empty_count=_validated_whole_seconds(template.empty_count, "template.empty_count"),
        start_time_s=start_time_s,
        flex_zone_hold_s=_nearest_allowed_value(
            max(
                0,
                min(config.max_hold_s, _validated_whole_number(template.flex_zone_hold_s, "template.flex_zone_hold_s")),
            ),
            config.allowed_holds_s,
        ),
        storage_align_shift_s=storage_shift_s,
        storage_preset_id=preset_id,
        heavy_departure_adjustments_s=heavy_adjustments,
        empty_departure_adjustments_s=empty_adjustments,
    )

def mutate_template(template: ScheduleTemplate, config: TemplateSearchConfig, rng: random.Random) -> ScheduleTemplate:
    """Mutate a low-dimensional template around expert-rule values."""
    heavy_delta = rng.choice([-1, 0, 1]) * config.headway_mutation_s
    empty_delta = rng.choice([-1, 0, 1]) * config.headway_mutation_s
    phase_delta = rng.choice([-1, 0, 1]) * config.phase_mutation_s
    hold_delta = rng.choice([-1, 0, 1]) * config.hold_mutation_s
    storage_shift_delta = rng.choice([-1, 0, 1]) * config.storage_shift_mutation_s
    storage_preset_id = str(getattr(template, "storage_preset_id", "") or "")
    if rng.random() > config.mutation_probability:
        heavy_delta = 0
    if rng.random() > config.mutation_probability:
        empty_delta = 0
    if rng.random() > config.mutation_probability:
        phase_delta = 0
    if rng.random() > config.mutation_probability:
        hold_delta = 0
    if rng.random() > config.mutation_probability:
        storage_shift_delta = 0
    if (
        config.enable_storage_preset_search
        and config.storage_preset_ids
        and rng.random() <= max(config.mutation_probability, config.storage_preset_mutation_probability)
    ):
        storage_preset_id = rng.choice([str(item) for item in config.storage_preset_ids])
    return clamp_template(
        replace(
            template,
            heavy_headway_s=template.heavy_headway_s + heavy_delta,
            empty_headway_s=template.empty_headway_s + empty_delta,
            heavy_empty_phase_s=template.heavy_empty_phase_s + phase_delta,
            flex_zone_hold_s=template.flex_zone_hold_s + hold_delta,
            storage_align_shift_s=template.storage_align_shift_s + storage_shift_delta,
            storage_preset_id=storage_preset_id,
        ),
        config,
    )

def crossover_templates(
    left: ScheduleTemplate,
    right: ScheduleTemplate,
    config: TemplateSearchConfig,
    rng: random.Random,) -> ScheduleTemplate:
    """Uniform crossover over the compact strategy parameters."""
    return clamp_template(
        replace(
            left,
            heavy_headway_s=rng.choice([left.heavy_headway_s, right.heavy_headway_s]),
            empty_headway_s=rng.choice([left.empty_headway_s, right.empty_headway_s]),
            heavy_empty_phase_s=rng.choice([left.heavy_empty_phase_s, right.heavy_empty_phase_s]),
            flex_zone_hold_s=rng.choice([left.flex_zone_hold_s, right.flex_zone_hold_s]),
            storage_align_shift_s=rng.choice([left.storage_align_shift_s, right.storage_align_shift_s]),
            storage_preset_id=rng.choice(
                [
                    str(getattr(left, "storage_preset_id", "") or ""),
                    str(getattr(right, "storage_preset_id", "") or ""),
                ]
            ),
        ),
        config,
    )

def unique_templates(templates: Iterable[ScheduleTemplate]) -> List[ScheduleTemplate]:
    """Deduplicate templates by strategy genes while preserving order."""
    result: List[ScheduleTemplate] = []
    seen: set[TemplateKey] = set()
    for template in templates:
        key = template_key(template)
        if key in seen:
            continue
        seen.add(key)
        result.append(template)
    return result

def batch_evaluate_templates(
    templates: Iterable[ScheduleTemplate],
    evaluate_template: Callable[[ScheduleTemplate], ScheduleScore],
    max_workers: int = 1,) -> List[Tuple[ScheduleTemplate, ScheduleScore]]:
    """Evaluate schedule templates in a deterministic order, optionally in parallel."""
    template_list = list(templates)
    if max_workers <= 1 or len(template_list) <= 1:
        return [(template, evaluate_template(template)) for template in template_list]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        scores = list(executor.map(evaluate_template, template_list))
    return list(zip(template_list, scores))


def _pad_unique_population(
    population: List[ScheduleTemplate],
    base_template: ScheduleTemplate,
    config: TemplateSearchConfig,
    rng: random.Random,
) -> List[ScheduleTemplate]:
    """Try to fill a population without looping forever in a degenerate search space."""

    population = unique_templates(population)
    seen = {template_key(template) for template in population}
    attempt_limit = max(100, config.population_size * 20)
    for _attempt in range(attempt_limit):
        if len(population) >= config.population_size:
            break
        candidate = mutate_template(base_template, config, rng)
        key = template_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        population.append(candidate)
    return population

def evolutionary_template_search(
    base_template: ScheduleTemplate,
    config: TemplateSearchConfig,
    evaluate_template,) -> List[Tuple[ScheduleTemplate, ScheduleScore]]:
    """Search compact strategy parameters with a lightweight evolutionary loop."""
    rng = random.Random(config.seed)
    seed_templates = unique_templates(
        [base_template]
        + robust_buffer_seed_templates(base_template)
        + candidate_templates(
            base_template,
            headway_offsets_s=(
                -2 * config.headway_mutation_s,
                -config.headway_mutation_s,
                0,
                config.headway_mutation_s,
                2 * config.headway_mutation_s,
            ),
            phase_offsets_s=(
                -2 * config.phase_mutation_s,
                -config.phase_mutation_s,
                0,
                config.phase_mutation_s,
                2 * config.phase_mutation_s,
            ),
            hold_options_s=(0, config.hold_mutation_s, min(config.max_hold_s, 2 * config.hold_mutation_s)),
            storage_shift_options_s=(
                0,
                config.storage_shift_mutation_s,
                -config.storage_shift_mutation_s,
                min(config.max_storage_align_shift_s, 2 * config.storage_shift_mutation_s),
                -min(config.max_storage_align_shift_s, 2 * config.storage_shift_mutation_s),
                min(config.max_storage_align_shift_s, 3 * config.storage_shift_mutation_s),
                -min(config.max_storage_align_shift_s, 3 * config.storage_shift_mutation_s),
            ),
        )
    )
    seed_templates = [clamp_template(template, config) for template in seed_templates]
    rng.shuffle(seed_templates)
    storage_seed_templates: List[ScheduleTemplate] = []
    forced_storage_templates: List[ScheduleTemplate] = []
    forced_robust_templates: List[ScheduleTemplate] = []
    # 始终将已知的轻度稳健运行图候选注入基线储能环境。
    for seed in known_light_robust_seed_templates(base_template):
        forced_robust_templates.append(clamp_template(seed, config))
    if config.enable_storage_preset_search and config.storage_preset_ids:
        for preset_id in config.storage_preset_ids:
            forced = clamp_template(replace(base_template, storage_preset_id=str(preset_id)), config)
            forced_storage_templates.append(forced)
            storage_seed_templates.append(forced)
            # 在每个储能预设下保留若干已知稳健运行图形状。
            for seed in known_light_robust_seed_templates(replace(base_template, storage_preset_id=str(preset_id)))[:8]:
                forced_robust_templates.append(clamp_template(seed, config))
            for seed in robust_buffer_seed_templates(replace(base_template, storage_preset_id=str(preset_id)))[:10]:
                storage_seed_templates.append(clamp_template(seed, config))
    else:
        for seed in robust_buffer_seed_templates(base_template)[:12]:
            storage_seed_templates.append(clamp_template(seed, config))
    seed_templates = unique_templates(forced_robust_templates + storage_seed_templates + seed_templates)
    # 种群被截断时，保留基线、储能基因和已知稳健运行图形状。
    population = unique_templates([base_template] + forced_storage_templates + forced_robust_templates + seed_templates)
    if len(population) > config.population_size:
        # 优先级为基线、每个储能预设一个候选、已知稳健形状。
        must_keep = unique_templates(
            [base_template] + forced_storage_templates + forced_robust_templates
        )
        # 条件允许时始终保留每个强制储能预设个体。
        keep_n = min(len(must_keep), max(config.population_size - 1, len(forced_storage_templates) + 1))
        must_keep = unique_templates(must_keep)[:keep_n]
        fillers = [item for item in population if template_key(item) not in {template_key(x) for x in must_keep}]
        population = unique_templates(must_keep + fillers)[: config.population_size]
    population = _pad_unique_population(population, base_template, config, rng)
    evaluated: Dict[TemplateKey, Tuple[ScheduleTemplate, ScheduleScore]] = {}
    def evaluate_once(template: ScheduleTemplate) -> Tuple[ScheduleTemplate, ScheduleScore]:
        """函数 evaluate_once：执行该模块中的相关处理逻辑。"""
        key = template_key(template)
        if key not in evaluated:
            evaluated[key] = (template, evaluate_template(template))
        return evaluated[key]
    def evaluate_many(templates: Iterable[ScheduleTemplate]) -> List[Tuple[ScheduleTemplate, ScheduleScore]]:
        """函数 evaluate_many：执行该模块中的相关处理逻辑。"""
        template_list = list(templates)
        missing = [template for template in template_list if template_key(template) not in evaluated]
        if missing:
            for template, score in batch_evaluate_templates(
                missing,
                evaluate_template,
                max_workers=max(1, config.parallel_workers),
            ):
                evaluated[template_key(template)] = (template, score)
        return [evaluated[template_key(template)] for template in template_list]
    for _generation in range(config.generations):
        ranked = sorted(evaluate_many(population), key=lambda item: candidate_selection_key(item[1]))
        elites = [template for template, _score in ranked[: config.elite_count]]
        next_population = list(elites)
        while len(next_population) < config.population_size:
            parent_a = rng.choice(elites)
            parent_b = rng.choice(elites)
            child = crossover_templates(parent_a, parent_b, config, rng)
            child = mutate_template(child, config, rng)
            next_population.append(child)
        population = unique_templates(next_population)
    evaluate_many(population)
    final_ranked = sorted(evaluated.values(), key=lambda item: candidate_selection_key(item[1]))
    return final_ranked

def nsga2_template_search(
    base_template: ScheduleTemplate,
    config: TemplateSearchConfig,
    evaluate_template,) -> List[Tuple[ScheduleTemplate, ScheduleScore]]:
    """Run a compact NSGA-II search over template strategy parameters."""
    rng = random.Random(config.seed)
    # 相位下界可能离基线数个变异步长。占用一个现有种群名额，仍按完整硬约束评分。
    phase_floor_template = clamp_template(replace(base_template, heavy_empty_phase_s=0), config)
    seed_templates = unique_templates(
        [base_template]
        + robust_buffer_seed_templates(base_template)
        + candidate_templates(
            base_template,
            headway_offsets_s=(
                -2 * config.headway_mutation_s,
                -config.headway_mutation_s,
                0,
                config.headway_mutation_s,
                2 * config.headway_mutation_s,
            ),
            phase_offsets_s=(
                -2 * config.phase_mutation_s,
                -config.phase_mutation_s,
                0,
                config.phase_mutation_s,
                2 * config.phase_mutation_s,
            ),
            hold_options_s=(0, config.hold_mutation_s, min(config.max_hold_s, 2 * config.hold_mutation_s)),
            storage_shift_options_s=(
                0,
                config.storage_shift_mutation_s,
                -config.storage_shift_mutation_s,
                min(config.max_storage_align_shift_s, 2 * config.storage_shift_mutation_s),
                -min(config.max_storage_align_shift_s, 2 * config.storage_shift_mutation_s),
                min(config.max_storage_align_shift_s, 3 * config.storage_shift_mutation_s),
                -min(config.max_storage_align_shift_s, 3 * config.storage_shift_mutation_s),
            ),
        )
    )
    seed_templates = [clamp_template(template, config) for template in seed_templates]
    rng.shuffle(seed_templates)
    storage_seed_templates: List[ScheduleTemplate] = []
    forced_storage_templates: List[ScheduleTemplate] = []
    forced_robust_templates: List[ScheduleTemplate] = []
    # 始终将已知的轻度稳健运行图候选注入基线储能环境。
    for seed in known_light_robust_seed_templates(base_template):
        forced_robust_templates.append(clamp_template(seed, config))
    if config.enable_storage_preset_search and config.storage_preset_ids:
        for preset_id in config.storage_preset_ids:
            forced = clamp_template(replace(base_template, storage_preset_id=str(preset_id)), config)
            forced_storage_templates.append(forced)
            storage_seed_templates.append(forced)
            # 在每个储能预设下保留若干已知稳健运行图形状。
            for seed in known_light_robust_seed_templates(replace(base_template, storage_preset_id=str(preset_id)))[:8]:
                forced_robust_templates.append(clamp_template(seed, config))
            for seed in robust_buffer_seed_templates(replace(base_template, storage_preset_id=str(preset_id)))[:10]:
                storage_seed_templates.append(clamp_template(seed, config))
    else:
        for seed in robust_buffer_seed_templates(base_template)[:12]:
            storage_seed_templates.append(clamp_template(seed, config))
    seed_templates = unique_templates(forced_robust_templates + storage_seed_templates + seed_templates)
    # 种群被截断时，保留基线、储能基因和已知稳健运行图形状。
    population = unique_templates(
        [base_template] + forced_storage_templates + forced_robust_templates + [phase_floor_template] + seed_templates
    )
    if len(population) > config.population_size:
        # 优先保留已知稳健形状，然后为每个储能预设保留一个个体。
        must_keep = unique_templates(
            [base_template] + forced_robust_templates + [phase_floor_template] + forced_storage_templates
        )
        keep_n = max(6, min(config.population_size - 1, max(len(forced_robust_templates), config.population_size // 2)))
        must_keep = unique_templates(must_keep)[:keep_n]
        fillers = [item for item in population if template_key(item) not in {template_key(x) for x in must_keep}]
        population = unique_templates(must_keep + fillers)[: config.population_size]
    population = _pad_unique_population(population, base_template, config, rng)
    evaluated: Dict[TemplateKey, Tuple[ScheduleTemplate, ScheduleScore]] = {}
    def evaluate_once(template: ScheduleTemplate) -> Tuple[ScheduleTemplate, ScheduleScore]:
        """函数 evaluate_once：执行该模块中的相关处理逻辑。"""
        key = template_key(template)
        if key not in evaluated:
            evaluated[key] = (template, evaluate_template(template))
        return evaluated[key]
    def evaluate_many(templates: Iterable[ScheduleTemplate]) -> List[Tuple[ScheduleTemplate, ScheduleScore]]:
        """函数 evaluate_many：执行该模块中的相关处理逻辑。"""
        template_list = list(templates)
        missing = [template for template in template_list if template_key(template) not in evaluated]
        if missing:
            for template, score in batch_evaluate_templates(
                missing,
                evaluate_template,
                max_workers=max(1, config.parallel_workers),
            ):
                evaluated[template_key(template)] = (template, score)
        return [evaluated[template_key(template)] for template in template_list]
    def tournament_select(ranked_population: List[Tuple[ScheduleTemplate, ScheduleScore]]) -> ScheduleTemplate:
        """函数 tournament_select：执行该模块中的相关处理逻辑。"""
        left = rng.choice(ranked_population)
        right = rng.choice(ranked_population)
        left_rank = front_ranks[template_key(left[0])]
        right_rank = front_ranks[template_key(right[0])]
        if left_rank < right_rank:
            return left[0]
        if right_rank < left_rank:
            return right[0]
        left_distance = crowding_by_key.get(template_key(left[0]), 0.0)
        right_distance = crowding_by_key.get(template_key(right[0]), 0.0)
        return left[0] if left_distance >= right_distance else right[0]
    front_ranks: Dict[Tuple[int, int, int, int], int] = {}
    crowding_by_key: Dict[TemplateKey, float] = {}
    for _generation in range(config.generations):
        evaluated_population = evaluate_many(population)
        fronts = non_dominated_sort(evaluated_population)
        front_ranks = {}
        crowding_by_key = {}
        for rank, front in enumerate(fronts):
            for template, _score in front:
                front_ranks[template_key(template)] = rank
            crowding_by_key.update(crowding_distances(front))
        offspring: List[ScheduleTemplate] = []
        while len(offspring) < config.population_size:
            parent_a = tournament_select(evaluated_population)
            parent_b = tournament_select(evaluated_population)
            child = crossover_templates(parent_a, parent_b, config, rng)
            child = mutate_template(child, config, rng)
            offspring.append(child)
        combined = unique_templates(population + offspring)
        evaluated_combined = evaluate_many(combined)
        combined_fronts = non_dominated_sort(evaluated_combined)
        next_population: List[ScheduleTemplate] = []
        for front in combined_fronts:
            if len(next_population) + len(front) <= config.population_size:
                next_population.extend(template for template, _score in front)
                continue
            distances = crowding_distances(front)
            remaining = config.population_size - len(next_population)
            sorted_front = sorted(
                front,
                key=lambda item: distances.get(template_key(item[0]), 0.0),
                reverse=True,
            )
            next_population.extend(template for template, _score in sorted_front[:remaining])
            break
        population = unique_templates(next_population)
    final_population = evaluate_many(population)
    final_fronts = non_dominated_sort(final_population)
    ranked: List[Tuple[ScheduleTemplate, ScheduleScore]] = []
    for front in final_fronts:
        distances = crowding_distances(front)
        ranked.extend(
            sorted(
                front,
                key=lambda item: (
                    candidate_selection_key(item[1]),
                    -distances.get(template_key(item[0]), 0.0),
                ),
            )
        )
    return ranked

def pareto_template_front(
    evaluated_templates: List[Tuple[ScheduleTemplate, ScheduleScore]],) -> List[Tuple[ScheduleTemplate, ScheduleScore]]:
    """Extract non-dominated low-dimensional schedule strategies."""
    feasible_items = [(template, score) for template, score in evaluated_templates if score.feasible]
    front: List[Tuple[ScheduleTemplate, ScheduleScore]] = []
    for template, score in feasible_items:
        dominated = False
        for other_template, other_score in feasible_items:
            if other_template == template:
                continue
            other_objectives = effective_objective_tuple(other_score)
            objectives = effective_objective_tuple(score)
            no_worse = all(other <= current for other, current in zip(other_objectives, objectives))
            strictly_better = any(other < current for other, current in zip(other_objectives, objectives))
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            front.append((template, score))
    sorted_front = sorted(front, key=lambda item: (candidate_selection_key(item[1]), objective_tuple(item[1])))
    unique_front: List[Tuple[ScheduleTemplate, ScheduleScore]] = []
    seen_objectives: set[Tuple[int, int, int]] = set()
    for template, score in sorted_front:
        key = effective_objective_tuple(score)
        if key in seen_objectives:
            continue
        seen_objectives.add(key)
        unique_front.append((template, score))
    return unique_front

def scenario_diagnostic_rows(
    schedule: GeneratedSchedule,
    scenario_scores: Iterable[ScenarioScore],
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    resource_model: ResourceModel | None = None,
    disturbance_from_time_s: int | None = None,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
) -> List[Dict]:
    """把已计算的单场景评分转换为可解释诊断行。"""

    rows: List[Dict] = []
    for scenario, score in scenario_scores:
        disturbed = apply_scenario(
            schedule,
            scenario,
            disturbance_from_time_s=disturbance_from_time_s,
            locked_heavy_departures_s=locked_heavy_departures_s,
            locked_empty_departures_s=locked_empty_departures_s,
        )
        conflict_summary = ""
        if resource_model is not None and score.resource_conflict_count:
            resource_check = check_schedule_resources(
                disturbed, resource_model, heavy_cache, empty_cache
            )
            top = resource_check.conflicts[:3]
            conflict_summary = " | ".join(
                f"{c.conflict_type}:{c.resource_name}:{c.train_a}/{c.train_b}"
                for c in top
            )
        rows.append(
            {
                "scenario": scenario.name,
                "feasible": score.feasible,
                "heavy_delay_s": scenario.heavy_delay_s,
                "empty_delay_s": scenario.empty_delay_s,
                "heavy_headway_stretch_s": scenario.heavy_headway_stretch_s,
                "empty_headway_stretch_s": scenario.empty_headway_stretch_s,
                "cost_multiplier": scenario.cost_multiplier,
                "constraint_violation": round(score.constraint_violation, 6),
                "resource_conflict_count": score.resource_conflict_count,
                "flow_continuity_violation_count": score.flow_continuity_violation_count,
                "total_cost": round(score.total_cost, 6),
                "grid_kwh": round(score.grid_kwh, 6),
                "wasted_kwh": round(score.wasted_kwh, 6),
                "battery_charge_kwh": round(score.battery_charge_kwh, 6),
                "battery_discharge_kwh": round(score.battery_discharge_kwh, 6),
                "final_soc_deviation_kwh": round(score.final_soc_deviation_kwh, 6),
                "conflict_summary": conflict_summary,
                "core_for_feasibility": _scenario_is_core_robust(scenario),
                "blocking": _scenario_is_core_robust(scenario) and (not score.feasible),
                "diagnostic_failure": not score.feasible,
            }
        )
    return rows


def explain_robust_scenarios(
    schedule: GeneratedSchedule,
    scenarios: List[DisturbanceScenario],
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    settlement_system: EnergySettlementSystem,
    signaling_system: Dict,
    resource_model: ResourceModel | None = None,
    storage_sections: Iterable[StorageSectionInterval] | None = None,
    min_depart_gap_s: int = 300,
    target_gap_s: int = 1000,
    objective_mode: str = OBJECTIVE_MODE_BALANCED,
    energy_scenario: str = ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    objective_priority: str = OBJECTIVE_PRIORITY_ENERGY_FIRST,
    disturbance_from_time_s: int | None = None,
    locked_heavy_departures_s: Iterable[int] = (),
    locked_empty_departures_s: Iterable[int] = (),
    energy_from_time_s: int | None = None,
    energy_until_time_s: int | None = None,
) -> List[Dict]:
    """Explain which disturbance scenarios keep/break a schedule."""
    scenario_scores: List[ScenarioScore] = []
    for scenario in scenarios:
        disturbed = apply_scenario(
            schedule,
            scenario,
            disturbance_from_time_s=disturbance_from_time_s,
            locked_heavy_departures_s=locked_heavy_departures_s,
            locked_empty_departures_s=locked_empty_departures_s,
        )
        score = evaluate_schedule(
            disturbed,
            heavy_cache,
            empty_cache,
            settlement_system,
            signaling_system,
            resource_model=resource_model,
            storage_sections=storage_sections,
            min_depart_gap_s=min_depart_gap_s,
            target_gap_s=target_gap_s,
            objective_mode=objective_mode,
            energy_scenario=energy_scenario,
            objective_priority=objective_priority,
            energy_from_time_s=energy_from_time_s,
            energy_until_time_s=energy_until_time_s,
        )
        scenario_scores.append((scenario, score))
    return scenario_diagnostic_rows(
        schedule,
        scenario_scores,
        heavy_cache,
        empty_cache,
        resource_model=resource_model,
        disturbance_from_time_s=disturbance_from_time_s,
        locked_heavy_departures_s=locked_heavy_departures_s,
        locked_empty_departures_s=locked_empty_departures_s,
    )

def build_search_diagnostics(
    ranked_templates: List[Tuple[ScheduleTemplate, ScheduleScore]],
    search_config: TemplateSearchConfig,) -> Dict:
    """Summarize whether the search explored diverse and energy-sensitive templates."""
    if not ranked_templates:
        return {
            "candidate_count": 0,
            "unique_template_count": 0,
            "feasible_count": 0,
            "core_robust_feasible_count": 0,
            "energy_flat": True,
            "recommended_search_profile": "large",
            "search_scale_note": "No candidates evaluated; increase population/generations or use --search-profile large.",
            "note": "No candidates were evaluated.",
        }
    templates = [template for template, _score in ranked_templates]
    scores = [score for _template, score in ranked_templates]
    grids = [round(score.grid_kwh, 3) for score in scores]
    wasted = [round(score.wasted_kwh, 3) for score in scores]
    charges = [round(score.battery_charge_kwh, 3) for score in scores]
    phases = [template.heavy_empty_phase_s for template in templates]
    holds = [template.flex_zone_hold_s for template in templates]
    storage_shifts = [template.storage_align_shift_s for template in templates]
    storage_presets = [str(getattr(template, "storage_preset_id", "") or "") for template in templates]
    headways = sorted({(template.heavy_headway_s, template.empty_headway_s) for template in templates})
    energy_flat = len(set(grids)) <= 1 and len(set(wasted)) <= 1 and len(set(charges)) <= 1
    core_robust_feasible_count = sum(1 for score in scores if score.feasible)
    if energy_flat:
        note = (
            "Energy metrics stayed flat across explored templates. If storage-preset search is disabled, "
            "schedule-only genes mainly change feasibility/capacity under storage_no_direct. Enable "
            "storage preset genes (power/coverage) to restore energy trade-offs."
        )
    else:
        note = "Search produced non-flat energy metrics across candidates."
        if len(set(storage_presets)) > 1:
            note += " Storage-preset genes contributed to energy diversity."
    if core_robust_feasible_count == 0:
        note += " No core-robust-feasible candidate was found."
    else:
        note += f" Core-robust-feasible candidates: {core_robust_feasible_count}."
    recommended = "standard"
    search_scale_note = "Current search scale is adequate for a prototype diagnostic run."
    if energy_flat or core_robust_feasible_count == 0 or len({template_key(template) for template in templates}) < max(4, search_config.population_size // 2):
        recommended = "large"
        large = SEARCH_PROFILE_PRESETS["large"]
        search_scale_note = (
            f"Recommend --search-profile large (population_size={large['population_size']}, "
            f"generations={large['generations']}) when energy is flat, robust coverage is weak, "
            f"or unique templates stay low."
        )
    elif search_config.population_size >= SEARCH_PROFILE_PRESETS["large"]["population_size"]:
        recommended = "large"
        search_scale_note = "Already running at or above the large search profile."
    return {
        "candidate_count": len(ranked_templates),
        "unique_template_count": len({template_key(template) for template in templates}),
        "feasible_count": sum(1 for score in scores if score.feasible),
        "core_robust_feasible_count": core_robust_feasible_count,
        "phase_span_s": (max(phases) - min(phases)) if phases else 0,
        "hold_span_s": (max(holds) - min(holds)) if holds else 0,
        "storage_shift_span_s": (max(storage_shifts) - min(storage_shifts)) if storage_shifts else 0,
        "unique_storage_presets": len(set(storage_presets)),
        "storage_presets": sorted(set(storage_presets)),
        "unique_headway_pairs": len(headways),
        "unique_grid_kwh": len(set(grids)),
        "unique_wasted_kwh": len(set(wasted)),
        "unique_battery_charge_kwh": len(set(charges)),
        "grid_kwh_span": round(max(grids) - min(grids), 3) if grids else 0.0,
        "wasted_kwh_span": round(max(wasted) - min(wasted), 3) if wasted else 0.0,
        "battery_charge_kwh_span": round(max(charges) - min(charges), 3) if charges else 0.0,
        "energy_flat": energy_flat,
        "search_method": search_config.method,
        "population_size": search_config.population_size,
        "generations": search_config.generations,
        "elite_count": search_config.elite_count,
        "enable_storage_preset_search": bool(search_config.enable_storage_preset_search),
        "recommended_search_profile": recommended,
        "search_scale_note": search_scale_note,
        "search_profile_presets": SEARCH_PROFILE_PRESETS,
        "note": note,
    }

def default_scenarios(observed_heavy_delay_s: int = 0, observed_empty_delay_s: int = 0) -> List[DisturbanceScenario]:
    """Default scenario set for robust evaluation.    Keep a hard +300s delay pair for operational robustness, and add lighter    +120s delays so the search can distinguish near-robust templates instead of    collapsing every candidate to infeasible.    """
    return [
        DisturbanceScenario("normal", observed_heavy_delay_s, observed_empty_delay_s),
        DisturbanceScenario("heavy_delay_light", observed_heavy_delay_s + 120, observed_empty_delay_s),
        DisturbanceScenario("empty_delay_light", observed_heavy_delay_s, observed_empty_delay_s + 120),
        DisturbanceScenario(
            "heavy_delay",
            observed_heavy_delay_s + 300,
            observed_empty_delay_s,
            core_for_feasibility=False,
        ),
        DisturbanceScenario(
            "empty_delay",
            observed_heavy_delay_s,
            observed_empty_delay_s + 300,
            core_for_feasibility=False,
        ),
    ]

class _SignalingRoute(Protocol):
    """滚动优化评价所需的最小线路接口。"""

    signaling_system: Dict[str, Any]


@dataclass(frozen=True)
class StorageEvalContext:
    """一个虚拟储能参数方案对应的预构建评价上下文。"""
    preset_id: str
    route: _SignalingRoute
    heavy_cache: PowerSeriesCache
    empty_cache: PowerSeriesCache
    settlement_system: EnergySettlementSystem
    storage_sections: Tuple[StorageSectionInterval, ...] = ()
    label: str = ""
    note: str = ""
    data_status: str = "planning_virtual_preset_search"
    battery: object | None = None
    power_arm_limits: object | None = None


def resolve_storage_eval_context(
    storage_contexts: Dict[str, StorageEvalContext],
    preset_id: str,
    default_preset_id: str = "",
) -> StorageEvalContext:
    """Resolve one storage context without silently changing the requested preset."""

    if not storage_contexts:
        raise ValueError("storage_contexts must contain at least one evaluation context")
    requested_id = str(preset_id or "").strip()
    default_id = str(default_preset_id or "").strip()
    resolved_id = requested_id or default_id
    if resolved_id in storage_contexts:
        return storage_contexts[resolved_id]
    source = "storage_preset_id" if requested_id else "default_storage_preset_id"
    raise ValueError(
        f"Unknown {source} {resolved_id!r}; "
        f"known preset IDs are {sorted(storage_contexts)!r}"
    )


class RollingOptimizer:
    """MPC-style rolling optimizer over a short future horizon."""
    def __init__(
        self,
        route,
        heavy_cache: PowerSeriesCache,
        empty_cache: PowerSeriesCache,
        settlement_system: EnergySettlementSystem,
        resource_model: ResourceModel | None = None,
        storage_sections: Iterable[StorageSectionInterval] | None = None,
        storage_contexts: Dict[str, StorageEvalContext] | None = None,
        default_storage_preset_id: str = "",
    ) -> None:
        """函数 __init__：执行该模块中的相关处理逻辑。"""
        self.route = route
        self.heavy_cache = heavy_cache
        self.empty_cache = empty_cache
        self.settlement_system = settlement_system
        self.resource_model = resource_model
        self.base_resource_model = resource_model
        self.storage_sections = tuple(storage_sections) if storage_sections is not None else None
        self.default_storage_preset_id = str(default_storage_preset_id or "")
        if storage_contexts:
            self.storage_contexts = dict(storage_contexts)
        else:
            baseline_id = self.default_storage_preset_id or ""
            self.storage_contexts = {
                baseline_id: StorageEvalContext(
                    preset_id=baseline_id,
                    route=route,
                    heavy_cache=heavy_cache,
                    empty_cache=empty_cache,
                    settlement_system=settlement_system,
                    storage_sections=tuple(self.storage_sections or ()),
                    label="baseline_storage",
                    note="Single fixed storage context.",
                    data_status="fixed_storage_context",
                )
            }
    def _context_for(self, template: ScheduleTemplate) -> StorageEvalContext:
        """函数 _context_for：执行该模块中的相关处理逻辑。"""
        return resolve_storage_eval_context(
            self.storage_contexts,
            str(getattr(template, "storage_preset_id", "") or ""),
            self.default_storage_preset_id,
        )
    def optimize_once(
        self,
        state: RollingWindowState,
        base_template: ScheduleTemplate,
        horizon_s: int = 7200,
        execute_window_s: int = 600,
        search_config: TemplateSearchConfig | None = None,
        objective_mode: str = OBJECTIVE_MODE_BALANCED,
        energy_scenario: str = ENERGY_SCENARIO_STORAGE_NO_DIRECT,
        objective_priority: str = OBJECTIVE_PRIORITY_ENERGY_FIRST,
        min_depart_gap_s: int | None = None,
        target_gap_s: int | None = None,
        enable_recovery: bool = True,
        allow_infeasible_commit_for_experiment: bool = False,
    ) -> RollingOptimizationResult:
        """Optimize one rolling horizon and return only near-term decisions to execute."""
        if not isinstance(enable_recovery, bool):
            raise TypeError("enable_recovery must be a boolean")
        if not isinstance(allow_infeasible_commit_for_experiment, bool):
            raise TypeError("allow_infeasible_commit_for_experiment must be a boolean")
        best_schedule: GeneratedSchedule | None = None
        best_score: ScheduleScore | None = None
        search_config = search_config or TemplateSearchConfig()
        observed_heavy_delay_s = _validated_whole_seconds(
            state.observed_heavy_delay_s, "state.observed_heavy_delay_s"
        )
        observed_empty_delay_s = _validated_whole_seconds(
            state.observed_empty_delay_s, "state.observed_empty_delay_s"
        )
        observed_train_delays_s = _normalize_observed_train_delays(
            state.observed_train_delays_s
        )
        self.resource_model = self.base_resource_model
        if state.resource_unavailabilities:
            if self.base_resource_model is None:
                raise ValueError("资源封锁事件需要已配置的资源模型。")
            self.resource_model = replace(
                self.base_resource_model,
                unavailabilities=tuple(state.resource_unavailabilities),
            )
        if observed_heavy_delay_s and any(
            train_id.startswith("H") and delay_s
            for train_id, delay_s in observed_train_delays_s
        ):
            raise ValueError("同一周期不能同时提供重车汇总晚点和重车逐列车晚点。")
        if observed_empty_delay_s and any(
            train_id.startswith("E") and delay_s
            for train_id, delay_s in observed_train_delays_s
        ):
            raise ValueError("同一周期不能同时提供空车汇总晚点和空车逐列车晚点。")
        scenarios = default_scenarios(
            observed_heavy_delay_s, observed_empty_delay_s
        )
        current_time_s = _validated_whole_seconds(
            state.current_time_s, "state.current_time_s"
        )
        locked_heavy_departures_s = [
            _validated_whole_seconds(value, "state.locked_heavy_departures_s")
            for value in state.locked_heavy_departures_s
        ]
        locked_empty_departures_s = [
            _validated_whole_seconds(value, "state.locked_empty_departures_s")
            for value in state.locked_empty_departures_s
        ]
        locked_empty_storage_hold_s = (
            None
            if state.locked_empty_storage_hold_s is None
            else _validated_whole_seconds(
                state.locked_empty_storage_hold_s,
                "state.locked_empty_storage_hold_s",
            )
        )
        locked_storage_preset_id = str(state.locked_storage_preset_id or "").strip()
        rolling_storage_soc_kwh = state.storage_soc_kwh
        rolling_storage_device_states = state.storage_device_states
        rolling_contexts: Dict[str, StorageEvalContext] = {}

        def context_for_state(template: ScheduleTemplate) -> StorageEvalContext:
            """返回使用当前窗口 SOC 的评价上下文，且不修改优化器共享配置。"""

            base_context = self._context_for(template)
            if (
                not rolling_storage_device_states
                and rolling_storage_soc_kwh is None
                and not state.dynamic_power_arm_limits
            ):
                return base_context
            cache_key = base_context.preset_id
            if cache_key not in rolling_contexts:
                if rolling_storage_device_states:
                    rolling_system = base_context.settlement_system.with_storage_runtime_states(
                        rolling_storage_device_states
                    )
                elif rolling_storage_soc_kwh is not None:
                    rolling_system = base_context.settlement_system.with_initial_soc(
                        rolling_storage_soc_kwh
                    )
                else:
                    rolling_system = base_context.settlement_system
                if state.dynamic_power_arm_limits:
                    rolling_system = rolling_system.with_dynamic_power_arm_limits(
                        state.dynamic_power_arm_limits
                    )
                rolling_contexts[cache_key] = replace(
                    base_context,
                    settlement_system=rolling_system,
                )
            return rolling_contexts[cache_key]

        # 旧调用方可能只提供已锁定发车时刻而没有两个策略字段；此时传入的基础模板是已提交计划的依据。
        # 若状态中存在显式值，则显式值优先。
        committed_hold_s = locked_empty_storage_hold_s
        if committed_hold_s is None and locked_empty_departures_s:
            committed_hold_s = _validated_whole_seconds(
                base_template.flex_zone_hold_s,
                "base_template.flex_zone_hold_s",
            )
        committed_storage_preset_id: str | None = None
        if locked_heavy_departures_s or locked_empty_departures_s:
            committed_storage_preset_id = (
                locked_storage_preset_id
                or str(getattr(base_template, "storage_preset_id", "") or "").strip()
                or self.default_storage_preset_id
            )
            if committed_storage_preset_id not in self.storage_contexts:
                raise ValueError(
                    "The committed storage preset is not available in this optimizer: "
                    f"{committed_storage_preset_id!r}"
                )

        def preserve_committed_policy(template: ScheduleTemplate) -> ScheduleTemplate:
            """函数 preserve_committed_policy：执行该模块中的相关处理逻辑。"""
            changes = {}
            if committed_hold_s is not None:
                changes["flex_zone_hold_s"] = committed_hold_s
            if committed_storage_preset_id is not None:
                changes["storage_preset_id"] = committed_storage_preset_id
            return replace(template, **changes) if changes else template

        # 滚动状态是规划窗口起点的权威来源。生成种子和限幅前先规范化模板，
        # 使储能偏移相对于后续 schedule_for_template() 使用的同一时刻进行限制。
        window_base_template = preserve_committed_policy(
            clamp_template(
                replace(base_template, start_time_s=current_time_s), search_config
            )
        )
        window_base_template = rolling_future_template(window_base_template, current_time_s, reject_past=True)
        horizon_s = _validated_whole_seconds(horizon_s, "horizon_s", positive=True)
        execute_window_s = _validated_whole_seconds(
            execute_window_s, "execute_window_s", positive=True
        )
        if execute_window_s > horizon_s:
            raise ValueError(
                "execute_window_s must not exceed horizon_s; "
                f"got execute_window_s={execute_window_s}, horizon_s={horizon_s}"
            )
        if min_depart_gap_s is None:
            min_depart_gap_s = (
                self.resource_model.config.min_depart_headway_s
                if self.resource_model is not None
                else search_config.min_headway_s
            )
        min_depart_gap_s = _validated_whole_seconds(min_depart_gap_s, "min_depart_gap_s")
        if target_gap_s is None:
            target_gap_s = int(
                round(
                    (
                        window_base_template.heavy_headway_s
                        + window_base_template.empty_headway_s
                    )
                    / 2.0
                )
            )
        target_gap_s = _validated_whole_seconds(target_gap_s, "target_gap_s")
        def schedule_for_template(template: ScheduleTemplate) -> GeneratedSchedule:
            """函数 schedule_for_template：执行该模块中的相关处理逻辑。"""
            window_template = rolling_future_template(preserve_committed_policy(
                replace(template, start_time_s=current_time_s)
            ), current_time_s)
            candidate = generate_schedule(window_template)
            combined = GeneratedSchedule(
                heavy_departures_s=sorted(
                    set(locked_heavy_departures_s)
                    | {t for t in candidate.heavy_departures_s if t <= current_time_s + horizon_s}
                ),
                empty_departures_s=sorted(
                    set(locked_empty_departures_s)
                    | {t for t in candidate.empty_departures_s if t <= current_time_s + horizon_s}
                ),
                template=window_template,
            )
            combined = apply_dynamic_train_services(
                combined,
                state.cancelled_train_ids,
                state.added_trains,
                current_time_s=current_time_s,
                locked_heavy_departures_s=locked_heavy_departures_s,
                locked_empty_departures_s=locked_empty_departures_s,
            )
            return apply_train_delay_observations(
                combined,
                observed_train_delays_s,
                current_time_s=current_time_s,
                locked_heavy_departures_s=locked_heavy_departures_s,
                locked_empty_departures_s=locked_empty_departures_s,
            )

        # 基础模板定义该预测窗口内已提交的服务数量。改变追踪间隔或相位可能把请求服务推到 ``horizon_s`` 之外；
        # 若把截断候选当作完整计划评价，就会给未服务列车虚假的能量和成本收益。
        raw_population_template = replace(
            base_template,
            start_time_s=current_time_s,
        )
        # 过期的负储能偏移不能在常规模板限幅修复前导致数量检查失败；该偏移不影响服务数量。
        raw_population_shift = _validated_whole_number(
            raw_population_template.storage_align_shift_s,
            "base_template.storage_align_shift_s",
        )
        raw_population_phase = _validated_whole_seconds(
            raw_population_template.heavy_empty_phase_s,
            "base_template.heavy_empty_phase_s",
        )
        raw_population_template = replace(
            raw_population_template,
            storage_align_shift_s=max(
                -(
                    current_time_s
                    + raw_population_phase
                ),
                raw_population_shift,
            ),
        )
        raw_population_template = rolling_future_template(raw_population_template, current_time_s, reject_past=True)
        required_window_schedule = schedule_for_template(raw_population_template)
        required_heavy_count = len(required_window_schedule.heavy_departures_s)
        required_empty_count = len(required_window_schedule.empty_departures_s)
        evaluation_cache: Dict[TemplateKey, ScheduleScore] = {}
        scenario_score_cache: Dict[TemplateKey, Tuple[ScenarioScore, ...]] = {}
        evaluation_cache_hits = 0
        evaluation_cache_misses = 0
        feasibility_repair_diagnostics: Dict = {
            "triggered": False,
            "evaluated_template_count": 0,
            "resource_feasible_seed_count": 0,
            "full_robust_evaluated_seed_count": 0,
            "full_robust_feasible_seed_count": 0,
            "note": "Regular search already produced a core-robust-feasible candidate.",
        }

        def enforce_window_service_population(
            candidate: GeneratedSchedule,
            score: ScheduleScore,
        ) -> ScheduleScore:
            """函数 enforce_window_service_population：执行该模块中的相关处理逻辑。"""
            service_count_violation = (
                abs(len(candidate.heavy_departures_s) - required_heavy_count)
                + abs(len(candidate.empty_departures_s) - required_empty_count)
            )
            service_count_violation += sum(t < current_time_s and t not in locked_heavy_departures_s
                                           for t in candidate.heavy_departures_s)
            service_count_violation += sum(t < current_time_s and t not in locked_empty_departures_s
                                           for t in candidate.empty_departures_s)
            service_count_violation += len(set(locked_heavy_departures_s) - set(candidate.heavy_departures_s))
            service_count_violation += len(set(locked_empty_departures_s) - set(candidate.empty_departures_s))
            if service_count_violation <= 0:
                return score
            return replace(
                score,
                feasible=False,
                constraint_violation=(
                    score.constraint_violation + float(service_count_violation)
                ),
            )

        def evaluate_template(template: ScheduleTemplate) -> ScheduleScore:
            """函数 evaluate_template：执行该模块中的相关处理逻辑。"""
            nonlocal evaluation_cache_hits, evaluation_cache_misses
            candidate = schedule_for_template(template)
            key = template_key(candidate.template)
            cached = evaluation_cache.get(key)
            if cached is not None:
                evaluation_cache_hits += 1
                return cached
            evaluation_cache_misses += 1
            context = context_for_state(candidate.template)
            scenario_scores: List[ScenarioScore] = []
            score = robust_evaluate_schedule(
                candidate,
                scenarios,
                context.heavy_cache,
                context.empty_cache,
                context.settlement_system,
                context.route.signaling_system,
                resource_model=self.resource_model,
                storage_sections=context.storage_sections,
                min_depart_gap_s=min_depart_gap_s,
                target_gap_s=target_gap_s,
                objective_mode=objective_mode,
                energy_scenario=energy_scenario,
                objective_priority=objective_priority,
                disturbance_from_time_s=current_time_s,
                locked_heavy_departures_s=locked_heavy_departures_s,
                locked_empty_departures_s=locked_empty_departures_s,
                scenario_score_sink=scenario_scores,
                energy_from_time_s=current_time_s,
            )
            score = enforce_window_service_population(candidate, score)
            evaluation_cache[key] = score
            scenario_score_cache[key] = tuple(scenario_scores)
            return score
        if search_config.method == "grid":
            ranked_templates = batch_evaluate_templates(
                [
                    clamp_template(template, search_config)
                    for template in candidate_templates(window_base_template)
                ],
                evaluate_template,
                max_workers=max(1, search_config.parallel_workers),
            )
            ranked_templates.sort(key=lambda item: candidate_selection_key(item[1]))
        elif search_config.method == "evolutionary":
            ranked_templates = evolutionary_template_search(
                window_base_template, search_config, evaluate_template
            )
        else:
            ranked_templates = nsga2_template_search(
                window_base_template, search_config, evaluate_template
            )
        # 确保可落地的储能预设都在稳健运行图候选上得到评价。
        forced_templates = landable_storage_force_templates(
            window_base_template, search_config
        )
        if forced_templates:
            seen = {template_key(template) for template, _score in ranked_templates}
            missing = [template for template in forced_templates if template_key(template) not in seen]
            if missing:
                ranked_templates.extend(
                    batch_evaluate_templates(
                        missing,
                        evaluate_template,
                        max_workers=max(1, search_config.parallel_workers),
                    )
                )
            ranked_templates.sort(key=lambda item: candidate_selection_key(item[1]))

        # 常规搜索和既有种子均失败时，先用较便宜的资源检查细扫窄相位窗口，
        # 再只对少量资源可行种子执行完整五场景能量与电气评价。
        if (
            self.resource_model is not None
            and not any(score.feasible for _template, score in ranked_templates)
        ):
            repair_context = context_for_state(window_base_template)
            repair_templates, feasibility_repair_diagnostics = (
                resource_feasibility_repair_templates(
                    window_base_template,
                    search_config,
                    scenarios,
                    self.resource_model,
                    repair_context.heavy_cache,
                    repair_context.empty_cache,
                    schedule_for_template,
                    required_heavy_count=required_heavy_count,
                    required_empty_count=required_empty_count,
                    disturbance_from_time_s=current_time_s,
                    locked_heavy_departures_s=locked_heavy_departures_s,
                    locked_empty_departures_s=locked_empty_departures_s,
                    exact_horizon_s=horizon_s,
                )
            )
            robust_evaluated_seed_count = 0
            robust_feasible_seed_count = 0
            for repair_template in repair_templates:
                preset_ids = (
                    tuple(search_config.storage_preset_ids)
                    if search_config.enable_storage_preset_search
                    and search_config.storage_preset_ids
                    else (repair_template.storage_preset_id,)
                )
                for preset_id in preset_ids:
                    repair_variant = replace(
                        repair_template,
                        storage_preset_id=str(preset_id or ""),
                    )
                    repair_score = evaluate_template(repair_variant)
                    robust_evaluated_seed_count += 1
                    ranked_templates.append((repair_variant, repair_score))
                    if repair_score.feasible:
                        robust_feasible_seed_count += 1
            feasibility_repair_diagnostics["full_robust_evaluated_seed_count"] = (
                robust_evaluated_seed_count
            )
            feasibility_repair_diagnostics["full_robust_feasible_seed_count"] = (
                robust_feasible_seed_count
            )
            ranked_templates.sort(key=lambda item: candidate_selection_key(item[1]))

        # 搜索算子仍可能为已提交的基因生成替代值。其评分使用上面保留的策略；
        # 因此也要规范化配对模板，避免导出候选和选中运行图声称使用不同于实际评价的停车或储能预设。
        canonical_ranked: Dict[TemplateKey, Tuple[ScheduleTemplate, ScheduleScore]] = {}
        for template, score in ranked_templates:
            canonical = preserve_committed_policy(
                replace(template, start_time_s=current_time_s)
            )
            key = template_key(canonical)
            previous = canonical_ranked.get(key)
            if previous is None or candidate_selection_key(score) < candidate_selection_key(previous[1]):
                canonical_ranked[key] = (canonical, score)
        ranked_templates = list(canonical_ranked.values())
        ranked_templates.sort(key=lambda item: candidate_selection_key(item[1]))

        # 联合储能规划在粗搜索后增加一轮小邻域能量精修。只改变相位、储能对齐
        # 和储能区停留，不改变列车数量或储能预设，避免把联合模式变成无界搜索。
        energy_refinement_before_count = len(ranked_templates)
        if energy_scenario != ENERGY_SCENARIO_DIRECT_NO_STORAGE and ranked_templates:
            feasible_ranked = [item for item in ranked_templates if item[1].feasible] or ranked_templates
            energy_seed = min(
                feasible_ranked,
                key=lambda item: (energy_scenario_objective(item[1]), candidate_selection_key(item[1])),
            )[0]
            local_step_s = 60
            local_templates = []
            for phase_delta, storage_delta, hold_delta in (
                (0, 0, 0),
                (-local_step_s, 0, 0),
                (local_step_s, 0, 0),
                (0, -local_step_s, 0),
                (0, local_step_s, 0),
                (0, 0, -local_step_s),
                (0, 0, local_step_s),
            ):
                local_templates.append(
                    preserve_committed_policy(
                        replace(
                            clamp_template(
                                replace(
                                    energy_seed,
                                    heavy_empty_phase_s=energy_seed.heavy_empty_phase_s + phase_delta,
                                    storage_align_shift_s=energy_seed.storage_align_shift_s + storage_delta,
                                    flex_zone_hold_s=energy_seed.flex_zone_hold_s + hold_delta,
                                ),
                                search_config,
                            ),
                            start_time_s=current_time_s,
                        )
                    )
                )
            local_templates = unique_templates(local_templates)
            local_missing = [
                template
                for template in local_templates
                if template_key(template) not in canonical_ranked
            ]
            if local_missing:
                for template, score in batch_evaluate_templates(
                    local_missing,
                    evaluate_template,
                    max_workers=max(1, search_config.parallel_workers),
                ):
                    canonical = preserve_committed_policy(
                        replace(template, start_time_s=current_time_s)
                    )
                    key = template_key(canonical)
                    previous = canonical_ranked.get(key)
                    if previous is None or candidate_selection_key(score) < candidate_selection_key(previous[1]):
                        canonical_ranked[key] = (canonical, score)
                ranked_templates = list(canonical_ranked.values())
                ranked_templates.sort(key=lambda item: candidate_selection_key(item[1]))
        energy_refinement_diagnostics = {
            "enabled": energy_scenario != ENERGY_SCENARIO_DIRECT_NO_STORAGE,
            "step_s": 60,
            "evaluated_neighbor_count": max(0, len(ranked_templates) - energy_refinement_before_count),
        }
        candidate_count = len(ranked_templates)
        feasible_candidate_count = sum(1 for _template, score in ranked_templates if score.feasible)
        pareto_candidates = pareto_template_front(ranked_templates)
        if feasible_candidate_count:
            selectable_templates = [(template, score) for template, score in ranked_templates if score.feasible]
            diagnostic = ""
        else:
            fallback_templates = list(ranked_templates)
            if all(
                template_key(template) != template_key(window_base_template)
                for template, _score in fallback_templates
            ):
                fallback_templates.append(
                    (window_base_template, evaluate_template(window_base_template))
                )
            nominal_scores = {}
            for template, _score in fallback_templates:
                context = context_for_state(template)
                nominal_candidate = schedule_for_template(template)
                nominal_scores[template_key(template)] = enforce_window_service_population(
                    nominal_candidate,
                    evaluate_schedule(
                    nominal_candidate,
                    context.heavy_cache,
                    context.empty_cache,
                    context.settlement_system,
                    context.route.signaling_system,
                    resource_model=self.resource_model,
                    storage_sections=context.storage_sections,
                    min_depart_gap_s=min_depart_gap_s,
                    target_gap_s=target_gap_s,
                    objective_mode=objective_mode,
                    energy_scenario=energy_scenario,
                        objective_priority=objective_priority,
                        energy_from_time_s=current_time_s,
                    ),
                )
            selectable_templates = sorted(
                (
                    (template, nominal_scores[template_key(template)])
                    for template, _robust_score in fallback_templates
                ),
                key=lambda item: candidate_selection_key(item[1]),
            )[:1]
            diagnostic = (
                "No robust-feasible optimization candidate was found in the search window; "
                "returning the best nominal-feasible candidate when available, otherwise the least-violating candidate."
            )
        # 搜索结束后，在稳健可行候选中优先选择能量目标更优者。
        selectable_templates = sorted(selectable_templates, key=lambda item: candidate_selection_key(item[1]))
        ranked_templates = sorted(ranked_templates, key=lambda item: candidate_selection_key(item[1]))
        for template, score in selectable_templates:
            better = False
            if best_score is None:
                better = True
            else:
                # 排序顺序为稳健可行性、弃电/电网购电量，最后是成本。
                better = candidate_selection_key(score) < candidate_selection_key(best_score)
            if better:
                best_score = score
                best_schedule = schedule_for_template(template)
        if best_schedule is None or best_score is None:
            raise RuntimeError("No rolling optimization candidate was generated.")
        recovery_repair_diagnostics: Dict = {
            "triggered": False,
            "adopted": False,
            "status": "not_applicable" if enable_recovery else "disabled",
            "note": (
                "常规搜索已经得到核心稳健可行解，或当前未配置资源模型。"
                if enable_recovery
                else "恢复级联已由调用方关闭，仅保留常规搜索结果。"
            ),
        }
        exact_recovery_diagnostics: Dict = {
            "triggered": False,
            "adopted": False,
            "status": "not_applicable" if enable_recovery else "disabled",
            "note": (
                "局部恢复未触发，或局部恢复已经解决资源可行性问题。"
                if enable_recovery
                else "恢复级联已由调用方关闭，精确恢复不参与本轮。"
            ),
        }
        selected_override_scenario_scores: Tuple[ScenarioScore, ...] | None = None
        # 常规搜索失败后，直接在合并运行图上按 H/E 列车编号执行局部恢复。
        # 这一步只允许移动第一阶段识别出的冲突相关未来列车，已提交历史保持不变。
        if (
            enable_recovery
            and self.resource_model is not None
            and feasible_candidate_count == 0
        ):
            from recovery_conflict_analysis import extract_recovery_conflict_analysis
            from recovery_repair import (
                repair_recovery_schedule,
                solve_exact_recovery_schedule,
            )

            recovery_base_schedule = best_schedule
            selected_context = context_for_state(best_schedule.template)
            recovery_analysis = extract_recovery_conflict_analysis(
                best_schedule,
                scenarios,
                self.resource_model,
                selected_context.heavy_cache,
                selected_context.empty_cache,
                current_time_s=current_time_s,
                locked_heavy_departures_s=locked_heavy_departures_s,
                locked_empty_departures_s=locked_empty_departures_s,
            )
            recovery_result = repair_recovery_schedule(
                best_schedule,
                recovery_analysis,
                scenarios,
                self.resource_model,
                selected_context.heavy_cache,
                selected_context.empty_cache,
                current_time_s=current_time_s,
                locked_heavy_departures_s=locked_heavy_departures_s,
                locked_empty_departures_s=locked_empty_departures_s,
                min_depart_gap_s=min_depart_gap_s,
            )
            recovery_repair_diagnostics = recovery_result.to_dict()
            recovery_repair_diagnostics["triggered"] = True
            recovery_repair_diagnostics["adopted"] = False
            baseline_robust_score = evaluation_cache.get(
                template_key(recovery_base_schedule.template)
            )
            if baseline_robust_score is None:
                baseline_robust_score = evaluate_template(
                    recovery_base_schedule.template
                )
            comparison_robust_score = baseline_robust_score
            if recovery_result.decisions and recovery_result.locked_departures_preserved:
                repaired_scenario_scores: List[ScenarioScore] = []
                repaired_score = robust_evaluate_schedule(
                    recovery_result.schedule,
                    scenarios,
                    selected_context.heavy_cache,
                    selected_context.empty_cache,
                    selected_context.settlement_system,
                    selected_context.route.signaling_system,
                    resource_model=self.resource_model,
                    storage_sections=selected_context.storage_sections,
                    min_depart_gap_s=min_depart_gap_s,
                    target_gap_s=target_gap_s,
                    objective_mode=objective_mode,
                    energy_scenario=energy_scenario,
                    objective_priority=objective_priority,
                    disturbance_from_time_s=current_time_s,
                    locked_heavy_departures_s=locked_heavy_departures_s,
                    locked_empty_departures_s=locked_empty_departures_s,
                    scenario_score_sink=repaired_scenario_scores,
                    energy_from_time_s=current_time_s,
                )
                repaired_score = enforce_window_service_population(
                    recovery_result.schedule, repaired_score
                )
                recovery_repair_diagnostics["baseline_constraint_violation"] = (
                    baseline_robust_score.constraint_violation
                )
                recovery_repair_diagnostics["repaired_constraint_violation"] = (
                    repaired_score.constraint_violation
                )
                recovery_repair_diagnostics["repaired_robust_feasible"] = (
                    repaired_score.feasible
                )
                if candidate_selection_key(repaired_score) < candidate_selection_key(
                    baseline_robust_score
                ):
                    best_schedule = recovery_result.schedule
                    best_score = repaired_score
                    comparison_robust_score = repaired_score
                    selected_override_scenario_scores = tuple(repaired_scenario_scores)
                    recovery_repair_diagnostics["adopted"] = True
                    diagnostic = (
                        "常规搜索未找到核心稳健可行解；已采用仅调整冲突相关未来列车的局部恢复结果。"
                        if repaired_score.feasible
                        else "常规搜索未找到核心稳健可行解；局部恢复降低了约束违反量，"
                        "但锁定历史仍需运营干预。"
                    )
            # 第三阶段：局部资源修复仍未完成时，以完整合并运行图和锁定历史调用精确MILP。
            # 精确候选仍须通过全场景能量、电气、信号、资源和SOC评价后才能采用。
            if not recovery_result.robust_resource_feasible:
                exact_recovery = solve_exact_recovery_schedule(
                    recovery_base_schedule,
                    recovery_analysis,
                    scenarios,
                    self.resource_model,
                    selected_context.heavy_cache,
                    selected_context.empty_cache,
                    current_time_s=current_time_s,
                    horizon_end_s=max(
                        current_time_s + horizon_s,
                        *recovery_base_schedule.heavy_departures_s,
                        *recovery_base_schedule.empty_departures_s,
                    ),
                    locked_heavy_departures_s=locked_heavy_departures_s,
                    locked_empty_departures_s=locked_empty_departures_s,
                    min_depart_gap_s=min_depart_gap_s,
                )
                exact_recovery_diagnostics = exact_recovery.to_dict()
                exact_recovery_diagnostics["adopted"] = False
                if (
                    exact_recovery.schedule is not None
                    and exact_recovery.exact_resource_feasible
                    and exact_recovery.locked_departures_preserved
                ):
                    exact_context = context_for_state(exact_recovery.schedule.template)
                    exact_scenario_scores: List[ScenarioScore] = []
                    exact_score = robust_evaluate_schedule(
                        exact_recovery.schedule,
                        scenarios,
                        exact_context.heavy_cache,
                        exact_context.empty_cache,
                        exact_context.settlement_system,
                        exact_context.route.signaling_system,
                        resource_model=self.resource_model,
                        storage_sections=exact_context.storage_sections,
                        min_depart_gap_s=min_depart_gap_s,
                        target_gap_s=target_gap_s,
                        objective_mode=objective_mode,
                        energy_scenario=energy_scenario,
                        objective_priority=objective_priority,
                        disturbance_from_time_s=current_time_s,
                        locked_heavy_departures_s=locked_heavy_departures_s,
                        locked_empty_departures_s=locked_empty_departures_s,
                        scenario_score_sink=exact_scenario_scores,
                        energy_from_time_s=current_time_s,
                    )
                    exact_score = enforce_window_service_population(
                        exact_recovery.schedule, exact_score
                    )
                    exact_recovery_diagnostics["full_robust_feasible"] = (
                        exact_score.feasible
                    )
                    exact_recovery_diagnostics["full_constraint_violation"] = (
                        exact_score.constraint_violation
                    )
                    if (
                        exact_score.feasible
                        and candidate_selection_key(exact_score) < candidate_selection_key(
                            comparison_robust_score
                        )
                    ):
                        best_schedule = exact_recovery.schedule
                        best_score = exact_score
                        selected_override_scenario_scores = tuple(exact_scenario_scores)
                        exact_recovery_diagnostics["adopted"] = True
                        diagnostic = "局部恢复未找到核心稳健资源可行解；精确资源求解器已找到并通过完整稳健评价。"
        execution_scenario = next(
            (scenario for scenario in scenarios if scenario.name == "normal"),
            next(scenario for scenario in scenarios if scenario.core_for_feasibility),
        )
        execution_schedule = apply_scenario(
            best_schedule,
            execution_scenario,
            disturbance_from_time_s=current_time_s,
            locked_heavy_departures_s=locked_heavy_departures_s,
            locked_empty_departures_s=locked_empty_departures_s,
        )
        selected_context = context_for_state(best_schedule.template)
        selected_key = template_key(best_schedule.template)
        cached_selected_scenarios = (
            selected_override_scenario_scores
            if selected_override_scenario_scores is not None
            else scenario_score_cache.get(selected_key)
        )
        if cached_selected_scenarios is None:
            selected_scenario_diagnostics = tuple(
                explain_robust_scenarios(
                best_schedule,
                scenarios,
                selected_context.heavy_cache,
                selected_context.empty_cache,
                selected_context.settlement_system,
                selected_context.route.signaling_system,
                resource_model=self.resource_model,
                storage_sections=selected_context.storage_sections,
                min_depart_gap_s=min_depart_gap_s,
                target_gap_s=target_gap_s,
                objective_mode=objective_mode,
                energy_scenario=energy_scenario,
                objective_priority=objective_priority,
                disturbance_from_time_s=current_time_s,
                locked_heavy_departures_s=locked_heavy_departures_s,
                locked_empty_departures_s=locked_empty_departures_s,
                energy_from_time_s=current_time_s,
                )
            )
        else:
            selected_scenario_diagnostics = tuple(
                scenario_diagnostic_rows(
                    best_schedule,
                    cached_selected_scenarios,
                    selected_context.heavy_cache,
                    selected_context.empty_cache,
                    resource_model=self.resource_model,
                    disturbance_from_time_s=current_time_s,
                    locked_heavy_departures_s=locked_heavy_departures_s,
                    locked_empty_departures_s=locked_empty_departures_s,
                )
            )
        commit_decision = gate_rolling_execution_commit(
            execution_schedule,
            selected_scenario_diagnostics,
            current_time_s=current_time_s,
            execute_window_s=execute_window_s,
            locked_heavy_departures_s=locked_heavy_departures_s,
            locked_empty_departures_s=locked_empty_departures_s,
            candidate_feasible=best_score.feasible,
            allow_infeasible_commit_for_experiment=(
                allow_infeasible_commit_for_experiment
            ),
        )
        search_diagnostics = build_search_diagnostics(ranked_templates, search_config)
        search_diagnostics["energy_local_refinement"] = energy_refinement_diagnostics
        search_diagnostics["candidate_evaluation_cache"] = {
            "requests": evaluation_cache_hits + evaluation_cache_misses,
            "actual_robust_evaluations": evaluation_cache_misses,
            "cache_hits": evaluation_cache_hits,
            "unique_cached_templates": len(evaluation_cache),
        }
        search_diagnostics["feasibility_repair"] = feasibility_repair_diagnostics
        search_diagnostics["recovery_repair"] = recovery_repair_diagnostics
        search_diagnostics["exact_recovery"] = exact_recovery_diagnostics
        search_diagnostics["recovery_policy"] = {
            "enabled": enable_recovery,
            "scope": "local_and_exact_post_search_recovery",
        }
        search_diagnostics["window_service_population"] = {
            "required_heavy_count": required_heavy_count,
            "required_empty_count": required_empty_count,
            "selected_heavy_count": len(best_schedule.heavy_departures_s),
            "selected_empty_count": len(best_schedule.empty_departures_s),
            "constraint": "candidate service population must match the base template within the prediction window",
        }
        search_diagnostics["rolling_energy_state"] = {
            "energy_from_time_s": current_time_s,
            "storage_soc_kwh": rolling_storage_soc_kwh,
            "storage_device_states": [
                {
                    "storage_section_id": item.storage_section_id,
                    "soc_kwh": item.soc_kwh,
                    "available": item.available,
                    "max_charge_power_kw": item.max_charge_power_kw,
                    "max_discharge_power_kw": item.max_discharge_power_kw,
                }
                for item in rolling_storage_device_states
            ],
            "state_mode": (
                "per_device"
                if rolling_storage_device_states
                else "aggregate_legacy"
                if rolling_storage_soc_kwh is not None
                else "static_configuration"
            ),
            "uses_dynamic_soc": bool(rolling_storage_device_states) or rolling_storage_soc_kwh is not None,
        }
        search_diagnostics["execution_state"] = {
            "scenario": execution_scenario.name,
            "observed_heavy_delay_s": execution_scenario.heavy_delay_s,
            "observed_empty_delay_s": execution_scenario.empty_delay_s,
            "observed_train_delays_s": dict(observed_train_delays_s),
            "cancelled_train_ids": list(state.cancelled_train_ids),
            "added_train_ids": [item.train_id for item in state.added_trains],
            "resource_unavailability_ids": [item.event_id for item in state.resource_unavailabilities],
            "dynamic_power_limit_ids": [item.event_id for item in state.dynamic_power_arm_limits],
            "planned_heavy_departures_s": list(best_schedule.heavy_departures_s),
            "planned_empty_departures_s": list(best_schedule.empty_departures_s),
            "planned_heavy_train_ids": list(best_schedule.heavy_train_ids),
            "planned_empty_train_ids": list(best_schedule.empty_train_ids),
            "realized_heavy_departures_s": list(execution_schedule.heavy_departures_s),
            "realized_empty_departures_s": list(execution_schedule.empty_departures_s),
        }
        search_diagnostics["commit_gate"] = {
            "status": commit_decision.commit_status,
            "core_robust_feasible": commit_decision.core_robust_feasible,
            "operational_intervention_required": (
                commit_decision.operational_intervention_required
            ),
            "allow_infeasible_commit_for_experiment": (
                allow_infeasible_commit_for_experiment
            ),
            "committed_heavy_departures_s": list(
                commit_decision.committed_execution_schedule.heavy_departures_s
            ),
            "committed_empty_departures_s": list(
                commit_decision.committed_execution_schedule.empty_departures_s
            ),
            "reason": commit_decision.reason,
        }
        return RollingOptimizationResult(
            schedule=best_schedule,
            execution_schedule=execution_schedule,
            committed_execution_schedule=(
                commit_decision.committed_execution_schedule
            ),
            score=best_score,
            executable_heavy_departures_s=(
                commit_decision.executable_heavy_departures_s
            ),
            executable_empty_departures_s=(
                commit_decision.executable_empty_departures_s
            ),
            core_robust_feasible=commit_decision.core_robust_feasible,
            commit_status=commit_decision.commit_status,
            operational_intervention_required=(
                commit_decision.operational_intervention_required
            ),
            ranked_candidates=tuple(ranked_templates),
            pareto_candidates=tuple(pareto_candidates),
            candidate_count=candidate_count,
            feasible_candidate_count=feasible_candidate_count,
            diagnostic=diagnostic,
            search_diagnostics=search_diagnostics,
            selected_scenario_diagnostics=selected_scenario_diagnostics,
            candidate_scenario_scores={
                template_key(template): scenario_score_cache[template_key(template)]
                for template, _score in ranked_templates
                if template_key(template) in scenario_score_cache
            },
        )


class RollingSafetyController:
    """协调提交门禁后的有限重试、等待新观测和人工升级。"""

    def __init__(self, policy: RollingSafetyPolicy | None = None) -> None:
        self.policy = policy or RollingSafetyPolicy()
        self._result_cache: Dict[str, RollingOptimizationResult] = {}
        self._consecutive_withheld = 0
        self._last_observation_fingerprint = ""

    def _annotate(
        self,
        result: RollingOptimizationResult,
        *,
        state_name: str,
        action: str,
        attempts: List[Dict],
        observation_changed: bool,
        request_fingerprint: str,
    ) -> RollingOptimizationResult:
        """把状态迁移和被扣留对象写入结果，供数据库与界面直接消费。"""

        candidate_heavy = set(result.execution_schedule.heavy_departures_s)
        candidate_empty = set(result.execution_schedule.empty_departures_s)
        committed_heavy = set(result.committed_execution_schedule.heavy_departures_s)
        committed_empty = set(result.committed_execution_schedule.empty_departures_s)
        failed_scenarios = [
            {"attempt_index": attempt["attempt_index"], **row}
            for attempt in attempts
            for row in attempt.get("failed_core_scenarios", [])
        ]
        transition = {
            "state": state_name,
            "action": action,
            "attempt_count": len(attempts),
            "consecutive_withheld_cycles": self._consecutive_withheld,
            "observation_changed": observation_changed,
            "request_fingerprint": request_fingerprint,
            "withheld_heavy_departures_s": sorted(candidate_heavy - committed_heavy),
            "withheld_empty_departures_s": sorted(candidate_empty - committed_empty),
            "failed_core_scenarios": failed_scenarios,
            "attempts": attempts,
        }
        diagnostics = dict(result.search_diagnostics)
        diagnostics["safety_state_machine"] = transition
        return replace(
            result,
            safety_state=state_name,
            safety_action=action,
            safety_attempt_count=len(attempts),
            safety_transition_history=(transition,),
            operational_intervention_required=(
                result.operational_intervention_required
                or state_name == "manual_intervention_required"
            ),
            search_diagnostics=diagnostics,
        )

    def optimize_cycle(
        self,
        optimizer: RollingOptimizer,
        state: RollingWindowState,
        base_template: ScheduleTemplate,
        *,
        horizon_s: int,
        execute_window_s: int,
        search_config: TemplateSearchConfig | None,
        enable_recovery: bool,
        allow_infeasible_commit_for_experiment: bool,
    ) -> RollingOptimizationResult:
        """执行一次受控求解；完全相同的请求直接复用已完成结果。"""

        request_fingerprint = _rolling_request_fingerprint(
            state,
            base_template,
            horizon_s=horizon_s,
            execute_window_s=execute_window_s,
            search_config=search_config,
            enable_recovery=enable_recovery,
            allow_infeasible_commit_for_experiment=(
                allow_infeasible_commit_for_experiment
            ),
        )
        cached = self._result_cache.get(request_fingerprint)
        if cached is not None:
            return cached

        observation_fingerprint = _rolling_observation_fingerprint(state)
        observation_changed = bool(self._last_observation_fingerprint) and (
            observation_fingerprint != self._last_observation_fingerprint
        )
        attempts: List[Dict] = []

        def run_attempt(
            attempt_index: int,
            attempt_horizon_s: int,
            attempt_config: TemplateSearchConfig | None,
            attempt_recovery: bool,
        ) -> RollingOptimizationResult:
            result = optimizer.optimize_once(
                state,
                base_template,
                horizon_s=attempt_horizon_s,
                execute_window_s=execute_window_s,
                search_config=attempt_config,
                enable_recovery=attempt_recovery,
                allow_infeasible_commit_for_experiment=(
                    allow_infeasible_commit_for_experiment
                ),
            )
            attempts.append(
                {
                    "attempt_index": attempt_index,
                    "horizon_s": attempt_horizon_s,
                    "population_size": (
                        attempt_config.population_size if attempt_config else None
                    ),
                    "generations": (
                        attempt_config.generations if attempt_config else None
                    ),
                    "recovery_enabled": attempt_recovery,
                    "commit_status": getattr(
                        result, "commit_status", "committed_robust_feasible"
                    ),
                    "core_robust_feasible": bool(
                        getattr(result, "core_robust_feasible", True)
                    ),
                    "withheld_heavy_departures_s": sorted(
                        set(getattr(result.execution_schedule, "heavy_departures_s", []))
                        - set(
                            getattr(
                                result.committed_execution_schedule,
                                "heavy_departures_s",
                                [],
                            )
                        )
                    ) if isinstance(result, RollingOptimizationResult) else [],
                    "withheld_empty_departures_s": sorted(
                        set(getattr(result.execution_schedule, "empty_departures_s", []))
                        - set(
                            getattr(
                                result.committed_execution_schedule,
                                "empty_departures_s",
                                [],
                            )
                        )
                    ) if isinstance(result, RollingOptimizationResult) else [],
                    "failed_core_scenarios": [
                        {
                            "scenario": row.get("scenario"),
                            "constraint_violation": row.get("constraint_violation"),
                            "resource_conflict_count": row.get("resource_conflict_count"),
                            "resource_overlap_violation_s": row.get(
                                "resource_overlap_violation_s"
                            ),
                            "conflict_summary": row.get("conflict_summary", ""),
                        }
                        for row in getattr(
                            result, "selected_scenario_diagnostics", ()
                        )
                        if bool(row.get("core_for_feasibility"))
                        and not bool(row.get("feasible"))
                    ],
                }
            )
            return result

        result = run_attempt(0, horizon_s, search_config, enable_recovery)
        if (
            getattr(result, "commit_status", "committed_robust_feasible")
            == "withheld_infeasible"
            and self.policy.enable_automatic_retry
        ):
            for retry_index in range(1, self.policy.max_retries_per_cycle + 1):
                retry_horizon_s = min(
                    self.policy.max_horizon_s,
                    max(
                        horizon_s,
                        int(math.ceil(horizon_s * self.policy.retry_horizon_multiplier ** retry_index)),
                    ),
                )
                retry_config = _expanded_retry_config(
                    search_config, self.policy, retry_index
                )
                result = run_attempt(
                    retry_index,
                    retry_horizon_s,
                    retry_config,
                    enable_recovery or self.policy.escalate_recovery_on_retry,
                )
                if result.commit_status != "withheld_infeasible":
                    break

        # 部分轻量测试替身只实现历史接口；生产优化器始终返回完整结果对象。
        if not isinstance(result, RollingOptimizationResult):
            self._result_cache[request_fingerprint] = result
            self._last_observation_fingerprint = observation_fingerprint
            return result

        if result.commit_status == "withheld_infeasible":
            self._consecutive_withheld += 1
            if (
                self._consecutive_withheld
                >= self.policy.manual_after_consecutive_withheld
            ):
                state_name = "manual_intervention_required"
                action = "hold_new_departures_and_request_dispatcher"
            else:
                state_name = "waiting_for_observation"
                action = "hold_new_departures_and_reoptimize_on_new_observation"
        elif result.commit_status == "committed_infeasible_experiment_only":
            self._consecutive_withheld = 0
            state_name = "experiment_only"
            action = "do_not_dispatch_in_production"
        else:
            recovered_by_retry = len(attempts) > 1
            recovered_after_observation = (
                self._consecutive_withheld > 0 and observation_changed
            )
            self._consecutive_withheld = 0
            if recovered_by_retry:
                state_name = "recovered_automatically"
            elif recovered_after_observation:
                state_name = "recovered_after_observation"
            else:
                state_name = "normal"
            action = "execute_committed_schedule"

        annotated = self._annotate(
            result,
            state_name=state_name,
            action=action,
            attempts=attempts,
            observation_changed=observation_changed,
            request_fingerprint=request_fingerprint,
        )
        self._last_observation_fingerprint = observation_fingerprint
        self._result_cache[request_fingerprint] = annotated
        return annotated

def run_mpc_cycles(
    optimizer: RollingOptimizer,
    initial_state: RollingWindowState,
    base_template: ScheduleTemplate,
    cycles: int = 3,
    horizon_s: int = 7200,
    execute_window_s: int = 600,
    search_config: TemplateSearchConfig | None = None,
    enable_recovery: bool = True,
    allow_infeasible_commit_for_experiment: bool = False,
    safety_policy: RollingSafetyPolicy | None = None,
    observation_provider: Callable[
        [int, RollingWindowState, RollingOptimizationResult | None],
        RollingCycleObservation,
    ]
    | None = None,
) -> List[RollingOptimizationResult]:
    """滚动执行多轮优化，并在每轮开始前接收最新晚点与 SOC 观测。"""
    if not isinstance(enable_recovery, bool):
        raise TypeError("enable_recovery must be a boolean")
    if not isinstance(allow_infeasible_commit_for_experiment, bool):
        raise TypeError("allow_infeasible_commit_for_experiment must be a boolean")
    cycles = _validated_whole_seconds(cycles, "cycles", positive=True)
    horizon_s = _validated_whole_seconds(horizon_s, "horizon_s", positive=True)
    execute_window_s = _validated_whole_seconds(
        execute_window_s, "execute_window_s", positive=True
    )
    if execute_window_s > horizon_s:
        raise ValueError(
            "execute_window_s must not exceed horizon_s; "
            f"got execute_window_s={execute_window_s}, horizon_s={horizon_s}"
        )
    results: List[RollingOptimizationResult] = []
    initial_locked_heavy = [
        _validated_whole_seconds(
            value, "initial_state.locked_heavy_departures_s"
        )
        for value in initial_state.locked_heavy_departures_s
    ]
    initial_locked_empty = [
        _validated_whole_seconds(
            value, "initial_state.locked_empty_departures_s"
        )
        for value in initial_state.locked_empty_departures_s
    ]
    initial_locked_hold = (
        None
        if initial_state.locked_empty_storage_hold_s is None
        else _validated_whole_seconds(
            initial_state.locked_empty_storage_hold_s,
            "initial_state.locked_empty_storage_hold_s",
        )
    )
    if initial_locked_hold is None and initial_locked_empty:
        initial_locked_hold = _validated_whole_seconds(
            base_template.flex_zone_hold_s,
            "base_template.flex_zone_hold_s",
        )
    initial_locked_preset = str(initial_state.locked_storage_preset_id or "").strip()
    if not initial_locked_preset and (initial_locked_heavy or initial_locked_empty):
        initial_locked_preset = (
            str(getattr(base_template, "storage_preset_id", "") or "").strip()
            or optimizer.default_storage_preset_id
        )
    state = replace(
        initial_state,
        current_time_s=_validated_whole_seconds(
            initial_state.current_time_s, "initial_state.current_time_s"
        ),
        locked_heavy_departures_s=initial_locked_heavy,
        locked_empty_departures_s=initial_locked_empty,
        observed_heavy_delay_s=_validated_whole_seconds(
            initial_state.observed_heavy_delay_s,
            "initial_state.observed_heavy_delay_s",
        ),
        observed_empty_delay_s=_validated_whole_seconds(
            initial_state.observed_empty_delay_s,
            "initial_state.observed_empty_delay_s",
        ),
        observed_train_delays_s=initial_state.observed_train_delays_s,
        locked_empty_storage_hold_s=initial_locked_hold,
        locked_storage_preset_id=initial_locked_preset,
    )
    locked_heavy = list(state.locked_heavy_departures_s)
    locked_empty = list(state.locked_empty_departures_s)
    previous_result: RollingOptimizationResult | None = None
    safety_controller = RollingSafetyController(safety_policy)
    for cycle_index in range(cycles):
        if observation_provider is not None:
            observation = observation_provider(cycle_index, state, previous_result)
            if not isinstance(observation, RollingCycleObservation):
                raise TypeError("observation_provider must return RollingCycleObservation")
            state = replace(
                state,
                observed_heavy_delay_s=_validated_whole_seconds(
                    observation.observed_heavy_delay_s,
                    "observation.observed_heavy_delay_s",
                ),
                observed_empty_delay_s=_validated_whole_seconds(
                    observation.observed_empty_delay_s,
                    "observation.observed_empty_delay_s",
                ),
                observed_train_delays_s=observation.observed_train_delays_s,
                storage_soc_kwh=observation.storage_soc_kwh,
                storage_device_states=observation.storage_device_states,
                cancelled_train_ids=observation.cancelled_train_ids,
                added_trains=observation.added_trains,
                resource_unavailabilities=observation.resource_unavailabilities,
                dynamic_power_arm_limits=observation.dynamic_power_arm_limits,
            )
        result = safety_controller.optimize_cycle(
            optimizer,
            state,
            base_template,
            horizon_s=horizon_s,
            execute_window_s=execute_window_s,
            search_config=search_config,
            enable_recovery=enable_recovery,
            allow_infeasible_commit_for_experiment=(
                allow_infeasible_commit_for_experiment
            ),
        )
        results.append(result)
        new_heavy = list(result.executable_heavy_departures_s)
        new_empty = list(result.executable_empty_departures_s)
        locked_heavy = sorted(set(locked_heavy + result.executable_heavy_departures_s))
        locked_empty = sorted(set(locked_empty + result.executable_empty_departures_s))
        locked_hold = state.locked_empty_storage_hold_s
        if locked_hold is None and new_empty:
            locked_hold = _validated_whole_seconds(
                result.schedule.template.flex_zone_hold_s,
                "result.schedule.template.flex_zone_hold_s",
            )
        locked_preset = str(state.locked_storage_preset_id or "").strip()
        if not locked_preset and (new_heavy or new_empty):
            locked_preset = (
                str(getattr(result.schedule.template, "storage_preset_id", "") or "").strip()
                or optimizer.default_storage_preset_id
            )
        next_time_s = state.current_time_s + execute_window_s
        state = replace(
            state,
            current_time_s=next_time_s,
            locked_heavy_departures_s=locked_heavy,
            locked_empty_departures_s=locked_empty,
            locked_empty_storage_hold_s=locked_hold,
            locked_storage_preset_id=locked_preset,
        )
        previous_result = result
    return results

def demo() -> None:
    """Run a small rolling optimization demo on the sandbox config."""
    route, trains, battery = load_config(Path("sandbox_config.json"))
    heavy_cache = build_power_cache(trains["Heavy"], route)
    empty_cache = build_power_cache(trains["Empty"], route)
    settlement_system = EnergySettlementSystem(
        battery,
        route.energy_transfer_ranges_km,
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
    )
    optimizer = RollingOptimizer(route, heavy_cache, empty_cache, settlement_system)
    base_template = ScheduleTemplate(
        heavy_headway_s=900,
        empty_headway_s=900,
        heavy_empty_phase_s=420,
        heavy_count=6,
        empty_count=6,
    )
    state = RollingWindowState(
        current_time_s=0,
        locked_heavy_departures_s=[],
        locked_empty_departures_s=[],
    )
    search_config = TemplateSearchConfig(population_size=10, generations=3, elite_count=3)
    result = optimizer.optimize_once(
        state,
        base_template,
        horizon_s=5400,
        execute_window_s=900,
        search_config=search_config,
    )
    print("=== Rolling Optimization Demo ===")
    print("Feasible:", result.score.feasible)
    print("Average cost:", round(result.score.total_cost, 2))
    print("Worst-case cost:", round(result.score.worst_case_cost, 2))
    print("Average headway deviation:", round(result.score.headway_deviation, 2))
    print("Chosen strategy:", describe_template(result.schedule.template))
    print("Chosen heavy departures:", result.schedule.heavy_departures_s)
    print("Chosen empty departures:", result.schedule.empty_departures_s)
    print("Execute now heavy:", result.executable_heavy_departures_s)
    print("Execute now empty:", result.executable_empty_departures_s)

if __name__ == "__main__":
    demo()
