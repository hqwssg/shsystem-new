# 模块功能说明：验证完整校准流水线只有通过质量门禁后才能生成并发布系数。

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import run_energy_calibration_pipeline as pipeline
from _calibration_success_fixture import write_nonzero_alignment_fixture


def main() -> int:
    """使用确定性桩隔离原始电表解析，覆盖质量通过后的发布路径。"""
    originals = {
        name: getattr(pipeline, name)
        for name in (
            "match_smart_meter_time_windows",
            "write_match_outputs",
            "analyze_matches",
            "build_calibration_samples",
            "build_alignment",
        )
    }

    def fake_match(*args, **kwargs):
        return []

    def fake_write_matches(rows, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "smart_meter_time_window_matching_summary.json").write_text(
            json.dumps({"match_count": 120}), encoding="utf-8"
        )

    def fake_analyze(input_csv, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "smart_meter_calibration_candidates.csv").write_text("sample_id\n", encoding="utf-8")
        return {"candidate_count": 120, "mismatch_count": 0}

    def fake_samples(input_csv, output_csv, **kwargs):
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        output_csv.write_text("sample_id\n", encoding="utf-8")
        summary = {"sample_count": 120, "selection_policy": "test_fixture", "covered_realtime_trainid_count": 4}
        output_csv.with_name(output_csv.stem + "_summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return summary

    def fake_alignment(input_csv, station_csv, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        output_csv = output_dir / "arc_energy_vs_meter_samples.csv"
        write_nonzero_alignment_fixture(output_csv)
        return {
            "sample_count": 120,
            "alignment_status_counts": {"aligned": 120},
            "output_csv": str(output_csv),
            "energy_calibration_mode": kwargs.get("energy_calibration_mode", "none"),
        }

    pipeline.match_smart_meter_time_windows = fake_match
    pipeline.write_match_outputs = fake_write_matches
    pipeline.analyze_matches = fake_analyze
    pipeline.build_calibration_samples = fake_samples
    pipeline.build_alignment = fake_alignment
    try:
        with TemporaryDirectory(prefix="calibration_quality_pipeline_") as temp_name:
            root = Path(temp_name)
            smart_meter_dir = root / "meter"
            data_dir = root / "data"
            output_dir = root / "output"
            smart_meter_dir.mkdir()
            data_dir.mkdir()
            (smart_meter_dir / "meter.csv").write_text("fixture", encoding="utf-8")
            (data_dir / "stations.csv").write_text("station_id,position_km\nA,0\nB,15\n", encoding="utf-8")
            summary = pipeline.run_pipeline(
                smart_meter_dir=smart_meter_dir,
                data_dir=data_dir,
                output_dir=output_dir,
                boundary_tolerance_s=300.0,
                energy_tolerance=1.0,
                max_interval_rows_per_file=None,
                max_realtime_rows_per_file=None,
                overlap_policy="exclude",
                representative_samples=True,
                max_per_realtime_trainid=50,
                publish_calibration=True,
            )
            assert summary["pipeline_completed"] is True
            assert summary["valid"] is True
            assert summary["publication_ready"] is True
            assert summary["publication_status"] == "published"
            assert summary["quality_audit"]["validation_sample_count"] >= 10
            assert (output_dir / "calibration_input_manifest.json").is_file()
            assert (output_dir / "06_quality_audit" / "CALIBRATION_QUALITY_REPORT.md").is_file()
            factor_path = data_dir / "energy_calibration_factors.json"
            assert factor_path.is_file()
            factor = json.loads(factor_path.read_text(encoding="utf-8"))
            assert factor["data_status"] == "validated_kwh_calibration"
            assert factor["quality_evidence"]["publication_ready"] is True

            external_alignment = root / "external_alignment.csv"
            write_nonzero_alignment_fixture(external_alignment)
            rows = (
                external_alignment.read_text(encoding="utf-8-sig")
                .replace("down-", "external-down-")
                .replace("up-", "external-up-")
            )
            external_alignment.write_text(rows, encoding="utf-8-sig")
            external_output = root / "external_output"
            external_summary = pipeline.run_pipeline(
                smart_meter_dir=smart_meter_dir,
                data_dir=data_dir,
                output_dir=external_output,
                boundary_tolerance_s=300.0,
                energy_tolerance=1.0,
                max_interval_rows_per_file=None,
                max_realtime_rows_per_file=None,
                overlap_policy="exclude",
                representative_samples=True,
                max_per_realtime_trainid=50,
                validation_alignment_csv=external_alignment,
            )
            assert external_summary["valid"] is True
            assert external_summary["quality_audit"]["validation_strategy"] == "external_validation_file"
            manifest = json.loads((external_output / "calibration_input_manifest.json").read_text(encoding="utf-8"))
            assert any(item["role"] == "external_validation_alignment" for item in manifest["files"])
    finally:
        for name, value in originals.items():
            setattr(pipeline, name, value)
    print("energy calibration quality pipeline smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
