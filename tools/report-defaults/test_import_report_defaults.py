from pathlib import Path
import copy
import json
import tempfile
import unittest
import import_report_defaults as loader


class DefaultsPolicyTest(unittest.TestCase):
    def test_materials_are_valid_for_three_companies(self):
        companies = loader.load_materials(Path(__file__).resolve().parent)
        self.assertEqual([v['company_key'] for v in companies], ['suning','yuanping','jiliang'])
        self.assertEqual(sum(len(v['images']) for v in companies),5)
        for company in companies:
            self.assertNotIn('org_chart',{v['role'] for v in company['images']})
            self.assertEqual(set(company['profile']), loader.PROFILE_FIELDS)

    def test_uncertain_and_year_specific_fields_are_empty(self):
        companies = loader.load_materials(Path(__file__).resolve().parent)
        blanks=['default_compiler','carbon_department','default_org_boundary','default_exclusion_note',
                'default_approver','default_validator','default_reviewer','default_checker','default_authors','header_template']
        for company in companies:
            with self.subTest(company=company['company_key']):
                p=company['profile']
                for key in blanks:self.assertEqual(p[key],'',key)
                for key in ['default_equipment_json','default_workload_json']:self.assertEqual(p[key],[])
                for key in ['default_activity_prose_json','default_chapter6_json']:self.assertEqual(p[key],{})
                for text in [p['company_overview'],p['business_description'],p['process_description']]:
                    self.assertNotRegex(text,r'202[0-9]|员工|[0-9]+台|[0-9]+公里|[0-9]+个')

    def test_replace_can_clear_outdated_defaults(self):
        changes=loader.profile_changes({'default_authors':'old','default_equipment_json':'[{"name":"old"}]'},
                                       {'default_authors':'','default_equipment_json':[]},'replace')
        self.assertEqual(changes,{'default_authors':'','default_equipment_json':'[]'})

    def test_retirement_requires_explicit_replace(self):
        with self.assertRaises(ValueError):
            loader.import_defaults(None,[],{},retire_unlisted_images=True)

    def test_duplicate_target_departments_rejected(self):
        companies=loader.load_materials(Path(__file__).resolve().parent)
        mapping={v['company_key']:{'dept_id':301} for v in companies}
        with self.assertRaises(ValueError):loader.import_defaults(None,companies,mapping)

    def test_missing_preserves_existing_text(self):
        self.assertEqual(loader.profile_changes({'default_compiler':'online'}, {'default_compiler':'source'}, 'missing'), {})

    def test_missing_fills_empty_json(self):
        self.assertEqual(json.loads(loader.profile_changes({'default_equipment_json':'[]'}, {'default_equipment_json':[{'name':'sample'}]}, 'missing')['default_equipment_json']), [{'name':'sample'}])

    def test_replace_is_explicit(self):
        self.assertEqual(loader.profile_changes({'default_compiler':'online'}, {'default_compiler':'source'}, 'replace'), {'default_compiler':'source'})

    def test_json_formatting_is_not_a_change(self):
        self.assertEqual(loader.profile_changes({'default_equipment_json':'[{ "name": "sample" }]'}, {'default_equipment_json':[{'name':'sample'}]}, 'replace'), {})

    def test_unexpected_fields_rejected(self):
        with self.assertRaises(ValueError):
            loader.profile_changes({}, {'calculation_template_id':123}, 'replace')

    def test_image_path_escape_rejected(self):
        folder=Path(__file__).resolve().parent
        data=json.loads((folder/'report-defaults.json').read_text(encoding='utf-8'))
        data['companies'][0]['images'][0]['path']='../outside.png'
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)
            (target/'report-defaults.json').write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(ValueError):
                loader.load_materials(target)


if __name__ == '__main__':
    unittest.main()
