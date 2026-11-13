"""MySQL 访问层（PyMySQL）。

- 统一 utf8mb4 / DictCursor
- 提供事务上下文
- 不在此层做业务规则，业务规则在 services / pipeline 中
"""
from __future__ import annotations

import json
import math
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterable, Optional

from .config import settings

def connect():
    dsn = settings.db_dsn.strip()
    scheme = dsn.split(":", 1)[0].lower() if ":" in dsn else ""
    if scheme in {"mysql", "mysql+pymysql"} or (not scheme and settings.db_driver.lower() in {"mysql", "mysql+pymysql"}):
        try:
            import pymysql
            from pymysql.cursors import DictCursor
        except ImportError as exc:
            raise RuntimeError("MySQL mode requires PyMySQL in the Python image") from exc
        from urllib.parse import unquote, urlparse
        parsed = urlparse(dsn) if dsn else None
        connection = pymysql.connect(
            host=(parsed.hostname if parsed else None) or settings.db_host,
            port=(parsed.port if parsed else None) or settings.db_port or 3306,
            user=unquote(parsed.username if parsed else "") or settings.db_user,
            password=unquote(parsed.password if parsed else "") or settings.db_password,
            database=((parsed.path if parsed else None) or "/" + settings.db_name).lstrip("/"),
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=8,
        )
        return connection
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("PostgreSQL/CERDB mode requires a psycopg-compatible driver") from exc
    dsn = dsn or (
        f"host={settings.db_host} port={settings.db_port} dbname={settings.db_name} "
        f"user={settings.db_user} password={settings.db_password} connect_timeout=8"
    )
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=False)


_active_connection = ContextVar("prediction_transaction_connection", default=None)


@contextmanager
def connection():
    active = _active_connection.get()
    if active is not None:
        yield active
        return
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction():
    active = _active_connection.get()
    if active is not None:
        yield active
        return
    conn = connect()
    token = _active_connection.set(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _active_connection.reset(token)
        conn.close()


def fetch_all(sql: str, params: Optional[Iterable[Any]] = None) -> list[dict]:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params) if params else None)
            return list(cur.fetchall())


def fetch_one(sql: str, params: Optional[Iterable[Any]] = None) -> Optional[dict]:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Optional[Iterable[Any]] = None) -> int:
    with transaction() as conn:
        with conn.cursor() as cur:
            return cur.execute(sql, tuple(params) if params else None)


def execute_many(sql: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with transaction() as conn:
        with conn.cursor() as cur:
            return cur.executemany(sql, rows)


def execute_script(path: str) -> None:
    """执行 SQL 脚本（按分号切分，忽略注释与空语句）。"""
    text = open(path, encoding="utf-8").read()
    # 去除行注释，保留字符串内的分号场景较少，本脚本可控
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("--") or not s:
            continue
        lines.append(line)
    statements = [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
    with transaction() as conn:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)


def healthcheck() -> dict:
    mysql_mode = settings.db_dsn.lower().startswith(("mysql:", "mysql+")) or settings.db_driver.lower() in {"mysql", "mysql+pymysql"}
    query = "SELECT VERSION() AS version, DATABASE() AS db" if mysql_mode else "SELECT VERSION() AS version, current_database() AS db"
    row = fetch_one(query)
    return {"ok": True, **(row or {})}


def _clean_json(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_json(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return _clean_json(value.item())
        except Exception:
            return str(value)
    return value


def j(value: Any) -> str:
    """JSON 序列化，供 MySQL JSON 列使用；NaN/Inf 转为 null。"""
    return json.dumps(_clean_json(value), ensure_ascii=False, default=str, allow_nan=False)


def audit(action: str, entity: str, entity_id: str | None, operator: str | None, detail: Any = None) -> None:
    execute(
        "INSERT INTO prediction_audit_log(action,entity,entity_id,operator,detail) VALUES(%s,%s,%s,%s,%s)",
        (action, entity, entity_id, operator, j(detail or {})),
    )
