# -*- coding: utf-8 -*-
"""把 docs/ 下的四份 Markdown 文档合并为一份 Word 文档《碳排放趋势预测系统设计》。

用法：
    python scripts/build_design_docx.py [输出路径]

说明：
  * 章节号、图号统一重排（第 N 章 / 图 N-M）；
  * Markdown 表格转为 Word 表格（深色表头、隔行底纹、表头跨页重复）；
  * 代码块保留等宽字体与浅色底纹；
  * 图片按正文宽度嵌入并加图题；
  * 生成封面、目录（TOC 域）、页眉页脚。

完整流程（目录页码需要 Word 的真实分页）：
  1) python scripts/build_design_docx.py            # 生成 docx，目录页码为占位符
  2) 用 Word 打开并 Repaginate，导出"标题 -> 页码"的 JSON（pages.json）
  3) python scripts/postprocess_design_docx.py <docx> <pages.json>   # 回写页码并压缩目录
  4) python scripts/check_design_docx.py <docx>     # 校验四份文档内容是否齐全
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

DOC_TITLE = "碳排放趋势预测系统设计"
DOC_SUBTITLE = "朔黄铁路大平台 · 碳排放趋势预测模块"

# 版面（A4）
PAGE_W, PAGE_H = Cm(21.0), Cm(29.7)
MARGIN_TOP, MARGIN_BOTTOM = Cm(2.54), Cm(2.54)
MARGIN_LEFT, MARGIN_RIGHT = Cm(2.8), Cm(2.6)
TEXT_W = Cm(15.6)

# 配色
C_PRIMARY = RGBColor(0x1F, 0x4E, 0x79)
C_TEXT = RGBColor(0x26, 0x26, 0x26)
C_GRAY = RGBColor(0x59, 0x59, 0x59)
C_WHITE = RGBColor(0xFF, 0xFF, 0xFF)

FONT_BODY_EA = "宋体"
FONT_BODY_ASCII = "Times New Roman"
FONT_HEAD_EA = "黑体"
FONT_HEAD_ASCII = "Arial"
FONT_MONO = "Consolas"

CHAPTERS = [
    dict(num=1, title="系统总体设计", file="02_系统设计说明书.md"),
    dict(num=2, title="数据库设计", file="03_数据库设计.md"),
    dict(num=3, title="接口设计", file="04_接口文档.md"),
    dict(num=4, title="模型评测与 2026 年预测", file="05_模型评测与预测报告.md"),
]

DOCSTRUCT = [
    ("第 1 章", "系统总体设计", "02_系统设计说明书",
     "设计目标与边界、总体架构、模块划分、数据流、关键设计决策、平台集成、增量训练、异常复核、非功能设计"),
    ("第 2 章", "数据库设计", "03_数据库设计",
     "表清单、核心表字段、视图、数据血缘与状态码、数据量估算、初始化与迁移、备份与恢复"),
    ("第 3 章", "接口设计", "04_接口文档",
     "通用约定、元数据与查询、灰色关联、训练、预测、月度增量接入、异常复核、模型与因子、看板、集成时序"),
    ("第 4 章", "模型评测与 2026 年预测", "05_模型评测与预测报告",
     "数据概况、GRA 结果、模型选择与 2025 留出测试、2026 年 BAU 预测、异常筛查结论、限制与建议、复现产物"),
]

ORG_NAME = {"JLG": "机辆分公司", "SNF": "肃宁分公司", "YPF": "原平分公司"}
FIG_KIND = {
    "gra": "灰色关联度排序",
    "model_compare": "候选模型 2025 年测试集 MASE 对比",
    "forecast": "2026 年 BAU 月度预测",
    "trend": "历史排放趋势与异常标记",
}


# --------------------------------------------------------------------------- #
# 底层排版工具
# --------------------------------------------------------------------------- #
def _q(tag: str):
    return qn(tag)


def _fld_char(kind):
    el = OxmlElement("w:fldChar")
    el.set(_q("w:fldCharType"), kind)
    return el


def set_font(run, size=None, bold=None, color=None, ascii_font=None, ea_font=None,
             mono=False, italic=None):
    if mono:
        # 代码块里 ─│┌ 等框线字符必须按半角宽度绘制，eastAsia 也指向等宽字体
        ascii_font, ea_font = FONT_MONO, FONT_MONO
    if ascii_font:
        run.font.name = ascii_font
        rPr = run._element.get_or_add_rPr()
        rPr.rFonts.set(_q("w:eastAsia"), ea_font or ascii_font)
        rPr.rFonts.set(_q("w:cs"), ascii_font)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color


def shade(parent_pr, fill: str):
    shd = OxmlElement("w:shd")
    shd.set(_q("w:val"), "clear")
    shd.set(_q("w:color"), "auto")
    shd.set(_q("w:fill"), fill)
    parent_pr.append(shd)


def _border_el(tag: str, sz: int, color: str, val: str = "single", space: int = 0):
    el = OxmlElement(tag)
    el.set(_q("w:val"), val)
    el.set(_q("w:sz"), str(sz))
    el.set(_q("w:space"), str(space))
    el.set(_q("w:color"), color)
    return el


def para_borders(paragraph, *, left=None, bottom=None, top=None, right=None):
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = pPr.find(_q("w:pBdr"))
    if pBdr is None:
        pBdr = OxmlElement("w:pBdr")
        pPr.append(pBdr)
    for tag, spec in (("w:top", top), ("w:left", left), ("w:bottom", bottom), ("w:right", right)):
        if spec:
            pBdr.append(_border_el(tag, spec[0], spec[1]))


def cell_shading(cell, fill: str):
    shade(cell._tc.get_or_add_tcPr(), fill)


def cell_margins(table, top=0.05, bottom=0.05, left=0.12, right=0.12):
    mar = OxmlElement("w:tblCellMar")
    for tag, val in (("w:top", top), ("w:left", left), ("w:bottom", bottom), ("w:right", right)):
        el = OxmlElement(tag)
        el.set(_q("w:w"), str(int(val * 567)))
        el.set(_q("w:type"), "dxa")
        mar.append(el)
    table._tbl.tblPr.append(mar)


def table_borders(table, outer=8, inner=4, color="BFBFBF", accent_left=False):
    borders = OxmlElement("w:tblBorders")
    specs = (("w:top", inner, color),
             ("w:left", outer if accent_left else inner, "1F4E79" if accent_left else color),
             ("w:bottom", inner, color),
             ("w:right", inner, color),
             ("w:insideH", inner, color),
             ("w:insideV", inner, color))
    for tag, sz, col in specs:
        borders.append(_border_el(tag, sz, col))
    table._tbl.tblPr.append(borders)


def repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(_q("w:val"), "true")
    trPr.append(el)


def cant_split(row):
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:cantSplit")
    el.set(_q("w:val"), "true")
    trPr.append(el)


def fixed_layout(table, widths_cm):
    tblPr = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(_q("w:type"), "fixed")
    tblPr.append(layout)
    tblW = OxmlElement("w:tblW")
    tblW.set(_q("w:w"), str(int(sum(widths_cm) * 567)))
    tblW.set(_q("w:type"), "dxa")
    tblPr.append(tblW)
    for i, w in enumerate(widths_cm):
        table.columns[i].width = Cm(w)
    for row in table.rows:
        for i, w in enumerate(widths_cm):
            row.cells[i].width = Cm(w)


def add_field(paragraph, instr: str, placeholder: str = "1", size=9.0, color=C_GRAY):
    paragraph.add_run()._r.append(_fld_char("begin"))
    r2 = paragraph.add_run()
    it = OxmlElement("w:instrText")
    it.set(_q("xml:space"), "preserve")
    it.text = instr
    r2._r.append(it)
    paragraph.add_run()._r.append(_fld_char("separate"))
    r4 = paragraph.add_run(placeholder)
    set_font(r4, size=size, color=color, ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)
    paragraph.add_run()._r.append(_fld_char("end"))


def enable_update_fields(doc):
    settings = doc.settings.element
    el = OxmlElement("w:updateFields")
    el.set(_q("w:val"), "true")
    compat = settings.find(_q("w:compat"))
    if compat is not None:
        compat.addprevious(el)
    else:
        settings.append(el)


# OOXML 子元素顺序（追加后统一按 schema 重排，避免 Word 报错）
_ORDER = {
    "w:pPr": ["w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr",
              "w:widowControl", "w:numPr", "w:suppressLineNumbers", "w:pBdr", "w:shd",
              "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
              "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
              "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
              "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
              "w:textDirection", "w:textAlignment", "w:textboxTightWrap",
              "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange"],
    "w:rPr": ["w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps",
              "w:smallCaps", "w:strike", "w:dstrike", "w:outline", "w:shadow",
              "w:emboss", "w:imprint", "w:noProof", "w:snapToGrid", "w:vanish",
              "w:webHidden", "w:color", "w:spacing", "w:w", "w:kern", "w:position",
              "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect", "w:bdr", "w:shd",
              "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
              "w:eastAsianLayout", "w:specVanish", "w:oMath"],
    "w:tblPr": ["w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual",
                "w:tblStyleRowBandSize", "w:tblStyleColBandSize", "w:tblW", "w:jc",
                "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout",
                "w:tblCellMar", "w:tblLook", "w:tblCaption", "w:tblDescription",
                "w:tblPrChange"],
    "w:tcPr": ["w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge",
               "w:tcBorders", "w:shd", "w:noWrap", "w:tcMar", "w:textDirection",
               "w:tcFitText", "w:vAlign", "w:hideMark", "w:headers", "w:cellIns",
               "w:cellDel", "w:cellMerge", "w:tcPrChange"],
    "w:trPr": ["w:cnfStyle", "w:divId", "w:gridBefore", "w:gridAfter", "w:wBefore",
               "w:wAfter", "w:cantSplit", "w:trHeight", "w:tblHeader",
               "w:tblCellSpacing", "w:jc", "w:hidden"],
    "w:sectPr": ["w:footnotePr", "w:endnotePr", "w:type", "w:pgSz", "w:pgMar",
                 "w:paperSrc", "w:pgBorders", "w:lnNumType", "w:pgNumType", "w:cols",
                 "w:formProt", "w:vAlign", "w:noEndnote", "w:titlePg",
                 "w:textDirection", "w:bidi", "w:rtlGutter", "w:docGrid",
                 "w:printerSettings", "w:sectPrChange"],
}


def normalize_order(doc):
    body = doc.element.body
    for tag, order in _ORDER.items():
        idx = {name: i for i, name in enumerate(order)}
        for el in body.iter(_q(tag)):
            children = list(el)
            if not children:
                continue
            decorated = []
            for pos, child in enumerate(children):
                decorated.append((idx.get(child.tag, len(order) + pos), pos, child))
            decorated.sort(key=lambda t: (t[0], t[1]))
            ordered = [c for _, _, c in decorated]
            if ordered != children:
                for child in children:
                    el.remove(child)
                for child in ordered:
                    el.append(child)


# --------------------------------------------------------------------------- #
# Markdown 解析
# --------------------------------------------------------------------------- #
@dataclass
class Block:
    kind: str
    text: str = ""
    level: int = 0
    rows: list = field(default_factory=list)
    aligns: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    lang: str = ""
    marker: str = ""
    path: str = ""
    alt: str = ""


CJK_RE = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef\u3000-\u303f]")


def disp_width(text: str) -> int:
    return sum(2 if CJK_RE.match(ch) else 1 for ch in text)


def is_table_sep(line: str) -> bool:
    s = line.strip()
    if not s.startswith("|"):
        return False
    cells = [c.strip() for c in s.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells)


def split_row(line: str) -> list:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def join_plain(parts: list) -> str:
    out = ""
    for p in parts:
        if not out:
            out = p
        elif out[-1].isascii() and p[0].isascii() and out[-1] not in "：:，,（(、":
            out += " " + p
        else:
            out += p
    return out


def parse_markdown(text: str) -> list:
    lines = text.splitlines()
    blocks: list = []
    i, n = 0, len(lines)
    plain_buf: list = []

    def flush_plain():
        if plain_buf:
            blocks.append(Block("p", text=join_plain(plain_buf)))
            plain_buf.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_plain()
            lang = stripped[3:].strip()
            code = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i].rstrip())
                i += 1
            i += 1
            blocks.append(Block("code", lines=code, lang=lang))
            continue

        if not stripped:
            flush_plain()
            i += 1
            continue

        if stripped.startswith("#"):
            flush_plain()
            m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            if m:
                blocks.append(Block("h", level=len(m.group(1)), text=m.group(2).strip()))
            i += 1
            continue

        if stripped in ("---", "***", "___"):
            flush_plain()
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < n and is_table_sep(lines[i + 1]):
            flush_plain()
            header = split_row(line)
            sep = [c.strip() for c in lines[i + 1].strip().strip("|").split("|")]
            aligns = []
            for c in sep:
                if c.startswith(":") and c.endswith(":"):
                    aligns.append("center")
                elif c.endswith(":"):
                    aligns.append("right")
                else:
                    aligns.append("left")
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            blocks.append(Block("table", rows=[header] + rows, aligns=aligns))
            continue

        if stripped.startswith(">"):
            flush_plain()
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            blocks.append(Block("quote", text=join_plain(quote)))
            continue

        m = re.match(r"^\s*!\[([^\]]*)\]\(([^)]+)\)\s*$", line)
        if m:
            flush_plain()
            blocks.append(Block("img", alt=m.group(1), path=m.group(2)))
            i += 1
            continue

        m = re.match(r"^(\s*)([-*+])\s+(.*)$", line)
        if m:
            flush_plain()
            blocks.append(Block("list", text=m.group(3), marker="•",
                                level=2 if len(m.group(1)) >= 2 else 1))
            i += 1
            continue

        m = re.match(r"^(\s*)(\d+)\.\s+(.*)$", line)
        if m:
            flush_plain()
            blocks.append(Block("list", text=m.group(3), marker=f"{m.group(2)}.",
                                level=2 if len(m.group(1)) >= 2 else 1))
            i += 1
            continue

        plain_buf.append(stripped)
        i += 1

    flush_plain()
    return blocks


INLINE_RE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")


def add_inline(paragraph, text: str, size=10.5, color=C_TEXT, bold=False, mono_inline=True):
    text = text.replace("\u2714", "\u221a").replace("\u2717", "\u00d7").replace("\u200b", "")
    for token in INLINE_RE.split(text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**") and len(token) > 4:
            run = paragraph.add_run(token[2:-2])
            set_font(run, size=size, bold=True, color=color,
                     ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)
        elif token.startswith("`") and token.endswith("`") and len(token) > 2:
            run = paragraph.add_run(token[1:-1])
            if mono_inline:
                set_font(run, size=max(size - 1.0, 7.5), bold=bold,
                         color=RGBColor(0x9C, 0x27, 0x1B), mono=True)
                shade(run._element.get_or_add_rPr(), "F2F2F2")
            else:
                set_font(run, size=size, bold=bold, color=color,
                         ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)
        elif token.startswith("[") and "](" in token:
            label = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", token)
            run = paragraph.add_run(label)
            set_font(run, size=size, bold=bold, color=color,
                     ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)
        else:
            run = paragraph.add_run(token)
            set_font(run, size=size, bold=bold, color=color,
                     ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)


def plain(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("`", "")
    return text.replace("\u2714", "\u221a").replace("\u200b", "")


# --------------------------------------------------------------------------- #
# 样式与节
# --------------------------------------------------------------------------- #
def setup_styles(doc):
    styles = doc.styles

    normal = styles["Normal"]
    normal.font.name = FONT_BODY_ASCII
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = C_TEXT
    rpr = normal.element.get_or_add_rPr()
    rpr.rFonts.set(_q("w:eastAsia"), FONT_BODY_EA)
    rpr.rFonts.set(_q("w:cs"), FONT_BODY_ASCII)
    pf = normal.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(18.5)
    pf.space_before = Pt(0)
    pf.space_after = Pt(4)
    pf.alignment = WD_ALIGN_PARAGRAPH.LEFT

    def tune(name, size, bold, color, before, after, page_break=False):
        st = styles[name]
        st.font.name = FONT_HEAD_ASCII
        st.font.size = Pt(size)
        st.font.bold = bold
        st.font.color.rgb = color
        rp = st.element.get_or_add_rPr()
        rp.rFonts.set(_q("w:eastAsia"), FONT_HEAD_EA)
        rp.rFonts.set(_q("w:cs"), FONT_HEAD_ASCII)
        p = st.paragraph_format
        p.space_before = Pt(before)
        p.space_after = Pt(after)
        p.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        p.line_spacing = 1.15
        p.keep_with_next = True
        p.keep_together = True
        p.first_line_indent = Cm(0)
        p.page_break_before = page_break
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT

    tune("Heading 1", 17, True, C_PRIMARY, 0, 14, page_break=True)
    tune("Heading 2", 13, True, C_PRIMARY, 14, 6)
    tune("Heading 3", 11.5, True, RGBColor(0x33, 0x33, 0x33), 10, 4)

    cap = styles["Caption"]
    cap.font.name = FONT_BODY_ASCII
    cap.font.size = Pt(9)
    cap.font.bold = False
    cap.font.color.rgb = C_GRAY
    cp = cap.paragraph_format
    cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cp.space_before = Pt(3)
    cp.space_after = Pt(10)
    cap.element.get_or_add_rPr().rFonts.set(_q("w:eastAsia"), FONT_BODY_EA)


def setup_toc_styles(doc):
    """定义 Word 内置 toc 1 / toc 2 样式，保证域更新后目录外观一致。"""
    for lvl, size, bold, indent, before in ((1, 10.0, True, 0.0, 5.0), (2, 9.5, False, 0.8, 0.0)):
        name = f"toc {lvl}"
        try:
            st = doc.styles[name]
        except KeyError:
            st = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = doc.styles["Normal"]
        st.font.name = FONT_BODY_ASCII
        st.font.size = Pt(size)
        st.font.bold = bold
        st.font.color.rgb = C_TEXT
        rpr = st.element.get_or_add_rPr()
        rpr.rFonts.set(_q("w:eastAsia"), FONT_BODY_EA)
        rpr.rFonts.set(_q("w:cs"), FONT_BODY_ASCII)
        pf = st.paragraph_format
        pf.left_indent = Cm(indent)
        pf.first_line_indent = Cm(0)
        pf.space_before = Pt(before)
        pf.space_after = Pt(1)
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = 1.08
        pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
        pf.tab_stops.add_tab_stop(TEXT_W, WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        st.element.set(_q("w:styleId"), f"TOC{lvl}")


def setup_section(section):
    section.page_width = PAGE_W
    section.page_height = PAGE_H
    section.top_margin = MARGIN_TOP
    section.bottom_margin = MARGIN_BOTTOM
    section.left_margin = MARGIN_LEFT
    section.right_margin = MARGIN_RIGHT
    section.header_distance = Cm(1.5)
    section.footer_distance = Cm(1.6)


def build_header_footer(section):
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False

    hp = section.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hp.paragraph_format.space_after = Pt(0)
    run = hp.add_run(DOC_TITLE)
    set_font(run, size=8.5, color=C_GRAY, ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)
    para_borders(hp, bottom=(4, "BFBFBF"))

    fp = section.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fp.paragraph_format.space_before = Pt(0)
    r = fp.add_run("第 ")
    set_font(r, size=9, color=C_GRAY, ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)
    add_field(fp, " PAGE ", "1", size=9.5, color=C_GRAY)
    r = fp.add_run(" 页")
    set_font(r, size=9, color=C_GRAY, ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)
    para_borders(fp, top=(4, "BFBFBF"))

    sectPr = section._sectPr
    pg = OxmlElement("w:pgNumType")
    pg.set(_q("w:start"), "1")
    sectPr.append(pg)


# --------------------------------------------------------------------------- #
# 封面 / 目录
# --------------------------------------------------------------------------- #
def build_cover(doc):
    for _ in range(3):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        set_font(p.add_run(""), size=10.5)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(24)
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.line_spacing = 1.1
    set_font(p.add_run(DOC_TITLE), size=30, bold=True, color=C_PRIMARY,
             ascii_font=FONT_HEAD_ASCII, ea_font=FONT_HEAD_EA)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    set_font(p.add_run(DOC_SUBTITLE), size=13, color=RGBColor(0x40, 0x40, 0x40),
             ascii_font=FONT_BODY_ASCII, ea_font="微软雅黑")

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(30)
    para_borders(p, bottom=(12, "1F4E79"))
    set_font(p.add_run(""), size=1)

    info = [
        ("文档名称", DOC_TITLE),
        ("文档版本", "V1.0"),
        ("文档类型", "系统设计文档（合并版）"),
        ("适用系统", "朔黄铁路大平台 · 碳排放趋势预测模块"),
        ("部署形态", "独立部署，或嵌入大平台作为预测服务"),
        ("数据库", "MySQL carbon_emissions（表前缀 prediction_）"),
        ("编制日期", "2026 年 10 月 31 日"),
    ]
    table = doc.add_table(rows=0, cols=2)
    for k, v in info:
        cells = table.add_row().cells
        p0 = cells[0].paragraphs[0]
        p0.paragraph_format.space_after = Pt(1)
        p0.paragraph_format.line_spacing = 1.2
        set_font(p0.add_run(k), size=10, color=C_GRAY, ascii_font=FONT_BODY_ASCII,
                 ea_font=FONT_BODY_EA)
        p1 = cells[1].paragraphs[0]
        p1.paragraph_format.space_after = Pt(1)
        p1.paragraph_format.line_spacing = 1.2
        set_font(p1.add_run(v), size=10, color=C_TEXT, ascii_font=FONT_BODY_ASCII,
                 ea_font=FONT_BODY_EA)
        for c in cells:
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            cell_shading(c, "F5F7FA")
    fixed_layout(table, [3.2, 12.4])
    cell_margins(table, top=0.07, bottom=0.07, left=0.18, right=0.16)
    table_borders(table, outer=4, inner=4, color="DCE3EC")

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(26)
    p.paragraph_format.space_after = Pt(8)
    set_font(p.add_run("文档构成"), size=10.5, bold=True, color=C_PRIMARY,
             ascii_font=FONT_HEAD_ASCII, ea_font=FONT_HEAD_EA)

    t2 = doc.add_table(rows=1, cols=3)
    for i, h in enumerate(["章节", "来源文档", "主要内容"]):
        cell = t2.rows[0].cells[i]
        p0 = cell.paragraphs[0]
        p0.paragraph_format.space_after = Pt(1)
        p0.paragraph_format.line_spacing = 1.1
        p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(p0.add_run(h), size=9, bold=True, color=C_WHITE,
                 ascii_font=FONT_HEAD_ASCII, ea_font=FONT_HEAD_EA)
        cell_shading(cell, "1F4E79")
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    repeat_header(t2.rows[0])
    for idx, (chap, title, src, desc) in enumerate(DOCSTRUCT):
        cells = t2.add_row().cells
        for i, txt in enumerate([f"{chap} {title}", src, desc]):
            p0 = cells[i].paragraphs[0]
            p0.paragraph_format.space_after = Pt(1)
            p0.paragraph_format.line_spacing = 1.12
            p0.alignment = WD_ALIGN_PARAGRAPH.LEFT
            set_font(p0.add_run(txt), size=8.5, color=C_TEXT,
                     ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)
            cells[i].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            if idx % 2 == 1:
                cell_shading(cells[i], "F2F5F9")
        cant_split(t2.rows[-1])
    fixed_layout(t2, [3.7, 3.3, 8.6])
    cell_margins(t2, top=0.06, bottom=0.06, left=0.14, right=0.14)
    table_borders(t2, outer=6, inner=4, color="D3DCE6")


def build_toc(doc, entries, pages, anchor):
    """在 anchor（占位段落）之前生成目录，anchor 之后即正文。"""

    def new_par(style=None):
        p = doc.add_paragraph(style=style) if style else doc.add_paragraph()
        anchor.addprevious(p._p)
        return p

    p = new_par()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(14)
    set_font(p.add_run("目　　录"), size=18, bold=True, color=C_PRIMARY,
             ascii_font=FONT_HEAD_ASCII, ea_font=FONT_HEAD_EA)

    first = True
    last_p = p
    for lvl, text in entries:
        if lvl > 2:
            continue
        p = new_par(style=f"toc {lvl}")
        pf = p.paragraph_format
        pf.left_indent = Cm(0.0 if lvl == 1 else 0.8)
        pf.first_line_indent = Cm(0)
        pf.space_before = Pt(5 if lvl == 1 else 0)
        pf.space_after = Pt(1)
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = 1.08
        pf.tab_stops.add_tab_stop(TEXT_W, WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)

        if first:
            p.add_run()._r.append(_fld_char("begin"))
            r2 = p.add_run()
            it = OxmlElement("w:instrText")
            it.set(_q("xml:space"), "preserve")
            it.text = ' TOC \\o "1-2" \\h \\z \\u '
            r2._r.append(it)
            p.add_run()._r.append(_fld_char("separate"))
            first = False

        size = 10 if lvl == 1 else 9.5
        bold = lvl == 1
        color = C_TEXT if lvl == 1 else RGBColor(0x33, 0x33, 0x33)
        set_font(p.add_run(text), size=size, bold=bold, color=color,
                 ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)
        set_font(p.add_run("\t"), size=size, bold=bold, color=color,
                 ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)
        set_font(p.add_run(str(pages.get(text, "-"))), size=size, bold=bold, color=color,
                 ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)
        last_p = p

    last_p.add_run()._r.append(_fld_char("end"))


# --------------------------------------------------------------------------- #
# 正文块渲染
# --------------------------------------------------------------------------- #
class Renderer:
    def __init__(self, doc, base_dir):
        self.doc = doc
        self.base_dir = base_dir
        self.chapter = 0
        self.sec = 0
        self.sub = 0
        self.fig = 0
        self.headings = []

    def heading1(self, title):
        title = plain(title)
        p = self.doc.add_paragraph(style="Heading 1")
        set_font(p.add_run(title), size=17, bold=True, color=C_PRIMARY,
                 ascii_font=FONT_HEAD_ASCII, ea_font=FONT_HEAD_EA)
        para_borders(p, bottom=(10, "1F4E79"))
        p.paragraph_format.space_after = Pt(14)
        self.headings.append((1, title))

    def heading2(self, text):
        self.sec += 1
        self.sub = 0
        title = f"{self.chapter}.{self.sec}　{plain(text)}"
        p = self.doc.add_paragraph(style="Heading 2")
        set_font(p.add_run(title), size=13, bold=True, color=C_PRIMARY,
                 ascii_font=FONT_HEAD_ASCII, ea_font=FONT_HEAD_EA)
        self.headings.append((2, title))

    def heading3(self, text):
        self.sub += 1
        title = f"{self.chapter}.{self.sec}.{self.sub}　{plain(text)}"
        p = self.doc.add_paragraph(style="Heading 3")
        set_font(p.add_run(title), size=11.5, bold=True, color=RGBColor(0x33, 0x33, 0x33),
                 ascii_font=FONT_HEAD_ASCII, ea_font=FONT_HEAD_EA)
        self.headings.append((3, title))

    def paragraph(self, text):
        p = self.doc.add_paragraph()
        p.paragraph_format.first_line_indent = Pt(21)
        p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        add_inline(p, text)

    def meta_box(self, items):
        if not items:
            return
        table = self.doc.add_table(rows=1, cols=1)
        cell = table.rows[0].cells[0]
        cell_shading(cell, "F5F7FA")
        cell.paragraphs[0]._p.getparent().remove(cell.paragraphs[0]._p)
        for idx, (label, value) in enumerate(items):
            p = cell.add_paragraph()
            pf = p.paragraph_format
            pf.space_before = Pt(3 if idx == 0 else 0)
            pf.space_after = Pt(3 if idx == len(items) - 1 else 0)
            pf.line_spacing = 1.25
            pf.first_line_indent = Cm(0)
            add_inline(p, f"**{label}**：{value}", size=9.5, color=RGBColor(0x40, 0x40, 0x40))
        fixed_layout(table, [TEXT_W.cm])
        cell_margins(table, top=0.07, bottom=0.07, left=0.24, right=0.2)
        table_borders(table, outer=4, inner=4, color="DCE3EC", accent_left=True)
        spacer = self.doc.add_paragraph()
        spacer.paragraph_format.space_after = Pt(6)
        spacer.paragraph_format.line_spacing = 0.6
        set_font(spacer.add_run(""), size=4)

    def list_item(self, marker, text, level):
        p = self.doc.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent = Cm(0.95 if level == 1 else 1.65)
        pf.first_line_indent = Cm(-0.6)
        pf.space_after = Pt(3)
        pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
        set_font(p.add_run(marker + " "), size=10.5, bold=marker.endswith("."),
                 color=C_TEXT, ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)
        add_inline(p, text)

    def quote(self, text):
        p = self.doc.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent = Cm(0.55)
        pf.space_before = Pt(4)
        pf.space_after = Pt(8)
        pf.line_spacing = 1.35
        pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
        shade(p._p.get_or_add_pPr(), "F7F9FC")
        para_borders(p, left=(18, "1F4E79"))
        add_inline(p, text, size=9.5, color=RGBColor(0x40, 0x40, 0x40))

    def code(self, lines, lang):
        if not lines:
            return
        max_units = max(disp_width(l) for l in lines) or 1
        avail_pt = 15.1 * 28.35
        size = max(7.2, min(9.0, avail_pt / (0.55 * max_units)))
        if len(lines) > 20:      # 高代码块略缩小，尽量整块落在一页
            size = min(size, 8.2)

        p = self.doc.add_paragraph()
        pf = p.paragraph_format
        pf.left_indent = Cm(0.15)
        pf.right_indent = Cm(0.15)
        pf.space_before = Pt(4)
        pf.space_after = Pt(10)
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = 1.1
        pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
        shade(p._p.get_or_add_pPr(), "F6F7F9")
        para_borders(p, top=(4, "D9DEE5"), left=(4, "D9DEE5"), bottom=(4, "D9DEE5"),
                     right=(4, "D9DEE5"))
        if len(lines) <= 18:
            pf.keep_together = True
        for idx, line in enumerate(lines):
            if idx:
                p.add_run().add_break()
            set_font(p.add_run(line), size=size, color=RGBColor(0x1A, 0x1A, 0x1A), mono=True)

    def table(self, rows, aligns):
        if not rows:
            return
        ncol = len(rows[0])
        body = [list(r[:ncol]) + [""] * max(0, ncol - len(r)) for r in rows[1:]]
        if not body:
            return

        weights = []
        for c in range(ncol):
            lens = [disp_width(r[c]) for r in [rows[0]] + body]
            weights.append(max(4, min(max(lens), 24)))
        total = sum(weights)
        widths = [TEXT_W.cm * w / total for w in weights]
        widths = [min(max(w, 1.35), 8.0) for w in widths]
        scale = TEXT_W.cm / sum(widths)
        widths = [w * scale for w in widths]
        fsize = 8.5 if (any(a == "right" for a in aligns) or ncol >= 6) else 9.0

        table = self.doc.add_table(rows=0, cols=ncol)
        hdr = table.add_row()
        repeat_header(hdr)
        cant_split(hdr)
        for i, text in enumerate(rows[0]):
            cell = hdr.cells[i]
            cell_shading(cell, "1F4E79")
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.line_spacing = 1.12
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_inline(p, text, size=fsize, color=C_WHITE, bold=True, mono_inline=False)
            for run in p.runs:
                run.font.bold = True
                run.font.color.rgb = C_WHITE

        for ridx, cells in enumerate(body):
            row = table.add_row()
            cant_split(row)
            for i, text in enumerate(cells):
                cell = row.cells[i]
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                if ridx % 2 == 1:
                    cell_shading(cell, "F2F5F9")
                p = cell.paragraphs[0]
                p.paragraph_format.space_before = Pt(0.5)
                p.paragraph_format.space_after = Pt(0.5)
                p.paragraph_format.line_spacing = 1.15
                al = aligns[i] if i < len(aligns) else "left"
                p.alignment = (WD_ALIGN_PARAGRAPH.RIGHT if al == "right"
                               else WD_ALIGN_PARAGRAPH.CENTER if al == "center"
                               else WD_ALIGN_PARAGRAPH.LEFT)
                add_inline(p, text, size=fsize, color=C_TEXT)

        fixed_layout(table, widths)
        cell_margins(table, top=0.05, bottom=0.05, left=0.12, right=0.12)
        table_borders(table, outer=6, inner=4, color="C9D3DF")

        spacer = self.doc.add_paragraph()
        spacer.paragraph_format.space_after = Pt(6)
        spacer.paragraph_format.line_spacing = 0.7
        set_font(spacer.add_run(""), size=5)

    def image(self, alt, rel_path):
        path = os.path.normpath(os.path.join(self.base_dir, rel_path))
        if not os.path.exists(path):
            p = self.doc.add_paragraph()
            add_inline(p, "[图片缺失：" + alt + "]", size=9.5, color=C_GRAY)
            return
        stem = os.path.splitext(os.path.basename(path))[0]
        kind, _, org = stem.partition("_")
        self.fig += 1
        caption = f"图 {self.chapter}-{self.fig}　{ORG_NAME.get(org, '')}{FIG_KIND.get(kind, alt)}"

        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.first_line_indent = Cm(0)
        p.add_run().add_picture(path, width=Cm(14.9))

        cp = self.doc.add_paragraph(style="Caption")
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(cp.add_run(caption), size=9, color=C_GRAY,
                 ascii_font=FONT_BODY_ASCII, ea_font=FONT_BODY_EA)


# --------------------------------------------------------------------------- #
# 章节处理
# --------------------------------------------------------------------------- #
META_RE = re.compile(r"^\*\*(.+?)\*\*[：:]\s*(.*)$")


def strip_number(text: str) -> str:
    return re.sub(r"^\d+(\.\d+)*\.?\s*", "", text).strip()


def split_chapter(md_text: str):
    lines = md_text.splitlines()
    body_start = 0
    for idx, line in enumerate(lines):
        if line.strip().startswith("# "):
            body_start = idx + 1
            break
    meta = []
    idx = body_start
    while idx < len(lines):
        s = lines[idx].strip()
        if not s:
            idx += 1
            continue
        m = META_RE.match(s)
        if not m:
            break
        meta.append((m.group(1), m.group(2).strip()))
        idx += 1
    return meta, "\n".join(lines[idx:])


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs_dir = os.path.join(here, "docs")
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(docs_dir, f"{DOC_TITLE}.docx")

    doc = Document()
    setup_styles(doc)
    setup_toc_styles(doc)
    setup_section(doc.sections[0])

    props = doc.core_properties
    props.title = DOC_TITLE
    props.subject = "朔黄铁路碳排放趋势预测模块 系统设计文档（合并版）"
    props.author = "碳排放趋势预测项目组"
    props.keywords = "碳排放预测;系统设计;数据库设计;接口文档;模型评测"
    props.comments = "由《系统设计说明书》《数据库设计》《接口文档》《模型评测与预测报告》合并"

    build_cover(doc)

    new_sec = doc.add_section(WD_SECTION.NEW_PAGE)
    setup_section(new_sec)
    build_header_footer(new_sec)

    renderer = Renderer(doc, docs_dir)
    toc_placeholder = doc.add_paragraph()
    toc_placeholder.paragraph_format.space_after = Pt(0)

    for chap in CHAPTERS:
        with open(os.path.join(docs_dir, chap["file"]), "r", encoding="utf-8") as fh:
            md = fh.read()
        meta, body = split_chapter(md)
        renderer.chapter = chap["num"]
        renderer.sec = 0
        renderer.sub = 0
        renderer.fig = 0
        renderer.heading1(f"第 {chap['num']} 章　{chap['title']}")
        renderer.meta_box(meta)
        for b in parse_markdown(body.replace("\r\n", "\n")):
            if b.kind == "h":
                if b.level == 1:
                    renderer.heading1(b.text)
                elif b.level == 2:
                    renderer.heading2(strip_number(b.text))
                else:
                    renderer.heading3(strip_number(b.text))
            elif b.kind == "p":
                renderer.paragraph(b.text)
            elif b.kind == "list":
                renderer.list_item(b.marker, b.text, b.level)
            elif b.kind == "quote":
                renderer.quote(b.text)
            elif b.kind == "code":
                renderer.code(b.lines, b.lang)
            elif b.kind == "table":
                renderer.table(b.rows, b.aligns)
            elif b.kind == "img":
                renderer.image(b.alt, b.path)

    pages = {}
    if os.environ.get("TOC_PAGES"):
        pages = json.loads(os.environ["TOC_PAGES"])

    marker = toc_placeholder._p
    build_toc(doc, renderer.headings, pages, marker)
    marker.getparent().remove(marker)

    normalize_order(doc)
    doc.save(out)
    print(f"saved: {out}")
    print(f"paragraphs={len(doc.paragraphs)} tables={len(doc.tables)} "
          f"headings={len(renderer.headings)}")


if __name__ == "__main__":
    main()
