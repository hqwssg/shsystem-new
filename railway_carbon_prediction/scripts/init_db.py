import _bootstrap  # noqa: F401
from carbon_prediction.config import settings
from carbon_prediction.db import execute_script, healthcheck

if __name__ == "__main__":
    execute_script(str(settings.sql_dir / "001_schema.sql"))
    execute_script(str(settings.sql_dir / "002_seed.sql"))
    print("数据库初始化完成:", healthcheck())
