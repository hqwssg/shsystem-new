"""Generate a non-destructive project hygiene report.

The report separates runtime inputs/source, current deliverables, historical
outputs and caches.  It never deletes or moves files; the resulting manifest is
intended to be reviewed before any archive operation is approved.

Usage (from the project root)::

    python tools/project_hygiene.py report
    python tools/project_hygiene.py report --output-dir outputs/project_hygiene_report

The default output directory is ``outputs/project_hygiene_report``.  That
directory is excluded from the scan so rerunning the command is stable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


CURRENT_OUTPUTS = {
    "README.md",
    "SIMULATION_TEST_REPORT.md",
    "simulation_workflow_summary.json",
    "data_quality_validation",
    "data_quality_validation_final",
    "data_quality_validation_final2",
    "dispatch_storage_no_direct_phase2600",
    "energy_calibration_alignment",
    "project_hygiene_report",
    "real_data_ingestion_check",
    "run_manifests",
    "simulation_experiment_suite",
    "performance_analysis",
    "performance_analysis_timetable",
    "performance_analysis_settlement",
    "synthetic_scenario_matrix",
    "synthetic_regression_baseline",
    "performance_capacity",
    "prototype_contract_validation",
    "timetable_energy_audit",
    "timetable_optimizer_nsga2",
}

PROTECTED_TOP_LEVEL = {
    "data",
    "data_templates",
    "docs",
    "prototypes",
    "resources",
    "shuohuang_data",
    "tests",
}


@dataclass(frozen=True)
class Entry:
    """类 Entry：执行该模块中的相关处理逻辑。"""
    path: str
    category: str
    size_bytes: int
    modified_utc: str
    sha256: str | None = None


def _relative(path: Path, root: Path) -> str:
    """函数 _relative：执行该模块中的相关处理逻辑。"""
    return path.relative_to(root).as_posix()


def _utc_timestamp(path: Path) -> str:
    """函数 _utc_timestamp：执行该模块中的相关处理逻辑。"""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """函数 _sha256：执行该模块中的相关处理逻辑。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(root: Path, excluded: set[Path]) -> Iterable[Path]:
    """Yield files while skipping excluded directories and reparse points."""

    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        # 不递归扫描输出报告、虚拟环境或缓存目录。
        dirs[:] = [
            name
            for name in dirs
            if (current_path / name).resolve() not in excluded
            and name not in {".git", ".venv", "venv", "env", "__pycache__"}
        ]
        for name in files:
            path = current_path / name
            try:
                if path.is_file() and path.resolve() not in excluded:
                    yield path
            except OSError:
                # 报告运行期间文件可能消失，不能因此导致整个清单失败。
                continue


def _category(path: Path, root: Path) -> str:
    """函数 _category：执行该模块中的相关处理逻辑。"""
    rel = _relative(path, root)
    parts = rel.split("/")
    name = path.name

    if parts[0] == "outputs":
        if len(parts) > 1 and parts[1] == "archive":
            return "archived_history"
        if len(parts) == 2 and name in CURRENT_OUTPUTS:
            return "current_deliverable"
        if len(parts) > 1 and parts[1] in CURRENT_OUTPUTS:
            return "current_deliverable"
        if name.startswith("_") or (len(parts) == 2 and name.endswith((".log", ".pid"))):
            return "archive_candidate_probe"
        return "archive_candidate_superseded_output"

    if parts[0] in PROTECTED_TOP_LEVEL:
        return "protected_input_or_reference"

    # ``__init__.py`` 是包入口，不是临时探针。此前的 ``name.startswith("_")`` 规则会将其判为可丢弃文件，
    # 可能把必要的导入文件放入归档计划。
    if (
        parts[0] == "tools"
        and name != "__init__.py"
        and (name.startswith("_") or name.startswith("tmp_"))
    ):
        return "archive_candidate_tool_probe"

    if len(parts) == 1 and (name.startswith("_") or name.endswith(".smashed.bak")):
        return "archive_candidate_recovery_script"

    if name.endswith((".log", ".pid")):
        return "local_runtime_log"

    return "active_source_or_configuration"


def build_entries(root: Path, output_dir: Path, with_hashes: bool) -> list[Entry]:
    """函数 build_entries：执行该模块中的相关处理逻辑。"""
    excluded = {output_dir.resolve()}
    entries: list[Entry] = []
    for path in _iter_files(root, excluded):
        try:
            stat = path.stat()
            digest = _sha256(path) if with_hashes else None
            entries.append(
                Entry(
                    path=_relative(path, root),
                    category=_category(path, root),
                    size_bytes=stat.st_size,
                    modified_utc=_utc_timestamp(path),
                    sha256=digest,
                )
            )
        except (OSError, PermissionError):
            continue
    return sorted(entries, key=lambda item: item.path)


def _format_bytes(value: int) -> str:
    """函数 _format_bytes：执行该模块中的相关处理逻辑。"""
    if value < 1024:
        return f"{value} B"
    if value < 1024**2:
        return f"{value / 1024:.1f} KiB"
    if value < 1024**3:
        return f"{value / 1024**2:.1f} MiB"
    return f"{value / 1024**3:.2f} GiB"


def _duplicate_groups(entries: list[Entry]) -> list[list[str]]:
    """函数 _duplicate_groups：执行该模块中的相关处理逻辑。"""
    by_hash: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        if entry.sha256:
            by_hash[entry.sha256].append(entry.path)
    return sorted(
        [sorted(paths) for paths in by_hash.values() if len(paths) > 1],
        key=lambda paths: (-len(paths), paths[0]),
    )


def _duplicate_category_summary(entries: list[Entry], duplicates: list[list[str]]) -> list[dict[str, object]]:
    """Summarize duplicate groups by category without recommending deletion."""

    by_path = {entry.path: entry for entry in entries}
    counts: dict[tuple[str, ...], int] = defaultdict(int)
    for group in duplicates:
        categories = tuple(sorted({by_path[path].category for path in group if path in by_path}))
        if categories:
            counts[categories] += 1
    return [
        {"categories": list(categories), "group_count": count}
        for categories, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def compare_dataset_snapshots(root: Path, with_hashes: bool = True) -> dict[str, object]:
    """Compare known data snapshots without treating equal files as deletable."""

    data_root = root / "data"
    snapshot_names = [
        "real_shuohuang",
        "real_shuohuang_backup_before_replace_20260725_183858",
        "real_shuohuang_rebuild_compare",
        "real_partial",
    ]
    snapshots: dict[str, dict[str, str]] = {}
    if not with_hashes:
        existing = [name for name in snapshot_names if (data_root / name).is_dir()]
        return {
            "snapshot_names": existing,
            "summary": {"identical": None, "different": None, "missing": None},
            "file_count": None,
            "rows": [],
            "hash_check_skipped": True,
        }
    for name in snapshot_names:
        path = data_root / name
        if not path.is_dir():
            continue
        file_hashes: dict[str, str] = {}
        for file_path in path.rglob("*"):
            if file_path.is_file():
                try:
                    file_hashes[file_path.relative_to(path).as_posix()] = _sha256(file_path)
                except OSError:
                    continue
        snapshots[name] = file_hashes

    relative_files = sorted({file for files in snapshots.values() for file in files})
    rows: list[dict[str, object]] = []
    summary = {"identical": 0, "different": 0, "missing": 0}
    for relative_file in relative_files:
        hashes = {name: snapshots[name].get(relative_file) for name in snapshots}
        present = [value for value in hashes.values() if value is not None]
        if len(present) < len(snapshots):
            status = "missing_in_some_snapshots"
            summary["missing"] += 1
        elif len(set(present)) == 1:
            status = "identical_in_all_snapshots"
            summary["identical"] += 1
        else:
            status = "different_content"
            summary["different"] += 1
        rows.append({"path": relative_file, "status": status, "sha256_by_snapshot": hashes})
    return {
        "snapshot_names": list(snapshots),
        "summary": summary,
        "file_count": len(relative_files),
        "rows": rows,
        "hash_check_skipped": False,
    }


def _render_dataset_comparison(comparison: dict[str, object], generated_at: str) -> str:
    """函数 _render_dataset_comparison：执行该模块中的相关处理逻辑。"""
    summary = comparison["summary"]
    names = comparison["snapshot_names"]
    lines = [
        "# 数据集快照对比（只读）",
        "",
        f"生成时间（UTC）：`{generated_at}`",
        "",
        "本报告只比较 SHA-256，不移动、删除或覆盖任何数据。内容相同不代表可以删除，",
        "因为快照可能承担复现、审计或回滚用途。",
        "",
        "## 快照",
        "",
    ]
    lines.extend(f"- `data/{name}/`" for name in names)
    if comparison.get("hash_check_skipped"):
        lines.extend(
            [
                "",
                "## 汇总",
                "",
                "本次使用了 `--no-hashes`，未执行数据集快照 SHA-256 对比。",
                "如需比较快照，请重新运行 `python tools/project_hygiene.py report`。",
            ]
        )
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "",
            "## 汇总",
            "",
            f"- 相对文件总数：{comparison['file_count']}",
            f"- 所有快照内容一致：{summary['identical']}",
            f"- 文件存在但内容不同：{summary['different']}",
            f"- 仅部分快照存在：{summary['missing']}",
            "",
            "## 需要人工确认的差异",
            "",
        ]
    )
    rows = [row for row in comparison["rows"] if row["status"] != "identical_in_all_snapshots"]
    if not rows:
        lines.append("没有差异或缺失文件。")
    else:
        lines.extend(["| 文件 | 状态 |", "| --- | --- |"])
        for row in rows:
            status = {
                "different_content": "内容不同，不能按重复文件处理",
                "missing_in_some_snapshots": "部分快照缺失，不能按重复文件处理",
            }.get(row["status"], str(row["status"]))
            lines.append(f"| `{row['path']}` | {status} |")
    lines.extend(
        [
            "",
            "完整 SHA-256 映射见同目录 `dataset_comparison.json`。默认运行数据 `data/real_shuohuang/`、",
            "来源数据 `data/source/` 和模板目录不应作为清理目标。",
        ]
    )
    return "\n".join(lines) + "\n"


def _candidate_key(path: str) -> str:
    """Return the smallest stable path token used for reference scanning."""

    parts = path.split("/")
    if parts and parts[0] == "outputs" and len(parts) >= 2:
        return "/".join(parts[:2])
    return path


def _is_text_file(path: Path) -> bool:
    """函数 _is_text_file：执行该模块中的相关处理逻辑。"""
    return path.suffix.lower() in {
        ".py",
        ".md",
        ".txt",
        ".json",
        ".csv",
        ".ps1",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
    }


def _reference_tokens(key: str) -> set[str]:
    """函数 _reference_tokens：执行该模块中的相关处理逻辑。"""
    normalized = key.replace("\\", "/").lower()
    tokens = {normalized}
    if normalized.startswith("outputs/"):
        tokens.add(normalized.replace("/", "\\"))
    if "/" not in normalized:
        tokens.add(normalized)
    return tokens


def scan_references(root: Path, entries: list[Entry], output_dir: Path) -> dict[str, list[str]]:
    """Find active source/document files mentioning archive candidates.

    Archived outputs and the generated report directory are excluded.  The
    scan is intentionally conservative: a mention marks a candidate as
    referenced, but no mention is treated as proof that deletion is safe.
    """

    candidate_keys = sorted(
        {
            _candidate_key(entry.path)
            for entry in entries
            if entry.category.startswith("archive_candidate")
        }
    )
    if not candidate_keys:
        return {}

    token_to_keys: dict[str, list[str]] = defaultdict(list)
    for key in candidate_keys:
        for token in _reference_tokens(key):
            token_to_keys[token].append(key)

    # 活跃源码和文档中的引用才有意义。扫描可能数百 MiB 的原始数据集不会增加有效信息，
    # 还会不必要地拖慢清单生成，因此跳过这些受保护目录。
    excluded = {
        output_dir.resolve(),
        (root / "outputs").resolve(),
        (root / "data").resolve(),
        (root / "shuohuang_data").resolve(),
        (root / "resources").resolve(),
        (root / "prototypes").resolve(),
        (root / "data_templates").resolve(),
    }
    entry_by_path = {entry.path: entry for entry in entries}
    references: dict[str, set[str]] = defaultdict(set)
    for path in _iter_files(root, excluded):
        if not _is_text_file(path):
            continue
        rel = _relative(path, root)
        # 不能仅因候选脚本包含探测期间使用的路径，就让候选引用自身或其他历史探针。
        if entry_by_path.get(rel) and entry_by_path[rel].category.startswith("archive_candidate"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        for token, keys in token_to_keys.items():
            if token in text:
                for key in keys:
                    references[key].add(rel)
    return {key: sorted(paths) for key, paths in sorted(references.items())}


def _candidate_groups(entries: list[Entry], references: dict[str, list[str]]) -> list[dict[str, object]]:
    """Aggregate candidate files by the directory/path that would be moved."""

    grouped: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not entry.category.startswith("archive_candidate") and entry.category != "local_runtime_log":
            continue
        key = _candidate_key(entry.path)
        group = grouped.setdefault(
            key,
            {
                "path": key,
                "categories": set(),
                "file_count": 0,
                "size_bytes": 0,
                "examples": [],
            },
        )
        group["categories"].add(entry.category)
        group["file_count"] += 1
        group["size_bytes"] += entry.size_bytes
        examples = group["examples"]
        if len(examples) < 3:
            examples.append(entry.path)

    result: list[dict[str, object]] = []
    for key, group in grouped.items():
        result.append(
            {
                "path": key,
                "categories": sorted(group["categories"]),
                "file_count": group["file_count"],
                "size_bytes": group["size_bytes"],
                "reference_count": len(references.get(key, [])),
                "examples": sorted(group["examples"]),
            }
        )
    return sorted(result, key=lambda group: (-int(group["size_bytes"]), str(group["path"])))


def _render_markdown(
    entries: list[Entry],
    duplicates: list[list[str]],
    references: dict[str, list[str]],
    generated_at: str,
    with_hashes: bool,
    duplicate_category_summary: list[dict[str, object]],
) -> str:
    """函数 _render_markdown：执行该模块中的相关处理逻辑。"""
    totals: dict[str, tuple[int, int]] = defaultdict(lambda: [0, 0])
    for entry in entries:
        totals[entry.category][0] += 1
        totals[entry.category][1] += entry.size_bytes

    lines = [
        "# 项目文件卫生报告",
        "",
        f"生成时间（UTC）：`{generated_at}`",
        "",
        "本报告只读扫描项目目录，未移动、删除或修改任何原有文件。",
        "归档候选仅表示根据命名和目录规则可考虑移入 `outputs/archive/` 的历史材料，",
        "不代表可以直接删除；归档前应先核对是否仍被脚本或文档引用。",
        "",
        "## 分类汇总",
        "",
        "| 分类 | 文件数 | 大小 | 处理建议 |",
        "| --- | ---: | ---: | --- |",
    ]
    recommendations = {
        "current_deliverable": "保留；作为当前交付/复核结果",
        "protected_input_or_reference": "保留；输入、模板、测试或参考资料",
        "active_source_or_configuration": "保留；活动源码或配置",
        "archived_history": "保留；已归档历史证据",
        "archive_candidate_probe": "建议复核后归档，不直接删除",
        "archive_candidate_superseded_output": "建议复核是否可归档",
        "archive_candidate_tool_probe": "建议复核后移入工具历史归档",
        "archive_candidate_recovery_script": "建议建立脚本历史清单后归档",
        "local_runtime_log": "可按保留期限清理；先确认无审计要求",
    }
    for category in sorted(totals):
        count, size = totals[category]
        lines.append(f"| `{category}` | {count} | {_format_bytes(size)} | {recommendations.get(category, '')} |")

    lines.extend(["", "## 归档候选", ""])
    candidates = _candidate_groups(entries, references)
    if not candidates:
        lines.append("没有发现归档候选。")
    else:
        lines.extend(["按可移动路径汇总（详细逐文件清单见 `manifest.json`）：", "", "| 路径 | 分类 | 文件数 | 大小 | 活动引用 | 示例 |", "| --- | --- | ---: | ---: | ---: | --- |"])
        for group in candidates:
            ref_count = int(group["reference_count"])
            ref_text = f"{ref_count} 个活动文件" if ref_count else "未发现活动引用"
            categories = ", ".join(f"`{category}`" for category in group["categories"])
            examples = ", ".join(f"`{path}`" for path in group["examples"])
            lines.append(
                f"| `{group['path']}` | {categories} | {group['file_count']} | {_format_bytes(int(group['size_bytes']))} | {ref_text} | {examples} |"
            )

    lines.extend(["", "## 活动引用明细", ""])
    if not references:
        lines.append("未发现活动源码或文档引用归档候选。")
    else:
        lines.extend(["下列候选在非归档源码/文档中仍被提及；归档前应更新引用或保留兼容说明。", ""])
        for key, paths in references.items():
            lines.append(f"- `{key}`：" + ", ".join(f"`{path}`" for path in paths[:20]))
            if len(paths) > 20:
                lines.append(f"  - 其余 {len(paths) - 20} 个引用未展开")

    lines.extend(["", "## 完全重复文件（SHA-256）", ""])
    if not with_hashes:
        lines.append("本次使用了 `--no-hashes`，未执行 SHA-256 重复检查；如需检查请重新运行 `python tools/project_hygiene.py report`。")
    elif not duplicates:
        lines.append("未发现内容完全相同的文件。")
    else:
        preview_limit = 20
        for index, paths in enumerate(duplicates[:preview_limit], start=1):
            lines.append(f"### 重复组 {index}")
            lines.extend(f"- `{path}`" for path in paths)
            lines.append("")
        if len(duplicates) > preview_limit:
            lines.append(
                f"共发现 {len(duplicates)} 组重复文件，仅展示前 {preview_limit} 组；完整列表见 `manifest.json`。"
            )
        lines.extend(["", "### 重复组分类汇总", "", "| 分类组合 | 重复组数 |", "| --- | ---: |"])
        for item in duplicate_category_summary:
            categories = ", ".join(f"`{category}`" for category in item["categories"])
            lines.append(f"| {categories} | {item['group_count']} |")
        lines.append("分类汇总仅用于定位重复来源，不表示任何路径可以直接删除。")

    lines.extend(
        [
            "## 推荐后续动作",
            "",
            "1. 先人工确认归档候选是否仍被复现脚本、文档或外部流程引用。",
            "2. 将确认后的候选移动到带日期的 `outputs/archive/YYYY-MM-project-hygiene/`，保留目录结构。",
            "3. 归档后重新运行 `python run_project.py smoke` 和 `python run_project.py validate-data`。",
            "4. 仅对确认可重建且不承担审计证据的日志/缓存考虑删除。",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_archive_plan(candidate_groups: list[dict[str, object]], generated_at: str) -> str:
    """函数 _render_archive_plan：执行该模块中的相关处理逻辑。"""
    lines = [
        "# 归档计划（仅计划，不执行）",
        "",
        f"生成时间（UTC）：`{generated_at}`",
        "",
        "本文件仅根据卫生扫描结果生成候选清单；没有移动、删除或覆盖任何文件。",
        "归档前必须人工确认复现、审计和外部引用，并单独执行经过批准的移动操作。",
        "",
        "## 绝不作为清理目标的路径",
        "",
        "- `data/source/`：审查后的原始来源表。",
        "- `data/real_shuohuang/`：当前默认运行数据集。",
        "- `data_templates/`：输入模板。",
        "- `tests/`：回归验证脚本和固定夹具。",
        "- `outputs/archive/`：已归档历史证据。",
        "",
        "## 候选汇总",
        "",
        "| 候选路径 | 文件数 | 大小 | 活动引用 | 建议 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for group in candidate_groups:
        references = int(group["reference_count"])
        if references:
            advice = "先更新引用或保留原位"
        else:
            advice = "可进入人工复核；不等于可删除"
        lines.append(
            f"| `{group['path']}` | {group['file_count']} | {_format_bytes(int(group['size_bytes']))} | {references} | {advice} |"
        )
    lines.extend(
        [
            "",
            "## 执行前检查",
            "",
            "1. 选择明确的候选路径，不使用通配符直接删除。",
            "2. 生成并保留归档前 SHA-256 manifest。",
            "3. 采用可恢复的移动方式，目标目录使用 `outputs/archive/YYYY-MM-project-hygiene/`。",
            "4. 归档后运行 `python run_project.py smoke` 和 `python run_project.py validate-data`。",
            "5. 对当前默认结果重新检查输入路径和关键 KPI，确认没有改变算法口径。",
        ]
    )
    return "\n".join(lines) + "\n"


def generate_report(root: Path, output_dir: Path, with_hashes: bool = True) -> tuple[Path, Path]:
    """函数 generate_report：执行该模块中的相关处理逻辑。"""
    root = root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = build_entries(root, output_dir, with_hashes)
    duplicates = _duplicate_groups(entries)
    duplicate_category_summary = _duplicate_category_summary(entries, duplicates)
    references = scan_references(root, entries, output_dir)
    candidate_groups = _candidate_groups(entries, references)
    dataset_comparison = compare_dataset_snapshots(root, with_hashes=with_hashes)
    generated_at = datetime.now(timezone.utc).isoformat()

    manifest = {
        "generated_at_utc": generated_at,
        "root": str(root),
        "hash_algorithm": "sha256" if with_hashes else None,
        "file_count": len(entries),
        "entries": [entry.__dict__ for entry in entries],
        "duplicate_groups": duplicates,
        "duplicate_category_summary": duplicate_category_summary,
        "candidate_references": references,
        "candidate_groups": candidate_groups,
        "dataset_comparison": dataset_comparison,
    }
    manifest_path = output_dir / "manifest.json"
    report_path = output_dir / "PROJECT_HYGIENE_REPORT.md"
    plan_path = output_dir / "ARCHIVE_PLAN.md"
    plan_json_path = output_dir / "archive_plan.json"
    dataset_report_path = output_dir / "DATASET_COMPARISON.md"
    dataset_json_path = output_dir / "dataset_comparison.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(
        _render_markdown(
            entries,
            duplicates,
            references,
            generated_at,
            with_hashes,
            duplicate_category_summary,
        ),
        encoding="utf-8",
    )
    plan_path.write_text(_render_archive_plan(candidate_groups, generated_at), encoding="utf-8")
    plan_json_path.write_text(
        json.dumps(
            {
                "generated_at_utc": generated_at,
                "mode": "plan_only",
                "apply_required": True,
                "protected_paths": [
                    "data/source",
                    "data/real_shuohuang",
                    "data_templates",
                    "tests",
                    "outputs/archive",
                ],
                "candidate_groups": candidate_groups,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    dataset_report_path.write_text(_render_dataset_comparison(dataset_comparison, generated_at), encoding="utf-8")
    dataset_json_path.write_text(json.dumps(dataset_comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path, manifest_path


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    report_parser = subparsers.add_parser("report", help="generate a non-destructive inventory report")
    report_parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root (default: current directory)")
    report_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/project_hygiene_report"),
        help="report directory, relative to --root unless absolute",
    )
    report_parser.add_argument("--no-hashes", action="store_true", help="skip SHA-256 calculation")

    args = parser.parse_args()
    if args.command == "report":
        root = args.root.resolve()
        output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
        report_path, manifest_path = generate_report(root, output_dir, with_hashes=not args.no_hashes)
        print(f"report: {report_path}")
        print(f"manifest: {manifest_path}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
