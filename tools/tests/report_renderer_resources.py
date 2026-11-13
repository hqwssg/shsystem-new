"""Required renderer layouts must ship with the package, independent of tests/fixtures."""
from pathlib import Path
import unittest
from carbon_report_agent.blueprint import DEFAULT_BLUEPRINT_PATH, load_blueprint
from carbon_report_agent.template_distiller import DEFAULT_TEMPLATE_PACKAGE_PATH, load_template_package


class RendererResourcesTest(unittest.TestCase):
    def test_blueprint_is_package_resource(self):
        self.assertEqual(DEFAULT_BLUEPRINT_PATH.parent.name, 'data')
        self.assertEqual(DEFAULT_BLUEPRINT_PATH.parent.parent.name, 'carbon_report_agent')
        blueprint=load_blueprint()
        self.assertTrue(blueprint.blocks)
        self.assertTrue(any(block.kind=='toc_field' for block in blueprint.blocks))

    def test_template_is_package_resource(self):
        self.assertEqual(DEFAULT_TEMPLATE_PACKAGE_PATH.parent.name, 'data')
        template=load_template_package()
        self.assertEqual(len(template.section_titles), 8)
        self.assertEqual(template.wording_snippets['cover_line2'], '温室气体排放报告')


if __name__ == '__main__':
    unittest.main()
