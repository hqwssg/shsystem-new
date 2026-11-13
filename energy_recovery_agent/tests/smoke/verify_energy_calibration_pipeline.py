# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from pathlib import Path
import sys
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from run_energy_calibration_pipeline import run_pipeline
from smoke_paths import smoke_output


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    output_dir = smoke_output("energy_calibration_pipeline_smoke")
    data_dir = Path("data") / "real_shuohuang"
    protected_paths = [
        data_dir / "smart_meter_calibration_samples.csv",
        data_dir / "smart_meter_calibration_samples_summary.json",
        data_dir / "energy_calibration_factors.json",
    ]
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in protected_paths
        if path.exists()
    }
    summary = run_pipeline(
        smart_meter_dir=Path("data") / "source" / "smart_meter",
        data_dir=data_dir,
        output_dir=output_dir,
        boundary_tolerance_s=300.0,
        energy_tolerance=1.0,
        max_interval_rows_per_file=2000,
        max_realtime_rows_per_file=5000,
        overlap_policy="exclude",
        representative_samples=True,
        max_per_realtime_trainid=2,
        publish_calibration=False,
        restrict_to_realtime_coverage=True,
    )
    after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in protected_paths
        if path.exists()
    }
    if before != after:
        raise AssertionError("Calibration smoke test modified protected real-data files.")
    if summary["inputs"].get("publish_calibration"):
        raise AssertionError("Calibration smoke test must not publish into data-dir.")
    if not str(summary["outputs"]["calibration_samples"]).startswith(str(output_dir)):
        raise AssertionError("Calibration samples must be written under the test output directory.")
    if summary["outputs"]["factor_config"] and not str(summary["outputs"]["factor_config"]).startswith(str(output_dir)):
        raise AssertionError("Calibration factor output path is inconsistent.")
    if summary["inputs"]["overlap_policy"] != "exclude":
        raise AssertionError("Expected pipeline to use overlap exclusion mode.")
    if summary["inputs"].get("restrict_to_realtime_coverage") is not True:
        raise AssertionError("Expected pipeline to restrict matches to SS4 realtime coverage by default.")
    policy = summary["calibration_samples"]["selection_policy"]
    if not str(policy).startswith("representative_by_realtime_trainid"):
        raise AssertionError(f"Expected representative sample selection, got {policy!r}.")
    if summary["inputs"].get("mainline_only") is not True:
        raise AssertionError("Expected mainline_only default to be enabled.")
    sample_count = summary["calibration_samples"]["sample_count"]
    if sample_count == 0:
        if summary["status"] != "incomplete_no_calibration_samples":
            raise AssertionError("Expected an explicit incomplete status when no calibration samples exist.")
        if summary["valid"]:
            raise AssertionError("Zero calibration samples must not be reported as a valid calibration.")
        if (output_dir / "06_factor_config" / "energy_calibration_factors.json").exists():
            raise AssertionError("Zero calibration samples must not generate a factor config.")
        print("energy calibration pipeline smoke completed with zero samples under row caps")
    else:
        if summary["status"] not in {"completed", "complete", "ok", "success", "incomplete_no_calibration_samples"} and not summary.get("valid", False):
            # 接受只写入 output_dir 的已完成实验结果。
            if not (output_dir / "03_calibration_samples" / "smart_meter_calibration_samples.csv").exists():
                raise AssertionError("Expected non-zero samples to be written under smoke output directory.")
        print("energy calibration pipeline smoke completed with non-zero samples under row caps")
    print(
        {
            "status": summary.get("status"),
            "valid": summary.get("valid"),
            "match_count": summary["time_matching"]["match_count"],
            "sample_count": sample_count,
            "covered_realtime_trainid_count": summary["calibration_samples"].get("covered_realtime_trainid_count"),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
