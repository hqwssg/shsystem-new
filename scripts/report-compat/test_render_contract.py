"""Document navigation regression with synthetic data only."""
import tempfile
import unittest
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
from carbon_report_agent.toc import TocEntry, insert_clickable_toc
from carbon_report_agent.publisher import publish_docx, _add_section_break
from carbon_report_agent.calculations import calculate_report
from carbon_report_agent.factors import FactorLibrary
from carbon_report_agent.models import ReportInput


class RenderNavigationTest(unittest.TestCase):
    def test_orientation_change_continues_body_page_numbers(self):
        doc = Document()
        _add_section_break(doc, page_number_format='decimal', page_number_start=1)
        _add_section_break(doc, page_number_format='decimal', section_orientation='landscape')
        numbering = doc.sections[-1]._sectPr.find(qn('w:pgNumType'))
        self.assertIsNone(numbering.get(qn('w:start')))

    def test_toc_uses_pageref_instead_of_sample_page_numbers(self):
        doc = Document()
        insert_clickable_toc(doc, [TocEntry(1, 'Test heading', 'heading_test')])
        instructions = doc.element.xpath('.//w:instrText')
        self.assertEqual([node.text.strip() for node in instructions], ['PAGEREF heading_test \\h'])
        self.assertEqual(doc.settings.element.find(qn('w:updateFields')).get(qn('w:val')), 'true')

    def test_conditional_sections_leave_no_broken_directory_links(self):
        report = ReportInput.model_validate(dict(
            metadata=dict(entity_name='Synthetic company', report_year=2025,
                          report_period='2025', compiler='', compile_date='2026-10-19'),
            entity_profile=dict(short_name='Synthetic', business_description='', carbon_department=''),
            fuel_activity=[], electricity_activity=[], heat_activity=[], monitoring_devices=[],
            source_period=dict(start='2025-01-01', end='2025-03-31', partial=True)))
        calculations = calculate_report(report, FactorLibrary.default_2024())
        with tempfile.TemporaryDirectory() as tmp:
            path = publish_docx(report, calculations, {}, Path(tmp) / 'test.docx')
            doc = Document(path)
        bookmarks = {node.get(qn('w:name')) for node in doc.element.xpath('.//w:bookmarkStart')}
        anchors = [node.get(qn('w:anchor')) for node in doc.element.xpath('.//w:hyperlink')]
        self.assertTrue(anchors)
        self.assertTrue(all(anchor in bookmarks for anchor in anchors))
        decimal_starts = [section._sectPr.find(qn('w:pgNumType')).get(qn('w:start'))
                          for section in doc.sections
                          if section._sectPr.find(qn('w:pgNumType')) is not None
                          and section._sectPr.find(qn('w:pgNumType')).get(qn('w:fmt')) in (None, 'decimal')]
        self.assertEqual(decimal_starts, ['1', None, None])


if __name__ == '__main__':
    unittest.main()
