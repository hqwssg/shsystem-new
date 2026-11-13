"""数据路径解析：把 configs/data_paths.yaml 变成可用的绝对路径。

设计约束（对应项目边界要求）：

* 不在任何代码中硬编码绝对路径；
* 共享铁路基础数据只读引用，不复制多份；
* 共享数据缺失时直接报错，不静默降级、不用假数据顶替。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml

# 环境变量覆盖名（优先级高于配置文件）
ENV_SHARED_DATA_ROOT = "SINGLE_TRAIN_SHARED_DATA_ROOT"
ENV_SINGLE_TRAIN_DATA_ROOT = "SINGLE_TRAIN_DATA_ROOT"
ENV_EXPERIMENTS_ROOT = "SINGLE_TRAIN_EXPERIMENTS_ROOT"

DEFAULT_CONFIG_RELATIVE = Path("configs") / "data_paths.yaml"


class DataPathError(RuntimeError):
    """数据路径配置或共享数据缺失。"""


def project_root() -> Path:
    """返回本项目根目录（regenerative_braking 包的上一级）。"""

    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ProjectPaths:
    """解析后的项目路径集合。"""

    project_root: Path
    config_path: Path
    shared_data_root: Path
    single_train_data_root: Path
    experiments_root: Path
    data_manifest_path: Path
    shared_data_read_only: bool
    shared_data_required_files: tuple

    # ---------- 派生路径 ----------
    @property
    def train_parameters_path(self) -> Path:
        return self.single_train_data_root / "train_parameters.json"

    @property
    def motor_parameters_path(self) -> Path:
        return self.single_train_data_root / "motor_parameters.json"

    @property
    def dc_dc_parameters_path(self) -> Path:
        return self.single_train_data_root / "dc_dc_parameters.json"

    @property
    def storage_parameters_path(self) -> Path:
        return self.single_train_data_root / "storage_parameters.json"

    def shared_file(self, name: str) -> Path:
        return self.shared_data_root / name

    def describe(self) -> str:
        return (
            f"project_root={self.project_root}\n"
            f"shared_data_root={self.shared_data_root}\n"
            f"single_train_data_root={self.single_train_data_root}\n"
            f"experiments_root={self.experiments_root}"
        )


def _resolve(base: Path, raw: Any, field_name: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise DataPathError(f"data_paths.yaml 字段 {field_name} 必须是非空字符串，实际为 {raw!r}")
    candidate = Path(raw.strip())
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def load_project_paths(
    config_path: Optional[Path] = None,
    project_root_override: Optional[Path] = None,
) -> ProjectPaths:
    """读取并解析数据路径配置。

    Args:
        config_path: 显式指定配置文件；默认 <project_root>/configs/data_paths.yaml。
        project_root_override: 用于测试时注入临时项目根目录。
    """

    base = Path(project_root_override).resolve() if project_root_override else project_root()
    cfg_path = Path(config_path) if config_path else base / DEFAULT_CONFIG_RELATIVE
    cfg_path = cfg_path if cfg_path.is_absolute() else (base / cfg_path)
    cfg_path = cfg_path.resolve()

    if not cfg_path.is_file():
        raise DataPathError(f"数据路径配置不存在：{cfg_path}")

    with cfg_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, Mapping):
        raise DataPathError(f"数据路径配置格式错误（应为 mapping）：{cfg_path}")

    shared_raw = os.environ.get(ENV_SHARED_DATA_ROOT) or raw.get("shared_data_root")
    single_raw = os.environ.get(ENV_SINGLE_TRAIN_DATA_ROOT) or raw.get("single_train_data_root")
    experiments_raw = os.environ.get(ENV_EXPERIMENTS_ROOT) or raw.get("experiments_root")
    manifest_raw = raw.get("data_manifest", "data/data_manifest.yaml")

    required = raw.get("shared_data_required_files") or []
    if not isinstance(required, (list, tuple)):
        raise DataPathError("shared_data_required_files 必须是列表")

    return ProjectPaths(
        project_root=base,
        config_path=cfg_path,
        shared_data_root=_resolve(base, shared_raw, "shared_data_root"),
        single_train_data_root=_resolve(base, single_raw, "single_train_data_root"),
        experiments_root=_resolve(base, experiments_raw, "experiments_root"),
        data_manifest_path=_resolve(base, manifest_raw, "data_manifest"),
        shared_data_read_only=bool(raw.get("shared_data_read_only", True)),
        shared_data_required_files=tuple(str(item) for item in required),
    )


def check_shared_data(paths: ProjectPaths) -> Dict[str, bool]:
    """检查共享数据根目录与必需文件是否就位。

    只做只读检查，不创建任何目录、不写入任何文件。
    """

    report: Dict[str, bool] = {"root_exists": paths.shared_data_root.is_dir()}
    for name in paths.shared_data_required_files:
        report[name] = (paths.shared_data_root / name).is_file()
    return report


def require_shared_data(paths: ProjectPaths) -> None:
    """共享数据未就位时抛出明确错误（不静默降级）。"""

    report = check_shared_data(paths)
    missing: List[str] = [name for name, ok in report.items() if not ok]
    if missing:
        raise DataPathError(
            "共享铁路基础数据未就位，缺失：" + ", ".join(missing) + "\n"
            f"shared_data_root = {paths.shared_data_root}\n"
            f"可用环境变量 {ENV_SHARED_DATA_ROOT} 覆盖，或在 {paths.config_path} 中修正。"
        )


def ensure_read_only(paths: ProjectPaths, target: Path) -> None:
    """写入保护：禁止任何输出落到共享数据根目录内。"""

    if not paths.shared_data_read_only:
        return
    resolved = Path(target).resolve()
    try:
        resolved.relative_to(paths.shared_data_root)
    except ValueError:
        return
    raise DataPathError(
        "共享铁路基础数据为只读引用，禁止写入：" f"{resolved}\n请把输出写到 experiments_root = {paths.experiments_root}"
    )
