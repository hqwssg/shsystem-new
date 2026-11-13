"""Check the delivered algorithm through the platform's real adapter."""
import ast
from dataclasses import replace
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from single_train_recovery_agent import WORKSPACE
from single_train_recovery_agent.core import (
    SIMULATION_DT, compatible_facts, default_parameters, default_auxiliary_files,
    encode_files, scenarios_for, default_rolling_stock,
)
from single_train_recovery_agent.worker import run_physics
from regenerative_braking.validation.baselines import baseline_catalog
from regenerative_braking.validation.scenarios import _flat_window, ValidationScenario
from regenerative_braking.simulation.scenario_runner import build_simulator
from regenerative_braking.simulation.regenerative_simulator import SimulationConfig
from regenerative_braking.dynamics.storage_model import StorageSystem, StorageModelError


@pytest.fixture
def prepared():
    root = WORKSPACE / 'single_train_recovery_agent/data_templates/shared_fixture'
    files = compatible_facts({p.name: p.read_bytes() for p in root.iterdir() if p.is_file()})
    files.update(default_auxiliary_files())
    files = default_rolling_stock(files)
    params = default_parameters(files)
    temp, bundle, scenarios = scenarios_for({'files': encode_files(files), 'parameters': params},
        {'scenarioKeys': ['s1_flat_braking[nominal]']})
    try:
        yield bundle, scenarios
    finally:
        temp.cleanup()


def test_selected_scene_and_physics_match_upstream(prepared):
    bundle, scenarios = prepared
    assert len(scenarios) == 1
    assert scenarios[0].series.dt == SIMULATION_DT == 1e-4
    series = _flat_window(bundle.train, dt=SIMULATION_DT, v0_kmh=36, decel_mps2=.25,
                         window_s=.025, scenario_id='refresh', description='短窗口一致性检查')
    scenario = ValidationScenario('refresh', 'test', 'nominal', '一致性', series)
    baseline = next(b for b in baseline_catalog() if b.is_optimized)
    result, metrics, audit, eligible = run_physics(bundle, scenario, baseline)
    original = build_simulator(bundle).run(series, baseline.controller(bundle, sample_time_s=SIMULATION_DT),
        SimulationConfig(dt=SIMULATION_DT, control_period_s=SIMULATION_DT, record_stride=1))
    assert result.ledger.to_dict() == original.ledger.to_dict()
    for key, value in result.arrays.to_columns().items():
        np.testing.assert_array_equal(value, original.arrays.to_columns()[key])
    assert metrics['simulation_dt_s'] == metrics['control_period_s'] == 1e-4
    assert 'physicalGate' in audit


def test_storage_port_limit_accounts_for_efficiency(prepared):
    bundle, _ = prepared
    params = replace(bundle.storage_params, capacity_j=1000, soc_initial=.899,
        soc_max=.9, charge_efficiency=.8, max_charge_power_w=100)
    storage = StorageSystem(params)
    assert storage.available_charge_power_w(1) == pytest.approx(1.25)
    with pytest.raises(StorageModelError):
        storage.available_charge_power_w(0)


def test_linux_font_fallback_and_existing_planning_flags(monkeypatch):
    root = WORKSPACE / 'energy_recovery_agent'
    for name in ('energy_settlement.py', 'run_dispatch_case.py'):
        tree = ast.parse((root / name).read_text('utf-8'))
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and
                   n.func.id == 'configure_matplotlib_chinese_font' for n in ast.walk(tree))
    spec = importlib.util.spec_from_file_location('font_config', root / 'matplotlib_chinese_font.py')
    font_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(font_config)
    assert 'Noto Sans CJK SC' in font_config.PREFERRED_CJK_FONTS
    spec = importlib.util.spec_from_file_location('refresh_cli', root / 'run_project.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = module.build_parser().parse_args(['plan-storage',
        '--planning-policy-code', 'policy', '--scenario-set-code', 'scenarios'])
    assert args.planning_policy_code == 'policy'
    assert args.scenario_set_code == 'scenarios'
    assert args.settlement_step_s == 60
