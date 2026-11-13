"""验证逐储能设备 SOC、可用状态和功率降额参与滚动能量评价。"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from energy_settlement import EnergySettlementSystem, StorageDeviceRuntimeState
from power_arm_electrical_limits import PowerArmElectricalLimit
from rolling_optimizer import RollingCycleObservation, RollingWindowState, _rolling_observation_fingerprint
from train_simulator import BatteryStorageParameters


def _system(states: tuple[StorageDeviceRuntimeState, ...]) -> EnergySettlementSystem:
    battery = BatteryStorageParameters(
        capacity_kwh=200.0,
        round_trip_efficiency=1.0,
        depreciation_cost_per_kwh=0.0,
        grid_price_per_kwh=1.0,
        max_charge_power_kW=200.0,
        max_discharge_power_kW=200.0,
    )
    limits = {
        "A1": PowerArmElectricalLimit(storage_available=True, storage_section_id="S1"),
        "A2": PowerArmElectricalLimit(storage_available=True, storage_section_id="S2"),
    }
    return EnergySettlementSystem(
        battery,
        settlement_time_step_s=3600,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits=limits,
        storage_runtime_states=states,
    )


def main() -> int:
    """执行设备级状态的确定性回归。"""

    states = (
        StorageDeviceRuntimeState("S2", 0.0, False, 0.0, 0.0),
        StorageDeviceRuntimeState("S1", 100.0, True, 25.0, 40.0),
    )
    system = _system(states)

    regen = system.settle([
        {0: (-100.0, 1.0, "A1", 3600.0, "S1")},
        {0: (-100.0, 1.0, "A2", 3600.0, "S2")},
    ])
    assert regen.battery_charge_kwh == 0.0
    assert regen.initial_soc_kwh == 100.0
    assert regen.initial_soc_by_storage_kwh == {"S1": 100.0, "S2": 0.0}
    assert regen.battery_charge_by_storage_kwh == {"S1": 0.0, "S2": 0.0}
    assert regen.wasted_kwh == 200.0
    assert regen.final_soc_by_storage_kwh == {"S1": 100.0, "S2": 0.0}

    discharge = system.settle([
        {0: (100.0, 1.0, "A1", 3600.0, "S1")},
        {0: (100.0, 1.0, "A2", 3600.0, "S2")},
    ])
    assert discharge.battery_discharge_kwh == 40.0
    assert discharge.battery_discharge_by_storage_kwh == {"S1": 40.0, "S2": 0.0}
    assert discharge.grid_kwh == 160.0
    assert discharge.final_soc_by_storage_kwh == {"S1": 60.0, "S2": 0.0}

    available = _system((
        StorageDeviceRuntimeState("S1", 100.0, True, 25.0, 40.0),
        StorageDeviceRuntimeState("S2", 0.0, True, 25.0, 40.0),
    )).settle([
        {0: (-100.0, 1.0, "A1", 3600.0, "S1")},
        {0: (-100.0, 1.0, "A2", 3600.0, "S2")},
    ])
    assert available.battery_charge_kwh == 25.0
    assert available.battery_charge_by_storage_kwh == {"S1": 0.0, "S2": 25.0}
    assert available.wasted_kwh == 175.0
    assert available.final_soc_by_storage_kwh == {"S1": 100.0, "S2": 25.0}

    state = RollingWindowState(0, [], [], storage_device_states=states)
    assert [item.storage_section_id for item in state.storage_device_states] == ["S1", "S2"]
    changed = RollingWindowState(
        0,
        [],
        [],
        storage_device_states=(
            StorageDeviceRuntimeState("S1", 100.0, False, 0.0, 0.0),
            StorageDeviceRuntimeState("S2", 0.0, False, 0.0, 0.0),
        ),
    )
    assert _rolling_observation_fingerprint(state) != _rolling_observation_fingerprint(changed)
    try:
        RollingCycleObservation(
            storage_soc_kwh=100.0,
            storage_device_states=states,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("汇总 SOC 与设备状态同时提供时应被拒绝")

    try:
        system_with_missing_state = _system((StorageDeviceRuntimeState("S1", 0.0),))
        system_with_missing_state.settle([])
    except ValueError:
        pass
    else:
        raise AssertionError("显式设备状态缺少 S2 时应被拒绝")

    for invalid_states in (
        (
            StorageDeviceRuntimeState("S1", 101.0),
            StorageDeviceRuntimeState("S2", 0.0),
        ),
        (
            StorageDeviceRuntimeState("S1", 0.0, True, 101.0, 0.0),
            StorageDeviceRuntimeState("S2", 0.0),
        ),
    ):
        try:
            _system(invalid_states).settle([])
        except ValueError:
            pass
        else:
            raise AssertionError(f"超过设备静态能力的状态必须被拒绝：{invalid_states}")

    print("rolling storage device state verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
