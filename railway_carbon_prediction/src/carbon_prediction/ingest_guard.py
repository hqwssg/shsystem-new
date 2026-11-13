"""月度入库保护：月份锁、请求体指纹与覆盖审计。"""
from __future__ import annotations

import hashlib
import json
from typing import Iterable, List, Optional


class MonthAlreadyIngested(Exception):
    """该组织该月份已有活动数据，默认拒绝重复入库。"""

    def __init__(self, org_id: str, period: str, existing_batch_id: Optional[str],
                 existing_rows: int):
        self.org_id = org_id
        self.period = period
        self.existing_batch_id = existing_batch_id
        self.existing_rows = existing_rows
        super().__init__(
            f"{org_id} {period[:7]} 已入库（{existing_rows} 条活动数据"
            + (f"，批次 {existing_batch_id}" if existing_batch_id else "")
            + "）。如确需覆盖，请传 override=true 并填写 override_reason。"
        )


class IdempotencyConflict(Exception):
    """同一 idempotency_key 被用于不同的请求体。"""


def _canonical_record(record: dict) -> dict:
    value = record.get("value")
    reported = record.get("reported_value")
    return {
        "org_id": record.get("org_id"),
        "period": str(record.get("period"))[:10],
        "var_id": record.get("var_id"),
        "value": None if value is None else round(float(value), 6),
        "reported_value": None if reported is None else round(float(reported), 6),
        "unit": record.get("unit"),
        "source_status": record.get("source_status", "原始"),
        "is_estimated": int(bool(record.get("is_estimated", False))),
    }


def payload_hash(records: Iterable[dict], *, operator: str = "system",
                 run_anomaly: bool = True, factor_version: Optional[str] = None,
                 override: bool = False, override_reason: Optional[str] = None) -> str:
    """对请求体做稳定规范化后计算 SHA-256。

    同一 idempotency_key 重试时，hash 必须一致；否则视为 key 被复用于新请求。
    """
    canonical: List[dict] = sorted(
        (_canonical_record(r) for r in records),
        key=lambda x: (x["org_id"] or "", x["period"], x["var_id"] or ""),
    )
    body = {
        "records": canonical,
        "operator": operator,
        "run_anomaly": bool(run_anomaly),
        "factor_version": factor_version,
        "override": bool(override),
        "override_reason": override_reason,
    }
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
