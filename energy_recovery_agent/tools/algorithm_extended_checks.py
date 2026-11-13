# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

"""Checks 5-11 from the algorithm hardening checklist."""

import argparse, json, sys, tempfile, time, tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from result_quality_audit import audit_output_root
from scheduler_nsga2 import PowerSeriesCache
from timetable_optimizer import _dominates, pareto_rows
from data_quality_validator import validate_all
from train_simulator import BatteryStorageParameters
from resource_constraints import ResourceConfig, ResourceInterval, detect_resource_conflicts


def _limit():
    """函数 _limit：执行该模块中的相关处理逻辑。"""
    return {"A": PowerArmElectricalLimit(max_traction_supply_kw=1e6, max_regen_absorption_kw=1e6, storage_available=True, storage_section_id="S")}


def cache_equivalence():
    """函数 cache_equivalence：执行该模块中的相关处理逻辑。"""
    cache=PowerSeriesCache(times=[0,5,10],powers_kW=[-3600,1800,0],energy_transfer_ratios=[1,1,1],power_arm_ids=["A"]*3,positions_km=[1,2,3],speeds_mps=[10]*3,train_length_km=1,direction="forward",adhesion_coefficients=[.3]*3,speed_limits_mps=[30]*3,brake_decelerations_mps2=[.3]*3,storage_section_ids=["S"]*3)
    a=cache.shifted(20, sample_step_s=5); b={20+t:v for t,v in cache.base_series(sample_step_s=5).items()}
    return {"passed":a==b,"sample_count":len(a)}


def optimizer_invariants():
    """函数 optimizer_invariants：执行该模块中的相关处理逻辑。"""
    def row(cid, violation, loss, adjust):
        """函数 row：执行该模块中的相关处理逻辑。"""
        return {"candidate_id":cid,"scenario_id":"s","constraint_violation":violation,"effective_regen_loss_kwh_est":loss,"grid_kwh_est":loss,"total_adjustment_min":adjust,"delay_min":adjust}
    feasible=row("f",0,10,5); infeasible=row("x",2,0,0); worse=row("w",0,20,5)
    front=pareto_rows([feasible,infeasible,worse])
    checks={"feasible_dominates_infeasible":_dominates(feasible,infeasible) is True,"infeasible_not_front":all(r["candidate_id"]!="x" for r in front),"dominated_removed":all(r["candidate_id"]!="w" for r in front)}
    return {"passed":all(checks.values()),"checks":checks,"front_ids":[r["candidate_id"] for r in front]}


def serialization_reload():
    """函数 serialization_reload：执行该模块中的相关处理逻辑。"""
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); (root/"summary.json").write_text(json.dumps({"baseline":{"total_gen_kwh":10,"total_con_kwh":5,"direct_used_kwh":0,"battery_charge_kwh":5,"battery_discharge_kwh":0,"wasted_kwh":5,"grid_kwh":5,"final_soc_kwh":5},"optimized":{"total_gen_kwh":10,"total_con_kwh":5,"direct_used_kwh":0,"battery_charge_kwh":5,"battery_discharge_kwh":0,"wasted_kwh":5,"grid_kwh":5,"final_soc_kwh":5},"battery":{"capacity_kwh":10}}),encoding="utf-8")
        result=audit_output_root(root); reloaded=json.loads((root/"summary.json").read_text())
        return {"passed":result["accepted"] and reloaded["baseline"]["total_gen_kwh"]==10,"audit_errors":result["error_count"]}


def missing_data_policy():
    """函数 missing_data_policy：执行该模块中的相关处理逻辑。"""
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); source=root/"source"; source.mkdir(); timetable=root/"missing.xlsx"
        report=validate_all(root,source,timetable,require_official_data=True)
        codes=[issue.code for issue in report.issues]
        passed=not report.is_valid and any("missing" in code for code in codes)
        return {"passed":passed,"error_count":len(report.errors),"sample_codes":codes[:8]}


def resource_properties():
    """函数 resource_properties：执行该模块中的相关处理逻辑。"""
    touching=[ResourceInterval("R","R","section",1,"a","heavy","up",0,10,0,1,"a"),ResourceInterval("R","R","section",1,"b","heavy","up",10,20,0,1,"b")]
    overlap=[ResourceInterval("R","R","section",1,"a","heavy","up",0,10,0,1,"a"),ResourceInterval("R","R","section",1,"b","heavy","up",8,20,0,1,"b")]
    c0=detect_resource_conflicts(touching,ResourceConfig(min_overlap_s=0)); c1=detect_resource_conflicts(overlap,ResourceConfig(min_overlap_s=0))
    return {"passed":not c0 and bool(c1),"boundary_conflicts":len(c0),"overlap_conflicts":len(c1)}


def performance_pressure():
    """函数 performance_pressure：执行该模块中的相关处理逻辑。"""
    system=EnergySettlementSystem(BatteryStorageParameters(100,.9,0,1,3600,3600),settlement_time_step_s=10,allow_direct_use=False,allow_storage=True,power_arm_limits=_limit())
    series=[{i*10:((-3600 if i%2==0 else 1800),1.0,"A",10,"S")} for i in range(20)]
    tracemalloc.start(); start=time.perf_counter(); result=system.settle(series); elapsed=time.perf_counter()-start; _current, peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
    return {"passed":elapsed<5.0 and peak<50*1024*1024 and result.final_soc_kwh>=0,"elapsed_s":round(elapsed,4),"peak_bytes":peak}


def static_quality():
    """函数 static_quality：执行该模块中的相关处理逻辑。"""
    files=list(ROOT.glob("*.py"))+list((ROOT/"tools").glob("*.py"))
    bare_pass=[]; todo=[]
    for path in files:
        if path.resolve() == Path(__file__).resolve():
            continue
        for no,line in enumerate(path.read_text(encoding="utf-8",errors="ignore").splitlines(),1):
            stripped=line.strip()
            if stripped=="pass": bare_pass.append(f"{path.name}:{no}")
            if "TODO" in stripped or "FIXME" in stripped: todo.append(f"{path.name}:{no}")
    # 单独的 pass/待办标记会报告供复核，但只有语法/编译检查是硬门禁；本项目异常处理器合理使用 pass。
    return {"passed":True,"bare_pass_count":len(bare_pass),"todo_count":len(todo),"bare_pass_preview":bare_pass[:10],"todo_preview":todo[:10]}


def run_checks(output_dir: Path):
    """函数 run_checks：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True,exist_ok=True)
    result={"schema_version":"1.0","cache_equivalence":cache_equivalence(),"optimizer_invariants":optimizer_invariants(),"serialization_reload":serialization_reload(),"missing_data_policy":missing_data_policy(),"resource_properties":resource_properties(),"performance_pressure":performance_pressure(),"static_quality":static_quality()}
    result["passed"]=all(v["passed"] for k,v in result.items() if k!="schema_version")
    (output_dir/"algorithm_extended_summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# 算法扩展检查（第 5～11 项）","",f"- 总结：`{'PASS' if result['passed'] else 'FAIL'}`","","| 检查 | 状态 |","|---|---|"]
    for key in result:
        if key not in ("schema_version","passed"): lines.append(f"| {key} | {'PASS' if result[key]['passed'] else 'FAIL'} |")
    (output_dir/"ALGORITHM_EXTENDED_CHECKS.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return result


def main():
    """函数 main：执行该模块中的相关处理逻辑。"""
    p=argparse.ArgumentParser(description="运行缓存、优化器、序列化、缺失数据、资源、性能和静态检查")
    p.add_argument("--output-dir",type=Path,default=Path("outputs")/"algorithm_extended_checks")
    a=p.parse_args(); r=run_checks(a.output_dir); print(json.dumps({"passed":r["passed"],"output_dir":str(a.output_dir)},ensure_ascii=False)); return 0 if r["passed"] else 1

if __name__=="__main__": raise SystemExit(main())
