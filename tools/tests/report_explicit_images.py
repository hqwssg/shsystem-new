"""Platform snapshots must never acquire historical Suning image defaults."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from carbon_report_agent.cli import _load_report


class ExplicitImagePolicyTest(unittest.TestCase):
    def load(self, payload):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_text(json.dumps(payload), encoding='utf-8')
            with patch('carbon_report_agent.cli.ReportInput.model_validate', side_effect=lambda x:x):
                return _load_report(path)

    def test_explicit_empty_images_stay_empty_for_all_companies(self):
        for company in ['suning', 'yuanping', 'jiliang']:
            with self.subTest(company=company), patch('carbon_report_agent.cli.enrich_images_from_assets') as enrich:
                self.assertEqual(self.load({'entity_code':company,'images':[]})['images'], [])
                enrich.assert_not_called()

    def test_explicit_partial_images_do_not_gain_org_chart(self):
        images=[{'role':'cover_logo','url':'/job-assets/cover_logo.png'}]
        with patch('carbon_report_agent.cli.enrich_images_from_assets') as enrich:
            self.assertEqual(self.load({'entity_code':'suning','images':images})['images'],images)
            enrich.assert_not_called()

    def test_other_companies_without_images_never_use_suning_assets(self):
        for company in ['yuanping','jiliang']:
            with self.subTest(company=company), patch('carbon_report_agent.cli.enrich_images_from_assets') as enrich:
                self.load({'entity_code':company})
                enrich.assert_not_called()

    def test_legacy_suning_input_without_images_keeps_compatibility(self):
        with patch('carbon_report_agent.cli.enrich_images_from_assets', side_effect=lambda x:x) as enrich:
            self.load({'entity_code':'suning'})
            enrich.assert_called_once()


if __name__=='__main__':
    unittest.main()
