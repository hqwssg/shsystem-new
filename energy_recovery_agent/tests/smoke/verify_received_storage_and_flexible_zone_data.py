"""Verify the two received documents are represented safely in runtime data."""

from pathlib import Path
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from data_ingestion import load_real_data_bundle, validate_real_data_bundle
from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from train_simulator import BatteryStorageParameters


def main() -> None:
    data_dir = ROOT / "data" / "real_shuohuang"
    report = validate_real_data_bundle(data_dir)
    assert report.summary()["valid"], report.summary()

    battery_raw = json.loads((data_dir / "battery.json").read_text(encoding="utf-8"))
    assert battery_raw["capacity_kwh"] == 145.0
    assert battery_raw["round_trip_efficiency"] == 0.9
    assert battery_raw["depreciation_cost_per_kwh"] == 0.326
    assert battery_raw["depreciation_cost_basis"] == "total_throughput"
    assert battery_raw["grid_price_per_kwh"] == 0.6818
    assert battery_raw["max_charge_power_kW"] == 2000.0
    assert battery_raw["max_discharge_power_kW"] == 0.0
    assert battery_raw["planning_max_discharge_power_assumption_kW"] == 2000.0
    assert battery_raw["field_data_status"]["max_discharge_power_kW"] == "missing_conservative_zero"

    with (data_dir / "energy_transfer_zones.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        zones = list(csv.DictReader(handle))
    assert len(zones) == 2
    assert {(row["implementation_status"], row["active_in_operational_baseline"]) for row in zones} == {
        ("implemented", "true"), ("planned", "false")
    }
    assert all(float(row["max_transfer_power_kW"]) == 12000.0 for row in zones)
    assert all(float(row["efficiency"]) == 0.95 for row in zones)

    bundle = load_real_data_bundle(data_dir)
    assert bundle.route.energy_transfer_ranges_km == [(108.0, 219.0)]
    assert bundle.route.flexible_energy_transfer_zones == ({
        "zone_id": "FLEX-IMPLEMENTED-001",
        "start_km": 108.0,
        "end_km": 219.0,
        "max_transfer_power_kW": 12000.0,
        "efficiency": 0.95,
    },)
    assert bundle.battery.capacity_kwh == 145.0
    assert bundle.battery.max_discharge_power_kW == 0.0

    # One-hour, 20 MW simultaneous regen/traction exceeds the 12 MW facility.
    # Only 12 MWh is admitted and 95% (11.4 MWh) reaches the usable side.
    unconstrained_battery = BatteryStorageParameters(0.0, 1.0, 0.0, 1.0, 0.0, 0.0)
    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=100000.0,
        max_regen_absorption_kw=100000.0,
        max_grid_feedback_kw=100000.0,
    )
    settlement = EnergySettlementSystem(
        unconstrained_battery,
        [(108.0, 219.0)],
        settlement_time_step_s=3600,
        allow_direct_use=True,
        allow_storage=False,
        power_arm_limits={"A": limit},
        flexible_energy_transfer_zones=bundle.route.flexible_energy_transfer_zones,
    ).settle([
        {0: (-20000.0, 1.0, "A", 3600.0)},
        {0: (20000.0, 1.0, "A", 3600.0)},
    ])
    assert abs(settlement.direct_used_kwh - 11400.0) < 1e-6
    assert abs(settlement.grid_kwh - 8600.0) < 1e-6
    assert abs(settlement.wasted_kwh - 8600.0) < 1e-6

    storage_limit = PowerArmElectricalLimit(
        max_traction_supply_kw=100000.0,
        max_regen_absorption_kw=100000.0,
        max_grid_feedback_kw=100000.0,
        storage_available=True,
        storage_section_id="S",
    )
    costs = {}
    for basis in ("total_throughput", "charge_energy", "discharge_energy"):
        cost_battery = BatteryStorageParameters(
            10.0, 1.0, 0.326, 0.0, 1.0, 1.0,
            depreciation_cost_basis=basis,
        )
        costs[basis] = EnergySettlementSystem(
            cost_battery,
            settlement_time_step_s=3600,
            allow_direct_use=False,
            allow_storage=True,
            power_arm_limits={"A": storage_limit},
        ).settle([{
            0: (-1.0, 1.0, "A", 3600.0, "S"),
            3600: (1.0, 1.0, "A", 3600.0, "S"),
        }]).battery_cost
    assert abs(costs["total_throughput"] - 0.652) < 1e-9
    assert abs(costs["charge_energy"] - 0.326) < 1e-9
    assert abs(costs["discharge_energy"] - 0.326) < 1e-9
    print("received storage/flexible-zone data smoke: PASS")


if __name__ == "__main__":
    main()
