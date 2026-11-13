"""验证合成状态驱动的多轮滚动重调度基础状态机。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from energy_settlement import EnergySettlementSystem, StorageDeviceRuntimeState
from rolling_optimizer import (
    GeneratedSchedule,
    RollingCycleObservation,
    RollingWindowState,
    ScheduleTemplate,
    clip_power_series_to_window,
    run_mpc_cycles,
)
from train_simulator import BatteryStorageParameters


def main() -> int:
    """执行无随机性的滚动状态、SOC和时间窗回归测试。"""

    clipped = clip_power_series_to_window(
        [{0: (100.0, 1.0, "A", 10.0), 10: (-50.0, 1.0, "A", 10.0)}],
        from_time_s=5,
        until_time_s=15,
        default_duration_s=10,
    )
    assert sorted(clipped[0]) == [5, 10]
    assert clipped[0][5][3] == 5.0
    assert clipped[0][10][3] == 5.0

    battery = BatteryStorageParameters(
        capacity_kwh=100.0,
        round_trip_efficiency=0.9,
        depreciation_cost_per_kwh=0.02,
        grid_price_per_kwh=0.5,
        max_charge_power_kW=50.0,
        max_discharge_power_kW=50.0,
    )
    settlement = EnergySettlementSystem(
        battery,
        settlement_time_step_s=10,
        initial_soc_kwh=5.0,
        target_final_soc_kwh=10.0,
        power_arm_limits={},
    )
    copied = settlement.with_initial_soc(35.0)
    assert copied.initial_soc_kwh == 35.0
    assert copied.target_final_soc_kwh == 10.0
    assert copied.capacity_kwh == settlement.capacity_kwh

    class ProbeOptimizer:
        """记录每轮输入状态并返回可执行发车的确定性优化器。"""

        default_storage_preset_id = "fixed"

        def __init__(self) -> None:
            self.states = []
            self.recovery_flags = []

        def optimize_once(self, state, base_template, **kwargs):
            self.states.append(state)
            self.recovery_flags.append(kwargs.get("enable_recovery"))
            template = replace(
                base_template,
                start_time_s=state.current_time_s,
                flex_zone_hold_s=120,
                storage_preset_id="fixed",
            )
            schedule = GeneratedSchedule(
                heavy_departures_s=[state.current_time_s],
                empty_departures_s=[state.current_time_s + 100],
                template=template,
            )
            return SimpleNamespace(
                schedule=schedule,
                executable_heavy_departures_s=[state.current_time_s],
                executable_empty_departures_s=[state.current_time_s + 100],
            )

    delays = ((0, 0), (180, 0), (60, 240), (0, 0))
    device_states = tuple(
        (
            StorageDeviceRuntimeState("S1", soc, available, 25.0 if available else 0.0, 25.0 if available else 0.0),
            StorageDeviceRuntimeState("S2", 5.0, True, 25.0, 25.0),
        )
        for soc, available in ((10.0, True), (14.0, False), (11.5, False), (18.0, True))
    )
    provider_calls = []

    def observation_provider(cycle_index, state, previous_result):
        provider_calls.append((cycle_index, state.current_time_s, previous_result is not None))
        heavy_delay, empty_delay = delays[cycle_index]
        return RollingCycleObservation(
            observed_heavy_delay_s=heavy_delay,
            observed_empty_delay_s=empty_delay,
            storage_device_states=device_states[cycle_index],
        )

    optimizer = ProbeOptimizer()
    results = run_mpc_cycles(
        optimizer,  # type: ignore[arg-type]
        RollingWindowState(0, [], []),
        ScheduleTemplate(900, 900, 300, 1, 1),
        cycles=4,
        horizon_s=1800,
        execute_window_s=600,
        observation_provider=observation_provider,
        enable_recovery=False,
    )
    assert len(results) == 4
    assert optimizer.recovery_flags == [False] * 4
    assert [state.current_time_s for state in optimizer.states] == [0, 600, 1200, 1800]
    assert [state.observed_heavy_delay_s for state in optimizer.states] == [0, 180, 60, 0]
    assert [state.observed_empty_delay_s for state in optimizer.states] == [0, 0, 240, 0]
    assert [state.storage_device_states for state in optimizer.states] == list(device_states)
    assert [
        state.storage_device_states[0].available for state in optimizer.states
    ] == [True, False, False, True]
    assert provider_calls[0][2] is False
    assert all(call[2] for call in provider_calls[1:])
    for previous, current in zip(optimizer.states, optimizer.states[1:]):
        assert set(previous.locked_heavy_departures_s).issubset(
            current.locked_heavy_departures_s
        )
        assert set(previous.locked_empty_departures_s).issubset(
            current.locked_empty_departures_s
        )
    assert optimizer.states[1].locked_empty_storage_hold_s == 120
    assert optimizer.states[1].locked_storage_preset_id == "fixed"

    print("synthetic rolling rescheduling smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
