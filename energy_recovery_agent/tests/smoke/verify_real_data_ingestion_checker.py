# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import csv
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from real_data_ingestion_checker import run_checks


ROOT = Path(__file__).resolve().parents[2]


valid = run_checks(
    ROOT / "data" / "real_shuohuang",
    "all",
    ROOT / "data_templates" / "running_diagram_template.xlsx",
    ROOT / "data" / "real_shuohuang" / "stations.csv",
    ROOT / "data" / "real_shuohuang" / "route_metadata.json",
)
assert valid.checked_files

with tempfile.TemporaryDirectory() as temp_dir:
    bad_path = Path(temp_dir) / "trains.csv"
    with bad_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("name", "mass_tons"))
        writer.writeheader()
        writer.writerow({"name": "bad", "mass_tons": ""})
    invalid = run_checks(
        bad_path,
        "traction",
        ROOT / "data_templates" / "running_diagram_template.xlsx",
        ROOT / "data" / "real_shuohuang" / "stations.csv",
        ROOT / "data" / "real_shuohuang" / "route_metadata.json",
    )
    assert not invalid.is_valid
    assert any(issue.issue_code == "missing_required_column" for issue in invalid.errors)

    station_path = Path(temp_dir) / "stations.csv"
    with station_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("station_id", "name", "position_km"))
        writer.writeheader()
        writer.writerow({"station_id": "S1", "name": "测试站", "position_km": "700"})
    invalid_stations = run_checks(
        station_path,
        "stations",
        ROOT / "data_templates" / "running_diagram_template.xlsx",
        ROOT / "data" / "real_shuohuang" / "stations.csv",
        ROOT / "data" / "real_shuohuang" / "route_metadata.json",
    )
    assert any(issue.issue_code == "km_out_of_mainline" for issue in invalid_stations.errors)

    power_arm_path = Path(temp_dir) / "power_arm_intervals.csv"
    with power_arm_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "section_id",
                "direction",
                "start_km",
                "end_km",
                "max_traction_supply_kw",
                "max_regen_absorption_kw",
                "max_grid_feedback_kw",
                "storage_available",
                "storage_section_id",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "section_id": "bad_arm",
                "direction": "up",
                "start_km": "0",
                "end_km": "1",
                "max_traction_supply_kw": "bad",
                "max_regen_absorption_kw": "-1",
                "max_grid_feedback_kw": "NaN",
                "storage_available": "maybe",
                "storage_section_id": "S-X",
            }
        )
    invalid_power_arms = run_checks(
        power_arm_path,
        "power-arm",
        ROOT / "data_templates" / "running_diagram_template.xlsx",
        ROOT / "data" / "real_shuohuang" / "stations.csv",
        ROOT / "data" / "real_shuohuang" / "route_metadata.json",
    )
    assert not invalid_power_arms.is_valid
    assert any(issue.issue_code == "invalid_electrical_limit" for issue in invalid_power_arms.errors)
    assert any(issue.issue_code == "invalid_storage_available" for issue in invalid_power_arms.errors)

print("real data ingestion checker smoke passed")
