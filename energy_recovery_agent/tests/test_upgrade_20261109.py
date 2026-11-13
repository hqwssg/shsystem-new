from pathlib import Path
from uuid import uuid4
import csv
import io
import json
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from database.dataset_projection import project_dataset
from database.result_projection import project_result_directory
from database.snapshots import collect_file_records, record_from_bytes
from database.worker import bind_database_storage_parameters
from database.mysql import SimulationRepository
from data_ingestion import load_real_data_bundle


def test_new_shared_facts_project_without_inventing_storage_devices():
    result = project_dataset(uuid4(), ROOT / 'data/real_shuohuang')
    assert next(t for t in result['train_types'] if t['train_type_code'] == 'Heavy')['mass_t'] == 22100
    assert not result['storage_devices']


def test_flexible_facility_can_run_with_frozen_aggregate_assumption():
    records = collect_file_records(ROOT / 'data/real_shuohuang')
    bound = bind_database_storage_parameters(records, [])
    assert {r.relative_path: r.content_sha256 for r in bound} == {r.relative_path: r.content_sha256 for r in records}
    assert not any(r.relative_path == 'storage_devices.json' for r in bound)
    with pytest.raises(ValueError, match='没有'):
        bind_database_storage_parameters([], [])


def test_missing_real_device_inventory_still_blocks():
    records = (
        record_from_bytes('power_arm_intervals.csv', b'power_arm_id,storage_section_id\nA,real-storage\n'),
        record_from_bytes('energy_transfer_zones.csv', b'zone_id,implementation_status\nF,implemented\n'),
        record_from_bytes('battery.json', b'{}'),
    )
    with pytest.raises(ValueError, match='没有'):
        bind_database_storage_parameters(records, [])


def test_empty_database_inventory_reaches_facility_binding_validation():
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): pass
        def fetchall(self): return []
    class Connection:
        def cursor(self): return Cursor()
    devices = SimulationRepository(Connection()).load_storage_device_parameters(uuid4())
    assert devices == ()
    records = collect_file_records(ROOT / 'data/real_shuohuang')
    assert bind_database_storage_parameters(records, devices) == records
    with pytest.raises(ValueError, match='没有'):
        bind_database_storage_parameters([], devices)


def test_curve_bank_uses_each_frozen_input_not_installation_defaults(tmp_path):
    folder = tmp_path / 'input'
    shutil.copytree(ROOT / 'data/real_shuohuang', folder)
    before = load_real_data_bundle(folder).trains['Heavy'].mass_tons
    curve = folder / 'locomotive_curves.json'
    payload = json.loads(curve.read_text('utf-8'))
    payload['locomotives']['SHENHUA_12']['params']['computed_mass_t'] += 100
    curve.write_text(json.dumps(payload), encoding='utf-8')
    assert load_real_data_bundle(folder).trains['Heavy'].mass_tons == before + 100
    curve.unlink()
    with pytest.raises(ValueError, match='locomotive_curves'):
        load_real_data_bundle(folder)


def test_infeasible_decision_and_interval_diagnostics_survive_projection(tmp_path):
    (tmp_path / 'optimizer_summary.json').write_text(json.dumps({
        'optimization_decision': {'action': 'no_feasible_solution', 'reason': 'baseline_infeasible',
                                  'selected_candidate_id': None, 'grid_improvement_kwh': None},
        'headway_preflight': {'blocking_pair_count': 1},
    }), encoding='utf-8')
    (tmp_path / 'resource_conflicts.csv').write_text('location_km,message\n1.0-2.0 km,conflict\n', encoding='utf-8')
    result = project_result_directory(uuid4(), tmp_path)
    assert result['decision']['action'] == 'no_feasible_solution'
    assert result['decision']['selected_candidate_id'] is None
    assert result['decision']['grid_improvement_kwh'] is None
    assert result['resource_conflicts'][0]['location_km'] is None
    assert '1.0-2.0 km' in result['resource_conflicts'][0]['message']
