"""MySQL 迁移、版本导入、任务领取和结果写入实现。"""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
import json
import os
import re
import tempfile

from .dataset_projection import project_dataset
from .file_names import records_to_storage_names
from .result_projection import project_result_directory
from .snapshots import (
    FileRecord,
    collect_file_records,
    materialize_file_records,
    merge_file_records,
    snapshot_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = Path(__file__).resolve().parent


def chinese_version_name(version_code: str) -> str:
    """把 v1 这类版本编码转成中文显示名，内部编码仍用 version_code。"""

    text = str(version_code or "").strip()
    match = re.fullmatch(r"[vV](\d+)", text)
    if match:
        return f"第{int(match.group(1))}版"
    return text


def project_dataset_records(
    version_id: UUID,
    records: Sequence[FileRecord],
) -> dict[str, list[dict]]:
    """从最终不可变文件集合生成关系投影。"""

    with tempfile.TemporaryDirectory(prefix="energy_dataset_projection_") as temp_name:
        projection_root = Path(temp_name)
        from .planning import normalized_planning_records
        materialize_file_records(normalized_planning_records(records), projection_root)
        return project_dataset(version_id, projection_root)


class RunLeaseLostError(RuntimeError):
    """工作进程的任务租约已过期、被回收或不再属于当前令牌。"""


class RunStateConflictError(RuntimeError):
    """任务状态不允许当前转换或幂等请求内容发生冲突。"""


def _parse_mysql_url(dsn: str) -> dict:
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
    connection = pymysql.connect(
        **kwargs,
        client_flag=pymysql.constants.CLIENT.FOUND_ROWS,
    )
    connection.autocommit(autocommit)
    return connection


@contextmanager
def transaction(connection) -> Iterator[None]:
    """提供与标准DB-API兼容的提交和回滚边界。"""

    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def apply_migrations(connection) -> list[str]:
    """Apply V1 and V3; never imports sample data. MySQL DDL commits implicitly."""
    import pymysql
    root = Path(__file__).resolve().parents[2] / "shuohuang-main/sql/carbon-energy"
    for name in ("V1__energy_tables.sql", "V3__storage_planning.sql"):
        path = root / name
        if not path.is_file():
            path = Path(__file__).resolve().parents[1] / "sql" / name
        raw = path.read_text(encoding="utf-8-sig")
        cleaned = "\n".join(line for line in raw.splitlines() if not line.strip().startswith("--"))
        with connection.cursor() as cursor:
            for statement in (part.strip() for part in cleaned.split(";") if part.strip()):
                try:
                    cursor.execute(statement)
                except pymysql.err.OperationalError as exc:
                    if exc.args[0] not in {1050, 1061}:
                        raise
        connection.commit()
    return ["v1", "v3"]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _bind(value: Any, *, json_col: bool = False):
    if json_col:
        return _json(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def run_request_sha256(
    project_id: UUID,
    version_id: UUID,
    run_type: str,
    parameters: Mapping[str, Any],
    requested_by: str,
    code_version: str,
) -> str:
    """计算不受JSON键顺序影响的任务请求摘要。"""

    canonical_parameters = dict(parameters)
    storage_devices = canonical_parameters.get("storage_devices")
    if str(run_type) == "rolling_rescheduling" and isinstance(storage_devices, list):
        canonical_parameters["storage_devices"] = sorted(
            storage_devices,
            key=lambda item: (
                str(item.get("storage_section_id", ""))
                if isinstance(item, Mapping)
                else repr(item)
            ),
        )
    payload = {
        "project_id": str(project_id),
        "version_id": str(version_id),
        "run_type": str(run_type),
        "parameters": canonical_parameters,
        "requested_by": str(requested_by),
        "code_version": str(code_version),
    }
    return sha256(_json(payload).encode("utf-8")).hexdigest()


def _validated_positive_seconds(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name}必须是正整数秒。")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是正整数秒。") from exc
    if number <= 0 or str(number) != str(value).strip():
        raise ValueError(f"{field_name}必须是正整数秒。")
    return number


def _insert_many(cursor, table: str, columns: Sequence[str], rows: Iterable[Mapping[str, Any]], *, json_columns: Iterable[str] = ()) -> int:
    """对固定白名单表执行批量插入，JSON字段显式转换为jsonb。"""

    row_list = list(rows)
    if not row_list:
        return 0
    json_set = set(json_columns)
    quoted = ["`rank`" if column == "rank" else column for column in columns]
    placeholders = ["%s" for _column in columns]
    sql = (
        f"INSERT INTO {table} ({', '.join(quoted)}) "
        f"VALUES ({', '.join(placeholders)})"
    )
    values = []
    for row in row_list:
        values.append(tuple(_bind(row.get(column), json_col=column in json_set) for column in columns))
    cursor.executemany(sql, values)
    return len(values)


class SimulationRepository:
    """平台与算法工作进程共享的数据库仓储。"""

    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def _insert_run_state_event(
        cursor,
        *,
        run_id: UUID,
        state_version: int,
        from_status: str | None,
        to_status: str,
        worker_id: str | None,
        lease_token: UUID | None,
        reason: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """在状态更新所在事务中追加不可变审计事件。"""

        cursor.execute(
            """
            INSERT INTO energy_run_state_event
                (run_id, state_version, from_status, to_status, worker_id,
                 lease_token, reason, details_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                state_version,
                from_status,
                to_status,
                worker_id,
                lease_token,
                reason,
                _json(dict(details or {})),
            ),
        )

    def import_dataset(
        self,
        source_dir: Path,
        *,
        project_code: str,
        project_name: str,
        route_name: str,
        version_code: str,
        data_status: str = "planning_placeholder",
        source_note: str = "",
        extra_files: Mapping[str, Path] | None = None,
    ) -> dict:
        """无损导入文件并写入常用关系投影，发布为不可变版本。"""

        records = merge_file_records(collect_file_records(source_dir), extra_files or {})
        project_id = uuid5(NAMESPACE_URL, f"carbon_emissions/project/{project_code}")
        version_id = uuid5(project_id, version_code)
        # 关系投影必须与最终无损快照使用完全相同的文件集合，尤其要包含平台通过
        # --extra-file 提交的逐设备储能参数，不能只投影原始目录。
        projection = project_dataset_records(version_id, records)
        storage_records = records_to_storage_names(records)
        manifest = snapshot_manifest(storage_records)
        with transaction(self.connection):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO energy_project
                        (project_id, project_code, project_name, route_name)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        project_name = VALUES(project_name),
                        route_name = VALUES(route_name),
                        updated_at = UTC_TIMESTAMP()
                    """,
                    (project_id, project_code, project_name, route_name),
                )
                cursor.execute(
                    "SELECT lifecycle_status, content_sha256 FROM energy_project_version WHERE version_id = %s",
                    (version_id,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    if str(existing[0]) == "published" and str(existing[1]) == manifest["snapshot_sha256"]:
                        return {"project_id": project_id, "version_id": version_id, **manifest, "already_present": True}
                    raise ValueError(f"版本代码已存在且不可覆盖：{version_code}")
                cursor.execute(
                    """
                    INSERT INTO energy_project_version
                        (version_id, project_id, version_code, version_name, data_status,
                         lifecycle_status, source_note, content_sha256, published_at)
                    VALUES (%s, %s, %s, %s, %s, 'published', %s, %s, UTC_TIMESTAMP())
                    """,
                    (version_id, project_id, version_code, chinese_version_name(version_code), data_status, source_note, manifest["snapshot_sha256"]),
                )
                _insert_many(
                    cursor,
                    "energy_dataset_file",
                    ("version_id", "relative_path", "media_type", "content", "content_size_bytes", "content_sha256"),
                    ({
                        "version_id": version_id,
                        "relative_path": record.relative_path,
                        "media_type": record.media_type,
                        "content": record.content,
                        "content_size_bytes": record.content_size_bytes,
                        "content_sha256": record.content_sha256,
                    } for record in storage_records),
                )
                self._insert_dataset_projection(cursor, version_id, projection)
        return {"project_id": project_id, "version_id": version_id, **manifest, "already_present": False}

    def replace_dataset(self, version_id: UUID, records: Sequence[FileRecord], *, source_note: str = "") -> dict:
        """用同一 version_id 覆盖文件快照并重建关系投影，不新建版本。"""

        if not records:
            raise ValueError("替换数据版本时至少要保留一个文件")
        projection = project_dataset_records(version_id, records)
        storage_records = records_to_storage_names(records)
        manifest = snapshot_manifest(storage_records)
        delete_tables = (
            "energy_storage_site_technology_option", "energy_storage_candidate_site", "energy_storage_technology",
            "energy_storage_planning_scenario", "energy_storage_planning_policy",
            "energy_station_resource",
            "energy_station",
            "energy_route_segment",
            "energy_train_type_parameter",
            "energy_storage_device",
            "energy_power_arm",
            "energy_signaling_block",
        )
        with transaction(self.connection):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    "SELECT version_code FROM energy_project_version WHERE version_id = %s AND lifecycle_status = 'published' FOR UPDATE",
                    (version_id,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise ValueError(f"找不到可覆盖的已发布版本：{version_id}")
                for table in delete_tables:
                    cursor.execute(f"DELETE FROM {table} WHERE version_id = %s", (version_id,))
                cursor.execute("DELETE FROM energy_dataset_file WHERE version_id = %s", (version_id,))
                _insert_many(
                    cursor,
                    "energy_dataset_file",
                    ("version_id", "relative_path", "media_type", "content", "content_size_bytes", "content_sha256"),
                    ({
                        "version_id": version_id,
                        "relative_path": record.relative_path,
                        "media_type": record.media_type,
                        "content": record.content,
                        "content_size_bytes": record.content_size_bytes,
                        "content_sha256": record.content_sha256,
                    } for record in storage_records),
                )
                self._insert_dataset_projection(cursor, version_id, projection)
                cursor.execute(
                    """
                    UPDATE energy_project_version
                    SET content_sha256 = %s,
                        source_note = %s,
                        published_at = UTC_TIMESTAMP()
                    WHERE version_id = %s
                    """,
                    (manifest["snapshot_sha256"], source_note, version_id),
                )
        return {
            "version_id": version_id,
            "version_code": str(existing[0]),
            **manifest,
            "replaced": True,
        }

    def resolve_version(self, project_code: str, version_code: str) -> tuple[UUID, UUID]:
        """按平台业务编码解析项目和已发布版本。"""

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.project_id, v.version_id
                FROM energy_project p
                JOIN energy_project_version v ON v.project_id = p.project_id
                WHERE p.project_code = %s AND v.version_code = %s AND v.lifecycle_status = 'published'
                """,
                (project_code, version_code),
            )
            row = cursor.fetchone()
        if row is None:
            raise ValueError(f"找不到已发布数据版本：{project_code}/{version_code}")
        return UUID(str(row[0])), UUID(str(row[1]))

    def get_run(self, run_id: UUID) -> dict:
        """返回平台轮询所需的任务状态和关键追踪字段。"""

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT run_id, project_id, version_id, run_type, status, requested_by,
                       code_version, random_seed, input_sha256, result_sha256,
                       error_count, warning_count, error_message, queued_at, started_at, finished_at,
                       idempotency_key, request_sha256, attempt_count, worker_id,
                       lease_expires_at, heartbeat_at, state_version
                FROM energy_run WHERE run_id = %s
                """,
                (run_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise ValueError(f"任务不存在：{run_id}")
        names = (
            "run_id", "project_id", "version_id", "run_type", "status", "requested_by",
            "code_version", "random_seed", "input_sha256", "result_sha256",
            "error_count", "warning_count", "error_message", "queued_at", "started_at", "finished_at",
            "idempotency_key", "request_sha256", "attempt_count", "worker_id",
            "lease_expires_at", "heartbeat_at", "state_version",
        )
        return {name: value for name, value in zip(names, row)}

    def load_run_state_events(self, run_id: UUID) -> list[dict]:
        """按状态版本返回任务生命周期审计事件。"""

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_id, run_id, state_version, from_status, to_status,
                       worker_id, lease_token, reason, details_json, occurred_at
                FROM energy_run_state_event
                WHERE run_id = %s
                ORDER BY state_version
                """,
                (run_id,),
            )
            rows = cursor.fetchall()
        names = (
            "event_id", "run_id", "state_version", "from_status", "to_status",
            "worker_id", "lease_token", "reason", "details", "occurred_at",
        )
        return [dict(zip(names, row)) for row in rows]

    def load_result_artifacts(self, run_id: UUID) -> tuple[FileRecord, ...]:
        """读取完整结果工件，供平台下载或复算。"""

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT relative_path, media_type, content, content_sha256
                FROM energy_result_artifact
                WHERE run_id = %s ORDER BY relative_path
                """,
                (run_id,),
            )
            return tuple(
                FileRecord(str(row[0]), str(row[1]), bytes(row[2]), str(row[3]))
                for row in cursor.fetchall()
            )

    @staticmethod
    def _insert_dataset_projection(cursor, version_id: UUID, projection: Mapping[str, list[dict]]) -> None:
        specs = (
            ("storage_candidate_sites", "energy_storage_candidate_site", ("candidate_site_id", "version_id", "site_code", "site_name", "position_km", "power_arm_code", "storage_section_start_km", "storage_section_end_km", "direction", "buildable", "max_connection_power_kw", "max_capacity_kwh", "fixed_site_cost_cny", "allowed_technology_codes_json", "data_status", "source_note"), ("allowed_technology_codes_json",)),
            ("storage_technologies", "energy_storage_technology", ("storage_technology_id", "version_id", "technology_code", "technology_name", "parameters_json", "data_status", "source_note"), ("parameters_json",)),
            ("storage_site_technology_options", "energy_storage_site_technology_option", ("option_id", "version_id", "site_code", "technology_code", "limits_json", "available", "source_note"), ("limits_json",)),
            ("storage_planning_scenarios", "energy_storage_planning_scenario", ("planning_scenario_id", "version_id", "scenario_set_code", "scenario_code", "scenario_name", "weight", "core_for_feasibility", "scenario_json", "data_status", "source_note"), ("scenario_json",)),
            ("storage_planning_policies", "energy_storage_planning_policy", ("planning_policy_id", "version_id", "policy_code", "policy_json", "data_status", "source_note"), ("policy_json",)),

            ("stations", "energy_station", ("station_id", "version_id", "station_code", "station_name", "position_km", "station_type", "track_capacity", "throat_capacity", "is_terminal", "source_note"), ()),
            ("segments", "energy_route_segment", ("segment_id", "version_id", "segment_code", "start_km", "end_km", "gradient_permille", "curve_radius_m", "speed_limit_kmh", "terrain", "direction", "source_note"), ()),
            ("train_types", "energy_train_type_parameter", ("train_type_id", "version_id", "train_type_code", "train_type", "mass_t", "mass_min_t", "mass_max_t", "length_km", "rotational_mass_factor", "max_traction_kn", "max_brake_kn", "max_power_kw", "davis_a", "davis_b", "davis_c", "direction", "longitudinal_segments", "extra_parameters_json", "data_status", "source_note"), ("extra_parameters_json",)),
            ("storage_devices", "energy_storage_device", ("storage_id", "version_id", "storage_code", "label", "capacity_kwh", "max_charge_power_kw", "max_discharge_power_kw", "charge_efficiency", "discharge_efficiency", "initial_soc_kwh", "min_soc_kwh", "max_soc_kwh", "start_km", "end_km", "direction", "available", "data_status", "source_note"), ()),
            ("power_arms", "energy_power_arm", ("power_arm_id", "version_id", "power_arm_code", "start_km", "end_km", "direction", "max_traction_supply_kw", "max_regen_absorption_kw", "max_grid_feedback_kw", "direct_use_allowed", "needs_manual_review", "data_status", "source_note"), ()),
            ("signaling_blocks", "energy_signaling_block", ("signaling_block_id", "version_id", "block_code", "start_km", "end_km", "direction", "capacity", "release_margin_s", "data_status", "source_note"), ()),
            ("station_resources", "energy_station_resource", ("station_resource_id", "version_id", "station_id", "track_capacity", "throat_capacity", "station_occupancy_s", "throat_occupancy_s", "extra_rules_json", "source_note"), ("extra_rules_json",)),
        )
        for key, table, columns, json_columns in specs:
            rows = []
            for source in projection.get(key, []):
                row = dict(source)
                row["version_id"] = version_id
                for json_field in json_columns:
                    if json_field not in row and json_field.endswith("_json"):
                        row[json_field] = row.pop(json_field[:-5], {})
                if "extra_parameters_json" in columns and "extra_parameters_json" not in row:
                    row["extra_parameters_json"] = row.pop("extra_parameters", {})
                if "extra_rules_json" in columns and "extra_rules_json" not in row:
                    row["extra_rules_json"] = row.pop("extra_rules", {})
                rows.append(row)
            _insert_many(cursor, table, columns, rows, json_columns=json_columns)

    def create_run(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
        run_type: str,
        parameters: Mapping[str, Any],
        requested_by: str = "platform",
        code_version: str = "working-tree",
        idempotency_key: str,
    ) -> UUID:
        """原子创建任务；相同幂等键只返回内容完全一致的已有任务。"""

        from .parameters import validate_run_parameters
        validate_run_parameters(run_type, parameters)
        normalized_key = str(idempotency_key).strip()
        if not normalized_key:
            raise ValueError("idempotency_key不能为空字符串。")
        if len(normalized_key) > 128:
            raise ValueError("idempotency_key长度不能超过128。")
        request_hash = run_request_sha256(
            project_id,
            version_id,
            run_type,
            parameters,
            requested_by,
            code_version,
        )
        run_id = uuid5(project_id, f"simulation-run:{normalized_key}")
        seed = int(parameters.get("seed", 0))
        with transaction(self.connection):
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT project_id FROM energy_project_version WHERE version_id = %s AND lifecycle_status = 'published' FOR UPDATE", (version_id,))
                version = cursor.fetchone()
                if version is None or str(version[0]) != str(project_id):
                    raise ValueError("任务项目与已发布版本不匹配。")
                if run_type == "storage_planning":
                    from .planning import validate_planning_records
                    validate_planning_records(self.load_version_files(version_id), parameters)
                cursor.execute(
                    """
                    INSERT IGNORE INTO energy_run
                        (run_id, project_id, version_id, run_type, status, requested_by,
                         code_version, random_seed, idempotency_key, request_sha256)
                    VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s)
                    
                    """,
                    (
                        run_id, project_id, version_id, run_type, requested_by,
                        code_version, seed, normalized_key, request_hash,
                    ),
                )
                inserted = cursor.rowcount == 1
                cursor.execute(
                    """
                    SELECT run_id, request_sha256
                    FROM energy_run
                    WHERE project_id = %s AND idempotency_key = %s
                    FOR UPDATE
                    """,
                    (project_id, normalized_key),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise RuntimeError("幂等任务写入后无法读取。")
                run_id = UUID(str(existing[0]))
                if str(existing[1]) != request_hash:
                    raise RunStateConflictError(
                        "同一idempotency_key对应了不同任务内容。"
                    )
                cursor.execute(
                    """
                    INSERT IGNORE INTO energy_run_parameter (run_id, parameters_json)
                    VALUES (%s, %s)
                    """,
                    (run_id, _json(dict(parameters))),
                )
                if inserted:
                    self._insert_run_state_event(
                        cursor,
                        run_id=run_id,
                        state_version=0,
                        from_status=None,
                        to_status="pending",
                        worker_id=None,
                        lease_token=None,
                        reason="run_created",
                        details={"idempotency_key": normalized_key},
                    )
        return run_id

    def claim_next_run(self, worker_id: str, *, lease_seconds: int = 300) -> dict | None:
        """以SKIP LOCKED原子领取一个任务，支持多个工作进程并发。"""

        worker_id = str(worker_id).strip()
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id必须为1到128个字符。")
        lease_seconds = _validated_positive_seconds(lease_seconds, "lease_seconds")
        self.requeue_expired_runs()
        lease_token = uuid4()
        with transaction(self.connection):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT r.run_id, r.project_id, r.version_id, r.run_type,
                           p.parameters_json, r.state_version
                    FROM energy_run r
                    JOIN energy_run_parameter p ON p.run_id = r.run_id
                    WHERE r.status = 'pending'
                    ORDER BY r.queued_at, r.run_id
                    FOR UPDATE
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute(
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
                    raise RunStateConflictError("任务在领取过程中已被其他工作进程修改。")
                self._insert_run_state_event(
                    cursor,
                    run_id=UUID(str(row[0])),
                    state_version=int(claimed_state[0]),
                    from_status="pending",
                    to_status="validating",
                    worker_id=worker_id,
                    lease_token=lease_token,
                    reason="worker_claimed",
                    details={"attempt_count": int(claimed_state[1])},
                )
                parameters = row[4] if isinstance(row[4], dict) else json.loads(row[4])
                return {
                    "run_id": row[0], "project_id": row[1], "version_id": row[2],
                    "run_type": row[3], "parameters": parameters,
                    "worker_id": worker_id, "lease_token": lease_token,
                    "lease_expires_at": claimed_state[2],
                    "attempt_count": int(claimed_state[1]),
                }

    def claim_run(self, run_id: UUID, worker_id: str, *, lease_seconds: int = 300) -> dict | None:
        """领取指定 pending 任务；不存在或已被领取时返回 None。"""

        worker_id = str(worker_id).strip()
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id必须为1到128个字符。")
        lease_seconds = _validated_positive_seconds(lease_seconds, "lease_seconds")
        self.requeue_expired_runs()
        lease_token = uuid4()
        with transaction(self.connection):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT r.run_id, r.project_id, r.version_id, r.run_type,
                           p.parameters_json, r.state_version
                    FROM energy_run r
                    JOIN energy_run_parameter p ON p.run_id = r.run_id
                    WHERE r.run_id = %s AND r.status = 'pending'
                    FOR UPDATE
                    """,
                    (str(run_id),),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute(
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
                    return None
                cursor.execute(
                    "SELECT state_version, attempt_count, lease_expires_at FROM energy_run WHERE run_id = %s",
                    (row[0],),
                )
                claimed_state = cursor.fetchone()
                if claimed_state is None:
                    return None
                self._insert_run_state_event(
                    cursor,
                    run_id=UUID(str(row[0])),
                    state_version=int(claimed_state[0]),
                    from_status="pending",
                    to_status="validating",
                    worker_id=worker_id,
                    lease_token=lease_token,
                    reason="worker_claimed",
                    details={"attempt_count": int(claimed_state[1])},
                )
                parameters = row[4] if isinstance(row[4], dict) else json.loads(row[4])
                return {
                    "run_id": row[0], "project_id": row[1], "version_id": row[2],
                    "run_type": row[3], "parameters": parameters,
                    "worker_id": worker_id, "lease_token": lease_token,
                    "lease_expires_at": claimed_state[2],
                    "attempt_count": int(claimed_state[1]),
                }

    def heartbeat_run(
        self,
        run_id: UUID,
        worker_id: str,
        lease_token: UUID,
        *,
        lease_seconds: int = 300,
    ) -> Any:
        """仅允许当前未过期租约续期，旧工作进程不能复活已失去的租约。"""

        lease_seconds = _validated_positive_seconds(lease_seconds, "lease_seconds")
        with transaction(self.connection):
            with self.connection.cursor() as cursor:
                cursor.execute(
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
                    (lease_seconds, str(run_id), worker_id, str(lease_token)),
                )
                cursor.execute(
                    """
                    SELECT lease_expires_at FROM energy_run
                    WHERE run_id = %s AND worker_id = %s AND lease_token = %s
                      AND status IN ('validating', 'running')
                      AND lease_expires_at > UTC_TIMESTAMP()
                    """,
                    (str(run_id), worker_id, str(lease_token)),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RunLeaseLostError(f"任务租约已失效：{run_id}")
                return row[0]

    def requeue_expired_runs(self, *, max_attempts: int = 3) -> dict[str, int]:
        """回收过期活跃任务；达到尝试上限的任务转为失败，避免无限重跑。"""

        max_attempts = _validated_positive_seconds(max_attempts, "max_attempts")
        counts = {"requeued": 0, "failed": 0}
        with transaction(self.connection):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT run_id, status, worker_id, lease_token,
                           state_version, attempt_count
                    FROM energy_run
                    WHERE status IN ('validating', 'running')
                      AND (lease_expires_at IS NULL OR lease_expires_at <= UTC_TIMESTAMP())
                    ORDER BY lease_expires_at, run_id
                    FOR UPDATE
                    """
                )
                for row in cursor.fetchall():
                    run_id = UUID(str(row[0]))
                    from_status = str(row[1])
                    old_worker_id = None if row[2] is None else str(row[2])
                    old_lease_token = None if row[3] is None else UUID(str(row[3]))
                    state_version = int(row[4]) + 1
                    attempt_count = int(row[5])
                    terminal = attempt_count >= max_attempts
                    to_status = "failed" if terminal else "pending"
                    reason = (
                        "lease_expired_attempt_limit"
                        if terminal
                        else "lease_expired_requeued"
                    )
                    cursor.execute(
                        """
                        UPDATE energy_run
                        SET status = %s, worker_id = NULL, lease_token = NULL,
                            lease_expires_at = NULL, heartbeat_at = NULL,
                            state_version = %s, updated_at = UTC_TIMESTAMP(),
                            finished_at = CASE WHEN %s = 'failed' THEN UTC_TIMESTAMP() ELSE NULL END,
                            error_count = error_count + CASE WHEN %s = 'failed' THEN 1 ELSE 0 END,
                            error_message = CASE
                                WHEN %s = 'failed' THEN '任务租约连续过期，已达到最大尝试次数。'
                                ELSE error_message
                            END
                        WHERE run_id = %s AND lease_token <=> %s
                        """,
                        (
                            to_status, state_version, to_status, to_status,
                            to_status, run_id, old_lease_token,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RunStateConflictError(f"回收任务状态冲突：{run_id}")
                    self._insert_run_state_event(
                        cursor,
                        run_id=run_id,
                        state_version=state_version,
                        from_status=from_status,
                        to_status=to_status,
                        worker_id=old_worker_id,
                        lease_token=old_lease_token,
                        reason=reason,
                        details={
                            "attempt_count": attempt_count,
                            "max_attempts": max_attempts,
                        },
                    )
                    counts["failed" if terminal else "requeued"] += 1
        return counts

    def cancel_run(self, run_id: UUID, reason: str = "cancelled_by_platform") -> bool:
        """以行锁原子取消非终态任务，并立即使工作进程租约失效。"""

        reason = str(reason).strip() or "cancelled_by_platform"
        with transaction(self.connection):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, worker_id, lease_token, state_version
                    FROM energy_run
                    WHERE run_id = %s FOR UPDATE
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ValueError(f"任务不存在：{run_id}")
                from_status = str(row[0])
                if from_status == "cancelled":
                    return False
                if from_status in {"succeeded", "failed"}:
                    raise RunStateConflictError(
                        f"终态任务不能取消：{run_id}/{from_status}"
                    )
                state_version = int(row[3]) + 1
                cursor.execute(
                    """
                    UPDATE energy_run
                    SET status = 'cancelled', lease_token = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL,
                        state_version = %s, finished_at = UTC_TIMESTAMP(), updated_at = UTC_TIMESTAMP()
                    WHERE run_id = %s AND status = %s
                    """,
                    (state_version, run_id, from_status),
                )
                if cursor.rowcount != 1:
                    raise RunStateConflictError(f"取消任务状态冲突：{run_id}")
                self._insert_run_state_event(
                    cursor,
                    run_id=run_id,
                    state_version=state_version,
                    from_status=from_status,
                    to_status="cancelled",
                    worker_id=None if row[1] is None else str(row[1]),
                    lease_token=None if row[2] is None else UUID(str(row[2])),
                    reason=reason[:128],
                )
                return True

    def delete_run(self, run_id: UUID) -> bool:
        """取消非终态租约后删除任务及其级联结果。"""

        with transaction(self.connection):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, worker_id, lease_token, state_version
                    FROM energy_run
                    WHERE run_id = %s FOR UPDATE
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ValueError(f"任务不存在：{run_id}")
                from_status = str(row[0])
                if from_status not in {"succeeded", "failed", "cancelled"}:
                    state_version = int(row[3]) + 1
                    cursor.execute(
                        """
                        UPDATE energy_run
                        SET status = 'cancelled', lease_token = NULL,
                            lease_expires_at = NULL, heartbeat_at = NULL,
                            state_version = %s, finished_at = UTC_TIMESTAMP(), updated_at = UTC_TIMESTAMP()
                        WHERE run_id = %s AND status = %s
                        """,
                        (state_version, run_id, from_status),
                    )
                    if cursor.rowcount != 1:
                        raise RunStateConflictError(f"删除任务状态冲突：{run_id}")
                    self._insert_run_state_event(
                        cursor,
                        run_id=run_id,
                        state_version=state_version,
                        from_status=from_status,
                        to_status="cancelled",
                        worker_id=None if row[1] is None else str(row[1]),
                        lease_token=None if row[2] is None else UUID(str(row[2])),
                        reason="deleted_by_platform",
                    )
                cursor.execute(
                    "UPDATE energy_optimization_decision SET selected_candidate_id = NULL WHERE run_id = %s",
                    (run_id,),
                )
                self._delete_run_results(cursor, run_id)
                cursor.execute("DELETE FROM energy_run WHERE run_id = %s", (run_id,))
                return cursor.rowcount == 1

    def load_version_files(self, version_id: UUID) -> tuple[FileRecord, ...]:
        """读取并校验一个已发布数据版本的全部原始文件。"""

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT relative_path, media_type, content, content_sha256
                FROM energy_dataset_file
                WHERE version_id = %s ORDER BY relative_path
                """,
                (version_id,),
            )
            records = tuple(
                FileRecord(str(row[0]), str(row[1]), bytes(row[2]), str(row[3]))
                for row in cursor.fetchall()
            )
        if not records:
            raise ValueError(f"数据版本没有文件：{version_id}")
        return records

    def load_version_files_by_paths(self, version_id: UUID, storage_paths: Sequence[str]) -> tuple[FileRecord, ...]:
        """只读取指定相对路径的版本文件；缺文件时返回空，方便按单表编辑。"""

        paths = tuple(dict.fromkeys(str(path) for path in storage_paths if str(path).strip()))
        if not paths:
            return ()
        marks = ", ".join(["%s"] * len(paths))
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT relative_path, media_type, content, content_sha256
                FROM energy_dataset_file
                WHERE version_id = %s AND relative_path IN ({marks})
                ORDER BY relative_path
                """,
                (version_id, *paths),
            )
            return tuple(
                FileRecord(str(row[0]), str(row[1]), bytes(row[2]), str(row[3]))
                for row in cursor.fetchall()
            )

    def load_version_files_like(self, version_id: UUID, pattern: str) -> tuple[FileRecord, ...]:
        """按相对路径前缀读取版本文件，供运行图这类文件名不固定的表使用。"""

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT relative_path, media_type, content, content_sha256
                FROM energy_dataset_file
                WHERE version_id = %s AND relative_path LIKE %s
                ORDER BY relative_path
                """,
                (version_id, pattern),
            )
            return tuple(
                FileRecord(str(row[0]), str(row[1]), bytes(row[2]), str(row[3]))
                for row in cursor.fetchall()
            )

    def load_storage_device_parameters(self, version_id: UUID) -> tuple[dict[str, Any], ...]:
        """读取实体设备额定参数；空清单由绑定阶段结合版本设施类型校验。"""

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT storage_code, capacity_kwh, max_charge_power_kw,
                       max_discharge_power_kw, charge_efficiency,
                       discharge_efficiency, initial_soc_kwh, min_soc_kwh,
                       max_soc_kwh, available, data_status, source_note
                FROM energy_storage_device
                WHERE version_id = %s
                ORDER BY storage_code
                """,
                (version_id,),
            )
            rows = cursor.fetchall()
        return tuple(
            {
                "storage_section_id": str(row[0]),
                "capacity_kwh": float(row[1]),
                "max_charge_power_kw": float(row[2]),
                "max_discharge_power_kw": float(row[3]),
                "charge_efficiency": float(row[4]),
                "discharge_efficiency": float(row[5]),
                "initial_soc_kwh": float(row[6]),
                "min_soc_kwh": float(row[7]),
                "max_soc_kwh": float(row[8]),
                "available": bool(row[9]),
                "data_status": str(row[10]),
                "source_note": "" if row[11] is None else str(row[11]),
            }
            for row in rows
        )

    def freeze_run_snapshot(
        self,
        run_id: UUID,
        version_id: UUID,
        manifest: Mapping[str, Any],
        *,
        worker_id: str,
        lease_token: UUID,
    ) -> UUID:
        """由当前租约持有者幂等固化输入，并原子进入运行状态。"""

        snapshot_id = uuid5(run_id, "input-snapshot")
        input_hash = str(manifest["snapshot_sha256"])
        with transaction(self.connection):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, worker_id, lease_token,
                           lease_expires_at > UTC_TIMESTAMP(), version_id,
                           input_sha256, state_version
                    FROM energy_run
                    WHERE run_id = %s FOR UPDATE
                    """,
                    (run_id,),
                )
                run_row = cursor.fetchone()
                if run_row is None:
                    raise ValueError(f"任务不存在：{run_id}")
                status = str(run_row[0])
                if (
                    status not in {"validating", "running"}
                    or str(run_row[1]) != str(worker_id)
                    or str(run_row[2]) != str(lease_token)
                    or not bool(run_row[3])
                ):
                    raise RunLeaseLostError(f"任务租约已失效：{run_id}")
                if UUID(str(run_row[4])) != version_id:
                    raise RunStateConflictError("任务版本与输入快照版本不一致。")
                cursor.execute(
                    """
                    SELECT version_id, input_sha256
                    FROM energy_run_input_snapshot
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                snapshot_row = cursor.fetchone()
                if snapshot_row is None:
                    cursor.execute(
                        """
                        INSERT INTO energy_run_input_snapshot
                            (snapshot_id, run_id, version_id, input_sha256, manifest_json)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (snapshot_id, run_id, version_id, input_hash, _json(manifest)),
                    )
                elif (
                    UUID(str(snapshot_row[0])) != version_id
                    or str(snapshot_row[1]) != input_hash
                ):
                    raise RunStateConflictError(
                        "任务已存在内容不同的冻结输入快照。"
                    )
                if run_row[5] not in (None, input_hash):
                    raise RunStateConflictError("任务input_sha256与冻结快照不一致。")
                if status == "validating":
                    state_version = int(run_row[6]) + 1
                    cursor.execute(
                        """
                        UPDATE energy_run
                        SET status = 'running', input_sha256 = %s,
                            state_version = %s, updated_at = UTC_TIMESTAMP()
                        WHERE run_id = %s AND status = 'validating'
                          AND worker_id = %s AND lease_token = %s
                        """,
                        (input_hash, state_version, run_id, worker_id, lease_token),
                    )
                    if cursor.rowcount != 1:
                        raise RunLeaseLostError(f"任务租约已失效：{run_id}")
                    self._insert_run_state_event(
                        cursor,
                        run_id=run_id,
                        state_version=state_version,
                        from_status="validating",
                        to_status="running",
                        worker_id=worker_id,
                        lease_token=lease_token,
                        reason="input_snapshot_frozen",
                        details={"input_sha256": input_hash},
                    )
        return snapshot_id

    def persist_result(
        self,
        run_id: UUID,
        output_dir: Path,
        *,
        worker_id: str,
        lease_token: UUID,
        settlement_step_s: int = 10,
    ) -> dict:
        """幂等替换一次运行的结果明细，并在同一事务中标记成功。"""

        projection = project_result_directory(run_id, output_dir, settlement_step_s)
        result_manifest = snapshot_manifest(projection["artifacts"])
        with transaction(self.connection):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, result_sha256, worker_id, lease_token,
                           IFNULL(lease_expires_at > UTC_TIMESTAMP(), 0), state_version
                    FROM energy_run
                    WHERE run_id = %s FOR UPDATE
                    """,
                    (run_id,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise ValueError(f"任务不存在：{run_id}")
                if str(existing[0]) == "succeeded":
                    if str(existing[1]) == result_manifest["snapshot_sha256"]:
                        return {
                            **result_manifest,
                            "already_present": True,
                            "projection_counts": {
                                key: len(value)
                                for key, value in projection.items()
                                if isinstance(value, (list, tuple))
                            },
                        }
                    raise RunStateConflictError(f"成功任务不能被不同结果覆盖：{run_id}")
                if (
                    str(existing[0]) not in {"validating", "running"}
                    or str(existing[2]) != str(worker_id)
                    or str(existing[3]) != str(lease_token)
                    or not bool(existing[4])
                ):
                    raise RunLeaseLostError(f"任务租约已失效：{run_id}")
                self._delete_run_results(cursor, run_id)
                self._insert_result_projection(cursor, run_id, projection)
                state_version = int(existing[5]) + 1
                cursor.execute(
                    """
                    UPDATE energy_run
                    SET status = 'succeeded', result_sha256 = %s,
                        lease_token = NULL, lease_expires_at = NULL,
                        heartbeat_at = NULL, state_version = %s,
                        finished_at = UTC_TIMESTAMP(), updated_at = UTC_TIMESTAMP(), error_message = NULL
                    WHERE run_id = %s AND status IN ('running', 'validating')
                      AND worker_id = %s AND lease_token = %s
                    """,
                    (
                        result_manifest["snapshot_sha256"], state_version,
                        run_id, worker_id, lease_token,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RunLeaseLostError(f"任务租约已失效：{run_id}")
                self._insert_run_state_event(
                    cursor,
                    run_id=run_id,
                    state_version=state_version,
                    from_status=str(existing[0]),
                    to_status="succeeded",
                    worker_id=worker_id,
                    lease_token=lease_token,
                    reason="result_committed",
                    details={
                        "result_sha256": result_manifest["snapshot_sha256"],
                    },
                )
        return {**result_manifest, "already_present": False, "projection_counts": {
            key: len(value) for key, value in projection.items() if isinstance(value, (list, tuple))
        }}

    @staticmethod
    def _delete_run_results(cursor, run_id: UUID) -> None:
        cursor.execute("DELETE FROM energy_storage_plan_decision WHERE run_id = %s", (run_id,))
        cursor.execute("DELETE FROM energy_storage_plan WHERE run_id = %s", (run_id,))
        for table in (
            "energy_rolling_control_event", "energy_optimization_decision", "energy_result_kpi", "energy_scenario_result",
            "energy_optimization_suggestion", "energy_audit_issue", "energy_resource_conflict",
            "energy_power_arm_settlement", "energy_time_slice", "energy_timetable_running_arc",
            "energy_timetable_audit_summary", "energy_result_artifact",
        ):
            cursor.execute(f"DELETE FROM {table} WHERE run_id = %s", (run_id,))
        cursor.execute(
            """
            DELETE FROM energy_candidate_train_adjustment
            WHERE candidate_id IN (
                SELECT candidate_id
                FROM energy_optimization_candidate
                WHERE run_id = %s
            )
            """,
            (run_id,),
        )
        cursor.execute(
            "DELETE FROM energy_optimization_candidate WHERE run_id = %s",
            (run_id,),
        )

    @staticmethod
    def _insert_result_projection(cursor, run_id: UUID, projection: Mapping[str, Any]) -> None:
        from .planning import insert_planning_results
        insert_planning_results(cursor, run_id, projection)
        artifacts = ({
            "run_id": run_id, "relative_path": item.relative_path,
            "artifact_type": Path(item.relative_path).suffix.lstrip(".") or "binary",
            "media_type": item.media_type, "content": item.content,
            "content_size_bytes": item.content_size_bytes, "content_sha256": item.content_sha256,
        } for item in projection["artifacts"])
        _insert_many(cursor, "energy_result_artifact", ("run_id", "relative_path", "artifact_type", "media_type", "content", "content_size_bytes", "content_sha256"), artifacts)

        candidate_columns = ("candidate_id", "run_id", "source_candidate_code", "candidate_set", "rank", "feasible", "pareto", "energy_scenario", "storage_preset_id", "objective_priority", "objective_1", "objective_2", "objective_3", "constraint_violation", "total_cost", "grid_kwh", "wasted_kwh", "recovered_energy_kwh", "final_soc_kwh", "resource_conflict_count", "parameters_json", "metrics_json")
        candidate_rows = []
        for source in projection["candidates"]:
            row = dict(source); row["run_id"] = run_id
            row["parameters_json"] = row.pop("parameters"); row["metrics_json"] = row.pop("metrics")
            candidate_rows.append(row)
        _insert_many(cursor, "energy_optimization_candidate", candidate_columns, candidate_rows, json_columns=("parameters_json", "metrics_json"))

        adjustment_columns = ("candidate_id", "train_id", "train_type", "sequence_no", "adjustment_s")
        _insert_many(cursor, "energy_candidate_train_adjustment", adjustment_columns, projection["candidate_adjustments"])

        kpi_columns = ("run_id", "case_name", "feasible", "total_gen_kwh", "total_con_kwh", "accepted_by_power_arm_kwh", "recovered_energy_kwh", "recovery_rate", "direct_used_kwh", "battery_charge_kwh", "battery_discharge_kwh", "wasted_kwh", "grid_kwh", "effective_regen_loss_kwh", "final_soc_kwh", "constraint_violation", "resource_conflict_count", "total_cost", "metrics_json")
        kpi_rows = []
        for source in projection["kpis"]:
            row = dict(source); row["run_id"] = run_id; row["metrics_json"] = row.pop("metrics")
            kpi_rows.append(row)
        _insert_many(cursor, "energy_result_kpi", kpi_columns, kpi_rows, json_columns=("metrics_json",))

        slice_columns = (
            "run_id", "case_name", "slice_start_s", "slice_end_s",
            "power_arm_code", "storage_code", "traction_kwh", "regen_kwh",
            "accepted_by_power_arm_kwh", "direct_used_kwh", "battery_charge_kwh",
            "battery_discharge_kwh", "wasted_kwh", "grid_kwh",
            "soc_before_kwh", "soc_after_kwh", "constraint_violation_kwh",
            "details_json",
        )
        slice_rows = []
        for source in projection["energy_slices"]:
            row = dict(source); row["run_id"] = run_id; row["details_json"] = row.pop("details")
            slice_rows.append(row)
        _insert_many(cursor, "energy_time_slice", slice_columns, slice_rows, json_columns=("details_json",))

        arc_columns = ("run_id", "source_arc_id", "train_id", "train_type", "direction", "from_station_code", "to_station_code", "arc_type", "start_time_s", "end_time_s", "start_km", "end_km", "traction_energy_kwh", "regen_energy_kwh", "power_arm_code", "storage_code", "details_json")
        arc_rows = []
        for source in projection["running_arcs"]:
            row = dict(source); row["run_id"] = run_id; row["details_json"] = row.pop("details")
            arc_rows.append(row)
        _insert_many(cursor, "energy_timetable_running_arc", arc_columns, arc_rows, json_columns=("details_json",))

        conflict_columns = ("run_id", "case_name", "conflict_type", "severity", "resource_code", "resource_name", "train_a", "train_b", "overlap_start_s", "overlap_end_s", "overlap_duration_s", "location_km", "message", "suggestion")
        conflict_rows = [dict(source, run_id=run_id) for source in projection["resource_conflicts"]]
        _insert_many(cursor, "energy_resource_conflict", conflict_columns, conflict_rows)

        scenario_columns = ("run_id", "candidate_id", "scenario_name", "core_for_feasibility", "feasible", "blocking", "constraint_violation", "resource_conflict_count", "total_cost", "grid_kwh", "wasted_kwh", "battery_charge_kwh", "battery_discharge_kwh", "final_soc_deviation_kwh", "conflict_summary", "details_json")
        scenario_rows = []
        for source in projection["scenario_results"]:
            row = dict(source); row["run_id"] = run_id; row["details_json"] = row.pop("details")
            scenario_rows.append(row)
        _insert_many(cursor, "energy_scenario_result", scenario_columns, scenario_rows, json_columns=("details_json",))

        settlement_columns = ("run_id", "power_arm_code", "window_start_s", "window_end_s", "traction_demand_kwh", "regen_input_kwh", "accepted_kwh", "charge_kwh", "discharge_kwh", "wasted_kwh", "grid_kwh", "max_traction_supply_kw", "max_regen_absorption_kw", "electrical_constraint_violation_kwh")
        settlement_rows = [dict(source, run_id=run_id) for source in projection["power_arm_settlements"]]
        _insert_many(cursor, "energy_power_arm_settlement", settlement_columns, settlement_rows)

        issue_columns = ("issue_id", "run_id", "issue_type", "severity", "power_arm_code", "start_time_s", "end_time_s", "impact_kwh", "reason", "details_json")
        issue_rows = []
        for source in projection["audit_issues"]:
            row = dict(source); row.pop("source_issue_code", None); row["run_id"] = run_id
            row["details_json"] = row.pop("details")
            issue_rows.append(row)
        _insert_many(cursor, "energy_audit_issue", issue_columns, issue_rows, json_columns=("details_json",))

        suggestion_columns = ("suggestion_id", "run_id", "source_issue_id", "suggestion_type", "reason")
        suggestion_rows = [dict(source, run_id=run_id) for source in projection["optimization_suggestions"]]
        _insert_many(cursor, "energy_optimization_suggestion", suggestion_columns, suggestion_rows)

        rolling_event_columns = (
            "event_id", "run_id", "cycle_index", "current_time_s",
            "commit_status", "safety_state", "safety_action",
            "core_robust_feasible", "operational_intervention_required",
            "attempt_count", "request_fingerprint", "event_json",
        )
        rolling_event_rows = []
        for source in projection.get("rolling_control_events", []):
            row = dict(source)
            row["run_id"] = run_id
            row["event_json"] = row.pop("event")
            rolling_event_rows.append(row)
        _insert_many(
            cursor,
            "energy_rolling_control_event",
            rolling_event_columns,
            rolling_event_rows,
            json_columns=("event_json",),
        )

        summary = projection.get("summary", {})
        baseline = summary.get("baseline", {}) if isinstance(summary, dict) else {}
        optimized = summary.get("optimized", {}) if isinstance(summary, dict) else {}
        cursor.execute(
            """
            INSERT INTO energy_timetable_audit_summary
                (run_id, valid, train_count, running_arc_count, time_slice_count,
                 settlement_window_count, energy_event_count, issue_count, suggestion_count,
                 baseline_total_gen_kwh, baseline_wasted_kwh, baseline_grid_kwh, summary_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id, bool(summary.get("valid", True)),
                int(summary.get("train_count", int(optimized.get("heavy_count", 0)) + int(optimized.get("empty_count", 0)))),
                int(summary.get("running_arc_count", optimized.get("time_space_arc_count", 0))),
                int(summary.get("time_slice_count", len(projection["energy_slices"]))),
                int(summary.get("settlement_window_count", len(projection["power_arm_settlements"]))),
                int(summary.get("energy_event_count", 0)),
                int(summary.get("issue_count", len(projection["audit_issues"]))),
                int(summary.get("suggestion_count", len(projection["optimization_suggestions"]))),
                baseline.get("total_gen_kwh"), baseline.get("wasted_kwh"), baseline.get("grid_kwh"), _json(summary),
            ),
        )
        if projection.get("storage_plan_decision"):
            return
        decision = dict(projection["decision"])
        selected_code = str(decision.get("selected_candidate_id") or "")
        selected_id = uuid5(run_id, f"candidate:{selected_code}") if selected_code else None
        if selected_id is not None and not any(item["candidate_id"] == selected_id for item in projection["candidates"]):
            selected_id = None
        cursor.execute(
            """
            INSERT INTO energy_optimization_decision
                (run_id, action, selected_candidate_id, reason, baseline_effective_regen_loss_kwh,
                 baseline_grid_kwh, effective_regen_loss_improvement_kwh, grid_improvement_kwh, decision_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id, decision["action"], selected_id, decision.get("reason", "unspecified"),
                decision.get("baseline_effective_regen_loss_kwh"), decision.get("baseline_grid_kwh"),
                decision.get("effective_regen_loss_improvement_kwh"), decision.get("grid_improvement_kwh"), _json(decision),
            ),
        )

    def mark_failed(
        self,
        run_id: UUID,
        message: str,
        *,
        worker_id: str,
        lease_token: UUID,
    ) -> None:
        """仅由当前租约持有者原子标记失败，禁止旧工作进程覆盖状态。"""

        with transaction(self.connection):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, state_version, lease_expires_at > UTC_TIMESTAMP()
                    FROM energy_run
                    WHERE run_id = %s AND worker_id = %s AND lease_token = %s
                    FOR UPDATE
                    """,
                    (run_id, worker_id, lease_token),
                )
                row = cursor.fetchone()
                if (
                    row is None
                    or str(row[0]) not in {"validating", "running"}
                    or not bool(row[2])
                ):
                    raise RunLeaseLostError(f"任务租约已失效：{run_id}")
                state_version = int(row[1]) + 1
                cursor.execute(
                    """
                    UPDATE energy_run
                    SET status = 'failed', error_count = error_count + 1,
                        error_message = %s, lease_token = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL,
                        state_version = %s, finished_at = UTC_TIMESTAMP(), updated_at = UTC_TIMESTAMP()
                    WHERE run_id = %s AND worker_id = %s AND lease_token = %s
                    """,
                    (
                        str(message)[:8000], state_version,
                        run_id, worker_id, lease_token,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RunLeaseLostError(f"任务租约已失效：{run_id}")
                self._insert_run_state_event(
                    cursor,
                    run_id=run_id,
                    state_version=state_version,
                    from_status=str(row[0]),
                    to_status="failed",
                    worker_id=worker_id,
                    lease_token=lease_token,
                    reason="worker_failed",
                    details={"message": str(message)[:8000]},
                )
