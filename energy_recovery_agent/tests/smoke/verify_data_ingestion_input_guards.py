# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data_ingestion import (
    RESOURCE_CONFIG_FILE,
    BATTERY_FILE,
    OPERATING_CONDITIONS_FILE,
    ROUTE_METADATA_FILE,
    SIGNAL_BLOCKS_FILE,
    STATIONS_FILE,
    TECHNICAL_OPERATION_TIMES_FILE,
    TRAINS_FILE,
    _bool,
    _optional_float,
    _optional_int,
    _as_range,
    load_real_data_bundle,
    validate_real_data_bundle,
    write_real_data_template_from_config,
)


TEMPLATE_DIR = Path("data_templates") / "shuohuang_virtual"


def _expect_value_error(callable_obj, expected_text: str) -> None:
    """函数 _expect_value_error：执行该模块中的相关处理逻辑。"""
    try:
        callable_obj()
    except ValueError as exc:
        assert expected_text in str(exc)
    else:
        raise AssertionError(f"invalid input was accepted; expected {expected_text!r}")


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    _expect_value_error(lambda: _optional_int("1.5"), "whole number")
    _expect_value_error(lambda: _optional_float("inf"), "finite")
    _expect_value_error(lambda: _bool("tru"), "boolean")
    assert _optional_int("2.0") == 2
    assert _bool("false") is False
    assert _as_range([0, 0]) == (0.0, 0.0)
    _expect_value_error(lambda: _as_range([True, 2]), "finite numbers")
    _expect_value_error(lambda: _as_range([1]), "exactly two")

    with TemporaryDirectory() as temp_name:
        invalid_dir = Path(temp_name) / "invalid_bundle"
        shutil.copytree(TEMPLATE_DIR, invalid_dir)

        signal_path = invalid_dir / SIGNAL_BLOCKS_FILE
        with signal_path.open("r", encoding="utf-8-sig", newline="") as handle:
            signal_rows = list(csv.DictReader(handle))
        signal_rows[0]["is_single_line"] = "flase"
        with signal_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(signal_rows[0]))
            writer.writeheader()
            writer.writerows(signal_rows)

        resource_path = invalid_dir / RESOURCE_CONFIG_FILE
        resource_config = json.loads(resource_path.read_text(encoding="utf-8"))
        resource_config["enforce_flow_continuity"] = "sometimes"
        resource_config["station_track_capacity"] = True
        resource_config["single_line_ranges_km"] = [[True, 2.0]]
        resource_path.write_text(json.dumps(resource_config, indent=2), encoding="utf-8")

        route_path = invalid_dir / ROUTE_METADATA_FILE
        route_config = json.loads(route_path.read_text(encoding="utf-8"))
        route_section = route_config.get("route", route_config)
        route_section["long_downhill_range_km"] = [True, 2.0]
        route_section.setdefault("signaling_system", {})["check_step_s"] = True
        route_path.write_text(json.dumps(route_config, indent=2), encoding="utf-8")

        battery_path = invalid_dir / BATTERY_FILE
        battery_config = json.loads(battery_path.read_text(encoding="utf-8"))
        battery_config["capacity_kwh"] = True
        battery_config["planning_assumption"] = "flase"
        battery_path.write_text(json.dumps(battery_config, indent=2), encoding="utf-8")

        operating_path = invalid_dir / OPERATING_CONDITIONS_FILE
        operating_path.write_text(
            json.dumps(
                {
                    "default_adhesion_coefficient": True,
                    "weather_conditions": [
                        {
                            "name": "invalid_weather",
                            "start_time_s": 10,
                            "end_time_s": 5,
                            "affected_ranges_km": [["not-a-number", 2.0]],
                            "speed_limit_kmh": True,
                        }
                    ],
                    "speed_restrictions": [
                        {
                            "name": "invalid_direction",
                            "start_km": 0,
                            "end_km": 1,
                            "speed_limit_kmh": 60,
                            "direction": "sideways",
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        with (invalid_dir / STATIONS_FILE).open("r", encoding="utf-8-sig", newline="") as handle:
            first_station = next(csv.DictReader(handle))["name"]
        operation_path = invalid_dir / TECHNICAL_OPERATION_TIMES_FILE
        operation_fields = (
            "station_name",
            "operation_location",
            "cars",
            "operation_type",
            "spotting_min",
            "loading_unloading_min",
            "pickup_min",
            "total_min",
        )
        with operation_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=operation_fields)
            writer.writeheader()
            writer.writerow(
                {
                    "station_name": first_station,
                    "operation_location": "yard",
                    "cars": "1.5",
                    "operation_type": "load",
                    "spotting_min": "1",
                    "loading_unloading_min": "1",
                    "pickup_min": "1",
                    "total_min": "3",
                }
            )

        report = validate_real_data_bundle(invalid_dir)
        invalid_fields = {issue.field for issue in report.errors}
        assert {
            "is_single_line",
            "enforce_flow_continuity",
            "station_track_capacity",
            "single_line_ranges_km[0]",
            "long_downhill_range_km",
            "signaling_system.check_step_s",
            "planning_assumption",
            "capacity_kwh",
            "default_adhesion_coefficient",
            "affected_ranges_km[0].start",
            "speed_limit_kmh",
            "start_time_s,end_time_s",
            "direction",
            "cars",
        } <= invalid_fields
        _expect_value_error(
            lambda: load_real_data_bundle(invalid_dir),
            "real-data validation failed",
        )

    with TemporaryDirectory() as temp_name:
        zero_force_dir = Path(temp_name) / "zero_force_bundle"
        shutil.copytree(TEMPLATE_DIR, zero_force_dir)
        trains_path = zero_force_dir / TRAINS_FILE
        with trains_path.open("r", encoding="utf-8-sig", newline="") as handle:
            train_rows = list(csv.DictReader(handle))
        train_rows[0]["max_traction_kN"] = "0"
        with trains_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(train_rows[0]))
            writer.writeheader()
            writer.writerows(train_rows)
        report = validate_real_data_bundle(zero_force_dir)
        if report.is_valid or not any(
            issue.field == "max_traction_kN" for issue in report.errors
        ):
            raise AssertionError(
                "zero max_traction_kN passed data validation even though TrainParameters rejects it"
            )
        _expect_value_error(
            lambda: load_real_data_bundle(zero_force_dir),
            "real-data validation failed",
        )

    with TemporaryDirectory() as temp_name:
        non_object_dir = Path(temp_name) / "non_object_bundle"
        shutil.copytree(TEMPLATE_DIR, non_object_dir)
        (non_object_dir / ROUTE_METADATA_FILE).write_text("[]", encoding="utf-8")
        report = validate_real_data_bundle(non_object_dir)
        assert any(issue.code == "invalid_json_object" for issue in report.errors)

    base_config = json.loads(Path("sandbox_config.json").read_text(encoding="utf-8"))
    for invalid_block_length in (0, -1, True, float("inf"), "bad"):
        with TemporaryDirectory() as temp_name:
            invalid_config = json.loads(json.dumps(base_config))
            invalid_config["route"].setdefault("signaling_system", {})[
                "fixed_block_length_km"
            ] = invalid_block_length
            config_path = Path(temp_name) / "invalid_config.json"
            config_path.write_text(json.dumps(invalid_config), encoding="utf-8")
            _expect_value_error(
                lambda: write_real_data_template_from_config(
                    config_path,
                    Path(temp_name) / "generated",
                ),
                "fixed_block_length_km",
            )

    print("data ingestion strict numeric and boolean guards passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
