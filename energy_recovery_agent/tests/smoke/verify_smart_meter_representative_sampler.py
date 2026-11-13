# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import csv
import sys
from tempfile import TemporaryDirectory

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from smart_meter_representative_sampler import build_representative_samples
from smoke_paths import smoke_output


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    output_csv = smoke_output("smart_meter_representative_sampler_smoke", "smart_meter_representative_interval_samples.csv")
    with TemporaryDirectory(prefix="representative_sampler_source_") as temp_name:
        source_dir = Path(temp_name)
        fields = [
            "guid", "trainid", "starttime", "endtime", "start_station", "end_station",
            "use_ygdn", "use_fkdn", "start_ygdn", "end_ygdn", "start_fkdn", "end_fkdn",
        ]
        with (source_dir / "nhtj_jkfile_ammeter_info_fixture.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow({"guid": "A58", "trainid": "58A", "starttime": "2026-01-01 00:00:00", "endtime": "2026-01-01 00:10:00", "start_station": "A", "end_station": "B", "use_ygdn": 6, "use_fkdn": 2, "start_ygdn": 10, "end_ygdn": 16, "start_fkdn": 3, "end_fkdn": 5})
            writer.writerow({"guid": "A151", "trainid": "151B", "starttime": "2026-01-01 01:00:00", "endtime": "2026-01-01 01:10:00", "start_station": "B", "end_station": "C", "use_ygdn": 5, "use_fkdn": 1, "start_ygdn": 20, "end_ygdn": 25, "start_fkdn": 4, "end_fkdn": 5})
        with (source_dir / "nhtj_jkfile_station_fixture.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow({"guid": "S1", "trainid": "58A", "starttime": "2026-01-01 00:00:00", "endtime": "2026-01-01 00:08:00"})
            writer.writerow({"guid": "S2", "trainid": "58A", "starttime": "2026-01-01 00:05:00", "endtime": "2026-01-01 00:12:00"})
        for trainid in ("58A", "151B"):
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.append(["trainid", "recordtime", "ygdn", "fk_dn", "ammeterid"])
            worksheet.append([trainid, "2026-01-01 00:05:00", 16, 5, f"M{trainid}"])
            workbook.save(source_dir / f"SS4-{trainid}.xlsx")
        summary = build_representative_samples(
            source_dir,
            output_csv,
            max_per_normalized_trainid=5,
            max_realtime_rows_per_file=100000,
        )
    covered = set(summary["realtime_normalized_trainids"])
    if not {"58", "151"}.issubset(covered):
        raise AssertionError(f"Expected representative sampler to cover 58 and 151, got {covered}.")
    if summary["sample_count"] <= 0:
        raise AssertionError("Expected representative samples.")
    if summary["overlap_pair_count_for_realtime_trainids"] <= 0:
        raise AssertionError("Expected overlapped station intervals to be detected and excluded.")
    print("smart meter representative sampler passed")
    print(
        {
            "sample_count": summary["sample_count"],
            "covered": summary["realtime_normalized_trainids"],
            "by_table": summary["sample_counts_by_source_table"],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
