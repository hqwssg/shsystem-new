# 模块功能说明：验证校准质量门禁使用独立留出集，并能阻断样本不足或系数异常的结果。

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import shutil
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from energy_calibration_quality import audit_calibration_quality, deterministic_holdout, write_quality_outputs
from _calibration_success_fixture import write_nonzero_alignment_fixture


def main() -> int:
    """覆盖通过、样本不足和异常系数三类质量结论。"""
    with TemporaryDirectory(prefix="calibration_quality_") as temp_name:
        root = Path(temp_name)
        fixture = write_nonzero_alignment_fixture(root / "aligned.csv")
        passed = audit_calibration_quality(fixture)
        assert passed["accepted"], passed
        assert passed["selected_validation_mode"] == "grouped"
        assert passed["fit_sample_count"] >= 30
        assert passed["validation_sample_count"] >= 10
        assert passed["validation_metrics"]["selected"]["median_ape_pct"] < passed["validation_metrics"]["uncalibrated"]["median_ape_pct"]
        write_quality_outputs(passed, root / "quality")
        assert (root / "quality" / "calibration_quality_summary.json").is_file()
        assert (root / "quality" / "calibration_quality_checks.csv").is_file()
        assert (root / "quality" / "CALIBRATION_QUALITY_REPORT.md").is_file()

        fit1, validation1 = deterministic_holdout(list(csv.DictReader(fixture.open("r", encoding="utf-8-sig"))))
        fit2, validation2 = deterministic_holdout(list(reversed(fit1 + validation1)))
        assert {row["sample_id"] for row in fit1} == {row["sample_id"] for row in fit2}
        assert {row["sample_id"] for row in validation1} == {row["sample_id"] for row in validation2}

        insufficient = audit_calibration_quality(fixture, min_fit_samples=1000)
        assert not insufficient["accepted"]
        assert "minimum_fit_samples" in insufficient["failed_checks"]

        implausible = audit_calibration_quality(fixture, min_scale=2.0, max_scale=3.0)
        assert not implausible["accepted"]
        assert "plausible_global_scale" in implausible["failed_checks"]

        external_fixture = root / "external_aligned.csv"
        with fixture.open("r", encoding="utf-8-sig", newline="") as source:
            external_rows = list(csv.DictReader(source))
            fieldnames = list(external_rows[0])
        for index, row in enumerate(external_rows):
            row["sample_id"] = f"external-{index}"
        with external_fixture.open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(external_rows)
        external = audit_calibration_quality(fixture, validation_alignment_csv=external_fixture)
        assert external["accepted"], external
        assert external["validation_strategy"] == "external_validation_file"
        assert external["fit_sample_count"] == external["fit_core_rows"]

        duplicate_fixture = root / "duplicate_aligned.csv"
        shutil.copy2(fixture, duplicate_fixture)
        duplicate = audit_calibration_quality(fixture, validation_alignment_csv=duplicate_fixture)
        assert not duplicate["accepted"]
        assert "independent_validation_no_overlap" in duplicate["failed_checks"]

        global_model = audit_calibration_quality(fixture, validation_model="global")
        assert global_model["selected_validation_mode"] == "global"

    print("energy calibration quality smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
