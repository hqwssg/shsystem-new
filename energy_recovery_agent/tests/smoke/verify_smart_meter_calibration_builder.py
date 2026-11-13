# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import csv
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from smart_meter_calibration_builder import build_calibration_samples
from smart_meter_match_analyzer import analyze_matches
from _smart_meter_success_fixture import write_success_fixture


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    with TemporaryDirectory() as temp_name:
        fixture_dir = Path(temp_name)
        match_csv = write_success_fixture(fixture_dir / "smart_meter_time_window_matches.csv")
        analysis_dir = fixture_dir / "analysis"
        analysis = analyze_matches(match_csv, analysis_dir)
        if analysis["candidate_count"] != 1:
            raise AssertionError("Synthetic upstream match did not produce one calibration candidate.")
        candidate_csv = analysis_dir / "smart_meter_calibration_candidates.csv"
        output_csv = fixture_dir / "smart_meter_calibration_samples.csv"
        summary = build_calibration_samples(candidate_csv, output_csv)
        if summary["sample_count"] != 1:
            raise AssertionError("Expected exactly one synthetic calibration sample.")
        with output_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            first = next(csv.DictReader(handle), None)
        if first is None:
            raise AssertionError("Calibration sample CSV is empty.")
        if first.get("traction_energy_raw") != "120" or first.get("regen_energy_raw") != "20":
            raise AssertionError("Calibration sample did not preserve the interval energy values.")
        if first.get("net_energy_raw") != "100" or first.get("duration_s") != "600":
            raise AssertionError("Calibration sample derived fields are incorrect.")
        if first.get("calibration_status") != "usable_high_confidence":
            raise AssertionError("Successful match was not classified as usable calibration data.")
    print("smart meter calibration builder passed")
    print({"sample_count": summary["sample_count"], "output_csv": str(output_csv)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
