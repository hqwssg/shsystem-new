"""Synthetic regression fixtures only; no online business quantities or credentials."""
import copy
import unittest
from carbon_report_agent.models import ReportInput
from carbon_report_agent.factors import FactorLibrary
from carbon_report_agent.calculations import calculate_report


def payload():
    return dict(metadata=dict(entity_name='测试公司',report_year=2025,report_period='2025年测试',compiler='',compile_date='2026-10-19'),
                entity_profile=dict(short_name='测试',business_description='',carbon_department=''),
                fuel_activity=[],electricity_activity=[],heat_activity=[],monitoring_devices=[])


class FrozenSourceCalculationTest(unittest.TestCase):
    def calculate(self,data):
        return calculate_report(ReportInput.model_validate(data),FactorLibrary.default_2024())

    def test_per_meter_factors_and_emissions_override_current_library(self):
        data=payload()
        data['electricity_activity']=[dict(scope='purchased-electricity',quantity_mwh=10,source_name='甲',source_emission_tco2=4,factor_tco2_per_unit=.4,data_origin='AUTO'),
                                      dict(scope='purchased-electricity',quantity_mwh=10,source_name='乙',source_emission_tco2=7,factor_tco2_per_unit=.7,data_origin='AUTO')]
        self.assertEqual(self.calculate(data).electricity_emissions_tco2,11)

    def test_mismatched_source_is_rejected(self):
        data=payload();data['heat_activity']=[dict(site='甲',quantity_gj=100,source_name='热',source_emission_tco2=.01,factor_tco2_per_unit=.1)]
        with self.assertRaisesRegex(ValueError,'reconcile'):self.calculate(data)

    def test_override_uses_frozen_factor_and_requires_reason(self):
        data=payload();row=dict(site='甲',quantity_gj=200,source_name='热',source_emission_tco2=10,factor_tco2_per_unit=.1,data_origin='OVERRIDE',override_reason='已核对本报告调整')
        data['heat_activity']=[row];self.assertEqual(self.calculate(data).heat_emissions_tco2,20)
        row['override_reason']=''
        with self.assertRaisesRegex(ValueError,'reason'):self.calculate(data)

    def test_partial_snapshot_is_not_silently_recalculated(self):
        data=payload();data['electricity_activity']=[dict(scope='purchased-electricity',quantity_mwh=10,source_name='甲',source_emission_tco2=5)]
        with self.assertRaisesRegex(ValueError,'Incomplete'):self.calculate(data)

    def test_frozen_fuel_direct_factor_is_used(self):
        data=payload();data['fuel_activity']=[dict(fuel_type='natural_gas',facility='测试',quantity=2,unit='10k_m3',source_name='表甲',source_emission_tco2=40,factor_tco2_per_unit=20,data_origin='AUTO')]
        self.assertEqual(self.calculate(data).fuel_emissions['natural_gas'],40)

    def test_true_zero_is_valid_when_snapshot_is_complete(self):
        data=payload();data['heat_activity']=[dict(site='甲',quantity_gj=0,source_name='热',source_emission_tco2=0,factor_tco2_per_unit=.1)]
        self.assertEqual(self.calculate(data).total_emissions_tco2,0)

    def test_existing_unfrozen_inputs_remain_compatible(self):
        data=payload();data['electricity_activity']=[dict(scope='purchased-electricity',quantity_mwh=100,source_name='甲')]
        self.assertEqual(self.calculate(data).electricity_emissions_tco2,53.66)

    def test_source_period_retained_in_strict_model(self):
        data=payload();data['source_period']=dict(start='2024-01-01',end='2025-05-31',partial=True)
        model=ReportInput.model_validate(data);self.assertTrue(model.source_period.partial)
        self.assertEqual(model.source_period.end,'2025-05-31')

if __name__=='__main__':unittest.main()
