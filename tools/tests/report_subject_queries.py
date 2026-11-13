"""Run the actual subject-option mapper SQL against isolated in-memory tables."""
from pathlib import Path
import sqlite3
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


class SubjectQueryTest(unittest.TestCase):
    def setUp(self):
        mapper = ROOT / 'ruoyi-modules/ruoyi-carbon-report/src/main/resources/mapper/carbon/report/ReportDeptSubjectMapper.xml'
        self.sql = ET.parse(mapper).getroot().find("select[@id='selectNodes']").text
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('''
          create table sys_dept(dept_id integer, status text, del_flag text);
          create table emission_template(id integer, name text, dept_id integer);
          create table emission_node(id integer, name text, type_id integer, template_id integer);
          create table report_dept_subject(dept_id integer, subject_node_id integer);
          insert into sys_dept values(301,'0','0'),(303,'0','0'),(304,'1','0');
          insert into emission_template values(501,'A',301),(503,'B',303);
          insert into emission_node values
              (1001,'Legacy mapped',2,null),(1002,'A root',1,501),
              (3171,'B root',1,503),(3172,'Collection point',3,503),
              (9000,'Unowned orphan',2,null),(9001,'Disabled legacy',2,null);
          insert into report_dept_subject values(301,1001),(304,9001);
        ''')

    def tearDown(self):
        self.db.close()

    def options(self, scope=''):
        return {row[0] for row in self.db.execute(self.sql.replace('${params.dataScope}', scope))}

    def test_legacy_mapped_node_is_available_without_exposing_unowned_orphans(self):
        self.assertEqual({1001, 1002, 3171}, self.options())

    def test_department_scope_applies_to_both_template_and_legacy_union(self):
        self.assertEqual({1001, 1002}, self.options('and t.dept_id = 301'))
        self.assertEqual({3171}, self.options('and t.dept_id = 303'))

    def test_denied_scope_returns_no_nodes(self):
        self.assertEqual(set(), self.options('and t.dept_id = 0'))


class CompanyQueryTest(unittest.TestCase):
    def setUp(self):
        mapper = ROOT / 'ruoyi-modules/ruoyi-carbon-report/src/main/resources/mapper/carbon/report/ReportDeptSubjectMapper.xml'
        self.query = ET.parse(mapper).getroot().find("select[@id='selectCompanies']")
        self.db = sqlite3.connect(':memory:')
        self.db.executescript("""
          create table sys_dept(dept_id integer, dept_name text, order_num integer, status text, del_flag text);
          create table sys_carbon_company(dept_id integer primary key);
          create table report_dept_subject(dept_id integer, subject_node_id integer, energy_allocation text, enabled text);
          create table emission_node(id integer, name text);
          insert into sys_dept values
            (301,'Company A',1,'0','0'),(303,'Company B',2,'0','0'),
            (304,'Disabled',3,'1','0'),(305,'Deleted',4,'0','2'),
            (400,'Ordinary department',5,'0','0'),(306,'Unconfigured company',6,'0','0');
          insert into sys_carbon_company values(301),(303),(304),(305),(306);
          insert into emission_node values(1001,'A boundary'),(3171,'B boundary');
          insert into report_dept_subject values(301,1001,'suring','1'),(303,3171,'jilong','1'),(400,1001,'suring','1');
        """)

    def tearDown(self):
        self.db.close()

    def companies(self, scope='', dept=None):
        sql = self.query.text
        for child in self.query:
            if child.tag != 'if' or dept is not None:
                sql += child.text or ''
            sql += child.tail or ''
        sql = sql.replace('${params.dataScope}', scope).replace('#{deptId}', ':dept')
        return list(self.db.execute(sql, {'dept': dept}))

    def test_only_active_registered_companies_are_listed_even_when_ordinary_department_has_mapping(self):
        self.assertEqual([301, 303, 306], [row[0] for row in self.companies()])

    def test_report_scope_intersects_company_registration_without_parent_promotion(self):
        self.assertEqual([303], [row[0] for row in self.companies('and d.dept_id = 303')])
        self.assertEqual([], self.companies('and d.dept_id = 400'))
        self.assertEqual([], self.companies('and d.dept_id = 0'))

    def test_forged_company_is_still_limited_by_operation_scope(self):
        self.assertEqual([], self.companies('and d.dept_id = 301', 303))
        self.assertEqual([301], [row[0] for row in self.companies('and d.dept_id = 301', 301)])

    def test_unconfigured_company_is_visible_for_admin_configuration_without_fake_boundary(self):
        rows = self.companies(dept=306)
        self.assertEqual(1, len(rows))
        self.assertIsNone(rows[0][2])
        self.assertIsNone(rows[0][4])


if __name__ == '__main__':
    unittest.main()
