"""检查PostgreSQL版本、迁移、表、角色权限和任务队列。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence
import argparse
from hashlib import sha256
import json
import os

import psycopg


REQUIRED_MIGRATIONS = tuple(f"{index:03d}" for index in range(1, 8))
REQUIRED_TABLES = (
    "simulation_project",
    "simulation_project_version",
    "simulation_dataset_file",
    "simulation_run",
    "simulation_run_parameter",
    "simulation_run_input_snapshot",
    "simulation_run_state_event",
    "simulation_result_artifact",
    "simulation_result_kpi",
    "simulation_energy_time_slice",
    "simulation_rolling_control_event",
)
REQUIRED_ROLES = (
    "simulation_migrator",
    "simulation_platform",
    "simulation_worker",
    "simulation_readonly",
)
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "database" / "migrations"


def _expected_migration_checksums() -> dict[str, str]:
    """读取当前软件版本携带的迁移文件及其权威校验和。"""

    result = {}
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        version = path.name.split("_", 1)[0]
        result[version] = sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    return result


def healthcheck(database_url: str, *, require_tls: bool = False) -> dict[str, Any]:
    """返回机器可读健康状态，任何硬门禁失败时accepted为false。"""

    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, details: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "details": details})

    with psycopg.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_setting('server_version_num')::integer, "
                "current_user, pg_is_in_recovery(), current_setting('server_encoding')"
            )
            database_name, version_num, current_user, in_recovery, server_encoding = cursor.fetchone()
            add("postgresql_major_version", int(version_num) >= 160000, int(version_num))
            add("database_name", str(database_name) == "carbon_emissions", str(database_name))
            add("server_encoding", str(server_encoding).upper() == "UTF8", str(server_encoding))
            add("primary_writable_server", not bool(in_recovery), {"in_recovery": bool(in_recovery)})
            cursor.execute("SELECT ssl, version, cipher FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
            ssl_row = cursor.fetchone()
            ssl_enabled = bool(ssl_row and ssl_row[0])
            add(
                "tls_connection",
                ssl_enabled or not require_tls,
                {
                    "required": bool(require_tls),
                    "enabled": ssl_enabled,
                    "version": str(ssl_row[1]) if ssl_enabled else "",
                    "cipher": str(ssl_row[2]) if ssl_enabled else "",
                },
            )

            cursor.execute(
                "SELECT version FROM energy_recovery.simulation_schema_migration ORDER BY version"
            )
            migrations = tuple(str(row[0]) for row in cursor.fetchall())
            add("schema_migrations", migrations == REQUIRED_MIGRATIONS, list(migrations))
            cursor.execute(
                "SELECT version, checksum_sha256 FROM energy_recovery.simulation_schema_migration"
            )
            actual_checksums = {str(row[0]): str(row[1]) for row in cursor.fetchall()}
            expected_checksums = _expected_migration_checksums()
            add(
                "migration_checksums",
                actual_checksums == expected_checksums,
                {
                    "expected_versions": sorted(expected_checksums),
                    "mismatched_versions": sorted(
                        version for version in set(actual_checksums) | set(expected_checksums)
                        if actual_checksums.get(version) != expected_checksums.get(version)
                    ),
                },
            )

            cursor.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'energy_recovery' AND table_name = ANY(%s)
                ORDER BY table_name
                """,
                (list(REQUIRED_TABLES),),
            )
            tables = {str(row[0]) for row in cursor.fetchall()}
            add("required_tables", tables == set(REQUIRED_TABLES), {
                "found": sorted(tables),
                "missing": sorted(set(REQUIRED_TABLES) - tables),
            })

            cursor.execute(
                "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
                (list(REQUIRED_ROLES),),
            )
            roles = {str(row[0]): bool(row[1]) for row in cursor.fetchall()}
            add("security_roles", set(roles) == set(REQUIRED_ROLES) and not any(roles.values()), roles)

            cursor.execute(
                "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'energy_recovery'"
            )
            schema_owner_row = cursor.fetchone()
            schema_owner = str(schema_owner_row[0]) if schema_owner_row else ""
            add("schema_owner", schema_owner == "simulation_migrator", schema_owner)
            cursor.execute(
                """
                SELECT c.relkind, pg_get_userbyid(c.relowner), count(*)
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'energy_recovery' AND c.relkind IN ('r', 'p', 'S', 'v', 'm')
                GROUP BY c.relkind, pg_get_userbyid(c.relowner)
                ORDER BY c.relkind, pg_get_userbyid(c.relowner)
                """
            )
            ownership_rows = [
                {"kind": str(row[0]), "owner": str(row[1]), "count": int(row[2])}
                for row in cursor.fetchall()
            ]
            add(
                "business_object_owners",
                bool(ownership_rows)
                and all(row["owner"] == "simulation_migrator" for row in ownership_rows),
                ownership_rows,
            )

            cursor.execute(
                """
                SELECT
                  has_table_privilege('simulation_platform', 'energy_recovery.simulation_run', 'INSERT'),
                  has_table_privilege('simulation_worker', 'energy_recovery.simulation_result_artifact', 'INSERT'),
                  has_table_privilege('simulation_readonly', 'energy_recovery.simulation_result_artifact', 'SELECT'),
                  has_table_privilege('simulation_readonly', 'energy_recovery.simulation_result_artifact', 'INSERT')
                """
            )
            privileges = tuple(bool(value) for value in cursor.fetchone())
            add("role_privileges", privileges == (True, True, True, False), {
                "platform_can_create_run": privileges[0],
                "worker_can_write_artifact": privileges[1],
                "readonly_can_read_artifact": privileges[2],
                "readonly_can_write_artifact": privileges[3],
            })

            cursor.execute("SELECT status, count(*) FROM energy_recovery.simulation_run GROUP BY status")
            queue = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
            add("queue_query", True, queue)

    return {
        "schema_version": "1.0",
        "accepted": all(item["passed"] for item in checks),
        "database": str(database_name),
        "current_user": str(current_user),
        "checks": checks,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("SIMULATION_DATABASE_URL"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-tls", action="store_true", help="生产环境要求当前连接使用TLS")
    args = parser.parse_args(argv)
    if not args.database_url:
        raise RuntimeError("必须通过--database-url或SIMULATION_DATABASE_URL提供连接串。")
    result = healthcheck(args.database_url, require_tls=args.require_tls)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
