"""数据库读写仓库。

所有 SQL 集中在此，便于平台集成时替换为 MyBatis/ORM。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from . import db
from .config import settings

# ---------------------------------------------------------------------------
# 组织 / 品种
# ---------------------------------------------------------------------------
def get_orgs(active_only: bool = True) -> List[dict]:
    sql = "SELECT * FROM prediction_org"
    if active_only:
        sql += " WHERE status='active'"
    sql += " ORDER BY org_level, org_id"
    return db.fetch_all(sql)


def get_org(org_id: str) -> Optional[dict]:
    return db.fetch_one("SELECT * FROM prediction_org WHERE org_id=%s", (org_id,))


def get_vars() -> List[dict]:
    return db.fetch_all("SELECT * FROM prediction_energy_var ORDER BY sort_order")


def get_var_map() -> Dict[str, dict]:
    return {r["var_id"]: r for r in get_vars()}


# ---------------------------------------------------------------------------
# 历史数据导入
# ---------------------------------------------------------------------------
def upsert_activity(df: pd.DataFrame, batch_id: str, data_version: str) -> int:
    rows = []
    for r in df.itertuples(index=False):
        rows.append((
            r.org_id, r.period, r.var_id, r.value, r.reported_value, r.unit,
            r.source_status, int(r.is_estimated), r.quality_status,
            getattr(r, "data_flag", None), batch_id, data_version,
        ))
    sql = """
    INSERT INTO prediction_activity_monthly
      (org_id,period,var_id,value,reported_value,unit,source_status,is_estimated,
       quality_status,data_flag,batch_id,data_version)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
      value=VALUES(value), reported_value=VALUES(reported_value), unit=VALUES(unit),
      source_status=VALUES(source_status), is_estimated=VALUES(is_estimated),
      quality_status=VALUES(quality_status), data_flag=VALUES(data_flag),
      batch_id=VALUES(batch_id), data_version=VALUES(data_version)
    """
    return db.execute_many(sql, rows)


def upsert_emission(df: pd.DataFrame, batch_id: str, data_version: str) -> int:
    rows = []
    for r in df.itertuples(index=False):
        snapshot = getattr(r, "factor_snapshot", None)
        if snapshot is not None and not isinstance(snapshot, str):
            snapshot = db.j(snapshot)
        rows.append((
            r.org_id, r.period, r.scope, r.gas_tco2, r.gasoline_tco2,
            r.diesel_tco2, r.electricity_tco2, r.heat_tco2,
            r.total_reported_tco2, r.total_comparable_tco2,
            r.electricity_factor, r.heat_factor,
            getattr(r, "factor_version", None),
            getattr(r, "heat_area_factor", None),
            getattr(r, "factor_source", None),
            snapshot,
            r.calc_method, int(r.is_verified), batch_id, data_version,
        ))
    sql = """
    INSERT INTO prediction_emission_monthly
      (org_id,period,scope,gas_tco2,gasoline_tco2,diesel_tco2,electricity_tco2,
       heat_tco2,total_reported_tco2,total_comparable_tco2,electricity_factor,
       heat_factor,factor_version,heat_area_factor,factor_source,factor_snapshot,
       calc_method,is_verified,batch_id,data_version)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
      gas_tco2=VALUES(gas_tco2), gasoline_tco2=VALUES(gasoline_tco2),
      diesel_tco2=VALUES(diesel_tco2), electricity_tco2=VALUES(electricity_tco2),
      heat_tco2=VALUES(heat_tco2), total_reported_tco2=VALUES(total_reported_tco2),
      total_comparable_tco2=VALUES(total_comparable_tco2),
      electricity_factor=VALUES(electricity_factor), heat_factor=VALUES(heat_factor),
      factor_version=VALUES(factor_version), heat_area_factor=VALUES(heat_area_factor),
      factor_source=VALUES(factor_source), factor_snapshot=VALUES(factor_snapshot),
      calc_method=VALUES(calc_method), is_verified=VALUES(is_verified),
      batch_id=VALUES(batch_id), data_version=VALUES(data_version)
    """
    return db.execute_many(sql, rows)


def upsert_emission_factors(factors: List[dict]) -> int:
    rows = []
    for f in factors:
        rows.append((
            f["var_id"], f["factor_value"], f["factor_unit"],
            f.get("factor_version") or "legacy", f["effective_from"],
            f.get("effective_to"), f.get("factor_source"),
            int(bool(f.get("is_caliber_change", False))), f.get("policy_basis"),
        ))
    sql = """
    INSERT INTO prediction_emission_factor
      (var_id,factor_value,factor_unit,factor_version,effective_from,effective_to,
       factor_source,is_caliber_change,policy_basis)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
      factor_value=VALUES(factor_value), factor_unit=VALUES(factor_unit),
      factor_version=VALUES(factor_version), effective_to=VALUES(effective_to),
      factor_source=VALUES(factor_source),
      is_caliber_change=VALUES(is_caliber_change),
      policy_basis=VALUES(policy_basis)
    """
    return db.execute_many(sql, rows)


def upsert_caliber_rules(rules: List[dict]) -> int:
    rows = []
    for x in rules:
        rows.append((
            x["rule_id"], x["org_id"], x["rule_type"], x["effective_from"],
            x.get("effective_to"), x["rule_value"], x["unit"],
            x.get("rule_version") or "legacy", x.get("source"), x.get("note"),
        ))
    sql = """
    INSERT INTO prediction_caliber_rule
      (rule_id,org_id,rule_type,effective_from,effective_to,rule_value,unit,
       rule_version,source,note)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
      org_id=VALUES(org_id), rule_type=VALUES(rule_type),
      effective_from=VALUES(effective_from), effective_to=VALUES(effective_to),
      rule_value=VALUES(rule_value), unit=VALUES(unit),
      rule_version=VALUES(rule_version), source=VALUES(source), note=VALUES(note)
    """
    return db.execute_many(sql, rows)


def upsert_policy_factors(df: pd.DataFrame) -> int:
    rows = []
    for r in df.itertuples(index=False):
        rows.append((
            r.factor_id, r.factor_name, r.period, r.value, r.unit, r.category,
            r.source_level, r.source_status, int(r.is_scenario_only), r.data_source,
        ))
    sql = """
    INSERT INTO prediction_policy_factor
      (factor_id,factor_name,period,value,unit,category,source_level,source_status,
       is_scenario_only,data_source)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
      factor_name=VALUES(factor_name), value=VALUES(value), unit=VALUES(unit),
      category=VALUES(category), source_level=VALUES(source_level),
      source_status=VALUES(source_status), is_scenario_only=VALUES(is_scenario_only),
      data_source=VALUES(data_source)
    """
    return db.execute_many(sql, rows)


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def load_emission_series(org_id: str, start: str | date | None = None,
                         end: str | date | None = None,
                         valid_only: bool = False) -> pd.DataFrame:
    sql = """SELECT e.period,e.total_reported_tco2,e.total_comparable_tco2,
                    e.diesel_tco2,e.electricity_factor,e.heat_factor,e.is_verified
             FROM prediction_emission_monthly e
             WHERE e.org_id=%s AND e.scope='Total'"""
    params: list[Any] = [org_id]
    if start:
        sql += " AND e.period>=%s"; params.append(start)
    if end:
        sql += " AND e.period<=%s"; params.append(end)
    if valid_only:
        sql += (" AND NOT EXISTS (SELECT 1 FROM prediction_activity_monthly a "
                "WHERE a.org_id=e.org_id AND a.period=e.period AND a.quality_status<>'valid')"
                " AND NOT EXISTS (SELECT 1 FROM prediction_monthly_source_head h "
                "WHERE h.org_id=e.org_id AND h.period=e.period AND h.awaiting_source=1)")
    sql += " ORDER BY e.period"
    rows = db.fetch_all(sql, params)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["period"] = pd.to_datetime(df["period"])
    for c in ["total_reported_tco2", "total_comparable_tco2", "diesel_tco2",
              "electricity_factor", "heat_factor"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def load_activity_wide(org_id: str, valid_only: bool = False) -> pd.DataFrame:
    sql = """SELECT period,var_id,value,reported_value,source_status,is_estimated,quality_status,data_flag
             FROM prediction_activity_monthly a WHERE org_id=%s"""
    if valid_only:
        sql += (" AND NOT EXISTS (SELECT 1 FROM prediction_monthly_source_head h WHERE "
                "h.org_id=a.org_id AND h.period=a.period AND h.awaiting_source=1)"
                " AND NOT EXISTS (SELECT 1 FROM prediction_activity_monthly q WHERE "
                "q.org_id=a.org_id AND q.period=a.period AND q.quality_status<>'valid')")
    rows = db.fetch_all(
        sql + " ORDER BY period",
        (org_id,),
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["period"] = pd.to_datetime(df["period"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["reported_value"] = pd.to_numeric(df["reported_value"], errors="coerce")
    value = df.pivot_table(index="period", columns="var_id", values="value", aggfunc="last")
    reported = df.pivot_table(index="period", columns="var_id", values="reported_value", aggfunc="last")
    value.columns = [f"{c}" for c in value.columns]
    reported.columns = [f"REP_{c}" for c in reported.columns]
    out = value.join(reported, how="outer").reset_index().sort_values("period")
    return out


def load_activity_long(org_id: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM prediction_activity_monthly"
    params = []
    if org_id:
        sql += " WHERE org_id=%s"
        params.append(org_id)
    sql += " ORDER BY org_id,period,var_id"
    df = pd.DataFrame(db.fetch_all(sql, params))
    if not df.empty:
        df["period"] = pd.to_datetime(df["period"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["reported_value"] = pd.to_numeric(df["reported_value"], errors="coerce")
    return df


def get_activity(org_id: str, period: str | date, var_id: str) -> Optional[dict]:
    return db.fetch_one(
        "SELECT * FROM prediction_activity_monthly WHERE org_id=%s AND period=%s AND var_id=%s",
        (org_id, period, var_id),
    )


def update_activity(org_id: str, period: str | date, var_id: str, **kwargs) -> None:
    allowed = {"value", "reported_value", "quality_status", "data_flag", "source_status",
               "is_estimated", "batch_id"}
    sets, params = [], []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k}=%s"); params.append(v)
    if not sets:
        return
    params.extend([org_id, period, var_id])
    db.execute(
        f"UPDATE prediction_activity_monthly SET {','.join(sets)} "
        "WHERE org_id=%s AND period=%s AND var_id=%s",
        params,
    )


def load_external_wide(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    sql = "SELECT period,factor_id,value FROM prediction_policy_factor"
    params: list[Any] = []
    if start and end:
        sql += " WHERE period BETWEEN %s AND %s"; params = [start, end]
    sql += " ORDER BY period"
    rows = db.fetch_all(sql, params)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["period"] = pd.to_datetime(df["period"])
    wide = df.pivot_table(index="period", columns="factor_id", values="value", aggfunc="last")
    return wide.reset_index().sort_values("period")


def load_policy_events() -> pd.DataFrame:
    rows = db.fetch_all("SELECT * FROM prediction_policy_event ORDER BY start_period")
    return pd.DataFrame(rows)


def latest_period(org_id: str) -> Optional[date]:
    row = db.fetch_one(
        """SELECT MAX(e.period) AS p FROM prediction_emission_monthly e WHERE e.org_id=%s AND e.scope='Total'
           AND NOT EXISTS (SELECT 1 FROM prediction_monthly_source_head h
             WHERE h.org_id=e.org_id AND h.period=e.period AND h.awaiting_source=1)
           AND NOT EXISTS (SELECT 1 FROM prediction_activity_monthly a
             WHERE a.org_id=e.org_id AND a.period=e.period AND a.quality_status<>'valid')""", (org_id,)
    )
    return row["p"] if row and row["p"] else None


# ---------------------------------------------------------------------------
# 批次 / 版本
# ---------------------------------------------------------------------------
def create_batch(batch_id: str, org_id: str | None, start: date | None, end: date | None,
                 row_count: int, idempotency_key: str | None, operator: str,
                 status: str = "received", message: str | None = None,
                 payload_hash: str | None = None, override_flag: bool = False,
                 override_reason: str | None = None,
                 replaces_batch_id: str | None = None) -> None:
    db.execute(
        """INSERT INTO prediction_ingest_batch
           (batch_id,org_id,period_start,period_end,row_count,status,idempotency_key,
            payload_hash,override_flag,override_reason,replaces_batch_id,operator,message)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (batch_id, org_id, start, end, row_count, status, idempotency_key,
         payload_hash, int(bool(override_flag)), override_reason, replaces_batch_id,
         operator, message),
    )


def get_batch(batch_id: str) -> Optional[dict]:
    return db.fetch_one("SELECT * FROM prediction_ingest_batch WHERE batch_id=%s", (batch_id,))


def get_batch_by_idempotency(key: str) -> Optional[dict]:
    return db.fetch_one("SELECT * FROM prediction_ingest_batch WHERE idempotency_key=%s", (key,))


def get_month_activity(org_id: str, period: date | str) -> List[dict]:
    return db.fetch_all(
        "SELECT id,org_id,period,var_id,value,reported_value,unit,source_status,"
        "is_estimated,quality_status,data_flag,batch_id,data_version "
        "FROM prediction_activity_monthly WHERE org_id=%s AND period=%s ORDER BY var_id",
        (org_id, period),
    )


def get_month_emission(org_id: str, period: date | str) -> Optional[dict]:
    return db.fetch_one(
        "SELECT * FROM prediction_emission_monthly WHERE org_id=%s AND period=%s AND scope='Total'",
        (org_id, period),
    )


def get_month_anomalies(org_id: str, period: date | str) -> List[dict]:
    return db.fetch_all(
        "SELECT id,org_id,period,var_id,detect_batch_id,level,category,status,"
        "final_disposition,score,value,evidence FROM prediction_anomaly "
        "WHERE org_id=%s AND period=%s ORDER BY id",
        (org_id, period),
    )


def close_batch_if_no_pending(batch_id: str, message: str) -> None:
    if not batch_id:
        return
    row = db.fetch_one(
        "SELECT COUNT(*) AS n FROM prediction_anomaly "
        "WHERE detect_batch_id=%s AND status='pending'", (batch_id,))
    if row and int(row["n"]) == 0:
        db.execute(
            "UPDATE prediction_ingest_batch SET status='completed', completed_at=NOW(), "
            "message=%s WHERE batch_id=%s", (message, batch_id))


def supersede_month_anomalies(org_id: str, period: date | str,
                              batch_id: str) -> int:
    """覆盖入库时，把同月旧的 pending 异常标记为 rejected，避免重复待办。"""
    return db.execute(
        "UPDATE prediction_anomaly "
        "SET status='rejected', review_note=CASE "
        "WHEN review_note IS NULL OR review_note='' "
        "THEN CONCAT('被新入库批次 ', %s, ' 覆盖') "
        "ELSE CONCAT(review_note, ' | 被新入库批次 ', %s, ' 覆盖') END "
        "WHERE org_id=%s AND period=%s AND status='pending'",
        (batch_id, batch_id, org_id, period),
    )


def insert_ingest_audit(rows: List[dict]) -> int:
    if not rows:
        return 0
    sql = """
    INSERT INTO prediction_ingest_audit
      (batch_id,replaces_batch_id,org_id,period,entity_type,entity_key,var_id,
       old_value,new_value,old_status,new_status,detail,operator)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    vals = [(
        r["batch_id"], r.get("replaces_batch_id"), r["org_id"], r["period"],
        r["entity_type"], r["entity_key"], r.get("var_id"),
        r.get("old_value"), r.get("new_value"), r.get("old_status"),
        r.get("new_status"), db.j(r.get("detail") or {}), r.get("operator"),
    ) for r in rows]
    return db.execute_many(sql, vals)


def update_batch(batch_id: str, **kwargs) -> None:
    allowed = {"status", "anomaly_count", "message", "completed_at", "row_count"}
    sets, params = [], []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k}=%s")
            params.append(v)
    if not sets:
        return
    params.append(batch_id)
    db.execute(f"UPDATE prediction_ingest_batch SET {','.join(sets)} WHERE batch_id=%s", params)


def save_dataset_version(org_id: str, start: date, end: date, row_count: int,
                         content: str, note: str = "") -> str:
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()
    existing = db.fetch_one(
        "SELECT version_id FROM prediction_dataset_version "
        "WHERE org_id=%s AND content_hash=%s ORDER BY created_at LIMIT 1",
        (org_id, h),
    )
    if existing:
        return existing["version_id"]
    version_id = f"DV-{org_id}-{end.strftime('%Y%m')}-{uuid.uuid4().hex[:8]}"
    db.execute(
        """INSERT INTO prediction_dataset_version
           (version_id,org_id,start_period,end_period,row_count,content_hash,note)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (version_id, org_id, start, end, row_count, h, note),
    )
    return version_id


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
def insert_anomalies(rows: List[dict]) -> int:
    if not rows:
        return 0
    sql = """
    INSERT INTO prediction_anomaly
      (org_id,period,var_id,detect_batch_id,channel,score,score_percentile,level,
       category,confidence,suggested_disposition,status,final_disposition,value,reference_value,
       evidence,reviewer,reviewed_at,review_note,algorithm_version,raw_score,resid_score,
       joint_score,channels,context_flags,breakpoint_date,breakpoint_stat,shift_pct,cv_ratio,
       in_breakpoint_window)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
      score=VALUES(score), score_percentile=VALUES(score_percentile), level=VALUES(level),
      category=VALUES(category), confidence=VALUES(confidence),
      suggested_disposition=VALUES(suggested_disposition),
      final_disposition=VALUES(final_disposition), evidence=VALUES(evidence),
      algorithm_version=VALUES(algorithm_version), raw_score=VALUES(raw_score),
      resid_score=VALUES(resid_score), joint_score=VALUES(joint_score),
      channels=VALUES(channels), context_flags=VALUES(context_flags),
      breakpoint_date=VALUES(breakpoint_date), breakpoint_stat=VALUES(breakpoint_stat),
      shift_pct=VALUES(shift_pct), cv_ratio=VALUES(cv_ratio),
      in_breakpoint_window=VALUES(in_breakpoint_window)
    """
    def n(v):
        try:
            f = float(v)
            return f if np.isfinite(f) else None
        except (TypeError, ValueError):
            return None

    vals = [(
        r["org_id"], r["period"], r["var_id"], r["detect_batch_id"],
        r.get("channel") or r.get("channels") or "stl_residual",
        n(r.get("score")), n(r.get("score_percentile")), r.get("level"), r.get("category"),
        n(r.get("confidence")), r.get("suggested_disposition"), r.get("status", "pending"),
        r.get("final_disposition"),
        n(r.get("value")), n(r.get("reference_value")), r.get("evidence"),
        r.get("reviewer"), r.get("reviewed_at"), r.get("review_note"),
        r.get("algorithm_version", "v2"), n(r.get("raw_score")), n(r.get("resid_score")),
        n(r.get("joint_score")), r.get("channels"), r.get("context_flags"),
        r.get("breakpoint_date"), n(r.get("breakpoint_stat")), n(r.get("shift_pct")),
        n(r.get("cv_ratio")), int(r.get("in_breakpoint_window", 0)),
    ) for r in rows]
    return db.execute_many(sql, vals)


def insert_watch(rows: List[dict]) -> int:
    if not rows:
        return 0
    sql = """
    INSERT INTO prediction_anomaly_watch
      (org_id,period,var_id,level,category,score,raw_score,resid_score,joint_score,
       channels,context_flags,evidence,algorithm_version)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
      level=VALUES(level),category=VALUES(category),score=VALUES(score),
      raw_score=VALUES(raw_score),resid_score=VALUES(resid_score),
      joint_score=VALUES(joint_score),channels=VALUES(channels),
      context_flags=VALUES(context_flags),evidence=VALUES(evidence)
    """
    def n(v):
        try:
            f = float(v)
            return f if np.isfinite(f) else None
        except (TypeError, ValueError):
            return None

    vals = [(
        r["org_id"], r["period"], r["var_id"], r.get("level", "关注"),
        r.get("category"), n(r.get("score")), n(r.get("raw_score")),
        n(r.get("resid_score")), n(r.get("joint_score")),
        r.get("channels"), r.get("context_flags"), r.get("evidence"),
        r.get("algorithm_version", "v2"),
    ) for r in rows]
    return db.execute_many(sql, vals)


def load_watch(org_id: str | None = None, limit: int = 500) -> List[dict]:
    sql = "SELECT * FROM prediction_anomaly_watch WHERE 1=1"
    params: list[Any] = []
    if org_id:
        sql += " AND org_id=%s"; params.append(org_id)
    sql += " ORDER BY period DESC, id DESC LIMIT %s"; params.append(limit)
    return db.fetch_all(sql, params)


def insert_calibration(rows: List[dict]) -> int:
    if not rows:
        return 0
    sql = """
    INSERT INTO prediction_anomaly_calibration
      (run_id,org_id,var_id,quantile,threshold_value,precision_v,recall_v,f1,
       n_pos,n_neg,selected,note)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
      threshold_value=VALUES(threshold_value),precision_v=VALUES(precision_v),
      recall_v=VALUES(recall_v),f1=VALUES(f1),selected=VALUES(selected),note=VALUES(note)
    """
    vals = [(
        r["run_id"], r["org_id"], r["var_id"], r["quantile"], r.get("threshold_value"),
        r.get("precision_v"), r.get("recall_v"), r.get("f1"), r.get("n_pos", 0),
        r.get("n_neg", 0), int(r.get("selected", 0)), r.get("note"),
    ) for r in rows]
    return db.execute_many(sql, vals)


def load_anomalies(org_id: str | None = None, status: str | None = None,
                   limit: int = 500) -> List[dict]:
    sql = "SELECT * FROM prediction_anomaly WHERE 1=1"
    params: list[Any] = []
    if org_id:
        sql += " AND org_id=%s"; params.append(org_id)
    if status:
        sql += " AND status=%s"; params.append(status)
    sql += " ORDER BY period DESC, id DESC LIMIT %s"; params.append(limit)
    return db.fetch_all(sql, params)


def get_anomaly(anomaly_id: int) -> Optional[dict]:
    return db.fetch_one("SELECT * FROM prediction_anomaly WHERE id=%s", (anomaly_id,))


def update_anomaly(anomaly_id: int, **kwargs) -> None:
    allowed = {"status", "final_disposition", "correction_value", "reviewer",
               "reviewed_at", "review_note", "category", "confidence"}
    sets, params = [], []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k}=%s"); params.append(v)
    if not sets:
        return
    params.append(anomaly_id)
    db.execute(f"UPDATE prediction_anomaly SET {','.join(sets)} WHERE id=%s", params)


def insert_anomaly_audit(anomaly_id: int, action: str, before: float | None,
                         after: float | None, operator: str, note: str | None) -> None:
    db.execute(
        """INSERT INTO prediction_anomaly_audit
           (anomaly_id,action,before_value,after_value,operator,note)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (anomaly_id, action, before, after, operator, note),
    )


# ---------------------------------------------------------------------------
# GRA
# ---------------------------------------------------------------------------
def _finite_or_none(v):
    try:
        return float(v) if v is not None and np.isfinite(float(v)) else None
    except Exception:
        return None


def insert_gra_results(df: pd.DataFrame, run_id: str) -> int:
    rows = []
    for r in df.itertuples(index=False):
        rows.append((
            run_id, r.org_id, r.var_id, r.var_name,
            _finite_or_none(r.r), _finite_or_none(r.r_detrend), int(r.rank_no),
            int(r.selected), int(r.spurious), int(r.rho_sensitive), int(r.borderline),
            r.direction, r.note,
        ))
    sql = """
    INSERT INTO prediction_gra_result
      (run_id,org_id,var_id,var_name,r,r_detrend,rank_no,selected,spurious,
       rho_sensitive,borderline,direction,note)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
      r=VALUES(r), r_detrend=VALUES(r_detrend), rank_no=VALUES(rank_no),
      selected=VALUES(selected), spurious=VALUES(spurious),
      rho_sensitive=VALUES(rho_sensitive), borderline=VALUES(borderline),
      direction=VALUES(direction), note=VALUES(note)
    """
    return db.execute_many(sql, rows)


def load_gra_results(org_id: str, run_id: str | None = None) -> List[dict]:
    if run_id:
        return db.fetch_all(
            "SELECT * FROM prediction_gra_result WHERE org_id=%s AND run_id=%s ORDER BY rank_no",
            (org_id, run_id),
        )
    row = db.fetch_one(
        "SELECT run_id FROM prediction_gra_result WHERE org_id=%s ORDER BY created_at DESC LIMIT 1",
        (org_id,),
    )
    if not row:
        return []
    return db.fetch_all(
        "SELECT * FROM prediction_gra_result WHERE org_id=%s AND run_id=%s ORDER BY rank_no",
        (org_id, row["run_id"]),
    )


# ---------------------------------------------------------------------------
# 模型
# ---------------------------------------------------------------------------
def insert_model(m: dict) -> None:
    db.execute(
        """INSERT INTO prediction_model
           (model_id,org_id,model_type,version,status,is_champion,target_var,window_size,
            horizon,feature_order,hyperparams,scaler_state,metrics,train_start,train_end,
            n_samples,artifact_path,data_version,trained_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE status=VALUES(status),is_champion=VALUES(is_champion),
             metrics=VALUES(metrics),artifact_path=VALUES(artifact_path)""",
        (m["model_id"], m["org_id"], m["model_type"], m["version"], m.get("status", "candidate"),
         int(m.get("is_champion", 0)), m.get("target_var", "CO2_COMPARABLE"),
         m["window_size"], m["horizon"], db.j(m["feature_order"]), db.j(m["hyperparams"]),
         db.j(m["scaler_state"]), db.j(m["metrics"]), m["train_start"], m["train_end"],
         m["n_samples"], m["artifact_path"], m.get("data_version"), m.get("trained_by")),
    )


def promote_champion(org_id: str, model_id: str) -> None:
    with db.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE prediction_model SET is_champion=0,status='deprecated' "
                "WHERE org_id=%s AND model_id<>%s",
                (org_id, model_id),
            )
            cur.execute(
                "UPDATE prediction_model SET is_champion=1,status='active' WHERE model_id=%s",
                (model_id,),
            )


def load_champion(org_id: str) -> Optional[dict]:
    return db.fetch_one(
        "SELECT * FROM prediction_model WHERE org_id=%s AND is_champion=1 ORDER BY trained_at DESC LIMIT 1",
        (org_id,),
    )


def load_models(org_id: str | None = None) -> List[dict]:
    if org_id:
        return db.fetch_all(
            "SELECT * FROM prediction_model WHERE org_id=%s ORDER BY trained_at DESC", (org_id,)
        )
    return db.fetch_all("SELECT * FROM prediction_model ORDER BY trained_at DESC")


# ---------------------------------------------------------------------------
# 预测
# ---------------------------------------------------------------------------
def insert_forecasts(rows: List[dict]) -> int:
    if not rows:
        return 0
    sql = """
    INSERT INTO prediction_forecast
      (model_id,org_id,period,scenario,target_var,point,lower_bound,upper_bound,
       reported_point,comparable_point,confidence_level)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
      point=VALUES(point), lower_bound=VALUES(lower_bound), upper_bound=VALUES(upper_bound),
      reported_point=VALUES(reported_point), comparable_point=VALUES(comparable_point),
      confidence_level=VALUES(confidence_level)
    """
    vals = [(
        r["model_id"], r["org_id"], r["period"], r.get("scenario", "BAU"),
        r.get("target_var", "CO2_COMPARABLE"), r["point"], r.get("lower_bound"),
        r.get("upper_bound"), r.get("reported_point"), r.get("comparable_point"),
        r.get("confidence_level", 0.90),
    ) for r in rows]
    return db.execute_many(sql, vals)


def load_forecasts(org_id: str, scenario: str = "BAU",
                   start: str | None = None, end: str | None = None) -> List[dict]:
    sql = "SELECT * FROM prediction_forecast WHERE org_id=%s AND scenario=%s"
    params: list[Any] = [org_id, scenario]
    if start:
        sql += " AND period>=%s"; params.append(start)
    if end:
        sql += " AND period<=%s"; params.append(end)
    sql += " ORDER BY period"
    return db.fetch_all(sql, params)


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------
def create_job(job_id: str, job_type: str, params: dict, operator: str) -> None:
    db.execute(
        "INSERT INTO prediction_job(job_id,job_type,status,params,operator) VALUES(%s,%s,'queued',%s,%s)",
        (job_id, job_type, db.j(params), operator),
    )


def update_job(job_id: str, status: str, result: Any = None, error: str | None = None) -> None:
    if status == "running":
        db.execute("UPDATE prediction_job SET status='running',started_at=NOW() WHERE job_id=%s", (job_id,))
    elif status in ("succeeded", "failed"):
        db.execute(
            "UPDATE prediction_job SET status=%s,result=%s,error=%s,finished_at=NOW() WHERE job_id=%s",
            (status, db.j(result) if result is not None else None, error, job_id),
        )
    else:
        db.execute("UPDATE prediction_job SET status=%s WHERE job_id=%s", (status, job_id))


def get_job(job_id: str) -> Optional[dict]:
    return db.fetch_one("SELECT * FROM prediction_job WHERE job_id=%s", (job_id,))


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------
def log(action: str, entity: str, entity_id: str | None, operator: str | None, detail: Any = None) -> None:
    db.audit(action, entity, entity_id, operator, detail)
