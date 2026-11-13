"""滑动窗口构造、时序划分与标准化。

关键约束：
- 先划分，后 fit scaler；scaler 只在训练段 fit。
- 验证/测试段只 transform。
- 窗口不得跨越训练/验证边界。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np
from sklearn.preprocessing import MinMaxScaler, StandardScaler


@dataclass
class WindowSet:
    X: np.ndarray      # (n, W, F)
    y: np.ndarray      # (n, H)
    origins: np.ndarray  # 每个窗口最后一个输入点的索引
    target_start: np.ndarray


def build_windows(y: np.ndarray, X: np.ndarray, W: int, H: int) -> WindowSet:
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    n = len(y)
    if n < W + H:
        raise ValueError(f"样本不足：N={n}, W={W}, H={H}")
    count = n - W - H + 1
    Xw = np.stack([X[t:t + W] for t in range(count)], axis=0)
    yw = np.stack([y[t + W:t + W + H] for t in range(count)], axis=0)
    origins = np.arange(W - 1, W - 1 + count)
    target_start = np.arange(W, W + count)
    return WindowSet(Xw, yw, origins, target_start)


def train_val_windows(y: np.ndarray, X: np.ndarray, W: int, H: int,
                      train_end: int, val_end: int) -> Tuple[WindowSet, WindowSet]:
    """train_end/val_end 为 exclusive 索引。

    训练窗口：目标期完全落在 [0, train_end)
    验证窗口：目标期完全落在 [train_end, val_end)，且输入窗口不早于 train_end-W+1
    """
    ws = build_windows(y[:val_end], X[:val_end], W, H)
    target_end = ws.target_start + H
    train_mask = target_end <= train_end
    val_mask = (ws.target_start >= train_end) & (target_end <= val_end)
    train = WindowSet(ws.X[train_mask], ws.y[train_mask], ws.origins[train_mask], ws.target_start[train_mask])
    val = WindowSet(ws.X[val_mask], ws.y[val_mask], ws.origins[val_mask], ws.target_start[val_mask])
    return train, val


class Scaler:
    """特征 StandardScaler + 目标 MinMaxScaler。

    特征用 StandardScaler 而非 MinMax，原因是趋势项在 2026 年会超出训练期
    min/max，MinMax 会把未来趋势截断；Standard 允许线性外推。
    """

    def __init__(self):
        self.x_scaler = StandardScaler()
        self.y_scaler = MinMaxScaler()

    def fit(self, X: np.ndarray, y: np.ndarray) -> "Scaler":
        n, W, F = X.shape
        self.x_scaler.fit(X.reshape(-1, F))
        self.y_scaler.fit(y.reshape(-1, 1))
        return self

    def transform_X(self, X: np.ndarray) -> np.ndarray:
        n, W, F = X.shape
        return self.x_scaler.transform(X.reshape(-1, F)).reshape(n, W, F)

    def transform_y(self, y: np.ndarray) -> np.ndarray:
        return self.y_scaler.transform(y.reshape(-1, 1)).reshape(y.shape)

    def inverse_y(self, y: np.ndarray) -> np.ndarray:
        shape = y.shape
        return self.y_scaler.inverse_transform(y.reshape(-1, 1)).reshape(shape)

    def state(self) -> dict:
        return {
            "x_mean": self.x_scaler.mean_.tolist(),
            "x_scale": self.x_scaler.scale_.tolist(),
            "x_var": self.x_scaler.var_.tolist(),
            "y_min": float(self.y_scaler.min_[0]),
            "y_scale": float(self.y_scaler.scale_[0]),
            "y_data_min": float(self.y_scaler.data_min_[0]),
            "y_data_max": float(self.y_scaler.data_max_[0]),
        }

    @classmethod
    def from_state(cls, state: dict) -> "Scaler":
        s = cls()
        s.x_scaler.mean_ = np.asarray(state["x_mean"], dtype=float)
        s.x_scaler.scale_ = np.asarray(state["x_scale"], dtype=float)
        s.x_scaler.var_ = np.asarray(state["x_var"], dtype=float)
        s.x_scaler.n_features_in_ = len(state["x_mean"])
        s.y_scaler.min_ = np.asarray([state["y_min"]], dtype=float)
        s.y_scaler.scale_ = np.asarray([state["y_scale"]], dtype=float)
        s.y_scaler.data_min_ = np.asarray([state["y_data_min"]], dtype=float)
        s.y_scaler.data_max_ = np.asarray([state["y_data_max"]], dtype=float)
        s.y_scaler.n_features_in_ = 1
        return s


def flatten_windows(X: np.ndarray) -> np.ndarray:
    """供 Ridge/GBM 使用的二维特征：末值、均值、标准差、斜率。"""
    last = X[:, -1, :]
    mean = X.mean(axis=1)
    std = X.std(axis=1)
    slope = X[:, -1, :] - X[:, 0, :]
    return np.concatenate([last, mean, std, slope], axis=1)
