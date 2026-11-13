"""全局配置。

所有配置均可通过环境变量覆盖，便于在大平台容器/配置中心中注入。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
EXTERNAL_DIR = DATA_DIR / "external"
ARTIFACT_DIR = Path(os.getenv("PREDICTION_ARTIFACT_DIR", str(BASE_DIR / "artifacts")))
MODEL_DIR = ARTIFACT_DIR / "models"
REPORT_DIR = ARTIFACT_DIR / "reports"
SQL_DIR = BASE_DIR / "sql"


def _load_dotenv(path: Path) -> None:
    """极简 .env 解析，避免额外依赖。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


_load_dotenv(BASE_DIR / ".env")


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    # 数据库（与平台同库）
    # DATABASE_* is the neutral deployment contract. CERDB_* remains a
    # compatible fallback for vendor PostgreSQL-wire deployments.
    db_dsn: str = _env("DATABASE_DSN", _env("CERDB_DSN", _env("ENERGY_DATABASE_URL", "")))
    db_host: str = _env("DATABASE_HOST", _env("CERDB_HOST", _env("DB_HOST", "127.0.0.1")))
    db_port: int = _env_int("DATABASE_PORT", _env_int("CERDB_PORT", _env_int("DB_PORT", 3306)))
    db_user: str = _env("DATABASE_USER", _env("CERDB_APP_USER", _env("DB_USER", "shsystem_app")))
    db_password: str = _env("DATABASE_PASSWORD", _env("CERDB_APP_PASSWORD", _env("DB_PASSWORD", "")))
    db_name: str = _env("DATABASE_NAME", _env("CERDB_DB", _env("DB_NAME", "carbon_emissions")))
    db_driver: str = _env("DATABASE_DRIVER", _env("CERDB_DRIVER", "mysql"))

    # 服务
    api_prefix: str = _env("API_PREFIX", "/api/v1/prediction")
    api_key: str = _env("API_KEY", "dev-key")
    api_host: str = _env("API_HOST", "0.0.0.0")
    api_port: int = _env_int("API_PORT", 8000)
    cors_origins: str = _env("CORS_ORIGINS", "*")

    # 建模
    seed: int = _env_int("MODEL_SEED", 20260928)
    horizon: int = _env_int("FORECAST_HORIZON", 12)
    test_year: int = _env_int("TEST_YEAR", 2025)
    w_grid: List[int] = field(default_factory=lambda: [6, 9, 12])
    lstm_hidden_grid: List[int] = field(default_factory=lambda: [32, 64])
    lstm_epochs: int = _env_int("LSTM_EPOCHS", 220)
    lstm_patience: int = _env_int("LSTM_PATIENCE", 25)
    lstm_batch: int = _env_int("LSTM_BATCH", 16)
    lstm_lr: float = _env_float("LSTM_LR", 1e-3)
    gra_rho: float = _env_float("GRA_RHO", 0.5)
    gra_threshold: float = _env_float("GRA_THRESHOLD", 0.70)
    gra_detrend_ratio: float = _env_float("GRA_DETREND_RATIO", 0.60)
    anomaly_contamination: float = _env_float("ANOMALY_CONTAMINATION", 0.03)

    # 口径基准
    base_grid_factor: float = _env_float("BASE_GRID_FACTOR", 0.5306)
    base_heat_factor: float = _env_float("BASE_HEAT_FACTOR", 0.11)
    base_heat_area_factor: float = _env_float("BASE_HEAT_AREA_FACTOR", 0.9224)

    # 路径
    base_dir: Path = BASE_DIR
    data_dir: Path = DATA_DIR
    raw_dir: Path = RAW_DIR
    external_dir: Path = EXTERNAL_DIR
    artifact_dir: Path = ARTIFACT_DIR
    model_dir: Path = MODEL_DIR
    report_dir: Path = REPORT_DIR
    sql_dir: Path = SQL_DIR

    # 业务常量
    reporting_timezone: str = "Asia/Shanghai"
    forecast_target: str = "CO2_COMPARABLE"


settings = Settings()

for _p in (settings.artifact_dir, settings.model_dir, settings.report_dir):
    _p.mkdir(parents=True, exist_ok=True)
