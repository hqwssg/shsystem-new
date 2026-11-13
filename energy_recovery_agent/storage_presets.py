# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
import csv
import math

from power_arm_electrical_limits import (
    PowerArmElectricalLimit,
    StorageSectionInterval,
    storage_section_intervals_from_rows,
)
from power_arm_lookup import load_power_arm_intervals
from train_simulator import BatteryStorageParameters, RouteData


@dataclass(frozen=True)
class StoragePresetScenario:
    """Virtual storage planning scenario.

    These presets are intentionally editable planning assumptions. They are not
    official storage-device parameters until replaced by real data.
    """

    scenario_id: str
    label: str
    ranges_km: Tuple[Tuple[float, float], ...]
    capacity_kwh: float
    max_charge_power_kw: float
    max_discharge_power_kw: float
    round_trip_efficiency: float = 0.9
    note: str = ""

    def __post_init__(self) -> None:
        """函数 __post_init__：执行该模块中的相关处理逻辑。"""
        scenario_id = str(self.scenario_id).strip()
        label = str(self.label).strip()
        if not scenario_id:
            raise ValueError("storage preset scenario_id must not be empty")
        if not label:
            raise ValueError("storage preset label must not be empty")
        numeric_fields = (
            "capacity_kwh",
            "max_charge_power_kw",
            "max_discharge_power_kw",
            "round_trip_efficiency",
        )
        parsed = {}
        for field_name in numeric_fields:
            raw_value = getattr(self, field_name)
            if isinstance(raw_value, bool):
                raise ValueError(f"storage preset {field_name} must be finite, got {raw_value!r}")
            try:
                number = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"storage preset {field_name} must be finite, got {raw_value!r}"
                ) from exc
            if not math.isfinite(number):
                raise ValueError(f"storage preset {field_name} must be finite, got {raw_value!r}")
            parsed[field_name] = number
        for field_name in ("capacity_kwh", "max_charge_power_kw", "max_discharge_power_kw"):
            if parsed[field_name] < 0.0:
                raise ValueError(f"storage preset {field_name} must be non-negative")
        if not 0.0 <= parsed["round_trip_efficiency"] <= 1.0:
            raise ValueError("storage preset round_trip_efficiency must be in [0, 1]")
        ranges = tuple(_range_union(self.ranges_km))
        if not ranges:
            raise ValueError("storage preset ranges_km must contain at least one non-empty range")
        if any(start < 0.0 for start, _end in ranges):
            raise ValueError("storage preset ranges_km must be non-negative")
        object.__setattr__(self, "scenario_id", scenario_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "ranges_km", ranges)
        for field_name, number in parsed.items():
            object.__setattr__(self, field_name, number)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    """函数 _overlap：执行该模块中的相关处理逻辑。"""
    left = max(min(a0, a1), min(b0, b1))
    right = min(max(a0, a1), max(b0, b1))
    return max(0.0, right - left)


def _range_union(ranges_km: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """函数 _range_union：执行该模块中的相关处理逻辑。"""
    normalized: List[Tuple[float, float]] = []
    for index, raw_range in enumerate(ranges_km):
        try:
            raw_start, raw_end = raw_range
        except (TypeError, ValueError) as exc:
            raise ValueError(f"storage range {index} must contain exactly two bounds") from exc
        if isinstance(raw_start, bool) or isinstance(raw_end, bool):
            raise ValueError(f"storage range {index} bounds must be finite numbers")
        try:
            start = float(raw_start)
            end = float(raw_end)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"storage range {index} bounds must be finite numbers") from exc
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError(f"storage range {index} bounds must be finite numbers")
        if abs(start - end) <= 1e-9:
            continue
        normalized.append((min(start, end), max(start, end)))
    cleaned = sorted(normalized)
    if not cleaned:
        return []
    merged = [list(cleaned[0])]
    for start, end in cleaned[1:]:
        # 仅边界相接的范围属于不同储能设备；只有真正重叠时才合并。
        if start < merged[-1][1] - 1e-9:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(float(start), float(end)) for start, end in merged]


def default_storage_preset_library(base_battery: BatteryStorageParameters) -> List[StoragePresetScenario]:
    """Editable virtual storage presets for energy-search experiments."""

    # 保留显式值和缺失即零的设备值。将零替换为大型虚拟设备会静默虚构储能能力，
    # 把设备不可用案例变成虚假节能结果。正向规划假设应写入 battery.json 或显式选择的预设，
    # 不能隐藏在此处的真值回退中。
    base_cap = float(base_battery.capacity_kwh)
    base_charge = float(getattr(base_battery, "max_charge_power_kW", 0.0))
    base_discharge = float(getattr(base_battery, "max_discharge_power_kW", 0.0))
    base_eff = float(base_battery.round_trip_efficiency)
    two = ((145.0, 164.0), (164.0, 200.7))
    return [
        StoragePresetScenario(
            scenario_id="virtual_two_section_base",
            label="current virtual two-section preset",
            ranges_km=two,
            capacity_kwh=base_cap,
            max_charge_power_kw=base_charge,
            max_discharge_power_kw=base_discharge,
            round_trip_efficiency=base_eff,
            note="Baseline virtual preset currently shipped in battery.json / energy_transfer_zones.csv.",
        ),
        StoragePresetScenario(
            scenario_id="virtual_two_section_high_power",
            label="same two sections, higher charge/discharge power",
            ranges_km=two,
            capacity_kwh=base_cap,
            max_charge_power_kw=base_charge * 2.0,
            max_discharge_power_kw=base_discharge * 2.0,
            round_trip_efficiency=base_eff,
            note="Power-limited recovery diagnosis: keep zones, raise virtual inverter power.",
        ),
        StoragePresetScenario(
            scenario_id="virtual_two_section_high_capacity",
            label="same two sections, higher energy capacity",
            ranges_km=two,
            capacity_kwh=base_cap * 2.0,
            max_charge_power_kw=base_charge,
            max_discharge_power_kw=base_discharge,
            round_trip_efficiency=base_eff,
            note="Capacity-limited recovery diagnosis: keep zones, raise virtual storage capacity.",
        ),
        StoragePresetScenario(
            scenario_id="virtual_two_section_high_power_capacity",
            label="same two sections, higher power and capacity",
            ranges_km=two,
            capacity_kwh=base_cap * 2.0,
            max_charge_power_kw=base_charge * 2.0,
            max_discharge_power_kw=base_discharge * 2.0,
            round_trip_efficiency=base_eff,
            note="Hybrid landable diagnosis: raise both virtual inverter power and storage capacity on the two-section layout.",
        ),
        StoragePresetScenario(
            scenario_id="virtual_expanded_regen_corridor",
            label="expanded virtual corridor K100-K250 + K450-K560",
            ranges_km=((100.0, 250.0), (450.0, 560.0)),
            capacity_kwh=base_cap * 1.5,
            max_charge_power_kw=base_charge * 1.5,
            max_discharge_power_kw=base_discharge * 1.5,
            round_trip_efficiency=base_eff,
            note="Coverage diagnosis: add extra virtual storage corridors beyond the original two sections.",
        ),
        StoragePresetScenario(
            scenario_id="virtual_mainline_dense_four",
            label="four virtual mainline storage bands",
            ranges_km=((80.0, 160.0), (160.0, 240.0), (320.0, 400.0), (480.0, 560.0)),
            capacity_kwh=base_cap * 2.0,
            max_charge_power_kw=base_charge * 2.0,
            max_discharge_power_kw=base_discharge * 2.0,
            round_trip_efficiency=base_eff,
            note="Layout diagnosis: denser virtual storage coverage on mainline. Prefer corridor/two-section presets for landable main search.",
        ),
        StoragePresetScenario(
            scenario_id="virtual_mainline_near_full",
            label="near-full mainline virtual storage coverage",
            ranges_km=((20.0, 560.0),),
            capacity_kwh=base_cap * 3.0,
            max_charge_power_kw=base_charge * 2.5,
            max_discharge_power_kw=base_discharge * 2.5,
            round_trip_efficiency=base_eff,
            note="Upper-bound diagnosis only: most mainline regeneration becomes storage-eligible. Exclude from default main search; pass explicitly for ceiling tests.",
        ),
    ]


def apply_storage_ranges_to_power_arm_limits(
    base_limits: Dict[str, PowerArmElectricalLimit],
    power_arm_path: Path,
    ranges_km: Sequence[Tuple[float, float]],
    *,
    status: str = "planning_virtual_preset_search",
    note: str = "Virtual storage coverage override for energy-search scenarios; not official equipment data.",
) -> Tuple[Dict[str, PowerArmElectricalLimit], Tuple[StorageSectionInterval, ...]]:
    """Rewrite storage availability tags according to virtual ranges."""

    ranges = _range_union(ranges_km)
    intervals = load_power_arm_intervals(power_arm_path)
    # 按 section_id 映射两个方向的区段几何范围。
    geometry: Dict[str, Tuple[float, float, str]] = {}
    for item in intervals:
        geometry[item.section_id] = (float(item.min_km), float(item.max_km), str(item.direction))

    # 同时读取 CSV 行，以保持原有非储能字段稳定。
    with Path(power_arm_path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    updated_limits: Dict[str, PowerArmElectricalLimit] = dict(base_limits)
    synthetic_rows: List[Dict[str, object]] = []
    for row in rows:
        section_id = str(row.get("section_id") or "").strip()
        if not section_id:
            continue
        start_km, end_km, direction = geometry.get(
            section_id,
            (
                float(row.get("start_km") or 0.0),
                float(row.get("end_km") or 0.0),
                str(row.get("direction") or ""),
            ),
        )
        matched = []
        for idx, (r0, r1) in enumerate(ranges, start=1):
            if _overlap(start_km, end_km, r0, r1) > 1e-6:
                matched.append((idx, r0, r1, _overlap(start_km, end_km, r0, r1)))
        base_limit = base_limits.get(section_id) or base_limits.get(str(row.get("power_arm_id") or "").strip())
        if base_limit is None:
            continue
        if matched:
            # 优先选择重叠范围最大的虚拟区段 ID。
            matched.sort(key=lambda item: item[3], reverse=True)
            storage_ids = []
            for idx, r0, r1, _ov in matched:
                storage_ids.append(f"storage_section_{idx}:K{r0:g}-K{r1:g}")
            # 去重并保持原有顺序。
            seen = set()
            ordered_ids = []
            for storage_id in storage_ids:
                if storage_id not in seen:
                    seen.add(storage_id)
                    ordered_ids.append(storage_id)
            new_limit = replace(
                base_limit,
                storage_available=True,
                storage_section_id=";".join(ordered_ids),
                storage_status=status,
                storage_note=note,
            )
            for idx, range_start, range_end, _overlap_km in matched:
                synthetic_rows.append(
                    {
                        "storage_available": "yes",
                        "storage_section_id": f"storage_section_{idx}:K{range_start:g}-K{range_end:g}",
                        "storage_start_km": range_start,
                        "storage_end_km": range_end,
                        "direction": direction or row.get("direction") or "",
                        "start_km": start_km,
                        "end_km": end_km,
                    }
                )
        else:
            new_limit = replace(
                base_limit,
                storage_available=False,
                storage_section_id="",
                storage_status="no_storage_in_current_section",
                storage_note="当前虚拟预设未覆盖该区段，储能不可用。",
            )
        updated_limits[section_id] = new_limit
        power_arm_id = str(row.get("power_arm_id") or "").strip()
        if power_arm_id:
            updated_limits[power_arm_id] = new_limit

    storage_sections = storage_section_intervals_from_rows(synthetic_rows)
    # 如果行匹配没有结果，则直接根据范围生成几何回退值。
    if not storage_sections and ranges:
        fallback: List[StorageSectionInterval] = []
        for idx, (r0, r1) in enumerate(ranges, start=1):
            storage_id = f"storage_section_{idx}:K{r0:g}-K{r1:g}"
            fallback.append(StorageSectionInterval(storage_id, r0, r1, "forward"))
            fallback.append(StorageSectionInterval(storage_id, r0, r1, "reverse"))
        storage_sections = tuple(fallback)
    return updated_limits, storage_sections


def apply_storage_preset_to_battery(
    base_battery: BatteryStorageParameters,
    preset: StoragePresetScenario,
) -> BatteryStorageParameters:
    """函数 apply_storage_preset_to_battery：执行该模块中的相关处理逻辑。"""
    return replace(
        base_battery,
        capacity_kwh=float(preset.capacity_kwh),
        max_charge_power_kW=float(preset.max_charge_power_kw),
        max_discharge_power_kW=float(preset.max_discharge_power_kw),
        round_trip_efficiency=float(preset.round_trip_efficiency),
        data_status="planning_virtual_preset_search",
        scenario_name=preset.scenario_id,
        planning_assumption=True,
        note=(
            f"虚拟储能预设 `{preset.scenario_id}`：{preset.label}。"
            f"ranges={list(preset.ranges_km)}; {preset.note}"
        ),
    )


def apply_storage_preset_to_route(route: RouteData, preset: StoragePresetScenario) -> RouteData:
    """函数 apply_storage_preset_to_route：执行该模块中的相关处理逻辑。"""
    return replace(route, energy_transfer_ranges_km=list(_range_union(preset.ranges_km)))


def preset_to_dict(preset: StoragePresetScenario) -> Dict[str, object]:
    """函数 preset_to_dict：执行该模块中的相关处理逻辑。"""
    return {
        "scenario_id": preset.scenario_id,
        "label": preset.label,
        "ranges_km": [list(item) for item in preset.ranges_km],
        "capacity_kwh": preset.capacity_kwh,
        "max_charge_power_kw": preset.max_charge_power_kw,
        "max_discharge_power_kw": preset.max_discharge_power_kw,
        "round_trip_efficiency": preset.round_trip_efficiency,
        "note": preset.note,
        "data_status": "planning_virtual_preset_search",
    }
