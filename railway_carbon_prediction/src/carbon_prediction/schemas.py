"""API 请求/响应模型（Pydantic v2）。"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_period(v: str) -> str:
    if not PERIOD_RE.match(v):
        raise ValueError("period 必须为 YYYY-MM 格式")
    return v


class ActivityRecordIn(BaseModel):
    org_id: str = Field(..., examples=["JLG"])
    period: str = Field(..., examples=["2026-01"])
    var_id: str = Field(..., examples=["ELEC_TOTAL"])
    value: Optional[float] = Field(None, allow_inf_nan=False, description="物理/可比口径值；缺失可传 null")
    reported_value: Optional[float] = Field(None, allow_inf_nan=False, description="报表口径值；热力口径切换时使用")
    unit: Optional[str] = None
    source_status: str = "原始"
    is_estimated: bool = False

    _period = field_validator("period")(validate_period)

    @field_validator("value", "reported_value")
    @classmethod
    def non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("活动量不得为负")
        return v


class MonthlyHeatSource(BaseModel):
    kind: Literal["measured", "area"]
    amount: Decimal = Field(ge=0, allow_inf_nan=False)


class MonthlySourceSnapshot(BaseModel):
    version: int = Field(gt=0)
    org_id: Literal["JLG", "SNF", "YPF"]
    period: str
    operation_type: Literal[1, 2]
    complete: bool
    missing: List[str] = Field(default_factory=list)
    heat_sources: List[MonthlyHeatSource] = Field(default_factory=list)

    _period = field_validator("period")(validate_period)


class IngestRequest(BaseModel):
    records: List[ActivityRecordIn]
    idempotency_key: Optional[str] = Field(None, max_length=64)
    operator: str = "system"
    run_anomaly: bool = True
    factor_version: Optional[str] = Field(
        None, max_length=128,
        description="可选：调用方期望的因子版本；与当前解析版本不一致时返回 409",
    )
    override: bool = Field(False, description="是否显式覆盖同月已入库数据")
    override_reason: Optional[str] = Field(None, max_length=512, description="覆盖原因")
    source_snapshot: Optional[MonthlySourceSnapshot] = None

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.source_snapshot is None:
            if not self.records:
                raise ValueError("records 不能为空")
        elif self.idempotency_key != f"carbon-month-{self.source_snapshot.version}":
            raise ValueError("月度快照需要稳定的版本幂等键")
        return self


class ReviewRequest(BaseModel):
    action: Literal["keep", "correct", "exclude", "mark_breakpoint"]
    correction_value: Optional[float] = None
    reviewer: str = Field(..., min_length=1)
    note: Optional[str] = None

    @field_validator("correction_value")
    @classmethod
    def non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("修正值不得为负")
        return v


class TrainRequest(BaseModel):
    org_ids: List[str] = Field(default_factory=lambda: ["JLG", "SNF", "YPF"])
    mode: Literal["auto", "full", "finetune"] = "auto"
    as_of: Optional[str] = None
    force: bool = False
    operator: str = "system"

    @field_validator("as_of")
    @classmethod
    def period_optional(cls, v: Optional[str]) -> Optional[str]:
        return validate_period(v) if v else v


class ForecastRequest(BaseModel):
    org_ids: List[str] = Field(default_factory=lambda: ["JLG", "SNF", "YPF"])
    horizon: int = Field(12, ge=1, le=12)
    scenario: str = "BAU"
    as_of: Optional[str] = None
    write_db: bool = True
    operator: str = "system"
    # Long-running model recovery/training must be submitted as a job so that
    # clients do not hold an HTTP request open while the forecast is generated.
    async_run: bool = False

    @field_validator("as_of")
    @classmethod
    def period_optional(cls, v: Optional[str]) -> Optional[str]:
        return validate_period(v) if v else v


class GraRequest(BaseModel):
    org_ids: List[str] = Field(default_factory=lambda: ["JLG", "SNF", "YPF"])
    as_of: Optional[str] = None
    operator: str = "system"

    @field_validator("as_of")
    @classmethod
    def period_optional(cls, v: Optional[str]) -> Optional[str]:
        return validate_period(v) if v else v


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Any = None
    trace_id: Optional[str] = None


class PolicyFactorIn(BaseModel):
    factor_id: str
    factor_name: str
    period: str
    value: float
    unit: str
    category: str = "policy"
    source_level: str = "national"
    source_status: str = "原始"
    is_scenario_only: bool = False
    data_source: Optional[str] = None

    _period = field_validator("period")(validate_period)


class PolicyFactorBatchIn(BaseModel):
    factors: List[PolicyFactorIn]
    operator: str = "system"


class EmissionFactorIn(BaseModel):
    """排放因子主数据写入项；按 var_id + effective_from 唯一切片。"""

    var_id: str = Field(..., max_length=32, examples=["ELEC_TOTAL"])
    factor_value: float = Field(..., ge=0)
    factor_unit: str = Field(..., max_length=32, examples=["tCO2/MWh"])
    effective_from: date
    effective_to: Optional[date] = None
    factor_version: str = Field(..., min_length=1, max_length=64, examples=["EF-ELEC-2026"])
    factor_source: Optional[str] = Field(None, max_length=64)
    is_caliber_change: bool = False
    policy_basis: Optional[str] = Field(None, max_length=512)

    @model_validator(mode="after")
    def valid_effective_range(self):
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to 不得早于 effective_from")
        return self


class EmissionFactorBatchIn(BaseModel):
    factors: List[EmissionFactorIn] = Field(..., min_length=1)
    operator: str = "system"


class CaliberRuleIn(BaseModel):
    """供热面积系数/电网因子等口径规则写入项。"""

    rule_id: str = Field(..., max_length=64)
    org_id: str = Field(..., max_length=16, examples=["SNF"])
    rule_type: Literal["heat_area_factor", "grid_factor"]
    effective_from: date
    effective_to: Optional[date] = None
    rule_value: float = Field(..., ge=0)
    unit: str = Field(..., max_length=32, examples=["GJ/m2"])
    rule_version: str = Field(..., min_length=1, max_length=64)
    source: Optional[str] = Field(None, max_length=512)
    note: Optional[str] = Field(None, max_length=512)

    @model_validator(mode="after")
    def valid_effective_range(self):
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to 不得早于 effective_from")
        return self


class CaliberRuleBatchIn(BaseModel):
    rules: List[CaliberRuleIn] = Field(..., min_length=1)
    operator: str = "system"


class JobOut(BaseModel):
    job_id: str
    job_type: str
    status: str
    params: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
