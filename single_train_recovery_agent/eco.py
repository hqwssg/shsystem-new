"""Eco-driving jobs on the existing immutable versions, cases and artifacts."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid5
import csv
import io
import math
import tempfile

import numpy as np

from .core import (SIMULATION_DT, DISCLAIMER, algorithm_shared_files, materialize,
                   load_component_bundle, decode_files, dumps)
from eco_driving.io.data_loader import load_eco_driving_data
from eco_driving.models import EcoDrivingScenario, RunConstraints
from eco_driving.optimizer.baseline import run_baseline
from eco_driving.optimizer.eco_driving_optimizer import EcoDrivingOptimizer
from eco_driving.integration.regenerative_interface import evaluate_regenerative_recovery
from eco_driving.io.profile_writer import write_profile_csv
from regenerative_braking.simulation.closed_loop import build_closed_loop_controller
from regenerative_braking.simulation.regenerative_simulator import SimulationConfig
from regenerative_braking.validation.energy_gap import physical_gate

FIELDS = {
    'runtime_s': ['运行时间（s）', '轨迹实际运行时间'],
    'traction_energy_kwh': ['牵引能耗（kWh）', '纵向动力学牵引能耗'],
    'section_net_energy_kwh': ['区段净能耗（kWh）', '牵引能耗减去扣除电网回吸的净再生回收'],
    'trajectory_feasible': ['轨迹约束通过', '终点、末速度、运行时分及线路限速约束'],
    'constraint_violations': ['轨迹约束说明', '未通过的轨迹约束'],
}


def validate_parameters(parameters):
    allowed = {'trainName', 'routeStartKm', 'routeEndKm', 'initialSpeedKmh',
               'terminalSpeedKmh', 'targetRuntimeS', 'initialSoc'}
    if not isinstance(parameters, dict) or set(parameters) - allowed:
        raise ValueError('节能操纵只接受列车、区段、速度、运行时间和初始电量')
    if parameters.get('trainName', 'Heavy') not in ('Heavy', 'Empty'):
        raise ValueError('请选择重车或空车')
    for key in allowed - {'trainName'}:
        value = parameters.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(key + '必须填写有限数值')
    if not 0 <= parameters['routeStartKm'] < parameters['routeEndKm']:
        raise ValueError('终点里程必须大于起点里程')
    if not 0 <= parameters['initialSpeedKmh'] <= 80 or not 0 <= parameters['terminalSpeedKmh'] <= 80:
        raise ValueError('速度需在0～80 km/h之间')
    if not 0 < parameters['targetRuntimeS'] <= 195:
        raise ValueError('单次精细电气仿真运行时间需在0～195秒之间，请选择较短区段')
    if not 0 <= parameters['initialSoc'] <= 1:
        raise ValueError('初始电量需在0～100%之间')


@contextmanager
def inputs(snapshot, parameters):
    validate_parameters(parameters)
    validate_train(snapshot, parameters.get('trainName', 'Heavy'))
    with tempfile.TemporaryDirectory(prefix='single_eco_') as directory:
        paths = materialize(algorithm_shared_files(snapshot), Path(directory))
        data = load_eco_driving_data(parameters.get('trainName', 'Heavy'), paths)
        start, end = parameters['routeStartKm'], parameters['routeEndKm']
        if not data.railway.segments[0].start_km <= start < end <= data.railway.segments[-1].end_km:
            raise ValueError('起止里程超出当前数据版本的线路范围')
        bundle = load_component_bundle(paths)
        if not bundle.storage_params.soc_min <= parameters['initialSoc'] <= bundle.storage_params.soc_max:
            raise ValueError('初始电量超出当前储能允许范围')
        bundle = replace(bundle, train=data.train, storage_params=replace(
            bundle.storage_params, soc_initial=parameters['initialSoc']))
        scenario = EcoDrivingScenario(start, end, parameters['initialSpeedKmh'] / 3.6,
            constraints=RunConstraints(target_runtime_s=parameters['targetRuntimeS'],
                terminal_speed_mps=parameters['terminalSpeedKmh'] / 3.6),
            data_status=data.train.data_status, description='节能操纵区段')
        yield data, bundle, scenario


def preset(snapshot):
    # Read frozen geometry, never replace an existing version's files or parameters.
    with tempfile.TemporaryDirectory(prefix='eco_preset_') as directory:
        paths = materialize(algorithm_shared_files(snapshot), Path(directory))
        validate_train(snapshot, 'Heavy')
        data = load_eco_driving_data(paths=paths)
        first, last = data.railway.segments[0].start_km, data.railway.segments[-1].end_km
        start = min(max(108.0, first), max(first, last - .2))
        return {'minKm': first, 'maxKm': last, 'routeStartKm': start,
                'routeEndKm': min(last, start + .2), 'targetRuntimeS': 40.0,
                'initialSpeedKmh': 36.0, 'terminalSpeedKmh': 0.0}


def validate_train(snapshot, name):
    # Older frozen versions deliberately omitted these columns. Never use the
    # legacy geometry reader's zero placeholders as real dynamics inputs.
    rows = csv.DictReader(io.StringIO(decode_files(snapshot['files'])['trains.csv'].decode('utf-8-sig')))
    row = next((r for r in rows if r.get('name') == name), None)
    required = ('max_traction_kN', 'max_brake_kN', 'davis_a', 'davis_b', 'davis_c')
    for field in required:
        try:
            value = float(row[field])
            if not math.isfinite(value) or value < 0 or (field in required[:2] and value == 0):
                raise ValueError()
        except (TypeError, KeyError, ValueError):
            raise ValueError('当前版本缺少' + name + '的有效牵引、制动或阻力数据；请从完整来源派生新版本后使用节能驾驶') from None


def solve(repo, row, snapshot, parameters, check, root):
    from .worker import add_artifact, finite_json
    run_id = row['run_id']
    with inputs(snapshot, parameters) as (data, bundle, scenario):
        check(True)
        baseline = run_baseline(scenario, data.railway, data.train, dt=1., traction_limit_n=data.traction_limit_n)
        optimized = EcoDrivingOptimizer(data.railway, data.train, data.traction_limit_n,
            dt=1., beam_width=60).optimize(scenario, check=check)
        rows = []
        for key, label, profile in [('baseline', '经验操纵', baseline), ('optimized', '优化操纵', optimized)]:
            check(True)
            repo.write('UPDATE single_run SET current_case=%s WHERE run_id=%s', (label, run_id))
            if profile.runtime_s > 200:
                raise ValueError('轨迹超过200万步精细电气仿真上限，请缩短区段')
            controller = build_closed_loop_controller(limits=bundle.converter_params.duty_limits,
                converter_params=bundle.converter_params, storage_params=bundle.storage_params,
                sample_time_s=SIMULATION_DT)
            evaluation = evaluate_regenerative_recovery(profile, bundle=bundle, controller=controller,
                config=SimulationConfig(dt=SIMULATION_DT, record_stride=1), start_km=scenario.start_km, check=check)
            simulation = evaluation.simulation
            gate = physical_gate(simulation, bundle)
            ledger = simulation.ledger.to_dict(kwh=True)
            closure = abs(simulation.ledger.closure_residual_j) / max(1., simulation.ledger.mechanical_braking_energy_j)
            trajectory_ok = bool(profile.metadata.get('feasible_candidate', False))
            eligible = trajectory_ok and not gate['physical_violation'] and closure <= 1e-4
            energy = profile.metadata.get('energy') or {}
            traction = float(energy['traction_energy_kwh'])
            metrics = finite_json({**ledger, 'runtime_s': profile.runtime_s,
                'trajectory_feasible': trajectory_ok, 'constraint_violations': profile.metadata.get('constraint_violations', []),
                'traction_energy_kwh': traction,
                'section_net_energy_kwh': traction - float(ledger['storage_net_of_grid_import_energy_kWh']),
                'physical_violation': gate['physical_violation'], 'violation_reasons': gate['violation_reasons'],
                'closure_relative_residual': float(closure), 'closure_failure': closure > 1e-4,
                'simulation_dt_s': SIMULATION_DT, 'metric_schema_version': '2026.11.12',
                'soc_final': float(simulation.arrays.soc[-1])})
            metrics['output_voltage_peak_v'] = float(np.max(simulation.arrays.output_voltage_v))
            metrics['inductor_current_peak_a'] = float(np.max(np.abs(simulation.arrays.inductor_current_a)))
            case_id = str(uuid5(UUID(run_id), 'eco_driving|' + key))
            columns = simulation.arrays.to_columns()
            times = np.array([p.time_s for p in profile.samples])
            columns['speed_mps'] = np.interp(columns['time_s'], times, [p.speed_mps for p in profile.samples])
            columns['position_m'] = np.interp(columns['time_s'], times, [p.position_m for p in profile.samples])
            trace = root / (case_id + '.npz'); np.savez_compressed(trace, **columns)
            csv_path = write_profile_csv(profile, root / (label + '轨迹.csv'))
            check(True)
            with repo.atomic():
                repo.write("INSERT INTO single_case(case_id,run_id,scenario_key,scenario_name,controller_key,controller_name,status,eligible,metrics_json,audit_json) VALUES(%s,%s,%s,%s,%s,%s,'completed',%s,%s,%s)",
                    (case_id, run_id, 'eco_driving', '节能操纵', key, label, int(eligible), dumps(metrics),
                     dumps(finite_json({'physicalGate': gate, 'trajectory': profile.metadata, 'disclaimer': DISCLAIMER}))))
                add_artifact(repo, run_id, case_id, trace, 'npz')
                add_artifact(repo, run_id, case_id, csv_path, 'csv')
                repo.write('UPDATE single_run SET completed_cases=completed_cases+1 WHERE run_id=%s', (run_id,))
            rows.append({'方案': label, '运行时间(s)': metrics['runtime_s'], '牵引能耗(kWh)': traction,
                         '净再生回收(kWh)': ledger['storage_net_of_grid_import_energy_kWh'],
                         '区段净能耗(kWh)': metrics['section_net_energy_kwh'], '比较资格': eligible})
            del evaluation, simulation, columns
        summary = {'rows': rows, 'comparisonFeasible': all(r['比较资格'] for r in rows),
                   'energySavingKwh': rows[0]['区段净能耗(kWh)'] - rows[1]['区段净能耗(kWh)'] if all(r['比较资格'] for r in rows) else None,
                   'recoveryBasis': 'storage_net_of_grid_import_energy_kWh', 'disclaimer': DISCLAIMER}
        for filename, kind in [('节能操纵对比.csv', 'csv'), ('节能操纵对比.json', 'manifest')]:
            path = root / filename
            if kind == 'csv':
                with path.open('w', encoding='utf-8-sig', newline='') as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
            else:
                path.write_bytes(dumps(summary).encode('utf8'))
            add_artifact(repo, run_id, None, path, kind)
