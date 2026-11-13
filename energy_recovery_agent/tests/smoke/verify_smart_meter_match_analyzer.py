# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import csv
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from smart_meter_match_analyzer import analyze_matches, diagnosis_hint
from _smart_meter_success_fixture import write_success_fixture


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    with TemporaryDirectory() as temp_name:
        fixture_dir = Path(temp_name)
        match_csv = write_success_fixture(fixture_dir / "smart_meter_time_window_matches.csv")
        output_dir = fixture_dir / "analysis"
        summary = analyze_matches(match_csv, output_dir)
        if summary["candidate_count"] != 1 or summary["mismatch_count"] != 1:
            raise AssertionError("Synthetic matches did not exercise both analyzer success branches.")
        candidate_csv = output_dir / "smart_meter_calibration_candidates.csv"
        mismatch_csv = output_dir / "smart_meter_mismatch_analysis.csv"
        if not candidate_csv.exists() or not mismatch_csv.exists():
            raise AssertionError("Expected analyzer CSV outputs were not written.")
        with candidate_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            first = next(csv.DictReader(handle), None)
        if first is None or first.get("match_status") != "matched_energy_consistent":
            raise AssertionError("Unexpected calibration candidate from synthetic successful match.")
        with mismatch_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            mismatch = next(csv.DictReader(handle), None)
        if mismatch is None or not mismatch.get("diagnosis_hint"):
            raise AssertionError("Mismatch analysis did not produce a diagnosis.")
        for invalid_count in ("1.5", "inf", -1, True):
            try:
                diagnosis_hint({"point_count_in_window": invalid_count}, None, None)
            except ValueError as exc:
                assert "point_count_in_window" in str(exc)
            else:
                raise AssertionError(f"Invalid smart-meter point count was accepted: {invalid_count!r}")
    print("smart meter match analyzer passed")
    print({"candidate_count": summary["candidate_count"], "mismatch_count": summary["mismatch_count"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
