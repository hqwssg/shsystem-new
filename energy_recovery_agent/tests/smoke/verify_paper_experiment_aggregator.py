"""验证异构论文实验自动汇总、质量门禁和路径边界。"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.paper_experiment_aggregator import aggregate_paper_experiments


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    outputs_root = ROOT / "outputs"
    outputs_root.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="paper_aggregate_smoke_", dir=outputs_root) as temp_name:
        temp = Path(temp_name)
        source = temp / "source"
        source.mkdir()
        (source / "complete.json").write_text(
            json.dumps({"passed": True, "metric": {"count": 7}}), encoding="utf-8"
        )
        (source / "blocked.json").write_text(
            json.dumps({"completed": True, "publication_ready": False}), encoding="utf-8"
        )
        manifest = {
            "study_title": "汇总测试",
            "data_boundary": "仅用于测试。",
            "entries": [
                {
                    "experiment_id": "T01", "title": "完成项", "category": "正确性",
                    "source_summary": str((source / "complete.json").relative_to(ROOT)).replace("\\", "/"),
                    "completion_field": "passed", "completion_values": [True],
                    "metrics": {"案例数": "metric.count"},
                },
                {
                    "experiment_id": "T02", "title": "门禁项", "category": "校准",
                    "source_summary": str((source / "blocked.json").relative_to(ROOT)).replace("\\", "/"),
                    "completion_field": "completed", "completion_values": [True],
                    "quality_gate_field": "publication_ready", "quality_gate_values": [True],
                },
            ],
            "formal_evidence_requirements": [
                {"requirement_id": "F00", "title": "正式数据", "status": "waiting"}
            ],
        }
        manifest_path = temp / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        output = temp / "result"
        report = temp / "report.md"
        summary = aggregate_paper_experiments(manifest_path, output, report)
        assert summary["aggregation_completed"] is True
        assert summary["completed_count"] == 1
        assert summary["quality_blocked_count"] == 1
        assert summary["failed_count"] == 0 and summary["missing_count"] == 0
        assert summary["formal_claim_ready"] is False
        evidence = _read_csv(output / "paper_experiment_evidence_matrix.csv")
        assert [row["result_state"] for row in evidence] == ["completed", "quality_blocked"]
        metrics = _read_csv(output / "paper_experiment_metrics.csv")
        assert metrics[0]["metric_value"] == "7"
        assert (output / "figures" / "paper_experiment_status.png").stat().st_size > 1000
        assert "质量门禁未通过" in report.read_text(encoding="utf-8")

        bad_manifest = dict(manifest)
        bad_manifest["entries"] = [dict(manifest["entries"][0], source_summary="../outside.json")]
        bad_path = temp / "bad_manifest.json"
        bad_path.write_text(json.dumps(bad_manifest, ensure_ascii=False), encoding="utf-8")
        try:
            aggregate_paper_experiments(bad_path, temp / "bad_output", temp / "bad.md")
        except ValueError as exc:
            assert "越出项目目录" in str(exc)
        else:
            raise AssertionError("汇总器必须拒绝项目目录外证据路径。")

    print("paper experiment aggregator smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
