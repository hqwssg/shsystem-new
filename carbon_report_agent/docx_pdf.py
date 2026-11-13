from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_FANGSONG_MARKERS = ("仿宋", "FangSong")

_FONT_PAIR_NAMES = (
    ("fangsong_gb2312", "仿宋_GB2312", "仿宋"),
    ("fangsong", "仿宋", "仿宋"),
    ("fangsong_en_gb2312", "FangSong_GB2312", "FangSong"),
    ("fangsong_en", "FangSong", "FangSong"),
)


class PdfConversionUnavailableError(RuntimeError):
    """Raised when no LibreOffice/soffice executable can be found."""


class PdfConversionError(RuntimeError):
    """Raised when LibreOffice is found but the conversion fails."""


def find_soffice_executable() -> str:
    configured = os.environ.get("CARBON_REPORT_SOFFICE_PATH", "").strip()
    if configured:
        configured_path = Path(configured)
        if configured_path.is_file():
            return str(configured_path)
        configured_command = shutil.which(configured)
        if configured_command:
            return configured_command
        raise PdfConversionUnavailableError(
            "Configured CARBON_REPORT_SOFFICE_PATH does not point to a usable executable: "
            f"{configured}. Install LibreOffice or set CARBON_REPORT_SOFFICE_PATH to soffice/libreoffice."
        )

    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if executable:
        return executable

    raise PdfConversionUnavailableError(
        "LibreOffice/soffice not found. Install LibreOffice or set CARBON_REPORT_SOFFICE_PATH "
        "to the soffice/libreoffice executable."
    )


def _user_installation_uri(profile_dir: Path) -> str:
    return "file:///" + profile_dir.resolve().as_posix().lstrip("/")


def _font_pair_item(node_name: str, replace_font: str, substitute_font: str) -> str:
    return (
        f'<item oor:path="/org.openoffice.Office.Common/Font/Substitution/FontPairs">'
        f'<node oor:name="{node_name}" oor:op="fuse">'
        f'<prop oor:name="ReplaceFont" oor:op="fuse"><value>{replace_font}</value></prop>'
        f'<prop oor:name="SubstituteFont" oor:op="fuse"><value>{substitute_font}</value></prop>'
        f'<prop oor:name="Always" oor:op="fuse"><value>true</value></prop>'
        f'<prop oor:name="OnScreenOnly" oor:op="fuse"><value>false</value></prop>'
        f"</node></item>"
    )


def lo_font_substitution_xcu() -> str:
    """LibreOffice profile XML: map FangSong/仿宋 families onto regular 仿宋."""
    pairs = "".join(
        _font_pair_item(name, replace, substitute)
        for name, replace, substitute in _FONT_PAIR_NAMES
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<item oor:path="/org.openoffice.Office.Common/Font/Substitution">'
        '<prop oor:name="Replacement" oor:op="fuse"><value>true</value></prop>'
        "</item>"
        f"{pairs}"
        "</oor:items>\n"
    )


def write_lo_font_substitution_profile(profile_dir: Path) -> Path:
    user_dir = Path(profile_dir) / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    xcu_path = user_dir / "registrymodifications.xcu"
    xcu_path.write_text(lo_font_substitution_xcu(), encoding="utf-8")
    return xcu_path


_SIMSUN = "宋体"
_TOC_BOLD_STYLE_NAMES = {"toc 1", "toc1"}


def _rfonts_is_fangsong(fonts) -> bool:
    if fonts is None:
        return False
    values = " ".join(
        str(fonts.get(f"{_W_NS}{attr}") or "")
        for attr in ("eastAsia", "ascii", "hAnsi", "cs")
    )
    return any(marker in values for marker in _FANGSONG_MARKERS)


def _rpr_has_bold(rpr) -> bool:
    return rpr.find(f"{_W_NS}b") is not None or rpr.find(f"{_W_NS}bCs") is not None


def _keep_fangsong_bold_as_simsun(rpr) -> bool:
    """TOC L1 / 目录 title should stay bold; cover 仿宋 fake-bold must not."""
    node = rpr
    while node is not None:
        if node.tag == f"{_W_NS}style":
            name_el = node.find(f"{_W_NS}name")
            name = (name_el.get(f"{_W_NS}val") or "").strip().lower() if name_el is not None else ""
            if name in _TOC_BOLD_STYLE_NAMES:
                return True
        if node.tag == f"{_W_NS}p":
            p_pr = node.find(f"{_W_NS}pPr")
            p_style = p_pr.find(f"{_W_NS}pStyle") if p_pr is not None else None
            style_val = (
                (p_style.get(f"{_W_NS}val") or "").strip().lower()
                if p_style is not None
                else ""
            )
            if style_val in _TOC_BOLD_STYLE_NAMES:
                return True
            compact = "".join(node.itertext()).replace(" ", "").replace("\u3000", "")
            if compact.startswith("目录"):
                return True
        node = node.getparent()
    return False


def _set_east_asia_font(rpr, font_name: str) -> None:
    fonts = rpr.find(f"{_W_NS}rFonts")
    if fonts is None:
        fonts = etree.SubElement(rpr, f"{_W_NS}rFonts")
        rpr.insert(0, fonts)
    fonts.set(f"{_W_NS}eastAsia", font_name)


def _strip_bold(rpr) -> None:
    for tag in ("b", "bCs"):
        element = rpr.find(f"{_W_NS}{tag}")
        if element is not None:
            rpr.remove(element)


def _adjust_fangsong_bold_xml(xml_bytes: bytes) -> bytes:
    root = etree.fromstring(xml_bytes)
    for rpr in root.iter(f"{_W_NS}rPr"):
        if not _rfonts_is_fangsong(rpr.find(f"{_W_NS}rFonts")):
            continue
        if _keep_fangsong_bold_as_simsun(rpr):
            _set_east_asia_font(rpr, _SIMSUN)
            continue
        if _rpr_has_bold(rpr):
            _strip_bold(rpr)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def prepare_docx_for_pdf(src: Path, dest: Path) -> Path:
    """Copy DOCX for LibreOffice: keep cover as regular 仿宋, TOC L1 as 宋体加粗."""
    src = Path(src)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.startswith("word/") and info.filename.endswith(".xml"):
                try:
                    data = _adjust_fangsong_bold_xml(data)
                except etree.XMLSyntaxError:
                    pass
            zout.writestr(info, data)
    return dest


def convert_docx_to_pdf(
    docx_path: Path | str,
    pdf_path: Path | str,
    *,
    timeout_seconds: float = 120.0,
    job_id: str | None = None,
) -> Path:
    docx_path = Path(docx_path)
    pdf_path = Path(pdf_path)
    if not docx_path.exists():
        raise FileNotFoundError(f"DOCX input does not exist: {docx_path}")

    soffice = find_soffice_executable()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"carbon-report-pdf-{job_id or 'job'}-"

    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        tmp_dir = Path(tmp)
        outdir = tmp_dir / "out"
        profile_dir = tmp_dir / "lo-profile"
        outdir.mkdir()
        profile_dir.mkdir()
        write_lo_font_substitution_profile(profile_dir)
        work_docx = tmp_dir / docx_path.name
        prepare_docx_for_pdf(docx_path, work_docx)
        command = [
            soffice,
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--nodefault",
            "--norestore",
            f"-env:UserInstallation={_user_installation_uri(profile_dir)}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(outdir),
            str(work_docx),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PdfConversionError(
                f"LibreOffice PDF conversion timed out after {timeout_seconds:g} seconds."
            ) from exc

        if result.returncode != 0:
            details = "\n".join(part for part in [result.stderr.strip(), result.stdout.strip()] if part)
            raise PdfConversionError(
                "LibreOffice PDF conversion failed"
                + (f": {details}" if details else ".")
            )

        converted = outdir / f"{work_docx.stem}.pdf"
        if not converted.exists():
            available = ", ".join(path.name for path in outdir.glob("*")) or "none"
            raise PdfConversionError(
                "LibreOffice PDF conversion did not produce the expected PDF "
                f"({converted.name}); output files: {available}."
            )

        if pdf_path.exists():
            pdf_path.unlink()
        shutil.move(str(converted), str(pdf_path))

    return pdf_path


__all__ = [
    "PdfConversionError",
    "PdfConversionUnavailableError",
    "convert_docx_to_pdf",
    "find_soffice_executable",
    "lo_font_substitution_xcu",
    "prepare_docx_for_pdf",
    "write_lo_font_substitution_profile",
]
