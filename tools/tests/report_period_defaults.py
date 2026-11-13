"""Historical report template years must not become defaults for new reports."""
from types import SimpleNamespace
import unittest
from docx import Document
from carbon_report_agent.boilerplate import load_boilerplate_library
from carbon_report_agent.publisher import _render_appendix_emission_summary


class ReportPeriodDefaultsTest(unittest.TestCase):
    def test_preface_has_no_fixed_year_or_expired_reporting_notice(self):
        text=load_boilerplate_library().by_id['preface.opening_guide'].text
        self.assertIn('本报告期',text)
        self.assertNotRegex(text,r'20\d\d')

    def check_summary(self, year, month, expected):
        report=SimpleNamespace(period_grain='month' if month else 'year',metadata=SimpleNamespace(report_year=year,report_month=month))
        calc=SimpleNamespace(fuel_combustion_tco2=0,electricity_emissions_tco2=1,heat_emissions_tco2=0,total_emissions_tco2=1)
        doc=Document();_render_appendix_emission_summary(doc,calc,report)
        self.assertEqual(doc.tables[0].cell(0,0).text,expected)

    def test_annual_summary_uses_selected_year(self):
        self.check_summary(2026,None,'2026年')

    def test_monthly_summary_uses_selected_year_and_month(self):
        self.check_summary(2025,3,'2025年3月')


if __name__=='__main__':unittest.main()
