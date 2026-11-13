"""Chinese business tables for the five upstream planning files (no JSON editing)."""
from pathlib import Path
import json
import re

SITES = dict(zip(('site_code','site_name','position_km','power_arm_code','storage_section_start_km','storage_section_end_km','direction','buildable','max_connection_power_kw','max_capacity_kwh','fixed_site_cost_cny','allowed_technology_codes','data_status','source_note'), ('站点编码','站点名称','里程km','供电臂编码','服务区段起点km','服务区段终点km','方向','允许建设','最大接入功率kW','最大容量kWh','场地固定投资元','允许技术编码','数据状态','来源说明')))
TECHNOLOGIES = dict(zip(('technology_code','technology_name','min_capacity_kwh','max_capacity_kwh','capacity_step_kwh','min_charge_power_kw','max_charge_power_kw','charge_power_step_kw','min_discharge_power_kw','max_discharge_power_kw','discharge_power_step_kw','charge_efficiency','discharge_efficiency','min_soc_ratio','max_soc_ratio','self_discharge_rate_per_hour','calendar_life_years','cycle_life','fixed_device_cost_cny','cost_per_kwh_cny','charge_power_cost_per_kw_cny','discharge_power_cost_per_kw_cny','annual_om_rate','throughput_degradation_cost_per_kwh','data_status','source_note'), ('技术编码','技术名称','最小容量kWh','最大容量kWh','容量档位步长kWh','最小充电功率kW','最大充电功率kW','充电功率档位步长kW','最小放电功率kW','最大放电功率kW','放电功率档位步长kW','充电效率','放电效率','最小荷电比例','最大荷电比例','每小时自放电率','日历寿命年','循环寿命次数','设备固定投资元','容量单价元每kWh','充电功率单价元每kW','放电功率单价元每kW','年运维费率','吞吐衰减成本元每kWh','数据状态','来源说明')))
OPTIONS = dict(zip(('site_code','technology_code','min_capacity_kwh','max_capacity_kwh','max_charge_power_kw','max_discharge_power_kw','max_unit_count','available','source_note'), ('站点编码','技术编码','最小容量kWh','最大容量kWh','最大充电功率kW','最大放电功率kW','最大设备数量','可用','来源说明')))
SET = {'scenario_set_code': '场景集编码'}
SCENARIOS = dict(zip(('scenario_code','scenario_name','weight','core_for_feasibility','timetable_relative_path','grid_price_per_kwh','demand_charge_per_kw_year','wasted_energy_penalty_per_kwh','storage_outage_site_codes','data_status','source_note'), ('场景编码','场景名称','场景权重','核心可行性场景','运行图文件','电价元每kWh','需量电价元每kW年','弃能惩罚元每kWh','故障站点编码','数据状态','来源说明')))
SCHEDULE = dict(zip(('heavy_count','empty_count','heavy_headway_s','empty_headway_s','heavy_empty_phase_s'), ('重车数量','空车数量','重车发车间隔秒','空车发车间隔秒','重空相位秒')))
OVERRIDES = dict(zip(('heavy_mass_factor','empty_mass_factor','traction_power_factor','brake_power_factor','davis_resistance_factor','storage_efficiency_factor','power_arm_capacity_factor','storage_power_factor'), ('重车质量倍率','空车质量倍率','牵引功率倍率','制动功率倍率','运行阻力倍率','储能效率倍率','供电臂容量倍率','储能功率倍率')))
POLICY = dict(zip(('policy_code','planning_horizon_years','discount_rate','analysis_days_per_year','max_site_count','total_budget_cny','allow_no_build','target_final_soc_rule','final_soc_tolerance_kwh','objective_mode','include_demand_charge','allow_timetable_coordination','coordination_shortlist_size','core_scenarios_must_all_be_feasible','risk_measure','cvar_alpha','minimum_grid_reduction_kwh','minimum_annual_saving_cny','solver_profile','max_wall_clock_s','seed','data_status','source_note'), ('策略编码','规划期年','折现率','年分析天数','最多建设站点数','总投资预算元','允许不建设','期末荷电规则','期末荷电容差kWh','规划目标','计入需量电费','运行图协同规划','协同候选数','核心场景全部可行','风险度量','风险置信度','最小年购电削减kWh','最小年节约元','求解资源档位','最大计算秒数','随机种子','数据状态','来源说明')))
TABLES = (
    ('候选站点', SITES, 'storage_candidate_sites.csv'),
    ('储能技术', TECHNOLOGIES, 'storage_technologies.csv'),
    ('站点技术配置', OPTIONS, 'storage_site_technology_options.csv'),
    ('场景集', SET, 'storage_planning_scenarios.json'),
    ('规划场景', {**SCENARIOS, **SCHEDULE, **OVERRIDES}, 'storage_planning_scenarios.json'),
    ('规划策略', POLICY, 'storage_planning_policy.json'),
)
BOOL = {'buildable','available','core_for_feasibility','allow_no_build','include_demand_charge','allow_timetable_coordination','core_scenarios_must_all_be_feasible'}
TEXT = {'site_code','site_name','power_arm_code','direction','technology_code','technology_name','scenario_code','scenario_name','scenario_set_code','timetable_relative_path','policy_code','target_final_soc_rule','objective_mode','risk_measure','solver_profile','data_status','source_note'}
OPTIONAL = {'capacity_step_kwh','charge_power_step_kw','discharge_power_step_kw','cvar_alpha'}
ENUMS = {
    'direction': {'正向':'forward','反向':'reverse','双向':'both'},
    'data_status': {'正式数据':'official','正式推导数据':'derived_from_official','规划占位数据':'planning_placeholder','样例数据':'synthetic'},
    'target_final_soc_rule': {'循环一致':'cyclic','不低于初值':'not_below_initial','偏差计价':'priced_deviation'},
    'objective_mode': {'年化成本':'annualized_cost','节能优先':'energy_first','均衡':'balanced'},
    'risk_measure': {'期望值':'expected','最坏场景':'worst_case','条件风险价值':'cvar'},
    'solver_profile': {'快速':'quick','标准':'standard','精细':'fine'},
}


def _parse(row, mapping, *, csv_mode=False):
    from .user_excel import ExcelConversionError
    result = {}
    for key, label in mapping.items():
        value = row.get(label, '')
        text = str(value if value is not None else '').strip()
        if key in ENUMS:
            value = ENUMS[key].get(text, text)
        elif key in BOOL:
            if text.lower() in {'是','true','1','允许'}:
                value = True
            elif text.lower() in {'否','false','0','不允许'}:
                value = False
            else:
                raise ExcelConversionError(f'{label}必须填是或否。')
            if csv_mode:
                value = 'true' if value else 'false'
        elif key in {'allowed_technology_codes','storage_outage_site_codes'}:
            codes = [x.strip() for x in re.split('[,，;；|]', text) if x.strip()]
            value = '|'.join(codes) if csv_mode else codes
        elif key in TEXT:
            value = text
        elif not text:
            value = '' if csv_mode else None
        else:
            try:
                value = float(text)
                if value.is_integer():
                    value = int(value)
            except (ValueError, OverflowError) as exc:
                raise ExcelConversionError(f'{label}必须是数值，不要填写单位。') from exc
        result[key] = value
    return result


def _display(row, mapping):
    result = {}
    for key, label in mapping.items():
        value = row.get(key)
        if key in ENUMS:
            value = {v:k for k,v in ENUMS[key].items()}.get(value, value)
        elif key in BOOL:
            value = '是' if value in (True, 'true', 'True', '1') else '否'
        elif isinstance(value, (tuple,list)):
            value = '，'.join(str(item) for item in value)
        elif key == 'allowed_technology_codes' and isinstance(value, str):
            value = value.replace('|', '，')
        result[label] = '' if value is None else str(value)
    return result


def export_tables(baseline):
    from .user_excel import _csv_maps, _sheet_document
    scenario_root = json.loads(baseline.get('storage_planning_scenarios.json', b'{}').decode('utf-8-sig'))
    policy = json.loads(baseline.get('storage_planning_policy.json', b'{}').decode('utf-8-sig'))
    tables = []
    for name, mapping, file in TABLES:
        if file.endswith('.csv'):
            rows = _csv_maps(baseline[file]) if file in baseline else []
        elif name == '场景集':
            rows = [scenario_root] if scenario_root.get('scenario_set_code') else []
        elif name == '规划策略':
            rows = [policy] if policy else []
        else:
            rows = [{**row, **(row.get('schedule_template') or {}), **row.get('parameter_overrides', {})} for row in scenario_root.get('scenarios', [])]
        tables.append(_sheet_document(name, tuple(mapping.values()), '编号保持唯一；空白数值表示未设置；编码列表用中文逗号分隔。', [_display(row, mapping) for row in rows]))
    return tables


def convert_rows(rows_by_sheet, baseline, *, preserve_empty=True):
    from .user_excel import _csv_bytes, _json_bytes, ExcelConversionError
    from .file_names import to_algorithm_path
    base_rows = {table['name']: table['rows'] for table in export_tables(baseline)}
    rows = dict(base_rows)
    for name, supplied in rows_by_sheet.items():
        if name not in base_rows:
            raise ExcelConversionError(f'未知储能规划工作表：{name}')
        columns = next(set(mapping.values()) for sheet, mapping, _ in TABLES if sheet == name)
        for row in supplied:
            unknown = set(row) - columns
            if unknown:
                raise ExcelConversionError(f'{name}包含未知字段：' + '、'.join(sorted(unknown)))
        if supplied or not preserve_empty:
            rows[name] = supplied
    if not any(rows.values()):
        return {}
    if len(rows['场景集']) != 1 or len(rows['规划策略']) != 1:
        raise ExcelConversionError('首版需要且仅支持一份规划策略、一个场景集。')
    for name in ('候选站点','储能技术','站点技术配置','规划场景'):
        if not rows[name]:
            raise ExcelConversionError(f'储能规划数据不完整：请补齐{name}。')
    files = {}
    for name, mapping, file in TABLES[:3]:
        parsed = [_parse(row, mapping, csv_mode=True) for row in rows[name]]
        files[file] = _csv_bytes(tuple(mapping), parsed)
    scenarios = []
    for row in rows['规划场景']:
        parsed = _parse(row, SCENARIOS)
        if parsed.get('timetable_relative_path'):
            parsed['timetable_relative_path'] = to_algorithm_path(parsed['timetable_relative_path'])
            if any(str(row.get(label, '')).strip() for label in SCHEDULE.values()):
                raise ExcelConversionError('运行图文件与重空发车模板不能同时填写。')
        else:
            parsed.pop('timetable_relative_path', None)
            parsed['schedule_template'] = _parse(row, SCHEDULE)
        parsed['parameter_overrides'] = {key:value for key,value in _parse(row, OVERRIDES).items() if value is not None}
        scenarios.append(parsed)
    scenario_set = _parse(rows['场景集'][0], SET)
    files['storage_planning_scenarios.json'] = _json_bytes({'schema_version':'1.0', **scenario_set, 'scenarios':scenarios})
    files['storage_planning_policy.json'] = _json_bytes({'schema_version':'1.0', **_parse(rows['规划策略'][0], POLICY)})
    return files


def convert_excel(path, baseline):
    from .user_excel import _sheet_maps
    return convert_rows({name:[row for _,row in _sheet_maps(path, name, '储能规划.xlsx')] for name,_,_ in TABLES}, baseline)


def workbook_spec():
    from .user_excel import WorkbookSpec
    return WorkbookSpec('storage_planning', '储能规划.xlsx', '储能规划', '候选站点、储能技术、场景和规划策略', ('储能规划','storage_planning'),
                        '首次发布六表必须完整。每版一份策略、一个场景集。运行图文件填版本内路径；未填文件时需填写固定重空发车模板。方向、是否字段可用中文。容量和功率使用离散档位；关闭运行图协同规划。样例或占位数据只能形成规划敏感性结论。',
                        tuple((name, tuple(mapping.values()), '编码列表用中文逗号分隔；数值不带单位。') for name,mapping,_ in TABLES), convert_excel)
