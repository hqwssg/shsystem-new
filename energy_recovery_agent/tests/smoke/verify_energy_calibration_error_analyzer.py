# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from energy_calibration_error_analyzer import analyze_energy_errors
from smoke_paths import smoke_output
from _calibration_success_fixture import write_nonzero_alignment_fixture


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    output_dir = smoke_output("energy_calibration_error_analyzer_smoke")
    alignment_csv = write_nonzero_alignment_fixture(output_dir / "fixture" / "arc_energy_vs_meter_samples.csv")
    summary = analyze_energy_errors(alignment_csv, output_dir)
    if summary["usable_aligned_nonzero_traction_count"] != 120:
        raise AssertionError("Expected all 120 non-zero fixture rows to be usable.")
    if summary["robust_fit_sample_count"] != 60:
        raise AssertionError("Expected 60 aggregated AB rows in the robust fit.")
    if summary["suggested_global_traction_scale"] <= 0:
        raise AssertionError("Expected positive calibration scale.")
    group_coefficients = output_dir / "energy_calibration_group_coefficients.csv"
    group_scaled = output_dir / "energy_calibration_group_scaled_errors.csv"
    if not group_coefficients.exists() or not group_scaled.exists():
        raise AssertionError("Expected group calibration outputs.")
    print("energy calibration error analyzer passed")
    print(
        {
            "usable": summary["usable_aligned_nonzero_traction_count"],
            "robust": summary["robust_fit_sample_count"],
            "scale": round(summary["suggested_global_traction_scale"], 6),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
