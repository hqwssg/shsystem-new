"""验证目标平台四类数据库登录账号、TLS和实际拒绝行为。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Sequence

import psycopg
from psycopg import errors


MODULE_ROLES = (
    "simulation_migrator",
    "simulation_platform",
    "simulation_worker",
    "simulation_readonly",
)
ACCOUNT_SPECS = (
    ("migrator", "simulation_migrator", "SIMULATION_MIGRATOR_DATABASE_URL"),
    ("platform", "simulation_platform", "SIMULATION_PLATFORM_DATABASE_URL"),
    ("worker", "simulation_worker", "SIMULATION_DATABASE_URL"),
    ("readonly", "simulation_readonly", "SIMULATION_READONLY_DATABASE_URL"),
)


def _add(checks: list[dict[str, Any]], name: str, passed: bool, details: Any) -> None:
    checks.append({"name": name, "passed": bool(passed), "details": details})


def _statement_is_denied(connection, statement: str) -> tuple[bool, str]:
    """在回滚事务中执行拒绝探针；只有权限不足SQLSTATE才算通过。"""

    try:
        with connection.cursor() as cursor:
            cursor.execute(statement)
    except errors.InsufficientPrivilege as exc:
        connection.rollback()
        return True, str(exc.sqlstate or "")
    except Exception as exc:
        connection.rollback()
        return False, str(getattr(exc, "sqlstate", "") or type(exc).__name__)
    connection.rollback()
    return False, "statement_succeeded"


def _inspect_account(
    label: str,
    expected_role: str,
    database_url: str,
    *,
    expected_database: str,
    require_tls: bool,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT current_user, current_database(),
                       current_setting('server_version_num')::integer,
                       current_setting('server_encoding'),
                       r.rolsuper, r.rolcanlogin
                FROM pg_roles r WHERE r.rolname = current_user
                """
            )
            current_user, database_name, version_num, encoding, is_superuser, can_login = cursor.fetchone()
            cursor.execute("SELECT ssl, version, cipher FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
            ssl_row = cursor.fetchone()
            memberships = {}
            for role in MODULE_ROLES:
                cursor.execute("SELECT pg_has_role(current_user, %s, 'MEMBER')", (role,))
                memberships[role] = bool(cursor.fetchone()[0])

        _add(checks, "database_name", str(database_name) == expected_database, str(database_name))
        _add(checks, "postgresql_major_version", int(version_num) >= 160000, int(version_num))
        _add(checks, "server_encoding", str(encoding).upper() == "UTF8", str(encoding))
        _add(checks, "login_role", bool(can_login) and not bool(is_superuser), {
            "current_user": str(current_user),
            "can_login": bool(can_login),
            "is_superuser": bool(is_superuser),
        })
        expected_memberships = {role: role == expected_role for role in MODULE_ROLES}
        _add(checks, "exclusive_module_role_membership", memberships == expected_memberships, memberships)
        ssl_enabled = bool(ssl_row and ssl_row[0])
        _add(checks, "tls_connection", ssl_enabled or not require_tls, {
            "required": require_tls,
            "enabled": ssl_enabled,
            "version": str(ssl_row[1]) if ssl_enabled else "",
            "cipher": str(ssl_row[2]) if ssl_enabled else "",
        })

        if label == "migrator":
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL ROLE simulation_migrator")
                    cursor.execute(
                        "CREATE TABLE energy_recovery.simulation_migrator_owner_probe (id integer)"
                    )
                    cursor.execute(
                        """
                        SELECT tableowner FROM pg_tables
                        WHERE schemaname = 'energy_recovery'
                          AND tablename = 'simulation_migrator_owner_probe'
                        """
                    )
                    owner = str(cursor.fetchone()[0])
                connection.rollback()
                _add(checks, "migration_ddl_and_owner", owner == "simulation_migrator", owner)
            except Exception as exc:
                connection.rollback()
                _add(checks, "migration_ddl_and_owner", False, {
                    "sqlstate": str(getattr(exc, "sqlstate", "") or ""),
                    "error_type": type(exc).__name__,
                })
        else:
            denied, result = _statement_is_denied(
                connection,
                "CREATE TABLE energy_recovery.simulation_nonmigrator_ddl_probe (id integer)",
            )
            _add(checks, "ddl_denied", denied, result)

        if label == "readonly":
            denied, result = _statement_is_denied(
                connection,
                """
                INSERT INTO energy_recovery.simulation_result_artifact
                    (run_id, relative_path, artifact_type, media_type, content,
                     content_size_bytes, content_sha256)
                VALUES
                    ('00000000-0000-0000-0000-000000000000', 'permission-probe',
                     'probe', 'text/plain', ''::bytea, 0, repeat('0', 64))
                """,
            )
            _add(checks, "write_denied", denied, result)

    return {
        "account": label,
        "expected_role": expected_role,
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
    }


def verify_target_access(
    urls: dict[str, str],
    *,
    expected_database: str = "carbon_emissions",
    require_tls: bool = True,
) -> dict[str, Any]:
    """验证四个独立登录账号，不在报告中保留连接串。"""

    accounts = []
    for label, expected_role, _environment_name in ACCOUNT_SPECS:
        accounts.append(
            _inspect_account(
                label,
                expected_role,
                urls[label],
                expected_database=expected_database,
                require_tls=require_tls,
            )
        )
    return {
        "schema_version": "1.0",
        "expected_database": expected_database,
        "tls_required": require_tls,
        "accepted": all(item["passed"] for item in accounts),
        "accounts": accounts,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for label, _expected_role, environment_name in ACCOUNT_SPECS:
        parser.add_argument(
            f"--{label}-database-url",
            default=os.environ.get(environment_name),
            help=f"默认读取{environment_name}",
        )
    parser.add_argument("--expected-database", default="carbon_emissions")
    parser.add_argument("--allow-insecure", action="store_true", help="仅限本地隔离测试实例")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    urls = {label: getattr(args, f"{label}_database_url") for label, _, _ in ACCOUNT_SPECS}
    missing = [label for label, value in urls.items() if not value]
    if missing:
        raise RuntimeError(f"缺少目标数据库账号连接：{missing}")
    result = verify_target_access(
        urls,
        expected_database=str(args.expected_database),
        require_tls=not bool(args.allow_insecure),
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
