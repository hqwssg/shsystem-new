"""把现有调度/运行图归因结果导出为中文前端展示JSON，不更改算法工件。"""

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from result_explanation import build_result_explanation


def _csv(result_dir: Path, name: str) -> list[dict]:
    path = result_dir / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def export_explanation(result_dir: Path, output: Path, run_id: str, run_status: str,
                       data_evidence: dict | None = None) -> dict:
    result_dir = Path(result_dir)
    paths = [result_dir / name for name in ("optimizer_summary.json", "summary.json")]
    summary_path = next((path for path in paths if path.is_file()), None)
    if summary_path is None:
        raise FileNotFoundError("目录没有运行图优化或重空调度摘要。")
    attribution_path = result_dir / "optimization_attribution_summary.json"
    attribution = json.loads(attribution_path.read_text(encoding="utf-8")) if attribution_path.is_file() else {}
    payload = build_result_explanation(
        run_id=run_id, run_status=run_status, summary=json.loads(summary_path.read_text(encoding="utf-8")),
        attribution=attribution, data_evidence=data_evidence,
        candidate_rows=_csv(result_dir, "optimization_candidate_decisions.csv"),
        metric_rows=_csv(result_dir, "optimization_kpi_attribution.csv"),
        dimension_rows=_csv(result_dir, "optimization_dimension_attribution.csv"))
    # 只允许新增展示工件，避免用户误指定输出覆盖原始评分文件。
    if output.name != "result_explanation.json":
        raise ValueError("输出文件名必须为result_explanation.json。")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-status", choices=("unknown", "pending", "running", "succeeded", "failed", "cancelled"), default="unknown")
    parser.add_argument("--data-evidence", type=Path)
    args = parser.parse_args()
    evidence = json.loads(args.data_evidence.read_text(encoding="utf-8")) if args.data_evidence else None
    payload = export_explanation(args.result_dir, args.output, args.run_id, args.run_status, evidence)
    print(json.dumps({"output": str(args.output), "decision": payload["decision"], "data_confidence": payload["data_confidence"]["label"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
