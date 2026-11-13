from pathlib import Path
import importlib.util
import json
import tempfile
import unittest
from zipfile import ZipFile
from PIL import Image
import hashlib
import build_initializer as builder


ROOT=Path(__file__).resolve().parents[3]
DEFAULTS=Path(__file__).resolve().parent.parent/'defaults'


class ImageDefaultsTest(unittest.TestCase):
    def test_nine_images_have_valid_role_content_and_original_dimensions(self):
        materials=json.loads((DEFAULTS/'report-defaults.json').read_text(encoding='utf-8'))
        provenance=json.loads((DEFAULTS/'material-provenance.json').read_text(encoding='utf-8'))
        self.assertEqual(9,sum(len(c['images']) for c in materials['companies']))
        for company in materials['companies']:
            self.assertEqual({'org_chart','cover_logo','office_location'},{i['role'] for i in company['images']})
            source=next(c for c in provenance['companies'] if c['company_key']==company['company_key'])
            for image in company['images']:
                path=DEFAULTS/image['path'];raw=path.read_bytes()
                self.assertEqual(image['size_bytes'],len(raw));self.assertEqual(image['sha256'],hashlib.sha256(raw).hexdigest())
                with Image.open(path) as im: im.verify()
            if company['company_key']=='jiliang':
                photo=next(i for i in source['images'] if i['role']=='office_location')
                self.assertTrue(photo['user_confirmed_office_location'])
                self.assertIn('现场图',photo['description'])

    def test_image_only_package_is_self_contained_and_has_no_profile_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory);manifest=builder.build(output)
            sql=(output/'init_report_images.sql').read_text(encoding='ascii')
            runner=(output/'init_report_images.sh').read_text(encoding='ascii')
        self.assertEqual(3,len(manifest['companies']))
        self.assertEqual(9,sql.count('INSERT INTO tmp_cr_image (company_key,role'))
        self.assertNotIn('UPDATE report_dept_profile',sql)
        self.assertNotIn('INSERT INTO report_dept_profile',sql)
        self.assertNotIn('DELETE FROM report_file',sql)
        self.assertIn('archived_default',sql)
        self.assertIn('REPORT_IMAGES_INIT_OK',runner)
        self.assertNotIn('__EMBEDDED_SQL__',runner);self.assertNotIn('__BACKUP_WHERE__',runner)
        self.assertIn('images.before.sql',runner)
        self.assertIn('--where="$backup_where"',runner)
        self.assertIn('BINARY dept_name IN (',runner)


if __name__=='__main__':unittest.main()
