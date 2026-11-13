# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tempfile import TemporaryDirectory
import csv
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import heavy_empty_network_optimizer as optimizer_module
from heavy_empty_network_optimizer import (
    HeOdDemand,
    HeScenario,
    OperationNode,
    ServiceType,
    VirtualTrainsetConfig,
    load_he_input_template,
    non_dominated_sort,
    optimize_heavy_empty_network,
    pareto_front,
    parse_time_to_s,
    energy_time_slice_rows,
    power_arm_energy_settlement_rows,
    write_optimization_outputs,
)
from power_arm_electrical_limits import PowerArmElectricalLimit, StorageSectionInterval
from energy_settlement import storage_no_direct_effective_loss_kwh
from train_simulator import BatteryStorageParameters
from smoke_paths import smoke_output


TEMPLATE = Path("data_templates") / "heavy_empty_od_template.xlsx"
OUTPUT_ROOT = smoke_output("heavy_empty_network_optimizer")


def test_energy_slice_aggregation_keeps_full_precision() -> None:
    """函数 test_energy_slice_aggregation_keeps_full_precision：执行该模块中的相关处理逻辑。"""
    per_arc_kwh = 0.33333351
    arcs = tuple(
        optimizer_module.HeArc(
            arc_id=f"A{index}",
            layer="service",
            demand_id="D",
            train_id=f"T{index}",
            train_type="Heavy",
            from_node_id="n0",
            to_node_id="n1",
            arc_type="heavy_running",
            start_station="S0",
            end_station="S1",
            start_time_s=0,
            end_time_s=10,
            start_km=0.0,
            end_km=1.0,
            distance_km=1.0,
            energy_kwh=per_arc_kwh,
            base_energy_kwh=per_arc_kwh,
            avg_gradient_promille=0.0,
            curve_equivalent=0.0,
            power_arm_ids=("A",),
            power_arm_review_required=False,
            cost=0.0,
            capacity_resource_id="power_arm:A",
            source="precision-regression",
        )
        for index in range(4)
    )
    candidate = SimpleNamespace(candidate_id="precision", arcs=arcs)
    true_total_kwh = per_arc_kwh * len(arcs)
    limit = PowerArmElectricalLimit(
        max_traction_supply_kw=true_total_kwh * 360.0,
    )
    rows = power_arm_energy_settlement_rows(
        candidate,
        10,
        BatteryStorageParameters(1.0, 1.0, 0.0, 0.0),
        {"A": limit},
    )
    if rows[0]["traction_supply_excess_kwh"] != 0.0:
        raise AssertionError(
            "full-capacity energy was marked as excess after time-slice aggregation: "
            f"{rows[0]['traction_supply_excess_kwh']}"
        )
    sliced_total_kwh = sum(
        float(row["traction_kwh"])
        for row in energy_time_slice_rows(candidate, 10)
    )
    if abs(sliced_total_kwh - true_total_kwh) > 1e-12:
        raise AssertionError(sliced_total_kwh)

    per_window_kwh = 1.0000004
    window_arcs = tuple(
        replace(
            arcs[0],
            arc_id=f"W{index}",
            start_time_s=index * 10,
            end_time_s=(index + 1) * 10,
            energy_kwh=per_window_kwh,
            base_energy_kwh=per_window_kwh,
        )
        for index in range(3)
    )
    window_candidate = SimpleNamespace(candidate_id="window-precision", arcs=window_arcs)
    settlement, _rows = optimizer_module.summarize_energy_settlement(
        window_candidate,
        10,
        BatteryStorageParameters(1.0, 1.0, 0.0, 0.0),
        {"A": PowerArmElectricalLimit(max_traction_supply_kw=360.0)},
    )
    expected_excess_kwh = 3 * (per_window_kwh - 1.0)
    if abs(settlement.traction_supply_excess_kwh - expected_excess_kwh) > 1e-12:
        raise AssertionError(
            "sub-micro-kWh window violations were lost before candidate aggregation: "
            f"{settlement.traction_supply_excess_kwh}"
        )


def test_fractional_arc_boundaries_align_to_integer_settlement_windows() -> None:
    """函数 test_fractional_arc_boundaries_align_to_integer_settlement_windows：执行该模块中的相关处理逻辑。"""
    arc = optimizer_module.HeArc(
        arc_id="fractional",
        layer="service",
        demand_id="D",
        train_id="T",
        train_type="Heavy",
        from_node_id="n0",
        to_node_id="n1",
        arc_type="heavy_running",
        start_station="S0",
        end_station="S1",
        start_time_s=9.6,
        end_time_s=19.6,
        start_km=0.0,
        end_km=1.0,
        distance_km=1.0,
        energy_kwh=10.0,
        base_energy_kwh=10.0,
        avg_gradient_promille=0.0,
        curve_equivalent=0.0,
        power_arm_ids=("A",),
        power_arm_review_required=False,
        cost=0.0,
        capacity_resource_id="power_arm:A",
        source="fractional-time-regression",
    )
    rows = energy_time_slice_rows(SimpleNamespace(candidate_id="fractional", arcs=(arc,)), 10)
    if [(row["time_window_start_s"], row["time_window_end_s"]) for row in rows] != [
        (0, 10),
        (10, 20),
    ]:
        raise AssertionError(f"fractional arc windows were not aligned: {rows}")
    if abs(sum(float(row["traction_kwh"]) for row in rows) - 10.0) > 1e-12:
        raise AssertionError("fractional arc slicing did not conserve energy")


def test_downhill_energy_is_not_counted_twice() -> None:
    """函数 test_downhill_energy_is_not_counted_twice：执行该模块中的相关处理逻辑。"""
    arc = optimizer_module.HeArc(
        arc_id="downhill",
        layer="service",
        demand_id="D",
        train_id="T",
        train_type="Heavy",
        from_node_id="n0",
        to_node_id="n1",
        arc_type="heavy_running",
        start_station="S0",
        end_station="S1",
        start_time_s=0,
        end_time_s=10,
        start_km=0.0,
        end_km=1.0,
        distance_km=1.0,
        energy_kwh=67.5,
        base_energy_kwh=100.0,
        avg_gradient_promille=-5.0,
        curve_equivalent=0.0,
        power_arm_ids=("A",),
        power_arm_review_required=False,
        cost=0.0,
        capacity_resource_id="power_arm:A",
        source="downhill-regression",
        regen_energy_kwh=32.5,
    )
    traction, regen = optimizer_module._running_arc_energy_components(arc)
    if abs(traction - 100.0) > 1e-12 or abs(regen - 32.5) > 1e-12:
        raise AssertionError((traction, regen))
    if abs((traction - regen) - arc.energy_kwh) > 1e-12:
        raise AssertionError("grade benefit was applied once to the arc and again in settlement")


def test_multi_storage_terminal_soc_uses_actual_device_ids() -> None:
    """函数 test_multi_storage_terminal_soc_uses_actual_device_ids：执行该模块中的相关处理逻辑。"""
    base_arc = optimizer_module.HeArc(
        arc_id="A1",
        layer="service",
        demand_id="D",
        train_id="T1",
        train_type="Heavy",
        from_node_id="n0",
        to_node_id="n1",
        arc_type="heavy_running",
        start_station="S0",
        end_station="S1",
        start_time_s=0,
        end_time_s=10,
        start_km=0.0,
        end_km=1.0,
        distance_km=1.0,
        energy_kwh=0.0,
        base_energy_kwh=100.0,
        avg_gradient_promille=-10.0,
        curve_equivalent=0.0,
        power_arm_ids=("A",),
        power_arm_review_required=False,
        cost=0.0,
        capacity_resource_id="power_arm:A",
        source="multi-storage-regression",
        storage_section_id="S1",
        regen_energy_kwh=65.0,
    )
    candidate = SimpleNamespace(
        candidate_id="multi-storage",
        arcs=(
            base_arc,
            replace(
                base_arc,
                arc_id="A2",
                train_id="T2",
                start_time_s=10,
                end_time_s=20,
                storage_section_id="S2",
            ),
        ),
    )
    limit = PowerArmElectricalLimit(
        storage_available=True,
        storage_section_id="S1;S2",
    )
    settlement, rows = optimizer_module.summarize_energy_settlement(
        candidate,
        10,
        BatteryStorageParameters(
            capacity_kwh=400.0,
            round_trip_efficiency=1.0,
            depreciation_cost_per_kwh=0.0,
            grid_price_per_kwh=1.0,
            max_charge_power_kW=1e9,
            max_discharge_power_kW=1e9,
        ),
        {"A": limit},
    )
    if {row["storage_section_id"] for row in rows} != {"S1", "S2"}:
        raise AssertionError("power-arm metadata overwrote actual storage device IDs")
    if settlement.final_soc_by_storage_kwh != {"S1": 65.0, "S2": 65.0}:
        raise AssertionError(settlement.final_soc_by_storage_kwh)
    if settlement.final_soc_kwh != 130.0:
        raise AssertionError("multi-device terminal SOC was under-counted")


def test_energy_settlement_step_is_independent_from_capacity_slot() -> None:
    """函数 test_energy_settlement_step_is_independent_from_capacity_slot：执行该模块中的相关处理逻辑。"""
    base_arc = optimizer_module.HeArc(
        arc_id="regen",
        layer="service",
        demand_id="D",
        train_id="T1",
        train_type="Heavy",
        from_node_id="n0",
        to_node_id="n1",
        arc_type="heavy_running",
        start_station="S0",
        end_station="S1",
        start_time_s=0,
        end_time_s=10,
        start_km=0.0,
        end_km=1.0,
        distance_km=1.0,
        energy_kwh=-1.0,
        base_energy_kwh=0.0,
        avg_gradient_promille=0.0,
        curve_equivalent=0.0,
        power_arm_ids=("A",),
        power_arm_review_required=False,
        cost=0.0,
        capacity_resource_id="power_arm:A",
        source="settlement-step-regression",
        storage_section_id="S",
        regen_energy_kwh=1.0,
    )
    candidate = SimpleNamespace(
        candidate_id="settlement-step",
        arcs=(
            base_arc,
            replace(
                base_arc,
                arc_id="traction",
                train_id="T2",
                start_time_s=100,
                end_time_s=110,
                energy_kwh=1.0,
                base_energy_kwh=1.0,
                regen_energy_kwh=0.0,
            ),
        ),
    )
    battery = BatteryStorageParameters(
        capacity_kwh=10.0,
        round_trip_efficiency=1.0,
        depreciation_cost_per_kwh=0.0,
        grid_price_per_kwh=1.0,
        max_charge_power_kW=1e9,
        max_discharge_power_kW=1e9,
    )
    limits = {
        "A": PowerArmElectricalLimit(
            storage_available=True,
            storage_section_id="S",
        )
    }
    ten_second, _rows = optimizer_module.summarize_energy_settlement(
        candidate, 10, battery, limits
    )
    coarse, _rows = optimizer_module.summarize_energy_settlement(
        candidate, 900, battery, limits
    )
    summary_only, summary_rows = optimizer_module.summarize_energy_settlement(
        candidate,
        10,
        battery,
        limits,
        include_rows=False,
    )
    if summary_only != ten_second or summary_rows:
        raise AssertionError("仅摘要结算与完整明细结算的数值不一致")
    if ten_second.grid_kwh != 0.0 or ten_second.battery_discharge_kwh != 1.0:
        raise AssertionError(ten_second)
    if coarse.grid_kwh != 1.0 or coarse.battery_discharge_kwh != 0.0:
        raise AssertionError("regression fixture no longer distinguishes 10s and 900s settlement")


def test_duplicate_genomes_are_evaluated_once(bundle) -> None:
    """重复基因组应复用评价，但候选数量、编号和最佳解明细不能减少。"""

    source = bundle.scenarios["capacity_surplus_demo"]
    scenario = replace(source, population_size=4, generations=1)
    scenario_bundle = replace(bundle, scenarios={scenario.scenario_id: scenario})
    genome = optimizer_module.HeGenome(0, scenario.min_headway_s, None)
    original_builder = optimizer_module._candidate_from_genome
    with patch.object(
        optimizer_module,
        "_initial_genomes",
        return_value=[genome, genome, genome, genome],
    ), patch.object(
        optimizer_module,
        "_candidate_from_genome",
        wraps=original_builder,
    ) as candidate_builder:
        result = optimize_heavy_empty_network(scenario_bundle, scenario.scenario_id)

    if candidate_builder.call_count != 1:
        raise AssertionError(f"重复基因组实际评价了 {candidate_builder.call_count} 次")
    if len(result.candidates) != 4 or len({item.candidate_id for item in result.candidates}) != 4:
        raise AssertionError("评价缓存改变了候选数量或候选编号")
    if not result.best_candidate.energy_settlement_rows:
        raise AssertionError("最佳候选没有补建完整能量结算明细")
    if any(
        item.energy_settlement_rows
        for item in result.candidates
        if item.candidate_id != result.best_candidate.candidate_id
    ):
        raise AssertionError("搜索阶段候选仍保留了不需要的结算明细")


def test_global_departure_shift_search_is_signed() -> None:
    """全局发车时移应同时覆盖提前和延后，而不是把负值截成零。"""

    scenario = HeScenario(
        scenario_id="signed-shift",
        objective_mode="capacity_surplus",
        time_slice_s=60,
        max_departure_shift_s=600,
        population_size=32,
        generations=1,
        seed=7,
        min_headway_s=60,
        section_capacity_per_slot=1,
        weight_energy=1.0,
        weight_distance=1.0,
        weight_connection=1.0,
        weight_virtual=1.0,
        weight_throughput=1.0,
    )
    clamped = optimizer_module._clamp_genome(
        optimizer_module.HeGenome(-300, 300, None), scenario, total_requested_trains=10
    )
    if clamped.departure_shift_s != -300:
        raise AssertionError("负的全局发车时移被错误截成了零")

    shifts = {
        genome.departure_shift_s
        for genome in optimizer_module._initial_genomes(scenario, 10, random.Random(7))
    }
    if not any(value < 0 for value in shifts) or not any(value > 0 for value in shifts):
        raise AssertionError(f"初始种群未覆盖正负时移：{sorted(shifts)}")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    test_energy_slice_aggregation_keeps_full_precision()
    test_fractional_arc_boundaries_align_to_integer_settlement_windows()
    test_downhill_energy_is_not_counted_twice()
    test_multi_storage_terminal_soc_uses_actual_device_ids()
    test_energy_settlement_step_is_independent_from_capacity_slot()
    test_global_departure_shift_search_is_signed()
    invalid_entities = (
        (
            lambda: HeOdDemand("D", "A", "B", "Heavy", 1.5, 0, 10, 20, 1.0, 1.0, 1),
            "train_count",
        ),
        (
            lambda: HeOdDemand("D", "A", "B", "Heavy", 1, 20, 10, 30, 1.0, 1.0, 1),
            "latest_departure_s",
        ),
        (
            lambda: ServiceType("Heavy", "sideways", 1, 0, 0, 0, 50, 20),
            "direction",
        ),
        (
            lambda: ServiceType("Heavy", "forward", 1, 0, 0, 0, 0, 20),
            "nominal_speed_kmh",
        ),
        (lambda: OperationNode("S", "load", -1, 1), "operation_min_s"),
        (lambda: VirtualTrainsetConfig("V", 1.0, -1, 1.0), "initial_trainsets"),
    )
    for constructor, expected_field in invalid_entities:
        try:
            constructor()
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid heavy-empty entity was accepted: {expected_field}")

    scenario_values = {
        "scenario_id": "validation",
        "objective_mode": "capacity_surplus",
        "time_slice_s": 60,
        "max_departure_shift_s": 0,
        "population_size": 2,
        "generations": 1,
        "seed": 1,
        "min_headway_s": 60,
        "section_capacity_per_slot": 1,
        "weight_energy": 1.0,
        "weight_distance": 1.0,
        "weight_connection": 1.0,
        "weight_virtual": 1.0,
        "weight_throughput": 1.0,
    }
    for overrides, expected_field in (
        ({"objective_mode": "unknown"}, "objective_mode"),
        ({"population_size": 0}, "population_size"),
        ({"generations": 0}, "generations"),
        ({"time_slice_s": float("nan")}, "time_slice_s"),
        ({"max_departure_shift_s": -1}, "max_departure_shift_s"),
        ({"weight_energy": -1}, "weight_energy"),
    ):
        try:
            HeScenario(**{**scenario_values, **overrides})
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid heavy-empty scenario was accepted: {overrides!r}")
    for value in (float("nan"), float("inf"), "nan", -1, 1.5, "1.5", "00:60:00"):
        try:
            parse_time_to_s(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"non-finite time was accepted: {value!r}")
    assert parse_time_to_s(0.5) == 12 * 3600
    assert optimizer_module._optional_float(float("inf")) is None
    assert optimizer_module._is_mainline_road({"road": "Shuohuang"})
    assert optimizer_module._strict_optional_float("", "probe") is None
    for value in (True, "bad", "nan", float("inf")):
        try:
            optimizer_module._strict_optional_float(value, "probe")
        except ValueError as exc:
            assert "probe" in str(exc)
        else:
            raise AssertionError(f"invalid explicit optional number was accepted: {value!r}")
    for row, expected_field in (
        ({"mass_tons": "bad"}, "mass_tons"),
        ({"wagon_count": "nan"}, "wagon_count"),
    ):
        try:
            optimizer_module._resolve_service_formation(row, ())
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid service formation value was accepted: {row!r}")
    for row, expected_field in (
        ({"mass_energy_reference_tons": "bad"}, "mass_energy_reference_tons"),
        ({"mass_energy_reference_tons": 0}, "mass_energy_reference_tons"),
        ({"mass_energy_exponent": 1.2}, "requires"),
    ):
        try:
            optimizer_module._effective_energy_kwh_per_km(row, 1000.0)
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid mass-energy scaling was accepted: {row!r}")
    for value in (True, "maybe"):
        try:
            if value is True:
                optimizer_module._finite_number(value, "probe")
            else:
                optimizer_module._boolish(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid heavy-empty input was accepted: {value!r}")

    with TemporaryDirectory() as temp_name:
        power_arm_path = Path(temp_name) / "power_arms.xlsx"
        power_arm_path.touch()
        invalid_power_arm_row = {
            "record_id": "P",
            "source_page": 1.5,
            "road": "",
            "direction": "forward",
            "start_km": 0,
            "center_km": 1,
            "end_km": 2,
            "min_km": 0,
            "max_km": 2,
            "needs_manual_review": "no",
        }
        with patch.object(optimizer_module, "_read_sheet_rows", return_value=[invalid_power_arm_row]):
            try:
                optimizer_module._load_power_arms(power_arm_path)
            except ValueError as exc:
                assert "source_page" in str(exc)
            else:
                raise AssertionError("fractional power-arm source_page was silently truncated")
        zero_origin_row = {
            **invalid_power_arm_row,
            "source_page": 1,
            "start_km": 0,
            "center_km": 0,
            "end_km": 0,
            "min_km": 5,
            "max_km": 10,
        }
        with patch.object(optimizer_module, "_read_sheet_rows", return_value=[zero_origin_row]):
            zero_origin_arm = optimizer_module._load_power_arms(power_arm_path)[0]
        assert zero_origin_arm.start_km == 0.0
        assert zero_origin_arm.center_km == 0.0
        assert zero_origin_arm.end_km == 0.0
        battery_dir = Path(temp_name) / "battery_data"
        battery_dir.mkdir()
        (battery_dir / "battery.json").write_text("[]", encoding="utf-8")
        try:
            optimizer_module._load_battery_parameters(battery_dir)
        except ValueError as exc:
            assert "root" in str(exc)
        else:
            raise AssertionError("non-object heavy-empty battery JSON was accepted")
        invalid_arm_csv = Path(temp_name) / "invalid_power_arms.csv"
        invalid_arm_csv.write_text(
            "section_id,road,start_km,end_km\nP,Shuohuang,bad,10\n",
            encoding="utf-8",
        )
        try:
            optimizer_module._load_power_arm_intervals(invalid_arm_csv)
        except ValueError as exc:
            assert "start_km" in str(exc)
        else:
            raise AssertionError("invalid heavy-empty power-arm bound was silently skipped")

    bundle = load_he_input_template(TEMPLATE)
    test_duplicate_genomes_are_evaluated_once(bundle)
    # 虚拟供电臂模板使用英文方向别名（up/down），而提取的真实表使用中文标签；
    # 两者必须映射到相同的运行弧段电气分配。
    if bundle.infrastructure.power_arms:
        source_arm = bundle.infrastructure.power_arms[0]
        virtual_profile = replace(
            bundle.infrastructure,
            power_arms=(replace(source_arm, direction="down"),),
        )
        attrs = optimizer_module._arc_infrastructure_attributes(
            virtual_profile, source_arm.min_km, source_arm.min_km + 0.1
        )
        if not attrs.power_arm_ids:
            raise AssertionError("English virtual power-arm direction was not matched")
    for invalid_bundle, expected_text in (
        (replace(bundle, service_types={}), "service type"),
        (
            replace(
                bundle,
                demands=(replace(bundle.demands[0], train_type="UNKNOWN"),),
            ),
            "unknown train_type",
        ),
        (
            replace(
                bundle,
                demands=(replace(bundle.demands[0], origin_station="UNKNOWN"),),
            ),
            "unknown station",
        ),
        (
            replace(
                bundle,
                operation_nodes={"UNKNOWN": next(iter(bundle.operation_nodes.values()))},
            ),
            "operation_nodes",
        ),
    ):
        try:
            optimizer_module._validate_he_input_bundle(invalid_bundle)
        except ValueError as exc:
            assert expected_text in str(exc)
        else:
            raise AssertionError(f"invalid heavy-empty references were accepted: {expected_text}")
    with TemporaryDirectory() as station_temp_name:
        station_dir = Path(station_temp_name)
        (station_dir / "stations.csv").write_text(
            "name,position_km\nA,0\nA,1\n",
            encoding="utf-8",
        )
        try:
            optimizer_module._load_station_positions(station_dir)
        except ValueError as exc:
            assert "duplicate" in str(exc)
        else:
            raise AssertionError("duplicate station name was silently overwritten")
        (station_dir / "stations.csv").write_text(
            "name,position_km\nA,inf\n",
            encoding="utf-8",
        )
        try:
            optimizer_module._load_station_positions(station_dir)
        except ValueError as exc:
            assert "position_km" in str(exc)
        else:
            raise AssertionError("infinite station position was accepted")
    original_sheet_reader = optimizer_module._read_sheet_rows
    for duplicated_sheet, expected_text in (
        ("od_demands", "duplicate demand_id"),
        ("service_types", "duplicate train_type"),
        ("operation_nodes", "duplicate station_name"),
        ("scenarios", "duplicate scenario_id"),
    ):
        def _duplicated_rows(path, sheet_name, *, target=duplicated_sheet):
            """函数 _duplicated_rows：执行该模块中的相关处理逻辑。"""
            rows = original_sheet_reader(path, sheet_name)
            if sheet_name == target and rows:
                return [*rows, dict(rows[0])]
            return rows

        with patch.object(optimizer_module, "_read_sheet_rows", side_effect=_duplicated_rows):
            try:
                load_he_input_template(TEMPLATE)
            except ValueError as exc:
                assert expected_text in str(exc)
            else:
                raise AssertionError(f"duplicate {duplicated_sheet} identifier was accepted")
    base_scenario = bundle.scenarios["capacity_surplus_demo"]
    no_initial = optimizer_module._build_candidate(
        bundle,
        base_scenario,
        "NO_INITIAL",
        departure_shift_s=0,
        headway_s=base_scenario.min_headway_s,
    )
    one_initial_bundle = replace(
        bundle,
        virtual_trainset=replace(bundle.virtual_trainset, initial_trainsets=1),
    )
    one_initial = optimizer_module._build_candidate(
        one_initial_bundle,
        base_scenario,
        "ONE_INITIAL",
        departure_shift_s=0,
        headway_s=base_scenario.min_headway_s,
    )
    assert no_initial.virtual_trainset_count == one_initial.virtual_trainset_count + 1
    assert sum(arc.arc_type == "virtual_trainset" for arc in no_initial.arcs) == no_initial.virtual_trainset_count
    assert no_initial.virtual_cost == no_initial.virtual_trainset_count * bundle.virtual_trainset.penalty_cost

    origin_name = bundle.demands[0].origin_station
    constrained_nodes = dict(bundle.operation_nodes)
    constrained_nodes[origin_name] = replace(constrained_nodes[origin_name], capacity_per_slot=1)
    operation_limited = optimizer_module._build_candidate(
        replace(bundle, operation_nodes=constrained_nodes),
        replace(base_scenario, section_capacity_per_slot=99),
        "OPERATION_LIMITED",
        departure_shift_s=0,
        headway_s=base_scenario.min_headway_s,
    )
    assert operation_limited.conflict_count > no_initial.conflict_count
    assert any("operation capacity" in message for message in operation_limited.diagnostics)

    custom_data_dir = Path("data") / "real_shuohuang"
    custom_profile = optimizer_module.load_infrastructure_profile(custom_data_dir)
    with patch.object(
        optimizer_module,
        "load_infrastructure_profile",
        return_value=custom_profile,
    ) as profile_loader:
        optimizer_module.load_he_input_template(TEMPLATE, real_data_dir=custom_data_dir)
    profile_loader.assert_called_once_with(custom_data_dir)
    results = []
    for scenario_id in ("capacity_surplus_demo", "capacity_tight_demo"):
        result = optimize_heavy_empty_network(bundle, scenario_id=scenario_id)
        out_dir = OUTPUT_ROOT / scenario_id
        write_optimization_outputs(result, out_dir)
        results.append(result)
        assert result.best_candidate.delivered_train_count > 0
        assert result.best_candidate.arcs
        assert result.best_candidate.nodes
        assert result.pareto_candidates
        assert result.best_candidate.energy_settlement_rows
        assert result.best_candidate.energy_settlement.direct_used_kwh == 0.0
        assert result.best_candidate.energy_settlement.battery_charge_kwh > 0.0
        # 2026-09-18 起运行基线的最大放电功率为 0 kW（真实最大放电功率未提供，
        # 见 docs/new_real_data_integration_20260918.md），真实数据集场景必须只充电、
        # 不放电；放电结算能力由本文件 summarize_energy_settlement 的显式电池单测覆盖。
        assert result.best_candidate.energy_settlement.battery_discharge_kwh == 0.0, (
            result.best_candidate.energy_settlement
        )
        assert result.best_candidate.electrical_constraint_violation_kwh == 0.0
        assert result.best_candidate.constraint_violation == 0.0
        expected_energy_objective = (
            result.best_candidate.energy_settlement.grid_kwh
            + storage_no_direct_effective_loss_kwh(
                result.best_candidate.energy_settlement.wasted_kwh,
                result.best_candidate.energy_settlement.battery_charge_kwh,
                result.best_candidate.energy_settlement.battery_discharge_kwh,
                result.best_candidate.energy_settlement.final_soc_kwh,
                bundle.battery.round_trip_efficiency,
            )
        )
        if abs(result.best_candidate.energy_objective_kwh - expected_energy_objective) > 1e-6:
            raise AssertionError("Candidate energy objective does not account for terminal parked energy")
        assert (out_dir / "ranked_candidates.csv").exists()
        assert (out_dir / "pareto_candidates.csv").exists()
        assert (out_dir / "time_space_nodes.csv").exists()
        assert (out_dir / "time_space_arcs.csv").exists()
        assert (out_dir / "power_arm_energy_settlement.csv").exists()
        assert (out_dir / "summary.json").exists()
        storage_boundaries = {145.0, 164.0, 200.7}
        arc_boundaries = {
            round(value, 3)
            for arc in result.best_candidate.arcs
            if "running" in arc.arc_type
            for value in (arc.start_km, arc.end_km)
        }
        missing_boundaries = storage_boundaries - arc_boundaries
        if missing_boundaries:
            raise AssertionError(f"Storage boundaries were not used to split running arcs: {missing_boundaries}")
        if not any(arc.storage_section_id for arc in result.best_candidate.arcs if "running" in arc.arc_type):
            raise AssertionError("Storage section IDs are missing from split running arcs")

    feasible = results[0].best_candidate
    parked_settlement = replace(
        feasible.energy_settlement,
        wasted_kwh=0.0,
        grid_kwh=10.0,
        battery_charge_kwh=10.0,
        battery_discharge_kwh=0.0,
        final_soc_kwh=9.0,
    )
    rejected_settlement = replace(
        parked_settlement,
        wasted_kwh=10.0,
        battery_charge_kwh=0.0,
        final_soc_kwh=0.0,
    )
    parked_objective = parked_settlement.grid_kwh + storage_no_direct_effective_loss_kwh(
        parked_settlement.wasted_kwh,
        parked_settlement.battery_charge_kwh,
        parked_settlement.battery_discharge_kwh,
        parked_settlement.final_soc_kwh,
        bundle.battery.round_trip_efficiency,
    )
    rejected_objective = rejected_settlement.grid_kwh + storage_no_direct_effective_loss_kwh(
        rejected_settlement.wasted_kwh,
        rejected_settlement.battery_charge_kwh,
        rejected_settlement.battery_discharge_kwh,
        rejected_settlement.final_soc_kwh,
        bundle.battery.round_trip_efficiency,
    )
    assert abs(rejected_objective - parked_objective) < 1e-9
    infeasible = replace(
        feasible,
        candidate_id="INFEASIBLE_HIGH_THROUGHPUT",
        feasible=False,
        constraint_violation=1.0,
        conflict_count=1,
        throughput_ton_km=feasible.throughput_ton_km * 10.0,
    )
    assert pareto_front((feasible, infeasible)) == (feasible,)
    assert non_dominated_sort((feasible, infeasible))[0] == [feasible]

    with TemporaryDirectory() as temp_name:
        custom_power_arms = Path(temp_name) / "power_arm_intervals.csv"
        with custom_power_arms.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    "road",
                    "direction",
                    "start_km",
                    "end_km",
                    "storage_available",
                    "storage_section_id",
                    "storage_start_km",
                    "storage_end_km",
                ),
            )
            writer.writeheader()
            writer.writerow(
                {
                    "road": "",
                    "direction": "down",
                    "start_km": "100",
                    "end_km": "130",
                    "storage_available": "yes",
                    "storage_section_id": "CUSTOM_STORAGE",
                    "storage_start_km": "111.1",
                    "storage_end_km": "123.4",
                }
            )
        custom_storage = optimizer_module._load_storage_sections(custom_power_arms)
    assert custom_storage == (
        StorageSectionInterval("CUSTOM_STORAGE", 111.1, 123.4, "forward"),
    )
    custom_profile = replace(bundle.infrastructure, storage_sections=custom_storage)
    split_kms = optimizer_module._power_arm_split_kms(custom_profile, 100.0, 130.0)
    assert 111.1 in split_kms and 123.4 in split_kms
    assert 145.0 not in split_kms and 164.0 not in split_kms and 200.7 not in split_kms

    print("heavy-empty network optimizer verification passed")
    for result in results:
        best = result.best_candidate
        print(
            result.scenario.scenario_id,
            {
                "objective_mode": result.scenario.objective_mode,
                "candidate_count": len(result.candidates),
                "pareto_count": len(result.pareto_candidates),
                "best": best.candidate_id,
                "feasible": best.feasible,
                "energy_kwh": round(best.energy_kwh, 3),
                "throughput_ton_km": round(best.throughput_ton_km, 3),
                "virtual_trainset_count": best.virtual_trainset_count,
                "conflict_count": best.conflict_count,
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
