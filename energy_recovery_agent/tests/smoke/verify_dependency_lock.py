"""验证发布依赖锁覆盖直接依赖，且每个锁定项都有制品哈希。"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^;\s\\]+)")


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_blocks(path: Path) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw[:1].isspace():
            if current:
                current.append(stripped)
            continue
        if current:
            blocks.append(" ".join(current))
        current = [stripped]
    if current:
        blocks.append(" ".join(current))
    return blocks


def main() -> int:
    lock_path = ROOT / "requirements-lock.txt"
    direct_path = ROOT / "requirements.txt"
    if not lock_path.is_file():
        raise AssertionError("发布包缺少requirements-lock.txt")
    blocks = _requirement_blocks(lock_path)
    locked: set[str] = set()
    for block in blocks:
        match = REQUIREMENT.match(block)
        if match is None:
            raise AssertionError(f"无法识别锁定依赖：{block}")
        if "--hash=sha256:" not in block:
            raise AssertionError(f"锁定依赖缺少SHA-256制品哈希：{match.group(1)}")
        locked.add(_normalized(match.group(1)))
    direct = {
        _normalized(match.group(1))
        for line in direct_path.read_text(encoding="utf-8").splitlines()
        if (match := REQUIREMENT.match(line.strip())) is not None
    }
    missing = sorted(direct - locked)
    if missing:
        raise AssertionError(f"锁文件未覆盖直接依赖：{missing}")
    if len(locked) < len(direct):
        raise AssertionError("锁文件没有记录传递依赖闭包")
    print(f"dependency lock verification: PASS ({len(locked)} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
