"""排放因子与口径规则的统一解析。

设计原则：
- 活动数据只存活动量，不重复存排放因子；
- 因子按 var_id + effective_from/effective_to 生效；
- 供热面积系数按 org_id + rule_type 生效；
- 计算时统一解析，并把解析结果快照到排放结果表，保证可追溯。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from . import db

# 必须能解析到因子的品种；HEAT_REPORTED 复用 HEAT 因子
REQUIRED_FACTOR_VARS: Tuple[str, ...] = (
    "GAS", "GASOLINE", "DIESEL", "ELEC_TOTAL", "HEAT",
)
FACTOR_ALIASES = {"HEAT_REPORTED": "HEAT"}


class FactorError(Exception):
    """因子解析基类异常。"""


class FactorNotFound(FactorError):
    """指定期间没有生效因子。"""


class FactorAmbiguous(FactorError):
    """同一期间命中多条互相冲突的因子/规则。"""


class FactorVersionConflict(FactorError):
    """调用方声明的因子版本与当前解析版本不一致。"""


def month_start(value: str | date | datetime) -> date:
    """把任意日期/月份统一为该月 1 日。"""
    if isinstance(value, datetime):
        return value.date().replace(day=1)
    if isinstance(value, date):
        return value.replace(day=1)
    ts = pd.Timestamp(value)
    return date(ts.year, ts.month, 1)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _factor_dict(row: dict) -> dict:
    return {
        "factor_id": row.get("factor_id"),
        "var_id": row.get("var_id"),
        "factor_value": _num(row.get("factor_value")),
        "factor_unit": row.get("factor_unit"),
        "effective_from": _iso(row.get("effective_from")),
        "effective_to": _iso(row.get("effective_to")),
        "factor_version": row.get("factor_version") or "legacy",
        "factor_source": row.get("factor_source"),
        "is_caliber_change": int(row.get("is_caliber_change") or 0),
        "policy_basis": row.get("policy_basis"),
    }


def _rule_dict(row: dict) -> dict:
    return {
        "rule_id": row.get("rule_id"),
        "org_id": row.get("org_id"),
        "rule_type": row.get("rule_type"),
        "rule_value": _num(row.get("rule_value")),
        "unit": row.get("unit"),
        "effective_from": _iso(row.get("effective_from")),
        "effective_to": _iso(row.get("effective_to")),
        "rule_version": row.get("rule_version") or "legacy",
        "source": row.get("source"),
        "note": row.get("note"),
    }


def _compose_version(items: Iterable[dict], key: str) -> str:
    versions: List[str] = []
    for item in items:
        version = item.get(key) or "legacy"
        if version not in versions:
            versions.append(version)
    return "|".join(versions) if versions else "legacy"


def _compose_source(items: Iterable[dict]) -> Optional[str]:
    sources: List[str] = []
    for item in items:
        source = item.get("factor_source") or item.get("source")
        if source and source not in sources:
            sources.append(str(source))
    return "; ".join(sources)[:255] if sources else None


class FactorResolver:
    """按组织和月份解析排放因子、供热面积系数。

    可注入 ``fetch_all`` 以便单元测试；默认使用 ``db.fetch_all``。
    """

    def __init__(self, fetch_all: Optional[Callable[..., List[dict]]] = None):
        self._fetch_all = fetch_all or db.fetch_all
        self._cache: Dict[Tuple[str, date], dict] = {}

    # ------------------------------------------------------------------
    # 单因子
    # ------------------------------------------------------------------
    def resolve_factor(self, var_id: str, org_id: str, period: str | date | datetime) -> dict:
        target_var = FACTOR_ALIASES.get(var_id, var_id)
        p = month_start(period)
        rows = self._fetch_all(
            """
            SELECT factor_id,var_id,factor_value,factor_unit,effective_from,effective_to,
                   factor_version,factor_source,is_caliber_change,policy_basis
            FROM prediction_emission_factor
            WHERE var_id=%s
              AND effective_from<=%s
              AND (effective_to IS NULL OR effective_to>=%s)
            ORDER BY effective_from DESC
            """,
            (target_var, p, p),
        )
        if not rows:
            raise FactorNotFound(f"{org_id} {p:%Y-%m} 缺少 {target_var} 排放因子")
        if len(rows) > 1:
            ids = ", ".join(str(r.get("factor_id")) for r in rows)
            raise FactorAmbiguous(
                f"{org_id} {p:%Y-%m} 的 {target_var} 命中多条因子：{ids}"
            )
        return _factor_dict(rows[0])

    # ------------------------------------------------------------------
    # 供热面积系数（org 专属优先于 ALL）
    # ------------------------------------------------------------------
    def resolve_heat_area(self, org_id: str, period: str | date | datetime) -> dict:
        p = month_start(period)
        rows = self._fetch_all(
            """
            SELECT rule_id,org_id,rule_type,rule_value,unit,effective_from,effective_to,
                   rule_version,source,note
            FROM prediction_caliber_rule
            WHERE rule_type='heat_area_factor'
              AND (org_id=%s OR org_id='ALL')
              AND effective_from<=%s
              AND (effective_to IS NULL OR effective_to>=%s)
            ORDER BY effective_from DESC
            """,
            (org_id, p, p),
        )
        if not rows:
            raise FactorNotFound(f"{org_id} {p:%Y-%m} 缺少供热面积系数")
        specific = [r for r in rows if r.get("org_id") == org_id]
        if len(specific) > 1:
            ids = ", ".join(str(r.get("rule_id")) for r in specific)
            raise FactorAmbiguous(
                f"{org_id} {p:%Y-%m} 的供热面积系数命中多条规则：{ids}"
            )
        if specific:
            return _rule_dict(specific[0])
        all_rows = [r for r in rows if r.get("org_id") == "ALL"]
        if len(all_rows) > 1:
            ids = ", ".join(str(r.get("rule_id")) for r in all_rows)
            raise FactorAmbiguous(
                f"{org_id} {p:%Y-%m} 的通用供热面积系数命中多条规则：{ids}"
            )
        if not all_rows:
            raise FactorNotFound(f"{org_id} {p:%Y-%m} 缺少供热面积系数")
        return _rule_dict(all_rows[0])

    # ------------------------------------------------------------------
    # 一次解析全部必需因子
    # ------------------------------------------------------------------
    def resolve_all(self, org_id: str, period: str | date | datetime) -> dict:
        p = month_start(period)
        cache_key = (org_id, p)
        if cache_key in self._cache:
            return self._cache[cache_key]

        factors: Dict[str, dict] = {}
        missing: List[str] = []
        ambiguous: List[str] = []
        for var_id in REQUIRED_FACTOR_VARS:
            try:
                factors[var_id] = self.resolve_factor(var_id, org_id, p)
            except FactorNotFound:
                missing.append(var_id)
            except FactorAmbiguous as exc:
                ambiguous.append(str(exc))

        heat_area = None
        try:
            heat_area = self.resolve_heat_area(org_id, p)
        except FactorNotFound:
            missing.append("HEAT_AREA")
        except FactorAmbiguous as exc:
            ambiguous.append(str(exc))

        items = list(factors.values())
        if heat_area:
            items.append(heat_area)
        result = {
            "org_id": org_id,
            "period": p.isoformat(),
            "complete": not missing and not ambiguous,
            "missing": missing,
            "ambiguous": ambiguous,
            "factors": factors,
            "heat_area": heat_area,
            "heat_area_factor": heat_area["rule_value"] if heat_area else None,
            "factor_version": (_compose_version(items, "factor_version") if factors else "legacy")[:128],
            "heat_area_version": heat_area.get("rule_version") if heat_area else None,
            "factor_source": _compose_source(items),
        }
        # 规则也有 rule_version；组合版本需把 heat_area 的版本一并纳入
        if heat_area:
            versions = [f.get("factor_version") or "legacy" for f in factors.values()]
            hv = heat_area.get("rule_version") or "legacy"
            if hv not in versions:
                versions.append(hv)
            result["factor_version"] = ("|".join(versions) if versions else "legacy")[:128]
        result["factor_snapshot"] = {
            **{k: v for k, v in factors.items()},
            **({"HEAT_AREA": heat_area} if heat_area else {}),
        }
        self._cache[cache_key] = result
        return result

    def coverage(self, org_id: str, period: str | date | datetime) -> dict:
        """返回该组织该月的因子覆盖情况；不抛异常，供关账前检查。"""
        try:
            return self.resolve_all(org_id, period)
        except FactorError as exc:
            p = month_start(period)
            return {
                "org_id": org_id, "period": p.isoformat(), "complete": False,
                "missing": [], "ambiguous": [str(exc)], "factors": {},
                "factor_version": None, "factor_source": None,
            }

    def clear_cache(self) -> None:
        self._cache.clear()


def resolve_all(org_id: str, period: str | date | datetime,
                resolver: Optional[FactorResolver] = None) -> dict:
    return (resolver or FactorResolver()).resolve_all(org_id, period)


def resolve_factor(var_id: str, org_id: str, period: str | date | datetime,
                   resolver: Optional[FactorResolver] = None) -> dict:
    return (resolver or FactorResolver()).resolve_factor(var_id, org_id, period)
