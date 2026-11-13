"""Redraw the system architecture diagram for the prediction module."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parents[1] / "artifacts" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

NAVY = "#1F3A5F"
INK = "#2C3E50"
MUTED = "#5D6D7E"
BLUE = "#EAF2F8"
PURPLE = "#F4ECF7"
GREEN = "#E8F8F5"
AMBER = "#FEF9E7"
PLATFORM = "#F4F7FB"


def box(ax, x, y, w, h, text, fc=BLUE, ec=INK, fs=10, lw=1.0,
        dashed=False, bold=False):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                       linewidth=lw, edgecolor=ec, facecolor=fc,
                       linestyle="--" if dashed else "-")
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, color=INK, fontweight="bold" if bold else "normal",
            linespacing=1.35)


def arrow(ax, x1, y1, x2, y2, ls="-", color=INK, lw=1.1):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                 mutation_scale=11, linewidth=lw,
                                 color=color, linestyle=ls,
                                 shrinkA=0, shrinkB=0, zorder=3))


def line(ax, x1, y1, x2, y2, ls="-", color=INK, lw=1.1):
    ax.plot([x1, x2], [y1, y2], color=color, lw=lw, linestyle=ls,
            solid_capstyle="round", zorder=2)


def main():
    fig, ax = plt.subplots(figsize=(12.6, 9.6))
    ax.set_xlim(-0.15, 12.6)
    ax.set_ylim(0.8, 9.7)
    ax.axis("off")

    # ---------------- platform ----------------
    box(ax, 0.3, 7.75, 11.8, 1.55, "", PLATFORM, MUTED, dashed=True, lw=1.0)
    ax.text(6.2, 9.05, "大平台 / 业务系统", ha="center", va="center",
            fontsize=15, color=NAVY, fontweight="bold")
    items = [
        (0.65, "数据采集", 1.9),
        (2.70, "排放核算", 1.9),
        (4.75, "可视化", 1.9),
        (6.80, "报表", 1.9),
        (8.85, "权限 / 组织（sys_dept）", 2.95),
    ]
    for x, text, w in items:
        box(ax, x, 7.92, w, 0.48, text, "#FFFFFF", "#AAB7B8", fs=10.2)

    # ---------------- REST ----------------
    arrow(ax, 3.1, 7.74, 3.1, 6.86, lw=1.3)
    ax.text(3.22, 7.29, "REST / JSON", ha="left", va="center",
            fontsize=9.5, color=MUTED)

    # ---------------- module ----------------
    box(ax, 0.4, 3.88, 10.6, 2.98, "", "#FFFFFF", NAVY, lw=1.3)
    ax.text(5.70, 6.57, "FastAPI 预测模块（本系统）", ha="center", va="center",
            fontsize=15, color=NAVY, fontweight="bold")
    ax.text(5.70, 6.22,
            "鉴权 X-API-Key ｜ 统一响应 ｜ 幂等 ｜ 异步任务 ｜ OpenAPI /docs",
            ha="center", va="center", fontsize=10.0, color=MUTED)

    services = [
        (0.70, "接入服务\ningest"),
        (3.20, "异常服务\nanomaly"),
        (5.70, "训练服务\ntrain"),
        (8.20, "预测服务\nforecast"),
    ]
    for x, text in services:
        box(ax, x, 5.30, 2.20, 0.58, text, BLUE, NAVY, fs=10.5)
        arrow(ax, x + 1.10, 5.28, x + 1.10, 5.08)

    box(ax, 0.65, 4.10, 10.30, 0.96, "", PURPLE, NAVY, lw=1.0)
    ax.text(5.80, 4.81, "编排层 pipeline.py", ha="center", va="center",
            fontsize=11.0, color=NAVY, fontweight="bold")
    ax.text(5.80, 4.39,
            "口径还原 ｜ 缺失推算 ｜ GRA ｜ 滑窗 ｜ 模型选择 ｜ 柴油模块 ｜ 折算",
            ha="center", va="center", fontsize=9.6, color=INK)

    # ---------------- storage ----------------
    arrow(ax, 2.95, 4.08, 2.95, 2.78, lw=1.2)
    arrow(ax, 8.55, 4.08, 8.55, 2.78, lw=1.2)
    ax.text(3.08, 3.52, "读写", ha="left", va="center", fontsize=9.0, color=MUTED)
    ax.text(8.68, 3.52, "保存 / 加载", ha="left", va="center", fontsize=9.0, color=MUTED)

    box(ax, 0.40, 1.42, 5.00, 1.32, "", GREEN, NAVY, lw=1.2)
    ax.text(2.90, 2.40, "MySQL  carbon_emissions", ha="center", va="center",
            fontsize=11.0, color=NAVY, fontweight="bold")
    ax.text(2.90, 1.93, "prediction_*：21 张表 + 1 视图", ha="center", va="center",
            fontsize=9.6, color=INK)
    ax.text(2.90, 1.63, "活动 / 排放 / 异常 / 模型 / 预测 / 外部因子", ha="center", va="center",
            fontsize=8.8, color=MUTED)

    box(ax, 6.20, 1.42, 4.80, 1.32, "", AMBER, NAVY, lw=1.2)
    ax.text(8.60, 2.40, "模型工件  artifacts/", ha="center", va="center",
            fontsize=11.0, color=NAVY, fontweight="bold")
    ax.text(8.60, 1.93, ".pt / .joblib / scaler.json", ha="center", va="center",
            fontsize=9.6, color=INK)
    ax.text(8.60, 1.63, "metrics.json / feature_order", ha="center", va="center",
            fontsize=8.8, color=MUTED)

    # ---------------- platform -> same DB ----------------
    line(ax, 0.30, 8.48, 0.18, 8.48, ls=(0, (4, 3)), color=MUTED, lw=1.0)
    line(ax, 0.18, 8.48, 0.18, 2.85, ls=(0, (4, 3)), color=MUTED, lw=1.0)
    arrow(ax, 0.18, 2.85, 0.38, 2.85, ls=(0, (4, 3)), color=MUTED, lw=1.0)
    ax.text(0.45, 3.02, "同库读取", ha="left", va="center",
            fontsize=8.8, color=MUTED)

    ax.text(6.3, 9.60, "铁路碳排放趋势预测模块——系统架构",
            ha="center", va="center", fontsize=13.5, color=NAVY, fontweight="bold")

    fig.tight_layout()
    fig.savefig(OUT / "fig_00_system_architecture.png", dpi=240,
                facecolor="white", bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    print("saved", OUT / "fig_00_system_architecture.png")


if __name__ == "__main__":
    main()
