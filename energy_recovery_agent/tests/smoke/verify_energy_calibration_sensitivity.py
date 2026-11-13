# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from energy_calibration_sensitivity import build_sensitivity_rows, run_sensitivity
from energy_calibration_error_analyzer import analyze_energy_errors
from energy_calibration_factor_builder import build_factor_config
from _calibration_success_fixture import write_nonzero_alignment_fixture
from smoke_paths import smoke_output


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    output_dir = smoke_output("energy_calibration_sensitivity_smoke")
    alignment_csv = write_nonzero_alignment_fixture(output_dir / "fixture" / "arc_energy_vs_meter_samples.csv")
    analysis_dir = output_dir / "analysis"
    analyze_energy_errors(alignment_csv, analysis_dir)
    factor_json = output_dir / "energy_calibration_factors.json"
    build_factor_config(
        analysis_dir / "energy_calibration_group_coefficients.csv",
        analysis_dir / "energy_calibration_error_analysis_summary.json",
        factor_json,
        sample_source=alignment_csv,
    )
    summary = run_sensitivity(alignment_csv, factor_json, output_dir)
    if summary["sample_count"] <= 0:
        raise AssertionError("Expected sensitivity samples.")
    if summary["group_median_abs_pct_error"] >= summary["uncalibrated_median_abs_pct_error"]:
        raise AssertionError("Expected grouped calibration to improve median error for the fixture.")
    output_csv = output_dir / "energy_calibration_sensitivity_comparison.csv"
    if not output_csv.exists():
        raise AssertionError("Expected sensitivity comparison CSV.")
    probe_rows = [
        {
            "alignment_status": "aligned",
            "meter_traction_energy_raw": "10",
            "prototype_traction_energy_raw": "10",
        }
    ]
    for invalid_scale in (0, -1, True, float("inf")):
        try:
            build_sensitivity_rows(
                probe_rows,
                {"global": {"sample_count": 1, "traction_scale": invalid_scale}},
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid global sensitivity scale was accepted: {invalid_scale!r}")
    print("energy calibration sensitivity passed")
    print(
        {
            "sample_count": summary["sample_count"],
            "uncalibrated_median": round(summary["uncalibrated_median_abs_pct_error"], 6),
            "global_median": round(summary["global_median_abs_pct_error"], 6),
            "group_median": round(summary["group_median_abs_pct_error"], 6),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
