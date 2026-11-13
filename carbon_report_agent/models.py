from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FuelType = Literal["natural_gas", "gasoline", "diesel"]
FuelUnit = Literal["10k_m3", "t"]
ReportTableRole = Literal[
    "workload_monthly",
    "electricity_internal_detail",
    "electricity_balance_detail",
    "appendix_emission_summary",
    "appendix_fuel",
    "appendix_electricity",
    "appendix_heat",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportMetadata(StrictModel):
    entity_name: str
    report_title: str = ""
    template_name: str = ""
    period_start: date | None = None
    period_end: date | None = None
    report_year: int = Field(ge=2000, le=2100)
    report_month: int | None = Field(default=None, ge=1, le=12)
    report_period: str
    compiler: str
    compile_date: date
    reviewer: str = ""
    approver: str = ""
    validator: str = ""
    checker: str = ""
    authors: str = ""
    report_number: str = ""
    header_text: str = ""


class EntityProfile(StrictModel):
    short_name: str
    business_description: str
    carbon_department: str
    company_overview: str = ""
    process_description: str = ""
    monitoring_note: str = ""


class EmissionSourceRow(StrictModel):
    category: str = ""
    facility: str = ""
    location: str = ""
    source: str = ""


class OrganizationBoundary(StrictModel):
    boundary_description: str = ""
    emission_sources: list[str] = []
    emission_source_rows: list[EmissionSourceRow] = []
    accounting_method: str = ""


class EmissionBoundaryNotes(StrictModel):
    fuel_boundary_exclusion: str = ""


class ActivityNaturalGasProse(StrictModel):
    usage: str = ""
    metering_method: str = ""
    source_documents: list[str] = []
    unit_note: str = ""
    standard_condition_note: str = ""
    change_note: str = ""


class ActivityLiquidFuelProse(StrictModel):
    usage: str = ""
    metering_method: str = ""
    source_documents: list[str] = []


class ActivityElectricityProse(StrictModel):
    non_fossil_power_note: str = ""
    grid_source: str = ""
    source_documents: list[str] = []
    settlement_note: str = ""


class ActivityHeatProse(StrictModel):
    contract_note: str = ""
    payment_method: str = ""
    estimation_method: str = ""
    no_resale_note: str = ""
    source_documents: list[str] = []


class ActivityProseContext(StrictModel):
    natural_gas: ActivityNaturalGasProse = Field(default_factory=ActivityNaturalGasProse)
    liquid_fuel: ActivityLiquidFuelProse = Field(default_factory=ActivityLiquidFuelProse)
    electricity: ActivityElectricityProse = Field(default_factory=ActivityElectricityProse)
    heat: ActivityHeatProse = Field(default_factory=ActivityHeatProse)


class Chapter6EmissionIntensity(StrictModel):
    applicable: bool | None = None
    unit: str = ""
    current_year_value: float | None = None
    prior_year_value: float | None = None
    change_percent: float | None = None
    analysis: str = ""
    not_applicable_note: str = ""


class Chapter6TrendYear(StrictModel):
    year: int = Field(ge=2000, le=2100)
    total_emissions_tco2: float = Field(ge=0)
    fuel_combustion_tco2: float | None = Field(default=None, ge=0)
    electricity_emissions_tco2: float | None = Field(default=None, ge=0)
    heat_emissions_tco2: float | None = Field(default=None, ge=0)
    workload: float | None = Field(default=None, ge=0)
    workload_unit: str = ""


class Chapter6ProseContext(StrictModel):
    emission_intensity: Chapter6EmissionIntensity = Field(default_factory=Chapter6EmissionIntensity)
    trend_years: list[Chapter6TrendYear] = []


class EquipmentItem(StrictModel):
    name: str
    category: str = ""
    quantity: float | None = None
    unit: str = ""
    model: str = ""
    energy_type: str = ""
    remark: str = ""


class WorkloadRecord(StrictModel):
    name: str
    quantity: float = 0
    unit: str = ""


class SourceActivityRecord(StrictModel):
    source_emission_tco2: float | None = Field(default=None, ge=0)
    factor_tco2_per_unit: float | None = Field(default=None, ge=0)
    data_origin: str = ""
    override_reason: str = ""


class FuelActivityRecord(SourceActivityRecord):
    fuel_type: FuelType
    facility: str
    quantity: float = Field(ge=0)
    unit: FuelUnit
    month: int | None = Field(default=None, ge=1, le=12)
    year: int | None = Field(default=None, ge=2000, le=2100)
    source_name: str


class ElectricityActivityRecord(SourceActivityRecord):
    scope: str
    quantity_mwh: float = Field(ge=0)
    month: int | None = Field(default=None, ge=1, le=12)
    year: int | None = Field(default=None, ge=2000, le=2100)
    source_name: str


class HeatActivityRecord(SourceActivityRecord):
    site: str
    quantity_gj: float = Field(ge=0)
    source_name: str
    month: int | None = Field(default=None, ge=1, le=12)
    year: int | None = Field(default=None, ge=2000, le=2100)
    heating_area_m2: float | None = Field(default=None, ge=0)
    heat_coefficient: float | None = Field(default=None, ge=0)


class ReportImage(StrictModel):
    role: str
    caption: str = ""
    url: str | None = None
    mime_type: str = "image/png"


class ReportTablePayload(StrictModel):
    role: ReportTableRole
    caption: str = ""
    rows: list[list[str | int | float | None]]


class MonitoringDevice(StrictModel):
    name: str
    model: str = ""
    accuracy: str = ""
    measurement_range: str = ""
    location: str = ""
    calibration_frequency: str = ""
    actual_calibration_frequency: str = ""
    calibration_time: str = ""
    guide_compliant: str = ""


class PriorYearComparison(StrictModel):
    period_start: date | None = None
    period_end: date | None = None
    source_label: str = ""
    report_year: int = Field(ge=2000, le=2100)
    report_month: int | None = Field(default=None, ge=1, le=12)
    total_emissions_tco2: float = Field(ge=0)
    fuel_combustion_tco2: float | None = Field(default=None, ge=0)
    electricity_emissions_tco2: float | None = Field(default=None, ge=0)
    heat_emissions_tco2: float | None = Field(default=None, ge=0)


class SnapshotFuelFactor(StrictModel):
    carbon_content: float | None = None
    oxidation_rate: float | None = None
    expected_unit: FuelUnit
    ncv: float = 0.0
    emission_factor: float | None = None
    source: str = ""
    name: str = ""
    fuel_type: FuelType | None = None


    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_value(cls, data):
        # Older Java snapshots sent both the internal value and emission_factor.
        # Accept only this documented alias; retain extra="forbid" for all other fields.
        if not isinstance(data, dict) or "value" not in data:
            return data
        normalized = dict(data)
        legacy = normalized.pop("value")
        current = normalized.get("emission_factor")
        if current is None:
            normalized["emission_factor"] = legacy
        elif legacy is not None:
            try:
                equal = Decimal(str(current)) == Decimal(str(legacy))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("燃料因子value与emission_factor不是有效数值") from exc
            if not equal:
                raise ValueError("燃料因子value与emission_factor冲突，不能选择其中一个继续生成")
        return normalized


class SnapshotFactors(StrictModel):
    version: str = ""
    source: str = ""
    electricity_factor_tco2_per_mwh: float | None = None
    heat_factor_tco2_per_gj: float | None = None
    fuel_factors: dict[str, SnapshotFuelFactor] = Field(default_factory=dict)


class SourcePeriod(StrictModel):
    start: str
    end: str
    partial: bool = False


class ReportInput(StrictModel):
    entity_code: str = "suning"
    metadata: ReportMetadata
    entity_profile: EntityProfile
    period_grain: Literal["year", "month", "range"] = "year"
    period_contract_version: int = Field(default=0, ge=0, le=1)
    organization_boundary: OrganizationBoundary | None = None
    emission_boundary_notes: EmissionBoundaryNotes = Field(default_factory=EmissionBoundaryNotes)
    activity_prose: ActivityProseContext = Field(default_factory=ActivityProseContext)
    equipment: list[EquipmentItem] = []
    workload: list[WorkloadRecord] = []
    prior_year: PriorYearComparison | None = None
    prior_month: PriorYearComparison | None = None
    fuel_activity: list[FuelActivityRecord]
    electricity_activity: list[ElectricityActivityRecord]
    monthly_fuel_activity: list[FuelActivityRecord] = Field(default_factory=list)
    monthly_electricity_activity: list[ElectricityActivityRecord] = Field(default_factory=list)
    heat_activity: list[HeatActivityRecord]
    monitoring_devices: list[MonitoringDevice]
    report_tables: list[ReportTablePayload] = []
    images: list[ReportImage] = []
    chapter6: Chapter6ProseContext = Field(default_factory=Chapter6ProseContext)
    render_contract_version: str = ""
    source_period: SourcePeriod | None = None
    factors: SnapshotFactors | None = None

    @model_validator(mode="after")
    def validate_period_contract(self):
        if not self.period_contract_version:
            if self.period_grain == "range":
                raise ValueError("期间报告必须包含版本化的起止日期")
            return self
        from calendar import monthrange
        from datetime import timedelta
        meta = self.metadata
        start, end = meta.period_start, meta.period_end
        if not start or not end or start > end or not meta.report_title:
            raise ValueError("报告名称和有效起止日期不可缺失")
        grain = "year" if start == date(start.year, 1, 1) and end == date(start.year, 12, 31) else "month" if start.day == 1 and start.year == end.year and start.month == end.month and end.day == monthrange(end.year, end.month)[1] else "range"
        if self.period_grain != grain or meta.report_year != end.year:
            raise ValueError("报告期间类型与实际起止日期不一致")
        if grain == "month" and meta.report_month != start.month:
            raise ValueError("报告月份与实际期间不一致")
        if self.source_period and (self.source_period.start != start.isoformat() or self.source_period.end != end.isoformat()):
            raise ValueError("报告期间与核算来源期间不一致")
        if grain == "range" and (self.prior_year or self.prior_month):
            raise ValueError("非完整自然年月的报告不支持自动对比")
        if grain == "year" and self.prior_month:
            raise ValueError("年报不支持月环比")
        for slot, prior in (("yoy", self.prior_year), ("mom", self.prior_month)):
            if prior is None:
                continue
            if slot == "mom":
                expected_end = start - timedelta(days=1)
                expected_start = expected_end.replace(day=1)
            elif grain == "year":
                expected_start, expected_end = date(start.year - 1, 1, 1), date(start.year - 1, 12, 31)
            else:
                expected_start = date(start.year - 1, start.month, 1)
                expected_end = expected_start.replace(day=monthrange(expected_start.year, expected_start.month)[1])
            if prior.period_start != expected_start or prior.period_end != expected_end:
                raise ValueError("对比数据未精确覆盖对应基期")
        return self
