from pathlib import Path
import json
import unittest
from docx import Document
from docx.oxml.ns import qn
from docx.enum.text import WD_LINE_SPACING
from carbon_report_agent.models import EquipmentItem, ReportInput
from carbon_report_agent.publisher import _render_equipment
from pydantic import ValidationError

FOLDER=Path(__file__).resolve().parent


class EquipmentDefaultsTest(unittest.TestCase):
    def test_counts_provenance_and_missing_quantities(self):
        companies=json.loads((FOLDER/'equipment-defaults.json').read_text(encoding='utf-8'))['companies']
        expected={'suning':(9,1),'yuanping':(4,0),'jiliang':(57,6)}
        for c in companies:
            count,missing=expected[c['company_key']]
            self.assertEqual(count,len(c['equipment']))
            self.assertEqual(missing,sum(r['quantity'] is None for r in c['equipment']))
            self.assertTrue(all(str(c['source_year']) in r['remark'] for r in c['equipment']))
            self.assertEqual(count,len(c['raw_rows']))
            for source,row in zip(c['raw_rows'],c['equipment']):
                self.assertEqual(source[2],row['name']);self.assertEqual(source[4],row['model'])
                self.assertEqual(source[1],row['energy_type'])
                if row['quantity'] is not None:self.assertEqual(float(source[3]),row['quantity'])

    def test_duplicate_original_serial_is_preserved(self):
        c=next(c for c in json.loads((FOLDER/'equipment-defaults.json').read_text(encoding='utf-8'))['companies'] if c['company_key']=='jiliang')
        self.assertEqual(2,sum(r[0]=='33' for r in c['raw_rows']))
        self.assertEqual(3,sum(r['model']=='JC25X4' for r in c['equipment']))

    def test_null_quantity_renders_blank_while_true_zero_remains_zero(self):
        from types import SimpleNamespace
        report=SimpleNamespace(equipment=[EquipmentItem(name='数量未知'),EquipmentItem(name='真实零',quantity=0),EquipmentItem(name='已知数量',quantity=87)])
        document=Document();_render_equipment(document,report)
        self.assertEqual(['','0','87'],[row.cells[3].text for row in document.tables[0].rows[1:]])
        self.assertIsNotNone(document.tables[0].rows[0]._tr.trPr.find(qn('w:tblHeader')))
        self.assertTrue(all(row._tr.trPr.find(qn('w:cantSplit')) is not None for row in document.tables[0].rows))
        self.assertTrue(all(p.paragraph_format.line_spacing_rule == WD_LINE_SPACING.SINGLE
                            for row in document.tables[0].rows for cell in row.cells for p in cell.paragraphs))

    def test_unknown_model_fields_are_still_rejected(self):
        with self.assertRaises(ValidationError):EquipmentItem(name='测试',unexpected_source=1)


if __name__=='__main__':unittest.main()
