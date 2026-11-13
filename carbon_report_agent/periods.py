"""Period labels shared by prose, charts and tables; legacy wording stays unchanged."""
from carbon_report_agent.models import ReportInput


def period_label(report: ReportInput) -> str:
    if report.period_contract_version:
        return f"{report.metadata.period_start}至{report.metadata.period_end}"
    if report.period_grain == "month" and report.metadata.report_month:
        return f"{report.metadata.report_year}年{report.metadata.report_month}月"
    return f"{report.metadata.report_year}年"


def period_column(report: ReportInput) -> str:
    return "本期" if report.period_contract_version else f"{report.metadata.report_year}年"
