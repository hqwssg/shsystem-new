"""固定被控对象的阶段能量差距诊断；能量积分须使用全部样本。"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from ..simulation.profiles import ProfileSeries
from ..simulation.regenerative_simulator import SimulationResult
from ..simulation.scenario_runner import ComponentBundle
from ..metrics import energy_accounting

EXCLUDED_BASELINES = frozenset(("ideal_upper_bound", "no_storage_zero_duty", "rhonn_nsmc",
                                "rhonn_nsmc_fixed_ekf", "rhonn_nsmc_fixed_ukf"))
PHASES = ("startup", "power_transition", "sustained", "end_window", "brake_exit")


def phase_labels(
    series: ProfileSeries, mechanical_power: np.ndarray, *, startup_s: float = 0.1,
    transition_s: float = 0.05, end_window_s: float = 0.1,
) -> np.ndarray:
    """按外生剖面分段，控制器共用掩码；末尾窗口不等于真实制动退出。"""
    if not len(series) or mechanical_power.shape != (len(series),):
        raise ValueError("阶段掩码需要与剖面等长的功率序列")
    if not all(math.isfinite(v) and v >= 0 for v in (startup_s, transition_s, end_window_s)):
        raise ValueError("阶段窗口必须为非负有限值")
    times = np.array([s.time_s for s in series.samples])
    inputs = np.array([(s.acceleration_mps2, s.gradient_per_mille, s.brake_command)
                       for s in series.samples])
    # 线路阻力随速度平滑变化也会改变加速度。使用有单位的诊断阈值，
    # 避免把每个浮点变化都当阶跃；它们不参与控制器模式切换。
    thresholds = np.array((0.01, 0.25, 0.02))  # m/s²、‰、制动指令比例
    events = np.flatnonzero(np.any(np.abs(np.diff(inputs, axis=0)) > thresholds, axis=1)) + 1
    labels = np.full(len(series), "sustained", dtype="<U20")
    labels[times >= times[0] + series.duration_s - end_window_s - 1e-12] = "end_window"
    for event in events:
        stop = np.searchsorted(times, times[event] + transition_s - 1e-12)
        labels[event:stop] = "power_transition"
    labels[mechanical_power <= 1e-9] = "brake_exit"
    labels[times < times[0] + startup_s - 1e-12] = "startup"
    return labels


def physical_gate(result: SimulationResult, bundle: ComponentBundle) -> dict[str, Any]:
    """全分辨率检查输入/输出电压、电流、输入功率、SOC、实际 PWM 可行域。"""
    if result.config.record_stride != 1:
        raise ValueError("物理门禁必须使用 record_stride=1")
    a, p, s = result.arrays, bundle.converter_params, bundle.storage_params
    checks = {
        "input_voltage": (a.input_voltage_v, p.input_voltage_min_v, p.input_voltage_max_v),
        "output_voltage": (a.output_voltage_v, p.output_voltage_min_v, p.output_voltage_max_v),
        "inductor_current": (np.abs(a.inductor_current_a), 0.0, p.max_output_current_a),
        "output_current": (np.abs(a.output_current_a), 0.0, p.max_output_current_a),
        "input_current": (np.abs(a.input_current_a), 0.0, p.max_input_current_a),
        "input_power": (np.abs(a.motor_electrical_power_w), 0.0, p.power_rating_w),
        "soc": (np.r_[s.soc_initial, a.soc], s.soc_min, s.soc_max),
        "duty_T1": (a.duty_cycle_T1, *result.duty_bounds),
        "duty_T2": (a.duty_cycle_T2, *result.duty_bounds),
    }
    details = {}
    for name, (values, low, high) in checks.items():
        violations = (~np.isfinite(values)) | (values < low - 1e-9) | (values > high + 1e-9)
        details[name] = {"min": float(np.min(values)), "max": float(np.max(values)),
                         "lower_limit": low, "upper_limit": high,
                         "violation_steps": int(np.count_nonzero(violations))}
    reasons = [name for name, item in details.items() if item["violation_steps"]]
    return {"physical_violation": bool(reasons), "violation_reasons": reasons, "limits": details}


def phase_energies(result: SimulationResult, labels: np.ndarray) -> list[dict[str, Any]]:
    a, dt = result.arrays, result.config.dt
    if result.config.record_stride != 1 or labels.shape != a.time_s.shape:
        raise ValueError("阶段积分必须使用全分辨率并与标签等长")
    increments = {
        "mechanical_braking_energy_kWh": a.mechanical_braking_power_w * dt,
        "captured_energy_kWh": a.accepted_power_w * dt,
        "storage_energy_kWh": a.stored_energy_delta_j,
        "grid_import_energy_kWh": a.grid_import_power_w * dt,
        "grid_export_energy_kWh": a.grid_export_power_w * dt,
        "friction_braking_energy_kWh": a.friction_braking_power_w * dt,
        "motor_loss_energy_kWh": np.maximum(a.regen_wheel_power_w - a.motor_electrical_power_w, 0) * dt,
        "converter_loss_energy_kWh": a.converter_loss_power_w * dt,
        "converter_inductor_loss_energy_kWh": a.converter_inductor_loss_power_w * dt,
        "grid_source_loss_energy_kWh": a.grid_source_loss_w * dt,
        "storage_loss_energy_kWh": a.storage_loss_j,
        "curtailed_energy_kWh": a.curtailed_power_w * dt,
        "reactive_energy_delta_kWh": a.reactive_energy_delta_j,
    }
    if any(v.shape != labels.shape or not np.all(np.isfinite(v)) for v in increments.values()):
        raise ValueError("缺少全量阶段能量记录或记录含非有限值")
    ledger = result.ledger.to_dict()
    for key, values in increments.items():
        if not math.isclose(float(np.sum(values)) / 3.6e6, ledger[key], rel_tol=1e-9, abs_tol=1e-8):
            raise ValueError(f"阶段能量与 EnergyLedger 不一致：{key}")
    rows = []
    for phase in PHASES:
        mask = labels == phase
        row = {key: float(np.sum(values[mask])) / 3.6e6 for key, values in increments.items()}
        row.update(phase=phase, steps=int(np.count_nonzero(mask)), duration_s=int(np.count_nonzero(mask)) * dt)
        row["grid_net_export_energy_kWh"] = row["grid_export_energy_kWh"] - row["grid_import_energy_kWh"]
        row.update(energy_accounting(row))
        rows.append(row)
    return rows


def best_feasible_baseline(rows: Sequence[Mapping[str, Any]], objective: str) -> Mapping[str, Any] | None:
    eligible = [r for r in rows if r["baseline"] not in EXCLUDED_BASELINES
                and not r["physical_violation"] and not r["closure_failure"]]
    return min(eligible, key=lambda r: (-r[objective], r["baseline"])) if eligible else None
