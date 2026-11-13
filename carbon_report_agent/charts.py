from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

from carbon_report_agent.calculations import CalculationResult
from carbon_report_agent.models import PriorYearComparison, ReportInput

CATEGORY_LABELS = ("化石燃料", "净购入电力", "净购入热力")


class ChartRenderError(RuntimeError):
    pass


def _current_category_values(calculations: CalculationResult) -> list[float]:
    return [
        calculations.fuel_combustion_tco2,
        calculations.electricity_emissions_tco2,
        calculations.heat_emissions_tco2,
    ]


def _prior_year_category_values(prior: PriorYearComparison) -> list[float]:
    return [
        prior.fuel_combustion_tco2 or 0.0,
        prior.electricity_emissions_tco2 or 0.0,
        prior.heat_emissions_tco2 or 0.0,
    ]


def _should_include_prior_year(prior: PriorYearComparison) -> bool:
    # Only include prior bars when category breakdown exists; total-only skips prior.
    return any(
        value is not None
        for value in (
            prior.fuel_combustion_tco2,
            prior.electricity_emissions_tco2,
            prior.heat_emissions_tco2,
        )
    )


def _period_bar_label(year: int, month: int | None = None) -> str:
    if month:
        return f"{year}年{month}月"
    return str(year)


def _comparison_chartable(report, prior) -> bool:
    if report.period_contract_version:
        return all(value is not None for value in (prior.fuel_combustion_tco2, prior.electricity_emissions_tco2, prior.heat_emissions_tco2))
    return _should_include_prior_year(prior)


def distribution_series(
    report: ReportInput, calculations: CalculationResult
) -> tuple[list[tuple[str, list[float], str]], str]:
    current_values = _current_category_values(calculations)
    series: list[tuple[str, list[float], str]] = []
    if report.period_grain == "range":
        from carbon_report_agent.periods import period_label
        return [(period_label(report), current_values, "#2563eb")], "报告期间"

    if report.period_grain == "month":
        if report.prior_year is not None and _comparison_chartable(report, report.prior_year):
            series.append(
                (
                    _period_bar_label(report.prior_year.report_year, report.prior_year.report_month),
                    _prior_year_category_values(report.prior_year),
                    "#94a3b8",
                )
            )
        if report.prior_month is not None and _comparison_chartable(report, report.prior_month):
            series.append(
                (
                    _period_bar_label(report.prior_month.report_year, report.prior_month.report_month),
                    _prior_year_category_values(report.prior_month),
                    "#f59e0b",
                )
            )
        series.append(
            (
                _period_bar_label(report.metadata.report_year, report.metadata.report_month),
                current_values,
                "#2563eb",
            )
        )
        return series, "期间"
    if report.prior_year is not None and _comparison_chartable(report, report.prior_year):
        series.append(
            (
                str(report.prior_year.report_year),
                _prior_year_category_values(report.prior_year),
                "#94a3b8",
            )
        )
    series.append((str(report.metadata.report_year), current_values, "#2563eb"))
    return series, "年度"


def render_emissions_distribution_png(report: ReportInput, calculations: CalculationResult) -> bytes:
    try:
        series, legend_title = distribution_series(report, calculations)
        buf = io.BytesIO()
        fig, ax = plt.subplots(figsize=(7, 4))

        x_positions = range(len(CATEGORY_LABELS))
        count = len(series)
        bar_width = 0.6 if count == 1 else 0.8 / count
        offset = (count - 1) / 2

        for index, (label, values, color) in enumerate(series):
            ax.bar(
                [x + (index - offset) * bar_width for x in x_positions],
                values,
                width=bar_width,
                label=label,
                color=color,
            )

        ax.legend(title=legend_title)
        ax.set_xticks(list(x_positions), CATEGORY_LABELS)
        ax.set_ylabel(r"排放量 (tCO$_2$)")
        ax.set_title("温室气体排放分布")
        ax.grid(axis="y", linestyle="--", alpha=0.35)

        fig.tight_layout()
        fig.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise ChartRenderError(str(exc)) from exc
