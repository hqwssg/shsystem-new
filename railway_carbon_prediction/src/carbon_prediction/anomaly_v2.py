"""异常检测 V2：双通道孤立森林 + MAD 残差 z + CUSUM/池化断点 + 日历/多变量证据。

V2 在 V1 基础上落实六项改进：
1. 复核标签校准（弱标签，输出 precision/recall/F1 与推荐分位阈值）；
2. raw 与 STL 残差两棵独立孤立森林，双通道一致升级；
3. CUSUM + 池化统计量月度断点检测，替代 3 期均值；
4. 春节/疫情/检修日历哑变量（检修待企业填报，机制已预留）；
5. 电力/热力/柴油/天然气/周转量多变量联合检测；
6. “关注”级写入独立监控表，不进入复核队列。

说明：本模块不改变 V1 的 C1—C4 语义，只增强证据与分流。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.seasonal import STL

from . import db
from .config import settings

DETERMINISTIC_VARS = {"HEAT"}  # 热力由供热规则解释，统计检测误报高；V2 豁免
KEY_VARS = ["ELEC_TOTAL", "DIESEL", "GAS", "GASOLINE", "CO2_COMPARABLE"]
JOINT_VARS = ["ELEC_TOTAL", "DIESEL", "GAS", "GASOLINE", "TURNOVER"]
REVIEW_VARS = {"ELEC_TOTAL", "DIESEL", "GAS", "CO2_COMPARABLE"}  # 汽油量极小，只进监控
# 确定性热力序列的规则登记事件（不做统计检测，避免 27+ 误报）
HEAT_RULE_EVENTS = {
    "JLG": [("2023-01-01", "2023 年供热面积/档位调整，年热力 72,809→88,618 GJ")],
    "SNF": [("2023-11-01", "2023 年供热面积调整，年热力 49,687→63,618 GJ")],
    "YPF": [("2021-12-01", "2021 年供热面积调整，年热力 142,318→159,377 GJ")],
}
HEATING_MONTHS = {
    "JLG": [1, 2, 3, 4, 11, 12],
    "SNF": [1, 2, 3, 11, 12],
    "YPF": [1, 2, 3, 4, 11, 12],
}
TRANSITION_MONTHS = 3
BREAKPOINT_MIN_SEGMENT = 6
BREAKPOINT_MIN_STAT = 3.0
BREAKPOINT_MIN_SHIFT_PCT = 25.0
BREAKPOINT_CV_RATIO_MAX = 1.5
SEASONAL_BLOCK_SEGMENT = 6
SEASONAL_MAX_ABS_Z = 50.0
FOREST_QUANTILE = 0.95
EPS = 1e-9


# ---------------------------------------------------------------------------
# Schema / 日历
# ---------------------------------------------------------------------------
def ensure_schema() -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS prediction_anomaly_watch (
          id BIGINT NOT NULL AUTO_INCREMENT,
          org_id VARCHAR(16) NOT NULL,
          period DATE NOT NULL,
          var_id VARCHAR(32) NOT NULL,
          level VARCHAR(16) NOT NULL DEFAULT '关注',
          category VARCHAR(16) DEFAULT NULL,
          score DECIMAL(10,6) DEFAULT NULL,
          raw_score DECIMAL(10,6) DEFAULT NULL,
          resid_score DECIMAL(10,6) DEFAULT NULL,
          joint_score DECIMAL(10,6) DEFAULT NULL,
          channels VARCHAR(64) DEFAULT NULL,
          context_flags VARCHAR(128) DEFAULT NULL,
          evidence VARCHAR(1000) DEFAULT NULL,
          algorithm_version VARCHAR(16) NOT NULL DEFAULT 'v2',
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (id),
          UNIQUE KEY uk_org_period_var (org_id,period,var_id,algorithm_version),
          KEY idx_org_period (org_id,period)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='关注级异常监控（不进复核队列）'
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS prediction_anomaly_calibration (
          id BIGINT NOT NULL AUTO_INCREMENT,
          run_id VARCHAR(40) NOT NULL,
          org_id VARCHAR(16) NOT NULL,
          var_id VARCHAR(32) NOT NULL,
          quantile DECIMAL(6,4) NOT NULL,
          threshold_value DECIMAL(12,6) DEFAULT NULL,
          precision_v DECIMAL(8,4) DEFAULT NULL,
          recall_v DECIMAL(8,4) DEFAULT NULL,
          f1 DECIMAL(8,4) DEFAULT NULL,
          n_pos INT NOT NULL DEFAULT 0,
          n_neg INT NOT NULL DEFAULT 0,
          selected TINYINT(1) NOT NULL DEFAULT 0,
          note VARCHAR(512) DEFAULT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (id),
          UNIQUE KEY uk_run_org_var_q (run_id,org_id,var_id,quantile),
          KEY idx_org_var (org_id,var_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='异常阈值/污染率弱标签校准'
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS prediction_calendar_event (
          id BIGINT NOT NULL AUTO_INCREMENT,
          event_id VARCHAR(48) NOT NULL,
          event_type VARCHAR(32) NOT NULL,
          event_name VARCHAR(128) NOT NULL,
          start_date DATE NOT NULL,
          end_date DATE NOT NULL,
          org_id VARCHAR(16) NOT NULL DEFAULT 'ALL',
          impact_direction VARCHAR(16) DEFAULT 'unknown',
          source VARCHAR(512) DEFAULT NULL,
          note VARCHAR(512) DEFAULT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (id),
          UNIQUE KEY uk_event (event_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='节假日/疫情/检修日历事件'
    """)
    watch_cols = {r["COLUMN_NAME"].lower() for r in db.fetch_all(
        "SELECT COLUMN_NAME FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name='prediction_anomaly_watch'"
    )}
    if "category" not in watch_cols:
        db.execute("ALTER TABLE prediction_anomaly_watch ADD COLUMN category VARCHAR(16) DEFAULT NULL AFTER level")

    existing = {r["COLUMN_NAME"].lower() for r in db.fetch_all(
        "SELECT COLUMN_NAME FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name='prediction_anomaly'"
    )}
    cols = {
        "algorithm_version": "VARCHAR(16) NOT NULL DEFAULT 'v1'",
        "raw_score": "DECIMAL(10,6) DEFAULT NULL",
        "resid_score": "DECIMAL(10,6) DEFAULT NULL",
        "joint_score": "DECIMAL(10,6) DEFAULT NULL",
        "channels": "VARCHAR(64) DEFAULT NULL",
        "context_flags": "VARCHAR(128) DEFAULT NULL",
        "breakpoint_date": "DATE DEFAULT NULL",
        "breakpoint_stat": "DECIMAL(10,4) DEFAULT NULL",
        "shift_pct": "DECIMAL(10,4) DEFAULT NULL",
        "cv_ratio": "DECIMAL(10,4) DEFAULT NULL",
        "in_breakpoint_window": "TINYINT(1) NOT NULL DEFAULT 0",
    }
    for c, ddl in cols.items():
        if c not in existing:
            db.execute(f"ALTER TABLE prediction_anomaly ADD COLUMN `{c}` {ddl}")

    # 日历事件：春节/疫情；检修需企业填报，暂不硬编码
    cny = [
        ("2019-02-04", "2019-02-10"), ("2020-01-24", "2020-01-30"),
        ("2021-02-11", "2021-02-17"), ("2022-01-31", "2022-02-06"),
        ("2023-01-21", "2023-01-27"), ("2024-02-10", "2024-02-16"),
        ("2025-01-28", "2025-02-03"), ("2026-02-17", "2026-02-23"),
    ]
    for i, (s, e) in enumerate(cny, 1):
        db.execute(
            """INSERT INTO prediction_calendar_event
               (event_id,event_type,event_name,start_date,end_date,org_id,impact_direction,source,note)
               VALUES (%s,'spring_festival','春节假期',%s,%s,'ALL','down','国务院节假日安排',
                       '春节前后运量/用电通常回落，用于降低 C3 误报')
               ON DUPLICATE KEY UPDATE start_date=VALUES(start_date),end_date=VALUES(end_date)""",
            (f"CNY-{i}", s, e),
        )
    db.execute(
        """INSERT INTO prediction_calendar_event
           (event_id,event_type,event_name,start_date,end_date,org_id,impact_direction,source,note)
           VALUES ('COVID-2020','epidemic','新冠疫情初期',%s,%s,'ALL','down','公开公共卫生事件',
                   '2020年初需求冲击，用于解释电力/运量水平位移')
           ON DUPLICATE KEY UPDATE start_date=VALUES(start_date),end_date=VALUES(end_date)""",
        ("2020-01-01", "2020-04-30"),
    )


def load_calendar_flags() -> pd.DataFrame:
    rows = db.fetch_all("SELECT event_type,start_date,end_date,org_id FROM prediction_calendar_event")
    idx = pd.date_range("2019-01-01", "2026-12-01", freq="MS")
    out = pd.DataFrame(index=idx)
    out["CAL_SPRING_FESTIVAL"] = 0
    out["CAL_COVID"] = 0
    out["CAL_MAINTENANCE"] = 0
    month_start = pd.Series(idx, index=idx)
    month_end = pd.Series(idx + pd.offsets.MonthEnd(0), index=idx)
    for r in rows:
        et = str(r["event_type"])
        col = {"spring_festival": "CAL_SPRING_FESTIVAL", "epidemic": "CAL_COVID",
               "maintenance": "CAL_MAINTENANCE"}.get(et)
        if not col:
            continue
        # 事件与月份有交集即标记，不能只看月首日
        mask = (month_start <= pd.Timestamp(r["end_date"])) & (month_end >= pd.Timestamp(r["start_date"]))
        out.loc[mask.values, col] = 1
    return out.reset_index().rename(columns={"index": "period"})


def _context(row: pd.Series) -> str:
    names = []
    if int(row.get("CAL_SPRING_FESTIVAL", 0)):
        names.append("spring_festival")
    if int(row.get("CAL_COVID", 0)):
        names.append("covid")
    if int(row.get("CAL_MAINTENANCE", 0)):
        names.append("maintenance")
    return ",".join(names)


# ---------------------------------------------------------------------------
# 特征 / 双通道森林
# ---------------------------------------------------------------------------
def _stl_resid(y: np.ndarray) -> np.ndarray:
    s = pd.Series(y).interpolate(limit_direction="both")
    if len(s.dropna()) < 24:
        return np.zeros(len(y))
    try:
        return STL(s, period=12, robust=True).fit().resid.values
    except Exception:
        return np.zeros(len(y))


def _raw_features(y: np.ndarray, period: pd.Series, cal: pd.DataFrame) -> np.ndarray:
    s = pd.Series(y)
    df = pd.DataFrame({
        "value": s,
        "mom": s.pct_change().replace([np.inf, -np.inf], 0),
        "yoy": s.pct_change(12).replace([np.inf, -np.inf], 0),
        "roll_mean3": s.rolling(3, min_periods=1).mean(),
        "roll_std3": s.rolling(3, min_periods=1).std().fillna(0),
        "month_sin": np.sin(2 * np.pi * pd.to_datetime(period).dt.month / 12),
        "month_cos": np.cos(2 * np.pi * pd.to_datetime(period).dt.month / 12),
    })
    for c in ["CAL_SPRING_FESTIVAL", "CAL_COVID", "CAL_MAINTENANCE"]:
        df[c] = cal[c].values
    return df.fillna(0).values


def _resid_features(resid: np.ndarray, period: pd.Series, cal: pd.DataFrame) -> np.ndarray:
    r = pd.Series(resid)
    scale = 1.4826 * np.median(np.abs(r - np.median(r)))
    scale = float(scale) if scale > EPS else float(r.std()) or 1.0
    df = pd.DataFrame({
        "resid": r,
        "resid_z": (r - r.median()) / scale,
        "abs_resid_z": np.abs((r - r.median()) / scale),
        "resid_roll_std3": r.rolling(3, min_periods=1).std().fillna(0),
        "month_sin": np.sin(2 * np.pi * pd.to_datetime(period).dt.month / 12),
        "month_cos": np.cos(2 * np.pi * pd.to_datetime(period).dt.month / 12),
    })
    for c in ["CAL_SPRING_FESTIVAL", "CAL_COVID", "CAL_MAINTENANCE"]:
        df[c] = cal[c].values
    return df.fillna(0).values


def _iforest(X: np.ndarray, seed: int, contamination: float = 0.05):
    Xs = StandardScaler().fit_transform(X)
    model = IsolationForest(
        n_estimators=200, max_samples="auto", contamination=contamination,
        random_state=seed, n_jobs=1,
    )
    model.fit(Xs)
    scores = -model.score_samples(Xs)
    decisions = model.decision_function(Xs)
    pct = pd.Series(scores).rank(pct=True).values * 100
    return scores, decisions, pct


# ---------------------------------------------------------------------------
# 断点：CUSUM + 池化统计量
# ---------------------------------------------------------------------------
def detect_breakpoint(y: np.ndarray) -> Dict:
    y = np.asarray(y, dtype=float)
    n = len(y)
    empty = {"detected": False, "index": None, "date": None, "stat": 0.0,
             "shift_pct": 0.0, "cv_ratio": 0.0, "pre_mean": np.nan,
             "post_mean": np.nan, "post_is_zero": False}
    if n < 2 * BREAKPOINT_MIN_SEGMENT:
        return empty
    best = None
    for t in range(BREAKPOINT_MIN_SEGMENT, n - BREAKPOINT_MIN_SEGMENT + 1):
        left, right = y[:t], y[t:]
        n1, n2 = len(left), len(right)
        v1, v2 = float(np.var(left, ddof=1)), float(np.var(right, ddof=1))
        pooled = np.sqrt(max(((n1 - 1) * v1 + (n2 - 1) * v2) / (n - 2), EPS))
        m1, m2 = float(np.mean(left)), float(np.mean(right))
        stat = abs(m2 - m1) / pooled * np.sqrt(n1 * n2 / n)
        shift = (m2 - m1) / max(abs(m1), EPS) * 100
        cv1 = float(np.std(left, ddof=1) / abs(m1)) if abs(m1) > EPS else np.inf
        post_zero = abs(m2) < 1e-9
        cv2 = 0.0 if post_zero else (float(np.std(right, ddof=1) / abs(m2)) if abs(m2) > EPS else np.inf)
        if best is None or stat > best["stat"]:
            best = {"index": t, "stat": stat, "shift_pct": shift,
                    "pre_mean": m1, "post_mean": m2, "cv1": cv1, "cv2": cv2,
                    "post_is_zero": post_zero}
    if best is None:
        return empty
    detected = (
        best["stat"] >= BREAKPOINT_MIN_STAT
        and abs(best["shift_pct"]) >= BREAKPOINT_MIN_SHIFT_PCT
        and (best["post_is_zero"] or best["cv2"] <= best["cv1"] * BREAKPOINT_CV_RATIO_MAX)
    )
    best.update({"detected": bool(detected), "cv_ratio": best["cv2"] / best["cv1"] if best["cv1"] not in (0, np.inf) else np.nan})
    return best


def _segment_len(z: np.ndarray, i: int, threshold: float = 3.0) -> int:
    lo = i
    while lo > 0 and abs(z[lo - 1]) > threshold:
        lo -= 1
    hi = i
    while hi < len(z) - 1 and abs(z[hi + 1]) > threshold:
        hi += 1
    return hi - lo + 1


def _recurrence(period: pd.Series, z: np.ndarray, i: int) -> int:
    month = pd.Timestamp(period.iloc[i]).month
    sign = np.sign(z[i])
    years = set()
    for j in range(len(z)):
        if j == i:
            continue
        if pd.Timestamp(period.iloc[j]).month == month and np.sign(z[j]) == sign and abs(z[j]) > 3:
            years.add(pd.Timestamp(period.iloc[j]).year)
    return len(years)


# ---------------------------------------------------------------------------
# 多变量联合
# ---------------------------------------------------------------------------
def _joint_flags(org_id: str, activity: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    sub = activity[activity["org_id"] == org_id]
    wide = sub.pivot_table(index="period", columns="var_id", values="value", aggfunc="last")
    cols = [c for c in JOINT_VARS if c in wide.columns]
    if len(cols) < 2:
        return pd.DataFrame(columns=["period", "joint_score", "joint_pct", "joint_flag"])
    X = wide[cols].astype(float).ffill().bfill()
    Z = (X - X.mean()) / X.std().replace(0, 1)
    Z["month_sin"] = np.sin(2 * np.pi * pd.to_datetime(Z.index).month / 12)
    Z["month_cos"] = np.cos(2 * np.pi * pd.to_datetime(Z.index).month / 12)
    scores, _, pct = _iforest(Z.values, settings.seed, 0.05)
    return pd.DataFrame({
        "period": Z.index, "joint_score": scores, "joint_pct": pct,
        "joint_flag": pct >= FOREST_QUANTILE * 100,
    })


# ---------------------------------------------------------------------------
# 单序列检测
# ---------------------------------------------------------------------------
def detect_series_v2(org_id: str, var_id: str, y: np.ndarray, period: pd.Series,
                     cal: pd.DataFrame, joint: pd.DataFrame) -> List[dict]:
    if var_id in DETERMINISTIC_VARS or len(y) < 24:
        return []
    resid = _stl_resid(y)
    med = float(np.median(resid))
    mad = float(1.4826 * np.median(np.abs(resid - med)))
    scale = mad if mad > EPS else float(np.std(resid)) or 1.0
    z = (resid - med) / scale
    raw_s, raw_d, raw_pct = _iforest(_raw_features(y, period, cal), settings.seed, 0.05)
    res_s, res_d, res_pct = _iforest(_resid_features(resid, period, cal), settings.seed, 0.05)
    bp = detect_breakpoint(y)
    joint_map = {pd.Timestamp(r.period): r for r in joint.itertuples(index=False)} if len(joint) else {}
    out = []
    for i in range(len(y)):
        ts = pd.Timestamp(period.iloc[i])
        j = joint_map.get(ts)
        joint_score = float(j.joint_score) if j is not None else np.nan
        joint_flag = bool(j.joint_flag) if j is not None else False
        raw_flag = raw_pct[i] >= FOREST_QUANTILE * 100
        res_flag = res_pct[i] >= FOREST_QUANTILE * 100
        both = raw_flag and res_flag
        # 联合通道只做佐证，不单独产出异常；避免 z≈0 的联合噪声进入监控表
        if not (raw_flag or res_flag or abs(z[i]) > 3):
            continue
        seg = _segment_len(z, i)
        recur = _recurrence(period, z, i)
        in_bp = bool(bp["detected"] and bp["index"] is not None
                     and bp["index"] <= i < bp["index"] + TRANSITION_MONTHS)
        seasonal = raw_flag and not res_flag and seg < SEASONAL_BLOCK_SEGMENT and abs(z[i]) <= SEASONAL_MAX_ABS_Z
        ctx = _context(cal.iloc[i])
        zero_exit = bool(in_bp and bp.get("post_is_zero"))

        if in_bp:
            category, conf = ("C3", 0.75) if zero_exit else ("C3", 0.72)
            subtype = "zero_exit" if zero_exit else "persist"
            note = ("断点后归零，C3 zero_exit" if zero_exit
                    else f"月度断点统计量 {bp['stat']:.2f}，位移 {bp['shift_pct']:.2f}%，后段CV比 {bp.get('cv_ratio', float('nan')):.2f}")
        elif seasonal or (recur >= 2 and abs(z[i]) > 3 and seg < SEASONAL_BLOCK_SEGMENT):
            category, conf, subtype = "C4", 0.65, ""
            note = "季节可解释或同月同向跨年复现"
        elif seg >= SEASONAL_BLOCK_SEGMENT:
            category, conf, subtype = "C2", 0.60, ""
            note = f"连续 {seg} 个月离群，疑似数据质量台阶"
        elif abs(z[i]) > 3 and seg <= 1:
            category, conf, subtype = "C1", 0.78, ""
            note = "单点尖峰，次期回落"
        elif abs(z[i]) > 3:
            category, conf, subtype = "C2", 0.60, ""
            note = f"连续 {seg} 个月同向漂移"
        else:
            category, conf, subtype = "UNDETERMINED", 0.45, ""
            note = "统计异常，业务证据不足"

        # 日历事件解释的 C1 不判为录入错误，降为 C2/数据质量并保留证据
        if ctx and category == "C1":
            category, conf = "C2", 0.60
            note += f"；日历事件（{ctx}）可解释，不判为录入错误"

        score = float(max(raw_s[i], res_s[i]))
        if category == "C4":
            level = "关注"
        elif both and (score >= 0.65 or abs(z[i]) >= 5):
            level = "严重异常"
        elif both or (joint_flag and (raw_flag or res_flag)) or abs(z[i]) >= 5:
            level = "异常"
        else:
            level = "关注"

        channels = "+".join([c for c, f in [("raw", raw_flag), ("resid", res_flag), ("joint", joint_flag)] if f])
        out.append({
            "org_id": org_id, "period": ts.date(), "var_id": var_id,
            "level": level, "category": category, "confidence": conf,
            "value": float(y[i]), "reference_value": float(np.median(y)),
            "score": round(score, 6), "raw_score": round(float(raw_s[i]), 6),
            "resid_score": round(float(res_s[i]), 6),
            "joint_score": round(joint_score, 6) if np.isfinite(joint_score) else None,
            "channels": channels or "resid",
            "context_flags": ctx,
            "both": bool(both), "joint_flag": bool(joint_flag),
            "z": round(float(z[i]), 4),
            "seg_len": seg, "recurrence": recur,
            "breakpoint_detected": bool(bp["detected"]),
            "breakpoint_date": (period.iloc[bp["index"]].date() if bp["detected"] else None),
            "breakpoint_stat": round(float(bp["stat"]), 4) if bp["detected"] else None,
            "shift_pct": round(float(bp["shift_pct"]), 4) if bp["detected"] else None,
            "cv_ratio": (round(float(bp["cv_ratio"]), 4)
                         if bp["detected"] and bp.get("cv_ratio") is not None
                         and np.isfinite(bp.get("cv_ratio", np.nan)) else None),
            "in_breakpoint_window": int(in_bp),
            "subtype": subtype,
            "evidence": f"{note}；z={z[i]:.2f}，连续段={seg}，复现={recur}；通道={channels or 'resid'}；上下文={ctx or '无'}",
        })
    return out


# ---------------------------------------------------------------------------
# 批量检测
# ---------------------------------------------------------------------------
def _is_reviewable(r: dict) -> bool:
    """进入复核队列的准入：控制噪声，同时保留关键异常。"""
    if r.get("channels") == "rule":
        return True  # 确定性序列的规则登记事件（如热力档位调整）
    if r["var_id"] not in REVIEW_VARS:
        return False
    if r["category"] == "C4":
        return False
    if r["category"] == "C3":
        return True
    # 日历事件可解释的短段异常进监控，不占用人工复核队列
    if r.get("context_flags") and r["category"] in ("C1", "C2", "UNDETERMINED") \
            and int(r.get("seg_len", 1)) < 6:
        return False
    if r["var_id"] == "GAS":
        # 天然气量级极小，只保留“严重且长段”的台阶/退出
        return r["category"] == "C2" and r["level"] == "严重异常" and int(r.get("seg_len", 0)) >= 6
    if r["category"] == "UNDETERMINED":
        return r["level"] == "严重异常"
    if r["level"] == "严重异常":
        return True
    return bool(r.get("both")) and abs(float(r.get("z", 0))) >= 5


def _consolidate(rows: List[dict]) -> List[dict]:
    """把连续同类异常合并为一条，避免整年台阶刷屏。"""
    if not rows:
        return []
    df = pd.DataFrame(rows)
    df["period"] = pd.to_datetime(df["period"])
    out: List[dict] = []
    for _, g in df.groupby(["org_id", "var_id", "category"]):
        g = g.sort_values("period")
        seg, prev = [], None
        groups = []
        for _, r in g.iterrows():
            if prev is None or (r["period"].to_period("M") - prev.to_period("M")).n == 1:
                seg.append(r)
            else:
                groups.append(seg); seg = [r]
            prev = r["period"]
        if seg:
            groups.append(seg)
        for seg_rows in groups:
            seg_df = pd.DataFrame(seg_rows)
            best = seg_df.loc[seg_df["score"].idxmax()].to_dict()
            best["seg_len"] = len(seg_df)
            best["evidence"] = str(best.get("evidence", "")) + f"；合并连续{len(seg_df)}个同类点"
            out.append(best)
    return out


def detect_history_v2(activity: pd.DataFrame) -> Tuple[List[dict], List[dict]]:
    cal = load_calendar_flags()
    anomalies, watch = [], []
    batch_id = f"ANOM-V2-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    for org_id, org_df in activity.groupby("org_id"):
        joint = _joint_flags(org_id, org_df, cal)
        raw_rows: List[dict] = []
        for var_id in KEY_VARS:
            sub = org_df[org_df["var_id"] == var_id].sort_values("period")
            if len(sub) < 24:
                continue
            y = pd.to_numeric(sub["value"], errors="coerce").interpolate(limit_direction="both").values
            period = pd.to_datetime(sub["period"]).reset_index(drop=True)
            cal_sub = cal.set_index("period").reindex(period).reset_index().fillna(0)
            raw_rows.extend(detect_series_v2(org_id, var_id, y, period, cal_sub, joint))
        # 规则登记：确定性热力事件
        for ts, note in HEAT_RULE_EVENTS.get(org_id, []):
            raw_rows.append({
                "org_id": org_id, "period": pd.Timestamp(ts).date(), "var_id": "HEAT",
                "level": "严重异常", "category": "C3", "confidence": 0.80,
                "score": 0.0, "raw_score": 0.0, "resid_score": 0.0, "joint_score": None,
                "channels": "rule", "context_flags": "", "both": False, "joint_flag": False,
                "z": 0.0, "seg_len": 1, "recurrence": 0,
                "breakpoint_detected": True, "breakpoint_date": pd.Timestamp(ts).date(),
                "breakpoint_stat": None, "shift_pct": None, "cv_ratio": None,
                "in_breakpoint_window": 1, "subtype": "persist",
                "evidence": f"确定性热力序列规则登记：{note}；不做统计检测",
            })
        for r in _consolidate(raw_rows):
            r["detect_batch_id"] = batch_id
            r["algorithm_version"] = "v2"
            if _is_reviewable(r):
                r["status"] = "auto_closed"
                r["suggested_disposition"] = "mark_breakpoint" if r["category"] in ("C2", "C3") else "keep"
                r["final_disposition"] = r["suggested_disposition"]
                r["reviewer"] = "system"
                r["reviewed_at"] = datetime.now()
                r["review_note"] = "V2 历史自动筛查，按规则保留/标记结构断点"
                anomalies.append(r)
            else:
                watch.append(r)
    return anomalies, watch


# ---------------------------------------------------------------------------
# 新增单点
# ---------------------------------------------------------------------------
def detect_new_point_v2(org_id: str, var_id: str, period: str, value: float,
                        history: pd.Series, history_period: pd.Series,
                        cal: Optional[pd.DataFrame] = None) -> Optional[dict]:
    y = pd.to_numeric(history, errors="coerce").astype(float).reset_index(drop=True)
    p = pd.Series(pd.to_datetime(history_period)).reset_index(drop=True)
    if len(y) < 18:
        return None
    month = pd.Timestamp(period).month
    same = y[p.dt.month == month]
    base = same if len(same) >= 3 else y.tail(24)
    med = float(base.median())
    mad = float(1.4826 * (base - med).abs().median())
    sigma = mad if mad > EPS else float(base.std()) or 1.0
    z = (value - med) / sigma
    outside = value > float(y.max()) * 1.2 or value < max(0.0, float(y.min()) * 0.8)
    if abs(z) <= 2.5 and not outside:
        return None
    level = "严重异常" if abs(z) > 5 else ("异常" if abs(z) > 3 or outside else "关注")
    return {
        "org_id": org_id, "period": period, "var_id": var_id,
        "level": level, "category": "UNDETERMINED" if level != "关注" else "UNDETERMINED",
        "confidence": 0.5, "score": round(min(1.0, abs(z) / 10), 6),
        "raw_score": None, "resid_score": None, "joint_score": None,
        "channels": "raw", "context_flags": "",
        "evidence": f"同月稳健 z={z:.2f}；同月中位数={med:.2f}；超出历史区间={outside}",
        "algorithm_version": "v2", "z": round(z, 4), "seg_len": 1, "recurrence": 0,
        "breakpoint_detected": False, "breakpoint_date": None, "breakpoint_stat": None,
        "shift_pct": None, "cv_ratio": None, "in_breakpoint_window": 0,
        "subtype": "",
    }


# ---------------------------------------------------------------------------
# 弱标签校准
# ---------------------------------------------------------------------------
def calibrate_from_v1(activity: pd.DataFrame, v1_rows: List[dict],
                      run_id: str) -> pd.DataFrame:
    """用 V1 复核/规则结果做弱标签，评估不同分位阈值的 F1。

    正样本：V1 中 level=异常/严重异常 且 category∈C1/C2/C3；
    负样本：其余月份。仅作治理参考，不宣称 ground truth。
    """
    cal = load_calendar_flags()
    rows = []
    v1 = pd.DataFrame(v1_rows)
    for org_id, org_df in activity.groupby("org_id"):
        joint = _joint_flags(org_id, org_df, cal)
        for var_id in KEY_VARS:
            if var_id in DETERMINISTIC_VARS:
                continue
            sub = org_df[org_df["var_id"] == var_id].sort_values("period")
            if len(sub) < 24:
                continue
            y = pd.to_numeric(sub["value"], errors="coerce").interpolate(limit_direction="both").values
            period = pd.to_datetime(sub["period"]).reset_index(drop=True)
            cal_sub = cal.set_index("period").reindex(period).reset_index().fillna(0)
            resid = _stl_resid(y)
            raw_s, _, _ = _iforest(_raw_features(y, period, cal_sub), settings.seed, 0.05)
            res_s, _, _ = _iforest(_resid_features(resid, period, cal_sub), settings.seed, 0.05)
            score = np.maximum(raw_s, res_s)
            pos = set()
            if not v1.empty:
                m = v1[(v1["org_id"] == org_id) & (v1["var_id"] == var_id) &
                       (v1["level"].isin(["异常", "严重异常"])) &
                       (v1["category"].isin(["C1", "C2", "C3"]))]
                pos = {pd.Timestamp(x).date() for x in m["period"]}
            labels = np.array([1 if d.date() in pos else 0 for d in period])
            n_pos, n_neg = int(labels.sum()), int((1 - labels).sum())
            if n_pos < 2 or n_neg < 10:
                continue
            best = None
            for q in [0.90, 0.92, 0.95, 0.97, 0.98, 0.99]:
                thr = float(np.quantile(score, q))
                pred = score >= thr
                tp = int(((pred == 1) & (labels == 1)).sum())
                fp = int(((pred == 1) & (labels == 0)).sum())
                fn = int(((pred == 0) & (labels == 1)).sum())
                prec = tp / (tp + fp) if tp + fp else 0.0
                rec = tp / (tp + fn) if tp + fn else 0.0
                f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
                rec_row = {"run_id": run_id, "org_id": org_id, "var_id": var_id,
                           "quantile": q, "threshold_value": round(thr, 6),
                           "precision_v": round(prec, 4), "recall_v": round(rec, 4),
                           "f1": round(f1, 4), "n_pos": n_pos, "n_neg": n_neg,
                           "selected": 0, "note": "弱标签校准，非ground truth"}
                rows.append(rec_row)
                if best is None or f1 > best["f1"]:
                    best = rec_row
            if best:
                for r in rows:
                    if (r["run_id"] == run_id and r["org_id"] == org_id and r["var_id"] == var_id
                            and r["quantile"] == best["quantile"]):
                        r["selected"] = 1
    return pd.DataFrame(rows)
