"""验证数据库逐设备额定参数直接控制储能结算。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from argparse import Namespace
from uuid import uuid4
import json
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_ingestion import _load_battery
from database.snapshots import materialize_file_records, record_from_bytes
from database.dataset_projection import project_dataset
from database.postgres import project_dataset_records
from database.worker import bind_database_storage_parameters
from energy_settlement import EnergySettlementSystem, StorageDeviceRuntimeState
from power_arm_electrical_limits import PowerArmElectricalLimit
from run_dispatch_case import apply_battery_scenario, resolve_storage_preset_search


DEVICE_ROWS = [
    {
        "storage_section_id": "S1", "capacity_kwh": 150.0,
        "max_charge_power_kw": 36.0, "max_discharge_power_kw": 18.0,
        "charge_efficiency": 0.8, "discharge_efficiency": 0.8,
        "initial_soc_kwh": 40.0, "min_soc_kwh": 20.0, "max_soc_kwh": 120.0,
        "available": True, "data_status": "official", "source_note": "数据库设备S1",
        "start_km": 0.0, "end_km": 1.0,
    },
    {
        "storage_section_id": "S2", "capacity_kwh": 50.0,
        "max_charge_power_kw": 72.0, "max_discharge_power_kw": 36.0,
        "charge_efficiency": 0.5, "discharge_efficiency": 0.5,
        "initial_soc_kwh": 10.0, "min_soc_kwh": 10.0, "max_soc_kwh": 45.0,
        "available": False, "data_status": "official", "source_note": "数据库设备S2",
        "start_km": 1.0, "end_km": 2.0,
    },
]


def _database_battery():
    with TemporaryDirectory(prefix="database_storage_model_") as temp_name:
        root = Path(temp_name)
        battery_payload = json.dumps({
            "capacity_kwh": 9999, "max_charge_power_kW": 9999,
            "max_discharge_power_kW": 9999, "round_trip_efficiency": 1,
            "depreciation_cost_per_kwh": 0, "grid_price_per_kwh": 1,
        }).encode("utf-8")
        records = bind_database_storage_parameters(
            (record_from_bytes("battery.json", battery_payload),), DEVICE_ROWS
        )
        materialize_file_records(records, root)
        return _load_battery(root)


def _system(*, states=None):
    battery = _database_battery()
    assert battery.capacity_kwh == 200.0
    assert battery.max_charge_power_kW == 108.0
    assert battery.max_discharge_power_kW == 54.0
    assert len(battery.storage_devices) == 2
    return EnergySettlementSystem(
        battery, settlement_time_step_s=100, allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={
            "A1": PowerArmElectricalLimit(storage_available=True, storage_section_id="S1"),
            "A2": PowerArmElectricalLimit(storage_available=True, storage_section_id="S2"),
        },
        storage_runtime_states=states,
    )


def main() -> int:
    with TemporaryDirectory(prefix="database_storage_projection_") as temp_name:
        root = Path(temp_name)
        (root / "battery.json").write_text(json.dumps({
            "capacity_kwh": 9999, "max_charge_power_kW": 9999,
            "max_discharge_power_kW": 9999, "round_trip_efficiency": 1,
        }), encoding="utf-8")
        (root / "energy_transfer_zones.csv").write_text(
            "start_km,end_km,storage_section_id\n0,1,S1\n1,2,S2\n",
            encoding="utf-8",
        )
        (root / "storage_devices.json").write_text(
            json.dumps(DEVICE_ROWS, ensure_ascii=False), encoding="utf-8"
        )
        projected = project_dataset(uuid4(), root)["storage_devices"]
        (root / "storage_devices.json").write_text(
            json.dumps(DEVICE_ROWS[:1], ensure_ascii=False), encoding="utf-8"
        )
        try:
            project_dataset(uuid4(), root)
        except ValueError:
            pass
        else:
            raise AssertionError("逐设备文件缺少储能区段时应在发布投影阶段拒绝")
        (root / "storage_devices.json").unlink()
        (root / "energy_transfer_zones.csv").write_text(
            "start_km,end_km,zone_id,implementation_status\n0,1,S1,\n1,2,FLEX,implemented\n",
            encoding="utf-8",
        )
        legacy = project_dataset(uuid4(), root)["storage_devices"]
        assert [row["storage_code"] for row in legacy] == ["S1"]
        assert legacy[0]["capacity_kwh"] == 9999
    assert [item["capacity_kwh"] for item in projected] == [150.0, 50.0]
    assert [item["charge_efficiency"] for item in projected] == [0.8, 0.5]
    assert [item["min_soc_kwh"] for item in projected] == [20.0, 10.0]

    base_records = (
        record_from_bytes("battery.json", json.dumps({
            "capacity_kwh": 9999, "max_charge_power_kW": 9999,
            "max_discharge_power_kW": 9999, "round_trip_efficiency": 1,
        }).encode("utf-8")),
        record_from_bytes(
            "energy_transfer_zones.csv",
            b"start_km,end_km,storage_section_id\n0,1,S1\n1,2,S2\n",
        ),
    )
    merged_projection = project_dataset_records(
        uuid4(), bind_database_storage_parameters(base_records, DEVICE_ROWS)
    )["storage_devices"]
    assert [item["capacity_kwh"] for item in merged_projection] == [150.0, 50.0]

    system = _system()
    storage_search = resolve_storage_preset_search(
        Namespace(
            enable_storage_preset_search=True,
            disable_storage_preset_search=False,
            storage_preset_ids="",
        ),
        _database_battery(),
    )
    assert storage_search["enabled"] is False
    assert storage_search["uses_database_device_parameters"] is True
    try:
        apply_battery_scenario(
            _database_battery(), capacity_kwh=300.0,
            max_charge_power_kW=None, max_discharge_power_kW=None,
            round_trip_efficiency=None,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("数据库逐设备参数不应被聚合物理参数覆盖")
    charged = system.settle([{0: (-100.0, 1.0, "A1", 100.0, "S1")}])
    assert charged.initial_soc_by_storage_kwh == {"S1": 40.0, "S2": 10.0}
    assert abs(charged.battery_charge_by_storage_kwh["S1"] - 1.0) < 1e-9
    assert abs(charged.final_soc_by_storage_kwh["S1"] - 40.8) < 1e-9
    assert charged.battery_charge_by_storage_kwh["S2"] == 0.0
    assert charged.storage_parameters_by_id["S1"]["capacity_kwh"] == 150.0
    assert charged.storage_parameters_by_id["S1"]["max_soc_kwh"] == 120.0
    assert charged.storage_parameters_by_id["S2"]["available"] is False

    discharged = system.settle([{0: (100.0, 1.0, "A1", 100.0, "S1")}])
    assert abs(discharged.battery_discharge_by_storage_kwh["S1"] - 0.5) < 1e-9
    assert abs(discharged.final_soc_by_storage_kwh["S1"] - 39.375) < 1e-9

    at_minimum = _system(states=(
        StorageDeviceRuntimeState("S1", 20.0),
        StorageDeviceRuntimeState("S2", 10.0),
    )).settle([{0: (100.0, 1.0, "A1", 100.0, "S1")}])
    assert at_minimum.battery_discharge_kwh == 0.0
    assert at_minimum.final_soc_by_storage_kwh["S1"] == 20.0

    for invalid_states in (
        (StorageDeviceRuntimeState("S1", 19.0), StorageDeviceRuntimeState("S2", 10.0)),
        (StorageDeviceRuntimeState("S1", 121.0), StorageDeviceRuntimeState("S2", 10.0)),
        (StorageDeviceRuntimeState("S1", 40.0, True, 37.0), StorageDeviceRuntimeState("S2", 10.0)),
    ):
        try:
            _system(states=invalid_states).settle([])
        except ValueError:
            pass
        else:
            raise AssertionError(f"数据库设备额定边界未阻止非法实时状态：{invalid_states}")

    print("database storage device binding verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
