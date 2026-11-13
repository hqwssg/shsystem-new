"""验证软件成分审计能够正确识别有效和不完整的依赖哈希锁。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from software_composition_audit import _inspect_artifact_hash_lock  # noqa: E402


def main() -> int:
    expected = {"numpy": "2.0.2", "psycopg": "3.2.13"}
    valid_text = """numpy==2.0.2 \\
    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
psycopg==3.2.13 \\
    --hash=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
"""
    invalid_text = """numpy==2.0.2 \\
    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
psycopg==3.2.12
"""
    with tempfile.TemporaryDirectory() as temporary:
        lock_path = Path(temporary) / "requirements-lock.txt"
        lock_path.write_text(valid_text, encoding="utf-8")
        valid = _inspect_artifact_hash_lock(lock_path, expected)
        if not valid["valid"] or valid["locked_component_count"] != 2:
            raise AssertionError(f"有效哈希锁识别失败：{valid}")

        lock_path.write_text(invalid_text, encoding="utf-8")
        invalid = _inspect_artifact_hash_lock(lock_path, expected)
        if invalid["valid"]:
            raise AssertionError("版本不一致且缺少哈希的锁文件不应通过")
        if invalid["version_mismatches"] != [{"name": "psycopg", "expected": "3.2.13", "locked": "3.2.12"}]:
            raise AssertionError(f"未正确报告版本不一致：{invalid}")
        if invalid["unhashed_components"] != ["psycopg"]:
            raise AssertionError(f"未正确报告缺少哈希：{invalid}")

    print("software composition hash lock verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
