"""Safely archive explicitly approved project candidates.

The command is intentionally plan-only unless ``--apply`` is supplied.  It
preserves each path below a dated archive directory and verifies every moved
file by SHA-256, leaving an auditable manifest for restoration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


PROTECTED_PREFIXES = (
    "data/source",
    "data/real_shuohuang",
    "data_templates",
    "tests",
    "outputs/archive",
    "outputs/run_manifests",
)


def sha256(path: Path) -> str:
    """函数 sha256：执行该模块中的相关处理逻辑。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_under(path: Path) -> list[Path]:
    """函数 files_under：执行该模块中的相关处理逻辑。"""
    if path.is_file():
        return [path]
    return sorted(candidate for candidate in path.rglob("*") if candidate.is_file())


def normalize_target(root: Path, raw: str) -> tuple[Path, str]:
    """函数 normalize_target：执行该模块中的相关处理逻辑。"""
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"target is outside project root: {raw}") from exc
    if relative == "" or any(relative == prefix or relative.startswith(prefix + "/") for prefix in PROTECTED_PREFIXES):
        raise ValueError(f"protected path cannot be archived: {relative}")
    return candidate, relative


def build_plan(root: Path, targets: list[str], archive_root: Path) -> dict[str, object]:
    """函数 build_plan：执行该模块中的相关处理逻辑。"""
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in targets:
        source, relative = normalize_target(root, raw)
        if relative in seen:
            continue
        seen.add(relative)
        if not source.exists():
            raise FileNotFoundError(source)
        files = files_under(source)
        entries.append(
            {
                "source": relative,
                "file_count": len(files),
                "size_bytes": sum(path.stat().st_size for path in files),
                "files": [
                    {
                        "relative": path.relative_to(root).as_posix(),
                        "size_bytes": path.stat().st_size,
                        "sha256": sha256(path),
                    }
                    for path in files
                ],
            }
        )
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if archive_root.exists() else "plan_only",
        "project_root": str(root),
        "archive_root": str(archive_root),
        "entries": entries,
    }


def apply_plan(root: Path, archive_root: Path, plan: dict[str, object]) -> None:
    """函数 apply_plan：执行该模块中的相关处理逻辑。"""
    archive_root.mkdir(parents=True, exist_ok=True)
    for entry in plan["entries"]:
        source = root / str(entry["source"])
        for file_record in entry["files"]:
            relative = Path(str(file_record["relative"]))
            source_file = root / relative
            destination = archive_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise FileExistsError(destination)
            shutil.move(str(source_file), str(destination))
            if sha256(destination) != file_record["sha256"]:
                raise RuntimeError(f"SHA-256 verification failed after move: {relative}")
        if source.is_dir():
            # 移动文件后可能留下空目录；只删除已确认为空的目录，以保持源码树整洁。
            for directory in sorted((path for path in source.rglob("*") if path.is_dir()), reverse=True):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            try:
                source.rmdir()
            except OSError:
                pass


def rebuild_manifest(root: Path, archive_root: Path) -> dict[str, object]:
    """Reconstruct an auditable manifest from an existing archive tree."""

    entries: list[dict[str, object]] = []
    for archived in sorted(path for path in archive_root.rglob("*") if path.is_file() and path.name != "ARCHIVE_MANIFEST.json"):
        relative = archived.relative_to(archive_root).as_posix()
        original = root / relative
        entries.append(
            {
                "source": relative,
                "file_count": 1,
                "size_bytes": archived.stat().st_size,
                "files": [
                    {
                        "relative": relative,
                        "size_bytes": archived.stat().st_size,
                        "sha256": sha256(archived),
                    }
                ],
                "original_missing_after_archive": not original.exists(),
            }
        )
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "rebuild",
        "project_root": str(root),
        "archive_root": str(archive_root),
        "entries": entries,
        "verification": "sha256_verified_in_archive",
    }


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="explicit relative paths to archive")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="perform verified moves")
    parser.add_argument("--rebuild", action="store_true", help="rebuild manifest from an existing archive")
    args = parser.parse_args()
    if not args.rebuild and not args.paths:
        parser.error("at least one path is required unless --rebuild is used")
    root = args.root.resolve()
    archive_dir = args.archive_dir if args.archive_dir.is_absolute() else root / args.archive_dir
    archive_dir = archive_dir.resolve()
    if args.rebuild:
        plan = rebuild_manifest(root, archive_dir)
        manifest = archive_dir / "ARCHIVE_MANIFEST.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"mode": plan["mode"], "archive_manifest": str(manifest), "entries": len(plan["entries"])}, ensure_ascii=False))
        return 0
    plan = build_plan(root, args.paths, archive_dir)
    move_plan = plan
    existing_manifest = archive_dir / "ARCHIVE_MANIFEST.json"
    if args.apply and existing_manifest.is_file():
        try:
            previous = json.loads(existing_manifest.read_text(encoding="utf-8"))
            previous_entries = previous.get("entries", []) if isinstance(previous, dict) else []
            existing_sources = {str(item.get("source")) for item in previous_entries if isinstance(item, dict)}
            new_entries = [item for item in plan["entries"] if str(item.get("source")) not in existing_sources]
            move_plan = dict(plan)
            move_plan["entries"] = new_entries
            plan["entries"] = list(previous_entries) + new_entries
            plan["merged_previous_manifest"] = True
        except (OSError, ValueError, TypeError):
            # 格式错误的旧清单不能阻止已验证文件移动；生成的新清单仍会包含本批次内容。
            plan["merged_previous_manifest"] = False
    plan["mode"] = "apply" if args.apply else "plan_only"
    if args.apply:
        apply_plan(root, archive_dir, move_plan)
        plan["verification"] = "sha256_verified_after_move"
    else:
        plan["verification"] = "not_applied"
    manifest = archive_dir / "ARCHIVE_MANIFEST.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"mode": plan["mode"], "archive_manifest": str(manifest), "entries": len(plan["entries"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
