"""Exercise the mapper's ANSI SQL in memory; never connects to business MySQL."""
from pathlib import Path
import re
import sqlite3
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


class CandidateProvenanceTest(unittest.TestCase):
    def setUp(self):
        mapper = ROOT / 'ruoyi-modules/ruoyi-carbon-report/src/main/resources/mapper/carbon/report/EmissionCalculationMapper.xml'
        self.sql = ET.parse(mapper).getroot().find("select[@id='selectCandidates']").text
        self.sql = re.sub(r'#\{(\w+)\}', r':\1', self.sql)
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('''
          create table emission_template(id integer, name text, template_type integer);
          create table emission_node(id integer, source_node_id integer, name text, type_id integer);
          create table emission_calculation_template(id integer, template_id integer, status integer,
            calculation_cycle_start_date text, calculation_cycle_end_date text, calculation_end_time text);
          create table emission_calculation_node(id integer, calculation_template_id integer, node_id integer, name text, type_id integer);
          create table report_dept_subject(dept_id integer, subject_node_id integer);
          create table sys_carbon_company(dept_id integer);
          insert into emission_template values(2,'Calculation',2),(3,'Node template',1);
          insert into report_dept_subject values(101,1000),(202,2000);
          insert into sys_carbon_company values(101),(202);
          insert into emission_node values
            (1000,0,'Same department',2),(2000,0,'Same department',2),
            (10,1000,'First copy',2),(20,1000,'Repeated copy',2),
            (30,2000,'Other company copy',2),(40,0,'Same department-copy',2);
        ''')
        self.db.execute('alter table emission_calculation_template add column company_dept_id integer')
        for task, node, template, start, end in [
            (1, 1000, 2, '2025-01-01', '2025-12-31'),
            (2, 10, 2, '2025-01-01', '2025-12-31'),
            (3, 20, 2, '2025-03-01', '2025-03-31'),
            (4, 30, 2, '2025-01-01', '2025-12-31'),
            (5, 40, 2, '2025-01-01', '2025-12-31'),
            (6, 1000, 3, '2025-01-01', '2025-12-31'),
            (7, 1000, 2, '2024-01-01', '2024-12-31'),
        ]:
            self.db.execute('insert into emission_calculation_template(id,template_id,status,calculation_cycle_start_date,calculation_cycle_end_date,calculation_end_time) values(?,?,2,?,?,?)',
                            (task, template, start, end, end))
            self.db.execute('insert into emission_calculation_node values(?,?,?, ?,2)',
                            (task, task, node, 'Same department'))

    def tearDown(self):
        self.db.close()

    def candidates(self, subject=1000, start='2025-01-01', end='2025-12-31'):
        rows = self.db.execute(self.sql, dict(subjectNodeId=subject, periodStart=start, periodEnd=end))
        return {row[0] for row in rows}

    def test_direct_first_copy_and_repeated_copy(self):
        self.assertEqual({1, 2, 3}, self.candidates())

    def test_same_name_department_does_not_leak(self):
        self.assertEqual({4}, self.candidates(2000))

    def test_name_prefix_is_not_a_source_relationship(self):
        self.assertNotIn(5, self.candidates())

    def test_node_templates_are_excluded(self):
        self.assertNotIn(6, self.candidates())

    def test_period_intersection_is_preserved(self):
        self.assertEqual({1, 2}, self.candidates(start='2025-12-01', end='2025-12-31'))
        self.assertEqual({7}, self.candidates(start='2024-01-01', end='2024-12-31'))

    def test_unknown_subject_returns_nothing(self):
        self.assertEqual(set(), self.candidates(9999))


if __name__ == '__main__':
    unittest.main()
