"""Verify provider-file profiling, candidate mappings, and fail-closed reporting."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.profile_external_data import profile_directory


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="external_data_profile_smoke_") as temp_name:
        root = Path(temp_name)
        csv_path = root / "传感器数据.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["车号", "采集时间", "经度", "纬度", "加速度", "累计电度"],
            )
            writer.writeheader()
            writer.writerow({"车号": "H001", "采集时间": "2026-10-29 08:00:00", "经度": "112.1", "纬度": "38.1", "加速度": "0.2", "累计电度": "100.0"})
            writer.writerow({"车号": "H001", "采集时间": "2026-10-29 08:00:01", "经度": "112.2", "纬度": "38.1", "加速度": "0.3", "累计电度": "100.1"})
        json_path = root / "motion.json"
        json_path.write_text(json.dumps({"data": [{"trainNo": "H001", "timestamp": "2026-10-29T08:00:00+08:00", "pitch": 1.2}]}), encoding="utf-8")
        (root / "legacy.xls").write_bytes(b"legacy-provider-export")
        before = csv_path.read_bytes()

        report = profile_directory(root, root / "report", max_rows=10)
        assert report["file_count"] == 3, report
        assert report["error_file_count"] == 0, report
        assert report["unsupported_file_count"] == 1, report
        csv_report = next(item for item in report["reports"] if item["file_name"] == csv_path.name)
        fields = {item["source_field"]: item for item in csv_report["sheets"][0]["fields"]}
        assert fields["车号"]["candidate_canonical_field"] == "train_id"
        assert fields["采集时间"]["candidate_canonical_field"] == "event_time"
        assert fields["经度"]["candidate_canonical_field"] == "longitude"
        assert fields["加速度"]["candidate_canonical_field"] == "acceleration"
        assert csv_path.read_bytes() == before
        assert (root / "report" / "external_data_profile.json").is_file() is False
        print("external data profiler mapping and source immutability: PASS")


if __name__ == "__main__":
    main()
