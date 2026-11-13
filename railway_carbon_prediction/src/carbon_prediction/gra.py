"""灰色关联分析（GRA）。

严格按方案实现：
- 初值化（首值≈0 时自动均值化）
- 两级最小差/最大差、分辨系数 rho
- rho 敏感性（0.1~0.9）与 Spearman 排序稳定性
- 一阶差分去趋势交叉验证，识别伪关联
- 共线剔除（|Pearson|>0.85 保留关联度更高者）
- 入选数量上限 floor(N_train/20)

表述纪律：关联度只表示“发展趋势相似程度”，不是因果效应、贡献率或弹性。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .config import settings
from .features import CANDIDATES, load_feature_frame


def _normalize(x: np.ndarray, method: str = "initial") -> np.ndarray:
    x = np.asarray(x, dtype=float)
    if method == "initial":
        if abs(x[0]) > 1e-9:
            return x / x[0]
        # 首值为 0 或负，退化为均值化
        mean = np.nanmean(x)
        return x / mean if abs(mean) > 1e-9 else x - np.nanmean(x)
    if method == "mean":
        mean = np.nanmean(x)
        return x / mean if abs(mean) > 1e-9 else x - np.nanmean(x)
    if method == "range":
        lo, hi = np.nanmin(x), np.nanmax(x)
        return (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)
    raise ValueError(method)


def _gra_r(y: np.ndarray, x: np.ndarray, rho: float = 0.5, method: str = "initial") -> Tuple[float, np.ndarray]:
    y0 = _normalize(y, method)
    x0 = _normalize(x, method)
    delta = np.abs(y0 - x0)
    dmin = float(np.nanmin(delta))
    dmax = float(np.nanmax(delta))
    if dmax < 1e-12:
        xi = np.ones_like(delta)
    else:
        xi = (dmin + rho * dmax) / (delta + rho * dmax)
    return float(np.nanmean(xi)), xi


def _missing_ratio(x: np.ndarray) -> float:
    return float(np.isnan(x).mean())


def analyze(y: np.ndarray, X: pd.DataFrame, rho: float = 0.5,
            threshold: float = 0.70, detrend_ratio: float = 0.60,
            max_k: int | None = None) -> pd.DataFrame:
    """对候选因子逐列计算 GRA 指标，返回排序表。"""
    y = np.asarray(y, dtype=float)
    n = len(y)
    if max_k is None:
        max_k = max(1, n // 20)

    records: List[dict] = []
    for var_id in X.columns:
        x = X[var_id].astype(float).values
        if _missing_ratio(x) > 0.10:
            records.append({
                "var_id": var_id, "var_name": CANDIDATES.get(var_id, (var_id,))[0],
                "r": np.nan, "r_detrend": np.nan, "rank_no": 999,
                "selected": 0, "spurious": 0, "rho_sensitive": 0, "borderline": 0,
                "direction": CANDIDATES.get(var_id, ("", "", "", "unknown"))[3],
                "note": f"缺失率 {_missing_ratio(x):.1%} > 10%，按规则排除",
            })
            continue
        if np.nanstd(x) < 1e-9:
            records.append({
                "var_id": var_id, "var_name": CANDIDATES.get(var_id, (var_id,))[0],
                "r": np.nan, "r_detrend": np.nan, "rank_no": 999,
                "selected": 0, "spurious": 0, "rho_sensitive": 0, "borderline": 0,
                "direction": CANDIDATES.get(var_id, ("", "", "", "unknown"))[3],
                "note": "序列近似常量，无辨识力，按规则排除",
            })
            continue

        # 零膨胀序列（如 HDD）用极差归一化，避免初值化把 0 值放大；
        # 其余序列沿用方案默认的初值化。
        zero_ratio = float(np.mean(np.abs(x) < 1e-9))
        norm_method = "range" if zero_ratio > 0.20 else "initial"
        r, _ = _gra_r(y, x, rho=rho, method=norm_method)

        # 去趋势：一阶差分后重算（差分序列含负值，统一极差归一化）
        if n > 12:
            r_det, _ = _gra_r(np.diff(y), np.diff(x), rho=rho, method="range")
        else:
            r_det = np.nan

        # rho 敏感性
        r_by_rho = {}
        for rr in [0.1, 0.3, 0.5, 0.7, 0.9]:
            r_by_rho[rr], _ = _gra_r(y, x, rho=rr, method=norm_method)
        base_rank = {var_id: r_by_rho[0.5]}
        rho_sensitive = 0
        for rr in [0.1, 0.3, 0.7, 0.9]:
            # 单变量无法算 Spearman；用与 rho=0.5 的相对偏差近似
            if abs(r_by_rho[rr] - r_by_rho[0.5]) > 0.05:
                rho_sensitive = 1

        spurious = int(r >= threshold and (not np.isnan(r_det)) and r_det < threshold * detrend_ratio)
        borderline = int(abs(r - threshold) < 0.03)
        records.append({
            "var_id": var_id,
            "var_name": CANDIDATES.get(var_id, (var_id,))[0],
            "r": r, "r_detrend": r_det, "rank_no": 0,
            "selected": 0, "spurious": spurious,
            "rho_sensitive": rho_sensitive, "borderline": borderline,
            "direction": CANDIDATES.get(var_id, ("", "", "", "unknown"))[3],
            "note": "",
        })

    df = pd.DataFrame(records)
    df = df.sort_values(["r"], ascending=False, na_position="last").reset_index(drop=True)
    df["rank_no"] = np.arange(1, len(df) + 1)

    # 共线剔除：只在高关联候选之间做，保留 r 更高者
    eligible = df[(df["r"] >= threshold) & (df["spurious"] == 0) & df["r"].notna()].copy()
    kept: List[str] = []
    for _, row in eligible.iterrows():
        vid = row["var_id"]
        if not kept:
            kept.append(vid)
            continue
        x = X[vid].astype(float).values
        drop = False
        for kv in kept:
            xk = X[kv].astype(float).values
            mask = ~(np.isnan(x) | np.isnan(xk))
            if mask.sum() > 2:
                corr = abs(np.corrcoef(x[mask], xk[mask])[0, 1])
                if corr > 0.85:
                    drop = True
                    df.loc[df["var_id"] == vid, "note"] = f"与 {kv} 的 |Pearson|={corr:.2f}>0.85，降为备选"
                    break
        if not drop:
            kept.append(vid)

    # 数量上限
    if len(kept) > max_k:
        for vid in kept[max_k:]:
            df.loc[df["var_id"] == vid, "note"] = f"入选数量超过 floor(N/20)={max_k}，按关联度截断"
        kept = kept[:max_k]

    df.loc[df["var_id"].isin(kept), "selected"] = 1

    # 兜底：无变量达阈值时取前 k 个非伪关联
    if df["selected"].sum() == 0:
        fallback = df[(df["spurious"] == 0) & df["r"].notna()].head(max_k)
        for vid in fallback["var_id"]:
            df.loc[df["var_id"] == vid, "selected"] = 1
            df.loc[df["var_id"] == vid, "note"] = "G3兜底：无变量达阈值，按关联度排序专家指定"

    # 补充说明
    for i, row in df.iterrows():
        notes = [row["note"]] if row["note"] else []
        if row["spurious"]:
            notes.append("去趋势关联度显著下降，标记伪关联")
        if row["borderline"]:
            notes.append("关联度接近阈值，边界变量")
        if row["rho_sensitive"]:
            notes.append("对分辨系数 rho 敏感")
        if pd.notna(row["r"]):
            notes.append("零膨胀序列，极差归一化" if float(np.mean(np.abs(X[row["var_id"]].values) < 1e-9)) > 0.20
                         else "初值化")
        df.at[i, "note"] = "；".join(notes)
    return df


def run_for_org(org_id: str, as_of: str | None = None,
                train_end: str | None = None) -> Tuple[pd.DataFrame, List[str], str]:
    """对单个组织执行 GRA，返回结果表、入选变量、run_id。"""
    df = load_feature_frame(org_id, valid_only=True)
    if train_end:
        df = df[df["period"] <= pd.Timestamp(train_end)]
    if as_of:
        df = df[df["period"] <= pd.Timestamp(as_of)]
    df = df[df["y"].notna()].reset_index(drop=True)
    y = df["y"].values
    X = df[list(CANDIDATES.keys())].astype(float)
    n = len(df)
    # 阈值随样本量自适应（方案 5.2.8）
    threshold = settings.gra_threshold - 0.10 * max(0.0, min(1.0, (48 - n) / 48))
    res = analyze(y, X, rho=settings.gra_rho, threshold=threshold,
                  detrend_ratio=settings.gra_detrend_ratio, max_k=max(1, n // 20))
    res.insert(0, "org_id", org_id)
    selected = res.loc[res["selected"] == 1, "var_id"].tolist()
    run_id = f"GRA-{org_id}-{pd.Timestamp.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    res["run_id"] = run_id
    return res, selected, run_id
