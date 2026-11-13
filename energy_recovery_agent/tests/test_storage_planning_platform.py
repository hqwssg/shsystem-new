from pathlib import Path
from uuid import uuid4
import csv
import json
import shutil
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from database.snapshots import collect_file_records, materialize_file_records, record_from_bytes
from database.user_excel import export_version_tables, tables_to_overlays, convert_excel_files, _write_topic_workbook, _spec_by_code
from database.planning import validate_planning_records, planning_preset
from database.parameters import validate_run_parameters
from database.worker import build_algorithm_command
from database.solver_budget import build_solve_attempts
from storage_planning_contract import load_storage_planning_bundle
from storage_planning_mvp import run_storage_planning_mvp


def csv_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def csv_write(path, fields, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def tiny_case(path):
    # Freeze this regression's physical inputs; product defaults are independently versioned.
    shutil.copytree(ROOT / 'tests/fixtures/storage_planning_platform_legacy', path, dirs_exist_ok=True)
    shutil.copytree(ROOT / 'data_templates/storage_planning_example', path, dirs_exist_ok=True)
    train_fields, trains = csv_rows(path / 'trains.csv')
    if 'max_power_kW' not in train_fields:
        train_fields.append('max_power_kW')
        for train in trains:
            train['max_power_kW'] = '1000000000'
        csv_write(path / 'trains.csv', train_fields, trains)
    fields, sites = csv_rows(path / 'storage_candidate_sites.csv')
    site = sites[0]
    site['allowed_technology_codes'] = 'SYN-LFP'
    site['fixed_site_cost_cny'] = '0'
    csv_write(path / 'storage_candidate_sites.csv', fields, [site])
    fields, technologies = csv_rows(path / 'storage_technologies.csv')
    technology = next(row for row in technologies if row['technology_code'] == 'SYN-LFP')
    for field in ('fixed_device_cost_cny', 'cost_per_kwh_cny', 'charge_power_cost_per_kw_cny', 'discharge_power_cost_per_kw_cny', 'annual_om_rate', 'throughput_degradation_cost_per_kwh'):
        technology[field] = '0'
    csv_write(path / 'storage_technologies.csv', fields, [technology])
    fields, options = csv_rows(path / 'storage_site_technology_options.csv')
    csv_write(path / 'storage_site_technology_options.csv', fields, [next(row for row in options if row['site_code'] == site['site_code'] and row['technology_code'] == 'SYN-LFP')])
    scenarios = json.loads((path / 'storage_planning_scenarios.json').read_text(encoding='utf-8'))
    scenario = scenarios['scenarios'][0]
    scenario['weight'] = 1.0
    scenario['schedule_template'].update(heavy_count=1, empty_count=1)
    scenarios['scenarios'] = [scenario]
    (path / 'storage_planning_scenarios.json').write_text(json.dumps(scenarios), encoding='utf-8')
    policy = json.loads((path / 'storage_planning_policy.json').read_text(encoding='utf-8'))
    policy.update(max_site_count=1, max_wall_clock_s=120)
    (path / 'storage_planning_policy.json').write_text(json.dumps(policy), encoding='utf-8')
    return path


@pytest.fixture
def inputs(tmp_path):
    return tiny_case(tmp_path / 'inputs')


def codes(inputs):
    bundle = load_storage_planning_bundle(inputs)
    return {'planning_policy_code': bundle.policy.policy_code, 'scenario_set_code': bundle.scenario_set_code,
            'search_mode': 'coarse', 'max_levels_per_dimension': 2, 'settlement_step_s': 300}


def test_chinese_excel_and_browser_roundtrip(inputs, tmp_path):
    records = collect_file_records(inputs)
    tables = export_version_tables(records, 'storage_planning')['sheets']
    assert len(tables) == 6 and all('json' not in name.lower() for table in tables for name in table['columns'])
    baseline = {row.relative_path: row.content for row in records}
    overlays = tables_to_overlays('storage_planning', tables, baseline)
    new_records = [record_from_bytes(key, value) for key, value in {**baseline, **overlays}.items()]
    before, after = validate_planning_records(records), validate_planning_records(new_records)
    assert before.input_fingerprint_sha256 == after.input_fingerprint_sha256
    workbook = _write_topic_workbook(_spec_by_code('storage_planning'), {table['name']: table['rows'] for table in tables}, tmp_path / '储能规划.xlsx')
    excel = convert_excel_files([workbook], baseline)
    assert validate_planning_records([record_from_bytes(key, value) for key, value in {**baseline, **excel}.items()]).input_fingerprint_sha256 == before.input_fingerprint_sha256
    materialize_file_records(new_records, tmp_path / 'roundtrip')
    assert load_storage_planning_bundle(tmp_path / 'roundtrip').scenario_set_code == before.scenario_set_code


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'technology', 'arm', 'range', 'weight', 'timetable'])
def test_invalid_planning_inputs_block_publish_and_enqueue(inputs, fault):
    if fault == 'missing':
        (inputs / 'storage_technologies.csv').unlink()
    elif fault in {'duplicate', 'technology', 'arm', 'range'}:
        fields, rows = csv_rows(inputs / 'storage_candidate_sites.csv')
        if fault == 'duplicate': rows.append(dict(rows[0]))
        if fault == 'technology': rows[0]['allowed_technology_codes'] = 'DOES_NOT_EXIST'
        if fault == 'arm': rows[0]['power_arm_code'] = 'DOES_NOT_EXIST'
        if fault == 'range': rows[0]['storage_section_end_km'] = '-1'
        csv_write(inputs / 'storage_candidate_sites.csv', fields, rows)
    else:
        path = inputs / 'storage_planning_scenarios.json'
        payload = json.loads(path.read_text(encoding='utf-8'))
        if fault == 'weight': payload['scenarios'][0]['weight'] = .2
        if fault == 'timetable':
            payload['scenarios'][0].pop('schedule_template')
            payload['scenarios'][0]['timetable_relative_path'] = 'platform/不存在.csv'
        path.write_text(json.dumps(payload), encoding='utf-8')
    records = collect_file_records(inputs)
    assert not planning_preset(records)['planningReady']
    with pytest.raises(ValueError): validate_planning_records(records)
    from database.mysql import project_dataset_records
    with pytest.raises(ValueError): project_dataset_records(uuid4(), records)


@pytest.mark.parametrize('override', [{'planning_policy_code':'bad'}, {'scenario_set_code':'bad'}])
def test_version_code_mismatch(inputs, override):
    with pytest.raises(ValueError): validate_planning_records(collect_file_records(inputs), {**codes(inputs), **override})


@pytest.mark.parametrize('override', [{'search_mode':'bad'}, {'max_levels_per_dimension':1}, {'settlement_step_s':float('nan')}, {'refinement_shortlist_size':1.5}, {'unknown':1}])
def test_parameter_validation(inputs, override):
    with pytest.raises(ValueError): validate_run_parameters('storage_planning', {**codes(inputs), **override})


def test_chinese_timetable_reference(inputs):
    (inputs / 'platform').mkdir(exist_ok=True)
    (inputs / 'platform/运行图.xlsx').write_bytes(b'path-resolution-only')
    path = inputs / 'storage_planning_scenarios.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['scenarios'][0].pop('schedule_template')
    payload['scenarios'][0]['timetable_relative_path'] = 'platform/运行图.xlsx'
    path.write_text(json.dumps(payload), encoding='utf-8')
    assert validate_planning_records(collect_file_records(inputs)).scenarios[0].timetable_relative_path == 'platform/running_diagram.xlsx'


def test_planning_budget_has_no_fallback_and_whitelisted_command(inputs, tmp_path):
    for profile, timeout in [('quick',180),('standard',600),('fine',1200)]:
        attempts = build_solve_attempts('storage_planning', codes(inputs), profile)
        assert len(attempts) == 1 and attempts[0].wall_time_s == timeout and not attempts[0].parameter_overrides
    command = build_algorithm_command('storage_planning', codes(inputs), data_dir=inputs, output_dir=tmp_path/'out')
    assert 'plan-storage' in command and '--planning-policy-code' in command


def test_empty_unknown_duplicate_and_partial_online_sheets(inputs):
    records = collect_file_records(inputs)
    baseline = {record.relative_path: record.content for record in records}
    tables = export_version_tables(records, 'storage_planning')['sheets']
    policy = next(table for table in tables if table['name'] == '规划策略')
    # A partial online edit preserves the other five sheets from the same version.
    overlays = tables_to_overlays('storage_planning', [policy], baseline)
    assert validate_planning_records([record_from_bytes(key,value) for key,value in {**baseline, **overlays}.items()]).input_fingerprint_sha256 == validate_planning_records(records).input_fingerprint_sha256
    for invalid in ([{'name':'规划策略','rows':[]}], [policy, policy], [{'name':'未知表','rows':[]}], [{'name':'规划策略','rows':[{**policy['rows'][0], '未批准字段':'1'}]}]):
        with pytest.raises(ValueError): tables_to_overlays('storage_planning', invalid, baseline)


def test_multi_technology_and_flattened_scenario_roundtrip(inputs):
    # Restore the complete upstream planning example with several allowed technologies.
    shutil.copytree(ROOT / 'data_templates/storage_planning_example', inputs, dirs_exist_ok=True)
    path = inputs / 'storage_planning_scenarios.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['scenarios'][0]['parameter_overrides'] = {'heavy_mass_factor':1.01, 'storage_power_factor':.9}
    payload['scenarios'][0]['storage_outage_site_codes'] = ['SYN-SITE-145']
    path.write_text(json.dumps(payload), encoding='utf-8')
    records = collect_file_records(inputs)
    baseline = {record.relative_path: record.content for record in records}
    tables = export_version_tables(records, 'storage_planning')['sheets']
    overlays = tables_to_overlays('storage_planning', tables, baseline)
    assert validate_planning_records([record_from_bytes(key,value) for key,value in {**baseline, **overlays}.items()]).input_fingerprint_sha256 == validate_planning_records(records).input_fingerprint_sha256


@pytest.mark.parametrize('mode,expected', [('build','recommend_build'),('no_build','keep_no_build'),('infeasible','no_feasible_plan'),('partial',None)])
def test_real_small_planning_decisions_and_projections(inputs, tmp_path, mode, expected):
    path = inputs / 'storage_planning_policy.json'
    policy = json.loads(path.read_text(encoding='utf-8'))
    if mode == 'build':
        # The updated braking model has no regen in the old K145 fixture arm.
        # Exercise a profitable construction using an actual regenerative arm, without lowering the benefit gates.
        fields, sites = csv_rows(inputs / 'storage_candidate_sites.csv')
        sites[0].update(position_km='300', storage_section_start_km='200.7', storage_section_end_km='594', power_arm_code='VPA-F-004')
        csv_write(inputs / 'storage_candidate_sites.csv', fields, sites)
        scenario_path = inputs / 'storage_planning_scenarios.json'
        scenarios = json.loads(scenario_path.read_text(encoding='utf-8'))
        # A following empty train consumes previously stored braking energy; no end-SOC constraint is relaxed.
        scenarios['scenarios'][0]['schedule_template']['heavy_empty_phase_s'] = 86400
        scenario_path.write_text(json.dumps(scenarios), encoding='utf-8')
    if mode == 'no_build': policy['minimum_annual_saving_cny'] = 10**12
    if mode == 'infeasible': policy.update(allow_no_build=False, total_budget_cny=0, minimum_annual_saving_cny=10**12)
    policy['max_wall_clock_s'] = 1 if mode == 'partial' else 120
    path.write_text(json.dumps(policy), encoding='utf-8')
    out = tmp_path / 'results'
    summary = run_storage_planning_mvp(inputs, inputs, out, settlement_step_s=300)
    if expected: assert summary['decision'] == expected
    assert summary['declared_search_domain']['complete_for_declared_domain'] is (mode != 'partial')
    from database.result_projection import project_result_directory
    projection = project_result_directory(uuid4(), out)
    assert projection['storage_plan_decision']['decision_json'] == json.loads((out / 'storage_planning_summary.json').read_text(encoding='utf-8'))
    assert len(projection['storage_plans']) == summary['declared_search_domain']['evaluated_plan_count']
    if mode == 'infeasible': assert not any(row['selected'] for row in projection['storage_plans'])
