"""孤立森林异常检测（历史批量 + 新增单点）。

历史数据：按组织×品种独立建树，STL 残差通道为主、原始通道为辅；
新增数据：用历史稳健分布做单点打分，命中后进入 pending 人工复核。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.seasonal import STL

from .config import settings

KEY_VARS = ["ELEC_TOTAL", "DIESEL", "HEAT", "GAS", "CO2_COMPARABLE"]
HEATING_MONTHS = {"JLG": [1, 2, 3, 4, 11, 12], "SNF": [1, 2, 3, 11, 12], "YPF": [1, 2, 3, 4, 11, 12]}


def _series_features(y: pd.Series, period: pd.Series) -> pd.DataFrame:
    y = pd.to_numeric(y, errors="coerce").astype(float)
    resid = pd.Series(0.0, index=y.index)
    if len(y.dropna()) >= 24:
        try:
            stl = STL(y.interpolate(limit_direction="both"), period=12, robust=True).fit()
            resid = pd.Series(stl.resid, index=y.index)
        except Exception:
            pass
    sigma = float(resid.std()) or 1.0
    feat = pd.DataFrame({
        "value": y,
        "resid": resid,
        "resid_z": resid / sigma,
        "mom": y.pct_change().replace([np.inf, -np.inf], 0),
        "yoy": y.pct_change(12).replace([np.inf, -np.inf], 0),
        "roll_mean3": y.rolling(3, min_periods=1).mean(),
        "roll_std3": y.rolling(3, min_periods=1).std().fillna(0),
        "month_sin": np.sin(2 * np.pi * pd.to_datetime(period).dt.month / 12),
        "month_cos": np.cos(2 * np.pi * pd.to_datetime(period).dt.month / 12),
    })
    return feat.fillna(0.0)


def _grade(score: float, decision: float, percentile: float) -> str:
    if score < 0.55 and decision >= 0:
        return "正常"
    if score >= 0.75 or percentile >= 99:
        return "严重异常"
    if score >= 0.65 and decision < 0:
        return "异常"
    return "关注"


def _classify(y: np.ndarray, i: int, resid: np.ndarray, month: int, org_id: str) -> tuple[str, float, str]:
    sigma = float(np.nanstd(resid)) or 1.0
    n = len(y)
    prev = y[i - 1] if i > 0 else np.nan
    nxt = y[i + 1] if i < n - 1 else np.nan
    d1 = y[i] - prev if np.isfinite(prev) else 0
    d2 = nxt - y[i] if np.isfinite(nxt) else 0

    # C4 季节峰谷：供暖月且残差不大
    if month in HEATING_MONTHS.get(org_id, []) and abs(resid[i]) < 2 * sigma:
        return "C4", 0.65, "供暖季正常峰谷，残差在 2σ 内"

    # C3 水平位移：前后 3 期均值差 > 2σ 且不回落
    if 3 <= i < n - 3:
        before = np.nanmean(y[i - 3:i])
        after = np.nanmean(y[i:i + 3])
        if abs(after - before) > 2 * sigma and abs(after - before) > 0.15 * max(abs(before), 1e-9):
            return "C3", 0.72, f"前后3期均值位移 {after-before:.2f}，超过2σ且持续"

    # C1 孤立尖峰：前后方向相反且都超过 2σ
    if np.isfinite(prev) and np.isfinite(nxt) and np.sign(d1) != np.sign(d2) \
            and abs(d1) > 2 * sigma and abs(d2) > 2 * sigma:
        return "C1", 0.78, "单点尖峰，次期回落，疑似录入/抄表错误"

    # C2 连续多点漂移
    if i >= 2:
        window = y[max(0, i - 2):i + 1]
        if np.all(np.abs(np.diff(window)) > 1.0 * sigma):
            return "C2", 0.60, "连续多点同向漂移，疑似计量通道异常"

    return "UNDETERMINED", 0.45, "统计异常，业务证据不足"


def detect_history(activity: pd.DataFrame) -> List[dict]:
    """对历史长表逐组织×品种运行孤立森林，返回异常记录（已自动处置）。"""
    out: List[dict] = []
    batch_id = f"ANOM-HIST-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    for org_id, org_df in activity.groupby("org_id"):
        for var_id in KEY_VARS:
            sub = org_df[org_df["var_id"] == var_id].sort_values("period")
            if len(sub) < 24:
                continue
            y = pd.to_numeric(sub["value"], errors="coerce").reset_index(drop=True)
            period = pd.to_datetime(sub["period"]).reset_index(drop=True)
            feat = _series_features(y, period)
            X = StandardScaler().fit_transform(feat.values)
            model = IsolationForest(
                n_estimators=200, contamination=settings.anomaly_contamination,
                random_state=settings.seed, n_jobs=1,
            )
            model.fit(X)
            scores = -model.score_samples(X)
            decisions = model.decision_function(X)
            pct = pd.Series(scores).rank(pct=True).values * 100
            resid = feat["resid"].values
            for i in range(len(y)):
                level = _grade(float(scores[i]), float(decisions[i]), float(pct[i]))
                # 历史批量筛查只固化“异常/严重异常”；“关注”级不落库，避免噪声淹没复核队列
                if level in ("正常", "关注"):
                    continue
                cat, conf, evidence = _classify(y.values, i, resid, int(period.iloc[i].month), org_id)
                if cat in ("C3", "C2"):
                    disp = "mark_breakpoint"
                elif cat == "C4":
                    disp = "keep"
                else:
                    disp = "keep"
                out.append({
                    "org_id": org_id, "period": period.iloc[i].date(), "var_id": var_id,
                    "detect_batch_id": batch_id, "channel": "stl_residual",
                    "score": round(float(scores[i]), 6),
                    "score_percentile": round(float(pct[i]), 2),
                    "level": level, "category": cat, "confidence": conf,
                    "suggested_disposition": disp, "status": "auto_closed",
                    "final_disposition": disp, "value": float(y.iloc[i]),
                    "reference_value": float(np.nanmedian(y)),
                    "evidence": evidence, "reviewer": "system",
                    "reviewed_at": datetime.now(), "review_note": "历史数据自动筛查，按规则保留/标记结构断点",
                })
    return out


def detect_new_point(org_id: str, var_id: str, period: str, value: float,
                     history: pd.Series, history_period: pd.Series) -> Optional[dict]:
    """新增单点稳健打分；返回异常记录或 None。"""
    y = pd.to_numeric(history, errors="coerce").astype(float).reset_index(drop=True)
    p = pd.to_datetime(history_period).reset_index(drop=True)
    if len(y) < 18:
        return None
    month = pd.Timestamp(period).month
    same_month = y[p.dt.month == month]
    base = same_month if len(same_month) >= 3 else y.tail(24)
    med = float(base.median())
    mad = float((base - med).abs().median()) * 1.4826
    sigma = mad if mad > 0 else float(base.std()) or 1.0
    z = (value - med) / sigma
    outside = value > float(y.max()) * 1.2 or value < max(0.0, float(y.min()) * 0.8)
    if abs(z) <= 3 and not outside:
        return None
    return {
        "org_id": org_id, "period": period, "var_id": var_id,
        "detect_batch_id": f"ANOM-NEW-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "channel": "raw", "score": round(min(1.0, abs(z) / 10), 6),
        "score_percentile": None, "level": "严重异常" if abs(z) > 5 else "异常",
        "category": "UNDETERMINED", "confidence": 0.5,
        "suggested_disposition": "keep", "status": "pending",
        "value": float(value), "reference_value": med,
        "evidence": f"同月稳健 z={z:.2f}；历史同月中位数={med:.2f}；超出历史区间={outside}",
        "reviewer": None, "reviewed_at": None, "review_note": None,
    }
