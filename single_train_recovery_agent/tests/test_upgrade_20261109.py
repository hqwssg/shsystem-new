import copy
from pathlib import Path

import numpy as np
import pytest

from single_train_recovery_agent import ALGORITHM
from single_train_recovery_agent.core import (
    compatible_facts, default_auxiliary_files, default_parameters, default_rolling_stock,
    encode_files, parameter_metadata, readiness, scenarios_for, SIMULATION_DT,
)
from single_train_recovery_agent.worker import run_physics
from regenerative_braking.validation.baselines import baseline_catalog
from regenerative_braking.validation.scenarios import ValidationScenario, _flat_window


@pytest.fixture
def snapshot():
    files = compatible_facts({p.name: p.read_bytes() for p in (ALGORITHM / 'data/shared').iterdir() if p.is_file()})
    files.update(default_auxiliary_files())
    files = default_rolling_stock(files)
    return {'files': encode_files(files), 'parameters': default_parameters(files)}


def test_snapshot_freezes_new_curve_and_combined_mass(snapshot):
    before = copy.deepcopy(snapshot)
    assert readiness(snapshot)['ready']
    temp, bundle, scenarios = scenarios_for(snapshot, {'scenarioKeys': ['s1_flat_braking[nominal]']})
    try:
        assert bundle.train.mass_kg == 22_100_000
        assert bundle.motor.max_regen_power_w == 24_000_000
        assert len(scenarios) == 1
        assert len(scenarios[0].series) == 80_000
        assert sum(len(rows) for rows in parameter_metadata(snapshot['parameters']).values()) == 64
        for topic,field in [('train','max_regen_force_n'),('motor','max_regen_force_n'),('motor','max_regen_power_w'),('dc_dc','power_rating_w')]:
            assert snapshot['parameters'][topic]['field_data_status'][field] == 'derived'
            assert '本字段登记的是 1 台口径' not in snapshot['parameters'][topic]['provenance'][field]
            assert '冻结' in snapshot['parameters'][topic]['provenance'][field]
        assert snapshot == before
    finally:
        temp.cleanup()


def test_old_snapshot_requires_explicit_upgrade(snapshot):
    del snapshot['files']['locomotive_curves.json']
    before = copy.deepcopy(snapshot)
    state = readiness(snapshot)
    assert not state['ready']
    assert 'locomotive_curves.json' in state['missing']
    assert snapshot == before


def test_all_scenarios_and_selected_route_reference(snapshot):
    temp, bundle, scenarios = scenarios_for(snapshot, {})
    try:
        assert len(scenarios) == 14
        assert len({s.label for s in scenarios}) == 14
        route = next(s for s in scenarios if s.scenario_id == 'sR_route_braking')
        assert 'reference_section_distance_km' in route.reference
    finally:
        temp.cleanup()


@pytest.mark.parametrize('baseline_key', [b.label for b in baseline_catalog()])
def test_each_controller_runs_with_new_metrics(snapshot, baseline_key):
    temp, bundle, _ = scenarios_for(snapshot, {'scenarioKeys': ['s1_flat_braking[nominal]']})
    try:
        series = _flat_window(bundle.train, dt=SIMULATION_DT, v0_kmh=36,
                              decel_mps2=.25, window_s=.02, scenario_id='short', description='短窗口接入检查')
        scenario = ValidationScenario('short', 'test', 'nominal', '接入检查', series)
        baseline = next(b for b in baseline_catalog() if b.label == baseline_key)
        result, metrics, audit, eligible = run_physics(bundle, scenario, baseline)
        assert metrics['metric_schema_version'] == '2026.11.08'
        assert metrics['simulation_dt_s'] == 1e-4
        assert np.isfinite(metrics['storage_net_of_grid_import_energy_kWh'])
        assert 'parameterStatus' in audit
        assert all(np.isfinite(values).all() for values in result.arrays.to_columns().values())
    finally:
        temp.cleanup()
