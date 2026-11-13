"""Fuel contract regression, using synthetic quantities and the three reported factor values."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pydantic import ValidationError
from carbon_report_agent.models import SnapshotFuelFactor, ReportInput
from carbon_report_agent.factors import FactorLibrary
from carbon_report_agent.calculations import calculate_report

VALUES = {"natural_gas": 21.621888, "gasoline": 3.042547, "diesel": 3.145122}

def item(fuel, both=True):
    factor = dict(expected_unit="10k_m3" if fuel == "natural_gas" else "t", carbon_content=0,
                  oxidation_rate=1, source="calculation-snapshot", emission_factor=VALUES[fuel])
    if both:
        factor["value"] = VALUES[fuel]
    return factor

def payload():
    return dict(entity_code="jiliang", metadata=dict(entity_name="合成燃料契约测试 非正式",report_year=2025,
        report_period="2025年度合成测试",compiler="合成测试",compile_date="2026-10-20"),
        entity_profile=dict(short_name="测试",business_description="合成测试",carbon_department="测试"),
        fuel_activity=[dict(fuel_type=fuel,facility="合成采集点",source_name="合成计量记录",quantity=1,
            unit="10k_m3" if fuel=="natural_gas" else "t", source_emission_tco2=value,
            factor_tco2_per_unit=value,data_origin="AUTO") for fuel,value in VALUES.items()],
        electricity_activity=[],heat_activity=[],monitoring_devices=[],images=[],
        factors=dict(source="calculation-snapshot",fuel_factors={f:item(f) for f in VALUES}))

class FuelFactorContractTest(unittest.TestCase):
    def test_all_three_reported_values_are_accepted_without_changing_input(self):
        for fuel,value in VALUES.items():
            data=item(fuel);saved=copy.deepcopy(data)
            factor=SnapshotFuelFactor.model_validate(data)
            self.assertEqual(value,factor.emission_factor)
            self.assertNotIn("value",factor.model_dump())
            self.assertEqual(saved,data)
    def test_canonical_only_and_legacy_only(self):
        for fuel,value in VALUES.items():
            self.assertEqual(value,SnapshotFuelFactor.model_validate(item(fuel,False)).emission_factor)
            legacy=item(fuel);del legacy['emission_factor']
            self.assertEqual(value,SnapshotFuelFactor.model_validate(legacy).emission_factor)
    def test_conflicting_aliases_are_rejected(self):
        data=item('diesel');data['value']=99
        with self.assertRaises(ValidationError):SnapshotFuelFactor.model_validate(data)
    def test_unrelated_extra_field_still_rejected(self):
        data=item('gasoline');data['unrecognized_parameter']=1
        with self.assertRaises(ValidationError) as error:SnapshotFuelFactor.model_validate(data)
        self.assertIn('extra_forbidden',str(error.exception))
    def test_zero_and_numeric_string_alias_do_not_fall_back(self):
        data=item('diesel');data.update(value=0,emission_factor=0)
        self.assertEqual(0,SnapshotFuelFactor.model_validate(data).emission_factor)
        data.update(value='3.145122',emission_factor=3.145122)
        self.assertEqual(3.145122,SnapshotFuelFactor.model_validate(data).emission_factor)
    def test_real_report_input_and_per_row_fuel_factors(self):
        data=payload();data['fuel_activity'].append(dict(fuel_type='gasoline',facility='第二合成汽油表',source_name='第二合成计量记录',
            quantity=2,unit='t',factor_tco2_per_unit=4.5,source_emission_tco2=9,data_origin='AUTO'))
        report=ReportInput.model_validate(data)
        result=calculate_report(report,FactorLibrary.from_snapshot(report.factors))
        self.assertEqual(12.04,result.fuel_emissions['gasoline'])
        self.assertEqual(36.81,result.fuel_combustion_tco2)

if __name__=='__main__':unittest.main()
