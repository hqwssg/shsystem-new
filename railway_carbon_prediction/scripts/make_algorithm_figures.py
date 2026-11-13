"""Generate algorithm diagrams for the Word design document."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parents[1] / "artifacts" / "figures"
OUT.mkdir(parents=True, exist_ok=True)


def box(ax, x, y, w, h, text, fc="#EAF2F8", ec="#2C3E50", fs=9):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                       linewidth=1.0, edgecolor=ec, facecolor=fc)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs)


def arrow(ax, x1, y1, x2, y2):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                 mutation_scale=10, linewidth=1.0, color="#34495E"))


def overall():
    fig, ax = plt.subplots(figsize=(11, 5.2))
    ax.set_xlim(0, 11); ax.set_ylim(0, 5.2); ax.axis("off")
    box(ax, 0.3, 3.8, 1.9, 0.9, "原始台账\n3 分公司×84 月", "#FDEBD0")
    box(ax, 2.6, 3.8, 1.9, 0.9, "口径还原\n双口径排放", "#EAF2F8")
    box(ax, 4.9, 3.8, 1.9, 0.9, "异常检测 V2\n复核/关注分流", "#E8F8F5")
    box(ax, 7.2, 3.8, 1.9, 0.9, "GRA\n因素筛选", "#F4ECF7")
    box(ax, 9.5, 3.8, 1.2, 0.9, "特征\n面板", "#F4ECF7")
    box(ax, 0.3, 1.9, 2.2, 0.9, "滑动窗口\nW∈{6,9,12}", "#FEF9E7")
    box(ax, 2.9, 1.9, 2.2, 0.9, "SW-LSTM\n直接 12 步", "#EBF5FB")
    box(ax, 5.5, 1.9, 2.2, 0.9, "基线与降级\nRidge/GBM/HW/SN", "#F2F3F4")
    box(ax, 8.1, 1.9, 2.4, 0.9, "柴油模块\n台数×强度", "#FDEBD0")
    box(ax, 3.2, 0.3, 2.2, 0.8, "2026 预测\n可比口径", "#E8F8F5")
    box(ax, 6.1, 0.3, 2.4, 0.8, "报表口径折算\n热力系数", "#E8F8F5")
    box(ax, 9.0, 0.3, 1.8, 0.8, "写库/API\nprediction_forecast", "#EAF2F8")
    for x in [2.2, 4.5, 6.8, 9.1]:
        arrow(ax, x, 4.25, x + 0.35, 4.25)
    arrow(ax, 10.1, 3.75, 1.6, 2.85)
    arrow(ax, 2.5, 2.35, 2.85, 2.35)
    arrow(ax, 5.1, 2.35, 5.45, 2.35)
    arrow(ax, 7.7, 2.35, 8.05, 2.35)
    arrow(ax, 9.3, 1.85, 4.4, 1.15)
    arrow(ax, 5.4, 0.7, 6.05, 0.7)
    arrow(ax, 8.5, 0.7, 8.95, 0.7)
    ax.text(5.5, 4.95, "数据准备 → 异常治理 → 因素筛选 → 时序建模 → 预测与折算",
            ha="center", fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "fig_01_overall_flow.png", dpi=200)
    plt.close(fig)


def anomaly():
    fig, ax = plt.subplots(figsize=(10.8, 7.0))
    ax.set_xlim(0, 10.8); ax.set_ylim(0, 7.0); ax.axis("off")

    def line(x1, y1, x2, y2):
        ax.plot([x1, x2], [y1, y2], color="#34495E", lw=1.0, zorder=1,
                solid_capstyle="round")

    # top chain
    box(ax, 0.3, 5.8, 2.0, 0.72, "月度序列\n(org×var)", fs=12)
    box(ax, 2.6, 5.8, 2.0, 0.72, "STL 分解\nperiod=12", fs=12)
    box(ax, 4.9, 5.8, 2.0, 0.72, "统计量构造\nMAD z / 断点", fs=12)
    arrow(ax, 2.3, 6.16, 2.56, 6.16)
    arrow(ax, 4.6, 6.16, 4.86, 6.16)

    # evidence row
    box(ax, 0.3, 4.1, 3.2, 0.9, "双通道森林\nraw / resid / joint", fs=11.5)
    box(ax, 3.8, 4.1, 2.8, 0.9, "月度断点\nCUSUM + 池化", fs=11.5)
    box(ax, 6.9, 4.1, 3.2, 0.9, "日历 / 护栏\n春节 / 疫情 / 检修", fs=11.5)

    # bus 1: statistic -> evidence
    line(5.9, 5.8, 5.9, 5.28)
    line(1.9, 5.28, 8.5, 5.28)
    for cx in (1.9, 5.2, 8.5):
        arrow(ax, cx, 5.28, cx, 5.02)

    # classification row
    box(ax, 2.7, 2.7, 4.8, 0.8, "C1—C4 规则分类\n断点 → 季节 → 单点 → 连续段", "#F4ECF7", fs=12)

    # bus 2: evidence -> classification
    line(1.9, 4.1, 1.9, 3.8)
    line(8.5, 4.1, 8.5, 3.8)
    line(1.9, 3.8, 8.5, 3.8)
    for cx in (1.9, 5.2, 8.5):
        line(cx, 4.1, cx, 3.8)
    arrow(ax, 5.1, 3.8, 5.1, 3.52)

    # outputs
    box(ax, 1.5, 1.5, 2.8, 0.7, "复核级\nprediction_anomaly", "#FADBD8", fs=10.5)
    box(ax, 5.2, 1.5, 2.8, 0.7, "关注级\nanomaly_watch", "#D5F5E3", fs=10.5)
    line(5.1, 2.7, 5.1, 2.45)
    line(2.9, 2.45, 6.6, 2.45)
    arrow(ax, 2.9, 2.45, 2.9, 2.22)
    arrow(ax, 6.6, 2.45, 6.6, 2.22)

    # bottom: history / new-point branches
    box(ax, 0.3, 0.3, 4.5, 0.7, "历史数据 → auto_closed\nkeep / mark_breakpoint", "#EAF2F8", fs=9.5)
    box(ax, 5.2, 0.3, 5.2, 0.7, "新增单点 → 人工复核 → 重算/审计\nkeep / correct / exclude / mark", "#FEF9E7", fs=9.3)

    ax.text(5.4, 6.82, "异常检测 V2：证据层 → 分类层 → 分流层",
            ha="center", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "fig_02_anomaly_flow.png", dpi=220)
    plt.close(fig)


def lstm():
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.set_xlim(0, 10); ax.set_ylim(0, 3.6); ax.axis("off")
    box(ax, 0.3, 1.2, 1.8, 1.1, "输入\nW×F\n目标+特征", "#EAF2F8")
    box(ax, 2.7, 1.2, 2.0, 1.1, "LSTM\nunits=32/64\ndropout=0.2", "#EBF5FB")
    box(ax, 5.3, 1.2, 1.7, 1.1, "Dense\nReLU\n32", "#FEF9E7")
    box(ax, 7.6, 1.2, 1.7, 1.1, "输出\nH=12\n线性", "#E8F8F5")
    arrow(ax, 2.1, 1.75, 2.65, 1.75)
    arrow(ax, 4.7, 1.75, 5.25, 1.75)
    arrow(ax, 7.0, 1.75, 7.55, 1.75)
    ax.text(5.0, 3.1, "SW-LSTM 结构：滑动窗口 → 直接多步",
            ha="center", fontsize=11, fontweight="bold")
    ax.text(5.0, 0.55, "损失 MSE；Adam；early stopping；gradient clip=1.0；forget bias=1.0",
            ha="center", fontsize=9, color="#34495E")
    fig.tight_layout()
    fig.savefig(OUT / "fig_03_lstm_arch.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    overall()
    anomaly()
    lstm()
    print("figures:", [p.name for p in OUT.glob("*.png")])
