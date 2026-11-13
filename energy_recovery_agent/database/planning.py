"""Version-bound storage planning validation and transactional result inserts."""
from pathlib import Path
from tempfile import TemporaryDirectory

from storage_planning_contract import (
    CONTRACT_FILE_NAMES, load_storage_planning_bundle,
    validate_storage_planning_power_arm_references,
)
from .file_names import records_to_algorithm_names, to_algorithm_path
from .snapshots import materialize_file_records, record_from_bytes


def has_planning_data(root):
    return any((Path(root) / name).is_file() for name in CONTRACT_FILE_NAMES)


def validate_planning_directory(root, parameters=None, *, check_codes=True, power_arm_path=None):
    root = Path(root)
    missing = [name for name in CONTRACT_FILE_NAMES if not (root / name).is_file()]
    if missing:
        raise ValueError("储能规划数据不完整，请补齐：" + "、".join(missing))
    bundle = load_storage_planning_bundle(root)
    codes = [bundle.policy.policy_code, bundle.scenario_set_code]
    codes += [item.site_code for item in bundle.sites] + [item.technology_code for item in bundle.technologies] + [item.scenario_code for item in bundle.scenarios]
    if any(len(code) > 128 for code in codes):
        raise ValueError('规划编码长度不能超过128字符。')
    validate_storage_planning_power_arm_references(bundle, power_arm_path or root / 'power_arm_intervals.csv')
    if bundle.policy.allow_timetable_coordination:
        raise ValueError("储能规划仅支持固定运行图，请关闭运行图协同规划。")
    if parameters is not None and check_codes:
        if parameters.get('planning_policy_code') != bundle.policy.policy_code:
            raise ValueError("策略编码与所选版本不一致，请重新选择版本中的策略。")
        if parameters.get('scenario_set_code') != bundle.scenario_set_code:
            raise ValueError("场景集编码与所选版本不一致，请重新选择版本中的场景集。")
    return bundle


def normalized_planning_records(records):
    """Chinese logical timetable references resolve to frozen algorithm file names."""
    import json
    result = []
    for record in records_to_algorithm_names(records):
        if record.relative_path == 'storage_planning_scenarios.json':
            payload = json.loads(record.content.decode('utf-8-sig'))
            for scenario in payload.get('scenarios', []):
                if scenario.get('timetable_relative_path'):
                    scenario['timetable_relative_path'] = to_algorithm_path(scenario['timetable_relative_path'])
            record = record_from_bytes(record.relative_path, json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        result.append(record)
    return tuple(result)


def validate_planning_records(records, parameters=None):
    with TemporaryDirectory(prefix='planning-contract-') as folder:
        materialize_file_records(normalized_planning_records(records), Path(folder))
        return validate_planning_directory(folder, parameters)


def planning_preset(records):
    try:
        bundle = validate_planning_records(records)
        return {'planningReady': True, 'planningIssues': [],
                'planningPolicyOptions': [{'code': bundle.policy.policy_code, 'label': bundle.policy.policy_code}],
                'scenarioSetOptions': [{'code': bundle.scenario_set_code, 'label': bundle.scenario_set_code}]}
    except (ValueError, OSError) as exc:
        return {'planningReady': False, 'planningIssues': [str(exc)],
                'planningPolicyOptions': [], 'scenarioSetOptions': []}


def insert_planning_results(cursor, run_id, projection):
    from .mysql import _insert_many
    specs = (
        ('storage_plans', 'energy_storage_plan', ('storage_plan_id', 'run_id', 'source_plan_code', 'rank', 'selected', 'feasible', 'within_budget', 'meets_business_thresholds', 'site_count', 'site_codes', 'total_capacity_kwh', 'total_charge_power_kw', 'total_discharge_power_kw', 'capex_cny', 'annual_total_cost_cny', 'annual_saving_vs_no_build_cny', 'grid_reduction_vs_no_build_kwh_per_year', 'rejection_reasons', 'metrics_json'), 'metrics'),
        ('storage_plan_devices', 'energy_storage_plan_device', ('storage_plan_id', 'device_index', 'site_code', 'technology_code', 'capacity_kwh', 'charge_power_kw', 'discharge_power_kw', 'capex_cny', 'device_json'), 'device'),
        ('storage_plan_scenarios', 'energy_storage_plan_scenario_result', ('storage_plan_id', 'scenario_code', 'core_for_feasibility', 'feasible', 'grid_kwh', 'wasted_kwh', 'storage_charge_kwh', 'storage_discharge_kwh', 'final_soc_kwh', 'annual_operating_cost_cny', 'result_json'), 'result'),
    )
    for key, table, columns, json_key in specs:
        rows = []
        for source in projection.get(key, []):
            row = dict(source, run_id=run_id)
            row[json_key + '_json'] = row.pop(json_key)
            rows.append(row)
        _insert_many(cursor, table, columns, rows, json_columns=(json_key + '_json',))
    decision = projection.get('storage_plan_decision')
    if decision:
        if decision['decision'] not in {'recommend_build', 'keep_no_build', 'no_feasible_plan'}:
            raise ValueError('储能规划决策不在合同枚举中。')
        columns = ('run_id', 'decision', 'selected_storage_plan_id', 'best_build_storage_plan_id', 'decision_reason', 'recommendation_level', 'formal_engineering_conclusion_allowed', 'complete_for_declared_domain', 'decision_json')
        _insert_many(cursor, 'energy_storage_plan_decision', columns, [dict(decision, run_id=run_id)], json_columns=('decision_json',))
