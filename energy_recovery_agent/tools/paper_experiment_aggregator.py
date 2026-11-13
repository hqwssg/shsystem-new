"""汇总异构论文实验结果，生成当前证据总览、指标表和缺口表。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib
from matplotlib import font_manager

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "paper" / "实验设计" / "论文实验自动汇总清单.json"
DEFAULT_OUTPUT = ROOT / "paper" / "experiments" / "论文实验自动汇总"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON根节点必须是对象：{path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_project_path(value: str) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"论文实验证据路径越出项目目录：{value}") from exc
    return resolved


def _field(value: Any, dotted_path: str) -> Any:
    """读取对象或数组中的点分路径，数组段使用十进制下标。"""

    current = value
    for part in dotted_path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _configure_fonts() -> None:
    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC"):
        if name in available:
            matplotlib.rcParams["font.sans-serif"] = [name]
            matplotlib.rcParams["axes.unicode_minus"] = False
            return


def _plot_category_status(rows: Sequence[Mapping[str, Any]], output: Path) -> dict[str, Any]:
    _configure_fonts()
    categories = sorted({str(row["category"]) for row in rows})
    states = ("completed", "quality_blocked", "failed", "missing")
    state_labels = ("完成", "质量门禁未通过", "失败", "缺失")
    colors = ("#287271", "#E9C46A", "#E76F51", "#8D99AE")
    figure, axis = plt.subplots(figsize=(10, max(4.5, len(categories) * 0.62)))
    left = [0] * len(categories)
    for state, label, color in zip(states, state_labels, colors):
        values = [sum(row["result_state"] == state for row in rows if row["category"] == category) for category in categories]
        axis.barh(categories, values, left=left, label=label, color=color)
        left = [a + b for a, b in zip(left, values)]
    axis.set_xlabel("实验数量")
    axis.set_title("论文实验当前证据状态")
    axis.legend(loc="lower right")
    axis.grid(axis="x", alpha=0.2)
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return {"accepted": output.is_file() and output.stat().st_size > 1000, "path": output.as_posix()}


def _inventory(
    experiments_root: Path, registered_roots: set[str], ignored_directories: set[Path]
) -> list[dict[str, Any]]:
    rows = []
    if not experiments_root.is_dir():
        return rows
    for directory in sorted((item for item in experiments_root.iterdir() if item.is_dir()), key=lambda item: item.name.lower()):
        if directory.resolve() in ignored_directories:
            continue
        files = [item for item in directory.rglob("*") if item.is_file()]
        latest = max((item.stat().st_mtime for item in files), default=directory.stat().st_mtime)
        rows.append({
            "directory": directory.name,
            "registered_current_evidence": directory.name in registered_roots,
            "classification": "current_evidence" if directory.name in registered_roots else "historical_or_supporting",
            "file_count": len(files),
            "summary_json_count": sum("summary" in item.name.lower() and item.suffix.lower() == ".json" for item in files),
            "latest_modified": datetime.fromtimestamp(latest, timezone.utc).isoformat(),
        })
    return rows


def aggregate_paper_experiments(
    manifest_path: Path = DEFAULT_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """按显式清单汇总当前证据，并将未登记目录隔离为历史库存。"""

    manifest_path = Path(manifest_path)
    output_dir = Path(output_dir)
    report_path = Path(report_path) if report_path else ROOT / "paper" / "experiments" / "实验结果汇总.md"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"论文实验汇总清单不存在：{manifest_path}")
    manifest = _read_json(manifest_path)
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("论文实验汇总清单entries必须是非空数组。")
    identifiers: set[str] = set()
    evidence_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    registered_roots: set[str] = set()
    for entry in entries:
        experiment_id = str(entry.get("experiment_id", "")).strip()
        if not experiment_id or experiment_id in identifiers:
            raise ValueError(f"实验编号为空或重复：{experiment_id or '<空>'}")
        identifiers.add(experiment_id)
        source_relative = str(entry.get("source_summary", "")).replace("\\", "/")
        source = _resolve_project_path(source_relative)
        parts = Path(source_relative).parts
        if len(parts) >= 3 and parts[0] == "paper" and parts[1] == "experiments":
            registered_roots.add(parts[2])
        row = {
            "experiment_id": experiment_id,
            "title": str(entry.get("title", "")),
            "category": str(entry.get("category", "未分类")),
            "result_state": "missing",
            "data_basis": str(entry.get("data_basis", "")),
            "evidence_role": str(entry.get("evidence_role", "")),
            "claim_boundary": str(entry.get("claim_boundary", "")),
            "source_summary": source_relative,
            "source_sha256": "",
            "source_modified": "",
            "status_detail": "源文件缺失",
        }
        if source.is_file():
            payload = _read_json(source)
            completion_field = str(entry.get("completion_field", "")).strip()
            completion_value = True if not completion_field else _field(payload, completion_field)
            completion_values = entry.get("completion_values", [True])
            completed = completion_value in completion_values
            quality_field = str(entry.get("quality_gate_field", "")).strip()
            quality_value = _field(payload, quality_field) if quality_field else True
            quality_values = entry.get("quality_gate_values", [True])
            quality_passed = quality_value in quality_values
            row.update({
                "result_state": "completed" if completed and quality_passed else "quality_blocked" if completed else "failed",
                "source_sha256": _sha256(source),
                "source_modified": datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(),
                "status_detail": (
                    "实验完成且质量门禁通过" if completed and quality_passed
                    else f"实验完成但质量门禁未通过：{quality_field}={_display(quality_value)}" if completed
                    else f"完成条件未满足：{completion_field}={_display(completion_value)}"
                ),
            })
            for metric_name, metric_path in dict(entry.get("metrics") or {}).items():
                metric_rows.append({
                    "experiment_id": experiment_id,
                    "title": row["title"],
                    "category": row["category"],
                    "metric_name": metric_name,
                    "metric_path": metric_path,
                    "metric_value": _display(_field(payload, str(metric_path))),
                    "source_summary": source_relative,
                })
        evidence_rows.append(row)

    experiments_root = ROOT / "paper" / "experiments"
    inventory_rows = _inventory(experiments_root, registered_roots, {output_dir.resolve()})
    requirement_rows = [dict(item) for item in manifest.get("formal_evidence_requirements", [])]
    output_dir.mkdir(parents=True, exist_ok=True)
    figure = _plot_category_status(evidence_rows, output_dir / "figures" / "paper_experiment_status.png")
    counts = Counter(row["result_state"] for row in evidence_rows)
    summary = {
        "schema_version": "1.0",
        "generated_at": datetime.now().astimezone().isoformat(),
        "study_title": manifest.get("study_title", ""),
        "aggregation_completed": True,
        "manifest": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "registered_experiment_count": len(evidence_rows),
        "state_counts": dict(counts),
        "completed_count": counts["completed"],
        "quality_blocked_count": counts["quality_blocked"],
        "failed_count": counts["failed"],
        "missing_count": counts["missing"],
        "formal_claim_ready": bool(requirement_rows) and all(
            str(row.get("status", "")) == "ready" for row in requirement_rows
        ),
        "formal_requirement_count": len(requirement_rows),
        "historical_or_supporting_directory_count": sum(row["classification"] != "current_evidence" for row in inventory_rows),
        "visualization": figure,
        "data_boundary": manifest.get("data_boundary", ""),
        "outputs": {
            "report": str(report_path),
            "evidence_matrix": str(output_dir / "paper_experiment_evidence_matrix.csv"),
            "metrics": str(output_dir / "paper_experiment_metrics.csv"),
            "formal_gaps": str(output_dir / "paper_formal_evidence_gaps.csv"),
            "directory_inventory": str(output_dir / "paper_experiment_directory_inventory.csv"),
            "summary": str(output_dir / "paper_experiment_aggregate_summary.json"),
        },
    }
    _write_csv(output_dir / "paper_experiment_evidence_matrix.csv", evidence_rows, list(evidence_rows[0]))
    _write_csv(output_dir / "paper_experiment_metrics.csv", metric_rows, list(metric_rows[0]))
    _write_csv(output_dir / "paper_formal_evidence_gaps.csv", requirement_rows, ["requirement_id", "title", "status"])
    _write_csv(
        output_dir / "paper_experiment_directory_inventory.csv",
        inventory_rows,
        [
            "directory",
            "registered_current_evidence",
            "classification",
            "file_count",
            "summary_json_count",
            "latest_modified",
        ],
    )
    (output_dir / "paper_experiment_aggregate_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 当前论文实验自动汇总", "",
        f"自动生成时间：{summary['generated_at']}", "",
        "## 一、结论先行", "",
        f"当前登记核心证据 {len(evidence_rows)} 项：完成且门禁通过 {counts['completed']} 项，质量门禁未通过 {counts['quality_blocked']} 项，执行失败 {counts['failed']} 项，缺失 {counts['missing']} 项。",
        "", str(manifest.get("data_boundary", "")), "",
        "当前 `formal_claim_ready=false`。这不表示算法链路未完成，而是正式数据、多评价窗成对实验和校准发布门禁尚未满足。", "",
        "![论文实验状态](论文实验自动汇总/figures/paper_experiment_status.png)", "",
        "## 二、当前核心证据", "",
        "| 编号 | 实验 | 分类 | 状态 | 主要用途 | 结论边界 |", "| --- | --- | --- | --- | --- | --- |",
    ]
    labels = {"completed": "完成", "quality_blocked": "质量门禁未通过", "failed": "失败", "missing": "缺失"}
    for row in evidence_rows:
        cells = [row["experiment_id"], row["title"], row["category"], labels[row["result_state"]], row["evidence_role"], row["claim_boundary"]]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|").replace("\n", " ") for value in cells) + " |")
    lines.extend(["", "## 三、关键指标", "", "| 实验 | 指标 | 结果 |", "| --- | --- | --- |"])
    for row in metric_rows:
        lines.append(f"| {row['experiment_id']} {row['title']} | {row['metric_name']} | {row['metric_value'] or '未记录'} |")
    lines.extend(["", "## 四、正式论文证据缺口", "", "| 编号 | 缺口 | 当前状态 |", "| --- | --- | --- |"])
    for row in requirement_rows:
        lines.append(f"| {row['requirement_id']} | {row['title']} | {row['status']} |")
    lines.extend([
        "", "## 五、如何复现", "",
        "```powershell", "python run_project.py aggregate-paper-experiments", "```", "",
        "机器可读明细位于 `paper/experiments/论文实验自动汇总/`。未登记目录只列入目录库存，不进入当前结论；需要提升为当前证据时必须先修改汇总清单并说明取代关系。", "",
    ])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-path", type=Path, default=ROOT / "paper" / "experiments" / "实验结果汇总.md")
    args = parser.parse_args(argv)
    result = aggregate_paper_experiments(args.manifest, args.output_dir, args.report_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["failed_count"] == 0 and result["missing_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
