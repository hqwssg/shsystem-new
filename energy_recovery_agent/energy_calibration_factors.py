# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import json
import math


DEFAULT_FACTOR_PATH = Path("data") / "real_shuohuang" / "energy_calibration_factors.json"


@dataclass(frozen=True)
class EnergyCalibrationFactor:
    """类 EnergyCalibrationFactor：执行该模块中的相关处理逻辑。"""
    traction_scale: float
    group_level: str
    group_value: str
    coefficient_status: str
    enabled_by_default: bool
    data_status: str


def _clean(value: Any) -> str:
    """函数 _clean：执行该模块中的相关处理逻辑。"""
    return "" if value is None else str(value).strip()


def _as_float(value: Any, default: float = 1.0) -> float:
    """函数 _as_float：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"calibration number must be finite, got {value!r}")
    try:
        if value is None or value == "":
            number = float(default)
        else:
            number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"calibration number must be finite, got {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"calibration number must be finite, got {value!r}")
    return number


def _as_int(value: Any, default: int = 0) -> int:
    """函数 _as_int：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"calibration count must be a finite whole number, got {value!r}")
    try:
        if value is None or value == "":
            number = float(default)
        else:
            number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"calibration count must be a finite whole number, got {value!r}") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"calibration count must be a finite whole number, got {value!r}")
    return int(number)


def _as_bool(value: Any, default: bool = False) -> bool:
    """函数 _as_bool：执行该模块中的相关处理逻辑。"""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = _clean(value).lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"enabled_by_default must be a recognized boolean, got {value!r}")


def _positive_scale(value: Any) -> float:
    """函数 _positive_scale：执行该模块中的相关处理逻辑。"""
    number = _as_float(value)
    if number <= 0.0:
        raise ValueError(f"traction_scale must be positive, got {value!r}")
    return number


def _has_usable_group_samples(groups: Any) -> bool:
    """函数 _has_usable_group_samples：执行该模块中的相关处理逻辑。"""
    if not isinstance(groups, dict):
        return False
    return any(
        isinstance(item, dict)
        and item.get("coefficient_status") == "usable"
        and item.get("traction_scale") is not None
        and _as_int(item.get("sample_count")) > 0
        for level in groups.values()
        if isinstance(level, dict)
        for item in level.values()
    )


def load_energy_calibration_config(path: Path = DEFAULT_FACTOR_PATH) -> dict[str, Any]:
    """函数 load_energy_calibration_config：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        return {}
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("energy calibration config root must be a JSON object")
    return config


def resolve_energy_calibration_factor(
    *,
    travel_direction: str = "",
    aggregation_type: str = "",
    path: Path = DEFAULT_FACTOR_PATH,
    config: Optional[dict[str, Any]] = None,
) -> EnergyCalibrationFactor:
    """函数 resolve_energy_calibration_factor：执行该模块中的相关处理逻辑。"""
    cfg = config if config is not None else load_energy_calibration_config(path)
    if not isinstance(cfg, dict):
        raise ValueError("energy calibration config root must be a dictionary")
    if not cfg:
        return EnergyCalibrationFactor(
            traction_scale=1.0,
            group_level="default",
            group_value="no_config",
            coefficient_status="not_configured",
            enabled_by_default=False,
            data_status="missing",
        )

    groups = cfg.get("groups", {})
    global_cfg = cfg.get("global", {})
    if not isinstance(groups, dict):
        raise ValueError("energy calibration groups must be a dictionary")
    if not isinstance(global_cfg, dict):
        raise ValueError("energy calibration global settings must be a dictionary")
    for level_name, level_groups in groups.items():
        if not isinstance(level_groups, dict):
            raise ValueError(
                f"energy calibration groups[{level_name!r}] must be a dictionary"
            )
        for group_value, item in level_groups.items():
            if not isinstance(item, dict):
                raise ValueError(
                    "energy calibration group entry "
                    f"{level_name!r}/{group_value!r} must be a dictionary"
                )
    if _as_int(global_cfg.get("sample_count")) <= 0 and not _has_usable_group_samples(groups):
        return EnergyCalibrationFactor(
            traction_scale=1.0,
            group_level="default",
            group_value="no_calibration_samples",
            coefficient_status="no_calibration_samples",
            enabled_by_default=False,
            data_status=_clean(cfg.get("data_status")) or "incomplete",
        )
    direction = _clean(travel_direction)
    agg = _clean(aggregation_type)
    candidates: list[tuple[str, str]] = []
    if direction and agg:
        candidates.append(("direction_aggregation", f"{direction}|{agg}"))
    if direction:
        candidates.append(("travel_direction", direction))
    if agg:
        candidates.append(("aggregation_type", agg))

    for level, value in candidates:
        item = groups.get(level, {}).get(value)
        if item and item.get("coefficient_status") == "usable" and item.get("traction_scale") is not None:
            return EnergyCalibrationFactor(
                traction_scale=_positive_scale(item.get("traction_scale")),
                group_level=level,
                group_value=value,
                coefficient_status=_clean(item.get("coefficient_status")),
                enabled_by_default=_as_bool(cfg.get("enabled_by_default"), False),
                data_status=_clean(cfg.get("data_status")),
            )

    return EnergyCalibrationFactor(
        traction_scale=_positive_scale(global_cfg.get("traction_scale")),
        group_level="global",
        group_value="all",
        coefficient_status="usable",
        enabled_by_default=_as_bool(cfg.get("enabled_by_default"), False),
        data_status=_clean(cfg.get("data_status")),
    )
