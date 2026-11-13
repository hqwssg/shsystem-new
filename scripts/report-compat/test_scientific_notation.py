"""Scientific typography preserves document structures and calculation semantics."""
import tempfile
import unittest
from pathlib import Path
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree
from carbon_report_agent.scientific_text import format_scientific_document, display_unit
from carbon_report_agent.publisher import (
    _add_omml_formula_paragraph, _render_formula_table, publish_docx,
)
from carbon_report_agent.models import ReportInput
from carbon_report_agent.factors import FactorLibrary
from carbon_report_agent.calculations import calculate_report
from carbon_report_agent.narrative import _period_intensity


def scripted(document, alignment):
    return ["".join(r.itertext(qn("w:t"))) for r in document.element.iter(qn("w:r"))
            if r.find(f'./{qn("w:rPr")}/{qn("w:vertAlign")}') is not None
            and r.find(f'./{qn("w:rPr")}/{qn("w:vertAlign")}').get(qn("w:val")) == alignment]


class ScientificNotationTest(unittest.TestCase):
    def test_body_tables_header_and_existing_unicode(self):
        doc = Document()
        doc.add_paragraph('CO2 tCO2e kgCO₂ m2 Nm3 m³ GJ/m2 ×10-3 10^{-4} 500m3 120m2')
        doc.add_table(rows=1, cols=1).cell(0, 0).text = '排放量tCO2'
        doc.sections[0].header.paragraphs[0].text = 'CO2'
        format_scientific_document(doc)
        self.assertEqual(scripted(doc, 'subscript'), ['2', '2', '2', '2'])
        self.assertEqual(scripted(doc, 'superscript'), ['2', '3', '3', '2', '−3', '−4', '3', '2'])
        self.assertIn('tCO2e', doc.paragraphs[0].text)
        self.assertTrue(doc.sections[0].header._element.xpath('.//w:vertAlign'))

    def test_split_runs_hyperlinks_bookmarks_and_fields_survive(self):
        doc = Document(); p = doc.add_paragraph()
        p.add_run('tC').bold = True
        link = OxmlElement('w:hyperlink'); link.set(qn('w:anchor'), 'target')
        for text in ['O', '2']:
            r = OxmlElement('w:r'); t = OxmlElement('w:t'); t.text = text; r.append(t); link.append(r)
        p._p.append(link)
        mark = OxmlElement('w:bookmarkStart'); mark.set(qn('w:id'), '1'); mark.set(qn('w:name'), 'target');p._p.append(mark)
        instr = OxmlElement('w:instrText'); instr.text = 'PAGEREF CO2 \\h'; r = OxmlElement('w:r');r.append(instr);p._p.append(r)
        format_scientific_document(doc)
        self.assertEqual(scripted(doc, 'subscript'), ['2'])
        self.assertEqual(link.get(qn('w:anchor')), 'target')
        self.assertEqual(instr.text, 'PAGEREF CO2 \\h')
        self.assertEqual(mark.get(qn('w:name')), 'target')
        self.assertTrue(p.runs[0].bold)

    def test_arbitrary_numbers_identifiers_models_dates_are_untouched(self):
        doc = Document(); p=doc.add_paragraph('2025-03-01 104 10-3 SS4B HXD1 90081 10k_m3 CO20 file_CO2_value')
        before=p.text;format_scientific_document(doc)
        self.assertEqual(before,p.text)
        self.assertEqual([],scripted(doc,'superscript'))
        self.assertEqual([],scripted(doc,'subscript'))

    def test_format_is_idempotent_and_does_not_rebuild_math_or_breaks(self):
        doc=Document();p=doc.add_paragraph('CO2');p.add_run().add_break()
        _add_omml_formula_paragraph(doc,'method_fuel_formula')
        math=doc.element.xpath('.//m:oMath')[0];before=etree.tostring(math)
        format_scientific_document(doc);once=doc.element.xml
        format_scientific_document(doc)
        self.assertEqual(once,doc.element.xml)
        self.assertEqual(before,etree.tostring(math))
        self.assertEqual(1,len(doc.element.xpath('.//w:br')))

    def test_carbon_formula_has_double_sum_fraction_and_matching_terms(self):
        doc=Document();_add_omml_formula_paragraph(doc,'method_fuel_formula');_render_formula_table(doc,'formula_fuel')
        self.assertEqual(2,len(doc.element.xpath('.//m:nary')))
        self.assertEqual(2,len(doc.element.xpath('.//m:f')))
        text=''.join(doc.element.xpath('.//w:t/text()|.//m:t/text()'))
        self.assertIn('i,j',text);self.assertIn('t或万m3',text);self.assertIn('0至1',text)
        self.assertTrue(all(row._tr.xpath('./w:trPr/w:cantSplit') for row in doc.tables[0].rows))

    def test_direct_factor_formula_never_multiplies_carbon_conversion_again(self):
        doc=Document();_add_omml_formula_paragraph(doc,'method_fuel_formula',direct_fuel=True)
        _render_formula_table(doc,'formula_fuel',direct_fuel=True)
        self.assertFalse(doc.element.xpath('.//m:f'))
        text=''.join(doc.element.xpath('.//w:t/text()|.//m:t/text()'))
        self.assertIn('EFr',text);self.assertNotIn('CC',text)
        self.assertNotIn('44',''.join(doc.element.xpath('.//m:t/text()')))

    def test_power_and_heat_sum_per_record_factors(self):
        doc=Document()
        for energy in ['electricity','heat']:
            _add_omml_formula_paragraph(doc,'method_'+energy+'_formula')
            _render_formula_table(doc,'formula_'+energy)
        self.assertEqual(2,len(doc.element.xpath('.//m:nary')))
        self.assertIn('电力,r',''.join(doc.element.xpath('.//m:t/text()')))
        self.assertIn('热力,r',''.join(doc.element.xpath('.//m:t/text()')))

    def test_storage_units_are_only_translated_for_display(self):
        self.assertEqual('万m3',display_unit('10k_m3'))
        self.assertEqual('10^4t·km',display_unit('104t·km'))
        self.assertEqual('MWh',display_unit('MWh'))

    def test_workload_unit_exponent_does_not_change_quantity_or_intensity(self):
        report=ReportInput.model_validate(dict(
            period_contract_version=1,
            metadata=dict(entity_name='测试',report_title='科学符号测试',report_year=2025,report_period='2025',compiler='',compile_date='2026-10-22',
                          period_start='2025-01-01',period_end='2025-12-31'),
            entity_profile=dict(short_name='测试',business_description='',carbon_department=''),
            workload=[dict(name='测试',quantity=100,unit='104t·km')],
            fuel_activity=[],electricity_activity=[],heat_activity=[],monitoring_devices=[]))
        calc=calculate_report(report,FactorLibrary.default_2024())
        calc.total_emissions_tco2=50
        text=_period_intensity(report,calc)
        self.assertIn('100 10^4t·km',text);self.assertIn('0.5 tCO2/10^4t·km',text)
        self.assertEqual('104t·km',report.workload[0].unit)

    def test_full_report_keeps_values_and_document_navigation(self):
        report=ReportInput.model_validate(dict(
            metadata=dict(entity_name='CO2符号合成测试',report_year=2025,report_period='2025',compiler='',compile_date='2026-10-22'),
            entity_profile=dict(short_name='测试',business_description='CO2',carbon_department=''),
            fuel_activity=[dict(fuel_type='gasoline',facility='测试',quantity=1,unit='t',source_name='测试')],
            electricity_activity=[],heat_activity=[],monitoring_devices=[],workload=[]))
        factors=FactorLibrary.default_2024();before=report.model_dump();calc=calculate_report(report,factors)
        with tempfile.TemporaryDirectory() as tmp:
            doc=Document(publish_docx(report,calc,{},Path(tmp)/'test.docx',factors=factors))
        self.assertEqual(before,report.model_dump())
        self.assertEqual(calc,calculate_report(report,factors))
        self.assertTrue(doc.element.xpath('.//w:hyperlink'))
        self.assertTrue(doc.element.xpath('.//w:bookmarkStart'))
        self.assertTrue(doc.element.xpath('.//w:vertAlign'))
        self.assertNotIn('tCO2e',''.join(doc.element.xpath('.//w:t/text()')))


if __name__ == '__main__':
    unittest.main()
