"""将算法交付包同步到本运行根，保留 MySQL 适配层。"""

from __future__ import annotations

from pathlib import Path
import argparse
import shutil
import sys


PROTECTED = {
    "database/mysql.py",
    "database/cli.py",
    "database/worker.py",
    "database/postgres.py",
    "sql/V1__energy_tables.sql",
    "tests/test_mysql_layer.py",
    "tools/run_worker_loop.py",
    "tools/sync_algorithm_drop.py",
    "_build_mysql_layer.py",
    "requirements.txt",
    "README.md",
}

SKIP_PREFIXES = (
    "database/migrations/",
)

SKIP_NAMES = {
    "database.env.example",
    "security_roles.sql",
}


def should_skip(relative: str) -> bool:
    normalized = relative.replace("\\", "/")
    if normalized in PROTECTED:
        return True
    if any(normalized.startswith(prefix) for prefix in SKIP_PREFIXES):
        return True
    if Path(normalized).name in SKIP_NAMES:
        return True
    return False


def sync(source: Path, target: Path) -> dict[str, int]:
    copied = 0
    skipped = 0
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix()
        if should_skip(relative):
            skipped += 1
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied += 1
    return {"copied": copied, "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    source = args.source.resolve()
    target = args.target.resolve()
    if not source.is_dir():
        raise SystemExit(f"源目录不存在: {source}")
    counts = sync(source, target)
    print(f"copied={counts['copied']} skipped={counts['skipped']} target={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
