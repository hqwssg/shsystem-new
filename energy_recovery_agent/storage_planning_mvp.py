"""固定运行图下的储能基线、热点分析与离散选址定容规划 MVP。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from itertools import combinations, product
from pathlib import Path
from time import monotonic
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple, Optional
import csv
import json
import math

from energy_settlement import build_settlement_energy_bins
from power_arm_electrical_limits import (
    PowerArmElectricalLimit,
    StorageSectionInterval,
    load_power_arm_electrical_limits,
)
from power_arm_lookup import load_power_arm_intervals
from rolling_optimizer import GeneratedSchedule, ScheduleTemplate, build_power_series, generate_schedule
from run_dispatch_case import (
    CaseInputs,
    build_settlement_series,
    load_case_inputs,
    make_settlement_system,
)
from scheduler_nsga2 import PowerSeriesCache, build_power_cache
from storage_planning_contract import (
    StorageCandidateSite,
    StoragePlanningBundle,
    StoragePlanningScenario,
    StorageSiteTechnologyOption,
    StorageTechnology,
    load_storage_planning_bundle,
    validate_storage_planning_power_arm_references,
)
from timetable_input import load_canonical_timetable
from train_simulator import BatteryStorageParameters, DavisCoefficients, StorageDeviceParameters, TrainParameters


@dataclass(frozen=True)
class StoragePlanDevice:
    """一个离散候选方案中的单站设备决策。"""

    site_code: str
    site_name: str
    technology_code: str
    capacity_kwh: float
    charge_power_kw: float
    discharge_power_kw: float
    capex_cny: float
    annual_om_cny: float


@dataclass(frozen=True)
class PreparedScenario:
    """已生成固定运行图和场景化列车参数的评价上下文。"""

    source: StoragePlanningScenario
    schedule: GeneratedSchedule
    trains: Mapping[str, TrainParameters]
    power_arm_limits: Mapping[str, PowerArmElectricalLimit]


def _train_cache_key(context: PreparedScenario, selected_ids: Tuple[str, ...]) -> Tuple[Any, ...]:
    """Return the geometry/dynamics key shared by scenarios with equal train inputs."""

    return (
        context.trains["Heavy"],
        context.trains["Empty"],
        tuple(context.schedule.heavy_departures_s),
        tuple(context.schedule.empty_departures_s),
        selected_ids,
    )


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    """按固定列顺序写 UTF-8 BOM CSV，空结果仍保留表头。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _crf(years: int, discount_rate: float) -> float:
    """计算资本回收系数；零贴现率时退化为直线年化。"""

    if discount_rate == 0.0:
        return 1.0 / years
    factor = (1.0 + discount_rate) ** years
    return discount_rate * factor / (factor - 1.0)


def _discrete_levels(minimum: float, maximum: float, step: float | None, max_levels: int | None) -> Tuple[float, ...]:
    """生成合法离散值；max_levels=None 表示完整原始步长域。"""

    if maximum < minimum - 1e-9:
        return ()
    if step is None:
        values = [minimum] if math.isclose(minimum, maximum) else [minimum, maximum]
    else:
        count = int(math.floor((maximum - minimum) / step + 1e-9))
        values = [minimum + index * step for index in range(count + 1)]
        if not math.isclose(values[-1], maximum, abs_tol=1e-9):
            values.append(maximum)
    if max_levels is None or len(values) <= max_levels:
        return tuple(float(value) for value in values)
    indices = sorted({round(index * (len(values) - 1) / (max_levels - 1)) for index in range(max_levels)})
    return tuple(float(values[index]) for index in indices)


def _effective_option_domain(
    site: StorageCandidateSite,
    technology: StorageTechnology,
    option: StorageSiteTechnologyOption,
    max_levels: int | None,
) -> Iterable[StoragePlanDevice]:
    """把技术参数、站点接入上限和关联表上限求交后生成单站设备档位。"""

    option_min_capacity = (
        option.min_capacity_kwh
        if option.min_capacity_kwh is not None
        else technology.min_capacity_kwh
    )
    option_max_capacity = (
        option.max_capacity_kwh
        if option.max_capacity_kwh is not None
        else technology.max_capacity_kwh
    )
    option_max_charge = (
        option.max_charge_power_kw
        if option.max_charge_power_kw is not None
        else technology.max_charge_power_kw
    )
    option_max_discharge = (
        option.max_discharge_power_kw
        if option.max_discharge_power_kw is not None
        else technology.max_discharge_power_kw
    )
    cap_min = max(technology.min_capacity_kwh, option_min_capacity)
    cap_max = min(site.max_capacity_kwh, technology.max_capacity_kwh, option_max_capacity)
    charge_max = min(site.max_connection_power_kw, technology.max_charge_power_kw, option_max_charge)
    discharge_max = min(site.max_connection_power_kw, technology.max_discharge_power_kw, option_max_discharge)
    capacities = _discrete_levels(cap_min, cap_max, technology.capacity_step_kwh, max_levels)
    charge_powers = _discrete_levels(technology.min_charge_power_kw, charge_max, technology.charge_power_step_kw, max_levels)
    discharge_powers = _discrete_levels(technology.min_discharge_power_kw, discharge_max, technology.discharge_power_step_kw, max_levels)
    for capacity, charge_power, discharge_power in product(capacities, charge_powers, discharge_powers):
        capex = (
            site.fixed_site_cost_cny
            + technology.fixed_device_cost_cny
            + capacity * technology.cost_per_kwh_cny
            + charge_power * technology.charge_power_cost_per_kw_cny
            + discharge_power * technology.discharge_power_cost_per_kw_cny
        )
        yield StoragePlanDevice(
            site_code=site.site_code,
            site_name=site.site_name,
            technology_code=technology.technology_code,
            capacity_kwh=capacity,
            charge_power_kw=charge_power,
            discharge_power_kw=discharge_power,
            capex_cny=capex,
            annual_om_cny=capex * technology.annual_om_rate,
        )


def _plan_structure(devices: Sequence[StoragePlanDevice]) -> Tuple[Tuple[str, str], ...]:
    return tuple(sorted((item.site_code, item.technology_code) for item in devices))


def _plan_signature(devices: Sequence[StoragePlanDevice]) -> Tuple[Tuple[Any, ...], ...]:
    return tuple(sorted(
        (item.site_code, item.technology_code, item.capacity_kwh, item.charge_power_kw, item.discharge_power_kw)
        for item in devices
    ))


def enumerate_storage_plans(
    bundle: StoragePlanningBundle,
    max_levels: int | None = 2,
    allowed_structures: Sequence[Tuple[Tuple[str, str], ...]] | None = None,
) -> Tuple[Tuple[StoragePlanDevice, ...], ...]:
    """枚举粗粒度、完整步长域或指定站址/技术结构的完整参数域。"""

    if max_levels is not None and max_levels < 2:
        raise ValueError("max_levels 必须至少为 2，以保留每个维度的上下界。")
    sites = {item.site_code: item for item in bundle.sites if item.buildable}
    technologies = {item.technology_code: item for item in bundle.technologies}
    by_site: Dict[str, List[StoragePlanDevice]] = {code: [] for code in sites}
    for option in bundle.site_technology_options:
        if option.available and option.site_code in sites:
            by_site[option.site_code].extend(
                _effective_option_domain(sites[option.site_code], technologies[option.technology_code], option, max_levels)
            )
    # 无储能基线是所有收益的比较基准，即使策略不允许最终选择“不建设”，也必须评价。
    plans: List[Tuple[StoragePlanDevice, ...]] = [tuple()]
    site_codes = sorted(code for code, values in by_site.items() if values)
    if allowed_structures is not None:
        plans = []
        for structure in sorted(set(allowed_structures)):
            choices = []
            for site_code, technology_code in structure:
                values = [item for item in by_site.get(site_code, ()) if item.technology_code == technology_code]
                if not values:
                    choices = []
                    break
                choices.append(values)
            if choices:
                plans.extend(tuple(items) for items in product(*choices))
        unique = {_plan_signature(plan): plan for plan in plans}
        return tuple(unique[key] for key in sorted(unique))
    for site_count in range(1, min(bundle.policy.max_site_count, len(site_codes)) + 1):
        for selected_codes in combinations(site_codes, site_count):
            plans.extend(tuple(items) for items in product(*(by_site[code] for code in selected_codes)))
    return tuple(plans)


def _apply_train_overrides(trains: Mapping[str, TrainParameters], overrides: Mapping[str, float]) -> Dict[str, TrainParameters]:
    """将典型日参数倍率作用于列车对象，不修改权威输入文件。"""

    output: Dict[str, TrainParameters] = {}
    for key, train in trains.items():
        mass_factor = overrides.get("heavy_mass_factor", 1.0) if key == "Heavy" else overrides.get("empty_mass_factor", 1.0)
        traction_factor = overrides.get("traction_power_factor", 1.0)
        brake_factor = overrides.get("brake_power_factor", 1.0)
        davis_factor = overrides.get("davis_resistance_factor", 1.0)
        output[key] = replace(
            train,
            mass_tons=train.mass_tons * mass_factor,
            # 车辆质量随倍率同步缩放，保持「总重 = 车辆 + 机车」的记录口径一致。
            vehicle_mass_tons=(
                train.vehicle_mass_tons * mass_factor
                if train.vehicle_mass_tons is not None
                else None
            ),
            mass_min_tons=None,
            mass_max_tons=None,
            max_traction_kN=train.max_traction_kN * traction_factor,
            max_brake_kN=train.max_brake_kN * brake_factor,
            max_power_kW=train.max_power_kW * traction_factor,
            # 配置了 locomotive_consist 时功率上限由特性表逐台累加得到，
            # 只缩放 max_power_kW 不会生效，必须同时给出 power_scale。
            power_scale=train.power_scale * traction_factor,
            davis=DavisCoefficients(
                a=train.davis.a * davis_factor,
                b=train.davis.b * davis_factor,
                c=train.davis.c * davis_factor,
            ),
            mass_data_status="storage_planning_scenario",
            mass_note=f"储能规划场景倍率：{dict(overrides)}",
        )
    return output


def _scaled_power_arm_limits(
    limits: Mapping[str, PowerArmElectricalLimit], factor: float
) -> Dict[str, PowerArmElectricalLimit]:
    """按场景倍率统一缩放供电、再生吸收和反馈能力。"""

    return {
        key: replace(
            value,
            max_traction_supply_kw=value.max_traction_supply_kw * factor,
            max_regen_absorption_kw=value.max_regen_absorption_kw * factor,
            max_grid_feedback_kw=value.max_grid_feedback_kw * factor,
        )
        for key, value in limits.items()
    }


def _schedule_from_timetable(scenario: StoragePlanningScenario, planning_root: Path) -> GeneratedSchedule:
    """把合同引用的规范运行图转换为储能评价所需的固定发车序列。"""

    assert scenario.timetable_relative_path is not None
    timetable_path = planning_root / scenario.timetable_relative_path
    timetable = load_canonical_timetable(timetable_path)
    if not timetable.validation_report.is_valid:
        errors = "; ".join(
            f"{item.sheet}:{item.row or '-'}:{item.field}:{item.message}"
            for item in timetable.validation_report.errors[:5]
        )
        raise ValueError(f"场景 {scenario.scenario_code} 的运行图校验失败：{errors}")

    stops_by_train: Dict[str, List[Any]] = {}
    for stop in timetable.stops:
        stops_by_train.setdefault(stop.train_id, []).append(stop)
    heavy: List[Tuple[int, str]] = []
    empty: List[Tuple[int, str]] = []
    for train in timetable.trains:
        train_stops = sorted(stops_by_train.get(train.train_id, ()), key=lambda item: item.seq)
        if not train_stops:
            raise ValueError(f"场景 {scenario.scenario_code} 的列车 {train.train_id} 没有运行图节点。")
        departure = int(train_stops[0].departure_time_s)
        normalized_type = train.train_type.strip().lower()
        if normalized_type == "heavy":
            heavy.append((departure, train.train_id))
        elif normalized_type == "empty":
            empty.append((departure, train.train_id))
        else:
            raise ValueError(
                f"场景 {scenario.scenario_code} 的列车 {train.train_id} 类型为 {train.train_type!r}；"
                "储能规划当前只接受 Heavy 或 Empty。"
            )

    def headway(items: Sequence[Tuple[int, str]]) -> int:
        times = sorted(item[0] for item in items)
        gaps = [later - earlier for earlier, later in zip(times, times[1:]) if later > earlier]
        return max(1, int(round(sum(gaps) / len(gaps)))) if gaps else 1

    heavy.sort()
    empty.sort()
    first_heavy = heavy[0][0] if heavy else 0
    first_empty = empty[0][0] if empty else first_heavy
    template = ScheduleTemplate(
        heavy_headway_s=headway(heavy),
        empty_headway_s=headway(empty),
        heavy_empty_phase_s=max(0, first_empty - first_heavy),
        heavy_count=len(heavy),
        empty_count=len(empty),
        start_time_s=min(first_heavy, first_empty),
    )
    return GeneratedSchedule(
        heavy_departures_s=[item[0] for item in heavy],
        empty_departures_s=[item[0] for item in empty],
        template=template,
        heavy_train_ids=[item[1] for item in heavy],
        empty_train_ids=[item[1] for item in empty],
    )


def _local_continuous_refinement_plans(
    bundle: StoragePlanningBundle,
    devices: Sequence[StoragePlanDevice],
) -> Tuple[Tuple[StoragePlanDevice, ...], ...]:
    """Generate a small local interpolation neighborhood around a discrete plan."""

    sites = {item.site_code: item for item in bundle.sites}
    technologies = {item.technology_code: item for item in bundle.technologies}
    options = {
        (item.site_code, item.technology_code): item
        for item in bundle.site_technology_options
        if item.available
    }

    def bounds(device: StoragePlanDevice) -> Tuple[float, float, float, float, float, float]:
        site = sites[device.site_code]
        technology = technologies[device.technology_code]
        option = options[(device.site_code, device.technology_code)]
        capacity_min = max(
            technology.min_capacity_kwh,
            option.min_capacity_kwh if option.min_capacity_kwh is not None else technology.min_capacity_kwh,
        )
        capacity_max = min(
            site.max_capacity_kwh,
            technology.max_capacity_kwh,
            option.max_capacity_kwh if option.max_capacity_kwh is not None else technology.max_capacity_kwh,
        )
        charge_max = min(
            site.max_connection_power_kw,
            technology.max_charge_power_kw,
            option.max_charge_power_kw if option.max_charge_power_kw is not None else technology.max_charge_power_kw,
        )
        discharge_max = min(
            site.max_connection_power_kw,
            technology.max_discharge_power_kw,
            option.max_discharge_power_kw if option.max_discharge_power_kw is not None else technology.max_discharge_power_kw,
        )
        return (
            float(capacity_min), float(capacity_max),
            float(technology.min_charge_power_kw), float(charge_max),
            float(technology.min_discharge_power_kw), float(discharge_max),
        )

    def interpolate(current: float, minimum: float, maximum: float) -> Tuple[float, ...]:
        if maximum <= minimum + 1e-9:
            return (current,)
        values = (current, minimum + 0.5 * (current - minimum), current + 0.5 * (maximum - current))
        return tuple(sorted({round(max(minimum, min(maximum, value)), 6) for value in values}))

    def reprice(device: StoragePlanDevice, capacity: float, charge: float, discharge: float) -> StoragePlanDevice:
        site = sites[device.site_code]
        technology = technologies[device.technology_code]
        capex = (
            site.fixed_site_cost_cny
            + technology.fixed_device_cost_cny
            + capacity * technology.cost_per_kwh_cny
            + charge * technology.charge_power_cost_per_kw_cny
            + discharge * technology.discharge_power_cost_per_kw_cny
        )
        return replace(
            device,
            capacity_kwh=capacity,
            charge_power_kw=charge,
            discharge_power_kw=discharge,
            capex_cny=capex,
            annual_om_cny=capex * technology.annual_om_rate,
        )

    base = tuple(devices)
    candidates: Dict[Tuple[Tuple[Any, ...], ...], Tuple[StoragePlanDevice, ...]] = {}
    candidates[_plan_signature(base)] = base
    for index, device in enumerate(base):
        cap_min, cap_max, charge_min, charge_max, discharge_min, discharge_max = bounds(device)
        variants = []
        for capacity in interpolate(device.capacity_kwh, cap_min, cap_max):
            variants.append(reprice(device, capacity, device.charge_power_kw, device.discharge_power_kw))
        for charge in interpolate(device.charge_power_kw, charge_min, charge_max):
            variants.append(reprice(device, device.capacity_kwh, charge, device.discharge_power_kw))
        for discharge in interpolate(device.discharge_power_kw, discharge_min, discharge_max):
            variants.append(reprice(device, device.capacity_kwh, device.charge_power_kw, discharge))
        for variant in variants:
            plan = tuple(variant if position == index else other for position, other in enumerate(base))
            candidates[_plan_signature(plan)] = plan
    return tuple(candidates[key] for key in sorted(candidates))


def _fixed_schedule(scenario: StoragePlanningScenario, planning_root: Path) -> GeneratedSchedule:
    """把合同中的模板或运行图文件冻结成逐列车发车时刻；规划器不改变运行图。"""

    if scenario.schedule_template is None:
        return _schedule_from_timetable(scenario, planning_root)
    item = scenario.schedule_template
    return generate_schedule(
        ScheduleTemplate(
            heavy_headway_s=item.heavy_headway_s,
            empty_headway_s=item.empty_headway_s,
            heavy_empty_phase_s=item.heavy_empty_phase_s,
            heavy_count=item.heavy_count,
            empty_count=item.empty_count,
        )
    )


def _selected_geometry(
    devices: Sequence[StoragePlanDevice], sites: Mapping[str, StorageCandidateSite]
) -> Tuple[Tuple[StorageSectionInterval, ...], List[Tuple[float, float]]]:
    """将站点决策转换为仿真器可识别的设备服务区段。"""

    sections: List[StorageSectionInterval] = []
    ranges: List[Tuple[float, float]] = []
    for device in devices:
        site = sites[device.site_code]
        directions = ("forward", "reverse") if site.direction == "both" else (site.direction,)
        for direction in directions:
            sections.append(
                StorageSectionInterval(
                    storage_section_id=site.site_code,
                    start_km=site.storage_section_start_km,
                    end_km=site.storage_section_end_km,
                    direction=direction,
                )
            )
        ranges.append((site.storage_section_start_km, site.storage_section_end_km))
    return tuple(sections), ranges


def _limits_for_devices(
    base_limits: Mapping[str, PowerArmElectricalLimit],
    power_arm_path: Path,
    devices: Sequence[StoragePlanDevice],
    sites: Mapping[str, StorageCandidateSite],
) -> Dict[str, PowerArmElectricalLimit]:
    """仅为被选站址覆盖的供电臂写入对应设备 ID，未建设站点保持不可储能。"""

    output = {
        key: replace(value, storage_available=False, storage_section_id="", storage_status="storage_planning_not_selected")
        for key, value in base_limits.items()
    }
    selected_sites = [sites[item.site_code] for item in devices]
    for interval in load_power_arm_intervals(power_arm_path):
        matches = [
            site
            for site in selected_sites
            if site.storage_section_start_km < interval.max_km
            and site.storage_section_end_km > interval.min_km
            and (
                site.direction == "both"
                or (site.direction == "forward" and interval.direction in {"下行", "down", "forward"})
                or (site.direction == "reverse" and interval.direction in {"上行", "up", "reverse"})
            )
        ]
        if not matches or interval.section_id not in output:
            continue
        storage_ids = ";".join(sorted({site.site_code for site in matches}))
        output[interval.section_id] = replace(
            output[interval.section_id],
            storage_available=True,
            storage_section_id=storage_ids,
            storage_status="storage_planning_selected",
            storage_note="由阶段B离散规划候选方案临时映射。",
        )
    return output


def _battery_for_devices(
    devices: Sequence[StoragePlanDevice],
    technologies: Mapping[str, StorageTechnology],
    efficiency_factor: float,
    grid_price: float,
    power_factor: float = 1.0,
    outage_site_codes: Sequence[str] = (),
) -> BatteryStorageParameters:
    """构建设备级物理参数；初始 SOC 取下限，避免用期初库存制造虚假节能。"""

    parameters: List[StorageDeviceParameters] = []
    outage_ids = set(outage_site_codes)
    for device in devices:
        tech = technologies[device.technology_code]
        charge_efficiency = min(1.0, tech.charge_efficiency * efficiency_factor)
        discharge_efficiency = min(1.0, tech.discharge_efficiency * efficiency_factor)
        minimum_soc = tech.min_soc_ratio * device.capacity_kwh
        parameters.append(
            StorageDeviceParameters(
                storage_section_id=device.site_code,
                capacity_kwh=device.capacity_kwh,
                max_charge_power_kw=device.charge_power_kw * power_factor,
                max_discharge_power_kw=device.discharge_power_kw * power_factor,
                charge_efficiency=charge_efficiency,
                discharge_efficiency=discharge_efficiency,
                initial_soc_kwh=minimum_soc,
                min_soc_kwh=minimum_soc,
                max_soc_kwh=tech.max_soc_ratio * device.capacity_kwh,
                available=device.site_code not in outage_ids,
                self_discharge_rate_per_hour=tech.self_discharge_rate_per_hour,
                data_status=tech.data_status,
                source_note="阶段B规划候选设备；已计入自放电、场景功率降额和停运状态。",
            )
        )
    return BatteryStorageParameters(
        capacity_kwh=sum(item.capacity_kwh for item in parameters),
        round_trip_efficiency=1.0 if not parameters else min(item.charge_efficiency * item.discharge_efficiency for item in parameters),
        depreciation_cost_per_kwh=0.0,
        grid_price_per_kwh=grid_price,
        max_charge_power_kW=sum(item.max_charge_power_kw for item in parameters),
        max_discharge_power_kW=sum(item.max_discharge_power_kw for item in parameters),
        data_status="storage_planning_candidate" if parameters else "no_storage_baseline",
        scenario_name="阶段B固定运行图离散规划",
        planning_assumption=bool(parameters),
        note="设备级效率和 SOC 由规划合同生成；经济成本在规划层单独年化。",
        storage_devices=tuple(parameters),
    )


def _scenario_operating_cost(
    settlement: Any,
    scenario: StoragePlanningScenario,
    devices: Sequence[StoragePlanDevice],
    technologies: Mapping[str, StorageTechnology],
    days: int,
    include_demand_charge: bool,
) -> Tuple[float, float, float, float, float]:
    """计算典型日对应的年购电、退化、弃能和需量成本。"""

    grid = settlement.grid_kwh * scenario.grid_price_per_kwh * days
    degradation = 0.0
    for device in devices:
        throughput = (
            settlement.battery_charge_by_storage_kwh.get(device.site_code, 0.0)
            + settlement.battery_discharge_by_storage_kwh.get(device.site_code, 0.0)
        )
        degradation += throughput * technologies[device.technology_code].throughput_degradation_cost_per_kwh * days
    waste = settlement.wasted_kwh * scenario.wasted_energy_penalty_per_kwh * days
    peak_grid_kw = max(settlement.grid_kW, default=0.0)
    demand = peak_grid_kw * scenario.demand_charge_per_kw_year if include_demand_charge else 0.0
    return grid + degradation + waste + demand, grid, degradation, demand, peak_grid_kw


def _annualized_lifecycle_investment(
    devices: Sequence[StoragePlanDevice],
    sites: Mapping[str, StorageCandidateSite],
    technologies: Mapping[str, StorageTechnology],
    planning_horizon_years: int,
    discount_rate: float,
    annual_cycles_by_site: Mapping[str, float],
) -> Tuple[float, List[Dict[str, Any]]]:
    """按日历/循环寿命、折现重置和期末残值计算等年值投资。"""

    total_npv = 0.0
    details: List[Dict[str, Any]] = []
    for device in devices:
        site_cost = sites[device.site_code].fixed_site_cost_cny
        equipment_cost = max(0.0, device.capex_cny - site_cost)
        technology = technologies[device.technology_code]
        annual_cycles = max(0.0, annual_cycles_by_site.get(device.site_code, 0.0))
        cycle_life_years = (
            technology.cycle_life / annual_cycles if annual_cycles > 1e-12 else math.inf
        )
        effective_life = max(1e-6, min(technology.calendar_life_years, cycle_life_years))
        purchase_times: List[float] = []
        purchase_time = 0.0
        while purchase_time < planning_horizon_years - 1e-9:
            purchase_times.append(purchase_time)
            purchase_time += effective_life
        equipment_npv = sum(
            equipment_cost / ((1.0 + discount_rate) ** purchase_time)
            for purchase_time in purchase_times
        )
        last_purchase = purchase_times[-1] if purchase_times else 0.0
        age_at_horizon = planning_horizon_years - last_purchase
        remaining_life_ratio = max(0.0, min(1.0, (effective_life - age_at_horizon) / effective_life))
        residual_value = equipment_cost * remaining_life_ratio
        residual_npv = residual_value / ((1.0 + discount_rate) ** planning_horizon_years)
        device_npv = site_cost + equipment_npv - residual_npv
        total_npv += device_npv
        details.append({
            "site_code": device.site_code,
            "technology_code": device.technology_code,
            "annual_equivalent_cycles": annual_cycles,
            "calendar_life_years": technology.calendar_life_years,
            "cycle_limited_life_years": None if math.isinf(cycle_life_years) else cycle_life_years,
            "effective_life_years": effective_life,
            "replacement_count": max(0, len(purchase_times) - 1),
            "replacement_years": ";".join(f"{value:.6g}" for value in purchase_times[1:]),
            "residual_value_cny": residual_value,
            "discounted_lifecycle_investment_cny": device_npv,
        })
    return total_npv * _crf(planning_horizon_years, discount_rate), details


def _risk_aggregate(values: Sequence[Tuple[float, float]], risk_measure: str, alpha: float | None) -> float:
    """按合同风险口径聚合场景年成本。"""

    if risk_measure == "expected":
        return sum(weight * value for weight, value in values)
    if risk_measure == "worst_case":
        return max(value for _weight, value in values)
    threshold = float(alpha or 0.95)
    tail_mass = max(1e-12, 1.0 - threshold)
    remaining = tail_mass
    total = 0.0
    for weight, value in sorted(values, key=lambda item: item[1], reverse=True):
        take = min(remaining, weight)
        total += take * value
        remaining -= take
        if remaining <= 1e-12:
            break
    return total / tail_mass


def select_storage_plan(
    candidate_rows: Sequence[Mapping[str, Any]],
    *,
    allow_no_build: bool,
    objective_mode: str,
) -> Tuple[str, Mapping[str, Any], str]:
    """从已完整评价的离散候选中作出建设、不建设或不可行决策。"""

    baseline = next((row for row in candidate_rows if row["plan_id"] in {"NO_BUILD", "NO_BUILD_REFERENCE"}), None)
    if baseline is None:
        raise ValueError("候选结果缺少无储能参考方案。")
    feasible_builds = [
        row
        for row in candidate_rows
        if int(row["site_count"]) > 0
        and bool(row["within_budget"])
        and bool(row["core_feasible"])
        and bool(row["meets_business_thresholds"])
    ]

    def _tiebreak(row: Mapping[str, Any]) -> Tuple[Any, ...]:
        """并列时的决胜键必须只依赖**方案内容**，不能依赖 plan_id。

        ``plan_id`` 是按评估顺序编号的，而评估顺序随搜索模式变化
        （``exhaustive`` 先粗后细全部展开，``coarse_to_fine`` 先粗筛再展开短名单）。
        用 plan_id 决胜会让「成本完全相同」的两个方案在不同搜索模式下选出不同的那个，
        表现为「粗到精与穷举结果不一致」——这不是搜索没收敛，而是排序不确定。
        """

        return (
            str(row.get("site_codes") or ""),
            float(row.get("total_capacity_kwh") or 0.0),
            float(row.get("total_charge_power_kw") or 0.0),
            float(row.get("total_discharge_power_kw") or 0.0),
        )

    def rank(row: Mapping[str, Any]) -> Tuple[Any, ...]:
        if objective_mode == "energy_first":
            return (-float(row["grid_reduction_vs_no_build_kwh_per_year"]), float(row["annual_total_cost_cny"])) + _tiebreak(row)
        if objective_mode == "balanced":
            # 平衡模式先要求正收益，再以“单位年化成本带来的购电削减”排序。
            reduction = max(1e-9, float(row["grid_reduction_vs_no_build_kwh_per_year"]))
            return (float(row["annual_total_cost_cny"]) / reduction, float(row["annual_total_cost_cny"])) + _tiebreak(row)
        return (float(row["annual_total_cost_cny"]), -float(row["grid_reduction_vs_no_build_kwh_per_year"])) + _tiebreak(row)

    if feasible_builds:
        selected = min(feasible_builds, key=rank)
        return (
            "recommend_build",
            selected,
            "至少一个建设方案通过预算、核心场景和最低收益门槛，已按规划目标选择最优者。",
        )
    if bool(baseline["core_feasible"]) and allow_no_build:
        return (
            "keep_no_build",
            baseline,
            "无建设方案同时通过预算、核心场景及最低节能经济门槛，保留无储能基线。",
        )
    return (
        "no_feasible_plan",
        baseline,
        "无储能基线或全部建设候选未通过核心可行性，不能形成可提交方案。",
    )


def _series_for_schedule(schedule: GeneratedSchedule, heavy: PowerSeriesCache, empty_: PowerSeriesCache, step_s: int) -> List[Dict[int, Any]]:
    """生成不含储能设备的固定运行图功率序列，供热点分析复用。"""

    return build_power_series(heavy, schedule.heavy_departures_s, sample_step_s=step_s) + build_power_series(
        empty_, schedule.empty_departures_s, sample_step_s=step_s
    )


def _hotspot_rows(
    prepared: Sequence[PreparedScenario],
    case: CaseInputs,
    settlement_step_s: int,
    sites: Sequence[StorageCandidateSite],
) -> List[Dict[str, Any]]:
    """统计无储能条件下各供电臂的牵引、再生和同时发生时间，形成热点排序。"""

    aggregate: Dict[str, Dict[str, float]] = {}
    arm_intervals = {item.section_id: item for item in load_power_arm_intervals(case.power_arm_path)}
    grouped_contexts: Dict[Tuple[Any, ...], Tuple[PreparedScenario, float]] = {}

    def train_key(train: TrainParameters) -> Tuple[Any, ...]:
        return (
            float(train.mass_tons),
            float(train.max_traction_kN),
            float(train.max_brake_kN),
            float(train.max_power_kW),
            float(train.power_scale),
            float(train.rotational_mass_factor),
            float(train.davis.a),
            float(train.davis.b),
            float(train.davis.c),
            float(train.length_km),
            int(train.longitudinal_segments),
            str(train.direction),
            str(train.locomotive_type or ""),
            int(train.locomotive_count or 0),
            tuple(train.locomotive_consist or ()),
            str(train.freight_load_state or ""),
        )

    for context in prepared:
        group_key = (
            tuple(context.schedule.heavy_departures_s),
            tuple(context.schedule.empty_departures_s),
            train_key(context.trains["Heavy"]),
            train_key(context.trains["Empty"]),
        )
        representative, weight = grouped_contexts.get(group_key, (context, 0.0))
        grouped_contexts[group_key] = (representative, weight + context.source.weight)

    for context, context_weight in grouped_contexts.values():
        # 保留现有柔性供电能力作为无新增储能的基线。
        route = replace(case.route, energy_transfer_ranges_km=[])
        heavy = build_power_cache(context.trains["Heavy"], route, simulation_step_s=5, power_arm_interval_path=case.power_arm_path, storage_sections=())
        empty_ = build_power_cache(context.trains["Empty"], route, simulation_step_s=5, power_arm_interval_path=case.power_arm_path, storage_sections=())
        bucket_signs: Dict[Tuple[str, int], List[float]] = {}
        for series in _series_for_schedule(context.schedule, heavy, empty_, settlement_step_s):
            for time_s, sample in series.items():
                power_kw = float(sample[0])
                arm = str(sample[2]) if len(sample) >= 3 else "UNMAPPED"
                duration_s = float(sample[3]) if len(sample) >= 4 else 1.0
                row = aggregate.setdefault(arm, {"traction_kwh": 0.0, "regen_kwh": 0.0, "coincident_bucket_count": 0.0})
                energy = abs(power_kw) * duration_s / 3600.0 * context_weight
                row["traction_kwh" if power_kw >= 0.0 else "regen_kwh"] += energy
                signs = bucket_signs.setdefault((arm, int(time_s // settlement_step_s)), [0.0, 0.0])
                signs[0 if power_kw >= 0.0 else 1] += abs(power_kw)
        for (arm, _bucket), signs in bucket_signs.items():
            if signs[0] > 0.0 and signs[1] > 0.0:
                aggregate[arm]["coincident_bucket_count"] += context_weight
    rows = []
    for arm, values in aggregate.items():
        interval = arm_intervals.get(arm)
        if interval is None:
            matching_sites = [site for site in sites if site.power_arm_code == arm]
        else:
            matching_sites = [
                site
                for site in sites
                if site.storage_section_start_km < interval.max_km
                and site.storage_section_end_km > interval.min_km
                and (
                    site.direction == "both"
                    or (site.direction == "forward" and interval.direction in {"下行", "down", "forward"})
                    or (site.direction == "reverse" and interval.direction in {"上行", "up", "reverse"})
                )
            ]
        rows.append(
            {
                "power_arm_id": arm,
                "candidate_site_codes": ";".join(site.site_code for site in matching_sites),
                "buildable_candidate_site_codes": ";".join(site.site_code for site in matching_sites if site.buildable),
                "has_only_unbuildable_candidates": bool(matching_sites) and not any(site.buildable for site in matching_sites),
                "weighted_traction_kwh_per_typical_day": round(values["traction_kwh"], 6),
                "weighted_regen_kwh_per_typical_day": round(values["regen_kwh"], 6),
                "weighted_coincident_bucket_count": round(values["coincident_bucket_count"], 6),
                "hotspot_score": round(values["regen_kwh"] * (1.0 + min(values["coincident_bucket_count"], 10.0) / 10.0), 6),
            }
        )
    rows.sort(key=lambda row: (-float(row["hotspot_score"]), str(row["power_arm_id"])))
    for index, row in enumerate(rows, start=1):
        row["hotspot_rank"] = index
    return rows


def _hotspot_rows_from_cached_series(
    prepared: Sequence[PreparedScenario],
    series_by_key: Mapping[Tuple[Any, ...], List[Dict[int, Any]]],
    settlement_step_s: int,
    sites: Sequence[StorageCandidateSite],
    power_arm_path: Path,
) -> List[Dict[str, Any]]:
    """从无储能基线已缓存的功率序列生成热点排名。"""

    aggregate: Dict[str, Dict[str, float]] = {}
    grouped_contexts: Dict[Tuple[Any, ...], Tuple[PreparedScenario, float]] = {}

    def train_key(train: TrainParameters) -> Tuple[Any, ...]:
        return (
            float(train.mass_tons), float(train.max_traction_kN), float(train.max_brake_kN),
            float(train.max_power_kW), float(train.power_scale), float(train.rotational_mass_factor),
            float(train.davis.a), float(train.davis.b), float(train.davis.c),
            float(train.length_km), int(train.longitudinal_segments), str(train.direction),
            str(train.locomotive_type or ""), int(train.locomotive_count or 0),
            tuple(train.locomotive_consist or ()), str(train.freight_load_state or ""),
        )

    for context in prepared:
        key = (
            tuple(context.schedule.heavy_departures_s),
            tuple(context.schedule.empty_departures_s),
            train_key(context.trains["Heavy"]),
            train_key(context.trains["Empty"]),
        )
        representative, weight = grouped_contexts.get(key, (context, 0.0))
        grouped_contexts[key] = (representative, weight + context.source.weight)

    for context, context_weight in grouped_contexts.values():
        series = series_by_key.get((*_train_cache_key(context, ()), settlement_step_s))
        if series is None:
            raise RuntimeError(
                f"缺少储能规划无储能热点序列缓存：{context.source.scenario_code}"
            )
        bucket_signs: Dict[Tuple[str, int], List[float]] = {}
        for component in series:
            for time_s, sample in component.items():
                power_kw = float(sample[0])
                arm = str(sample[2]) if len(sample) >= 3 else "UNMAPPED"
                duration_s = float(sample[3]) if len(sample) >= 4 else 1.0
                row = aggregate.setdefault(
                    arm,
                    {"traction_kwh": 0.0, "regen_kwh": 0.0, "coincident_bucket_count": 0.0},
                )
                energy = abs(power_kw) * duration_s / 3600.0 * context_weight
                row["traction_kwh" if power_kw >= 0.0 else "regen_kwh"] += energy
                signs = bucket_signs.setdefault((arm, int(time_s // settlement_step_s)), [0.0, 0.0])
                signs[0 if power_kw >= 0.0 else 1] += abs(power_kw)
        for (arm, _bucket), signs in bucket_signs.items():
            if signs[0] > 0.0 and signs[1] > 0.0:
                aggregate[arm]["coincident_bucket_count"] += context_weight

    arm_intervals = {item.section_id: item for item in load_power_arm_intervals(power_arm_path)}
    rows = []
    for arm, values in aggregate.items():
        interval = arm_intervals.get(arm)
        matching_sites = []
        if interval is not None:
            matching_sites = [
                site
                for site in sites
                if site.storage_section_start_km < interval.max_km
                and site.storage_section_end_km > interval.min_km
                and (
                    site.direction == "both"
                    or (site.direction == "forward" and interval.direction in {"下行", "down", "forward"})
                    or (site.direction == "reverse" and interval.direction in {"上行", "up", "reverse"})
                )
            ]
        else:
            matching_sites = [site for site in sites if site.power_arm_code == arm]
        rows.append(
            {
                "power_arm_id": arm,
                "candidate_site_codes": ";".join(site.site_code for site in matching_sites),
                "buildable_candidate_site_codes": ";".join(site.site_code for site in matching_sites if site.buildable),
                "has_only_unbuildable_candidates": bool(matching_sites) and not any(site.buildable for site in matching_sites),
                "weighted_traction_kwh_per_typical_day": round(values["traction_kwh"], 6),
                "weighted_regen_kwh_per_typical_day": round(values["regen_kwh"], 6),
                "weighted_coincident_bucket_count": round(values["coincident_bucket_count"], 6),
                "hotspot_score": round(values["regen_kwh"] * (1.0 + min(values["coincident_bucket_count"], 10.0) / 10.0), 6),
            }
        )
    rows.sort(key=lambda row: (-float(row["hotspot_score"]), str(row["power_arm_id"])))
    for index, row in enumerate(rows, start=1):
        row["hotspot_rank"] = index
    return rows


def run_storage_planning_mvp(
    planning_input_dir: Path | str,
    case_data_dir: Path | str,
    output_dir: Path | str,
    *,
    power_arm_path: Path | str | None = None,
    max_levels_per_dimension: int = 2,
    settlement_step_s: int = 60,
    search_mode: str = "coarse",
    refinement_shortlist_size: int = 3,
    expected_policy_code: str | None = None,
    expected_scenario_set_code: str | None = None,
) -> Dict[str, Any]:
    """执行阶段B端到端流程并写出可审计的基线、热点、候选和推荐结果。"""

    started = monotonic()
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    bundle = load_storage_planning_bundle(planning_input_dir)
    wall_clock_limit = bundle.policy.max_wall_clock_s
    if expected_policy_code is not None and bundle.policy.policy_code != expected_policy_code:
        raise ValueError(
            f"规划策略编码不匹配：请求 {expected_policy_code!r}，输入版本为 {bundle.policy.policy_code!r}。"
        )
    if expected_scenario_set_code is not None and bundle.scenario_set_code != expected_scenario_set_code:
        raise ValueError(
            f"规划场景集编码不匹配：请求 {expected_scenario_set_code!r}，输入版本为 {bundle.scenario_set_code!r}。"
        )
    case = load_case_inputs(Path(case_data_dir), output_root / "case_data_validation")
    arm_path = Path(power_arm_path) if power_arm_path is not None else case.power_arm_path
    if arm_path.resolve() != case.power_arm_path.resolve():
        case = replace(
            case,
            power_arm_path=arm_path,
            power_arm_limits=load_power_arm_electrical_limits(arm_path),
        )
    validate_storage_planning_power_arm_references(bundle, arm_path)
    sites = {item.site_code: item for item in bundle.sites}
    technologies = {item.technology_code: item for item in bundle.technologies}
    prepared: List[PreparedScenario] = []
    schedule_cache: Dict[Tuple[Any, ...], GeneratedSchedule] = {}
    for scenario in bundle.scenarios:
        overrides = dict(scenario.parameter_overrides)
        if scenario.timetable_relative_path is not None:
            schedule_key = (
                "timetable",
                str((bundle.source_dir / scenario.timetable_relative_path).resolve()),
            )
        else:
            template = scenario.schedule_template
            assert template is not None
            schedule_key = (
                "template",
                template.heavy_count,
                template.empty_count,
                template.heavy_headway_s,
                template.empty_headway_s,
                template.heavy_empty_phase_s,
            )
        schedule = schedule_cache.get(schedule_key)
        if schedule is None:
            schedule = _fixed_schedule(scenario, bundle.source_dir)
            schedule_cache[schedule_key] = schedule
        prepared.append(
            PreparedScenario(
                source=scenario,
                schedule=schedule,
                trains=_apply_train_overrides(case.trains, overrides),
                power_arm_limits=_scaled_power_arm_limits(case.power_arm_limits, overrides.get("power_arm_capacity_factor", 1.0)),
            )
        )

    if search_mode not in {"coarse", "coarse_to_fine", "exhaustive"}:
        raise ValueError("search_mode 必须是 coarse、coarse_to_fine 或 exhaustive。")
    if refinement_shortlist_size < 1:
        raise ValueError("refinement_shortlist_size 必须至少为1。")
    plans = list(enumerate_storage_plans(
        bundle,
        max_levels=None if search_mode == "exhaustive" else max_levels_per_dimension,
    ))
    coarse_candidate_count = len(plans)
    baseline_rows: List[Dict[str, Any]] = []
    candidate_rows: List[Dict[str, Any]] = []
    scenario_rows: List[Dict[str, Any]] = []
    device_rows: List[Dict[str, Any]] = []
    device_scenario_rows: List[Dict[str, Any]] = []
    lifecycle_rows: List[Dict[str, Any]] = []
    cache_by_key: Dict[
        Tuple[Any, ...],
        Tuple[Any, PowerSeriesCache, PowerSeriesCache, Tuple[StorageSectionInterval, ...]],
    ] = {}
    series_by_key: Dict[Tuple[Any, ...], List[Dict[int, Any]]] = {}
    energy_bins_by_key: Dict[
        Tuple[Any, ...],
        Dict[Tuple[int, str, str, str], Tuple[float, float, float, float]],
    ] = {}

    def evaluate_plan(plan_id: str, devices: Tuple[StoragePlanDevice, ...]) -> Dict[str, Any]:
        selected_ids = tuple(sorted(item.site_code for item in devices))
        capex = sum(item.capex_cny for item in devices)
        annual_om = sum(item.annual_om_cny for item in devices)
        operating_costs: List[Tuple[float, float]] = []
        expected_grid = 0.0
        expected_grid_energy_cost = 0.0
        expected_waste = 0.0
        expected_annual_cycles_by_site = {item.site_code: 0.0 for item in devices}
        all_core_feasible = True
        for context in prepared:
            cache_key = _train_cache_key(context, selected_ids)
            if cache_key not in cache_by_key:
                sections, ranges = _selected_geometry(devices, sites)
                # 新增储能与已实施柔性供电能力可以同时存在。
                route = replace(case.route, energy_transfer_ranges_km=ranges)
                heavy = build_power_cache(context.trains["Heavy"], route, simulation_step_s=5, power_arm_interval_path=arm_path, storage_sections=sections)
                empty_ = build_power_cache(context.trains["Empty"], route, simulation_step_s=5, power_arm_interval_path=arm_path, storage_sections=sections)
                cache_by_key[cache_key] = (route, heavy, empty_, sections)
            route, heavy, empty_, sections = cache_by_key[cache_key]
            # 供电臂容量倍率属于场景结算约束，不影响动力学功率缓存。
            limits = _limits_for_devices(context.power_arm_limits, arm_path, devices, sites)
            overrides = dict(context.source.parameter_overrides)
            battery = _battery_for_devices(
                devices,
                technologies,
                overrides.get("storage_efficiency_factor", 1.0),
                context.source.grid_price_per_kwh,
                power_factor=overrides.get("storage_power_factor", 1.0),
                outage_site_codes=context.source.storage_outage_site_codes,
            )
            initial_soc = sum(item.initial_soc_kwh for item in battery.storage_devices)
            target_soc = initial_soc if bundle.policy.target_final_soc_rule in {"cyclic", "not_below_initial"} and devices else None
            system = make_settlement_system(
                battery,
                route,
                settlement_step_s,
                initial_soc,
                target_soc,
                bundle.policy.final_soc_tolerance_kwh,
                0.0,
                context.source.wasted_energy_penalty_per_kwh,
                "storage_no_direct",
                limits,
            )
            series_key = (*_train_cache_key(context, selected_ids), settlement_step_s)
            series = series_by_key.get(series_key)
            if series is None:
                series = build_settlement_series(
                    context.schedule,
                    heavy,
                    empty_,
                    settlement_step_s,
                    case.resource_model,
                )
                series_by_key[series_key] = series
            energy_bins = energy_bins_by_key.get(series_key)
            if energy_bins is None:
                energy_bins = build_settlement_energy_bins(
                    series,
                    settlement_step_s,
                    validated=True,
                )
                energy_bins_by_key[series_key] = energy_bins
            settlement = system.settle(series, precomputed_energy_bins=energy_bins)
            device_soc_deviations = [
                abs(settlement.final_soc_by_storage_kwh.get(item.storage_section_id, item.initial_soc_kwh) - item.initial_soc_kwh)
                for item in battery.storage_devices
            ]
            device_soc_shortfalls = [
                max(0.0, item.initial_soc_kwh - settlement.final_soc_by_storage_kwh.get(item.storage_section_id, item.initial_soc_kwh))
                for item in battery.storage_devices
            ]
            soc_deviation = max(device_soc_deviations, default=0.0) if target_soc is not None else 0.0
            soc_feasible = (
                True
                if bundle.policy.target_final_soc_rule == "priced_deviation" or not devices
                else (
                    max(device_soc_shortfalls, default=0.0) <= bundle.policy.final_soc_tolerance_kwh + 1e-6
                    if bundle.policy.target_final_soc_rule == "not_below_initial"
                    else soc_deviation <= bundle.policy.final_soc_tolerance_kwh + 1e-6
                )
            )
            electrical_feasible = settlement.traction_supply_excess_kwh <= 1e-6 and settlement.regen_absorption_excess_kwh <= 1e-6
            feasible = soc_feasible and electrical_feasible
            if bundle.policy.core_scenarios_must_all_be_feasible and context.source.core_for_feasibility and not feasible:
                all_core_feasible = False
            annual_operating, grid_energy_cost, degradation, demand, peak = _scenario_operating_cost(
                settlement,
                context.source,
                devices,
                technologies,
                bundle.policy.analysis_days_per_year,
                bundle.policy.include_demand_charge,
            )
            operating_costs.append((context.source.weight, annual_operating))
            expected_grid_energy_cost += context.source.weight * grid_energy_cost
            expected_grid += context.source.weight * settlement.grid_kwh * bundle.policy.analysis_days_per_year
            expected_waste += context.source.weight * settlement.wasted_kwh * bundle.policy.analysis_days_per_year
            row = {
                "plan_id": plan_id,
                "scenario_code": context.source.scenario_code,
                "scenario_weight": context.source.weight,
                "core_for_feasibility": context.source.core_for_feasibility,
                "feasible": feasible,
                "soc_feasible": soc_feasible,
                "electrical_feasible": electrical_feasible,
                "total_regen_kwh": settlement.total_gen_kwh,
                "storage_charge_kwh": settlement.battery_charge_kwh,
                "storage_discharge_kwh": settlement.battery_discharge_kwh,
                "self_discharge_loss_kwh": settlement.self_discharge_loss_kwh,
                "storage_outage_site_codes": ";".join(context.source.storage_outage_site_codes),
                "storage_power_factor": overrides.get("storage_power_factor", 1.0),
                "grid_kwh": settlement.grid_kwh,
                "wasted_kwh": settlement.wasted_kwh,
                "initial_soc_kwh": initial_soc,
                "final_soc_kwh": settlement.final_soc_kwh,
                "soc_deviation_kwh": soc_deviation,
                "peak_grid_kw": peak,
                "annual_operating_cost_cny": annual_operating,
                "annual_grid_energy_cost_cny": grid_energy_cost,
                "annual_degradation_cost_cny": degradation,
                "annual_demand_charge_cny": demand,
            }
            scenario_rows.append(row)
            for item in battery.storage_devices:
                tech = technologies[next(device.technology_code for device in devices if device.site_code == item.storage_section_id)]
                charge_kwh = settlement.battery_charge_by_storage_kwh.get(item.storage_section_id, 0.0)
                discharge_kwh = settlement.battery_discharge_by_storage_kwh.get(item.storage_section_id, 0.0)
                daily_cycles = (charge_kwh + discharge_kwh) / (2.0 * item.capacity_kwh)
                expected_annual_cycles_by_site[item.storage_section_id] += (
                    context.source.weight * daily_cycles * bundle.policy.analysis_days_per_year
                )
                device_scenario_rows.append(
                    {
                        "plan_id": plan_id,
                        "scenario_code": context.source.scenario_code,
                        "site_code": item.storage_section_id,
                        "initial_soc_kwh": item.initial_soc_kwh,
                        "final_soc_kwh": settlement.final_soc_by_storage_kwh.get(item.storage_section_id, item.initial_soc_kwh),
                        "charge_kwh": charge_kwh,
                        "discharge_kwh": discharge_kwh,
                        "wasted_kwh": settlement.wasted_by_storage_kwh.get(item.storage_section_id, 0.0),
                        "self_discharge_loss_kwh": settlement.self_discharge_loss_by_storage_kwh.get(item.storage_section_id, 0.0),
                        "available": item.available,
                        "rated_power_factor": overrides.get("storage_power_factor", 1.0),
                        "equivalent_full_cycles_per_typical_day": daily_cycles,
                        "cycle_life_reference": tech.cycle_life,
                    }
                )
            if not devices:
                baseline_rows.append(dict(row))
        annualized_capex, plan_lifecycle = _annualized_lifecycle_investment(
            devices,
            sites,
            technologies,
            bundle.policy.planning_horizon_years,
            bundle.policy.discount_rate,
            expected_annual_cycles_by_site,
        )
        for item in plan_lifecycle:
            lifecycle_rows.append({"plan_id": plan_id, **item})
        risk_operating_cost = _risk_aggregate(operating_costs, bundle.policy.risk_measure, bundle.policy.cvar_alpha)
        return {
            "plan_id": plan_id,
            "site_count": len(devices),
            "site_codes": ";".join(selected_ids),
            "technology_codes": ";".join(item.technology_code for item in devices),
            "total_capacity_kwh": sum(item.capacity_kwh for item in devices),
            "total_charge_power_kw": sum(item.charge_power_kw for item in devices),
            "total_discharge_power_kw": sum(item.discharge_power_kw for item in devices),
            "capex_cny": capex,
            "annualized_capex_cny": annualized_capex,
            "annual_om_cny": annual_om,
            "risk_operating_cost_cny": risk_operating_cost,
            "annual_total_cost_cny": risk_operating_cost + annualized_capex + annual_om,
            "expected_grid_kwh_per_year": expected_grid,
            "expected_grid_energy_cost_cny_per_year": expected_grid_energy_cost,
            "annual_non_grid_cost_cny": annualized_capex + annual_om + risk_operating_cost - expected_grid_energy_cost,
            "expected_wasted_kwh_per_year": expected_waste,
            "within_budget": capex <= bundle.policy.total_budget_cny + 1e-6,
            "core_feasible": all_core_feasible,
        }

    evaluated_signatures: set[Tuple[Tuple[Any, ...], ...]] = set()
    plan_by_id: Dict[str, Tuple[StoragePlanDevice, ...]] = {}
    search_timed_out = False

    def evaluate_pending(pending_plans: Sequence[Tuple[StoragePlanDevice, ...]]) -> None:
        nonlocal search_timed_out
        for devices in pending_plans:
            if candidate_rows and monotonic() - started > wall_clock_limit:
                search_timed_out = True
                break
            signature = _plan_signature(devices)
            if signature in evaluated_signatures:
                continue
            evaluated_signatures.add(signature)
            index = len(candidate_rows)
            plan_id = "NO_BUILD" if not devices else f"PLAN-{index:05d}"
            plan_by_id[plan_id] = tuple(devices)
            row = evaluate_plan(plan_id, devices)
            candidate_rows.append(row)
            for device_index, device in enumerate(devices, start=1):
                device_rows.append({"plan_id": plan_id, "device_index": device_index, **asdict(device)})

    evaluate_pending(plans)
    refined_structures: List[Tuple[Tuple[str, str], ...]] = []
    local_refined_plan_count = 0
    refinement_started = search_mode != "coarse_to_fine"
    if search_mode == "coarse_to_fine" and monotonic() - started <= bundle.policy.max_wall_clock_s:
        refinement_started = True
        no_build_ref = next((row for row in candidate_rows if row["plan_id"] == "NO_BUILD"), None)
        no_build_grid_kwh = (
            float(no_build_ref["expected_grid_kwh_per_year"])
            if no_build_ref is not None
            else 0.0
        )

        def _shortlist_key(row: Mapping[str, Any]) -> Tuple[Any, ...]:
            tiebreak = (
                str(row.get("site_codes") or ""),
                float(row.get("total_capacity_kwh") or 0.0),
                float(row.get("total_charge_power_kw") or 0.0),
                float(row.get("total_discharge_power_kw") or 0.0),
            )
            reduction = no_build_grid_kwh - float(row["expected_grid_kwh_per_year"])
            cost = float(row["annual_total_cost_cny"])
            if bundle.policy.objective_mode == "energy_first":
                return (-reduction, cost) + tiebreak
            if bundle.policy.objective_mode == "balanced":
                return (cost / max(1e-9, reduction), cost) + tiebreak
            return (cost, -reduction) + tiebreak

        ranked_builds = sorted(
            (row for row in candidate_rows if row["site_count"] > 0 and row["within_budget"] and row["core_feasible"]),
            key=_shortlist_key,
        )
        devices_by_plan = {
            "NO_BUILD" if not plan else f"PLAN-{index:05d}": plan
            for index, plan in enumerate(plans)
        }
        for row in ranked_builds:
            structure = _plan_structure(devices_by_plan[row["plan_id"]])
            if structure not in refined_structures:
                refined_structures.append(structure)
            if len(refined_structures) >= refinement_shortlist_size:
                break
        refined_plans = enumerate_storage_plans(bundle, max_levels=None, allowed_structures=refined_structures)
        plans.extend(plan for plan in refined_plans if _plan_signature(plan) not in {_plan_signature(item) for item in plans})
        evaluate_pending(refined_plans)

        # 对粗到细筛出的少量结构再做局部连续插值，保持全局枚举规模可控。
        local_refined_plans: List[Tuple[StoragePlanDevice, ...]] = []
        local_ranked_rows = sorted(
            (
                row
                for row in candidate_rows
                if row["site_count"] > 0 and row["within_budget"] and row["core_feasible"]
            ),
            key=_shortlist_key,
        )[: max(1, refinement_shortlist_size)]
        for row in local_ranked_rows:
            devices = plan_by_id.get(str(row["plan_id"]))
            if devices:
                local_refined_plans.extend(_local_continuous_refinement_plans(bundle, devices))
        local_refined_plans = list({
            _plan_signature(plan): plan for plan in local_refined_plans
            if _plan_signature(plan) not in evaluated_signatures
        }.values())
        if local_refined_plans:
            plans.extend(local_refined_plans)
            local_refined_plan_count = len(local_refined_plans)
            evaluate_pending(local_refined_plans)

    baseline = next((row for row in candidate_rows if row["plan_id"] == "NO_BUILD"), None)
    if baseline is None:
        baseline = evaluate_plan("NO_BUILD_REFERENCE", tuple())
        # 超时可能发生在第一个候选方案开始前。仍然把无储能参考方案写入
        # 候选结果，避免不完整搜索因缺少基线而抛出无关异常。
        candidate_rows.append(baseline)
    hotspots = _hotspot_rows_from_cached_series(
        prepared,
        series_by_key,
        settlement_step_s,
        bundle.sites,
        arm_path,
    )
    baseline_scenario_metrics = {
        str(row["scenario_code"]): row
        for row in scenario_rows
        if str(row.get("plan_id")) in {"NO_BUILD", "NO_BUILD_REFERENCE"}
    }
    for row in candidate_rows:
        row["annual_saving_vs_no_build_cny"] = baseline["annual_total_cost_cny"] - row["annual_total_cost_cny"]
        row["grid_reduction_vs_no_build_kwh_per_year"] = baseline["expected_grid_kwh_per_year"] - row["expected_grid_kwh_per_year"]
        grid_reduction = row["grid_reduction_vs_no_build_kwh_per_year"]
        incremental_non_grid_cost = row["annual_non_grid_cost_cny"] - baseline["annual_non_grid_cost_cny"]
        row["break_even_grid_price_cny_per_kwh"] = (
            incremental_non_grid_cost / grid_reduction
            if bundle.policy.risk_measure == "expected" and grid_reduction > 1e-9
            else None
        )
        row["meets_business_thresholds"] = (
            row["annual_saving_vs_no_build_cny"] >= bundle.policy.minimum_annual_saving_cny
            and row["grid_reduction_vs_no_build_kwh_per_year"] >= bundle.policy.minimum_grid_reduction_kwh
        )
        rejection_reasons: List[str] = []
        if row["site_count"] > 0:
            if not row["within_budget"]:
                rejection_reasons.append("over_budget")
            if not row["core_feasible"]:
                rejection_reasons.append("core_scenario_infeasible")
            if row["grid_reduction_vs_no_build_kwh_per_year"] < bundle.policy.minimum_grid_reduction_kwh:
                rejection_reasons.append("grid_reduction_below_threshold")
            if row["annual_saving_vs_no_build_cny"] < bundle.policy.minimum_annual_saving_cny:
                rejection_reasons.append("annual_saving_below_threshold")
        row["rejection_reasons"] = ";".join(rejection_reasons)

    # 将逐设备结果补成相对无储能基线的分站、分场景节能归因。
    scenario_by_plan = {
        (str(row.get("plan_id")), str(row.get("scenario_code"))): row
        for row in scenario_rows
    }
    for row in device_scenario_rows:
        plan_id = str(row.get("plan_id"))
        scenario_code = str(row.get("scenario_code"))
        plan_scenario = scenario_by_plan.get((plan_id, scenario_code), {})
        baseline_scenario = baseline_scenario_metrics.get(scenario_code, {})
        baseline_grid = float(baseline_scenario.get("grid_kwh", 0.0))
        plan_grid = float(plan_scenario.get("grid_kwh", 0.0))
        baseline_wasted = float(baseline_scenario.get("wasted_kwh", 0.0))
        plan_wasted = float(plan_scenario.get("wasted_kwh", 0.0))
        row["baseline_grid_kwh"] = round(baseline_grid, 6)
        row["plan_grid_kwh"] = round(plan_grid, 6)
        row["grid_reduction_vs_no_build_kwh"] = round(baseline_grid - plan_grid, 6)
        row["baseline_wasted_kwh"] = round(baseline_wasted, 6)
        row["plan_wasted_kwh"] = round(plan_wasted, 6)
        row["wasted_reduction_vs_no_build_kwh"] = round(baseline_wasted - plan_wasted, 6)
        row["recovered_energy_kwh"] = round(
            float(row.get("charge_kwh", 0.0)) + float(row.get("discharge_kwh", 0.0)),
            6,
        )
    decision, selected, decision_reason = select_storage_plan(
        candidate_rows,
        allow_no_build=bundle.policy.allow_no_build,
        objective_mode=bundle.policy.objective_mode,
    )
    feasible_build_alternatives = [
        row for row in candidate_rows
        if row["site_count"] > 0 and row["within_budget"] and row["core_feasible"]
    ]
    best_build_alternative = min(
        feasible_build_alternatives,
        key=lambda row: (float(row["annual_total_cost_cny"]), str(row["plan_id"])),
        default=None,
    )

    complete_search = (
        refinement_started
        and any(row["plan_id"] == "NO_BUILD" for row in candidate_rows)
        and len(candidate_rows) == len({_plan_signature(plan) for plan in plans})
    )
    search_timed_out = search_timed_out or not complete_search
    build_rows = [row for row in candidate_rows if row["site_count"] > 0]
    rejection_reason_counts: Dict[str, int] = {}
    for row in build_rows:
        for reason in str(row["rejection_reasons"]).split(";"):
            if reason:
                rejection_reason_counts[reason] = rejection_reason_counts.get(reason, 0) + 1
    decision_explanation = {
        "build_candidate_count": len(build_rows),
        "within_budget_count": sum(1 for row in build_rows if row["within_budget"]),
        "core_feasible_count": sum(1 for row in build_rows if row["core_feasible"]),
        "business_threshold_pass_count": sum(1 for row in build_rows if row["meets_business_thresholds"]),
        "rejection_reason_counts": dict(sorted(rejection_reason_counts.items())),
    }
    summary = {
        "schema_version": "1.0",
        "module": "storage_siting_sizing_phase_b_mvp",
        "decision": decision,
        "decision_reason": decision_reason,
        "selected_plan": selected,
        "best_feasible_build_alternative": best_build_alternative,
        "decision_explanation": decision_explanation,
        "recommendation_level": bundle.recommendation_level,
        "data_statuses": sorted({bundle.policy.data_status} | {item.data_status for item in bundle.sites + bundle.technologies + bundle.scenarios}),
        "runtime_budget_s": wall_clock_limit,
        "formal_engineering_conclusion_allowed": bundle.recommendation_level == "formal_engineering",
        "energy_scenario": "storage_no_direct",
        "fixed_timetable_changed": False,
        "planning_input_dir": str(bundle.source_dir),
        "case_data_dir": str(Path(case_data_dir).resolve()),
        "scenario_schedule_sources": {
            item.scenario_code: (
                item.timetable_relative_path if item.timetable_relative_path is not None else "schedule_template"
            )
            for item in bundle.scenarios
        },
        "input_fingerprint_sha256": bundle.input_fingerprint_sha256,
        "declared_search_domain": {
            "search_mode": search_mode,
            "max_levels_per_dimension": max_levels_per_dimension,
            "coarse_candidate_count": coarse_candidate_count,
            "refined_structure_count": len(refined_structures),
            "local_continuous_refined_plan_count": local_refined_plan_count,
            "candidate_plan_count": len(plans),
            "evaluated_plan_count": len(candidate_rows),
            "complete_for_declared_domain": complete_search,
            "original_step_domain_exhaustive": search_mode == "exhaustive" and complete_search,
        },
        "search_status": "complete" if complete_search else "incomplete_timeout",
        "search_timed_out": search_timed_out,
        "limitations": [
            "固定运行图可由 schedule_template 或 timetable_relative_path 提供；规划阶段不会修改发车时刻。",
            "coarse_to_fine 只对粗筛入围的站址/技术结构展开完整参数域；全局完整步长域需显式选择 exhaustive。",
            "已计入桶级自放电、场景功率降额、站点停运以及日历/循环寿命更换现金流；coarse_to_fine 模式会对入围方案增加局部连续插值，但仍不是完整连续全局搜索。",
            "输入含 synthetic/planning_placeholder 时结果仅用于诊断，不得作为采购或正式工程结论。",
        ],
        "runtime_s": monotonic() - started,
    }
    candidate_rows.sort(key=lambda row: (row["annual_total_cost_cny"], row["plan_id"]))
    _write_csv(output_root / "no_build_baseline.csv", baseline_rows, list(baseline_rows[0]) if baseline_rows else ["plan_id"])
    _write_csv(output_root / "energy_hotspots.csv", hotspots, list(hotspots[0]) if hotspots else ["power_arm_id"])
    _write_csv(output_root / "storage_plan_candidates.csv", candidate_rows, list(candidate_rows[0]) if candidate_rows else ["plan_id"])
    rejection_rows = [
        {
            "plan_id": row["plan_id"],
            "site_codes": row["site_codes"],
            "annual_saving_vs_no_build_cny": row["annual_saving_vs_no_build_cny"],
            "grid_reduction_vs_no_build_kwh_per_year": row["grid_reduction_vs_no_build_kwh_per_year"],
            "rejection_reasons": row["rejection_reasons"],
        }
        for row in build_rows if row["rejection_reasons"]
    ]
    _write_csv(
        output_root / "storage_plan_rejections.csv",
        rejection_rows,
        list(rejection_rows[0]) if rejection_rows else ["plan_id", "rejection_reasons"],
    )
    sensitivity_rows = [
        {
            "plan_id": row["plan_id"],
            "site_codes": row["site_codes"],
            "total_capacity_kwh": row["total_capacity_kwh"],
            "total_charge_power_kw": row["total_charge_power_kw"],
            "total_discharge_power_kw": row["total_discharge_power_kw"],
            "grid_reduction_vs_no_build_kwh_per_year": row["grid_reduction_vs_no_build_kwh_per_year"],
            "incremental_non_grid_cost_cny_per_year": row["annual_non_grid_cost_cny"] - baseline["annual_non_grid_cost_cny"],
            "break_even_grid_price_cny_per_kwh": row["break_even_grid_price_cny_per_kwh"],
        }
        for row in candidate_rows if row["site_count"] > 0
    ]
    _write_csv(
        output_root / "storage_economic_sensitivity.csv",
        sensitivity_rows,
        list(sensitivity_rows[0]) if sensitivity_rows else ["plan_id"],
    )
    _write_csv(output_root / "storage_plan_devices.csv", device_rows, list(device_rows[0]) if device_rows else ["plan_id", "device_index"])
    _write_csv(output_root / "storage_plan_lifecycle.csv", lifecycle_rows, list(lifecycle_rows[0]) if lifecycle_rows else ["plan_id", "site_code"])
    _write_csv(output_root / "storage_plan_scenario_results.csv", scenario_rows, list(scenario_rows[0]) if scenario_rows else ["plan_id"])
    _write_csv(
        output_root / "storage_device_scenario_results.csv",
        device_scenario_rows,
        list(device_scenario_rows[0]) if device_scenario_rows else ["plan_id", "scenario_code", "site_code"],
    )
    (output_root / "storage_planning_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_lines = [
        "# 储能选址定容阶段B结果",
        "",
        f"- 决策：`{decision}`",
        f"- 说明：{decision_reason}",
        f"- {'参考基线' if decision == 'no_feasible_plan' else '选中方案'}：`{selected['plan_id']}`，站点 `{selected['site_codes'] or '无'}`",
        f"- 年总成本：{selected['annual_total_cost_cny']:.2f} 元",
        f"- 相对无储能年节省：{selected['annual_saving_vs_no_build_cny']:.2f} 元",
        f"- 相对无储能年购电减少：{selected['grid_reduction_vs_no_build_kwh_per_year']:.2f} kWh",
        f"- 评价候选：{len(candidate_rows)}/{len(plans)}；声明离散域完整：{complete_search}",
        f"- 搜索状态：`{summary['search_status']}`",
        f"- 结论等级：`{bundle.recommendation_level}`；正式工程结论：{summary['formal_engineering_conclusion_allowed']}",
        f"- 建设候选门禁：预算内 {decision_explanation['within_budget_count']}/{decision_explanation['build_candidate_count']}，核心可行 {decision_explanation['core_feasible_count']}/{decision_explanation['build_candidate_count']}，业务门槛通过 {decision_explanation['business_threshold_pass_count']}/{decision_explanation['build_candidate_count']}",
    ]
    if decision == "no_feasible_plan":
        report_lines.append("- 无可行方案中的基线仅供参考，不作为推荐建设方案。")
    if not complete_search:
        report_lines.append("- 搜索未完整结束，结论仅针对已评价候选，不代表未评价候选不存在可行方案。")
    if not summary["formal_engineering_conclusion_allowed"]:
        report_lines.append("- 规划敏感性结论，不能作为正式工程结论。")
    if best_build_alternative is not None:
        report_lines.extend([
            "",
            "## 最佳可行建设备选",
            "",
            f"- 方案：`{best_build_alternative['plan_id']}`，站点 `{best_build_alternative['site_codes']}`",
            f"- 容量：{best_build_alternative['total_capacity_kwh']:.2f} kWh",
            f"- 最大充/放电功率：{best_build_alternative['total_charge_power_kw']:.2f} / {best_build_alternative['total_discharge_power_kw']:.2f} kW",
            f"- 相对无储能年购电减少：{best_build_alternative['grid_reduction_vs_no_build_kwh_per_year']:.2f} kWh",
            f"- 相对无储能年节省：{best_build_alternative['annual_saving_vs_no_build_cny']:.2f} 元",
        ])
        if best_build_alternative["break_even_grid_price_cny_per_kwh"] is not None:
            report_lines.append(
                f"- 盈亏平衡综合电量价格：{best_build_alternative['break_even_grid_price_cny_per_kwh']:.4f} 元/kWh"
            )
    report_lines.extend(["", "完整候选、场景结果、设备清单和热点排名见同目录 CSV。"])
    (output_root / "storage_planning_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return summary


__all__ = ["StoragePlanDevice", "enumerate_storage_plans", "run_storage_planning_mvp", "select_storage_plan"]
