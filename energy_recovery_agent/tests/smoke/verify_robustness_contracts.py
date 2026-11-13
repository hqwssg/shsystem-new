# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import replace
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from energy_settlement import (
    EnergySettlementSystem,
    ensure_storage_section_state,
    initialize_storage_settlement_state,
)
from power_arm_electrical_limits import PowerArmElectricalLimit
from operating_conditions import (
    AdhesionZone,
    OperatingConditions,
    TemporarySpeedRestriction,
    WeatherCondition,
    operating_conditions_from_dict,
)
from rolling_optimizer import (
    DisturbanceScenario,
    GeneratedSchedule,
    ScheduleTemplate,
    TemplateSearchConfig,
    _pad_unique_population,
    clamp_template,
    generate_schedule,
    robust_evaluate_schedule,
)
from train_simulator import (
    BatteryStorageParameters,
    DavisCoefficients,
    RouteData,
    Segment,
    Station,
    TrainParameters,
    TrainSimulator,
    _average_capped_force_power_kW,
    calculate_forces,
    effective_mass_factor,
    load_config,
    lookahead_speed_target_mps,
    run_train_simulation,
)
from operating_conditions import default_operating_conditions
from run_dispatch_case import recommended_energy_observability, safe_pct


def test_invalid_battery_params_rejected() -> None:
    """函数 test_invalid_battery_params_rejected：执行该模块中的相关处理逻辑。"""
    invalid_battery_fields = (
        ("capacity_kwh", -10.0),
        ("round_trip_efficiency", 1.5),
        ("depreciation_cost_per_kwh", -1.0),
        ("grid_price_per_kwh", -2.0),
    )
    for field_name, bad_value in invalid_battery_fields:
        values = {
            "capacity_kwh": 100.0,
            "round_trip_efficiency": 0.9,
            "depreciation_cost_per_kwh": 0.1,
            "grid_price_per_kwh": 0.5,
            "max_charge_power_kW": 0.0,
            "max_discharge_power_kW": 0.0,
        }
        values[field_name] = bad_value
        try:
            EnergySettlementSystem(
                battery=BatteryStorageParameters(**values),
                settlement_time_step_s=1,
                allow_direct_use=False,
                allow_storage=True,
                power_arm_limits={},
            )
        except ValueError as exc:
            if field_name not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid {field_name} was silently adjusted")

    battery = BatteryStorageParameters(100.0, 0.9, 0.1, 0.5)
    try:
        BatteryStorageParameters(100.0, 0.9, 0.1, 0.5, planning_assumption="false")
    except ValueError as exc:
        assert "planning_assumption" in str(exc)
    else:
        raise AssertionError("string battery planning_assumption was accepted as truthy")
    for kwargs, expected_field in (
        ({"initial_soc_kwh": 100.1}, "initial_soc_kwh"),
        ({"target_final_soc_kwh": 100.1}, "target_final_soc_kwh"),
        ({"final_soc_tolerance_kwh": -1.0}, "final_soc_tolerance_kwh"),
        ({"allow_storage": "false"}, "allow_storage"),
    ):
        try:
            EnergySettlementSystem(battery, power_arm_limits={}, **kwargs)
        except (TypeError, ValueError) as exc:
            if expected_field not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid settlement parameter was accepted: {kwargs!r}")

    for value in (0, -1, 1.5, float("nan")):
        try:
            EnergySettlementSystem(
                BatteryStorageParameters(100.0, 0.9, 0.1, 0.5),
                settlement_time_step_s=value,
                power_arm_limits={},
            )
        except ValueError as exc:
            if "settlement_time_step_s" not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid settlement step was accepted: {value!r}")


def test_none_series_type_error() -> None:
    """函数 test_none_series_type_error：执行该模块中的相关处理逻辑。"""
    system = EnergySettlementSystem(
        battery=BatteryStorageParameters(100.0, 0.9, 0.1, 0.5),
        settlement_time_step_s=10,
        allow_direct_use=False,
        allow_storage=True,
        power_arm_limits={},
    )
    try:
        system.settle([None])  # type: ignore[list-item]
    except TypeError as exc:
        if "power_series_list[0]" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("expected TypeError for None series")


def test_negative_train_counts_rejected() -> None:
    """函数 test_negative_train_counts_rejected：执行该模块中的相关处理逻辑。"""
    template = ScheduleTemplate(
        heavy_headway_s=1000,
        empty_headway_s=1000,
        heavy_empty_phase_s=0,
        heavy_count=-2,
        empty_count=-3,
        start_time_s=0,
        flex_zone_hold_s=0,
        storage_align_shift_s=0,
        storage_preset_id="",
    )
    for operation in (generate_schedule, lambda value: clamp_template(value, TemplateSearchConfig())):
        try:
            operation(template)
        except ValueError as exc:
            if "count" not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError("negative train counts were silently accepted")

    negative_departure = ScheduleTemplate(
        1000,
        1000,
        0,
        1,
        1,
        storage_align_shift_s=-120,
    )
    safe = clamp_template(negative_departure, TemplateSearchConfig())
    if safe.storage_align_shift_s != 0:
        raise AssertionError(
            "template clamping did not prevent a negative first empty departure"
        )
    try:
        generate_schedule(negative_departure)
    except ValueError as exc:
        if "negative" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("negative empty-train departure was silently generated")

    for template, operation, expected_field in (
        (ScheduleTemplate(900.5, 900, 0, 1, 1), generate_schedule, "heavy_headway_s"),
        (ScheduleTemplate(900, 900, 0, 1.5, 1), generate_schedule, "heavy_count"),
        (
            ScheduleTemplate(900, 900, 0, 1, 1, storage_align_shift_s=float("nan")),
            lambda value: clamp_template(value, TemplateSearchConfig()),
            "storage_align_shift_s",
        ),
    ):
        try:
            operation(template)
        except ValueError as exc:
            if expected_field not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"fractional template gene was accepted: {expected_field}")


def test_empty_robust_scenario_list_rejected() -> None:
    """函数 test_empty_robust_scenario_list_rejected：执行该模块中的相关处理逻辑。"""
    schedule = GeneratedSchedule([], [], ScheduleTemplate(900, 900, 0, 0, 0))
    try:
        robust_evaluate_schedule(schedule, [], None, None, None, {})  # type: ignore[arg-type]
    except ValueError as exc:
        if "at least one disturbance scenario" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("expected ValueError for empty disturbance scenarios")


def test_invalid_scenario_cost_multipliers_rejected() -> None:
    """函数 test_invalid_scenario_cost_multipliers_rejected：执行该模块中的相关处理逻辑。"""
    for value in (float("nan"), float("inf"), float("-inf"), -0.1, True):
        try:
            DisturbanceScenario("invalid", cost_multiplier=value)
        except ValueError as exc:
            if "cost_multiplier" not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"expected ValueError for cost_multiplier={value!r}")

    for field_name in (
        "heavy_delay_s",
        "empty_delay_s",
        "heavy_headway_stretch_s",
        "empty_headway_stretch_s",
    ):
        for value in (float("nan"), float("inf"), 1.5, -1, True):
            try:
                DisturbanceScenario("invalid", **{field_name: value})
            except ValueError as exc:
                if field_name not in str(exc):
                    raise AssertionError(exc) from exc
            else:
                raise AssertionError(f"expected ValueError for {field_name}={value!r}")
    try:
        DisturbanceScenario("invalid", core_for_feasibility="false")
    except ValueError as exc:
        assert "core_for_feasibility" in str(exc)
    else:
        raise AssertionError("non-boolean core_for_feasibility was accepted")
    for constructor, expected_field in (
        (lambda: Station("S", True), "station.position_km"),
        (lambda: WeatherCondition("weather", start_time_s=True), "start_time_s"),
    ):
        try:
            constructor()
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"boolean numeric input was accepted: {expected_field}")
    route, trains, _battery = load_config(Path("sandbox_config.json"))
    for kwargs, expected_field in (
        ({"delta_t_s": True}, "delta_t_s"),
        ({"start_time_s": -1}, "start_time_s"),
    ):
        try:
            run_train_simulation(route, trains["Heavy"], **kwargs)
        except ValueError as exc:
            assert expected_field in str(exc)
        else:
            raise AssertionError(f"invalid train simulation timing was accepted: {kwargs!r}")


def test_non_finite_settlement_parameters_rejected() -> None:
    """函数 test_non_finite_settlement_parameters_rejected：执行该模块中的相关处理逻辑。"""
    fields = {
        "capacity_kwh": float("inf"),
        "round_trip_efficiency": float("nan"),
        "depreciation_cost_per_kwh": float("inf"),
        "grid_price_per_kwh": float("inf"),
        "max_charge_power_kW": float("inf"),
        "max_discharge_power_kW": float("nan"),
    }
    for field_name, bad_value in fields.items():
        values = {
            "capacity_kwh": 100.0,
            "round_trip_efficiency": 0.9,
            "depreciation_cost_per_kwh": 0.1,
            "grid_price_per_kwh": 0.5,
            "max_charge_power_kW": 100.0,
            "max_discharge_power_kW": 100.0,
        }
        values[field_name] = bad_value
        try:
            EnergySettlementSystem(
                BatteryStorageParameters(**values),
                power_arm_limits={},
            )
        except ValueError as exc:
            if "finite" not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"expected ValueError for {field_name}={bad_value!r}")

    for field_name in ("max_charge_power_kW", "max_discharge_power_kW"):
        values = {
            "capacity_kwh": 100.0,
            "round_trip_efficiency": 0.9,
            "depreciation_cost_per_kwh": 0.1,
            "grid_price_per_kwh": 0.5,
            "max_charge_power_kW": 100.0,
            "max_discharge_power_kW": 100.0,
        }
        values[field_name] = -1.0
        try:
            EnergySettlementSystem(BatteryStorageParameters(**values), power_arm_limits={})
        except ValueError as exc:
            if "non-negative" not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"negative {field_name} became an unbounded power limit")


def test_storage_state_soc_is_bounded_and_conserved_on_late_section() -> None:
    """函数 test_storage_state_soc_is_bounded_and_conserved_on_late_section：执行该模块中的相关处理逻辑。"""
    try:
        initialize_storage_settlement_state(
            ["S1"], 100.0, 100.0, 100.0, 180.0, 0.9
        )
    except ValueError as exc:
        if "initial_soc_kwh" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("initial SOC above capacity was silently clipped")

    state = initialize_storage_settlement_state(
        ["S1"], 100.0, 100.0, 100.0, 80.0, 0.9
    )
    ensure_storage_section_state(state, "S2")
    if abs(sum(state.soc_by_storage_kwh.values()) - 80.0) > 1e-9:
        raise AssertionError(f"SOC was not conserved: {state.soc_by_storage_kwh}")
    if any(value > state.capacity_per_storage_kwh + 1e-9 for value in state.soc_by_storage_kwh.values()):
        raise AssertionError(f"per-section capacity exceeded: {state}")

    legacy = initialize_storage_settlement_state([], 100.0, 100.0, 100.0, 40.0, 0.9)
    ensure_storage_section_state(legacy, "S1")
    if legacy.soc_by_storage_kwh != {"S1": 40.0}:
        raise AssertionError(f"legacy SOC was not migrated: {legacy.soc_by_storage_kwh}")

    # 连续充放电可能产生机器精度量级的负零，应归零但不能放过真实负SOC。
    state.soc_by_storage_kwh["S1"] = -1e-15
    ensure_storage_section_state(state, "S1")
    if state.soc_by_storage_kwh["S1"] != 0.0:
        raise AssertionError(f"tiny negative SOC was not normalized: {state.soc_by_storage_kwh}")
    state.soc_by_storage_kwh["S1"] = -1e-6
    try:
        ensure_storage_section_state(state, "S1")
    except ValueError as exc:
        if "must be non-negative" not in str(exc):
            raise AssertionError(exc) from exc
    else:
        raise AssertionError("materially negative SOC was silently normalized")


def test_invalid_search_configs_rejected() -> None:
    """函数 test_invalid_search_configs_rejected：执行该模块中的相关处理逻辑。"""
    invalid_cases = (
        ({"method": "unknown"}, "method"),
        ({"population_size": 0}, "population_size"),
        ({"generations": 1.5}, "generations"),
        ({"elite_count": float("nan")}, "elite_count"),
        ({"parallel_workers": -1}, "parallel_workers"),
        ({"headway_mutation_s": -1}, "headway_mutation_s"),
        ({"mutation_probability": 1.01}, "mutation_probability"),
        ({"storage_preset_mutation_probability": float("inf")}, "storage_preset_mutation_probability"),
        ({"min_headway_s": 901, "max_headway_s": 900}, "max_headway_s"),
    )
    for kwargs, expected_field in invalid_cases:
        try:
            TemplateSearchConfig(**kwargs)
        except ValueError as exc:
            if expected_field not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid search config was accepted: {kwargs!r}")


def test_degenerate_population_padding_terminates() -> None:
    """函数 test_degenerate_population_padding_terminates：执行该模块中的相关处理逻辑。"""
    base = ScheduleTemplate(900, 900, 0, 1, 1)
    config = TemplateSearchConfig(
        population_size=50,
        generations=1,
        headway_mutation_s=0,
        phase_mutation_s=0,
        hold_mutation_s=0,
        storage_shift_mutation_s=0,
        min_headway_s=900,
        max_headway_s=900,
        max_phase_s=0,
        max_hold_s=0,
        max_storage_align_shift_s=0,
        enable_storage_preset_search=False,
    )
    padded = _pad_unique_population([base], base, config, random.Random(1))
    if padded != [base]:
        raise AssertionError(padded)


def test_invalid_operating_conditions_rejected() -> None:
    """函数 test_invalid_operating_conditions_rejected：执行该模块中的相关处理逻辑。"""
    invalid_cases = (
        (lambda: WeatherCondition("rain", start_time_s=10, end_time_s=5), "end_time_s"),
        (lambda: WeatherCondition("rain", rolling_resistance_multiplier=float("nan")), "rolling_resistance_multiplier"),
        (lambda: AdhesionZone("ice", 1.0, 2.0, adhesion_coefficient=0.0), "adhesion_coefficient"),
        (lambda: TemporarySpeedRestriction("work", 1.0, 2.0, 0.0), "speed_limit_kmh"),
        (lambda: OperatingConditions(traction_adhesion_safety_factor=1.1), "traction_adhesion_safety_factor"),
        (lambda: OperatingConditions(weather_conditions=[{"name": "rain"}]), "WeatherCondition"),
        (
            lambda: operating_conditions_from_dict({"default_adhesion_coefficient": True}),
            "default_adhesion_coefficient",
        ),
        (
            lambda: operating_conditions_from_dict(
                {"weather_conditions": [{"name": "rain", "affected_ranges_km": [[True, 2.0]]}]}
            ),
            "affected_ranges_km",
        ),
    )
    for constructor, expected_field in invalid_cases:
        try:
            constructor()
        except ValueError as exc:
            if expected_field not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid operating condition was accepted: {expected_field}")


def test_route_geometry_and_condition_ranges_rejected() -> None:
    """函数 test_route_geometry_and_condition_ranges_rejected：执行该模块中的相关处理逻辑。"""
    route, _trains, _battery = load_config(Path("sandbox_config.json"))
    if route.energy_transfer_ranges_km:
        original_start, original_end = route.energy_transfer_ranges_km[0]
        normalized = replace(
            route,
            energy_transfer_ranges_km=[
                (original_end, original_start),
                *route.energy_transfer_ranges_km[1:],
            ],
        )
        assert normalized.energy_transfer_ranges_km[0] == (
            min(original_start, original_end),
            max(original_start, original_end),
        )
    invalid_cases = (
        (lambda: replace(route, segments=route.segments[1:]), "start at position 0"),
        (lambda: replace(route, stations=list(reversed(route.stations))), "ordered"),
        (lambda: replace(route, signaling_system={"mode": "sideways"}), "mode"),
        (
            lambda: replace(route, signaling_system={"fixed_block_length_km": True}),
            "fixed_block_length_km",
        ),
        (
            lambda: replace(route, signaling_system={"check_step_s": 1.5}),
            "check_step_s",
        ),
        (
            lambda: replace(
                route,
                operating_conditions=OperatingConditions(
                    weather_conditions=[
                        WeatherCondition(
                            "outside_route",
                            affected_ranges_km=[
                                (route.total_length_km, route.total_length_km + 1.0)
                            ],
                        )
                    ]
                ),
            ),
            "exceeds route",
        ),
    )
    for constructor, expected_text in invalid_cases:
        try:
            constructor()
        except ValueError as exc:
            if expected_text not in str(exc):
                raise AssertionError(exc) from exc
        else:
            raise AssertionError(f"invalid route geometry was accepted: {expected_text}")


def test_direct_config_structure_and_train_keys() -> None:
    """函数 test_direct_config_structure_and_train_keys：执行该模块中的相关处理逻辑。"""
    base = json.loads(Path("sandbox_config.json").read_text(encoding="utf-8"))
    invalid_cases = (
        ([], "root"),
        ({**base, "route": []}, "route"),
        ({**base, "trains": {}}, "trains"),
        ({**base, "battery": []}, "battery"),
        (
            {
                **base,
                "route": {**base["route"], "operating_conditions": []},
            },
            "operating_conditions",
        ),
        (
            {
                **base,
                "route": {
                    **base["route"],
                    "operating_conditions": {"weather_conditions": {}},
                },
            },
            "weather_conditions",
        ),
        ({**base, "trains": [{**base["trains"][0], "davis": []}]}, "davis"),
        (
            {
                **base,
                "trains": [
                    base["trains"][0],
                    {**base["trains"][1], "name": f" {base['trains'][0]['name']} "},
                ],
            },
            "duplicate normalized train name",
        ),
    )
    with TemporaryDirectory() as temp_name:
        temp_dir = Path(temp_name)
        for index, (payload, expected_text) in enumerate(invalid_cases):
            path = temp_dir / f"invalid_{index}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            try:
                load_config(path)
            except ValueError as exc:
                assert expected_text in str(exc)
            else:
                raise AssertionError(f"invalid direct config was accepted: {expected_text}")

        normalized_payload = {
            **base,
            "trains": [{**base["trains"][0], "name": f" {base['trains'][0]['name']} "}],
        }
        normalized_path = temp_dir / "normalized.json"
        normalized_path.write_text(json.dumps(normalized_payload), encoding="utf-8")
        _route, normalized_trains, _battery = load_config(normalized_path)
        expected_name = str(base["trains"][0]["name"]).strip()
        assert tuple(normalized_trains) == (expected_name,)


def test_train_mass_bounds_are_consistent() -> None:
    """函数 test_train_mass_bounds_are_consistent：执行该模块中的相关处理逻辑。"""
    _route, trains, _battery = load_config(Path("sandbox_config.json"))
    train = trains["Empty"]
    for overrides, expected_text in (
        ({"mass_min_tons": True}, "mass_min_tons"),
        ({"mass_min_tons": float("nan")}, "mass_min_tons"),
        ({"mass_min_tons": -1.0}, "mass_min_tons"),
        ({"mass_min_tons": train.mass_tons + 1.0}, "below"),
        ({"mass_max_tons": train.mass_tons - 1.0}, "exceed"),
        ({"mass_min_tons": train.mass_tons, "mass_max_tons": train.mass_tons - 1.0}, "must not exceed"),
    ):
        try:
            replace(train, **overrides)
        except ValueError as exc:
            assert expected_text in str(exc)
        else:
            raise AssertionError(f"invalid train mass bounds were accepted: {overrides!r}")


def test_terminal_approach_does_not_teleport_train() -> None:
    """函数 test_terminal_approach_does_not_teleport_train：执行该模块中的相关处理逻辑。"""
    route, trains, _battery = load_config(Path("sandbox_config.json"))
    for train_name in ("Heavy", "Empty"):
        records = run_train_simulation(route, trains[train_name], delta_t_s=10)
        if len(records) < 2:
            raise AssertionError(f"{train_name} simulation did not produce an arrival path")
        terminal_km = route.total_length_km if trains[train_name].direction == "forward" else 0.0
        if abs(records[-1].position_km - terminal_km) > 1e-9:
            raise AssertionError(f"{train_name} did not reach the terminal")
        last_jump_m = abs(records[-1].position_km - records[-2].position_km) * 1000.0
        if last_jump_m > 3.0:
            raise AssertionError(
                f"{train_name} was teleported {last_jump_m:.3f} m onto the terminal"
            )
        final_approach = next(
            record
            for record in records
            if abs(record.position_km - terminal_km) * 1000.0 <= 150.0
        )
        if records[-1].time_s - final_approach.time_s > 360:
            raise AssertionError(
                f"{train_name} spent an implausible {records[-1].time_s - final_approach.time_s}s "
                "in the final 150 m"
            )


def test_acceleration_command_is_not_scaled_by_step_size() -> None:
    """A larger Euler step must not change the commanded physical acceleration."""

    route = RouteData(
        total_length_km=10.0,
        max_speed_kmh=80.0,
        stations=[Station("A", 0.0), Station("B", 10.0)],
        segments=[Segment(0.0, 10.0, 0.0)],
        long_downhill_range_km=(0.0, 0.0),
        energy_transfer_ranges_km=[],
        signaling_system={},
        operating_conditions=default_operating_conditions(),
    )
    train = TrainParameters(
        name="step-invariance",
        mass_tons=1000.0,
        max_traction_kN=300.0,
        max_brake_kN=400.0,
        rotational_mass_factor=1.05,
        davis=DavisCoefficients(0.92, 0.0048, 0.000125),
        max_power_kW=3000.0,
    )
    rb_kN, rg_kN, _ = calculate_forces(train, route, 0.0, 0.0, 0)
    commands = [
        TrainSimulator(route, train, delta_t_s=step).control_traction_brake(
            0.0, 0.0, rb_kN, rg_kN, 0
        )[0]
        for step in (1, 10)
    ]
    if abs(commands[0] - commands[1]) > 1e-9:
        raise AssertionError(
            "traction command changed with the integration step; acceleration was likely scaled by dt"
        )


def test_unit_rotational_mass_factor_is_not_double_counted() -> None:
    """The documented boundary value 1.0 must leave effective mass unchanged."""

    train = TrainParameters(
        name="unit-rotational-factor",
        mass_tons=1000.0,
        max_traction_kN=300.0,
        max_brake_kN=400.0,
        rotational_mass_factor=1.0,
        davis=DavisCoefficients(0.92, 0.0048, 0.000125),
    )
    if abs(effective_mass_factor(train) - 1.0) > 1e-12:
        raise AssertionError(
            "rotational_mass_factor=1.0 was treated as an additive rho term: "
            f"effective_mass_factor={effective_mass_factor(train)}"
        )

    # 纯牵引力加速度检查明确验证能量影响：无阻力时，1000 t 列车承受 100 kN、持续 1 秒，
    # 且倍率为 1 时，速度必须增加 0.1 m/s。
    route = RouteData(
        total_length_km=1.0,
        max_speed_kmh=80.0,
        stations=[Station("A", 0.0), Station("B", 1.0)],
        segments=[Segment(0.0, 1.0, 0.0)],
        long_downhill_range_km=(0.0, 0.0),
        energy_transfer_ranges_km=[],
        signaling_system={},
        operating_conditions=default_operating_conditions(),
    )
    simulator = TrainSimulator(route, train, delta_t_s=1)
    rb_kN, rg_kN, _ = calculate_forces(train, route, 0.0, 0.0, 0)
    command = simulator.control_traction_brake(0.0, 0.0, rb_kN, rg_kN, 0)
    expected_accel_mps2 = (
        (command[0] - command[1] - rb_kN - rg_kN) * 1000.0
        / (train.mass_tons * 1000.0)
    )
    expected_with_helper = (
        (command[0] - command[1] - rb_kN - rg_kN) * 1000.0
        / (train.mass_tons * 1000.0 * effective_mass_factor(train))
    )
    if abs(expected_accel_mps2 - expected_with_helper) > 1e-12:
        raise AssertionError("unit rotational mass factor still altered acceleration")


def test_interval_power_uses_average_speed() -> None:
    """A whole-step energy sample must include work done from standstill."""

    route = RouteData(
        total_length_km=10.0,
        max_speed_kmh=80.0,
        stations=[Station("A", 0.0), Station("B", 10.0)],
        segments=[Segment(0.0, 10.0, 0.0)],
        long_downhill_range_km=(0.0, 0.0),
        energy_transfer_ranges_km=[],
        signaling_system={},
        operating_conditions=default_operating_conditions(),
    )
    train = TrainParameters(
        name="interval-energy",
        mass_tons=1000.0,
        max_traction_kN=300.0,
        max_brake_kN=400.0,
        rotational_mass_factor=1.05,
        davis=DavisCoefficients(0.92, 0.0048, 0.000125),
        max_power_kW=3000.0,
    )
    records = run_train_simulation(route, train, delta_t_s=5)
    first, second = records[:2]
    expected_power_kW = min(
        first.traction_kN * 0.5 * (first.speed_mps + second.speed_mps),
        train.max_power_kW,
    )
    expected_position_km = (
        0.5 * (first.speed_mps + second.speed_mps) * 5.0 / 1000.0
    )
    if first.power_kW <= 0.0:
        raise AssertionError("the first acceleration interval created kinetic energy with zero traction energy")
    if abs(first.power_kW - expected_power_kW) > 1e-9:
        raise AssertionError(
            f"interval traction power did not use average speed: {first.power_kW} != {expected_power_kW}"
        )
    if abs(second.position_km - expected_position_km) > 1e-9:
        raise AssertionError(
            "acceleration-step distance did not integrate the within-step speed: "
            f"{second.position_km} != {expected_position_km}"
        )


def test_traction_power_limit_constrains_motion() -> None:
    """Do not hide an over-power acceleration by clipping only its reported power."""

    route = RouteData(
        total_length_km=10.0,
        max_speed_kmh=80.0,
        stations=[Station("A", 0.0), Station("B", 10.0)],
        segments=[Segment(0.0, 10.0, 0.0)],
        long_downhill_range_km=(0.0, 0.0),
        energy_transfer_ranges_km=[],
        signaling_system={},
        operating_conditions=default_operating_conditions(),
    )
    train = TrainParameters(
        name="low-power",
        mass_tons=1000.0,
        max_traction_kN=300.0,
        max_brake_kN=400.0,
        rotational_mass_factor=1.05,
        davis=DavisCoefficients(0.92, 0.0048, 0.000125),
        max_power_kW=100.0,
    )
    records = run_train_simulation(route, train, delta_t_s=5)
    for current, following in zip(records[:-2], records[1:-1]):
        endpoint_power_kW = current.traction_kN * max(
            current.speed_mps,
            following.speed_mps,
        )
        if endpoint_power_kW > train.max_power_kW + 1e-7:
            raise AssertionError(
                "traction dynamics exceeded the continuous power limit: "
                f"{endpoint_power_kW} > {train.max_power_kW}"
            )


def test_regen_power_cap_is_integrated_within_step() -> None:
    # 10 kN 制动力使速度从 20 m/s 线性降至 0 m/s；功率上限为 100 kW 时，
    # 前半段受上限约束，后半段功率从 100 kW 逐渐降至 0。
    """函数 test_regen_power_cap_is_integrated_within_step：执行该模块中的相关处理逻辑。"""
    average_power_kW = _average_capped_force_power_kW(
        10.0,
        20.0,
        0.0,
        1.0,
        100.0,
    )
    if abs(average_power_kW - 75.0) > 1e-9:
        raise AssertionError(
            f"within-step regenerative cap was not integrated exactly: {average_power_kW}"
        )
    stopped_halfway_power_kW = _average_capped_force_power_kW(
        10.0,
        20.0,
        0.0,
        0.5,
        100.0,
    )
    if abs(stopped_halfway_power_kW - 37.5) > 1e-9:
        raise AssertionError(
            "power after an early stop was still counted for the idle remainder of the step"
        )


def test_terminal_crossing_scales_power_to_travelled_fraction() -> None:
    """A terminal reached mid-step must not receive a full-step energy credit."""

    route = RouteData(
        total_length_km=0.5,
        max_speed_kmh=160.0,
        stations=[Station("A", 0.0), Station("B", 0.5)],
        segments=[Segment(0.0, 0.5, -100.0)],
        long_downhill_range_km=(0.0, 0.5),
        energy_transfer_ranges_km=[],
        signaling_system={},
        operating_conditions=default_operating_conditions(),
    )
    train = TrainParameters(
        name="terminal-energy",
        mass_tons=1000.0,
        max_traction_kN=300.0,
        max_brake_kN=400.0,
        rotational_mass_factor=1.05,
        davis=DavisCoefficients(0.92, 0.0048, 0.000125),
        max_power_kW=3000.0,
    )

    coarse = run_train_simulation(route, train, delta_t_s=10)
    final_motion_sample = coarse[-2]
    if not (-3000.0 < final_motion_sample.power_kW < 0.0):
        raise AssertionError(
            "terminal-crossing power was still integrated over the nominal step: "
            f"power={final_motion_sample.power_kW}"
        )


def test_stationary_terminal_restart_respects_target() -> None:
    """函数 test_stationary_terminal_restart_respects_target：执行该模块中的相关处理逻辑。"""
    route = RouteData(
        total_length_km=10.0,
        max_speed_kmh=80.0,
        stations=[Station("A", 0.0), Station("B", 10.0)],
        segments=[Segment(0.0, 10.0, 0.0)],
        long_downhill_range_km=(0.0, 0.0),
        energy_transfer_ranges_km=[],
        signaling_system={},
        operating_conditions=default_operating_conditions(),
    )
    train = TrainParameters(
        name="terminal-restart",
        mass_tons=1000.0,
        max_traction_kN=300.0,
        max_brake_kN=400.0,
        rotational_mass_factor=1.05,
        davis=DavisCoefficients(0.92, 0.0048, 0.000125),
        max_power_kW=3000.0,
    )
    position_km = 9.997
    simulator = TrainSimulator(route, train, delta_t_s=5)
    rb_kN, rg_kN, _ = calculate_forces(train, route, position_km, 0.0, 0)
    command = simulator.control_traction_brake(position_km, 0.0, rb_kN, rg_kN, 0)
    target_mps = lookahead_speed_target_mps(
        route,
        train,
        position_km,
        0.0,
        0,
        command[3],
        command[7],
    )
    if target_mps >= command[3] - 1e-9:
        raise AssertionError("a stationary train near the terminal ignored the terminal speed target")
    projected_speed_mps = (
        (command[0] - command[1] - rb_kN - rg_kN)
        * 1000.0
        * simulator.delta_t_s
        / (train.mass_tons * 1000.0 * effective_mass_factor(train))
    )
    if projected_speed_mps > target_mps + 1e-9:
        raise AssertionError(
            f"terminal restart overshot its target within one step: {projected_speed_mps} > {target_mps}"
        )


def test_downhill_hold_force_is_not_counted_twice() -> None:
    """函数 test_downhill_hold_force_is_not_counted_twice：执行该模块中的相关处理逻辑。"""
    route = RouteData(
        total_length_km=100.0,
        max_speed_kmh=80.0,
        stations=[Station("A", 0.0), Station("B", 100.0)],
        segments=[Segment(0.0, 100.0, -10.0)],
        long_downhill_range_km=(1.0, 99.0),
        energy_transfer_ranges_km=[],
        signaling_system={},
        operating_conditions=default_operating_conditions(),
    )
    train = TrainParameters(
        name="downhill-hold",
        mass_tons=1000.0,
        max_traction_kN=300.0,
        max_brake_kN=400.0,
        rotational_mass_factor=1.05,
        davis=DavisCoefficients(0.92, 0.0048, 0.000125),
        max_power_kW=3000.0,
    )
    simulator = TrainSimulator(route, train, delta_t_s=5)
    position_km = 50.0
    speed_mps = 21.5
    rb_kN, rg_kN, _ = calculate_forces(train, route, position_km, speed_mps, 0)
    command = simulator.control_traction_brake(
        position_km,
        speed_mps,
        rb_kN,
        rg_kN,
        0,
    )
    raw_target_mps = lookahead_speed_target_mps(
        route,
        train,
        position_km,
        speed_mps,
        0,
        command[3],
        command[7],
    )
    step_margin_mps = min(2.2, max(0.35, 0.14 * simulator.delta_t_s))
    target_mps = min(raw_target_mps, max(0.0, command[3] - step_margin_mps))
    projected_speed_mps = speed_mps + (
        (command[0] - command[1] - rb_kN - rg_kN)
        * 1000.0
        * simulator.delta_t_s
        / (train.mass_tons * 1000.0 * effective_mass_factor(train))
    )
    if abs(projected_speed_mps - target_mps) > 1e-9:
        raise AssertionError(
            "downhill grade was counted more than once in the hold-speed brake: "
            f"{projected_speed_mps} != {target_mps}"
        )


def test_terminal_brake_accounts_for_uphill_resistance() -> None:
    """函数 test_terminal_brake_accounts_for_uphill_resistance：执行该模块中的相关处理逻辑。"""
    train = TrainParameters(
        name="terminal-grade",
        mass_tons=1000.0,
        max_traction_kN=300.0,
        max_brake_kN=400.0,
        rotational_mass_factor=1.05,
        davis=DavisCoefficients(0.92, 0.0048, 0.000125),
        max_power_kW=3000.0,
    )

    def brake_command(gradient_per_mille: float) -> float:
        """函数 brake_command：执行该模块中的相关处理逻辑。"""
        route = RouteData(
            total_length_km=10.0,
            max_speed_kmh=80.0,
            stations=[Station("A", 0.0), Station("B", 10.0)],
            segments=[Segment(0.0, 10.0, gradient_per_mille)],
            long_downhill_range_km=(0.0, 0.0),
            energy_transfer_ranges_km=[],
            signaling_system={},
            operating_conditions=default_operating_conditions(),
        )
        rb_kN, rg_kN, _ = calculate_forces(train, route, 9.999, 0.1, 0)
        return TrainSimulator(route, train).control_traction_brake(
            9.999, 0.1, rb_kN, rg_kN, 0
        )[1]

    flat_brake_kN = brake_command(0.0)
    uphill_brake_kN = brake_command(20.0)
    if uphill_brake_kN >= flat_brake_kN - 1e-9:
        raise AssertionError(
            "terminal brake did not credit the deceleration supplied by an uphill grade"
        )


def test_energy_observability_settings_are_strict() -> None:
    """函数 test_energy_observability_settings_are_strict：执行该模块中的相关处理逻辑。"""
    base = {
        "wasted_energy_penalty_per_kwh": 0.0,
        "enable_energy_observability": True,
        "disable_energy_observability": False,
    }
    assert recommended_energy_observability(Namespace(**base))[
        "applied_wasted_energy_penalty_per_kwh"
    ] == 0.05
    for override, expected_text in (
        ({"wasted_energy_penalty_per_kwh": True}, "wasted_energy_penalty_per_kwh"),
        ({"wasted_energy_penalty_per_kwh": -1.0}, "wasted_energy_penalty_per_kwh"),
        ({"wasted_energy_penalty_per_kwh": float("nan")}, "wasted_energy_penalty_per_kwh"),
        ({"enable_energy_observability": "false"}, "enable_energy_observability"),
        ({"disable_energy_observability": 0}, "disable_energy_observability"),
    ):
        try:
            recommended_energy_observability(Namespace(**{**base, **override}))
        except ValueError as exc:
            assert expected_text in str(exc)
        else:
            raise AssertionError(f"invalid energy observability setting was accepted: {override!r}")


def test_zero_baseline_percentage_is_not_reported_as_no_change() -> None:
    """函数 test_zero_baseline_percentage_is_not_reported_as_no_change：执行该模块中的相关处理逻辑。"""
    if safe_pct(0.0, 0.0) != 0.0:
        raise AssertionError("zero-to-zero comparison must remain an exact 0% change")
    if safe_pct(0.0, 1.0) is not None:
        raise AssertionError("an increase from a zero baseline has no finite reduction percentage")
    if safe_pct(10.0, 8.0) != 20.0:
        raise AssertionError("ordinary reduction percentage changed")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    test_invalid_battery_params_rejected()
    test_none_series_type_error()
    test_negative_train_counts_rejected()
    test_empty_robust_scenario_list_rejected()
    test_invalid_scenario_cost_multipliers_rejected()
    test_non_finite_settlement_parameters_rejected()
    test_storage_state_soc_is_bounded_and_conserved_on_late_section()
    test_invalid_search_configs_rejected()
    test_degenerate_population_padding_terminates()
    test_invalid_operating_conditions_rejected()
    test_route_geometry_and_condition_ranges_rejected()
    test_direct_config_structure_and_train_keys()
    test_train_mass_bounds_are_consistent()
    test_terminal_approach_does_not_teleport_train()
    test_acceleration_command_is_not_scaled_by_step_size()
    test_unit_rotational_mass_factor_is_not_double_counted()
    test_interval_power_uses_average_speed()
    test_traction_power_limit_constrains_motion()
    test_regen_power_cap_is_integrated_within_step()
    test_terminal_crossing_scales_power_to_travelled_fraction()
    test_stationary_terminal_restart_respects_target()
    test_downhill_hold_force_is_not_counted_twice()
    test_terminal_brake_accounts_for_uphill_resistance()
    test_energy_observability_settings_are_strict()
    test_zero_baseline_percentage_is_not_reported_as_no_change()
    print("robustness contract verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
