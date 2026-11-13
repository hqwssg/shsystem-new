# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

"""Cross-module, ablation, and monotonicity checks on a small synthetic case.

These checks are deliberately deterministic and do not use official data. They
test relationships that individual unit tests may miss while leaving algorithm
defaults unchanged.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from timetable_energy_audit import evaluate_scenario_time_slices
from timetable_input import TimetableScenario
from train_simulator import BatteryStorageParameters


def _battery(capacity: float = 20.0, efficiency: float = 0.9, power: float = 3600.0) -> BatteryStorageParameters:
    """函数 _battery：执行该模块中的相关处理逻辑。"""
    return BatteryStorageParameters(capacity, efficiency, 0.0, 1.0, power, power)


def _limits() -> dict[str, PowerArmElectricalLimit]:
    """函数 _limits：执行该模块中的相关处理逻辑。"""
    return {"A": PowerArmElectricalLimit(
        max_traction_supply_kw=1e6,
        max_regen_absorption_kw=1e6,
        storage_available=True,
        storage_section_id="S",
    )}


def _system(battery: BatteryStorageParameters, *, storage: bool = True) -> EnergySettlementSystem:
    """函数 _system：执行该模块中的相关处理逻辑。"""
    return EnergySettlementSystem(
        battery=battery,
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=storage,
        power_arm_limits=_limits(),
    )


def _series(traction_kwh: float = 9.0, regen_kwh: float = 10.0) -> list[dict[int, tuple[float, float, str, int, str]]]:
    # 先发生再生、下一时间桶发生牵引：新充入的能量不能在同一时间桶放出，但可服务后续需求。
    """函数 _series：执行该模块中的相关处理逻辑。"""
    return [{
        0: (-regen_kwh * 360.0, 1.0, "A", 10, "S"),
        10: (traction_kwh * 360.0, 1.0, "A", 10, "S"),
    }]


def cross_module_check() -> dict[str, Any]:
    """函数 cross_module_check：执行该模块中的相关处理逻辑。"""
    battery = _battery()
    direct = _system(battery).settle(_series())
    scenario = TimetableScenario("cross", False, True, 20.0, 3600.0, 0.0, 10, "same_power_arm", storage_efficiency=0.9)
    rows = [
        {"power_arm_id": "A", "storage_section_id": "S", "time_window_start_s": 0, "time_window_end_s": 10, "traction_kwh": 0.0, "regen_kwh": 10.0},
        {"power_arm_id": "A", "storage_section_id": "S", "time_window_start_s": 10, "time_window_end_s": 20, "traction_kwh": 9.0, "regen_kwh": 0.0},
    ]
    _settlement_rows, _issues, audited = evaluate_scenario_time_slices(rows, scenario, _limits())
    pairs = {
        "total_gen_kwh": (direct.total_gen_kwh, audited["total_regen_kwh"]),
        "total_con_kwh": (direct.total_con_kwh, audited["total_traction_kwh"]),
        "battery_charge_kwh": (direct.battery_charge_kwh, audited["storage_absorbed_kwh"]),
        "battery_discharge_kwh": (direct.battery_discharge_kwh, audited["storage_discharged_kwh"]),
        "wasted_kwh": (direct.wasted_kwh, audited["wasted_kwh"]),
        "grid_kwh": (direct.grid_kwh, audited["grid_kwh"]),
        "final_soc_kwh": (direct.final_soc_kwh, audited["final_soc_kwh"]),
    }
    differences = {key: abs(left - right) for key, (left, right) in pairs.items()}
    passed = all(value <= 1e-5 for value in differences.values())
    return {"passed": passed, "differences": differences, "direct": {key: left for key, (left, _right) in pairs.items()}, "audit": {key: right for key, (_left, right) in pairs.items()}}


def ablation_check() -> dict[str, Any]:
    """函数 ablation_check：执行该模块中的相关处理逻辑。"""
    battery = _battery()
    full = _system(battery, storage=True).settle(_series())
    no_storage = _system(_battery(capacity=0.0, efficiency=0.9, power=0.0), storage=False).settle(_series())
    checks = {
        "storage_reduces_grid": full.grid_kwh <= no_storage.grid_kwh + 1e-9,
        "storage_does_not_increase_waste": full.wasted_kwh <= no_storage.wasted_kwh + 1e-9,
        "direct_use_disabled": abs(full.direct_used_kwh) <= 1e-9,
    }
    return {"passed": all(checks.values()), "checks": checks, "full": {"grid_kwh": full.grid_kwh, "wasted_kwh": full.wasted_kwh, "battery_discharge_kwh": full.battery_discharge_kwh}, "no_storage": {"grid_kwh": no_storage.grid_kwh, "wasted_kwh": no_storage.wasted_kwh}}


def _monotone(values: Iterable[float]) -> bool:
    """函数 _monotone：执行该模块中的相关处理逻辑。"""
    values = list(values)
    return all(values[index] <= values[index - 1] + 1e-9 for index in range(1, len(values)))


def monotonicity_check() -> dict[str, Any]:
    """函数 monotonicity_check：执行该模块中的相关处理逻辑。"""
    capacity_results = [_system(_battery(capacity=capacity)).settle(_series()) for capacity in (5.0, 10.0, 20.0)]
    power_results = [_system(_battery(power=power)).settle(_series()) for power in (900.0, 1800.0, 3600.0)]
    efficiency_results = [_system(_battery(efficiency=efficiency)).settle(_series(traction_kwh=9.0)) for efficiency in (0.5, 0.8, 1.0)]
    groups = {
        "capacity": {"grid_kwh": [r.grid_kwh for r in capacity_results], "wasted_kwh": [r.wasted_kwh for r in capacity_results]},
        "power": {"grid_kwh": [r.grid_kwh for r in power_results], "wasted_kwh": [r.wasted_kwh for r in power_results]},
        "efficiency": {"grid_kwh": [r.grid_kwh for r in efficiency_results], "wasted_kwh": [r.wasted_kwh for r in efficiency_results]},
    }
    checks = {f"{group}_{metric}_nonincreasing": _monotone(values) for group, metrics in groups.items() for metric, values in metrics.items()}
    return {"passed": all(checks.values()), "checks": checks, "values": groups}


def run_checks(output_dir: Path) -> dict[str, Any]:
    """函数 run_checks：执行该模块中的相关处理逻辑。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": "1.0", "cross_module": cross_module_check(), "ablation": ablation_check(), "monotonicity": monotonicity_check()}
    result["passed"] = all(section["passed"] for key, section in result.items() if key != "schema_version")
    (output_dir / "algorithm_consistency_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 算法一致性、消融与单调性检查", "", f"- 总结：`{'PASS' if result['passed'] else 'FAIL'}`", "", "| 检查 | 状态 |", "|---|---|", f"| 模块间交叉验证 | {'PASS' if result['cross_module']['passed'] else 'FAIL'} |", f"| 基线/消融 | {'PASS' if result['ablation']['passed'] else 'FAIL'} |", f"| 参数单调性 | {'PASS' if result['monotonicity']['passed'] else 'FAIL'} |"]
    (output_dir / "ALGORITHM_CONSISTENCY_CHECKS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description="运行算法模块间一致性、消融和参数单调性检查")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs") / "algorithm_consistency_checks")
    args = parser.parse_args()
    result = run_checks(args.output_dir)
    print(json.dumps({"passed": result["passed"], "output_dir": str(args.output_dir)}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
