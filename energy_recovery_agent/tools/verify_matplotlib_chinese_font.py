"""Verify the exact Matplotlib font used by the deployed energy engine."""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from matplotlib_chinese_font import (  # noqa: E402
    CJK_GLYPH_SAMPLE,
    configure_matplotlib_chinese_font,
    font_supports_text,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    selected = configure_matplotlib_chinese_font()
    if selected is None:
        print(json.dumps({"ok": False, "reason": "no verified CJK font"}, ensure_ascii=False))
        return 2
    family, path = selected
    result = {
        "ok": font_supports_text(path),
        "family": family,
        "path": path,
        "sample": CJK_GLYPH_SAMPLE,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        fig, axis = plt.subplots(figsize=(9, 2.4))
        axis.text(0.5, 0.5, "重空协同：滚动状态时间线，储能 SOC（kWh）", ha="center", va="center", fontsize=16)
        axis.set_axis_off()
        fig.tight_layout()
        fig.savefig(args.output, dpi=150)
        plt.close(fig)
        result["output"] = str(args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
