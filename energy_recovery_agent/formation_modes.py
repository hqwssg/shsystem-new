# 模块功能说明：本文件实现项目中的相关数据处理、算法、工具或验证流程。

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional
import csv
import math
import re


DEFAULT_FORMATION_MODE_PATH = Path("data") / "real_shuohuang" / "train_formation_modes_2025.csv"


@dataclass(frozen=True)
class FormationMode:
    """类 FormationMode：执行该模块中的相关处理逻辑。"""
    category: str
    load_state: str
    formation_mode: str
    traction_config_raw: str
    wagon_count: int
    mass_tons: float
    mass_interpretation: str
    loco_config_status: str
    dispatch_usage_status: str
    source_file: str
    notes: str


@dataclass(frozen=True)
class FormationModeSemantics:
    """类 FormationModeSemantics：执行该模块中的相关处理逻辑。"""
    formation_mode: str
    locomotive_layout: str
    tail_equipment: str
    description: str
    status: str = "confirmed_by_user_context"


FORMATION_MODE_SEMANTICS: Dict[str, FormationModeSemantics] = {
    "1+1": FormationModeSemantics(
        formation_mode="1+1",
        locomotive_layout="distributed_two_locomotives",
        tail_equipment="optional_controllable_tail_device",
        description=(
            "Two locomotives are placed at different positions in the train and "
            "work through synchronized control for heavy-haul operation."
        ),
    ),
    "2+0": FormationModeSemantics(
        formation_mode="2+0",
        locomotive_layout="two_head_end_locomotives",
        tail_equipment="controllable_tail_device_no_tail_locomotive",
        description=(
            "Two locomotives are coupled at the head end; the tail has no locomotive "
            "and may use a controllable tail device."
        ),
    ),
    "单牵": FormationModeSemantics(
        formation_mode="单牵",
        locomotive_layout="single_locomotive",
        tail_equipment="none",
        description="One locomotive independently hauls the whole train.",
    ),
}


def _clean(value: object) -> str:
    """函数 _clean：执行该模块中的相关处理逻辑。"""
    return "" if value is None else str(value).strip()


def _norm(value: object) -> str:
    """函数 _norm：执行该模块中的相关处理逻辑。"""
    text = _clean(value).lower()
    return re.sub(r"[\s（）()]+", "", text)


def _whole_count(value: object, field_name: str) -> int:
    """函数 _whole_count：执行该模块中的相关处理逻辑。"""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite non-negative integer, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite non-negative integer, got {value!r}") from exc
    if not math.isfinite(number) or number < 0.0 or not number.is_integer():
        raise ValueError(f"{field_name} must be a finite non-negative integer, got {value!r}")
    return int(number)


def _finite_float(value: object, field_name: str) -> float:
    """函数 _finite_float：执行该模块中的相关处理逻辑。"""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite, got {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite, got {value!r}")
    return number


def formation_mode_semantics(formation_mode: str) -> Optional[FormationModeSemantics]:
    """函数 formation_mode_semantics：执行该模块中的相关处理逻辑。"""
    normalized = _norm(formation_mode)
    for key, value in FORMATION_MODE_SEMANTICS.items():
        key_norm = _norm(key)
        if normalized == key_norm or (key_norm and key_norm in normalized):
            return value
    return None


def load_formation_modes(path: Path = DEFAULT_FORMATION_MODE_PATH) -> tuple[FormationMode, ...]:
    """函数 load_formation_modes：执行该模块中的相关处理逻辑。"""
    if not path.exists():
        return ()
    modes: list[FormationMode] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            wagon_count_text = _clean(row.get("wagon_count"))
            mass_text = _clean(row.get("mass_tons"))
            if not wagon_count_text or not mass_text:
                continue
            modes.append(
                FormationMode(
                    category=_clean(row.get("category")),
                    load_state=_clean(row.get("load_state")),
                    formation_mode=_clean(row.get("formation_mode")),
                    traction_config_raw=_clean(row.get("traction_config_raw")),
                    wagon_count=_whole_count(wagon_count_text, "wagon_count"),
                    mass_tons=_finite_float(mass_text, "mass_tons"),
                    mass_interpretation=_clean(row.get("mass_interpretation")),
                    loco_config_status=_clean(row.get("loco_config_status")),
                    dispatch_usage_status=_clean(row.get("dispatch_usage_status")),
                    source_file=_clean(row.get("source_file")),
                    notes=_clean(row.get("notes")),
                )
            )
    return tuple(modes)


def infer_load_state(train_type: str) -> str:
    """函数 infer_load_state：执行该模块中的相关处理逻辑。"""
    normalized = _norm(train_type)
    if normalized in {"heavy", "loaded", "重车", "重列"}:
        return "heavy"
    if normalized in {"empty", "return", "空车", "空列"}:
        return "empty"
    return ""


def resolve_formation_mode(
    modes: Iterable[FormationMode],
    *,
    category: str = "",
    load_state: str = "",
    formation_mode: str = "",
    wagon_count: Optional[int] = None,
    free_text: str = "",
) -> Optional[FormationMode]:
    """函数 resolve_formation_mode：执行该模块中的相关处理逻辑。"""
    candidates = list(modes)
    category_n = _norm(category)
    load_n = _norm(load_state)
    mode_n = _norm(formation_mode)
    free_n = _norm(free_text)

    if category_n:
        candidates = [item for item in candidates if _norm(item.category) == category_n]
    if load_n:
        candidates = [item for item in candidates if _norm(item.load_state) == load_n]
    if mode_n:
        candidates = [item for item in candidates if _norm(item.formation_mode) == mode_n]
    elif free_n:
        matched = [item for item in candidates if _norm(item.formation_mode) and _norm(item.formation_mode) in free_n]
        if matched:
            candidates = matched
    if wagon_count is not None:
        candidates = [item for item in candidates if item.wagon_count == wagon_count]

    return candidates[0] if len(candidates) == 1 else None


def formation_source_note(mode: FormationMode) -> str:
    """函数 formation_source_note：执行该模块中的相关处理逻辑。"""
    semantics = formation_mode_semantics(mode.formation_mode)
    parts = [
        f"category={mode.category}",
        f"load_state={mode.load_state}",
        f"formation_mode={mode.formation_mode}",
        f"wagon_count={mode.wagon_count}",
        f"mass_tons={mode.mass_tons}",
    ]
    if mode.source_file:
        parts.insert(0, mode.source_file)
    if mode.mass_interpretation:
        parts.append(f"mass_interpretation={mode.mass_interpretation}")
    if semantics is not None:
        parts.append(f"locomotive_layout={semantics.locomotive_layout}")
        parts.append(f"semantics_status={semantics.status}")
    return "; ".join(parts)
