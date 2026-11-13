"""将当前文件数据集投影为数据库基础数据记录。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from dataclasses import asdict
from uuid import UUID, uuid5
import csv
import json
import math


def _storage_zone_rows(root: Path, transfer_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Keep legacy storage IDs; flexible facility IDs are not storage device IDs."""
    if any(str(row.get("storage_section_id") or "").strip() for row in transfer_rows):
        return transfer_rows
    from power_arm_electrical_limits import storage_section_intervals_from_rows

    power_rows = _csv_rows(root / "power_arm_intervals.csv")
    by_id: dict[str, dict[str, Any]] = {}
    for interval in storage_section_intervals_from_rows(power_rows):
        code = interval.storage_section_id
        zone = by_id.setdefault(code, {
            "storage_section_id": code, "start_km": interval.min_km, "end_km": interval.max_km,
            "direction": interval.direction or "both", "data_status": "planning_placeholder",
            "source_note": "Derived from power_arm_intervals.csv storage references; aggregated battery ratings split equally until per-device ratings are supplied.",
        })
        zone["start_km"] = min(zone["start_km"], interval.min_km)
        zone["end_km"] = max(zone["end_km"], interval.max_km)
        if zone["direction"] != (interval.direction or "both"):
            zone["direction"] = "both"
    return list(by_id.values())


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _uuid(version_id: UUID, entity: str, source_id: str) -> UUID:
    return uuid5(version_id, f"{entity}:{source_id}")


def _locomotive_computed_mass(root: Path) -> dict[str, float]:
    """读取各机型表10「计算重量」（t）。缺失时返回空表，投影退化为原始值。

    trains.csv 的 mass_tons 是**车辆总重**（编组资料口径，不含机车），
    而算法使用整列车总重。投影必须用同一口径，否则库表与仿真结果会差 3–8%。
    """

    path = root / "locomotive_curves.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    output: dict[str, float] = {}
    for code, loco in (data.get("locomotives") or {}).items():
        params = loco.get("params") or {}
        unit_mass = params.get("computed_mass_t")
        if unit_mass is not None:
            output[str(code)] = float(unit_mass)
    return output

def _number(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"数据库投影不接受非有限数值：{value!r}")
    return result


def _zone_code(row: dict[str, str]) -> str:
    """兼容显式储能标识和旧储能区段表的 zone_id。"""

    return str(
        row.get("storage_section_id") or row.get("zone_id") or row.get("storage_code") or ""
    ).strip()


def is_flexible_transfer_zone(row: dict[str, str]) -> bool:
    """实施状态描述柔性供电设施，不能据此推导储能设备。"""
    return not (row.get("storage_section_id") or row.get("storage_code")) and bool(
        row.get("implementation_status") or row.get("active_in_operational_baseline")
    )


def normalize_data_status(value: Any, default: str = "planning_placeholder") -> str:
    """将现有来源标签收敛到数据库固定可信状态。"""

    text = str(value or "").strip().lower()
    if text in {"official", "derived_from_official", "planning_placeholder", "synthetic"}:
        return text
    if "synthetic" in text or "test" in text:
        return "synthetic"
    if "planning" in text or "virtual" in text or "placeholder" in text or "heuristic" in text:
        return "planning_placeholder"
    if "derived" in text or "reviewed" in text or "pdf" in text or "real" in text:
        return "derived_from_official"
    return default


def project_dataset(version_id: UUID, source_dir: Path) -> dict[str, list[dict]]:
    """投影平台常用基础数据；原文件仍由dataset_file表无损保存。"""

    root = Path(source_dir)
    stations = []
    station_by_name = {}
    resource_by_name = {row["station_name"]: row for row in _csv_rows(root / "station_resources.csv")}
    for row in _csv_rows(root / "stations.csv"):
        code = str(row["station_id"])
        station_id = _uuid(version_id, "station", code)
        resource = resource_by_name.get(row["name"], {})
        item = {
            "station_id": station_id,
            "station_code": code,
            "station_name": row["name"],
            "position_km": _number(row["position_km"], 0.0),
            "station_type": None,
            "track_capacity": int(resource["track_capacity"]) if resource.get("track_capacity") else None,
            "throat_capacity": int(resource["throat_capacity"]) if resource.get("throat_capacity") else None,
            "is_terminal": str(resource.get("is_terminal", "")).lower() == "true",
            "source_note": "stations.csv + station_resources.csv",
        }
        stations.append(item)
        station_by_name[item["station_name"]] = station_id

    segments = []
    for row in _csv_rows(root / "segments.csv"):
        code = str(row["segment_id"])
        segments.append({
            "segment_id": _uuid(version_id, "segment", code),
            "segment_code": code,
            "start_km": _number(row["start_km"], 0.0),
            "end_km": _number(row["end_km"], 0.0),
            "gradient_permille": _number(row.get("gradient_per_mille"), 0.0),
            "curve_radius_m": _number(row.get("curve_radius_m")),
            "speed_limit_kmh": _number(row.get("speed_limit_kmh")),
            "terrain": row.get("terrain") or None,
            "direction": "both",
            "source_note": "segments.csv",
        })

    train_types = []
    locomotive_unit_mass = _locomotive_computed_mass(root)
    for row in _csv_rows(root / "trains.csv"):
        code = str(row["name"])
        kind = "heavy" if code.strip().lower() == "heavy" else "empty"
        known = {
            "name", "mass_tons", "max_traction_kN", "max_brake_kN",
            "rotational_mass_factor", "davis_a", "davis_b", "davis_c", "length_km",
            "longitudinal_segments", "direction", "max_power_kW", "mass_data_status",
            "mass_min_tons", "mass_max_tons", "mass_note",
            "locomotive_type", "locomotive_count", "locomotive_consist",
            "freight_load_state",
        }
        # trains.csv 的 mass_tons 是车辆总重；库表统一存整列车总重（含机车），
        # 与 train_simulator 的计算口径保持一致。
        loco_count = int(float(row.get("locomotive_count") or 0))
        unit_mass = locomotive_unit_mass.get(str(row.get("locomotive_type") or "").strip(), 0.0)
        locomotive_mass = unit_mass * loco_count
        # 混合编组（如 12 轴 + 8 轴）时按清单累加，单一机型时结果与上面一致。
        consist_text = str(row.get("locomotive_consist") or "").strip()
        if consist_text:
            locomotive_mass = 0.0
            for chunk in consist_text.replace(";", "|").split("|"):
                if not chunk.strip():
                    continue
                loco_type, count_text = chunk.rsplit(":", 1)
                locomotive_mass += locomotive_unit_mass.get(
                    loco_type.strip(), 0.0
                ) * int(float(count_text))
        raw_mass = _number(row["mass_tons"])
        raw_min = _number(row.get("mass_min_tons"))
        raw_max = _number(row.get("mass_max_tons"))
        train_types.append({
            "train_type_id": _uuid(version_id, "train_type", code),
            "train_type_code": code,
            "train_type": kind,
            "mass_t": None if raw_mass is None else raw_mass + locomotive_mass,
            "mass_min_t": None if raw_min is None else raw_min + locomotive_mass,
            "mass_max_t": None if raw_max is None else raw_max + locomotive_mass,
            "length_km": _number(row["length_km"], 0.0),
            "rotational_mass_factor": _number(row["rotational_mass_factor"]),
            "max_traction_kn": _number(row["max_traction_kN"]),
            "max_brake_kn": _number(row["max_brake_kN"]),
            "max_power_kw": _number(row.get("max_power_kW"), 0.0),
            "davis_a": _number(row["davis_a"]),
            "davis_b": _number(row["davis_b"]),
            "davis_c": _number(row["davis_c"]),
            "direction": row["direction"],
            "longitudinal_segments": int(row["longitudinal_segments"]),
            "extra_parameters": {key: value for key, value in row.items() if key not in known or key in {"locomotive_type", "locomotive_count", "locomotive_consist", "freight_load_state"}},
            "data_status": normalize_data_status(row.get("mass_data_status")),
            "source_note": (
                (row.get("mass_note") or "trains.csv")
                + (
                    f"；库表 mass_t 为整列车总重：车辆 {raw_mass:g} t + 机车 {locomotive_mass:g} t"
                    if locomotive_mass > 0 and raw_mass is not None
                    else ""
                )
            ),
        })

    battery = json.loads((root / "battery.json").read_text(encoding="utf-8"))
    round_trip = float(battery["round_trip_efficiency"])
    one_way = math.sqrt(round_trip)
    transfer_rows = _csv_rows(root / "energy_transfer_zones.csv")
    zone_rows = [row for row in transfer_rows if not is_flexible_transfer_zone(row)]
    if not any(is_flexible_transfer_zone(row) for row in transfer_rows):
        zone_rows = _storage_zone_rows(root, zone_rows)
    zone_by_id = {}
    for row in zone_rows:
        zone_key = _zone_code(row)
        if zone_key:
            zone_by_id[zone_key] = row
    planning_version = (root / "storage_planning_policy.json").is_file()
    device_path = root / "storage_devices.json"
    if device_path.is_file():
        device_rows = json.loads(device_path.read_text(encoding="utf-8"))
        if not isinstance(device_rows, list) or (not device_rows and not planning_version) or any(
            not isinstance(item, dict) for item in device_rows
        ):
            raise ValueError("storage_devices.json必须是非空JSON对象数组。")
    else:
        device_count = max(1, len(zone_rows))
        device_rows = [
            {
                **row,
                "capacity_kwh": float(battery["capacity_kwh"]) / device_count,
                "max_charge_power_kw": float(battery["max_charge_power_kW"]) / device_count,
                "max_discharge_power_kw": float(battery["max_discharge_power_kW"]) / device_count,
                "charge_efficiency": one_way,
                "discharge_efficiency": one_way,
                "initial_soc_kwh": 0.0,
                "min_soc_kwh": 0.0,
                "max_soc_kwh": float(battery["capacity_kwh"]) / device_count,
                "available": True,
            }
            for row in zone_rows
        ]
    storage_devices = []
    seen_storage_codes = set()
    for row in device_rows:
        code = _zone_code(row)
        if not code:
            raise ValueError("储能设备缺少storage_section_id。")
        if code in seen_storage_codes:
            raise ValueError(f"储能设备ID重复：{code}")
        seen_storage_codes.add(code)
        zone = zone_by_id.get(code, {})
        capacity = _number(row.get("capacity_kwh"))
        if capacity is None:
            raise ValueError(f"储能设备{code}缺少capacity_kwh。")
        available_raw = row.get("available", True)
        if isinstance(available_raw, bool):
            available = available_raw
        elif str(available_raw).strip().lower() in {"1", "true", "yes", "y"}:
            available = True
        elif str(available_raw).strip().lower() in {"0", "false", "no", "n"}:
            available = False
        else:
            raise ValueError(f"储能设备{code}的available不是有效布尔值。")
        storage_devices.append({
            "storage_id": _uuid(version_id, "storage", code),
            "storage_code": code,
            "label": row.get("label") or code,
            "capacity_kwh": capacity,
            "max_charge_power_kw": _number(row.get("max_charge_power_kw")),
            "max_discharge_power_kw": _number(row.get("max_discharge_power_kw")),
            "charge_efficiency": _number(row.get("charge_efficiency")),
            "discharge_efficiency": _number(row.get("discharge_efficiency")),
            "initial_soc_kwh": _number(row.get("initial_soc_kwh"), 0.0),
            "min_soc_kwh": _number(row.get("min_soc_kwh"), 0.0),
            "max_soc_kwh": _number(row.get("max_soc_kwh"), capacity),
            "start_km": _number(row.get("start_km"), _number(zone.get("start_km"))),
            "end_km": _number(row.get("end_km"), _number(zone.get("end_km"))),
            "direction": row.get("direction") or "both",
            "available": available,
            "data_status": normalize_data_status(row.get("data_status") or battery.get("data_status")),
            "source_note": row.get("source_note") or row.get("note") or battery.get("note"),
        })
    if device_path.is_file() and seen_storage_codes != set(zone_by_id) and not (planning_version and not device_rows):
        missing = sorted(set(zone_by_id) - seen_storage_codes)
        unknown = sorted(seen_storage_codes - set(zone_by_id))
        raise ValueError(
            f"storage_devices.json必须完整覆盖energy_transfer_zones.csv；missing={missing}, unknown={unknown}"
        )

    power_arms = []
    for row in _csv_rows(root / "power_arm_intervals.csv"):
        code = str(row["section_id"])
        direction = str(row.get("direction") or "both").strip().lower()
        direction = {"down": "forward", "up": "reverse", "下行": "forward", "上行": "reverse"}.get(direction, direction)
        if direction not in {"forward", "reverse", "both"}:
            direction = "both"
        power_arms.append({
            "power_arm_id": _uuid(version_id, "power_arm", code),
            "power_arm_code": code,
            "start_km": _number(row["start_km"]),
            "end_km": _number(row["end_km"]),
            "direction": direction,
            "max_traction_supply_kw": _number(row.get("max_traction_supply_kw")),
            "max_regen_absorption_kw": _number(row.get("max_regen_absorption_kw")),
            "max_grid_feedback_kw": _number(row.get("max_grid_feedback_kw")),
            "direct_use_allowed": False,
            "needs_manual_review": str(row.get("needs_manual_review", "")).lower() == "true",
            "data_status": normalize_data_status(row.get("electrical_limit_status")),
            "source_note": row.get("electrical_limit_note") or row.get("review_note"),
        })

    signaling_blocks = []
    for row in _csv_rows(root / "signaling_blocks.csv"):
        code = str(row.get("block_id") or row.get("signaling_block_id"))
        signaling_blocks.append({
            "signaling_block_id": _uuid(version_id, "signaling_block", code),
            "block_code": code,
            "start_km": _number(row["start_km"]),
            "end_km": _number(row["end_km"]),
            "direction": row.get("direction") or "both",
            "capacity": int(row.get("capacity") or 1),
            "release_margin_s": int(row.get("release_margin_s") or 0),
            "data_status": normalize_data_status(row.get("data_status")),
            "source_note": row.get("note") or "signaling_blocks.csv",
        })

    station_resources = []
    resource_config = {}
    config_path = root / "resource_config.json"
    if config_path.is_file():
        resource_config = json.loads(config_path.read_text(encoding="utf-8"))
    for name, row in resource_by_name.items():
        station_id = station_by_name.get(name)
        if station_id is None:
            continue
        station_resources.append({
            "station_resource_id": _uuid(version_id, "station_resource", name),
            "station_id": station_id,
            "track_capacity": int(row["track_capacity"]),
            "throat_capacity": int(row["throat_capacity"]),
            "station_occupancy_s": int(resource_config.get("station_occupancy_s", 180)),
            "throat_occupancy_s": int(resource_config.get("throat_occupancy_s", 90)),
            "extra_rules": resource_config,
            "source_note": "station_resources.csv + resource_config.json",
        })

    planning_sites: list[dict] = []
    planning_technologies: list[dict] = []
    planning_options: list[dict] = []
    planning_scenarios: list[dict] = []
    planning_policies: list[dict] = []
    from .planning import has_planning_data, validate_planning_directory
    if has_planning_data(root):
        bundle = validate_planning_directory(root)
        for item in bundle.sites:
            row = asdict(item)
            planning_sites.append({
                "candidate_site_id": _uuid(version_id, "storage_candidate_site", item.site_code),
                **{key: row[key] for key in (
                    "site_code", "site_name", "position_km", "power_arm_code",
                    "storage_section_start_km", "storage_section_end_km", "direction", "buildable",
                    "max_connection_power_kw", "max_capacity_kwh", "fixed_site_cost_cny",
                    "data_status", "source_note",
                )},
                "allowed_technology_codes": list(item.allowed_technology_codes),
            })
        for item in bundle.technologies:
            row = asdict(item)
            planning_technologies.append({
                "storage_technology_id": _uuid(version_id, "storage_technology", item.technology_code),
                "technology_code": item.technology_code, "technology_name": item.technology_name,
                "parameters": row, "data_status": item.data_status, "source_note": item.source_note,
            })
        for item in bundle.site_technology_options:
            row = asdict(item)
            planning_options.append({
                "option_id": _uuid(version_id, "storage_site_technology_option", f"{item.site_code}:{item.technology_code}"),
                "site_code": item.site_code, "technology_code": item.technology_code,
                "limits": row, "available": item.available, "source_note": item.source_note,
            })
        for item in bundle.scenarios:
            row = asdict(item)
            planning_scenarios.append({
                "planning_scenario_id": _uuid(version_id, "storage_planning_scenario", f"{bundle.scenario_set_code}:{item.scenario_code}"),
                "scenario_set_code": bundle.scenario_set_code, "scenario_code": item.scenario_code,
                "scenario_name": item.scenario_name, "weight": item.weight,
                "core_for_feasibility": item.core_for_feasibility, "scenario": row,
                "data_status": item.data_status, "source_note": item.source_note,
            })
        policy = asdict(bundle.policy)
        planning_policies.append({
            "planning_policy_id": _uuid(version_id, "storage_planning_policy", bundle.policy.policy_code),
            "policy_code": bundle.policy.policy_code, "policy": policy,
            "data_status": bundle.policy.data_status, "source_note": bundle.policy.source_note,
        })

    return {
        "stations": stations,
        "segments": segments,
        "train_types": train_types,
        "storage_devices": storage_devices,
        "power_arms": power_arms,
        "signaling_blocks": signaling_blocks,
        "station_resources": station_resources,
        "storage_candidate_sites": planning_sites,
        "storage_technologies": planning_technologies,
        "storage_site_technology_options": planning_options,
        "storage_planning_scenarios": planning_scenarios,
        "storage_planning_policies": planning_policies,
    }
