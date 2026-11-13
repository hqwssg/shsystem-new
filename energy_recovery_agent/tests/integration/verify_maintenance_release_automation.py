"""验证维护与发布自动化的锁、可复现构建和门禁编排。"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from tools.automate_release import build_accepted_release_pointer
from tools.build_algorithm_delivery_package import _write_reproducible_zip
from tools.process_lock import ProcessLock
from tools.run_release_acceptance import acceptance_commands


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maintenance_release_automation_") as temp:
        root = Path(temp)
        source = root / "source"
        source.mkdir()
        (source / "b.txt").write_text("second\n", encoding="utf-8")
        (source / "a.txt").write_text("first\n", encoding="utf-8")
        timestamp = datetime(2026, 9, 11, 6, 0, 0, tzinfo=timezone.utc)
        first = root / "first.zip"
        second = root / "second.zip"
        _write_reproducible_zip(source, first, "package", timestamp)
        _write_reproducible_zip(source, second, "package", timestamp)
        if _sha256(first) != _sha256(second):
            raise AssertionError("相同输入和构建时间必须生成字节一致的ZIP")

        lock_path = root / "task.lock"
        with ProcessLock(lock_path, "outer"):
            try:
                with ProcessLock(lock_path, "inner"):
                    raise AssertionError("并发锁不应获取成功")
            except RuntimeError:
                pass
        if lock_path.exists():
            raise AssertionError("正常退出后必须释放锁")

        acceptance_dir = root / "acceptance"
        acceptance_dir.mkdir()
        acceptance_summary = acceptance_dir / "release_acceptance_summary.json"
        acceptance_summary.write_text(json.dumps({"accepted": True, "complete_scope": True, "release_version": "2026.09.11.6"}), encoding="utf-8")
        release_zip = root / "deliverables/algorithm_release_20260911_v6.zip"
        release_zip.parent.mkdir()
        release_zip.write_bytes(b"release")
        pointer = build_accepted_release_pointer(
            acceptance_summary,
            release_zip,
            {"release_version": "2026.09.11.6", "package_id": "algorithm_release_20260911_v6"},
            root,
        )
        if pointer["status"] != "accepted" or pointer["package_zip_sha256"] != _sha256(release_zip):
            raise AssertionError("正式版本指针没有绑定验收状态和算法包哈希")

        commands = acceptance_commands(root / "acceptance", root / "package", root / "package.zip", False)
        names = [name for name, _ in commands]
        expected = ["release_package", "package_runtime", "release_security", "interface_contract", "local_ci", "short_smoke", "long_regression"]
        if names != expected:
            raise AssertionError(f"发布门禁顺序不正确：{names}")

    print("maintenance and release automation verification: PASS")


if __name__ == "__main__":
    main()
