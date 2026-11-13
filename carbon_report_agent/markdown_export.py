"""Export a frozen Markdown artifact and task-local images without recalculation."""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import unquote, urlsplit

import mistune
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image

from .docx_pdf import convert_docx_to_pdf


class MarkdownExportError(ValueError):
    pass


class ReportWriter:
    def __init__(self, manifest: dict):
        self.root = Path(manifest['root']).resolve()
        self.source = self.resolve(manifest['source'])
        self.names = manifest['names']
        self.artifacts = set(manifest['artifacts'])
        self.doc = Document()
        section = self.doc.sections[0]
        section.page_width, section.page_height = Inches(8.5), Inches(11)
        section.top_margin = section.bottom_margin = Inches(.7)
        section.left_margin = section.right_margin = Inches(.75)
        self.width = 7
        for name in ('Normal', 'Title', 'Heading 1', 'Heading 2', 'Heading 3', 'List Bullet', 'List Number'):
            style = self.doc.styles[name]
            style.font.name = 'Arial'
            style._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), 'Noto Sans CJK SC')
            style.font.color.rgb = RGBColor(0, 0, 0)
            for border in style._element.xpath('.//w:pBdr'):
                border.getparent().remove(border)
        normal = self.doc.styles['Normal']
        normal.font.size = Pt(10.5)
        normal.paragraph_format.line_spacing = 1.2
        normal.paragraph_format.space_after = Pt(6)

    def resolve(self, relative: str) -> Path:
        value = relative.replace('\\', '/')
        if urlsplit(value).scheme or PurePosixPath(value).is_absolute():
            raise MarkdownExportError('报告引用必须来自同一任务附件')
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise MarkdownExportError('报告包含非法附件路径')
        return path

    def display_name(self, path: str) -> str:
        rel = PurePosixPath(path.replace('\\', '/'))
        name = rel.name
        display = self.names['files'].get(name)
        if display:
            return display + rel.suffix
        folder = self.names['folders'].get(rel.parent.name)
        return folder + '：' + name if folder else name

    def localize(self, text: str) -> str:
        aliases = {key: self.display_name(key) for key in self.names['files']}
        short = {}
        for rel in self.artifacts:
            aliases[rel] = self.display_name(rel)
            short.setdefault(PurePosixPath(rel).name, set()).add(self.display_name(rel))
        aliases.update({k: next(iter(v)) for k, v in short.items() if len(v) == 1})
        aliases.update({v: v for v in list(aliases.values())})
        pattern = re.compile(r'(^|[^a-zA-Z0-9_./\\-])(?:\./)?(' + '|'.join(
            re.escape(k) for k in sorted(aliases, key=len, reverse=True)) + r')(?=$|[^a-zA-Z0-9_.-])')
        parts = re.split(r'(https?://[^\s<>)`]+)', text)
        return ''.join(s if i % 2 else pattern.sub(lambda m: m[1] + aliases[m[2]], s)
                       for i, s in enumerate(parts))

    def image(self, paragraph, url: str):
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc:
            raise MarkdownExportError('不支持外部图片，请使用已归档的任务图片')
        # Resolve original references before applying Chinese display names.
        path = self.resolve(str(self.source.parent.relative_to(self.root) / unquote(parsed.path)))
        rel = path.relative_to(self.root).as_posix()
        if rel not in self.artifacts or not path.is_file():
            raise MarkdownExportError('报告引用的图片未归档：' + rel)
        try:
            with Image.open(path) as im:
                width, height = im.size
                data = BytesIO()
                im.convert('RGB').save(data, format='PNG')
            data.seek(0)
            inches = min(self.width, 8.2 * width / height)
            paragraph.add_run().add_picture(data, width=Inches(inches))
        except (OSError, ValueError) as exc:
            raise MarkdownExportError('图片无法转换：' + rel) from exc

    def math(self, paragraph, formula: str):
        from matplotlib import mathtext
        from matplotlib.font_manager import FontProperties
        data = BytesIO()
        try:
            mathtext.math_to_image('$' + formula.strip() + '$', data,
                prop=FontProperties(size=12), dpi=220, format='png')
            data.seek(0)
            with Image.open(data) as im:
                width = min(self.width, im.width / 220)
            data.seek(0)
            paragraph.add_run().add_picture(data, width=Inches(width))
        except (ValueError, RuntimeError) as exc:
            raise MarkdownExportError('公式无法排版：' + formula[:100]) from exc

    def inline(self, paragraph, tokens, **formatting):
        for token in tokens:
            kind = token['type']
            if kind == 'image':
                self.image(paragraph, token['attrs']['url'])
            elif kind == 'inline_math':
                self.math(paragraph, token['raw'])
            elif kind in ('strong', 'emphasis', 'strikethrough'):
                self.inline(paragraph, token['children'], **{**formatting,
                    {'strong': 'bold', 'emphasis': 'italic', 'strikethrough': 'strike'}[kind]: True})
            elif kind == 'link':
                self.inline(paragraph, token['children'], **formatting)
                url = token['attrs']['url']
                if urlsplit(url).scheme in ('http', 'https'):
                    paragraph.add_run(' (' + url + ')')
            elif 'children' in token:
                self.inline(paragraph, token['children'], **formatting)
            else:
                text = '\n' if kind == 'linebreak' else ' ' if kind == 'softbreak' else self.localize(token.get('raw', ''))
                run = paragraph.add_run(text)
                for key, value in formatting.items():
                    setattr(run.font, key, value)
                if kind == 'codespan':
                    run.font.name = 'Consolas'
                    run.font.size = Pt(9)

    def blocks(self, tokens, depth=0):
        for token in tokens:
            kind = token['type']
            if kind in ('paragraph', 'block_text', 'heading'):
                level = token.get('attrs', {}).get('level', 1)
                style = 'Title' if kind == 'heading' and level == 1 and not self.doc.paragraphs else (
                    'Heading ' + str(min(level, 3)) if kind == 'heading' else None)
                paragraph = self.doc.add_paragraph(style=style)
                paragraph.paragraph_format.left_indent = Inches(depth * .2)
                self.inline(paragraph, token['children'])
            elif kind == 'list':
                ordered = token['attrs'].get('ordered', False)
                start = token['attrs'].get('start', 1)
                for i, item in enumerate(token['children']):
                    children = item['children']
                    if children and children[0]['type'] in ('block_text', 'paragraph'):
                        paragraph = self.doc.add_paragraph()
                        paragraph.paragraph_format.left_indent = Inches((depth + 1) * .2)
                        paragraph.add_run(str(start + i) + '. ' if ordered else '• ')
                        self.inline(paragraph, children[0]['children'])
                        self.blocks(children[1:], depth + 1)
                    else:
                        self.blocks(children, depth + 1)
            elif kind == 'table':
                self.table(token)
            elif kind == 'block_code':
                paragraph = self.doc.add_paragraph()
                run = paragraph.add_run(self.localize(token['raw']))
                run.font.name, run.font.size = 'Consolas', Pt(8)
            elif kind == 'block_math':
                self.math(self.doc.add_paragraph(), token['raw'])
            elif kind == 'block_quote':
                self.blocks(token['children'], depth + 1)
            elif kind in ('block_html', 'inline_html'):
                # Preserve visible source rather than executing embedded HTML.
                self.doc.add_paragraph(token['raw'])
            elif 'children' in token:
                self.blocks(token['children'], depth)

    def table(self, token):
        head, body = token['children']
        rows = [head['children']] + [row['children'] for row in body['children']]
        cols = len(rows[0])
        # Very wide result tables are continued in column groups with the identifier repeated.
        groups = [list(range(cols))] if cols <= 6 else [[0] + list(range(i, min(i + 5, cols))) for i in range(1, cols, 5)]
        for group in groups:
            if len(groups) > 1:
                self.doc.add_paragraph('表格列组 ' + str(groups.index(group) + 1))
            table = self.doc.add_table(rows=0, cols=len(group))
            table.style = 'Table Grid'
            table.autofit = False
            for column in table.columns:
                column.width = Inches(self.width / len(group))
            for row_index, cells in enumerate(rows):
                row = table.add_row()
                if row_index == 0:
                    row._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
                for cell, index in zip(row.cells, group):
                    self.inline(cell.paragraphs[0], cells[index].get('children', []), bold=row_index == 0)
                    for paragraph in cell.paragraphs:
                        paragraph.paragraph_format.space_after = Pt(3)
                        paragraph.paragraph_format.space_before = Pt(3)
                        for run in paragraph.runs:
                            run.font.size = Pt(9)
            self.doc.add_paragraph()

    def save(self, output: Path):
        text = self.source.read_text('utf-8-sig')
        parser = mistune.create_markdown(renderer='ast', plugins=['table', 'math', 'strikethrough', 'url'])
        self.blocks(parser(text))
        self.doc.save(output)


def export(manifest_path: Path, output: Path):
    manifest = json.loads(manifest_path.read_text('utf-8'))
    if output.suffix.lower() not in ('.docx', '.pdf'):
        raise MarkdownExportError('仅支持Word和PDF格式')
    writer = ReportWriter(manifest)
    docx = output if output.suffix.lower() == '.docx' else output.with_suffix('.docx')
    writer.save(docx)
    if output.suffix.lower() == '.pdf':
        convert_docx_to_pdf(docx, output, timeout_seconds=120)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        export(args.manifest, args.output)
    except Exception as exc:
        print('报告导出失败：' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
