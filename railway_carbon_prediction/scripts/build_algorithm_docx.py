"""Build《铁路碳排放趋势预测算法设计》DOCX from the implemented system."""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "artifacts" / "figures"
OUT = ROOT / "docs" / "铁路碳排放趋势预测算法设计_V1.1.docx"

DARK = RGBColor(0x1F, 0x3A, 0x5F)
GRAY = RGBColor(0x59, 0x59, 0x59)
LIGHT_BLUE = "D9E2F3"
LIGHT_GRAY = "F2F3F4"
LIGHT_GREEN = "E8F5E9"


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------
def set_run_font(run, name="宋体", size=10.5, bold=False, color=None, italic=False):
    run.font.name = "Times New Roman"
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color is not None:
        run.font.color.rgb = color


def set_style_font(style, east="宋体", size=10.5, bold=False, color=None):
    style.font.name = "Times New Roman"
    style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), east)
    style.font.size = Pt(size)
    style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color


def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def set_repeat_table_header(row):
    trPr = row._tr.get_or_add_trPr()
    tblHeader = OxmlElement("w:tblHeader")
    tblHeader.set(qn("w:val"), "true")
    trPr.append(tblHeader)


def no_table_borders(t):
    tblPr = t._tbl.tblPr
    for old in tblPr.findall(qn("w:tblStyle")):
        tblPr.remove(old)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    tblPr.append(borders)


def set_cell_margins(cell, top=40, bottom=40, left=70, right=70):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for tag, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        el = OxmlElement(f"w:{tag}")
        el.set(qn("w:w"), str(val))
        el.set(qn("w:type"), "dxa")
        tcMar.append(el)
    tcPr.append(tcMar)


def add_bottom_border(paragraph, color="1F3A5F", sz="8"):
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), sz)
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), color)
    pBdr.append(bottom)
    pPr.append(pBdr)


def add_field(paragraph, instr, placeholder=""):
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = instr
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = placeholder
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr_el)
    run._r.append(fld_sep)
    run._r.append(text)
    run._r.append(fld_end)
    return run


def add_page_number(footer):
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("第 ")
    set_run_font(r, "宋体", 9, color=GRAY)
    add_field(p, "PAGE", "1")
    r2 = p.add_run(" 页")
    set_run_font(r2, "宋体", 9, color=GRAY)


def add_header(section, text="铁路碳排放趋势预测算法设计", version="V1.0"):
    header = section.header
    header.is_linked_to_previous = False
    p = header.paragraphs[0]
    p.text = ""
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p.add_run(text)
    set_run_font(r, "宋体", 9, color=GRAY)
    add_bottom_border(p, "BFBFBF", "4")
    p.paragraph_format.space_after = Pt(0)


# ---------------------------------------------------------------------------
# Content helpers
# ---------------------------------------------------------------------------
def parse_bold(paragraph, text, size=10.5, east="宋体", color=None):
    parts = re.split(r"(\*\*.*?\*\*)", text)
    for part in parts:
        if not part:
            continue
        bold = part.startswith("**") and part.endswith("**")
        content = part[2:-2] if bold else part
        run = paragraph.add_run(content)
        set_run_font(run, east, size, bold=bold, color=color)


def para(doc, text, indent=True, size=10.5, color=None, space_after=6):
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.space_after = Pt(space_after)
    if indent:
        p.paragraph_format.first_line_indent = Pt(21)
    parse_bold(p, text, size=size, color=color)
    return p


def bullet(doc, text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.line_spacing = 1.4
    p.paragraph_format.space_after = Pt(3)
    parse_bold(p, text, size=size)
    return p


def note(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.6)
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(text)
    set_run_font(r, "宋体", 9, color=GRAY, italic=True)
    return p


def code(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(6)
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), LIGHT_GRAY)
    pPr.append(shd)
    lines = text.strip("\n").split("\n")
    for i, line in enumerate(lines):
        r = p.add_run(line)
        set_run_font(r, "宋体", 8.5)
        r.font.name = "Consolas"
        if i < len(lines) - 1:
            r.add_break()
    return p


def formula(doc, text, number):
    p = doc.add_paragraph()
    p.paragraph_format.tab_stops.clear_all()
    p.paragraph_format.tab_stops.add_tab_stop(Cm(15.3), alignment=2)
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.left_indent = Cm(0)
    r = p.add_run(text)
    set_run_font(r, "宋体", 8.8)
    r.font.name = "Cambria Math"
    p.add_run("\t")
    r2 = p.add_run(f"（{number}）")
    set_run_font(r2, "宋体", 8.8)
    return p


def caption(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run(text)
    set_run_font(r, "宋体", 9, bold=True, color=GRAY)


def figure(doc, filename, width_cm, cap):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(3)
    run = p.add_run()
    run.add_picture(str(FIG / filename), width=Cm(width_cm))
    caption(doc, cap)


def table(doc, headers, rows, widths=None, font_size=8.8, cap=None):
    if cap:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.keep_with_next = True
        r = p.add_run(cap)
        set_run_font(r, "宋体", 9, bold=True, color=GRAY)
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = True
    hdr = t.rows[0]
    set_repeat_table_header(hdr)
    trPr = hdr._tr.get_or_add_trPr()
    trPr.append(OxmlElement("w:cantSplit"))
    for i, h in enumerate(headers):
        c = hdr.cells[i]
        c.text = ""
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(str(h))
        set_run_font(r, "黑体", font_size, bold=True, color=DARK)
        shade(c, LIGHT_BLUE)
        c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_margins(c)
    for ri, row in enumerate(rows):
        new_row = t.add_row()
        new_row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        cells = new_row.cells
        for ci, val in enumerate(row):
            c = cells[ci]
            c.text = ""
            p = c.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if ci == 0 or isinstance(val, str) else WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run("" if val is None else str(val))
            set_run_font(r, "宋体", font_size)
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_margins(c)
            if ri % 2 == 1:
                shade(c, "F8F9FA")
    if widths:
        for i, w in enumerate(widths):
            for row in t.rows:
                row.cells[i].width = Cm(w)
    if len(rows) <= 6:
        for row in t.rows[:-1]:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.keep_with_next = True
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def h1(doc, text, page_break=True):
    p = doc.add_heading(text, level=1)
    p.paragraph_format.page_break_before = page_break
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(10)
    return p


def h2(doc, text):
    p = doc.add_heading(text, level=2)
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(5)
    return p


def h3(doc, text):
    p = doc.add_heading(text, level=3)
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    return p


# ---------------------------------------------------------------------------
# Document setup
# ---------------------------------------------------------------------------
def setup_styles(doc):
    normal = doc.styles["Normal"]
    set_style_font(normal, "宋体", 10.5)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(6)

    for name, size, before, after in [("Heading 1", 16, 12, 8), ("Heading 2", 13.5, 10, 5), ("Heading 3", 12, 8, 4)]:
        st = doc.styles[name]
        set_style_font(st, "黑体", size, bold=True, color=DARK)
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(after)
        st.paragraph_format.keep_with_next = True

    title = doc.styles["Title"]
    set_style_font(title, "黑体", 26, bold=True, color=DARK)
    title.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

    sub = doc.styles["Subtitle"]
    set_style_font(sub, "宋体", 12, color=GRAY)
    sub.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER


def setup_page(doc):
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(2.5)
    sec.bottom_margin = Cm(2.4)
    sec.left_margin = Cm(2.8)
    sec.right_margin = Cm(2.5)
    sec.header_distance = Cm(1.4)
    sec.footer_distance = Cm(1.3)
    sec.different_first_page_header_footer = True


def add_cover(doc):
    for _ in range(3):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("铁路碳排放趋势预测")
    set_run_font(r, "黑体", 28, bold=True, color=DARK)
    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = p2.add_run("算法设计")
    set_run_font(r2, "黑体", 30, bold=True, color=DARK)
    add_bottom_border(p2, "1F3A5F", "12")

    p3 = doc.add_paragraph()
    p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p3.paragraph_format.space_before = Pt(18)
    r3 = p3.add_run("基于朔黄铁路机辆 / 肃宁 / 原平 2019—2025 年月度数据")
    set_run_font(r3, "宋体", 12.5, color=GRAY)

    p4 = doc.add_paragraph()
    p4.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p4.paragraph_format.space_before = Pt(6)
    r4 = p4.add_run("异常检测 · GRA 因素筛选 · 滑动窗口 LSTM · 预测与折算")
    set_run_font(r4, "宋体", 11, color=GRAY)

    for _ in range(7):
        doc.add_paragraph()

    info = [
        ("文档版本", "V1.0"),
        ("文档状态", "设计版"),
        ("编制日期", "2026 年 11 月"),
        ("适用系统", "铁路碳排放趋势预测模块"),
    ]
    t = doc.add_table(rows=0, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for k, v in info:
        cells = t.add_row().cells
        cells[0].text = ""
        cells[1].text = ""
        p = cells[0].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = p.add_run(k + "：")
        set_run_font(r, "宋体", 10.5, color=GRAY)
        p2 = cells[1].paragraphs[0]
        r2 = p2.add_run(v)
        set_run_font(r2, "宋体", 10.5)
    doc.add_page_break()


def add_revision(doc):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p.add_run("文档信息与修订记录")
    set_run_font(r, "黑体", 15, bold=True, color=DARK)
    add_bottom_border(p, "1F3A5F", "6")
    doc.add_paragraph()
    table(doc,
          ["项目", "内容"],
          [["文档名称", "铁路碳排放趋势预测算法设计"],
           ["版本", "V1.0"],
           ["编制日期", "2026-11-01"],
           ["适用数据", "机辆、肃宁、原平 2019-01—2025-12 月度数据"],
           ["算法链路", "口径还原 → 异常检测 V2 → GRA → 滑动窗口 → SW-LSTM/基线 → 预测与折算"],
           ["实现位置", "railway_carbon_prediction/src/carbon_prediction"]],
          widths=[4.0, 11.5], font_size=9.5)
    table(doc,
          ["版本", "日期", "修订内容", "编制/修订"],
          [["V1.0", "2026-11-01", "初版：基于已实现的碳排放预测系统，描述算法流程、模块、公式、参数与验证结果", "算法设计组"]],
          widths=[2.0, 3.0, 9.5, 2.5], font_size=9.0)
    doc.add_page_break()


def add_abstract(doc):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p.add_run("摘要")
    set_run_font(r, "黑体", 16, bold=True, color=DARK)
    add_bottom_border(p, "1F3A5F", "6")
    doc.add_paragraph()
    para(doc, "本文档描述铁路碳排放趋势预测模块所采用的算法设计。系统面向朔黄铁路机辆、肃宁、原平三个分公司 2019—2025 年月度数据，构建“数据口径还原—异常检测—灰色关联筛选—滑动窗口 LSTM—预测与折算”的算法链路。针对电力排放因子多次切换、2025 年供热面积折算系数调整、内燃机车退役等真实数据特征，系统采用报表口径与可比口径双输出、柴油独立模块、异常复核/关注分流等设计。")
    para(doc, "算法核心包括：逐品种 STL 残差与 MAD 修正 z、raw/resid 双通道孤立森林、月度断点检测、日历与多变量证据、灰色关联分析、直接多步滑动窗口 LSTM，以及 Ridge/GBM/Holt-Winters/Seasonal Naive 基线与降级机制。训练采用多折滚动验证、MASE 主指标、LSTM 优先规则与年度完整窗口规则；预测阶段将非柴油可比排放与柴油模块相加，再按供热系数折算为报表口径。")
    para(doc, "在 2025 年留出测试中，机辆 SW-LSTM（W=12）MASE=1.0906、MAPE=9.75%；肃宁 Ridge（W=6）MASE=0.4822、MAPE=10.56%；原平 GBM（W=6）MASE=0.6393、MAPE=8.15%。2026 年 BAU 预测分别为 913,940、25,404、29,964 tCO2e（可比口径）。异常检测 V2 固化复核级异常 8 条、关注级 143 条、热力规则事件 3 条。")
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    r = p.add_run("关键词：")
    set_run_font(r, "黑体", 10.5, bold=True)
    r2 = p.add_run("铁路碳排放；异常检测；灰色关联分析；滑动窗口；LSTM；可比口径")
    set_run_font(r2, "宋体", 10.5)
    doc.add_page_break()


def add_toc(doc):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = p.add_run("目录")
    set_run_font(r, "黑体", 16, bold=True, color=DARK)
    add_bottom_border(p, "1F3A5F", "6")
    note(doc, "目录为 Word 域；首次打开如未显示页码，请右键“更新域”或按 F9 更新。")
    p = doc.add_paragraph()
    add_field(p, 'TOC \\o "1-3" \\h \\z \\u', "右键更新目录")
    doc.add_page_break()


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------
def ch1(doc):
    h1(doc, "1 目标与范围", page_break=False)
    h2(doc, "1.1 目标")
    para(doc, "本文档面向铁路碳排放趋势预测模块的算法实现，描述从原始月度台账到未来 12 个月预测的完整算法流程、模块划分、输入输出契约、核心公式、参数选择与训练方式。文档以已实现的系统为准，不描述平台前端、权限、部署等非算法内容。")
    bullet(doc, "建立可复现的月度碳排放数据口径，区分报表口径与可比口径；")
    bullet(doc, "识别数据错误、计量异常、真实业务跃变与季节峰谷，并给出处置；")
    bullet(doc, "用灰色关联分析筛选外部因素，降低小样本下的维度；")
    bullet(doc, "用滑动窗口 LSTM 及基线模型完成未来 12 个月预测；")
    bullet(doc, "把预测结果写回数据库，供平台其他模块查询。")

    h2(doc, "1.2 数据对象")
    table(doc,
          ["项目", "内容"],
          [["组织", "机辆分公司（JLG）、肃宁分公司（SNF）、原平分公司（YPF）"],
           ["时间范围", "2019-01—2025-12，每组织 84 个月"],
           ["核心活动量", "货运周转量（仅机辆）、天然气、汽油、柴油、电力总和、牵引电力（仅机辆）、辅助生产电力、热力"],
           ["排放结果", "天然气、汽油、柴油、电力、热力分项排放与总排放"],
           ["外部因子", "四地气温/HDD、秦皇岛港动力煤长协价、三省原煤产量、全国铁路货运量、全国火力发电量、政策事件"],
           ["数据规模", "252 条月度排放记录、1,932 条活动数据、2,244 条外部因子"]],
          widths=[3.2, 12.3], font_size=9.2, cap="表 1-1 数据对象")

    h2(doc, "1.3 算法边界")
    para(doc, "本文档覆盖：数据口径还原、异常检测、GRA 因素筛选、滑动窗口构造、SW-LSTM/基线训练、预测与报表折算、增量训练。")
    para(doc, "不覆盖：碳排放核算方法学与排放因子制定、平台前端、权限与组织管理、碳交易与碳资产管理、政策情景曲线的外推（本期仅 BAU）。")

    h2(doc, "1.4 关键设计约束")
    table(doc,
          ["约束", "数据证据", "算法响应"],
          [["电力因子多次切换", "2019—2021 为 0.8843；2022 为 0.5703；2023 为 0.5568；2024 为 0.5366；2025 为 0.5306", "构造可比口径目标，固定 2025 因子 0.5306；报表口径按当年因子"],
           ["2025 供热系数调整", "肃宁 0.9224→0.380；原平 0.9224→0.334；面积未变", "还原物理热力后建模；报表口径保留原值"],
           ["柴油结构断点", "机辆柴油 2024 年 18,735.74 t 降至 2025 年 9,529.50 t", "柴油独立模块，按台数×单机强度预测；不进入 LSTM 目标"],
           ["小样本", "84 个月，W=12 时仅 61 个窗口", "W∈{6,9,12}；多折验证；Ridge/GBM/HW/SN 降级与对照"],
           ["异常噪声", "84 个点上“关注”级可达 100+ 条", "复核级/关注级分流；关注级进入独立监控表"]],
          widths=[3.0, 7.2, 5.3], font_size=8.8, cap="表 1-2 关键设计约束")

    h2(doc, "1.5 符号与术语")
    table(doc,
          ["符号/术语", "含义"],
          [["E_rep,t", "第 t 月报表口径总排放，tCO2e"],
           ["E_cmp,t", "第 t 月可比口径总排放，tCO2e"],
           ["y_t", "建模目标：可比口径总排放减去柴油排放"],
           ["P_elec,t", "第 t 月电力总和，MWh"],
           ["H_t", "第 t 月物理热力，GJ"],
           ["D_t", "第 t 月柴油消耗，t"],
           ["EF_elec(year)", "当年电力排放因子，tCO2/MWh"],
           ["EF_heat", "热力排放因子，0.11 tCO2/GJ"],
           ["W", "滑动窗口长度（月）"],
           ["H", "预测步长（月），本文取 12"],
           ["F", "每个时间步的特征数"],
           ["MASE", "平均绝对误差 / 季节 naive 平均绝对误差"]],
          widths=[4.0, 11.0], font_size=9.0, cap="表 1-3 符号与术语")


def ch2(doc):
    h1(doc, "2 总体算法流程")
    h2(doc, "2.1 流程阶段")
    table(doc,
          ["阶段", "名称", "主要工作", "输出"],
          [["P1", "数据准备", "读取原始 Excel、字段标准化、口径还原、缺失推算、排放计算", "activity / emission 双表、数据版本"],
           ["P2", "异常治理", "STL/MAD、双通道森林、断点、日历/多变量、C1—C4 分类、复核/关注分流", "异常表、关注表、处置记录"],
           ["P3", "因素筛选", "GRA 无量纲化、关联系数、rho 敏感性、去趋势、共线剔除", "入选变量集、关联度排序"],
           ["P4", "样本构造", "滑动窗口、直接多步、训练/验证/测试划分、标准化", "三维张量、scaler、特征顺序"],
           ["P5", "模型训练", "SW-LSTM、Ridge/GBM/HW/SN、多折验证、窗口/超参搜索、冠军选择", "模型工件、指标 JSON"],
           ["P6", "预测折算", "非柴油预测 + 柴油模块 + 热力折算 + 区间 + 写库", "prediction_forecast"]],
          widths=[1.3, 3.0, 8.6, 3.3], font_size=8.8, cap="表 2-1 算法流程阶段")

    h2(doc, "2.2 数据流")
    para(doc, "总体数据流如图 2-1 所示。数据准备阶段同时产出报表口径与可比口径；异常治理阶段对活动量与总排放做检测；GRA 与滑窗使用治理后的可比口径；模型输出非柴油可比排放，再与柴油模块相加；最后按供热系数折算为报表口径并写库。")
    figure(doc, "fig_01_overall_flow.png", 16.2, "图 2-1 总体算法流程")

    h2(doc, "2.3 阶段门控")
    table(doc,
          ["门控", "位置", "通过条件", "未通过处置"],
          [["G1", "P1 末", "三个组织各 84 个月；活动量非负；年度排放恒等式偏差 <0.5%", "阻断，补数据或修正口径"],
           ["G2", "P2 末", "复核级异常 100% 有处置；关注级已入监控表；热力规则事件已登记", "阻断，补处置"],
           ["G3", "P3 末", "至少 1 个变量入选；无强共线残留；入选数 ≤ floor(N/20)", "告警，使用 G3 兜底变量集"],
           ["G4", "P5 末", "测试集 MASE 优于季节 naive；无数据泄露", "回退基线或检查边界"],
           ["G5", "P6 末", "预测区间、口径、假设完整；12 个月写库", "告警，补预测/说明"]],
          widths=[1.2, 2.0, 8.3, 4.7], font_size=8.8, cap="表 2-2 阶段门控")

    h2(doc, "2.4 运行模式")
    table(doc,
          ["模式", "触发", "行为", "输出"],
          [["历史导入", "首次上线/重导", "全量 2019—2025 入库，生成数据版本", "activity/emission/外部因子"],
           ["全量训练", "新增 ≥12 个月/口径变更", "重新 GRA、选 W/模型、2025 留出评估、2019—as_of 重训", "新冠军模型"],
           ["增量微调", "新增 1—11 个月", "加载冠军工件，LSTM lr=1e-4、40 epoch；Ridge/GBM refit", "v1.0-ft 模型"],
           ["预测", "训练后/月度", "直接 12 步预测，柴油模块相加，报表折算，写库", "prediction_forecast"],
           ["增量接入", "平台推送", "写入 activity，重算 emission，单点异常检测", "批次/异常/关注"]],
          widths=[2.4, 3.2, 8.4, 2.6], font_size=8.8, cap="表 2-3 运行模式")

    h2(doc, "2.5 算法与模块映射")
    table(doc,
          ["模块", "职责", "主要文件"],
          [["M1 数据接入", "读取原始文件、字段标准化、数据版本", "data.py"],
           ["M2 口径还原", "双口径排放、电力因子、供热系数、缺失推算", "data.py"],
           ["M3 异常检测", "STL/MAD、双通道森林、断点、日历/多变量", "anomaly_v2.py"],
           ["M4 异常分流", "复核级/关注级、人工复核、重算与审计", "pipeline.py、repository.py"],
           ["M5 GRA", "无量纲化、关联系数、rho 敏感性、去趋势、共线", "gra.py"],
           ["M6 特征/窗口", "特征面板、滑动窗口、划分、标准化", "features.py、dataset.py"],
           ["M7 模型", "SW-LSTM、Ridge、GBM、HW、SN、训练与选参", "models.py、pipeline.py"],
           ["M8 预测", "非柴油预测、柴油模块、热力折算、区间", "pipeline.py"],
           ["M9 评估", "MAE/RMSE/MAPE/sMAPE/MASE/R2/Bias", "metrics.py"],
           ["M10 存储/接口", "模型注册、预测写库、REST API", "repository.py、api.py"]],
          widths=[3.0, 9.0, 4.0], font_size=8.8, cap="表 2-4 算法与模块映射")


def ch3(doc):
    h1(doc, "3 数据预处理与口径还原算法")
    h2(doc, "3.1 输入字段")
    table(doc,
          ["字段", "类型", "说明"],
          [["org_id", "string", "JLG/SNF/YPF"],
           ["period", "date", "每月 1 日"],
           ["var_id", "string", "TURNOVER/GAS/GASOLINE/DIESEL/ELEC_TOTAL/ELEC_TRAC/ELEC_AUX/HEAT/HEAT_REPORTED"],
           ["value", "decimal", "物理/可比口径值"],
           ["reported_value", "decimal", "报表口径值；热力口径切换时与 value 不同"],
           ["source_status", "string", "原始/推算/补全/口径还原/异常剔除/无此项"],
           ["is_estimated", "tinyint", "是否推算"],
           ["quality_status", "string", "valid/pending/excluded"],
           ["data_flag", "string", "结构断点/口径切换/待核实"]],
          widths=[3.4, 2.6, 10.0], font_size=9.0, cap="表 3-1 活动数据字段")

    h2(doc, "3.2 双口径定义")
    para(doc, "报表口径按当年实际电力因子与供热系数计算，用于对外报送；可比口径固定 2025 年电力因子 0.5306、供热面积系数 0.9224 GJ/m²，用于趋势建模。")
    formula(doc, "E_rep,t = E_gas,t + E_gasoline,t + E_diesel,t + P_elec,t × EF_elec(year) + H_rep,t × EF_heat", "3-1")
    formula(doc, "E_cmp,t = E_gas,t + E_gasoline,t + E_diesel,t + P_elec,t × 0.5306 + H_t × 0.11", "3-2")
    formula(doc, "y_t = E_cmp,t − E_diesel,t", "3-3")
    formula(doc, "E_diesel,t = D_t × 3.145245", "3-4")
    para(doc, "其中 E_gas、E_gasoline、E_diesel 分别为天然气、汽油、柴油排放；H_rep 为报表热力，H 为物理热力；EF_heat=0.11 tCO2/GJ。")

    h2(doc, "3.3 电力因子切换")
    table(doc,
          ["期间", "电力因子（tCO2/MWh）", "处理"],
          [["2019—2021", "0.8843", "报表使用；可比统一为 0.5306"],
           ["2022", "0.5703", "报表使用；可比统一为 0.5306"],
           ["2023", "0.5568", "报表使用；可比统一为 0.5306"],
           ["2024", "0.5366", "报表使用；可比统一为 0.5306"],
           ["2025", "0.5306", "报表与可比一致"]],
          widths=[3.0, 5.0, 7.8], font_size=9.2, cap="表 3-2 电力因子切换")

    h2(doc, "3.4 热力系数还原")
    para(doc, "2025 年肃宁、原平供热面积折算系数调整，但供热面积未变。为保持物理热力可比，按面积部分还原到 0.9224 GJ/m² 基准：")
    formula(doc, "H_phys,SNF = H_area,rep × (0.9224 / 0.380) + H_meter", "3-5")
    formula(doc, "H_phys,YPF = H_rep × (0.9224 / 0.334)", "3-6")
    para(doc, "还原后肃宁 2025 年物理热力约 65,348.66 GJ，原平约 170,335.85 GJ；报表热力仍保留 37,885.16 GJ、61,678.42 GJ。")

    h2(doc, "3.5 缺失推算")
    h3(doc, "3.5.1 机辆货运周转量（2019—2020）")
    para(doc, "按 2021—2025 年同月“周转量/电量”中位数推算：")
    formula(doc, "T_m = P_elec,m × median(T/P_elec)_same_month", "3-7")
    note(doc, "周转量仅作解释变量，不进入最终预测特征；推算结果标记 source_status=推算-电量系数法。")

    h3(doc, "3.5.2 机辆牵引/辅助电力拆分（2019—2023）")
    para(doc, "仅对机辆分公司执行。肃宁、原平没有牵引电力，电力总和全部归辅助生产电力，不生成牵引电力记录。机辆以 2024—2025 年同月辅助用电占比中位数拆分，保持合计不变：")
    formula(doc, "P_aux,m = P_total,m × median(P_aux/P_total)_same_month", "3-8")
    formula(doc, "P_trac,m = P_total,m − P_aux,m", "3-9")
    note(doc, "以上拆分仅用于 2019—2023 历史缺失段。2024 年起机辆已有实测牵引/辅助数据；后续月度接入不再自动拆分，数据源必须同时提供 ELEC_TOTAL、ELEC_TRAC、ELEC_AUX，并校验三者闭合。")

    h3(doc, "3.5.3 肃宁天然气（2019—2021）")
    para(doc, "仅有年总量，按 HDD 权重分摊到 12 个月，保持年总量不变：")
    formula(doc, "w_m = (0.3 + 0.7 × HDD_m / mean(HDD)) / Σ_k w_k", "3-10")

    h2(doc, "3.6 柴油拆分与结构断点")
    para(doc, "机辆柴油 2024 年 18,735.74 t、2025 年 9,529.50 t，降幅约 49%，对应内燃机车由 2024 年下半年逐步减至 2025 年一季度 16 台。柴油不进入 LSTM 目标，由独立模块按台数强度预测：")
    formula(doc, "D_target = D_ref × N_target / N_ref", "3-11")
    para(doc, "2026 年按 15 台、2025 年 16 台推算；月度按参考年同月占比分摊。柴油排放按式（3-4）计算。")

    h2(doc, "3.7 数据质量状态")
    table(doc,
          ["字段/值", "含义", "训练是否使用"],
          [["source_status=原始", "台账原值", "是"],
           ["source_status=推算-电量系数法", "周转量缺失推算", "是（解释变量）"],
           ["source_status=推算-辅占比重构", "机辆牵引/辅助拆分", "是"],
           ["source_status=推算-供暖度日分摊", "年热力/天然气分摊", "是"],
           ["source_status=异常剔除-同期补全", "2024 机辆天然气", "是（补全值）"],
           ["source_status=口径还原", "2025 热力", "是（可比口径）"],
           ["quality_status=pending", "新增待复核", "否"],
           ["quality_status=excluded", "复核排除", "否"]],
          widths=[7.0, 5.5, 3.3], font_size=8.8, cap="表 3-3 数据质量状态")

    h2(doc, "3.8 口径校验")
    para(doc, "三个组织 2019—2025 年共 252 条月度排放记录，年度报表口径与原始台账年度合计偏差均小于 0.5%，全部通过校验。2025 年肃宁、原平报表热力与可比热力分列存储，避免“供热系数调整”被误读为减排。")
    table(doc,
          ["组织", "2019 报表", "2025 报表", "2019 可比", "2025 可比", "报表变化", "可比变化"],
          [["机辆", "1,457,258", "941,131", "893,083", "941,131", "-35.4%", "+5.4%"],
           ["肃宁", "42,296", "22,913", "28,495", "25,934", "-45.8%", "-9.0%"],
           ["原平", "32,673", "16,699", "26,267", "28,652", "-48.9%", "+9.1%"]],
          widths=[2.0, 2.6, 2.6, 2.6, 2.6, 2.2, 2.2], font_size=8.6, cap="表 3-4 报表/可比口径年度对比（tCO2e）")


def ch4(doc):
    h1(doc, "4 异常检测算法 V2")
    h2(doc, "4.1 检测对象")
    para(doc, "对每个组织×品种序列独立检测，品种包括电力总和、柴油、天然气、汽油、可比口径总排放。热力由供热规则解释，不进入统计检测，改由规则事件登记。每个序列至少 24 个月才建模。")
    table(doc,
          ["var_id", "名称", "单位", "检测方式"],
          [["ELEC_TOTAL", "电力总和", "MWh", "STL+MAD z、双通道森林、断点"],
           ["DIESEL", "柴油", "t", "STL+MAD z、双通道森林、断点"],
           ["GAS", "天然气", "万m³", "STL+MAD z、双通道森林"],
           ["GASOLINE", "汽油", "t", "STL+MAD z、双通道森林（只进关注）"],
           ["CO2_COMPARABLE", "可比总排放", "tCO2e", "STL+MAD z、双通道森林"],
           ["HEAT", "热力", "GJ", "规则登记，不做统计检测"]],
          widths=[3.8, 3.0, 2.4, 6.5], font_size=9.0, cap="表 4-1 异常检测对象")

    h2(doc, "4.2 证据层：STL 与 MAD 修正 z")
    h3(doc, "4.2.1 STL 分解")
    formula(doc, "y_t = T_t + S_t + R_t", "4-1")
    para(doc, "使用 statsmodels STL，period=12，robust=True。R_t 为残差，用于后续稳健统计；缺失值仅用于分解前插值，不改写原始表。")
    h3(doc, "4.2.2 MAD 修正 z")
    formula(doc, "med = median(R),  MAD = median(|R − med|)", "4-2")
    formula(doc, "σ = 1.4826 × MAD,  z_t = (R_t − med) / σ", "4-3")
    para(doc, "|z_t|>3 记为离群；|z_t|>5 升级为严重异常。MAD=0 时退化为残差标准差；仍为 0 则跳过该序列。")
    figure(doc, "fig_02_anomaly_flow.png", 13.6, "图 4-1 异常检测 V2 流程")

    h2(doc, "4.3 证据层：raw/resid 双通道孤立森林")
    table(doc,
          ["通道", "特征", "数量"],
          [["raw", "value、mom、yoy、roll_mean3、roll_std3、month_sin、month_cos、CAL_SPRING_FESTIVAL、CAL_COVID、CAL_MAINTENANCE", "10"],
           ["resid", "resid、resid_z、abs_resid_z、resid_roll_std3、month_sin、month_cos、CAL_SPRING_FESTIVAL、CAL_COVID、CAL_MAINTENANCE", "9"]],
          widths=[2.0, 12.0, 1.5], font_size=8.8, cap="表 4-2 双通道特征")
    formula(doc, "raw_score = −raw_model.score_samples(raw_X)", "4-4")
    formula(doc, "resid_score = −resid_model.score_samples(resid_X)", "4-5")
    formula(doc, "raw_flag = raw_score ≥ Q95(raw_score),  resid_flag = resid_score ≥ Q95(resid_score)", "4-6")
    para(doc, "两棵森林均为 200 棵树、max_samples=auto、contamination=0.05、random_state=20260928、n_jobs=1。both=raw_flag∧resid_flag 表示量级与残差形态同时异常，作为升级依据；仅 raw 可能由季节解释，转 C4 候选；仅 joint 不单独产出异常。")

    h2(doc, "4.4 证据层：月度断点")
    para(doc, "对每个候选切点 t（左右各至少 6 个月），采用池化统计量定位水平位移：")
    formula(doc, "pooled_std = sqrt[((n_L−1)·var_L + (n_R−1)·var_R)/(n−2)]", "4-7")
    formula(doc, "stat = |mean_R − mean_L| / pooled_std × sqrt(n_L·n_R/n)", "4-8")
    formula(doc, "shift_pct = (mean_R − mean_L)/|mean_L| × 100", "4-9")
    formula(doc, "CV_L = std_L/|mean_L|,  CV_R = std_R/|mean_R|", "4-10")
    table(doc,
          ["判据", "阈值", "作用"],
          [["stat", "≥3.0", "排除噪声"],
           ["|shift_pct|", "≥25%", "排除小幅漂移"],
           ["CV_R", "≤CV_L×1.5，或断点后均值≈0", "要求新稳态，排除质量台阶"]],
          widths=[3.0, 6.0, 6.5], font_size=9.0, cap="表 4-3 断点三判据")
    para(doc, "断点后 3 个月为过渡窗，仅窗内点标 C3；输出 breakpoint_date、breakpoint_stat、shift_pct、cv_ratio、in_breakpoint_window。")

    h2(doc, "4.5 证据层：日历与多变量")
    table(doc,
          ["事件", "期间", "作用"],
          [["春节", "2019—2026 共 8 段", "解释春节前后用电/运量回落"],
           ["疫情初期", "2020-01—2020-04", "解释 2020 年初需求冲击"],
           ["检修", "企业计划维护", "解释计划检修低位；本期未提供，取 0"]],
          widths=[3.0, 5.0, 7.5], font_size=9.0, cap="表 4-4 日历事件")
    para(doc, "多变量联合变量为 ELEC_TOTAL、DIESEL、GAS、GASOLINE、TURNOVER；标准化后加月份正余弦，训练孤立森林，取 95% 分位为 joint_flag。联合只作佐证：与单通道同时触发时提高置信度；不单独产出异常，避免小量级品种被电力淹没。")

    h2(doc, "4.6 证据层：确定性热力")
    para(doc, "热力由供热面积、月份、计费方式决定，零值月与档位跳变会被统计法大量误判。HEAT 不进入 STL/MAD/森林，已知年度调整以规则事件登记为 C3。")
    table(doc,
          ["组织", "期间", "年热力变化", "处置"],
          [["机辆", "2023-01", "72,809→88,618 GJ", "mark_breakpoint"],
           ["肃宁", "2023-11", "49,687→63,618 GJ", "mark_breakpoint"],
           ["原平", "2021-12", "142,318→159,377 GJ", "mark_breakpoint"]],
          widths=[2.5, 3.0, 7.5, 4.0], font_size=9.0, cap="表 4-5 热力规则事件")

    h2(doc, "4.7 分类层与分流层")
    table(doc,
          ["顺序", "条件", "类别", "分流"],
          [["1", "断点窗内", "C3", "复核级"],
           ["2", "日历可解释短段", "C1/C2", "关注级"],
           ["3", "连续段≥6", "C2", "复核/关注"],
           ["4", "|z|>3 且连续段≤1", "C1", "复核/关注"],
           ["5", "|z|>3 且连续段 2—5", "C2", "复核/关注"],
           ["6", "未定类", "UNDETERMINED", "严重进复核，否则关注"]],
          widths=[1.3, 7.5, 3.2, 4.5], font_size=8.8, cap="表 4-6 分类顺序")
    para(doc, "复核准入：C3、规则事件、天然气严重且连续段≥6、其他严重异常、双通道且|z|≥5。汽油、日历可解释短段、低物质性品种进入关注表。历史复核级 auto_closed；新增数据进入 pending，人工复核后重算排放并追加审计。")

    h2(doc, "4.8 参数")
    table(doc,
          ["参数", "取值", "说明"],
          [["n_estimators", "200", "森林树数"],
           ["max_samples", "auto", "min(256,N)"],
           ["contamination", "0.05", "森林预期异常比例"],
           ["random_state", "20260928", "全局种子"],
           ["STL period", "12", "月度周期"],
           ["MAD z 阈值", "3 / 5", "离群/严重"],
           ["森林分位", "0.95", "各通道触发"],
           ["断点最小段", "6 个月", "左右各至少 6"],
           ["断点 stat", "3.0", "判据①"],
           ["断点位移", "25%", "判据②"],
           ["断点 CV 比", "1.5", "判据③"],
           ["过渡窗", "3 个月", "断点后 3 个月"]],
          widths=[4.0, 4.0, 8.0], font_size=8.8, cap="表 4-7 异常检测参数")

    h2(doc, "4.9 验证结果")
    table(doc,
          ["组织", "期间", "变量", "类别", "score", "实测/中位数", "处置"],
          [["机辆", "2023-01", "天然气", "C2", "0.738", "0.680 / 0.070", "mark_breakpoint"],
           ["机辆", "2023-01", "热力", "C3", "0.000", "规则事件", "mark_breakpoint"],
           ["机辆", "2024-10", "柴油", "C3", "0.733", "851.85 / 1,589.61", "mark_breakpoint"],
           ["肃宁", "2021-12", "柴油", "C2", "0.660", "58.77 / 42.37", "mark_breakpoint"],
           ["肃宁", "2023-11", "热力", "C3", "0.000", "规则事件", "mark_breakpoint"],
           ["原平", "2021-01", "电力总和", "C2", "0.676", "3,796.33 / 1,396.99", "mark_breakpoint"],
           ["原平", "2021-12", "热力", "C3", "0.000", "规则事件", "mark_breakpoint"],
           ["原平", "2024-05", "柴油", "C1", "0.793", "133.31 / 31.22", "keep"]],
          widths=[1.8, 2.2, 2.7, 1.5, 1.5, 4.5, 3.0], font_size=8.4, cap="表 4-8 复核级异常（8 条）")
    para(doc, "柴油 2024-10 断点核实：stat=9.1938、shift=-47.744%、CV_R/CV_L=0.8734，满足三判据，判定 C3 persist。关注级 143 条（机辆 42、肃宁 58、原平 43），不进入复核队列。")
    table(doc,
          ["组织", "C1", "C2", "C3", "C4", "UNDETERMINED", "合计"],
          [["机辆", "12", "11", "1", "12", "6", "42"],
           ["肃宁", "12", "23", "0", "21", "2", "58"],
           ["原平", "15", "14", "0", "9", "5", "43"],
           ["合计", "39", "48", "1", "42", "13", "143"]],
          widths=[2.5, 2.0, 2.0, 2.0, 2.0, 3.5, 2.0], font_size=9.0, cap="表 4-9 关注级分布")

    h2(doc, "4.10 复杂度")
    para(doc, "每个序列训练两棵孤立森林，时间复杂度约 O(T·N log N)，T=200、N≤84；单次全量检测 15 条序列耗时约 6 s（CPU）。断点为 O(N²) 扫描，N=84 时可忽略。")


def ch5(doc):
    h1(doc, "5 灰色关联因素筛选算法")
    h2(doc, "5.1 序列与预处理")
    para(doc, "以可比口径总排放为参考序列 X0，以候选外部因子为比较序列 Xi。要求等时距、等长度、同期对齐；缺失率>10% 的变量直接排除，不做插值参与。")
    table(doc,
          ["候选因子", "单位", "类别"],
          [["采暖度日 HDD", "℃·d", "气象"],
           ["秦皇岛港 5500 大卡动力煤长协价", "元/吨", "价格"],
           ["三省原煤产量合计", "万吨", "供给"],
           ["全国铁路货运量", "万吨", "运输"],
           ["全国火力发电量", "亿千瓦时", "能源"],
           ["政策事件强度指数", "0—1", "政策"]],
          widths=[9.0, 3.0, 3.0], font_size=9.0, cap="表 5-1 GRA 候选因子")
    note(doc, "CDD 在原平全 0、在其他组织强零膨胀，初值化会产生伪高关联，故不进入主筛选；仍保留在外部因子表中备查。")

    h2(doc, "5.2 无量纲化")
    formula(doc, "x'_i(k) = x_i(k) / x_i(1)  （初值化）", "5-1")
    formula(doc, "x'_i(k) = (x_i(k) − min x_i)/(max x_i − min x_i)  （极差化）", "5-2")
    para(doc, "普通序列用初值化；零膨胀序列（HDD）零值占比>20% 时改用极差化，避免初值化把 0 值放大。")

    h2(doc, "5.3 关联系数与关联度")
    formula(doc, "Δ_i(k) = |x'_0(k) − x'_i(k)|", "5-3")
    formula(doc, "ξ_i(k) = (Δ_min + ρ·Δ_max)/(Δ_i(k) + ρ·Δ_max)", "5-4")
    formula(doc, "r_i = (1/n)·Σ_k ξ_i(k)", "5-5")
    para(doc, "ρ 默认 0.5；在 {0.1,0.3,0.5,0.7,0.9} 上重算，若关联度变化超过 0.05 标记 rho_sensitive。r 只表示趋势相似度，不是因果、贡献率或弹性。")

    h2(doc, "5.4 去趋势与伪关联")
    formula(doc, "r_detrend,i = GRA(Δy, Δx_i)", "5-6")
    para(doc, "若 r≥阈值且 r_detrend<0.6×阈值，标记 spurious_trend，降为备选。该步骤用于识别“共同单调趋势”造成的伪关联。")

    h2(doc, "5.5 共线、阈值与数量约束")
    formula(doc, "threshold = 0.70 − 0.10 × clip((48−n)/48, 0, 1)", "5-7")
    formula(doc, "k_max = floor(N/20)", "5-8")
    para(doc, "入选变量间 |Pearson|>0.85 时保留 r 更高者；入选数不超过 k_max。若无变量达阈值，按 G3 兜底取前 k 个，并在报告中标注“专家兜底”。")

    h2(doc, "5.6 参数")
    table(doc,
          ["参数", "取值", "说明"],
          [["无量纲化", "初值化/极差化", "零膨胀用极差化"],
           ["ρ", "0.5", "分辨系数"],
           ["ρ 网格", "0.1—0.9", "敏感性"],
           ["阈值", "0.70", "n≥48；小样本自适应下调"],
           ["去趋势阈值", "0.6×阈值", "伪关联"],
           ["共线阈值", "|Pearson|>0.85", "保留 r 高者"],
           ["数量上限", "floor(N/20)", "小样本约束"]],
          widths=[4.0, 5.0, 7.0], font_size=9.0, cap="表 5-2 GRA 参数")

    h2(doc, "5.7 结果")
    table(doc,
          ["组织", "排名", "因子", "r", "r_detrend", "入选"],
          [["机辆", "1", "全国火力发电量", "0.705", "0.670", "是"],
           ["机辆", "2", "全国铁路货运量", "0.692", "0.688", "否"],
           ["机辆", "3", "秦皇岛港动力煤长协价", "0.616", "0.632", "否"],
           ["肃宁", "1", "采暖度日", "0.651", "0.658", "是（兜底）"],
           ["肃宁", "2", "政策事件强度", "0.515", "0.487", "是（兜底）"],
           ["肃宁", "3", "全国火力发电量", "0.510", "0.701", "是（兜底）"],
           ["原平", "1", "采暖度日", "0.803", "0.785", "是"],
           ["原平", "2", "政策事件强度", "0.580", "0.599", "否"]],
          widths=[1.8, 1.5, 6.2, 2.0, 2.4, 2.8], font_size=8.8, cap="表 5-3 GRA 主要结果")
    para(doc, "机辆仅火电略高于阈值；肃宁无变量达阈值，按 G3 兜底取前 4；原平 HDD 稳定入选。外部政策因子整体偏弱，模型以历史自回归为主。")


def ch6(doc):
    h1(doc, "6 滑动窗口样本构造")
    h2(doc, "6.1 窗口重构")
    formula(doc, "X_t = [z_t, z_{t+1}, …, z_{t+W−1}]", "6-1")
    formula(doc, "Y_t = [z_{t+W}, z_{t+W+1}, …, z_{t+W+H−1}]", "6-2")
    formula(doc, "n_samples = N − W − H + 1", "6-3")
    para(doc, "每个时间步包含目标历史与入选特征，形成 W×F 张量；输出为 H=12 的直接多步向量。")

    h2(doc, "6.2 直接多步")
    para(doc, "采用 Direct 策略：一次前向输出 12 个月，不递归回灌，避免误差累积。输出层单元数为 H。")

    h2(doc, "6.3 划分与验证")
    table(doc,
          ["用途", "时间范围", "说明"],
          [["训练（选参折）", "2019—2021 / 2019—2022 / 2019—2023", "分别验证 2022/2023/2024"],
           ["验证（测试前）", "2024", "窗口长度/超参选择"],
           ["测试", "2025", "只评估一次"],
           ["最终重训", "2019—2025", "预测 2026"],
           ["留出预测", "2026-01—2026-12", "写库"]],
          widths=[4.0, 7.0, 5.0], font_size=9.0, cap="表 6-1 训练/验证/测试划分")
    para(doc, "训练窗口的目标期完全落在训练段内；验证/测试窗口的目标期落在其后；输入窗口只使用目标期之前的数据，禁止未来信息。测试集只用于最终评估，不参与 W/超参选择。")

    h2(doc, "6.4 标准化边界")
    para(doc, "特征使用 StandardScaler，目标使用 MinMaxScaler；两者只在训练段 fit，验证/测试/预测只 transform。scaler 参数、特征顺序、W、H 写入模型工件，推理时复用，禁止重新 fit。")

    h2(doc, "6.5 样本量")
    table(doc,
          ["W", "N=84 时窗口数", "N=72 时窗口数", "说明"],
          [["6", "67", "55", "短窗口，样本多"],
           ["9", "64", "52", "中等"],
           ["12", "61", "49", "年度完整周期，机辆冠军"]],
          widths=[2.0, 4.0, 4.0, 6.0], font_size=9.0, cap="表 6-2 窗口样本量（H=12）")


def ch7(doc):
    h1(doc, "7 滑动窗口 LSTM 模型")
    h2(doc, "7.1 建模目标")
    para(doc, "模型目标为 y_t = E_cmp,t − E_diesel,t，即非柴油可比排放。柴油由独立模块预测后相加，避免 2025 年退役断点被 LSTM 当作趋势。")
    h2(doc, "7.2 网络结构")
    figure(doc, "fig_03_lstm_arch.png", 15.0, "图 7-1 SW-LSTM 结构")
    table(doc,
          ["层", "配置", "说明"],
          [["输入", "(batch, W, F)", "F=目标历史+入选特征"],
           ["LSTM", "units=32/64，batch_first=True", "单层；forget bias=1.0"],
           ["Dropout", "0.2", "防止小样本过拟合"],
           ["Dense", "hidden/2，ReLU", "特征压缩"],
           ["输出", "H=12，线性", "直接多步"]],
          widths=[2.5, 6.5, 6.5], font_size=9.0, cap="表 7-1 SW-LSTM 结构")

    h2(doc, "7.3 LSTM 前向公式")
    formula(doc, "i_t = σ(W_i x_t + U_i h_{t−1} + b_i)", "7-1")
    formula(doc, "f_t = σ(W_f x_t + U_f h_{t−1} + b_f)", "7-2")
    formula(doc, "o_t = σ(W_o x_t + U_o h_{t−1} + b_o)", "7-3")
    formula(doc, "g_t = tanh(W_g x_t + U_g h_{t−1} + b_g)", "7-4")
    formula(doc, "c_t = f_t ⊙ c_{t−1} + i_t ⊙ g_t,  h_t = o_t ⊙ tanh(c_t)", "7-5")
    formula(doc, "ŷ = W_o h_T + b_o", "7-6")
    para(doc, "其中 σ 为 Sigmoid，⊙ 为逐元素乘；h_T 为窗口最后一步隐状态；ŷ 为 12 维标准化域输出，经 MinMax 逆变换还原。")

    h2(doc, "7.4 损失与训练")
    formula(doc, "L = (1/H)·Σ_{h=1}^{H} (y_h − ŷ_h)²", "7-7")
    para(doc, "优化器 Adam，lr=1e-3，weight_decay=1e-4，batch=16，epochs≤220，EarlyStopping patience=25，restore_best。梯度裁剪 clip_norm=1.0；LSTM forget gate bias 初始化为 1.0；全局种子 20260928。")
    code(doc, """
for epoch in 1..epochs:
    for batch in shuffle(train_loader):
        pred = model(batch.X)
        loss = MSE(pred, batch.Y)
        loss.backward()
        clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
    val_loss = evaluate(model, val_loader)
    if val_loss < best:
        save_best(); wait = 0
    else:
        wait += 1
        if wait >= patience: break
restore_best()
""")
    para(doc, "早停验证集来自训练窗口末尾 20%，不使用 2024/2025 评估段，避免测试信息进入训练。")

    h2(doc, "7.5 窗口与超参搜索")
    table(doc,
          ["阶段", "搜索空间", "选择依据"],
          [["第一阶段", "W∈{6,9,12}", "固定 hidden=32，三折平均 MASE"],
           ["第二阶段", "hidden∈{32,64}", "W* 下三折平均 MASE"],
           ["候选模型", "SW-LSTM/Ridge/GBM/HW/SN", "同一折协议"],
           ["LSTM 优先", "与最优模型差距≤10%", "按方案优先选 SW-LSTM"],
           ["年度窗口", "LSTM 最优 2% 内取较大 W", "年度展望优先完整周期"]],
          widths=[3.0, 7.0, 6.0], font_size=9.0, cap="表 7-2 窗口/超参选择")

    h2(doc, "7.6 基线与降级")
    table(doc,
          ["模型", "配置", "作用"],
          [["Ridge", "alpha=10，多输出", "线性基线/降级"],
           ["GBM", "250 棵，lr=0.05，depth=3，subsample=0.9", "非线性基线"],
           ["Holt-Winters", "additive trend/season", "统计基线"],
           ["Seasonal Naive", "去年同月", "最低基线"],
           ["SW-LSTM", "W×F → LSTM → H", "主模型"]],
          widths=[3.2, 8.8, 4.0], font_size=9.0, cap="表 7-3 模型集合")

    h2(doc, "7.7 冠军选择")
    para(doc, "以三折（2022/2023/2024）平均 MASE 为主指标；若 SW-LSTM 与最优模型差距≤10%，优先 SW-LSTM；LSTM 内部在最优 2% 误差带内取较大 W。2025 测试集只评估一次，不参与选择。")
    para(doc, "最终冠军：机辆 SW-LSTM W=12、hidden=32；肃宁 Ridge W=6；原平 GBM W=6。")

    h2(doc, "7.8 训练参数")
    table(doc,
          ["参数", "取值", "说明"],
          [["seed", "20260928", "全局"],
           ["lr", "1e-3", "Adam"],
           ["weight_decay", "1e-4", "L2"],
           ["batch", "16", "小样本"],
           ["epochs", "≤220", "早停"],
           ["patience", "25", "验证损失"],
           ["dropout", "0.2", "LSTM 后"],
           ["grad clip", "1.0", "防爆炸"],
           ["forget bias", "1.0", "长期依赖"],
           ["hidden", "32/64", "搜索"]],
          widths=[3.5, 4.0, 8.0], font_size=8.8, cap="表 7-4 LSTM 训练参数")

    h2(doc, "7.9 模型工件")
    para(doc, "每个模型保存权重（model.pt 或 model.joblib）、scaler.json、特征顺序、W/H、超参、训练区间、指标 JSON、数据版本。推理时先加载 scaler 与特征顺序，禁止重新 fit 或改变列顺序。")
    code(doc, """
artifacts/models/{model_id}/
  model.pt | model.joblib
  scaler.json
prediction_model: feature_order / scaler_state / hyperparams / metrics
""")


def ch8(doc):
    h1(doc, "8 预测、折算与增量训练")
    h2(doc, "8.1 直接 12 步预测")
    para(doc, "取最近 W 个月特征，标准化后输入冠军模型，一次输出 12 个月标准化预测，逆变换得到非柴油可比排放。")
    formula(doc, "ŷ_{t+1:t+12} = f_SW-LSTM(X_{t−W+1:t})", "8-1")
    formula(doc, "Ê_cmp,t+h = ŷ_nondiesel,t+h + Ê_diesel,t+h", "8-2")

    h2(doc, "8.2 柴油模块")
    formula(doc, "D_target = D_ref × N_target/N_ref", "8-3")
    para(doc, "机辆 2026 年按 15 台、2025 年 16 台；月度按参考年同月占比分摊。肃宁/原平柴油量小，用上年同月季节 naive。")

    h2(doc, "8.3 报表口径折算")
    formula(doc, "Ê_rep,t+h = Ê_cmp,t+h − (H_phys,t+h − H_rep,t+h) × 0.11", "8-4")
    para(doc, "肃宁/原平按 2025 年热力系数差折算；机辆热力口径未变，差值为 0。")

    h2(doc, "8.4 预测区间")
    para(doc, "以 2025 测试残差的相对分位数给出 90% 名义区间：")
    formula(doc, "q_lo = Q5((y−ŷ)/y),  q_hi = Q95((y−ŷ)/y)", "8-5")
    formula(doc, "lower = ŷ(1+q_lo),  upper = ŷ(1+q_hi)", "8-6")
    para(doc, "2025 实际覆盖率：机辆 75%、肃宁 92%、原平 83%。区间作为不确定性提示，不作为承诺值。")

    h2(doc, "8.5 增量训练")
    table(doc,
          ["模式", "行为", "适用"],
          [["full", "重新 GRA/选参/2025 评估/2019—as_of 重训", "新增≥12 月/口径变更"],
           ["finetune", "加载冠军工件，LSTM lr=1e-4、40 epoch；Ridge/GBM refit", "新增 1—11 月"],
           ["auto", "按 train_end 与 as_of 月数自动选择", "月度例行"]],
          widths=[2.5, 9.5, 4.0], font_size=9.0, cap="表 8-1 增量训练模式")


def ch9(doc):
    h1(doc, "9 功能模块与模块级输入/输出")
    h2(doc, "9.1 模块清单")
    table(doc,
          ["模块", "输入", "输出", "关键规则"],
          [["M1 数据接入", "原始 Excel/CSV、组织/品种元数据", "标准化长表、数据版本", "字段/单位/期间校验"],
           ["M2 口径还原", "活动量、电力因子、供热系数", "报表/可比排放", "双口径；年度总量校验"],
           ["M3 异常检测", "可比总排放、活动量、日历", "复核级/关注级异常", "双通道+断点+MAD"],
           ["M4 异常复核", "异常记录、复核动作", "处置结果、审计、重算排放", "keep/correct/exclude/mark"],
           ["M5 GRA", "目标序列、候选因子", "关联度、入选变量", "初值/极差、rho、去趋势"],
           ["M6 特征/窗口", "治理后序列、入选变量", "X 张量、y 张量、scaler", "训练段 fit，禁止泄露"],
           ["M7 模型训练", "窗口张量、参数", "模型工件、指标", "多折 MASE、冠军选择"],
           ["M8 预测", "冠军模型、柴油计划、热力系数", "12 月可比/报表预测", "非柴油+柴油；热力折算"],
           ["M9 评估", "预测值、实际值", "MAE/RMSE/MAPE/MASE/R2", "2025 留出"],
           ["M10 存储/API", "模型/预测/异常", "数据库/JSON", "幂等、审计、版本"]],
          widths=[2.6, 4.5, 4.5, 4.4], font_size=8.4, cap="表 9-1 功能模块与 I/O")

    h2(doc, "9.2 关键输入/输出契约")
    table(doc,
          ["对象", "字段", "约束"],
          [["活动数据", "org_id, period, var_id, value, reported_value, unit, source_status, quality_status", "非负；唯一键 org+period+var"],
           ["排放结果", "org_id, period, total_reported_tco2, total_comparable_tco2", "年度校验；双口径"],
           ["异常", "org_id, period, var_id, level, category, score, channels, context_flags, final_disposition", "复核级/关注级分开"],
           ["模型", "model_id, org_id, model_type, W, feature_order, scaler_state, metrics", "冠军唯一；工件路径"],
           ["预测", "model_id, org_id, period, scenario, point, lower, upper, reported_point", "12 个月；BAU"]],
          widths=[2.8, 9.0, 3.8], font_size=8.6, cap="表 9-2 关键契约")

    h2(doc, "9.3 API")
    table(doc,
          ["方法", "路径", "用途"],
          [["POST", "/api/v1/prediction/ingest/monthly", "月度增量接入"],
           ["GET", "/api/v1/prediction/anomalies", "复核级异常"],
           ["GET", "/api/v1/prediction/anomalies/watch", "关注级监控"],
           ["POST", "/api/v1/prediction/anomalies/{id}/review", "人工复核"],
           ["POST", "/api/v1/prediction/train", "训练任务"],
           ["POST", "/api/v1/prediction/forecast", "未来 12 月预测"],
           ["GET", "/api/v1/prediction/gra", "GRA 结果"],
           ["GET", "/api/v1/prediction/models", "模型注册表"]],
          widths=[2.0, 9.5, 4.5], font_size=8.8, cap="表 9-3 主要 API")


def ch10(doc):
    h1(doc, "10 算法评估")
    h2(doc, "10.1 指标公式")
    formula(doc, "MAE = (1/n)Σ|y_i − ŷ_i|", "10-1")
    formula(doc, "RMSE = sqrt((1/n)Σ(y_i − ŷ_i)²)", "10-2")
    formula(doc, "MAPE = (100%/n)Σ|(y_i − ŷ_i)/y_i|", "10-3")
    formula(doc, "sMAPE = (100%/n)Σ 2|y_i − ŷ_i|/(|y_i|+|ŷ_i|)", "10-4")
    formula(doc, "MASE = MAE_model / MAE_seasonal_naive(train)", "10-5")
    formula(doc, "R² = 1 − Σ(y_i − ŷ_i)²/Σ(y_i − ȳ)²", "10-6")
    formula(doc, "Bias = (1/n)Σ(ŷ_i − y_i)", "10-7")

    h2(doc, "10.2 2025 留出测试")
    table(doc,
          ["组织", "冠军", "W", "hidden", "MASE", "MAPE", "RMSE", "R²", "Bias"],
          [["机辆", "SW-LSTM", "12", "32", "1.0906", "9.75%", "9,473", "-0.9401", "+65"],
           ["肃宁", "Ridge", "6", "—", "0.4822", "10.56%", "265", "0.9207", "-54"],
           ["原平", "GBM", "6", "—", "0.6393", "8.15%", "298", "0.9714", "+83"]],
          widths=[2.0, 2.8, 1.2, 1.4, 1.8, 1.8, 1.8, 1.8, 1.5], font_size=8.6, cap="表 10-1 2025 测试集冠军指标")

    h2(doc, "10.3 基线对比")
    table(doc,
          ["模型", "机辆 MASE", "肃宁 MASE", "原平 MASE"],
          [["SW-LSTM", "1.0906", "0.6943", "0.9635"],
           ["Ridge", "1.1533", "0.4822", "0.9959"],
           ["GBM", "1.3419", "0.3814", "0.6393"],
           ["Holt-Winters", "11.0653", "4.5767", "7.3979"],
           ["Seasonal Naive", "1.4028", "0.5456", "0.8557"]],
          widths=[5.0, 3.6, 3.6, 3.6], font_size=9.0, cap="表 10-2 2025 测试集基线 MASE")
    para(doc, "肃宁 GBM 单年 MASE 更低，但多折平均与跨折方差不如 Ridge；按多折平均 MASE 选 Ridge。机辆 MASE 仅略优于季节 naive，说明 12 个月直接多步在结构断点年仍有难度。")

    h2(doc, "10.4 2026 年预测")
    table(doc,
          ["组织", "2025 可比", "2026 可比", "同比", "2025 报表", "2026 报表", "同比"],
          [["机辆", "941,131", "913,940", "-2.89%", "941,131", "913,940", "-2.89%"],
           ["肃宁", "25,934", "25,404", "-2.04%", "22,913", "22,383", "-2.31%"],
           ["原平", "28,652", "29,964", "+4.58%", "16,699", "18,012", "+7.86%"]],
          widths=[2.0, 2.6, 2.6, 2.0, 2.6, 2.6, 2.0], font_size=8.6, cap="表 10-3 2026 年 BAU 预测（tCO2e）")

    h2(doc, "10.5 异常与稳定性")
    para(doc, "异常检测 V2 固化复核级 8 条、关注级 143 条、热力规则事件 3 条；柴油 2024-10 断点三判据通过。2025 测试中，机辆 Bias≈+65，几乎无系统性偏移；肃宁/原平 R²>0.92，热力/供暖规律可被模型捕捉。")

    h2(doc, "10.6 讨论")
    para(doc, "机辆 R² 为负，主要因为 2025 年水平与波动结构变化，R² 对水平偏移敏感；MASE/MAPE 更贴近实际可用性。区间覆盖率为 75%/92%/83%，90% 名义区间偏窄，应作为不确定性提示。GRA 的外部因子整体偏弱，模型以历史自回归为主，不能把预测解释为政策减排效果。")


def ch11(doc):
    h1(doc, "11 参数汇总")
    table(doc,
          ["类别", "参数", "取值"],
          [["数据", "时间范围", "2019-01—2025-12"],
           ["数据", "组织", "JLG/SNF/YPF"],
           ["口径", "基准电力因子", "0.5306"],
           ["口径", "基准供热系数", "0.9224 GJ/m²"],
           ["异常", "森林树数/污染率", "200 / 0.05"],
           ["异常", "MAD z 阈值", "3 / 5"],
           ["异常", "断点 stat/shift/CV", "3.0 / 25% / 1.5"],
           ["GRA", "rho/阈值", "0.5 / 0.70"],
           ["窗口", "W 网格", "6, 9, 12"],
           ["LSTM", "hidden/epochs/patience", "32,64 / 220 / 25"],
           ["LSTM", "lr/batch/dropout", "1e-3 / 16 / 0.2"],
           ["预测", "H", "12"],
           ["预测", "区间", "90% 名义"]],
          widths=[2.5, 7.0, 6.0], font_size=9.0, cap="表 11-1 参数汇总")


def ch12(doc):
    h1(doc, "12 实现与可复现性")
    h2(doc, "12.1 代码结构")
    table(doc,
          ["文件", "职责"],
          [["data.py", "原始读取、口径还原、缺失推算、排放计算"],
           ["anomaly_v2.py", "STL/MAD、双通道森林、断点、日历、联合、关注分流"],
           ["gra.py", "GRA 无量纲化、关联系数、rho、去趋势、共线"],
           ["features.py", "目标/候选因子面板"],
           ["dataset.py", "滑窗、划分、Scaler"],
           ["models.py", "SW-LSTM、Ridge、GBM、HW、SN"],
           ["pipeline.py", "导入/训练/预测/接入/复核编排"],
           ["metrics.py", "评估指标"],
           ["repository.py / api.py", "存储与接口"]],
          widths=[5.0, 10.5], font_size=8.8, cap="表 12-1 代码结构")

    h2(doc, "12.2 可复现性")
    para(doc, "全局种子 20260928；模型工件保存权重、scaler、特征顺序、W/H、超参、训练区间、数据版本；数据版本记录内容指纹；测试集只评估一次；所有异常处置与复核写审计表。")
    code(doc, """
artifacts/models/{model_id}/
  model.pt / model.joblib
  scaler.json
prediction_model.metrics:
  test_2025 / validation_2024 / baselines / backtest / selected_final
""")

    h2(doc, "12.3 测试")
    para(doc, "单元测试覆盖 GRA 恒等、指标完美预测、窗口形状、scaler 边界、数据行数/口径、合成台阶断点、极端新点检测，共 7 项通过。")


def ch13(doc):
    h1(doc, "13 适用条件与限制")
    bullet(doc, "月度序列不少于 24 个月；少于 24 个月不启用统计异常检测。")
    bullet(doc, "供热、检修等确定性事件需有规则或业务登记；未登记事件可能被当作统计异常。")
    bullet(doc, "2026 预测假设电力因子维持 0.5306、供热系数维持 2025 年值、内燃机车 15 台；假设变化需重跑。")
    bullet(doc, "GRA 只表示趋势相似度，不是因果、贡献率或弹性；政策因子弱时模型以自回归为主。")
    bullet(doc, "区间覆盖率为 75%/92%/83%，90% 名义区间偏窄；应结合业务不确定性使用。")
    bullet(doc, "机辆 MASE=1.09，仅略优于季节 naive；不能宣称显著提升。")


def appendix(doc):
    h1(doc, "附录 A 数据字典（核心表）")
    table(doc,
          ["表", "关键字段", "说明"],
          [["prediction_activity_monthly", "org_id, period, var_id, value, reported_value, quality_status", "月度活动数据"],
           ["prediction_emission_monthly", "org_id, period, total_reported_tco2, total_comparable_tco2", "双口径排放"],
           ["prediction_anomaly", "org_id, period, var_id, level, category, channels, breakpoint_stat, final_disposition", "复核级异常"],
           ["prediction_anomaly_watch", "org_id, period, var_id, level, category, score", "关注级监控"],
           ["prediction_gra_result", "org_id, var_id, r, r_detrend, selected", "GRA 结果"],
           ["prediction_model", "model_id, org_id, model_type, W, feature_order, metrics", "模型注册"],
           ["prediction_forecast", "model_id, org_id, period, point, reported_point", "预测结果"]],
          widths=[5.2, 7.8, 3.0], font_size=8.6, cap="表 A-1 核心表")

    h1(doc, "附录 B 冠军模型配置")
    code(doc, """
JLG: SW_LSTM, W=12, hidden=32, H=12
SNF: RIDGE,   W=6,  alpha=10, H=12
YPF: GBM,     W=6,  n_estimators=250, lr=0.05, depth=3, H=12

target: y_t = CO2_COMPARABLE - DIESEL_TCO2
features: selected GRA vars + month_sin + month_cos
scaler: StandardScaler(X), MinMaxScaler(y)
seed: 20260928
""")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    doc = Document()
    setup_page(doc)
    setup_styles(doc)
    doc.core_properties.title = "铁路碳排放趋势预测算法设计"
    doc.core_properties.subject = "铁路碳排放趋势预测模块算法设计"
    doc.core_properties.author = "算法设计组"
    doc.core_properties.comments = "基于已实现的碳排放预测系统"

    add_cover(doc)
    add_revision(doc)
    add_abstract(doc)
    add_toc(doc)

    # Body section with page numbering starting at 1
    body = doc.add_section(WD_SECTION.NEW_PAGE)
    body.header.is_linked_to_previous = False
    body.footer.is_linked_to_previous = False
    add_header(body)
    add_page_number(body.footer)
    pgNumType = OxmlElement("w:pgNumType")
    pgNumType.set(qn("w:start"), "1")
    body._sectPr.append(pgNumType)

    # settings update fields
    settings = doc.settings.element
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    settings.append(update)

    ch1(doc)
    ch2(doc)
    ch3(doc)
    ch4(doc)
    ch5(doc)
    ch6(doc)
    ch7(doc)
    ch8(doc)
    ch9(doc)
    ch10(doc)
    ch11(doc)
    ch12(doc)
    ch13(doc)
    appendix(doc)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print("saved", OUT)


if __name__ == "__main__":
    main()
