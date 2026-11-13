"""Snapshots, canonical shared facts and operator parameter validation."""
from dataclasses import replace
from pathlib import Path
import base64
import csv
import hashlib
import io
import json
import math
import tempfile

from . import ALGORITHM
from regenerative_braking.io.data_paths import ProjectPaths
from regenerative_braking.io.data_loader import load_shared_railway_data
from regenerative_braking.simulation.scenario_runner import load_component_bundle
from regenerative_braking.validation.scenarios import ScenarioProfileConfig, build_validation_scenarios
from regenerative_braking.io.data_loader import combine_regen_curves, consist_entries_for, power_cap_w
from regenerative_braking.io.parameter_glossary import PARAMETER_FIELD_CN, flatten_parameters, lookup, unit_of, display_text

SHARED = ('stations.csv','segments.csv','gradients.csv','curves.csv','trains.csv','power_arm_intervals.csv','route_metadata.json','locomotive_curves.json')
SHARED_OPTIONAL = ('section_run_times.csv','smart_meter_interval_feedback.csv')
SIMULATION_DT = 1e-4
PARAMETERS = ('train','motor','dc_dc','storage')
CONTROLLERS = {
 'rhonn_nsmc':'主算法 RHONN＋EKF/UKF＋NSMC', 'uncontrolled_zero_duty':'无控制（回网）',
 'fixed_duty_d1_0.75':'固定控制（轻载）', 'fixed_duty_d1_0.85':'固定控制（高负载）',
 'pi':'PI 控制', 'pid':'PID 控制', 'traditional_smc':'传统滑模控制',
 'ideal_upper_bound':'理想上界参照', 'no_storage_zero_duty':'无储能参照'}
RUN_TYPES = ('simulation','comparison','validation','eco_driving')
DISCLAIMER = '仿真结果；模型包含预设和占位参数，不作为工程结论。'

def dumps(value):
    def native(v):
        if hasattr(v, 'item'): return v.item()
        if isinstance(v, Path): return str(v)
        if hasattr(v, 'isoformat'): return v.isoformat()
        raise TypeError(type(v).__name__)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, default=native)

def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()

def code_digest():
    files = [*sorted((ALGORITHM/'regenerative_braking').rglob('*.py')), *sorted((ALGORITHM/'eco_driving').rglob('*.py')), *sorted(Path(__file__).parent.glob('*.py'))]
    return digest({str(p.relative_to(ALGORITHM)) if p.is_relative_to(ALGORITHM) else 'adapter/'+p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files})

def encode_files(files):
    return {name:base64.b64encode(content).decode() for name,content in files.items()}

def decode_files(files):
    return {name:base64.b64decode(content, validate=True) for name,content in files.items()}

def validate_name(name):
    p = Path(name.replace('\\','/'))
    if p.is_absolute() or '..' in p.parts or ':' in name or not name or '\x00' in name:
        raise ValueError('文件名必须是安全的相对路径')
    return p.as_posix()

def materialize(snapshot, root):
    for name, content in decode_files(snapshot['files']).items():
        dest = root / 'shared' / validate_name(name)
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(content)
    for name, params in snapshot['parameters'].items():
        if name not in PARAMETERS: raise ValueError('未知参数主题')
        dest = root / 'parameters' / (name+'_parameters.json')
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text(dumps(params),encoding='utf-8')
    return ProjectPaths(ALGORITHM, ALGORITHM/'configs/data_paths.yaml',root/'shared',root/'parameters',root/'results',ALGORITHM/'data/data_manifest.yaml',True,SHARED)

def compatible_facts(files):
    """Export frozen shared facts, including train-specific eco-driving limits."""
    result = {k:v for k,v in files.items() if k in SHARED + SHARED_OPTIONAL and k != 'trains.csv'}
    if 'trains.csv' in files:
        fields = ('name','mass_tons','length_km','rotational_mass_factor','longitudinal_segments','direction','mass_data_status','mass_note',
                  'locomotive_type','locomotive_count','locomotive_consist','freight_load_state','max_power_kW',
                  'max_traction_kN','max_brake_kN','davis_a','davis_b','davis_c')
        rows = list(csv.DictReader(io.StringIO(files['trains.csv'].decode('utf-8-sig'))))
        fields=tuple(k for k in fields if any(k in row for row in rows))
        out=io.StringIO(); w=csv.DictWriter(out,fieldnames=fields,lineterminator='\n');w.writeheader()
        for row in rows:
            if not row.get('name'): raise ValueError('列车基础数据缺少名称')
            mass=float(row.get('mass_tons','nan'))
            if not math.isfinite(mass) or mass <= 0: raise ValueError('列车质量必须为正数（吨）')
            w.writerow({k:row.get(k,'') for k in fields})
        result['trains.csv']=out.getvalue().encode()
    return result

def algorithm_shared_files(snapshot):
    """The legacy reader requests heavy-specific columns it never uses for geometry.
    Supply explicit placeholders locally, never export them as shared facts.
    """
    files=decode_files(snapshot['files'])
    if 'trains.csv' in files:
        rows=list(csv.DictReader(io.StringIO(files['trains.csv'].decode('utf-8-sig'))))
        fields=list(rows[0]) if rows else []
        extras=('max_traction_kN','max_brake_kN','davis_a','davis_b','davis_c','max_power_kW')
        for field in extras:
            if field not in fields: fields.append(field)
        out=io.StringIO();w=csv.DictWriter(out,fieldnames=fields,lineterminator='\n');w.writeheader()
        for row in rows:
            for field in extras: row.setdefault(field,'0')
            w.writerow(row)
        files['trains.csv']=out.getvalue().encode()
    # These source files carry module-specific assumptions and must be supplied explicitly.
    return {**snapshot,'files':encode_files(files)}

def default_parameters(files):
    params={k:json.loads((ALGORITHM/'data/single_train'/(k+'_parameters.json')).read_text(encoding='utf-8')) for k in PARAMETERS}
    rows=list(csv.DictReader(io.StringIO(files.get('trains.csv',b'').decode('utf-8-sig'))))
    chosen=next((r for r in rows if r.get('name')=='Heavy'), rows[0] if rows else None)
    if chosen:
        train=params['train']
        for source,target,scale in [('length_km','train_length_m',1000),('rotational_mass_factor','rotational_mass_factor',1),('longitudinal_segments','longitudinal_segments',1)]:
            if chosen.get(source): train[target]=float(chosen[source])*scale
        train.setdefault('provenance',{})['platform_shared_train']=dict(chosen)
        with tempfile.TemporaryDirectory(prefix='single_defaults_') as directory:
            snapshot={'files':encode_files(files),'parameters':{}}
            shared=load_shared_railway_data(materialize(algorithm_shared_files(snapshot),Path(directory)))
        record=shared.trains.get('Heavy')
        if record is None:raise ValueError('单列车默认参数需要名为 Heavy 的列车基础记录')
        combined=combine_regen_curves(consist_entries_for(record),shared.locomotives)
        train.update(vehicle_mass_tons=record.mass_tons,mass_kg=(record.mass_tons+combined.mass_t)*1000,
                     locomotive_type=record.locomotive_type,locomotive_count=record.locomotive_count,
                     max_regen_force_n=combined.peak_force_kn*1000*train['electrical_level'])
        params['motor'].update(max_regen_power_w=power_cap_w(record,locomotives=shared.locomotives),max_regen_force_n=combined.peak_force_kn*1000)
        params['dc_dc']['power_rating_w']=params['motor']['max_regen_power_w']
        train.setdefault('field_data_status',{})['mass_kg']='derived'
        train.setdefault('provenance',{})['mass_kg']='车辆总重与冻结机车曲线中的编组自重相加；车辆来源：'+str(chosen.get('mass_note',''))
        mirrors={
            'train':{
                'vehicle_mass_tons':'冻结 trains.csv 的车辆总重，不含机车。'+str(chosen.get('mass_note','')),
                'locomotive_type':'冻结 trains.csv 的首型机车；完整编组以 locomotive_consist 为准。',
                'locomotive_count':'冻结 trains.csv 的首型机车台数，不是完整编组总台数；完整编组以 locomotive_consist 为准。',
                'max_regen_force_n':'按本版本完整编组与冻结 locomotive_curves.json 合并电制动力峰值，再乘本版本 electrical_level；不是全列空气加电制动总上限。',
            },
            'motor':{
                'max_regen_power_w':'由冻结 trains.csv 的完整编组、功率缩放与 locomotive_curves.json 推导整列机车再生功率上限。',
                'max_regen_force_n':'由冻结 locomotive_curves.json 合并本版本完整编组的电制动力峰值，未乘电制动级位。',
            },
            'dc_dc':{'power_rating_w':'与本版本 motor.max_regen_power_w 一致，来自冻结完整机车编组及功率上限。'},
        }
        for topic,fields in mirrors.items():
            for field,note in fields.items():
                params[topic].setdefault('field_data_status',{})[field]='derived'
                params[topic].setdefault('provenance',{})[field]=note
    return params

def default_auxiliary_files():
    # Explicit default-template operation, labelled independently from copied facts.
    root=Path(__file__).resolve().parent/'data_templates'
    return {k:(root/k).read_bytes() for k in ('operating_conditions.json','battery.json')} | {
        'locomotive_curves.json':(ALGORITHM/'data/shared/locomotive_curves.json').read_bytes()}

def default_rolling_stock(files):
    """Explicit draft-default operation only; never used while running an old snapshot."""
    rows=list(csv.DictReader(io.StringIO(files.get('trains.csv',b'').decode('utf-8-sig'))))
    if not rows:raise ValueError('缺少列车基础数据，请先导入基础数据')
    with (ALGORITHM/'data/shared/trains.csv').open(encoding='utf-8-sig') as handle:
        references={r['name']:r for r in csv.DictReader(handle)}
    fields=list(rows[0]);required=('locomotive_type','locomotive_count','locomotive_consist','freight_load_state','max_power_kW')
    for field in required:
        if field not in fields:fields.append(field)
    for row in rows:
        reference=references.get(row['name'],{})
        # A specified consist belongs to this version; only complete missing legacy metadata.
        if not row.get('locomotive_type') and not row.get('locomotive_consist'):
            for field in required:
                if not row.get(field):row[field]=reference.get(field,'')
    out=io.StringIO();writer=csv.DictWriter(out,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)
    return {**files,'trains.csv':out.getvalue().encode('utf-8')}

def parameter_metadata(parameters):
    result={}
    for topic,payload in parameters.items():
        result[topic]=[{'path':path,'label':PARAMETER_FIELD_CN.get(path,path),'unit':unit_of(path),
                        'dataStatus':lookup(payload.get('field_data_status',{}),path) or payload.get('data_status','unknown'),
                        'provenance':display_text(str(lookup(payload.get('provenance',{}),path) or '未提供字段来源'))}
                       for path,value in flatten_parameters(payload)]
    return result

def readiness(snapshot, target='single'):
    files=decode_files(snapshot['files']); missing=[k for k in SHARED if k not in files]
    if target=='energy':
        required=('battery.json','operating_conditions.json','headway_constraints.csv','technical_operation_times.csv','station_operation_assignments.csv','station_resources.csv','resource_config.json')
        missing += [k for k in required if k not in files]
        if not any(k in files for k in ('platform/running_diagram.xlsx','platform/timetable.xlsx','platform/timetable.csv')): missing.append('运行图')
        missing += ['trains.csv: '+k for k in ('max_traction_kN','max_brake_kN','davis_a','davis_b','davis_c','max_power_kW') if k not in (next(csv.DictReader(io.StringIO(files.get('trains.csv',b'').decode('utf-8-sig'))),{}))]
        planning=('storage_candidate_sites.csv','storage_technologies.csv','storage_site_technology_options.csv','storage_planning_scenarios.json','storage_planning_policy.json')
        dedicated={'storage_planning':planning,'joint_parameter_robustness':('platform/joint_parameter_ranges.json',),
            'historical_disturbance_replay':('platform/historical_disturbance_replay.json',)}
        features={}
        for t in ('timetable_audit','timetable_optimization','rolling_rescheduling','joint_parameter_robustness','historical_disturbance_replay','storage_planning'):
            required=missing+[k for k in dedicated.get(t,()) if k not in files]
            features[t]={'ready':not required,'missing':required}
        return {'ready':not missing,'missing':missing,'features':features}
    missing += [k+'_parameters.json' for k in PARAMETERS if k not in snapshot['parameters']]
    missing += [k for k in ('operating_conditions.json','battery.json') if k not in files]
    errors=[]
    if not missing:
        try:
            with tempfile.TemporaryDirectory(prefix='single_ready_') as t:
                paths=materialize(algorithm_shared_files(snapshot),Path(t));load_component_bundle(paths);load_shared_railway_data(paths)
        except Exception as ex: errors.append(str(ex))
    features={k:{'ready':not missing and not errors,'missing':missing,'errors':errors} for k in RUN_TYPES}
    if not missing and not errors:
        from .eco import validate_train
        try:validate_train(snapshot,'Heavy')
        except ValueError as ex:features['eco_driving']={'ready':False,'missing':[],'errors':[str(ex)]}
    return {'ready':not missing and not errors,'missing':missing,'errors':errors,'features':features}

def validate_operator_parameters(parameters, run_type):
    if run_type not in RUN_TYPES: raise ValueError('不支持的单列车任务类型')
    if run_type == 'eco_driving':
        from .eco import validate_parameters
        return validate_parameters(parameters)
    allowed={'scenarioKeys','initialSpeedKmh','initialSoc','routeStartKm'}
    if set(parameters)-allowed: raise ValueError('任务只能提交业务参数；技术配置由管理员维护')
    for k in ('initialSpeedKmh','initialSoc','routeStartKm'):
        if k in parameters:
            v=float(parameters[k])
            if not math.isfinite(v): raise ValueError(k+'必须为有限数值')
            if k=='initialSpeedKmh' and not 5.4 <= v <= 80: raise ValueError('初始速度需在 5.4～80 km/h 之间')
            if k=='initialSoc' and not 0 <= v <= 1: raise ValueError('初始电量需在 0～100% 之间')
            if k=='routeStartKm' and v<0: raise ValueError('起点里程不可为负数')
    keys=parameters.get('scenarioKeys',[])
    if not isinstance(keys,list) or not keys or any(not isinstance(k,str) for k in keys): raise ValueError('请选择制动场景')
    if len(set(keys)) != len(keys): raise ValueError('场景不可重复')
    if run_type!='validation' and len(keys)!=1: raise ValueError('此功能需要选择一个场景')

def scenario_speed_bounds(bundle, scenario):
    """Derive entry limits from the unchanged nominal braking profile, not a second set of deceleration constants."""
    if scenario.scenario_id == 'sR_route_braking':
        return {'speedMinKmh':None,'speedMaxKmh':80.0}
    samples=scenario.series.samples
    entry=float(samples[0].speed_mps);lowest=min(float(s.speed_mps) for s in samples)
    floor=float(bundle.motor.min_regen_speed_m_per_s)*ScenarioProfileConfig().regen_speed_margin
    if scenario.scenario_id in ('s2_long_downhill','s5_soc_near_limit'):
        minimum=floor*entry/lowest
    else:
        minimum=floor+entry-lowest
    # Round upwards; sample endpoints can differ slightly from the continuous window.
    return {'speedMinKmh':max(5.4,math.ceil(minimum*3.6*10-1e-9)/10),'speedMaxKmh':80.0}

def scenarios_for(snapshot, operator):
    # The caller owns the temporary directory throughout execution.
    temp=tempfile.TemporaryDirectory(prefix='single_snapshot_')
    try:
        paths=materialize(algorithm_shared_files(snapshot),Path(temp.name))
        bundle=load_component_bundle(paths); shared=load_shared_railway_data(paths)
        if 'initialSoc' in operator:
            soc=float(operator['initialSoc'])
            if not bundle.storage_params.soc_min<=soc<=bundle.storage_params.soc_max: raise ValueError('初始电量超出当前储能允许范围')
            bundle=replace(bundle,storage_params=replace(bundle.storage_params,soc_initial=soc))
        config=ScenarioProfileConfig()
        wanted=operator.get('scenarioKeys')
        has_route_override='routeStartKm' in operator and (wanted is None or 'sR_route_braking[nominal]' in wanted)
        if 'initialSpeedKmh' in operator:
            non_route=None if wanted is None else [k for k in wanted if k!='sR_route_braking[nominal]']
            nominal=build_validation_scenarios(bundle,SIMULATION_DT,shared=None,config=config,selected_keys=non_route) if non_route is None or non_route else ()
        else:
            nominal=() if has_route_override else build_validation_scenarios(bundle,SIMULATION_DT,shared=shared,config=config,selected_keys=wanted)
        changes={}
        if 'initialSpeedKmh' in operator:
            speed=float(operator['initialSpeedKmh'])
            for scenario in nominal:
                bounds=scenario_speed_bounds(bundle,scenario)
                if bounds['speedMinKmh'] is not None and not bounds['speedMinKmh']<=speed<=bounds['speedMaxKmh']:
                    raise ValueError(f"当前场景初始速度需在 {bounds['speedMinKmh']:g}～{bounds['speedMaxKmh']:g} km/h 之间，保证整个制动窗口高于再生投入门限")
            changes={'flat_v0_kmh':speed,'downhill_entry_kmh':speed,'downhill_target_kmh':speed*config.downhill_target_kmh/config.downhill_entry_kmh,'route_v0_kmh':speed}
        if has_route_override:
            start=float(operator['routeStartKm'])
            if not shared.segments[0].start_km<=start<shared.segments[-1].end_km:raise ValueError('起点里程超出当前线路范围')
            changes['route_start_km']=start
        config=replace(config,**changes)
        scenarios=build_validation_scenarios(bundle,SIMULATION_DT,shared=shared,config=config,selected_keys=wanted) if changes else nominal
        return temp,bundle,scenarios
    except BaseException:
        temp.cleanup();raise
