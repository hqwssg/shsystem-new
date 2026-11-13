"""Smoke checks for verified, recoverable hygiene archives."""

from __future__ import annotations

import tempfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.archive_project_candidates import apply_plan, build_plan, rebuild_manifest


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    with tempfile.TemporaryDirectory(prefix="archive_candidates_smoke_") as temp:
        root = Path(temp)
        (root / "tools").mkdir()
        (root / "tools" / "probe.py").write_text("probe\n", encoding="utf-8")
        (root / "recover.py").write_text("recover\n", encoding="utf-8")
        archive = root / "outputs" / "archive" / "test"
        plan = build_plan(root, ["tools/probe.py"], archive)
        apply_plan(root, archive, plan)
        if (root / "tools" / "probe.py").exists() or not (archive / "tools" / "probe.py").is_file():
            raise AssertionError("approved candidate was not moved")
        plan2 = build_plan(root, ["recover.py"], archive)
        apply_plan(root, archive, plan2)
        rebuilt = rebuild_manifest(root, archive)
        if len(rebuilt["entries"]) != 2 or rebuilt["verification"] != "sha256_verified_in_archive":
            raise AssertionError("archive manifest rebuild did not retain both batches")
        try:
            build_plan(root, ["tests"], archive)
        except (ValueError, FileNotFoundError):
            pass
        else:
            raise AssertionError("protected paths must be rejected")
    print("archive candidate verification: PASS")


if __name__ == "__main__":
    main()
