"""Real company candidate mapper SQL against an isolated in-memory database."""
from pathlib import Path
import sqlite3, unittest, re, xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]

class CompanyCandidates(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        xml = ROOT / 'ruoyi-modules/ruoyi-carbon-report/src/main/resources/mapper/carbon/report/EmissionCalculationMapper.xml'
        self.sql = re.sub(r'#\{(\w+)\}', r':\1', ET.parse(xml).getroot().find("select[@id='selectCompanyCandidates']").text)
        self.db.executescript('''
          create table emission_template(id integer, name text, template_type integer, dept_id integer);
          create table emission_calculation_template(id integer,template_id integer,company_dept_id integer,status integer,
            calculation_cycle_start_date text,calculation_cycle_end_date text,calculation_end_time text);
          insert into emission_template values(1,'Annual A',2,3000),(2,'Independent next year',2,303),(3,'Node only',1,302);
          insert into emission_calculation_template values
            (11,1,302,2,'2025-01-01','2025-12-31','2026-01-01'),
            (12,2,302,2,'2024-01-01','2024-12-31','2025-01-01'),
            (13,1,303,2,'2025-01-01','2025-12-31','2026-01-01'),
            (14,1,null,2,'2025-01-01','2025-12-31','2026-01-01'),
            (15,1,302,3,'2025-01-01','2025-12-31','2026-01-01'),
            (16,3,302,2,'2025-01-01','2025-12-31','2026-01-01'),
            (17,1,302,2,'2024-01-01','2026-12-31','2026-01-01');
        ''')

    def tearDown(self): self.db.close()

    def candidates(self, year=2025, company=302):
        return {r[0] for r in self.db.execute(self.sql, dict(companyDeptId=company,periodStart=f'{year}-01-01',periodEnd=f'{year}-12-31'))}

    def test_company_snapshot_overrides_current_template_department_and_survives_changes(self):
        self.assertEqual({11,17}, self.candidates())
        self.db.execute('update emission_template set dept_id=303')
        self.assertEqual({11,17}, self.candidates())

    def test_independent_yearly_nodes_do_not_need_a_common_fixed_node(self):
        self.assertEqual({12,17}, self.candidates(2024))

    def test_foreign_failed_unconfirmed_and_node_templates_do_not_leak(self):
        self.assertEqual({13}, self.candidates(company=303))
        self.assertEqual(set(), self.candidates(company=999))

    def test_confirmed_historical_ownership_appears_without_changing_calculated_values(self):
        before = self.db.execute('select * from emission_calculation_template where id=14').fetchone()
        self.db.execute('update emission_calculation_template set company_dept_id=302 where id=14 and company_dept_id is null')
        self.assertEqual({11,14,17}, self.candidates())
        after = self.db.execute('select * from emission_calculation_template where id=14').fetchone()
        self.assertEqual(before[:2]+before[3:], after[:2]+after[3:])

if __name__ == '__main__': unittest.main()
