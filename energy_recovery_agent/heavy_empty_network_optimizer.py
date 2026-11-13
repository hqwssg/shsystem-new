# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple
from collections import defaultdict
import csv
import json
import math
import random

from formation_modes import (
    DEFAULT_FORMATION_MODE_PATH,
    FormationMode,
    formation_source_note,
    infer_load_state,
    load_formation_modes,
    resolve_formation_mode,
)
from power_arm_electrical_limits import (
    DEFAULT_POWER_ARM_INTERVAL_PATH,
    PowerArmElectricalLimit,
    StorageSectionInterval,
    electrical_limit_fields,
    limit_for_power_arm,
    load_power_arm_electrical_limits,
    power_arm_electrical_limit_from_row,
    storage_boundary_kms,
    storage_section_intervals_from_rows,
    storage_section_for_position,
    time_window_capacity_kwh,
)
from energy_settlement import (
    EnergyBucketRequest,
    enabled_storage_section_id,
    initialize_storage_settlement_state,
    power_arm_limit_is_explicit,
    settle_energy_bucket_group,
    storage_no_direct_effective_loss_kwh,
    storage_section_ids_from_limits,
)
from train_simulator import BatteryStorageParameters

try:
    import openpyxl
except ImportError:  # pragma: no cover - 仅使用 CSV 执行时仍可正常工作。
    openpyxl = None


OBJECTIVE_MODE_CAPACITY_SURPLUS = "capacity_surplus"
OBJECTIVE_MODE_CAPACITY_TIGHT = "capacity_tight"
REGEN_RECOVERY_EFFICIENCY = 0.65
ELECTRICAL_CONSTRAINT_TOLERANCE_KWH = 1e-6

FORMATION_ARC_TYPES: Dict[str, str] = {
    "combine": "combining",
    "dismantle": "dismantling",
}

# 重空协同方式：integrated = 重列与空列在同一时空网络内协同（车底周转复用 + 联合间隔）；
# decoupled = 割裂规划（重列先独立规划、空列再独立调配，不复用车底、不考虑联合间隔），
# 用于技术方案 4.1.2.4 场景 3 的"割裂规划方案"对比基准。
COORDINATION_MODE_INTEGRATED = "integrated"
COORDINATION_MODE_DECOUPLED = "decoupled"
COORDINATION_MODES: Tuple[str, ...] = (
    COORDINATION_MODE_INTEGRATED,
    COORDINATION_MODE_DECOUPLED,
)
"""组合/分解作业在时空网络中的弧类型名（技术方案 4.2.1.2(2) 第三类约束）。"""


def _finite_number(value: Any, field_name: str, *, minimum: float | None = None) -> float:
    """函数 _finite_number：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be finite, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite, got {value!r}") from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        constraint = f" and greater than or equal to {minimum}" if minimum is not None else ""
        raise ValueError(f"{field_name} must be finite{constraint}, got {value!r}")
    return number


def _whole_number(value: Any, field_name: str, *, minimum: int | None = None) -> int:
    """函数 _whole_number：执行该模块中的相关处理逻辑。"""
    number = _finite_number(value, field_name)
    if not number.is_integer() or (minimum is not None and number < minimum):
        constraint = f" and greater than or equal to {minimum}" if minimum is not None else ""
        raise ValueError(f"{field_name} must be a finite whole number{constraint}, got {value!r}")
    return int(number)


def _copy_index_tuple(value: Any, field_name: str) -> Tuple[int, ...]:
    """解析模板中的车底序号列表（``1,2`` 或可迭代整数），返回去重升序元组。"""
    if isinstance(value, (str, bytes)):
        raw_items: List[Any] = [
            part for part in str(value).replace("\uff0c", ",").split(",") if part.strip()
        ]
    else:
        raw_items = list(value)
    if not raw_items:
        raise ValueError(f"{field_name} must not be empty")
    indices: List[int] = []
    for item in raw_items:
        index = _whole_number(_clean(item), field_name, minimum=1)
        if index in indices:
            raise ValueError(f"{field_name} contains duplicate copy index {index}")
        indices.append(index)
    return tuple(sorted(indices))


def _value_or_default(value: Any, default: Any) -> Any:
    """函数 _value_or_default：执行该模块中的相关处理逻辑。"""
    return default if value is None or (isinstance(value, str) and not value.strip()) else value


def _optional_value_or_default(value: Optional[float], default: float) -> float:
    """函数 _optional_value_or_default：执行该模块中的相关处理逻辑。"""
    return default if value is None else value


@dataclass(frozen=True)
class HeOdDemand:
    """类 HeOdDemand：执行该模块中的相关处理逻辑。"""
    demand_id: str
    origin_station: str
    destination_station: str
    train_type: str
    train_count: int
    earliest_departure_s: int
    latest_departure_s: int
    due_arrival_s: int
    cargo_tons: float
    cargo_value: float
    priority: int

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        for field_name in ("demand_id", "origin_station", "destination_station", "train_type"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.origin_station == self.destination_station:
            raise ValueError("origin_station and destination_station must differ")
        object.__setattr__(
            self, "train_count", _whole_number(self.train_count, "train_count", minimum=1)
        )
        for field_name in ("earliest_departure_s", "latest_departure_s", "due_arrival_s"):
            object.__setattr__(
                self,
                field_name,
                _whole_number(getattr(self, field_name), field_name, minimum=0),
            )
        if self.latest_departure_s < self.earliest_departure_s:
            raise ValueError("latest_departure_s must not precede earliest_departure_s")
        if self.due_arrival_s < self.earliest_departure_s:
            raise ValueError("due_arrival_s must not precede earliest_departure_s")
        object.__setattr__(
            self, "cargo_tons", _finite_number(self.cargo_tons, "cargo_tons", minimum=0.0)
        )
        object.__setattr__(
            self, "cargo_value", _finite_number(self.cargo_value, "cargo_value", minimum=0.0)
        )
        object.__setattr__(self, "priority", _whole_number(self.priority, "priority", minimum=1))


@dataclass(frozen=True)
class ServiceType:
    """类 ServiceType：执行该模块中的相关处理逻辑。"""
    train_type: str
    direction: str
    consist_unit: int
    fixed_cost: float
    distance_cost_per_km: float
    energy_cost_per_kwh: float
    nominal_speed_kmh: float
    energy_kwh_per_km: float
    formation_category: str = ""
    formation_mode: str = ""
    wagon_count: int = 0
    mass_tons: float = 0.0
    mass_source: str = ""

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        if not str(self.train_type).strip():
            raise ValueError("train_type must not be empty")
        if self.direction not in {"forward", "reverse"}:
            raise ValueError(f"direction must be forward or reverse, got {self.direction!r}")
        object.__setattr__(
            self, "consist_unit", _whole_number(self.consist_unit, "consist_unit", minimum=1)
        )
        for field_name in ("fixed_cost", "distance_cost_per_km", "energy_cost_per_kwh", "mass_tons"):
            object.__setattr__(
                self,
                field_name,
                _finite_number(getattr(self, field_name), field_name, minimum=0.0),
            )
        for field_name in ("nominal_speed_kmh", "energy_kwh_per_km"):
            value = _finite_number(getattr(self, field_name), field_name)
            if value <= 0.0:
                raise ValueError(f"{field_name} must be positive, got {value!r}")
            object.__setattr__(self, field_name, value)
        object.__setattr__(
            self, "wagon_count", _whole_number(self.wagon_count, "wagon_count", minimum=0)
        )


@dataclass(frozen=True)
class GradientSegment:
    """类 GradientSegment：执行该模块中的相关处理逻辑。"""
    source_image: str
    start_km: float
    end_km: float
    length_m: float
    gradient_promille: float


@dataclass(frozen=True)
class CurveSegment:
    """类 CurveSegment：执行该模块中的相关处理逻辑。"""
    source_sheet: str
    start_km: Optional[float]
    end_km: Optional[float]
    radius_m: float
    length_m: float
    direction: str


@dataclass(frozen=True)
class PowerArmSegment:
    """类 PowerArmSegment：执行该模块中的相关处理逻辑。"""
    record_id: str
    source_page: int
    direction: str
    start_km: float
    center_km: float
    end_km: float
    min_km: float
    max_km: float
    traction_substation: str
    power_supply_range: str
    needs_manual_review: bool
    source_kind: str = "boundary_record"
    electrical_limit: PowerArmElectricalLimit = PowerArmElectricalLimit()


@dataclass(frozen=True)
class InfrastructureProfile:
    """类 InfrastructureProfile：执行该模块中的相关处理逻辑。"""
    gradients: Tuple[GradientSegment, ...]
    curves: Tuple[CurveSegment, ...]
    power_arms: Tuple[PowerArmSegment, ...]
    storage_sections: Tuple[StorageSectionInterval, ...]
    phase_boundary_kms: Tuple[float, ...]
    source_notes: Tuple[str, ...]


@dataclass(frozen=True)
class ArcInfrastructureAttributes:
    """类 ArcInfrastructureAttributes：执行该模块中的相关处理逻辑。"""
    avg_gradient_promille: float
    gradient_sample_count: int
    curve_equivalent: float
    curve_positioned_count: int
    power_arm_ids: Tuple[str, ...]
    power_arm_review_required: bool
    energy_multiplier: float
    infrastructure_note: str


@dataclass(frozen=True)
class OperationNode:
    """类 OperationNode：执行该模块中的相关处理逻辑。"""
    station_name: str
    role: str
    operation_min_s: int
    capacity_per_slot: int

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        if not str(self.station_name).strip():
            raise ValueError("station_name must not be empty")
        object.__setattr__(
            self,
            "operation_min_s",
            _whole_number(self.operation_min_s, "operation_min_s", minimum=0),
        )
        object.__setattr__(
            self,
            "capacity_per_slot",
            _whole_number(self.capacity_per_slot, "capacity_per_slot", minimum=1),
        )


@dataclass(frozen=True)
class VirtualTrainsetConfig:
    """类 VirtualTrainsetConfig：执行该模块中的相关处理逻辑。"""
    virtual_station: str
    penalty_cost: float
    initial_trainsets: int
    end_return_penalty_cost: float

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        if not str(self.virtual_station).strip():
            raise ValueError("virtual_station must not be empty")
        object.__setattr__(
            self,
            "penalty_cost",
            _finite_number(self.penalty_cost, "penalty_cost", minimum=0.0),
        )
        object.__setattr__(
            self,
            "initial_trainsets",
            _whole_number(self.initial_trainsets, "initial_trainsets", minimum=0),
        )
        object.__setattr__(
            self,
            "end_return_penalty_cost",
            _finite_number(
                self.end_return_penalty_cost,
                "end_return_penalty_cost",
                minimum=0.0,
            ),
        )


@dataclass(frozen=True)
class HeScenario:
    """类 HeScenario：执行该模块中的相关处理逻辑。"""
    scenario_id: str
    objective_mode: str
    time_slice_s: int
    max_departure_shift_s: int
    population_size: int
    generations: int
    seed: int
    min_headway_s: int
    section_capacity_per_slot: int
    weight_energy: float
    weight_distance: float
    weight_connection: float
    weight_virtual: float
    weight_throughput: float
    energy_settlement_step_s: int = 10
    min_arrival_headway_s: int = 0

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        if not str(self.scenario_id).strip():
            raise ValueError("scenario_id must not be empty")
        if self.objective_mode not in {OBJECTIVE_MODE_CAPACITY_SURPLUS, OBJECTIVE_MODE_CAPACITY_TIGHT}:
            raise ValueError(f"Unsupported objective_mode: {self.objective_mode!r}")
        for field_name in (
            "time_slice_s",
            "population_size",
            "generations",
            "min_headway_s",
            "section_capacity_per_slot",
            "energy_settlement_step_s",
        ):
            object.__setattr__(
                self,
                field_name,
                _whole_number(getattr(self, field_name), field_name, minimum=1),
            )
        object.__setattr__(
            self,
            "max_departure_shift_s",
            _whole_number(self.max_departure_shift_s, "max_departure_shift_s", minimum=0),
        )
        object.__setattr__(self, "seed", _whole_number(self.seed, "seed"))
        object.__setattr__(
            self,
            "min_arrival_headway_s",
            _whole_number(self.min_arrival_headway_s, "min_arrival_headway_s", minimum=0),
        )
        for field_name in (
            "weight_energy",
            "weight_distance",
            "weight_connection",
            "weight_virtual",
            "weight_throughput",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite_number(getattr(self, field_name), field_name, minimum=0.0),
            )


@dataclass(frozen=True)
class FormationOperation:
    """组合站/分解站的显式作业关系（技术方案 4.2.1.2(2) 第三类约束：分解站流平衡）。

    一条记录描述一次"输入车底 → 站内作业 → 输出车底"的列型变换：

    - ``combine``：``input_copies`` 各以 ``upstream_service`` 运行至 ``station_name``，在站组合后
      由 ``output_copies`` 以 ``downstream_service`` 继续运行（小列 + 小列 → 大列）。
    - ``dismantle``：``input_copies`` 各以 ``upstream_service`` 运行至 ``station_name``，在站分解后
      由 ``output_copies`` 以 ``downstream_service`` 继续运行（大列 → 小列 + 小列）。

    ``leg`` 指明作用在重列运行段（``heavy``）还是空列回送段（``empty``）；``input_copies`` /
    ``output_copies`` 为 1 基车底序号（对应 ``{demand_id}:H{copy}`` / ``{demand_id}:E{copy}``）。
    数量守恒与列型守恒在 ``_validate_he_input_bundle`` 中校验，站内作业在 ``_build_candidate``
    中物化为真实的 ``combining`` / ``dismantling`` 弧。
    """

    operation_id: str
    station_name: str
    operation_type: str
    leg: str
    demand_id: str
    input_copies: Tuple[int, ...]
    output_copies: Tuple[int, ...]
    upstream_service: str
    downstream_service: str
    operation_min_s: Optional[int] = None
    note: str = ""

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        for field_name in (
            "operation_id",
            "station_name",
            "demand_id",
            "upstream_service",
            "downstream_service",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"formation operation {field_name} must not be empty")
        if self.operation_type not in {"combine", "dismantle"}:
            raise ValueError(
                f"formation operation_type must be combine or dismantle, got {self.operation_type!r}"
            )
        if self.leg not in {"heavy", "empty"}:
            raise ValueError(f"formation leg must be heavy or empty, got {self.leg!r}")
        object.__setattr__(self, "input_copies", _copy_index_tuple(self.input_copies, "input_copies"))
        object.__setattr__(self, "output_copies", _copy_index_tuple(self.output_copies, "output_copies"))
        if self.operation_min_s is not None:
            object.__setattr__(
                self,
                "operation_min_s",
                _whole_number(self.operation_min_s, "operation_min_s", minimum=0),
            )

    def service_for(self, copies: Sequence[int]) -> str:
        """返回给定车底序号对应的服务类型名（输入侧取上游，输出侧取下游）。"""
        return self.upstream_service if tuple(copies) == self.input_copies else self.downstream_service


@dataclass(frozen=True)
class SectionElasticity:
    """高敏区段的软惩罚/弹性边界配置（技术方案 4.2.1.2(1)）。

    针对敏感性分析识别出的高敏区段，可在名义通过能力之上叠加一层**弹性边界**：

    - ``capacity_multiplier``：区段有效通过能力 = ``section_capacity_per_slot × multiplier``（须 ≥1.0，只放宽）。
    - ``soft_penalty_weight``：占用超过名义能力但仍在弹性边界内时的**软惩罚**系数（≥0），计入综合成本而不判为硬冲突。

    未声明任何 ``section_elasticity`` 时行为与既有完全一致（默认 no-op）。
    """

    section_key: str
    capacity_multiplier: float = 1.0
    soft_penalty_weight: float = 0.0
    note: str = ""

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        if not str(self.section_key).strip():
            raise ValueError("section_elasticity section_key must not be empty")
        object.__setattr__(
            self,
            "capacity_multiplier",
            _finite_number(self.capacity_multiplier, "capacity_multiplier", minimum=1.0),
        )
        object.__setattr__(
            self,
            "soft_penalty_weight",
            _finite_number(self.soft_penalty_weight, "soft_penalty_weight", minimum=0.0),
        )


@dataclass(frozen=True)
class ThroatCapacity:
    """车站咽喉能力配置（技术方案 4.2.1.2(1) 约束体系新增"咽喉能力"）。

    咽喉是车站到发线与区间/股道衔接的进路区，同一时间片内可同时办理的进出站作业数受
    咽喉能力限制。本配置按车站声明每时间片可占用的咽喉作业数；重列到发与空列到发各计
    一次咽喉占用，越限即记为冲突。

    未声明任何 ``throat_capacity`` 时行为与既有完全一致（默认 no-op）。
    """

    station_name: str
    capacity_per_slot: int
    note: str = ""

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        if not str(self.station_name).strip():
            raise ValueError("throat_capacity station_name must not be empty")
        object.__setattr__(
            self,
            "capacity_per_slot",
            _whole_number(self.capacity_per_slot, "capacity_per_slot", minimum=1),
        )


@dataclass(frozen=True)
class HeInputBundle:
    """类 HeInputBundle：执行该模块中的相关处理逻辑。"""
    demands: Tuple[HeOdDemand, ...]
    service_types: Dict[str, ServiceType]
    operation_nodes: Dict[str, OperationNode]
    virtual_trainset: VirtualTrainsetConfig
    scenarios: Dict[str, HeScenario]
    station_positions_km: Dict[str, float]
    infrastructure: InfrastructureProfile
    battery: BatteryStorageParameters
    power_arm_limits: Dict[str, PowerArmElectricalLimit]
    formation_operations: Tuple[FormationOperation, ...] = ()
    od_time_shifts: Tuple[Tuple[str, int], ...] = ()
    section_elasticity: Tuple[SectionElasticity, ...] = ()
    throat_capacity: Tuple[ThroatCapacity, ...] = ()


def _validate_he_input_bundle(bundle: HeInputBundle) -> HeInputBundle:
    """函数 _validate_he_input_bundle：执行该模块中的相关处理逻辑。"""
    if not bundle.demands:
        raise ValueError("heavy-empty input must contain at least one OD demand")
    if not bundle.service_types:
        raise ValueError("heavy-empty input must contain at least one service type")
    if not bundle.scenarios:
        raise ValueError("heavy-empty input must contain at least one scenario")
    for demand in bundle.demands:
        if demand.train_type not in bundle.service_types:
            raise ValueError(
                f"demand {demand.demand_id!r} references unknown train_type {demand.train_type!r}"
            )
        for field_name, station_name in (
            ("origin_station", demand.origin_station),
            ("destination_station", demand.destination_station),
        ):
            if station_name not in bundle.station_positions_km:
                raise ValueError(
                    f"demand {demand.demand_id!r} {field_name} references unknown station "
                    f"{station_name!r}"
                )
    unknown_operation_nodes = sorted(
        set(bundle.operation_nodes).difference(bundle.station_positions_km)
    )
    if unknown_operation_nodes:
        raise ValueError(
            f"operation_nodes reference unknown stations: {unknown_operation_nodes}"
        )
    _validate_formation_operations(bundle)
    _validate_od_time_shifts(bundle)
    _validate_section_elasticity(bundle)
    _validate_throat_capacity(bundle)
    return bundle


def _od_time_shift_map(
    pairs: Any,
    *,
    field_name: str = "od_time_shifts",
) -> Dict[str, int]:
    """把逐 OD 流时移声明规范化为 ``{demand_id: shift_s}``。

    技术方案 4.2.1.2(2) 扩展约束 (16)(17)"时间调整唯一性"要求同一 OD 流只允许**一个**
    时间调整量，因此这里对重复 ``demand_id`` 直接报错，避免同一流被调整两次。
    """
    result: Dict[str, int] = {}
    if pairs is None:
        return result
    if isinstance(pairs, Mapping):
        items = list(pairs.items())
    else:
        items = list(pairs)
    for item in items:
        demand_id, shift = item
        demand_id = str(demand_id).strip()
        if not demand_id:
            raise ValueError(f"{field_name} contains an empty demand_id")
        if demand_id in result:
            raise ValueError(
                f"{field_name} declares duplicate demand_id {demand_id!r}; the time adjustment "
                f"of one OD flow must be unique"
            )
        result[demand_id] = _whole_number(shift, f"{field_name}[{demand_id}]")
    return result


def _validate_od_time_shifts(bundle: HeInputBundle) -> None:
    """装载期校验逐 OD 流时移声明的唯一性与引用合法性。"""
    shift_map = _od_time_shift_map(bundle.od_time_shifts)
    known = {demand.demand_id for demand in bundle.demands}
    unknown = sorted(set(shift_map).difference(known))
    if unknown:
        raise ValueError(f"od_time_shifts reference unknown demands: {unknown}")


def _section_elasticity_map(
    entries: Any,
    *,
    field_name: str = "section_elasticity",
) -> Dict[str, SectionElasticity]:
    """把区段弹性边界声明规范化为 ``{section_key: SectionElasticity}``。

    同一区段只允许一条声明（重复即报错），避免同一区段的弹性能力被叠加两次。
    """
    result: Dict[str, SectionElasticity] = {}
    for entry in entries or ():
        section_key = str(entry.section_key).strip()
        if section_key in result:
            raise ValueError(
                f"{field_name} declares duplicate section_key {section_key!r}"
            )
        result[section_key] = entry
    return result


def _validate_section_elasticity(bundle: HeInputBundle) -> None:
    """装载期校验区段弹性边界声明的唯一性。"""
    _section_elasticity_map(bundle.section_elasticity)


def _throat_capacity_map(
    entries: Any,
    *,
    field_name: str = "throat_capacity",
) -> Dict[str, int]:
    """把车站咽喉能力声明规范化为 ``{station_name: capacity_per_slot}``。

    同一车站只允许一条声明（重复即报错），避免同一车站的咽喉能力被叠加两次。
    """
    result: Dict[str, int] = {}
    for entry in entries or ():
        station_name = str(entry.station_name).strip()
        if station_name in result:
            raise ValueError(
                f"{field_name} declares duplicate station_name {station_name!r}"
            )
        result[station_name] = entry.capacity_per_slot
    return result


def _validate_throat_capacity(bundle: HeInputBundle) -> None:
    """装载期校验车站咽喉能力声明的唯一性与引用合法性。"""
    capacity_map = _throat_capacity_map(bundle.throat_capacity)
    unknown = sorted(set(capacity_map).difference(bundle.station_positions_km))
    if unknown:
        raise ValueError(f"throat_capacity reference unknown stations: {unknown}")


def _combined_train_shift_issues(
    bundle: HeInputBundle,
    shift_map: Mapping[str, int],
    fallback_shift_s: int = 0,
) -> List[str]:
    """校验组合列车"两支一致"（技术方案 4.2.1.2(2) 扩展约束 (23)）。

    组合列车由多支车底在组合站并为一列运行，因此**同一组合站上参与组合的各 OD 流必须采用
    相同的时间调整量**，否则并线后的大列无法给出一致的到发时刻。这里按组合站归组检查各
    来源 OD 的有效时移，不一致即返回问题描述（由调用方计入约束违反）。
    """
    by_station: Dict[str, Dict[str, int]] = {}
    for operation in bundle.formation_operations:
        if operation.operation_type != "combine":
            continue
        effective = int(shift_map.get(operation.demand_id, fallback_shift_s))
        by_station.setdefault(operation.station_name, {})[operation.demand_id] = effective
    issues: List[str] = []
    for station_name, demand_shifts in sorted(by_station.items()):
        distinct = sorted(set(demand_shifts.values()))
        if len(distinct) > 1:
            detail = ", ".join(
                f"{demand_id}={shift}s" for demand_id, shift in sorted(demand_shifts.items())
            )
            issues.append(
                f"combined train at {station_name} requires one shared time adjustment across its "
                f"branches, got {detail}"
            )
    return issues


def _formation_operation_standard_units(
    service_types: Dict[str, ServiceType],
    service_name: str,
    copies: Sequence[int],
) -> float:
    """按"每一大列换算为 2 个标准列"的口径计算一侧车底的标准列数。"""
    service = service_types[service_name]
    return float(len(tuple(copies)) * service.consist_unit)


def _validate_formation_operations(bundle: HeInputBundle) -> None:
    """校验组合/分解作业的数量守恒、列型守恒与站点/车底引用。

    技术方案 4.2.1.2(2) 第三类约束要求"大列拆解为两小列"数量匹配，避免类型与数量不匹配。
    这里在装载期就把不合法的组合/分解关系拦下，避免进入搜索后产生静默错误。
    """
    if not bundle.formation_operations:
        return
    demand_by_id = {item.demand_id: item for item in bundle.demands}
    seen_operation_ids: set[str] = set()
    for operation in bundle.formation_operations:
        if operation.operation_id in seen_operation_ids:
            raise ValueError(
                f"formation_operations contains duplicate operation_id {operation.operation_id!r}"
            )
        seen_operation_ids.add(operation.operation_id)
        if operation.demand_id not in demand_by_id:
            raise ValueError(
                f"formation operation {operation.operation_id!r} references unknown demand "
                f"{operation.demand_id!r}"
            )
        for label, service_name in (
            ("upstream_service", operation.upstream_service),
            ("downstream_service", operation.downstream_service),
        ):
            if service_name not in bundle.service_types:
                raise ValueError(
                    f"formation operation {operation.operation_id!r} {label} references unknown "
                    f"train_type {service_name!r}"
                )
        node = bundle.operation_nodes.get(operation.station_name)
        if node is None:
            raise ValueError(
                f"formation operation {operation.operation_id!r} station "
                f"{operation.station_name!r} is not declared in operation_nodes"
            )
        if node.role != "combine_split":
            raise ValueError(
                f"formation operation {operation.operation_id!r} station "
                f"{operation.station_name!r} role must be combine_split, got {node.role!r}"
            )
        demand = demand_by_id[operation.demand_id]
        max_copy = demand.train_count
        for label, copies in (
            ("input_copies", operation.input_copies),
            ("output_copies", operation.output_copies),
        ):
            out_of_range = [index for index in copies if index > max_copy]
            if out_of_range:
                raise ValueError(
                    f"formation operation {operation.operation_id!r} {label} {out_of_range} exceed "
                    f"demand {operation.demand_id!r} train_count {max_copy}"
                )
        input_units = _formation_operation_standard_units(
            bundle.service_types, operation.upstream_service, operation.input_copies
        )
        output_units = _formation_operation_standard_units(
            bundle.service_types, operation.downstream_service, operation.output_copies
        )
        if abs(input_units - output_units) > 1e-9:
            raise ValueError(
                f"formation operation {operation.operation_id!r} violates quantity conservation: "
                f"inputs {operation.input_copies} x {operation.upstream_service} = {input_units} "
                f"standard units but outputs {operation.output_copies} x "
                f"{operation.downstream_service} = {output_units} standard units"
            )
        if operation.operation_type == "combine":
            if len(operation.input_copies) <= len(operation.output_copies):
                raise ValueError(
                    f"combine operation {operation.operation_id!r} must merge more train copies than "
                    f"it produces, got {len(operation.input_copies)} -> {len(operation.output_copies)}"
                )
        else:
            if len(operation.input_copies) >= len(operation.output_copies):
                raise ValueError(
                    f"dismantle operation {operation.operation_id!r} must split into more train copies "
                    f"than it consumes, got {len(operation.input_copies)} -> "
                    f"{len(operation.output_copies)}"
                )
        station_km = bundle.station_positions_km[operation.station_name]
        origin_km = bundle.station_positions_km[demand.origin_station]
        destination_km = bundle.station_positions_km[demand.destination_station]
        lower, upper = sorted((origin_km, destination_km))
        if not lower < station_km < upper:
            raise ValueError(
                f"formation operation {operation.operation_id!r} station "
                f"{operation.station_name!r} ({station_km} km) is not strictly between "
                f"{demand.origin_station} and {demand.destination_station}"
            )
    _validate_formation_operation_chains(bundle)


def _validate_formation_operation_chains(bundle: HeInputBundle) -> None:
    """校验同一 OD、同一运行段上组合/分解关系的接续性。

    两点要求：同一站同一段上不能声明两个作业（否则站内作业含义不唯一）；任一作业的输出车底
    必须在此之前已经到达该站（是本作业的输入，或更早作业的输入），否则会出现"凭空出现"的车底。
    """
    by_demand_leg: Dict[Tuple[str, str], List[FormationOperation]] = {}
    for operation in bundle.formation_operations:
        by_demand_leg.setdefault((operation.demand_id, operation.leg), []).append(operation)
    for (demand_id, leg), operations in by_demand_leg.items():
        stations = [operation.station_name for operation in operations]
        if len(stations) != len(set(stations)):
            raise ValueError(
                f"demand {demand_id!r} {leg} leg declares more than one formation operation at the "
                f"same station: {sorted(stations)}"
            )
        ordered = sorted(
            operations, key=lambda item: bundle.station_positions_km[item.station_name]
        )
        available_copies: set[int] = set()
        for operation in ordered:
            available_copies.update(operation.input_copies)
            missing = [
                index for index in operation.output_copies if index not in available_copies
            ]
            if missing:
                raise ValueError(
                    f"formation operation {operation.operation_id!r} produces copies {missing} that "
                    f"never arrive at {operation.station_name!r} on the {leg} leg of {demand_id!r}"
                )


@dataclass(frozen=True)
class HeGenome:
    """类 HeGenome：执行该模块中的相关处理逻辑。"""
    departure_shift_s: int
    headway_s: int
    max_heavy_services: Optional[int]


@dataclass(frozen=True)
class HeArc:
    """类 HeArc：执行该模块中的相关处理逻辑。"""
    arc_id: str
    layer: str
    demand_id: str
    train_id: str
    train_type: str
    from_node_id: str
    to_node_id: str
    arc_type: str
    start_station: str
    end_station: str
    start_time_s: int
    end_time_s: int
    start_km: float
    end_km: float
    distance_km: float
    energy_kwh: float
    base_energy_kwh: float
    avg_gradient_promille: float
    curve_equivalent: float
    power_arm_ids: Tuple[str, ...]
    power_arm_review_required: bool
    cost: float
    capacity_resource_id: str
    source: str
    parent_arc_id: str = ""
    segment_index: int = 0
    segment_count: int = 1
    power_arm_split: bool = False
    storage_section_id: str = ""
    regen_energy_kwh: float = 0.0


@dataclass(frozen=True)
class HeNode:
    """类 HeNode：执行该模块中的相关处理逻辑。"""
    node_id: str
    layer: str
    demand_id: str
    train_id: str
    station_name: str
    position_km: float
    time_s: int
    state: str


@dataclass(frozen=True)
class EnergySettlementSummary:
    """类 EnergySettlementSummary：执行该模块中的相关处理逻辑。"""
    traction_kwh: float
    regen_kwh: float
    direct_used_kwh: float
    battery_charge_kwh: float
    battery_discharge_kwh: float
    battery_charge_limited_kwh: float
    battery_discharge_limited_kwh: float
    wasted_kwh: float
    grid_kwh: float
    traction_supply_excess_kwh: float
    regen_absorption_excess_kwh: float
    final_soc_kwh: float
    final_soc_by_storage_kwh: Dict[str, float]
    direct_use_ratio: float
    time_slice_count: int
    settlement_window_count: int


@dataclass(frozen=True)
class HeCandidate:
    """类 HeCandidate：执行该模块中的相关处理逻辑。"""
    candidate_id: str
    objective_mode: str
    feasible: bool
    constraint_violation: float
    electrical_constraint_violation_kwh: float
    total_cost: float
    energy_kwh: float
    energy_objective_kwh: float
    distance_cost: float
    connection_cost: float
    virtual_cost: float
    throughput_ton_km: float
    delivered_train_count: int
    virtual_trainset_count: int
    conflict_count: int
    max_delay_s: int
    departure_shift_s: int
    headway_s: int
    score: float
    energy_settlement: EnergySettlementSummary
    energy_settlement_rows: Tuple[Dict[str, object], ...]
    nodes: Tuple[HeNode, ...]
    arcs: Tuple[HeArc, ...]
    diagnostics: Tuple[str, ...]
    arrival_headway_violation_count: int = 0
    od_time_shift_violation_count: int = 0
    combined_train_shift_violation_count: int = 0
    od_time_shift_rows: Tuple[Dict[str, object], ...] = ()
    coordination_mode: str = COORDINATION_MODE_INTEGRATED
    elastic_soft_penalty: float = 0.0
    elastic_relief_count: int = 0
    throat_conflict_count: int = 0


@dataclass(frozen=True)
class HeOptimizationResult:
    """类 HeOptimizationResult：执行该模块中的相关处理逻辑。"""
    scenario: HeScenario
    candidates: Tuple[HeCandidate, ...]
    pareto_candidates: Tuple[HeCandidate, ...]
    best_candidate: HeCandidate
    infrastructure_notes: Tuple[str, ...]


def parse_time_to_s(value: Any) -> int:
    """函数 parse_time_to_s：执行该模块中的相关处理逻辑。"""
    if value is None:
        return 0
    if hasattr(value, "hour") and hasattr(value, "minute") and hasattr(value, "second"):
        if int(getattr(value, "microsecond", 0)) != 0:
            raise ValueError(f"time must resolve to a whole second, got {value!r}")
        return int(value.hour) * 3600 + int(value.minute) * 60 + int(value.second)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = _finite_number(value, "time", minimum=0.0)
        if 0 <= number < 1:
            seconds = number * 86400.0
        else:
            seconds = number
        rounded = round(seconds)
        if not math.isclose(seconds, rounded, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError(f"time must resolve to a whole second, got {value!r}")
        return int(rounded)
    text = str(value).strip()
    if not text:
        return 0
    parts = text.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = (int(part) for part in parts)
        if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
            raise ValueError(f"time must use valid HH:MM:SS fields, got {value!r}")
        return hours * 3600 + minutes * 60 + seconds
    if len(parts) == 2:
        minutes, seconds = (int(part) for part in parts)
        if minutes < 0 or not 0 <= seconds < 60:
            raise ValueError(f"time must use valid MM:SS fields, got {value!r}")
        return minutes * 60 + seconds
    return _whole_number(text, "time", minimum=0)


def format_s_as_hhmmss(seconds: int) -> str:
    """函数 format_s_as_hhmmss：执行该模块中的相关处理逻辑。"""
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _clean(value: Any) -> str:
    """函数 _clean：执行该模块中的相关处理逻辑。"""
    return "" if value is None else str(value).strip()


def _read_sheet_rows(path: Path, sheet_name: Any) -> List[Dict[str, Any]]:
    """函数 _read_sheet_rows：执行该模块中的相关处理逻辑。"""
    if openpyxl is None:
        raise RuntimeError("openpyxl is required to read the heavy-empty Excel template.")
    wb = openpyxl.load_workbook(path, data_only=True)
    sheet_names = (sheet_name,) if isinstance(sheet_name, str) else tuple(sheet_name)
    matched_sheet = next((name for name in sheet_names if name in wb.sheetnames), None)
    if matched_sheet is None:
        return []
    ws = wb[matched_sheet]
    headers = [_clean(cell.value) for cell in ws[1]]
    rows: List[Dict[str, Any]] = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        item = {headers[idx]: value for idx, value in enumerate(row) if idx < len(headers)}
        if any(_clean(value) for value in item.values()):
            rows.append(item)
    return rows


def _read_csv_rows(path: Path) -> List[Dict[str, Any]]:
    """函数 _read_csv_rows：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _optional_float(value: Any) -> Optional[float]:
    """函数 _optional_float：执行该模块中的相关处理逻辑。"""
    text = _clean(value)
    if not text or text.lower() == "nan":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def _strict_optional_float(value: Any, field_name: str) -> Optional[float]:
    """函数 _strict_optional_float：执行该模块中的相关处理逻辑。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    number = _optional_float(value)
    if number is None:
        raise ValueError(f"{field_name} must be a finite number, got {value!r}")
    return number


def _first_present(row: Dict[str, Any], keys: Sequence[str]) -> Any:
    """函数 _first_present：执行该模块中的相关处理逻辑。"""
    for key in keys:
        if key in row and row[key] is not None and _clean(row[key]) != "":
            return row[key]
    return None


def _boolish(value: Any) -> bool:
    """函数 _boolish：执行该模块中的相关处理逻辑。"""
    text = _clean(value).lower()
    if text in {"1", "true", "yes", "y", "是", "需复核", "需要复核", "缺失"}:
        return True
    if text in {"", "0", "false", "no", "n", "否", "无需复核", "已有"}:
        return False
    raise ValueError(f"boolean flag must be a recognized true/false value, got {value!r}")


def _is_mainline_road(row: Dict[str, Any]) -> bool:
    """函数 _is_mainline_road：执行该模块中的相关处理逻辑。"""
    road = _clean(row.get("road") or row.get("line")).lower()
    return not road or road in {"朔黄线", "shuohuang"}


def _load_station_positions(real_data_dir: Path) -> Dict[str, float]:
    """函数 _load_station_positions：执行该模块中的相关处理逻辑。"""
    positions: Dict[str, float] = {}
    stations_path = real_data_dir / "stations.csv"
    if not stations_path.exists():
        return positions
    with stations_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = _clean(row.get("name") or row.get("station_name"))
            raw_position = row.get("position_km")
            if raw_position is None or not _clean(raw_position):
                raw_position = row.get("km")
            if not name:
                continue
            if name in positions:
                raise ValueError(f"stations.csv contains duplicate station name {name!r}")
            position = _finite_number(raw_position, f"stations[{name!r}].position_km", minimum=0.0)
            positions[name] = position
    return positions


def _resolve_service_formation(
    row: Dict[str, Any],
    formation_modes: Tuple[FormationMode, ...],
) -> Tuple[Optional[FormationMode], float, str]:
    """函数 _resolve_service_formation：执行该模块中的相关处理逻辑。"""
    category = _clean(row.get("formation_category"))
    formation_mode = _clean(row.get("formation_mode"))
    wagon_count_value = _strict_optional_float(row.get("wagon_count"), "wagon_count")
    wagon_count = (
        _whole_number(wagon_count_value, "wagon_count", minimum=0)
        if wagon_count_value is not None
        else None
    )
    explicit_mass = _strict_optional_float(row.get("mass_tons"), "mass_tons")
    resolved = resolve_formation_mode(
        formation_modes,
        category=category,
        load_state=_clean(row.get("load_state")) or infer_load_state(_clean(row.get("train_type"))),
        formation_mode=formation_mode,
        wagon_count=wagon_count,
        free_text=_clean(row.get("formation")),
    )
    if explicit_mass is not None:
        return resolved, explicit_mass, "service_types.mass_tons"
    if resolved:
        return resolved, resolved.mass_tons, "formation_modes_2025"
    return None, 0.0, ""


def _effective_energy_kwh_per_km(row: Dict[str, Any], mass_tons: float) -> float:
    """函数 _effective_energy_kwh_per_km：执行该模块中的相关处理逻辑。"""
    base_energy = float(_value_or_default(row.get("energy_kwh_per_km"), 25))
    reference_mass = _strict_optional_float(
        row.get("mass_energy_reference_tons"),
        "mass_energy_reference_tons",
    )
    exponent = _strict_optional_float(row.get("mass_energy_exponent"), "mass_energy_exponent")
    if reference_mass is not None and reference_mass <= 0.0:
        raise ValueError("mass_energy_reference_tons must be positive")
    if exponent is not None and reference_mass is None:
        raise ValueError("mass_energy_exponent requires mass_energy_reference_tons")
    if mass_tons > 0 and reference_mass is not None:
        return base_energy * ((mass_tons / reference_mass) ** float(exponent if exponent is not None else 1.0))
    return base_energy


def _load_gradients(path: Path) -> Tuple[GradientSegment, ...]:
    """函数 _load_gradients：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        return ()
    rows = _read_csv_rows(path) if path.suffix.lower() == ".csv" else _read_sheet_rows(path, "\u5761\u5ea6\u8868")
    segments: List[GradientSegment] = []
    for row in rows:
        start = _optional_float(row.get("start_km"))
        end = _optional_float(row.get("end_km"))
        grade = _optional_float(
            _first_present(row, ("\u5761\u5ea6", "\u5761\u5ea6(\u5343\u5206\u7387)", "gradient_promille", "gradient_per_mille"))
        )
        length = _optional_float(_first_present(row, ("length", "length(m)", "length_m")))
        if start is None or end is None or grade is None:
            continue
        segments.append(
            GradientSegment(
                source_image=_clean(row.get("source_image")),
                start_km=min(start, end),
                end_km=max(start, end),
                length_m=float(length or abs(end - start) * 1000.0),
                gradient_promille=float(grade),
            )
        )
    return tuple(sorted(segments, key=lambda item: (item.start_km, item.end_km)))


def _load_curves(path: Path) -> Tuple[CurveSegment, ...]:
    """函数 _load_curves：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        return ()
    sheet_name = "\u7ebf\u8def\u66f2\u7ebf\u8868 (2)"
    rows = _read_csv_rows(path) if path.suffix.lower() == ".csv" else _read_sheet_rows(path, sheet_name)
    curves: List[CurveSegment] = []
    for row in rows:
        radius = _optional_float(_first_present(row, ("\u534a\u5f84R(m)", "radius_m")))
        length = _optional_float(_first_present(row, ("\u66f2\u7ebf\u957f\u5ea6L(m)", "length_m")))
        if radius is None or length is None or radius <= 0 or length <= 0:
            continue
        start = _optional_float(_first_present(row, ("\u66f2\u7ebf\u8d77\u59cb\u4f4d\u7f6e(km)", "start_km")))
        end = _optional_float(_first_present(row, ("\u66f2\u7ebf\u7ed3\u675f\u4f4d\u7f6e(km)", "end_km")))
        curves.append(
            CurveSegment(
                source_sheet=_clean(row.get("source_sheet")) or sheet_name,
                start_km=min(start, end) if start is not None and end is not None else None,
                end_km=max(start, end) if start is not None and end is not None else None,
                radius_m=float(radius),
                length_m=float(length),
                direction=_clean(_first_present(row, ("\u66f2\u7ebf\u65b9\u5411", "direction"))),
            )
        )
    # 保持带位置曲线有序，使区间查询在后续记录超出弧段时即可停止；
    # 无位置曲线放在末尾，并由属性计算逻辑跳过。
    return tuple(sorted(curves, key=lambda item: (float("inf") if item.start_km is None else item.start_km, float("inf") if item.end_km is None else item.end_km)))


def _load_power_arms(path: Path) -> Tuple[PowerArmSegment, ...]:
    """函数 _load_power_arms：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        return ()
    rows = _read_sheet_rows(path, "\u4f9b\u7535\u81c2\u7ed3\u6784\u5316\u8349\u7a3f")
    arms: List[PowerArmSegment] = []
    for row in rows:
        min_km = _optional_float(row.get("min_km"))
        max_km = _optional_float(row.get("max_km"))
        if min_km is None or max_km is None:
            continue
        if not _is_mainline_road(row):
            continue
        arms.append(
            PowerArmSegment(
                record_id=_clean(row.get("record_id")),
                source_page=_whole_number(row.get("source_page") or 0, "source_page", minimum=0),
                direction=_clean(row.get("direction")),
                start_km=float(_optional_value_or_default(_optional_float(row.get("start_km")), min_km)),
                center_km=float(
                    _optional_value_or_default(
                        _optional_float(row.get("center_km")),
                        (min_km + max_km) / 2.0,
                    )
                ),
                end_km=float(_optional_value_or_default(_optional_float(row.get("end_km")), max_km)),
                min_km=float(min(min_km, max_km)),
                max_km=float(max(min_km, max_km)),
                traction_substation=_clean(row.get("traction_substation_raw")),
                power_supply_range=_clean(row.get("power_supply_range_raw")),
                needs_manual_review=_boolish(row.get("needs_manual_review")),
                electrical_limit=power_arm_electrical_limit_from_row(row),
            )
        )
    return tuple(sorted(arms, key=lambda item: (item.min_km, item.max_km, item.record_id)))


def _load_power_arm_intervals(path: Path) -> Tuple[PowerArmSegment, ...]:
    """函数 _load_power_arm_intervals：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        return ()
    rows = (
        _read_csv_rows(path)
        if path.suffix.lower() == ".csv"
        else _read_sheet_rows(path, "\u4f9b\u7535\u81c2\u8fde\u7eed\u533a\u95f4\u8868")
    )
    arms: List[PowerArmSegment] = []
    for row in rows:
        if not _is_mainline_road(row):
            continue
        section_id = _clean(row.get("section_id"))
        power_arm_id = _clean(row.get("power_arm_id"))
        record_id = section_id or power_arm_id
        start_km = _strict_optional_float(
            row.get("start_km"),
            f"power_arm[{record_id or '<unknown>'}].start_km",
        )
        end_km = _strict_optional_float(
            row.get("end_km"),
            f"power_arm[{record_id or '<unknown>'}].end_km",
        )
        if start_km is None or end_km is None:
            raise ValueError(
                f"power_arm[{record_id or '<unknown>'}] requires start_km and end_km"
            )
        if math.isclose(start_km, end_km, abs_tol=1e-12):
            raise ValueError(
                f"power_arm[{record_id or '<unknown>'}] start_km and end_km must be distinct"
            )
        review_flag = _clean(row.get("needs_manual_review"))
        arms.append(
            PowerArmSegment(
                record_id=record_id,
                source_page=0,
                direction=_clean(row.get("direction")),
                start_km=float(start_km),
                center_km=(float(start_km) + float(end_km)) / 2.0,
                end_km=float(end_km),
                min_km=float(min(start_km, end_km)),
                max_km=float(max(start_km, end_km)),
                traction_substation=_clean(row.get("traction_substation_raw")),
                power_supply_range=_clean(row.get("power_supply_range_raw")),
                needs_manual_review=review_flag != "\u5df2\u6709",
                source_kind="continuous_interval_draft",
                electrical_limit=power_arm_electrical_limit_from_row(row),
            )
        )
    return tuple(sorted(arms, key=lambda item: (item.direction, item.min_km, item.max_km, item.record_id)))


def _load_storage_sections(path: Path) -> Tuple[StorageSectionInterval, ...]:
    """函数 _load_storage_sections：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        return ()
    rows = (
        _read_csv_rows(path)
        if path.suffix.lower() == ".csv"
        else _read_sheet_rows(path, ("供电臂连续区间表", "供电臂结构化草稿"))
    )
    return storage_section_intervals_from_rows(row for row in rows if _is_mainline_road(row))


def _load_phase_boundary_kms(path: Path) -> Tuple[float, ...]:
    """函数 _load_phase_boundary_kms：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        return ()
    points: set[float] = set()
    if path.suffix.lower() == ".csv":
        for row in _read_csv_rows(path):
            if not _is_mainline_road(row):
                continue
            for key in ("start_km", "end_km"):
                km = _optional_float(row.get(key))
                if km is not None:
                    points.add(round(float(km), 6))
        return tuple(sorted(points))
    for sheet_name in (
        "\u6e90\u8fb9\u754c\u8bb0\u5f55",
        "\u4f9b\u7535\u81c2\u7ed3\u6784\u5316\u8349\u7a3f",
    ):
        rows = _read_sheet_rows(path, sheet_name)
        for row in rows:
            if not _is_mainline_road(row):
                continue
            center_km = _optional_float(row.get("center_km"))
            if center_km is not None:
                points.add(round(float(center_km), 6))
    return tuple(sorted(points))


def _first_existing(paths: Iterable[Path]) -> Optional[Path]:
    """函数 _first_existing：执行该模块中的相关处理逻辑。"""
    return next((path for path in paths if path.exists()), None)


def load_infrastructure_profile(data_dir: Path = Path("data") / "real_shuohuang") -> InfrastructureProfile:
    """函数 load_infrastructure_profile：执行该模块中的相关处理逻辑。"""
    data_dir = Path(data_dir)
    real_gradient_csv = data_dir / "gradients.csv"
    official_gradient_path = data_dir / "\u5761\u5ea6\u8868.xlsx"
    recalculated_gradient_path = data_dir / "\u5761\u5ea6\u8868_\u4e09\u5f20\u7ebf\u8def\u56fe\u8f6c\u5f55\u5408\u5e76\u4fee\u6b63\u7248_\u7ebf\u8def\u56fe3\u5761\u5ea6\u7b26\u53f7\u6279\u91cf\u4fee\u6b63_\u5168\u8868\u91cc\u7a0b\u91cd\u7b97.xlsx"
    corrected_gradient_path = data_dir / "\u5761\u5ea6\u8868_\u4e09\u5f20\u7ebf\u8def\u56fe\u8f6c\u5f55\u5408\u5e76\u4fee\u6b63\u7248_\u7ebf\u8def\u56fe3\u5761\u5ea6\u7b26\u53f7\u6279\u91cf\u4fee\u6b63.xlsx"
    fallback_gradient_path = data_dir / "\u5761\u5ea6\u8868_\u4e09\u5f20\u7ebf\u8def\u56fe\u8f6c\u5f55\u5408\u5e76\u4fee\u6b63\u7248.xlsx"
    gradient_path = _first_existing(
        (
            real_gradient_csv,
            official_gradient_path,
            recalculated_gradient_path,
            corrected_gradient_path,
            fallback_gradient_path,
        )
    )
    if gradient_path is None:
        raise FileNotFoundError(f"No gradient table found under selected data directory: {data_dir}")
    real_curve_csv = data_dir / "curves.csv"
    official_curve_path = data_dir / "\u5e73\u66f2\u7ebf\u8868.xlsx"
    fallback_curve_path = data_dir / "\u5e73\u66f2\u7ebf\u8868_\u6e90\u56fe\u590d\u6838\u4fee\u6b63\u7248.xlsx"
    curve_path = _first_existing((real_curve_csv, official_curve_path, fallback_curve_path))
    if curve_path is None:
        raise FileNotFoundError(f"No curve table found under selected data directory: {data_dir}")
    official_power_arm_source_path = data_dir / "\u4f9b\u7535\u81c2\u8d77\u6b62\u4fe1\u606f.xlsx"
    legacy_power_arm_source_path = data_dir / "\u4f9b\u7535\u81c2\u8d77\u6b62\u4fe1\u606f_\u7ed3\u6784\u5316\u8f6c\u5f55.xlsx"
    power_arm_path = official_power_arm_source_path if official_power_arm_source_path.exists() else legacy_power_arm_source_path
    real_power_arm_interval_path = data_dir / "power_arm_intervals.csv"
    official_power_arm_interval_path = data_dir / "\u4f9b\u7535\u81c2\u8fde\u7eed\u533a\u95f4\u8868.xlsx"
    draft_power_arm_interval_path = data_dir / "\u4f9b\u7535\u81c2\u8fde\u7eed\u533a\u95f4\u8868_\u63a8\u65ad\u8349\u7a3f.xlsx"
    gradients = _load_gradients(gradient_path)
    curves = _load_curves(curve_path)
    power_arm_interval_path = _first_existing(
        (real_power_arm_interval_path, official_power_arm_interval_path)
    )
    power_arms = _load_power_arm_intervals(power_arm_interval_path) if power_arm_interval_path else ()
    power_arm_source = power_arm_interval_path if power_arms and power_arm_interval_path else power_arm_path
    if not power_arms:
        power_arms = _load_power_arm_intervals(draft_power_arm_interval_path)
        power_arm_source = draft_power_arm_interval_path if power_arms else power_arm_source
    if not power_arms:
        if not power_arm_path.exists():
            raise FileNotFoundError(f"No power-arm table found under selected data directory: {data_dir}")
        power_arms = _load_power_arms(power_arm_path)
    phase_boundary_kms = (
        _load_phase_boundary_kms(power_arm_interval_path) if power_arm_interval_path else ()
    ) or _load_phase_boundary_kms(power_arm_path)
    storage_sections = _load_storage_sections(power_arm_source)
    if not storage_sections:
        storage_sections = storage_section_intervals_from_rows(
            {
                "start_km": arm.min_km,
                "end_km": arm.max_km,
                "direction": arm.direction,
                "storage_available": arm.electrical_limit.storage_available,
                "storage_section_id": arm.electrical_limit.storage_section_id,
            }
            for arm in power_arms
        )
    positioned_curves = sum(1 for curve in curves if curve.start_km is not None and curve.end_km is not None)
    notes = (
        f"gradients={len(gradients)} from {gradient_path.name}",
        f"curves={len(curves)} positioned={positioned_curves} from {curve_path.name}",
        f"power_arms={len(power_arms)} from {power_arm_source.name}",
        f"storage_sections={len(storage_sections)} from power-arm storage fields",
        f"phase_boundaries={len(phase_boundary_kms)} from neutral-section center_km; non-crossable boundary modeled at midpoint",
    )
    return InfrastructureProfile(
        gradients=gradients,
        curves=curves,
        power_arms=power_arms,
        storage_sections=storage_sections,
        phase_boundary_kms=phase_boundary_kms,
        source_notes=notes,
    )


def _load_battery_parameters(data_dir: Path) -> BatteryStorageParameters:
    """函数 _load_battery_parameters：执行该模块中的相关处理逻辑。"""
    path = data_dir / "battery.json"
    if not path.exists():
        raise FileNotFoundError(f"No battery configuration found under selected data directory: {data_dir}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("battery.json root must be a JSON object")
    return BatteryStorageParameters(
        capacity_kwh=raw.get("capacity_kwh", 0.0),
        round_trip_efficiency=raw.get("round_trip_efficiency", 0.0),
        depreciation_cost_per_kwh=raw.get("depreciation_cost_per_kwh", 0.0),
        grid_price_per_kwh=raw.get("grid_price_per_kwh", 0.0),
        max_charge_power_kW=raw.get("max_charge_power_kW", 0.0),
        max_discharge_power_kW=raw.get("max_discharge_power_kW", 0.0),
        data_status=_clean(raw.get("data_status")) or "unknown",
        scenario_name=_clean(raw.get("scenario_name")),
        planning_assumption=_boolish(raw.get("planning_assumption", False)),
        note=_clean(raw.get("note")),
    )


def load_he_input_template(path: Path, real_data_dir: Path = Path("data") / "real_shuohuang") -> HeInputBundle:
    """函数 load_he_input_template：执行该模块中的相关处理逻辑。"""
    real_data_dir = Path(real_data_dir)
    demands = tuple(
        HeOdDemand(
            demand_id=_clean(row.get("demand_id")),
            origin_station=_clean(row.get("origin_station")),
            destination_station=_clean(row.get("destination_station")),
            train_type=_clean(row.get("train_type") or "Heavy"),
            train_count=_value_or_default(row.get("train_count"), 1),
            earliest_departure_s=parse_time_to_s(row.get("earliest_departure")),
            latest_departure_s=parse_time_to_s(row.get("latest_departure")),
            due_arrival_s=parse_time_to_s(row.get("due_arrival")),
            cargo_tons=float(_value_or_default(row.get("cargo_tons"), 0)),
            cargo_value=float(_value_or_default(row.get("cargo_value"), 0)),
            priority=_value_or_default(row.get("priority"), 1),
        )
        for row in _read_sheet_rows(path, "od_demands")
    )
    demand_ids = [item.demand_id for item in demands]
    if len(demand_ids) != len(set(demand_ids)):
        raise ValueError("od_demands contains duplicate demand_id values")
    formation_modes = load_formation_modes(real_data_dir / DEFAULT_FORMATION_MODE_PATH.name)
    service_types: Dict[str, ServiceType] = {}
    for row in _read_sheet_rows(path, "service_types"):
        train_type = _clean(row.get("train_type"))
        if not train_type:
            continue
        if train_type in service_types:
            raise ValueError(f"service_types contains duplicate train_type {train_type!r}")
        resolved_mode, mass_tons, mass_source = _resolve_service_formation(row, formation_modes)
        explicit_wagon_count = _strict_optional_float(row.get("wagon_count"), "wagon_count")
        service_types[train_type] = ServiceType(
            train_type=train_type,
            direction=_clean(row.get("direction") or "forward"),
            consist_unit=_value_or_default(row.get("consist_unit"), 1),
            fixed_cost=float(_value_or_default(row.get("fixed_cost"), 0)),
            distance_cost_per_km=float(_value_or_default(row.get("distance_cost_per_km"), 0)),
            energy_cost_per_kwh=float(_value_or_default(row.get("energy_cost_per_kwh"), 0.55)),
            nominal_speed_kmh=float(_value_or_default(row.get("nominal_speed_kmh"), 55)),
            energy_kwh_per_km=_effective_energy_kwh_per_km(row, mass_tons),
            formation_category=_clean(row.get("formation_category")) or (resolved_mode.category if resolved_mode else ""),
            formation_mode=_clean(row.get("formation_mode")) or (resolved_mode.formation_mode if resolved_mode else ""),
            wagon_count=(
                int(explicit_wagon_count)
                if explicit_wagon_count is not None
                else (resolved_mode.wagon_count if resolved_mode else 0)
            ),
            mass_tons=mass_tons,
            mass_source=mass_source if not resolved_mode else f"{mass_source}; {formation_source_note(resolved_mode)}",
        )
    operation_nodes: Dict[str, OperationNode] = {}
    for row in _read_sheet_rows(path, "operation_nodes"):
        station_name = _clean(row.get("station_name"))
        if not station_name:
            continue
        if station_name in operation_nodes:
            raise ValueError(f"operation_nodes contains duplicate station_name {station_name!r}")
        operation_nodes[station_name] = OperationNode(
            station_name=_clean(row.get("station_name")),
            role=_clean(row.get("role")),
            operation_min_s=int(float(_value_or_default(row.get("operation_min"), 0)) * 60),
            capacity_per_slot=int(_value_or_default(row.get("capacity_per_slot"), 1)),
        )
    virtual_rows = _read_sheet_rows(path, "virtual_trainset")
    virtual_row = virtual_rows[0] if virtual_rows else {}
    virtual_trainset = VirtualTrainsetConfig(
        virtual_station=_clean(virtual_row.get("virtual_station") or "VIRTUAL"),
        penalty_cost=float(_value_or_default(virtual_row.get("penalty_cost"), 100000)),
        initial_trainsets=_value_or_default(virtual_row.get("initial_trainsets"), 0),
        end_return_penalty_cost=float(
            _value_or_default(virtual_row.get("end_return_penalty_cost"), 10000)
        ),
    )
    scenarios: Dict[str, HeScenario] = {}
    for row in _read_sheet_rows(path, "scenarios"):
        scenario_id = _clean(row.get("scenario_id"))
        if not scenario_id:
            continue
        if scenario_id in scenarios:
            raise ValueError(f"scenarios contains duplicate scenario_id {scenario_id!r}")
        min_headway_min = _value_or_default(row.get("min_headway_min"), 10)
        min_arrival_headway_min = _value_or_default(
            row.get("min_arrival_headway_min"), min_headway_min
        )
        scenarios[scenario_id] = HeScenario(
            scenario_id=scenario_id,
            objective_mode=_clean(row.get("objective_mode") or OBJECTIVE_MODE_CAPACITY_SURPLUS),
            time_slice_s=int(float(_value_or_default(row.get("time_slice_min"), 15)) * 60),
            max_departure_shift_s=int(float(_value_or_default(row.get("max_departure_shift_min"), 30)) * 60),
            population_size=int(_value_or_default(row.get("population_size"), 24)),
            generations=int(_value_or_default(row.get("generations"), 8)),
            seed=int(_value_or_default(row.get("seed"), 42)),
            min_headway_s=int(float(min_headway_min) * 60),
            min_arrival_headway_s=int(float(min_arrival_headway_min) * 60),
            section_capacity_per_slot=int(_value_or_default(row.get("section_capacity_per_slot"), 2)),
            weight_energy=float(_value_or_default(row.get("weight_energy"), 1)),
            weight_distance=float(_value_or_default(row.get("weight_distance"), 1)),
            weight_connection=float(_value_or_default(row.get("weight_connection"), 1)),
            weight_virtual=float(_value_or_default(row.get("weight_virtual"), 1)),
            weight_throughput=float(_value_or_default(row.get("weight_throughput"), 1)),
            energy_settlement_step_s=_value_or_default(
                row.get("energy_settlement_step_s"),
                10,
            ),
        )
    formation_operations: List[FormationOperation] = []
    for row in _read_sheet_rows(path, "formation_operations"):
        operation_id = _clean(row.get("operation_id"))
        if not operation_id:
            continue
        operation_min_raw = _strict_optional_float(row.get("operation_min"), "operation_min")
        formation_operations.append(
            FormationOperation(
                operation_id=operation_id,
                station_name=_clean(row.get("station_name")),
                operation_type=_clean(row.get("operation_type") or "combine"),
                leg=_clean(row.get("leg") or "heavy"),
                demand_id=_clean(row.get("demand_id")),
                input_copies=_copy_index_tuple(row.get("input_copies"), "input_copies"),
                output_copies=_copy_index_tuple(row.get("output_copies"), "output_copies"),
                upstream_service=_clean(row.get("upstream_service")),
                downstream_service=_clean(row.get("downstream_service")),
                operation_min_s=(
                    None if operation_min_raw is None else int(round(operation_min_raw * 60))
                ),
                note=_clean(row.get("note")),
            )
        )
    od_time_shifts: List[Tuple[str, int]] = []
    for row in _read_sheet_rows(path, "od_time_shift"):
        demand_id = _clean(row.get("demand_id"))
        if not demand_id:
            continue
        shift_min_raw = _strict_optional_float(row.get("shift_min"), "shift_min")
        if shift_min_raw is None:
            continue
        od_time_shifts.append((demand_id, int(round(shift_min_raw * 60))))
    section_elasticity: List[SectionElasticity] = []
    for row in _read_sheet_rows(path, "section_elasticity"):
        section_key = _clean(row.get("section_key"))
        if not section_key:
            continue
        section_elasticity.append(
            SectionElasticity(
                section_key=section_key,
                capacity_multiplier=_value_or_default(row.get("capacity_multiplier"), 1.0),
                soft_penalty_weight=_value_or_default(row.get("soft_penalty_weight"), 0.0),
                note=_clean(row.get("note")),
            )
        )
    throat_capacity: List[ThroatCapacity] = []
    for row in _read_sheet_rows(path, "throat_capacity"):
        station_name = _clean(row.get("station_name"))
        if not station_name:
            continue
        capacity_raw = _strict_optional_float(row.get("capacity_per_slot"), "capacity_per_slot")
        if capacity_raw is None:
            continue
        throat_capacity.append(
            ThroatCapacity(
                station_name=station_name,
                capacity_per_slot=int(round(capacity_raw)),
                note=_clean(row.get("note")),
            )
        )
    bundle = HeInputBundle(
        demands=demands,
        service_types=service_types,
        operation_nodes=operation_nodes,
        virtual_trainset=virtual_trainset,
        scenarios=scenarios,
        station_positions_km=_load_station_positions(real_data_dir),
        infrastructure=load_infrastructure_profile(real_data_dir),
        battery=_load_battery_parameters(real_data_dir),
        power_arm_limits=load_power_arm_electrical_limits(real_data_dir / DEFAULT_POWER_ARM_INTERVAL_PATH.name),
        formation_operations=tuple(formation_operations),
        od_time_shifts=tuple(sorted(od_time_shifts)),
        section_elasticity=tuple(section_elasticity),
        throat_capacity=tuple(throat_capacity),
    )
    return _validate_he_input_bundle(bundle)


def _station_km(bundle: HeInputBundle, station_name: str) -> float:
    """函数 _station_km：执行该模块中的相关处理逻辑。"""
    if station_name in bundle.station_positions_km:
        return bundle.station_positions_km[station_name]
    known = ", ".join(sorted(bundle.station_positions_km)[:8])
    raise KeyError(f"Station {station_name!r} is not in stations.csv. Known examples: {known}")


def _travel_time_s(distance_km: float, service: ServiceType) -> int:
    """函数 _travel_time_s：执行该模块中的相关处理逻辑。"""
    speed = max(1.0, service.nominal_speed_kmh)
    return int(math.ceil(distance_km / speed * 3600.0))


def _overlap_km(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    """函数 _overlap_km：执行该模块中的相关处理逻辑。"""
    start = max(min(left_start, left_end), min(right_start, right_end))
    end = min(max(left_start, left_end), max(right_start, right_end))
    return max(0.0, end - start)


def _travel_direction(start_km: float, end_km: float) -> str:
    """函数 _travel_direction：执行该模块中的相关处理逻辑。"""
    if end_km > start_km:
        return "\u4e0b\u884c"
    if end_km < start_km:
        return "\u4e0a\u884c"
    return ""


def _power_arm_direction_matches(model_direction: str, arm_direction: str) -> bool:
    """Match model travel directions to Chinese/English arm-table aliases.

    The real extracted table uses Chinese direction labels while the virtual
    input template uses ``up``/``down``.  Treating raw labels as identical
    silently drops virtual arms from running arcs, bypassing their electrical
    limits and storage tags.
    """

    model = _clean(model_direction).lower()
    arm = _clean(arm_direction).lower()
    if not model or not arm or arm in {"single", "both", "shared", "bidirectional", "单线"}:
        return True
    aliases = {
        "下行": {"下行", "down", "forward"},
        "上行": {"上行", "up", "reverse"},
    }
    return arm in aliases.get(model, {model})


def _arc_infrastructure_attributes(
    profile: InfrastructureProfile,
    start_km: float,
    end_km: float,
) -> ArcInfrastructureAttributes:
    """函数 _arc_infrastructure_attributes：执行该模块中的相关处理逻辑。"""
    arc_min = min(start_km, end_km)
    arc_max = max(start_km, end_km)
    distance = max(0.0, arc_max - arc_min)
    if distance <= 0:
        return ArcInfrastructureAttributes(
            avg_gradient_promille=0.0,
            gradient_sample_count=0,
            curve_equivalent=0.0,
            curve_positioned_count=0,
            power_arm_ids=(),
            power_arm_review_required=False,
            energy_multiplier=1.0,
            infrastructure_note="stationary arc",
        )

    weighted_grade = 0.0
    gradient_coverage = 0.0
    gradient_count = 0
    for segment in profile.gradients:
        if segment.start_km >= arc_max:
            break
        overlap = _overlap_km(arc_min, arc_max, segment.start_km, segment.end_km)
        if overlap <= 0:
            continue
        weighted_grade += segment.gradient_promille * overlap
        gradient_coverage += overlap
        gradient_count += 1
    avg_grade = weighted_grade / gradient_coverage if gradient_coverage > 0 else 0.0
    if end_km < start_km:
        avg_grade = -avg_grade

    curve_equivalent = 0.0
    curve_positioned_count = 0
    for curve in profile.curves:
        if curve.start_km is None or curve.end_km is None:
            continue
        if curve.start_km >= arc_max:
            break
        overlap = _overlap_km(arc_min, arc_max, curve.start_km, curve.end_km)
        if overlap <= 0:
            continue
        curve_positioned_count += 1
        curve_length_km = max(0.001, abs(curve.end_km - curve.start_km))
        overlap_length_m = curve.length_m * min(1.0, overlap / curve_length_km)
        curve_equivalent += overlap_length_m / max(1.0, curve.radius_m)

    direction = _travel_direction(start_km, end_km)
    arms: List[PowerArmSegment] = []
    for arm in profile.power_arms:
        if direction and not _power_arm_direction_matches(direction, arm.direction):
            continue
        if arm.min_km >= arc_max:
            break
        if _overlap_km(arc_min, arc_max, arm.min_km, arm.max_km) > 0:
            arms.append(arm)
    arm_ids = tuple(arm.record_id for arm in arms if arm.record_id)
    review_required = any(arm.needs_manual_review for arm in arms)

    # 正坡度增加牵引需求，负坡度在本原型中降低净牵引需求；获得里程位置后才启用曲线贡献。
    # 根据 fit_core 智能电表诊断，坡度系数由 0.025 调整为 0.12：平坡约 25 kWh/km，
    # 陡峭正负坡度此前存在系统性低估或高估。该值仍是原型代理值，不是正式牵引曲线。
    energy_multiplier = 1.0 + 0.12 * avg_grade + 0.001 * curve_equivalent
    energy_multiplier = min(2.2, max(0.15, energy_multiplier))
    note_parts = [
        f"gradient_segments={gradient_count}",
        f"gradient_coverage_km={gradient_coverage:.3f}",
        f"curve_positioned_count={curve_positioned_count}",
        f"power_arm_count={len(arm_ids)}",
        f"travel_direction={direction or 'stationary'}",
    ]
    if profile.curves and curve_positioned_count == 0:
        note_parts.append("curve_table_loaded_but_missing_km_positions")
    return ArcInfrastructureAttributes(
        avg_gradient_promille=avg_grade,
        gradient_sample_count=gradient_count,
        curve_equivalent=curve_equivalent,
        curve_positioned_count=curve_positioned_count,
        power_arm_ids=arm_ids,
        power_arm_review_required=review_required,
        energy_multiplier=energy_multiplier,
        infrastructure_note="; ".join(note_parts),
    )


def _power_arm_split_kms(profile: InfrastructureProfile, start_km: float, end_km: float) -> List[float]:
    """函数 _power_arm_split_kms：执行该模块中的相关处理逻辑。"""
    arc_min = min(start_km, end_km)
    arc_max = max(start_km, end_km)
    direction = _travel_direction(start_km, end_km)
    points = {round(start_km, 6), round(end_km, 6)}
    for arm in profile.power_arms:
        if direction and not _power_arm_direction_matches(direction, arm.direction):
            continue
        for km in (arm.min_km, arm.max_km):
            if arc_min < km < arc_max:
                points.add(round(km, 6))
    for km in profile.phase_boundary_kms:
        if arc_min < km < arc_max:
            points.add(round(km, 6))
    for km in storage_boundary_kms(profile.storage_sections, direction):
        if arc_min < km < arc_max:
            points.add(round(km, 6))
    reverse = end_km < start_km
    return sorted(points, reverse=reverse)


def _interpolate_time_s(
    start_time_s: float,
    end_time_s: float,
    start_km: float,
    end_km: float,
    current_km: float,
) -> float:
    """函数 _interpolate_time_s：执行该模块中的相关处理逻辑。"""
    distance = abs(end_km - start_km)
    if distance <= 0:
        return float(start_time_s)
    ratio = abs(current_km - start_km) / distance
    return float(start_time_s) + (float(end_time_s) - float(start_time_s)) * ratio


def _rounded_segment_times(
    start_time_s: int,
    end_time_s: int,
    split_kms: List[float],
    start_km: float,
    end_km: float,
) -> List[int]:
    """将空间边界分配为单调整数秒，避免密集边界产生零时长运行弧。"""

    segment_count = len(split_kms) - 1
    if segment_count <= 0:
        return [int(start_time_s)]
    duration_s = int(end_time_s) - int(start_time_s)
    raw_times = [
        _interpolate_time_s(start_time_s, end_time_s, start_km, end_km, point)
        for point in split_kms
    ]
    # 当总时长足以表示全部正长度片段时，限制每个内部边界的可用整数秒范围。
    # 这样只修正四舍五入造成的局部重复，不改变运行弧的首尾时刻。
    if duration_s >= segment_count:
        rounded = [int(start_time_s)]
        for index in range(1, segment_count):
            lower = max(int(start_time_s) + index, rounded[-1] + 1)
            upper = int(end_time_s) - (segment_count - index)
            rounded.append(min(upper, max(lower, int(round(raw_times[index])))))
        rounded.append(int(end_time_s))
        return rounded
    return [int(round(value)) for value in raw_times]


def _power_arm_capacity_resource(arc_type: str, section_key: str, infra: ArcInfrastructureAttributes) -> str:
    """函数 _power_arm_capacity_resource：执行该模块中的相关处理逻辑。"""
    if len(infra.power_arm_ids) == 1:
        return f"power_arm:{infra.power_arm_ids[0]}"
    if len(infra.power_arm_ids) > 1:
        return "power_arm_overlap:" + ";".join(infra.power_arm_ids)
    return f"power_arm_unassigned:{arc_type}:{section_key}"


def _build_running_arc_segments(
    profile: InfrastructureProfile,
    infra_cache: Dict[Tuple[float, float], ArcInfrastructureAttributes],
    nodes: List[HeNode],
    parent_arc_id: str,
    layer: str,
    demand_id: str,
    train_id: str,
    train_type: str,
    from_node_id: str,
    to_node_id: str,
    arc_type: str,
    start_station: str,
    end_station: str,
    start_time_s: int,
    end_time_s: int,
    start_km: float,
    end_km: float,
    service: ServiceType,
    section_key: str,
) -> Tuple[List[HeArc], float, float]:
    """函数 _build_running_arc_segments：执行该模块中的相关处理逻辑。"""
    split_kms = _power_arm_split_kms(profile, start_km, end_km)
    if len(split_kms) < 2:
        split_kms = [start_km, end_km]

    boundary_node_ids = [from_node_id]
    for idx, boundary_km in enumerate(split_kms[1:-1], start=1):
        boundary_time = _interpolate_time_s(start_time_s, end_time_s, start_km, end_km, boundary_km)
        boundary_node_id = f"{parent_arc_id}:boundary:{idx:03d}"
        nodes.append(
            HeNode(
                boundary_node_id,
                "service",
                demand_id,
                train_id,
                f"{start_station}->{end_station}",
                boundary_km,
                int(round(boundary_time)),
                "power_arm_boundary",
            )
        )
        boundary_node_ids.append(boundary_node_id)
    boundary_node_ids.append(to_node_id)

    total_distance = abs(end_km - start_km)
    segment_count = len(split_kms) - 1
    segment_times = _rounded_segment_times(
        start_time_s,
        end_time_s,
        split_kms,
        start_km,
        end_km,
    )
    arcs: List[HeArc] = []
    total_energy = 0.0
    total_cost = 0.0
    for idx in range(segment_count):
        seg_start_km = split_kms[idx]
        seg_end_km = split_kms[idx + 1]
        seg_distance = abs(seg_end_km - seg_start_km)
        seg_start_time = segment_times[idx]
        seg_end_time = segment_times[idx + 1]
        infra_key = (round(seg_start_km, 6), round(seg_end_km, 6))
        seg_infra = infra_cache.get(infra_key)
        if seg_infra is None:
            seg_infra = _arc_infrastructure_attributes(profile, seg_start_km, seg_end_km)
            infra_cache[infra_key] = seg_infra
        seg_base_energy = seg_distance * service.energy_kwh_per_km
        terrain_adjusted_energy = seg_base_energy * seg_infra.energy_multiplier
        # 只分解一次下坡修正。下坡收益仅通过可回收再生能量体现，未回收部分不能默认为额外牵引减少；
        # 上坡和曲线惩罚仍计入牵引侧。``energy_kwh`` 是净电能，结算时按“净能量 + 再生能量”还原总牵引量。
        downhill_reduction = max(0.0, seg_base_energy - terrain_adjusted_energy)
        seg_regen_energy = downhill_reduction * REGEN_RECOVERY_EFFICIENCY
        seg_traction_energy = max(seg_base_energy, terrain_adjusted_energy)
        seg_energy = seg_traction_energy - seg_regen_energy
        fixed_share = service.fixed_cost * (seg_distance / total_distance) if total_distance > 0 else service.fixed_cost
        seg_cost = seg_distance * service.distance_cost_per_km + fixed_share
        total_energy += seg_energy
        total_cost += seg_cost
        source = f"{seg_infra.infrastructure_note}; parent_arc={parent_arc_id}"
        arcs.append(
            HeArc(
                f"{parent_arc_id}:S{idx + 1:03d}",
                layer,
                demand_id,
                train_id,
                train_type,
                boundary_node_ids[idx],
                boundary_node_ids[idx + 1],
                arc_type,
                start_station,
                end_station,
                int(round(seg_start_time)),
                int(round(seg_end_time)),
                seg_start_km,
                seg_end_km,
                seg_distance,
                seg_energy,
                seg_base_energy,
                seg_infra.avg_gradient_promille,
                seg_infra.curve_equivalent,
                seg_infra.power_arm_ids,
                seg_infra.power_arm_review_required,
                seg_cost,
                _power_arm_capacity_resource(arc_type, section_key, seg_infra),
                source,
                parent_arc_id,
                idx + 1,
                segment_count,
                True,
                storage_section_for_position(
                    (seg_start_km + seg_end_km) / 2.0,
                    profile.storage_sections,
                    _travel_direction(seg_start_km, seg_end_km),
                ),
                regen_energy_kwh=seg_regen_energy,
            )
        )
    return arcs, total_energy, total_cost


def _running_arc_energy_components(arc: HeArc) -> Tuple[float, float]:
    """函数 _running_arc_energy_components：执行该模块中的相关处理逻辑。"""
    if "running" not in arc.arc_type:
        return 0.0, 0.0
    regen_kwh = max(0.0, arc.regen_energy_kwh)
    traction_kwh = max(0.0, arc.energy_kwh + regen_kwh)
    return traction_kwh, regen_kwh


class EnergySliceCandidate(Protocol):
    """生成能量时间片所需的最小候选接口。"""

    @property
    def candidate_id(self) -> str: ...

    @property
    def arcs(self) -> Tuple[HeArc, ...]: ...


def energy_time_slice_rows(candidate: EnergySliceCandidate, time_slice_s: int) -> List[Dict[str, object]]:
    """函数 energy_time_slice_rows：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, object]] = []
    slice_s = _whole_number(time_slice_s, "time_slice_s", minimum=1)
    for (
        arc,
        power_arm_id,
        window_start,
        window_end,
        overlap_s,
        traction_kwh,
        regen_kwh,
    ) in _iter_energy_time_slices(candidate, slice_s):
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "time_window_start_s": window_start,
                "time_window_end_s": window_end,
                "time_window_start": format_s_as_hhmmss(window_start),
                "time_window_end": format_s_as_hhmmss(window_end),
                "arc_id": arc.arc_id,
                "parent_arc_id": arc.parent_arc_id,
                "train_id": arc.train_id,
                "train_type": arc.train_type,
                "arc_type": arc.arc_type,
                "power_arm_id": power_arm_id,
                "storage_section_id": arc.storage_section_id,
                "direction": _travel_direction(arc.start_km, arc.end_km),
                "overlap_s": overlap_s,
                # 计算值保持完整精度，避免聚合后产生虚假的电气容量违反。
                "traction_kwh": traction_kwh,
                "regen_kwh": regen_kwh,
                "net_energy_kwh": traction_kwh - regen_kwh,
                "source": "prototype_time_slice_from_running_arc",
            }
        )
    return rows


def _iter_energy_time_slices(candidate: EnergySliceCandidate, slice_s: int):
    """逐条生成数值时间片；搜索阶段使用该路径，避免创建展示字典和时间字符串。"""

    for arc in candidate.arcs:
        if "running" not in arc.arc_type:
            continue
        start_time_s = _finite_number(arc.start_time_s, f"arcs[{arc.arc_id}].start_time_s")
        end_time_s = _finite_number(arc.end_time_s, f"arcs[{arc.arc_id}].end_time_s")
        if end_time_s <= start_time_s:
            continue
        traction_kwh, regen_kwh = _running_arc_energy_components(arc)
        duration = end_time_s - start_time_s
        power_arm_id = ";".join(arc.power_arm_ids) if arc.power_arm_ids else "UNASSIGNED"
        # 按里程切分基础设施后，弧段边界可能落在小数秒。结算请求要求整数秒窗口，
        # 因此显式对齐窗口，不能依赖后续 ``int()`` 截断，否则可能合并相邻窗口。
        window_start = int(math.floor(start_time_s / slice_s)) * slice_s
        while window_start < end_time_s:
            window_end = window_start + slice_s
            overlap_start = max(start_time_s, float(window_start))
            overlap_end = min(end_time_s, float(window_end))
            overlap_s = max(0, overlap_end - overlap_start)
            if overlap_s > 0:
                ratio = overlap_s / duration
                yield (
                    arc,
                    power_arm_id,
                    window_start,
                    window_end,
                    overlap_s,
                    traction_kwh * ratio,
                    regen_kwh * ratio,
                )
            window_start = window_end


def _power_arm_energy_settlement(
    candidate: "HeCandidate",
    time_slice_s: int,
    battery: BatteryStorageParameters,
    power_limits: Optional[Dict[str, PowerArmElectricalLimit]] = None,
    *,
    include_rows: bool = True,
) -> Tuple[
    List[Dict[str, object]],
    Dict[str, float],
    Dict[str, float],
    int,
    int,
]:
    """函数 _power_arm_energy_settlement：执行该模块中的相关处理逻辑。"""
    selected_limits = power_limits or {}
    grouped: Dict[Tuple[str, str, int, int], Dict[str, float]] = {}
    slice_s = _whole_number(time_slice_s, "time_slice_s", minimum=1)
    time_slice_count = 0
    for (
        arc,
        power_arm_id,
        window_start,
        window_end,
        _overlap_s,
        traction_kwh,
        regen_kwh,
    ) in _iter_energy_time_slices(candidate, slice_s):
        key = (
            power_arm_id,
            arc.storage_section_id,
            window_start,
            window_end,
        )
        bucket = grouped.setdefault(key, {"traction_kwh": 0.0, "regen_kwh": 0.0})
        bucket["traction_kwh"] += traction_kwh
        bucket["regen_kwh"] += regen_kwh
        time_slice_count += 1

    power_arm_ids = {key[0] for key in grouped}
    limits_by_power_arm = {
        power_arm_id: limit_for_power_arm(power_arm_id, selected_limits)
        for power_arm_id in power_arm_ids
    }
    explicit_by_power_arm = {
        power_arm_id: power_arm_limit_is_explicit(power_arm_id, selected_limits)
        for power_arm_id in power_arm_ids
    }

    storage_ids = storage_section_ids_from_limits(selected_limits)
    tagged_storage_ids = sorted(
        {
            enabled_storage_section_id(
                storage_section_id,
                limits_by_power_arm[power_arm_id],
                explicit_by_power_arm[power_arm_id],
            )
            for power_arm_id, storage_section_id, _start_s, _end_s in grouped
            if str(storage_section_id).strip()
        }
        - {""}
    )
    if tagged_storage_ids:
        storage_ids = sorted(set(storage_ids).union(tagged_storage_ids))
    storage_state = initialize_storage_settlement_state(
        storage_ids,
        battery.capacity_kwh,
        battery.max_charge_power_kW,
        battery.max_discharge_power_kW,
        0.0,
        battery.round_trip_efficiency,
    )
    grouped_by_time: Dict[
        Tuple[int, int],
        List[Tuple[Tuple[str, str, int, int], Dict[str, float]]],
    ] = {}
    for key, values in grouped.items():
        grouped_by_time.setdefault((key[2], key[3]), []).append((key, values))

    bucket_results = {}
    totals = {
        "traction_kwh": 0.0,
        "regen_kwh": 0.0,
        "direct_used_kwh": 0.0,
        "battery_charge_kwh": 0.0,
        "battery_discharge_kwh": 0.0,
        "battery_charge_limited_kwh": 0.0,
        "battery_discharge_limited_kwh": 0.0,
        "wasted_kwh": 0.0,
        "grid_kwh": 0.0,
        "traction_supply_excess_kwh": 0.0,
        "regen_absorption_excess_kwh": 0.0,
    }
    for (_start_s, _end_s), group_items in sorted(grouped_by_time.items()):
        requests = [
            EnergyBucketRequest(
                traction_kwh=values["traction_kwh"],
                regen_kwh=values["regen_kwh"],
                non_transfer_traction_kwh=0.0,
                non_transfer_regen_kwh=0.0,
                start_s=key[2],
                end_s=key[3],
                storage_section_id=key[1],
                limit=limits_by_power_arm[key[0]],
                power_arm_id=key[0],
                storage_availability_explicit=explicit_by_power_arm[key[0]],
            )
            for key, values in group_items
        ]
        results = settle_energy_bucket_group(
            requests,
            allow_direct_use=False,
            allow_storage=True,
            storage_state=storage_state,
        )
        for (key, _values), result in zip(group_items, results):
            bucket_results[key] = result

    rows: List[Dict[str, object]] = []
    for (power_arm_id, storage_section_id, start_s, end_s), values in sorted(
        grouped.items(), key=lambda item: (item[0][2], item[0][0], item[0][1])
    ):
        traction = values["traction_kwh"]
        regen = values["regen_kwh"]
        limit = limits_by_power_arm[power_arm_id]
        result = bucket_results[(power_arm_id, storage_section_id, start_s, end_s)]
        totals["traction_kwh"] += traction
        totals["regen_kwh"] += regen
        totals["direct_used_kwh"] += result.direct_used_kwh
        totals["battery_charge_kwh"] += result.battery_charge_kwh
        totals["battery_discharge_kwh"] += result.battery_discharge_kwh
        totals["battery_charge_limited_kwh"] += result.battery_charge_limited_kwh
        totals["battery_discharge_limited_kwh"] += result.battery_discharge_limited_kwh
        totals["wasted_kwh"] += result.wasted_kwh
        totals["grid_kwh"] += result.grid_kwh
        totals["traction_supply_excess_kwh"] += result.traction_supply_excess_kwh
        totals["regen_absorption_excess_kwh"] += result.regen_absorption_excess_kwh
        if include_rows:
            traction_capacity_kwh = time_window_capacity_kwh(limit.max_traction_supply_kw, start_s, end_s)
            regen_absorption_capacity_kwh = time_window_capacity_kwh(limit.max_regen_absorption_kw, start_s, end_s)
            grid_feedback_capacity_kwh = time_window_capacity_kwh(limit.max_grid_feedback_kw, start_s, end_s)
            rows.append({
                "candidate_id": candidate.candidate_id,
                "power_arm_id": power_arm_id,
                "time_window_start_s": start_s,
                "time_window_end_s": end_s,
                "time_window_start": format_s_as_hhmmss(start_s),
                "time_window_end": format_s_as_hhmmss(end_s),
                "traction_kwh": traction,
                "regen_kwh": regen,
                "direct_used_kwh": result.direct_used_kwh,
                "battery_charge_kwh": result.battery_charge_kwh,
                "battery_discharge_kwh": result.battery_discharge_kwh,
                "battery_charge_limited_kwh": result.battery_charge_limited_kwh,
                "battery_discharge_limited_kwh": result.battery_discharge_limited_kwh,
                "storage_soc_before_kwh": result.soc_before_kwh,
                "storage_soc_after_kwh": result.soc_after_kwh,
                "wasted_kwh": result.wasted_kwh,
                "grid_kwh": result.grid_kwh,
                "traction_capacity_kwh": round(traction_capacity_kwh, 6),
                "regen_absorption_capacity_kwh": round(regen_absorption_capacity_kwh, 6),
                "grid_feedback_capacity_kwh": round(grid_feedback_capacity_kwh, 6),
                "traction_supply_excess_kwh": result.traction_supply_excess_kwh,
                "regen_absorption_excess_kwh": result.regen_absorption_excess_kwh,
                **electrical_limit_fields(limit),
                # 一个供电臂可能登记多个附属设备；当前切分弧段的实际设备由几何范围生成的键确定，
                # 供结算使用，不能被设备列表覆盖。
                "storage_section_id": storage_section_id,
                "direct_use_ratio": result.direct_used_kwh / regen if regen > 0 else 0.0,
                "settlement_mode": "storage_absorption_no_direct_use_storage_sections_only",
                "source": "prototype_power_arm_energy_settlement",
            })
    final_soc_by_storage = {
        storage_id: soc_kwh
        for storage_id, soc_kwh in sorted(storage_state.soc_by_storage_kwh.items())
        if storage_id != "__legacy__"
    }
    return rows, final_soc_by_storage, totals, time_slice_count, len(grouped)


def power_arm_energy_settlement_rows(
    candidate: "HeCandidate",
    time_slice_s: int,
    battery: BatteryStorageParameters,
    power_limits: Optional[Dict[str, PowerArmElectricalLimit]] = None,
) -> List[Dict[str, object]]:
    """函数 power_arm_energy_settlement_rows：执行该模块中的相关处理逻辑。"""
    rows, _final_soc_by_storage, _totals, _time_slice_count, _window_count = _power_arm_energy_settlement(
        candidate, time_slice_s, battery, power_limits
    )
    return rows


def summarize_energy_settlement(
    candidate: "HeCandidate",
    time_slice_s: int,
    battery: BatteryStorageParameters,
    power_limits: Dict[str, PowerArmElectricalLimit],
    *,
    include_rows: bool = True,
) -> Tuple[EnergySettlementSummary, Tuple[Dict[str, object], ...]]:
    """函数 summarize_energy_settlement：执行该模块中的相关处理逻辑。"""
    settlement_rows, final_soc_by_storage, totals, time_slice_count, window_count = _power_arm_energy_settlement(
        candidate,
        time_slice_s,
        battery,
        power_limits,
        include_rows=include_rows,
    )
    traction = totals["traction_kwh"]
    regen = totals["regen_kwh"]
    direct_used = totals["direct_used_kwh"]
    battery_charge = totals["battery_charge_kwh"]
    battery_discharge = totals["battery_discharge_kwh"]
    battery_charge_limited = totals["battery_charge_limited_kwh"]
    battery_discharge_limited = totals["battery_discharge_limited_kwh"]
    wasted = totals["wasted_kwh"]
    grid = totals["grid_kwh"]
    traction_excess = totals["traction_supply_excess_kwh"]
    regen_excess = totals["regen_absorption_excess_kwh"]
    summary = EnergySettlementSummary(
        traction_kwh=traction,
        regen_kwh=regen,
        direct_used_kwh=direct_used,
        battery_charge_kwh=battery_charge,
        battery_discharge_kwh=battery_discharge,
        battery_charge_limited_kwh=battery_charge_limited,
        battery_discharge_limited_kwh=battery_discharge_limited,
        wasted_kwh=wasted,
        grid_kwh=grid,
        traction_supply_excess_kwh=traction_excess,
        regen_absorption_excess_kwh=regen_excess,
        final_soc_kwh=sum(final_soc_by_storage.values()),
        final_soc_by_storage_kwh=dict(sorted(final_soc_by_storage.items())),
        direct_use_ratio=direct_used / regen if regen > 0 else 0.0,
        time_slice_count=time_slice_count,
        settlement_window_count=window_count,
    )
    return summary, tuple(settlement_rows)


def _formation_operations_by_demand_leg(
    bundle: HeInputBundle,
) -> Dict[Tuple[str, str], Tuple[FormationOperation, ...]]:
    """按 (demand_id, leg) 归组组合/分解作业，并按沿运行方向的推进顺序排序。"""
    grouped: Dict[Tuple[str, str], List[FormationOperation]] = {}
    for operation in bundle.formation_operations:
        grouped.setdefault((operation.demand_id, operation.leg), []).append(operation)
    return {
        key: tuple(
            sorted(
                operations,
                key=lambda item: bundle.station_positions_km[item.station_name],
            )
        )
        for key, operations in grouped.items()
    }


def _formation_leg_plan(
    bundle: HeInputBundle,
    operations: Sequence[FormationOperation],
    copies: Sequence[int],
    native_service_name: str,
    origin_km: float,
    destination_km: float,
    departures: Dict[int, int],
) -> Tuple[Dict[int, Dict[str, object]], Dict[str, Dict[str, object]]]:
    """规划一段运行（重列或空列）上的组合/分解作业。

    返回逐车底的分段计划与作业计划。由于任一作业的输入车底在其站点之前的行程只受更早站点
    的作业影响，按站点推进顺序做**一次正向遍历**即可确定所有时刻。

    当某个作业声明的车底没有全部入选（例如能力紧张场景裁剪了服务），该作业整体不生效，
    相关车底按原生服务贯通运行，避免出现"半边作业"。
    """
    span = destination_km - origin_km
    state: Dict[int, Dict[str, object]] = {
        index: {
            "km": origin_km,
            "service": native_service_name,
            "time": departures[index],
            "segments": [],
            "waits": [],
            "absorbed": False,
        }
        for index in copies
    }
    operation_plan: Dict[str, Dict[str, object]] = {}
    produced: set[int] = set()
    if span == 0 or not operations:
        for index in copies:
            entry = state[index]
            service = bundle.service_types[native_service_name]
            travel = _travel_time_s(abs(destination_km - origin_km), service)
            entry["segments"].append(
                (origin_km, destination_km, native_service_name, departures[index], departures[index] + travel)
            )
            entry["km"] = destination_km
            entry["time"] = departures[index] + travel
        return state, operation_plan

    def _progress(operation: FormationOperation) -> float:
        return (bundle.station_positions_km[operation.station_name] - origin_km) / span

    for operation in sorted(operations, key=_progress):
        station_km = bundle.station_positions_km[operation.station_name]
        if not 0.0 < _progress(operation) < 1.0:
            continue
        inputs = [index for index in operation.input_copies if index in state]
        outputs = [index for index in operation.output_copies if index in state]
        if set(inputs) != set(operation.input_copies) or set(outputs) != set(operation.output_copies):
            continue
        arrivals: List[int] = []
        for index in inputs:
            entry = state[index]
            if entry["absorbed"]:
                raise ValueError(
                    f"formation operation {operation.operation_id!r} consumes copy {index} after it "
                    f"was already absorbed at an earlier formation station"
                )
            service_name = str(entry["service"])
            if service_name != operation.upstream_service:
                if index not in produced and abs(float(entry["km"]) - origin_km) < 1e-9:
                    # 该车底在本作业之前尚未由任何组合/分解作业定型，采用本作业声明的上游
                    # 服务类型（例如组合站之前按小列运行）。
                    entry["service"] = operation.upstream_service
                    service_name = operation.upstream_service
                else:
                    raise ValueError(
                        f"formation operation {operation.operation_id!r} expects upstream_service "
                        f"{operation.upstream_service!r} at {operation.station_name!r}, but copy "
                        f"{index} arrives as {service_name!r}"
                    )
            service = bundle.service_types[service_name]
            travel = _travel_time_s(abs(station_km - float(entry["km"])), service)
            entry["segments"].append(
                (entry["km"], station_km, service_name, entry["time"], entry["time"] + travel)
            )
            entry["km"] = station_km
            entry["time"] = int(entry["time"]) + travel
            arrivals.append(int(entry["time"]))
        operation_min_s = operation.operation_min_s
        if operation_min_s is None:
            node = bundle.operation_nodes.get(operation.station_name)
            operation_min_s = node.operation_min_s if node else 0
        operation_start_s = max(arrivals)
        operation_end_s = operation_start_s + operation_min_s
        for index in inputs:
            entry = state[index]
            if int(entry["time"]) < operation_start_s:
                entry["waits"].append((station_km, int(entry["time"]), operation_start_s))
                entry["time"] = operation_start_s
        for index in outputs:
            entry = state[index]
            entry["km"] = station_km
            entry["service"] = operation.downstream_service
            entry["time"] = operation_end_s
            entry["absorbed"] = False
        for index in inputs:
            if index not in outputs:
                state[index]["absorbed"] = True
        produced.update(outputs)
        operation_plan[operation.operation_id] = {
            "operation": operation,
            "station_km": station_km,
            "start_s": operation_start_s,
            "end_s": operation_end_s,
            "inputs": inputs,
            "outputs": outputs,
        }

    for index in copies:
        entry = state[index]
        if entry["absorbed"]:
            continue
        service = bundle.service_types[str(entry["service"])]
        travel = _travel_time_s(abs(destination_km - float(entry["km"])), service)
        entry["segments"].append(
            (entry["km"], destination_km, entry["service"], entry["time"], int(entry["time"]) + travel)
        )
        entry["km"] = destination_km
        entry["time"] = int(entry["time"]) + travel
    return state, operation_plan


def _create_formation_station_nodes(
    nodes: List[HeNode],
    operation_plan: Dict[str, Dict[str, object]],
    train_prefix: str,
    reserve_operation_slot: Callable[[str, int], None],
) -> Dict[str, Dict[str, str]]:
    """为每个组合/分解作业建立合并节点与输出节点，并占用站场作业时隙。"""
    mapping: Dict[str, Dict[str, str]] = {}
    for operation_id, info in operation_plan.items():
        operation = info["operation"]
        station_km = float(info["station_km"])
        merge_node_id = f"{operation_id}:{train_prefix}:merge"
        out_node_id = f"{operation_id}:{train_prefix}:out"
        nodes.append(
            HeNode(
                merge_node_id,
                "service",
                operation.demand_id,
                operation.demand_id,
                operation.station_name,
                station_km,
                int(info["start_s"]),
                "formation_merge",
            )
        )
        nodes.append(
            HeNode(
                out_node_id,
                "service",
                operation.demand_id,
                operation.demand_id,
                operation.station_name,
                station_km,
                int(info["end_s"]),
                "formation_output",
            )
        )
        mapping[operation_id] = {"merge": merge_node_id, "out": out_node_id}
        reserve_operation_slot(operation.station_name, int(info["start_s"]))
    return mapping


def _emit_formation_leg_arcs(
    bundle: HeInputBundle,
    infra_cache: Dict[Tuple[float, float], ArcInfrastructureAttributes],
    nodes: List[HeNode],
    arcs: List[HeArc],
    plan: Dict[str, object],
    operation_plan: Dict[str, Dict[str, object]],
    formation_node_map: Dict[str, Dict[str, str]],
    demand_id: str,
    train_id: str,
    train_type: str,
    arc_type: str,
    first_node_id: str,
    first_station_name: str,
    final_node_id: str,
    final_station_name: str,
) -> Tuple[float, float, bool]:
    """把一段运行计划展开为真实运行弧，并在组合/分解站接入显式作业弧。

    返回 ``(能量, 距离成本, 是否在组合站并入大列)``。当车底在某个组合站并入大列时，其运行段
    终止于该站，后续由该作业的输出车底承接，不再产生独立运行弧。
    """
    segments: List[Tuple[float, float, str, int, int]] = plan["segments"]  # type: ignore[assignment]
    station_ops = {
        round(float(info["station_km"]), 6): (operation_id, info)
        for operation_id, info in operation_plan.items()
    }
    leg_energy = 0.0
    leg_cost = 0.0
    absorbed = False
    for segment_index, (seg_start_km, seg_end_km, seg_service_name, seg_start_s, seg_end_s) in enumerate(segments):
        seg_service = bundle.service_types[str(seg_service_name)]
        seg_is_last = segment_index == len(segments) - 1
        # 每段的起点节点：首段由调用方给出；后续段一律从该站组合/分解作业的输出节点接续，
        # 这样"在组合站并入大列、在分解站重新出现"的车底也能正确挂到真实节点上。
        if segment_index == 0:
            from_node_id = first_node_id
            from_station_name = first_station_name
        else:
            start_entry = station_ops.get(round(float(seg_start_km), 6))
            if start_entry is None:
                raise ValueError(
                    f"{train_id} leg segment {segment_index + 1} starts at {seg_start_km} km which is "
                    f"not a declared combine/dismantle station"
                )
            from_node_id = formation_node_map[start_entry[0]]["out"]
            from_station_name = start_entry[1]["operation"].station_name
        operation_entry = station_ops.get(round(float(seg_end_km), 6))
        if operation_entry is None:
            to_node_id = final_node_id
            end_station_name = final_station_name
        else:
            operation_id, operation_info = operation_entry
            operation = operation_info["operation"]
            merge_node_id = formation_node_map[operation_id]["merge"]
            if int(seg_end_s) == int(operation_info["start_s"]):
                to_node_id = merge_node_id
            else:
                to_node_id = f"{train_id}:formation_arrive:{operation_id}"
                nodes.append(
                    HeNode(
                        to_node_id,
                        "service",
                        demand_id,
                        train_id,
                        operation.station_name,
                        float(seg_end_km),
                        int(seg_end_s),
                        "formation_arrive",
                    )
                )
                arcs.append(
                    HeArc(
                        f"{train_id}:formation_wait:{operation_id}",
                        "demand",
                        demand_id,
                        train_id,
                        train_type,
                        to_node_id,
                        merge_node_id,
                        "waiting",
                        operation.station_name,
                        operation.station_name,
                        int(seg_end_s),
                        int(operation_info["start_s"]),
                        float(seg_end_km),
                        float(seg_end_km),
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        (),
                        False,
                        0.0,
                        f"station:{operation.station_name}",
                        f"formation_operation_wait:{operation_id}",
                    )
                )
            end_station_name = operation.station_name
            if seg_is_last:
                absorbed = True
        section_key = f"{from_station_name}->{end_station_name}"
        seg_arcs, seg_energy, seg_cost = _build_running_arc_segments(
            bundle.infrastructure,
            infra_cache,
            nodes,
            f"{train_id}:{arc_type}:{segment_index + 1:02d}",
            "service",
            demand_id,
            train_id,
            str(seg_service_name),
            from_node_id,
            to_node_id,
            arc_type,
            from_station_name,
            end_station_name,
            int(seg_start_s),
            int(seg_end_s),
            float(seg_start_km),
            float(seg_end_km),
            seg_service,
            section_key,
        )
        arcs.extend(seg_arcs)
        leg_energy += seg_energy
        leg_cost += seg_cost
        if seg_is_last:
            break
    return leg_energy, leg_cost, absorbed


def _emit_formation_operation_arcs(
    arcs: List[HeArc],
    operation_plan: Dict[str, Dict[str, object]],
    formation_node_map: Dict[str, Dict[str, str]],
) -> None:
    """生成显式的 ``combining`` / ``dismantling`` 作业弧（技术方案第三类约束的载体）。"""
    for operation_id, info in operation_plan.items():
        operation = info["operation"]
        station_km = float(info["station_km"])
        arcs.append(
            HeArc(
                f"{operation_id}:{FORMATION_ARC_TYPES[operation.operation_type]}",
                "demand",
                operation.demand_id,
                operation.demand_id,
                operation.upstream_service,
                formation_node_map[operation_id]["merge"],
                formation_node_map[operation_id]["out"],
                FORMATION_ARC_TYPES[operation.operation_type],
                operation.station_name,
                operation.station_name,
                int(info["start_s"]),
                int(info["end_s"]),
                station_km,
                station_km,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                (),
                False,
                0.0,
                f"station:{operation.station_name}",
                f"formation_operation:{operation_id}",
            )
        )


def _build_candidate(
    bundle: HeInputBundle,
    scenario: HeScenario,
    candidate_id: str,
    departure_shift_s: int,
    headway_s: int,
    max_heavy_services: Optional[int] = None,
    infra_cache: Optional[Dict[Tuple[float, float], ArcInfrastructureAttributes]] = None,
    od_time_shifts: Optional[Mapping[str, int]] = None,
    coordination_mode: str = COORDINATION_MODE_INTEGRATED,
) -> HeCandidate:
    """函数 _build_candidate：执行该模块中的相关处理逻辑。"""
    if coordination_mode not in COORDINATION_MODES:
        raise ValueError(f"unsupported coordination_mode: {coordination_mode!r}")
    nodes: List[HeNode] = []
    arcs: List[HeArc] = []
    diagnostics: List[str] = []
    conflict_count = 0
    virtual_count = 0
    delivered = 0
    total_energy = 0.0
    distance_cost = 0.0
    connection_cost = 0.0
    virtual_cost = 0.0
    throughput = 0.0
    max_delay_s = 0
    occupied_slots: Dict[Tuple[str, int], int] = {}
    operation_slots: Dict[Tuple[str, int], int] = {}
    # 高敏区段软惩罚/弹性边界（技术方案 4.2.1.2(1)）：未声明时为空映射，行为与既有完全一致。
    elasticity_map = _section_elasticity_map(bundle.section_elasticity)
    elastic_soft_penalty = 0.0
    elastic_relief_count = 0
    # 车站咽喉能力（技术方案 4.2.1.2(1) 约束体系）：未声明时为空映射，行为与既有完全一致。
    throat_capacity_map = _throat_capacity_map(bundle.throat_capacity)
    throat_slots: Dict[Tuple[str, int], int] = {}
    throat_conflict_count = 0
    last_departure_by_station: Dict[str, int] = {}
    returned_trainsets_by_station: Dict[str, List[int]] = {}
    initial_trainsets_remaining = bundle.virtual_trainset.initial_trainsets
    formation_operations_by_key = _formation_operations_by_demand_leg(bundle)
    last_empty_departure_by_group: Dict[Tuple[str, str, str], int] = {}
    last_empty_arrival_by_group: Dict[Tuple[str, str, str], int] = {}
    arrival_headway_violation_count = 0
    # 逐 OD 流时移（技术方案 4.2.1.2(2) 扩展约束 (16)–(23)）：未声明时回落到全局发车时移。
    shift_map: Dict[str, int] = (
        dict(od_time_shifts) if od_time_shifts is not None else dict(bundle.od_time_shifts)
    )
    od_time_shift_violation_count = 0
    od_chain_violation_count = 0
    combined_train_shift_violation_count = 0
    od_time_shift_rows: List[Dict[str, object]] = []
    for message in _combined_train_shift_issues(bundle, shift_map, departure_shift_s):
        combined_train_shift_violation_count += 1
        diagnostics.append(message)
    if infra_cache is None:
        infra_cache = {}

    def reserve_operation_slot(station_name: str, operation_start_s: int) -> None:
        """函数 reserve_operation_slot：执行该模块中的相关处理逻辑。"""
        nonlocal conflict_count
        operation = bundle.operation_nodes.get(station_name)
        if operation is None:
            return
        slot = operation_start_s // scenario.time_slice_s
        key = (station_name, slot)
        operation_slots[key] = operation_slots.get(key, 0) + 1
        if operation_slots[key] > operation.capacity_per_slot:
            conflict_count += 1
            diagnostics.append(
                f"{station_name} operation capacity exceeds {operation.capacity_per_slot} "
                f"at {format_s_as_hhmmss(slot * scenario.time_slice_s)}."
            )

    def reserve_throat_slot(station_name: str, event_time_s: int) -> None:
        """车站咽喉能力（技术方案 4.2.1.2(1)）：按车站-时间片统计进出站作业数。

        未声明该车站的咽喉能力时直接返回（默认 no-op），因此不改变既有搜索轨迹。
        """
        nonlocal conflict_count, throat_conflict_count
        capacity = throat_capacity_map.get(station_name)
        if capacity is None:
            return
        slot = event_time_s // scenario.time_slice_s
        key = (station_name, slot)
        throat_slots[key] = throat_slots.get(key, 0) + 1
        if throat_slots[key] > capacity:
            conflict_count += 1
            throat_conflict_count += 1
            diagnostics.append(
                f"{station_name} throat capacity exceeds {capacity} at "
                f"{format_s_as_hhmmss(slot * scenario.time_slice_s)}."
            )

    for demand in sorted(bundle.demands, key=lambda item: (item.earliest_departure_s, item.demand_id)):
        service = bundle.service_types.get(demand.train_type)
        if service is None:
            diagnostics.append(f"Missing service type: {demand.train_type}")
            conflict_count += 1
            continue
        origin_km = _station_km(bundle, demand.origin_station)
        dest_km = _station_km(bundle, demand.destination_station)
        distance = abs(dest_km - origin_km)
        unload_s = bundle.operation_nodes.get(demand.destination_station, OperationNode(demand.destination_station, "unload", 0, 1)).operation_min_s
        load_s = bundle.operation_nodes.get(demand.origin_station, OperationNode(demand.origin_station, "load", 0, 1)).operation_min_s

        heavy_operations = formation_operations_by_key.get((demand.demand_id, "heavy"), ())
        empty_operations = formation_operations_by_key.get((demand.demand_id, "empty"), ())

        # 逐 OD 流时移：同一 OD 的所有车底共用一个调整量（约束 16–22 的唯一性与一致性口径），
        # 未声明时回落为全局发车时移。上下界超过场景上限则记为违反并夹紧到边界继续构建。
        requested_shift = int(shift_map.get(demand.demand_id, departure_shift_s))
        applied_shift = requested_shift
        shift_within_bounds = abs(applied_shift) <= scenario.max_departure_shift_s
        if not shift_within_bounds:
            od_time_shift_violation_count += 1
            diagnostics.append(
                f"{demand.demand_id} od_time_shift {requested_shift}s exceeds the "
                f"{scenario.max_departure_shift_s}s limit."
            )
            applied_shift = max(
                -scenario.max_departure_shift_s,
                min(scenario.max_departure_shift_s, applied_shift),
            )

        # 第一遍：确定入选车底与发车时刻。组合/分解站的站内作业开始时刻取全部输入车底到站
        # 时刻的最大值，因此必须先定下发车时刻，再统一排定作业，避免先到车底被错误地提前。
        selected: List[Tuple[int, int]] = []
        post_shift_feasible = True
        for copy_idx in range(demand.train_count):
            if max_heavy_services is not None and delivered + len(selected) >= max_heavy_services:
                diagnostics.append(
                    f"{demand.demand_id} service copy {copy_idx + 1} not selected in "
                    f"capacity-tight candidate."
                )
                continue
            train_id = f"{demand.demand_id}:H{copy_idx + 1:02d}"
            nominal_departure = demand.earliest_departure_s + copy_idx * headway_s
            requested_departure = nominal_departure + applied_shift
            # 移位后时间可行性：负向时移不得把发车时刻推到发车窗口之前。正向越窗由既有
            # 发车窗口冲突逻辑（depart > latest_departure_s）统一记账，这里不重复计数。
            if requested_departure < demand.earliest_departure_s:
                post_shift_feasible = False
                od_time_shift_violation_count += 1
                diagnostics.append(
                    f"{train_id} od_time_shift {applied_shift}s moves departure before the "
                    f"earliest departure window."
                )
            earliest = requested_departure
            depart = min(max(earliest, demand.earliest_departure_s), demand.latest_departure_s)
            previous_depart = last_departure_by_station.get(demand.origin_station)
            if previous_depart is not None and depart - previous_depart < scenario.min_headway_s:
                depart = previous_depart + scenario.min_headway_s
            last_departure_by_station[demand.origin_station] = depart
            if depart > demand.latest_departure_s:
                diagnostics.append(f"{train_id} departs after latest departure window.")
                conflict_count += 1
            selected.append((copy_idx, depart))

        heavy_plan, heavy_operation_plan = _formation_leg_plan(
            bundle,
            heavy_operations,
            [copy_idx + 1 for copy_idx, _ in selected],
            demand.train_type,
            origin_km,
            dest_km,
            {copy_idx + 1: depart for copy_idx, depart in selected},
        )
        heavy_formation_nodes = _create_formation_station_nodes(
            nodes,
            heavy_operation_plan,
            "H",
            reserve_operation_slot,
        )

        # OD 链起终一致性（约束 18–22）：同一 OD 流的时移必须同时体现在始发发车与终到到达上，
        # 即"发车偏移量 == 到达偏移量"。核对用的基线把**实际发车时刻整体减去本 OD 时移**，从而
        # 在保持站间追踪间隔结构不变的前提下单独剥离 OD 时移的影响；若时移只改了发车、没等量
        # 传递到到达（或不同车底用了不同时移），两个偏移量就会不等。取到达终到站的车底
        # （组合后被吸收的车底不计）。
        observed_copy = next(
            (
                copy_idx
                for copy_idx, _ in selected
                if abs(float(heavy_plan[copy_idx + 1]["km"]) - dest_km) < 1e-6
            ),
            None,
        )
        od_departure_delta: Optional[int] = None
        od_arrival_delta: Optional[int] = None
        od_chain_consistent = True
        if observed_copy is not None:
            nominal_departures = {
                copy_idx + 1: depart - applied_shift for copy_idx, depart in selected
            }
            nominal_plan, _ = _formation_leg_plan(
                bundle,
                heavy_operations,
                [copy_idx + 1 for copy_idx, _ in selected],
                demand.train_type,
                origin_km,
                dest_km,
                nominal_departures,
            )
            observed_departure = dict(selected)[observed_copy]
            od_departure_delta = observed_departure - nominal_departures[observed_copy + 1]
            od_arrival_delta = (
                int(heavy_plan[observed_copy + 1]["time"])
                - int(nominal_plan[observed_copy + 1]["time"])
            )
            od_chain_consistent = od_departure_delta == od_arrival_delta
            if not od_chain_consistent:
                od_chain_violation_count += 1
                diagnostics.append(
                    f"{demand.demand_id} od_time_shift breaks OD-chain consistency: departure shift "
                    f"{od_departure_delta}s but arrival shift {od_arrival_delta}s."
                )

        demand_capacity_overflow = False
        for copy_idx, depart in selected:
            train_id = f"{demand.demand_id}:H{copy_idx + 1:02d}"
            plan = heavy_plan[copy_idx + 1]
            segments: List[Tuple[float, float, str, int, int]] = plan["segments"]  # type: ignore[assignment]
            reached_destination = abs(float(plan["km"]) - dest_km) < 1e-6
            arrive = int(plan["time"]) if reached_destination else int(segments[-1][4])
            unload_end = arrive + unload_s

            trainset_needed_s = depart - load_s
            returned_times = returned_trainsets_by_station.setdefault(demand.origin_station, [])
            # 割裂规划（decoupled）下重列与空列各自独立规划，空列回送的车底不再被后续重列复用，
            # 因此这里不做周转匹配；协同（integrated）模式下才允许复用已返回的车底。
            usable_index = (
                next(
                    (
                        index
                        for index, available_s in enumerate(returned_times)
                        if available_s <= trainset_needed_s
                    ),
                    None,
                )
                if coordination_mode == COORDINATION_MODE_INTEGRATED
                else None
            )
            needs_virtual_trainset = False
            if usable_index is not None:
                returned_times.pop(usable_index)
            elif initial_trainsets_remaining > 0:
                initial_trainsets_remaining -= 1
            else:
                needs_virtual_trainset = True

            reserve_operation_slot(demand.origin_station, depart - load_s)
            reserve_throat_slot(demand.origin_station, depart)
            if reached_destination:
                reserve_operation_slot(demand.destination_station, arrive)
                reserve_throat_slot(demand.destination_station, arrive)
                delay = max(0, arrive - demand.due_arrival_s)
            else:
                delay = 0
            max_delay_s = max(max_delay_s, delay)
            if delay:
                connection_cost += delay / 60.0 * demand.priority

            slot = depart // scenario.time_slice_s
            section_key = f"{demand.origin_station}->{demand.destination_station}"
            occupied_slots[(section_key, slot)] = occupied_slots.get((section_key, slot), 0) + 1
            elasticity = elasticity_map.get(section_key)
            nominal_capacity = scenario.section_capacity_per_slot
            effective_capacity = nominal_capacity * (
                elasticity.capacity_multiplier if elasticity is not None else 1.0
            )
            occupied = occupied_slots[(section_key, slot)]
            if occupied > effective_capacity:
                # 能力复核：时移后的发车时刻仍需落在区段通过能力之内，越限即记为冲突。
                demand_capacity_overflow = True
                conflict_count += 1
                diagnostics.append(f"{section_key} exceeds slot capacity at {format_s_as_hhmmss(slot * scenario.time_slice_s)}.")
            elif elasticity is not None and occupied > nominal_capacity:
                # 落在弹性边界内：不判硬冲突，按软惩罚系数计入综合成本。
                elastic_relief_count += 1
                elastic_soft_penalty += elasticity.soft_penalty_weight * (occupied - nominal_capacity)
                diagnostics.append(
                    f"{section_key} within elastic boundary at {format_s_as_hhmmss(slot * scenario.time_slice_s)} "
                    f"(occupied {occupied} > nominal {nominal_capacity}, soft penalty applied)."
                )

            throughput += demand.cargo_tons * distance
            delivered += 1

            n0 = HeNode(f"{train_id}:load_start", "demand", demand.demand_id, train_id, demand.origin_station, origin_km, depart - load_s, "load_start")
            n1 = HeNode(f"{train_id}:depart", "service", demand.demand_id, train_id, demand.origin_station, origin_km, depart, "heavy_departure")
            nodes.extend([n0, n1])
            arcs.append(
                HeArc(
                    f"{train_id}:loading",
                    "demand",
                    demand.demand_id,
                    train_id,
                    demand.train_type,
                    n0.node_id,
                    n1.node_id,
                    "loading",
                    demand.origin_station,
                    demand.origin_station,
                    depart - load_s,
                    depart,
                    origin_km,
                    origin_km,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    (),
                    False,
                    0.0,
                    f"station:{demand.origin_station}",
                    "heavy_empty_od_template",
                )
            )
            arrival_node_id = f"{train_id}:arrive"
            if reached_destination:
                nodes.append(
                    HeNode(
                        arrival_node_id,
                        "service",
                        demand.demand_id,
                        train_id,
                        demand.destination_station,
                        dest_km,
                        arrive,
                        "heavy_arrival",
                    )
                )
            heavy_energy, heavy_distance_cost, absorbed_here = _emit_formation_leg_arcs(
                bundle,
                infra_cache,
                nodes,
                arcs,
                plan,
                heavy_operation_plan,
                heavy_formation_nodes,
                demand.demand_id,
                train_id,
                demand.train_type,
                "heavy_running",
                n1.node_id,
                demand.origin_station,
                arrival_node_id,
                demand.destination_station,
            )
            total_energy += heavy_energy
            distance_cost += heavy_distance_cost
            if absorbed_here or not reached_destination:
                # 车底在组合站并入大列：本站之后不再有独立重列运行弧，其空列回送由后续
                # 分解作业的输出车底承接，因此这里不生成空列回送。
                continue

            n2 = HeNode(f"{train_id}:arrive", "service", demand.demand_id, train_id, demand.destination_station, dest_km, arrive, "heavy_arrival")
            n3 = HeNode(f"{train_id}:empty_ready", "demand", demand.demand_id, train_id, demand.destination_station, dest_km, unload_end, "empty_ready")
            nodes.extend([n2, n3])
            arcs.append(
                HeArc(
                    f"{train_id}:unloading",
                    "demand",
                    demand.demand_id,
                    train_id,
                    demand.train_type,
                    n2.node_id,
                    n3.node_id,
                    "unloading",
                    demand.destination_station,
                    demand.destination_station,
                    arrive,
                    unload_end,
                    dest_km,
                    dest_km,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    (),
                    False,
                    0.0,
                    f"station:{demand.destination_station}",
                    "heavy_empty_od_template",
                )
            )
            # 原型空车返回：将卸车端连接回始发需求点。
            empty_service_name = "Empty" if "Empty" in bundle.service_types else demand.train_type
            empty_service = bundle.service_types[empty_service_name]
            empty_train_id = f"{demand.demand_id}:E{copy_idx + 1:02d}"
            empty_plan, empty_operation_plan = _formation_leg_plan(
                bundle,
                empty_operations,
                [copy_idx + 1],
                empty_service_name,
                dest_km,
                origin_km,
                {copy_idx + 1: unload_end},
            )
            # 第四类约束：空列发发间隔 h（卸车站/分解站出发）与到到间隔 g（装车站/分解站到达），
            # 按车站—方向—列型分组。空列运行段时长与出发时刻无关，因此可先由试算得到时长，
            # 再把出发时刻推迟到同时满足两类间隔的最早时刻；推迟量超过最大时移则记为违反。
            # 割裂规划（decoupled）下空列按自身计划即刻回送，不与重列到达做联合间隔协同；
            # 但联合间隔违反仍然如实记录，便于与协同方案做对照。
            empty_duration = int(empty_plan[copy_idx + 1]["time"]) - unload_end
            empty_start = unload_end
            departure_key = _headway_group_key(demand.destination_station, empty_service, dest_km, origin_km)
            arrival_key = _headway_group_key(demand.origin_station, empty_service, dest_km, origin_km)
            required_start = empty_start
            previous_departure = last_empty_departure_by_group.get(departure_key)
            if previous_departure is not None:
                required_start = max(required_start, previous_departure + scenario.min_headway_s)
            previous_arrival = last_empty_arrival_by_group.get(arrival_key)
            if previous_arrival is not None:
                required_start = max(
                    required_start,
                    previous_arrival + scenario.min_arrival_headway_s - empty_duration,
                )
            required_delay = required_start - unload_end
            if required_delay > 0:
                if coordination_mode == COORDINATION_MODE_INTEGRATED:
                    if required_delay > scenario.max_departure_shift_s:
                        arrival_headway_violation_count += 1
                        diagnostics.append(
                            f"{empty_train_id} arrival/departure headway at "
                            f"{demand.origin_station}/{demand.destination_station} needs "
                            f"{required_delay}s delay beyond the "
                            f"{scenario.max_departure_shift_s}s shift limit."
                        )
                        empty_start = unload_end + scenario.max_departure_shift_s
                    else:
                        empty_start = required_start
                else:
                    # 割裂规划不执行联合间隔修复，仅记录违反。
                    arrival_headway_violation_count += 1
                    diagnostics.append(
                        f"{empty_train_id} decoupled empty dispatch violates the joint "
                        f"arrival/departure headway by {required_delay}s at "
                        f"{demand.origin_station}/{demand.destination_station}."
                    )
            if empty_start != unload_end:
                empty_plan, empty_operation_plan = _formation_leg_plan(
                    bundle,
                    empty_operations,
                    [copy_idx + 1],
                    empty_service_name,
                    dest_km,
                    origin_km,
                    {copy_idx + 1: empty_start},
                )
            last_empty_departure_by_group[departure_key] = empty_start
            empty_formation_nodes = _create_formation_station_nodes(
                nodes,
                empty_operation_plan,
                f"E{copy_idx + 1:02d}",
                reserve_operation_slot,
            )
            empty_arrive = int(empty_plan[copy_idx + 1]["time"])
            last_empty_arrival_by_group[arrival_key] = empty_arrive
            reserve_throat_slot(demand.destination_station, empty_start)
            reserve_throat_slot(demand.origin_station, empty_arrive)
            e0 = HeNode(f"{empty_train_id}:depart", "service", demand.demand_id, empty_train_id, demand.destination_station, dest_km, empty_start, "empty_departure")
            e1 = HeNode(f"{empty_train_id}:arrive", "service", demand.demand_id, empty_train_id, demand.origin_station, origin_km, empty_arrive, "empty_arrival")
            nodes.extend([e0, e1])
            if empty_start > unload_end:
                # 空列在卸车站等待至满足发发/到到间隔的最早出发时刻，作为显式等待弧输出。
                arcs.append(
                    HeArc(
                        f"{empty_train_id}:headway_wait",
                        "demand",
                        demand.demand_id,
                        empty_train_id,
                        "Empty",
                        n3.node_id,
                        e0.node_id,
                        "waiting",
                        demand.destination_station,
                        demand.destination_station,
                        unload_end,
                        empty_start,
                        dest_km,
                        dest_km,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        (),
                        False,
                        0.0,
                        f"station:{demand.destination_station}",
                        "arrival_departure_headway_repair",
                    )
                )
            empty_energy, empty_cost, _ = _emit_formation_leg_arcs(
                bundle,
                infra_cache,
                nodes,
                arcs,
                empty_plan[copy_idx + 1],
                empty_operation_plan,
                empty_formation_nodes,
                demand.demand_id,
                empty_train_id,
                "Empty",
                "empty_running",
                e0.node_id,
                demand.destination_station,
                e1.node_id,
                demand.origin_station,
            )
            total_energy += empty_energy
            distance_cost += empty_cost
            _emit_formation_operation_arcs(arcs, empty_operation_plan, empty_formation_nodes)
            returned_trainsets_by_station.setdefault(demand.origin_station, []).append(empty_arrive)
            returned_trainsets_by_station[demand.origin_station].sort()

            if needs_virtual_trainset:
                virtual_count += 1
                virtual_cost += bundle.virtual_trainset.penalty_cost
                arcs.append(
                    HeArc(
                        f"{train_id}:virtual_trainset",
                        "service",
                        demand.demand_id,
                        train_id,
                        demand.train_type,
                        n0.node_id,
                        n0.node_id,
                        "virtual_trainset",
                        bundle.virtual_trainset.virtual_station,
                        demand.origin_station,
                        depart - load_s,
                        depart - load_s,
                        origin_km,
                        origin_km,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        (),
                        False,
                        bundle.virtual_trainset.penalty_cost,
                        "virtual_trainset",
                        "virtual trainset placeholder",
                    )
                )

        _emit_formation_operation_arcs(arcs, heavy_operation_plan, heavy_formation_nodes)
        od_time_shift_rows.append(
            {
                "demand_id": demand.demand_id,
                "origin_station": demand.origin_station,
                "destination_station": demand.destination_station,
                "train_count": demand.train_count,
                "selected_train_count": len(selected),
                "requested_shift_s": requested_shift,
                "applied_shift_s": applied_shift,
                "within_bounds": shift_within_bounds,
                "post_shift_feasible": post_shift_feasible,
                "departure_shift_s": "" if od_departure_delta is None else od_departure_delta,
                "arrival_shift_s": "" if od_arrival_delta is None else od_arrival_delta,
                "od_chain_consistent": od_chain_consistent,
                "capacity_recheck": "ok" if not demand_capacity_overflow else "overflow",
            }
        )


    empty_settlement = EnergySettlementSummary(
        traction_kwh=0.0,
        regen_kwh=0.0,
        direct_used_kwh=0.0,
        battery_charge_kwh=0.0,
        battery_discharge_kwh=0.0,
        battery_charge_limited_kwh=0.0,
        battery_discharge_limited_kwh=0.0,
        wasted_kwh=0.0,
        grid_kwh=0.0,
        traction_supply_excess_kwh=0.0,
        regen_absorption_excess_kwh=0.0,
        final_soc_kwh=0.0,
        final_soc_by_storage_kwh={},
        direct_use_ratio=0.0,
        time_slice_count=0,
        settlement_window_count=0,
    )
    candidate = HeCandidate(
        candidate_id=candidate_id,
        objective_mode=scenario.objective_mode,
        feasible=False,
        constraint_violation=0.0,
        electrical_constraint_violation_kwh=0.0,
        total_cost=0.0,
        energy_kwh=total_energy,
        energy_objective_kwh=0.0,
        distance_cost=distance_cost,
        connection_cost=connection_cost,
        virtual_cost=virtual_cost,
        throughput_ton_km=throughput,
        delivered_train_count=delivered,
        virtual_trainset_count=virtual_count,
        conflict_count=conflict_count,
        max_delay_s=max_delay_s,
        departure_shift_s=departure_shift_s,
        headway_s=headway_s,
        score=0.0,
        energy_settlement=empty_settlement,
        energy_settlement_rows=(),
        nodes=tuple(nodes),
        arcs=tuple(arcs),
        diagnostics=tuple(diagnostics),
        arrival_headway_violation_count=arrival_headway_violation_count,
        od_time_shift_violation_count=od_time_shift_violation_count,
        combined_train_shift_violation_count=combined_train_shift_violation_count,
        od_time_shift_rows=tuple(od_time_shift_rows),
        coordination_mode=coordination_mode,
    )
    settlement, settlement_rows = summarize_energy_settlement(
        candidate,
        scenario.energy_settlement_step_s,
        bundle.battery,
        bundle.power_arm_limits,
        include_rows=False,
    )
    electrical_violation = settlement.traction_supply_excess_kwh + settlement.regen_absorption_excess_kwh
    shift_violation = (
        od_time_shift_violation_count
        + od_chain_violation_count
        + combined_train_shift_violation_count
    )
    constraint_violation = (
        float(conflict_count + arrival_headway_violation_count + shift_violation) + electrical_violation
    )
    feasible = (
        conflict_count == 0
        and arrival_headway_violation_count == 0
        and shift_violation == 0
        and electrical_violation <= ELECTRICAL_CONSTRAINT_TOLERANCE_KWH
    )
    energy_objective = settlement.grid_kwh + storage_no_direct_effective_loss_kwh(
        settlement.wasted_kwh,
        settlement.battery_charge_kwh,
        settlement.battery_discharge_kwh,
        settlement.final_soc_kwh,
        bundle.battery.round_trip_efficiency,
    )
    total_cost = (
        scenario.weight_energy * energy_objective
        + scenario.weight_distance * distance_cost
        + scenario.weight_connection * connection_cost
        + scenario.weight_virtual * virtual_cost
        + elastic_soft_penalty
    )
    if scenario.objective_mode == OBJECTIVE_MODE_CAPACITY_TIGHT:
        score = total_cost - scenario.weight_throughput * throughput / 1000.0
    else:
        score = total_cost
    if not feasible:
        score += constraint_violation * 1_000_000.0
    return replace(
        candidate,
        feasible=feasible,
        constraint_violation=constraint_violation,
        electrical_constraint_violation_kwh=electrical_violation,
        total_cost=total_cost,
        energy_objective_kwh=energy_objective,
        score=score,
        energy_settlement=settlement,
        energy_settlement_rows=settlement_rows,
        elastic_soft_penalty=elastic_soft_penalty,
        elastic_relief_count=elastic_relief_count,
        throat_conflict_count=throat_conflict_count,
    )


def _objective_tuple(candidate: HeCandidate) -> Tuple[float, ...]:
    """函数 _objective_tuple：执行该模块中的相关处理逻辑。"""
    if candidate.objective_mode == OBJECTIVE_MODE_CAPACITY_TIGHT:
        return (
            candidate.constraint_violation,
            -candidate.throughput_ton_km,
            candidate.energy_objective_kwh,
            candidate.distance_cost,
            candidate.connection_cost,
            candidate.virtual_cost,
        )
    return (
        candidate.constraint_violation,
        candidate.energy_objective_kwh,
        candidate.distance_cost,
        candidate.connection_cost,
        candidate.virtual_cost,
        -candidate.throughput_ton_km,
    )


def pareto_front(candidates: Sequence[HeCandidate]) -> Tuple[HeCandidate, ...]:
    # 用户选择的 Pareto 输出遵循正式运行图优化器的相同规则：不可行候选不能进入 Pareto 前沿。
    """函数 pareto_front：执行该模块中的相关处理逻辑。"""
    eligible = [candidate for candidate in candidates if candidate.feasible]
    front: List[HeCandidate] = []
    seen_objectives: set[Tuple[float, ...]] = set()
    for candidate in eligible:
        dominated = False
        objectives = _objective_tuple(candidate)
        for other in eligible:
            if other.candidate_id == candidate.candidate_id:
                continue
            if _dominates(other, candidate):
                dominated = True
                break
        if not dominated:
            objective_key = tuple(round(value, 6) for value in objectives)
            if objective_key in seen_objectives:
                continue
            seen_objectives.add(objective_key)
            front.append(candidate)
    return tuple(sorted(front, key=lambda item: item.score))


def _dominates(left: HeCandidate, right: HeCandidate) -> bool:
    """函数 _dominates：执行该模块中的相关处理逻辑。"""
    if left.feasible != right.feasible:
        return left.feasible
    if not left.feasible:
        return left.constraint_violation < right.constraint_violation
    left_objectives = _objective_tuple(left)
    right_objectives = _objective_tuple(right)
    no_worse = all(l <= r for l, r in zip(left_objectives, right_objectives))
    better = any(l < r for l, r in zip(left_objectives, right_objectives))
    return no_worse and better


def non_dominated_sort(candidates: Sequence[HeCandidate]) -> List[List[HeCandidate]]:
    """Return NSGA-II style non-dominated fronts."""

    dominates: Dict[str, List[str]] = {candidate.candidate_id: [] for candidate in candidates}
    dominated_count: Dict[str, int] = {candidate.candidate_id: 0 for candidate in candidates}
    by_id = {candidate.candidate_id: candidate for candidate in candidates}

    first_front: List[HeCandidate] = []
    for candidate in candidates:
        for other in candidates:
            if candidate.candidate_id == other.candidate_id:
                continue
            if _dominates(candidate, other):
                dominates[candidate.candidate_id].append(other.candidate_id)
            elif _dominates(other, candidate):
                dominated_count[candidate.candidate_id] += 1
        if dominated_count[candidate.candidate_id] == 0:
            first_front.append(candidate)

    fronts: List[List[HeCandidate]] = []
    current = first_front
    while current:
        fronts.append(sorted(current, key=lambda item: item.score))
        next_front: List[HeCandidate] = []
        for candidate in current:
            for dominated_id in dominates[candidate.candidate_id]:
                dominated_count[dominated_id] -= 1
                if dominated_count[dominated_id] == 0:
                    next_front.append(by_id[dominated_id])
        current = next_front
    return fronts


def crowding_distance(front: Sequence[HeCandidate]) -> Dict[str, float]:
    """Calculate NSGA-II crowding distance inside one front."""

    if not front:
        return {}
    distances = {candidate.candidate_id: 0.0 for candidate in front}
    objective_count = len(_objective_tuple(front[0]))
    if len(front) <= 2:
        return {candidate.candidate_id: float("inf") for candidate in front}
    for objective_idx in range(objective_count):
        ordered = sorted(front, key=lambda item: _objective_tuple(item)[objective_idx])
        distances[ordered[0].candidate_id] = float("inf")
        distances[ordered[-1].candidate_id] = float("inf")
        low = _objective_tuple(ordered[0])[objective_idx]
        high = _objective_tuple(ordered[-1])[objective_idx]
        span = high - low
        if abs(span) < 1e-12:
            continue
        for idx in range(1, len(ordered) - 1):
            prev_value = _objective_tuple(ordered[idx - 1])[objective_idx]
            next_value = _objective_tuple(ordered[idx + 1])[objective_idx]
            distances[ordered[idx].candidate_id] += (next_value - prev_value) / span
    return distances


def _select_next_generation(candidates: Sequence[HeCandidate], population_size: int) -> List[HeCandidate]:
    """函数 _select_next_generation：执行该模块中的相关处理逻辑。"""
    selected: List[HeCandidate] = []
    for front in non_dominated_sort(candidates):
        if len(selected) + len(front) <= population_size:
            selected.extend(front)
            continue
        distances = crowding_distance(front)
        selected.extend(
            sorted(front, key=lambda item: (-distances.get(item.candidate_id, 0.0), item.score))[
                : max(0, population_size - len(selected))
            ]
        )
        break
    return selected


def _clamp_genome(genome: HeGenome, scenario: HeScenario, total_requested_trains: int) -> HeGenome:
    """函数 _clamp_genome：执行该模块中的相关处理逻辑。"""
    max_headway = max(scenario.min_headway_s, scenario.min_headway_s + scenario.time_slice_s * 4)
    max_services = genome.max_heavy_services
    if max_services is not None:
        max_services = min(max(1, int(max_services)), max(1, total_requested_trains))
    return HeGenome(
        departure_shift_s=min(
            max(-scenario.max_departure_shift_s, int(genome.departure_shift_s)),
            scenario.max_departure_shift_s,
        ),
        headway_s=min(max(scenario.min_headway_s, int(genome.headway_s)), max_headway),
        max_heavy_services=max_services,
    )


def _initial_genomes(scenario: HeScenario, total_requested_trains: int, rng: random.Random) -> List[HeGenome]:
    """函数 _initial_genomes：执行该模块中的相关处理逻辑。"""
    base_headway = max(scenario.min_headway_s, scenario.time_slice_s)
    step = max(60, scenario.time_slice_s // 3)
    genomes: List[HeGenome] = [HeGenome(0, base_headway, None)]
    shift_values = list(range(0, scenario.max_departure_shift_s + 1, step))
    if scenario.max_departure_shift_s not in shift_values:
        shift_values.append(scenario.max_departure_shift_s)
    shift_values += [-value for value in shift_values if value]
    for idx in range(1, scenario.population_size):
        shift = rng.choice(shift_values)
        headway = base_headway + rng.randrange(0, max(scenario.time_slice_s * 3, 60) + 1, step)
        max_services = None
        if scenario.objective_mode == OBJECTIVE_MODE_CAPACITY_TIGHT and total_requested_trains > 1:
            max_services = 1 + (idx % total_requested_trains)
        genomes.append(_clamp_genome(HeGenome(shift, headway, max_services), scenario, total_requested_trains))
    return genomes


def _adaptive_rates(generation: int, generations: int, parent_scores: Sequence[float]) -> Tuple[float, float]:
    """函数 _adaptive_rates：执行该模块中的相关处理逻辑。"""
    if generations <= 1:
        progress = 1.0
    else:
        progress = generation / float(generations - 1)
    diversity = len({round(score, 6) for score in parent_scores}) / max(1, len(parent_scores))
    crossover_rate = min(0.9, max(0.55, 0.78 - 0.18 * progress + 0.10 * diversity))
    mutation_rate = min(0.55, max(0.12, 0.18 + 0.22 * progress + 0.15 * (1.0 - diversity)))
    return crossover_rate, mutation_rate


def _crossover(left: HeGenome, right: HeGenome, rng: random.Random, scenario: HeScenario, total_requested_trains: int) -> HeGenome:
    """函数 _crossover：执行该模块中的相关处理逻辑。"""
    shift = left.departure_shift_s if rng.random() < 0.5 else right.departure_shift_s
    headway = int(round((left.headway_s + right.headway_s) / 2.0))
    if left.max_heavy_services is None:
        max_services = right.max_heavy_services
    elif right.max_heavy_services is None:
        max_services = left.max_heavy_services
    else:
        max_services = rng.choice([left.max_heavy_services, right.max_heavy_services])
    return _clamp_genome(HeGenome(shift, headway, max_services), scenario, total_requested_trains)


def _mutate(genome: HeGenome, rng: random.Random, scenario: HeScenario, total_requested_trains: int) -> HeGenome:
    """函数 _mutate：执行该模块中的相关处理逻辑。"""
    step = max(60, scenario.time_slice_s // 3)
    shift = genome.departure_shift_s + rng.choice([-step, 0, step])
    headway = genome.headway_s + rng.choice([-step, 0, step])
    max_services = genome.max_heavy_services
    if scenario.objective_mode == OBJECTIVE_MODE_CAPACITY_TIGHT and total_requested_trains > 1:
        if max_services is None:
            max_services = total_requested_trains
        max_services += rng.choice([-1, 0, 1])
    return _clamp_genome(HeGenome(shift, headway, max_services), scenario, total_requested_trains)


def _candidate_from_genome(
    bundle: HeInputBundle,
    scenario: HeScenario,
    genome: HeGenome,
    candidate_id: str,
    infra_cache: Dict[Tuple[float, float], ArcInfrastructureAttributes],
    coordination_mode: str = COORDINATION_MODE_INTEGRATED,
) -> HeCandidate:
    """函数 _candidate_from_genome：执行该模块中的相关处理逻辑。"""
    return _build_candidate(
        bundle,
        scenario,
        candidate_id,
        genome.departure_shift_s,
        genome.headway_s,
        genome.max_heavy_services,
        infra_cache,
        coordination_mode=coordination_mode,
    )


def _materialize_candidate_settlement_rows(
    candidate: HeCandidate,
    bundle: HeInputBundle,
    scenario: HeScenario,
) -> HeCandidate:
    """为最终展示候选补建完整结算明细，搜索阶段只保留数值摘要。"""

    if candidate.energy_settlement_rows:
        return candidate
    settlement, settlement_rows = summarize_energy_settlement(
        candidate,
        scenario.energy_settlement_step_s,
        bundle.battery,
        bundle.power_arm_limits,
        include_rows=True,
    )
    return replace(
        candidate,
        energy_settlement=settlement,
        energy_settlement_rows=settlement_rows,
    )


def optimize_heavy_empty_network(
    bundle: HeInputBundle,
    scenario_id: str,
    coordination_mode: str = COORDINATION_MODE_INTEGRATED,
) -> HeOptimizationResult:
    """函数 optimize_heavy_empty_network：执行该模块中的相关处理逻辑。"""
    if scenario_id not in bundle.scenarios:
        raise KeyError(f"Scenario {scenario_id!r} not found in template.")
    if coordination_mode not in COORDINATION_MODES:
        raise ValueError(f"unsupported coordination_mode: {coordination_mode!r}")
    scenario = bundle.scenarios[scenario_id]
    rng = random.Random(scenario.seed)
    total_requested_trains = sum(demand.train_count for demand in bundle.demands)
    population = _initial_genomes(scenario, total_requested_trains, rng)
    all_candidates: List[HeCandidate] = []
    current_candidates: List[HeCandidate] = []
    infra_cache: Dict[Tuple[float, float], ArcInfrastructureAttributes] = {}
    evaluation_cache: Dict[HeGenome, HeCandidate] = {}

    for generation in range(scenario.generations):
        current_candidates = []
        for idx, genome in enumerate(population):
            candidate_id = f"G{generation:02d}_I{idx + 1:03d}"
            cached = evaluation_cache.get(genome)
            if cached is None:
                candidate = _candidate_from_genome(
                    bundle,
                    scenario,
                    genome,
                    candidate_id,
                    infra_cache,
                    coordination_mode=coordination_mode,
                )
                evaluation_cache[genome] = candidate
            else:
                # 节点、弧段和摘要均由基因组唯一决定，可以安全共享不可变对象。
                candidate = replace(cached, candidate_id=candidate_id)
            current_candidates.append(candidate)
        all_candidates.extend(current_candidates)
        parents = _select_next_generation(current_candidates, max(2, scenario.population_size))
        if generation == scenario.generations - 1:
            break

        crossover_rate, mutation_rate = _adaptive_rates(
            generation,
            scenario.generations,
            [candidate.score for candidate in parents],
        )
        parent_genomes = [
            HeGenome(candidate.departure_shift_s, candidate.headway_s, None if scenario.objective_mode != OBJECTIVE_MODE_CAPACITY_TIGHT else candidate.delivered_train_count)
            for candidate in parents
        ]
        next_population = parent_genomes[: max(1, min(len(parent_genomes), scenario.population_size // 4))]
        while len(next_population) < scenario.population_size:
            left = rng.choice(parent_genomes)
            right = rng.choice(parent_genomes)
            child = _crossover(left, right, rng, scenario, total_requested_trains) if rng.random() < crossover_rate else left
            if rng.random() < mutation_rate:
                child = _mutate(child, rng, scenario, total_requested_trains)
            next_population.append(_clamp_genome(child, scenario, total_requested_trains))
        population = next_population[: scenario.population_size]

    ranked_without_rows = tuple(sorted(all_candidates, key=lambda item: item.score))
    front_without_rows = pareto_front(ranked_without_rows)
    best_pool = [candidate for candidate in ranked_without_rows if candidate.feasible] or list(ranked_without_rows)
    best_without_rows = min(best_pool, key=lambda item: item.score)
    best = _materialize_candidate_settlement_rows(best_without_rows, bundle, scenario)
    ranked = tuple(
        best if candidate.candidate_id == best.candidate_id else candidate
        for candidate in ranked_without_rows
    )
    front = tuple(
        best if candidate.candidate_id == best.candidate_id else candidate
        for candidate in front_without_rows
    )
    return HeOptimizationResult(
        scenario=scenario,
        candidates=ranked,
        pareto_candidates=front,
        best_candidate=best,
        infrastructure_notes=bundle.infrastructure.source_notes,
    )


def candidate_rows(candidates: Iterable[HeCandidate], candidate_set: str) -> List[Dict[str, object]]:
    """函数 candidate_rows：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, object]] = []
    for rank, candidate in enumerate(candidates, start=1):
        per_transport = energy_per_transport(candidate)
        rows.append(
            {
                "candidate_set": candidate_set,
                "rank": rank,
                "candidate_id": candidate.candidate_id,
                "generation": candidate.candidate_id.split("_", 1)[0] if "_" in candidate.candidate_id else "",
                "objective_mode": candidate.objective_mode,
                "feasible": candidate.feasible,
                "constraint_violation": round(candidate.constraint_violation, 6),
                "electrical_constraint_violation_kwh": round(candidate.electrical_constraint_violation_kwh, 6),
                "score": round(candidate.score, 6),
                "total_cost": round(candidate.total_cost, 6),
                "energy_kwh": round(candidate.energy_kwh, 6),
                "energy_objective_kwh": round(candidate.energy_objective_kwh, 6),
                "energy_per_1000_ton_km": per_transport["energy_per_1000_ton_km"],
                "energy_per_ton_km": per_transport["energy_per_ton_km"],
                "traction_kwh": round(candidate.energy_settlement.traction_kwh, 6),
                "regen_kwh": round(candidate.energy_settlement.regen_kwh, 6),
                "direct_used_kwh": round(candidate.energy_settlement.direct_used_kwh, 6),
                "battery_charge_kwh": round(candidate.energy_settlement.battery_charge_kwh, 6),
                "battery_discharge_kwh": round(candidate.energy_settlement.battery_discharge_kwh, 6),
                "battery_charge_limited_kwh": round(candidate.energy_settlement.battery_charge_limited_kwh, 6),
                "battery_discharge_limited_kwh": round(candidate.energy_settlement.battery_discharge_limited_kwh, 6),
                "wasted_kwh": round(candidate.energy_settlement.wasted_kwh, 6),
                "grid_kwh": round(candidate.energy_settlement.grid_kwh, 6),
                "traction_supply_excess_kwh": round(candidate.energy_settlement.traction_supply_excess_kwh, 6),
                "regen_absorption_excess_kwh": round(candidate.energy_settlement.regen_absorption_excess_kwh, 6),
                "final_soc_kwh": round(candidate.energy_settlement.final_soc_kwh, 6),
                "direct_use_ratio": round(candidate.energy_settlement.direct_use_ratio, 6),
                "energy_time_slice_count": candidate.energy_settlement.time_slice_count,
                "energy_settlement_window_count": candidate.energy_settlement.settlement_window_count,
                "distance_cost": round(candidate.distance_cost, 6),
                "connection_cost": round(candidate.connection_cost, 6),
                "virtual_cost": round(candidate.virtual_cost, 6),
                "throughput_ton_km": round(candidate.throughput_ton_km, 6),
                "delivered_train_count": candidate.delivered_train_count,
                "virtual_trainset_count": candidate.virtual_trainset_count,
                "conflict_count": candidate.conflict_count,
                "arrival_headway_violation_count": candidate.arrival_headway_violation_count,
                "od_time_shift_violation_count": candidate.od_time_shift_violation_count,
                "combined_train_shift_violation_count": candidate.combined_train_shift_violation_count,
                "elastic_soft_penalty": round(candidate.elastic_soft_penalty, 6),
                "elastic_relief_count": candidate.elastic_relief_count,
                "max_delay_s": candidate.max_delay_s,
                "departure_shift_s": candidate.departure_shift_s,
                "headway_s": candidate.headway_s,
                "diagnostics": " | ".join(candidate.diagnostics),
            }
        )
    return rows


def node_rows(candidate: HeCandidate) -> List[Dict[str, object]]:
    """函数 node_rows：执行该模块中的相关处理逻辑。"""
    return [
        {
            "candidate_id": candidate.candidate_id,
            "node_id": node.node_id,
            "layer": node.layer,
            "demand_id": node.demand_id,
            "train_id": node.train_id,
            "station_name": node.station_name,
            "position_km": round(node.position_km, 6),
            "time_s": node.time_s,
            "time": format_s_as_hhmmss(node.time_s),
            "state": node.state,
        }
        for node in candidate.nodes
    ]


def arc_rows(candidate: HeCandidate) -> List[Dict[str, object]]:
    """函数 arc_rows：执行该模块中的相关处理逻辑。"""
    return [
        {
            "candidate_id": candidate.candidate_id,
            "arc_id": arc.arc_id,
            "parent_arc_id": arc.parent_arc_id,
            "segment_index": arc.segment_index,
            "segment_count": arc.segment_count,
            "power_arm_split": arc.power_arm_split,
            "layer": arc.layer,
            "demand_id": arc.demand_id,
            "train_id": arc.train_id,
            "train_type": arc.train_type,
            "from_node_id": arc.from_node_id,
            "to_node_id": arc.to_node_id,
            "arc_type": arc.arc_type,
            "start_station": arc.start_station,
            "end_station": arc.end_station,
            "start_time_s": arc.start_time_s,
            "end_time_s": arc.end_time_s,
            "start_time": format_s_as_hhmmss(arc.start_time_s),
            "end_time": format_s_as_hhmmss(arc.end_time_s),
            "start_km": round(arc.start_km, 6),
            "end_km": round(arc.end_km, 6),
            "distance_km": round(arc.distance_km, 6),
            "energy_kwh": round(arc.energy_kwh, 6),
            "base_energy_kwh": round(arc.base_energy_kwh, 6),
            "regen_energy_kwh": round(arc.regen_energy_kwh, 6),
            "traction_energy_kwh": round(arc.energy_kwh + arc.regen_energy_kwh, 6),
            "energy_adjustment_kwh": round(arc.energy_kwh - arc.base_energy_kwh, 6),
            "avg_gradient_promille": round(arc.avg_gradient_promille, 6),
            "curve_equivalent": round(arc.curve_equivalent, 6),
            "power_arm_ids": ";".join(arc.power_arm_ids),
            "power_arm_review_required": arc.power_arm_review_required,
            "storage_section_id": arc.storage_section_id,
            "cost": round(arc.cost, 6),
            "capacity_resource_id": arc.capacity_resource_id,
            "source": arc.source,
        }
        for arc in candidate.arcs
    ]


def _write_csv(path: Path, rows: Sequence[Dict[str, object]]) -> None:
    """函数 _write_csv：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _service_size_class(service: ServiceType) -> str:
    """Map a service definition to the technical-plan large/small train class."""
    category = str(service.formation_category or "").lower()
    mode = str(service.formation_mode or "").lower()
    is_large = (
        service.consist_unit >= 2
        or "combined" in category
        or "two_10000" in category
        or mode in {"1+1", "2+0"}
    )
    return "large" if is_large else "small"


def _headway_group_key(
    station_name: str,
    service: ServiceType,
    start_km: float,
    end_km: float,
) -> Tuple[str, str, str]:
    """列车间隔分组键：按车站、运行方向与列型分类分组（技术方案第四类约束口径）。"""
    return (station_name, _travel_direction(start_km, end_km), _service_size_class(service))


def _first_running_arcs(candidate: HeCandidate) -> List[HeArc]:
    rows: Dict[Tuple[str, str], HeArc] = {}
    for arc in candidate.arcs:
        if arc.arc_type not in {"heavy_running", "empty_running"}:
            continue
        key = (arc.train_id, arc.arc_type)
        current = rows.get(key)
        if current is None or (arc.start_time_s, arc.segment_index) < (
            current.start_time_s,
            current.segment_index,
        ):
            rows[key] = arc
    return sorted(rows.values(), key=lambda arc: (arc.start_time_s, arc.train_id))


DISPATCH_SCHEME_OUTPUT_FILES: Tuple[str, ...] = (
    "periodic_headway_recommendations.csv",
    "od_large_small_train_ratio.csv",
    "combination_station_connection_rhythm.csv",
    "station_wait_bounds.csv",
    "section_station_capacity_utilization.csv",
)
"""重空协同调度方案的五类业务输出文件名（与技术方案五类派生输出一一对应）。"""

ENERGY_PER_TRANSPORT_UNIT = "kWh/(千吨·km)"
"""单位运量能耗的主口径单位（技术方案解释性指标「单位运量能耗」）。"""

SHIFT_BOUNDARY_HOURS: Tuple[int, ...] = (0, 8, 16)
"""换班边界小时（三班制 0/8/16 点），用于二级择优的「换班友好性」。"""

SECONDARY_RANKING_WEIGHTS: Dict[str, float] = {
    "timetable_smoothness": 1.0,
    "operation_balance": 1.0,
    "shift_friendliness": 1.0,
}
"""二级择优三项子指标的默认权重（等权）。"""

CONGESTION_RISK_FREE_UTILIZATION = 0.6
"""拥堵风险指数为 0 的容量利用率阈值：利用率不高于该值视为无拥堵风险。"""


def energy_per_transport(candidate: HeCandidate) -> Dict[str, float]:
    """单位运量能耗（技术方案解释性指标）：总能耗 / 货物周转量。

    返回 ``kWh/(千吨·km)`` 与 ``kWh/(吨·km)`` 两种口径；周转量为 0 时返回 0.0，
    避免除零并把「无运量」与「零能耗」区分开（调用方可通过周转量字段判别）。
    """
    throughput = float(candidate.throughput_ton_km)
    energy = float(candidate.energy_kwh)
    if throughput <= 0.0:
        return {"energy_per_1000_ton_km": 0.0, "energy_per_ton_km": 0.0}
    per_ton_km = energy / throughput
    return {
        "energy_per_1000_ton_km": round(per_ton_km * 1000.0, 6),
        "energy_per_ton_km": round(per_ton_km, 9),
    }


def _coefficient_of_variation(values: Sequence[float]) -> float:
    """变异系数（标准差 / 均值）；样本少于 2 或均值为 0 时返回 0.0。"""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean <= 0.0:
        return 0.0
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance) / mean


def _timetable_smoothness(candidate: HeCandidate) -> float:
    """时刻平滑度（0–1，越大越好）：各列型发车时刻间隔的规整程度。

    对每种列型的首发车时刻求相邻间隔，计算间隔的变异系数 ``cv``，
    以 ``1/(1+cv)`` 映射到 (0,1]：间隔完全均匀时为 1，波动越大越接近 0。
    多种列型取算术平均。
    """
    first_runs = _first_running_arcs(candidate)
    by_type: Dict[str, List[int]] = defaultdict(list)
    for arc in first_runs:
        by_type[arc.train_type].append(arc.start_time_s)
    scores: List[float] = []
    for times in by_type.values():
        ordered = sorted(times)
        gaps = [right - left for left, right in zip(ordered, ordered[1:])]
        cv = _coefficient_of_variation([float(gap) for gap in gaps])
        scores.append(1.0 / (1.0 + cv))
    if not scores:
        return 1.0
    return sum(scores) / len(scores)


def _operation_balance(candidate: HeCandidate, bundle: Optional[HeInputBundle]) -> float:
    """作业均衡度（0–1，越大越好）：各车站作业量分布的均匀程度。

    统计装/卸/组合/拆解/技术作业事件在各站的分布，计算站间作业量的变异系数 ``cv``，
    以 ``1/(1+cv)`` 映射到 (0,1]：各站作业量越接近越接近 1。
    """
    operation_arcs = [
        arc
        for arc in candidate.arcs
        if arc.arc_type in {"loading", "unloading", "combining", "dismantling", "technical_operation"}
    ]
    if not operation_arcs:
        return 1.0
    counts: Dict[str, int] = defaultdict(int)
    for arc in operation_arcs:
        counts[arc.start_station] += 1
    cv = _coefficient_of_variation([float(value) for value in counts.values()])
    return 1.0 / (1.0 + cv)


def _shift_boundaries(max_time_s: int) -> List[int]:
    """按三班制换班边界（每 8 小时一个边界）生成覆盖时间窗的边界时刻。"""
    step = 8 * 3600
    boundaries: List[int] = []
    boundary = 0
    while boundary <= max_time_s:
        boundaries.append(boundary)
        boundary += step
    return boundaries


def _shift_friendliness(candidate: HeCandidate) -> float:
    """换班友好性（0–1，越大越好）：作业/运行事件不跨越换班边界的比例。

    事件 ``[start, end)`` 若严格跨越某个换班边界（``start < boundary < end``），
    视为需要中途交接、对换班不友好。返回 ``1 - 跨越事件数 / 事件总数``。
    """
    work_arcs = [
        arc
        for arc in candidate.arcs
        if arc.arc_type
        in {
            "heavy_running",
            "empty_running",
            "loading",
            "unloading",
            "combining",
            "dismantling",
            "technical_operation",
        }
        and arc.end_time_s > arc.start_time_s
    ]
    if not work_arcs:
        return 1.0
    max_time = max(arc.end_time_s for arc in work_arcs)
    boundaries = _shift_boundaries(max_time)
    straddled = 0
    for arc in work_arcs:
        if any(arc.start_time_s < boundary < arc.end_time_s for boundary in boundaries):
            straddled += 1
    return 1.0 - straddled / len(work_arcs)


def secondary_ranking_metrics(
    candidate: HeCandidate,
    bundle: Optional[HeInputBundle] = None,
) -> Dict[str, float]:
    """二级择优指标（技术方案：多解同优时按时刻平滑度/作业均衡度/换班友好性择优）。

    返回三项子指标与加权综合 ``secondary_ranking_score``（0–1，越大越好）。
    该指标为**后处理决策支持层**，不进入 NSGA-II 适应度，故不改变既有搜索轨迹。
    """
    smoothness = _timetable_smoothness(candidate)
    balance = _operation_balance(candidate, bundle)
    friendliness = _shift_friendliness(candidate)
    weight_sum = sum(SECONDARY_RANKING_WEIGHTS.values())
    if weight_sum <= 0.0:
        combined = 0.0
    else:
        combined = (
            SECONDARY_RANKING_WEIGHTS["timetable_smoothness"] * smoothness
            + SECONDARY_RANKING_WEIGHTS["operation_balance"] * balance
            + SECONDARY_RANKING_WEIGHTS["shift_friendliness"] * friendliness
        ) / weight_sum
    return {
        "timetable_smoothness": round(smoothness, 6),
        "operation_balance": round(balance, 6),
        "shift_friendliness": round(friendliness, 6),
        "secondary_ranking_score": round(combined, 6),
    }


def secondary_ranking_rows(
    result: HeOptimizationResult,
    bundle: Optional[HeInputBundle] = None,
    *,
    tie_tolerance: float = 1e-6,
) -> List[Dict[str, object]]:
    """二级择优明细：按主目标并列分组，组内按二级分降序给出择优次序。

    - ``primary_rank``：候选在主目标（``score``）升序下的名次（沿用既有排序）。
    - ``tie_group_id``：主目标并列（差值在 ``tie_tolerance`` 内）的候选归为同一组。
    - ``rank_within_tie``：组内按 ``secondary_ranking_score`` 降序的名次（1 为组内最优）。
    - ``secondary_selected``：该候选是否为所在并列组的二级择优结果。
    """
    candidates = list(result.candidates)
    rows: List[Dict[str, object]] = []
    group_index = -1
    index = 0
    while index < len(candidates):
        group_index += 1
        base_score = candidates[index].score
        group: List[HeCandidate] = []
        while index < len(candidates) and abs(candidates[index].score - base_score) <= tie_tolerance:
            group.append(candidates[index])
            index += 1
        metrics = {candidate.candidate_id: secondary_ranking_metrics(candidate, bundle) for candidate in group}
        ordered = sorted(
            group,
            key=lambda item: (-metrics[item.candidate_id]["secondary_ranking_score"], item.candidate_id),
        )
        best_id = ordered[0].candidate_id
        for within, candidate in enumerate(ordered, start=1):
            metric = metrics[candidate.candidate_id]
            rows.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "primary_rank": rows.__len__() + 1,
                    "tie_group_id": group_index,
                    "tie_group_size": len(group),
                    "score": round(candidate.score, 6),
                    "feasible": candidate.feasible,
                    "timetable_smoothness": metric["timetable_smoothness"],
                    "operation_balance": metric["operation_balance"],
                    "shift_friendliness": metric["shift_friendliness"],
                    "secondary_ranking_score": metric["secondary_ranking_score"],
                    "rank_within_tie": within,
                    "secondary_selected": candidate.candidate_id == best_id,
                }
            )
    return rows


def _capacity_utilization_rows(
    candidate: HeCandidate,
    scenario: HeScenario,
    bundle: Optional[HeInputBundle],
) -> List[Dict[str, object]]:
    """按 (资源类型, 资源 id, 时间片) 统计容量占用与利用率。

    区段资源取 ``section_capacity_per_slot``；车站资源取作业节点 ``capacity_per_slot``。
    """
    slot_s = scenario.time_slice_s
    operation_nodes = bundle.operation_nodes if bundle else {}
    usage: Dict[Tuple[str, str, int], set[str]] = defaultdict(set)
    for arc in candidate.arcs:
        if arc.end_time_s <= arc.start_time_s:
            continue
        if arc.arc_type in {"heavy_running", "empty_running"}:
            resource_type = "section"
            resource_id = arc.capacity_resource_id
        elif arc.arc_type in {"loading", "unloading", "combining", "dismantling", "technical_operation", "waiting"}:
            resource_type = "station"
            resource_id = f"station:{arc.start_station}"
        else:
            continue
        first_slot = arc.start_time_s // slot_s
        last_slot = max(first_slot, (arc.end_time_s - 1) // slot_s)
        for slot in range(first_slot, last_slot + 1):
            usage[(resource_type, resource_id, slot)].add(arc.train_id)
    rows: List[Dict[str, object]] = []
    for (resource_type, resource_id, slot), train_ids in sorted(usage.items()):
        if resource_type == "section":
            capacity = scenario.section_capacity_per_slot
        else:
            station = resource_id.split(":", 1)[1]
            operation = operation_nodes.get(station)
            capacity = operation.capacity_per_slot if operation else 1
        used = len(train_ids)
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "period_start_s": slot * slot_s,
                "period_end_s": (slot + 1) * slot_s,
                "used_train_count": used,
                "capacity_per_slot": capacity,
                "utilization_ratio": round(used / capacity, 6) if capacity else 0.0,
                "over_capacity": used > capacity,
                "basis": "distinct_train_occupancy_by_capacity_slot",
            }
        )
    return rows


def _congestion_risk_index(utilization_ratio: float) -> float:
    """拥堵风险指数（0–1）：利用率在阈值以下为 0，达到/超过容量为 1。"""
    if utilization_ratio <= CONGESTION_RISK_FREE_UTILIZATION:
        return 0.0
    span = 1.0 - CONGESTION_RISK_FREE_UTILIZATION
    return round(min(1.0, (utilization_ratio - CONGESTION_RISK_FREE_UTILIZATION) / span), 6)


def congestion_risk_rows(
    result: HeOptimizationResult,
    bundle: Optional[HeInputBundle] = None,
) -> List[Dict[str, object]]:
    """拥堵风险指数明细（技术方案解释性指标「瓶颈拥堵风险」）。

    按 (区段/车站, 时间片) 输出拥堵风险指数（0–1），可按区段/车站/时段定位。
    风险由容量利用率非线性映射：``util <= 0.6`` 为 0，``util >= 1.0`` 为 1。
    """
    candidate = result.best_candidate
    rows: List[Dict[str, object]] = []
    for row in _capacity_utilization_rows(candidate, result.scenario, bundle):
        utilization = float(row["utilization_ratio"])
        rows.append(
            {
                **row,
                "congestion_risk_index": _congestion_risk_index(utilization),
                "basis": "capacity_utilization_nonlinear_risk_mapping",
            }
        )
    return rows


def corridor_capacity_rows(
    candidate: HeCandidate,
    scenario: HeScenario,
    bundle: Optional[HeInputBundle] = None,
) -> List[Dict[str, object]]:
    """按 (OD 区段走廊, 时间片) 统计发车占用、利用率与拥堵风险。

    口径与 ``_build_candidate`` 的区段通过能力复核一致：走廊键为 ``"始发站->终到站"``，
    能力取 ``scenario.section_capacity_per_slot``；``section_elasticity`` 也按该键声明。
    每个车底按首发重列运行弧的出发时刻占用一个时间片。
    """
    slot_s = scenario.time_slice_s
    demand_by_id = {item.demand_id: item for item in bundle.demands} if bundle else {}
    first_by_train: Dict[str, HeArc] = {}
    for arc in candidate.arcs:
        if arc.arc_type != "heavy_running":
            continue
        current = first_by_train.get(arc.train_id)
        if current is None or (arc.start_time_s, arc.segment_index) < (
            current.start_time_s,
            current.segment_index,
        ):
            first_by_train[arc.train_id] = arc
    usage: Dict[Tuple[str, int], int] = defaultdict(int)
    for arc in first_by_train.values():
        demand = demand_by_id.get(arc.demand_id)
        origin = demand.origin_station if demand else arc.start_station
        destination = demand.destination_station if demand else arc.end_station
        usage[(f"{origin}->{destination}", arc.start_time_s // slot_s)] += 1
    rows: List[Dict[str, object]] = []
    for (section_key, slot), used in sorted(usage.items()):
        capacity = scenario.section_capacity_per_slot
        utilization = used / capacity if capacity else 0.0
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "section_key": section_key,
                "period_start_s": slot * slot_s,
                "period_end_s": (slot + 1) * slot_s,
                "used_train_count": used,
                "capacity_per_slot": capacity,
                "utilization_ratio": round(utilization, 6),
                "over_capacity": used > capacity,
                "congestion_risk_index": _congestion_risk_index(utilization),
                "basis": "corridor_departure_occupancy_matches_capacity_check",
            }
        )
    return rows


def dispatch_plan_output_rows(
    result: HeOptimizationResult,
    bundle: Optional[HeInputBundle],
) -> Dict[str, List[Dict[str, object]]]:
    """Build the five scheme outputs required by the heavy-empty dispatch plan."""
    candidate = result.best_candidate
    scenario = result.scenario
    slot_s = scenario.time_slice_s
    first_runs = _first_running_arcs(candidate)

    departure_groups: Dict[Tuple[int, str], List[int]] = defaultdict(list)
    for arc in first_runs:
        departure_groups[(arc.start_time_s // slot_s, arc.train_type)].append(arc.start_time_s)
    headway_rows: List[Dict[str, object]] = []
    for (slot, train_type), times in sorted(departure_groups.items()):
        ordered = sorted(times)
        gaps = [right - left for left, right in zip(ordered, ordered[1:])]
        headway_rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "period_start_s": slot * slot_s,
                "period_end_s": (slot + 1) * slot_s,
                "train_type": train_type,
                "departure_count": len(ordered),
                "recommended_headway_s": candidate.headway_s,
                "observed_min_headway_s": min(gaps) if gaps else "",
                "observed_avg_headway_s": round(sum(gaps) / len(gaps), 3) if gaps else "",
                "observed_max_headway_s": max(gaps) if gaps else "",
                "basis": "best_candidate_departures",
            }
        )

    demand_by_id = {item.demand_id: item for item in bundle.demands} if bundle else {}
    od_counts: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(lambda: {"large": 0, "small": 0})
    counted_heavy: set[str] = set()
    for arc in first_runs:
        if arc.arc_type != "heavy_running" or arc.train_id in counted_heavy:
            continue
        counted_heavy.add(arc.train_id)
        demand = demand_by_id.get(arc.demand_id)
        origin = demand.origin_station if demand else arc.start_station
        destination = demand.destination_station if demand else arc.end_station
        service = bundle.service_types.get(demand.train_type) if bundle and demand else None
        size_class = _service_size_class(service) if service else "small"
        od_counts[(origin, destination)][size_class] += 1
    od_ratio_rows: List[Dict[str, object]] = []
    for (origin, destination), counts in sorted(od_counts.items()):
        total = counts["large"] + counts["small"]
        od_ratio_rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "origin_station": origin,
                "destination_station": destination,
                "large_train_count": counts["large"],
                "small_train_count": counts["small"],
                "total_train_count": total,
                "large_train_ratio": round(counts["large"] / total, 6) if total else 0.0,
                "small_train_ratio": round(counts["small"] / total, 6) if total else 0.0,
                "ratio_text": f"{counts['large']}:{counts['small']}",
                "basis": "selected_services_and_formation",
            }
        )

    operation_arcs = [
        arc for arc in candidate.arcs
        if arc.arc_type in {"loading", "unloading", "combining", "dismantling", "technical_operation"}
    ]
    operation_groups: Dict[str, List[HeArc]] = defaultdict(list)
    for arc in operation_arcs:
        operation_groups[arc.start_station].append(arc)
    rhythm_rows: List[Dict[str, object]] = []
    operation_nodes = bundle.operation_nodes if bundle else {}
    station_names = sorted(set(operation_groups) | set(operation_nodes))
    for station in station_names:
        arcs = sorted(operation_groups.get(station, []), key=lambda arc: (arc.start_time_s, arc.train_id))
        starts = [arc.start_time_s for arc in arcs]
        gaps = [right - left for left, right in zip(starts, starts[1:])]
        positive_gaps = [gap for gap in gaps if gap > 0]
        recommended_rhythm = (
            round(sum(positive_gaps) / len(positive_gaps), 3)
            if positive_gaps
            else max(1.0, float(candidate.headway_s), float(scenario.min_headway_s))
        )
        operation = operation_nodes.get(station)
        rhythm_rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "station_name": station,
                "station_role": operation.role if operation else "operation",
                "operation_count": len(arcs),
                "connection_count": len({arc.train_id for arc in arcs}),
                "recommended_formation_rhythm_s": recommended_rhythm,
                "minimum_operation_time_s": operation.operation_min_s if operation else 0,
                "capacity_per_slot": operation.capacity_per_slot if operation else "",
                "connection_model_status": (
                    "explicit_combination_arcs"
                    if any(arc.arc_type in {"combining", "dismantling"} for arc in arcs)
                    else "no_explicit_combination_arc_in_current_model"
                ),
                "basis": "best_candidate_operation_events",
            }
        )

    explicit_waits: Dict[str, List[int]] = defaultdict(list)
    for arc in candidate.arcs:
        if arc.arc_type == "waiting":
            explicit_waits[arc.start_station].append(max(0, arc.end_time_s - arc.start_time_s))
    waiting_rows: List[Dict[str, object]] = []
    for station in sorted(set(operation_nodes) | set(explicit_waits)):
        waits = explicit_waits.get(station, [])
        waiting_rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "station_name": station,
                "wait_lower_bound_s": min(waits) if waits else 0,
                "wait_upper_bound_s": max(waits) if waits else 0,
                "observed_wait_count": len(waits),
                "data_status": "optimized_explicit_wait" if waits else "no_explicit_wait_arc_in_current_model",
                "basis": "best_candidate_waiting_arcs",
            }
        )

    capacity_rows = _capacity_utilization_rows(candidate, scenario, bundle)

    return {
        "periodic_headway_recommendations.csv": headway_rows,
        "od_large_small_train_ratio.csv": od_ratio_rows,
        "combination_station_connection_rhythm.csv": rhythm_rows,
        "station_wait_bounds.csv": waiting_rows,
        "section_station_capacity_utilization.csv": capacity_rows,
    }


def arrival_headway_rows(
    result: HeOptimizationResult,
    bundle: Optional[HeInputBundle],
) -> List[Dict[str, object]]:
    """空列到达间隔统计（技术方案 4.2.1.2(2) 第四类约束的到到间隔 g）。

    与 ``periodic_headway_recommendations.csv``（发发间隔）相互独立：这里只统计空列**到达**
    装车站/分解站的事件，按车站、运行方向、列型分类和时段分组，给出实际到到间隔与建议值。
    """
    if bundle is None:
        return []
    candidate = result.best_candidate
    slot_s = result.scenario.time_slice_s
    arrivals: Dict[str, int] = {}
    train_meta: Dict[str, Tuple[str, str, str]] = {}
    for arc in candidate.arcs:
        if arc.arc_type != "empty_running":
            continue
        if arc.train_id not in arrivals or arc.end_time_s > arrivals[arc.train_id]:
            service = bundle.service_types.get(arc.train_type)
            if service is None:
                continue
            arrivals[arc.train_id] = arc.end_time_s
            train_meta[arc.train_id] = (
                arc.end_station,
                _travel_direction(arc.start_km, arc.end_km),
                _service_size_class(service),
            )
    groups: Dict[Tuple[int, str, str, str], List[int]] = defaultdict(list)
    for train_id, arrival_s in arrivals.items():
        station, direction, size_class = train_meta[train_id]
        groups[(arrival_s // slot_s, station, direction, size_class)].append(arrival_s)
    rows: List[Dict[str, object]] = []
    for (slot, station, direction, size_class), times in sorted(groups.items()):
        ordered = sorted(times)
        gaps = [right - left for left, right in zip(ordered, ordered[1:])]
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "period_start_s": slot * slot_s,
                "period_end_s": (slot + 1) * slot_s,
                "station_name": station,
                "direction": direction,
                "train_size_class": size_class,
                "arrival_count": len(ordered),
                "recommended_arrival_headway_s": result.scenario.min_arrival_headway_s,
                "observed_min_arrival_headway_s": min(gaps) if gaps else "",
                "observed_avg_arrival_headway_s": round(sum(gaps) / len(gaps), 3) if gaps else "",
                "observed_max_arrival_headway_s": max(gaps) if gaps else "",
                "violation_count": candidate.arrival_headway_violation_count,
                "basis": "best_candidate_empty_arrivals",
            }
        )
    return rows


def od_time_shift_rows(
    result: HeOptimizationResult,
    bundle: Optional[HeInputBundle],
) -> List[Dict[str, object]]:
    """逐 OD 流时移明细（技术方案 4.2.1.2(2) 扩展约束 (16)–(23)）。

    每行给出一个 OD 流的时移声明与四项约束的核对结果：

    - ``within_bounds``：时移是否在 ``max_departure_shift_s`` 上下界内（约束 16/17 唯一性与
      边界口径）；
    - ``post_shift_feasible``：移位后发车是否仍在发车窗口内（移位后时间可行性）；
    - ``od_chain_consistent``：始发发车偏移量与终到到达偏移量是否一致（约束 18–22，OD 链起终
      一致）；
    - ``capacity_recheck``：移位后的发车时刻是否仍满足区段通过能力（能力复核）。
    """
    candidate_id = result.best_candidate.candidate_id
    return [{"candidate_id": candidate_id, **row} for row in result.best_candidate.od_time_shift_rows]


def write_optimization_outputs(
    result: HeOptimizationResult,
    output_dir: Path,
    bundle: Optional[HeInputBundle] = None,
) -> None:
    """函数 write_optimization_outputs：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "ranked_candidates.csv", candidate_rows(result.candidates, "ranked"))
    _write_csv(output_dir / "pareto_candidates.csv", candidate_rows(result.pareto_candidates, "pareto"))
    _write_csv(output_dir / "time_space_nodes.csv", node_rows(result.best_candidate))
    _write_csv(output_dir / "time_space_arcs.csv", arc_rows(result.best_candidate))
    _write_csv(
        output_dir / "energy_time_slices.csv",
        energy_time_slice_rows(
            result.best_candidate,
            result.scenario.energy_settlement_step_s,
        ),
    )
    _write_csv(
        output_dir / "power_arm_energy_settlement.csv",
        result.best_candidate.energy_settlement_rows,
    )
    scheme_outputs = dispatch_plan_output_rows(result, bundle)
    missing_scheme = [name for name in DISPATCH_SCHEME_OUTPUT_FILES if name not in scheme_outputs]
    if missing_scheme:
        raise AssertionError(f"dispatch scheme outputs missing: {missing_scheme}")
    for filename, rows in scheme_outputs.items():
        _write_csv(output_dir / filename, rows)
    _write_csv(output_dir / "arrival_headway_recommendations.csv", arrival_headway_rows(result, bundle))
    _write_csv(output_dir / "od_time_shift.csv", od_time_shift_rows(result, bundle))
    _write_csv(output_dir / "secondary_ranking.csv", secondary_ranking_rows(result, bundle))
    risk_rows = congestion_risk_rows(result, bundle)
    _write_csv(output_dir / "congestion_risk.csv", risk_rows)
    corridor_rows = corridor_capacity_rows(result.best_candidate, result.scenario, bundle)
    _write_csv(output_dir / "corridor_capacity_utilization.csv", corridor_rows)
    split_arcs = [arc for arc in result.best_candidate.arcs if arc.power_arm_split]
    settlement = result.best_candidate.energy_settlement
    best_per_transport = energy_per_transport(result.best_candidate)
    best_secondary = secondary_ranking_metrics(result.best_candidate, bundle)
    risk_values = [float(row["congestion_risk_index"]) for row in risk_rows]
    summary = {
        "scenario_id": result.scenario.scenario_id,
        "objective_mode": result.scenario.objective_mode,
        "capacity_time_slice_s": result.scenario.time_slice_s,
        "energy_settlement_step_s": result.scenario.energy_settlement_step_s,
        "candidate_count": len(result.candidates),
        "pareto_candidate_count": len(result.pareto_candidates),
        "best_arrival_headway_violation_count": result.best_candidate.arrival_headway_violation_count,
        "best_od_time_shift_violation_count": result.best_candidate.od_time_shift_violation_count,
        "best_combined_train_shift_violation_count": result.best_candidate.combined_train_shift_violation_count,
        "best_energy_per_1000_ton_km": best_per_transport["energy_per_1000_ton_km"],
        "best_energy_per_ton_km": best_per_transport["energy_per_ton_km"],
        "energy_per_transport_unit": ENERGY_PER_TRANSPORT_UNIT,
        "best_secondary_ranking": {
            "timetable_smoothness": best_secondary["timetable_smoothness"],
            "operation_balance": best_secondary["operation_balance"],
            "shift_friendliness": best_secondary["shift_friendliness"],
            "secondary_ranking_score": best_secondary["secondary_ranking_score"],
        },
        "secondary_ranking_output": "secondary_ranking.csv",
        "congestion_risk_output": "congestion_risk.csv",
        "max_congestion_risk_index": round(max(risk_values), 6) if risk_values else 0.0,
        "mean_congestion_risk_index": round(sum(risk_values) / len(risk_values), 6) if risk_values else 0.0,
        "over_capacity_period_count": sum(1 for row in risk_rows if row["over_capacity"]),
        "congestion_risk_free_utilization": CONGESTION_RISK_FREE_UTILIZATION,
        "declared_section_elasticity_count": len(bundle.section_elasticity) if bundle else 0,
        "corridor_capacity_output": "corridor_capacity_utilization.csv",
        "max_corridor_congestion_risk_index": (
            round(max(float(row["congestion_risk_index"]) for row in corridor_rows), 6)
            if corridor_rows
            else 0.0
        ),
        "over_capacity_corridor_period_count": sum(1 for row in corridor_rows if row["over_capacity"]),
        "best_elastic_soft_penalty": round(result.best_candidate.elastic_soft_penalty, 6),
        "best_elastic_relief_count": result.best_candidate.elastic_relief_count,
        "declared_throat_capacity_count": len(bundle.throat_capacity) if bundle else 0,
        "best_throat_conflict_count": result.best_candidate.throat_conflict_count,
        "best_candidate": candidate_rows([result.best_candidate], "best")[0],
        "best_energy_settlement": {
            "traction_kwh": round(settlement.traction_kwh, 6),
            "regen_kwh": round(settlement.regen_kwh, 6),
            "direct_used_kwh": round(settlement.direct_used_kwh, 6),
            "battery_charge_kwh": round(settlement.battery_charge_kwh, 6),
            "battery_discharge_kwh": round(settlement.battery_discharge_kwh, 6),
            "battery_charge_limited_kwh": round(settlement.battery_charge_limited_kwh, 6),
            "battery_discharge_limited_kwh": round(settlement.battery_discharge_limited_kwh, 6),
            "wasted_kwh": round(settlement.wasted_kwh, 6),
            "grid_kwh": round(settlement.grid_kwh, 6),
            "traction_supply_excess_kwh": round(settlement.traction_supply_excess_kwh, 6),
            "regen_absorption_excess_kwh": round(settlement.regen_absorption_excess_kwh, 6),
            "final_soc_kwh": round(settlement.final_soc_kwh, 6),
            "final_soc_by_storage_kwh": settlement.final_soc_by_storage_kwh,
            "direct_use_ratio": round(settlement.direct_use_ratio, 6),
            "time_slice_count": settlement.time_slice_count,
            "settlement_window_count": settlement.settlement_window_count,
            "settlement_mode": "storage_absorption_no_direct_use_storage_sections_only",
        },
        "infrastructure_notes": list(result.infrastructure_notes),
        "power_arm_split_arc_count": len(split_arcs),
        "power_arm_assigned_split_arc_count": sum(1 for arc in split_arcs if arc.power_arm_ids),
        "power_arm_unassigned_split_arc_count": sum(1 for arc in split_arcs if not arc.power_arm_ids),
        "max_power_arm_segment_count": max((arc.segment_count for arc in split_arcs), default=0),
        "dispatch_scheme_outputs": {
            "periodic_headway_recommendations": "periodic_headway_recommendations.csv",
            "od_large_small_train_ratio": "od_large_small_train_ratio.csv",
            "combination_station_connection_rhythm": "combination_station_connection_rhythm.csv",
            "station_wait_bounds": "station_wait_bounds.csv",
            "section_station_capacity_utilization": "section_station_capacity_utilization.csv",
        },
        "arrival_headway_output": "arrival_headway_recommendations.csv",
        "min_arrival_headway_s": result.scenario.min_arrival_headway_s,
        "od_time_shift_output": "od_time_shift.csv",
        "declared_od_time_shift_count": len(result.best_candidate.od_time_shift_rows),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 重空列协同优化原型结果",
        "",
        f"- 场景：`{result.scenario.scenario_id}` / `{result.scenario.objective_mode}`",
        f"- 候选方案数：{len(result.candidates)}",
        f"- Pareto 候选数：{len(result.pareto_candidates)}",
        f"- 最优候选：`{result.best_candidate.candidate_id}`",
        f"- 是否可行：{result.best_candidate.feasible}",
        f"- 总能耗：{result.best_candidate.energy_kwh:.3f} kWh",
        f"- 牵引电量：{settlement.traction_kwh:.3f} kWh",
        f"- 再生电量：{settlement.regen_kwh:.3f} kWh",
        f"- 直用电量：{settlement.direct_used_kwh:.3f} kWh",
        f"- 储能充电量：{settlement.battery_charge_kwh:.3f} kWh",
        f"- 储能放电量：{settlement.battery_discharge_kwh:.3f} kWh",
        f"- 浪费电量：{settlement.wasted_kwh:.3f} kWh",
        f"- 电网取电：{settlement.grid_kwh:.3f} kWh",
        f"- 再生直用率：{settlement.direct_use_ratio:.3%}",
        f"- 货物周转量：{result.best_candidate.throughput_ton_km:.3f} ton-km",
        f"- 单位运量能耗：{best_per_transport['energy_per_1000_ton_km']:.6f} kWh/(千吨·km)",
        f"- 二级择优综合分：{best_secondary['secondary_ranking_score']:.6f}（时刻平滑度 {best_secondary['timetable_smoothness']:.6f} / 作业均衡度 {best_secondary['operation_balance']:.6f} / 换班友好性 {best_secondary['shift_friendliness']:.6f}）",
        f"- 最大拥堵风险指数：{(max(risk_values) if risk_values else 0.0):.6f}（无风险利用率阈值 {CONGESTION_RISK_FREE_UTILIZATION}）",
        f"- 弹性边界软惩罚：{result.best_candidate.elastic_soft_penalty:.3f}（触发 {result.best_candidate.elastic_relief_count} 次；声明区段弹性配置 {len(bundle.section_elasticity) if bundle else 0} 条）",
        f"- 虚拟车底次数：{result.best_candidate.virtual_trainset_count}",
        f"- 冲突数：{result.best_candidate.conflict_count}",
        "",
        "本原型把运行弧按供电臂边界和时间片展开，并在同一供电臂、同一时间窗内做牵引电量与再生电量结算。当前再生电量仍按坡度/曲线启发式能耗差估算，尚不等同于最终牵引制动物理模型。",
    ]
    (output_dir / "HEAVY_EMPTY_NETWORK_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

def run_from_template(template_path: Path, output_dir: Path, scenario_id: str, real_data_dir: Path = Path("data") / "real_shuohuang") -> HeOptimizationResult:
    """函数 run_from_template：执行该模块中的相关处理逻辑。"""
    bundle = load_he_input_template(template_path, real_data_dir=real_data_dir)
    result = optimize_heavy_empty_network(bundle, scenario_id=scenario_id)
    write_optimization_outputs(result, output_dir, bundle=bundle)
    return result
