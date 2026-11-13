# -*- coding: utf-8 -*-
"""校验合并后的 docx 是否完整保留了四份 Markdown 的正文、表格与图题。

用法：python scripts/check_design_docx.py <docx>
"""

from __future__ import annotations

import os
import re
import sys

from docx import Document

DOCS = ["02_系统设计说明书.md", "03_数据库设计.md", "04_接口文档.md", "05_模型评测与预测报告.md"]
SKIP_CODE_LANG = True


def norm(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = s.replace("**", "").replace("`", "")
    s = s.replace("\u2714", "\u221a")
    return re.sub(r"\s+", "", s)


def doc_text(path: str) -> str:
    d = Document(path)
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            for c in row.cells:
                parts.append(c.text)
    return norm("\n".join(parts))


def clean_line(s: str) -> str:
    s = re.sub(r"^#{1,6}\s*", "", s)
    s = re.sub(r"^[-*+]\s+", "", s)
    s = re.sub(r"^\d+\.\s+", "", s)
    return s


def md_spans(path: str):
    spans = []
    in_code = False
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                if len(norm(s)) > 12:
                    spans.append(s)  # 代码块只抽查部分行
                continue
            if not s or s in ("---", "***"):
                continue
            if re.fullmatch(r"\|[\s\-:|]+\|", s):
                continue
            if s.startswith("|"):
                cells = [c.strip() for c in s.strip("|").split("|")]
                spans.extend([c for c in cells if c])
                continue
            if s.startswith("!["):
                continue
            spans.append(clean_line(s))
    return spans


def main() -> int:
    docx_path = sys.argv[1]
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs_dir = os.path.join(here, "docs")
    full = doc_text(docx_path)

    total = 0
    missing = []
    for name in DOCS:
        path = os.path.join(docs_dir, name)
        spans = md_spans(path)
        for raw in spans:
            key = norm(raw)
            if len(key) < 6:
                continue
            total += 1
            probe = key[:min(len(key), 40)]
            if probe not in full:
                missing.append((name, raw[:90]))

    print(f"checked spans: {total}")
    print(f"missing: {len(missing)}")
    for name, raw in missing[:30]:
        print(f"  [{name}] {raw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
