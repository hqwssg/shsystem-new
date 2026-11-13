from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from carbon_report_agent.factors import FactorLibrary
from carbon_report_agent.models import ReportInput

CO2_CARBON_MASS_RATIO = 44 / 12


class CalculationResult(BaseModel):
    factor_version: str
    fuel_emissions: dict[str, float]
    electricity_emissions_tco2: float
    heat_emissions_tco2: float
    total_emissions_tco2: float
    fuel_combustion_tco2: float
    shares: dict[str, float]
    activity_fuel_totals: dict[str, float]
    electricity_total_mwh: float
    heat_total_gj: float


def round_tco2(value: float) -> float:
    return round(value + 1e-9, 2)


def source_emission(record, quantity: float) -> float | None:
    if record.source_emission_tco2 is None and record.factor_tco2_per_unit is None:
        return None
    if record.source_emission_tco2 is None or record.factor_tco2_per_unit is None:
        raise ValueError("Incomplete calculation source snapshot")
    calculated = quantity * record.factor_tco2_per_unit
    if record.data_origin == "OVERRIDE":
        if not record.override_reason.strip():
            raise ValueError("Report override requires a reason")
        return calculated
    if abs(calculated - record.source_emission_tco2) > 0.000001:
        raise ValueError("Calculation source energy, factor and emissions do not reconcile")
    return record.source_emission_tco2


def calculate_report(report: ReportInput, factors: FactorLibrary) -> CalculationResult:
    fuel_totals: dict[str, float] = defaultdict(float)
    activity_fuel_totals: dict[str, float] = defaultdict(float)
    for record in report.fuel_activity:
        factor = factors.fuel_factors[record.fuel_type]
        if record.unit != factor.expected_unit:
            raise ValueError(f"{record.fuel_type} expected unit {factor.expected_unit}, got {record.unit}")
        activity_fuel_totals[record.fuel_type] += record.quantity
        frozen = source_emission(record, record.quantity)
        if frozen is not None:
            fuel_totals[record.fuel_type] += frozen
        elif factor.emission_factor is not None:
            fuel_totals[record.fuel_type] += record.quantity * factor.emission_factor
        else:
            fuel_totals[record.fuel_type] += (
                record.quantity * factor.carbon_content * factor.oxidation_rate * CO2_CARBON_MASS_RATIO
            )

    fuel_emissions = {fuel_type: round_tco2(value) for fuel_type, value in sorted(fuel_totals.items())}
    def row_total(records, quantity, fallback):
        total = 0.0
        for item in records:
            frozen = source_emission(item, quantity(item))
            total += frozen if frozen is not None else quantity(item) * fallback
        return round_tco2(total)

    electricity = row_total(report.electricity_activity, lambda r: r.quantity_mwh, factors.electricity_factor_tco2_per_mwh)
    heat = row_total(report.heat_activity, lambda r: r.quantity_gj, factors.heat_factor_tco2_per_gj)
    fuel_combustion = round_tco2(sum(fuel_emissions.values()))
    total = round_tco2(fuel_combustion + electricity + heat)
    shares = {
        "fuel": round(100 * fuel_combustion / total, 2) if total else 0.0,
        "electricity": round(100 * electricity / total, 2) if total else 0.0,
        "heat": round(100 * heat / total, 2) if total else 0.0,
    }
    electricity_total_mwh = sum(item.quantity_mwh for item in report.electricity_activity)
    heat_total_gj = sum(item.quantity_gj for item in report.heat_activity)

    return CalculationResult(
        factor_version=factors.version,
        fuel_emissions=fuel_emissions,
        electricity_emissions_tco2=electricity,
        heat_emissions_tco2=heat,
        total_emissions_tco2=total,
        fuel_combustion_tco2=fuel_combustion,
        shares=shares,
        activity_fuel_totals=dict(sorted(activity_fuel_totals.items())),
        electricity_total_mwh=electricity_total_mwh,
        heat_total_gj=heat_total_gj,
    )
