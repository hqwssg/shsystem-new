"""Regenerate the standalone prototype wrapper from its editable fragment."""

from __future__ import annotations

import html
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRAGMENT = ROOT / "prototypes" / "heavy-empty-coordination-ui.fragment.html"
OUTPUT = ROOT / "prototypes" / "heavy-empty-coordination-ui.html"


def main() -> int:
    """函数 main：执行该模块中的相关处理逻辑。"""
    fragment = FRAGMENT.read_text(encoding="utf-8")
    srcdoc = "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>重空协同优化系统</title></head><body>" + fragment + "</body></html>"
    escaped = html.escape(srcdoc, quote=True)
    prefix = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob: data:; style-src 'unsafe-inline' blob: data:; img-src blob: data:; font-src blob: data:; media-src blob: data:; worker-src blob:; connect-src blob: data:; frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>重空协同优化系统</title>
<style>:root{color-scheme:light dark;background:light-dark(rgb(255 255 255),rgb(24 24 24))}html,body{margin:0}body{box-sizing:border-box;padding:1rem;background:inherit}iframe{display:block;width:100%;height:calc(100vh - 2rem);margin:0 auto;border:0}</style>
</head>
<body>
<iframe sandbox="allow-scripts" referrerpolicy="no-referrer" title="重空协同优化系统" srcdoc='"""
    suffix = """'></iframe>
</body>
</html>
"""
    wrapper = prefix + escaped + suffix
    OUTPUT.write_text(wrapper, encoding="utf-8")
    print(f"synced {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
