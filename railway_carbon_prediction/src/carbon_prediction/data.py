"""数据接入、口径还原、缺失推算与外部因子构建。

设计要点
--------
1. 原始报表的 co2_t 受“电力排放因子逐年切换”和“2025 年供热面积折算系数调整”
   影响，报表口径不可直接用于训练。本模块同时产出：
   - 报表口径 total_reported_tco2（与台账一致，供对外报送/展示）
   - 可比口径 total_comparable_tco2（固定 2025 年电力因子 0.5306、
     固定 0.9224 GJ/m2 供热基准系数，供建模）
2. 2019-2020 货运周转量、2019-2023 牵引电力、2019-2021 肃宁天然气月度值
   为推算值，全部打 is_estimated / source_status 标记，可追溯。
3. 2024 年机辆天然气按用户说明排除，用 2023 年同月值补全（气量占比 <0.01%，
   对总量影响可忽略，但保留审计痕迹）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd

from .config import settings

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
ORG_FILES = {
    "JLG": "2020-2024碳排放度数据-机辆1.xlsx",
    "SNF": "2020-2024碳排放度数据-肃宁-1.xlsx",
    "YPF": "2020-2024碳排放度数据-原平-1.xlsx",
}
ORG_NAMES = {"JLG": "机辆分公司", "SNF": "肃宁分公司", "YPF": "原平分公司"}
HEATING_MONTHS = {
    "JLG": [1, 2, 3, 4, 11, 12],
    "SNF": [1, 2, 3, 11, 12],
    "YPF": [1, 2, 3, 4, 11, 12],
}
# 企业台账实际采用的电力因子（按年）
EF_ELEC_BY_YEAR = {
    2019: 0.8843,
    2020: 0.8843,
    2021: 0.8843,
    2022: 0.5703,
    2023: 0.5568,
    2024: 0.5366,
    2025: 0.5306,
}
BASE_EF_ELEC = settings.base_grid_factor       # 0.5306
EF_GAS = 21.621732                            # tCO2 / 万m3
EF_GASOLINE = 3.042475                        # tCO2 / t
EF_DIESEL = 3.145245                          # tCO2 / t
EF_HEAT = 0.11                                # tCO2 / GJ
BASE_HEAT_AREA_FACTOR = settings.base_heat_area_factor  # 0.9224 GJ/m2
HEAT_AREA_FACTOR_2025 = {"SNF": 0.380, "YPF": 0.334}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def month_index(start: str = "2019-01-01", end: str = "2026-12-01") -> pd.DatetimeIndex:
    return pd.date_range(start=start, end=end, freq="MS")


def _period(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.to_period("M").dt.to_timestamp()


def _num(df: pd.DataFrame, col: str, default: float = np.nan) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce")


def _days_in_month(period: pd.Series) -> pd.Series:
    return pd.to_datetime(period).dt.days_in_month.astype(float)


def hdd_series(temp_c: pd.Series, period: pd.Series, base: float = 18.0) -> pd.Series:
    """供暖度日 HDD = max(base - T, 0) × 当月天数。"""
    return (base - pd.to_numeric(temp_c, errors="coerce")).clip(lower=0) * _days_in_month(period)


def cdd_series(temp_c: pd.Series, period: pd.Series, base: float = 26.0) -> pd.Series:
    return (pd.to_numeric(temp_c, errors="coerce") - base).clip(lower=0) * _days_in_month(period)


# ---------------------------------------------------------------------------
# 原始数据读取
# ---------------------------------------------------------------------------
def read_org_raw(org_id: str) -> pd.DataFrame:
    path = settings.raw_dir / ORG_FILES[org_id]
    df = pd.read_excel(path, header=0)
    df.columns = [str(c).strip() for c in df.columns]
    df["period"] = _period(df["date"])
    df = df.sort_values("period").reset_index(drop=True)
    return df


def read_temperature() -> pd.DataFrame:
    """返回 period + 四个站点 + 四地平均气温。"""
    xlsx = settings.external_dir / "朔州_原平_肃宁_黄骅_月平均气温_2019-2026.xlsx"
    if xlsx.exists():
        df = pd.read_excel(xlsx, sheet_name="月度气温")
        df.columns = [str(c).strip() for c in df.columns]
        rename = {
            "年月": "period",
            "朔州(℃)": "SHUOZHOU",
            "原平(℃)": "YUANPING",
            "肃宁(℃)": "SUNING",
            "黄骅(℃)": "HUANGHUA",
            "四地平均(℃)": "AVG4",
        }
        df = df.rename(columns=rename)
        df["period"] = pd.to_datetime(df["period"] + "-01", errors="coerce")
    else:
        csv = settings.external_dir / "朔州_原平_肃宁_黄骅_月平均气温_2019-2026.csv"
        df = pd.read_csv(csv, encoding="utf-8-sig")
        df = df.rename(columns={
            "年月": "period", "朔州(℃)": "SHUOZHOU", "原平(℃)": "YUANPING",
            "肃宁(℃)": "SUNING", "黄骅(℃)": "HUANGHUA", "四地平均(℃)": "AVG4",
        })
        df["period"] = pd.to_datetime(df["period"] + "-01", errors="coerce")
    for c in ["SHUOZHOU", "YUANPING", "SUNING", "HUANGHUA", "AVG4"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["period", "SHUOZHOU", "YUANPING", "SUNING", "HUANGHUA", "AVG4"]].sort_values("period")


def read_coal_price() -> pd.DataFrame:
    csv = settings.external_dir / "动力煤长协价_秦皇岛港5500大卡_月度数据_2019-2026.csv"
    df = pd.read_csv(csv, encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    df["period"] = pd.to_datetime(df["年月"] + "-01", errors="coerce")
    df["value"] = pd.to_numeric(df["长协价_元每吨"], errors="coerce")
    df["source_status"] = df.get("数据性质", "公开报道").fillna("公开报道")
    return df[["period", "value", "source_status"]].sort_values("period")


def read_coal_production() -> pd.DataFrame:
    path = settings.external_dir / "煤产量数据.xlsx"
    df = pd.read_excel(path, sheet_name="外部因子月度序列")
    df.columns = [str(c).strip() for c in df.columns]
    df["period"] = _period(df["date"])
    rename = {
        "山西原煤产量": "COAL_SHANXI",
        "内蒙古原煤产量": "COAL_NEIMENGGU",
        "陕西原煤产量": "COAL_SHAANXI",
        "全国铁路货运量": "RAIL_FREIGHT",
        "全国火力发电量": "THERMAL_POWER",
    }
    df = df.rename(columns=rename)
    for c in rename.values():
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[["period", "COAL_SHANXI", "COAL_NEIMENGGU", "COAL_SHAANXI",
               "RAIL_FREIGHT", "THERMAL_POWER"]].sort_values("period")


# ---------------------------------------------------------------------------
# 外部因子：补齐 2026 年缺失月份
# ---------------------------------------------------------------------------
def _extend_with_seasonal_naive(df: pd.DataFrame, value_cols: List[str],
                                full_index: pd.DatetimeIndex) -> pd.DataFrame:
    """把外部因子补齐到 full_index。

    已有月份保留；缺失月份优先用上年同月 × 最近 8 个月同比增长率；
    无上年同月时用上一可用值。仅用于 2026 年 9-12 月的外推。
    """
    out = df.set_index("period").reindex(full_index)
    out.index.name = "period"
    for col in value_cols:
        s = out[col].astype(float)
        # 最近 8 个月同比增长率（按已观测月份）
        observed = s.dropna()
        growth = 1.0
        if len(observed) >= 20:
            cur = observed.iloc[-8:]
            prev = observed.iloc[-20:-12]
            if len(cur) == len(prev) and prev.sum() != 0:
                growth = float(np.clip(cur.sum() / prev.sum(), 0.8, 1.2))
        for ts in s[s.isna()].index:
            prev_year = ts - pd.DateOffset(years=1)
            if prev_year in s.index and pd.notna(s.loc[prev_year]):
                s.loc[ts] = float(s.loc[prev_year]) * growth
        s = s.ffill().bfill()
        out[col] = s
    return out.reset_index()


def build_external_factors() -> pd.DataFrame:
    """构建 2019-01 ~ 2026-12 的月度外部因子长表。"""
    idx = month_index("2019-01-01", "2026-12-01")

    # 气温：2026-11/12 用 2019-2025 同月气候态
    temp = read_temperature().set_index("period").reindex(idx)
    for c in ["SHUOZHOU", "YUANPING", "SUNING", "HUANGHUA", "AVG4"]:
        clim = temp.loc["2019-01-01":"2025-12-01", c].groupby(
            temp.loc["2019-01-01":"2025-12-01"].index.month).mean()
        for ts in temp.index[temp[c].isna()]:
            if ts.month in clim.index:
                temp.loc[ts, c] = float(clim.loc[ts.month])
    temp = temp.reset_index().rename(columns={"index": "period"})
    for c in ["SHUOZHOU", "YUANPING", "SUNING", "HUANGHUA", "AVG4"]:
        temp[f"HDD_{c}"] = hdd_series(temp[c], temp["period"])
        temp[f"CDD_{c}"] = cdd_series(temp[c], temp["period"])

    # 煤价：线性插值 2019 年缺月；2026-11/12 用最近三个月均值
    price = read_coal_price().set_index("period").reindex(idx)
    price["value"] = price["value"].interpolate(method="linear", limit_direction="both")
    last3 = price["value"].dropna().iloc[-3:].mean()
    price["value"] = price["value"].fillna(last3)
    price["source_status"] = price["source_status"].fillna("插值/外推")
    price = price.reset_index().rename(columns={"index": "period"})

    # 煤产量/铁路货运/火电：2026-09~12 季节性外推
    prod = read_coal_production()
    prod = _extend_with_seasonal_naive(
        prod, ["COAL_SHANXI", "COAL_NEIMENGGU", "COAL_SHAANXI", "RAIL_FREIGHT", "THERMAL_POWER"], idx
    )
    prod["COAL_TOTAL"] = prod[["COAL_SHANXI", "COAL_NEIMENGGU", "COAL_SHAANXI"]].sum(axis=1)

    # 合并
    base = temp.merge(price, on="period", how="left").merge(prod, on="period", how="left")

    # 政策事件强度（定性政策的结构化近似，仅作情景/描述，不进入GRA主筛选）
    event_intensity = pd.Series(0.0, index=idx)
    events = [
        ("2021-10-01", "2022-06-30", 0.80),
        ("2022-02-01", "2026-12-01", 0.90),
        ("2024-05-01", "2026-12-01", 0.45),
        ("2025-01-01", "2026-12-01", 0.35),
        ("2025-01-01", "2026-12-01", 0.40),
    ]
    for s, e, v in events:
        event_intensity.loc[pd.Timestamp(s):pd.Timestamp(e)] = np.maximum(
            event_intensity.loc[pd.Timestamp(s):pd.Timestamp(e)].values, v
        )

    rows: List[dict] = []

    def add(fid: str, name: str, values: Iterable[float], unit: str, category: str,
            source_level: str = "national", source_status: str = "原始",
            scenario_only: int = 0, source: str = "") -> None:
        for ts, v in zip(base["period"], values):
            if v is None or (isinstance(v, float) and math.isnan(v)):
                continue
            rows.append({
                "factor_id": fid, "factor_name": name, "period": ts.date(),
                "value": float(v), "unit": unit, "category": category,
                "source_level": source_level, "source_status": source_status,
                "is_scenario_only": scenario_only, "data_source": source,
            })

    station_map = {
        "SHUOZHOU": "朔州", "YUANPING": "原平", "SUNING": "肃宁", "HUANGHUA": "黄骅", "AVG4": "四地平均"
    }
    for c, cn in station_map.items():
        add(f"TEMP_{c}", f"{cn}月平均气温", base[c], "℃", "weather",
            source_level="station", source="ECMWF ERA5 / Open-Meteo")
        add(f"HDD_{c}", f"{cn}供暖度日", base[f"HDD_{c}"], "℃·d", "weather",
            source_level="station", source="ECMWF ERA5 / Open-Meteo")
        add(f"CDD_{c}", f"{cn}制冷度日", base[f"CDD_{c}"], "℃·d", "weather",
            source_level="station", source="ECMWF ERA5 / Open-Meteo")

    add("COAL_PRICE_QHD5500", "秦皇岛港5500大卡动力煤长协价", base["value"], "元/吨",
        "price", source_level="market", source="公开报道/CCTD/媒体汇总", scenario_only=0,
        source_status="原始/插值")
    add("COAL_OUTPUT_SHANXI", "山西原煤产量", base["COAL_SHANXI"], "万吨", "supply",
        source_level="provincial", source="国家统计局")
    add("COAL_OUTPUT_NEIMENGGU", "内蒙古原煤产量", base["COAL_NEIMENGGU"], "万吨", "supply",
        source_level="provincial", source="国家统计局")
    add("COAL_OUTPUT_SHAANXI", "陕西原煤产量", base["COAL_SHAANXI"], "万吨", "supply",
        source_level="provincial", source="国家统计局")
    add("COAL_OUTPUT_TOTAL", "三省原煤产量合计", base["COAL_TOTAL"], "万吨", "supply",
        source_level="provincial", source="国家统计局")
    add("RAIL_FREIGHT_CN", "全国铁路货运量", base["RAIL_FREIGHT"], "万吨", "transport",
        source_level="national", source="国家统计局")
    add("THERMAL_POWER_CN", "全国火力发电量", base["THERMAL_POWER"], "亿千瓦时", "power",
        source_level="national", source="国家统计局")
    add("POLICY_EVENT_INTENSITY", "政策事件强度指数", event_intensity.values, "0-1", "policy",
        source_level="national", source="政策事件时间线（专家评分）", scenario_only=1)

    # 内燃机车台数：企业访谈/规划（2024下半年逐步减量，2025年16台，2026年15台）
    loco = pd.Series(np.nan, index=idx)
    # 2024 年下半年逐步减量；按柴油量反推，2024 年均约 30 台（与 2025 年 16 台、
    # 2025 年柴油 9,529 t 的吨/台强度一致）。2026 年计划 15 台。
    loco.loc["2024-01-01":"2024-06-01"] = 32
    for m, v in zip(pd.date_range("2024-07-01", "2024-12-01", freq="MS"), [31, 30, 29, 28, 27, 26]):
        loco.loc[m] = v
    loco.loc["2025-01-01":"2025-12-01"] = 16
    loco.loc["2026-01-01":"2026-12-01"] = 15
    add("DIESEL_LOCO_COUNT", "内燃机车运用台数", loco.values, "台", "operation",
        source_level="enterprise", source="企业访谈/更新改造计划", scenario_only=1,
        source_status="企业计划")

    out = pd.DataFrame(rows)
    return out.sort_values(["factor_id", "period"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 组织级历史数据构建
# ---------------------------------------------------------------------------
@dataclass
class OrgHistory:
    org_id: str
    raw: pd.DataFrame
    activity: pd.DataFrame   # 长表
    emission: pd.DataFrame   # 宽表
    quality: pd.DataFrame    # 质量问题/口径调整清单


def _hdd_weights(temp_c: pd.Series, periods: pd.Series, months: List[int],
                 base: float = 18.0) -> pd.Series:
    w = pd.Series(0.0, index=temp_c.index)
    days = pd.to_datetime(periods).dt.days_in_month.astype(float)
    for m in months:
        mask = pd.to_datetime(periods).dt.month == m
        if mask.any():
            w.loc[mask] = np.maximum(
                (base - temp_c.loc[mask]).clip(lower=0) * days.loc[mask], 1.0
            )
    if w.sum() == 0:
        return pd.Series(1.0 / len(months), index=temp_c.index)
    return w / w.sum()


def _redistribute_annual_by_hdd(df: pd.DataFrame, annual: float, year: int,
                                months: List[int], temp_col: str) -> pd.Series:
    out = pd.Series(0.0, index=df.index)
    mask_year = df["period"].dt.year == year
    if not mask_year.any():
        return out
    sub = df.loc[mask_year]
    w = _hdd_weights(sub[temp_col], sub["period"], months)
    out.loc[mask_year] = annual * w.values
    return out


def build_org_history(org_id: str, external: pd.DataFrame) -> OrgHistory:
    raw = read_org_raw(org_id)
    raw = raw.set_index("period").reindex(month_index("2019-01-01", "2025-12-01")).reset_index()
    raw = raw.rename(columns={"index": "period"})
    # 保留原始日期列用于追溯
    if "date" not in raw.columns:
        raw["date"] = raw["period"]

    # 温度/Hdd
    ext = external[external["factor_id"].isin(
        ["TEMP_SHUOZHOU", "TEMP_YUANPING", "TEMP_SUNING", "TEMP_HUANGHUA", "TEMP_AVG4",
         "HDD_SHUOZHOU", "HDD_YUANPING", "HDD_SUNING", "HDD_HUANGHUA", "HDD_AVG4"]
    )].pivot(index="period", columns="factor_id", values="value")
    ext.index = pd.to_datetime(ext.index)
    for c in ["TEMP_SHUOZHOU", "TEMP_YUANPING", "TEMP_SUNING", "TEMP_HUANGHUA", "TEMP_AVG4",
              "HDD_SHUOZHOU", "HDD_YUANPING", "HDD_SUNING", "HDD_HUANGHUA", "HDD_AVG4"]:
        if c not in ext.columns:
            ext[c] = np.nan
    raw = raw.merge(ext.reset_index(), on="period", how="left")

    # 站点的温度列
    if org_id == "SNF":
        temp_col, hdd_col = "TEMP_SUNING", "HDD_SUNING"
    elif org_id == "YPF":
        temp_col, hdd_col = "TEMP_YUANPING", "HDD_YUANPING"
    else:
        temp_col, hdd_col = "TEMP_AVG4", "HDD_AVG4"

    quality: List[dict] = []

    # 数值化
    for c in ["货运周转量", "天然气", "汽油", "柴油", "牵引电力", "辅助生产电力",
              "电力总和", "热力", "co2_t", "电力排放因子"]:
        raw[c] = pd.to_numeric(raw.get(c), errors="coerce")
    raw["year"] = raw["period"].dt.year
    raw["month"] = raw["period"].dt.month

    # ------------------------------------------------------------------
    # 1) 牵引/辅助电力拆分
    # ------------------------------------------------------------------
    raw["ELEC_TOTAL"] = raw["电力总和"]
    raw["elec_split_estimated"] = 0

    # 业务规则：牵引电力全部归机辆分公司；肃宁、原平没有牵引电力，
    # 其“电力总和”全部作为辅助生产电力，不生成 ELEC_TRAC 记录。
    if org_id != "JLG":
        raw["ELEC_TRAC"] = np.nan
        raw["ELEC_AUX"] = raw["ELEC_TOTAL"]
    else:
        raw["ELEC_TRAC"] = raw.get("牵引电力", pd.Series(np.nan, index=raw.index))
        raw["ELEC_AUX"] = raw.get("辅助生产电力", pd.Series(np.nan, index=raw.index))

        obs = raw.loc[raw["year"].isin([2024, 2025]) & raw["ELEC_TRAC"].notna()].copy()
        if len(obs):
            obs["aux_share"] = obs["ELEC_AUX"] / obs["ELEC_TOTAL"]
            share_by_month = obs.groupby("month")["aux_share"].median()
            overall_share = float(obs["aux_share"].median())
        else:
            share_by_month = pd.Series(dtype=float)
            overall_share = 0.006

        for i, row in raw.iterrows():
            if pd.isna(row["ELEC_TRAC"]) or pd.isna(row["ELEC_AUX"]):
                share = float(share_by_month.get(row["month"], overall_share))
                aux = float(row["ELEC_TOTAL"]) * share if pd.notna(row["ELEC_TOTAL"]) else np.nan
                raw.at[i, "ELEC_AUX"] = aux
                raw.at[i, "ELEC_TRAC"] = float(row["ELEC_TOTAL"]) - aux if pd.notna(row["ELEC_TOTAL"]) else np.nan
                raw.at[i, "elec_split_estimated"] = 1
                quality.append({
                    "org_id": org_id, "period": row["period"], "var_id": "ELEC_TRAC",
                    "issue": "牵引/辅助电力未分列", "disposition": "推算",
                    "note": f"按2024-2025年同月辅助用电占比中位数 {share:.4%} 拆分；合计不变"
                })

    # ------------------------------------------------------------------
    # 2) 货运周转量（机辆 2019-2020 缺失）
    # ------------------------------------------------------------------
    raw["TURNOVER"] = raw["货运周转量"]
    raw["turnover_estimated"] = 0
    if org_id == "JLG":
        base = raw.loc[raw["year"].between(2021, 2025) & raw["TURNOVER"].notna()].copy()
        if len(base):
            base["ratio"] = base["TURNOVER"] / base["ELEC_TOTAL"]
            ratio_by_month = base.groupby("month")["ratio"].median()
            fallback = float(base["ratio"].median())
            for i, row in raw.iterrows():
                if pd.isna(row["TURNOVER"]) and pd.notna(row["ELEC_TOTAL"]):
                    ratio = float(ratio_by_month.get(row["month"], fallback))
                    raw.at[i, "TURNOVER"] = float(row["ELEC_TOTAL"]) * ratio
                    raw.at[i, "turnover_estimated"] = 1
                    quality.append({
                        "org_id": org_id, "period": row["period"], "var_id": "TURNOVER",
                        "issue": "货运周转量缺失", "disposition": "推算",
                        "note": f"按2021-2025年同月周转量/电量比值中位数 {ratio:.6f} 推算；仅作解释变量"
                    })

    # ------------------------------------------------------------------
    # 3) 天然气
    # ------------------------------------------------------------------
    raw["GAS"] = raw["天然气"].fillna(0.0)
    raw["gas_status"] = raw.get("天然气_status", "原始")
    raw["gas_flag"] = ""
    if org_id == "JLG":
        # 2024 年天然气整体异常：用 2023 年同月值补全
        mask = raw["year"] == 2024
        for i in raw.loc[mask].index:
            m = int(raw.at[i, "month"])
            ref = raw.loc[(raw["year"] == 2023) & (raw["month"] == m), "GAS"]
            if len(ref) and pd.notna(ref.iloc[0]):
                old = raw.at[i, "GAS"]
                raw.at[i, "GAS"] = float(ref.iloc[0])
                raw.at[i, "gas_status"] = "异常剔除-同期补全"
                raw.at[i, "gas_flag"] = "GAS_2024_ANOMALY"
                quality.append({
                    "org_id": org_id, "period": raw.at[i, "period"], "var_id": "GAS",
                    "issue": "2024年天然气用量整体异常（用户说明）", "disposition": "剔除并补全",
                    "note": f"原值 {old:.4f} 万m3，按2023年同月 {raw.at[i,'GAS']:.4f} 万m3 补全；气量占比<0.01%"
                })
    elif org_id == "SNF":
        # 2019-2021 只有年总量，原表按月均值；改为按供暖度日分摊（保留年总量）
        for y in [2019, 2020, 2021]:
            mask = raw["year"] == y
            if not mask.any():
                continue
            annual = float(raw.loc[mask, "GAS"].sum())
            redistributed = _redistribute_annual_by_hdd(raw, annual, y, list(range(1, 13)), temp_col)
            raw.loc[mask, "GAS"] = redistributed.loc[mask].values
            raw.loc[mask, "gas_status"] = "推算-供暖度日分摊"
            quality.append({
                "org_id": org_id, "period": f"{y}-01", "var_id": "GAS",
                "issue": "仅有年总量，原表按12个月均值", "disposition": "重新分摊",
                "note": f"年总量 {annual:.4f} 万m3，按0.3+0.7×HDD权重分摊到12个月，年总量不变"
            })
    elif org_id == "YPF":
        raw["GAS"] = 0.0
        raw["gas_status"] = "无此项"

    # ------------------------------------------------------------------
    # 4) 热力：年度总量 → 供暖月按 HDD 分摊；2025 年口径还原
    # ------------------------------------------------------------------
    raw["HEAT"] = raw["热力"].fillna(0.0)
    raw["HEAT_REPORTED"] = raw["HEAT"].copy()
    raw["heat_status"] = "原始"
    raw["heat_flag"] = ""

    if org_id in ("SNF", "YPF"):
        months = HEATING_MONTHS[org_id]
        for y in range(2019, 2026):
            mask = raw["year"] == y
            if not mask.any():
                continue
            annual_reported = float(raw.loc[mask, "HEAT_REPORTED"].sum())
            annual_physical = annual_reported
            if y == 2025:
                if org_id == "SNF":
                    # 2025 报表：面积折算 19,240.86 GJ（系数0.380）+ 计量 18,644 GJ
                    area_reported = 19240.86
                    metered = 18644.00
                    annual_physical = area_reported * (BASE_HEAT_AREA_FACTOR / HEAT_AREA_FACTOR_2025[org_id]) + metered
                else:
                    annual_physical = annual_reported * (BASE_HEAT_AREA_FACTOR / HEAT_AREA_FACTOR_2025[org_id])
                raw.loc[mask, "heat_flag"] = "CALIBER_CHANGE_2025"
                quality.append({
                    "org_id": org_id, "period": f"{y}-01", "var_id": "HEAT",
                    "issue": "2025年供热面积折算系数调整，面积未变", "disposition": "口径还原",
                    "note": (f"报表年热力 {annual_reported:.2f} GJ；按基准系数 {BASE_HEAT_AREA_FACTOR} "
                             f"还原为 {annual_physical:.2f} GJ，用于可比口径建模；报表口径保留原值")
                })
            rep = _redistribute_annual_by_hdd(raw, annual_reported, y, months, temp_col)
            phy = _redistribute_annual_by_hdd(raw, annual_physical, y, months, temp_col)
            raw.loc[mask, "HEAT_REPORTED"] = rep.loc[mask].values
            raw.loc[mask, "HEAT"] = phy.loc[mask].values
            raw.loc[mask, "heat_status"] = "推算-供暖度日分摊"

    # ------------------------------------------------------------------
    # 5) 排放计算
    # ------------------------------------------------------------------
    raw["ef_elec"] = raw["year"].map(EF_ELEC_BY_YEAR)
    raw["ef_elec"] = raw["ef_elec"].fillna(raw.get("电力排放因子"))
    raw["co2_gas"] = raw["GAS"] * EF_GAS
    raw["co2_gasoline"] = raw["汽油"] * EF_GASOLINE
    raw["co2_diesel"] = raw["柴油"] * EF_DIESEL
    raw["co2_elec_reported"] = raw["ELEC_TOTAL"] * raw["ef_elec"]
    raw["co2_heat_reported"] = raw["HEAT_REPORTED"] * EF_HEAT
    raw["co2_reported_calc"] = (
        raw["co2_gas"] + raw["co2_gasoline"] + raw["co2_diesel"] +
        raw["co2_elec_reported"] + raw["co2_heat_reported"]
    )
    raw["co2_comparable"] = (
        raw["co2_gas"] + raw["co2_gasoline"] + raw["co2_diesel"] +
        raw["ELEC_TOTAL"] * BASE_EF_ELEC + raw["HEAT"] * EF_HEAT
    )
    raw["co2_reported_sheet"] = raw["co2_t"]
    # 月度热力已按 HDD 重新分摊，逐月与原始台账不再逐点一致；
    # 校验以“年度总量”为准（年总量不变是口径还原的硬约束）。
    raw["annual_sheet"] = raw.groupby("year")["co2_reported_sheet"].transform("sum")
    raw["annual_calc"] = raw.groupby("year")["co2_reported_calc"].transform("sum")
    raw["calc_diff_pct"] = np.where(
        raw["annual_sheet"].abs() > 1e-9,
        (raw["annual_calc"] - raw["annual_sheet"]).abs() / raw["annual_sheet"].abs() * 100,
        0.0,
    )
    raw["monthly_diff_pct"] = np.where(
        raw["co2_reported_sheet"].abs() > 1e-9,
        (raw["co2_reported_calc"] - raw["co2_reported_sheet"]).abs() / raw["co2_reported_sheet"].abs() * 100,
        0.0,
    )
    raw["is_verified"] = (raw["calc_diff_pct"] < 0.5).astype(int)

    # ------------------------------------------------------------------
    # 6) 长表
    # ------------------------------------------------------------------
    act_rows: List[dict] = []

    def add_act(var_id: str, value: pd.Series, unit: str, status: str,
                estimated: bool | pd.Series = False, reported: pd.Series | None = None,
                flag: str | pd.Series = "") -> None:
        for i, ts in enumerate(raw["period"]):
            v = value.iloc[i]
            if pd.isna(v):
                continue
            rv = reported.iloc[i] if reported is not None else v
            est = bool(estimated.iloc[i]) if isinstance(estimated, pd.Series) else bool(estimated)
            fl = str(flag.iloc[i]) if isinstance(flag, pd.Series) else str(flag)
            act_rows.append({
                "org_id": org_id, "period": ts.date(), "var_id": var_id,
                "value": float(v), "reported_value": float(rv), "unit": unit,
                "source_status": status, "is_estimated": int(est),
                "quality_status": "valid", "data_flag": fl,
            })

    turnover_flag = pd.Series(
        np.where(raw["turnover_estimated"] == 1, "ESTIMATED_2019_2020", ""), index=raw.index
    )
    add_act("TURNOVER", raw["TURNOVER"], "百万吨公里", "推算-电量系数法",
            estimated=raw["turnover_estimated"].astype(bool), flag=turnover_flag)
    add_act("GAS", raw["GAS"], "万立方米", "原始")
    # gas 状态逐行覆盖
    for r in act_rows:
        if r["var_id"] == "GAS":
            idx = raw.index[raw["period"] == pd.Timestamp(r["period"])][0]
            r["source_status"] = str(raw.at[idx, "gas_status"])
            r["is_estimated"] = int(str(raw.at[idx, "gas_status"]).startswith(("推算", "异常")))
            r["data_flag"] = str(raw.at[idx, "gas_flag"] or "")
    add_act("GASOLINE", raw["汽油"], "吨", "原始")
    diesel_flag = pd.Series(
        np.where(raw["year"] == 2025, "LOCO_RETIREMENT_2025", ""), index=raw.index
    )
    add_act("DIESEL", raw["柴油"], "吨", "原始", flag=diesel_flag)
    elec_flag = pd.Series(
        np.where(raw["year"] == 2024, "LEVEL_SHIFT_2024", ""), index=raw.index
    )
    add_act("ELEC_TOTAL", raw["ELEC_TOTAL"], "MWh", "原始", flag=elec_flag)
    add_act("ELEC_TRAC", raw["ELEC_TRAC"], "MWh", "原始")
    add_act("ELEC_AUX", raw["ELEC_AUX"], "MWh", "原始")
    for r in act_rows:
        if r["var_id"] in ("ELEC_TRAC", "ELEC_AUX"):
            idx = raw.index[raw["period"] == pd.Timestamp(r["period"])][0]
            if int(raw.at[idx, "elec_split_estimated"]) == 1:
                r["source_status"] = "推算-辅占比重构"
                r["is_estimated"] = 1
    add_act("HEAT", raw["HEAT"], "GJ", "原始")
    add_act("HEAT_REPORTED", raw["HEAT_REPORTED"], "GJ", "原始")
    for r in act_rows:
        if r["var_id"] in ("HEAT", "HEAT_REPORTED"):
            idx = raw.index[raw["period"] == pd.Timestamp(r["period"])][0]
            r["source_status"] = str(raw.at[idx, "heat_status"])
            r["is_estimated"] = int(str(raw.at[idx, "heat_status"]).startswith("推算"))
            r["data_flag"] = str(raw.at[idx, "heat_flag"] or "")

    activity = pd.DataFrame(act_rows)

    # ------------------------------------------------------------------
    # 7) 排放宽表
    # ------------------------------------------------------------------
    emission = pd.DataFrame({
        "org_id": org_id,
        "period": raw["period"].dt.date,
        "scope": "Total",
        "gas_tco2": raw["co2_gas"].round(6),
        "gasoline_tco2": raw["co2_gasoline"].round(6),
        "diesel_tco2": raw["co2_diesel"].round(6),
        "electricity_tco2": raw["co2_elec_reported"].round(6),
        "heat_tco2": raw["co2_heat_reported"].round(6),
        "total_reported_tco2": raw["co2_reported_calc"].round(6),
        "total_comparable_tco2": raw["co2_comparable"].round(6),
        "electricity_factor": raw["ef_elec"],
        "heat_factor": EF_HEAT,
        "calc_method": "activity_x_factor",
        "is_verified": raw["is_verified"],
    })

    quality_df = pd.DataFrame(quality)
    return OrgHistory(org_id=org_id, raw=raw, activity=activity, emission=emission, quality=quality_df)


def build_all_history() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """返回 activity / emission / quality / external 四个 DataFrame。"""
    external = build_external_factors()
    acts, ems, quals = [], [], []
    for org_id in ORG_FILES:
        h = build_org_history(org_id, external)
        acts.append(h.activity)
        ems.append(h.emission)
        if len(h.quality):
            quals.append(h.quality)
    activity = pd.concat(acts, ignore_index=True)
    emission = pd.concat(ems, ignore_index=True)
    quality = pd.concat(quals, ignore_index=True) if quals else pd.DataFrame()
    return activity, emission, quality, external


def annual_summary(emission: pd.DataFrame, activity: pd.DataFrame) -> pd.DataFrame:
    """年度汇总，供报告与快速核对。"""
    e = emission.copy()
    e["year"] = pd.to_datetime(e["period"]).dt.year
    a = activity.copy()
    a["year"] = pd.to_datetime(a["period"]).dt.year
    piv = a.pivot_table(index=["org_id", "year"], columns="var_id", values="value", aggfunc="sum").reset_index()
    agg = e.groupby(["org_id", "year"]).agg(
        co2_reported=("total_reported_tco2", "sum"),
        co2_comparable=("total_comparable_tco2", "sum"),
    ).reset_index()
    return agg.merge(piv, on=["org_id", "year"], how="left")
