# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import csv
import sys
from tempfile import TemporaryDirectory

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from smart_meter_adapter import CONFIRMED_ENERGY_UNIT_STATUS, INTERVAL_MASS_STATUS, load_smart_meter_directory, write_calibration_csv
from smoke_paths import smoke_output


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    with TemporaryDirectory(prefix="smart_meter_adapter_smoke_") as temp_name:
        source_dir = Path(temp_name)
        interval_headers = [
            "guid", "unitid", "traintypeid", "trainid", "sxx", "trainorder",
            "starttime", "endtime", "start_station", "end_station", "use_ygdn",
            "use_fkdn", "train_weight", "train_load", "a_use_ygdn", "b_use_ygdn",
            "c_use_ygdn", "a_use_fkdn", "b_use_fkdn", "c_use_fkdn", "start_ygdn",
            "end_ygdn", "start_fkdn", "end_fkdn",
        ]
        with (source_dir / "nhtj_jkfile_ammeter_info_fixture.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=interval_headers)
            writer.writeheader()
            writer.writerow(
                {
                    "guid": "G1", "unitid": "U1", "traintypeid": "225", "trainid": "T1",
                    "sxx": "1", "trainorder": "1", "starttime": "2026-01-01 00:00:00",
                    "endtime": "2026-01-01 00:10:00", "start_station": "A", "end_station": "B",
                    "use_ygdn": 6, "use_fkdn": 3, "train_weight": 10000, "train_load": 8000,
                    "a_use_ygdn": 1, "b_use_ygdn": 2, "c_use_ygdn": 3,
                    "a_use_fkdn": 1, "b_use_fkdn": 1, "c_use_fkdn": 1,
                    "start_ygdn": 10, "end_ygdn": 16, "start_fkdn": 2, "end_fkdn": 5,
                }
            )
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["id", "unitid", "traintypeid", "trainid", "recordtime", "ygdn", "fk_dn", "ammeterid", "zz"])
        worksheet.append(["R1", "U1", "225", "T1", "2026-01-01 00:05:00", 16, 5, "M1", 10000])
        workbook.save(source_dir / "SS4-fixture.xlsx")
        result = load_smart_meter_directory(source_dir, max_rows_per_file=5)
    if result.errors:
        for issue in result.errors:
            print(issue)
        raise AssertionError(f"Smart meter adapter has {len(result.errors)} errors.")
    if not result.records:
        raise AssertionError("Smart meter adapter produced no calibration records.")

    first = next(record for record in result.records if record.source_table != "realtime_meter_monitor")
    assert first.trainid
    assert first.positive_energy_raw is not None
    assert first.feedback_energy_raw is not None
    assert first.energy_unit_status == CONFIRMED_ENERGY_UNIT_STATUS
    assert first.mass_mapping_status == INTERVAL_MASS_STATUS
    assert first.abc_sum_status == "confirmed_use_equals_a_b_c_sum"
    assert first.delta_sum_status == "confirmed_use_equals_end_minus_start"
    assert first.association_policy == "trainid_time_window_match"

    realtime_records = [record for record in result.records if record.source_table == "realtime_meter_monitor"]
    if not realtime_records:
        raise AssertionError("Expected SS4 realtime meter records to be loaded.")
    assert realtime_records[0].association_policy == "trainid_recordtime_match"
    assert realtime_records[0].realtime_positive_cumulative_raw is not None

    output_csv = smoke_output("smart_meter_calibration", "smart_meter_adapter_smoke.csv")
    write_calibration_csv(result.records, output_csv)
    if not output_csv.exists():
        raise AssertionError(f"Expected output CSV {output_csv} was not written.")

    print("smart meter adapter passed")
    print({"record_count": len(result.records), "warning_count": len(result.warnings), "output_csv": str(output_csv)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
