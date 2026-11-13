"""Run with: python -m unittest discover -s tools/algorithm-db-comments -v"""
import unittest
from pathlib import Path
from manage_comments import (load_catalog, replace_comment, structure_hash, legacy_structure_hash,
                             legacy_charset_compatible_hash, quote_comment,
                             column_definitions, alter_sql)


class CommentTests(unittest.TestCase):
    def test_only_comment_changes(self):
        original = "`v` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT 'COMMENT ''literal''' COMMENT 'old' INVISIBLE"
        updated = replace_comment(original, "new 'quote' \\ text", '')
        self.assertEqual(structure_hash(original), structure_hash(updated))
        self.assertIn("DEFAULT 'COMMENT ''literal'''", updated)
        self.assertTrue(updated.endswith(' INVISIBLE'))

    def test_definition_attributes(self):
        cases = [
            "`id` bigint unsigned NOT NULL AUTO_INCREMENT",
            "`ts` timestamp(6) NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)",
            "`g` int GENERATED ALWAYS AS ((`a` + 1)) STORED",
            "`g` varchar(50) GENERATED ALWAYS AS (concat('COMMENT ',`a`)) VIRTUAL",
            "`d` decimal(16,6) NOT NULL DEFAULT '0.000000'",
        ]
        for definition in cases:
            with self.subTest(definition=definition):
                self.assertEqual(structure_hash(definition), structure_hash(replace_comment(definition, 'test', '')))

    def test_detects_schema_changes(self):
        ddl = "CREATE TABLE `t` (`id` int NOT NULL AUTO_INCREMENT, `x` int DEFAULT '1', PRIMARY KEY (`id`), KEY `idx` (`x`), CHECK (`x` >= 0)) ENGINE=InnoDB AUTO_INCREMENT=10 COMMENT='old'"
        self.assertEqual(structure_hash(ddl), structure_hash(ddl.replace("COMMENT='old'", "COMMENT='new'").replace('AUTO_INCREMENT=10', 'AUTO_INCREMENT=100')))
        for before, after in [('`id` int', '`id` bigint'), ('NOT NULL', 'NULL'), ("DEFAULT '1'", "DEFAULT '2'"), ('KEY `idx`', 'UNIQUE KEY `idx`'), ('>= 0', '> 0'), ('ENGINE=InnoDB', 'ENGINE=MyISAM')]:
            self.assertNotEqual(structure_hash(ddl), structure_hash(ddl.replace(before, after)))

    def test_quoting(self):
        self.assertEqual(quote_comment("a'b\\c", ''), "'a''b\\\\c'")
        self.assertEqual(quote_comment("a'b\\c", 'NO_BACKSLASH_ESCAPES'), "'a''b\\c'")

    def test_mysql_legacy_check_serialization(self):
        ddl = "CHECK (`train_type` in (_gbk'heavy',_gbk'empty'))"
        self.assertEqual(structure_hash(ddl), structure_hash(ddl.replace('_gbk', '_utf8mb4')))
        self.assertNotEqual(structure_hash(ddl), structure_hash(ddl.replace('_gbk', '_binary')))
        self.assertNotEqual(structure_hash("CHECK (`x`=_gbk'中文')"), structure_hash("CHECK (`x`=_utf8mb4'中文')"))

    def test_expanded_inherited_column_charset(self):
        inherited = """CREATE TABLE `t` (
  `name` varchar(32) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"""
        expanded = """CREATE TABLE `t` (
  `name` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"""
        changed = expanded.replace('utf8mb4_general_ci NOT NULL', 'utf8mb4_bin NOT NULL')
        self.assertEqual(structure_hash(inherited), structure_hash(expanded))
        self.assertNotEqual(structure_hash(inherited), structure_hash(changed))

    def test_default_charset_expansion_preserves_planned_collation(self):
        planned = """CREATE TABLE `t` (
  `candidate_id` char(36) COLLATE utf8mb4_general_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"""
        current = """CREATE TABLE `t` (
  `candidate_id` char(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"""
        changed = current.replace('CHARACTER SET utf8mb4', 'CHARACTER SET latin1')
        self.assertEqual(structure_hash(planned), structure_hash(current))
        self.assertNotEqual(structure_hash(planned), structure_hash(changed))

    def test_legacy_plan_hash_compatibility_preserves_collation_tokens(self):
        planned = """CREATE TABLE `t` (
  `candidate_id` char(36) COLLATE utf8mb4_general_ci NOT NULL,
  CONSTRAINT `ck` CHECK ((`x` in (_gbk'heavy',_gbk'empty')))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"""
        current = planned.replace(
            ' COLLATE utf8mb4_general_ci NOT NULL',
            ' CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL',
        ).replace('_gbk', '_utf8mb4')
        expected_legacy_hash = legacy_structure_hash(planned)
        self.assertNotEqual(legacy_structure_hash(current), expected_legacy_hash)
        self.assertEqual(legacy_charset_compatible_hash(current), expected_legacy_hash)
        changed = current.replace('char(36)', 'char(37)')
        self.assertNotEqual(legacy_charset_compatible_hash(changed), expected_legacy_hash)
        changed_collation = current.replace('COLLATE utf8mb4_general_ci', 'COLLATE utf8mb4_bin')
        self.assertNotEqual(legacy_charset_compatible_hash(changed_collation), expected_legacy_hash)

    def test_legacy_plan_hash_accepts_current_expanded_ddl(self):
        planned = """CREATE TABLE `t` (
  `name` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT 'old'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='table old'"""
        current = planned.replace("COMMENT 'old'", "COMMENT 'new'").replace("COMMENT='table old'", "COMMENT='table new'")
        old_plan_hash = legacy_structure_hash(planned)
        self.assertNotEqual(structure_hash(current), old_plan_hash)
        self.assertEqual(legacy_structure_hash(current), old_plan_hash)
        altered = current.replace('varchar(32)', 'varchar(64)')
        self.assertNotEqual(legacy_structure_hash(altered), old_plan_hash)
        self.assertNotEqual(structure_hash(altered), old_plan_hash)

    def test_parse_show_create(self):
        ddl = "CREATE TABLE `t` (\n  `id` bigint NOT NULL,\n  `x` varchar(20) DEFAULT 'a,b',\n  PRIMARY KEY (`id`)\n) ENGINE=InnoDB"
        defs = column_definitions(ddl)
        self.assertEqual(set(defs), {'id', 'x'})
        self.assertTrue(defs['x'].endswith("'a,b'"))

    def test_no_change_no_alter(self):
        comments = {'table': 'a', 'columns': {'id': 'b'}}
        self.assertIsNone(alter_sql('energy_test', {'comments': comments}, comments, ''))

    def test_catalog(self):
        catalog = load_catalog(Path(__file__).with_name('comments.json'))
        self.assertEqual(len(catalog['tables']), 53)
        self.assertEqual(sum(len(t['columns']) for t in catalog['tables'].values()), 667)
        for table in catalog['tables'].values():
            for comment in table['columns'].values():
                self.assertNotIn('字段字段', comment)
                self.assertNotIn('关联对象ID', comment)
                self.assertNotIn('\ufffd', comment)


if __name__ == '__main__':
    unittest.main()
