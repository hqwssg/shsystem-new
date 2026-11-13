from pathlib import Path
import json
import zipfile

from docx import Document
from PIL import Image
import pytest
from carbon_report_agent.markdown_export import ReportWriter, MarkdownExportError


@pytest.fixture
def writer(tmp_path):
    root = Path(__file__).resolve().parents[2]
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'nested/report.md').write_text('# 中文报告\n', encoding='utf-8')
    Image.new('RGB', (600, 300), 'blue').save(tmp_path / 'nested/chart.png')
    return ReportWriter({'root': str(tmp_path), 'source': 'nested/report.md',
        'names': json.loads((root / 'ruoyi-modules/ruoyi-energy/src/main/resources/energy-report-names.json').read_text('utf-8')),
        'artifacts': ['nested/report.md', 'nested/chart.png', 'summary.json', 'audit_summary.json']})


def test_real_markdown_structures_and_original_image_paths(writer, tmp_path):
    writer.source.write_text('''# 中文报告

**加粗**和*斜体*，`summary.json`、`audit_summary.json`。

1. 第一项
2. 第二项

![趋势](chart.png)

| 标识 | 数值 |
|---|---|
| 真零 | 0 |
| 缺失 | — |

$$
E=\\frac{P t}{3600}
$$
''', encoding='utf-8')
    out = tmp_path / 'report.docx'
    writer.save(out)
    doc = Document(out)
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert '调度结果总览.json' in text and '运行图审查总览.json' in text
    assert '第一项' in text and '第二项' in text
    assert doc.tables[0].cell(1, 1).text == '0'
    assert doc.tables[0].cell(2, 1).text == '—'
    with zipfile.ZipFile(out) as z:
        assert len([n for n in z.namelist() if n.startswith('word/media/')]) == 2
        assert b'tblHeader' in z.read('word/document.xml')


def test_no_filesystem_or_network_images_and_no_silent_omission(writer):
    for url in ('../../outside.png', 'https://example.invalid/chart.png', 'file:///etc/passwd', 'missing.png'):
        with pytest.raises(MarkdownExportError):
            writer.image(writer.doc.add_paragraph(), url)
    assert writer.localize('https://example.invalid/summary.json') == 'https://example.invalid/summary.json'


def test_wide_table_retains_every_cell(writer):
    tokens = [{'type': 'text', 'raw': str(i)} for i in range(12)]
    cells = [{'children': [t]} for t in tokens]
    writer.table({'children': [{'children': cells}, {'children': [{'children': cells}]}]})
    assert len(writer.doc.tables) == 3
    for i in range(12):
        assert any(str(i) == c.text for t in writer.doc.tables for row in t.rows for c in row.cells)
