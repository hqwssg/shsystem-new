"""One-shot generator: MySQL energy_* DDL + adapted Python database package."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "新功能" / "数据库交付信息包_20260912"
DST = ROOT / "energy_recovery_agent"
SQL_OUT = ROOT / "shuohuang-main" / "sql" / "carbon-energy"
MIG = SRC / "database" / "migrations"


def convert_types(sql: str) -> str:
    sql = sql.replace("energy_recovery.simulation_", "energy_")
    sql = re.sub(r"\buuid\b", "char(36)", sql)
    sql = re.sub(r"\bjsonb\b", "json", sql)
    sql = sql.replace("bytea", "longblob")
    sql = sql.replace("timestamp with time zone", "datetime")
    sql = sql.replace("numeric", "decimal")
    sql = sql.replace("boolean", "tinyint(1)")
    sql = sql.replace(
        "bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY",
        "bigint(20) NOT NULL AUTO_INCREMENT",
    )
    sql = sql.replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP")
    sql = sql.replace("DEFAULT '{}'::json", "")
    sql = sql.replace("DEFAULT false", "DEFAULT 0")
    sql = sql.replace("DEFAULT true", "DEFAULT 1")
    sql = sql.replace("CREATE INDEX IF NOT EXISTS", "CREATE INDEX")
    sql = re.sub(r"CONSTRAINT ck_\w+ CHECK \(\s*jsonb_typeof\([^)]+\) = 'object'[^)]*\)[,]?", "", sql)
    sql = re.sub(
        r"CONSTRAINT ck_\w+ CHECK \(\s*jsonb_typeof\([^)]+\) = 'object' AND jsonb_typeof\([^)]+\) = 'object'\s*\)[,]?",
        "",
        sql,
    )
    sql = re.sub(
        r"AND relative_path !~ '[^']+' AND relative_path !~ '[^']+'",
        "",
        sql,
    )
    sql = sql.replace("uq_simulation_", "uq_energy_")
    sql = sql.replace("fk_simulation_", "fk_energy_")
    sql = sql.replace("ck_simulation_", "ck_energy_")
    sql = sql.replace("idx_simulation_", "idx_energy_")
    sql = re.sub(r"\brank integer\b", "`rank` int", sql)
    sql = sql.replace("integer", "int")
    sql = re.sub(r"[ \t]+\n", "\n", sql)
    return sql


def extract_creates(text: str) -> list[str]:
    blocks = []
    for match in re.finditer(r"CREATE TABLE(?: IF NOT EXISTS)?[\s\S]+?;", text):
        block = match.group(0)
        if " IF NOT EXISTS" not in block:
            block = block.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
        blocks.append(block)
    return blocks


def extract_indexes(text: str) -> list[str]:
    return re.findall(r"CREATE INDEX[\s\S]+?;", text)


def inject_run_columns(create_sql: str) -> str:
    extra = """    idempotency_key varchar(128) NOT NULL,
    request_sha256 char(64) NOT NULL,
    attempt_count int NOT NULL DEFAULT 0,
    lease_token char(36) DEFAULT NULL,
    lease_expires_at datetime DEFAULT NULL,
    heartbeat_at datetime DEFAULT NULL,
    state_version bigint NOT NULL DEFAULT 0,
"""
    create_sql = create_sql.replace(
        "CONSTRAINT ck_energy_run_type CHECK (run_type IN ('dispatch', 'timetable_audit', 'timetable_optimization'))",
        "CONSTRAINT ck_energy_run_type CHECK (run_type IN ('dispatch', 'timetable_audit', 'timetable_optimization', 'rolling_rescheduling', 'joint_parameter_robustness'))",
    )
    marker = "    CONSTRAINT fk_energy_run_project"
    if marker not in create_sql:
        raise SystemExit("energy_run marker missing")
    return create_sql.replace(marker, extra + marker)


def table_engine(create_sql: str) -> str:
    body = create_sql.strip().rstrip(";").rstrip()
    if body.endswith(")"):
        inner = body[:-1].rstrip()
    else:
        inner = body
    if "bigint(20) NOT NULL AUTO_INCREMENT" in inner and "PRIMARY KEY (" not in inner:
        first = re.search(r"^\s+(\w+)\s+bigint\(20\) NOT NULL AUTO_INCREMENT", inner, re.M)
        if first:
            inner += f",\n    PRIMARY KEY ({first.group(1)})"
    inner = inner.replace("energy_energy_scenario", "energy_scenario")
    inner = inner.replace("energy_energy_time_slice", "energy_time_slice")
    return inner + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n"


def build_ddl() -> str:
    parts = [
        "-- Energy recovery tables. Idempotent. Prefix energy_. Does not alter emission_* or report_*.\n"
    ]
    for name in ("001_core.sql", "002_inputs.sql", "003_runs.sql", "004_outputs.sql"):
        raw = convert_types((MIG / name).read_text(encoding="utf-8"))
        for block in extract_creates(raw):
            if "energy_schema_migration" in block:
                continue
            if "CREATE TABLE IF NOT EXISTS energy_run (" in block:
                block = inject_run_columns(block)
            parts.append(table_engine(block))
            parts.append("")
    rolling = convert_types((MIG / "005_rolling_control.sql").read_text(encoding="utf-8"))
    for block in extract_creates(rolling):
        parts.append(table_engine(block))
        parts.append("")
    events = convert_types((MIG / "006_run_transaction_idempotency.sql").read_text(encoding="utf-8"))
    for block in extract_creates(events):
        parts.append(table_engine(block))
        parts.append("")

    parts.append(
        """CREATE TABLE IF NOT EXISTS energy_dept_project (
  id                bigint(20)   NOT NULL AUTO_INCREMENT,
  dept_id           bigint(20)   NOT NULL,
  project_code      varchar(64)  NOT NULL,
  enabled           char(1)      NOT NULL DEFAULT '0',
  create_by         varchar(64)  DEFAULT '',
  create_time       datetime     DEFAULT NULL,
  update_by         varchar(64)  DEFAULT '',
  update_time       datetime     DEFAULT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_energy_dept_project (dept_id, project_code),
  KEY idx_energy_dept_project_code (project_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='登录部门与能量项目对照';
"""
    )
    index_src = convert_types((MIG / "004_outputs.sql").read_text(encoding="utf-8"))
    indexes = extract_indexes(index_src)
    indexes += extract_indexes(convert_types((MIG / "005_rolling_control.sql").read_text(encoding="utf-8")))
    indexes += [
        "CREATE INDEX idx_energy_run_idempotency ON energy_run(project_id, idempotency_key);",
        "CREATE INDEX idx_energy_run_expired_lease ON energy_run(status, lease_expires_at);",
        "CREATE INDEX idx_energy_run_event_timeline ON energy_run_state_event(run_id, state_version);",
    ]
    for idx in indexes:
        idx = idx.replace("created_at DESC", "created_at")
        idx = idx.replace("energy_energy_scenario", "energy_scenario")
        idx = idx.replace("energy_energy_time_slice", "energy_time_slice")
        parts.append(idx if idx.endswith(";") else idx + ";")
        parts.append("")
    return "\n".join(parts)


def copy_package() -> None:
    db_dst = DST / "database"
    db_dst.mkdir(parents=True, exist_ok=True)
    for name in (
        "cli.py",
        "worker.py",
        "parameters.py",
        "snapshots.py",
        "dataset_projection.py",
        "result_projection.py",
        "solver_budget.py",
        "io_mapping.json",
        "platform_api_contract.json",
        "interface_contract_freeze.json",
    ):
        shutil.copy2(SRC / "database" / name, db_dst / name)
    examples = db_dst / "examples"
    examples.mkdir(exist_ok=True)
    for path in (SRC / "database" / "examples").glob("*.json"):
        shutil.copy2(path, examples / path.name)
    templates = DST / "data_templates"
    if (SRC / "data_templates").exists():
        if templates.exists():
            shutil.rmtree(templates)
        shutil.copytree(SRC / "data_templates", templates)
    (DST / "tools").mkdir(exist_ok=True)


def transform_postgres() -> str:
    src = (SRC / "database" / "postgres.py").read_text(encoding="utf-8")
    src = src.replace("PostgreSQL迁移、版本导入、任务领取和结果写入实现。", "MySQL 迁移、版本导入、任务领取和结果写入实现。")
    src = src.replace("延迟加载psycopg，避免文件模式运行依赖数据库驱动。", "延迟加载 PyMySQL。")
    src = src.replace("connect_postgres", "connect_mysql")
    src = src.replace("energy_recovery.simulation_", "energy_")
    src = src.replace("energy_recovery.{table}", "{table}")
    src = src.replace("energy_energy_scenario", "energy_scenario")
    src = src.replace("energy_energy_time_slice", "energy_time_slice")
    src = src.replace('"simulation_', '"energy_')
    src = src.replace("'simulation_", "'energy_")
    src = src.replace("%s::jsonb", "%s")
    src = src.replace("::jsonb", "")
    src = src.replace("now() + %s * interval '1 second'", "DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s SECOND)")
    src = src.replace("now()", "UTC_TIMESTAMP()")
    src = src.replace("FOR UPDATE OF r SKIP LOCKED", "FOR UPDATE")
    src = src.replace("FOR UPDATE SKIP LOCKED", "FOR UPDATE")
    src = src.replace("JOIN energy_project_version v USING (project_id)", "JOIN energy_project_version v ON v.project_id = p.project_id")
    src = src.replace("JOIN energy_run_parameter p USING (run_id)", "JOIN energy_run_parameter p ON p.run_id = r.run_id")
    src = src.replace("lease_token IS NOT DISTINCT FROM %s", "lease_token <=> %s")
    src = src.replace("COALESCE(lease_expires_at > UTC_TIMESTAMP(), false)", "IFNULL(lease_expires_at > UTC_TIMESTAMP(), 0)")
    src = src.replace("started_at = COALESCE(started_at, UTC_TIMESTAMP())", "started_at = IFNULL(started_at, UTC_TIMESTAMP())")
    src = src.replace(
        """                    ON CONFLICT (project_code) DO UPDATE SET
                        project_name = EXCLUDED.project_name,
                        route_name = EXCLUDED.route_name,
                        updated_at = UTC_TIMESTAMP()""",
        """                    ON DUPLICATE KEY UPDATE
                        project_name = VALUES(project_name),
                        route_name = VALUES(route_name),
                        updated_at = UTC_TIMESTAMP()""",
    )
    src = src.replace("ON CONFLICT DO NOTHING", "")
    src = src.replace(
        """                    INSERT INTO energy_run_parameter (run_id, parameters_json)
                    VALUES (%s, %s)
                    ON CONFLICT (run_id) DO NOTHING""",
        """                    INSERT IGNORE INTO energy_run_parameter (run_id, parameters_json)
                    VALUES (%s, %s)""",
    )
    src = src.replace(
        """                    WHERE run_id = %s AND status = 'pending'
                    RETURNING state_version, attempt_count, lease_expires_at""",
        """                    WHERE run_id = %s AND status = 'pending'""",
    )
    src = src.replace(
        """                      AND lease_expires_at > UTC_TIMESTAMP()
                    RETURNING lease_expires_at""",
        """                      AND lease_expires_at > UTC_TIMESTAMP()""",
    )
    old_connect = '''def connect_mysql(database_url: str | None = None, *, autocommit: bool = False):
    """延迟加载 PyMySQL。"""

    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "数据库模式需要 psycopg。请安装 requirements-database.txt 中的依赖。"
        ) from exc
    dsn = database_url or os.environ.get("SIMULATION_DATABASE_URL")
    if not dsn:
        raise RuntimeError("未设置 SIMULATION_DATABASE_URL。")
    return psycopg.connect(dsn, autocommit=autocommit)
'''
    new_connect = '''def _parse_mysql_url(dsn: str) -> dict:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(dsn)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise RuntimeError("ENERGY_DATABASE_URL 必须是 mysql://user:pass@host:port/db")
    database = (parsed.path or "").lstrip("/")
    if not database:
        raise RuntimeError("ENERGY_DATABASE_URL 缺少数据库名。")
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or "root"),
        "password": unquote(parsed.password or ""),
        "database": database,
        "charset": "utf8mb4",
    }


def connect_mysql(database_url: str | None = None, *, autocommit: bool = False):
    """延迟加载 PyMySQL。"""

    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("数据库模式需要 PyMySQL。请安装 energy_recovery_agent/requirements.txt。") from exc
    dsn = database_url or os.environ.get("ENERGY_DATABASE_URL") or os.environ.get("SIMULATION_DATABASE_URL")
    if not dsn:
        raise RuntimeError("未设置 ENERGY_DATABASE_URL。")
    kwargs = _parse_mysql_url(dsn)
    connection = pymysql.connect(**kwargs)
    connection.autocommit(autocommit)
    return connection
'''
    if old_connect not in src:
        raise SystemExit("connect function pattern not found")
    src = src.replace(old_connect, new_connect)

    old_migrate = '''def apply_migrations(connection) -> list[str]:
    """按版本顺序执行迁移，并拒绝已应用迁移被静默篡改。"""

    applied = []
    files = _migration_files()
    with transaction(connection):
        with connection.cursor() as cursor:
            # 首次部署时迁移角色可能尚未创建；安全脚本执行后，所有升级迁移必须以
            # simulation_migrator 身份创建对象，避免对象归实际LOGIN账号而阻断后续ALTER。
            cursor.execute(
                """
                SELECT pg_get_userbyid(nspowner)
                FROM pg_namespace
                WHERE nspname = 'energy_recovery'
                """
            )
            schema_owner_row = cursor.fetchone()
            schema_exists = schema_owner_row is not None
            if schema_owner_row and str(schema_owner_row[0]) == "energy_migrator":
                cursor.execute(
                    "SELECT pg_has_role(current_user, 'simulation_migrator', 'MEMBER')"
                )
                if not bool(cursor.fetchone()[0]):
                    raise RuntimeError(
                        "迁移连接必须继承simulation_migrator角色，不能以非迁移账号升级数据库。"
                    )
                cursor.execute("SET LOCAL ROLE simulation_migrator")
            # 第一份迁移负责创建Schema和迁移历史表，本身是幂等的。
            # 已完成首次部署后不再重复执行CREATE SCHEMA，避免给迁移角色授予数据库级CREATE。
            if not schema_exists:
                cursor.execute(files[0].read_text(encoding="utf-8"))
            cursor.execute(
                "SELECT version, checksum_sha256 FROM energy_schema_migration"
            )
            known = {str(row[0]): str(row[1]) for row in cursor.fetchall()}
            for path in files:
                version = path.name.split("_", 1)[0]
                sql = path.read_text(encoding="utf-8")
                checksum = sha256(sql.encode("utf-8")).hexdigest()
                if version in known:
                    if known[version] != checksum:
                        raise RuntimeError(f"已应用迁移校验和变化：{path.name}")
                    continue
                if path != files[0]:
                    cursor.execute(sql)
                cursor.execute(
                    """
                    INSERT INTO energy_schema_migration
                        (version, description, checksum_sha256)
                    VALUES (%s, %s, %s)
                    """,
                    (version, path.stem, checksum),
                )
                applied.append(version)
    return applied
'''
    # The above may not match due to incomplete replacements. Replace apply_migrations by regex.
    src = re.sub(
        r"def apply_migrations\(connection\) -> list\[str\]:[\s\S]*?\n\ndef _json",
        '''def apply_migrations(connection) -> list[str]:
    """执行 MySQL energy_* 建表脚本（幂等 CREATE TABLE）。"""

    sql_path = Path(__file__).resolve().parents[2] / "shuohuang-main" / "sql" / "carbon-energy" / "V1__energy_tables.sql"
    if not sql_path.exists():
        sql_path = Path(__file__).resolve().parents[1] / "sql" / "V1__energy_tables.sql"
    sql = sql_path.read_text(encoding="utf-8")
    statements = [part.strip() for part in sql.split(";") if part.strip() and not part.strip().startswith("--")]
    with transaction(connection):
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
    return ["v1"]


def _json''',
        src,
        count=1,
    )
    src = src.replace("MIGRATIONS_DIR = Path(__file__).resolve().parent / \"migrations\"", "MIGRATIONS_DIR = Path(__file__).resolve().parent")
    src = re.sub(
        r"def _migration_files\(\) -> tuple\[Path, \.\.\.\]:[\s\S]*?\n\ndef apply_migrations",
        "def apply_migrations",
        src,
        count=1,
    )

    # INSERT IGNORE for create_run after stripping ON CONFLICT DO NOTHING
    src = src.replace(
        """                    INSERT INTO energy_run
                        (run_id, project_id, version_id, run_type, status, requested_by,
                         code_version, random_seed, idempotency_key, request_sha256)
                    VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s)
                    """,
        """                    INSERT IGNORE INTO energy_run
                        (run_id, project_id, version_id, run_type, status, requested_by,
                         code_version, random_seed, idempotency_key, request_sha256)
                    VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s)
                    """,
    )

    heartbeat_old = '''                cursor.execute(
                    """
                    UPDATE energy_run
                    SET heartbeat_at = UTC_TIMESTAMP(),
                        lease_expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s SECOND),
                        updated_at = UTC_TIMESTAMP()
                    WHERE run_id = %s
                      AND worker_id = %s
                      AND lease_token = %s
                      AND status IN ('validating', 'running')
                      AND lease_expires_at > UTC_TIMESTAMP()
                    """,
                    (lease_seconds, run_id, worker_id, lease_token),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RunLeaseLostError(f"任务租约已失效：{run_id}")
                return row[0]'''
    heartbeat_new = '''                cursor.execute(
                    """
                    UPDATE energy_run
                    SET heartbeat_at = UTC_TIMESTAMP(),
                        lease_expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s SECOND),
                        updated_at = UTC_TIMESTAMP()
                    WHERE run_id = %s
                      AND worker_id = %s
                      AND lease_token = %s
                      AND status IN ('validating', 'running')
                      AND lease_expires_at > UTC_TIMESTAMP()
                    """,
                    (lease_seconds, run_id, worker_id, lease_token),
                )
                if cursor.rowcount != 1:
                    raise RunLeaseLostError(f"任务租约已失效：{run_id}")
                cursor.execute(
                    "SELECT lease_expires_at FROM energy_run WHERE run_id = %s",
                    (run_id,),
                )
                row = cursor.fetchone()
                return row[0]'''
    if heartbeat_old not in src:
        raise SystemExit("heartbeat block not found")
    src = src.replace(heartbeat_old, heartbeat_new)

    claim_old = '''                cursor.execute(
                    """
                    UPDATE energy_run
                    SET status = 'validating', worker_id = %s, lease_token = %s,
                        lease_expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s SECOND),
                        heartbeat_at = UTC_TIMESTAMP(), started_at = IFNULL(started_at, UTC_TIMESTAMP()),
                        attempt_count = attempt_count + 1,
                        state_version = state_version + 1, updated_at = UTC_TIMESTAMP()
                    WHERE run_id = %s AND status = 'pending'
                    """,
                    (worker_id, lease_token, lease_seconds, row[0]),
                )
                claimed_state = cursor.fetchone()
                if claimed_state is None:
                    raise RunStateConflictError("任务在领取过程中已被其他工作进程修改。")'''
    claim_new = '''                cursor.execute(
                    """
                    UPDATE energy_run
                    SET status = 'validating', worker_id = %s, lease_token = %s,
                        lease_expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL %s SECOND),
                        heartbeat_at = UTC_TIMESTAMP(), started_at = IFNULL(started_at, UTC_TIMESTAMP()),
                        attempt_count = attempt_count + 1,
                        state_version = state_version + 1, updated_at = UTC_TIMESTAMP()
                    WHERE run_id = %s AND status = 'pending'
                    """,
                    (worker_id, lease_token, lease_seconds, row[0]),
                )
                if cursor.rowcount != 1:
                    raise RunStateConflictError("任务在领取过程中已被其他工作进程修改。")
                cursor.execute(
                    "SELECT state_version, attempt_count, lease_expires_at FROM energy_run WHERE run_id = %s",
                    (row[0],),
                )
                claimed_state = cursor.fetchone()
                if claimed_state is None:
                    raise RunStateConflictError("任务在领取过程中已被其他工作进程修改。")'''
    if claim_old not in src:
        raise SystemExit("claim block not found")
    src = src.replace(claim_old, claim_new)

    # stringify UUID in _insert_many
    src = src.replace(
        "values.append(tuple(_json(row.get(column)) if column in json_set else row.get(column) for column in columns))",
        "values.append(tuple(_bind(row.get(column), json_col=column in json_set) for column in columns))",
    )
    src = src.replace(
        "def _json(value: Any) -> str:\n    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(\",\", \":\"))",
        '''def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _bind(value: Any, *, json_col: bool = False):
    if json_col:
        return _json(value)
    if isinstance(value, UUID):
        return str(value)
    return value''',
    )
    return src


def patch_cli(text: str) -> str:
    text = text.replace("from .postgres import", "from .mysql import")
    text = text.replace("connect_postgres", "connect_mysql")
    text = text.replace("bootstrap.set_defaults(func=cmd_bootstrap_removed)", "bootstrap.set_defaults(func=cmd_bootstrap)")
    text = text.replace("覆盖SIMULATION_DATABASE_URL。", "覆盖 ENERGY_DATABASE_URL。")
    text = text.replace("cmd_bootstrap", "cmd_bootstrap_removed")
    # keep migrate
    text = text.replace("连接postgres管理数据库的DSN。", "未使用：库已存在于 MySQL carbon_emissions。")
    return text.replace(
        '''def cmd_bootstrap_removed(args: argparse.Namespace) -> int:
    """在管理连接中创建carbon_emissions数据库。"""

    connection = connect_mysql(args.admin_url, autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", ("carbon_emissions",))
            if cursor.fetchone() is None:
                from psycopg import sql
                cursor.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(
                    sql.Identifier("carbon_emissions")
                ))
                created = True
            else:
                created = False
        _print({"database": "carbon_emissions", "created": created})
    finally:
        connection.close()
    return 0
''',
        '''def cmd_bootstrap(args: argparse.Namespace) -> int:
    """MySQL 库由总系统维护，这里只确认可连接。"""

    connection = connect_mysql(args.database_url or os.environ.get("ENERGY_DATABASE_URL"))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE()")
            _print({"database": cursor.fetchone()[0], "engine": "mysql"})
    finally:
        connection.close()
    return 0
'''
    )


def patch_worker(text: str) -> str:
    return text.replace("from .postgres import", "from .mysql import")


def main() -> None:
    SQL_OUT.mkdir(parents=True, exist_ok=True)
    ddl = build_ddl()
    (SQL_OUT / "V1__energy_tables.sql").write_text(ddl, encoding="utf-8")
    copy_package()
    mysql_src = transform_postgres()
    (DST / "database" / "mysql.py").write_text(mysql_src, encoding="utf-8")
    (DST / "database" / "postgres.py").write_text(
        "from .mysql import *  # noqa: F401\nfrom .mysql import connect_mysql as connect_postgres\n",
        encoding="utf-8",
    )
    cli = patch_cli((DST / "database" / "cli.py").read_text(encoding="utf-8"))
    (DST / "database" / "cli.py").write_text(cli, encoding="utf-8")
    worker = patch_worker((DST / "database" / "worker.py").read_text(encoding="utf-8"))
    (DST / "database" / "worker.py").write_text(worker, encoding="utf-8")
    (DST / "database" / "__init__.py").write_text("", encoding="utf-8")
    (DST / "__init__.py").write_text("", encoding="utf-8")
    print("ddl_chars", len(ddl))
    print("mysql_chars", len(mysql_src))
    print("create_tables", ddl.count("CREATE TABLE"))


if __name__ == "__main__":
    main()
