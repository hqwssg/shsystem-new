"""FastAPI 服务：供大平台集成的预测模块接口。

统一响应：{code, message, data, trace_id}
鉴权：X-API-Key（默认 dev-key，生产通过环境变量覆盖）
幂等：POST /ingest/monthly 支持 idempotency_key
异步：训练任务返回 job_id，通过 /jobs/{job_id} 轮询
"""
from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db, monthly_source, pipeline, repository
from .config import settings
from .factors import (FactorAmbiguous, FactorError, FactorNotFound,
                      FactorResolver, FactorVersionConflict)
from .ingest_guard import IdempotencyConflict, MonthAlreadyIngested
from .schemas import (ApiResponse, CaliberRuleBatchIn, EmissionFactorBatchIn,
                      ForecastRequest, GraRequest, IngestRequest,
                      PolicyFactorBatchIn, ReviewRequest, TrainRequest)

app = FastAPI(
    title="铁路碳排放趋势预测模块",
    description="孤立森林异常检测 → 灰色关联筛选 → 滑动窗口 LSTM；支持月度增量接入、异常复核与未来一年预测。",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.cors_origins.split(",")] if settings.cors_origins != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="prediction-job")


def _trace() -> str:
    return uuid.uuid4().hex[:16]


def _ok(data: Any, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": jsonable_encoder(data), "trace_id": _trace()}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def require_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="无效的 X-API-Key")
    return True


@app.exception_handler(Exception)
async def unhandled_exception(request, exc: Exception):
    return JSONResponse(status_code=500, content={
        "code": 500, "message": f"服务内部错误: {type(exc).__name__}: {exc}",
        "data": None, "trace_id": _trace(),
    })


# ---------------------------------------------------------------------------
# 健康检查 / 元数据
# ---------------------------------------------------------------------------
@app.get("/health", tags=["system"])
def health():
    try:
        info = db.healthcheck()
        return _ok({"status": "UP", **info, "version": "1.0.0"})
    except Exception as exc:
        return JSONResponse(status_code=503, content={
            "code": 503, "message": f"数据库不可用: {exc}", "data": None, "trace_id": _trace()
        })


@app.get(f"{settings.api_prefix}/orgs", tags=["metadata"], dependencies=[Depends(require_key)])
def orgs():
    return _ok(repository.get_orgs())


@app.get(f"{settings.api_prefix}/vars", tags=["metadata"], dependencies=[Depends(require_key)])
def vars_meta():
    return _ok(repository.get_vars())


@app.get(f"{settings.api_prefix}/series", tags=["data"], dependencies=[Depends(require_key)])
def series(org_id: str = Query(...), start: str | None = None, end: str | None = None):
    sql = "SELECT * FROM prediction_v_carbon_monthly WHERE org_id=%s"
    params: list[Any] = [org_id]
    if start:
        sql += " AND period>=%s"; params.append(start)
    if end:
        sql += " AND period<=%s"; params.append(end)
    sql += " ORDER BY period"
    return _ok(_jsonable(db.fetch_all(sql, params)))


# ---------------------------------------------------------------------------
# GRA
# ---------------------------------------------------------------------------
@app.get(f"{settings.api_prefix}/gra", tags=["gra"], dependencies=[Depends(require_key)])
def get_gra(org_id: str = Query(...), run_id: str | None = None):
    return _ok(_jsonable(repository.load_gra_results(org_id, run_id)))


@app.post(f"{settings.api_prefix}/gra/run", tags=["gra"], dependencies=[Depends(require_key)])
def run_gra(req: GraRequest):
    import pandas as pd
    from . import gra
    out = {}
    for org_id in req.org_ids:
        res, selected, run_id = gra.run_for_org(org_id, train_end=req.as_of or "2025-12")
        repository.insert_gra_results(res, run_id)
        out[org_id] = {"run_id": run_id, "selected": selected,
                       "results": _jsonable(res.to_dict(orient="records"))}
    return _ok(out)


# ---------------------------------------------------------------------------
# 训练（异步）
# ---------------------------------------------------------------------------
def _run_train_job(job_id: str, req: TrainRequest):
    repository.update_job(job_id, "running")
    try:
        result = pipeline.train_all(mode=req.mode, as_of=req.as_of or "2025-12",
                                    org_ids=req.org_ids, operator=req.operator)
        repository.update_job(job_id, "succeeded", result=result)
    except Exception as exc:
        repository.update_job(job_id, "failed", error=f"{type(exc).__name__}: {exc}")


def _run_forecast_job(job_id: str, req: ForecastRequest):
    repository.update_job(job_id, "running")
    try:
        result = pipeline.forecast_all(horizon=req.horizon, scenario=req.scenario,
                                       as_of=req.as_of, org_ids=req.org_ids,
                                       write_db=req.write_db, operator=req.operator)
        repository.update_job(job_id, "succeeded", result=result)
    except Exception as exc:
        repository.update_job(job_id, "failed", error=f"{type(exc).__name__}: {exc}")


@app.post(f"{settings.api_prefix}/train", tags=["training"], dependencies=[Depends(require_key)])
def train(req: TrainRequest):
    job_id = f"JOB-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    repository.create_job(job_id, "TRAIN", req.model_dump(), req.operator)
    _executor.submit(_run_train_job, job_id, req)
    return _ok({"job_id": job_id, "status": "queued"}, "训练任务已提交")


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}", tags=["training"], dependencies=[Depends(require_key)])
def job(job_id: str):
    row = repository.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _ok(_jsonable(row))


# ---------------------------------------------------------------------------
# 预测
# ---------------------------------------------------------------------------
@app.post(f"{settings.api_prefix}/forecast", tags=["forecast"], dependencies=[Depends(require_key)])
def forecast(req: ForecastRequest):
    if req.async_run:
        job_id = f"JOB-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        repository.create_job(job_id, "FORECAST", req.model_dump(), req.operator)
        _executor.submit(_run_forecast_job, job_id, req)
        return _ok({"job_id": job_id, "status": "queued"}, "预测任务已提交")
    result = pipeline.forecast_all(horizon=req.horizon, scenario=req.scenario,
                                   as_of=req.as_of, org_ids=req.org_ids,
                                   write_db=req.write_db, operator=req.operator)
    return _ok(result)


@app.get(f"{settings.api_prefix}/forecast", tags=["forecast"], dependencies=[Depends(require_key)])
def get_forecast(org_id: str = Query(...), scenario: str = "BAU",
                 start: str | None = None, end: str | None = None):
    return _ok(_jsonable(repository.load_forecasts(org_id, scenario, start, end)))


# ---------------------------------------------------------------------------
# 增量接入 / 异常复核
# ---------------------------------------------------------------------------
@app.post(f"{settings.api_prefix}/ingest/monthly", tags=["ingest"], dependencies=[Depends(require_key)])
def ingest(req: IngestRequest):
    try:
        result = monthly_source.ingest(req)
    except MonthAlreadyIngested as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FactorVersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc),
                            headers={"X-Prediction-Ingest-Error": "factor_version"}) from exc
    except FactorAmbiguous as exc:
        raise HTTPException(status_code=409, detail=str(exc),
                            headers={"X-Prediction-Ingest-Error": "factor_ambiguous"}) from exc
    except FactorNotFound as exc:
        raise HTTPException(status_code=422, detail=str(exc),
                            headers={"X-Prediction-Ingest-Error": "factor_missing"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _ok(result, "数据已接收" if result.get("status") != "pending_review" else "数据已接收，存在待复核异常")


@app.get(f"{settings.api_prefix}/ingest/monthly/capabilities", tags=["ingest"], dependencies=[Depends(require_key)])
def monthly_source_capabilities():
    db.fetch_one("SELECT 1 FROM prediction_monthly_source_head LIMIT 1")
    db.fetch_one("SELECT 1 FROM prediction_monthly_source_receipt LIMIT 1")
    return _ok({"source_snapshot": 1})


@app.get(f"{settings.api_prefix}/ingest/monthly/source/{{org_id}}/{{period}}", tags=["ingest"],
         dependencies=[Depends(require_key)])
def get_monthly_source(org_id: str, period: str):
    from .schemas import validate_period
    try:
        month = date.fromisoformat(validate_period(period) + "-01")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = db.fetch_one(
        """SELECT h.source_version,h.awaiting_source,h.batch_id,b.status,b.message
           FROM prediction_monthly_source_head h LEFT JOIN prediction_ingest_batch b ON h.batch_id=b.batch_id
           WHERE h.org_id=%s AND h.period=%s AND h.source_version>0""", (org_id, month))
    if result is None:
        raise HTTPException(status_code=404, detail="未找到核算月度快照")
    if result["awaiting_source"]:
        receipt = db.fetch_one(
            """SELECT response FROM prediction_monthly_source_receipt WHERE org_id=%s AND period=%s
               AND JSON_UNQUOTE(JSON_EXTRACT(response,'$.batch_id'))=%s ORDER BY source_version DESC LIMIT 1""",
            (org_id, month, result["batch_id"]))
        result["missing"] = json.loads(receipt["response"]).get("missing", []) if receipt else []
    return _ok(result)


@app.get(f"{settings.api_prefix}/anomalies", tags=["anomaly"], dependencies=[Depends(require_key)])
def anomalies(org_id: str | None = None, status: str | None = None, limit: int = 200):
    return _ok(_jsonable(repository.load_anomalies(org_id, status, limit)))


@app.get(f"{settings.api_prefix}/anomalies/watch", tags=["anomaly"],
         dependencies=[Depends(require_key)])
def anomaly_watch(org_id: str | None = None, limit: int = 500):
    """关注级监控：不进复核队列，供月度数据质量报告使用。"""
    return _ok(_jsonable(repository.load_watch(org_id, limit)))


@app.get(f"{settings.api_prefix}/anomalies/quality-report", tags=["anomaly"],
         dependencies=[Depends(require_key)])
def anomaly_quality_report(org_id: str | None = None, limit: int = 24):
    """按组织×月汇总复核级/监控级异常数量。"""
    where, params = "", []
    if org_id:
        where = " WHERE org_id=%s"
        params = [org_id]
    review = db.fetch_all(
        "SELECT org_id,DATE_FORMAT(period,'%%Y-%%m') month,COUNT(*) n,"
        "SUM(category='C3') c3,SUM(category='C2') c2,SUM(category='C1') c1 "
        f"FROM prediction_anomaly{where} GROUP BY org_id,month ORDER BY month DESC LIMIT %s",
        (*params, limit),
    )
    watch = db.fetch_all(
        "SELECT org_id,DATE_FORMAT(period,'%%Y-%%m') month,COUNT(*) n,"
        "SUM(category='C4') c4,SUM(category='C1') c1,SUM(category='C2') c2 "
        f"FROM prediction_anomaly_watch{where} GROUP BY org_id,month ORDER BY month DESC LIMIT %s",
        (*params, limit),
    )
    return _ok({"review": _jsonable(review), "watch": _jsonable(watch)})


@app.post(f"{settings.api_prefix}/anomalies/scan", tags=["anomaly"], dependencies=[Depends(require_key)])
def scan_anomalies(operator: str = "system"):
    return _ok(pipeline.run_anomaly_scan(operator=operator))


@app.post(f"{settings.api_prefix}/anomalies/{{anomaly_id}}/review", tags=["anomaly"],
          dependencies=[Depends(require_key)])
def review(anomaly_id: int, req: ReviewRequest):
    try:
        anomaly = repository.get_anomaly(anomaly_id)
        if anomaly is None:
            raise HTTPException(status_code=404, detail="异常记录不存在")
        with db.transaction():
            monthly_source.lock_month(anomaly["org_id"], anomaly["period"])
            return _ok(pipeline.review_anomaly(anomaly_id, req.action, req.reviewer,
                                               req.correction_value, req.note))
    except FactorError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# 模型 / 政策因子 / 看板
# ---------------------------------------------------------------------------
@app.get(f"{settings.api_prefix}/models", tags=["model"], dependencies=[Depends(require_key)])
def models(org_id: str | None = None, champion_only: bool = False):
    rows = repository.load_models(org_id)
    if champion_only:
        rows = [r for r in rows if int(r.get("is_champion") or 0) == 1]
    return _ok(_jsonable(rows))


@app.get(f"{settings.api_prefix}/models/{{model_id}}", tags=["model"], dependencies=[Depends(require_key)])
def model_detail(model_id: str):
    row = db.fetch_one("SELECT * FROM prediction_model WHERE model_id=%s", (model_id,))
    if not row:
        raise HTTPException(status_code=404, detail="模型不存在")
    return _ok(_jsonable(row))


@app.post(f"{settings.api_prefix}/policy/factors", tags=["policy"], dependencies=[Depends(require_key)])
def upsert_factors(req: PolicyFactorBatchIn):
    import pandas as pd
    rows = []
    for f in req.factors:
        rows.append({
            "factor_id": f.factor_id, "factor_name": f.factor_name,
            "period": f.period + "-01", "value": f.value, "unit": f.unit,
            "category": f.category, "source_level": f.source_level,
            "source_status": f.source_status, "is_scenario_only": int(f.is_scenario_only),
            "data_source": f.data_source,
        })
    n = repository.upsert_policy_factors(pd.DataFrame(rows))
    repository.log("UPSERT_POLICY_FACTORS", "prediction_policy_factor", None, req.operator, {"rows": n})
    return _ok({"rows": n})


@app.get(f"{settings.api_prefix}/factors", tags=["factor"], dependencies=[Depends(require_key)])
def get_factors(
    org_id: str = Query(..., description="组织编码"),
    period: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM"),
    var_id: Optional[str] = Query(None, description="品种；为空时返回全部必需因子"),
):
    """解析某组织某月生效的排放因子与供热面积系数。"""
    resolver = FactorResolver()
    try:
        if var_id:
            factor = resolver.resolve_factor(var_id, org_id, period)
            return _ok({
                "org_id": org_id, "period": period, "var_id": var_id,
                "factor": factor, "factor_version": factor["factor_version"],
            })
        return _ok(resolver.resolve_all(org_id, period))
    except FactorNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FactorAmbiguous as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/factors/coverage", tags=["factor"],
         dependencies=[Depends(require_key)])
def factor_coverage(
    org_id: str = Query(...),
    period: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
):
    """关账前检查：该组织该月所有必算因子是否齐全、是否冲突。"""
    return _ok(FactorResolver().coverage(org_id, period))


@app.post(f"{settings.api_prefix}/factors", tags=["factor"],
          dependencies=[Depends(require_key)])
def upsert_emission_factors(req: EmissionFactorBatchIn):
    """新增/更新排放因子；同一 var_id 的生效期不得重叠。"""
    rows = []
    var_map = repository.get_var_map()
    for f in req.factors:
        if f.var_id not in var_map:
            raise HTTPException(status_code=422, detail=f"未知品种 {f.var_id}")
        overlaps = db.fetch_all(
            "SELECT factor_id,effective_from FROM prediction_emission_factor "
            "WHERE var_id=%s AND effective_from<=%s "
            "AND (effective_to IS NULL OR effective_to>=%s)",
            (f.var_id, f.effective_to or date(9999, 12, 31), f.effective_from),
        )
        # 同一 var_id + effective_from 是更新，不算冲突；其他重叠一律拒绝
        conflicts = [x for x in overlaps if x["effective_from"] != f.effective_from]
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail=f"{f.var_id} 在 {f.effective_from} 起的生效期与已有因子 {conflicts[0]['factor_id']} 重叠",
            )
        rows.append(f.model_dump())
    n = repository.upsert_emission_factors(rows)
    repository.log("UPSERT_EMISSION_FACTORS", "prediction_emission_factor", None,
                   req.operator, {"rows": n, "versions": [f.factor_version for f in req.factors]})
    return _ok({"rows": n})


@app.post(f"{settings.api_prefix}/caliber-rules", tags=["factor"],
          dependencies=[Depends(require_key)])
def upsert_caliber_rules(req: CaliberRuleBatchIn):
    """新增/更新供热面积系数、电网因子等口径规则；同组织同类型不得重叠。"""
    rows = []
    org_ids = {"ALL"} | {o["org_id"] for o in repository.get_orgs()}
    for x in req.rules:
        if x.org_id not in org_ids:
            raise HTTPException(status_code=422, detail=f"未知组织 {x.org_id}")
        overlaps = db.fetch_all(
            "SELECT rule_id FROM prediction_caliber_rule "
            "WHERE org_id=%s AND rule_type=%s AND effective_from<=%s "
            "AND (effective_to IS NULL OR effective_to>=%s)",
            (x.org_id, x.rule_type, x.effective_to or date(9999, 12, 31), x.effective_from),
        )
        conflicts = [r for r in overlaps if r["rule_id"] != x.rule_id]
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail=f"{x.org_id}/{x.rule_type} 生效期与已有规则 {conflicts[0]['rule_id']} 重叠",
            )
        rows.append(x.model_dump())
    n = repository.upsert_caliber_rules(rows)
    repository.log("UPSERT_CALIBER_RULES", "prediction_caliber_rule", None,
                   req.operator, {"rows": n, "versions": [x.rule_version for x in req.rules]})
    return _ok({"rows": n})


@app.get(f"{settings.api_prefix}/dashboard/summary", tags=["dashboard"], dependencies=[Depends(require_key)])
def dashboard_summary():
    orgs_data = []
    for org in repository.get_orgs():
        org_id = org["org_id"]
        latest = db.fetch_one(
            "SELECT period,total_reported_tco2,total_comparable_tco2 FROM prediction_emission_monthly "
            "WHERE org_id=%s ORDER BY period DESC LIMIT 1", (org_id,))
        fc = db.fetch_one(
            "SELECT COUNT(*) n,SUM(point) point,SUM(reported_point) reported FROM prediction_forecast "
            "WHERE org_id=%s AND scenario='BAU'",
            (org_id,))
        pending = db.fetch_one(
            "SELECT COUNT(*) n FROM prediction_anomaly WHERE org_id=%s AND status='pending'", (org_id,))
        orgs_data.append({
            "org_id": org_id, "org_name": org["org_name"],
            "latest_actual": _jsonable(latest),
            "forecast_next_12m": _jsonable(fc),
            "pending_anomalies": int(pending["n"]) if pending else 0,
        })
    return _ok({"orgs": orgs_data, "generated_at": datetime.now().isoformat()})
