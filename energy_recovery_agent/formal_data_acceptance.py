# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

"""Formal-data acceptance gate.

This module deliberately composes the existing quality and ingestion checks
instead of reimplementing their field rules.  It adds the release decision:
all required runtime files must exist and both validators must be error-free
when official provenance is required.
"""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import csv
import json

from data_quality_validator import validate_all
from real_data_ingestion_checker import run_checks


REQUIRED_RUNTIME_FILES = (
    "route_metadata.json",
    "stations.csv",
    "gradients.csv",
    "curves.csv",
    "trains.csv",
    "battery.json",
    "resource_config.json",
    "power_arm_intervals.csv",
    "train_formation_modes_2025.csv",
)


@dataclass(frozen=True)
class AcceptanceIssue:
    """类 AcceptanceIssue：执行该模块中的相关处理逻辑。"""
    severity: str
    source: str
    code: str
    message: str
    suggestion: str = ""


def _required_file_issues(data_dir: Path) -> List[AcceptanceIssue]:
    """函数 _required_file_issues：执行该模块中的相关处理逻辑。"""
    issues: List[AcceptanceIssue] = []
    for name in REQUIRED_RUNTIME_FILES:
        path = data_dir / name
        if not path.is_file():
            issues.append(AcceptanceIssue("error", str(path), "missing_runtime_file", "正式运行所需文件不存在。", "补齐文件后重新验收。"))
        elif path.stat().st_size == 0:
            issues.append(AcceptanceIssue("error", str(path), "empty_runtime_file", "正式运行所需文件为空。", "提供包含表头和记录的正式文件。"))
    return issues


def run_acceptance(
    data_dir: Path,
    source_dir: Path,
    timetable: Path,
) -> Dict[str, Any]:
    """函数 run_acceptance：执行该模块中的相关处理逻辑。"""
    data_dir = Path(data_dir)
    source_dir = Path(source_dir)
    timetable = Path(timetable)
    issues = _required_file_issues(data_dir)

    quality = validate_all(data_dir, source_dir, timetable, require_official_data=True)
    issues.extend(
        AcceptanceIssue(item.severity, item.source, item.code, item.message, item.suggestion)
        for item in quality.issues
    )

    ingestion = run_checks(data_dir, "all", timetable)
    issues.extend(
        AcceptanceIssue(item.severity, f"{item.file}:{item.table}" if item.table else item.file, item.issue_code, item.message, item.suggestion)
        for item in ingestion.issues
    )

    error_count = sum(item.severity == "error" for item in issues)
    warning_count = sum(item.severity == "warning" for item in issues)
    return {
        "accepted": error_count == 0,
        "data_dir": str(data_dir),
        "source_dir": str(source_dir),
        "timetable": str(timetable),
        "required_runtime_files": list(REQUIRED_RUNTIME_FILES),
        "error_count": error_count,
        "warning_count": warning_count,
        "quality_validation": quality.summary(),
        "ingestion_validation": ingestion.summary(),
        "issues": [asdict(item) for item in issues],
    }


def write_report(summary: Dict[str, Any], output_dir: Path) -> None:
    """函数 write_report：执行该模块中的相关处理逻辑。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "formal_data_acceptance_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "formal_data_acceptance_issues.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("severity", "source", "code", "message", "suggestion"))
        writer.writeheader()
        writer.writerows(summary["issues"])
    lines = [
        "# 正式数据自动验收报告",
        "",
        "本报告只做读取和检查，不修改数据目录。只有 `accepted=true` 才允许把该目录作为正式数据发布。",
        "",
        f"- 验收结论：`{summary['accepted']}`",
        f"- 错误：`{summary['error_count']}`",
        f"- 警告：`{summary['warning_count']}`",
        "",
        "## 问题明细",
        "",
        "| 级别 | 来源 | 代码 | 说明 | 建议 |",
        "| --- | --- | --- | --- | --- |",
    ]
    rows = summary["issues"] or [{"severity": "info", "source": "-", "code": "no_issue", "message": "未发现阻断问题。", "suggestion": "-"}]
    lines.extend(
        "| {severity} | `{source}` | `{code}` | {message} | {suggestion} |".format(**row).replace("|", "/")
        for row in rows[:500]
    )
    (output_dir / "FORMAL_DATA_ACCEPTANCE_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    import argparse

    parser = argparse.ArgumentParser(description="验收正式数据目录，阻止虚拟/未确认数据进入正式运行。")
    parser.add_argument("--data-dir", type=Path, default=Path("data") / "real_shuohuang")
    parser.add_argument("--source-dir", type=Path, default=Path("data") / "source")
    parser.add_argument("--timetable", type=Path, default=Path("data_templates") / "running_diagram_template.xlsx")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs") / "formal_data_acceptance")
    args = parser.parse_args(argv)
    summary = run_acceptance(args.data_dir, args.source_dir, args.timetable)
    write_report(summary, args.output_dir)
    printable = {k: summary[k] for k in ("accepted", "error_count", "warning_count", "data_dir")}
    printable["output_dir"] = str(args.output_dir)
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
