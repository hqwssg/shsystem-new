# -*- coding: utf-8 -*-
"""对 Word 已生成目录的 docx 做收尾处理：
  1) 压缩目录条目间距/字号（排版更紧凑）；
  2) 可选：按 JSON 映射重写目录页码（由 Word 分页结果给出）。

用法：
    python scripts/postprocess_design_docx.py <docx> [pages.json]
"""

from __future__ import annotations

import json
import re
import sys

from docx import Document
from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

EA = "宋体"
ASCII = "Times New Roman"
PRIMARY = RGBColor(0x1F, 0x4E, 0x79)
DARK = RGBColor(0x26, 0x26, 0x26)
TEXT_W_CM = 15.6


def _set_fonts(run, size, bold, color):
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = rPr.get_or_add_rFonts()
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if rFonts.get(qn(attr)) is not None:
            del rFonts.attrib[qn(attr)]
    rFonts.set(qn("w:ascii"), ASCII)
    rFonts.set(qn("w:hAnsi"), ASCII)
    rFonts.set(qn("w:eastAsia"), EA)
    rFonts.set(qn("w:cs"), ASCII)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def style_level(name: str) -> int:
    m = re.search(r"(\d)", name)
    return int(m.group(1)) if m else 1


def iter_runs(paragraph):
    """目录条目被 Word 包在 w:hyperlink 里，需按 XML 递归取 run。"""
    from docx.text.run import Run

    return [Run(r, paragraph) for r in paragraph._p.iter(qn("w:r"))]


def main() -> int:
    path = sys.argv[1]
    pages_path = sys.argv[2] if len(sys.argv) > 2 else ""

    doc = Document(path)

    # 1) 样式层面：把 toc 1 / toc 2 改回紧凑定义
    for st in doc.styles:
        if st.type != 1 or not st.name.lower().startswith("toc"):
            continue
        if st.name.lower() in ("toc heading",):
            continue
        lvl = style_level(st.name)
        size = 10.0 if lvl == 1 else 9.5
        st.font.name = ASCII
        st.font.size = Pt(size)
        st.font.bold = (lvl == 1)
        st.font.color.rgb = DARK if lvl == 1 else RGBColor(0x33, 0x33, 0x33)
        rpr = st.element.get_or_add_rPr()
        rpr.rFonts.set(qn("w:eastAsia"), EA)
        rpr.rFonts.set(qn("w:cs"), ASCII)
        pf = st.paragraph_format
        pf.left_indent = Cm(0.0 if lvl == 1 else 0.8)
        pf.first_line_indent = Cm(0)
        pf.space_before = Pt(4 if lvl == 1 else 0)
        pf.space_after = Pt(0.8)
        pf.line_spacing = 1.0
        # 去掉 Word 加的自动重定义标记，避免后续被重置
        for tag in ("w:autoRedefine", "w:unhideWhenUsed"):
            el = st.element.find(qn(tag))
            if el is not None:
                st.element.remove(el)

    # 2) 段落层面：逐条压缩
    toc_paras = []
    for p in doc.paragraphs:
        name = (p.style.name or "").lower()
        if not name.startswith("toc") or name == "toc heading":
            continue
        toc_paras.append(p)

    for p in toc_paras:
        lvl = style_level(p.style.name)
        size = 10.0 if lvl == 1 else 9.5
        bold = lvl == 1
        color = DARK if lvl == 1 else RGBColor(0x33, 0x33, 0x33)
        pf = p.paragraph_format
        pf.left_indent = Cm(0.0 if lvl == 1 else 0.8)
        pf.first_line_indent = Cm(0)
        pf.space_before = Pt(4 if lvl == 1 else 0)
        pf.space_after = Pt(0.8)
        pf.line_spacing = 1.0
        pf.tab_stops.clear_all()
        pf.tab_stops.add_tab_stop(Cm(TEXT_W_CM), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        for run in iter_runs(p):
            if run.text.strip() or "\t" in run.text:
                _set_fonts(run, size, bold, color)

    # 3) 目录尾部 Word 生成的空段落：压到 1pt，不占整行
    for p in doc.paragraphs:
        name = (p.style.name or "").lower()
        if name.startswith("toc") and not p.text.strip():
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.0
            for run in iter_runs(p):
                run.font.size = Pt(1)

    # 4) 可选：按 Word 分页结果重写页码
    if pages_path:
        with open(pages_path, "r", encoding="utf-8") as fh:
            mapping = json.load(fh)
        changed = 0
        for p in toc_paras:
            text = p.text
            title = text.split("\t")[0].strip()
            page = mapping.get(title)
            if page is None:
                key = re.sub(r"\s+", "", title)
                for k, v in mapping.items():
                    if re.sub(r"\s+", "", k) == key:
                        page = v
                        break
            if page is None:
                continue
            runs = [r for r in iter_runs(p) if r.text.strip()]
            if runs:
                last = runs[-1].text.strip()
                if last != str(page) and (last.isdigit() or last in ("-", "\u2013", "\u2014")):
                    runs[-1].text = str(page)
                    changed += 1
        print(f"page numbers rewritten: {changed}")

    doc.save(path)
    print(f"postprocessed: {path}  toc entries: {len(toc_paras)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
