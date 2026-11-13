"""验证重空协同模块MySQL表和字段中文注释补丁覆盖完整。"""

from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.generate_module_db_comments import _parse_tables


def main() -> int:
    source = Path(r"D:\dev\project\bb.sql")
    patch = ROOT / "database" / "mysql_module_comments.sql"
    document = ROOT / "docs" / "algorithm_database_design_zh.md"
    if not source.is_file():
        print(f"module database comments verification: SKIP（未挂载外部bb.sql：{source}）")
        return 0
    assert patch.is_file() and document.is_file()
    tables = _parse_tables(source.read_text(encoding="utf-8"))
    text = patch.read_text(encoding="utf-8")
    table_comments = set(re.findall(r"^ALTER TABLE `([^`]+)` COMMENT=", text, re.MULTILINE))
    column_comments = re.findall(r"^ALTER TABLE `([^`]+)` MODIFY COLUMN `([^`]+)` .* COMMENT '([^']*)';$", text, re.MULTILINE)
    assert table_comments == set(tables)
    expected = {(table, field) for table, fields in tables.items() for field, _definition, _existing in fields}
    actual = {(table, field) for table, field, comment in column_comments if any("\u4e00" <= char <= "\u9fff" for char in comment)}
    assert actual == expected, sorted(expected - actual)[:10]
    assert "排放核算、预测和其他业务表不在本文档范围内" in document.read_text(encoding="utf-8")
    print(f"module database comments verification: PASS ({len(tables)} tables, {len(expected)} columns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
