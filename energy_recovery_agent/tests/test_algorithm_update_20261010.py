"""Regression coverage for the five-task update and its local data adapters."""

from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import io
import json
import sys
from uuid import uuid4

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_ingestion import _load_battery, load_real_data_bundle, validate_real_data_bundle
from database.cli import build_parser
from database.dataset_projection import project_dataset
from database.excel_conflicts import conflict_report
from database.parameters import PARAMETER_FLAGS, validate_run_parameters
from database.snapshots import materialize_file_records, record_from_bytes
from database.user_excel import ExcelConversionError, convert_excel_files, export_version_tables, tables_to_overlays
from database.worker import bind_database_storage_parameters, build_algorithm_command
from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from timetable_input import TimetableScenario
from train_simulator import BatteryStorageParameters, StorageDeviceParameters

UPDATE_DATA = ROOT / "data_templates" / "five_task_update_20261010"
DEVICE = {
    "storage_section_id": "S", "capacity_kwh": 10.0,
    "max_charge_power_kw": 10.0, "max_discharge_power_kw": 0.0,
    "charge_efficiency": 1.0, "discharge_efficiency": 1.0,
    "initial_soc_kwh": 10.0, "min_soc_kwh": 0.0, "max_soc_kwh": 10.0,
    "available": True,
}


def _record_payload(rows):
    return record_from_bytes("storage_devices.json", json.dumps(rows).encode("utf-8"))


def _bound_payload(records, devices):
    bound = bind_database_storage_parameters(records, devices)
    record = next(item for item in bound if item.relative_path == "storage_devices.json")
    return json.loads(record.content)


def _storage_baseline():
    battery = {"capacity_kwh": 145, "round_trip_efficiency": 0.9,
               "depreciation_cost_basis": "charge_energy", "source_document": "equipment.doc"}
    zones = (
        "zone_id,start_km,end_km,max_transfer_power_kW,efficiency,implementation_status,active_in_operational_baseline,source_document,source_sha256,extra_fact\n"
        "FLEX-1,108,219,12000,0.95,implemented,true,facility.doc,abc,keep-me\n"
        "FLEX-2,16,139,12000,0.95,planned,false,facility.doc,def,planned-fact\n"
    )
    return {"battery.json": json.dumps(battery).encode(), "energy_transfer_zones.csv": zones.encode()}


def test_original_five_cli_commands_retained_with_sixth_task(tmp_path):
    platform = tmp_path / "platform"
    platform.mkdir()
    (platform / "timetable.csv").write_text("fixture", encoding="utf-8")
    (platform / "joint_parameter_ranges.json").write_text("{}", encoding="utf-8")
    assert set(PARAMETER_FLAGS) == {
        "dispatch", "timetable_audit", "timetable_optimization",
        "rolling_rescheduling", "joint_parameter_robustness",
        "storage_planning",
    }
    parser = build_parser()
    assert parser.parse_args(["worker-once", "--run-id", str(uuid4())]).run_id
    assert parser.parse_args(["delete-run", "--run-id", str(uuid4())]).command == "delete-run"
    args = parser.parse_args(["create-run", "--project-code", "p", "--version-code", "v", "--run-type", "dispatch", "--parameters-json", "{}", "--idempotency-key", "upgrade-test"])
    assert args.code_version == "2026.10.10.1-mysql-six-tasks"
    with pytest.raises(ValueError):
        validate_run_parameters("storage_planning", {})
    for run_type, parameters in (
        ("dispatch", {}), ("timetable_audit", {"timetable_relative_path": "platform/时刻表.csv"}),
        ("timetable_optimization", {"timetable_relative_path": "platform/时刻表.csv"}),
        ("rolling_rescheduling", {}),
        ("joint_parameter_robustness", {"parameter_ranges_relative_path": "platform/联合参数区间.json"}),
    ):
        command = build_algorithm_command(run_type, parameters, data_dir=tmp_path, output_dir=tmp_path / "outputs")
        assert "plan-storage" not in command
        assert "heavy-empty-plan" not in command


def test_database_ratings_win_but_version_self_discharge_survives():
    metadata = {**DEVICE, "capacity_kwh": 999, "self_discharge_rate_per_hour": 0.1}
    rows = _bound_payload((_record_payload([metadata]),), [DEVICE])
    assert rows[0]["capacity_kwh"] == 10
    assert rows[0]["max_discharge_power_kw"] == 0
    assert rows[0]["self_discharge_rate_per_hour"] == 0.1
    assert _bound_payload((), [DEVICE])[0]["self_discharge_rate_per_hour"] == 0
    rated = {**DEVICE, "self_discharge_rate_per_hour": 0.2}
    assert _bound_payload((_record_payload([metadata]),), [rated])[0]["self_discharge_rate_per_hour"] == 0.2


@pytest.mark.parametrize("rate", [-0.1, 1.1, float("nan"), float("inf"), True, "invalid"])
def test_invalid_self_discharge_is_rejected_before_snapshot(rate):
    with pytest.raises(ValueError):
        bind_database_storage_parameters((_record_payload([{**DEVICE, "self_discharge_rate_per_hour": rate}]),), [DEVICE])


def test_self_discharge_reaches_model_and_ledger():
    with TemporaryDirectory() as temp:
        root = Path(temp)
        battery = record_from_bytes("battery.json", b'{"capacity_kwh":10,"round_trip_efficiency":1}')
        records = bind_database_storage_parameters((battery, _record_payload([{**DEVICE, "self_discharge_rate_per_hour": 0.1}])), [DEVICE])
        materialize_file_records(records, root)
        parameters = _load_battery(root)
    assert parameters.storage_devices[0].self_discharge_rate_per_hour == 0.1
    settlement = EnergySettlementSystem(parameters, settlement_time_step_s=3600,
        power_arm_limits={"A": PowerArmElectricalLimit(storage_available=True, storage_section_id="S")})
    result = settlement.settle([{0: (1.0, 1.0, "A", 3600.0, "S")}])
    assert result.self_discharge_loss_kwh == pytest.approx(1.0)
    assert result.final_soc_by_storage_kwh["S"] == pytest.approx(9.0)
    assert result.battery_discharge_kwh == 0


def test_storage_tables_roundtrip_preserves_new_and_unknown_facts():
    baseline = _storage_baseline()
    records = [record_from_bytes(path, payload) for path, payload in baseline.items()]
    exported = export_version_tables(records, "storage")
    battery_sheet = next(sheet for sheet in exported["sheets"] if sheet["name"] == "储能参数")
    zone_sheet = next(sheet for sheet in exported["sheets"] if sheet["name"] == "储能区段")
    assert "折旧计费口径" in battery_sheet["columns"]
    assert "最大传输功率kW" in zone_sheet["columns"]
    zone_sheet["rows"][0]["效率"] = "0.94"
    overlays = tables_to_overlays("storage", exported["sheets"], baseline)
    saved = list(csv.DictReader(io.StringIO(overlays["energy_transfer_zones.csv"].decode())))
    assert saved[0]["efficiency"] == "0.94"
    assert saved[0]["max_transfer_power_kW"] == "12000.0"
    assert saved[0]["source_sha256"] == "abc"
    assert saved[0]["extra_fact"] == "keep-me"
    assert saved[1]["active_in_operational_baseline"] == "false"
    assert json.loads(overlays["battery.json"])["source_document"] == "equipment.doc"


def test_legacy_excel_preserves_facility_metadata_and_depreciation_basis():
    with TemporaryDirectory() as temp:
        path = Path(temp) / "储能设备.xlsx"
        book = Workbook()
        battery = book.active
        battery.title = "储能参数"
        battery.append(["容量kWh", "往返效率", "折旧成本每kWh", "电价每kWh", "最大充电功率kW", "最大放电功率kW", "备注"])
        battery.append([145, 0.9, 0.326, 0.6818, 2000, 0, "legacy"])
        zone = book.create_sheet("储能区段")
        zone.append(["起点km", "终点km", "效率", "储能区段编号", "数据状态", "备注"])
        zone.append([108, 219, 0.9, "FLEX-1", "", "edited"])
        book.save(path)
        overlays = convert_excel_files([path], _storage_baseline())
    saved = list(csv.DictReader(io.StringIO(overlays["energy_transfer_zones.csv"].decode())))
    assert saved[0]["zone_id"] == "FLEX-1"
    assert saved[0]["max_transfer_power_kW"] == "12000.0"
    assert json.loads(overlays["battery.json"])["depreciation_cost_basis"] == "charge_energy"


def test_facility_validation_accepts_inactive_planning_but_checks_active_overlap():
    columns = ["设施编号", "起点km", "终点km", "运行基线启用", "实施状态"]
    operational = {"设施编号": "FLEX-1", "起点km": "108", "终点km": "219", "运行基线启用": "true"}
    planned = {"设施编号": "FLEX-2", "起点km": "16", "终点km": "139", "运行基线启用": "false"}
    assert conflict_report("储能设备.xlsx", [("储能区段", columns, [(2, operational), (3, planned)])]) is None
    assert "重叠" in conflict_report("储能设备.xlsx", [("储能区段", columns, [(2, operational), (3, {**planned, "运行基线启用": "true"})])])
    assert "重复" in conflict_report("储能设备.xlsx", [("储能区段", columns, [(2, operational), (3, {**planned, "设施编号": "FLEX-1"})])])
    assert "必须小于" in conflict_report("储能设备.xlsx", [("储能区段", columns, [(2, {**planned, "起点km": "200"})])])


def test_new_facility_excel_import_accepts_planning_and_preserves_metadata(tmp_path):
    baseline = _storage_baseline()
    exported = export_version_tables([record_from_bytes(p, c) for p, c in baseline.items()], "storage")
    book = Workbook()
    book.remove(book.active)
    for sheet in exported["sheets"]:
        page = book.create_sheet(sheet["name"])
        page.append(sheet["columns"])
        for row in sheet["rows"]:
            page.append([row.get(column, "") for column in sheet["columns"]])
    path = tmp_path / "储能设备.xlsx"
    book.save(path)
    overlays = convert_excel_files([path], baseline)
    saved = list(csv.DictReader(io.StringIO(overlays["energy_transfer_zones.csv"].decode())))
    assert len(saved) == 2
    assert saved[1]["active_in_operational_baseline"] == "false"
    assert saved[1]["extra_fact"] == "planned-fact"


@pytest.mark.parametrize("field,value", [("实施状态", "invalid"), ("运行基线启用", "invalid"), ("最大传输功率kW", "nan")])
def test_invalid_facility_fields_are_rejected(field, value):
    exported = export_version_tables([record_from_bytes(p, c) for p, c in _storage_baseline().items()], "storage")
    zones = next(sheet for sheet in exported["sheets"] if sheet["name"] == "储能区段")
    zones["rows"][0][field] = value
    with pytest.raises(ExcelConversionError):
        tables_to_overlays("storage", exported["sheets"], _storage_baseline())


def test_new_dataset_facilities_are_filtered_and_projected_without_key_error():
    assert validate_real_data_bundle(UPDATE_DATA).summary()["valid"]
    bundle = load_real_data_bundle(UPDATE_DATA)
    assert bundle.route.energy_transfer_ranges_km == [(108.0, 219.0)]
    assert bundle.battery.capacity_kwh == 145
    assert bundle.battery.max_discharge_power_kW == 0
    assert bundle.route.flexible_energy_transfer_zones[0]["max_transfer_power_kW"] == 12000
    projected = project_dataset(uuid4(), UPDATE_DATA)["storage_devices"]
    # Explicit flexible facilities and planning-only arm references are not device inventory.
    assert projected == []
    with TemporaryDirectory() as temp:
        root = Path(temp)
        devices = [{**{key: value for key, value in row.items() if key != "storage_id"}, "storage_section_id": row["storage_code"]} for row in projected]
        records = [record_from_bytes(path.name, path.read_bytes()) for path in UPDATE_DATA.iterdir() if path.is_file()]
        materialize_file_records(bind_database_storage_parameters(records, devices), root)
        assert validate_real_data_bundle(root).summary()["valid"]
        assert not _load_battery(root).storage_devices
        assert _load_battery(root).capacity_kwh == 145


def test_flexible_facility_without_storage_connection_is_not_a_storage_device(tmp_path):
    from database.dataset_projection import _storage_zone_rows
    assert _storage_zone_rows(tmp_path, [{"zone_id": "FLEX-1", "start_km": "108", "end_km": "219"}]) == []


def test_flexible_transfer_limit_and_loss_affect_energy():
    limit = PowerArmElectricalLimit(max_traction_supply_kw=100000, max_regen_absorption_kw=100000, max_grid_feedback_kw=100000)
    system = EnergySettlementSystem(BatteryStorageParameters(0, 1, 0, 1, 0, 0), [(108, 219)],
        settlement_time_step_s=3600, allow_direct_use=True, allow_storage=False,
        power_arm_limits={"A": limit},
        flexible_energy_transfer_zones=[{"max_transfer_power_kW": 12000, "efficiency": 0.95}])
    result = system.settle([{0: (-20000.0, 1.0, "A", 3600.0)}, {0: (20000.0, 1.0, "A", 3600.0)}])
    assert result.direct_used_kwh == pytest.approx(11400)
    assert result.grid_kwh == pytest.approx(8600)
    assert result.wasted_kwh == pytest.approx(8600)


@pytest.mark.parametrize("basis,cost", [("total_throughput", 0.652), ("charge_energy", 0.326), ("discharge_energy", 0.326)])
def test_explicit_depreciation_basis(basis, cost):
    parameters = BatteryStorageParameters(10, 1, 0.326, 0, 1, 1, depreciation_cost_basis=basis)
    result = EnergySettlementSystem(parameters, settlement_time_step_s=3600,
        power_arm_limits={"A": PowerArmElectricalLimit(storage_available=True, storage_section_id="S")}).settle([
            {0: (-1.0, 1.0, "A", 3600.0, "S"), 3600: (1.0, 1.0, "A", 3600.0, "S")}])
    assert result.battery_cost == pytest.approx(cost)


def test_charge_only_timetable_scenario():
    scenario = TimetableScenario("charge-only", False, True, 145, None, 0, 300, "power_arm",
        storage_charge_power_kw=2000, storage_discharge_power_kw=0)
    assert scenario.storage_discharge_power_kw == 0
