# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

"""Operational checks that do not require official field data.

This module validates the future real-time state contract, explicit degraded
mode behavior, result attribution, manifest compatibility and a performance
regression threshold. It does not connect to production systems.
"""

import argparse, json, math, statistics, sys, time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from data_quality_validator import validate_all
from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from realtime_state_guard import validate_realtime_batch
from train_simulator import BatteryStorageParameters


def realtime_contract_check() -> dict[str, Any]:
    """函数 realtime_contract_check：执行该模块中的相关处理逻辑。"""
    valid=[{"timestamp_s":0,"train_id":"T1","direction":"forward","position_km":0,"speed_mps":10,"power_kW":1000,"soc_kwh":2},{"timestamp_s":10,"train_id":"T1","direction":"forward","position_km":0.1,"speed_mps":10,"power_kW":800,"soc_kwh":2.5}]
    # 先保留有效基线，使批次级时间戳单调规则和逐行枚举/范围检查都得到覆盖。
    # 无效行彼此独立，格式错误的行不能更新历史状态。
    invalid=[valid[0],dict(valid[1],timestamp_s=0),dict(valid[1],direction="sideways"),dict(valid[1],position_km=-1)]
    good=validate_realtime_batch(valid,capacity_kwh=10); bad=validate_realtime_batch(invalid,capacity_kwh=10)
    checks={"valid_batch_accepts":good["valid"],"invalid_batch_rejects":not bad["valid"],"invalid_count_reported":bad["error_count"]==3}
    return {"passed":all(checks.values()),"checks":checks,"valid":good,"invalid":bad}


def degradation_policy_check() -> dict[str, Any]:
    # 严格模式必须拒绝空候选目录；本检查不会静默推断降级或默认模式。
    """函数 degradation_policy_check：执行该模块中的相关处理逻辑。"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); report=validate_all(root,root/"source",root/"missing.xlsx",require_official_data=True)
        blocked=not report.is_valid and len(report.errors)>0
    return {"passed":blocked,"strict_mode_blocks_missing_data":blocked,"error_count":len(report.errors)}


def result_attribution_check() -> dict[str, Any]:
    """函数 result_attribution_check：执行该模块中的相关处理逻辑。"""
    battery=BatteryStorageParameters(20,.9,0,1,3600,3600)
    limits={"A":PowerArmElectricalLimit(max_traction_supply_kw=1e6,max_regen_absorption_kw=1e6,storage_available=True,storage_section_id="S")}
    result=EnergySettlementSystem(battery,settlement_time_step_s=10,allow_direct_use=False,allow_storage=True,power_arm_limits=limits).settle([{0:(-3600,1,"A",10,"S")},{10:(3600,1,"A",10,"S")}])
    rows=[{"source":"regen","metric":"total_gen_kwh","value":result.total_gen_kwh,"reason":"再生制动功率序列"},{"source":"storage","metric":"battery_charge_kwh","value":result.battery_charge_kwh,"reason":"储能区段和充电功率限制"},{"source":"storage","metric":"battery_discharge_kwh","value":result.battery_discharge_kwh,"reason":"后续牵引需求和 SOC"},{"source":"grid","metric":"grid_kwh","value":result.grid_kwh,"reason":"储能无法覆盖的牵引需求"},{"source":"loss","metric":"wasted_kwh","value":result.wasted_kwh,"reason":"容量/功率/供电边界剩余"}]
    valid=all(str(row["source"]).strip() and str(row["reason"]).strip() and math.isfinite(float(row["value"])) for row in rows)
    checks={"rows_have_reasons":valid,"generation_reconciles":abs(result.total_gen_kwh-(result.battery_charge_kwh+result.wasted_kwh))<=1e-9,"traction_reconciles":abs(result.total_con_kwh-(result.battery_discharge_kwh+result.grid_kwh))<=1e-9}
    return {"passed":all(checks.values()),"checks":checks,"rows":rows}


def manifest_compatibility_check() -> dict[str, Any]:
    """函数 manifest_compatibility_check：执行该模块中的相关处理逻辑。"""
    accepted=[]; rejected=[]
    for payload in ({"schema_version":"1.1","status":"success","return_code":0},{"schema_version":"1.1","status":"failed","return_code":1},{"schema_version":"2.0","status":"success","return_code":0},{"schema_version":"bad","status":"success","return_code":0}):
        version=str(payload.get("schema_version",""))
        ok=version=="1.1" and payload.get("status") in {"success","failed"} and isinstance(payload.get("return_code"),int)
        (accepted if ok else rejected).append(payload)
    checks={"known_versions_accepted":len(accepted)==2,"future_or_malformed_rejected":len(rejected)==2}
    return {"passed":all(checks.values()),"checks":checks,"accepted":accepted,"rejected":rejected}


def performance_gate() -> dict[str, Any]:
    """函数 performance_gate：执行该模块中的相关处理逻辑。"""
    limits={"A":PowerArmElectricalLimit(max_traction_supply_kw=1e6,max_regen_absorption_kw=1e6,storage_available=True,storage_section_id="S")}
    system=EnergySettlementSystem(BatteryStorageParameters(100,.9,0,1,3600,3600),settlement_time_step_s=10,allow_direct_use=False,allow_storage=True,power_arm_limits=limits)
    series=[{i*10:((-3600 if i%2==0 else 1800),1,"A",10,"S")} for i in range(300)]; times=[]
    for _ in range(5): start=time.perf_counter(); system.settle(series); times.append(time.perf_counter()-start)
    median=statistics.median(times)
    return {"passed":median<0.2,"median_s":round(median,6),"max_s":round(max(times),6),"repetitions":5}


def run_checks(output_dir: Path):
    """函数 run_checks：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True,exist_ok=True)
    result={"schema_version":"1.0","realtime_contract":realtime_contract_check(),"degradation_policy":degradation_policy_check(),"result_attribution":result_attribution_check(),"manifest_compatibility":manifest_compatibility_check(),"performance_gate":performance_gate()}
    result["passed"]=all(v["passed"] for k,v in result.items() if k!="schema_version")
    (output_dir/"operational_readiness_summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# 算法运行准备度检查","",f"- 总结：`{'PASS' if result['passed'] else 'FAIL'}`","","| 检查 | 状态 |","|---|---|"]
    for key in result:
        if key not in ("schema_version","passed"): lines.append(f"| {key} | {'PASS' if result[key]['passed'] else 'FAIL'} |")
    (output_dir/"OPERATIONAL_READINESS_CHECKS.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return result


def main():
    """函数 main：执行该模块中的相关处理逻辑。"""
    p=argparse.ArgumentParser(description="运行实时契约、降级策略、结果解释、版本兼容和性能门禁")
    p.add_argument("--output-dir",type=Path,default=Path("outputs")/"operational_readiness_checks")
    a=p.parse_args(); r=run_checks(a.output_dir); print(json.dumps({"passed":r["passed"],"output_dir":str(a.output_dir)},ensure_ascii=False)); return 0 if r["passed"] else 1

if __name__=="__main__": raise SystemExit(main())
