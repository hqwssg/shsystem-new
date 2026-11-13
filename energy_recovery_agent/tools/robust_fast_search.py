# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
import time, json
import run_dispatch_case as rdc
from rolling_optimizer import ScheduleTemplate, generate_schedule, apply_scenario, DisturbanceScenario
from scheduler_nsga2 import build_power_cache
from resource_constraints import check_schedule_resources

out = Path('outputs/_robust_fast'); out.mkdir(parents=True, exist_ok=True)
t0=time.time()
case = rdc.load_case_inputs(Path('data/real_shuohuang'), out)
trains = rdc.apply_train_mass_scenario(case.trains, None)
power_arm_path = Path('data/real_shuohuang/power_arm_intervals.csv')
heavy_cache = build_power_cache(trains['Heavy'], case.route, power_arm_interval_path=power_arm_path, storage_sections=case.storage_sections)
empty_cache = build_power_cache(trains['Empty'], case.route, power_arm_interval_path=power_arm_path, storage_sections=case.storage_sections)
print('cache', round(time.time()-t0,1), flush=True)

scenarios = [
    DisturbanceScenario('normal'),
    DisturbanceScenario('h60', heavy_delay_s=60),
    DisturbanceScenario('e60', empty_delay_s=60),
    DisturbanceScenario('h120', heavy_delay_s=120),
    DisturbanceScenario('e120', empty_delay_s=120),
    DisturbanceScenario('h180', heavy_delay_s=180),
    DisturbanceScenario('e180', empty_delay_s=180),
    DisturbanceScenario('h300', heavy_delay_s=300),
    DisturbanceScenario('e300', empty_delay_s=300),
]

def ok(schedule, delay_s_h=0, delay_s_e=0):
    """函数 ok：执行该模块中的相关处理逻辑。"""
    sc = apply_scenario(schedule, DisturbanceScenario('x', heavy_delay_s=delay_s_h, empty_delay_s=delay_s_e))
    chk = check_schedule_resources(sc, case.resource_model, heavy_cache, empty_cache)
    return chk.conflict_count == 0, chk.conflict_count, [c.conflict_type + ':' + getattr(c,'location','') for c in chk.conflicts[:3]]

found=[]
# 密集扫描。
for h in range(2700, 4201, 150):
    for e in range(2400, 4201, 150):
        for p in range(1500, 4001, 100):
            for s in (-600, -300, 0, 300, 600):
                tpl=ScheduleTemplate(h,e,p,3,3,storage_align_shift_s=s)
                sch=generate_schedule(tpl)
                base_ok, base_c, _ = ok(sch,0,0)
                if not base_ok:
                    continue
                h60, c1, _ = ok(sch,60,0)
                e60, c2, _ = ok(sch,0,60)
                h120, c3, _ = ok(sch,120,0)
                e120, c4, _ = ok(sch,0,120)
                if h60 and e60:
                    row=dict(h=h,e=e,p=p,s=s,h60=h60,e60=e60,h120=h120,e120=e120,h300=ok(sch,300,0)[0],e300=ok(sch,0,300)[0])
                    found.append(row)
                    print('FOUND', row, flush=True)
                    if h120 and e120:
                        print('LIGHT_ROBUST', row, flush=True)

print('found_count', len(found), 'elapsed', round(time.time()-t0,1), flush=True)
(out/'found.json').write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding='utf-8')
light=[r for r in found if r['h120'] and r['e120']]
hard=[r for r in found if r['h300'] and r['e300']]
print('light_robust', len(light), 'hard_robust', len(hard), flush=True)
if light:
    print('sample light', light[:5], flush=True)
if found and not light:
    print('sample 60-only', found[:5], flush=True)
