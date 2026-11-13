"""把朔黄演示线路版本导入已部署的重空协调库，并可绑定登录部门。"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

PROJECT_CODE = "shuohuang_demo"
PROJECT_NAME = "朔黄演示"
ROUTE_NAME = "shuohuang"
VERSION_CODE = "v1"
DATA_STATUS = "planning_placeholder"
SOURCE_NOTE = "朔黄重空协调规划占位数据；含实验性电表能量标定样本"


def _materialize_algorithm_names(data_dir: Path, destination: Path) -> Path:
    """库里存的是中文路径，导入投影读取英文文件名。"""

    from database.file_names import to_algorithm_path

    for path in sorted(item for item in data_dir.rglob("*") if item.is_file()):
        relative = path.relative_to(data_dir).as_posix()
        target = destination.joinpath(*to_algorithm_path(relative).split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="导入朔黄演示 v1，并可把项目绑到登录部门。")
    parser.add_argument("--project-root", required=True, type=Path, help="已部署的 energy_recovery_agent 目录")
    parser.add_argument("--database-url", default=None, help="覆盖环境变量 ENERGY_DATABASE_URL，不要写进文件")
    parser.add_argument("--dept-id", action="append", type=int, default=[], help="要绑定的登录部门编号，可重复")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not (project_root / "database" / "mysql.py").is_file():
        print(f"找不到能量项目：{project_root}", file=sys.stderr)
        return 1
    data_dir = Path(__file__).resolve().parent / "data"
    data_files = sorted(item for item in data_dir.rglob("*") if item.is_file())
    if not data_dir.is_dir() or len(data_files) != 28:
        print(f"数据目录不存在或文件不完整：{data_dir}（需要28个数据文件，实际{len(data_files)}个）", file=sys.stderr)
        return 1
    for dept_id in args.dept_id:
        if dept_id <= 0:
            print(f"部门编号必须是正整数：{dept_id}", file=sys.stderr)
            return 1

    if args.database_url:
        os.environ["ENERGY_DATABASE_URL"] = args.database_url
    sys.path.insert(0, str(project_root))
    from database.mysql import SimulationRepository, connect_mysql, transaction

    connection = connect_mysql()
    try:
        with tempfile.TemporaryDirectory(prefix="energy_init_") as temp_name:
            algorithm_dir = _materialize_algorithm_names(data_dir, Path(temp_name))
            result = SimulationRepository(connection).import_dataset(
                algorithm_dir,
                project_code=PROJECT_CODE,
                project_name=PROJECT_NAME,
                route_name=ROUTE_NAME,
                version_code=VERSION_CODE,
                data_status=DATA_STATUS,
                source_note=SOURCE_NOTE,
            )
        if args.dept_id:
            with transaction(connection):
                with connection.cursor() as cursor:
                    for dept_id in args.dept_id:
                        cursor.execute(
                            """
                            INSERT INTO energy_dept_project
                                (dept_id, project_code, enabled, create_by, create_time)
                            VALUES (%s, %s, '1', 'init', NOW())
                            ON DUPLICATE KEY UPDATE
                                enabled = '1',
                                update_by = 'init',
                                update_time = NOW()
                            """,
                            (dept_id, PROJECT_CODE),
                        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        connection.close()

    state = "已存在，未覆盖" if result.get("already_present") else "已导入"
    print(f"{PROJECT_NAME} / {VERSION_CODE}：{state}，文件 {result.get('file_count')} 个。")
    if args.dept_id:
        print("已绑定部门：" + "、".join(str(item) for item in args.dept_id))
    else:
        print("未绑定部门。管理员可以直接看到该版本；其他账号需要再执行并传入 --dept-id。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
