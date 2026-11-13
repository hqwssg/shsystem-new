import copy
import json
from contextlib import nullcontext
from uuid import uuid4

import numpy as np
import pytest

from single_train_recovery_agent import ALGORITHM
from single_train_recovery_agent.core import compatible_facts, default_auxiliary_files, default_parameters, encode_files
from single_train_recovery_agent.eco import inputs, solve, validate_parameters, validate_train


@pytest.fixture
def snapshot():
    files = compatible_facts({p.name: p.read_bytes() for p in (ALGORITHM / 'data/shared').iterdir() if p.is_file()})
    files.update(default_auxiliary_files())
    return {'files': encode_files(files), 'parameters': default_parameters(files)}


def test_frozen_inputs_and_train_specific_dynamics(snapshot):
    before = copy.deepcopy(snapshot)
    params = dict(trainName='Heavy', routeStartKm=108., routeEndKm=108.005,
                  initialSpeedKmh=18., terminalSpeedKmh=18., targetRuntimeS=1., initialSoc=.5)
    with inputs(snapshot, params) as (data, bundle, scenario):
        assert data.traction_limit_n == 5_600_000
        assert bundle.train.mass_kg == 22_100_000
        assert bundle.train.resistance.a_n_per_kn == .92
        assert scenario.length_m == pytest.approx(5)
    with inputs(snapshot, {**params, 'trainName': 'Empty'}) as (data, bundle, scenario):
        assert data.traction_limit_n == 2_800_000
        assert bundle.train.mass_kg == 4_820_000
        assert bundle.train.resistance.a_n_per_kn == 2.23
    assert snapshot == before
    with pytest.raises(ValueError): validate_parameters({**params, 'initialSoc': float('nan')})
    with pytest.raises(ValueError): validate_parameters({**params, 'targetRuntimeS': 196})
    with pytest.raises(ValueError):
        with inputs(snapshot, {**params, 'routeEndKm': 1000}): pass
    legacy = {**snapshot, 'files': {**snapshot['files'], **encode_files({'trains.csv': b'name,mass_tons\nHeavy,21600\n'})}}
    with pytest.raises(ValueError, match='完整来源'): validate_train(legacy, 'Heavy')


def test_eco_job_runs_both_physics_and_archives(tmp_path, monkeypatch, snapshot):
    monkeypatch.setenv('SINGLE_TRAIN_RESULT_ROOT', str(tmp_path))
    run_id = str(uuid4())
    root = tmp_path / run_id
    root.mkdir()
    cases, artifacts = [], []

    class Repo:
        def atomic(self): return nullcontext()
        def write(self, sql, args=()):
            if sql.startswith('INSERT INTO single_case'): cases.append(args)
            if sql.startswith('INSERT INTO single_artifact'): artifacts.append(args)

    params = dict(trainName='Heavy', routeStartKm=108., routeEndKm=108.005,
                  initialSpeedKmh=18., terminalSpeedKmh=18., targetRuntimeS=1., initialSoc=.5)
    solve(Repo(), {'run_id': run_id}, snapshot, params, lambda force=False: None, root)
    assert len(cases) == 2
    assert {c[4] for c in cases} == {'baseline', 'optimized'}
    assert len(artifacts) == 6
    for case in cases:
        m = json.loads(case[7])
        assert np.isfinite(m['section_net_energy_kwh'])
        assert m['section_net_energy_kwh'] == pytest.approx(m['traction_energy_kwh'] - m['storage_net_of_grid_import_energy_kWh'])
        assert m['simulation_dt_s'] == 1e-4
    for artifact in artifacts:
        assert (root / artifact[3]).stat().st_size == artifact[5]
    summary = json.loads((root / '节能操纵对比.json').read_text('utf8'))
    assert len(summary['rows']) == 2
    assert summary['comparisonFeasible'] == all(bool(c[6]) for c in cases)
    with np.load(next(root.glob('*.npz')), allow_pickle=False) as data:
        assert len(data['speed_mps']) == len(data['time_s'])


def test_optimizer_checks_cancellation(snapshot):
    from eco_driving.optimizer.eco_driving_optimizer import EcoDrivingOptimizer
    params = dict(trainName='Heavy', routeStartKm=108., routeEndKm=108.005,
                  initialSpeedKmh=18., terminalSpeedKmh=18., targetRuntimeS=1., initialSoc=.5)
    def cancelled(): raise InterruptedError('cancelled')
    with inputs(snapshot, params) as (data, bundle, scenario):
        with pytest.raises(InterruptedError):
            EcoDrivingOptimizer(data.railway, data.train, data.traction_limit_n).optimize(scenario, check=cancelled)
