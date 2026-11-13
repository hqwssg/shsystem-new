"""Smoke checks for the editable and standalone prototype assets."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> None:
    """函数 main：执行该模块中的相关处理逻辑。"""
    root = Path(__file__).resolve().parents[2]
    fragment = root / "prototypes" / "heavy-empty-coordination-ui.fragment.html"
    standalone = root / "prototypes" / "heavy-empty-coordination-ui.html"
    fragment_text = fragment.read_text(encoding="utf-8")
    standalone_text = standalone.read_text(encoding="utf-8")
    if '<div id="hec-v2">' not in fragment_text:
        raise AssertionError("editable prototype root is missing")
    if 'data-page="performance"' not in fragment_text or 'data-page-panel="performance"' not in fragment_text:
        raise AssertionError("performance page is not wired in the prototype")
    if 'id="hec2-run-progress"' not in fragment_text or 'id="hec2-progress-bar"' not in fragment_text:
        raise AssertionError("run progress indicator is missing")
    if "尚未连接正式优化算法" not in fragment_text:
        raise AssertionError("prototype must disclose that results are simulated")
    if "不能直接提交" not in fragment_text or "正式 CLI 当前可直接映射" not in fragment_text:
        raise AssertionError("prototype must disclose backend input mapping boundaries")
    for ui_id in ("hec2-decision-title", "hec2-confidence-label", "hec2-explanation-file", "hec2-data-checks"):
        assert f'id="{ui_id}"' in fragment_text
    assert "textContent = text" in fragment_text
    assert "$('#hec2-demo-values').hidden = imported" in fragment_text
    assert "production_dispatch_allowed !== false" in fragment_text
    if not re.search(r"srcdoc=(?:\"|')", standalone_text) or "hec2-run-progress" not in html.unescape(standalone_text):
        raise AssertionError("standalone wrapper is out of sync with fragment")
    if not re.search(r"<iframe[^>]+sandbox=\"allow-scripts\"", standalone_text):
        raise AssertionError("standalone prototype must keep script sandbox")
    print("prototype assets verification: PASS")


if __name__ == "__main__":
    main()
