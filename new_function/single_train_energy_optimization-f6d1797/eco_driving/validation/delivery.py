"""真实线路、目标时分和鲁棒性验证套件。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterable, Mapping, Optional

from regenerative_braking.simulation.regenerative_simulator import SimulationConfig
from regenerative_braking.simulation.scenario_runner import load_component_bundle

from ..io.data_loader import load_eco_driving_data
from ..io.heavy_empty_interface import request_from_shared_data, validate_request_against_shared_data
from ..io.output_contract import EcoDrivingOutputRecord, write_output_records
from ..optimizer.baseline import run_baseline
from ..optimizer.eco_driving_optimizer import EcoDrivingOptimizer
from .end_to_end import run_end_to_end_comparison


def _metrics(result):
    return result.metrics


def _scenario_result_feasible(result, scenario) -> bool:
    """Check the same endpoint/runtime/speed-limit contract for baseline and optimized."""

    if not bool(result.metadata.get("reached_end", False)):
        return False
    if not bool(result.metadata.get("feasible_candidate", True)):
        return False
    for sample in result.samples:
        if sample.speed_limit_mps is not None and sample.speed_mps > sample.speed_limit_mps + 1e-6:
            return False
    target = scenario.constraints.target_runtime_s
    if target is not None and abs(result.runtime_s - target) > scenario.constraints.runtime_tolerance_s:
        return False
    return abs(result.final_speed_mps - scenario.constraints.terminal_speed_mps) <= 0.5


def run_delivery_suite(
    *,
    train_id: str = "eco-delivery-heavy-001",
    train_type: str = "Heavy",
    start_km: float = 108.0,
    end_km: float = 108.2,
    initial_speed_kmh: float = 36.0,
    regen_dt: float = 2e-4,
    eco_dt: float = 1.0,
    beam_width: int = 8,
    runtime_factors: Iterable[Optional[float]] = (None, 0.9, 1.0, 1.1),
    robustness_mass_factors: Iterable[float] = (0.8, 1.0, 1.2),
    out_dir: Optional[Path] = None,
) -> tuple[list[EcoDrivingOutputRecord], Mapping[str, Path] | None]:
    data = load_eco_driving_data(train_type)
    request = request_from_shared_data(
        data.railway,
        train_id=train_id,
        train_type=train_type,
        route_start_km=start_km,
        route_end_km=end_km,
        initial_speed_mps=initial_speed_kmh / 3.6,
    )
    audit = validate_request_against_shared_data(request, data.railway)
    base_scenario = request.to_scenario()
    base_bundle = replace(load_component_bundle(), train=data.train)
    base_baseline = run_baseline(base_scenario, data.railway, data.train, dt=eco_dt, traction_limit_n=data.traction_limit_n)
    nominal_runtime = base_baseline.runtime_s
    records: list[EcoDrivingOutputRecord] = []
    cases: list[tuple[str, object, object, Optional[float], object, object]] = []
    for factor in runtime_factors:
        target = None if factor is None else nominal_runtime * factor
        scenario = replace(base_scenario, constraints=replace(base_scenario.constraints, target_runtime_s=target))
        train_profile = data.train
        baseline = run_baseline(scenario, data.railway, train_profile, dt=eco_dt, traction_limit_n=data.traction_limit_n)
        optimized = EcoDrivingOptimizer(data.railway, train_profile, data.traction_limit_n, beam_width=beam_width, dt=eco_dt).optimize(scenario)
        label = "runtime_free" if factor is None else f"runtime_{factor:.2f}x"
        cases.append((label, baseline, optimized, target, base_bundle, scenario))
    for mass_factor in robustness_mass_factors:
        if mass_factor == 1.0:
            continue
        scenario = replace(base_scenario, description=f"列车质量倍率={mass_factor:g}")
        train_profile = replace(data.train, mass_kg=data.train.mass_kg * mass_factor)
        baseline = run_baseline(scenario, data.railway, train_profile, dt=eco_dt, traction_limit_n=data.traction_limit_n)
        optimized = EcoDrivingOptimizer(data.railway, train_profile, data.traction_limit_n, beam_width=beam_width, dt=eco_dt).optimize(scenario)
        # 质量扰动必须同时进入 eco-driving 和 regenerative_braking，避免
        # 端到端比较把改变后的速度曲线送回标称列车模型。
        cases.append((f"mass_{mass_factor:g}x", baseline, optimized, None, replace(base_bundle, train=train_profile), scenario))
    for label, baseline, optimized, runtime_target, case_bundle, scenario in cases:
        comparison = run_end_to_end_comparison(
            baseline, optimized,
            bundle=case_bundle,
            config=SimulationConfig(dt=regen_dt, record_stride=1),
            start_km=start_km,
            controller_profile="main",
        )
        b_eco = _metrics(comparison.baseline_regenerative)
        o_eco = _metrics(comparison.optimized_regenerative)
        violations = optimized.metadata.get("constraint_violations", ())
        baseline_energy_map = baseline.metadata.get("energy") or {}
        optimized_energy_map = optimized.metadata.get("energy") or {}
        baseline_traction = float(baseline_energy_map.get("traction_energy_kwh", 0.0))
        optimized_traction = float(optimized_energy_map.get("traction_energy_kwh", 0.0))
        baseline_regen = float(b_eco.get("captured_regenerative_energy_kwh", 0.0))
        optimized_regen = float(o_eco.get("captured_regenerative_energy_kwh", 0.0))
        # 正式输出的 section energy 统一为同一条物理链上的净能耗：
        # eco-driving 负责牵引功，regenerative_braking 负责实际储能吸收功。
        baseline_energy = baseline_traction - baseline_regen
        optimized_energy = optimized_traction - optimized_regen
        comparison_feasible = _scenario_result_feasible(baseline, scenario) and bool(
            optimized.metadata.get("feasible_candidate", False)
        )
        saving = baseline_energy - optimized_energy if comparison_feasible else None
        records.append(EcoDrivingOutputRecord(
            train_id=train_id,
            train_type=train_type,
            route_start_km=start_km,
            route_end_km=end_km,
            scenario=label,
            target_runtime_s=runtime_target,
            baseline_runtime_s=baseline.runtime_s,
            optimized_runtime_s=optimized.runtime_s,
            baseline_section_energy_kwh=baseline_energy,
            optimized_section_energy_kwh=optimized_energy,
            baseline_traction_energy_kwh=baseline_traction,
            optimized_traction_energy_kwh=optimized_traction,
            baseline_braking_energy_kwh=float(baseline_energy_map.get("mechanical_braking_energy_kwh", 0.0)),
            optimized_braking_energy_kwh=float(optimized_energy_map.get("mechanical_braking_energy_kwh", 0.0)),
            baseline_regenerative_energy_kwh=baseline_regen,
            optimized_regenerative_energy_kwh=optimized_regen,
            baseline_soc_end=float(b_eco.get("soc_end", 0.0)),
            optimized_soc_end=float(o_eco.get("soc_end", 0.0)),
            energy_saving_kwh=saving,
            energy_saving_percent=(
                100.0 * saving / (
                    abs(baseline_energy)
                    if abs(baseline_energy) >= 1.0
                    else (baseline_traction if baseline_traction >= 1.0 else 1.0)
                )
                if saving is not None and (abs(baseline_energy) > 1e-12 or baseline_traction > 1e-12)
                else None
            ),
            runtime_constraint_feasible=bool(optimized.metadata.get("feasible_candidate", False)),
            optimized_constraint_violations="; ".join(str(item) for item in violations),
            controller_name=comparison.controller_name,
            data_status=request.data_status,
            comparison_feasible=comparison_feasible,
        ))
    if out_dir is None:
        return records, None
    paths = write_output_records(records, out_dir, {
        "schema_version": "1.0",
        "source": "重空协同项目的共享铁路数据（只读引用）",
        "request": audit,
        "route": {"start_km": start_km, "end_km": end_km},
        "eco_dt_s": eco_dt,
        "regenerative_dt_s": regen_dt,
        "disclaimer": "仿真结果，不作为工程结论",
    })
    return records, paths
