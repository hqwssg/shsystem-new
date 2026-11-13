"""受扰实验的逐案例检查点、源文件摘要与完整物理门禁归档。"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

import numpy as np

from ..simulation.regenerative_simulator import SimulationConfig
from ..simulation.scenario_runner import build_simulator
from .energy_gap import phase_energies, phase_labels, physical_gate

ROOT = Path(__file__).resolve().parents[2]


def source_signature(entry):
    files = [*sorted((ROOT / "regenerative_braking").rglob("*.py")), Path(entry),
             ROOT / "tools" / "evaluate_reference_allocation.py",
             *sorted((ROOT / "data" / "single_train").glob("*.json"))]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def series_digest(series):
    digest = hashlib.sha256()
    for sample in series.samples:
        digest.update(json.dumps(asdict(sample), sort_keys=True).encode())
    return digest.hexdigest()


def plant_snapshot(bundle):
    return {name: asdict(getattr(bundle, name)) for name in ("train", "motor", "converter_params", "storage_params")}


def run_case(plant, series, controller, inner, *, ts, dt, scenario, candidate, trace, plant_update=None):
    result = build_simulator(plant).run(series, controller,
        SimulationConfig(dt=dt, control_period_s=ts, record_stride=1), plant_update=plant_update)
    gate = physical_gate(result, plant)
    ledger = result.ledger
    # 数值扰动可传播 NumPy 标量；JSON 边界使用原生 float/bool。
    closure = float(abs(ledger.closure_residual_j) / max(ledger.mechanical_braking_energy_j, 1.0))
    a = result.arrays
    row = dict(scenario=scenario, candidate=candidate, dt=dt, control_period_s=ts,
        integration_steps=len(series), control_updates=int(np.sum(a.control_update)),
        safety_overrides=int(np.sum(a.charge_safety_override)), **ledger.to_dict(),
        closure_relative_residual=closure, closure_failure=bool(closure > 1e-4),
        physical_violation=gate["physical_violation"], violation_reasons=",".join(gate["violation_reasons"]),
        output_voltage_peak_v=float(np.max(a.output_voltage_v)), inductor_current_peak_a=float(np.max(a.inductor_current_a)),
        control_effort_tv=result.to_scenario_metrics().to_flat_dict()["control_effort_tv"],
        negative_pwm_request_ratio=inner.nsmc.negative_pwm_request_steps / max(1, int(np.sum(a.control_update))))
    phases = phase_energies(result, phase_labels(series, a.mechanical_braking_power_w))
    np.savez_compressed(trace, **a.to_columns())
    return row, phases, dict(**gate, controller_audit=inner.audit()), result


def finish_archive(out, state, metadata):
    # 调用方 summary 可含公共字段；统一口径最后覆盖，避免重复关键字报错。
    payload = dict(metadata)
    payload.update(runs=len(state["rows"]), run_complete=True,
        code_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        code_worktree_dirty=bool(subprocess.check_output(["git", "status", "--porcelain", "--", "."], cwd=ROOT, text=True)),
        signature=state["signature"], physical_gates=state["gates"], trace_sha256=state["trace_sha256"],
        disclaimer="仿真结果，不作为工程结论")
    (out / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def checkpoint_case(out, state, row, phases, gate, trace):
    state["rows"].append(row)
    state["phases"].extend(dict(scenario=row["scenario"], candidate=row["candidate"], **r) for r in phases)
    state["gates"].append(dict(scenario=row["scenario"], candidate=row["candidate"], **gate))
    state["trace_sha256"][trace.name] = hashlib.sha256(trace.read_bytes()).hexdigest()
    path = out / "checkpoint.json"
    temporary = out / "checkpoint.tmp"
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
