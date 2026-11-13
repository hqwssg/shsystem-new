"""Smoke checks for the non-destructive project hygiene inventory."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.project_hygiene import (
    build_entries,
    compare_dataset_snapshots,
    generate_report,
    scan_references,
)


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    with tempfile.TemporaryDirectory(prefix="project_hygiene_smoke_") as temp:
        root = Path(temp)
        (root / "outputs" / "_probe").mkdir(parents=True)
        (root / "outputs" / "archive").mkdir(parents=True)
        (root / "outputs" / "README.md").write_text("current outputs\n", encoding="utf-8")
        (root / "outputs" / "performance_analysis").mkdir()
        (root / "outputs" / "performance_analysis" / "PERFORMANCE_REPORT.md").write_text("profile\n", encoding="utf-8")
        (root / "outputs" / "_probe" / "result.out").write_text("probe\n", encoding="utf-8")
        (root / "data" / "real_shuohuang").mkdir(parents=True)
        (root / "data" / "real_shuohuang" / "trains.csv").write_text("id\n", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "note.md").write_text("see outputs/_probe/result.out\n", encoding="utf-8")
        (root / "tools").mkdir()
        (root / "tools" / "__init__.py").write_text("# package\n", encoding="utf-8")
        (root / "tools" / "_probe.py").write_text("# temporary probe\n", encoding="utf-8")

        report_dir = root / "outputs" / "project_hygiene_report"
        report_path, manifest_path = generate_report(root, report_dir, with_hashes=True)
        if not report_path.is_file() or not manifest_path.is_file():
            raise AssertionError("hygiene report files were not created")
        plan_path = report_dir / "ARCHIVE_PLAN.md"
        plan_json_path = report_dir / "archive_plan.json"
        if not plan_path.is_file() or not plan_json_path.is_file():
            raise AssertionError("archive plan files were not created")
        plan_json = plan_json_path.read_text(encoding="utf-8")
        if '"mode": "plan_only"' not in plan_json or '"apply_required": true' not in plan_json:
            raise AssertionError("archive plan must be explicitly non-executing")
        if "data/real_shuohuang" not in plan_json:
            raise AssertionError("archive plan must list protected runtime data")
        comparison = compare_dataset_snapshots(root)
        if comparison["file_count"] != 1 or comparison["summary"]["identical"] != 1:
            raise AssertionError(f"unexpected dataset comparison: {comparison}")
        dataset_report = report_dir / "DATASET_COMPARISON.md"
        dataset_json = report_dir / "dataset_comparison.json"
        if not dataset_report.is_file() or not dataset_json.is_file():
            raise AssertionError("dataset comparison files were not created")

        entries = build_entries(root, report_dir, with_hashes=True)
        by_path = {entry.path: entry for entry in entries}
        if by_path["outputs/README.md"].category != "current_deliverable":
            raise AssertionError("outputs/README.md must remain a current deliverable")
        if by_path["outputs/performance_analysis/PERFORMANCE_REPORT.md"].category != "current_deliverable":
            raise AssertionError("performance analysis reports must remain current deliverables")
        if by_path["data/real_shuohuang/trains.csv"].category != "protected_input_or_reference":
            raise AssertionError("runtime data must be protected")
        if by_path["tools/__init__.py"].category != "active_source_or_configuration":
            raise AssertionError("tools/__init__.py must remain active package source")
        if by_path["tools/_probe.py"].category != "archive_candidate_tool_probe":
            raise AssertionError("temporary tools probe should remain an archive candidate")

        references = scan_references(root, entries, report_dir)
        if references.get("outputs/_probe") != ["docs/note.md"]:
            raise AssertionError(f"unexpected candidate references: {references}")
        if any(entry.path.startswith("outputs/project_hygiene_report/") for entry in entries):
            raise AssertionError("generated report directory must be excluded from the scan")

        fast_report_dir = root / "outputs" / "project_hygiene_fast_report"
        fast_report_path, fast_manifest_path = generate_report(root, fast_report_dir, with_hashes=False)
        if "未执行 SHA-256 重复检查" not in fast_report_path.read_text(encoding="utf-8"):
            raise AssertionError("no-hashes report must disclose that duplicate checking was skipped")
        if '"hash_algorithm": null' not in fast_manifest_path.read_text(encoding="utf-8"):
            raise AssertionError("no-hashes manifest must record a null hash algorithm")
        fast_plan_json = (fast_report_dir / "dataset_comparison.json").read_text(encoding="utf-8")
        if '"hash_check_skipped": true' not in fast_plan_json:
            raise AssertionError("no-hashes dataset comparison must be skipped")
        if "未执行数据集快照 SHA-256 对比" not in (fast_report_dir / "DATASET_COMPARISON.md").read_text(encoding="utf-8"):
            raise AssertionError("no-hashes dataset report must disclose skipped comparison")

    print("project hygiene smoke: PASS")


if __name__ == "__main__":
    main()
