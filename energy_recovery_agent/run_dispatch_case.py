# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import argparse
import csv
import json
import math
import sys

import matplotlib
from matplotlib_chinese_font import configure_matplotlib_chinese_font

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from data_ingestion import (
    DataValidationReport,
    load_real_data_bundle,
    write_validation_report,
)
from energy_settlement import (
    EnergySettlementSystem,
    SettlementResult,
    storage_no_direct_effective_loss_kwh,
)
from power_arm_electrical_limits import (
    DEFAULT_POWER_ARM_INTERVAL_PATH,
    PowerArmElectricalLimit,
    StorageSectionInterval,
    load_power_arm_electrical_limits,
    load_storage_section_intervals,
)
from power_arm_lookup import load_power_arm_intervals
from resource_constraints import (
    ResourceCheckResult,
    ResourceModel,
    build_default_resource_model,
    check_schedule_resources,
    conflicts_to_rows,
    post_departure_operation_delay_events,
)
from rolling_optimizer import (
    ENERGY_SCENARIO_DIRECT_NO_STORAGE,
    ENERGY_SCENARIO_DIRECT_WITH_STORAGE,
    ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    OBJECTIVE_MODE_BALANCED,
    OBJECTIVE_MODE_CAPACITY_SURPLUS,
    OBJECTIVE_MODE_CAPACITY_TIGHT,
    OBJECTIVE_PRIORITY_BALANCED,
    OBJECTIVE_PRIORITY_COST_FIRST,
    OBJECTIVE_PRIORITY_ENERGY_FIRST,
    SEARCH_PROFILE_PRESETS,
    GeneratedSchedule,
    RollingOptimizer,
    RollingWindowState,
    ScheduleScore,
    ScheduleTemplate,
    StorageEvalContext,
    TemplateSearchConfig,
    build_power_series,
    clip_power_series_to_window,
    capacity_pressure_objective,
    default_scenarios,
    evaluate_schedule,
    explain_robust_scenarios,
    generate_schedule,
    energy_scenario_objective,
    objective_tuple,
    pareto_template_front,
    resolve_storage_eval_context,
    scenario_diagnostic_rows,
    score_rank_value,
    candidate_selection_key,
    template_key,
)
from storage_presets import (
    apply_storage_preset_to_battery,
    apply_storage_preset_to_route,
    apply_storage_ranges_to_power_arm_limits,
    default_storage_preset_library,
    preset_to_dict,
)
from scheduler_nsga2 import PowerSeriesCache, build_power_cache, violates_headway, violates_signal_system
from time_space_network import (
    build_time_space_network,
    network_arc_rows,
    network_node_rows,
    network_path_rows,
    network_summary,
)
from train_simulator import (
    BatteryStorageParameters,
    RouteData,
    TrainParameters,
    consist_mass_tons,
    load_config,
    locomotive_mass_tons,
)
from optimization_attribution import write_optimization_attribution


DEFAULT_OUTPUT_DIR = Path("outputs") / "dispatch_case"
ENERGY_SCENARIOS = (
    ENERGY_SCENARIO_STORAGE_NO_DIRECT,
)
ENERGY_SCENARIO_AUTO = "auto"
OPTIMIZATION_MODES = (
    "joint_energy_planning",
    "dispatch_only",
)


def energy_scenario_settings(energy_scenario: str) -> Dict[str, Any]:
    """函数 energy_scenario_settings：执行该模块中的相关处理逻辑。"""
    if energy_scenario == ENERGY_SCENARIO_DIRECT_NO_STORAGE:
        return {
            "allow_direct_use": False,
            "allow_storage": False,
            "label": "legacy_no_direct_no_storage",
            "note": "Legacy diagnostic scenario only. Current Shuohuang workflow does not use this scenario because recovered regenerative energy requires storage.",
        }
    if energy_scenario == ENERGY_SCENARIO_STORAGE_NO_DIRECT:
        return {
            "allow_direct_use": False,
            "allow_storage": True,
            "label": "no_direct_use_with_storage",
            "note": "Current Shuohuang workflow: direct use is disabled, and regenerative energy can only be reused through storage-equipped sections.",
        }
    if energy_scenario == ENERGY_SCENARIO_DIRECT_WITH_STORAGE:
        return {
            "allow_direct_use": False,
            "allow_storage": True,
            "label": "legacy_alias_no_direct_use_with_storage",
            "note": "Legacy alias. Direct use is disabled by Shuohuang isolated power-supply rule; regenerated energy can only be reused through storage-equipped sections.",
        }
    raise ValueError(f"Unsupported energy scenario: {energy_scenario}")


def _dispatch_only_context(
    *,
    case_inputs: CaseInputs,
    trains: Dict[str, TrainParameters],
    base_battery: BatteryStorageParameters,
    settlement_step_s: int,
    final_soc_tolerance_kwh: float,
    final_soc_penalty_per_kwh: float,
    wasted_energy_penalty_per_kwh: float,
) -> StorageEvalContext:
    """Build a no-storage context for the standalone dispatch algorithm."""

    route = replace(case_inputs.route, energy_transfer_ranges_km=[])
    battery = replace(
        base_battery,
        capacity_kwh=0.0,
        max_charge_power_kW=0.0,
        max_discharge_power_kW=0.0,
        storage_devices=(),
        data_status="no_storage_baseline",
        scenario_name="no_storage_baseline",
        planning_assumption=False,
        note="Standalone heavy-empty dispatch baseline with storage excluded.",
    )
    power_arm_limits, storage_sections = apply_storage_ranges_to_power_arm_limits(
        case_inputs.power_arm_limits,
        case_inputs.power_arm_path,
        (),
        status="no_storage_baseline",
        note="Storage is excluded in standalone heavy-empty dispatch mode.",
    )
    heavy_cache = build_power_cache(
        trains["Heavy"], route, power_arm_interval_path=case_inputs.power_arm_path, storage_sections=()
    )
    empty_cache = build_power_cache(
        trains["Empty"], route, power_arm_interval_path=case_inputs.power_arm_path, storage_sections=()
    )
    settlement_system = make_settlement_system(
        battery,
        route,
        settlement_step_s,
        0.0,
        0.0,
        final_soc_tolerance_kwh,
        final_soc_penalty_per_kwh,
        wasted_energy_penalty_per_kwh,
        ENERGY_SCENARIO_DIRECT_NO_STORAGE,
        power_arm_limits,
    )
    return StorageEvalContext(
        preset_id="",
        route=route,
        heavy_cache=heavy_cache,
        empty_cache=empty_cache,
        settlement_system=settlement_system,
        storage_sections=tuple(storage_sections),
        label="standalone dispatch without storage",
        note="Heavy-empty dispatch is evaluated independently from storage planning.",
        data_status="no_storage_baseline",
        battery=battery,
        power_arm_limits=power_arm_limits,
    )

def configure_matplotlib_fonts() -> None:
    """函数 configure_matplotlib_fonts：执行该模块中的相关处理逻辑。"""

    configure_matplotlib_chinese_font()


configure_matplotlib_fonts()


@dataclass(frozen=True)
class CaseInputs:
    """类 CaseInputs：执行该模块中的相关处理逻辑。"""
    route: RouteData
    trains: Dict[str, TrainParameters]
    battery: BatteryStorageParameters
    resource_model: ResourceModel
    validation_report: Optional[DataValidationReport]
    source_kind: str
    source_metadata: Dict[str, Any]
    power_arm_path: Path
    power_arm_limits: Dict[str, PowerArmElectricalLimit]
    storage_sections: Tuple[StorageSectionInterval, ...]


@dataclass(frozen=True)
class ScheduleEvaluation:
    """类 ScheduleEvaluation：执行该模块中的相关处理逻辑。"""
    label: str
    schedule: GeneratedSchedule
    score: ScheduleScore
    settlement: SettlementResult
    resource_check: ResourceCheckResult
    heavy_headway_violation: bool
    empty_headway_violation: bool
    heavy_signal_violation: bool
    empty_signal_violation: bool

    @property
    def headway_feasible(self) -> bool:
        """函数 headway_feasible：执行该模块中的相关处理逻辑。"""
        return not (self.heavy_headway_violation or self.empty_headway_violation)

    @property
    def signal_feasible(self) -> bool:
        """函数 signal_feasible：执行该模块中的相关处理逻辑。"""
        return not (self.heavy_signal_violation or self.empty_signal_violation)

    @property
    def block_feasible(self) -> bool:
        """函数 block_feasible：执行该模块中的相关处理逻辑。"""
        return self.signal_feasible

    @property
    def resource_feasible(self) -> bool:
        """函数 resource_feasible：执行该模块中的相关处理逻辑。"""
        return self.resource_check.feasible

    @property
    def flow_continuity_feasible(self) -> bool:
        """函数 flow_continuity_feasible：执行该模块中的相关处理逻辑。"""
        return self.resource_check.flow_continuity_feasible

    @property
    def feasible(self) -> bool:
        """函数 feasible：执行该模块中的相关处理逻辑。"""
        return self.headway_feasible and self.signal_feasible and self.resource_feasible and self.score.feasible


def write_csv_rows(path: Path, fieldnames: List[str], rows: Iterable[Dict[str, Any]]) -> None:
    """函数 write_csv_rows：执行该模块中的相关处理逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def load_case_inputs(input_path: Path, output_dir: Path, *, ignore_installed_storage: bool = False) -> CaseInputs:
    """函数 load_case_inputs：执行该模块中的相关处理逻辑。"""
    if input_path.is_dir():
        bundle = load_real_data_bundle(input_path, ignore_installed_storage=ignore_installed_storage)
        write_validation_report(bundle.validation_report, output_dir / "data_validation")
        metadata_path = input_path / "source_metadata.json"
        source_metadata: Dict[str, Any] = {}
        if metadata_path.exists():
            source_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        power_arm_path = input_path / "power_arm_intervals.csv"
        if not power_arm_path.is_file():
            raise FileNotFoundError(
                f"Required power-arm interval file is missing: {power_arm_path}"
            )
        power_arm_intervals = load_power_arm_intervals(power_arm_path)
        power_arm_limits = load_power_arm_electrical_limits(power_arm_path)
        if not power_arm_intervals or not power_arm_limits:
            raise ValueError(
                "Power-arm interval file contains no valid mainline sections with "
                f"electrical limits: {power_arm_path}"
            )
        return CaseInputs(
            route=bundle.route,
            trains=bundle.trains,
            battery=bundle.battery,
            resource_model=bundle.resource_model,
            validation_report=bundle.validation_report,
            source_kind="real_data_directory",
            source_metadata=source_metadata,
            power_arm_path=power_arm_path,
            power_arm_limits=power_arm_limits,
            storage_sections=load_storage_section_intervals(power_arm_path),
        )

    power_arm_path = DEFAULT_POWER_ARM_INTERVAL_PATH
    if not power_arm_path.is_file():
        raise FileNotFoundError(
            f"Required power-arm interval file is missing: {power_arm_path}"
        )
    power_arm_intervals = load_power_arm_intervals(power_arm_path)
    power_arm_limits = load_power_arm_electrical_limits(power_arm_path)
    if not power_arm_intervals or not power_arm_limits:
        raise ValueError(
            "Power-arm interval file contains no valid mainline sections with "
            f"electrical limits: {power_arm_path}"
        )

    route, trains, battery = load_config(input_path)
    validation_dir = output_dir / "data_validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    (validation_dir / "data_validation_summary.json").write_text(
        json.dumps(
            {
                "source": str(input_path),
                "valid": True,
                "error_count": 0,
                "warning_count": 0,
                "note": "JSON config input; real-data directory validation was not required.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return CaseInputs(
        route=route,
        trains=trains,
        battery=battery,
        resource_model=build_default_resource_model(route),
        validation_report=None,
        source_kind="sandbox_json",
        source_metadata={},
        power_arm_path=power_arm_path,
        power_arm_limits=power_arm_limits,
        storage_sections=load_storage_section_intervals(power_arm_path),
    )


def apply_train_mass_scenario(
    trains: Dict[str, TrainParameters],
    empty_mass_tons: Optional[float],
) -> Dict[str, TrainParameters]:
    """Apply scenario-level mass overrides without changing source data files."""

    if empty_mass_tons is None:
        return trains
    if empty_mass_tons <= 0.0:
        raise ValueError("--empty-mass-tons must be positive when provided.")
    if "Empty" not in trains:
        raise ValueError("Cannot apply --empty-mass-tons because train row Empty is missing.")

    updated = dict(trains)
    empty = updated["Empty"]
    # --empty-mass-tons 按「车辆总重」解释（与编组资料口径一致），机车自重另计。
    vehicle_mass = float(empty_mass_tons)
    # 混合编组时按清单累加；单一机型时退化为「单机质量 × 台数」，两者结果一致。
    consist = getattr(empty, "locomotive_consist", ()) or ()
    locomotive_mass = (
        consist_mass_tons(consist)
        if consist
        else locomotive_mass_tons(empty.locomotive_type, empty.locomotive_count)
    )
    updated["Empty"] = replace(
        empty,
        mass_tons=vehicle_mass + locomotive_mass,
        vehicle_mass_tons=vehicle_mass,
        mass_data_status="scenario_override",
        mass_note=(
            f"Mass overridden by run_dispatch_case --empty-mass-tons = {vehicle_mass:g} t（车辆总重）；"
            f"按 {empty.locomotive_count} 台机车上限追加 {locomotive_mass:g} t，"
            f"整列车 {vehicle_mass + locomotive_mass:g} t。"
            "Use this for empty/light/mixed return-train sensitivity analysis."
        ),
    )
    return updated


def apply_battery_scenario(
    battery: BatteryStorageParameters,
    *,
    capacity_kwh: Optional[float],
    max_charge_power_kW: Optional[float],
    max_discharge_power_kW: Optional[float],
    round_trip_efficiency: Optional[float],
    depreciation_cost_per_kwh: Optional[float] = None,
    grid_price_per_kwh: Optional[float] = None,
) -> BatteryStorageParameters:
    """函数 apply_battery_scenario：执行该模块中的相关处理逻辑。"""
    if (
        capacity_kwh is None
        and max_charge_power_kW is None
        and max_discharge_power_kW is None
        and round_trip_efficiency is None
        and depreciation_cost_per_kwh is None
        and grid_price_per_kwh is None
    ):
        return battery
    physical_override_requested = any(
        value is not None
        for value in (
            capacity_kwh, max_charge_power_kW,
            max_discharge_power_kW, round_trip_efficiency,
        )
    )
    if battery.storage_devices and physical_override_requested:
        raise ValueError(
            "数据库逐设备储能参数已绑定，不能再使用聚合容量、功率或效率覆盖参数。"
        )
    if capacity_kwh is not None and capacity_kwh < 0:
        raise ValueError("--battery-capacity-kwh must be non-negative.")
    if max_charge_power_kW is not None and max_charge_power_kW < 0:
        raise ValueError("--battery-max-charge-power-kw must be non-negative.")
    if max_discharge_power_kW is not None and max_discharge_power_kW < 0:
        raise ValueError("--battery-max-discharge-power-kw must be non-negative.")
    # ``battery.json`` 和结算层用零表示不可用或停用的储能设备。
    # 场景覆盖参数也必须接受该值，否则有效数据配置无法通过调度命令复现。
    if round_trip_efficiency is not None and not (0.0 <= round_trip_efficiency <= 1.0):
        raise ValueError("--battery-round-trip-efficiency must be in [0, 1].")
    if depreciation_cost_per_kwh is not None and depreciation_cost_per_kwh < 0:
        raise ValueError("--battery-depreciation-per-kwh must be non-negative.")
    if grid_price_per_kwh is not None and grid_price_per_kwh < 0:
        raise ValueError("--battery-grid-price-per-kwh must be non-negative.")

    return replace(
        battery,
        capacity_kwh=battery.capacity_kwh if capacity_kwh is None else float(capacity_kwh),
        max_charge_power_kW=battery.max_charge_power_kW if max_charge_power_kW is None else float(max_charge_power_kW),
        max_discharge_power_kW=(
            battery.max_discharge_power_kW
            if max_discharge_power_kW is None
            else float(max_discharge_power_kW)
        ),
        round_trip_efficiency=(
            battery.round_trip_efficiency
            if round_trip_efficiency is None
            else float(round_trip_efficiency)
        ),
        depreciation_cost_per_kwh=(
            battery.depreciation_cost_per_kwh
            if depreciation_cost_per_kwh is None
            else float(depreciation_cost_per_kwh)
        ),
        grid_price_per_kwh=(
            battery.grid_price_per_kwh if grid_price_per_kwh is None else float(grid_price_per_kwh)
        ),
        data_status="scenario_override_placeholder",
        scenario_name="dispatch_sensitivity_override",
        planning_assumption=True,
        note="储能参数使用本次情景覆盖值，仅供敏感性分析。",
    )



# 主搜索只保留可落地和规划诊断预设；virtual_mainline_near_full 仍可通过显式
# --storage-preset-ids 使用，用于上界诊断。
DEFAULT_STORAGE_PRESET_SEARCH_IDS = (
    "virtual_two_section_base",
    "virtual_two_section_high_power",
    "virtual_two_section_high_capacity",
    "virtual_two_section_high_power_capacity",
    "virtual_expanded_regen_corridor",
)


def resolve_storage_preset_search(args: argparse.Namespace, base_battery: BatteryStorageParameters) -> Dict[str, Any]:
    """Resolve virtual storage-preset search settings for dispatch."""

    enable_value = getattr(args, "enable_storage_preset_search", True)
    disable_value = getattr(args, "disable_storage_preset_search", False)
    if type(enable_value) is not bool:
        raise ValueError("enable_storage_preset_search must be a boolean")
    if type(disable_value) is not bool:
        raise ValueError("disable_storage_preset_search must be a boolean")
    enable = enable_value
    if disable_value:
        enable = False
    library = default_storage_preset_library(base_battery)
    library_by_id = {preset.scenario_id: preset for preset in library}
    requested_value = getattr(args, "storage_preset_ids", "")
    if requested_value is not None and not isinstance(requested_value, str):
        raise ValueError("storage_preset_ids must be a comma-separated string")
    requested = str(requested_value or "").strip()
    if requested:
        ids = [item.strip() for item in requested.split(",") if item.strip()]
    else:
        ids = list(DEFAULT_STORAGE_PRESET_SEARCH_IDS)
    unknown_ids = [item for item in ids if item not in library_by_id]
    # 只保留已知预设并保持原有顺序。
    selected = []
    for item in ids:
        if item in library_by_id and item not in selected:
            selected.append(item)
    if not selected:
        if requested:
            raise ValueError(
                "storage_preset_ids did not contain any known preset IDs; "
                f"unknown_ids={unknown_ids!r}"
            )
        selected = [library[0].scenario_id]
    if not enable:
        selected = [selected[0]]
    if unknown_ids:
        print(f"WARNING: unknown storage preset IDs: {unknown_ids}", file=sys.stderr)
        # 按原逻辑仅使用已知 ID 继续处理。
    uses_database_devices = bool(base_battery.storage_devices)
    if uses_database_devices:
        enable = False
        selected = [library[0].scenario_id]
    return {
        "enabled": enable,
        "preset_ids": selected,
        "library_by_id": library_by_id,
        "presets": [preset_to_dict(library_by_id[item]) for item in selected if item in library_by_id],
        "data_status": (
            "database_device_parameters"
            if uses_database_devices else "planning_virtual_preset_search"
        ),
        "uses_database_device_parameters": uses_database_devices,
        "note": (
            "Storage-preset search is disabled because this run is bound to versioned "
            "per-device database parameters."
            if uses_database_devices else
            "Virtual storage capacity/power/coverage genes are searched because official storage "
            "strategy parameters are unavailable. Results are planning diagnostics, not engineering claims."
            if enable
            else "Storage-preset search disabled; the first explicitly selected fixed storage context is used."
        ),
        "unknown_ids": unknown_ids,
        "search_summary": "Storage preset search diagnostics always exported.",
    }


def build_storage_eval_contexts(
    *,
    case_inputs: CaseInputs,
    trains: Dict[str, TrainParameters],
    base_battery: BatteryStorageParameters,
    preset_ids: List[str],
    library_by_id: Dict[str, Any],
    settlement_step_s: int,
    initial_soc_kwh: Optional[float],
    target_final_soc_kwh: Optional[float],
    final_soc_tolerance_kwh: float,
    final_soc_penalty_per_kwh: float,
    wasted_energy_penalty_per_kwh: float,
    energy_scenario: str,
) -> Dict[str, StorageEvalContext]:
    """Prebuild power caches and settlement systems for each virtual storage preset."""

    contexts: Dict[str, StorageEvalContext] = {}
    for preset_id in preset_ids:
        preset = library_by_id[preset_id]
        if base_battery.storage_devices:
            route = case_inputs.route
            battery = base_battery
            power_arm_limits = case_inputs.power_arm_limits
            storage_sections = case_inputs.storage_sections
            context_label = "数据库逐设备储能配置"
            context_note = "容量、功率、效率和SOC边界来自版本化数据库设备表。"
            context_data_status = "database_device_parameters"
        else:
            route = apply_storage_preset_to_route(case_inputs.route, preset)
            battery = apply_storage_preset_to_battery(base_battery, preset)
            power_arm_limits, storage_sections = apply_storage_ranges_to_power_arm_limits(
                case_inputs.power_arm_limits,
                case_inputs.power_arm_path,
                preset.ranges_km,
                note=preset.note,
            )
            context_label = preset.label
            context_note = preset.note
            context_data_status = "planning_virtual_preset_search"
        heavy_cache = build_power_cache(
            trains["Heavy"],
            route,
            power_arm_interval_path=case_inputs.power_arm_path,
            storage_sections=storage_sections,
        )
        empty_cache = build_power_cache(
            trains["Empty"],
            route,
            power_arm_interval_path=case_inputs.power_arm_path,
            storage_sections=storage_sections,
        )
        settlement_system = make_settlement_system(
            battery,
            route,
            settlement_step_s,
            initial_soc_kwh,
            target_final_soc_kwh,
            final_soc_tolerance_kwh,
            final_soc_penalty_per_kwh,
            wasted_energy_penalty_per_kwh,
            energy_scenario,
            power_arm_limits,
        )
        contexts[preset_id] = StorageEvalContext(
            preset_id=preset_id,
            route=route,
            heavy_cache=heavy_cache,
            empty_cache=empty_cache,
            settlement_system=settlement_system,
            storage_sections=tuple(storage_sections),
            label=context_label,
            note=context_note,
            data_status=context_data_status,
            battery=battery,
            power_arm_limits=power_arm_limits,
        )
    return contexts


def make_settlement_system(
    battery: BatteryStorageParameters,
    route: RouteData,
    settlement_step_s: int,
    initial_soc_kwh: Optional[float],
    target_final_soc_kwh: Optional[float],
    final_soc_tolerance_kwh: float,
    final_soc_penalty_per_kwh: float,
    wasted_energy_penalty_per_kwh: float,
    energy_scenario: str,
    power_arm_limits: Optional[Dict[str, PowerArmElectricalLimit]] = None,
) -> EnergySettlementSystem:
    """函数 make_settlement_system：执行该模块中的相关处理逻辑。"""
    scenario = energy_scenario_settings(energy_scenario)
    return EnergySettlementSystem(
        battery,
        route.energy_transfer_ranges_km,
        settlement_time_step_s=settlement_step_s,
        initial_soc_kwh=initial_soc_kwh,
        target_final_soc_kwh=target_final_soc_kwh,
        final_soc_tolerance_kwh=final_soc_tolerance_kwh,
        final_soc_penalty_per_kwh=final_soc_penalty_per_kwh,
        wasted_energy_penalty_per_kwh=wasted_energy_penalty_per_kwh,
        allow_direct_use=bool(scenario["allow_direct_use"]),
        allow_storage=bool(scenario["allow_storage"]),
        power_arm_limits=power_arm_limits,
        flexible_energy_transfer_zones=route.flexible_energy_transfer_zones,
    )


def build_settlement_series(
    schedule: GeneratedSchedule,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    settlement_step_s: int,
    resource_model: ResourceModel | None = None,
) -> List[Dict[int, Any]]:
    """构造固定运行图的结算功率序列，供多个储能方案复用。"""

    storage_hold_s = int(getattr(schedule.template, "flex_zone_hold_s", 0))
    heavy_operation_events = None
    empty_operation_events = None
    if resource_model is not None:
        heavy_operation_events = {
            int(departure_s): post_departure_operation_delay_events(
                heavy_cache, int(departure_s), "Heavy", resource_model
            )
            for departure_s in schedule.heavy_departures_s
        }
        empty_operation_events = {
            int(departure_s): post_departure_operation_delay_events(
                empty_cache, int(departure_s), "Empty", resource_model
            )
            for departure_s in schedule.empty_departures_s
        }
    return build_power_series(
        heavy_cache,
        schedule.heavy_departures_s,
        sample_step_s=settlement_step_s,
        operation_delay_events_by_departure=heavy_operation_events,
    ) + build_power_series(
        empty_cache,
        schedule.empty_departures_s,
        sample_step_s=settlement_step_s,
        storage_hold_s=storage_hold_s,
        operation_delay_events_by_departure=empty_operation_events,
    )


def settle_schedule(
    schedule: GeneratedSchedule,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    settlement_system: EnergySettlementSystem,
    resource_model: ResourceModel | None = None,
    from_time_s: int | None = None,
    until_time_s: int | None = None,
) -> SettlementResult:
    """结算整张运行图或指定绝对时间窗内实际执行的能量。"""
    step_s = settlement_system.settlement_time_step_s
    series = build_settlement_series(
        schedule,
        heavy_cache,
        empty_cache,
        step_s,
        resource_model,
    )
    if from_time_s is not None or until_time_s is not None:
        series = clip_power_series_to_window(
            series,
            from_time_s=from_time_s,
            until_time_s=until_time_s,
            default_duration_s=step_s,
        )
    return settlement_system.settle(series)


def evaluate_dispatch_schedule(
    label: str,
    schedule: GeneratedSchedule,
    route: RouteData,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    settlement_system: EnergySettlementSystem,
    resource_model: ResourceModel,
    storage_sections: Iterable[StorageSectionInterval] | None,
    target_gap_s: int,
    min_depart_gap_s: int,
    objective_mode: str = OBJECTIVE_MODE_BALANCED,
    energy_scenario: str = ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    objective_priority: str = OBJECTIVE_PRIORITY_ENERGY_FIRST,
) -> ScheduleEvaluation:
    """函数 evaluate_dispatch_schedule：执行该模块中的相关处理逻辑。"""
    storage_hold_s = int(getattr(schedule.template, "flex_zone_hold_s", 0))
    heavy_operation_events = {
        int(departure_s): post_departure_operation_delay_events(
            heavy_cache,
            int(departure_s),
            "Heavy",
            resource_model,
        )
        for departure_s in schedule.heavy_departures_s
    }
    empty_operation_events = {
        int(departure_s): post_departure_operation_delay_events(
            empty_cache,
            int(departure_s),
            "Empty",
            resource_model,
        )
        for departure_s in schedule.empty_departures_s
    }
    score = evaluate_schedule(
        schedule,
        heavy_cache,
        empty_cache,
        settlement_system,
        route.signaling_system,
        resource_model=resource_model,
        storage_sections=storage_sections,
        target_gap_s=target_gap_s,
        min_depart_gap_s=min_depart_gap_s,
        objective_mode=objective_mode,
        energy_scenario=energy_scenario,
        objective_priority=objective_priority,
    )
    resource_check = check_schedule_resources(schedule, resource_model, heavy_cache, empty_cache)
    settlement = settle_schedule(
        schedule,
        heavy_cache,
        empty_cache,
        settlement_system,
        resource_model,
    )
    return ScheduleEvaluation(
        label=label,
        schedule=schedule,
        score=score,
        settlement=settlement,
        resource_check=resource_check,
        heavy_headway_violation=violates_headway(schedule.heavy_departures_s, min_gap_s=min_depart_gap_s),
        empty_headway_violation=violates_headway(schedule.empty_departures_s, min_gap_s=min_depart_gap_s),
        heavy_signal_violation=violates_signal_system(
            schedule.heavy_departures_s,
            heavy_cache,
            route.signaling_system,
            operation_delay_events_by_departure=heavy_operation_events,
        ),
        empty_signal_violation=violates_signal_system(
            schedule.empty_departures_s,
            empty_cache,
            route.signaling_system,
            storage_hold_s=storage_hold_s,
            operation_delay_events_by_departure=empty_operation_events,
        ),
    )


def train_rows(
    evaluation: ScheduleEvaluation,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    resource_model: ResourceModel | None = None,
) -> List[Dict[str, Any]]:
    """函数 train_rows：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, Any]] = []
    for prefix, train_type, direction, cache, departures, train_ids in (
        ("H", "Heavy", heavy_cache.direction, heavy_cache, evaluation.schedule.heavy_departures_s, evaluation.schedule.heavy_train_ids),
        ("E", "Empty", empty_cache.direction, empty_cache, evaluation.schedule.empty_departures_s, evaluation.schedule.empty_train_ids),
    ):
        for idx, (depart_time_s, train_id) in enumerate(zip(departures, train_ids), start=1):
            trajectory = cache._trajectory_for_departure(int(depart_time_s))
            run_time_s = trajectory.times[-1] if trajectory.times else 0
            operation_delay_s = 0
            if resource_model is not None:
                operation_delay_s = sum(
                    int(delay_s)
                    for threshold_s, delay_s in post_departure_operation_delay_events(
                        cache,
                        int(depart_time_s),
                        train_type,
                        resource_model,
                    )
                    if trajectory.times
                    and float(threshold_s) < float(trajectory.times[-1]) - 1e-9
                )
                run_time_s += operation_delay_s
            if (
                train_type == "Empty"
                and trajectory.first_storage_entry_elapsed_s(int(depart_time_s)) is not None
            ):
                run_time_s += int(
                    getattr(evaluation.schedule.template, "flex_zone_hold_s", 0)
                )
            rows.append(
                {
                    "case": evaluation.label,
                    "train_id": train_id,
                    "train_type": train_type,
                    "direction": direction,
                    "depart_time_s": int(depart_time_s),
                    "depart_time_min": round(depart_time_s / 60.0, 3),
                    "arrival_time_s": int(depart_time_s + run_time_s),
                    "arrival_time_min": round((depart_time_s + run_time_s) / 60.0, 3),
                    "run_time_min": round(run_time_s / 60.0, 3),
                    "operation_delay_s": operation_delay_s,
                }
            )
    return sorted(rows, key=lambda row: (row["depart_time_s"], row["train_id"]))


def _min_gap(times: List[int]) -> Optional[int]:
    """函数 _min_gap：执行该模块中的相关处理逻辑。"""
    if len(times) <= 1:
        return None
    sorted_times = sorted(times)
    return min(b - a for a, b in zip(sorted_times[:-1], sorted_times[1:]))


def effective_min_depart_gap_s(cli_min_gap_s: int, resource_model: ResourceModel) -> int:
    """函数 effective_min_depart_gap_s：执行该模块中的相关处理逻辑。"""
    return max(int(cli_min_gap_s), int(resource_model.config.min_depart_headway_s))


def kpi_dict(evaluation: ScheduleEvaluation) -> Dict[str, Any]:
    """函数 kpi_dict：执行该模块中的相关处理逻辑。"""
    settlement = evaluation.settlement
    schedule = evaluation.schedule
    total_gen = settlement.total_gen_kwh
    total_recovered = settlement.direct_used_kwh + settlement.battery_charge_kwh
    total_cost = settlement.total_cost
    return {
        "case": evaluation.label,
        "feasible": evaluation.feasible,
        "score_feasible": evaluation.score.feasible,
        "headway_feasible": evaluation.headway_feasible,
        "signal_feasible": evaluation.signal_feasible,
        "resource_feasible": evaluation.resource_feasible,
        "flow_continuity_feasible": evaluation.flow_continuity_feasible,
        "resource_conflict_count": evaluation.resource_check.conflict_count,
        "flow_continuity_violation_count": len(evaluation.resource_check.flow_continuity_violations),
        "constraint_violation": round(evaluation.score.constraint_violation, 6),
        "electrical_constraint_violation_kwh": round(
            evaluation.score.electrical_constraint_violation_kwh,
            6,
        ),
        "heavy_count": len(schedule.heavy_departures_s),
        "empty_count": len(schedule.empty_departures_s),
        "heavy_min_depart_gap_s": _min_gap(schedule.heavy_departures_s),
        "empty_min_depart_gap_s": _min_gap(schedule.empty_departures_s),
        "total_gen_kwh": round(settlement.total_gen_kwh, 3),
        "total_con_kwh": round(settlement.total_con_kwh, 3),
        "direct_used_kwh": round(settlement.direct_used_kwh, 3),
        "battery_charge_kwh": round(settlement.battery_charge_kwh, 3),
        "battery_discharge_kwh": round(settlement.battery_discharge_kwh, 3),
        "accepted_by_power_arm_kwh": round(settlement.accepted_by_power_arm_kwh, 3),
        "recovered_energy_kwh": round(settlement.recovered_energy_kwh, 3),
        "recovery_rate": round(settlement.recovery_rate, 4),
        "battery_charge_limited_kwh": round(settlement.battery_charge_limited_kwh, 3),
        "battery_discharge_limited_kwh": round(settlement.battery_discharge_limited_kwh, 3),
        "traction_supply_excess_kwh": round(settlement.traction_supply_excess_kwh, 3),
        "regen_absorption_excess_kwh": round(settlement.regen_absorption_excess_kwh, 3),
        "wasted_kwh": round(settlement.wasted_kwh, 3),
        "grid_kwh": round(settlement.grid_kwh, 3),
        "grid_cost": round(settlement.grid_cost, 3),
        "battery_cost": round(settlement.battery_cost, 3),
        "wasted_energy_penalty": round(settlement.wasted_energy_penalty, 3),
        "final_soc_penalty": round(settlement.final_soc_penalty, 3),
        "total_cost": round(total_cost, 3),
        "initial_soc_kwh": round(settlement.initial_soc_kwh, 3),
        "final_soc_kwh": round(settlement.final_soc_kwh, 3),
        "final_soc_deviation_kwh": round(evaluation.score.final_soc_deviation_kwh, 3),
        "final_soc_shortfall_kwh": round(evaluation.score.final_soc_shortfall_kwh, 3),
        "effective_regen_loss_kwh": round(
            getattr(
                settlement,
                "effective_regen_loss_kwh",
                evaluation.score.effective_regen_loss_kwh,
            ),
            3,
        ),
        "storage_efficiency": round(evaluation.score.storage_efficiency, 6),
        "energy_term": round(energy_scenario_objective(evaluation.score), 3),
        "parked_energy_kwh": round(settlement.final_soc_kwh - settlement.initial_soc_kwh, 3),
        "final_soc_by_storage_kwh": {
            storage_section_id: round(soc_kwh, 3)
            for storage_section_id, soc_kwh in settlement.final_soc_by_storage_kwh.items()
        },
        "direct_use_ratio": round(settlement.direct_used_kwh / total_gen, 4) if total_gen > 0 else 0.0,
        "recovered_or_stored_ratio": round(total_recovered / total_gen, 4) if total_gen > 0 else 0.0,
        "optimizer_average_cost": round(evaluation.score.total_cost, 3),
        "optimizer_worst_case_cost": round(evaluation.score.worst_case_cost, 3),
        "optimizer_headway_deviation": round(evaluation.score.headway_deviation, 3),
        "optimizer_capacity_margin_s": round(evaluation.score.capacity_margin_s, 3),
        "optimizer_objective_mode": evaluation.score.objective_mode,
        "optimizer_energy_scenario": evaluation.score.energy_scenario,
        "time_space_node_count": evaluation.score.time_space_node_count,
        "time_space_arc_count": evaluation.score.time_space_arc_count,
    }


def storage_comparison_scope(
    baseline_preset_id: str,
    optimized_preset_id: str,
) -> Dict[str, Any]:
    """Describe whether a KPI delta is dispatch-only or a joint planning result.

    A storage preset changes capacity, power and/or coverage.  When the selected
    optimized preset differs from the baseline preset, the resulting energy
    delta cannot be attributed to timetable optimization alone.
    """

    baseline_id = str(baseline_preset_id or "").strip()
    optimized_id = str(optimized_preset_id or "").strip()
    changed = baseline_id != optimized_id
    return {
        "comparison_scope": (
            "joint_dispatch_and_virtual_storage_planning"
            if changed
            else "fixed_storage_dispatch_only"
        ),
        "dispatch_only_attribution_allowed": not changed,
        "storage_preset_changed": changed,
        "baseline_storage_preset_id": baseline_id,
        "optimized_storage_preset_id": optimized_id,
        "comparison_note": (
            "基线和候选使用不同虚拟储能预设，差值同时包含调度与储能规划变化。"
            if changed
            else "基线和候选使用同一储能预设，可以在固定设备条件下比较调度差值。"
        ),
    }


def comparison_rows(
    baseline: ScheduleEvaluation,
    optimized: ScheduleEvaluation,
    *,
    comparison_scope: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """函数 comparison_rows：执行该模块中的相关处理逻辑。"""
    base = kpi_dict(baseline)
    opt = kpi_dict(optimized)
    metric_units = {
        "total_cost": "CNY",
        "grid_kwh": "kWh",
        "wasted_kwh": "kWh",
        "direct_used_kwh": "kWh",
        "battery_charge_kwh": "kWh",
        "battery_discharge_kwh": "kWh",
        "accepted_by_power_arm_kwh": "kWh",
        "recovered_energy_kwh": "kWh",
        "resource_conflict_count": "count",
        "flow_continuity_violation_count": "count",
        "optimizer_capacity_margin_s": "s",
        "direct_use_ratio": "ratio",
        "recovered_or_stored_ratio": "ratio",
        "recovery_rate": "ratio",
        "final_soc_kwh": "kWh",
        "final_soc_deviation_kwh": "kWh",
        "energy_term": "kWh",
        "parked_energy_kwh": "kWh",
        "final_soc_penalty": "CNY",
    }
    rows: List[Dict[str, Any]] = []
    for metric, unit in metric_units.items():
        base_value = base[metric]
        opt_value = opt[metric]
        improvement_pct = ""
        if (
            (comparison_scope or {}).get("energy_comparison_eligible", True)
            and isinstance(base_value, (int, float))
            and isinstance(opt_value, (int, float))
        ):
            reduction = safe_pct(float(base_value), float(opt_value))
            improvement_pct = "" if reduction is None else round(reduction, 3)
        rows.append(
            {
                **(comparison_scope or {}),
                "metric": metric,
                "unit": unit,
                "baseline": base_value,
                "optimized": opt_value,
                "optimized_minus_baseline": (
                    round(opt_value - base_value, 3)
                    if isinstance(base_value, (int, float)) and isinstance(opt_value, (int, float))
                    else ""
                ),
                "reduction_pct": improvement_pct,
            }
        )
    return rows


def energy_timeline_rows(
    evaluation: ScheduleEvaluation,
    battery: BatteryStorageParameters,
    settlement_step_s: int,
) -> List[Dict[str, Any]]:
    """函数 energy_timeline_rows：执行该模块中的相关处理逻辑。"""
    settlement = evaluation.settlement
    soc_kwh = settlement.initial_soc_kwh
    efficiency = max(0.0, min(1.0, battery.round_trip_efficiency))
    rows: List[Dict[str, Any]] = []
    for idx, time_s in enumerate(settlement.timeline_s):
        charge_kwh = settlement.battery_charge_kW[idx] * settlement_step_s / 3600.0
        discharge_kwh = settlement.battery_discharge_kW[idx] * settlement_step_s / 3600.0
        soc_kwh = max(0.0, min(battery.capacity_kwh, soc_kwh + charge_kwh * efficiency - discharge_kwh))
        rows.append(
            {
                "case": evaluation.label,
                "time_s": int(time_s),
                "time_min": round(time_s / 60.0, 3),
                "direct_used_kW": round(settlement.direct_used_kW[idx], 3),
                "battery_charge_kW": round(settlement.battery_charge_kW[idx], 3),
                "battery_discharge_kW": round(settlement.battery_discharge_kW[idx], 3),
                "wasted_kW": round(settlement.wasted_kW[idx], 3),
                "grid_kW": round(settlement.grid_kW[idx], 3),
                "soc_kwh": round(soc_kwh, 3),
            }
        )
    return rows


def conflict_rows(evaluations: Iterable[ScheduleEvaluation]) -> List[Dict[str, Any]]:
    """函数 conflict_rows：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, Any]] = []
    for evaluation in evaluations:
        for row in conflicts_to_rows(evaluation.resource_check.conflicts):
            row["case"] = evaluation.label
            rows.append(row)
    return rows


def flow_continuity_rows(evaluations: Iterable[ScheduleEvaluation]) -> List[Dict[str, Any]]:
    """函数 flow_continuity_rows：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, Any]] = []
    for evaluation in evaluations:
        for event in evaluation.resource_check.flow_continuity_events:
            row = dict(event)
            row["case"] = evaluation.label
            rows.append(row)
    return rows


def flow_violation_rows(evaluations: Iterable[ScheduleEvaluation]) -> List[Dict[str, Any]]:
    """函数 flow_violation_rows：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, Any]] = []
    for evaluation in evaluations:
        for violation in evaluation.resource_check.flow_continuity_violations:
            row = dict(violation)
            row["case"] = evaluation.label
            rows.append(row)
    return rows


def _candidate_schedule(
    template: ScheduleTemplate,
    current_time_s: int,
    horizon_s: int,
) -> GeneratedSchedule:
    """函数 _candidate_schedule：执行该模块中的相关处理逻辑。"""
    schedule = generate_schedule(template)
    return GeneratedSchedule(
        heavy_departures_s=sorted([t for t in schedule.heavy_departures_s if t <= current_time_s + horizon_s]),
        empty_departures_s=sorted([t for t in schedule.empty_departures_s if t <= current_time_s + horizon_s]),
        template=template,
    )


def candidate_rows(
    candidates: Iterable[Tuple[ScheduleTemplate, ScheduleScore]],
    current_time_s: int,
    horizon_s: int,
    candidate_set: str,
    energy_scenario: str,
) -> List[Dict[str, Any]]:
    """函数 candidate_rows：执行该模块中的相关处理逻辑。"""
    rows: List[Dict[str, Any]] = []
    for rank, (template, score) in enumerate(candidates, start=1):
        schedule = _candidate_schedule(template, current_time_s, horizon_s)
        obj_1, obj_2, obj_3 = objective_tuple(score)
        candidate_id = candidate_id_for_template(template)
        rows.append(
            {
                "candidate_id": candidate_id,
                "candidate_set": candidate_set,
                "rank": rank,
                "energy_scenario": energy_scenario,
                "storage_preset_id": str(getattr(template, "storage_preset_id", "") or ""),
                "objective_priority": score.objective_priority,
                "feasible": score.feasible,
                "score_rank_value": round(score_rank_value(score), 6),
                "objective_1_effective_regen_loss_kwh": round(obj_1, 6),
                "objective_2_grid_kwh": round(obj_2, 6),
                "objective_3_capacity_or_headway": round(obj_3, 6),
                "constraint_violation": round(score.constraint_violation, 6),
                "headway_violation_s": round(score.headway_violation_s, 6),
                "signal_violation_count": score.signal_violation_count,
                "resource_overlap_violation_s": round(score.resource_overlap_violation_s, 6),
                "traction_supply_excess_kwh": round(score.traction_supply_excess_kwh, 6),
                "regen_absorption_excess_kwh": round(score.regen_absorption_excess_kwh, 6),
                "electrical_constraint_violation_kwh": round(
                    score.electrical_constraint_violation_kwh,
                    6,
                ),
                "capacity_pressure_objective": round(capacity_pressure_objective(score), 6),
                "energy_scenario_objective": round(energy_scenario_objective(score), 6),
                "total_cost": round(score.total_cost, 6),
                "headway_deviation": round(score.headway_deviation, 6),
                "worst_case_cost": round(score.worst_case_cost, 6),
                "worst_case_headway_deviation": round(score.worst_case_headway_deviation, 6),
                "capacity_margin_s": round(score.capacity_margin_s, 6),
                "direct_used_kwh": round(score.direct_used_kwh, 6),
                "battery_charge_kwh": round(score.battery_charge_kwh, 6),
                "battery_discharge_kwh": round(score.battery_discharge_kwh, 6),
                "wasted_kwh": round(score.wasted_kwh, 6),
                "grid_kwh": round(score.grid_kwh, 6),
                "final_soc_kwh": round(score.final_soc_kwh, 6),
                "final_soc_deviation_kwh": round(score.final_soc_deviation_kwh, 6),
                 "final_soc_shortfall_kwh": round(score.final_soc_shortfall_kwh, 6),
                 "effective_regen_loss_kwh": round(score.effective_regen_loss_kwh, 6),
                 "storage_efficiency": round(score.storage_efficiency, 6),
                "resource_conflict_count": score.resource_conflict_count,
                "flow_continuity_feasible": score.flow_continuity_feasible,
                "flow_continuity_violation_count": score.flow_continuity_violation_count,
                "time_space_node_count": score.time_space_node_count,
                "time_space_arc_count": score.time_space_arc_count,
                "objective_mode": score.objective_mode,
                "scenario_count": score.scenario_count,
                "heavy_headway_s": template.heavy_headway_s,
                "empty_headway_s": template.empty_headway_s,
                "heavy_empty_phase_s": template.heavy_empty_phase_s,
                "flex_zone_hold_s": template.flex_zone_hold_s,
                "storage_align_shift_s": template.storage_align_shift_s,
                "heavy_departure_adjustments_s": json.dumps(
                    list(template.heavy_departure_adjustments_s), ensure_ascii=False
                ),
                "empty_departure_adjustments_s": json.dumps(
                    list(template.empty_departure_adjustments_s), ensure_ascii=False
                ),
                "heavy_count": template.heavy_count,
                "empty_count": template.empty_count,
                "heavy_departures_s": json.dumps(schedule.heavy_departures_s, ensure_ascii=False),
                "empty_departures_s": json.dumps(schedule.empty_departures_s, ensure_ascii=False),
            }
        )
    return rows


def candidate_id_for_template(template: ScheduleTemplate) -> str:
    """Return a stable identifier derived from the dispatch template genes."""

    preset = str(getattr(template, "storage_preset_id", "") or "") or "base"
    short = preset.replace("virtual_", "v_").replace("section_", "sec_")
    heavy_adjustments = ",".join(str(value) for value in template.heavy_departure_adjustments_s)
    empty_adjustments = ",".join(str(value) for value in template.empty_departure_adjustments_s)
    local_suffix = (
        f"-AH[{heavy_adjustments}]-AE[{empty_adjustments}]"
        if heavy_adjustments or empty_adjustments
        else ""
    )
    return (
        f"D-H{template.heavy_headway_s}-E{template.empty_headway_s}-"
        f"P{template.heavy_empty_phase_s}-HC{template.heavy_count}-EC{template.empty_count}-"
        f"T{template.start_time_s}-F{template.flex_zone_hold_s}-"
        f"S{template.storage_align_shift_s}-ST{short}{local_suffix}"
    )


def candidate_json_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """函数 candidate_json_rows：执行该模块中的相关处理逻辑。"""
    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["heavy_departures_s"] = json.loads(str(row["heavy_departures_s"]))
        item["empty_departures_s"] = json.loads(str(row["empty_departures_s"]))
        for field_name in (
            "heavy_departure_adjustments_s",
            "empty_departure_adjustments_s",
        ):
            if field_name in item:
                item[field_name] = json.loads(str(item[field_name]))
        result.append(item)
    return result


def _trajectory_for_departure(cache: PowerSeriesCache, depart_time_s: int) -> PowerSeriesCache:
    """函数 _trajectory_for_departure：执行该模块中的相关处理逻辑。"""
    return cache._trajectory_for_departure(int(depart_time_s))


def _trajectory_plot_points(
    cache: PowerSeriesCache,
    depart_time_s: int,
    storage_hold_s: int = 0,
    operation_delay_events: Iterable[Tuple[float, int]] = (),
) -> Tuple[List[float], List[float]]:
    """Return trajectory points on the same time axis used by settlement.

    The power series, signaling checks, resource intervals, and schedule CSV all
    apply the empty-train hold at the first positive storage overlap.  Preserve
    that wait in the train diagram as a horizontal segment instead of plotting
    the unheld cached trajectory.
    """

    trajectory = _trajectory_for_departure(cache, depart_time_s)
    times = [float(value) for value in trajectory.times]
    positions = [float(value) for value in trajectory.positions_km]
    if not times:
        return [], []
    hold_s = int(storage_hold_s)
    last_elapsed_s = times[-1]
    holds: List[Tuple[float, int, str]] = []
    for raw_threshold_s, raw_delay_s in operation_delay_events:
        threshold_s = float(raw_threshold_s)
        delay_s = int(raw_delay_s)
        if (
            math.isfinite(threshold_s)
            and threshold_s >= 0.0
            and threshold_s < last_elapsed_s - 1e-9
            and delay_s > 0
        ):
            holds.append((threshold_s, delay_s, "operation"))
    entry_s = (
        trajectory.first_storage_entry_elapsed_s(int(depart_time_s))
        if hold_s > 0
        else None
    )
    if entry_s is not None:
        holds.append((float(entry_s), hold_s, "storage"))
    if not holds:
        return times, positions
    holds.sort(key=lambda item: (item[0], 0 if item[2] == "operation" else 1))

    points: List[Tuple[float, int, float]] = []
    for time_s, position_km in zip(times, positions):
        shifted_time_s = time_s + sum(
            delay_s for threshold_s, delay_s, _hold_type in holds if time_s >= threshold_s - 1e-9
        )
        points.append((shifted_time_s, 2, position_km))

    cumulative_delay_s = 0
    for threshold_s, delay_s, hold_type in holds:
        wait_start_s = threshold_s + cumulative_delay_s
        state_elapsed_s = (
            int(math.floor(threshold_s))
            if hold_type == "operation"
            else max(0, int(math.floor(threshold_s)) - 1)
        )
        wait_state = trajectory.state_at(
            state_elapsed_s,
            depart_time_s=int(depart_time_s),
        )
        wait_position_km = (
            float(wait_state[0])
            if wait_state is not None
            else positions[0]
        )
        points.append((wait_start_s, 0, wait_position_km))
        points.append((wait_start_s + delay_s, 1, wait_position_km))
        cumulative_delay_s += delay_s

    points.sort(key=lambda item: (item[0], item[1]))
    return [item[0] for item in points], [item[2] for item in points]


def _scenario_label(label: str) -> str:
    """把方案标识翻译为中文标题用词。"""
    return {"baseline": "基线方案", "optimized": "优化方案"}.get(label, label)


def plot_timetable(
    baseline: ScheduleEvaluation,
    optimized: ScheduleEvaluation,
    baseline_route: RouteData,
    baseline_heavy_cache: PowerSeriesCache,
    baseline_empty_cache: PowerSeriesCache,
    output_path: Path,
    *,
    optimized_route: RouteData | None = None,
    optimized_heavy_cache: PowerSeriesCache | None = None,
    optimized_empty_cache: PowerSeriesCache | None = None,
    resource_model: ResourceModel | None = None,
) -> None:
    """函数 plot_timetable：执行该模块中的相关处理逻辑。"""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    cases = [
        (
            baseline,
            axes[0],
            baseline_route,
            baseline_heavy_cache,
            baseline_empty_cache,
        ),
        (
            optimized,
            axes[1],
            optimized_route or baseline_route,
            optimized_heavy_cache or baseline_heavy_cache,
            optimized_empty_cache or baseline_empty_cache,
        ),
    ]
    for evaluation, ax, route, heavy_cache, empty_cache in cases:
        storage_hold_s = int(getattr(evaluation.schedule.template, "flex_zone_hold_s", 0))
        for train_type, cache, departures, color in (
            ("Heavy", heavy_cache, evaluation.schedule.heavy_departures_s, "#d62728"),
            ("Empty", empty_cache, evaluation.schedule.empty_departures_s, "#1f77b4"),
        ):
            for depart_time_s in departures:
                operation_events = (
                    post_departure_operation_delay_events(
                        cache,
                        int(depart_time_s),
                        train_type,
                        resource_model,
                    )
                    if resource_model is not None
                    else ()
                )
                plot_kwargs: Dict[str, Any] = {
                    "storage_hold_s": storage_hold_s if train_type == "Empty" else 0,
                }
                if operation_events:
                    plot_kwargs["operation_delay_events"] = operation_events
                elapsed_times, positions = _trajectory_plot_points(
                    cache,
                    int(depart_time_s),
                    **plot_kwargs,
                )
                step = max(1, len(elapsed_times) // 700)
                times_min = [(depart_time_s + t) / 60.0 for t in elapsed_times[::step]]
                ax.plot(times_min, positions[::step], color=color, alpha=0.55, linewidth=0.9)
            if departures:
                ax.plot([], [], color=color, label="重车" if train_type == "Heavy" else "空车")

        for start, end in route.energy_transfer_ranges_km:
            ax.axhspan(start, end, color="#2ca02c", alpha=0.08)
        ax.set_title(_scenario_label(evaluation.label))
        ax.set_xlabel("时间（分钟）")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best")
    axes[0].set_ylabel("里程（公里）")
    fig.suptitle("列车运行图：时间—里程")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_energy_flow(evaluation: ScheduleEvaluation, output_path: Path) -> None:
    """函数 plot_energy_flow：执行该模块中的相关处理逻辑。"""
    settlement = evaluation.settlement
    time_axis = [time_s / 60.0 for time_s in settlement.timeline_s]
    direct = settlement.direct_used_kW
    discharge = settlement.battery_discharge_kW
    grid = settlement.grid_kW
    charge = settlement.battery_charge_kW
    wasted = settlement.wasted_kW

    positive_direct = direct
    positive_battery = [d + b for d, b in zip(direct, discharge)]
    positive_total = [d + b + g for d, b, g in zip(direct, discharge, grid)]
    negative_direct = [-d for d in direct]
    negative_charge = [-(d + c) for d, c in zip(direct, charge)]
    negative_total = [-(d + c + w) for d, c, w in zip(direct, charge, wasted)]

    fig, ax = plt.subplots(1, 1, figsize=(12, 5))
    ax.fill_between(time_axis, 0, positive_direct, color="#4c78a8", alpha=0.65, label="直接供电")
    ax.fill_between(time_axis, positive_direct, positive_battery, color="#72b7b2", alpha=0.65, label="储能放电")
    ax.fill_between(time_axis, positive_battery, positive_total, color="#f58518", alpha=0.65, label="电网购电")
    ax.fill_between(time_axis, 0, negative_direct, color="#54a24b", alpha=0.65, label="直接回收")
    ax.fill_between(time_axis, negative_direct, negative_charge, color="#e45756", alpha=0.65, label="储能充电")
    ax.fill_between(time_axis, negative_charge, negative_total, color="#b279a2", alpha=0.65, label="弃能")
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title(f"{_scenario_label(evaluation.label)}能源流")
    ax.set_xlabel("时间（分钟）")
    ax.set_ylabel("功率（千瓦）")
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_soc_curve(
    baseline_rows: List[Dict[str, Any]],
    optimized_rows: List[Dict[str, Any]],
    output_path: Path,
) -> None:
    """函数 plot_soc_curve：执行该模块中的相关处理逻辑。"""
    fig, ax = plt.subplots(1, 1, figsize=(11, 4.5))
    for label, rows, color in (
        ("基线方案", baseline_rows, "#4c78a8"),
        ("优化方案", optimized_rows, "#e45756"),
    ):
        ax.plot([row["time_min"] for row in rows], [row["soc_kwh"] for row in rows], label=label, color=color)
    ax.set_title("储能 SOC 曲线")
    ax.set_xlabel("时间（分钟）")
    ax.set_ylabel("SOC（千瓦时）")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_cost_comparison(baseline: ScheduleEvaluation, optimized: ScheduleEvaluation, output_path: Path) -> None:
    """函数 plot_cost_comparison：执行该模块中的相关处理逻辑。"""
    metrics = ["grid_cost", "battery_cost", "wasted_energy_penalty", "final_soc_penalty", "total_cost"]
    labels = ["购电", "储能", "弃能", "终端SOC", "合计"]
    base = kpi_dict(baseline)
    opt = kpi_dict(optimized)
    x_positions = list(range(len(metrics)))
    width = 0.35
    fig, ax = plt.subplots(1, 1, figsize=(10, 4.8))
    ax.bar([x - width / 2 for x in x_positions], [base[m] for m in metrics], width, label="基线方案", color="#4c78a8")
    ax.bar([x + width / 2 for x in x_positions], [opt[m] for m in metrics], width, label="优化方案", color="#e45756")
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels)
    ax.set_ylabel("成本（元）")
    ax.set_title("成本对比")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_resource_conflicts(rows: List[Dict[str, Any]], output_path: Path) -> None:
    """函数 plot_resource_conflicts：执行该模块中的相关处理逻辑。"""
    fig, ax = plt.subplots(1, 1, figsize=(12, 5))
    if not rows:
        ax.text(0.5, 0.5, "没有资源冲突", ha="center", va="center", transform=ax.transAxes, fontsize=14)
        ax.set_axis_off()
    else:
        labels = []
        for idx, row in enumerate(rows):
            label = f"{row['case']} {row['resource_name']} {row['train_a']}/{row['train_b']}"
            labels.append(label)
            ax.hlines(
                y=idx,
                xmin=float(row["overlap_start_s"]) / 60.0,
                xmax=float(row["overlap_end_s"]) / 60.0,
                color="#d62728" if row["case"] == "baseline" else "#1f77b4",
                linewidth=3,
            )
        ax.set_yticks(list(range(len(labels))))
        ax.set_yticklabels(labels, fontsize=8)
        ax.set_xlabel("时间（分钟）")
        ax.set_title("资源冲突时间线")
        ax.grid(True, axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def safe_pct(base: float, optimized: float) -> Optional[float]:
    """Return a reduction percentage without disguising a zero baseline.

    When both values are zero the reduction is exactly zero.  If the baseline
    is zero but the optimized value is non-zero, a percentage is undefined;
    returning ``None`` prevents reports from silently displaying ``0%`` for a
    real increase from zero.
    """

    if abs(base) <= 1e-9:
        return 0.0 if abs(optimized) <= 1e-9 else None
    return (base - optimized) / base * 100.0


def _rounded_pct(base: float, optimized: float) -> Optional[float]:
    """函数 _rounded_pct：执行该模块中的相关处理逻辑。"""
    value = safe_pct(base, optimized)
    return None if value is None else round(value, 3)


def _formatted_pct(base: float, optimized: float) -> str:
    """函数 _formatted_pct：执行该模块中的相关处理逻辑。"""
    value = safe_pct(base, optimized)
    return "不适用（基线为零）" if value is None else f"{value:.2f}%"


def _report_source_notes(case_inputs: CaseInputs) -> List[str]:
    """函数 _report_source_notes：执行该模块中的相关处理逻辑。"""
    metadata = case_inputs.source_metadata or {}
    files = metadata.get("files", {}) if isinstance(metadata.get("files", {}), dict) else {}
    resource_model = case_inputs.resource_model
    battery = case_inputs.battery
    heavy = case_inputs.trains.get("Heavy")
    empty = case_inputs.trains.get("Empty")

    notes = [
        f"- 最小发车间隔：{resource_model.config.min_depart_headway_s}秒"
        + (
            f" ({resource_model.config.min_depart_headway_source})."
            if resource_model.config.min_depart_headway_source
            else "."
        ),
        f"- 储能数据状态：`{battery.data_status}`。规划假设：{'是' if battery.planning_assumption else '否'}。",
        f"- 本轮基线实际使用的储能容量为 {battery.capacity_kwh:g} 千瓦时，"
        f"最大充电功率为 {battery.max_charge_power_kW:g} 千瓦，最大放电功率为 {battery.max_discharge_power_kW:g} 千瓦。",
    ]
    if battery.note:
        notes.append(f"- 储能说明：{battery.note}")
    if heavy is not None:
        notes.append(f"- 重车质量状态：`{heavy.mass_data_status}`；质量 {heavy.mass_tons:.1f} 吨。")
    if empty is not None:
        notes.append(f"- 空车质量状态：`{empty.mass_data_status}`；质量 {empty.mass_tons:.1f} 吨。")
        if empty.mass_note:
            notes.append(f"- 空车说明：{empty.mass_note}")

    if files:
        for file_name in (
            "route_metadata.json",
            "stations.csv",
            "station_resources.csv",
            "segments.csv",
            "signaling_blocks.csv",
            "headway_constraints.csv",
            "technical_operation_times.csv",
            "station_operation_assignments.csv",
            "resource_config.json",
            "battery.json",
            "trains.csv",
        ):
            if file_name in files:
                notes.append(f"- `{file_name}`: {files[file_name]}")
    elif case_inputs.source_kind == "sandbox_json":
        notes.append("- 输入为沙箱 JSON 配置；当前没有可用的数据来源元信息。")

    return notes



def robust_nominal_compare_rows(
    templates_and_scores: Iterable[Tuple[ScheduleTemplate, ScheduleScore]],
    *,
    heavy_cache: PowerSeriesCache,
    empty_cache: PowerSeriesCache,
    settlement_system: EnergySettlementSystem,
    route: RouteData,
    resource_model: ResourceModel,
    storage_sections: Iterable[StorageSectionInterval] | None,
    storage_contexts: Dict[str, StorageEvalContext] | None = None,
    default_storage_preset_id: str = "",
    min_depart_gap_s: int,
    target_gap_s: int,
    objective_mode: str,
    energy_scenario: str,
    objective_priority: str = OBJECTIVE_PRIORITY_ENERGY_FIRST,
    current_time_s: int = 0,
    horizon_s: int = 14400,
    scenario_scores_by_template: Dict[Any, Tuple[Any, ...]] | None = None,
) -> List[Dict[str, Any]]:
    """Build core-robust vs nominal comparison rows for dispatch reporting."""

    rows: List[Dict[str, Any]] = []
    scenarios = default_scenarios()
    for rank, (template, robust_score) in enumerate(templates_and_scores, start=1):
        schedule = _candidate_schedule(template, current_time_s, horizon_s)
        local_heavy = heavy_cache
        local_empty = empty_cache
        local_settlement = settlement_system
        local_route = route
        local_storage_sections = storage_sections
        if storage_contexts:
            context = resolve_storage_eval_context(
                storage_contexts,
                str(getattr(template, "storage_preset_id", "") or ""),
                default_storage_preset_id,
            )
            local_heavy = context.heavy_cache
            local_empty = context.empty_cache
            local_settlement = context.settlement_system
            local_route = context.route
            local_storage_sections = context.storage_sections
        nominal_score = evaluate_schedule(
            schedule,
            local_heavy,
            local_empty,
            local_settlement,
            local_route.signaling_system,
            resource_model=resource_model,
            storage_sections=local_storage_sections,
            min_depart_gap_s=min_depart_gap_s,
            target_gap_s=target_gap_s,
            objective_mode=objective_mode,
            energy_scenario=energy_scenario,
            objective_priority=objective_priority,
        )
        cached_scenario_scores = (
            scenario_scores_by_template.get(template_key(template))
            if scenario_scores_by_template is not None
            else None
        )
        if cached_scenario_scores is None:
            scenario_rows = explain_robust_scenarios(
                schedule,
                scenarios,
                local_heavy,
                local_empty,
                local_settlement,
                local_route.signaling_system,
                resource_model=resource_model,
                storage_sections=local_storage_sections,
                min_depart_gap_s=min_depart_gap_s,
                target_gap_s=target_gap_s,
                objective_mode=objective_mode,
                energy_scenario=energy_scenario,
                objective_priority=objective_priority,
            )
        else:
            scenario_rows = scenario_diagnostic_rows(
                schedule,
                cached_scenario_scores,
                local_heavy,
                local_empty,
                resource_model=resource_model,
            )
        core_blocking = [row for row in scenario_rows if row["blocking"]]
        diagnostic_failures = [row for row in scenario_rows if row["diagnostic_failure"]]
        rows.append(
            {
                "rank": rank,
                "candidate_id": candidate_id_for_template(template),
                "heavy_headway_s": template.heavy_headway_s,
                "empty_headway_s": template.empty_headway_s,
                "heavy_empty_phase_s": template.heavy_empty_phase_s,
                "flex_zone_hold_s": template.flex_zone_hold_s,
                "storage_align_shift_s": template.storage_align_shift_s,
                "heavy_departure_adjustments_s": json.dumps(
                    list(template.heavy_departure_adjustments_s), ensure_ascii=False
                ),
                "empty_departure_adjustments_s": json.dumps(
                    list(template.empty_departure_adjustments_s), ensure_ascii=False
                ),
                "nominal_feasible": nominal_score.feasible,
                "core_robust_feasible": robust_score.feasible,
                "nominal_resource_conflict_count": nominal_score.resource_conflict_count,
                "core_robust_resource_conflict_count": robust_score.resource_conflict_count,
                "nominal_constraint_violation": round(nominal_score.constraint_violation, 6),
                "core_robust_constraint_violation": round(robust_score.constraint_violation, 6),
                "nominal_total_cost": round(nominal_score.total_cost, 6),
                "core_robust_total_cost": round(robust_score.total_cost, 6),
                "nominal_grid_kwh": round(nominal_score.grid_kwh, 6),
                "core_robust_grid_kwh": round(robust_score.grid_kwh, 6),
                "nominal_wasted_kwh": round(nominal_score.wasted_kwh, 6),
                "core_robust_wasted_kwh": round(robust_score.wasted_kwh, 6),
                "core_blocking_scenario_count": len(core_blocking),
                "core_blocking_scenarios": ";".join(row["scenario"] for row in core_blocking),
                "diagnostic_failure_scenario_count": len(diagnostic_failures),
                "diagnostic_failure_scenarios": ";".join(row["scenario"] for row in diagnostic_failures),
                "diagnostic_failure_conflict_summary": " || ".join(
                    f"{row['scenario']}:{row['conflict_summary']}"
                    for row in diagnostic_failures
                    if row["conflict_summary"]
                ),
            }
        )
    return rows


def recommended_energy_observability(args: argparse.Namespace) -> Dict[str, Any]:
    """Return recommended energy-observability settings for current synthetic runs."""

    raw_requested = getattr(args, "wasted_energy_penalty_per_kwh", 0.0)
    if isinstance(raw_requested, bool):
        raise ValueError("wasted_energy_penalty_per_kwh must be a finite non-negative number")
    try:
        requested = float(0.0 if raw_requested is None or raw_requested == "" else raw_requested)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "wasted_energy_penalty_per_kwh must be a finite non-negative number"
        ) from exc
    if not math.isfinite(requested) or requested < 0.0:
        raise ValueError("wasted_energy_penalty_per_kwh must be a finite non-negative number")
    recommended = 0.05
    applied = requested
    note = "Using caller-provided wasted-energy penalty."
    enable_value = getattr(args, "enable_energy_observability", True)
    disable_value = getattr(args, "disable_energy_observability", False)
    if type(enable_value) is not bool:
        raise ValueError("enable_energy_observability must be a boolean")
    if type(disable_value) is not bool:
        raise ValueError("disable_energy_observability must be a boolean")
    enable_flag = enable_value
    if disable_value:
        enable_flag = False
    if requested <= 0.0 and enable_flag:
        applied = recommended
        note = (
            "Enabled recommended wasted-energy penalty so regenerative waste is visible in total_cost "
            "while physical energy KPIs remain unchanged."
        )
    elif requested <= 0.0:
        note = (
            "Wasted-energy penalty is 0. Energy waste is tracked in wasted_kwh but does not affect total_cost. "
            "Use --enable-energy-observability or --wasted-energy-penalty-per-kwh 0.05 for cost visibility."
        )
    return {
        "requested_wasted_energy_penalty_per_kwh": requested,
        "recommended_wasted_energy_penalty_per_kwh": recommended,
        "applied_wasted_energy_penalty_per_kwh": applied,
        "enabled": applied > 0.0,
        "note": note,
    }


def write_markdown_report(
    output_path: Path,
    input_path: Path,
    case_inputs: CaseInputs,
    baseline: ScheduleEvaluation,
    optimized: ScheduleEvaluation,
    comparison: List[Dict[str, Any]],
    energy_scenario: Dict[str, Any],
    pareto_basis: str,
    pareto_count: int,
    optimizer_diagnostics: Optional[Dict[str, Any]] = None,
    compare_rows: Optional[List[Dict[str, Any]]] = None,
    scenario_rows: Optional[List[Dict[str, Any]]] = None,
    energy_observability: Optional[Dict[str, Any]] = None,
) -> None:
    """函数 write_markdown_report：执行该模块中的相关处理逻辑。"""
    base = kpi_dict(baseline)
    opt = kpi_dict(optimized)
    route = case_inputs.route
    diagnostics = optimizer_diagnostics or {}
    compare_rows = compare_rows or []
    scenario_rows = scenario_rows or []
    energy_observability = energy_observability or {}
    comparison_meta = comparison[0] if comparison else {}
    validation_line = "输入为 JSON 配置；未执行真实数据目录验收。"
    if case_inputs.validation_report is not None:
        validation_line = (
            f"真实数据验收通过：错误 {len(case_inputs.validation_report.errors)} 项，"
            f"警告 {len(case_inputs.validation_report.warnings)} 项。"
        )

    lines = [
        "# 重空列车方案评价报告",
        "",
        "## 1. 数据与线路",
        "",
        f"- 输入：`{input_path}`",
        f"- 输入类型：`{case_inputs.source_kind}`",
        f"- 数据验收：{validation_line}",
        f"- 线路长度：{route.total_length_km:.3f} 千米",
        f"- 最高速度：{route.max_speed_kmh:.1f} 千米/小时",
        f"- 车站数量：{len(route.stations)}",
        f"- 柔性供电区段数量：{len(route.energy_transfer_ranges_km)}",
        f"- 能源场景：`{energy_scenario['label']}`（`{energy_scenario['mode']}`）。",
        f"- 是否允许直接利用：`{energy_scenario['allow_direct_use']}`；是否启用储能：`{energy_scenario['allow_storage']}`。",
        "",
        "## 1.1 数据来源与计算假设",
        "",
        *_report_source_notes(case_inputs),
        "",
        "## 2. 重空列车方案",
        "",
        f"- 基线方案：{base['heavy_count']} 列重车，{base['empty_count']} 列空车。",
        f"- 优化方案：{opt['heavy_count']} 列重车，{opt['empty_count']} 列空车。",
        f"- 基线是否可行：`{baseline.feasible}`；优化方案是否可行：`{optimized.feasible}`。",
        f"- 优化器平均代价：基线 {base['optimizer_average_cost']:.3f}，优化方案 {opt['optimizer_average_cost']:.3f}。",
        f"- 优化目标模式：`{opt['optimizer_objective_mode']}`；优化方案能力裕度 {opt['optimizer_capacity_margin_s']:.3f} 秒。",
        f"- 优化方案时空网络：{opt['time_space_node_count']} 个节点，{opt['time_space_arc_count']} 条弧。",
        f"- 帕累托候选方案：导出 {pareto_count} 条，依据为 `{pareto_basis}`。",
        "- `core_robust_feasible` 表示通过正常场景和 ±120 秒核心扰动场景；±300 秒场景仅作为诊断信息。",
        "- `nominal_feasible_fallback` 表示没有找到核心稳健可行方案时导出的名义可行备选。",
        "",
        "![列车运行图](timetable.png)",
        "",
        "## 2.1 核心稳健方案与名义方案对比",
        "",
        f"- 排名导出依据：`{diagnostics.get('ranked_export_basis', '不适用')}`。",
        f"- 核心稳健可行候选数量：{diagnostics.get('core_robust_feasible_candidate_count', '不适用')}。",
        f"- 选中方案是否可行：`{diagnostics.get('returned_candidate_score_feasible', '不适用')}`。",
        f"- 搜索能耗指标是否无变化：`{diagnostics.get('search_diagnostics', {}).get('energy_flat', '不适用')}`。",
        f"- 搜索说明：{diagnostics.get('search_diagnostics', {}).get('note', '不适用')}",
        f"- 推荐搜索档位：`{diagnostics.get('search_diagnostics', {}).get('recommended_search_profile', '不适用')}`。",
        f"- 搜索规模说明：{diagnostics.get('search_diagnostics', {}).get('search_scale_note', '不适用')}",
        f"- 目标优先级：`{diagnostics.get('search_diagnostics', {}).get('objective_priority', '不适用')}`。",
        f"- 实际使用搜索档位：`{diagnostics.get('search_diagnostics', {}).get('search_profile', '不适用')}`。",
        f"- 未知储能预设编号：`{((diagnostics.get('search_diagnostics') or {}).get('storage_preset_search') or {}).get('unknown_ids', [])}`。",
        f"- 是否启用储能预设搜索：`{((diagnostics.get('search_diagnostics') or {}).get('storage_preset_search') or {}).get('enabled', '不适用')}`。",
        f"- 基线储能预设：`{comparison_meta.get('baseline_storage_preset_id', '不适用')}`。",
        f"- 选中储能预设：`{((diagnostics.get('search_diagnostics') or {}).get('storage_preset_search') or {}).get('selected_optimized_preset_id', '不适用')}`。",
        f"- 指标比较范围：`{comparison_meta.get('comparison_scope', '未说明')}`。",
        f"- 是否允许仅归因于调度：`{comparison_meta.get('dispatch_only_attribution_allowed', False)}`。",
        f"- 比较说明：{comparison_meta.get('comparison_note', '不适用')}",
        "",
    ]
    if compare_rows:
        lines.extend(
            [
                "| 排名 | 候选方案 | 名义可行 | 核心稳健可行 | 诊断失败场景 | 名义代价 | 核心稳健代价 |",
                "| ---: | --- | ---: | ---: | --- | ---: | ---: |",
            ]
        )
        for row in compare_rows[:8]:
            lines.append(
                f"| {row['rank']} | {row['candidate_id']} | {row['nominal_feasible']} | {row['core_robust_feasible']} | "
                f"{row.get('diagnostic_failure_scenarios') or '-'} | {row['nominal_total_cost']:.3f} | {row['core_robust_total_cost']:.3f} |"
            )
        lines.append("")
    if scenario_rows:
        lines.extend(
            [
                "### 选中方案的场景分解",
                "",
                "| 场景 | 是否为核心可行性场景 | 可行 | 冲突数 | 约束违反量 | 冲突说明 |",
                "| --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in scenario_rows:
            lines.append(
                f"| {row['scenario']} | {row['core_for_feasibility']} | {row['feasible']} | {row['resource_conflict_count']} | "
                f"{row['constraint_violation']:.6f} | {row.get('conflict_summary') or '-'} |"
            )
        lines.append("")
    if energy_observability:
        lines.extend(
            [
                "### 能源可观测性",
                "",
                f"- 已应用的弃能惩罚：{energy_observability.get('applied_wasted_energy_penalty_per_kwh')}",
                f"- 推荐弃能惩罚：{energy_observability.get('recommended_wasted_energy_penalty_per_kwh')}",
                f"- 说明：{energy_observability.get('note')}",
                "",
            ]
        )

    lines.extend(
        [
            "## 3. 指标比较",
            "",
            f"- 比较范围：`{comparison_meta.get('comparison_scope', '未说明')}`。",
            f"- {comparison_meta.get('comparison_note', '未提供比较范围说明。')}",
            "",
            "| 指标 | 单位 | 基线 | 优化方案 | 优化方案减基线 | 降幅 |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in comparison:
        reduction = "" if row["reduction_pct"] == "" else f"{row['reduction_pct']:.3f}%"
        lines.append(
            f"| `{row['metric']}` | {row['unit']} | {row['baseline']} | {row['optimized']} | "
            f"{row['optimized_minus_baseline']} | {reduction} |"
        )

    lines.extend(
        [
            "",
            "## 4. 能源与储能",
            "",
            f"- 能源场景：`{energy_scenario['label']}`。",
            *(
                [
                    f"- 总代价降幅：{_formatted_pct(base['total_cost'], opt['total_cost'])}。",
                    f"- 电网供能降幅：{_formatted_pct(base['grid_kwh'], opt['grid_kwh'])}。",
                    f"- 弃能降幅：{_formatted_pct(base['wasted_kwh'], opt['wasted_kwh'])}。",
                ]
                if comparison_meta.get("energy_comparison_eligible", True)
                else ["- 本轮只展示能量诊断值。"]
            ),
            f"- 优化方案直接利用能量：{opt['direct_used_kwh']:.3f} 千瓦时。",
            f"- 优化方案储能充电/放电：{opt['battery_charge_kwh']:.3f} / {opt['battery_discharge_kwh']:.3f} 千瓦时。",
            "",
            "![基线能源流](energy_flow_baseline.png)",
            "",
            "![优化方案能源流](energy_flow_optimized.png)",
            "",
            "![储能SOC曲线](soc_curve.png)",
            "",
            "## 5. 安全与资源",
            "",
            f"- 基线方案：发车间隔 `{baseline.headway_feasible}`，信号 `{baseline.signal_feasible}`，资源 `{baseline.resource_feasible}`，冲突 {base['resource_conflict_count']} 项。",
            f"- 优化方案：发车间隔 `{optimized.headway_feasible}`，信号 `{optimized.signal_feasible}`，资源 `{optimized.resource_feasible}`，冲突 {opt['resource_conflict_count']} 项。",
            f"- 流向连续性：基线 `{baseline.flow_continuity_feasible}`，违反 {base['flow_continuity_violation_count']} 项；优化方案 `{optimized.flow_continuity_feasible}`，违反 {opt['flow_continuity_violation_count']} 项。",
            "",
            "![资源冲突时间线](resource_conflict_timeline.png)",
            "",
            "## 6. 输出文件",
            "",
            "- `summary.json`：方案摘要和主要指标",
            "- `kpi_comparison.csv`：基线与优化方案指标对比",
            "- `baseline_schedule.csv` / `optimized_schedule.csv`：生成的列车运行图",
            "- `energy_timeline.csv`：能源流和SOC时间序列",
            "- `resource_conflicts.csv`：资源冲突说明",
            "- `core_robust_nominal_comparison.csv`：核心稳健候选与名义候选对比",
            "- `selected_plan_scenario_diagnostics.csv`：选中方案的扰动场景分解",
            "- `search_space_diagnostics.json`：搜索是否形成能耗有差异的候选方案",
            "- `flow_continuity_events.csv` / `flow_continuity_violations.csv`：重空重流向连续事件和违反记录",
            "- `pareto_candidates.csv` / `pareto_candidates.json`：非支配候选方案",
            "- `ranked_candidates.csv`：按优化器排序的全部候选方案",
            "- `time_space_nodes.csv` / `time_space_arcs.csv` / `time_space_paths.csv`：优化方案导出的时空网络；路径到达表示正线终到，到达完成还包括终端技术作业",
            "- `timetable.png`、`energy_flow_*.png`、`soc_curve.png`、`cost_comparison.png`：报告图表",
            "",
            "## 7. 结论",
            "",
            "本报告根据当前输入数据包生成。后续补充正式线路、运行图、供电、储能或车辆数据后，应重新运行流程，并以更新后的结果作为结论依据。",
            "",
            "![代价对比](cost_comparison.png)",
            "",
        ]
    )
    output_path.write_text(chr(10).join(lines), encoding="utf-8")



def evaluate_template_with_contexts(
    template: ScheduleTemplate,
    *,
    storage_contexts: Dict[str, StorageEvalContext],
    default_preset_id: str,
    resource_model: ResourceModel,
    min_depart_gap_s: int,
    target_gap_s: int,
    objective_mode: str,
    energy_scenario: str,
    objective_priority: str = OBJECTIVE_PRIORITY_ENERGY_FIRST,
    current_time_s: int = 0,
    horizon_s: int = 14400,
) -> ScheduleScore:
    """Evaluate one template under its own storage-preset context."""

    context = resolve_storage_eval_context(
        storage_contexts,
        str(getattr(template, "storage_preset_id", "") or ""),
        default_preset_id,
    )
    schedule = generate_schedule(replace(template, start_time_s=current_time_s))
    # 报告使用的时域截断必须与优化器可执行窗口保持一致。
    schedule = GeneratedSchedule(
        heavy_departures_s=[t for t in schedule.heavy_departures_s if t <= current_time_s + horizon_s],
        empty_departures_s=[t for t in schedule.empty_departures_s if t <= current_time_s + horizon_s],
        template=schedule.template,
    )
    return evaluate_schedule(
        schedule,
        context.heavy_cache,
        context.empty_cache,
        context.settlement_system,
        context.route.signaling_system,
        resource_model=resource_model,
        storage_sections=context.storage_sections,
        min_depart_gap_s=min_depart_gap_s,
        target_gap_s=target_gap_s,
        objective_mode=objective_mode,
        energy_scenario=energy_scenario,
        objective_priority=objective_priority,
    )


def run_case(args: argparse.Namespace) -> Dict[str, Any]:
    """函数 run_case：执行该模块中的相关处理逻辑。"""
    optimization_mode = str(
        getattr(args, "optimization_mode", "joint_energy_planning")
        or "joint_energy_planning"
    ).strip().lower()
    if optimization_mode not in OPTIMIZATION_MODES:
        raise ValueError(
            f"Unsupported optimization_mode {optimization_mode!r}; "
            f"choose one of {OPTIMIZATION_MODES!r}."
        )
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    case_inputs = load_case_inputs(input_path, output_dir)
    route = case_inputs.route
    trains = apply_train_mass_scenario(case_inputs.trains, args.empty_mass_tons)
    battery = apply_battery_scenario(
        case_inputs.battery,
        capacity_kwh=args.battery_capacity_kwh,
        max_charge_power_kW=args.battery_max_charge_power_kw,
        max_discharge_power_kW=args.battery_max_discharge_power_kw,
        round_trip_efficiency=args.battery_round_trip_efficiency,
        depreciation_cost_per_kwh=getattr(args, "battery_depreciation_per_kwh", None),
        grid_price_per_kwh=getattr(args, "battery_grid_price_per_kwh", None),
    )
    if optimization_mode == "dispatch_only":
        args.energy_scenario = ENERGY_SCENARIO_DIRECT_NO_STORAGE
        args.enable_storage_preset_search = False
        args.disable_storage_preset_search = True
    energy_scenario = energy_scenario_settings(args.energy_scenario)
    energy_scenario = {"mode": args.energy_scenario, **energy_scenario}
    min_depart_gap_s = effective_min_depart_gap_s(args.min_depart_gap_s, case_inputs.resource_model)
    if "Heavy" not in trains or "Empty" not in trains:
        raise ValueError("Input data must contain Heavy and Empty train definitions.")

    energy_observability = recommended_energy_observability(args)
    wasted_energy_penalty_per_kwh = float(energy_observability["applied_wasted_energy_penalty_per_kwh"])
    storage_search = resolve_storage_preset_search(args, battery)
    if optimization_mode == "dispatch_only":
        storage_search = {
            **storage_search,
            "enabled": False,
            "preset_ids": [],
            "presets": [],
            "data_status": "no_storage_baseline",
            "note": "Standalone heavy-empty dispatch excludes virtual and installed storage parameters.",
        }
    initial_soc_kwh = args.initial_soc_kwh
    target_final_soc_kwh = args.target_final_soc_kwh
    if not battery.storage_devices:
        initial_soc_kwh = 0.0 if initial_soc_kwh is None else initial_soc_kwh
        target_final_soc_kwh = 0.0 if target_final_soc_kwh is None else target_final_soc_kwh
    elif target_final_soc_kwh is None:
        target_final_soc_kwh = sum(
            item.initial_soc_kwh for item in battery.storage_devices
        )
    if optimization_mode == "dispatch_only":
        standalone_context = _dispatch_only_context(
            case_inputs=case_inputs,
            trains=trains,
            base_battery=battery,
            settlement_step_s=args.settlement_step_s,
            final_soc_tolerance_kwh=args.final_soc_tolerance_kwh,
            final_soc_penalty_per_kwh=args.final_soc_penalty_per_kwh,
            wasted_energy_penalty_per_kwh=wasted_energy_penalty_per_kwh,
        )
        storage_contexts = {"": standalone_context}
        baseline_preset_id = ""
    else:
        storage_contexts = build_storage_eval_contexts(
            case_inputs=case_inputs,
            trains=trains,
            base_battery=battery,
            preset_ids=list(storage_search["preset_ids"]),
            library_by_id=storage_search["library_by_id"],
            settlement_step_s=args.settlement_step_s,
            initial_soc_kwh=initial_soc_kwh,
            target_final_soc_kwh=target_final_soc_kwh,
            final_soc_tolerance_kwh=args.final_soc_tolerance_kwh,
            final_soc_penalty_per_kwh=args.final_soc_penalty_per_kwh,
            wasted_energy_penalty_per_kwh=wasted_energy_penalty_per_kwh,
            energy_scenario=args.energy_scenario,
        )
        baseline_preset_id = str(storage_search["preset_ids"][0])
    baseline_context = storage_contexts[baseline_preset_id]
    route = baseline_context.route
    battery = baseline_context.battery or battery
    heavy_cache = baseline_context.heavy_cache
    empty_cache = baseline_context.empty_cache
    settlement_system = baseline_context.settlement_system
    storage_sections = baseline_context.storage_sections
    baseline_template = ScheduleTemplate(
        heavy_headway_s=max(args.baseline_heavy_headway_s, min_depart_gap_s),
        empty_headway_s=max(args.baseline_empty_headway_s, min_depart_gap_s),
        heavy_empty_phase_s=args.baseline_phase_s,
        heavy_count=args.heavy_count,
        empty_count=args.empty_count,
        storage_preset_id=baseline_preset_id,
    )
    # 基线和优化计划必须包含相同的预测窗口列车数量。若基线评价全部发车而优化器按 horizon_s 过滤，
    # 模板超出当前规划窗口时就会产生虚假的能量/成本下降。
    baseline_schedule = _candidate_schedule(
        baseline_template,
        current_time_s=0,
        horizon_s=args.horizon_s,
    )

    profile_name = str(getattr(args, "search_profile", "standard") or "standard").strip().lower()
    if profile_name not in SEARCH_PROFILE_PRESETS:
        profile_name = "standard"
    args.search_profile = profile_name
    if profile_name != "standard":
        profile = SEARCH_PROFILE_PRESETS[profile_name]
        args.population_size = int(profile["population_size"])
        args.generations = int(profile["generations"])
        args.elite_count = int(profile["elite_count"])
    args.objective_priority = str(
        getattr(args, "objective_priority", OBJECTIVE_PRIORITY_ENERGY_FIRST) or OBJECTIVE_PRIORITY_ENERGY_FIRST
    )

    search_config = TemplateSearchConfig(
        method=args.search_method,
        population_size=args.population_size,
        generations=args.generations,
        elite_count=args.elite_count,
        min_headway_s=max(args.search_min_headway_s, min_depart_gap_s),
        max_headway_s=args.search_max_headway_s,
        phase_mutation_s=args.phase_mutation_s,
        hold_mutation_s=args.hold_mutation_s,
        headway_mutation_s=args.headway_mutation_s,
        storage_shift_mutation_s=getattr(args, "storage_shift_mutation_s", 300),
        max_phase_s=args.search_max_phase_s,
        max_hold_s=args.search_max_hold_s,
        max_storage_align_shift_s=getattr(args, "search_max_storage_align_shift_s", 1200),
        parallel_workers=args.parallel_workers,
        seed=args.seed,
        enable_storage_preset_search=bool(storage_search["enabled"]),
        storage_preset_ids=(
            () if optimization_mode == "dispatch_only"
            else tuple(storage_search["preset_ids"])
        ),
        storage_preset_mutation_probability=float(getattr(args, "storage_preset_mutation_probability", 0.55)),
    )
    optimizer = RollingOptimizer(
        route,
        heavy_cache,
        empty_cache,
        settlement_system,
        resource_model=case_inputs.resource_model,
        storage_sections=storage_sections,
        storage_contexts=storage_contexts,
        default_storage_preset_id=baseline_preset_id,
    )
    target_gap_s = int(round((baseline_template.heavy_headway_s + baseline_template.empty_headway_s) / 2.0))
    optimized_result = optimizer.optimize_once(
        RollingWindowState(0, [], []),
        baseline_template,
        horizon_s=args.horizon_s,
        execute_window_s=args.execute_window_s,
        search_config=search_config,
        objective_mode=args.objective_mode,
        energy_scenario=args.energy_scenario,
        objective_priority=args.objective_priority,
        min_depart_gap_s=min_depart_gap_s,
        target_gap_s=target_gap_s,
    )
    optimized_schedule = optimized_result.schedule
    baseline_population = (
        len(baseline_schedule.heavy_departures_s),
        len(baseline_schedule.empty_departures_s),
    )
    optimized_population = (
        len(optimized_schedule.heavy_departures_s),
        len(optimized_schedule.empty_departures_s),
    )
    if optimized_population != baseline_population:
        raise ValueError(
            "Optimizer changed the number of heavy/empty services inside the "
            "prediction horizon; refusing to report a misleading energy comparison. "
            f"baseline={baseline_population}, optimized={optimized_population}, "
            f"horizon_s={args.horizon_s}"
        )
    baseline_eval = evaluate_dispatch_schedule(
        "baseline",
        baseline_schedule,
        route,
        heavy_cache,
        empty_cache,
        settlement_system,
        case_inputs.resource_model,
        storage_sections,
        target_gap_s=target_gap_s,
        min_depart_gap_s=min_depart_gap_s,
        objective_mode=args.objective_mode,
        energy_scenario=args.energy_scenario,
        objective_priority=args.objective_priority,
    )
    optimized_template = optimized_result.schedule.template
    optimized_preset_id = str(getattr(optimized_template, "storage_preset_id", "") or baseline_preset_id)
    optimized_context = resolve_storage_eval_context(
        storage_contexts,
        optimized_preset_id,
        baseline_preset_id,
    )
    optimized_eval = evaluate_dispatch_schedule(
        "optimized",
        optimized_result.schedule,
        optimized_context.route,
        optimized_context.heavy_cache,
        optimized_context.empty_cache,
        optimized_context.settlement_system,
        case_inputs.resource_model,
        optimized_context.storage_sections,
        target_gap_s=target_gap_s,
        min_depart_gap_s=min_depart_gap_s,
        objective_mode=args.objective_mode,
        energy_scenario=args.energy_scenario,
        objective_priority=args.objective_priority,
    )

    # 将调度贡献、储能贡献和联合交互项分开，避免把储能收益归到列车调度上。
    if optimization_mode == "dispatch_only":
        no_storage_context = baseline_context
        baseline_no_storage_eval = baseline_eval
        optimized_no_storage_eval = optimized_eval
        baseline_with_selected_storage_eval = baseline_eval
    else:
        no_storage_context = _dispatch_only_context(
            case_inputs=case_inputs,
            trains=trains,
            base_battery=battery,
            settlement_step_s=args.settlement_step_s,
            final_soc_tolerance_kwh=args.final_soc_tolerance_kwh,
            final_soc_penalty_per_kwh=args.final_soc_penalty_per_kwh,
            wasted_energy_penalty_per_kwh=wasted_energy_penalty_per_kwh,
        )
        baseline_no_storage_eval = evaluate_dispatch_schedule(
            "baseline_no_storage",
            baseline_schedule,
            no_storage_context.route,
            no_storage_context.heavy_cache,
            no_storage_context.empty_cache,
            no_storage_context.settlement_system,
            case_inputs.resource_model,
            no_storage_context.storage_sections,
            target_gap_s=target_gap_s,
            min_depart_gap_s=min_depart_gap_s,
            objective_mode=args.objective_mode,
            energy_scenario=ENERGY_SCENARIO_DIRECT_NO_STORAGE,
            objective_priority=args.objective_priority,
        )
        optimized_no_storage_eval = evaluate_dispatch_schedule(
            "optimized_no_storage",
            optimized_result.schedule,
            no_storage_context.route,
            no_storage_context.heavy_cache,
            no_storage_context.empty_cache,
            no_storage_context.settlement_system,
            case_inputs.resource_model,
            no_storage_context.storage_sections,
            target_gap_s=target_gap_s,
            min_depart_gap_s=min_depart_gap_s,
            objective_mode=args.objective_mode,
            energy_scenario=ENERGY_SCENARIO_DIRECT_NO_STORAGE,
            objective_priority=args.objective_priority,
        )
        baseline_with_selected_storage_eval = evaluate_dispatch_schedule(
            "baseline_with_selected_storage",
            baseline_schedule,
            optimized_context.route,
            optimized_context.heavy_cache,
            optimized_context.empty_cache,
            optimized_context.settlement_system,
            case_inputs.resource_model,
            optimized_context.storage_sections,
            target_gap_s=target_gap_s,
            min_depart_gap_s=min_depart_gap_s,
            objective_mode=args.objective_mode,
            energy_scenario=args.energy_scenario,
            objective_priority=args.objective_priority,
        )
    energy_contribution = {
        "mode": optimization_mode,
        "baseline_no_storage_grid_kwh": round(baseline_no_storage_eval.settlement.grid_kwh, 6),
        "optimized_no_storage_grid_kwh": round(optimized_no_storage_eval.settlement.grid_kwh, 6),
        "baseline_with_selected_storage_grid_kwh": round(
            baseline_with_selected_storage_eval.settlement.grid_kwh,
            6,
        ),
        "dispatch_contribution_kwh": round(
            baseline_no_storage_eval.settlement.grid_kwh
            - optimized_no_storage_eval.settlement.grid_kwh,
            6,
        ),
        "storage_contribution_kwh": round(
            baseline_no_storage_eval.settlement.grid_kwh
            - baseline_with_selected_storage_eval.settlement.grid_kwh,
            6,
        ),
        "joint_saving_kwh": round(
            baseline_no_storage_eval.settlement.grid_kwh
            - optimized_eval.settlement.grid_kwh,
            6,
        ),
        "interaction_contribution_kwh": round(
            (
                baseline_no_storage_eval.settlement.grid_kwh
                - optimized_eval.settlement.grid_kwh
            )
            - (
                baseline_no_storage_eval.settlement.grid_kwh
                - optimized_no_storage_eval.settlement.grid_kwh
            )
            - (
                baseline_no_storage_eval.settlement.grid_kwh
                - baseline_with_selected_storage_eval.settlement.grid_kwh
            ),
            6,
        ),
        "eligible": bool(
            baseline_no_storage_eval.feasible
            and optimized_no_storage_eval.feasible
            and baseline_with_selected_storage_eval.feasible
            and optimized_eval.feasible
        ),
        "note": (
            "联合规划模式下拆分调度、储能和交互贡献；虚拟储能结果仍属于规划敏感性分析。"
            if optimization_mode == "joint_energy_planning"
            else "独立调度模式排除储能，储能贡献和交互贡献应解释为零。"
        ),
    }

    comparison_scope = storage_comparison_scope(
        baseline_preset_id,
        optimized_preset_id,
    )
    energy_comparison_eligible = baseline_eval.feasible and optimized_result.score.feasible and optimized_eval.feasible
    comparison_scope["energy_comparison_eligible"] = energy_comparison_eligible
    if not energy_comparison_eligible:
        comparison_scope.update(
            dispatch_only_attribution_allowed=False,
            comparison_note="基线或选中方案未通过适用约束检查。能耗值仅供诊断，暂不计算节能比例。",
        )
    kpi_rows = [kpi_dict(baseline_eval), kpi_dict(optimized_eval)]
    comparison = comparison_rows(
        baseline_eval,
        optimized_eval,
        comparison_scope=comparison_scope,
    )
    baseline_timeline = energy_timeline_rows(
        baseline_eval,
        baseline_context.battery or battery,
        args.settlement_step_s,
    )
    optimized_timeline = energy_timeline_rows(
        optimized_eval,
        optimized_context.battery or battery,
        args.settlement_step_s,
    )
    conflicts = conflict_rows([baseline_eval, optimized_eval])
    flow_events = flow_continuity_rows([baseline_eval, optimized_eval])
    flow_violations = flow_violation_rows([baseline_eval, optimized_eval])
    pareto_candidates_for_export = list(optimized_result.pareto_candidates)
    pareto_basis = "core_robust_feasible"
    ranked_export_candidates = list(optimized_result.ranked_candidates)
    ranked_export_basis = "core_robust"
    if not pareto_candidates_for_export and optimized_result.ranked_candidates:
        nominal_evaluated = []
        for template, _robust_score in optimized_result.ranked_candidates:
            nominal_score = evaluate_template_with_contexts(
                template,
                storage_contexts=storage_contexts,
                default_preset_id=baseline_preset_id,
                resource_model=case_inputs.resource_model,
                min_depart_gap_s=min_depart_gap_s,
                target_gap_s=target_gap_s,
                objective_mode=args.objective_mode,
                energy_scenario=args.energy_scenario,
                objective_priority=args.objective_priority,
            )
            nominal_evaluated.append((template, nominal_score))
        pareto_candidates_for_export = pareto_template_front(nominal_evaluated)
        pareto_basis = "nominal_feasible_fallback"
        ranked_export_candidates = sorted(
            nominal_evaluated,
            key=lambda item: candidate_selection_key(item[1]),
        )
        ranked_export_basis = "nominal_fallback"

    pareto_rows = candidate_rows(
        pareto_candidates_for_export,
        current_time_s=0,
        horizon_s=args.horizon_s,
        candidate_set=pareto_basis,
        energy_scenario=args.energy_scenario,
    )
    ranked_candidate_rows = candidate_rows(
        ranked_export_candidates,
        current_time_s=0,
        horizon_s=args.horizon_s,
        candidate_set=ranked_export_basis,
        energy_scenario=args.energy_scenario,
    )
    # 始终使用原始核心稳健排序集进行比较，使标称和诊断场景结果保持明确。
    compare_source = list(optimized_result.ranked_candidates)[:12]
    compare_rows = robust_nominal_compare_rows(
        compare_source,
        heavy_cache=heavy_cache,
        empty_cache=empty_cache,
        settlement_system=settlement_system,
        route=route,
        resource_model=case_inputs.resource_model,
        storage_sections=storage_sections,
        storage_contexts=storage_contexts,
        default_storage_preset_id=baseline_preset_id,
        min_depart_gap_s=min_depart_gap_s,
        target_gap_s=target_gap_s,
        objective_mode=args.objective_mode,
        energy_scenario=args.energy_scenario,
        objective_priority=args.objective_priority,
        current_time_s=0,
        horizon_s=args.horizon_s,
        scenario_scores_by_template=optimized_result.candidate_scenario_scores,
    )
    scenario_rows = list(optimized_result.selected_scenario_diagnostics)
    search_diagnostics = dict(optimized_result.search_diagnostics or {})
    search_diagnostics["storage_preset_search"] = {
        "enabled": bool(storage_search["enabled"]),
        "preset_ids": list(storage_search["preset_ids"]),
        "selected_optimized_preset_id": optimized_preset_id,
        "baseline_preset_id": baseline_preset_id,
        "data_status": storage_search["data_status"],
        "note": storage_search["note"],
        "presets": storage_search["presets"],
        "unknown_ids": list(storage_search.get("unknown_ids") or []),
        "search_summary": storage_search.get("search_summary", "Storage preset search diagnostics always exported."),
    }
    search_diagnostics["objective_priority"] = str(getattr(args, "objective_priority", OBJECTIVE_PRIORITY_ENERGY_FIRST))
    search_diagnostics["search_profile"] = str(getattr(args, "search_profile", "standard"))
    search_diagnostics["optimization_mode"] = optimization_mode
    baseline_network = build_time_space_network(
        baseline_eval.schedule,
        case_inputs.resource_model,
        heavy_cache,
        empty_cache,
        storage_sections,
    )
    optimized_network = build_time_space_network(
        optimized_eval.schedule,
        case_inputs.resource_model,
        optimized_context.heavy_cache,
        optimized_context.empty_cache,
        optimized_context.storage_sections,
    )

    if compare_rows:
        legacy_compare_path = output_dir / "robust_nominal_comparison.csv"
        if legacy_compare_path.exists():
            legacy_compare_path.unlink()
        write_csv_rows(output_dir / "core_robust_nominal_comparison.csv", list(compare_rows[0].keys()), compare_rows)
    if scenario_rows:
        write_csv_rows(
            output_dir / "selected_plan_scenario_diagnostics.csv",
            list(scenario_rows[0].keys()),
            scenario_rows,
        )
    (output_dir / "search_space_diagnostics.json").write_text(
        json.dumps(search_diagnostics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv_rows(output_dir / "kpi_summary.csv", list(kpi_rows[0].keys()), kpi_rows)
    write_csv_rows(output_dir / "kpi_comparison.csv", list(comparison[0].keys()), comparison)
    write_csv_rows(
        output_dir / "baseline_schedule.csv",
        list(
            train_rows(
                baseline_eval,
                heavy_cache,
                empty_cache,
                case_inputs.resource_model,
            )[0].keys()
        ),
        train_rows(
            baseline_eval,
            heavy_cache,
            empty_cache,
            case_inputs.resource_model,
        ),
    )
    write_csv_rows(
        output_dir / "optimized_schedule.csv",
        list(
            train_rows(
                optimized_eval,
                optimized_context.heavy_cache,
                optimized_context.empty_cache,
                case_inputs.resource_model,
            )[0].keys()
        ),
        train_rows(
            optimized_eval,
            optimized_context.heavy_cache,
            optimized_context.empty_cache,
            case_inputs.resource_model,
        ),
    )
    timeline_rows = baseline_timeline + optimized_timeline
    write_csv_rows(output_dir / "energy_timeline.csv", list(timeline_rows[0].keys()), timeline_rows)
    baseline_arc_rows = network_arc_rows(baseline_network)
    optimized_node_rows = network_node_rows(optimized_network)
    optimized_arc_rows = network_arc_rows(optimized_network)
    optimized_path_rows = network_path_rows(optimized_network)
    if optimized_node_rows:
        write_csv_rows(output_dir / "time_space_nodes.csv", list(optimized_node_rows[0].keys()), optimized_node_rows)
    if optimized_arc_rows:
        write_csv_rows(output_dir / "time_space_arcs.csv", list(optimized_arc_rows[0].keys()), optimized_arc_rows)
    if optimized_path_rows:
        write_csv_rows(output_dir / "time_space_paths.csv", list(optimized_path_rows[0].keys()), optimized_path_rows)
    conflict_fieldnames = [
        "case",
        "conflict_type",
        "severity",
        "resource_id",
        "resource_name",
        "train_a",
        "train_b",
        "train_a_type",
        "train_b_type",
        "overlap_start_s",
        "overlap_end_s",
        "overlap_duration_s",
        "location_km",
        "message",
        "suggestion",
    ]
    write_csv_rows(output_dir / "resource_conflicts.csv", conflict_fieldnames, conflicts)
    if flow_events:
        write_csv_rows(output_dir / "flow_continuity_events.csv", list(flow_events[0].keys()), flow_events)
    flow_violation_fieldnames = [
        "case",
        "time_s",
        "event_type",
        "flow_type",
        "train_id",
        "station_name",
        "stock_after",
        "message",
        "suggestion",
    ]
    write_csv_rows(output_dir / "flow_continuity_violations.csv", flow_violation_fieldnames, flow_violations)
    if pareto_rows:
        write_csv_rows(output_dir / "pareto_candidates.csv", list(pareto_rows[0].keys()), pareto_rows)
        (output_dir / "pareto_candidates.json").write_text(
            json.dumps(candidate_json_rows(pareto_rows), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if ranked_candidate_rows:
        write_csv_rows(
            output_dir / "ranked_candidates.csv",
            list(ranked_candidate_rows[0].keys()),
            ranked_candidate_rows,
        )

    plot_timetable(
        baseline_eval,
        optimized_eval,
        baseline_context.route,
        baseline_context.heavy_cache,
        baseline_context.empty_cache,
        output_dir / "timetable.png",
        optimized_route=optimized_context.route,
        optimized_heavy_cache=optimized_context.heavy_cache,
        optimized_empty_cache=optimized_context.empty_cache,
        resource_model=case_inputs.resource_model,
    )
    plot_energy_flow(baseline_eval, output_dir / "energy_flow_baseline.png")
    plot_energy_flow(optimized_eval, output_dir / "energy_flow_optimized.png")
    plot_soc_curve(baseline_timeline, optimized_timeline, output_dir / "soc_curve.png")
    plot_cost_comparison(baseline_eval, optimized_eval, output_dir / "cost_comparison.png")
    plot_resource_conflicts(conflicts, output_dir / "resource_conflict_timeline.png")

    summary = {
        "input": {
            "path": str(input_path),
            "source_kind": case_inputs.source_kind,
            "validation": None
            if case_inputs.validation_report is None
            else case_inputs.validation_report.summary(),
            "scenario_overrides": {
            "empty_mass_tons": args.empty_mass_tons,
            "battery_capacity_kwh": args.battery_capacity_kwh,
            "battery_max_charge_power_kw": args.battery_max_charge_power_kw,
            "battery_max_discharge_power_kw": args.battery_max_discharge_power_kw,
            "battery_round_trip_efficiency": args.battery_round_trip_efficiency,
            },
        },
        "route": {
            "total_length_km": route.total_length_km,
            "max_speed_kmh": route.max_speed_kmh,
            "station_count": len(route.stations),
            "energy_transfer_ranges_km": route.energy_transfer_ranges_km,
            "long_downhill_range_km": route.long_downhill_range_km,
        },
        "trains": {name: asdict(train) for name, train in trains.items()},
        "battery": asdict(baseline_context.battery or battery),
        "selected_storage_preset": {
            "baseline_preset_id": baseline_preset_id,
            "optimized_preset_id": optimized_preset_id,
            "optimized_label": optimized_context.label,
            "optimized_note": optimized_context.note,
            "optimized_data_status": optimized_context.data_status,
            "optimized_battery": asdict(optimized_context.battery) if optimized_context.battery is not None else None,
            "optimized_energy_transfer_ranges_km": list(getattr(optimized_context.route, "energy_transfer_ranges_km", []) or []),
            "search_enabled": bool(storage_search["enabled"]),
            "search_preset_ids": list(storage_search["preset_ids"]),
        },
        "optimization_mode": optimization_mode,
        "energy_contribution": energy_contribution,
        "energy_scenario": {
            "mode": args.energy_scenario,
            "label": energy_scenario["label"],
            "allow_direct_use": energy_scenario["allow_direct_use"],
            "allow_storage": energy_scenario["allow_storage"],
            "settlement_scope": "same_power_arm_same_time_window",
            "note": energy_scenario["note"],
        },
        "parameters": {
            "heavy_count": args.heavy_count,
            "empty_count": args.empty_count,
            "settlement_step_s": args.settlement_step_s,
            "horizon_s": args.horizon_s,
            "search_method": args.search_method,
            "population_size": args.population_size,
            "generations": args.generations,
            "seed": args.seed,
            "min_depart_gap_s": min_depart_gap_s,
            "requested_min_depart_gap_s": args.min_depart_gap_s,
            "resource_min_depart_headway_s": case_inputs.resource_model.config.min_depart_headway_s,
            "resource_min_depart_headway_source": case_inputs.resource_model.config.min_depart_headway_source,
            "station_operation_min_times_s": case_inputs.resource_model.station_operation_min_times_s,
            "station_operation_sources": case_inputs.resource_model.station_operation_sources,
            "station_operation_assignments": list(case_inputs.resource_model.station_operation_assignments),
            "initial_heavy_flow_count": case_inputs.resource_model.config.initial_heavy_flow_count,
            "initial_empty_flow_count": case_inputs.resource_model.config.initial_empty_flow_count,
            "enforce_flow_continuity": case_inputs.resource_model.config.enforce_flow_continuity,
            "objective_mode": args.objective_mode,
            "energy_scenario": args.energy_scenario,
            "energy_scenario_label": energy_scenario["label"],
            "allow_direct_use": energy_scenario["allow_direct_use"],
            "allow_storage": energy_scenario["allow_storage"],
            "settlement_scope": "same_power_arm_same_time_window",
        },
        "baseline": kpi_dict(baseline_eval),
        "optimized": kpi_dict(optimized_eval),
        "time_space_network": {
            "baseline": network_summary(baseline_network),
            "optimized": network_summary(optimized_network),
            "exported_files": [
                "time_space_nodes.csv",
                "time_space_arcs.csv",
                "time_space_paths.csv",
            ],
            "model_note": (
                "Schedules are now expanded into node-arc time-space paths for evaluation and export. "
                "The search genes remain compact headway/phase templates; replacing them with full network-flow "
                "decision variables is the next optimization-layer step."
            ),
        },
        "comparison": {
            **comparison_scope,
            "cost_reduction_pct": _rounded_pct(
                baseline_eval.settlement.total_cost,
                optimized_eval.settlement.total_cost,
            ) if energy_comparison_eligible else None,
            "grid_reduction_pct": _rounded_pct(
                baseline_eval.settlement.grid_kwh,
                optimized_eval.settlement.grid_kwh,
            ) if energy_comparison_eligible else None,
            "wasted_reduction_pct": _rounded_pct(
                baseline_eval.settlement.wasted_kwh,
                optimized_eval.settlement.wasted_kwh,
            ) if energy_comparison_eligible else None,
        },
        "optimized_departures": {
            "heavy_departures_s": optimized_eval.schedule.heavy_departures_s,
            "empty_departures_s": optimized_eval.schedule.empty_departures_s,
            "executable_heavy_departures_s": optimized_result.executable_heavy_departures_s,
            "executable_empty_departures_s": optimized_result.executable_empty_departures_s,
        },
        "energy_observability": energy_observability,
        "optimizer_diagnostics": {
            "candidate_count": optimized_result.candidate_count,
            "core_robust_feasible_candidate_count": optimized_result.feasible_candidate_count,
            "pareto_candidate_count": len(pareto_candidates_for_export),
            "pareto_export_basis": pareto_basis,
            "ranked_export_basis": ranked_export_basis,
            "all_core_robust_candidates_infeasible": optimized_result.feasible_candidate_count == 0,
            "returned_candidate_core_robust_feasible": (
                optimized_result.score.feasible if ranked_export_basis == "core_robust" else False
            ),
            "returned_candidate_score_feasible": optimized_result.score.feasible,
            "nominal_optimized_feasible": optimized_eval.feasible,
            "diagnostic": optimized_result.diagnostic,
            "search_diagnostics": search_diagnostics,
            "selected_scenario_diagnostics": scenario_rows,
            "energy_observability": energy_observability,
        },
        "pareto_candidates": {
            "count": len(pareto_candidates_for_export),
            "basis": pareto_basis,
            "exported_files": [
                "pareto_candidates.csv",
                "pareto_candidates.json",
                "ranked_candidates.csv",
            ],
            "objective_columns": [
                "objective_1_effective_regen_loss_kwh",
                "objective_2_grid_kwh",
                "objective_3_capacity_or_headway",
            ],
            "model_note": (
                "The optimizer exports the non-dominated core-robust-feasible candidate set when available. "
                "If no core-robust-feasible candidate exists but nominal candidates are feasible, "
                "pareto_candidates.* falls back to nominal-feasible alternatives and records basis="
                f"{pareto_basis}."
            ),
        },
        "flow_continuity": {
            "baseline_feasible": baseline_eval.flow_continuity_feasible,
            "optimized_feasible": optimized_eval.flow_continuity_feasible,
            "baseline_violation_count": len(baseline_eval.resource_check.flow_continuity_violations),
            "optimized_violation_count": len(optimized_eval.resource_check.flow_continuity_violations),
            "event_count": len(flow_events),
            "exported_files": [
                "flow_continuity_events.csv",
                "flow_continuity_violations.csv",
            ],
            "model_note": (
                "Flow continuity consumes Heavy flow at loaded departure, releases Empty flow after unloading, "
                "consumes Empty flow at empty departure, and releases Heavy flow after loading. Initial flow stock "
                "is scenario data in resource_config.json because official initial rolling-stock inventory is not "
                "available in the current PDF-derived bundle."
            ),
        },
        "outputs": {
            "report": "DISPATCH_CASE_REPORT.md",
            "kpi_summary": "kpi_summary.csv",
            "kpi_comparison": "kpi_comparison.csv",
            "energy_timeline": "energy_timeline.csv",
            "resource_conflicts": "resource_conflicts.csv",
            "core_robust_nominal_comparison": "core_robust_nominal_comparison.csv",
            "selected_plan_scenario_diagnostics": "selected_plan_scenario_diagnostics.csv",
            "search_space_diagnostics": "search_space_diagnostics.json",
            "flow_continuity_events": "flow_continuity_events.csv",
            "flow_continuity_violations": "flow_continuity_violations.csv",
            "pareto_candidates": "pareto_candidates.csv",
            "ranked_candidates": "ranked_candidates.csv",
            "timetable": "timetable.png",
            "cost_comparison": "cost_comparison.png",
        },
    }
    attribution = write_optimization_attribution(
        output_dir,
        workflow="dispatch",
        summary=summary,
        candidate_rows=ranked_candidate_rows,
        pareto_rows=pareto_rows,
        scenario_rows=scenario_rows,
        timeline_rows=timeline_rows,
        baseline_schedule_rows=train_rows(
            baseline_eval,
            heavy_cache,
            empty_cache,
            case_inputs.resource_model,
        ),
        optimized_schedule_rows=train_rows(
            optimized_eval,
            optimized_context.heavy_cache,
            optimized_context.empty_cache,
            case_inputs.resource_model,
        ),
        baseline_arc_rows=baseline_arc_rows,
        optimized_arc_rows=optimized_arc_rows,
    )
    summary["optimization_attribution"] = attribution
    summary["outputs"].update(
        {
            "optimization_attribution_report": "OPTIMIZATION_ATTRIBUTION_REPORT.md",
            "optimization_attribution_summary": "optimization_attribution_summary.json",
            "optimization_kpi_attribution": "optimization_kpi_attribution.csv",
            "optimization_candidate_decisions": "optimization_candidate_decisions.csv",
            "optimization_candidate_funnel": "optimization_candidate_funnel.csv",
            "optimization_bottlenecks": "optimization_bottlenecks.csv",
            "optimization_dimension_attribution": "optimization_dimension_attribution.csv",
        }
    )
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(
        output_dir / "DISPATCH_CASE_REPORT.md",
        input_path,
        replace(case_inputs, route=route, trains=trains, battery=battery),
        baseline_eval,
        optimized_eval,
        comparison,
        energy_scenario,
        pareto_basis,
        len(pareto_candidates_for_export),
        optimizer_diagnostics={
            "ranked_export_basis": ranked_export_basis,
            "core_robust_feasible_candidate_count": optimized_result.feasible_candidate_count,
            "returned_candidate_score_feasible": optimized_result.score.feasible,
            "search_diagnostics": search_diagnostics,
        },
        compare_rows=compare_rows,
        scenario_rows=scenario_rows,
        energy_observability=energy_observability,
    )
    return summary


def _summary_storage_efficiency(summary: Dict[str, Any]) -> float:
    """函数 _summary_storage_efficiency：执行该模块中的相关处理逻辑。"""
    selected = summary.get("selected_storage_preset") or {}
    battery = selected.get("optimized_battery") or summary.get("battery") or {}
    return float(battery.get("round_trip_efficiency", 1.0))


def energy_scenario_choice_score(summary: Dict[str, Any]) -> float:
    """函数 energy_scenario_choice_score：执行该模块中的相关处理逻辑。"""
    optimized = summary["optimized"]

    scenario = summary["energy_scenario"]["mode"]
    base = float(optimized["total_cost"])
    wasted = float(optimized["wasted_kwh"])
    grid = float(optimized["grid_kwh"])
    direct = float(optimized["direct_used_kwh"])
    charge = float(optimized["battery_charge_kwh"])
    discharge = float(optimized["battery_discharge_kwh"])
    final_soc_deviation = float(optimized.get("final_soc_deviation_kwh", 0.0))
    effective_loss = float(
        optimized.get(
            "effective_regen_loss_kwh",
            storage_no_direct_effective_loss_kwh(
                wasted,
                charge,
                discharge,
                final_soc_deviation,
                _summary_storage_efficiency(summary),
                float(optimized.get("final_soc_shortfall_kwh", 0.0)),
            ),
        )
    )
    flow_penalty = 1e9 * int(optimized.get("flow_continuity_violation_count", 0))
    conflict_penalty = 1e9 * int(optimized.get("resource_conflict_count", 0))

    if scenario == ENERGY_SCENARIO_DIRECT_NO_STORAGE:
        scenario_term = 0.05 * wasted + 0.05 * grid - 0.15 * direct
    elif scenario in {
        ENERGY_SCENARIO_STORAGE_NO_DIRECT,
        ENERGY_SCENARIO_DIRECT_WITH_STORAGE,
    }:
        scenario_term = 0.05 * (grid + effective_loss)
    else:
        scenario_term = 0.05 * wasted + 0.05 * grid - 0.12 * direct - 0.06 * (charge + discharge)
    feasibility_penalty = 1e15 if not optimized.get("feasible", False) else 0.0
    return base + scenario_term + flow_penalty + conflict_penalty + feasibility_penalty


def energy_scenario_choice_key(summary: Dict[str, Any]) -> Tuple[float, ...]:
    """函数 energy_scenario_choice_key：执行该模块中的相关处理逻辑。"""
    optimized = summary["optimized"]
    scenario = summary["energy_scenario"]["mode"]
    scenario_preference = {
        ENERGY_SCENARIO_STORAGE_NO_DIRECT: 0,
        ENERGY_SCENARIO_DIRECT_WITH_STORAGE: 1,
        ENERGY_SCENARIO_DIRECT_NO_STORAGE: 2,
    }
    storage_reused = float(optimized["battery_discharge_kwh"])
    effective_regen_loss = float(
        optimized.get(
            "effective_regen_loss_kwh",
            storage_no_direct_effective_loss_kwh(
                float(optimized["wasted_kwh"]),
                float(optimized["battery_charge_kwh"]),
                storage_reused,
                float(optimized.get("final_soc_deviation_kwh", 0.0)),
                _summary_storage_efficiency(summary),
                float(optimized.get("final_soc_shortfall_kwh", 0.0)),
            ),
        )
    )
    return (
        0.0 if optimized.get("feasible", False) else 1.0,
        float(optimized.get("resource_conflict_count", 0)),
        float(optimized.get("flow_continuity_violation_count", 0)),
        effective_regen_loss,
        float(optimized["grid_kwh"]),
        -storage_reused,
        float(scenario_preference.get(scenario, 99)),
        energy_scenario_choice_score(summary),
    )


def energy_scenario_comparison_row(summary: Dict[str, Any]) -> Dict[str, Any]:
    """函数 energy_scenario_comparison_row：执行该模块中的相关处理逻辑。"""
    optimized = summary["optimized"]
    scenario = summary["energy_scenario"]
    comparison = summary.get("comparison") or {}
    return {
        "energy_scenario": scenario["mode"],
        "energy_scenario_label": scenario["label"],
        "comparison_scope": comparison.get("comparison_scope", "unspecified"),
        "dispatch_only_attribution_allowed": comparison.get(
            "dispatch_only_attribution_allowed", False
        ),
        "storage_preset_changed": comparison.get("storage_preset_changed", False),
        "baseline_storage_preset_id": comparison.get("baseline_storage_preset_id", ""),
        "optimized_storage_preset_id": comparison.get("optimized_storage_preset_id", ""),
        "selected_score": round(energy_scenario_choice_score(summary), 6),
        "optimized_feasible": optimized["feasible"],
        "resource_conflict_count": optimized["resource_conflict_count"],
        "flow_continuity_violation_count": optimized["flow_continuity_violation_count"],
        "total_cost": optimized["total_cost"],
        "direct_used_kwh": optimized["direct_used_kwh"],
        "direct_use_ratio": optimized["direct_use_ratio"],
        "battery_charge_kwh": optimized["battery_charge_kwh"],
        "battery_discharge_kwh": optimized["battery_discharge_kwh"],
        "wasted_kwh": optimized["wasted_kwh"],
        "grid_kwh": optimized["grid_kwh"],
        "final_soc_kwh": optimized["final_soc_kwh"],
        "final_soc_deviation_kwh": optimized["final_soc_deviation_kwh"],
        "pareto_candidate_count": summary["pareto_candidates"]["count"],
        "output_dir": summary["outputs"].get("case_output_dir", ""),
    }


def write_auto_energy_report(output_dir: Path, rows: List[Dict[str, Any]], selected: Dict[str, Any]) -> None:
    """函数 write_auto_energy_report：执行该模块中的相关处理逻辑。"""
    lines = [
        "# 能源场景自动选择报告",
        "",
        f"选中场景：`{selected['energy_scenario']['mode']}` - {selected['energy_scenario']['label']}",
        "",
        "| 场景 | 是否可行 | 评分 | 代价 | 直接利用（千瓦时） | 储能充电/放电（千瓦时） | 弃能（千瓦时） | 电网供能（千瓦时） | 冲突数 | 流向违反数 | 输出目录 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['energy_scenario']}` | {row['optimized_feasible']} | {row['selected_score']} | "
            f"{row['total_cost']} | {row['direct_used_kwh']} | "
            f"{row['battery_charge_kwh']} / {row['battery_discharge_kwh']} | "
            f"{row['wasted_kwh']} | {row['grid_kwh']} | {row['resource_conflict_count']} | "
            f"{row['flow_continuity_violation_count']} | `{row['output_dir']}` |"
        )
    lines.extend(
        [
            "",
            "选择规则：优先选择可行场景。可行性相同时，依次比较资源冲突、流向连续性违反、弃能、电网供能、储能利用率和数值评分。当前朔黄上下行供电按相互隔离处理，因此直接利用奖励不会使直接利用兼容场景自动优先。",
            "",
        ]
    )
    (output_dir / "AUTO_ENERGY_SCENARIO_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run_auto_energy_scenario_case(args: argparse.Namespace) -> Dict[str, Any]:
    """函数 run_auto_energy_scenario_case：执行该模块中的相关处理逻辑。"""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries: List[Dict[str, Any]] = []
    for scenario in ENERGY_SCENARIOS:
        scenario_args = argparse.Namespace(**vars(args))
        scenario_args.energy_scenario = scenario
        scenario_args.output_dir = str(output_dir / scenario)
        summary = run_case(scenario_args)
        summary["outputs"]["case_output_dir"] = scenario_args.output_dir
        summaries.append(summary)

    selected = min(summaries, key=energy_scenario_choice_key)
    rows = [energy_scenario_comparison_row(summary) for summary in summaries]
    write_csv_rows(output_dir / "energy_scenario_comparison.csv", list(rows[0].keys()), rows)
    (output_dir / "energy_scenario_comparison.json").write_text(
        json.dumps(
            {
                "selected_energy_scenario": selected["energy_scenario"],
                "selection_score": energy_scenario_choice_score(selected),
                "scenarios": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_auto_energy_report(output_dir, rows, selected)
    return {
        "input": selected["input"],
        "energy_scenario_auto": True,
        "selected_energy_scenario": selected["energy_scenario"],
        "baseline": selected["baseline"],
        "optimized": selected["optimized"],
        "comparison": selected["comparison"],
        "optimizer_diagnostics": selected["optimizer_diagnostics"],
        "scenario_comparison": rows,
        "outputs": {
            "energy_scenario_comparison": "energy_scenario_comparison.csv",
            "energy_scenario_comparison_json": "energy_scenario_comparison.json",
            "auto_report": "AUTO_ENERGY_SCENARIO_REPORT.md",
            "selected_case_output_dir": selected["outputs"]["case_output_dir"],
        },
    }


def build_parser() -> argparse.ArgumentParser:
    """函数 build_parser：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="Run one dispatch case and export evaluation reports.")
    parser.add_argument(
        "--optimization-mode",
        choices=OPTIMIZATION_MODES,
        default="joint_energy_planning",
        help=(
            "Optimization mode. dispatch_only excludes storage parameters from heavy-empty dispatch. "
            "joint_energy_planning enables explicit storage-aware co-optimization."
        ),
    )
    parser.add_argument("--input", default="data/real_shuohuang", help="Real-data directory or legacy sandbox_config.json.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory.")
    parser.add_argument("--heavy-count", type=int, default=3)
    parser.add_argument("--empty-count", type=int, default=3)
    parser.add_argument("--baseline-heavy-headway-s", type=int, default=3300)
    parser.add_argument("--baseline-empty-headway-s", type=int, default=2700)
    parser.add_argument(
        "--baseline-phase-s",
        type=int,
        default=2600,
        help="Preset empty-train phase for the synthetic baseline template. 2600s with 3300/2700 headways is the current conflict-free synthetic baseline pending a real timetable.",
    )
    parser.add_argument("--min-depart-gap-s", type=int, default=300)
    parser.add_argument("--horizon-s", type=int, default=14400)
    parser.add_argument("--execute-window-s", type=int, default=1800)
    parser.add_argument("--settlement-step-s", type=int, default=10)
    parser.add_argument(
        "--empty-mass-tons",
        type=float,
        default=None,
        help="Scenario override for the Empty train mass; use for empty/light/mixed return-train sensitivity runs.",
    )
    parser.add_argument(
        "--battery-capacity-kwh",
        type=float,
        default=None,
        help="Scenario override for storage capacity; does not modify battery.json.",
    )
    parser.add_argument(
        "--battery-max-charge-power-kw",
        type=float,
        default=None,
        help="Scenario override for storage max charge power; does not modify battery.json.",
    )
    parser.add_argument(
        "--battery-max-discharge-power-kw",
        type=float,
        default=None,
        help="Scenario override for storage max discharge power; does not modify battery.json.",
    )
    parser.add_argument(
        "--battery-round-trip-efficiency",
        type=float,
        default=None,
        help="Scenario override for storage round-trip efficiency; does not modify battery.json.",
    )
    parser.add_argument(
        "--battery-depreciation-per-kwh",
        type=float,
        default=None,
        help="Scenario override for battery depreciation cost per kWh; lower values favor more storage throughput.",
    )
    parser.add_argument(
        "--battery-grid-price-per-kwh",
        type=float,
        default=None,
        help="Scenario override for grid purchase price per kWh used in settlement total_cost.",
    )
    parser.add_argument("--initial-soc-kwh", type=float, default=None)
    parser.add_argument("--target-final-soc-kwh", type=float, default=None, help="Target final SOC. File-mode defaults to 0; database device mode defaults to the sum of device initial SOC values.")
    parser.add_argument("--final-soc-tolerance-kwh", type=float, default=0.0)
    parser.add_argument("--final-soc-penalty-per-kwh", type=float, default=0.05, help="Penalty per kWh of final-SOC shortfall/excess. Default 0.05 discourages parked energy under energy_first.")
    parser.add_argument("--wasted-energy-penalty-per-kwh", type=float, default=0.0)
    parser.add_argument(
        "--enable-energy-observability",
        action="store_true",
        default=True,
        help=(
            "Apply the recommended wasted-energy penalty (0.05 CNY/kWh) when the explicit penalty is left at 0, "
            "so regenerative waste becomes visible in total_cost for algorithm diagnosis. Enabled by default."
        ),
    )
    parser.add_argument(
        "--disable-energy-observability",
        action="store_true",
        help="Disable the default wasted-energy observability penalty.",
    )
    parser.add_argument(
        "--energy-scenario",
        choices=[*ENERGY_SCENARIOS, ENERGY_SCENARIO_DIRECT_NO_STORAGE, ENERGY_SCENARIO_AUTO],
        default=ENERGY_SCENARIO_STORAGE_NO_DIRECT,
        help=(
            "Energy utilization scenario. Current Shuohuang workflow uses storage_no_direct only: "
            "direct use is disabled, and regenerative energy can only be reused through storage-equipped sections. "
            "auto is retained as an alias that evaluates the active scenario set."
        ),
    )
    parser.add_argument(
        "--objective-mode",
        choices=[OBJECTIVE_MODE_BALANCED, OBJECTIVE_MODE_CAPACITY_SURPLUS, OBJECTIVE_MODE_CAPACITY_TIGHT],
        default=OBJECTIVE_MODE_BALANCED,
        help=(
            "Optimizer objective profile: balanced keeps the original robust cost/headway balance; "
            "capacity_surplus rewards larger departure margins; capacity_tight rewards tighter capacity use."
        ),
    )
    parser.add_argument(
        "--objective-priority",
        choices=[OBJECTIVE_PRIORITY_ENERGY_FIRST, OBJECTIVE_PRIORITY_COST_FIRST, OBJECTIVE_PRIORITY_BALANCED],
        default=OBJECTIVE_PRIORITY_ENERGY_FIRST,
        help=(
            "Business objective alignment for ranking feasible candidates: "
            "energy_first minimizes wasted/grid first (default for storage_no_direct); "
            "cost_first minimizes settlement total_cost first; balanced blends both."
        ),
    )
    parser.add_argument(
        "--search-profile",
        choices=sorted(SEARCH_PROFILE_PRESETS.keys()),
        default="standard",
        help=(
            "Named search-scale profile. quick/standard/large set population/generations/elite. "
            "Use large when energy_flat or core_robust_feasible_count is low."
        ),
    )
    parser.add_argument("--search-method", choices=["nsga2", "grid", "evolutionary"], default="nsga2")
    parser.add_argument("--population-size", type=int, default=12)
    parser.add_argument("--generations", type=int, default=4)
    parser.add_argument("--elite-count", type=int, default=4)
    parser.add_argument("--search-min-headway-s", type=int, default=2400)
    parser.add_argument("--search-max-headway-s", type=int, default=4200)
    parser.add_argument("--search-max-phase-s", type=int, default=5400)
    parser.add_argument("--search-max-hold-s", type=int, default=900)
    parser.add_argument("--search-max-storage-align-shift-s", type=int, default=1200)
    parser.add_argument("--phase-mutation-s", type=int, default=300)
    parser.add_argument("--hold-mutation-s", type=int, default=180)
    parser.add_argument("--storage-shift-mutation-s", type=int, default=300)
    parser.add_argument("--headway-mutation-s", type=int, default=300)
    parser.add_argument("--parallel-workers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument(
        "--enable-storage-preset-search",
        action="store_true",
        default=True,
        help="Search editable virtual storage presets (capacity/power/coverage) as energy genes.",
    )
    parser.add_argument(
        "--disable-storage-preset-search",
        action="store_true",
        help="Disable virtual storage-preset search and keep a fixed storage context.",
    )
    parser.add_argument(
        "--storage-preset-ids",
        type=str,
        default=",".join([
            "virtual_two_section_base",
            "virtual_two_section_high_power",
            "virtual_two_section_high_capacity",
            "virtual_two_section_high_power_capacity",
            "virtual_expanded_regen_corridor",
        ]),
        help="Comma-separated virtual storage preset ids to search. Default excludes near_full upper-bound diagnosis.",
    )
    parser.add_argument(
        "--storage-preset-mutation-probability",
        type=float,
        default=0.55,
        help="Mutation probability for the virtual storage-preset gene.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    summary = (
        run_auto_energy_scenario_case(args)
        if args.energy_scenario == ENERGY_SCENARIO_AUTO
        else run_case(args)
    )
    print("=== 重空调度算例 ===")
    print("输出目录", Path(args.output_dir).resolve())
    if summary.get("energy_scenario_auto"):
        print("自动选中的能量场景", summary["selected_energy_scenario"]["mode"])
    print("基线是否可行", summary["baseline"]["feasible"])
    print("候选是否可行", summary["optimized"]["feasible"])
    print("基线总成本", summary["baseline"]["total_cost"])
    print("候选总成本", summary["optimized"]["total_cost"])
    print("比较范围", summary["comparison"].get("comparison_scope"))
    print(
        "是否允许归因于调度",
        summary["comparison"].get("dispatch_only_attribution_allowed"),
    )
    if not summary["comparison"].get("dispatch_only_attribution_allowed", False):
        print("比较说明", summary["comparison"].get("comparison_note"))
    print("成本降幅（百分比）", summary["comparison"]["cost_reduction_pct"])
    print("优化方案资源冲突数", summary["optimized"]["resource_conflict_count"])
    diagnostics = summary.get("optimizer_diagnostics", {})
    search_diagnostics = diagnostics.get("search_diagnostics", {}) or {}
    print("核心场景均可行的候选数", diagnostics.get("core_robust_feasible_candidate_count"))
    print("帕累托候选导出依据", diagnostics.get("pareto_export_basis"))
    print("搜索期间能耗指标是否持平", search_diagnostics.get("energy_flat"))
    print("弃能降幅（百分比）", summary["comparison"].get("wasted_reduction_pct"))
    print("购电降幅（百分比）", summary["comparison"].get("grid_reduction_pct"))
    storage_diag = (search_diagnostics.get("storage_preset_search") or {})
    if storage_diag:
        print("是否启用储能预设搜索", storage_diag.get("enabled"))
        print("选中的储能预设", storage_diag.get("selected_optimized_preset_id"))
    energy_obs = summary.get("energy_observability") or summary.get("baseline", {}).get("energy_observability")
    if not energy_obs:
        # 如果后续导出，则从嵌套参数中读取回退值。
        energy_obs = diagnostics.get("energy_observability")
    if energy_obs:
        print("是否启用能量可观测性", energy_obs.get("enabled"))
        print("弃能惩罚（元每千瓦时）", energy_obs.get("applied_wasted_energy_penalty_per_kwh"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
