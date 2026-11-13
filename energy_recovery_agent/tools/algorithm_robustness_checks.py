# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

"""Deterministic robustness checks for edge cases and evaluation resolution."""

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from train_simulator import BatteryStorageParameters


def _battery(capacity=20.0, efficiency=0.9, charge=3600.0, discharge=3600.0):
    """函数 _battery：执行该模块中的相关处理逻辑。"""
    return BatteryStorageParameters(capacity, efficiency, 0.0, 1.0, charge, discharge)


def _limit(storage=True, arm="A", section="S"):
    """函数 _limit：执行该模块中的相关处理逻辑。"""
    return {arm: PowerArmElectricalLimit(
        max_traction_supply_kw=1e6,
        max_regen_absorption_kw=1e6,
        storage_available=storage,
        storage_section_id=section if storage else "",
    )}


def _settle(step, series, battery=None, storage=True, limits=None):
    """函数 _settle：执行该模块中的相关处理逻辑。"""
    system = EnergySettlementSystem(
        battery or _battery(), settlement_time_step_s=step,
        allow_direct_use=False, allow_storage=storage,
        power_arm_limits=limits if limits is not None else _limit(storage),
    )
    return system.settle(series)


def extreme_cases() -> dict[str, Any]:
    """函数 extreme_cases：执行该模块中的相关处理逻辑。"""
    empty = _settle(10, [])
    no_regen = _settle(10, [{0: (3600.0, 1.0, "A", 10, "S")}])
    zero_storage = _settle(10, [{0: (-3600.0, 1.0, "A", 10, "S"), 10: (3600.0, 1.0, "A", 10, "S")}], _battery(0.0, 0.9, 0.0, 0.0), False, _limit(False))
    full_system = EnergySettlementSystem(
        _battery(10.0), settlement_time_step_s=10, initial_soc_kwh=10.0,
        allow_direct_use=False, allow_storage=True, power_arm_limits=_limit(True),
    )
    full_soc = full_system.settle([{0: (-3600.0, 1.0, "A", 10, "S")}])
    # 没有储能几何标签表示供电臂未知或不可用，不能吸收能量。
    outside_arm = _settle(10, [{0: (-3600.0, 1.0, "UNKNOWN", 1.0, "")}], _battery(), True, _limit(False))
    zero_efficiency_system = EnergySettlementSystem(
        _battery(10.0, 0.0), settlement_time_step_s=10, initial_soc_kwh=5.0,
        allow_direct_use=False, allow_storage=True, power_arm_limits=_limit(True),
    )
    zero_efficiency = zero_efficiency_system.settle([
        {0: (-3600.0, 1.0, "A", 10, "S"), 10: (3600.0, 1.0, "A", 10, "S")}
    ])
    exact_limit = _settle(
        10,
        [{0: (3600.0, 1.0, "A", 10, "")}],
        _battery(0.0),
        False,
        {"A": PowerArmElectricalLimit(max_traction_supply_kw=3600.0, max_regen_absorption_kw=3600.0, storage_available=False)},
    )
    huge_finite = _settle(
        86400,
        [{0: (-1.0e12, 1.0, "A", 86400, "")}],
        _battery(0.0),
        False,
        {"A": PowerArmElectricalLimit(max_traction_supply_kw=1.0e12, max_regen_absorption_kw=1.0e12, storage_available=False)},
    )
    tiny_finite = _settle(
        1,
        [{0: (1.0e-6, 1.0, "A", 1, "")}],
        _battery(0.0),
        False,
        {"A": PowerArmElectricalLimit(max_traction_supply_kw=1.0, max_regen_absorption_kw=1.0, storage_available=False)},
    )
    isolated_sections = EnergySettlementSystem(
        _battery(20.0, 0.9, 7200.0, 7200.0),
        settlement_time_step_s=10,
        initial_soc_kwh=0.0,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={
            "A": PowerArmElectricalLimit(max_traction_supply_kw=1.0e6, max_regen_absorption_kw=1.0e6, storage_available=True, storage_section_id="S1"),
            "B": PowerArmElectricalLimit(max_traction_supply_kw=1.0e6, max_regen_absorption_kw=1.0e6, storage_available=True, storage_section_id="S2"),
        },
    ).settle([
        {0: (-3600.0, 1.0, "A", 10, "S1")},
        {0: (-3600.0, 1.0, "B", 10, "S2")},
    ])
    checks = {
        "empty_series_zero_ledger": all(
            getattr(empty, field) == 0.0
            for field in ("total_gen_kwh", "total_con_kwh", "battery_charge_kwh", "battery_discharge_kwh", "wasted_kwh", "grid_kwh")
        ),
        "no_regen_no_charge": no_regen.battery_charge_kwh == 0.0 and no_regen.wasted_kwh == 0.0,
        "zero_storage_no_exchange": zero_storage.battery_charge_kwh == 0.0 and zero_storage.battery_discharge_kwh == 0.0,
        "full_soc_regen_wasted": full_soc.battery_charge_kwh == 0.0 and full_soc.wasted_kwh > 0.0,
        "outside_arm_not_absorbed": outside_arm.battery_charge_kwh == 0.0 and outside_arm.wasted_kwh > 0.0,
        "zero_efficiency_disables_exchange": zero_efficiency.battery_charge_kwh == 0.0
        and zero_efficiency.battery_discharge_kwh == 0.0
        and zero_efficiency.wasted_kwh > 0.0
        and zero_efficiency.grid_kwh > 0.0,
        "exact_power_limit_no_violation": exact_limit.traction_supply_excess_kwh == 0.0,
        "huge_finite_energy_stays_finite": all(
            math.isfinite(getattr(huge_finite, field))
            for field in ("total_gen_kwh", "wasted_kwh", "total_cost")
        ) and abs(huge_finite.total_gen_kwh - huge_finite.wasted_kwh) <= 1e-6,
        "tiny_finite_energy_preserved": tiny_finite.total_con_kwh > 0.0
        and abs(tiny_finite.total_con_kwh - tiny_finite.grid_kwh) <= 1e-18,
        "multiple_storage_sections_isolated": set(isolated_sections.final_soc_by_storage_kwh) == {"S1", "S2"}
        and all(value > 0.0 for value in isolated_sections.final_soc_by_storage_kwh.values())
        and abs(sum(isolated_sections.final_soc_by_storage_kwh.values()) - isolated_sections.final_soc_kwh) <= 1e-9,
    }
    return {"passed": all(checks.values()), "checks": checks, "observed": {
        "no_regen": {"charge": no_regen.battery_charge_kwh, "wasted": no_regen.wasted_kwh},
        "zero_storage": {"charge": zero_storage.battery_charge_kwh, "discharge": zero_storage.battery_discharge_kwh},
        "full_soc": {"charge": full_soc.battery_charge_kwh, "wasted": full_soc.wasted_kwh},
        "outside_arm": {"charge": outside_arm.battery_charge_kwh, "wasted": outside_arm.wasted_kwh},
        "zero_efficiency": {"charge": zero_efficiency.battery_charge_kwh, "discharge": zero_efficiency.battery_discharge_kwh},
        "exact_limit": {"traction_excess": exact_limit.traction_supply_excess_kwh},
        "huge_finite": {"generated": huge_finite.total_gen_kwh, "wasted": huge_finite.wasted_kwh},
        "tiny_finite": {"consumed": tiny_finite.total_con_kwh, "grid": tiny_finite.grid_kwh},
        "isolated_sections": isolated_sections.final_soc_by_storage_kwh,
    }}


def resolution_consistency() -> dict[str, Any]:
    # 当边界同时对齐两种分辨率时，带显式时长的恒功率样本不应受时间桶大小影响。
    """函数 resolution_consistency：执行该模块中的相关处理逻辑。"""
    series = [{0: (-1800.0, 1.0, "A", 20, "S"), 20: (900.0, 1.0, "A", 20, "S")}]
    fine = _settle(1, series)
    coarse = _settle(10, series)
    fields = ("total_gen_kwh", "total_con_kwh", "battery_charge_kwh", "battery_discharge_kwh", "wasted_kwh", "grid_kwh", "final_soc_kwh")
    differences = {field: abs(getattr(fine, field) - getattr(coarse, field)) for field in fields}
    return {"passed": all(value <= 1e-9 for value in differences.values()), "differences": differences}


def deterministic_replay() -> dict[str, Any]:
    # 结算层是确定性的；重放相同生成序列必须得到完全相同的机器数值。
    """函数 deterministic_replay：执行该模块中的相关处理逻辑。"""
    rng = random.Random(20260901)
    samples = {}
    for index in range(8):
        samples[index * 10] = (rng.choice((-3600.0, -1800.0, 900.0, 1800.0)), 1.0, "A", 10, "S")
    left = _settle(10, [samples])
    right = _settle(10, [dict(samples)])
    fields = ("total_gen_kwh", "total_con_kwh", "battery_charge_kwh", "battery_discharge_kwh", "wasted_kwh", "grid_kwh", "final_soc_kwh", "total_cost")
    differences = {field: abs(getattr(left, field) - getattr(right, field)) for field in fields}
    return {"passed": all(value == 0.0 for value in differences.values()), "differences": differences}


def run_checks(output_dir: Path) -> dict[str, Any]:
    """函数 run_checks：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": "1.0", "extreme_cases": extreme_cases(), "resolution_consistency": resolution_consistency(), "deterministic_replay": deterministic_replay()}
    result["passed"] = all(section["passed"] for key, section in result.items() if key != "schema_version")
    (output_dir / "algorithm_robustness_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 算法极端场景、分辨率和复现检查", "", f"- 总结：`{'PASS' if result['passed'] else 'FAIL'}`", "", "| 检查 | 状态 |", "|---|---|", f"| 极端场景退化 | {'PASS' if result['extreme_cases']['passed'] else 'FAIL'} |", f"| 快速/精细结算一致性 | {'PASS' if result['resolution_consistency']['passed'] else 'FAIL'} |", f"| 确定性重放 | {'PASS' if result['deterministic_replay']['passed'] else 'FAIL'} |"]
    (output_dir / "ALGORITHM_ROBUSTNESS_CHECKS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="运行算法极端场景、结算分辨率和确定性复现检查")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs") / "algorithm_robustness_checks")
    args = parser.parse_args()
    result = run_checks(args.output_dir)
    print(json.dumps({"passed": result["passed"], "output_dir": str(args.output_dir)}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
