"""Apply scientific typography to visible Word text without rebuilding paragraphs."""
from copy import deepcopy
import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


_CHEMICAL = re.compile(r"(?<![A-Za-z_])(?:kg|t)?CO(?P<script>[2₂])e?(?![A-Za-z0-9_])")
_UNIT = re.compile(r"(?<![A-Za-z_])(?:万)?N?m(?P<script>[23²³])(?![A-Za-z0-9_])")
_POWERS = (
    re.compile(r"10\^(?:\{(?P<braced>[+−-]?\d+)\}|(?P<plain>[+−-]?\d+))"),
    re.compile(r"×\s*10(?P<plain>[−-]\d+)"),
    re.compile(r"/\s*10(?P<plain>4)(?=\s*t\s*[·⋅]\s*km\b)"),
)
_DIGITS = str.maketrans({"₂": "2", "²": "2", "³": "3", "−": "−", "-": "−"})


def display_unit(unit: str) -> str:
    """Translate known storage units only at the display boundary."""
    if unit == "10k_m3":
        return "万m3"
    if re.fullmatch(r"104\s*t\s*[·⋅]\s*km", unit):
        return re.sub(r"^104", "10^4", unit)
    return unit


def _script_marks(text):
    marks = {}
    for pattern, alignment in ((_CHEMICAL, "subscript"), (_UNIT, "superscript")):
        for match in pattern.finditer(text):
            start, end = match.span("script")
            for index in range(start, end):
                marks[index] = (alignment, text[index].translate(_DIGITS))
    for pattern in _POWERS:
        for match in pattern.finditer(text):
            group = "braced" if match.groupdict().get("braced") else "plain"
            start, end = match.span(group)
            # Carets/braces are notation controls, never visible exponent characters.
            for index in range(match.start() + match.group().index("10") + 2, match.end()):
                marks[index] = ("superscript", text[index].translate(_DIGITS) if start <= index < end else "")
    return marks


def _format_paragraph(element):
    runs, chunks = [], []
    offset = 0
    for run in element.iter(qn("w:r")):
        if next((a for a in run.iterancestors() if a.tag == qn("w:p")), None) is not element:
            continue
        # Math, drawings, breaks and field instructions retain their original XML.
        safe = (not any(a.tag in (qn("m:oMath"), qn("m:oMathPara")) for a in run.iterancestors())
                and all(c.tag in (qn("w:rPr"), qn("w:t")) for c in run)
                and run.find(qn("w:t")) is not None)
        text = "".join(c.text or "" for c in run.findall(qn("w:t"))) if safe else "\0"
        if safe:
            runs.append((run, offset, text))
        chunks.append(text)
        offset += len(text)
    marks = _script_marks("".join(chunks))
    for run, start, text in runs:
        if not any(start + i in marks for i in range(len(text))):
            continue
        segments = []
        for i, char in enumerate(text):
            alignment, value = marks.get(start + i, (None, char))
            if segments and segments[-1][0] == alignment:
                segments[-1][1] += value
            else:
                segments.append([alignment, value])
        for alignment, value in segments:
            if not value:
                continue
            replacement = deepcopy(run)
            for child in list(replacement):
                if child.tag != qn("w:rPr"):
                    replacement.remove(child)
            if alignment:
                props = replacement.get_or_add_rPr()
                for old in list(props.findall(qn("w:vertAlign"))):
                    props.remove(old)
                vert = OxmlElement("w:vertAlign")
                vert.set(qn("w:val"), alignment)
                props.append(vert)
            node = OxmlElement("w:t")
            node.set(qn("xml:space"), "preserve")
            node.text = value
            replacement.append(node)
            run.addprevious(replacement)
        run.getparent().remove(run)


def format_scientific_document(document):
    """Cover tables, hyperlinks, cached TOC text, headers and footers in place."""
    roots = [document.element]
    roots.extend(part.element for part in document.part.related_parts.values()
                 if part.content_type in (
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"))
    for root in roots:
        for paragraph in root.iter(qn("w:p")):
            _format_paragraph(paragraph)
