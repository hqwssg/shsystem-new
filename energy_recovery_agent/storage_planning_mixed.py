"""从当前朔黄混合数据生成可运行的储能规划输入包。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple
import csv
import json
import re
import shutil

from storage_planning_contract import load_storage_planning_bundle, validate_storage_planning_power_arm_references


SITE_FIELDS = (
    "site_code", "site_name", "position_km", "power_arm_code", "storage_section_start_km",
    "storage_section_end_km", "direction", "buildable", "max_connection_power_kw",
    "max_capacity_kwh", "fixed_site_cost_cny", "allowed_technology_codes", "data_status", "source_note",
)
TECH_FIELDS = (
    "technology_code", "technology_name", "min_capacity_kwh", "max_capacity_kwh", "capacity_step_kwh",
    "min_charge_power_kw", "max_charge_power_kw", "charge_power_step_kw", "min_discharge_power_kw",
    "max_discharge_power_kw", "discharge_power_step_kw", "charge_efficiency", "discharge_efficiency",
    "min_soc_ratio", "max_soc_ratio", "self_discharge_rate_per_hour", "calendar_life_years", "cycle_life",
    "fixed_device_cost_cny", "cost_per_kwh_cny", "charge_power_cost_per_kw_cny",
    "discharge_power_cost_per_kw_cny", "annual_om_rate", "throughput_degradation_cost_per_kwh",
    "data_status", "source_note",
)
OPTION_FIELDS = (
    "site_code", "technology_code", "min_capacity_kwh", "max_capacity_kwh", "max_charge_power_kw",
    "max_discharge_power_kw", "max_unit_count", "available", "source_note",
)


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        writer.writerows(rows)


def _storage_range(token: str, row: Mapping[str, str]) -> Tuple[float, float]:
    start = str(row.get("storage_start_km") or "").strip()
    end = str(row.get("storage_end_km") or "").strip()
    if start and end:
        return float(start), float(end)
    match = re.search(r"K\s*([0-9.]+)\s*-\s*K?\s*([0-9.]+)", token, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"无法从储能区段 {token!r} 解析公里范围。")
    return float(match.group(1)), float(match.group(2))


def _candidate_sites(data_dir: Path, battery: Mapping[str, Any]) -> List[Dict[str, Any]]:
    arms = [
        row for row in _read_csv(data_dir / "power_arm_intervals.csv")
        if str(row.get("road") or "").strip() in {"朔黄线", "Shuohuang"}
    ]
    stations = _read_csv(data_dir / "stations.csv")
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in arms:
        raw_ids = str(row.get("storage_section_id") or "").strip()
        if not raw_ids:
            continue
        for raw_token in raw_ids.split(";"):
            token = raw_token.strip()
            if not token:
                continue
            start, end = _storage_range(token, row)
            code = token.split(":", 1)[0].strip()
            entry = grouped.setdefault(code, {"start": start, "end": end, "rows": []})
            if abs(entry["start"] - start) > 1e-6 or abs(entry["end"] - end) > 1e-6:
                raise ValueError(f"储能区段 {code} 在供电臂表中存在不一致范围。")
            entry["rows"].append(row)
    if not grouped:
        raise ValueError("power_arm_intervals.csv 未声明任何储能规划区段。")

    nominal_capacity = float(battery["capacity_kwh"])
    nominal_charge = float(battery["max_charge_power_kW"])
    raw_discharge = float(battery.get("max_discharge_power_kW", 0.0))
    # The received storage document omits maximum discharge power.  Planning still
    # needs a positive design variable, so use a clearly labelled symmetric design
    # assumption here; the operational baseline remains conservative at zero.
    planning_discharge = float(battery.get("planning_max_discharge_power_assumption_kW", nominal_charge))
    nominal_discharge = raw_discharge if raw_discharge > 0.0 else planning_discharge
    nominal_power = min(nominal_charge, nominal_discharge)
    output: List[Dict[str, Any]] = []
    for code, item in sorted(grouped.items()):
        midpoint = (item["start"] + item["end"]) / 2.0
        in_range = [row for row in stations if item["start"] <= float(row["position_km"]) <= item["end"]]
        station = min(in_range or stations, key=lambda row: abs(float(row["position_km"]) - midpoint))
        # 没有车站落在服务区段内时保留“邻近站点”作为可读标签，但候选电气接入点取区段中点。
        # 这仍是 planning_placeholder，不能解释为已确认的站内施工位置。
        position = float(station["position_km"]) if in_range else midpoint
        matching_arms = [
            row for row in item["rows"]
            if float(row["start_km"]) <= position <= float(row["end_km"])
        ]
        if not matching_arms:
            position = midpoint
            matching_arms = [
                row for row in item["rows"]
                if float(row["start_km"]) <= position <= float(row["end_km"])
            ]
        arm = sorted(matching_arms, key=lambda row: (str(row.get("direction")), str(row.get("section_id"))))[0]
        output.append({
            "site_code": f"MIXED-{code.upper()}",
            "site_name": f"{station['name']}附近规划候选（{code}）",
            "position_km": round(position, 6),
            "power_arm_code": arm.get("power_arm_id") or arm["section_id"],
            "storage_section_start_km": item["start"],
            "storage_section_end_km": item["end"],
            "direction": "both",
            "buildable": "true",
            "max_connection_power_kw": nominal_power * 2.0,
            "max_capacity_kwh": nominal_capacity * 2.0,
            "fixed_site_cost_cny": 4000000,
            "allowed_technology_codes": "MIXED-HYBRID",
            "data_status": "planning_placeholder",
            "source_note": "由混合数据中的规划储能区段与最近主线站点自动生成；可建设性、接入上限和成本待正式资料确认。",
        })
    return output


def build_storage_planning_mixed_inputs(
    data_dir: Path | str,
    timetable_path: Path | str,
    output_dir: Path | str,
) -> Dict[str, Any]:
    """生成五文件规划输入包，并完成合同与供电臂交叉校验。"""

    data_root = Path(data_dir).resolve()
    timetable_source = Path(timetable_path).resolve()
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    battery = json.loads((data_root / "battery.json").read_text(encoding="utf-8"))
    sites = _candidate_sites(data_root, battery)
    nominal_capacity = float(battery["capacity_kwh"])
    nominal_charge = float(battery["max_charge_power_kW"])
    raw_discharge = float(battery.get("max_discharge_power_kW", 0.0))
    discharge_is_assumed = raw_discharge <= 0.0
    nominal_discharge = (
        float(battery.get("planning_max_discharge_power_assumption_kW", nominal_charge))
        if discharge_is_assumed else raw_discharge
    )
    one_way_efficiency = float(battery["round_trip_efficiency"]) ** 0.5

    timetable_name = "mixed_running_diagram" + timetable_source.suffix.lower()
    shutil.copy2(timetable_source, output_root / timetable_name)
    _write_csv(output_root / "storage_candidate_sites.csv", SITE_FIELDS, sites)
    _write_csv(output_root / "storage_technologies.csv", TECH_FIELDS, [{
        "technology_code": "MIXED-HYBRID",
        "technology_name": "混合数据飞轮+钛酸锂规划参数族",
        "min_capacity_kwh": nominal_capacity * 0.5,
        "max_capacity_kwh": nominal_capacity * 2.0,
        "capacity_step_kwh": nominal_capacity * 0.5,
        "min_charge_power_kw": nominal_charge * 0.5,
        "max_charge_power_kw": nominal_charge * 2.0,
        "charge_power_step_kw": nominal_charge * 0.5,
        "min_discharge_power_kw": nominal_discharge * 0.5,
        "max_discharge_power_kw": nominal_discharge * 2.0,
        "discharge_power_step_kw": nominal_discharge * 0.5,
        "charge_efficiency": one_way_efficiency,
        "discharge_efficiency": one_way_efficiency,
        "min_soc_ratio": 0.1,
        "max_soc_ratio": 0.9,
        "self_discharge_rate_per_hour": 0.00005,
        "calendar_life_years": 12,
        "cycle_life": 6000,
        "fixed_device_cost_cny": 1500000,
        "cost_per_kwh_cny": 900,
        "charge_power_cost_per_kw_cny": 250,
        "discharge_power_cost_per_kw_cny": 250,
        "annual_om_rate": 0.02,
        "throughput_degradation_cost_per_kwh": battery.get("depreciation_cost_per_kwh", 0.25),
        # 该行同时包含资料提供值和未获原件支持的成本、寿命、SOC、
        # 充放电效率拆分等规划假设，整体只能按占位输入参与规划。
        "data_status": "planning_placeholder",
        "source_note": (
            "容量、最大充电功率、往返效率和吞吐折旧来自5.储能系统参数.doc；"
            + ("最大放电功率缺失，规划阶段暂按与最大充电功率相同处理；" if discharge_is_assumed else "最大放电功率来自当前数据；")
            + "投资、寿命、SOC范围及充放电效率拆分仍为本地敏感性占位参数。"
        ),
    }])
    _write_csv(output_root / "storage_site_technology_options.csv", OPTION_FIELDS, [{
        "site_code": site["site_code"],
        "technology_code": "MIXED-HYBRID",
        "min_capacity_kwh": nominal_capacity * 0.5,
        "max_capacity_kwh": site["max_capacity_kwh"],
        "max_charge_power_kw": site["max_connection_power_kw"],
        "max_discharge_power_kw": site["max_connection_power_kw"],
        "max_unit_count": 2,
        "available": "true",
        "source_note": "本地混合数据规划选项；需由正式接入和建设条件替换。",
    } for site in sites])
    timetable_source_note = (
        "运行图来自已登记的2026-06-13实绩重建运行图；"
        if "measured_20260613" in timetable_source.as_posix()
        else "运行图来自项目当前运行图模板；"
    )
    scenarios = {
        "schema_version": "1.0",
        "scenario_set_code": "shuohuang_mixed_current_timetable_v1",
        "scenarios": [
            {
                "scenario_code": "mixed_current_timetable",
                "scenario_name": "朔黄混合数据当前运行图",
                "weight": 0.7,
                "core_for_feasibility": True,
                "timetable_relative_path": timetable_name,
                "grid_price_per_kwh": float(battery.get("grid_price_per_kwh", 0.65)),
                "demand_charge_per_kw_year": 260,
                "wasted_energy_penalty_per_kwh": 0.05,
                "parameter_overrides": {},
                "storage_outage_site_codes": [],
                "data_status": "planning_placeholder",
                "source_note": timetable_source_note + "车辆、电气、价格和储能参数仍含规划占位。",
            },
            {
                "scenario_code": "mixed_storage_power_derating",
                "scenario_name": "储能充放电功率降额50%",
                "weight": 0.2,
                "core_for_feasibility": True,
                "timetable_relative_path": timetable_name,
                "grid_price_per_kwh": float(battery.get("grid_price_per_kwh", 0.65)),
                "demand_charge_per_kw_year": 260,
                "wasted_energy_penalty_per_kwh": 0.05,
                "parameter_overrides": {"storage_power_factor": 0.5},
                "storage_outage_site_codes": [],
                "data_status": "planning_placeholder",
                "source_note": "用于本地验证设备功率降额下推荐方案的稳健性。",
            },
            {
                "scenario_code": "mixed_single_site_outage",
                "scenario_name": "第一候选储能站停运",
                "weight": 0.1,
                "core_for_feasibility": True,
                "timetable_relative_path": timetable_name,
                "grid_price_per_kwh": float(battery.get("grid_price_per_kwh", 0.65)),
                "demand_charge_per_kw_year": 260,
                "wasted_energy_penalty_per_kwh": 0.05,
                "parameter_overrides": {},
                "storage_outage_site_codes": [sites[0]["site_code"]],
                "data_status": "planning_placeholder",
                "source_note": "用于本地验证单站停运场景，不代表现场故障概率。",
            },
        ],
    }
    policy = {
        "schema_version": "1.0", "policy_code": "shuohuang_mixed_local_v1",
        "planning_horizon_years": 12, "discount_rate": 0.06, "analysis_days_per_year": 365,
        "max_site_count": min(2, len(sites)), "total_budget_cny": 100000000,
        "allow_no_build": True, "target_final_soc_rule": "cyclic", "final_soc_tolerance_kwh": 0,
        "objective_mode": "annualized_cost", "include_demand_charge": True,
        "allow_timetable_coordination": False, "coordination_shortlist_size": 0,
        "core_scenarios_must_all_be_feasible": True, "risk_measure": "expected", "cvar_alpha": None,
        "minimum_grid_reduction_kwh": 1, "minimum_annual_saving_cny": 1,
        "solver_profile": "standard", "max_wall_clock_s": 600, "seed": 20260916,
        "data_status": "planning_placeholder",
        "source_note": "本地混合数据闭环策略；预算、电价与经济门槛均待正式资料确认。",
    }
    (output_root / "storage_planning_scenarios.json").write_text(json.dumps(scenarios, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_root / "storage_planning_policy.json").write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
    bundle = load_storage_planning_bundle(output_root)
    validate_storage_planning_power_arm_references(bundle, data_root / "power_arm_intervals.csv")
    summary = bundle.summary()
    summary.update({
        "generated_from_data_dir": str(data_root),
        "timetable_source": str(timetable_source),
        "output_dir": str(output_root),
    })
    (output_root / "mixed_input_build_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


__all__ = ["build_storage_planning_mixed_inputs"]
