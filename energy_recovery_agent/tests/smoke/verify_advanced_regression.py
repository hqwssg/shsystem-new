# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from energy_settlement import EnergySettlementSystem
from result_quality_audit import audit_output_root
from train_simulator import BatteryStorageParameters


def battery(**overrides):
    """函数 battery：执行该模块中的相关处理逻辑。"""
    values = dict(
        capacity_kwh=100.0,
        round_trip_efficiency=0.9,
        depreciation_cost_per_kwh=0.0,
        grid_price_per_kwh=0.0,
        max_charge_power_kW=1000.0,
        max_discharge_power_kW=1000.0,
    )
    values.update(overrides)
    return BatteryStorageParameters(**values)


# 单个时间桶的供电臂限制违反必须表现为未满足牵引需求，同时结果仍须通过能量守恒审计。
system = EnergySettlementSystem(
    battery(), settlement_time_step_s=10,
    power_arm_limits={"A": __import__("power_arm_electrical_limits").PowerArmElectricalLimit(
        max_traction_supply_kw=100.0, max_regen_absorption_kw=1000.0,
    )},
)
result = system.settle([{0: (200.0, 1.0, "A", 10.0)}])
assert result.total_con_kwh == 200.0 * 10.0 / 3600.0
assert result.traction_supply_excess_kwh > 0.0
assert abs(result.total_con_kwh - result.grid_kwh) < 1e-9

# 必须发现非默认调度后缀，且仅含调度结果的输出目录是有效的部分审计目标。
with TemporaryDirectory(prefix="advanced_result_audit_") as temp_name:
    root = Path(temp_name)
    dispatch_dir = root / "dispatch_storage_no_direct_phase1234"
    dispatch_dir.mkdir(parents=True)
    summary = {
        "battery": {"capacity_kwh": 10},
        "baseline": {
            "total_gen_kwh": 10, "total_con_kwh": 5, "direct_used_kwh": 0,
            "battery_charge_kwh": 2, "battery_discharge_kwh": 0,
            "wasted_kwh": 8, "grid_kwh": 5, "traction_supply_excess_kwh": 0,
            "final_soc_kwh": 2, "final_soc_by_storage_kwh": {"S1": 2},
        },
    }
    (dispatch_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    checked = audit_output_root(root)
    assert checked["accepted"] is True, checked

    # 直接传入调度目录时必须审计其中的汇总文件；截断案例必须被拒绝，不能把缺失指标默认为 0。
    direct = audit_output_root(dispatch_dir)
    assert direct["accepted"] is True, direct
    truncated = dict(summary)
    truncated["baseline"] = {"total_gen_kwh": 10}
    (dispatch_dir / "summary.json").write_text(json.dumps(truncated), encoding="utf-8")
    rejected = audit_output_root(dispatch_dir)
    assert rejected["accepted"] is False
    assert any(item["code"] == "missing_dispatch_metrics" for item in rejected["issues"])

print("advanced regression coverage passed")
