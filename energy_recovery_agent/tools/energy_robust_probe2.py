# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
import time, json
import run_dispatch_case as rdc
from rolling_optimizer import ScheduleTemplate, generate_schedule, evaluate_schedule, robust_evaluate_schedule, default_scenarios
from scheduler_nsga2 import build_power_cache

out = Path("outputs/_energy_probe2")
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
p(f"cache ready {time.time()-t0:.1f}")

# 能量竞争检查。
for power in [10000, 2500, 1000, 500]:
    batt = rdc.apply_battery_scenario(case.battery, capacity_kwh=None, max_charge_power_kW=power, max_discharge_power_kW=power, round_trip_efficiency=None)
    sett = rdc.make_settlement_system(batt, case.route, 10, 0.0, None, 0.0, 0.0, 0.05, rdc.ENERGY_SCENARIO_STORAGE_NO_DIRECT, case.power_arm_limits)
    vals = []
    for s in [0, 300, 600, -300, 900]:
        tpl = ScheduleTemplate(3300, 2700, 2600, 3, 3, storage_align_shift_s=s)
        sc = evaluate_schedule(generate_schedule(tpl), heavy_cache, empty_cache, sett, case.route.signaling_system, resource_model=case.resource_model, storage_sections=case.storage_sections, min_depart_gap_s=900, target_gap_s=3000)
        vals.append((s, round(sc.wasted_kwh,2), round(sc.grid_kwh,2), round(sc.battery_charge_kwh,2), sc.feasible))
    p({"power": power, "vals": vals, "unique_wasted": len(set(v[1] for v in vals))})

# 稳健相位扫描。
sett = rdc.make_settlement_system(battery, case.route, 10, 0.0, None, 0.0, 0.0, 0.05, rdc.ENERGY_SCENARIO_STORAGE_NO_DIRECT, case.power_arm_limits)
robust_ok = []
for h,e in [(3300,2700),(3000,3000),(3600,3000),(3300,3000),(3000,2700)]:
    for phase in range(1800, 4001, 200):
        for hold in [0, 120, 300]:
            tpl = ScheduleTemplate(h,e,phase,3,3,flex_zone_hold_s=hold)
            rs = robust_evaluate_schedule(generate_schedule(tpl), default_scenarios(), heavy_cache, empty_cache, sett, case.route.signaling_system, resource_model=case.resource_model, storage_sections=case.storage_sections, min_depart_gap_s=900, target_gap_s=3000)
            if rs.feasible:
                robust_ok.append((h,e,phase,hold, round(rs.constraint_violation,6), round(rs.total_cost,2)))
                p(("ROBUST_OK", h,e,phase,hold))
p({"robust_ok_count": len(robust_ok), "robust_ok": robust_ok[:20], "elapsed": round(time.time()-t0,1)})
(out/"results.json").write_text(json.dumps({"robust_ok": robust_ok}, ensure_ascii=False, indent=2), encoding="utf-8")
