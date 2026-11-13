"""Select a Matplotlib font that is verified to contain the required CJK glyphs."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Tuple

import matplotlib
from matplotlib import font_manager, ft2font


CJK_GLYPH_SAMPLE = "重空协同滚动状态时间线储能晚点轮次秒"
PREFERRED_CJK_FONTS = (
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "Noto Sans CJK TC",
    "Noto Sans CJK HK",
    "Noto Sans SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "Arial Unicode MS",
)
_CJK_NAME_MARKERS = ("CJK", "YaHei", "SimHei", "Source Han", "WenQuanYi", "PingFang")


def font_supports_text(font_path: str | Path, text: str = CJK_GLYPH_SAMPLE) -> bool:
    """Return whether the concrete font file contains every non-space glyph."""

    try:
        charmap = ft2font.FT2Font(str(font_path)).get_charmap()
    except (OSError, RuntimeError, ValueError):
        return False
    return all(character.isspace() or ord(character) in charmap for character in text)


def _matching_entries(names: Iterable[str]):
    entries = list(font_manager.fontManager.ttflist)
    for name in names:
        for entry in entries:
            if entry.name == name:
                yield entry
    for entry in entries:
        if entry.name not in names and any(marker in entry.name for marker in _CJK_NAME_MARKERS):
            yield entry


def find_verified_chinese_font() -> Optional[Tuple[str, str]]:
    """Find a preferred family whose Matplotlib-resolved file supports Chinese."""

    for entry in _matching_entries(PREFERRED_CJK_FONTS):
        if not font_supports_text(entry.fname):
            continue
        try:
            resolved = font_manager.findfont(
                font_manager.FontProperties(family=[entry.name]),
                fallback_to_default=False,
            )
        except ValueError:
            continue
        if font_supports_text(resolved):
            return entry.name, str(Path(resolved).resolve())
    return None


def configure_matplotlib_chinese_font() -> Optional[Tuple[str, str]]:
    """Configure Matplotlib and return the verified family and resolved file."""

    selected = find_verified_chinese_font()
    matplotlib.rcParams["axes.unicode_minus"] = False
    if selected is None:
        return None
    family, _ = selected
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = [family, "DejaVu Sans"]
    return selected
