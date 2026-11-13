"""扩展试验的冻结矩阵、滚动预筛语义和防伪造核验。"""

from dataclasses import replace
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from constraint_guided_search import screen_schedule
from energy_settlement import EnergySettlementSystem
from power_arm_electrical_limits import PowerArmElectricalLimit
from rolling_optimizer import DisturbanceScenario, ScheduleTemplate, generate_schedule
from train_simulator import BatteryStorageParameters
from tools.benchmark_constraint_guided_extended import make_domain, plan, config_for
from tools.verify_constraint_guided_extended import close, summarize, verify_rolling


def check_current_supply_limit_boundary():
    """记录既有口径而非认可现场物理含义；正式接入需确认是否应约束净外部供电。"""
    battery = BatteryStorageParameters(capacity_kwh=200.0, round_trip_efficiency=1.0,
                                        depreciation_cost_per_kwh=0.0, grid_price_per_kwh=1.0,
                                        max_charge_power_kW=100.0, max_discharge_power_kW=100.0)
    system = EnergySettlementSystem(battery, settlement_time_step_s=3600, initial_soc_kwh=100.0,
                                    power_arm_limits={"A": PowerArmElectricalLimit(
                                        max_traction_supply_kw=100.0, storage_available=True, storage_section_id="S")})
    result = system.settle([{0: (200.0, 1.0, "A", 3600.0, "S")}])
    assert result.battery_discharge_kwh == 100.0 and result.grid_kwh == 100.0
    assert result.traction_supply_excess_kwh == 100.0


def check_corrupted_rolling_evidence():
    windows = []
    states = {"S1": 10.0, "S2": 20.0}
    for index in range(10):
        final = {k: v + 2.0 for k, v in states.items()}
        windows.append(dict(from_time_s=index * 100, until_time_s=(index + 1) * 100,
                            initial_soc_by_storage_kwh=states, final_soc_by_storage_kwh=final,
                            battery_charge_by_storage_kwh={"S1": 5.0, "S2": 5.0},
                            battery_discharge_by_storage_kwh={"S1": 2.5, "S2": 2.5},
                            total_gen_kwh=10.0, total_con_kwh=10.0, grid_kwh=5.0, wasted_kwh=0.0,
                            battery_charge_kwh=10.0, battery_discharge_kwh=5.0, traction_supply_excess_kwh=0.0))
        states = final
    fields = ("total_gen_kwh", "total_con_kwh", "grid_kwh", "wasted_kwh", "battery_charge_kwh",
              "battery_discharge_kwh", "traction_supply_excess_kwh")
    whole = {k: sum(w[k] for w in windows) for k in fields}
    whole["final_soc_by_storage_kwh"] = states
    data = dict(storage_ids=["S1", "S2"], capacity_kwh=145.0, efficiency=.9,
                initial_states=[dict(storage_section_id="S1", soc_kwh=10.0), dict(storage_section_id="S2", soc_kwh=20.0)],
                windows=windows, whole=whole, reset_grid_kwh=999.0, reset_final_soc_by_storage_kwh=states,
                missing_device_rejected=True, overflow_soc_rejected=True,
                lock_success=dict(commit_status="committed_robust_feasible", hold_s=0, preset="virtual_two_section_base",
                                  disturbances=[dict(heavy=[0, 3300], empty=[2760, 6060])] * 5,
                                  screen={"rejected": False}, cancellation_rejected=True, observed_delay_rejected=True),
                lock_failure=dict(commit_status="withheld_infeasible", heavy=[0, 3300], empty=[2760, 6060],
                                  executable_heavy=[3300], executable_empty=[2760]))
    assert verify_rolling(data)["passed"]
    corrupted = deepcopy(data)
    corrupted["windows"][2]["initial_soc_by_storage_kwh"]["S1"] += 1.0
    assert not verify_rolling(corrupted)["passed"]
    corrupted = deepcopy(data)
    corrupted["windows"][3]["grid_kwh"] += .01
    assert not verify_rolling(corrupted)["passed"]
    corrupted = deepcopy(data)
    corrupted["lock_failure"]["executable_heavy"].append(1800)
    assert not verify_rolling(corrupted)["passed"]
    corrupted = deepcopy(data)
    corrupted["reset_grid_kwh"] = whole["grid_kwh"]
    assert not verify_rolling(corrupted)["passed"]


def main():
    check_current_supply_limit_boundary()
    check_corrupted_rolling_evidence()
    specs = plan(ROOT / "data/real_shuohuang", ROOT / "outputs/not_executed_unit_fixture")
    assert len(specs) == 26 and len({s["run_id"] for s in specs}) == 26
    assert {s["scale"] * 2 for s in specs} == {8, 12, 16}
    assert {s["full_budget"] for s in specs} == {24, 48}
    assert {s["profile"] for s in specs} == {"positive_discharge", "supply_limited"}
    for spec in specs:
        base, domain = make_domain(spec)
        assert len(domain) == 64 and base in domain
        assert config_for(spec["seed"]).population_size == 12
        for template in domain:
            schedule = generate_schedule(template)
            assert len(schedule.heavy_departures_s) == len(schedule.empty_departures_s) == spec["scale"]
            assert max(*schedule.heavy_departures_s, *schedule.empty_departures_s) <= spec["horizon_s"]
    # 旧预筛把已执行首列也延后，会制造500<600的假冲突；滚动语义下间隔620秒。
    schedule = generate_schedule(ScheduleTemplate(500, 500, 0, 2, 0))
    scenarios = [DisturbanceScenario("future_delay_1", heavy_delay_s=120),
                 DisturbanceScenario("future_delay_2", heavy_delay_s=120)]
    kwargs = dict(resource_model=None, heavy_cache=None, empty_cache=None, required_heavy_count=2,
                  required_empty_count=0, min_depart_gap_s=600)
    assert screen_schedule(schedule, scenarios=scenarios, **kwargs).rejected
    result = screen_schedule(schedule, scenarios=iter(scenarios), disturbance_from_time_s=400,
                             locked_heavy_departures_s=iter([0]), **kwargs)
    assert not result.rejected
    # 无显式核心场景的生成器也必须保留全部场景，不能被第一遍迭代耗尽。
    assert screen_schedule(schedule, scenarios=(replace(s, core_for_feasibility=False) for s in scenarios),
                           **kwargs).rejected
    assert not close({"score": 0.0}, {"score": .01})
    assert not close(True, 1) and not close(float("nan"), float("nan"))
    # 双方均失败的快速拒绝，不得被放进有效加速样本。
    rows = [dict(profile="positive_discharge", scale=4, full_budget=24, seed=11, arm=arm,
                 heuristic_found_feasible=False, selected_selection_key=None, full_evaluation_count=count,
                 screen_count=0, e2e_wall_time_s=elapsed)
            for arm, count, elapsed in (("baseline", 24, 100), ("combined", 0, 1))]
    effect = summarize(rows)["effectiveness"]
    assert effect["comparable_pair_count"] == 0 and effect["median_paired_e2e_ratio"] is None
    assert effect["full_evaluation_reduction"] is None
    print("extended validation design and rolling screen semantics: PASS")


if __name__ == "__main__":
    main()
