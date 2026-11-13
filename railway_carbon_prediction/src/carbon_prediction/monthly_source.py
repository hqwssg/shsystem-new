"""Receive committed carbon monthly snapshots without promoting missing inputs into model data."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from . import db, repository
from .config import settings
from .factors import FactorError, FactorResolver
from .ingest_guard import IdempotencyConflict
from .schemas import IngestRequest

OVERRIDE_REASON = "碳排放模版重新核算发生改变"
UNITS = {"ELEC_TOTAL": "MWh", "ELEC_TRAC": "MWh", "ELEC_AUX": "MWh",
         "GAS": "万立方米", "GASOLINE": "吨", "DIESEL": "吨", "HEAT_REPORTED": "GJ"}
ELECTRICITY = {"ELEC_TOTAL", "ELEC_TRAC", "ELEC_AUX"}
SCALE = Decimal("0.000001")


def _decimal(value) -> Decimal:
    return Decimal(str(value)).quantize(SCALE, rounding=ROUND_HALF_UP)


def _month(period: str) -> date:
    return date.fromisoformat(period + "-01")


def lock_month(org: str, period: date) -> dict:
    # No upstream DDL is run in an ingestion transaction.
    db.execute("INSERT INTO prediction_monthly_source_head(org_id,period) VALUES(%s,%s) "
               "ON DUPLICATE KEY UPDATE org_id=VALUES(org_id)", (org, period))
    return db.fetch_one("SELECT * FROM prediction_monthly_source_head "
                        "WHERE org_id=%s AND period=%s FOR UPDATE", (org, period))


def ingest(req: IngestRequest) -> dict:
    kwargs = dict(operator=req.operator, run_anomaly=req.run_anomaly, factor_version=req.factor_version)
    with db.transaction():
        if req.source_snapshot is None:
            for org, period in sorted({(r.org_id, r.period) for r in req.records}):
                lock_month(org, _month(period))
            return _write_records([r.model_dump() for r in req.records],
                                           idempotency_key=req.idempotency_key, override=req.override,
                                           override_reason=req.override_reason, **kwargs)
        return _receive(req, kwargs)


def _write_records(records, **kwargs):
    from .pipeline import ingest_records
    return ingest_records(records, **kwargs)


def _receive(req: IngestRequest, kwargs: dict) -> dict:
    source = req.source_snapshot
    org, period = source.org_id, _month(source.period)
    head = lock_month(org, period)
    payload = req.model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    receipt = db.fetch_one("SELECT request_hash,response FROM prediction_monthly_source_receipt "
                           "WHERE idempotency_key=%s", (req.idempotency_key,))
    if receipt:
        if receipt["request_hash"] != digest:
            raise IdempotencyConflict("月度快照幂等键已用于其他请求")
        return json.loads(receipt["response"])
    if source.version <= head["source_version"]:
        return {"status": "superseded"}

    old_rows = repository.get_month_activity(org, period)
    old = {row["var_id"]: row for row in old_rows}
    pending = bool(head["awaiting_source"])
    if source.operation_type == 1 and (old or pending):
        result = {"status": "skipped_existing"}
    else:
        records, missing = _prepare(req)
        if {"HEAT", "HEAT_REPORTED"} & old.keys() and "HEAT_REPORTED" not in records:
            missing.add("heat:missing_current_source")
        if missing or not source.complete or not records:
            batch = "SRC-" + uuid.uuid4().hex
            reason = "来源待复核：" + (", ".join(sorted(missing)) or "缺少完整月度活动量")
            repository.create_batch(batch, org, period, period, len(records), None, req.operator,
                                    status="pending_review", message=reason[:1000])
            repository.log("MONTHLY_SOURCE_REVIEW", "prediction_ingest_batch", batch, req.operator,
                           {"source_version": source.version, "missing": sorted(missing)})
            result, pending = {"status": "pending_review", "batch_id": batch, "missing": sorted(missing)}, True
        elif _same_values(old, records):
            batch = next((old[var]["batch_id"] for var in sorted(records) if old[var]["batch_id"]), None)
            needs_anomaly_review = any(row["quality_status"] == "pending" for row in old_rows)
            result = {"status": "pending_review" if needs_anomaly_review else "unchanged", "batch_id": batch}
            pending = False
        else:
            override = bool(old)
            result = _write_records(list(records.values()), override=override,
                                             override_reason=OVERRIDE_REASON if override else None, **kwargs)
            pending = False
        if head["awaiting_source"] and head["batch_id"]:
            repository.update_batch(head["batch_id"], status="rejected",
                                    message="已由新的核算月度快照替代")
            if not pending:
                repository.log("MONTHLY_SOURCE_CONFIRMED", "prediction_ingest_batch", head["batch_id"],
                               req.operator, {"source_version": source.version})

    db.execute("UPDATE prediction_monthly_source_head SET source_version=%s,awaiting_source=%s,"
               "batch_id=%s WHERE org_id=%s AND period=%s",
               (source.version, int(pending),
                head["batch_id"] if result["status"] == "skipped_existing" else result.get("batch_id"), org, period))
    db.execute("INSERT INTO prediction_monthly_source_receipt(idempotency_key,org_id,period,source_version,"
               "request_hash,payload,response) VALUES(%s,%s,%s,%s,%s,%s,%s)",
               (req.idempotency_key, org, period, source.version, digest, db.j(payload), db.j(result)))
    return result


def _same_values(old: dict, records: dict) -> bool:
    for var, row in records.items():
        before = old.get(var)
        if not before or before["value"] is None or _decimal(before["value"]) != _decimal(row["value"]):
            return False
        if var == "HEAT" and (before["reported_value"] is None
                             or _decimal(before["reported_value"]) != _decimal(row["reported_value"])):
            return False
    return bool(records)


def _prepare(req: IngestRequest) -> tuple[dict, set]:
    source = req.source_snapshot
    org, period = source.org_id, source.period
    records = {}
    seen = set()
    missing = set(source.missing)
    for r in req.records:
        if ((r.org_id, r.period) != (org, period) or r.var_id in seen
                or r.var_id not in UNITS or UNITS[r.var_id] != r.unit):
            raise ValueError("月度快照必须使用同一组织月份、唯一品种及其标准单位")
        seen.add(r.var_id)
        if org != "JLG" and r.var_id in ("ELEC_TRAC", "ELEC_AUX"):
            raise ValueError("肃宁和原平只提交总电")
        if r.value is None:
            missing.add("missing:" + r.var_id)
        else:
            records[r.var_id] = r.model_dump()
    if org == "JLG":
        if not ELECTRICITY <= records.keys():
            missing.add("electricity:incomplete")
        elif _decimal(records["ELEC_TOTAL"]["value"]) != (
                _decimal(records["ELEC_TRAC"]["value"]) + _decimal(records["ELEC_AUX"]["value"])):
            missing.add("electricity:not_closed")

    if source.heat_sources:
        try:
            reported, comparable = _heat_values(org, period, source.heat_sources)
        except (ValueError, FactorError):
            missing.add("heat:missing_approved_rule")
        else:
            for var, value in (("HEAT_REPORTED", reported), ("HEAT", comparable)):
                records[var] = dict(org_id=org, period=period, var_id=var, unit="GJ",
                                    value=float(value), reported_value=float(reported))
    elif "HEAT_REPORTED" in records:
        missing.add("heat:missing_source_breakdown")
    return records, missing


def _heat_values(org: str, period: str, sources) -> tuple[Decimal, Decimal]:
    measured = sum((s.amount for s in sources if s.kind == "measured"), Decimal(0))
    area = sum((s.amount for s in sources if s.kind == "area"), Decimal(0))
    if not area:
        return _decimal(measured), _decimal(measured)
    if os.getenv("PREDICTION_MONTHLY_AREA_RULES_APPROVED", "").lower() != "true":
        raise ValueError("面积热力还原规则尚未批准")
    rule = FactorResolver().resolve_heat_area(org, period)
    if rule.get("org_id") != org or rule.get("unit") != "GJ/m2":
        raise ValueError("没有适用的分公司面积热力规则")
    factor = Decimal(str(rule["rule_value"]))
    base = Decimal(str(settings.base_heat_area_factor))
    if factor <= 0 or base <= 0:
        raise ValueError("面积热力折算系数必须大于零")
    return _decimal(measured + area * factor), _decimal(measured + area * base)
