"""Synthetic period and cover regressions; contains no business data."""
import copy
import tempfile
import unittest
from datetime import date
from pathlib import Path
from docx import Document
from carbon_report_agent.models import ReportInput
from carbon_report_agent.periods import period_label
from carbon_report_agent.factors import FactorLibrary
from carbon_report_agent.calculations import calculate_report
from carbon_report_agent.narrative import build_narrative_sections
from carbon_report_agent.publisher import publish_docx, CoverLayoutError
from carbon_report_agent.charts import distribution_series


def fixture(start='2025-03-01', end='2025-05-31', template='三个月测试模板'):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    from calendar import monthrange
    grain = 'year' if start == f'{a.year}-01-01' and end == f'{a.year}-12-31' else 'month' if a.day == 1 and a.year == b.year and a.month == b.month and b.day == monthrange(b.year, b.month)[1] else 'range'
    return dict(period_contract_version=1, period_grain=grain,
        metadata=dict(entity_name='机辆分公司渲染测试主体', report_year=b.year, report_month=a.month if grain == 'month' else None,
            report_period=f'{start}至{end}', report_title=f'{template}（{start}至{end}）碳排放报告', template_name=template,
            period_start=start, period_end=end, compiler='测试编制单位', compile_date='2026-10-19', report_number='仅测试非正式20261019'),
        entity_profile=dict(short_name='测试主体', business_description='以下数据均为合成测试数据，不代表线上核算结果。', carbon_department='测试部门'),
        organization_boundary=dict(boundary_description='合成测试边界', emission_sources=['净购入电力','净购入热力','化石燃料燃烧'], accounting_method='冻结来源因子'),
        source_period=dict(start=start, end=end, partial=False),
        fuel_activity=[dict(fuel_type='natural_gas',facility='合成测试站点',quantity=2,unit='10k_m3',source_name='测试气表',factor_tco2_per_unit=20,source_emission_tco2=40)],
        electricity_activity=[dict(scope='测试电表',quantity_mwh=10,source_name='测试电表',factor_tco2_per_unit=.5,source_emission_tco2=5)],
        heat_activity=[dict(site='测试热力站',quantity_gj=100,source_name='测试热力表',factor_tco2_per_unit=.1,source_emission_tco2=10)],
        workload=[dict(name='合成测试工作量',quantity=100,unit='测试单位')], monitoring_devices=[])


class PeriodContractTest(unittest.TestCase):
    def test_ai_annual_drift_falls_back_to_exact_period_and_intensity(self):
        from unittest.mock import patch
        r=ReportInput.model_validate(fixture()); c=calculate_report(r,FactorLibrary.default_2024())
        with patch('carbon_report_agent.narrative.draft_chapter6_segments_with_llm',return_value=dict(before_chart='2025年度同比增长10%。',after_chart='全年排放增加。')):
            n=build_narrative_sections(r,c,FactorLibrary.default_2024(),llm_enabled=True)
        self.assertNotRegex(n['chapter6_conclusion'],'全年|年度|同比|环比')
        self.assertIn('0.55 tCO2/测试单位',n['chapter6_conclusion'])

    def test_partial_manual_baseline_does_not_make_missing_categories_zero_in_chart(self):
        d=fixture('2025-01-01','2025-12-31')
        d['prior_year']=dict(report_year=2024,period_start='2024-01-01',period_end='2024-12-31',source_label='手工填报',total_emissions_tco2=50,fuel_combustion_tco2=20)
        r=ReportInput.model_validate(d);c=calculate_report(r,FactorLibrary.default_2024())
        self.assertEqual(len(distribution_series(r,c)[0]),1)

    def test_calendar_classification_and_no_prorating(self):
        cases=[('2025-01-01','2025-12-31','year'),('2025-03-01','2025-03-31','month'),
               ('2024-02-01','2024-02-29','month'),('2025-03-01','2025-05-31','range'),
               ('2024-01-01','2025-05-31','range'),('2022-01-01','2025-12-31','range'),
               ('2025-03-05','2025-05-17','range'),('2024-06-01','2025-05-31','range')]
        for start,end,grain in cases:
            with self.subTest(start=start,end=end):
                report=ReportInput.model_validate(fixture(start,end))
                self.assertEqual(report.period_grain,grain)
                c=calculate_report(report,FactorLibrary.default_2024())
                self.assertEqual(c.total_emissions_tco2,55)
                n=build_narrative_sections(report,c,FactorLibrary.default_2024(),llm_enabled=False)
                self.assertIn(start,n['chapter1_basic']);self.assertIn(end,n['chapter5_summary_intro'])
                if grain=='range':
                    self.assertNotRegex(n['chapter6_conclusion'], '同比|环比|年度')
                    self.assertEqual(len(distribution_series(report,c)[0]),1)

    def test_invalid_and_changed_periods_rejected(self):
        for mutation in [lambda d:d['metadata'].update(period_end='2025-02-01'),
                         lambda d:d.update(period_grain='year'),
                         lambda d:d['source_period'].update(end='2025-06-01')]:
            d=fixture();mutation(d)
            with self.assertRaises(ValueError):ReportInput.model_validate(d)

    def test_exact_leap_month_baselines_and_zero_denominator(self):
        d=fixture('2024-02-01','2024-02-29')
        d['prior_year']=dict(report_year=2023,report_month=2,period_start='2023-02-01',period_end='2023-02-28',source_label='手工填报',total_emissions_tco2=0)
        d['prior_month']=dict(report_year=2024,report_month=1,period_start='2024-01-01',period_end='2024-01-31',source_label='核算任务测试ID',total_emissions_tco2=50)
        r=ReportInput.model_validate(d); c=calculate_report(r,FactorLibrary.default_2024())
        n=build_narrative_sections(r,c,FactorLibrary.default_2024(),llm_enabled=False)['chapter6_conclusion']
        self.assertIn('手工填报',n);self.assertIn('核算任务测试ID',n);self.assertIn('环比',n)
        d['prior_year']['period_end']='2023-02-27'
        with self.assertRaises(ValueError):ReportInput.model_validate(d)

    def test_range_rejects_comparison(self):
        d=fixture();d['prior_year']=dict(report_year=2024,total_emissions_tco2=10)
        with self.assertRaises(ValueError):ReportInput.model_validate(d)

    def test_legacy_drafts_keep_annual_wording(self):
        d=fixture();d.pop('period_contract_version');d['period_grain']='year'
        d['source_period']['partial']=True
        r=ReportInput.model_validate(d)
        self.assertEqual(period_label(r),'2025年')

    def test_long_cover_is_complete_and_unbounded_input_is_blocked(self):
        d=fixture(template='长模板名称'*40);r=ReportInput.model_validate(d)
        c=calculate_report(r,FactorLibrary.default_2024())
        with tempfile.TemporaryDirectory() as temp:
            p=publish_docx(r,c,{},Path(temp)/'long.docx')
            doc=Document(p)
            self.assertIn(d['metadata']['template_name'],'\n'.join(p.text for p in doc.paragraphs))
            d['metadata']['compiler']='过长编制单位'*1000
            with self.assertRaises(CoverLayoutError):
                publish_docx(ReportInput.model_validate(d),c,{},Path(temp)/'overflow.docx')

    def test_cross_year_and_mixed_month_rows_remain_totals(self):
        from carbon_report_agent.publisher import _render_activity_electricity_monthly
        for start,end in [('2024-01-01','2025-05-31'),('2025-03-01','2025-05-31')]:
            d=fixture(start,end);d['electricity_activity'][0]['month']=3
            row=copy.deepcopy(d['electricity_activity'][0]);row['month']=None;row['quantity_mwh']=2;row['source_emission_tco2']=1
            d['electricity_activity'].append(row)
            doc=Document();_render_activity_electricity_monthly(doc,ReportInput.model_validate(d))
            self.assertEqual(doc.tables[0].cell(1,1).text,'12.000')


if __name__=='__main__':unittest.main()
