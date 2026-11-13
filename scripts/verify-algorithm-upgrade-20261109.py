"""Isolated algorithm integration checks. No live database, deployment or business writes."""
from pathlib import Path
from uuid import uuid4
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'energy_recovery_agent'
sys.path.insert(0, str(ENGINE))
from database.worker import build_algorithm_command
from database.result_projection import project_result_directory

SMOKES = (
    'verify_energy_settlement_correctness', 'verify_settlement_invariants',
    'verify_received_storage_and_flexible_zone_data', 'verify_mass_basis',
    'verify_power_scale_consist', 'verify_timetable_optimizer_nsga2',
    'verify_resource_interval_contracts', 'verify_timetable_resource_constraints',
    'verify_optimization_attribution', 'verify_rolling_storage_device_state',
    'verify_rolling_commit_gate', 'verify_joint_parameter_robustness',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('smoke', 'tasks'), required=True)
    args = parser.parse_args()
    out = ROOT / 'output/algorithm-upgrade-20261109' / args.phase
    out.mkdir(parents=True, exist_ok=True)
    logs = out / 'logs'; logs.mkdir(exist_ok=True)
    results = []
    def execute(name, command, timeout=240):
        start = time.monotonic()
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1',
                   HEAVY_EMPTY_TRAIN_COORDINATION_SMOKE_OUTPUT_ROOT=str(out/'smoke-output'))
        with (logs/(name+'.out.log')).open('w',encoding='utf8') as stdout, (logs/(name+'.err.log')).open('w',encoding='utf8') as stderr:
            try:
                result = subprocess.run(command,cwd=ENGINE,env=env,stdout=stdout,stderr=stderr,timeout=timeout)
                row = {'name':name,'passed':result.returncode==0,'exit_code':result.returncode}
            except subprocess.TimeoutExpired:
                row = {'name':name,'passed':False,'error':'verification timeout'}
        row['seconds']=round(time.monotonic()-start,2)
        print(json.dumps(row,ensure_ascii=False),flush=True)
        return row
    if args.phase == 'smoke':
        for name in SMOKES:
            results.append(execute(name,[sys.executable,str(ENGINE/'tests/smoke'/(name+'.py'))]))
    else:
        inputs = out / 'inputs-current'
        shutil.copytree(ENGINE/'data/real_shuohuang',inputs,dirs_exist_ok=True)
        platform = inputs/'platform';platform.mkdir(exist_ok=True)
        shutil.copyfile(ENGINE/'data_templates/running_diagram_template.xlsx',platform/'timetable.xlsx')
        (platform/'joint_parameter_ranges.json').write_text(json.dumps({
            'schema_version':'1.0','evaluation_code':'local_20261109','data_status':'synthetic_test_interval',
            'ranges':{'storage_capacity':[.99,1.01]},'sampling':{'interior_sample_count':0,'seed':7}}),encoding='utf8')
        spec=importlib.util.spec_from_file_location('planning_fixture',ENGINE/'tests/test_storage_planning_platform.py')
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        planning=fixture.tiny_case(out/'planning-inputs')
        policy=json.loads((planning/'storage_planning_policy.json').read_text('utf8'))
        scenarios=json.loads((planning/'storage_planning_scenarios.json').read_text('utf8'))
        cases={
            'dispatch':{'heavy_count':1,'empty_count':1,'population_size':2,'generations':1,'seed':7,
                        'disable_storage_preset_search':True,'disable_energy_observability':True},
            'timetable_audit':{'timetable_relative_path':'platform/timetable.xlsx'},
            'timetable_optimization':{'timetable_relative_path':'platform/timetable.xlsx','mode':'nsga2','population_size':2,'generations':1,'max_candidates':3,'seed':7},
            'rolling_rescheduling':{'population_size':2,'generations':1,'seed':7},
            'joint_parameter_robustness':{'parameter_ranges_relative_path':'platform/joint_parameter_ranges.json','heavy_count':1,'empty_count':1},
            'storage_planning':{'planning_policy_code':policy['policy_code'],'scenario_set_code':scenarios['scenario_set_code'],
                                'search_mode':'coarse','max_levels_per_dimension':2,'settlement_step_s':300},
        }
        for kind,params in cases.items():
            destination=out/kind
            command=build_algorithm_command(kind,params,data_dir=planning if kind=='storage_planning' else inputs,output_dir=destination)
            row=execute(kind,command,timeout=360)
            if row['passed']:
                try:
                    projection=project_result_directory(uuid4(),destination)
                    assert projection['summary'] and projection['artifacts']
                    decision=projection.get('decision') or projection.get('storage_plan_decision') or {}
                    if decision.get('action')=='no_feasible_solution':assert decision.get('selected_candidate_id') is None
                    row['artifact_count']=len(projection['artifacts']);row['decision']=decision
                except Exception as ex:
                    row.update(passed=False,projection_error=str(ex))
            results.append(row)
            (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    return 0 if all(r['passed'] for r in results) else 1


if __name__=='__main__':
    raise SystemExit(main())
