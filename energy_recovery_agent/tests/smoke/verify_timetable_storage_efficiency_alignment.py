# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import json
import shutil
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from power_arm_electrical_limits import PowerArmElectricalLimit
from timetable_energy_audit import audit_timetable, evaluate_scenario_time_slices, load_storage_efficiency
from timetable_optimizer import optimize_timetable
from timetable_input import TimetableScenario
from train_simulator import StorageDeviceParameters


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "data_templates" / "running_diagram_template.xlsx"
DATA_DIR = ROOT / "data" / "real_shuohuang"


def _scenario(efficiency=None) -> TimetableScenario:
    """函数 _scenario：执行该模块中的相关处理逻辑。"""
    return TimetableScenario(
        scenario_id="storage_no_direct",
        direct_use_enabled=False,
        storage_enabled=True,
        storage_capacity_kwh=1000.0,
        storage_power_kw=1000.0,
        initial_soc_kwh=0.0,
        settlement_time_step_s=3600,
        transfer_scope="same_power_arm",
        storage_efficiency=efficiency,
    )


def _rows():
    """函数 _rows：执行该模块中的相关处理逻辑。"""
    return [
        {
            "power_arm_id": "A1",
            "storage_section_id": "S1",
            "time_window_start_s": 0,
            "time_window_end_s": 3600,
            "traction_kwh": 0.0,
            "regen_kwh": 100.0,
        }
    ]


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    limit = PowerArmElectricalLimit(
        max_regen_absorption_kw=1000.0,
        storage_available=True,
        storage_section_id="S1",
    )
    limits = {"A1": limit}
    _, _, summary_from_data = evaluate_scenario_time_slices(
        _rows(), _scenario(), limits, default_storage_efficiency=0.8
    )
    if summary_from_data["storage_efficiency"] != 0.8:
        raise AssertionError(summary_from_data)

    _, _, summary_explicit = evaluate_scenario_time_slices(
        _rows(), _scenario(0.7), limits, default_storage_efficiency=0.8
    )
    if summary_explicit["storage_efficiency"] != 0.7:
        raise AssertionError("explicit scenario storage_efficiency must override the data default")

    _, _, summary_disabled = evaluate_scenario_time_slices(
        _rows(), _scenario(), limits, default_storage_efficiency=0.0
    )
    if summary_disabled["storage_efficiency"] != 0.0 or summary_disabled["storage_absorbed_kwh"] != 0.0:
        raise AssertionError("zero battery efficiency must disable usable storage without crashing")

    database_device = StorageDeviceParameters(
        storage_section_id="S1",
        capacity_kwh=1000.0,
        max_charge_power_kw=1000.0,
        max_discharge_power_kw=1000.0,
        charge_efficiency=0.5,
        discharge_efficiency=0.8,
        initial_soc_kwh=20.0,
        min_soc_kwh=10.0,
        max_soc_kwh=900.0,
    )
    _, _, summary_database = evaluate_scenario_time_slices(
        _rows(), _scenario(0.7), limits,
        default_storage_efficiency=0.8,
        storage_device_parameters=(database_device,),
    )
    if summary_database["storage_efficiency"] != 0.4:
        raise AssertionError("运行图评价未采用数据库设备的双向效率")
    if summary_database["initial_soc_kwh"] != 20.0 or summary_database["final_soc_kwh"] != 70.0:
        raise AssertionError("运行图评价未采用数据库设备的初始SOC或充电效率")
    if summary_database["storage_parameters_by_id"]["S1"]["min_soc_kwh"] != 10.0:
        raise AssertionError("运行图评价未保留数据库设备SOC边界")

    with TemporaryDirectory() as temp_name:
        selected_data_dir = Path(temp_name) / "data"
        shutil.copytree(DATA_DIR, selected_data_dir)
        battery_path = selected_data_dir / "battery.json"
        battery = json.loads(battery_path.read_text(encoding="utf-8"))
        battery["round_trip_efficiency"] = 0.8
        battery_path.write_text(json.dumps(battery), encoding="utf-8")
        if load_storage_efficiency(selected_data_dir) != 0.8:
            raise AssertionError("battery.json efficiency was not loaded from the selected data directory")

        battery["round_trip_efficiency"] = 0.0
        battery_path.write_text(json.dumps(battery), encoding="utf-8")
        if load_storage_efficiency(selected_data_dir) != 0.0:
            raise AssertionError("zero battery efficiency should remain a valid disabled-storage value")
        battery["round_trip_efficiency"] = 0.8
        battery_path.write_text(json.dumps(battery), encoding="utf-8")

        audit_summary = audit_timetable(
            TEMPLATE,
            Path(temp_name) / "audit_output",
            selected_data_dir / "power_arm_intervals.csv",
            infrastructure_data_dir=selected_data_dir,
        )
        if not audit_summary.get("valid"):
            raise AssertionError(audit_summary)
        if audit_summary.get("storage_efficiency") != 0.8:
            raise AssertionError(
                "timetable audit did not report the battery efficiency from its selected data directory"
            )

        optimizer_summary = optimize_timetable(
            TEMPLATE,
            Path(temp_name) / "optimizer_output",
            max_candidates=1,
            mode="rule",
            resource_data_dir=selected_data_dir,
        )
        if not optimizer_summary.get("valid") or optimizer_summary.get("storage_efficiency") != 0.8:
            raise AssertionError(
                "timetable optimizer did not use the battery efficiency from its selected data directory"
            )

    print("timetable storage efficiency alignment passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
