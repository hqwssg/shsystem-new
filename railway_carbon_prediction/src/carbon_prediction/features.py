"""特征面板构建。

目标变量：CO2_COMPARABLE（可比口径，固定 2025 年电力因子与 0.9224 供热系数）。
候选外部因子：气象（HDD/CDD）、煤价、煤炭产量、铁路货运量、火电发电量、
政策事件强度。GRA 在候选因子中筛选，日历与趋势项作为控制变量始终保留。
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from . import repository

# var_id -> (中文名, 单位, 类别, 方向)
CANDIDATES: Dict[str, Tuple[str, str, str, str]] = {
    "HDD_ORG": ("采暖度日", "℃·d", "weather", "positive"),
    # CDD 在本地为强零膨胀序列（冬季全 0，且原表 2026 年前多处为 0），
    # 初值化会被人为放大，故不进入主筛选；保留在外部因子表中备查。
    "COAL_PRICE_QHD5500": ("秦皇岛港5500大卡动力煤长协价", "元/吨", "price", "unknown"),
    "COAL_OUTPUT_TOTAL": ("三省原煤产量合计", "万吨", "supply", "positive"),
    "RAIL_FREIGHT_CN": ("全国铁路货运量", "万吨", "transport", "positive"),
    "THERMAL_POWER_CN": ("全国火力发电量", "亿千瓦时", "power", "positive"),
    "POLICY_EVENT_INTENSITY": ("政策事件强度指数", "0-1", "policy", "unknown"),
}

# 小样本年度外推中，线性 trend 会把 2023 年前的上升趋势外推到 2025，
# 与 2024 年的电量回落、2025 年的柴油退役叠加后产生系统性高估；
# 因此模型只用月份周期项，趋势由窗口内的目标历史承载。
CALENDAR_FEATURES = ["month_sin", "month_cos"]


def _org_station(org_id: str) -> Tuple[str, str]:
    if org_id == "SNF":
        return "TEMP_SUNING", "HDD_SUNING"
    if org_id == "YPF":
        return "TEMP_YUANPING", "HDD_YUANPING"
    return "TEMP_AVG4", "HDD_AVG4"


def load_feature_frame(org_id: str, start: str | None = None, end: str | None = None,
                       valid_only: bool = False) -> pd.DataFrame:
    """加载 2019-01 至 2026-12 的目标与候选因子面板。

    valid_only=True 时排除存在 pending/excluded 活动记录的月份，用于训练/GRA/预测，
    避免未复核的新增数据进入模型。
    """
    em = repository.load_emission_series(org_id, start, end, valid_only=valid_only)
    if em.empty:
        raise ValueError(f"{org_id} 无排放数据")
    ext = repository.load_external_wide()
    df = em.merge(ext, on="period", how="left").sort_values("period").reset_index(drop=True)

    temp_col, hdd_col = _org_station(org_id)
    cdd_col = {"TEMP_SUNING": "CDD_SUNING", "TEMP_YUANPING": "CDD_YUANPING"}.get(
        temp_col, "CDD_AVG4"
    )
    df["TEMP_ORG"] = pd.to_numeric(df.get(temp_col), errors="coerce")
    df["HDD_ORG"] = pd.to_numeric(df.get(hdd_col), errors="coerce")
    df["CDD_ORG"] = pd.to_numeric(df.get(cdd_col), errors="coerce")

    # 日历与趋势（趋势以 2019-01 为原点，保证训练/推理一致）
    df["month"] = df["period"].dt.month
    df["year"] = df["period"].dt.year
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    origin = pd.Timestamp("2019-01-01")
    df["trend"] = ((df["period"] - origin).dt.days / 30.4375).round(6)

    df["y"] = pd.to_numeric(df["total_comparable_tco2"], errors="coerce")
    df["y_reported"] = pd.to_numeric(df["total_reported_tco2"], errors="coerce")
    df["diesel_tco2"] = pd.to_numeric(df.get("diesel_tco2"), errors="coerce").fillna(0.0)
    # 建模目标剔除柴油：2025 年内燃机车批量退役是已知结构断点，
    # 柴油由独立“台数×单机排放”模块预测，避免 LSTM 把政策断点当趋势。
    df["y_nondiesel"] = df["y"] - df["diesel_tco2"]

    # 外部因子数值化
    for c in CANDIDATES:
        if c not in df.columns:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # 目标期缺失（2026）不参与训练；外部因子已在外部队列补齐
    return df


def feature_columns(selected: List[str]) -> List[str]:
    cols = [c for c in selected if c in CANDIDATES]
    return cols + CALENDAR_FEATURES


def matrix(df: pd.DataFrame, selected: List[str]) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    cols = feature_columns(selected)
    X = df[cols].astype(float).copy()
    # 只允许用历史值填充：前向填充，首部用后向填充兜底
    X = X.ffill().bfill()
    y = df["y"].astype(float).values
    return X.values, y, cols


def future_frame(org_id: str, as_of: str, horizon: int) -> pd.DataFrame:
    """返回 as_of 之后的 horizon 个月，含已补齐的外部因子。"""
    df = load_feature_frame(org_id, valid_only=True)
    as_of_ts = pd.Timestamp(as_of) + pd.offsets.MonthBegin(1)
    fut = df[df["period"] >= as_of_ts].head(horizon).copy()
    if len(fut) < horizon:
        raise ValueError(f"{org_id} 未来外部因子不足：需要 {horizon} 个月，实际 {len(fut)}")
    return fut


def selected_from_gra(rows: List[dict]) -> List[str]:
    return [r["var_id"] for r in sorted(rows, key=lambda x: x["rank_no"]) if int(r["selected"]) == 1]
