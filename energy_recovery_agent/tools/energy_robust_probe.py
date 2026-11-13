# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
import time, json
import run_dispatch_case as rdc
from rolling_optimizer import ScheduleTemplate, generate_schedule, evaluate_schedule, robust_evaluate_schedule, default_scenarios
from scheduler_nsga2 import build_power_cache

out = Path("outputs/_energy_probe")
out.mkdir(parents=True, exist_ok=True)
log = out / "probe_log.txt"

def p(msg):
    """函数 p：执行该模块中的相关处理逻辑。"""
    print(msg, flush=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")

log.write_text("", encoding="utf-8")
t0 = time.time()
case = rdc.load_case_inputs(Path("data/real_shuohuang"), out)
p(f"load {time.time()-t0:.2f}")
trains = rdc.apply_train_mass_scenario(case.trains, None)
battery = rdc.apply_battery_scenario(
    case.battery,
    capacity_kwh=None,
    max_charge_power_kW=None,
    max_discharge_power_kW=None,
    round_trip_efficiency=None,
)
p(f"battery {battery.capacity_kwh} {battery.max_charge_power_kW}")
power_arm_path = Path("data/real_shuohuang/power_arm_intervals.csv")
t1 = time.time()
heavy_cache = build_power_cache(
    trains["Heavy"], case.route, power_arm_interval_path=power_arm_path, storage_sections=case.storage_sections
)
p(f"heavy cache {time.time()-t1:.2f} n={len(heavy_cache.times)} storage={sum(1 for x in heavy_cache.storage_section_ids if x)}")
t2 = time.time()
empty_cache = build_power_cache(
    trains["Empty"], case.route, power_arm_interval_path=power_arm_path, storage_sections=case.storage_sections
)
p(f"empty cache {time.time()-t2:.2f} n={len(empty_cache.times)} storage={sum(1 for x in empty_cache.storage_section_ids if x)}")
sett0 = rdc.make_settlement_system(
    battery, case.route, 10, 0.0, None, 0.0, 0.0, 0.0, rdc.ENERGY_SCENARIO_STORAGE_NO_DIRECT, case.power_arm_limits
)
sett1 = rdc.make_settlement_system(
    battery, case.route, 10, 0.0, None, 0.0, 0.0, 0.05, rdc.ENERGY_SCENARIO_STORAGE_NO_DIRECT, case.power_arm_limits
)
candidates = [
    ScheduleTemplate(3300, 2700, 2600, 3, 3),
    ScheduleTemplate(3300, 2700, 2300, 3, 3),
    ScheduleTemplate(3300, 2700, 2600, 3, 3, storage_align_shift_s=600),
    ScheduleTemplate(3300, 2700, 2600, 3, 3, storage_align_shift_s=-600),
    ScheduleTemplate(3000, 3000, 2300, 3, 3),
    ScheduleTemplate(3600, 3000, 3000, 3, 3),
    ScheduleTemplate(3900, 3600, 3300, 3, 3),
    ScheduleTemplate(3300, 2700, 3200, 3, 3, storage_align_shift_s=900),
]
rows = []
for tpl in candidates:
    sch = generate_schedule(tpl)
    s0 = evaluate_schedule(
        sch, heavy_cache, empty_cache, sett0, case.route.signaling_system,
        resource_model=case.resource_model, storage_sections=case.storage_sections,
        min_depart_gap_s=900, target_gap_s=3000, energy_scenario=rdc.ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    )
    s1 = evaluate_schedule(
        sch, heavy_cache, empty_cache, sett1, case.route.signaling_system,
        resource_model=case.resource_model, storage_sections=case.storage_sections,
        min_depart_gap_s=900, target_gap_s=3000, energy_scenario=rdc.ENERGY_SCENARIO_STORAGE_NO_DIRECT,
    )
    row = dict(
        h=tpl.heavy_headway_s, e=tpl.empty_headway_s, p=tpl.heavy_empty_phase_s,
        f=tpl.flex_zone_hold_s, s=tpl.storage_align_shift_s, feas=s0.feasible,
        conflicts=s0.resource_conflict_count, wasted=round(s0.wasted_kwh, 3),
        grid=round(s0.grid_kwh, 3), charge=round(s0.battery_charge_kwh, 3),
        cost0=round(s0.total_cost, 3), cost_pen=round(s1.total_cost, 3),
        cv=round(s0.constraint_violation, 6),
    )
    rows.append(row)
    p(row)

robust_rows = []
for tpl in [
    ScheduleTemplate(3300, 2700, 2600, 3, 3),
    ScheduleTemplate(3000, 3000, 2300, 3, 3),
    ScheduleTemplate(3600, 3300, 3000, 3, 3),
    ScheduleTemplate(3900, 3600, 3300, 3, 3),
    ScheduleTemplate(4200, 3900, 3600, 3, 3),
]:
    sch = generate_schedule(tpl)
    rs = robust_evaluate_schedule(
        sch, default_scenarios(), heavy_cache, empty_cache, sett1, case.route.signaling_system,
        resource_model=case.resource_model, storage_sections=case.storage_sections,
        min_depart_gap_s=900, target_gap_s=3000,
    )
    row = dict(
        h=tpl.heavy_headway_s, e=tpl.empty_headway_s, p=tpl.heavy_empty_phase_s,
        feas=rs.feasible, conflicts=rs.resource_conflict_count,
        cv=round(rs.constraint_violation, 6), cost=round(rs.total_cost, 3),
        wasted=round(rs.wasted_kwh, 3),
    )
    robust_rows.append(row)
    p(("robust", row))

(out / "probe_results.json").write_text(
    json.dumps({"rows": rows, "robust": robust_rows}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
p(f"done {time.time()-t0:.2f}")
