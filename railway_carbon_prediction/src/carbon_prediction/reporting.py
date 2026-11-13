"""图表、Excel 汇总与评测报告辅助。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import db, repository
from .config import settings
from .data import annual_summary, build_all_history

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ORG_NAMES = {"JLG": "机辆分公司", "SNF": "肃宁分公司", "YPF": "原平分公司"}


def _load_actual() -> tuple[pd.DataFrame, pd.DataFrame]:
    act, em, _, _ = build_all_history()
    return act, em


def _load_forecast() -> pd.DataFrame:
    rows = db.fetch_all(
        "SELECT org_id,period,point,lower_bound,upper_bound,reported_point,comparable_point "
        "FROM prediction_forecast WHERE scenario='BAU' ORDER BY org_id,period"
    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["period"] = pd.to_datetime(df["period"])
        for c in ["point", "lower_bound", "upper_bound", "reported_point", "comparable_point"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _load_gra() -> pd.DataFrame:
    rows = []
    for org_id in ORG_NAMES:
        rows.extend(repository.load_gra_results(org_id))
    df = pd.DataFrame(rows)
    if not df.empty:
        df["r"] = pd.to_numeric(df["r"], errors="coerce")
        df["r_detrend"] = pd.to_numeric(df["r_detrend"], errors="coerce")
    return df


def _load_models() -> pd.DataFrame:
    rows = repository.load_models()
    out = []
    for r in rows:
        metrics = r.get("metrics") or {}
        if isinstance(metrics, str):
            try:
                metrics = json.loads(metrics)
            except Exception:
                metrics = {}
        if not r.get("is_champion"):
            continue
        test = metrics.get("test_2025", {}) if isinstance(metrics, dict) else {}
        out.append({
            "org_id": r["org_id"], "model_id": r["model_id"], "model_type": r["model_type"],
            "W": r["window_size"], "MASE": test.get("MASE"), "MAPE": test.get("MAPE"),
            "RMSE": test.get("RMSE"), "R2": test.get("R2"), "Bias": test.get("Bias"),
            "metrics": metrics,
        })
    return pd.DataFrame(out)


def _plot_trend(act: pd.DataFrame, em: pd.DataFrame, org_id: str, out: Path) -> None:
    e = em[em["org_id"] == org_id].copy()
    e["period"] = pd.to_datetime(e["period"])
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.plot(e["period"], e["total_reported_tco2"], label="报表口径", color="#c0392b", lw=1.6)
    ax.plot(e["period"], e["total_comparable_tco2"], label="可比口径（2025因子/0.9224供热）",
            color="#2c7fb8", lw=1.6, ls="--")
    ax.set_title(f"{ORG_NAMES.get(org_id, org_id)} 月度碳排放（2019-2025）")
    ax.set_ylabel("tCO2e/月")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def _plot_forecast(em: pd.DataFrame, fc: pd.DataFrame, org_id: str, out: Path) -> None:
    e = em[em["org_id"] == org_id].copy()
    e["period"] = pd.to_datetime(e["period"])
    e = e[e["period"] >= "2023-01-01"]
    f = fc[fc["org_id"] == org_id].copy()
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.plot(e["period"], e["total_comparable_tco2"], label="历史可比口径", color="#2c7fb8", lw=1.6)
    if not f.empty:
        ax.plot(f["period"], f["comparable_point"], label="2026预测", color="#e67e22", lw=2)
        ax.fill_between(f["period"], f["lower_bound"], f["upper_bound"], color="#e67e22", alpha=0.18,
                        label="90%区间")
    ax.set_title(f"{ORG_NAMES.get(org_id, org_id)} 未来一年预测（可比口径）")
    ax.set_ylabel("tCO2e/月")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def _plot_gra(gra: pd.DataFrame, org_id: str, out: Path) -> None:
    g = gra[gra["org_id"] == org_id].dropna(subset=["r"]).sort_values("r")
    fig, ax = plt.subplots(figsize=(9, 4.2))
    colors = ["#e67e22" if int(s) == 1 else "#95a5a6" for s in g["selected"]]
    ax.barh(g["var_name"], g["r"], color=colors, label="关联度 r")
    ax.scatter(g["r_detrend"], g["var_name"], color="#2c3e50", s=24, label="去趋势 r", zorder=3)
    ax.axvline(0.70, color="#c0392b", ls="--", lw=1, label="阈值 0.70")
    ax.set_xlim(0, 1)
    ax.set_title(f"{ORG_NAMES.get(org_id, org_id)} 灰色关联度（橙色=入选）")
    ax.grid(axis="x", alpha=0.25)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def _plot_model_compare(models: pd.DataFrame, org_id: str, out: Path) -> None:
    row = models[models["org_id"] == org_id]
    if row.empty:
        return
    metrics = row.iloc[0]["metrics"]
    base = metrics.get("baselines_test_2025", {}) if isinstance(metrics, dict) else {}
    items = {k: v.get("MASE") for k, v in base.items() if v}
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    ax.bar(list(items.keys()), list(items.values()), color="#7fb3d5")
    ax.axhline(1.0, color="#c0392b", ls="--", lw=1, label="季节naive基准线 MASE=1")
    ax.set_ylabel("MASE（越低越好）")
    ax.set_title(f"{ORG_NAMES.get(org_id, org_id)} 2025测试集模型对比")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def generate_all() -> dict:
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    act, em = _load_actual()
    fc = _load_forecast()
    gra = _load_gra()
    models = _load_models()
    summary = annual_summary(em, act)

    for org_id in ORG_NAMES:
        _plot_trend(act, em, org_id, settings.report_dir / f"trend_{org_id}.png")
        _plot_forecast(em, fc, org_id, settings.report_dir / f"forecast_{org_id}.png")
        if not gra.empty:
            _plot_gra(gra, org_id, settings.report_dir / f"gra_{org_id}.png")
        _plot_model_compare(models, org_id, settings.report_dir / f"model_compare_{org_id}.png")

    # Excel 汇总
    xlsx = settings.report_dir / "碳排放预测结果汇总.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        if not fc.empty:
            out = fc.copy()
            out["org_name"] = out["org_id"].map(ORG_NAMES)
            out[["org_name", "org_id", "period", "comparable_point", "reported_point",
                 "lower_bound", "upper_bound"]].to_excel(writer, sheet_name="预测结果", index=False)
        if not models.empty:
            out = models[["org_id", "model_type", "W", "MASE", "MAPE", "RMSE", "R2", "Bias"]].copy()
            out["org_name"] = out["org_id"].map(ORG_NAMES)
            out.to_excel(writer, sheet_name="模型指标", index=False)
        if not gra.empty:
            out = gra[["org_id", "var_name", "r", "r_detrend", "rank_no", "selected",
                       "spurious", "rho_sensitive", "borderline", "note"]].copy()
            out["org_name"] = out["org_id"].map(ORG_NAMES)
            out.to_excel(writer, sheet_name="GRA关联度", index=False)
        anom = pd.DataFrame(repository.load_anomalies(limit=1000))
        if not anom.empty:
            cols = [c for c in ["org_id", "period", "var_id", "level", "category", "score",
                                "channels", "context_flags", "breakpoint_date", "breakpoint_stat",
                                "shift_pct", "cv_ratio", "final_disposition", "status",
                                "evidence"] if c in anom.columns]
            anom[cols].to_excel(writer, sheet_name="异常清单", index=False)
        watch = pd.DataFrame(repository.load_watch(limit=1000))
        if not watch.empty:
            cols = [c for c in ["org_id", "period", "var_id", "level", "category", "score",
                                "channels", "context_flags", "evidence"] if c in watch.columns]
            watch[cols].to_excel(writer, sheet_name="关注监控", index=False)
        calib = pd.DataFrame(db.fetch_all(
            "SELECT org_id,var_id,quantile,precision_v,recall_v,f1,n_pos,n_neg,selected "
            "FROM prediction_anomaly_calibration ORDER BY created_at DESC LIMIT 100"
        ))
        if not calib.empty:
            calib.to_excel(writer, sheet_name="阈值校准", index=False)
        summary.to_excel(writer, sheet_name="年度实际", index=False)
        pd.DataFrame([{
            "说明": "报表口径=当年实际电力因子/供热折算系数；可比口径=固定2025年电力因子0.5306、供热0.9224 GJ/m2，用于建模。"
        }]).to_excel(writer, sheet_name="口径说明", index=False)

    return {"report_dir": str(settings.report_dir), "xlsx": str(xlsx),
            "charts": len(list(settings.report_dir.glob("*.png")))}
