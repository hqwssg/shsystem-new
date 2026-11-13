"""Optional workload changes intensity disclosure, never the emission totals."""
import unittest
from unittest.mock import patch
from carbon_report_agent.models import ReportInput
from carbon_report_agent.factors import FactorLibrary
from carbon_report_agent.calculations import calculate_report
from carbon_report_agent.narrative import build_narrative_sections


def report_payload(version=1, workload=None):
    return dict(
        entity_code='jiliang', period_grain='year', period_contract_version=version,
        metadata=dict(entity_name='工作量选填合成测试 非正式', report_year=2025,
                      report_period='2025-01-01至2025-12-31', compiler='测试', compile_date='2026-10-21',
                      report_title='工作量选填合成测试报告', template_name='合成测试模板',
                      period_start='2025-01-01', period_end='2025-12-31'),
        entity_profile=dict(short_name='合成测试', business_description='非业务数据', carbon_department='测试'),
        fuel_activity=[], heat_activity=[], monitoring_devices=[], images=[],
        electricity_activity=[dict(scope='测试用电', quantity_mwh=100, source_name='合成测试表',
                                   factor_tco2_per_unit=.5, source_emission_tco2=50, data_origin='AUTO')],
        workload=[] if workload is None else workload)


class OptionalWorkloadTest(unittest.TestCase):
    def calculate(self, payload):
        report = ReportInput.model_validate(payload)
        factors = FactorLibrary.default_2024()
        return report, calculate_report(report, factors), factors

    def test_empty_workload_preserves_totals_and_discloses_no_intensity(self):
        report, calc, factors = self.calculate(report_payload())
        sections = build_narrative_sections(report, calc, factors, llm_enabled=False)
        self.assertEqual(50, calc.total_emissions_tco2)
        self.assertEqual([], report.workload)
        self.assertIn('未提供业务工作量', sections['chapter1_workload_intro'])
        self.assertIn('未提供工作量，不计算排放强度', sections['chapter6_conclusion'])
        self.assertNotIn('排放强度为', sections['chapter6_conclusion'])

    def test_valid_workload_computes_intensity_without_changing_emissions(self):
        report, calc, factors = self.calculate(report_payload(workload=[dict(name='测试周转量', quantity=100, unit='测试单位')]))
        sections = build_narrative_sections(report, calc, factors, llm_enabled=False)
        self.assertEqual(50, calc.total_emissions_tco2)
        self.assertIn('排放强度为0.5 tCO2/测试单位', sections['chapter6_conclusion'])
        self.assertNotIn('不计算排放强度', sections['chapter6_conclusion'])

    def test_zero_workload_never_divides_or_invents_intensity(self):
        report, calc, factors = self.calculate(report_payload(workload=[dict(name='测试周转量', quantity=0, unit='测试单位')]))
        sections = build_narrative_sections(report, calc, factors, llm_enabled=False)
        self.assertIn('不计算排放强度', sections['chapter6_conclusion'])
        self.assertNotIn('排放强度为', sections['chapter6_conclusion'])

    def test_legacy_draft_without_workload_also_discloses_no_intensity(self):
        report, calc, factors = self.calculate(report_payload(version=0))
        sections = build_narrative_sections(report, calc, factors, llm_enabled=False)
        self.assertIn('未提供工作量，不计算排放强度', sections['chapter6_conclusion'])

    def test_llm_cannot_remove_missing_workload_disclosure(self):
        report, calc, factors = self.calculate(report_payload())
        with patch('carbon_report_agent.narrative.draft_chapter3_activity_intro_segments', return_value=None), \
             patch('carbon_report_agent.narrative.draft_chapter6_segments_with_llm', return_value=dict(before_chart='测试合计。', after_chart='测试分布。')):
            sections = build_narrative_sections(report, calc, factors, llm_enabled=True)
        self.assertIn('未提供工作量，不计算排放强度', sections['chapter6_conclusion'])
        self.assertEqual(50, calc.total_emissions_tco2)


if __name__ == '__main__':
    unittest.main()
