"""从验证 CSV/JSON 生成可复现的 Markdown + SVG 统计报告。"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from regenerative_braking.io.output_presentation import glossary_lines, profile_label


def _rows(path: Path) -> list[dict[str, str]]:
    with (path / "summary.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("baseline") == "rhonn_nsmc"]


def _columns(path: Path) -> list[str]:
    """取指标表的真实表头，供报告逐列给出中文释义。"""
    with (path / "summary.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle))


def _spec(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError(f"--run 必须使用 label=directory：{value}")
    label, raw = value.split("=", 1)
    return label, Path(raw)


def _bar_chart(path: Path, title: str, labels: Sequence[str], values: Sequence[float], unit: str, *, logarithmic: bool = False) -> None:
    width, height = 920, 430
    left, right, top, bottom = 90, 30, 60, 90
    plot_w, plot_h = width - left - right, height - top - bottom
    transformed = [math.log10(max(value, 1e-12)) for value in values] if logarithmic else list(values)
    if logarithmic:
        lo = min(transformed, default=0.0) - 0.5
        hi = max(transformed, default=0.0) + 0.5
    else:
        lo = min(0.0, min(transformed, default=0.0))
        hi = max(transformed, default=1.0) * 1.15 or 1.0
    scale = plot_h / (hi - lo)
    bars = []
    slot = plot_w / max(len(labels), 1)
    bar_w = slot * 0.62
    for index, (label, raw, value) in enumerate(zip(labels, transformed, values)):
        x = left + index * slot + (slot - bar_w) / 2
        anchor = lo if logarithmic else max(lo, 0.0)
        y = top + (hi - max(raw, anchor)) * scale
        base = top + (hi - anchor) * scale
        height_bar = max(1.0, base - y)
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{height_bar:.1f}" fill="#4f8cc9" data-tooltip="{label}: {value:.6g} {unit}" />'
            f'<text x="{x + bar_w / 2:.1f}" y="{height - bottom + 26}" text-anchor="middle">{label}</text>'
            f'<text x="{x + bar_w / 2:.1f}" y="{max(top + 14, y - 6):.1f}" text-anchor="middle">{value:.4g}</text>'
        )
    scale_note = "；纵轴采用以10为底的对数标尺" if logarithmic else ""
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" class="validation-chart" role="img" aria-label="{title}" viewBox="0 0 {width} {height}" font-family="Microsoft YaHei, SimHei, sans-serif">
<title>{title}</title><desc>控制器配置比较结果，单位：{unit}{scale_note}</desc>
<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#8a8a8a" />
<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#8a8a8a" />
<text x="{width/2}" y="28" text-anchor="middle">{title}</text>
<text x="18" y="{height/2}" text-anchor="middle" transform="rotate(-90 18 {height/2})">{unit}</text>
{''.join(bars)}</svg>'''
    path.write_text(svg, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成验证统计 Markdown 和 SVG 报告")
    parser.add_argument("--run", action="append", required=True, help="label=summary/manifest 目录，可重复")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--robustness", type=Path, default=None, help="robustness_evaluation 输出目录")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    summaries = []
    for label, directory in (_spec(value) for value in args.run):
        rows = _rows(directory)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        summaries.append({
            "label": label,
            "dt": manifest["dt"],
            "energy": sum(float(row["captured_energy_kWh"]) for row in rows),
            "mean_capture": sum(float(row["capture_ratio"]) for row in rows) / len(rows),
            "max_closure": float(manifest["worst_closure_relative_residual"]),
            "closure_exceedances": len(manifest.get("closure_exceedances", [])),
        })
    _bar_chart(args.out / "profile-energy.svg", "主算法回收能量", [profile_label(item["label"]) for item in summaries], [item["energy"] for item in summaries], "千瓦时")
    _bar_chart(args.out / "profile-closure.svg", "最大闭合相对残差", [profile_label(item["label"]) for item in summaries], [item["max_closure"] for item in summaries], "相对残差", logarithmic=True)
    robustness_note = ""
    if args.robustness is not None:
        summary_path = args.robustness / "summary.json"
        if summary_path.is_file():
            robust = json.loads(summary_path.read_text(encoding="utf-8"))
            selected = robust.get("selected_candidate", "未提供")
            robustness_note = f"\n鲁棒性候选选择：`{selected}`；最差场景定义为物理越限、闭合失败、闭合残差、捕获率和控制抖振的分层排序。"
    report = [
        "# 仿真结果可视化报告",
        "",
        "所有结果均为 **仿真结果，不作为工程结论**。图表使用各结果目录的指标表和清单，每个数值均注明控制器配置与积分步长。",
        "",
        "## 控制器配置摘要",
        "",
        "| 控制器配置 | 积分步长（秒） | 回收能量（千瓦时） | 平均捕获比例 | 最大闭合残差 | 超差次数 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    report.extend(
        f"| {profile_label(item['label'])} | {item['dt']:.1e} | {item['energy']:.6f} | {item['mean_capture']:.7f} | {item['max_closure']:.4e} | {item['closure_exceedances']} |"
        for item in summaries
    )
    report.extend(["", "![主算法回收能量](profile-energy.svg)", "", "![最大闭合相对残差](profile-closure.svg)", robustness_note, ""])
    columns: list[str] = []
    for _, directory in (_spec(value) for value in args.run):
        for key in _columns(directory):
            if key not in columns:
                columns.append(key)
    report.extend(["## 指标字段释义", "",
                   "下表覆盖结果目录 `summary.csv` 的全部列；机读键名保持不变，中文仅用于阅读。", ""])
    report.extend(glossary_lines(columns))
    report.append("")
    (args.out / "report.md").write_text("\n".join(report), encoding="utf-8")
    (args.out / "report_manifest.json").write_text(json.dumps({"runs": summaries, "disclaimer": "仿真结果，不作为工程结论"}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告目录：", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
