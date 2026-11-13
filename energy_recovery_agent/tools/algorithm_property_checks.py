# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

"""Property-style checks for time boundaries, direction, terminal SOC and resources."""

import argparse, json, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from resource_constraints import ResourceConfig, ResourceInterval, detect_resource_conflicts, resource_capacity_overlap_violation_s
from operating_conditions import default_operating_conditions
from train_simulator import DavisCoefficients, RouteData, Segment, Station, TrainParameters, run_train_simulation, BatteryStorageParameters


def _limit():
    """函数 _limit：执行该模块中的相关处理逻辑。"""
    return {"A": PowerArmElectricalLimit(max_traction_supply_kw=1e6, max_regen_absorption_kw=1e6, storage_available=True, storage_section_id="S")}


def randomized_properties(seed=20260901, iterations=200):
    """函数 randomized_properties：执行该模块中的相关处理逻辑。"""
    rng = random.Random(seed); failures=[]
    for i in range(iterations):
        cap=rng.uniform(0,100); eff=rng.uniform(0.1,1); cp=rng.uniform(0,5000); dp=rng.uniform(0,5000)
        b=BatteryStorageParameters(cap,eff,0,1,cp,dp)
        system=EnergySettlementSystem(b,settlement_time_step_s=rng.choice([1,5,10,30]),allow_direct_use=False,allow_storage=True,power_arm_limits=_limit())
        series=[]; t=0
        for _ in range(rng.randint(1,5)):
            power=rng.uniform(-5000,5000); dur=rng.choice([1,3,7,10,20]); series.append({t:(power,1.0,"A",dur,"S")}); t += dur
        try: r=system.settle(series)
        except Exception as exc: failures.append({"iteration":i,"error":str(exc)}); continue
        vals=(r.total_gen_kwh,r.total_con_kwh,r.battery_charge_kwh,r.battery_discharge_kwh,r.wasted_kwh,r.grid_kwh,r.final_soc_kwh)
        if any(v < -1e-9 or v != v or abs(v)==float("inf") for v in vals) or r.final_soc_kwh > cap+1e-6:
            failures.append({"iteration":i,"values":vals})
    return {"passed":not failures,"iterations":iterations,"failure_count":len(failures),"failures":failures[:5]}


def bucket_boundaries():
    """函数 bucket_boundaries：执行该模块中的相关处理逻辑。"""
    b=BatteryStorageParameters(100,1,0,1,1e6,1e6)
    # 15 秒样本跨过 10 秒边界，总能量必须仍为 15 kWh。
    s=EnergySettlementSystem(b,settlement_time_step_s=10,allow_direct_use=False,allow_storage=False,power_arm_limits={})
    r=s.settle([{5:(3600,1.0,"A",15)}])
    crossing = abs(r.total_con_kwh-15.0)<=1e-9 and abs(r.grid_kwh-15.0)<=1e-9
    # 相邻样本不能重叠，也不能产生间隙。
    r2=s.settle([{0:(3600,1.0,"A",10),10:(3600,1.0,"A",10)}])
    adjacent = abs(r2.total_con_kwh-20.0)<=1e-9
    return {"passed":crossing and adjacent,"crossing":crossing,"adjacent":adjacent,"values":{"crossing_kwh":r.total_con_kwh,"adjacent_kwh":r2.total_con_kwh}}


def direction_symmetry():
    """函数 direction_symmetry：执行该模块中的相关处理逻辑。"""
    route=RouteData(5.0,60.0,[Station("A",0),Station("B",5)], [Segment(0,5,0)], (0,0), [], {}, default_operating_conditions())
    records={}
    for direction in ("forward","reverse"):
        train=TrainParameters("sym",1000,300,400,1.05,DavisCoefficients(5,.1,.002),3000,direction=direction)
        out=run_train_simulation(route,train,delta_t_s=5)
        records[direction]={"steps":len(out),"time_s":out[-1].time_s,"terminal_km":out[-1].position_km,"energy_proxy":sum(abs(x.power_kW) for x in out)}
    f,r=records["forward"],records["reverse"]
    checks={"steps_equal":f["steps"]==r["steps"],"time_equal":f["time_s"]==r["time_s"],"energy_equal":abs(f["energy_proxy"]-r["energy_proxy"])<=1e-6,"terminals_mirrored":f["terminal_km"]==5.0 and r["terminal_km"]==0.0}
    return {"passed":all(checks.values()),"checks":checks,"records":records}


def terminal_soc_targets():
    """函数 terminal_soc_targets：执行该模块中的相关处理逻辑。"""
    b=BatteryStorageParameters(100,1,0,1,1e6,1e6)
    lim=_limit()
    rows=[{0:(-3600,1.0,"A",10,"S")},{10:(3600,1.0,"A",10,"S")}]
    exact=EnergySettlementSystem(b,settlement_time_step_s=10,initial_soc_kwh=0,target_final_soc_kwh=0,allow_direct_use=False,allow_storage=True,power_arm_limits=lim).settle(rows)
    short=EnergySettlementSystem(b,settlement_time_step_s=10,initial_soc_kwh=10,target_final_soc_kwh=20,allow_direct_use=False,allow_storage=True,power_arm_limits=lim).settle([{}])
    checks={"exact_target_no_penalty":exact.final_soc_shortfall_kwh==0 and exact.final_soc_excess_kwh==0,"shortfall_reported":short.final_soc_shortfall_kwh==10}
    return {"passed":all(checks.values()),"checks":checks}


def resource_properties():
    """函数 resource_properties：执行该模块中的相关处理逻辑。"""
    base=[ResourceInterval("R","R","section",1,"a","heavy","up",0,10,0,1,"a"),ResourceInterval("R","R","section",1,"b","heavy","up",10,20,0,1,"b")]
    overlap=[ResourceInterval("R","R","section",1,"a","heavy","up",0,10,0,1,"a"),ResourceInterval("R","R","section",1,"b","heavy","up",8,20,0,1,"b")]
    c1=detect_resource_conflicts(base,ResourceConfig(min_overlap_s=0)); c2=detect_resource_conflicts(overlap,ResourceConfig(min_overlap_s=0))
    cap1=resource_capacity_overlap_violation_s(base,ResourceConfig()); cap2=resource_capacity_overlap_violation_s(overlap,ResourceConfig())
    checks={"boundary_no_conflict":not c1,"overlap_conflict":bool(c2),"violation_increases":cap2>=cap1}
    return {"passed":all(checks.values()),"checks":checks,"violations":{"base":cap1,"overlap":cap2}}


def run_checks(output_dir: Path):
    """函数 run_checks：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True,exist_ok=True)
    result={"schema_version":"1.0","randomized":randomized_properties(),"bucket_boundaries":bucket_boundaries(),"direction_symmetry":direction_symmetry(),"terminal_soc_targets":terminal_soc_targets(),"resource_properties":resource_properties()}
    result["passed"]=all(v["passed"] for k,v in result.items() if k!="schema_version")
    (output_dir/"algorithm_property_summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# 算法属性测试", "",f"- 总结：`{'PASS' if result['passed'] else 'FAIL'}`","","| 类别 | 状态 |","|---|---|"]
    for key in ("randomized","bucket_boundaries","direction_symmetry","terminal_soc_targets","resource_properties"):
        lines.append(f"| {key} | {'PASS' if result[key]['passed'] else 'FAIL'} |")
    (output_dir/"ALGORITHM_PROPERTY_CHECKS.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return result


def main():
    """函数 main：执行该模块中的相关处理逻辑。"""
    p=argparse.ArgumentParser(description="运行算法随机化、时间边界、方向、终端 SOC 和资源属性测试")
    p.add_argument("--output-dir",type=Path,default=Path("outputs")/"algorithm_property_checks")
    a=p.parse_args(); r=run_checks(a.output_dir); print(json.dumps({"passed":r["passed"],"output_dir":str(a.output_dir)},ensure_ascii=False)); return 0 if r["passed"] else 1

if __name__=="__main__": raise SystemExit(main())
