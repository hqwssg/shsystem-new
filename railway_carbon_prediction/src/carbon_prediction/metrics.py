"""预测精度、区间覆盖率与 Diebold-Mariano 检验。"""
from __future__ import annotations

from typing import Dict

import numpy as np
from scipy.stats import norm


def _safe_div(a: float, b: float) -> float:
    return float(a / b) if abs(b) > 1e-12 else float("nan")


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def mape(y_true: np.ndarray, y_pred: np.ndarray, eps: float = 1.0) -> float:
    mask = np.abs(y_true) > eps
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def smape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = np.abs(y_true) + np.abs(y_pred)
    mask = denom > 1e-9
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(2 * np.abs(y_true[mask] - y_pred[mask]) / denom[mask]) * 100)


def r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 1e-12 else float("nan")


def mase(y_true: np.ndarray, y_pred: np.ndarray, y_train: np.ndarray, season: int = 12) -> float:
    """MASE = MAE_model / MAE_seasonal_naive(训练集内)。"""
    y_train = np.asarray(y_train, dtype=float)
    if len(y_train) > season:
        naive = np.mean(np.abs(y_train[season:] - y_train[:-season]))
    else:
        naive = np.mean(np.abs(np.diff(y_train))) if len(y_train) > 1 else np.nan
    if not np.isfinite(naive) or naive < 1e-12:
        return float("nan")
    return float(mae(y_true, y_pred) / naive)


def evaluate(y_true: np.ndarray, y_pred: np.ndarray, y_train: np.ndarray) -> Dict[str, float]:
    y_true = np.asarray(y_true, dtype=float).ravel()
    y_pred = np.asarray(y_pred, dtype=float).ravel()
    return {
        "MAE": round(mae(y_true, y_pred), 4),
        "RMSE": round(rmse(y_true, y_pred), 4),
        "MAPE": round(mape(y_true, y_pred), 4),
        "sMAPE": round(smape(y_true, y_pred), 4),
        "MASE": round(mase(y_true, y_pred, y_train), 4),
        "R2": round(r2(y_true, y_pred), 4),
        "Bias": round(float(np.mean(y_pred - y_true)), 4),
    }


def residual_interval(y_true: np.ndarray, y_pred: np.ndarray,
                      level: float = 0.90) -> Dict[str, float]:
    """基于相对残差分位数给出区间宽度（乘性）。"""
    y_true = np.asarray(y_true, dtype=float).ravel()
    y_pred = np.asarray(y_pred, dtype=float).ravel()
    mask = np.abs(y_true) > 1e-9
    rel = (y_true[mask] - y_pred[mask]) / y_true[mask]
    if len(rel) < 3:
        return {"q_low": -0.15, "q_high": 0.15}
    alpha = (1 - level) / 2
    return {
        "q_low": float(np.quantile(rel, alpha)),
        "q_high": float(np.quantile(rel, 1 - alpha)),
    }


def interval_bounds(point: np.ndarray, q_low: float, q_high: float) -> tuple[np.ndarray, np.ndarray]:
    point = np.asarray(point, dtype=float)
    lower = np.maximum(0.0, point * (1 + q_low))
    upper = np.maximum(0.0, point * (1 + q_high))
    return lower, upper


def coverage(y_true: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float).ravel()
    return float(np.mean((y_true >= lower.ravel()) & (y_true <= upper.ravel())))


def dm_test(y_true: np.ndarray, pred_a: np.ndarray, pred_b: np.ndarray,
            h: int = 12) -> Dict[str, float]:
    """Diebold-Mariano 检验（平方损失，Newey-West HAC，滞后 h-1）。"""
    y_true = np.asarray(y_true, dtype=float).ravel()
    ea = (y_true - np.asarray(pred_a, dtype=float).ravel()) ** 2
    eb = (y_true - np.asarray(pred_b, dtype=float).ravel()) ** 2
    d = ea - eb
    n = len(d)
    if n < 3:
        return {"DM": float("nan"), "p_value": float("nan")}
    mean_d = float(np.mean(d))
    gamma0 = float(np.mean((d - mean_d) ** 2))
    var = gamma0
    lag = max(1, h - 1)
    for k in range(1, min(lag, n - 1) + 1):
        gamma = float(np.mean((d[k:] - mean_d) * (d[:-k] - mean_d)))
        var += 2 * (1 - k / (lag + 1)) * gamma
    se = np.sqrt(max(var, 1e-12) / n)
    stat = mean_d / se if se > 0 else float("nan")
    p = float(2 * (1 - norm.cdf(abs(stat)))) if np.isfinite(stat) else float("nan")
    return {"DM": round(float(stat), 4), "p_value": round(p, 4)}
