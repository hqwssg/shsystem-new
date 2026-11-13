"""Serial, cancellable physical simulations and full-resolution artifact archives."""
from pathlib import Path
from uuid import UUID, uuid4, uuid5
import csv
import hashlib
import json
import math
import os
import time
import numpy as np

from . import WORKSPACE
from .core import *
from .repository import Repository
from regenerative_braking.simulation.scenario_runner import build_simulator
from regenerative_braking.simulation.regenerative_simulator import SimulationConfig
from regenerative_braking.simulation.closed_loop import ClosedLoopController
from regenerative_braking.validation.baselines import baseline_catalog
from regenerative_braking.validation.perturbation import apply_plant_override, NoisyObservationController
from regenerative_braking.validation.energy_gap import physical_gate, EXCLUDED_BASELINES

class Cancelled(Exception):pass

def artifact_root():
    return Path(os.environ.get('SINGLE_TRAIN_RESULT_ROOT',str(WORKSPACE/'output/single_train_results'))).resolve()

def artifact_path(row):
    root=artifact_root();path=(root/row['run_id']/validate_name(row['relative_path'])).resolve()
    if not path.is_relative_to(root):raise ValueError('非法文件路径')
    if not path.is_file():raise ValueError('结果文件缺失，请从联合备份恢复结果目录')
    if path.stat().st_size!=row['size_bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['content_sha256']:raise ValueError('结果文件校验失败')
    return path

def finite_json(value):
    if isinstance(value,dict):return {k:finite_json(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [finite_json(v) for v in value]
    if hasattr(value,'item'):value=value.item()
    if isinstance(value,float) and not math.isfinite(value):return None
    return value

def add_artifact(repo,run_id,case_id,path,kind):
    relative=path.relative_to(artifact_root()/run_id).as_posix()
    repo.write('INSERT INTO single_artifact(artifact_id,run_id,case_id,relative_path,kind,size_bytes,content_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s)',
        (str(uuid4()),run_id,case_id,relative,kind,path.stat().st_size,hashlib.sha256(path.read_bytes()).hexdigest()))

def run_physics(bundle,scenario,baseline,check=lambda:None):
    plant=apply_plant_override(bundle,scenario.perturbation.plant)
    plant=apply_plant_override(plant,baseline.plant_override(bundle))
    nominal=bundle if scenario.perturbation.controller_uses_nominal else plant
    inner=baseline.controller(nominal,sample_time_s=SIMULATION_DT)
    controller=inner
    noise=scenario.perturbation.noise
    if noise is not None and not noise.is_noop:controller=NoisyObservationController(inner,noise)
    ticks=[0]
    def monitor(t,simulator):
        ticks[0]+=1
        if ticks[0]%1000==1:check()
    result=build_simulator(plant).run(scenario.series,controller,SimulationConfig(dt=SIMULATION_DT,control_period_s=SIMULATION_DT,record_stride=1,max_steps=2_000_000),plant_update=monitor)
    gate=physical_gate(result,plant)
    closure=float(abs(result.ledger.closure_residual_j)/max(result.ledger.mechanical_braking_energy_j,1))
    metrics={**result.to_scenario_metrics().to_flat_dict(),**result.ledger.to_dict(),
        'closure_relative_residual':closure,'closure_failure':closure>1e-4,
        'physical_violation':gate['physical_violation'],'violation_reasons':gate['violation_reasons'],
        'soc_final':float(result.arrays.soc[-1]),'output_voltage_peak_v':float(np.max(result.arrays.output_voltage_v)),
        'inductor_current_peak_a':float(np.max(np.abs(result.arrays.inductor_current_a))),
        'simulation_dt_s':SIMULATION_DT,'control_period_s':SIMULATION_DT,'integration_steps':len(scenario.series),'duration_s':scenario.series.duration_s,
        'metric_schema_version':'2026.11.08',**scenario.reference}
    valid=not gate['physical_violation'] and closure<=1e-4
    eligible=valid and baseline.label not in EXCLUDED_BASELINES-{'rhonn_nsmc'}
    audit={'physicalGate':gate,'controller':inner.audit() if isinstance(inner,ClosedLoopController) else {},
        'notes':list(scenario.notes)+list(baseline.notes)+list(result.extra_notes),
        'parameterStatus':bundle.parameter_status,'disclaimer':DISCLAIMER}
    return result,finite_json(metrics),finite_json(audit),eligible

def solve(repo,row):
    run_id=row['run_id'];snapshot=json.loads(row['snapshot_json']);operator=json.loads(row['parameters_json'])
    deadline=time.monotonic()+int(os.environ.get('SINGLE_TRAIN_SOLVE_TIMEOUT','7200'))
    last=[0.0]
    def check(force=False):
        if time.monotonic()>deadline:raise TimeoutError('任务超过运行时限，已保留完成案例')
        if not force and time.monotonic()-last[0]<1:return
        state=repo.query('SELECT cancel_requested,status FROM single_run WHERE run_id=%s',(run_id,))[0]
        if state['cancel_requested'] or state['status']!='running':raise Cancelled('任务已取消')
        repo.write('UPDATE single_run SET heartbeat_at=UTC_TIMESTAMP(6) WHERE run_id=%s',(run_id,));last[0]=time.monotonic()
    root=artifact_root()/run_id;root.mkdir(parents=True,exist_ok=True)
    t=None;failures=0
    try:
        check(True)
        if row['code_sha256']!=code_digest():raise ValueError('算法或适配代码在排队后已变化，请重新创建任务')
        if row['run_type']=='eco_driving':
            from .eco import solve as solve_eco
            solve_eco(repo,row,snapshot,operator,check,root)
        else:
            t,bundle,scenarios=scenarios_for(snapshot,operator)
            baselines=baseline_catalog('default',reference_strategy='storage_matched')
            if row['run_type']=='simulation':baselines=tuple(b for b in baselines if b.is_optimized)
            for scenario in scenarios:
                for baseline in baselines:
                    check(True)
                    case_id=str(uuid5(UUID(run_id),scenario.label+'|'+baseline.label))
                    repo.write('UPDATE single_run SET current_case=%s WHERE run_id=%s',(scenario.description+' / '+CONTROLLERS[baseline.label],run_id))
                    try:
                        result,metrics,audit,eligible=run_physics(bundle,scenario,baseline,check)
                        check(True)
                        trace=root/(case_id+'.npz');tmp=root/(case_id+'.tmp.npz')
                        np.savez_compressed(tmp,**result.arrays.to_columns());tmp.replace(trace)
                        csv_path=root/(case_id+'.csv');tmpcsv=root/(case_id+'.tmp.csv')
                        columns=result.arrays.to_columns()
                        with tmpcsv.open('w',encoding='utf-8-sig',newline='') as handle:
                            writer=csv.writer(handle);writer.writerow(columns);writer.writerows(zip(*columns.values()))
                        tmpcsv.replace(csv_path)
                        with repo.atomic():
                            repo.write('INSERT INTO single_case(case_id,run_id,scenario_key,scenario_name,controller_key,controller_name,status,eligible,metrics_json,audit_json) VALUES(%s,%s,%s,%s,%s,%s,\'completed\',%s,%s,%s)',
                                (case_id,run_id,scenario.label,scenario.description,baseline.label,CONTROLLERS[baseline.label],int(eligible),dumps(metrics),dumps(audit)))
                            add_artifact(repo,run_id,case_id,trace,'npz');add_artifact(repo,run_id,case_id,csv_path,'csv')
                            repo.write('UPDATE single_run SET completed_cases=completed_cases+1 WHERE run_id=%s',(run_id,))
                        del result,columns
                    except (Cancelled,TimeoutError):raise
                    except Exception as ex:
                        failures+=1
                        with repo.atomic():
                            repo.write('INSERT INTO single_case(case_id,run_id,scenario_key,scenario_name,controller_key,controller_name,status,metrics_json,audit_json,error_message) VALUES(%s,%s,%s,%s,%s,%s,\'failed\',%s,%s,%s)',
                                (case_id,run_id,scenario.label,scenario.description,baseline.label,CONTROLLERS[baseline.label],'{}','{}',str(ex)))
                            repo.write('UPDATE single_run SET completed_cases=completed_cases+1 WHERE run_id=%s',(run_id,))
        check(True)
        cases=repo.run(run_id)['cases']
        manifest={'runId':run_id,'snapshot':snapshot,'businessParameters':operator,'codeSha256':row['code_sha256'],'dt':SIMULATION_DT,'controlPeriod':SIMULATION_DT,'profile':'default','referenceStrategy':'storage_matched','disclaimer':DISCLAIMER,'cases':cases}
        p=root/'manifest.json';p.write_text(dumps(manifest),encoding='utf-8');add_artifact(repo,run_id,None,p,'manifest')
        status='partial' if failures and failures<len(cases) else 'failed' if failures else 'completed'
        repo.write('UPDATE single_run SET status=%s,current_case=NULL,finished_at=UTC_TIMESTAMP(6) WHERE run_id=%s AND status=\'running\'',(status,run_id))
    except Exception as ex:
        status='cancelled' if isinstance(ex,Cancelled) else 'failed'
        repo.write('UPDATE single_run SET status=%s,error_message=%s,finished_at=UTC_TIMESTAMP(6) WHERE run_id=%s',(status,str(ex),run_id))
    finally:
        if t:t.cleanup()

def work(connection):
    repo=Repository(connection)
    if repo.query("SELECT GET_LOCK('carbon_single_train_worker',0) locked")[0]['locked']!=1:return {'busy':True}
    try:
        # Owning the DB lock proves no other module worker is alive. Previous partial cases remain.
        repo.write("UPDATE single_run r SET completed_cases=(SELECT COUNT(*) FROM single_case c WHERE c.run_id=r.run_id AND c.status IN ('completed','failed')),status='failed',error_message='工作进程中断；已完成案例保留，可重新提交任务',finished_at=UTC_TIMESTAMP(6) WHERE status='running'")
        rows=repo.query("SELECT * FROM single_run WHERE status='queued' ORDER BY created_at LIMIT 1")
        if not rows:return {'idle':True}
        row=rows[0]
        changed=repo.write("UPDATE single_run SET status='running',started_at=UTC_TIMESTAMP(6),heartbeat_at=UTC_TIMESTAMP(6) WHERE run_id=%s AND status='queued'",(row['run_id'],))
        if changed:solve(repo,row)
        return {'runId':row['run_id']}
    finally:repo.query("SELECT RELEASE_LOCK('carbon_single_train_worker')")

def trace_preview(repo,case_id):
    rows=repo.query("SELECT * FROM single_artifact WHERE case_id=%s AND kind='npz'",(case_id,))
    if not rows:raise ValueError('此案例没有曲线文件')
    row=rows[0];repo.run(row['run_id']);path=artifact_path(row)
    with np.load(path,allow_pickle=False) as data:
        n=len(data['time_s']);indexes=np.linspace(0,n-1,min(n,2000),dtype=int)
        keys=('time_s','speed_mps','accepted_power_w','output_voltage_v','input_voltage_v','inductor_current_a','soc')
        # Include peaks so the preview cannot hide a narrow voltage/current violation.
        extrema=[]
        for k in ('output_voltage_v','input_voltage_v','inductor_current_a'):
            if k in data:extrema.extend((int(np.argmax(data[k])),int(np.argmin(data[k]))))
        indexes=np.unique(np.r_[indexes,extrema]).astype(int)
        return {'totalPoints':n,'displayPoints':len(indexes),'series':{k:finite_json(data[k][indexes].tolist()) for k in keys if k in data}}
