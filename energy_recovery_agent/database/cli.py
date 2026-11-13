"""数据库迁移、数据导入、任务创建和工作进程命令行入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID
import argparse
import json
import os
import socket
import sys

from .mysql import SimulationRepository, apply_migrations, connect_mysql, transaction
from .parameters import validate_run_parameters
from .snapshots import materialize_file_records


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _extra_files(values: list[str]) -> dict[str, Path]:
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--extra-file 必须使用 logical/path=local/path 格式。")
        logical, local = value.split("=", 1)
        result[logical] = Path(local)
    return result


def _load_parameters(args: argparse.Namespace) -> dict:
    if args.parameters_json:
        value = json.loads(args.parameters_json)
    else:
        value = json.loads(Path(args.parameters_file).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("任务参数必须是JSON对象。")
    return value


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """MySQL 库由总系统维护，这里只确认可连接。"""

    connection = connect_mysql(args.database_url or os.environ.get("ENERGY_DATABASE_URL"))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE()")
            _print({"database": cursor.fetchone()[0], "engine": "mysql"})
    finally:
        connection.close()
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    connection = connect_mysql(args.database_url)
    try:
        _print({"applied_versions": apply_migrations(connection)})
    finally:
        connection.close()
    return 0


def cmd_apply_security(args: argparse.Namespace) -> int:
    """MySQL 接入不再创建 PostgreSQL 四类角色。"""

    _print({"applied": False, "engine": "mysql", "message": "沿用 carbon_emissions 现有账号"})
    return 0


def cmd_excel_templates(args: argparse.Namespace) -> int:
    from .user_excel import catalog, write_templates

    if args.catalog:
        _print(catalog())
        return 0
    written = write_templates(args.output_dir)
    _print({"output_dir": str(args.output_dir or "data_templates/user_excel"), "files": [str(path.name) for path in written]})
    return 0


def cmd_version_tables(args: argparse.Namespace) -> int:
    from .user_excel import ExcelConversionError, export_version_tables, load_sheet_records

    topic = str(args.topic or "").strip()
    sheet = str(args.sheet or "").strip()
    # A damaged HTTP/Java argument can arrive as question marks or the Unicode
    # replacement character.  Treat it as an omitted sheet so the topic-level
    # export remains usable instead of failing before the real data is read.
    if sheet and ("?" in sheet or "\ufffd" in sheet):
        sheet = ""
    sheet = {
        "geometry|route": "线路参数",
        "geometry|stations": "车站",
        "geometry|segments": "区间",
        "trains|train": "列车",
        "storage|parameters": "储能参数",
        "storage|zones": "储能区段",
        "timetable|trains": "列车",
        "timetable|timetable": "时刻表",
        "timetable|metadata": "元数据",
        "operations|headway": "追踪间隔",
        "operations|technical": "技术作业时分",
        "operations|assignments": "作业适用范围",
        "power_arm|intervals": "供电臂",
        "disturbance|replay": "回放说明",
        "disturbance|periods": "周期",
        "disturbance|events": "事件",
        "joint_params|ranges": "参数区间",
        "joint_params|samples": "抽样",
    }.get(f"{topic}|{sheet}", sheet)
    if sheet and not topic:
        raise ExcelConversionError("指定工作表时必须指定主题")
    connection = connect_mysql(args.database_url)
    try:
        repository = SimulationRepository(connection)
        _project_id, version_id = repository.resolve_version(args.project_code, args.version_code)
        if sheet:
            records = load_sheet_records(repository, version_id, topic, sheet)
        else:
            records = repository.load_version_files(version_id)
        payload = export_version_tables(records, topic or None, sheet or None)
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
    finally:
        connection.close()
    return 0


def cmd_planning_preset(args):
    from .planning import planning_preset
    connection = connect_mysql(args.database_url)
    try:
        repository = SimulationRepository(connection)
        _, version_id = repository.resolve_version(args.project_code, args.version_code)
        _print(planning_preset(repository.load_version_files(version_id)))
    finally:
        connection.close()
    return 0


def cmd_replace_version_tables(args: argparse.Namespace) -> int:
    from .user_excel import replace_version_topic

    payload = json.loads(Path(args.tables_file).read_text(encoding="utf-8"))
    sheets = payload.get("sheets") if isinstance(payload, dict) else payload
    if not isinstance(sheets, list):
        raise ValueError("tables 文件必须包含 sheets 数组")
    connection = connect_mysql(args.database_url)
    try:
        repository = SimulationRepository(connection)
        _print(replace_version_topic(
            repository,
            project_code=args.project_code,
            version_code=args.version_code,
            topic=args.topic,
            sheets=sheets,
            source_note=args.source_note or "",
        ))
    finally:
        connection.close()
    return 0


def cmd_import_excel(args: argparse.Namespace) -> int:
    from .user_excel import ExcelConversionError, import_excel_dataset

    excel_paths = list(args.excel_file)
    if args.excel_dir:
        excel_paths.extend(sorted(path for path in Path(args.excel_dir).glob("*.xlsx") if path.is_file()))
    connection = connect_mysql(args.database_url)
    try:
        result = import_excel_dataset(
            SimulationRepository(connection),
            excel_paths,
            base_project_code=args.base_project_code,
            base_version_code=args.base_version_code,
            project_code=args.project_code,
            project_name=args.project_name,
            route_name=args.route_name,
            version_code=args.version_code,
            data_status=args.data_status,
            source_note=args.source_note,
        )
        _print(result)
    except ExcelConversionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        connection.close()
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    connection = connect_mysql(args.database_url)
    try:
        repository = SimulationRepository(connection)
        result = repository.import_dataset(
            args.source_dir,
            project_code=args.project_code,
            project_name=args.project_name,
            route_name=args.route_name,
            version_code=args.version_code,
            data_status=args.data_status,
            source_note=args.source_note,
            extra_files=_extra_files(args.extra_file),
        )
        _print(result)
    finally:
        connection.close()
    return 0


def cmd_create_run(args: argparse.Namespace) -> int:
    parameters = _load_parameters(args)
    validate_run_parameters(args.run_type, parameters)
    connection = connect_mysql(args.database_url)
    try:
        repository = SimulationRepository(connection)
        project_id, version_id = repository.resolve_version(args.project_code, args.version_code)
        run_id = repository.create_run(
            project_id=project_id,
            version_id=version_id,
            run_type=args.run_type,
            parameters=parameters,
            requested_by=args.requested_by,
            code_version=args.code_version,
            idempotency_key=args.idempotency_key,
        )
        _print({"run_id": run_id, "status": "pending"})
    finally:
        connection.close()
    return 0


def cmd_worker_once(args: argparse.Namespace) -> int:
    # 领取任务时才加载完整算法适配器。
    from .worker import run_one_pending, run_pending_run

    connection = connect_mysql(args.database_url)
    try:
        repository = SimulationRepository(connection)
        worker_id = args.worker_id or f"{socket.gethostname()}-{os.getpid()}"
        if args.run_id:
            result = run_pending_run(
                repository,
                worker_id,
                UUID(args.run_id),
                lease_seconds=args.lease_seconds,
                heartbeat_interval_s=args.heartbeat_interval_seconds,
                resource_profile=args.resource_profile,
            )
        else:
            result = run_one_pending(
                repository,
                worker_id,
                lease_seconds=args.lease_seconds,
                heartbeat_interval_s=args.heartbeat_interval_seconds,
                resource_profile=args.resource_profile,
            )
        _print(result or {"status": "idle", "message": "没有待执行任务"})
    finally:
        connection.close()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    connection = connect_mysql(args.database_url)
    try:
        repository = SimulationRepository(connection)
        run_id = UUID(args.run_id)
        result = repository.get_run(run_id)
        if args.include_events:
            result["state_events"] = repository.load_run_state_events(run_id)
        _print(result)
    finally:
        connection.close()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    connection = connect_mysql(args.database_url)
    try:
        records = SimulationRepository(connection).load_result_artifacts(UUID(args.run_id))
        if not records:
            raise ValueError("任务没有可导出的结果工件。")
        _print(materialize_file_records(records, args.output_dir))
    finally:
        connection.close()
    return 0


def cmd_recover_expired(args: argparse.Namespace) -> int:
    """回收租约过期任务，并限制最大执行尝试次数。"""

    connection = connect_mysql(args.database_url)
    try:
        _print(
            SimulationRepository(connection).requeue_expired_runs(
                max_attempts=args.max_attempts
            )
        )
    finally:
        connection.close()
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    """取消尚未进入终态的任务。"""

    connection = connect_mysql(args.database_url)
    try:
        cancelled = SimulationRepository(connection).cancel_run(
            UUID(args.run_id), args.reason
        )
        _print({"run_id": args.run_id, "cancelled": cancelled})
    finally:
        connection.close()
    return 0


def cmd_delete_run(args: argparse.Namespace) -> int:
    """删除任意状态的任务及其结果。"""

    connection = connect_mysql(args.database_url)
    try:
        deleted = SimulationRepository(connection).delete_run(UUID(args.run_id))
        _print({"run_id": args.run_id, "deleted": deleted})
    finally:
        connection.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="carbon_emissions数据库集成管理工具。")
    parser.add_argument("--database-url", default=None, help="覆盖 ENERGY_DATABASE_URL。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap", help="创建carbon_emissions数据库。")
    bootstrap.add_argument("--admin-url", required=True, help="未使用：库已存在于 MySQL carbon_emissions。")
    bootstrap.set_defaults(func=cmd_bootstrap)

    migrate = subparsers.add_parser("migrate", help="执行版本化Schema迁移。")
    migrate.set_defaults(func=cmd_migrate)

    security = subparsers.add_parser("apply-security", help="创建四类角色并应用最小权限授权。")
    security.set_defaults(func=cmd_apply_security)

    import_data = subparsers.add_parser("import-data", help="导入不可变数据版本。")
    import_data.add_argument("--source-dir", type=Path, required=True)
    import_data.add_argument("--project-code", required=True)
    import_data.add_argument("--project-name", required=True)
    import_data.add_argument("--route-name", required=True)
    import_data.add_argument("--version-code", required=True)
    import_data.add_argument("--data-status", choices=("official", "derived_from_official", "planning_placeholder", "synthetic"), default="planning_placeholder")
    import_data.add_argument("--source-note", default="")
    import_data.add_argument("--extra-file", action="append", default=[])
    import_data.set_defaults(func=cmd_import)

    excel_templates = subparsers.add_parser("excel-templates", help="生成或列出用户中文 Excel 模板。")
    excel_templates.add_argument("--output-dir", type=Path, default=None)
    excel_templates.add_argument("--catalog", action="store_true")
    excel_templates.set_defaults(func=cmd_excel_templates)

    import_excel = subparsers.add_parser("import-excel", help="按主题 Excel 叠在已有版本上发布新版本。")
    import_excel.add_argument("--excel-dir", type=Path)
    import_excel.add_argument("--excel-file", action="append", type=Path, default=[])
    import_excel.add_argument("--base-project-code", required=True)
    import_excel.add_argument("--base-version-code", required=True)
    import_excel.add_argument("--project-code", required=True)
    import_excel.add_argument("--project-name", required=True)
    import_excel.add_argument("--route-name", required=True)
    import_excel.add_argument("--version-code", required=True)
    import_excel.add_argument("--data-status", choices=("official", "derived_from_official", "planning_placeholder", "synthetic"), default="planning_placeholder")
    import_excel.add_argument("--source-note", default="")
    import_excel.set_defaults(func=cmd_import_excel)

    version_tables = subparsers.add_parser("version-tables", help="把已发布版本反解成中文表格。")
    version_tables.add_argument("--project-code", required=True)
    version_tables.add_argument("--version-code", required=True)
    version_tables.add_argument("--topic", default="")
    version_tables.add_argument("--sheet", default="")
    version_tables.set_defaults(func=cmd_version_tables)

    replace_tables = subparsers.add_parser("replace-version-tables", help="用中文表格覆盖当前版本的一个主题。")
    replace_tables.add_argument("--project-code", required=True)
    replace_tables.add_argument("--version-code", required=True)
    replace_tables.add_argument("--topic", required=True)
    replace_tables.add_argument("--tables-file", type=Path, required=True)
    replace_tables.add_argument("--source-note", default="")
    replace_tables.set_defaults(func=cmd_replace_version_tables)

    preset = subparsers.add_parser("planning-preset", help="Validate version planning data and return available codes.")
    preset.add_argument("--project-code", required=True)
    preset.add_argument("--version-code", required=True)
    preset.set_defaults(func=cmd_planning_preset)

    create_run = subparsers.add_parser("create-run", help="创建平台算法任务。")
    create_run.add_argument("--project-code", required=True)
    create_run.add_argument("--version-code", required=True)
    create_run.add_argument(
        "--run-type",
        choices=(
            "dispatch",
            "timetable_audit",
            "timetable_optimization",
            "rolling_rescheduling",
            "joint_parameter_robustness",
            "storage_planning",
        ),
        required=True,
    )
    parameters = create_run.add_mutually_exclusive_group(required=True)
    parameters.add_argument("--parameters-json")
    parameters.add_argument("--parameters-file", type=Path)
    create_run.add_argument("--requested-by", default="platform")
    create_run.add_argument("--code-version", default="2026.10.10.1-mysql-six-tasks")
    create_run.add_argument(
        "--idempotency-key",
        required=True,
        help="平台生成的项目内唯一请求键；相同键和内容重复提交将返回同一run_id。",
    )
    create_run.set_defaults(func=cmd_create_run)

    worker = subparsers.add_parser("worker-once", help="领取并执行一个待处理任务。")
    worker.add_argument("--run-id", help="只领取并执行指定任务；省略则领取队列中最早的一条。")
    worker.add_argument("--worker-id")
    worker.add_argument("--lease-seconds", type=int, default=300)
    worker.add_argument("--heartbeat-interval-seconds", type=int, default=60)
    worker.add_argument(
        "--resource-profile",
        choices=("quick", "standard", "fine"),
        default=os.environ.get("SIMULATION_WORKER_RESOURCE_PROFILE", "standard"),
        help="求解墙钟预算档位，默认standard。",
    )
    worker.set_defaults(func=cmd_worker_once)

    status = subparsers.add_parser("status", help="查询一个任务状态。")
    status.add_argument("--run-id", required=True)
    status.add_argument("--include-events", action="store_true")
    status.set_defaults(func=cmd_status)

    export = subparsers.add_parser("export-result", help="将数据库结果工件还原到目录。")
    export.add_argument("--run-id", required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    export.set_defaults(func=cmd_export)

    recover = subparsers.add_parser("recover-expired", help="回收租约已过期的任务。")
    recover.add_argument("--max-attempts", type=int, default=3)
    recover.set_defaults(func=cmd_recover_expired)

    cancel = subparsers.add_parser("cancel-run", help="取消一个非终态任务。")
    cancel.add_argument("--run-id", required=True)
    cancel.add_argument("--reason", default="cancelled_by_platform")
    cancel.set_defaults(func=cmd_cancel)

    delete_run = subparsers.add_parser("delete-run", help="删除一个任务及其结果。")
    delete_run.add_argument("--run-id", required=True)
    delete_run.set_defaults(func=cmd_delete_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
