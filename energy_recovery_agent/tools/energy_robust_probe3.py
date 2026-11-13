# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
import time, json
import run_dispatch_case as rdc
from rolling_optimizer import (
    ScheduleTemplate, generate_schedule, evaluate_schedule, robust_evaluate_schedule,
    default_scenarios
)
from scheduler_nsga2 import build_power_cache

out = Path("outputs/_energy_probe3")
out.mkdir(parents=True, exist_ok=True)
log = out / "log.txt"

def p(msg):
    """函数 p：执行该模块中的相关处理逻辑。"""
    print(msg, flush=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")

log.write_text("", encoding="utf-8")
t0 = time.time()
case = rdc.load_case_inputs(Path("data/real_shuohuang"), out)
trains = rdc.apply_train_mass_scenario(case.trains, None)
battery = rdc.apply_battery_scenario(case.battery, capacity_kwh=None, max_charge_power_kW=None, max_discharge_power_kW=None, round_trip_efficiency=None)
power_arm_path = Path("data/real_shuohuang/power_arm_intervals.csv")
heavy_cache = build_power_cache(trains["Heavy"], case.route, power_arm_interval_path=power_arm_path, storage_sections=case.storage_sections)
empty_cache = build_power_cache(trains["Empty"], case.route, power_arm_interval_path=power_arm_path, storage_sections=case.storage_sections)
sett = rdc.make_settlement_system(battery, case.route, 10, 0.0, None, 0.0, 0.0, 0.05, rdc.ENERGY_SCENARIO_STORAGE_NO_DIRECT, case.power_arm_limits)
p(f"cache {time.time()-t0:.1f}")

# 储能入口停车的能量敏感性。
hold_rows=[]
for hold in [0,120,240,360,600,900]:
    tpl=ScheduleTemplate(3300,2700,2600,3,3,flex_zone_hold_s=hold)
    sc=evaluate_schedule(generate_schedule(tpl), heavy_cache, empty_cache, sett, case.route.signaling_system, resource_model=case.resource_model, storage_sections=case.storage_sections, min_depart_gap_s=900, target_gap_s=3000)
    row=dict(hold=hold,feas=sc.feasible,wasted=round(sc.wasted_kwh,3),grid=round(sc.grid_kwh,3),charge=round(sc.battery_charge_kwh,3),cost=round(sc.total_cost,3),conflicts=sc.resource_conflict_count)
    hold_rows.append(row); p(row)

# 对有前景模板执行轻度/严格稳健性检查。
robust_rows=[]
for tpl in [
    ScheduleTemplate(3300,2700,2600,3,3),
    ScheduleTemplate(3000,3000,2300,3,3),
    ScheduleTemplate(3300,2700,2600,3,3,flex_zone_hold_s=300),
    ScheduleTemplate(3300,3000,2800,3,3,flex_zone_hold_s=240),
    ScheduleTemplate(3600,3000,3000,3,3),
    ScheduleTemplate(3300,2700,2000,3,3,storage_align_shift_s=300,flex_zone_hold_s=180),
]:
    rs=robust_evaluate_schedule(generate_schedule(tpl), default_scenarios(), heavy_cache, empty_cache, sett, case.route.signaling_system, resource_model=case.resource_model, storage_sections=case.storage_sections, min_depart_gap_s=900, target_gap_s=3000)
    row=dict(h=tpl.heavy_headway_s,e=tpl.empty_headway_s,p=tpl.heavy_empty_phase_s,f=tpl.flex_zone_hold_s,s=tpl.storage_align_shift_s,feas=rs.feasible,conflicts=rs.resource_conflict_count,cv=round(rs.constraint_violation,6),cost=round(rs.total_cost,3),wasted=round(rs.wasted_kwh,3),grid=round(rs.grid_kwh,3))
    robust_rows.append(row); p(("robust", row))

summary={
    "hold_rows": hold_rows,
    "unique_hold_wasted": len(set(r["wasted"] for r in hold_rows)),
    "unique_hold_grid": len(set(r["grid"] for r in hold_rows)),
    "robust_rows": robust_rows,
    "robust_feasible_count": sum(1 for r in robust_rows if r["feas"]),
    "elapsed": round(time.time()-t0,1),
}
(out/"results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
p(summary)
