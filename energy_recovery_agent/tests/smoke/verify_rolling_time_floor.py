"""新请求、候选限幅、服务数量和最后提交门禁的时间下界回归。"""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from energy_settlement import EnergySettlementSystem
from train_simulator import BatteryStorageParameters
from scheduler_nsga2 import PowerSeriesCache
from rolling_optimizer import (GeneratedSchedule, RollingOptimizer, RollingWindowState, ScheduleTemplate,
    TemplateSearchConfig, RollingTimeBoundaryError, rolling_future_template, generate_schedule,
    gate_rolling_execution_commit)


def main():
    base = ScheduleTemplate(900, 900, 300, 2, 2, start_time_s=1000)
    for field, value in (("heavy_departure_adjustments_s", (-120, 100)),
                         ("empty_departure_adjustments_s", (-420, 100)),
                         ("storage_align_shift_s", -420)):
        template = replace(base, **{field: value})
        try:
            rolling_future_template(template, 1000, reject_past=True)
        except RollingTimeBoundaryError:
            pass
        else:
            raise AssertionError("非法基线请求应明确拒绝，不得默默丢弃列车")
        safe = rolling_future_template(template, 1000)
        schedule = generate_schedule(safe)
        assert len(schedule.heavy_departures_s) == len(schedule.empty_departures_s) == 2
        assert min(schedule.heavy_departures_s + schedule.empty_departures_s) >= 1000
        assert rolling_future_template(safe, 1000) == safe
    for now in (0, 1000):
        safe = rolling_future_template(replace(base, heavy_departure_adjustments_s=(-120, 0)), now)
        assert generate_schedule(safe).heavy_departures_s == [now, now + 1020]
    phantom = GeneratedSchedule([880, 1120], [], base)
    rows = [{"core_for_feasibility": True, "feasible": True}]
    for override in (False, True):
        decision = gate_rolling_execution_commit(phantom, rows, current_time_s=1000,
            execute_window_s=600, allow_infeasible_commit_for_experiment=override)
        assert decision.commit_status == "withheld_infeasible" and not decision.core_robust_feasible
        assert decision.committed_execution_schedule.heavy_departures_s == []
        assert decision.executable_heavy_departures_s == []
    decision = gate_rolling_execution_commit(phantom, rows, current_time_s=1000, execute_window_s=600,
                                             locked_heavy_departures_s=[880])
    assert decision.core_robust_feasible and decision.executable_heavy_departures_s == [1120]
    denied = gate_rolling_execution_commit(phantom, rows, current_time_s=1000, execute_window_s=600,
        locked_heavy_departures_s=[880], candidate_feasible=False)
    assert denied.commit_status == "withheld_infeasible" and denied.executable_heavy_departures_s == []
    try:
        gate_rolling_execution_commit(phantom, rows, current_time_s=1000, execute_window_s=600,
                                      locked_heavy_departures_s=[881])
    except ValueError:
        pass
    else:
        raise AssertionError("遗漏锁定历史也必须在最终提交层拒绝")
    cache = PowerSeriesCache(times=[0, 10], powers_kW=[0., 0.], energy_transfer_ratios=[0., 0.],
        power_arm_ids=["A", "A"], positions_km=[0., 1.], speeds_mps=[0., 0.], train_length_km=1.,
        direction="forward", adhesion_coefficients=[.28, .28], speed_limits_mps=[10., 10.],
        brake_decelerations_mps2=[.3, .3])
    battery = BatteryStorageParameters(capacity_kwh=0, round_trip_efficiency=.9,
        depreciation_cost_per_kwh=0, grid_price_per_kwh=1, max_charge_power_kW=0, max_discharge_power_kW=0)
    optimizer = RollingOptimizer(SimpleNamespace(signaling_system={}), cache, cache, EnergySettlementSystem(battery))
    config = TemplateSearchConfig(population_size=2, generations=1, elite_count=1, min_headway_s=900,
        max_headway_s=900, max_phase_s=300, max_hold_s=0, max_storage_align_shift_s=0,
        allowed_heavy_headways_s=(900,), allowed_empty_headways_s=(900,), allowed_phases_s=(300,),
        allowed_holds_s=(0,), allowed_storage_align_shifts_s=(0,), enable_storage_preset_search=False)
    valid = replace(base, empty_count=0)
    invalid = replace(valid, heavy_departure_adjustments_s=(-120, 100))
    with patch("rolling_optimizer.nsga2_template_search", side_effect=lambda b, c, evaluate:
               [(valid, evaluate(valid)), (invalid, evaluate(invalid))]):
        result = optimizer.optimize_once(RollingWindowState(1000, [], []), valid,
            horizon_s=900, execute_window_s=600, min_depart_gap_s=0, search_config=config, enable_recovery=False)
    assert result.score.feasible and result.schedule.heavy_departures_s == [1000, 1900]
    assert not next(score for t, score in result.ranked_candidates if t == invalid).feasible
    assert all(t >= 1000 for t in result.committed_execution_schedule.heavy_departures_s)
    print("rolling time floor, service conservation and authoritative commit gate: PASS")


if __name__ == "__main__":
    main()
