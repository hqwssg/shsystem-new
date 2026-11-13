"""再生制动能量结算核心：按时间桶处理牵引、再生、储能和电网能量账本。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from matplotlib_chinese_font import configure_matplotlib_chinese_font


def configure_matplotlib_fonts() -> None:
    """优先选择系统中可用的中文字体，避免绘图告警。"""

    configure_matplotlib_chinese_font()


configure_matplotlib_fonts()

from train_simulator import (
    BatteryStorageParameters,
    StorageDeviceParameters,
    StepRecord,
    TrainParameters,
    load_config,
    run_train_simulation,
)
from power_arm_electrical_limits import (
    DEFAULT_POWER_ARM_INTERVAL_PATH,
    DynamicPowerArmLimit,
    PowerArmElectricalLimit,
    limit_for_power_arm,
    load_power_arm_electrical_limits,
    time_window_capacity_kwh,
)


PowerSample = Union[
    Tuple[float, float],
    Tuple[float, float, str],
    Tuple[float, float, str, float],
    Tuple[float, float, str, float, str],
]

# 能量账本采用1e-9 kWh作为浮点边界容差；只消除计算噪声，不掩盖真实负值。
NUMERICAL_ENERGY_TOLERANCE_KWH = 1e-9


def _finite_float(value: float, field_name: str) -> float:
    """Coerce a numeric input while rejecting NaN and infinities."""

    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be a finite number, got {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite, got {value!r}")
    return number


def _finite_nonnegative(value: float, field_name: str) -> float:
    """Coerce energy/power inputs while rejecting negative values."""

    number = _finite_float(value, field_name)
    if number < 0.0:
        raise ValueError(f"{field_name} must be non-negative, got {value!r}")
    return number


def _strict_nonnegative(value: float, field_name: str) -> float:
    """函数 _strict_nonnegative：执行该模块中的相关处理逻辑。"""
    return _finite_nonnegative(value, field_name)


def _finite_power_limit(value: float, field_name: str) -> float:
    """Validate a finite non-negative storage power limit.

    A zero nameplate or available-power value means that charging/discharging
    is unavailable.  Treating zero as an unbounded legacy sentinel can create
    fictitious storage savings when a field is missing or a device is offline.
    """

    number = _finite_float(value, field_name)
    if number < 0.0:
        raise ValueError(f"{field_name} must be non-negative, got {value!r}")
    return number


def storage_no_direct_effective_loss_kwh(
    wasted_kwh: float,
    battery_charge_kwh: float,
    battery_discharge_kwh: float,
    final_soc_deviation_kwh: float,
    storage_efficiency: float = 1.0,
    final_soc_shortfall_kwh: float = 0.0,
) -> float:
    """Return regenerative energy not reused within the evaluation horizon.

    The loss is measured on the regenerative-energy input side.  A discharge
    can include energy that was already in the device at the start of the
    horizon, so the whole discharge must not be credited against the current
    regenerative charge.  At most ``efficiency * charge`` can be attributed to
    this horizon's regeneration.  This preserves the conversion loss even
    when initial inventory is discharged in the same horizon.  The separate
    ``final_soc_shortfall_kwh`` term accounts for an unintended depletion of
    that initial inventory (or of the configured terminal-SOC target).
    """

    wasted = _finite_nonnegative(wasted_kwh, "wasted_kwh")
    _finite_nonnegative(battery_charge_kwh, "battery_charge_kwh")
    _finite_nonnegative(battery_discharge_kwh, "battery_discharge_kwh")
    final_soc_deviation = _finite_nonnegative(
        final_soc_deviation_kwh,
        "final_soc_deviation_kwh",
    )
    final_soc_shortfall = _finite_nonnegative(
        final_soc_shortfall_kwh,
        "final_soc_shortfall_kwh",
    )
    if final_soc_shortfall > final_soc_deviation + 1e-12:
        raise ValueError("final_soc_shortfall_kwh cannot exceed final_soc_deviation_kwh")
    efficiency = _finite_nonnegative(storage_efficiency, "storage_efficiency")
    if efficiency > 1.0:
        raise ValueError(f"storage_efficiency must be at most 1, got {storage_efficiency!r}")
    charge = float(battery_charge_kwh)
    discharge = float(battery_discharge_kwh)
    # 只有由本计算时域充入并保留下来的 SOC，才能计入本时域再生能量的再利用；
    # 若放电量超过该部分，超出的部分来自时域开始前的库存，不能抵销充电转换损失。
    reusable_regen_output = min(discharge, efficiency * charge)
    regen_input_not_reused = max(0.0, charge - reusable_regen_output)
    return wasted + regen_input_not_reused + final_soc_shortfall


@dataclass(frozen=True)
class TrainSchedule:
    """列车发车计划。"""

    name: str
    train: TrainParameters
    depart_time_s: int


@dataclass
class SettlementResult:
    """能量结算结果与可视化数据。"""

    total_gen_kwh: float
    total_con_kwh: float
    direct_used_kwh: float
    battery_charge_kwh: float
    battery_discharge_kwh: float
    battery_charge_limited_kwh: float
    battery_discharge_limited_kwh: float
    traction_supply_excess_kwh: float
    regen_absorption_excess_kwh: float
    wasted_kwh: float
    grid_kwh: float
    grid_cost: float
    battery_cost: float
    wasted_energy_penalty: float
    final_soc_penalty: float
    total_cost: float
    initial_soc_kwh: float
    final_soc_kwh: float
    final_soc_by_storage_kwh: Dict[str, float]
    target_final_soc_kwh: Optional[float]
    final_soc_shortfall_kwh: float
    final_soc_excess_kwh: float
    timeline_s: List[int]
    direct_used_kW: List[float]
    battery_charge_kW: List[float]
    battery_discharge_kW: List[float]
    wasted_kW: List[float]
    grid_kW: List[float]
    # 按储能设备分别计算再生能量的有效损失，避免汇总后把不同设备的充放电流错误配对。
    effective_regen_loss_kwh: float = 0.0
    initial_soc_by_storage_kwh: Dict[str, float] = field(default_factory=dict)
    battery_charge_by_storage_kwh: Dict[str, float] = field(default_factory=dict)
    battery_discharge_by_storage_kwh: Dict[str, float] = field(default_factory=dict)
    wasted_by_storage_kwh: Dict[str, float] = field(default_factory=dict)
    storage_parameters_by_id: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    self_discharge_loss_kwh: float = 0.0
    self_discharge_loss_by_storage_kwh: Dict[str, float] = field(default_factory=dict)

    @property
    def accepted_by_power_arm_kwh(self) -> float:
        """再生侧经供电臂/时间匹配后被直接利用或送入储能的能量。"""

        return self.direct_used_kwh + self.battery_charge_kwh

    @property
    def recovered_energy_kwh(self) -> float:
        """考虑储能转换效率后可继续利用的回收能量（输出侧口径）。"""

        storage_recovery = self._storage_recovered_energy_kwh
        if storage_recovery is None:
            storage_recovery = self.battery_charge_kwh * self._storage_efficiency
        return self.direct_used_kwh + storage_recovery

    @property
    def recovery_rate(self) -> float:
        """有效回收能量/理论再生能量。无再生能量时返回 0。"""

        if self.total_gen_kwh <= 0.0:
            return 0.0
        return self.recovered_energy_kwh / self.total_gen_kwh

    _storage_efficiency: float = field(default=1.0, repr=False)
    _storage_recovered_energy_kwh: Optional[float] = field(default=None, repr=False)


@dataclass
class StorageSettlementState:
    """调度与运行图结算共享的设备级可变 SOC 状态。"""

    soc_by_storage_kwh: Dict[str, float]
    capacity_per_storage_kwh: float
    charge_power_per_storage_kw: float
    discharge_power_per_storage_kw: float
    efficiency: float
    total_capacity_kwh: float = 0.0
    total_charge_power_kw: float = 0.0
    total_discharge_power_kw: float = 0.0
    capacity_by_storage_kwh: Dict[str, float] = field(default_factory=dict)
    charge_power_by_storage_kw: Dict[str, float] = field(default_factory=dict)
    discharge_power_by_storage_kw: Dict[str, float] = field(default_factory=dict)
    available_by_storage: Dict[str, bool] = field(default_factory=dict)
    min_soc_by_storage_kwh: Dict[str, float] = field(default_factory=dict)
    max_soc_by_storage_kwh: Dict[str, float] = field(default_factory=dict)
    charge_efficiency_by_storage: Dict[str, float] = field(default_factory=dict)
    discharge_efficiency_by_storage: Dict[str, float] = field(default_factory=dict)
    self_discharge_rate_by_storage_per_hour: Dict[str, float] = field(default_factory=dict)
    runtime_state_explicit: bool = False
    device_parameters_explicit: bool = False


@dataclass(frozen=True)
class StorageDeviceRuntimeState:
    """滚动窗口起点的一台储能设备实时状态。"""

    storage_section_id: str
    soc_kwh: float
    available: bool = True
    max_charge_power_kw: float | None = None
    max_discharge_power_kw: float | None = None

    def __post_init__(self) -> None:
        storage_id = str(self.storage_section_id).strip()
        if not storage_id:
            raise ValueError("storage_section_id must not be blank")
        if type(self.available) is not bool:
            raise ValueError("available must be a boolean")
        object.__setattr__(self, "storage_section_id", storage_id)
        object.__setattr__(
            self,
            "soc_kwh",
            _finite_nonnegative(self.soc_kwh, f"storage runtime {storage_id!r} soc_kwh"),
        )
        for field_name in ("max_charge_power_kw", "max_discharge_power_kw"):
            raw_value = getattr(self, field_name)
            if raw_value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _finite_power_limit(
                        raw_value,
                        f"storage runtime {storage_id!r} {field_name}",
                    ),
                )


def normalize_storage_runtime_states(
    states: Iterable[StorageDeviceRuntimeState] | None,
) -> Dict[str, StorageDeviceRuntimeState]:
    """校验设备状态集合并按稳定设备 ID 建立索引。"""

    normalized: Dict[str, StorageDeviceRuntimeState] = {}
    for index, state in enumerate(states or ()):
        if not isinstance(state, StorageDeviceRuntimeState):
            raise TypeError(
                f"storage_runtime_states[{index}] must be a StorageDeviceRuntimeState"
            )
        storage_id = state.storage_section_id
        if storage_id in normalized:
            raise ValueError(f"Duplicate storage runtime state ID: {storage_id!r}")
        normalized[storage_id] = state
    return normalized


@dataclass(frozen=True)
class EnergyBucketSettlement:
    """类 EnergyBucketSettlement：执行该模块中的相关处理逻辑。"""
    direct_used_kwh: float
    battery_charge_kwh: float
    battery_discharge_kwh: float
    battery_charge_limited_kwh: float
    battery_discharge_limited_kwh: float
    wasted_kwh: float
    grid_kwh: float
    traction_supply_excess_kwh: float
    regen_absorption_excess_kwh: float
    soc_before_kwh: float
    soc_after_kwh: float


@dataclass(frozen=True)
class EnergyBucketRequest:
    """类 EnergyBucketRequest：执行该模块中的相关处理逻辑。"""
    traction_kwh: float
    regen_kwh: float
    non_transfer_traction_kwh: float
    non_transfer_regen_kwh: float
    start_s: int
    end_s: int
    storage_section_id: str
    limit: PowerArmElectricalLimit
    power_arm_id: str = ""
    storage_availability_explicit: bool = True


def initialize_storage_settlement_state(
    storage_ids: List[str],
    capacity_kwh: float,
    max_charge_power_kw: float,
    max_discharge_power_kw: float,
    initial_soc_kwh: float,
    efficiency: float,
    storage_runtime_states: Iterable[StorageDeviceRuntimeState] | None = None,
    storage_device_parameters: Iterable[StorageDeviceParameters] | None = None,
    use_device_initial_soc: bool = False,
) -> StorageSettlementState:
    """函数 initialize_storage_settlement_state：执行该模块中的相关处理逻辑。"""
    unique_ids = sorted({str(item).strip() for item in storage_ids if str(item).strip()})
    storage_count = max(1, len(unique_ids))
    total_capacity = _finite_nonnegative(capacity_kwh, "capacity_kwh")
    total_charge_power = _finite_power_limit(max_charge_power_kw, "max_charge_power_kw")
    total_discharge_power = _finite_power_limit(max_discharge_power_kw, "max_discharge_power_kw")
    total_initial_soc = _finite_nonnegative(initial_soc_kwh, "initial_soc_kwh")
    if total_initial_soc > total_capacity:
        raise ValueError(
            f"initial_soc_kwh {total_initial_soc} exceeds capacity_kwh {total_capacity}"
        )
    storage_efficiency = _finite_nonnegative(efficiency, "efficiency")
    if storage_efficiency > 1.0:
        raise ValueError(f"efficiency must be at most 1, got {efficiency!r}")
    capacity_per_storage = total_capacity / storage_count
    charge_power_per_storage = total_charge_power / storage_count
    discharge_power_per_storage = total_discharge_power / storage_count
    runtime_by_storage = normalize_storage_runtime_states(storage_runtime_states)
    specifications = tuple(storage_device_parameters or ())
    if any(not isinstance(item, StorageDeviceParameters) for item in specifications):
        raise TypeError("storage_device_parameters must contain StorageDeviceParameters values")
    specification_by_storage = {item.storage_section_id: item for item in specifications}
    if len(specification_by_storage) != len(specifications):
        raise ValueError("Duplicate storage device parameter ID")
    if specification_by_storage:
        unknown_configured = sorted(set(unique_ids) - set(specification_by_storage))
        if unknown_configured:
            raise ValueError(
                f"Configured storage IDs are missing database device parameters: {unknown_configured}"
            )
        unique_ids = sorted(specification_by_storage)
        storage_count = len(unique_ids)
        total_capacity = sum(item.capacity_kwh for item in specifications)
        total_charge_power = sum(item.max_charge_power_kw for item in specifications)
        total_discharge_power = sum(item.max_discharge_power_kw for item in specifications)
        capacity_per_storage = total_capacity / storage_count
        charge_power_per_storage = total_charge_power / storage_count
        discharge_power_per_storage = total_discharge_power / storage_count
    capacity_by_storage = {
        storage_id: specification_by_storage[storage_id].capacity_kwh
        if specification_by_storage else capacity_per_storage
        for storage_id in unique_ids
    }
    min_soc_by_storage = {
        storage_id: specification_by_storage[storage_id].min_soc_kwh
        if specification_by_storage else 0.0
        for storage_id in unique_ids
    }
    max_soc_by_storage = {
        storage_id: float(
            specification_by_storage[storage_id].capacity_kwh
            if (max_soc := specification_by_storage[storage_id].max_soc_kwh) is None
            else max_soc
        )
        if specification_by_storage else capacity_per_storage
        for storage_id in unique_ids
    }
    charge_efficiency_by_storage = {
        storage_id: specification_by_storage[storage_id].charge_efficiency
        if specification_by_storage else storage_efficiency
        for storage_id in unique_ids
    }
    discharge_efficiency_by_storage = {
        storage_id: specification_by_storage[storage_id].discharge_efficiency
        if specification_by_storage else 1.0
        for storage_id in unique_ids
    }
    self_discharge_rate_by_storage = {
        storage_id: specification_by_storage[storage_id].self_discharge_rate_per_hour
        if specification_by_storage else 0.0
        for storage_id in unique_ids
    }
    if runtime_by_storage:
        configured_ids = set(unique_ids)
        runtime_ids = set(runtime_by_storage)
        if runtime_ids != configured_ids:
            missing = sorted(configured_ids - runtime_ids)
            unknown = sorted(runtime_ids - configured_ids)
            raise ValueError(
                "Explicit storage runtime state must exactly cover configured devices; "
                f"missing={missing}, unknown={unknown}"
            )
        soc_by_storage = {}
        charge_power_by_storage = {}
        discharge_power_by_storage = {}
        available_by_storage = {}
        for storage_id in unique_ids:
            runtime = runtime_by_storage[storage_id]
            minimum_soc = min_soc_by_storage[storage_id]
            maximum_soc = max_soc_by_storage[storage_id]
            if runtime.soc_kwh < minimum_soc - 1e-9 or runtime.soc_kwh > maximum_soc + 1e-9:
                raise ValueError(
                    f"Storage {storage_id!r} SOC {runtime.soc_kwh} kWh is outside "
                    f"[{minimum_soc}, {maximum_soc}] kWh"
                )
            specification = specification_by_storage.get(storage_id)
            rated_charge_power = (
                specification.max_charge_power_kw if specification else charge_power_per_storage
            )
            rated_discharge_power = (
                specification.max_discharge_power_kw if specification else discharge_power_per_storage
            )
            charge_limit = (
                rated_charge_power
                if runtime.max_charge_power_kw is None
                else runtime.max_charge_power_kw
            )
            discharge_limit = (
                rated_discharge_power
                if runtime.max_discharge_power_kw is None
                else runtime.max_discharge_power_kw
            )
            if charge_limit > rated_charge_power + 1e-9:
                raise ValueError(
                    f"Storage {storage_id!r} runtime charge limit {charge_limit} kW exceeds "
                    f"configured limit {rated_charge_power} kW"
                )
            if discharge_limit > rated_discharge_power + 1e-9:
                raise ValueError(
                    f"Storage {storage_id!r} runtime discharge limit {discharge_limit} kW exceeds "
                    f"configured limit {rated_discharge_power} kW"
                )
            soc_by_storage[storage_id] = runtime.soc_kwh
            static_available = specification.available if specification else True
            effective_available = static_available and runtime.available
            available_by_storage[storage_id] = effective_available
            charge_power_by_storage[storage_id] = charge_limit if effective_available else 0.0
            discharge_power_by_storage[storage_id] = (
                discharge_limit if effective_available else 0.0
            )
    elif specification_by_storage:
        if use_device_initial_soc:
            soc_by_storage = {
                storage_id: specification_by_storage[storage_id].initial_soc_kwh
                for storage_id in unique_ids
            }
        else:
            minimum_total = sum(min_soc_by_storage.values())
            maximum_total = sum(max_soc_by_storage.values())
            if total_initial_soc < minimum_total - 1e-9 or total_initial_soc > maximum_total + 1e-9:
                raise ValueError(
                    f"initial_soc_kwh {total_initial_soc} is outside database device aggregate "
                    f"bounds [{minimum_total}, {maximum_total}]"
                )
            soc_by_storage = dict(min_soc_by_storage)
            remaining_soc = total_initial_soc - minimum_total
            total_room = maximum_total - minimum_total
            for storage_id in unique_ids:
                room = max_soc_by_storage[storage_id] - min_soc_by_storage[storage_id]
                addition = remaining_soc * room / total_room if total_room > 0.0 else 0.0
                soc_by_storage[storage_id] += addition
        charge_power_by_storage = {
            storage_id: specification_by_storage[storage_id].max_charge_power_kw
            if specification_by_storage[storage_id].available else 0.0
            for storage_id in unique_ids
        }
        discharge_power_by_storage = {
            storage_id: specification_by_storage[storage_id].max_discharge_power_kw
            if specification_by_storage[storage_id].available else 0.0
            for storage_id in unique_ids
        }
        available_by_storage = {
            storage_id: specification_by_storage[storage_id].available
            for storage_id in unique_ids
        }
    else:
        soc_by_storage = {
            storage_id: total_initial_soc / storage_count
            for storage_id in unique_ids
        }
        charge_power_by_storage = {
            storage_id: charge_power_per_storage for storage_id in unique_ids
        }
        discharge_power_by_storage = {
            storage_id: discharge_power_per_storage for storage_id in unique_ids
        }
        available_by_storage = {storage_id: True for storage_id in unique_ids}
    if not soc_by_storage:
        soc_by_storage["__legacy__"] = total_initial_soc
        charge_power_by_storage["__legacy__"] = charge_power_per_storage
        discharge_power_by_storage["__legacy__"] = discharge_power_per_storage
        available_by_storage["__legacy__"] = True
        capacity_by_storage["__legacy__"] = capacity_per_storage
        min_soc_by_storage["__legacy__"] = 0.0
        max_soc_by_storage["__legacy__"] = capacity_per_storage
        charge_efficiency_by_storage["__legacy__"] = storage_efficiency
        discharge_efficiency_by_storage["__legacy__"] = 1.0
        self_discharge_rate_by_storage["__legacy__"] = 0.0
    return StorageSettlementState(
        soc_by_storage_kwh=soc_by_storage,
        capacity_per_storage_kwh=capacity_per_storage,
        charge_power_per_storage_kw=charge_power_per_storage,
        discharge_power_per_storage_kw=discharge_power_per_storage,
        efficiency=storage_efficiency,
        total_capacity_kwh=total_capacity,
        total_charge_power_kw=total_charge_power,
        total_discharge_power_kw=total_discharge_power,
        capacity_by_storage_kwh=capacity_by_storage,
        charge_power_by_storage_kw=charge_power_by_storage,
        discharge_power_by_storage_kw=discharge_power_by_storage,
        available_by_storage=available_by_storage,
        min_soc_by_storage_kwh=min_soc_by_storage,
        max_soc_by_storage_kwh=max_soc_by_storage,
        charge_efficiency_by_storage=charge_efficiency_by_storage,
        discharge_efficiency_by_storage=discharge_efficiency_by_storage,
        self_discharge_rate_by_storage_per_hour=self_discharge_rate_by_storage,
        runtime_state_explicit=bool(runtime_by_storage),
        device_parameters_explicit=bool(specification_by_storage),
    )


def ensure_storage_section_state(
    storage_state: StorageSettlementState,
    storage_section_id: str,
) -> str:
    """Register a newly observed storage section without inflating total capacity.

    Capacity and power budgets are re-split across currently known non-legacy
    sections so late-discovered IDs cannot exceed the battery nameplate totals.
    """

    storage_key = str(storage_section_id).strip()
    if not storage_key:
        return "__legacy__"
    if (
        storage_state.runtime_state_explicit or storage_state.device_parameters_explicit
    ) and storage_key not in storage_state.soc_by_storage_kwh:
        raise ValueError(
            f"Storage {storage_key!r} is missing from the explicit storage configuration."
        )
    active_before = [
        key for key in storage_state.soc_by_storage_kwh.keys() if key and key != "__legacy__"
    ]
    is_new = storage_key not in storage_state.soc_by_storage_kwh
    normalized_soc: dict[str, float] = {}
    for key, value in storage_state.soc_by_storage_kwh.items():
        numeric = _finite_float(value, f"soc_by_storage_kwh[{key!r}]")
        if numeric < -NUMERICAL_ENERGY_TOLERANCE_KWH:
            raise ValueError(
                f"soc_by_storage_kwh[{key!r}] must be non-negative, got {value!r}"
            )
        normalized_soc[key] = max(0.0, numeric)
    storage_state.soc_by_storage_kwh.update(normalized_soc)
    total_soc_before = sum(normalized_soc.values())
    if is_new:
        storage_state.soc_by_storage_kwh[storage_key] = 0.0
    active_ids = sorted(
        key for key in storage_state.soc_by_storage_kwh.keys() if key and key != "__legacy__"
    )
    if not active_ids:
        return storage_key
    # 兼容早期版本构造的状态对象：当时尚未保存 total_* 汇总字段。
    prior_count = max(1, len(active_before)) if active_before else 1
    total_capacity = _finite_nonnegative(storage_state.total_capacity_kwh, "total_capacity_kwh")
    total_charge_power = _finite_power_limit(storage_state.total_charge_power_kw, "total_charge_power_kw")
    total_discharge_power = _finite_power_limit(
        storage_state.total_discharge_power_kw,
        "total_discharge_power_kw",
    )
    if total_capacity <= 0.0:
        total_capacity = (
            _finite_nonnegative(storage_state.capacity_per_storage_kwh, "capacity_per_storage_kwh")
            * prior_count
        )
    if total_charge_power <= 0.0:
        total_charge_power = (
            _finite_power_limit(
                storage_state.charge_power_per_storage_kw,
                "charge_power_per_storage_kw",
            )
            * prior_count
        )
    if total_discharge_power <= 0.0:
        total_discharge_power = (
            _finite_power_limit(
                storage_state.discharge_power_per_storage_kw,
                "discharge_power_per_storage_kw",
            )
            * prior_count
        )
    storage_state.total_capacity_kwh = total_capacity
    storage_state.total_charge_power_kw = total_charge_power
    storage_state.total_discharge_power_kw = total_discharge_power
    if total_soc_before > total_capacity + NUMERICAL_ENERGY_TOLERANCE_KWH:
        raise ValueError(
            f"Total storage SOC {total_soc_before} kWh exceeds capacity {total_capacity} kWh."
        )
    count = len(active_ids)
    storage_state.capacity_per_storage_kwh = total_capacity / count
    storage_state.charge_power_per_storage_kw = total_charge_power / count
    storage_state.discharge_power_per_storage_kw = total_discharge_power / count
    if not storage_state.runtime_state_explicit and not storage_state.device_parameters_explicit:
        storage_state.capacity_by_storage_kwh = {
            section_id: storage_state.capacity_per_storage_kwh
            for section_id in active_ids
        }
        storage_state.charge_power_by_storage_kw = {
            section_id: storage_state.charge_power_per_storage_kw
            for section_id in active_ids
        }
        storage_state.discharge_power_by_storage_kw = {
            section_id: storage_state.discharge_power_per_storage_kw
            for section_id in active_ids
        }
        storage_state.available_by_storage = {
            section_id: True for section_id in active_ids
        }
        storage_state.min_soc_by_storage_kwh = {
            section_id: 0.0 for section_id in active_ids
        }
        storage_state.max_soc_by_storage_kwh = dict(storage_state.capacity_by_storage_kwh)
        storage_state.charge_efficiency_by_storage = {
            section_id: storage_state.efficiency for section_id in active_ids
        }
        storage_state.discharge_efficiency_by_storage = {
            section_id: 1.0 for section_id in active_ids
        }
        storage_state.self_discharge_rate_by_storage_per_hour = {
            section_id: 0.0 for section_id in active_ids
        }
    if is_new:
        # 后加入的 ID 会改变分区容量分配；只移动无法放入既有区段的 SOC，不能静默删除。
        storage_state.soc_by_storage_kwh.pop("__legacy__", None)
        redistributed = {
            section_id: min(
                _finite_nonnegative(
                    storage_state.soc_by_storage_kwh.get(section_id, 0.0),
                    f"soc_by_storage_kwh[{section_id!r}]",
                ),
                storage_state.capacity_per_storage_kwh,
            )
            for section_id in active_ids
        }
        remaining_soc = max(0.0, total_soc_before - sum(redistributed.values()))
        fill_order = [storage_key] + [item for item in active_ids if item != storage_key]
        for section_id in fill_order:
            room = storage_state.capacity_per_storage_kwh - redistributed[section_id]
            moved = min(room, remaining_soc)
            redistributed[section_id] += moved
            remaining_soc -= moved
        if remaining_soc > 1e-9:
            raise ValueError(f"Unable to redistribute {remaining_soc} kWh of storage SOC.")
        storage_state.soc_by_storage_kwh = redistributed
    else:
        storage_state.soc_by_storage_kwh[storage_key] = min(
            _finite_nonnegative(
                storage_state.soc_by_storage_kwh.get(storage_key, 0.0),
                f"soc_by_storage_kwh[{storage_key!r}]",
            ),
            storage_state.capacity_per_storage_kwh,
        )
    return storage_key


def storage_section_ids_from_limits(
    power_arm_limits: Mapping[str, PowerArmElectricalLimit] | None,
) -> List[str]:
    """Return the complete configured storage-device ID set."""

    if not power_arm_limits:
        return []
    return sorted(
        {
            item.strip()
            for limit in power_arm_limits.values()
            if limit.storage_available
            for item in limit.storage_section_id.split(";")
            if item.strip()
        }
    )


def enabled_storage_section_id(
    storage_section_id: str,
    limit: PowerArmElectricalLimit,
    storage_availability_explicit: bool = True,
) -> str:
    """Return a usable storage ID only when geometry and arm status agree.

    A geometry tag says where the sample is located; ``storage_available`` and
    the configured ID list say whether a device is actually connected and
    available there.  Requiring both prevents an old/stale geometry tag from
    charging an unavailable device.
    """

    storage_key = str(storage_section_id).strip()
    if type(storage_availability_explicit) is not bool:
        raise ValueError("storage_availability_explicit must be a boolean")
    if not storage_key:
        return ""
    # 没有该供电臂数据行时，几何标签仍采用文档规定的虚拟规划回退；显式数据行具有权威性。
    if not storage_availability_explicit:
        return storage_key
    if not limit.storage_available:
        return ""
    configured_ids = {
        item.strip()
        for item in str(limit.storage_section_id).split(";")
        if item.strip()
    }
    if storage_key not in configured_ids:
        raise ValueError(
            f"Storage section {storage_key!r} is not enabled by the power-arm "
            f"limit ({sorted(configured_ids)!r})."
        )
    return storage_key


def power_arm_limit_is_explicit(
    power_arm_id: str,
    limits: Mapping[str, PowerArmElectricalLimit] | None,
) -> bool:
    """函数 power_arm_limit_is_explicit：执行该模块中的相关处理逻辑。"""
    if not limits:
        return False
    return any(
        str(arm_id).strip() in limits
        for arm_id in str(power_arm_id).split(";")
        if str(arm_id).strip()
    )


def settle_energy_bucket(
    *,
    traction_kwh: float,
    regen_kwh: float,
    non_transfer_traction_kwh: float,
    non_transfer_regen_kwh: float,
    start_s: int,
    end_s: int,
    storage_section_id: str,
    limit: PowerArmElectricalLimit,
    allow_direct_use: bool,
    allow_storage: bool,
    storage_state: StorageSettlementState,
) -> EnergyBucketSettlement:
    """Backward-compatible wrapper for one settlement request."""

    return settle_energy_bucket_group(
        [
            EnergyBucketRequest(
                traction_kwh=traction_kwh,
                regen_kwh=regen_kwh,
                non_transfer_traction_kwh=non_transfer_traction_kwh,
                non_transfer_regen_kwh=non_transfer_regen_kwh,
                start_s=start_s,
                end_s=end_s,
                storage_section_id=storage_section_id,
                limit=limit,
            )
        ],
        allow_direct_use=allow_direct_use,
        allow_storage=allow_storage,
        storage_state=storage_state,
    )[0]


def _proportional_allocations(total: float, capacities: List[float]) -> List[float]:
    """函数 _proportional_allocations：执行该模块中的相关处理逻辑。"""
    available = sum(max(0.0, value) for value in capacities)
    if total <= 0.0 or available <= 0.0:
        return [0.0 for _value in capacities]
    return [total * max(0.0, value) / available for value in capacities]


def _canonical_power_arm_key(power_arm_id: str) -> str:
    """Canonicalize a possibly composite power-arm identifier for grouping.

    Composite IDs describe one physical overlap region.  Without canonical
    ordering, ``A;B`` and ``B;A`` were treated as separate arm buckets in a
    simultaneous settlement group, duplicating electrical capacity and direct
    matching opportunities.
    """

    parts = sorted({str(item).strip() for item in str(power_arm_id).split(";") if str(item).strip()})
    return ";".join(parts)


def settle_energy_bucket_group(
    requests: List[EnergyBucketRequest],
    *,
    allow_direct_use: bool,
    allow_storage: bool,
    storage_state: StorageSettlementState,
) -> List[EnergyBucketSettlement]:
    """Settle simultaneous buckets by power arm and storage section.

    Direct use and electrical limits are shared by every request on the same
    power arm, including requests split by storage-section tags. Remaining
    storage-eligible energy is then settled against each section-local SOC.
    """

    if not requests:
        return []
    if not isinstance(storage_state, StorageSettlementState):
        raise TypeError("storage_state must be a StorageSettlementState")
    if not isinstance(allow_direct_use, bool) or not isinstance(allow_storage, bool):
        raise TypeError("allow_direct_use and allow_storage must be boolean values")

    windows = set()
    traction: List[float] = []
    regen: List[float] = []
    non_transfer_traction: List[float] = []
    non_transfer_regen: List[float] = []
    storage_keys: List[str] = []
    arm_keys: List[str] = []
    for index, request in enumerate(requests):
        if not isinstance(request, EnergyBucketRequest):
            raise TypeError(f"requests[{index}] must be an EnergyBucketRequest")
        if not isinstance(request.limit, PowerArmElectricalLimit):
            raise TypeError(f"requests[{index}].limit must be a PowerArmElectricalLimit")
        if type(request.storage_availability_explicit) is not bool:
            raise TypeError(
                f"requests[{index}].storage_availability_explicit must be boolean"
            )
        start_value = _finite_float(request.start_s, "start_s")
        end_value = _finite_float(request.end_s, "end_s")
        if not start_value.is_integer() or not end_value.is_integer():
            raise ValueError("Settlement window bounds must be whole seconds.")
        if start_value < 0.0:
            raise ValueError(f"Settlement window start_s must be non-negative, got {request.start_s!r}")
        if end_value <= start_value:
            raise ValueError(
                f"Settlement window must have end_s > start_s, got {request.start_s!r}, {request.end_s!r}"
            )
        windows.add((int(start_value), int(end_value)))
        traction.append(_strict_nonnegative(request.traction_kwh, f"requests[{index}].traction_kwh"))
        regen.append(_strict_nonnegative(request.regen_kwh, f"requests[{index}].regen_kwh"))
        non_transfer_traction.append(
            _strict_nonnegative(
                request.non_transfer_traction_kwh,
                f"requests[{index}].non_transfer_traction_kwh",
            )
        )
        non_transfer_regen.append(
            _strict_nonnegative(
                request.non_transfer_regen_kwh,
                f"requests[{index}].non_transfer_regen_kwh",
            )
        )
        storage_keys.append(
            enabled_storage_section_id(
                request.storage_section_id,
                request.limit,
                request.storage_availability_explicit,
            )
        )
        power_arm_id = _canonical_power_arm_key(request.power_arm_id)
        # 不能假定未知供电臂之间存在电气连接。
        arm_keys.append(power_arm_id if power_arm_id else f"__request_{index}")
    if len(windows) != 1:
        raise ValueError("A simultaneous storage settlement group must use one identical time window.")
    start_s, end_s = next(iter(windows))
    duration_h = (end_s - start_s) / 3600.0

    request_count = len(requests)
    remaining_traction = list(traction)
    remaining_regen = list(regen)
    remaining_non_transfer_traction = list(non_transfer_traction)
    remaining_non_transfer_regen = list(non_transfer_regen)
    direct = [0.0] * request_count
    charge = [0.0] * request_count
    discharge = [0.0] * request_count
    charge_limited = [0.0] * request_count
    discharge_limited = [0.0] * request_count
    traction_excess = [0.0] * request_count
    regen_excess = [0.0] * request_count
    soc_before_by_request = [0.0] * request_count
    soc_after_by_request = [0.0] * request_count

    indices_by_arm: Dict[str, List[int]] = {}
    for index, arm_key in enumerate(arm_keys):
        indices_by_arm.setdefault(arm_key, []).append(index)

    regen_storage_capacities = [0.0] * request_count
    for arm_key, indices in indices_by_arm.items():
        first_limit = requests[indices[0]].limit
        if any(requests[index].limit != first_limit for index in indices[1:]):
            raise ValueError(f"Power arm {arm_key!r} has inconsistent electrical limits")
        traction_room = time_window_capacity_kwh(
            first_limit.max_traction_supply_kw, start_s, end_s
        )
        regen_room = time_window_capacity_kwh(
            first_limit.max_regen_absorption_kw, start_s, end_s
        )
        # 供电臂限制适用于臂上实际存在的全部能量，包括不可转移能量。
        # 直用是另一项契约：只有允许转移的牵引和再生部分才能配对，
        # 否则不可转移的牵引样本会产生虚假的直用节能量。
        transfer_traction_by_request = [traction[index] for index in indices]
        transfer_regen_by_request = [regen[index] for index in indices]
        transfer_traction = sum(transfer_traction_by_request)
        transfer_regen = sum(transfer_regen_by_request)
        non_transfer_traction_total = sum(non_transfer_traction[index] for index in indices)
        non_transfer_regen_total = sum(non_transfer_regen[index] for index in indices)
        # 不可转移能量不能参与直用匹配，但仍占用供电臂级供电/吸收能力；确认直用前必须预留该能力。
        transfer_traction_room = max(0.0, traction_room - non_transfer_traction_total)
        transfer_regen_room = max(0.0, regen_room - non_transfer_regen_total)
        direct_total = (
            min(
                transfer_traction,
                transfer_regen,
                transfer_traction_room,
                transfer_regen_room,
            )
            if allow_direct_use
            else 0.0
        )
        direct_from_traction = _proportional_allocations(
            direct_total, transfer_traction_by_request
        )
        direct_from_regen = _proportional_allocations(
            direct_total, transfer_regen_by_request
        )
        for offset, index in enumerate(indices):
            transfer_traction_value = transfer_traction_by_request[offset]
            if transfer_traction_value > 0.0:
                remaining_traction[index] = max(
                    0.0, transfer_traction_value - direct_from_traction[offset]
                )
            # 不可转移牵引不能被直用减少，结算后始终保留为电网需求。
            remaining_non_transfer_traction[index] = non_transfer_traction[index]
            transfer_regen_value = transfer_regen_by_request[offset]
            if transfer_regen_value > 0.0:
                remaining_regen[index] = max(
                    0.0, transfer_regen_value - direct_from_regen[offset]
                )
            # 同理，不可转移再生能量不能参与直用匹配。
            remaining_non_transfer_regen[index] = non_transfer_regen[index]
            # 在再生侧归属匹配能量，使逐行直用比例有意义，同时保持总量守恒。
            direct[index] = direct_from_regen[offset]

        # 直用匹配能量不再经过供电臂，因此电气超限必须根据匹配后的剩余量计算；
        # 使用匹配前总量会把本可行的直用错误判为超限。
        remaining_traction_by_request = [
            remaining_traction[index] + remaining_non_transfer_traction[index]
            for index in indices
        ]
        remaining_regen_by_request = [
            remaining_regen[index] + remaining_non_transfer_regen[index]
            for index in indices
        ]
        traction_excess_allocations = _proportional_allocations(
            max(0.0, sum(remaining_traction_by_request) - traction_room),
            remaining_traction_by_request,
        )
        regen_excess_allocations = _proportional_allocations(
            max(0.0, sum(remaining_regen_by_request) - regen_room),
            remaining_regen_by_request,
        )
        for offset, index in enumerate(indices):
            traction_excess[index] = traction_excess_allocations[offset]
            regen_excess[index] = regen_excess_allocations[offset]

        # 直用会占用供电臂部分再生吸收能力；剩余能力应在该供电臂所有带储能标签的请求间共享，
        # 不能给每个区段重复授予完整供电臂限制。
        eligible_remaining_regen = [
            remaining_regen[index] if storage_keys[index] else 0.0 for index in indices
        ]
        # 本时间窗内所有再生组件共享供电臂吸收限制。不可转移再生能量不能直用或进入储能，
        # 但仍占用电气吸收能力；忽略它会使储能超过供电臂物理上限并高估可回收能量。
        # 直用匹配后留下的每个再生组件都占用供电臂吸收通道，即使请求没有储能标签。
        # 旧计算只预留直用和不可转移再生能量，导致无标签的可转移再生请求可能与满额储能充电共存，
        # 使物理供电臂总量超过 ``max_regen_absorption_kw``。
        untagged_remaining_regen = sum(
            remaining_regen[index]
            for index in indices
            if not storage_keys[index]
        )
        storage_room = min(
            sum(eligible_remaining_regen),
            max(
                0.0,
                regen_room
                - direct_total
                - non_transfer_regen_total
                - untagged_remaining_regen,
            ),
        )
        storage_allocations = _proportional_allocations(
            storage_room, eligible_remaining_regen
        )
        for offset, index in enumerate(indices):
            regen_storage_capacities[index] = storage_allocations[offset]

    indices_by_storage: Dict[str, List[int]] = {}
    for index, storage_key in enumerate(storage_keys):
        if storage_key:
            indices_by_storage.setdefault(storage_key, []).append(index)

    for storage_key, indices in sorted(indices_by_storage.items()):
        state_key = ensure_storage_section_state(storage_state, storage_key)
        soc_before = storage_state.soc_by_storage_kwh.get(state_key, 0.0)
        capacity_limit = storage_state.capacity_by_storage_kwh.get(
            state_key, storage_state.capacity_per_storage_kwh
        )
        minimum_soc = storage_state.min_soc_by_storage_kwh.get(state_key, 0.0)
        maximum_soc = storage_state.max_soc_by_storage_kwh.get(
            state_key, capacity_limit
        )
        charge_efficiency = storage_state.charge_efficiency_by_storage.get(
            state_key, storage_state.efficiency
        )
        discharge_efficiency = storage_state.discharge_efficiency_by_storage.get(
            state_key, 1.0
        )
        charge_power_limit = storage_state.charge_power_by_storage_kw.get(
            state_key, storage_state.charge_power_per_storage_kw
        )
        discharge_power_limit = storage_state.discharge_power_by_storage_kw.get(
            state_key, storage_state.discharge_power_per_storage_kw
        )
        storage_available = storage_state.available_by_storage.get(state_key, True)
        for index in indices:
            soc_before_by_request[index] = soc_before

        charge_capacities = [regen_storage_capacities[index] for index in indices]
        charge_total = 0.0
        charge_limited_total = 0.0
        soc_after_charge = soc_before
        if (
            allow_storage
            and storage_available
            and sum(charge_capacities) > 0.0
            and charge_efficiency > 0.0
        ):
            capacity_room_input = max(
                0.0,
                (maximum_soc - soc_before)
                / charge_efficiency,
            )
            power_room = charge_power_limit * duration_h
            desired_charge = min(sum(charge_capacities), capacity_room_input)
            charge_total = min(desired_charge, power_room)
            charge_limited_total = max(0.0, desired_charge - charge_total)
            soc_after_charge += charge_total * charge_efficiency
        charge_allocations = _proportional_allocations(charge_total, charge_capacities)
        charge_limited_allocations = _proportional_allocations(
            charge_limited_total, charge_capacities
        )

        discharge_capacities = [remaining_traction[index] for index in indices]
        discharge_total = 0.0
        discharge_limited_total = 0.0
        soc_after = soc_after_charge
        # 物理储能设备不能在同一结算时间窗内同时充电和放电。再生能量吸收优先；
        # 只要本时间桶发生充电，牵引需求就仍由电网承担，新充入的能量从下一桶起可用。
        if (
            allow_storage
            and storage_available
            and sum(discharge_capacities) > 0.0
            and charge_total <= 0.0
            # 效率为零表示储能不可用，此时不能释放已有 SOC，否则停用设备仍会
            # 利用初始库存制造虚假的电网节能量。
            and charge_efficiency > 0.0
            and discharge_efficiency > 0.0
            and soc_before > minimum_soc
        ):
            power_room = discharge_power_limit * duration_h
            available_output_energy = max(
                0.0, (soc_before - minimum_soc) * discharge_efficiency
            )
            desired_discharge = min(sum(discharge_capacities), available_output_energy)
            discharge_total = min(desired_discharge, power_room)
            discharge_limited_total = max(0.0, desired_discharge - discharge_total)
            soc_after -= discharge_total / discharge_efficiency
        discharge_allocations = _proportional_allocations(
            discharge_total, discharge_capacities
        )
        discharge_limited_allocations = _proportional_allocations(
            discharge_limited_total, discharge_capacities
        )
        storage_state.soc_by_storage_kwh[state_key] = soc_after

        for offset, index in enumerate(indices):
            charge[index] = charge_allocations[offset]
            charge_limited[index] = charge_limited_allocations[offset]
            discharge[index] = discharge_allocations[offset]
            discharge_limited[index] = discharge_limited_allocations[offset]
            soc_after_by_request[index] = soc_after

    legacy_soc = storage_state.soc_by_storage_kwh.get("__legacy__", 0.0)
    for index, storage_key in enumerate(storage_keys):
        if not storage_key:
            soc_before_by_request[index] = legacy_soc
            soc_after_by_request[index] = legacy_soc

    results: List[EnergyBucketSettlement] = []
    for idx, _request in enumerate(requests):
        remaining_regen_value = max(0.0, remaining_regen[idx] - charge[idx])
        remaining_traction_value = max(0.0, remaining_traction[idx] - discharge[idx])
        results.append(
            EnergyBucketSettlement(
                direct_used_kwh=direct[idx],
                battery_charge_kwh=charge[idx],
                battery_discharge_kwh=discharge[idx],
                battery_charge_limited_kwh=charge_limited[idx],
                battery_discharge_limited_kwh=discharge_limited[idx],
                wasted_kwh=remaining_regen_value + remaining_non_transfer_regen[idx],
                grid_kwh=remaining_traction_value + remaining_non_transfer_traction[idx],
                traction_supply_excess_kwh=traction_excess[idx],
                regen_absorption_excess_kwh=regen_excess[idx],
                soc_before_kwh=soc_before_by_request[idx],
                soc_after_kwh=soc_after_by_request[idx],
            )
        )
    return results


def build_power_series(records: List[StepRecord], depart_time_s: int) -> Dict[int, PowerSample]:
    """Map single-train simulation records onto the global timeline."""

    if not isinstance(records, (list, tuple)):
        raise TypeError("records must be a list or tuple of StepRecord values")
    if isinstance(depart_time_s, bool):
        raise ValueError(f"depart_time_s must be a non-negative whole second, got {depart_time_s!r}")
    depart_value = _finite_float(depart_time_s, "depart_time_s")
    if not depart_value.is_integer() or depart_value < 0.0:
        raise ValueError(f"depart_time_s must be a non-negative whole second, got {depart_time_s!r}")
    depart_time = int(depart_value)

    normalized_times: List[int] = []
    for index, record in enumerate(records):
        if not isinstance(record, StepRecord):
            raise TypeError(f"records[{index}] must be a StepRecord")
        if isinstance(record.time_s, bool):
            raise ValueError(f"records[{index}].time_s must be a non-negative whole second")
        time_value = _finite_float(record.time_s, f"records[{index}].time_s")
        if not time_value.is_integer() or time_value < 0.0:
            raise ValueError(
                f"records[{index}].time_s must be a non-negative whole second, "
                f"got {record.time_s!r}"
            )
        _finite_float(record.power_kW, f"records[{index}].power_kW")
        ratio = _finite_float(
            record.energy_transfer_ratio,
            f"records[{index}].energy_transfer_ratio",
        )
        if not 0.0 <= ratio <= 1.0:
            raise ValueError(
                f"records[{index}].energy_transfer_ratio must be between 0 and 1, "
                f"got {record.energy_transfer_ratio!r}"
            )
        normalized_times.append(int(time_value))
    if any(right <= left for left, right in zip(normalized_times[:-1], normalized_times[1:])):
        raise ValueError("StepRecord times must be strictly increasing")

    series: Dict[int, PowerSample] = {}
    default_duration_s = 1.0
    if len(records) >= 2:
        default_duration_s = max(1.0, float(normalized_times[1] - normalized_times[0]))
    for index, record in enumerate(records):
        if index + 1 < len(records):
            duration_s = float(normalized_times[index + 1] - normalized_times[index])
        elif index > 0:
            duration_s = max(
                default_duration_s,
                float(normalized_times[index] - normalized_times[index - 1]),
            )
        else:
            duration_s = default_duration_s
        series[depart_time + normalized_times[index]] = (
            record.power_kW,
            record.energy_transfer_ratio,
            "",
            duration_s,
        )
    return series




def build_settlement_energy_bins(
    power_series_list: List[Dict[int, PowerSample]],
    settlement_step_s: int,
    *,
    validated: bool = False,
) -> Dict[Tuple[int, str, str, str], Tuple[float, float, float, float]]:
    """把功率序列预先分桶，供多个储能参数方案复用。

    ``validated=True`` is reserved for planner-owned series that were built from
    validated simulator caches. It skips repeated scalar validation in the hot
    path while the default keeps the public helper defensive.
    """

    if isinstance(settlement_step_s, bool) or int(settlement_step_s) != settlement_step_s or settlement_step_s <= 0:
        raise ValueError("settlement_step_s must be a positive whole number")
    step_s = int(settlement_step_s)
    energy_bins: Dict[Tuple[int, str, str, str], Tuple[float, float, float, float]] = {}
    for series_index, series in enumerate(power_series_list):
        if not isinstance(series, dict):
            raise TypeError(
                f"power_series_list[{series_index}] must be a dict of time_s -> power sample, "
                f"got {type(series).__name__}"
            )
        for time_s, sample in series.items():
            if not isinstance(sample, (tuple, list)) or len(sample) < 2:
                raise ValueError(
                    "Power sample must be a tuple/list with at least (power_kW, transfer_ratio)."
                )
            if validated:
                power_kW = float(sample[0])
                transfer_ratio = float(sample[1])
            else:
                power_kW = _finite_float(sample[0], "power_kW")
                transfer_ratio = _finite_float(sample[1], "transfer_ratio")
                if not 0.0 <= transfer_ratio <= 1.0:
                    raise ValueError(f"transfer_ratio must be between 0 and 1, got {sample[1]!r}")
            power_arm_id = str(sample[2]) if len(sample) >= 3 else ""
            unknown_arm_source = "" if power_arm_id.strip() else f"series:{series_index}"
            if len(sample) >= 4:
                sample_duration_s = (
                    float(sample[3])
                    if validated
                    else _finite_float(sample[3], "sample_duration_s")
                )
            else:
                sample_duration_s = float(step_s)
            if sample_duration_s <= 0.0:
                raise ValueError(
                    f"sample_duration_s must be positive, got {sample_duration_s!r}"
                )
            storage_section_id = str(sample[4]) if len(sample) >= 5 else ""
            if not math.isfinite(power_kW) or not math.isfinite(transfer_ratio):
                raise ValueError("power_kW and transfer_ratio must be finite numbers")
            effective_transfer_ratio = max(0.0, min(1.0, transfer_ratio))
            # bool 是 int 的子类：True 会被 float() 收成 1.0 并当作合法秒数，
            # 必须显式拒绝，否则脏样本会被静默吸收进结算。
            if isinstance(time_s, bool):
                raise ValueError(f"time_s must be a non-negative whole number, got {time_s!r}")
            sample_start_s = float(time_s)
            if (
                not math.isfinite(sample_start_s)
                or not sample_start_s.is_integer()
                or sample_start_s < 0.0
            ):
                raise ValueError(f"time_s must be a non-negative whole number, got {time_s!r}")
            sample_end_s = sample_start_s + sample_duration_s
            cursor_s = sample_start_s
            while cursor_s < sample_end_s - 1e-12:
                bin_time_s = int(math.floor(cursor_s / step_s)) * step_s
                bin_end_s = bin_time_s + step_s
                overlap_end_s = min(sample_end_s, float(bin_end_s))
                overlap_duration_s = max(0.0, overlap_end_s - cursor_s)
                if overlap_duration_s <= 0.0:
                    break
                bin_key = (bin_time_s, power_arm_id, storage_section_id, unknown_arm_source)
                p_gen_kwh, p_con_kwh, p_non_transfer_gen_kwh, p_non_transfer_con_kwh = energy_bins.get(
                    bin_key,
                    (0.0, 0.0, 0.0, 0.0),
                )
                overlap_kwh = abs(power_kW) * overlap_duration_s / 3600.0
                if power_kW >= 0.0:
                    p_con_kwh += overlap_kwh * effective_transfer_ratio
                    p_non_transfer_con_kwh += overlap_kwh * (1.0 - effective_transfer_ratio)
                else:
                    p_gen_kwh += overlap_kwh * effective_transfer_ratio
                    p_non_transfer_gen_kwh += overlap_kwh * (1.0 - effective_transfer_ratio)
                energy_bins[bin_key] = (
                    p_gen_kwh,
                    p_con_kwh,
                    p_non_transfer_gen_kwh,
                    p_non_transfer_con_kwh,
                )
                cursor_s = overlap_end_s
    return energy_bins


class EnergySettlementSystem:
    """按可配置时间桶结算多车功率的能量系统。"""

    def __init__(
        self,
        battery: BatteryStorageParameters,
        energy_transfer_ranges_km: Optional[List[Tuple[float, float]]] = None,
        settlement_time_step_s: int = 1,
        initial_soc_kwh: Optional[float] = None,
        target_final_soc_kwh: Optional[float] = None,
        final_soc_tolerance_kwh: float = 0.0,
        final_soc_penalty_per_kwh: float = 0.0,
        wasted_energy_penalty_per_kwh: float = 0.0,
        allow_direct_use: bool = False,
        allow_storage: bool = True,
        power_arm_limits: Optional[Mapping[str, PowerArmElectricalLimit]] = None,
        storage_runtime_states: Iterable[StorageDeviceRuntimeState] | None = None,
        dynamic_power_arm_limits: Iterable[DynamicPowerArmLimit] | None = None,
        flexible_energy_transfer_zones: Iterable[Mapping[str, Any]] | None = None,
    ) -> None:
        """函数 __init__：执行该模块中的相关处理逻辑。"""
        if not isinstance(battery, BatteryStorageParameters):
            raise TypeError("battery must be a BatteryStorageParameters object")
        self.storage_device_parameters = tuple(battery.storage_devices)
        self.use_device_initial_soc = initial_soc_kwh is None and bool(
            self.storage_device_parameters
        )
        self.capacity_kwh = _finite_nonnegative(battery.capacity_kwh, "battery.capacity_kwh")
        self.round_trip_efficiency = _finite_nonnegative(
            battery.round_trip_efficiency,
            "battery.round_trip_efficiency",
        )
        if self.round_trip_efficiency > 1.0:
            raise ValueError(
                "battery.round_trip_efficiency must be at most 1, "
                f"got {battery.round_trip_efficiency!r}"
            )
        self.depreciation_cost_per_kwh = _finite_nonnegative(
            battery.depreciation_cost_per_kwh,
            "battery.depreciation_cost_per_kwh",
        )
        self.depreciation_cost_basis = battery.depreciation_cost_basis
        self.grid_price_per_kwh = _finite_nonnegative(
            battery.grid_price_per_kwh,
            "battery.grid_price_per_kwh",
        )
        self.max_charge_power_kW = _finite_power_limit(
            getattr(battery, "max_charge_power_kW", 0.0),
            "battery.max_charge_power_kW",
        )
        self.max_discharge_power_kW = _finite_power_limit(
            getattr(battery, "max_discharge_power_kW", 0.0),
            "battery.max_discharge_power_kW",
        )
        self.energy_transfer_ranges_km = []
        for index, raw_range in enumerate(energy_transfer_ranges_km or []):
            try:
                raw_start, raw_end = raw_range
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"energy_transfer_ranges_km[{index}] must contain two bounds"
                ) from exc
            start_km = _finite_nonnegative(
                raw_start, f"energy_transfer_ranges_km[{index}][0]"
            )
            end_km = _finite_nonnegative(
                raw_end, f"energy_transfer_ranges_km[{index}][1]"
            )
            if math.isclose(start_km, end_km, abs_tol=1e-12):
                raise ValueError(
                    f"energy_transfer_ranges_km[{index}] bounds must be distinct"
                )
            self.energy_transfer_ranges_km.append(
                (min(start_km, end_km), max(start_km, end_km))
            )
        normalized_transfer_zones = []
        for index, raw_zone in enumerate(flexible_energy_transfer_zones or ()):
            if not isinstance(raw_zone, Mapping):
                raise TypeError(f"flexible_energy_transfer_zones[{index}] must be a mapping")
            maximum_power = _finite_power_limit(
                raw_zone.get("max_transfer_power_kW", 0.0),
                f"flexible_energy_transfer_zones[{index}].max_transfer_power_kW",
            )
            efficiency = _finite_nonnegative(
                raw_zone.get("efficiency", 1.0),
                f"flexible_energy_transfer_zones[{index}].efficiency",
            )
            if maximum_power <= 0.0:
                raise ValueError("flexible transfer maximum power must be positive")
            if not 0.0 < efficiency <= 1.0:
                raise ValueError("flexible transfer efficiency must be in (0, 1]")
            normalized_transfer_zones.append({
                "zone_id": str(raw_zone.get("zone_id") or f"ZONE-{index + 1:03d}"),
                "max_transfer_power_kW": maximum_power,
                "efficiency": efficiency,
            })
        self.flexible_energy_transfer_zones = tuple(normalized_transfer_zones)
        settlement_step = _finite_float(settlement_time_step_s, "settlement_time_step_s")
        if not settlement_step.is_integer() or settlement_step <= 0.0:
            raise ValueError(
                "settlement_time_step_s must be a finite positive whole number, "
                f"got {settlement_time_step_s!r}"
            )
        self.settlement_time_step_s = int(settlement_step)
        resolved_initial_soc = (
            sum(item.initial_soc_kwh for item in self.storage_device_parameters)
            if initial_soc_kwh is None and self.storage_device_parameters
            else (0.0 if initial_soc_kwh is None else initial_soc_kwh)
        )
        self.initial_soc_kwh = _finite_nonnegative(resolved_initial_soc, "initial_soc_kwh")
        if self.initial_soc_kwh > self.capacity_kwh:
            raise ValueError(
                f"initial_soc_kwh {self.initial_soc_kwh} exceeds battery capacity "
                f"{self.capacity_kwh}"
            )
        self.target_final_soc_kwh = (
            None
            if target_final_soc_kwh is None
            else _finite_nonnegative(target_final_soc_kwh, "target_final_soc_kwh")
        )
        if (
            self.target_final_soc_kwh is not None
            and self.target_final_soc_kwh > self.capacity_kwh
        ):
            raise ValueError(
                f"target_final_soc_kwh {self.target_final_soc_kwh} exceeds battery capacity "
                f"{self.capacity_kwh}"
            )
        self.final_soc_tolerance_kwh = _finite_nonnegative(
            final_soc_tolerance_kwh,
            "final_soc_tolerance_kwh",
        )
        self.final_soc_penalty_per_kwh = _finite_nonnegative(
            final_soc_penalty_per_kwh,
            "final_soc_penalty_per_kwh",
        )
        self.wasted_energy_penalty_per_kwh = _finite_nonnegative(
            wasted_energy_penalty_per_kwh,
            "wasted_energy_penalty_per_kwh",
        )
        if not isinstance(allow_direct_use, bool) or not isinstance(allow_storage, bool):
            raise TypeError("allow_direct_use and allow_storage must be boolean values")
        self.allow_direct_use = allow_direct_use
        self.allow_storage = allow_storage
        self.power_arm_limits = (
            dict(power_arm_limits)
            if power_arm_limits is not None
            else load_power_arm_electrical_limits(str(DEFAULT_POWER_ARM_INTERVAL_PATH))
        )
        for power_arm_id, limit in self.power_arm_limits.items():
            if not isinstance(limit, PowerArmElectricalLimit):
                raise TypeError(
                    f"power_arm_limits[{power_arm_id!r}] must be a PowerArmElectricalLimit"
                )
        self.dynamic_power_arm_limits = tuple(dynamic_power_arm_limits or ())
        if any(not isinstance(item, DynamicPowerArmLimit) for item in self.dynamic_power_arm_limits):
            raise TypeError("dynamic_power_arm_limits必须只包含DynamicPowerArmLimit。")
        normalized_runtime_states = normalize_storage_runtime_states(storage_runtime_states)
        self.storage_runtime_states = tuple(normalized_runtime_states.values())
        if normalized_runtime_states:
            runtime_initial_soc = sum(
                state.soc_kwh for state in normalized_runtime_states.values()
            )
            if runtime_initial_soc > self.capacity_kwh + 1e-9:
                raise ValueError(
                    f"Storage runtime SOC total {runtime_initial_soc} kWh exceeds "
                    f"battery capacity {self.capacity_kwh} kWh"
                )
            self.initial_soc_kwh = runtime_initial_soc

    def with_initial_soc(
        self,
        initial_soc_kwh: float,
        *,
        target_final_soc_kwh: Optional[float] = None,
        preserve_target: bool = True,
    ) -> "EnergySettlementSystem":
        """复制结算器并替换滚动窗口起点 SOC，其他物理与计价参数保持不变。"""

        battery = BatteryStorageParameters(
            capacity_kwh=self.capacity_kwh,
            round_trip_efficiency=self.round_trip_efficiency,
            depreciation_cost_per_kwh=self.depreciation_cost_per_kwh,
            grid_price_per_kwh=self.grid_price_per_kwh,
            max_charge_power_kW=self.max_charge_power_kW,
            max_discharge_power_kW=self.max_discharge_power_kW,
            data_status="rolling_state_copy",
            scenario_name="rolling_state_copy",
            planning_assumption=True,
            note="由既有结算器复制，仅更新滚动窗口起点 SOC。",
            storage_devices=self.storage_device_parameters,
            depreciation_cost_basis=self.depreciation_cost_basis,
        )
        resolved_target = (
            self.target_final_soc_kwh
            if preserve_target
            else target_final_soc_kwh
        )
        return EnergySettlementSystem(
            battery,
            list(self.energy_transfer_ranges_km),
            settlement_time_step_s=self.settlement_time_step_s,
            initial_soc_kwh=initial_soc_kwh,
            target_final_soc_kwh=resolved_target,
            final_soc_tolerance_kwh=self.final_soc_tolerance_kwh,
            final_soc_penalty_per_kwh=self.final_soc_penalty_per_kwh,
            wasted_energy_penalty_per_kwh=self.wasted_energy_penalty_per_kwh,
            allow_direct_use=self.allow_direct_use,
            allow_storage=self.allow_storage,
            power_arm_limits=self.power_arm_limits,
            dynamic_power_arm_limits=self.dynamic_power_arm_limits,
            flexible_energy_transfer_zones=self.flexible_energy_transfer_zones,
        )

    def with_storage_runtime_states(
        self,
        storage_runtime_states: Iterable[StorageDeviceRuntimeState],
        *,
        target_final_soc_kwh: Optional[float] = None,
        preserve_target: bool = True,
    ) -> "EnergySettlementSystem":
        """复制结算器，并用逐设备实时状态替换滚动窗口起点状态。"""

        normalized = normalize_storage_runtime_states(storage_runtime_states)
        if not normalized:
            raise ValueError("storage_runtime_states must contain at least one device")
        aggregate_soc = sum(state.soc_kwh for state in normalized.values())
        resolved_target = (
            self.target_final_soc_kwh
            if preserve_target
            else target_final_soc_kwh
        )
        battery = BatteryStorageParameters(
            capacity_kwh=self.capacity_kwh,
            round_trip_efficiency=self.round_trip_efficiency,
            depreciation_cost_per_kwh=self.depreciation_cost_per_kwh,
            grid_price_per_kwh=self.grid_price_per_kwh,
            max_charge_power_kW=self.max_charge_power_kW,
            max_discharge_power_kW=self.max_discharge_power_kW,
            data_status="rolling_device_state_copy",
            scenario_name="rolling_device_state_copy",
            planning_assumption=True,
            note="由既有结算器复制，并更新滚动窗口逐设备状态。",
            storage_devices=self.storage_device_parameters,
            depreciation_cost_basis=self.depreciation_cost_basis,
        )
        return EnergySettlementSystem(
            battery,
            list(self.energy_transfer_ranges_km),
            settlement_time_step_s=self.settlement_time_step_s,
            initial_soc_kwh=aggregate_soc,
            target_final_soc_kwh=resolved_target,
            final_soc_tolerance_kwh=self.final_soc_tolerance_kwh,
            final_soc_penalty_per_kwh=self.final_soc_penalty_per_kwh,
            wasted_energy_penalty_per_kwh=self.wasted_energy_penalty_per_kwh,
            allow_direct_use=self.allow_direct_use,
            allow_storage=self.allow_storage,
            power_arm_limits=self.power_arm_limits,
            storage_runtime_states=normalized.values(),
            dynamic_power_arm_limits=self.dynamic_power_arm_limits,
            flexible_energy_transfer_zones=self.flexible_energy_transfer_zones,
        )

    def with_dynamic_power_arm_limits(
        self, limits: Iterable[DynamicPowerArmLimit]
    ) -> "EnergySettlementSystem":
        """复制结算器并附加按时间窗生效的供电臂限制。"""

        copied = self.with_storage_runtime_states(self.storage_runtime_states) if self.storage_runtime_states else self.with_initial_soc(self.initial_soc_kwh)
        copied.dynamic_power_arm_limits = tuple(limits)
        if any(not isinstance(item, DynamicPowerArmLimit) for item in copied.dynamic_power_arm_limits):
            raise TypeError("dynamic_power_arm_limits必须只包含DynamicPowerArmLimit。")
        return copied

    def settle(
        self,
        power_series_list: List[Dict[int, PowerSample]],
        *,
        precomputed_energy_bins: Dict[Tuple[int, str, str, str], Tuple[float, float, float, float]] | None = None,
    ) -> SettlementResult:
        """执行能量结算，返回统计结果。"""

        total_gen_kwh = 0.0
        total_con_kwh = 0.0
        direct_used_kwh = 0.0
        battery_charge_kwh = 0.0
        battery_discharge_kwh = 0.0
        battery_charge_limited_kwh = 0.0
        battery_discharge_limited_kwh = 0.0
        traction_supply_excess_kwh = 0.0
        regen_absorption_excess_kwh = 0.0
        wasted_kwh = 0.0
        grid_kwh = 0.0

        # 一个候选中供电臂 ID 的种类很少，但每个功率样本和结算桶都会重复解析。
        # 缓存仅在本次结算内有效，可保持组合供电臂校验和默认回退语义不变。
        resolved_limit_cache: Dict[Tuple[str, int | None], PowerArmElectricalLimit] = {}
        explicit_limit_cache: Dict[str, bool] = {}

        def resolved_limit(
            power_arm_id: str,
            time_s: int | None = None,
            end_time_s: int | None = None,
        ) -> PowerArmElectricalLimit:
            key = str(power_arm_id)
            cache_key = (key, time_s)
            if cache_key not in resolved_limit_cache:
                limit = limit_for_power_arm(key, self.power_arm_limits)
                if time_s is not None:
                    resolved_end_s = time_s + step_s if end_time_s is None else end_time_s
                    for dynamic in self.dynamic_power_arm_limits:
                        if dynamic.overlaps(key, time_s, resolved_end_s):
                            limit = dynamic.overlay(limit)
                resolved_limit_cache[cache_key] = limit
            return resolved_limit_cache[cache_key]

        def limit_is_explicit(power_arm_id: str) -> bool:
            key = str(power_arm_id)
            if key not in explicit_limit_cache:
                explicit_limit_cache[key] = power_arm_limit_is_explicit(
                    key, self.power_arm_limits
                )
            return explicit_limit_cache[key]

        step_s = self.settlement_time_step_s
        energy_bins = (
            precomputed_energy_bins
            if precomputed_energy_bins is not None
            else build_settlement_energy_bins(power_series_list, step_s)
        )

        timeline = sorted({key[0] for key in energy_bins.keys()})
        timeline_totals: Dict[int, Dict[str, float]] = {
            time_s: {"direct": 0.0, "charge": 0.0, "discharge": 0.0, "wasted": 0.0, "grid": 0.0}
            for time_s in timeline
        }
        direct_used_kW: List[float] = []
        battery_charge_kW: List[float] = []
        battery_discharge_kW: List[float] = []
        wasted_kW: List[float] = []
        grid_kW: List[float] = []

        storage_ids = storage_section_ids_from_limits(self.power_arm_limits)
        tagged_storage_ids = sorted(
            {
                enabled_storage_section_id(
                    storage_section_id,
                    resolved_limit(power_arm_id),
                    limit_is_explicit(power_arm_id),
                )
                for _time_s, power_arm_id, storage_section_id, _unknown_source in energy_bins.keys()
                if str(storage_section_id).strip()
            }
            - {""}
        )
        if tagged_storage_ids:
            storage_ids = sorted(set(storage_ids).union(tagged_storage_ids))
        if self.storage_device_parameters:
            storage_ids = sorted(
                set(storage_ids).union(
                    item.storage_section_id for item in self.storage_device_parameters
                )
            )
        storage_state = initialize_storage_settlement_state(
            storage_ids,
            self.capacity_kwh,
            self.max_charge_power_kW,
            self.max_discharge_power_kW,
            self.initial_soc_kwh,
            self.round_trip_efficiency,
            self.storage_runtime_states,
            self.storage_device_parameters,
            self.use_device_initial_soc,
        )
        initial_soc_by_storage = dict(storage_state.soc_by_storage_kwh)
        storage_flow_by_storage: Dict[str, Dict[str, float]] = {
            storage_id: {"charge": 0.0, "discharge": 0.0, "wasted": 0.0}
            for storage_id in storage_state.soc_by_storage_kwh
        }
        wasted_outside_storage_kwh = 0.0
        self_discharge_loss_by_storage: Dict[str, float] = {
            storage_id: 0.0 for storage_id in storage_state.soc_by_storage_kwh
        }

        def apply_self_discharge(duration_s: int) -> None:
            if duration_s <= 0:
                return
            duration_h = duration_s / 3600.0
            for storage_id, soc in list(storage_state.soc_by_storage_kwh.items()):
                rate = storage_state.self_discharge_rate_by_storage_per_hour.get(storage_id, 0.0)
                if rate <= 0.0:
                    continue
                minimum = storage_state.min_soc_by_storage_kwh.get(storage_id, 0.0)
                # 合同中的小时率按复合留存率换算到任意时间长度，并保护设备SOC下限。
                retained = (1.0 - rate) ** duration_h
                next_soc = max(minimum, soc * retained)
                loss = max(0.0, soc - next_soc)
                storage_state.soc_by_storage_kwh[storage_id] = next_soc
                self_discharge_loss_by_storage[storage_id] = (
                    self_discharge_loss_by_storage.get(storage_id, 0.0) + loss
                )

        simultaneous_groups: Dict[
            int,
            List[Tuple[str, str, Tuple[float, float, float, float]]],
        ] = {}
        for t, power_arm_id, storage_section_id, unknown_source in energy_bins:
            simultaneous_groups.setdefault(t, []).append(
                (
                    power_arm_id,
                    storage_section_id,
                    energy_bins[(t, power_arm_id, storage_section_id, unknown_source)],
                )
            )

        previous_bucket_end_s: int | None = None
        for t, arm_buckets in sorted(simultaneous_groups.items()):
            if previous_bucket_end_s is not None:
                apply_self_discharge(max(0, t - previous_bucket_end_s))
            requests: List[EnergyBucketRequest] = []
            transfer_capacity_kwh = None
            transfer_efficiency = 1.0
            if self.flexible_energy_transfer_zones:
                total_transfer_power_kw = sum(
                    item["max_transfer_power_kW"] for item in self.flexible_energy_transfer_zones
                )
                transfer_capacity_kwh = total_transfer_power_kw * step_s / 3600.0
                transfer_efficiency = sum(
                    item["max_transfer_power_kW"] * item["efficiency"]
                    for item in self.flexible_energy_transfer_zones
                ) / total_transfer_power_kw
            total_transfer_regen = sum(values[0] for _arm, _storage, values in arm_buckets)
            total_transfer_traction = sum(values[1] for _arm, _storage, values in arm_buckets)
            regen_scale = (
                1.0 if transfer_capacity_kwh is None or total_transfer_regen <= transfer_capacity_kwh
                else transfer_capacity_kwh / total_transfer_regen
            )
            traction_scale = (
                1.0 if transfer_capacity_kwh is None or total_transfer_traction <= transfer_capacity_kwh
                else transfer_capacity_kwh / total_transfer_traction
            )
            for power_arm_id, storage_section_id, values in arm_buckets:
                p_gen_kwh, p_con_kwh, p_non_transfer_gen_kwh, p_non_transfer_con_kwh = values
                if transfer_capacity_kwh is not None:
                    admitted_gen = p_gen_kwh * regen_scale
                    delivered_gen = admitted_gen * transfer_efficiency
                    p_non_transfer_gen_kwh += p_gen_kwh - delivered_gen
                    p_gen_kwh = delivered_gen
                    admitted_con = p_con_kwh * traction_scale
                    p_non_transfer_con_kwh += p_con_kwh - admitted_con
                    p_con_kwh = admitted_con
                total_gen_kwh += p_gen_kwh + p_non_transfer_gen_kwh
                total_con_kwh += p_con_kwh + p_non_transfer_con_kwh
                requests.append(
                    EnergyBucketRequest(
                        traction_kwh=p_con_kwh,
                        regen_kwh=p_gen_kwh,
                        non_transfer_traction_kwh=p_non_transfer_con_kwh,
                        non_transfer_regen_kwh=p_non_transfer_gen_kwh,
                        start_s=t,
                        end_s=t + step_s,
                        storage_section_id=storage_section_id,
                        limit=resolved_limit(power_arm_id, t, t + step_s),
                        power_arm_id=power_arm_id,
                        storage_availability_explicit=limit_is_explicit(power_arm_id),
                    )
                )
            group_results = settle_energy_bucket_group(
                requests,
                allow_direct_use=self.allow_direct_use,
                allow_storage=self.allow_storage,
                storage_state=storage_state,
            )
            bucket = timeline_totals[t]
            for (power_arm_id, storage_section_id, _values), bucket_result in zip(
                arm_buckets,
                group_results,
            ):
                battery_charge_kwh += bucket_result.battery_charge_kwh
                battery_discharge_kwh += bucket_result.battery_discharge_kwh
                battery_charge_limited_kwh += bucket_result.battery_charge_limited_kwh
                battery_discharge_limited_kwh += bucket_result.battery_discharge_limited_kwh
                traction_supply_excess_kwh += bucket_result.traction_supply_excess_kwh
                regen_absorption_excess_kwh += bucket_result.regen_absorption_excess_kwh
                direct_used_kwh += bucket_result.direct_used_kwh
                wasted_kwh += bucket_result.wasted_kwh
                grid_kwh += bucket_result.grid_kwh
                bucket["direct"] += bucket_result.direct_used_kwh
                bucket["charge"] += bucket_result.battery_charge_kwh
                bucket["discharge"] += bucket_result.battery_discharge_kwh
                bucket["wasted"] += bucket_result.wasted_kwh
                bucket["grid"] += bucket_result.grid_kwh
                storage_key = enabled_storage_section_id(
                    storage_section_id,
                    resolved_limit(power_arm_id),
                    limit_is_explicit(power_arm_id),
                )
                if storage_key:
                    flow = storage_flow_by_storage.setdefault(
                        storage_key,
                        {"charge": 0.0, "discharge": 0.0, "wasted": 0.0},
                    )
                    flow["charge"] += bucket_result.battery_charge_kwh
                    flow["discharge"] += bucket_result.battery_discharge_kwh
                    flow["wasted"] += bucket_result.wasted_kwh
                else:
                    wasted_outside_storage_kwh += bucket_result.wasted_kwh
            apply_self_discharge(step_s)
            previous_bucket_end_s = t + step_s

        scale_to_kW = 3600.0 / step_s
        for t in timeline:
            bucket = timeline_totals[t]
            direct_used_kW.append(bucket["direct"] * scale_to_kW)
            battery_charge_kW.append(bucket["charge"] * scale_to_kW)
            battery_discharge_kW.append(bucket["discharge"] * scale_to_kW)
            wasted_kW.append(bucket["wasted"] * scale_to_kW)
            grid_kW.append(bucket["grid"] * scale_to_kW)

        grid_cost = grid_kwh * self.grid_price_per_kwh
        depreciation_energy_kwh = {
            "total_throughput": battery_charge_kwh + battery_discharge_kwh,
            "charge_energy": battery_charge_kwh,
            "discharge_energy": battery_discharge_kwh,
        }[self.depreciation_cost_basis]
        battery_cost = depreciation_energy_kwh * self.depreciation_cost_per_kwh
        wasted_energy_penalty = wasted_kwh * self.wasted_energy_penalty_per_kwh
        final_soc_shortfall_kwh = 0.0
        final_soc_excess_kwh = 0.0
        final_soc_kwh = sum(storage_state.soc_by_storage_kwh.values())
        if self.target_final_soc_kwh is not None:
            delta_soc_kwh = final_soc_kwh - self.target_final_soc_kwh
            if delta_soc_kwh < -self.final_soc_tolerance_kwh:
                final_soc_shortfall_kwh = abs(delta_soc_kwh) - self.final_soc_tolerance_kwh
            elif delta_soc_kwh > self.final_soc_tolerance_kwh:
                final_soc_excess_kwh = delta_soc_kwh - self.final_soc_tolerance_kwh
        final_soc_penalty = (
            final_soc_shortfall_kwh + final_soc_excess_kwh
        ) * self.final_soc_penalty_per_kwh
        total_cost = grid_cost + battery_cost + wasted_energy_penalty + final_soc_penalty

        if self.target_final_soc_kwh is None:
            # 没有显式终端目标时，以各独立设备的初始库存作为参考。先分别评价每个设备再汇总，
            # 防止一个区段的充电被另一区段的既有库存放电抵销。
            effective_regen_loss_kwh = wasted_outside_storage_kwh
            for storage_id, final_soc in storage_state.soc_by_storage_kwh.items():
                flow = storage_flow_by_storage.get(
                    storage_id,
                    {"charge": 0.0, "discharge": 0.0, "wasted": 0.0},
                )
                initial_soc = initial_soc_by_storage.get(storage_id, 0.0)
                final_soc_deviation = abs(final_soc - initial_soc)
                final_soc_shortfall = max(0.0, initial_soc - final_soc)
                effective_regen_loss_kwh += storage_no_direct_effective_loss_kwh(
                    flow["wasted"],
                    flow["charge"],
                    flow["discharge"],
                    final_soc_deviation,
                    storage_state.charge_efficiency_by_storage.get(
                        storage_id, self.round_trip_efficiency
                    ) * storage_state.discharge_efficiency_by_storage.get(storage_id, 1.0),
                    final_soc_shortfall,
                )
        else:
            # 终端目标是汇总契约，但再生能量的充放电仍属于独立设备。应按设备计算转换/弃能损失，
            # 再加上设备不平衡项和汇总目标偏差；否则 S1 充电与 S2 放电会在汇总 SOC 中相互抵销，
            # 把真实损失显示为零。
            effective_regen_loss_kwh = wasted_outside_storage_kwh
            # 将设备级转换/弃能项与下方终端 SOC 项分开。SOC 正变化可能表示仍停留在储能中的再生能量，
            # 已由辅助函数计入；负变化可能表示既有库存消耗。只有独立设备间相互抵销的部分才是额外损失，
            # 使用绝对变化量总和会重复计算停留的再生能量。
            device_positive_delta = 0.0
            device_negative_delta = 0.0
            for storage_id, final_soc in storage_state.soc_by_storage_kwh.items():
                flow = storage_flow_by_storage.get(
                    storage_id,
                    {"charge": 0.0, "discharge": 0.0, "wasted": 0.0},
                )
                initial_soc = initial_soc_by_storage.get(storage_id, 0.0)
                effective_regen_loss_kwh += storage_no_direct_effective_loss_kwh(
                    flow["wasted"],
                    flow["charge"],
                    flow["discharge"],
                    0.0,
                    storage_state.charge_efficiency_by_storage.get(
                        storage_id, self.round_trip_efficiency
                    ) * storage_state.discharge_efficiency_by_storage.get(storage_id, 1.0),
                    0.0,
                )
                device_delta = final_soc - initial_soc
                if device_delta >= 0.0:
                    device_positive_delta += device_delta
                else:
                    device_negative_delta += -device_delta
            # 一个设备充电、另一个设备放电时，汇总 SOC 可能不变，但放电设备已经损失初始库存。
            # 这里只计相互抵销的部分，净汇总变化由下方终端目标项处理。
            device_imbalance = min(device_positive_delta, device_negative_delta)
            effective_regen_loss_kwh += device_imbalance
            effective_regen_loss_kwh += abs(final_soc_kwh - self.target_final_soc_kwh)

        specification_by_storage = {
            item.storage_section_id: item for item in self.storage_device_parameters
        }
        storage_parameters_by_id: Dict[str, Dict[str, Any]] = {}
        legacy_storage_count = max(1, len(storage_state.soc_by_storage_kwh))
        for storage_id in storage_state.soc_by_storage_kwh:
            specification = specification_by_storage.get(storage_id)
            storage_parameters_by_id[storage_id] = {
                "capacity_kwh": storage_state.capacity_by_storage_kwh.get(
                    storage_id, storage_state.capacity_per_storage_kwh
                ),
                "max_charge_power_kw": (
                    specification.max_charge_power_kw
                    if specification else self.max_charge_power_kW / legacy_storage_count
                ),
                "max_discharge_power_kw": (
                    specification.max_discharge_power_kw
                    if specification else self.max_discharge_power_kW / legacy_storage_count
                ),
                "charge_efficiency": storage_state.charge_efficiency_by_storage.get(
                    storage_id, self.round_trip_efficiency
                ),
                "discharge_efficiency": storage_state.discharge_efficiency_by_storage.get(
                    storage_id, 1.0
                ),
                "self_discharge_rate_per_hour": storage_state.self_discharge_rate_by_storage_per_hour.get(
                    storage_id, 0.0
                ),
                "initial_soc_kwh": (
                    specification.initial_soc_kwh
                    if specification else initial_soc_by_storage.get(storage_id, 0.0)
                ),
                "min_soc_kwh": storage_state.min_soc_by_storage_kwh.get(storage_id, 0.0),
                "max_soc_kwh": storage_state.max_soc_by_storage_kwh.get(
                    storage_id, storage_state.capacity_per_storage_kwh
                ),
                "available": specification.available if specification else True,
                "data_status": specification.data_status if specification else "legacy_aggregate",
                "source_note": specification.source_note if specification else "",
            }

        return SettlementResult(
            total_gen_kwh=total_gen_kwh,
            total_con_kwh=total_con_kwh,
            direct_used_kwh=direct_used_kwh,
            battery_charge_kwh=battery_charge_kwh,
            battery_discharge_kwh=battery_discharge_kwh,
            battery_charge_limited_kwh=battery_charge_limited_kwh,
            battery_discharge_limited_kwh=battery_discharge_limited_kwh,
            traction_supply_excess_kwh=traction_supply_excess_kwh,
            regen_absorption_excess_kwh=regen_absorption_excess_kwh,
            wasted_kwh=wasted_kwh,
            grid_kwh=grid_kwh,
            grid_cost=grid_cost,
            battery_cost=battery_cost,
            wasted_energy_penalty=wasted_energy_penalty,
            final_soc_penalty=final_soc_penalty,
            total_cost=total_cost,
            initial_soc_kwh=sum(initial_soc_by_storage.values()),
            final_soc_kwh=final_soc_kwh,
            final_soc_by_storage_kwh=dict(sorted(storage_state.soc_by_storage_kwh.items())),
            target_final_soc_kwh=self.target_final_soc_kwh,
            final_soc_shortfall_kwh=final_soc_shortfall_kwh,
            final_soc_excess_kwh=final_soc_excess_kwh,
            timeline_s=timeline,
            direct_used_kW=direct_used_kW,
            battery_charge_kW=battery_charge_kW,
            battery_discharge_kW=battery_discharge_kW,
            wasted_kW=wasted_kW,
            grid_kW=grid_kW,
            effective_regen_loss_kwh=effective_regen_loss_kwh,
            initial_soc_by_storage_kwh=dict(sorted(initial_soc_by_storage.items())),
            battery_charge_by_storage_kwh={
                storage_id: flow["charge"]
                for storage_id, flow in sorted(storage_flow_by_storage.items())
            },
            battery_discharge_by_storage_kwh={
                storage_id: flow["discharge"]
                for storage_id, flow in sorted(storage_flow_by_storage.items())
            },
            wasted_by_storage_kwh={
                storage_id: flow["wasted"]
                for storage_id, flow in sorted(storage_flow_by_storage.items())
            },
            storage_parameters_by_id=dict(sorted(storage_parameters_by_id.items())),
            self_discharge_loss_kwh=sum(self_discharge_loss_by_storage.values()),
            self_discharge_loss_by_storage_kwh=dict(sorted(self_discharge_loss_by_storage.items())),
            _storage_efficiency=self.round_trip_efficiency,
            _storage_recovered_energy_kwh=sum(
                storage_flow_by_storage.get(storage_id, {}).get("charge", 0.0)
                * storage_state.charge_efficiency_by_storage.get(
                    storage_id, self.round_trip_efficiency
                )
                * storage_state.discharge_efficiency_by_storage.get(storage_id, 1.0)
                for storage_id in storage_state.soc_by_storage_kwh
            ),
        )


def print_report(result: SettlementResult) -> None:
    """打印结算报告。"""

    print("=== 能量结算报告 ===")
    print("系统总发电量: {:.2f} kWh".format(result.total_gen_kwh))
    print("系统总耗电量: {:.2f} kWh".format(result.total_con_kwh))
    print("直接协同抵扣电量: {:.2f} kWh".format(result.direct_used_kwh))
    print("电池充电量: {:.2f} kWh".format(result.battery_charge_kwh))
    print("电池放电量: {:.2f} kWh".format(result.battery_discharge_kwh))
    print("电池充电功率受限电量: {:.2f} kWh".format(result.battery_charge_limited_kwh))
    print("电池放电功率受限电量: {:.2f} kWh".format(result.battery_discharge_limited_kwh))
    print("牵引供电能力超限电量: {:.2f} kWh".format(result.traction_supply_excess_kwh))
    print("再生吸收能力超限电量: {:.2f} kWh".format(result.regen_absorption_excess_kwh))
    print("废弃电量: {:.2f} kWh".format(result.wasted_kwh))
    print("电网购电量: {:.2f} kWh".format(result.grid_kwh))
    print("电网购电成本: {:.2f} 元".format(result.grid_cost))
    print("电池折旧成本: {:.2f} 元".format(result.battery_cost))
    print("弃电惩罚成本: {:.2f} 元".format(result.wasted_energy_penalty))
    print("日终SOC惩罚成本: {:.2f} 元".format(result.final_soc_penalty))
    print("储能初始SOC: {:.2f} kWh".format(result.initial_soc_kwh))
    print("储能日终SOC: {:.2f} kWh".format(result.final_soc_kwh))
    print("净运营成本: {:.2f} 元".format(result.total_cost))


def plot_global_power(result: SettlementResult, output_path: Optional[Path] = None) -> None:
    """绘制全局时间功率堆叠图，区分直接使用与电池流向。"""

    time_axis = result.timeline_s
    direct = result.direct_used_kW
    discharge = result.battery_discharge_kW
    grid = result.grid_kW
    charge = result.battery_charge_kW
    wasted = result.wasted_kW

    cum_direct = direct
    cum_direct_discharge = [d + b for d, b in zip(direct, discharge)]
    cum_direct_discharge_grid = [d + b + g for d, b, g in zip(direct, discharge, grid)]

    cum_neg_direct = [-d for d in direct]
    cum_neg_direct_charge = [-(d + c) for d, c in zip(direct, charge)]
    cum_neg_total = [-(d + c + w) for d, c, w in zip(direct, charge, wasted)]

    fig, ax = plt.subplots(1, 1, figsize=(11, 5))

    ax.fill_between(time_axis, 0, cum_direct, color="#4c78a8", alpha=0.6, label="直接用电")
    ax.fill_between(time_axis, cum_direct, cum_direct_discharge, color="#72b7b2", alpha=0.6, label="电池放电")
    ax.fill_between(
        time_axis,
        cum_direct_discharge,
        cum_direct_discharge_grid,
        color="#f58518",
        alpha=0.6,
        label="电网购电",
    )

    ax.fill_between(time_axis, 0, cum_neg_direct, color="#54a24b", alpha=0.6, label="直接回收")
    ax.fill_between(time_axis, cum_neg_direct, cum_neg_direct_charge, color="#e45756", alpha=0.6, label="电池充电")
    ax.fill_between(time_axis, cum_neg_direct_charge, cum_neg_total, color="#b279a2", alpha=0.6, label="废弃电能")

    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_xlabel("时间（秒）")
    ax.set_ylabel("功率（千瓦）")
    ax.set_title("全局功率结算")
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=3, fontsize=9)

    plt.tight_layout()
    if output_path is not None:
        fig.savefig(output_path, dpi=150)
    if output_path is None:
        plt.show()
    plt.close(fig)


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    config_path = Path("sandbox_config.json")
    if not config_path.exists():
        raise FileNotFoundError("sandbox_config.json 不存在，请先运行 sandbox_data.py 生成配置文件。")

    route, trains, battery = load_config(config_path)

    heavy_train = trains.get("Heavy")
    empty_train = trains.get("Empty")
    if heavy_train is None or empty_train is None:
        raise ValueError("未找到 Heavy 或 Empty 列车参数，请检查配置文件。")

    schedules = [
        TrainSchedule(name="Heavy-0", train=heavy_train, depart_time_s=0),
        TrainSchedule(name="Empty-1", train=empty_train, depart_time_s=1000),
    ]

    power_series_list: List[Dict[int, PowerSample]] = []
    for schedule in schedules:
        records = run_train_simulation(route, schedule.train)
        power_series_list.append(build_power_series(records, schedule.depart_time_s))

    system = EnergySettlementSystem(battery, route.energy_transfer_ranges_km, allow_direct_use=False, allow_storage=True)
    result = system.settle(power_series_list)

    print_report(result)
    plot_global_power(result, output_path=Path("global_power.png"))


if __name__ == "__main__":
    main()
