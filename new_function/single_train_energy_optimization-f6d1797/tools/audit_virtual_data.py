"""参数字段溯源与虚拟值登记表生成器（只读）。

用途
----
    python tools/audit_virtual_data.py
    python tools/audit_virtual_data.py --out docs --name virtual_data_register_2026-11-05

把 `data/single_train/*.json` 的每个数值字段展开成一行，登记：
中文名、单位、当前取值、**溯源等级**、溯源依据。

判定「虚拟数据」的口径：`assumed` / `placeholder` / `synthetic` / `unknown`。
`real` / `official` / `derived` / `calibrated` 属于有真实来源或由真实数据推算，不算虚拟。

门禁
----
任何数值字段缺中文名、缺溯源等级或缺溯源说明，都直接判失败（退出码 1）。
理由：项目纪律要求「不得静默用默认值填充缺失字段」，字段没登记等级就等于静默。

边界
----
本脚本只读参数文件，不修改任何输入；输出只写到 `--out` 指定目录。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from regenerative_braking.io.parameter_glossary import (  # noqa: E402
    PARAMETER_FIELD_CN,
    display_text,
    flatten_parameters,
    lookup,
    unit_of,
)

#: 参数文件与展示顺序
PARAMETER_FILES: Tuple[Tuple[str, str], ...] = (
    ("train_parameters", "列车参数"),
    ("motor_parameters", "电机参数"),
    ("dc_dc_parameters", "变流器参数"),
    ("storage_parameters", "储能参数"),
)

#: 视为「虚拟数据」（无甲方实测/正式资料支撑）的等级
VIRTUAL_LEVELS = frozenset({"assumed", "placeholder", "synthetic", "unknown"})

LEVEL_ORDER = (
    "official",
    "real",
    "derived",
    "calibrated",
    "assumed",
    "placeholder",
    "synthetic",
    "unknown",
)


def format_value(value: Any) -> str:
    """数值的可读写法：整数不带小数，浮点去掉多余尾零。"""

    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        # repr 给出最短可往返表示，避免 0.948683 这类截断误导换数
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(format_value(item) for item in value) + "]"
    return str(value)


def collect_rows(root: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    """展开全部参数字段，返回 (行, 问题列表)。"""

    rows: List[Dict[str, str]] = []
    problems: List[str] = []
    for stem, label in PARAMETER_FILES:
        path = root / "data" / "single_train" / f"{stem}.json"
        if not path.exists():
            problems.append(f"{stem}.json 不存在：{path}")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        levels = payload.get("field_data_status") or {}
        provenance = payload.get("provenance") or {}
        for field_path, value in flatten_parameters(payload):
            name = PARAMETER_FIELD_CN.get(field_path, "")
            level = lookup(levels, field_path)
            basis = lookup(provenance, field_path)
            if not name:
                problems.append(f"{stem}.{field_path}：缺少中文名，请在 parameter_glossary.PARAMETER_FIELD_CN 登记")
            if not level:
                problems.append(f"{stem}.{field_path}：缺少溯源等级（field_data_status）")
            if not basis:
                problems.append(f"{stem}.{field_path}：缺少溯源说明（provenance）")
            rows.append(
                {
                    "file": stem,
                    "file_label": label,
                    "field": field_path,
                    "name_cn": name or "—",
                    "unit": unit_of(field_path) or "—",
                    "value": format_value(value),
                    "level": level or "未标注",
                    "basis": display_text(basis) if basis else "",
                    "virtual": "是" if level in VIRTUAL_LEVELS else "否",
                }
            )
        numeric_fields = {row["field"] for row in rows if row["file"] == stem}
        for key in levels:
            # 文本字段（如 locomotive_type）不进入数值展开，但仍然是真实存在的字段，不算失效键
            if key in payload and not isinstance(payload[key], dict):
                continue
            if key in numeric_fields or any(field.startswith(key + ".") for field in numeric_fields):
                continue
            problems.append(
                f"{stem}.field_data_status['{key}'] 没有匹配到任何数值字段（键名可能已改名）"
            )
    return rows, problems


def summarize(rows: Sequence[Dict[str, str]]) -> List[Tuple[str, Dict[str, int], int, int]]:
    """按文件统计各等级字段数与虚拟字段数。"""

    summary: List[Tuple[str, Dict[str, int], int, int]] = []
    for stem, label in PARAMETER_FILES:
        subset = [row for row in rows if row["file"] == stem]
        counts = {level: 0 for level in LEVEL_ORDER}
        for row in subset:
            counts[row["level"]] = counts.get(row["level"], 0) + 1
        virtual = sum(1 for row in subset if row["virtual"] == "是")
        summary.append((label, counts, len(subset), virtual))
    return summary


def write_csv(path: Path, rows: Sequence[Dict[str, str]]) -> None:
    columns = ("file_label", "field", "name_cn", "unit", "value", "level", "virtual", "basis")
    headers = ("参数文件", "字段", "中文名", "单位", "当前取值", "溯源等级", "是否虚拟", "溯源依据")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([row[column] for column in columns])


def write_markdown(
    path: Path, rows: Sequence[Dict[str, str]], problems: Sequence[str], command: str
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    generated = datetime.now().strftime("%Y-%m-%d")
    lines: List[str] = []
    lines.append(f"# 参数字段溯源与虚拟值登记表（{generated}）")
    lines.append("")
    lines.append("> 本文件由脚本生成，不要手工编辑。重新生成：")
    lines.append(">")
    lines.append(f"> ```bash\n> {command}\n> ```")
    lines.append("")
    lines.append(f"生成时间：{now}")
    lines.append("")
    lines.append("## 0 用途与换数流程")
    lines.append("")
    lines.append(
        "甲方资料未到位的字段，本项目一律用**取值合理、可追溯的虚拟值**填充，保证算法完整可跑；"
        "本表就是这些字段的清单，也是资料到位后逐条替换的工作单。"
    )
    lines.append("")
    lines.append("替换一个字段要同时改三处，缺一处会被 `tests/test_virtual_data_register.py` 拦下：")
    lines.append("")
    lines.append("1. `data/single_train/<文件>.json` 里的数值；")
    lines.append("2. 同文件 `field_data_status` 里的溯源等级（`official / real / derived / calibrated / assumed / placeholder`）；")
    lines.append("3. 同文件 `provenance` 里的依据出处（写清「谁给的、哪份文件、哪一页/哪张表」）。")
    lines.append("")
    lines.append("改完重新生成本表，并跑一次全量回归。")
    lines.append("")

    lines.append("## 1 汇总")
    lines.append("")
    lines.append("| 参数文件 | 字段数 | " + " | ".join(LEVEL_ORDER) + " | 虚拟字段 | 虚拟占比 |")
    lines.append("| --- | ---: | " + " | ".join("---:" for _ in LEVEL_ORDER) + " | ---: | ---: |")
    total_fields = 0
    total_virtual = 0
    for label, counts, count, virtual in summarize(rows):
        total_fields += count
        total_virtual += virtual
        ratio = f"{virtual / count * 100:.0f}%" if count else "—"
        lines.append(
            f"| {label} | {count} | "
            + " | ".join(str(counts.get(level, 0)) for level in LEVEL_ORDER)
            + f" | {virtual} | {ratio} |"
        )
    overall = f"{total_virtual / total_fields * 100:.0f}%" if total_fields else "—"
    totals = {level: sum(counts.get(level, 0) for _, counts, _, _ in summarize(rows)) for level in LEVEL_ORDER}
    lines.append(
        f"| **合计** | **{total_fields}** | "
        + " | ".join(f"**{totals[level]}**" for level in LEVEL_ORDER)
        + f" | **{total_virtual}** | **{overall}** |"
    )
    lines.append("")
    lines.append(
        "口径：`assumed` / `placeholder` / `synthetic` / `unknown` 记为虚拟数据；"
        "`real` / `official` / `derived` / `calibrated` 由真实资料或真实数据推算得到，不计入虚拟。"
    )
    lines.append("")

    lines.append("## 2 虚拟字段明细（甲方资料到位后逐条替换）")
    lines.append("")
    for stem, label in PARAMETER_FILES:
        subset = [row for row in rows if row["file"] == stem and row["virtual"] == "是"]
        if not subset:
            continue
        lines.append(f"### {label}（{len(subset)} 项）")
        lines.append("")
        lines.append("| 字段 | 中文名 | 取值 | 单位 | 等级 | 依据 |")
        lines.append("| --- | --- | ---: | --- | --- | --- |")
        for row in subset:
            basis = row["basis"].replace("|", "／")
            lines.append(
                f"| `{row['field']}` | {row['name_cn']} | {row['value']} | {row['unit']} | "
                f"{row['level']} | {basis} |"
            )
        lines.append("")

    lines.append("## 3 非虚拟字段（已有真实来源）")
    lines.append("")
    lines.append("| 参数文件 | 字段 | 中文名 | 取值 | 单位 | 等级 |")
    lines.append("| --- | --- | --- | ---: | --- | --- |")
    for row in rows:
        if row["virtual"] == "是":
            continue
        lines.append(
            f"| {row['file_label']} | `{row['field']}` | {row['name_cn']} | {row['value']} | "
            f"{row['unit']} | {row['level']} |"
        )
    lines.append("")

    if problems:
        lines.append("## 4 登记缺项")
        lines.append("")
        for item in problems:
            lines.append(f"- {item}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成参数字段溯源与虚拟值登记表（只读）")
    parser.add_argument("--root", default=str(ROOT), help="项目根目录")
    parser.add_argument("--out", default=str(ROOT / "data" / "experiments" / "virtual_data"), help="输出目录")
    parser.add_argument("--name", default="virtual_data_register", help="输出文件基名（不含扩展名）")
    parser.add_argument("--csv", action="store_true", help="同时写 CSV")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    rows, problems = collect_rows(root)

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = out_dir / f"{args.name}.md"
    try:
        out_display = out_dir.relative_to(root).as_posix()
    except ValueError:
        out_display = str(out_dir)
    command = (
        "python tools/audit_virtual_data.py "
        f"--out {out_display} "
        f"--name {args.name}"
    )
    write_markdown(markdown_path, rows, problems, command)
    if args.csv:
        write_csv(out_dir / f"{args.name}.csv", rows)

    total_virtual = sum(1 for row in rows if row["virtual"] == "是")
    print(f"字段总数 {len(rows)}，虚拟字段 {total_virtual}，登记缺项 {len(problems)}")
    for label, counts, count, virtual in summarize(rows):
        detail = "，".join(f"{level} {counts[level]}" for level in LEVEL_ORDER if counts.get(level))
        print(f"  {label}: {count} 项（虚拟 {virtual}）｜ {detail}")
    print(f"登记表：{markdown_path}")
    if problems:
        print("\n登记缺项：")
        for item in problems:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
