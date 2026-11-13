"""对PostgreSQL业务库执行安全的逻辑备份与隔离恢复演练。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote, urlparse

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.production_operations_snapshot import DEFAULT_POLICY, load_policy




def validate_restore_database_name(name: str, suffix: str, source_database: str) -> None:
    """只允许全新隔离测试库，拒绝业务库和宽泛名称。"""
    if not name or name == source_database or not name.endswith(suffix):
        raise ValueError(f"恢复库名称必须以{suffix}结尾且不能等于源库。")
    if not all(character.isalnum() or character == "_" for character in name):
        raise ValueError("恢复库名称只能包含字母、数字和下划线。")


def _connection_environment(database_url: str) -> tuple[dict[str, str], str]:
    """把连接串转为PG环境变量，避免密码出现在子进程命令行。"""
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ValueError("只支持标准PostgreSQL连接串。")
    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise ValueError("连接串必须包含数据库名。")
    environment = dict(os.environ)
    environment.update({
        "PGHOST": parsed.hostname,
        "PGPORT": str(parsed.port or 5432),
        "PGDATABASE": database,
        "PGUSER": unquote(parsed.username or ""),
    })
    if parsed.password is not None:
        environment["PGPASSWORD"] = unquote(parsed.password)
    query = dict(part.split("=", 1) for part in parsed.query.split("&") if "=" in part)
    if "sslmode" in query:
        environment["PGSSLMODE"] = query["sslmode"]
    return environment, database


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _find_binary(name: str, pg_bin: Path | None) -> str:
    candidate = pg_bin / f"{name}.exe" if pg_bin and os.name == "nt" else pg_bin / name if pg_bin else None
    if candidate and candidate.is_file():
        return str(candidate)
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"未找到{name}；请通过--pg-bin指定PostgreSQL bin目录。")
    return resolved


def _run(command: Sequence[str], *, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(command), cwd=ROOT, env=environment, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"命令失败（返回码{completed.returncode}）：{Path(command[0]).name}；"
            f"stderr={completed.stderr[-1000:].strip()}"
        )
    return completed


def _database_exists(connection: psycopg.Connection[Any], name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = %s)", (name,))
        return bool(cursor.fetchone()[0])


def _database_dsn(base_url: str, database: str) -> str:
    parsed = urlparse(base_url)
    return parsed._replace(path=f"/{database}").geturl()


def _inventory(database_url: str, tables: Sequence[str]) -> dict[str, int]:
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            result = {}
            for table in tables:
                cursor.execute(sql.SQL("SELECT count(*) FROM energy_recovery.{}").format(sql.Identifier(table)))
                result[table] = int(cursor.fetchone()[0])
            return result


def _dump_consistent_snapshot(
    source_url: str,
    *,
    pg_dump: str,
    backup_path: Path,
    source_environment: dict[str, str],
    row_count_tables: Sequence[str],
) -> tuple[dict[str, int], int]:
    """在同一导出快照上完成源表计数和pg_dump，拒绝活动任务。"""
    with psycopg.connect(source_url, connect_timeout=10) as connection:
        connection.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM energy_recovery.simulation_run "
                "WHERE status IN ('pending', 'validating', 'running')"
            )
            active_run_count = int(cursor.fetchone()[0])
            if active_run_count:
                raise RuntimeError(
                    f"源库存在{active_run_count}个活动或排队任务；暂停平台和worker后再演练。"
                )
            cursor.execute("SELECT pg_export_snapshot()")
            snapshot_id = str(cursor.fetchone()[0])
            counts = {}
            for table in row_count_tables:
                cursor.execute(
                    sql.SQL("SELECT count(*) FROM energy_recovery.{}").format(sql.Identifier(table))
                )
                counts[table] = int(cursor.fetchone()[0])
        _run([
            pg_dump, "--format=custom", "--snapshot", snapshot_id, "--file", str(backup_path)
        ], environment=source_environment)
        return counts, active_run_count


def run_drill(
    *, source_url: str, admin_url: str, restore_database: str, output_dir: Path,
    policy_path: Path, pg_bin: Path | None, cleanup: bool,
) -> dict[str, Any]:
    """创建备份、新建隔离库、恢复并对比结构与关键行数。"""
    policy = load_policy(policy_path)
    backup_policy = policy["backup"]
    source_env, source_database = _connection_environment(source_url)
    admin_env, _ = _connection_environment(admin_url)
    suffix = str(backup_policy["restore_database_suffix"])
    validate_restore_database_name(restore_database, suffix, source_database)
    output_dir.mkdir(parents=True, exist_ok=True)
    backup_path = output_dir / f"{source_database}.dump"
    pg_dump = _find_binary("pg_dump", pg_bin)
    pg_restore = _find_binary("pg_restore", pg_bin)
    created = False
    restored = False
    cleaned_up = False
    started_at = datetime.now(timezone.utc).isoformat()
    with psycopg.connect(admin_url, autocommit=True, connect_timeout=10) as admin_connection:
        if _database_exists(admin_connection, restore_database):
            raise RuntimeError(f"隔离恢复库已存在，工具拒绝覆盖：{restore_database}")
        source_counts, active_run_count = _dump_consistent_snapshot(
            source_url, pg_dump=pg_dump, backup_path=backup_path,
            source_environment=source_env,
            row_count_tables=backup_policy["row_count_tables"],
        )
        listing = _run([pg_restore, "--list", str(backup_path)], environment=source_env)
        if "energy_recovery" not in listing.stdout:
            raise RuntimeError("备份目录未包含energy_recovery对象。")
        try:
            with admin_connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(
                        sql.Identifier(restore_database)
                    )
                )
            created = True
            restore_env = dict(admin_env)
            restore_env["PGDATABASE"] = restore_database
            _run([
                pg_restore, "--dbname", restore_database, "--no-owner", "--no-privileges",
                "--exit-on-error", str(backup_path),
            ], environment=restore_env)
            restored = True
            restore_url = _database_dsn(admin_url, restore_database)
            with psycopg.connect(restore_url, connect_timeout=10) as restored_connection:
                with restored_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT version FROM energy_recovery.simulation_schema_migration ORDER BY version"
                    )
                    migrations = [str(row[0]) for row in cursor.fetchall()]
                    cursor.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='energy_recovery' ORDER BY table_name"
                    )
                    tables = {str(row[0]) for row in cursor.fetchall()}
            restored_counts = _inventory(restore_url, backup_policy["row_count_tables"])
            missing_tables = sorted(set(backup_policy["required_tables"]) - tables)
            checks = {
                "source_queue_quiescent": active_run_count == 0,
                "backup_nonempty": backup_path.stat().st_size > 0,
                "backup_catalog_readable": "energy_recovery" in listing.stdout,
                "migration_versions_match": migrations == list(backup_policy["required_migration_versions"]),
                "required_tables_present": not missing_tables,
                "row_counts_match": restored_counts == source_counts,
            }
        finally:
            if created and cleanup:
                with admin_connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()",
                        (restore_database,),
                    )
                    cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(restore_database)))
                cleaned_up = True
    accepted = restored and all(checks.values())
    result = {
        "schema_version": "1.0", "policy_version": policy["policy_version"],
        "started_at_utc": started_at, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_database": source_database, "restore_database": restore_database,
        "backup_path": str(backup_path), "backup_size_bytes": backup_path.stat().st_size,
        "backup_sha256": _sha256(backup_path), "restore_created": created,
        "restore_completed": restored, "cleanup_requested": cleanup, "restore_cleaned_up": cleaned_up,
        "source_row_counts": source_counts, "restored_row_counts": restored_counts,
        "migration_versions": migrations, "missing_required_tables": missing_tables,
        "checks": checks, "accepted": accepted,
        "credentials_recorded": False,
        "boundary": "本地恢复演练通过不替代正式备份介质、RPO和RTO验收。",
    }
    (output_dir / "backup_restore_drill.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# PostgreSQL备份恢复演练", "", f"- 结论：`{'PASS' if accepted else 'FAIL'}`",
        f"- 源库：`{source_database}`", f"- 隔离恢复库：`{restore_database}`",
        f"- 备份大小：`{result['backup_size_bytes']}` 字节",
        f"- 备份SHA-256：`{result['backup_sha256']}`",
        f"- 演练后清理：`{cleaned_up}`", "", "| 检查 | 状态 |", "| --- | --- |",
    ]
    lines.extend(f"| `{name}` | {'PASS' if passed else 'FAIL'} |" for name, passed in checks.items())
    lines.extend(["", "报告不记录连接串或密码。本结果仅证明本地逻辑备份可恢复。"])
    (output_dir / "BACKUP_RESTORE_DRILL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database-url", default=os.environ.get("SIMULATION_BACKUP_SOURCE_DATABASE_URL"))
    parser.add_argument("--admin-url", default=os.environ.get("POSTGRES_ADMIN_URL"))
    parser.add_argument("--restore-database", default="carbon_emissions_restore_test")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "production_backup_restore_drill")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--pg-bin", type=Path)
    parser.add_argument("--keep-restore-database", action="store_true")
    args = parser.parse_args(argv)
    if not args.source_database_url or not args.admin_url:
        raise RuntimeError("必须提供SIMULATION_BACKUP_SOURCE_DATABASE_URL和POSTGRES_ADMIN_URL。")
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    policy_path = args.policy if args.policy.is_absolute() else ROOT / args.policy
    result = run_drill(
        source_url=args.source_database_url, admin_url=args.admin_url,
        restore_database=args.restore_database, output_dir=output_dir,
        policy_path=policy_path, pg_bin=args.pg_bin,
        cleanup=not args.keep_restore_database,
    )
    print(json.dumps({
        "accepted": result["accepted"], "backup_sha256": result["backup_sha256"],
        "restore_cleaned_up": result["restore_cleaned_up"], "output_dir": str(output_dir),
    }, ensure_ascii=False))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
