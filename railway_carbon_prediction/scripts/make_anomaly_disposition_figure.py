"""Redraw the anomaly disposition flow (historical vs new data)."""
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
GREEN = "#E8F8F5"
AMBER = "#FEF9E7"
RED = "#FADBD8"
PINK = "#F5B7B1"
PURPLE = "#F4ECF7"


def box(ax, x, y, w, h, text, fc=BLUE, ec=INK, fs=9.5, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0.02,rounding_size=0.07",
                                linewidth=1.0, edgecolor=ec, facecolor=fc))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, color=INK, fontweight="bold" if bold else "normal",
            linespacing=1.35)


def arrow(ax, x1, y1, x2, y2, color=INK, lw=1.1):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                 mutation_scale=11, linewidth=lw,
                                 color=color, shrinkA=0, shrinkB=0, zorder=3))


def line(ax, x1, y1, x2, y2, color=INK, lw=1.0):
    ax.plot([x1, x2], [y1, y2], color=color, lw=lw,
            solid_capstyle="round", zorder=2)


def main():
    fig, ax = plt.subplots(figsize=(12.2, 8.4))
    ax.set_xlim(0, 12.3); ax.set_ylim(0.3, 8.45); ax.axis("off")

    # ---------------- historical lane ----------------
    ax.text(0.3, 8.02, "历史数据链路", fontsize=9, color=MUTED)
    box(ax, 0.3, 7.18, 1.9, 0.68, "历史数据", BLUE, fs=10)
    box(ax, 2.5, 7.18, 3.0, 0.68, "V2 双通道 / 断点 / 日历", BLUE, fs=9.6)
    box(ax, 5.9, 7.18, 2.5, 0.68, "复核级 auto_closed", GREEN, fs=9.6)
    box(ax, 8.8, 7.18, 2.2, 0.68, "keep /\nmark_breakpoint", GREEN, fs=9.2)
    arrow(ax, 2.22, 7.52, 2.48, 7.52)
    arrow(ax, 5.52, 7.52, 5.88, 7.52)
    arrow(ax, 8.42, 7.52, 8.78, 7.52)

    box(ax, 5.9, 5.92, 2.9, 0.68, "关注级 prediction_anomaly_watch\n（不进复核队列）", GREEN, fs=8.5)
    arrow(ax, 7.15, 7.16, 7.15, 6.62)
    ax.text(7.28, 6.88, "关注级", fontsize=8.2, color=MUTED)

    # ---------------- new-data lane ----------------
    ax.text(0.3, 5.66, "新增数据链路", fontsize=9, color=MUTED)
    box(ax, 0.3, 4.88, 1.9, 0.68, "新增数据", AMBER, fs=10)
    box(ax, 2.5, 4.88, 2.5, 0.68, "稳健 z + 区间", AMBER, fs=9.6)
    box(ax, 5.3, 4.88, 1.5, 0.68, "|z| 判定", PURPLE, fs=9.6)
    arrow(ax, 2.22, 5.22, 2.48, 5.22)
    arrow(ax, 5.02, 5.22, 5.28, 5.22)

    # bus to three outcomes
    line(ax, 6.05, 4.88, 6.05, 4.52)
    line(ax, 1.40, 4.52, 6.90, 4.52)
    for cx in (1.40, 4.10, 6.90):
        arrow(ax, cx, 4.52, cx, 4.28)

    box(ax, 0.4, 3.62, 2.0, 0.64, "正常\n|z| ≤ 2.5", GREEN, fs=9.2)
    box(ax, 2.8, 3.62, 2.6, 0.64, "关注\n2.5 < |z| ≤ 3 → watch", AMBER, fs=8.4)
    box(ax, 5.8, 3.62, 2.2, 0.64, "pending\n|z| > 3 → 人工复核", RED, fs=8.4)

    # pending -> review
    box(ax, 8.5, 3.62, 2.7, 0.64, "人工复核\nkeep / correct /\nexclude / mark", RED, fs=8.0)
    arrow(ax, 8.02, 3.94, 8.48, 3.94)

    # review -> actions
    line(ax, 9.85, 3.62, 9.85, 3.10)
    line(ax, 7.60, 3.10, 10.90, 3.10)
    for cx in (7.60, 9.05, 10.90):
        arrow(ax, cx, 3.10, cx, 2.72)

    box(ax, 7.00, 2.08, 1.2, 0.62, "keep", GREEN, fs=9.2)
    box(ax, 8.40, 2.08, 1.3, 0.62, "correct", AMBER, fs=9.2)
    box(ax, 9.90, 2.08, 2.0, 0.62, "exclude /\nmark_breakpoint", RED, fs=8.4)

    # actions -> common completion
    line(ax, 7.60, 2.08, 7.60, 1.55)
    line(ax, 9.05, 2.08, 9.05, 1.55)
    line(ax, 10.90, 2.08, 10.90, 1.55)
    line(ax, 7.60, 1.55, 10.90, 1.55)
    arrow(ax, 9.25, 1.55, 9.25, 1.30)

    box(ax, 7.0, 0.58, 4.9, 0.72,
        "quality_status 更新\nemission 重算 · audit 追加 · batch 完成", BLUE, fs=8.8)

    ax.text(6.15, 8.25, "异常分流与处置流程", ha="center", va="center",
            fontsize=14, color=NAVY, fontweight="bold")

    fig.tight_layout()
    fig.savefig(OUT / "fig_05_anomaly_disposition.png", dpi=240,
                facecolor="white", bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    print("saved", OUT / "fig_05_anomaly_disposition.png")


if __name__ == "__main__":
    main()
