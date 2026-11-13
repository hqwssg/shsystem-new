# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

"""Detailed synthetic validation suite for the current algorithm.

The suite produces evidence for resolution error, baseline/ablation, optimizer
stability, storage-policy parameterization, and a repeatable performance probe.
It does not use or modify official data.
"""

import argparse, json, statistics, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from timetable_optimizer import optimize_timetable
from train_simulator import BatteryStorageParameters


def limits():
    """函数 limits：执行该模块中的相关处理逻辑。"""
    return {"A": PowerArmElectricalLimit(max_traction_supply_kw=1e6,max_regen_absorption_kw=1e6,storage_available=True,storage_section_id="S")}


def settle(step, series, battery, allow_storage=True):
    """函数 settle：执行该模块中的相关处理逻辑。"""
    return EnergySettlementSystem(battery,settlement_time_step_s=step,allow_direct_use=False,allow_storage=allow_storage,power_arm_limits=limits()).settle(series)


def metrics(result):
    """函数 metrics：执行该模块中的相关处理逻辑。"""
    return {k: float(getattr(result,k)) for k in ("total_gen_kwh","total_con_kwh","battery_charge_kwh","battery_discharge_kwh","wasted_kwh","grid_kwh","final_soc_kwh","total_cost")}


def resolution_matrix():
    """函数 resolution_matrix：执行该模块中的相关处理逻辑。"""
    scenarios={
        "aligned": [{0:(-3600,1,"A",10,"S"),10:(1800,1,"A",10,"S")}],
        "crossing": [{5:(-3600,1,"A",15,"S"),20:(1800,1,"A",15,"S")}],
        "mixed": [{0:(-2700,1,"A",7,"S"),7:(900,1,"A",13,"S"),20:(-1800,1,"A",11,"S")}],
    }
    rows=[]
    battery=BatteryStorageParameters(20,.9,0,1,3600,3600)
    for name,series in scenarios.items():
        values={step:metrics(settle(step,series,battery)) for step in (1,5,10,30)}
        ref=values[1]
        errors={step:{k:abs(values[step][k]-ref[k]) for k in ref} for step in (5,10,30)}
        fine_errors={step:errors[step] for step in (5,10)}
        coarse_errors=errors[30]
        max_fine_rel=max((err/max(1,abs(ref[k])) for e in fine_errors.values() for k,err in e.items()),default=0)
        max_coarse_rel=max((err/max(1,abs(ref[k])) for k,err in coarse_errors.items()),default=0)
        rows.append({"scenario":name,"values":values,"errors_vs_1s":errors,"max_fine_relative_error":max_fine_rel,"max_30s_relative_error":max_coarse_rel,"coarse_step_sensitivity":max_coarse_rel>1e-9})
    # 总发电量和牵引量必须与时间分辨率无关。时间桶合并事件时，充电、放电和电网供能的分配可以合理变化；
    # 该影响应作为敏感性报告，不能被隐藏。
    invariant_ok = all(
        max(abs(row["values"][step][field] - row["values"][1][field]) for step in (5, 10, 30)) <= 1e-9
        for row in rows for field in ("total_gen_kwh", "total_con_kwh")
    )
    return {"passed": invariant_ok, "coarse_sensitivity_present": any(row["coarse_step_sensitivity"] for row in rows), "scenarios":rows}


def baseline_ablation():
    """函数 baseline_ablation：执行该模块中的相关处理逻辑。"""
    series=[{0:(-3600,1,"A",10,"S"),10:(3600,1,"A",10,"S")}]
    variants={
        "full_storage_no_direct":(BatteryStorageParameters(20,.9,0,1,3600,3600),True),
        "no_storage":(BatteryStorageParameters(0,.9,0,1,0,0),False),
        "low_capacity":(BatteryStorageParameters(5,.9,0,1,3600,3600),True),
        "low_power":(BatteryStorageParameters(20,.9,0,1,900,900),True),
        "low_efficiency":(BatteryStorageParameters(20,.5,0,1,3600,3600),True),
    }
    rows=[]
    for name,(battery,enabled) in variants.items(): rows.append({"variant":name,**metrics(settle(10,series,battery,enabled))})
    base=rows[0]; checks={"storage_vs_none_grid":base["grid_kwh"]<=rows[1]["grid_kwh"],"storage_vs_none_waste":base["wasted_kwh"]<=rows[1]["wasted_kwh"],"low_capacity_not_better_than_full":rows[2]["grid_kwh"]>=base["grid_kwh"],"low_power_not_better_than_full":rows[3]["grid_kwh"]>=base["grid_kwh"],"low_efficiency_not_better_than_full":rows[4]["grid_kwh"]>=base["grid_kwh"]}
    return {"passed":all(checks.values()),"checks":checks,"rows":rows}


def optimizer_stability():
    """函数 optimizer_stability：执行该模块中的相关处理逻辑。"""
    input_path=ROOT/"data_templates"/"running_diagram_template.xlsx"; rows=[]
    with tempfile.TemporaryDirectory() as d:
        for seed in (1,2,3,4,5):
            out=Path(d)/f"seed_{seed}"; start=time.perf_counter()
            summary=optimize_timetable(input_path,out,mode="nsga2",max_shift_min=10,step_min=5,max_dwell_extension_min=5,max_candidates=20,population_size=6,generations=2,seed=seed,strict_visualizations=False)
            rows.append({"seed":seed,"valid":summary.get("valid"),"candidate_count":summary.get("candidate_count"),"pareto_count":summary.get("pareto_count"),"feasible_candidate_count":summary.get("feasible_candidate_count"),"elapsed_s":round(time.perf_counter()-start,3)})
    checks={"all_valid":all(r["valid"] for r in rows),"nonempty_candidates":all(r["candidate_count"]>0 for r in rows),"stable_candidate_count":len({r["candidate_count"] for r in rows})==1,"stable_pareto_nonempty":all(r["pareto_count"]>0 for r in rows)}
    return {"passed":all(checks.values()),"checks":checks,"rows":rows}


def storage_policy_comparison():
    """函数 storage_policy_comparison：执行该模块中的相关处理逻辑。"""
    series=[{0:(-3600,1,"A",10,"S"),10:(3600,1,"A",10,"S")}]
    policies=[("storage_disabled",False,20,.9,3600,3600,None),("charge_discharge_balanced",True,20,.9,3600,3600,None),("conservative_capacity",True,10,.9,3600,3600,None),("high_efficiency",True,20,1.0,3600,3600,None),("terminal_target",True,20,.9,3600,3600,10)]
    rows=[]
    for name,enabled,cap,eff,cp,dp,target in policies:
        battery=BatteryStorageParameters(cap,eff,0,1,cp,dp)
        system=EnergySettlementSystem(battery,settlement_time_step_s=10,initial_soc_kwh=0,target_final_soc_kwh=target,allow_direct_use=False,allow_storage=enabled,power_arm_limits=limits())
        rows.append({"policy":name,**metrics(system.settle(series))})
    checks={"disabled_has_no_storage_flow":rows[0]["battery_charge_kwh"]==0 and rows[0]["battery_discharge_kwh"]==0,"high_efficiency_not_more_grid":rows[3]["grid_kwh"]<=rows[1]["grid_kwh"],"target_reported":rows[4]["final_soc_kwh"]>=0}
    return {"passed":all(checks.values()),"checks":checks,"rows":rows}


def feeder_performance_probe():
    """函数 feeder_performance_probe：执行该模块中的相关处理逻辑。"""
    series=[{i*10:((-3600 if i%3==0 else 1800),1,"A",10,"S")} for i in range(200)]
    battery=BatteryStorageParameters(100,.9,0,1,3600,3600); times=[]
    for _ in range(5):
        start=time.perf_counter(); settle(10,series,battery); times.append(time.perf_counter()-start)
    return {"passed":max(times)<5,"repetitions":len(times),"times_s":[round(t,6) for t in times],"median_s":round(statistics.median(times),6)}


def run_suite(output_dir):
    """函数 run_suite：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True,exist_ok=True)
    result={"schema_version":"1.0","resolution_matrix":resolution_matrix(),"baseline_ablation":baseline_ablation(),"optimizer_stability":optimizer_stability(),"storage_policy_comparison":storage_policy_comparison(),"feeder_performance_probe":feeder_performance_probe()}
    result["passed"]=all(v["passed"] for k,v in result.items() if k!="schema_version")
    (output_dir/"algorithm_validation_summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# 算法验证套件","",f"- 总结：`{'PASS' if result['passed'] else 'FAIL'}`","","| 项目 | 状态 |","|---|---|"]
    for key in result:
        if key not in ("schema_version","passed"): lines.append(f"| {key} | {'PASS' if result[key]['passed'] else 'FAIL'} |")
    (output_dir/"ALGORITHM_VALIDATION_REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return result


def main():
    """函数 main：执行该模块中的相关处理逻辑。"""
    p=argparse.ArgumentParser(description="运行快速/精细、基线消融、稳定性、储能策略和性能验证")
    p.add_argument("--output-dir",type=Path,default=Path("outputs")/"algorithm_validation_suite")
    a=p.parse_args(); r=run_suite(a.output_dir); print(json.dumps({"passed":r["passed"],"output_dir":str(a.output_dir)},ensure_ascii=False)); return 0 if r["passed"] else 1

if __name__=="__main__": raise SystemExit(main())
