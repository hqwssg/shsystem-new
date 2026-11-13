"""从既有优化输出目录补生成收益归因与瓶颈解释报告。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import csv
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optimization_attribution import write_optimization_attribution


ATTRIBUTION_FILES = {
    "OPTIMIZATION_ATTRIBUTION_REPORT.md",
    "optimization_attribution_summary.json",
    "optimization_kpi_attribution.csv",
    "optimization_candidate_decisions.csv",
    "optimization_candidate_funnel.csv",
    "optimization_bottlenecks.csv",
    "optimization_dimension_attribution.csv",
}


def _csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"摘要文件必须是JSON对象：{path}")
    return value


def detect_workflow(output_dir: Path) -> str:
    if (output_dir / "optimizer_summary.json").is_file():
        return "timetable_optimization"
    if (output_dir / "summary.json").is_file() and (output_dir / "ranked_candidates.csv").is_file():
        return "dispatch"
    raise ValueError("无法从目录识别运行图优化或重空调度输出。")


def generate(
    output_dir: Path,
    workflow: str = "auto",
    *,
    force: bool = False,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    resolved = detect_workflow(output_dir) if workflow == "auto" else workflow
    existing_summary = output_dir / "optimization_attribution_summary.json"
    if not force and all((output_dir / name).is_file() for name in ATTRIBUTION_FILES):
        existing = _json(existing_summary)
        if existing.get("workflow") == resolved:
            return existing
    if resolved == "timetable_optimization":
        summary = _json(output_dir / "optimizer_summary.json")
        return write_optimization_attribution(
            output_dir,
            workflow=resolved,
            summary=summary,
            candidate_rows=_csv_rows(output_dir / "candidate_summary.csv"),
            pareto_rows=_csv_rows(output_dir / "pareto_candidates.csv"),
            scenario_rows=_csv_rows(output_dir / "candidate_scenario_scores.csv"),
            issue_rows=_csv_rows(output_dir / "candidate_energy_issues.csv"),
        )
    if resolved == "dispatch":
        summary = _json(output_dir / "summary.json")
        return write_optimization_attribution(
            output_dir,
            workflow=resolved,
            summary=summary,
            candidate_rows=_csv_rows(output_dir / "ranked_candidates.csv"),
            pareto_rows=_csv_rows(output_dir / "pareto_candidates.csv"),
            scenario_rows=_csv_rows(output_dir / "selected_plan_scenario_diagnostics.csv"),
            timeline_rows=_csv_rows(output_dir / "energy_timeline.csv"),
            baseline_schedule_rows=_csv_rows(output_dir / "baseline_schedule.csv"),
            optimized_schedule_rows=_csv_rows(output_dir / "optimized_schedule.csv"),
        )
    raise ValueError(f"不支持的工作流：{resolved}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--workflow",
        choices=("auto", "timetable_optimization", "dispatch"),
        default="auto",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="即使完整归因工件已经存在，也从可用历史文件重新生成。",
    )
    args = parser.parse_args()
    result = generate(args.output_dir, args.workflow, force=args.force)
    print(json.dumps({
        "workflow": result["workflow"],
        "decision": result["decision"],
        "counts": result["counts"],
        "report": str(args.output_dir / "OPTIMIZATION_ATTRIBUTION_REPORT.md"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
