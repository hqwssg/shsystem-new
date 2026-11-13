"""预测模型集合。

主模型：SW-LSTM（滑动窗口 + 直接多步）
对照/降级：Ridge、HistGradientBoosting、Holt-Winters、Seasonal Naive

所有模型统一接口：
    fit(X_train, y_train, X_val=None, y_val=None)
    predict(X, y_context=None, periods=None) -> (n, H)
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.multioutput import MultiOutputRegressor
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from .dataset import Scaler, flatten_windows
from .metrics import evaluate


# ---------------------------------------------------------------------------
# 1. SW-LSTM
# ---------------------------------------------------------------------------
class SWLSTM(nn.Module):
    def __init__(self, input_size: int, hidden: int = 32, horizon: int = 12,
                 dropout: float = 0.2):
        super().__init__()
        self.input_size = input_size
        self.hidden = hidden
        self.horizon = horizon
        self.dropout = dropout
        self.lstm = nn.LSTM(input_size=input_size, hidden_size=hidden, batch_first=True)
        self.head = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(hidden, max(8, hidden // 2)),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(max(8, hidden // 2), horizon),
        )
        self._init_forget_bias()

    def _init_forget_bias(self) -> None:
        for name, param in self.lstm.named_parameters():
            if "bias" in name:
                n = param.shape[0]
                param.data[n // 4:n // 2].fill_(1.0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        last = out[:, -1, :]
        return self.head(last)


@dataclass
class LSTMForecaster:
    input_size: int
    hidden: int = 32
    horizon: int = 12
    dropout: float = 0.2
    lr: float = 1e-3
    epochs: int = 220
    patience: int = 25
    batch_size: int = 16
    seed: int = 20260928
    name: str = field(default="SW_LSTM", init=False)
    model: Optional[SWLSTM] = None
    best_epoch: int = 0
    train_loss: float = float("nan")
    val_loss: float = float("nan")

    def fit(self, X_train: np.ndarray, y_train: np.ndarray,
            X_val: Optional[np.ndarray] = None, y_val: Optional[np.ndarray] = None) -> "LSTMForecaster":
        torch.manual_seed(self.seed)
        np.random.seed(self.seed)
        self.model = SWLSTM(self.input_size, self.hidden, self.horizon, self.dropout)
        opt = torch.optim.Adam(self.model.parameters(), lr=self.lr, weight_decay=1e-4)
        loss_fn = nn.MSELoss()

        Xt = torch.tensor(X_train, dtype=torch.float32)
        yt = torch.tensor(y_train, dtype=torch.float32)
        ds = torch.utils.data.TensorDataset(Xt, yt)
        dl = torch.utils.data.DataLoader(ds, batch_size=min(self.batch_size, len(ds)), shuffle=True)

        Xv = torch.tensor(X_val, dtype=torch.float32) if X_val is not None and len(X_val) else None
        yv = torch.tensor(y_val, dtype=torch.float32) if y_val is not None and len(y_val) else None

        best_state = None
        best_val = float("inf")
        best_epoch = 0
        wait = 0
        last_train = float("nan")
        for epoch in range(1, self.epochs + 1):
            self.model.train()
            epoch_losses = []
            for xb, yb in dl:
                opt.zero_grad()
                pred = self.model(xb)
                loss = loss_fn(pred, yb)
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                opt.step()
                epoch_losses.append(float(loss.detach()))
            last_train = float(np.mean(epoch_losses)) if epoch_losses else float("nan")

            if Xv is not None and yv is not None:
                self.model.eval()
                with torch.no_grad():
                    val_pred = self.model(Xv)
                    val_loss = float(loss_fn(val_pred, yv).detach())
                if val_loss < best_val - 1e-7:
                    best_val = val_loss
                    best_epoch = epoch
                    best_state = {k: v.detach().clone() for k, v in self.model.state_dict().items()}
                    wait = 0
                else:
                    wait += 1
                    if wait >= self.patience:
                        break
            else:
                best_epoch = epoch
        if best_state is not None:
            self.model.load_state_dict(best_state)
        self.best_epoch = best_epoch or self.epochs
        self.train_loss = last_train
        self.val_loss = best_val if best_state is not None else float("nan")
        return self

    def predict(self, X: np.ndarray, y_context=None, periods=None) -> np.ndarray:
        self.model.eval()
        with torch.no_grad():
            pred = self.model(torch.tensor(X, dtype=torch.float32)).numpy()
        return pred

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        torch.save({
            "state_dict": self.model.state_dict(),
            "config": {
                "input_size": self.input_size, "hidden": self.hidden,
                "horizon": self.horizon, "dropout": self.dropout,
                "lr": self.lr, "epochs": self.epochs, "patience": self.patience,
                "batch_size": self.batch_size, "seed": self.seed,
                "best_epoch": self.best_epoch,
            },
        }, directory / "model.pt")

    @classmethod
    def load(cls, directory: Path) -> "LSTMForecaster":
        obj = torch.load(directory / "model.pt", map_location="cpu", weights_only=False)
        cfg = obj["config"]
        f = cls(
            input_size=cfg["input_size"], hidden=cfg["hidden"], horizon=cfg["horizon"],
            dropout=cfg["dropout"], lr=cfg["lr"], epochs=cfg["epochs"],
            patience=cfg["patience"], batch_size=cfg["batch_size"], seed=cfg["seed"],
        )
        f.model = SWLSTM(cfg["input_size"], cfg["hidden"], cfg["horizon"], cfg["dropout"])
        f.model.load_state_dict(obj["state_dict"])
        f.best_epoch = cfg.get("best_epoch", 0)
        return f


# ---------------------------------------------------------------------------
# 2. 统计基线
# ---------------------------------------------------------------------------
@dataclass
class SeasonalNaive:
    name: str = field(default="SEASONAL_NAIVE", init=False)
    y_train: Optional[np.ndarray] = None

    def fit(self, X_train=None, y_train=None, X_val=None, y_val=None) -> "SeasonalNaive":
        self.y_train = np.asarray(y_train, dtype=float).ravel()
        return self

    def predict(self, X=None, y_context=None, periods=None) -> np.ndarray:
        y = np.asarray(y_context if y_context is not None else self.y_train, dtype=float).ravel()
        periods = pd.DatetimeIndex(periods)
        out = []
        for ts in periods:
            idx = [i for i, p in enumerate(pd.date_range("2019-01-01", periods=len(y), freq="MS"))
                   if p.month == ts.month]
            if idx:
                out.append(y[idx[-1]])
            else:
                out.append(float(np.mean(y[-12:])))
        return np.asarray(out, dtype=float).reshape(1, -1)


@dataclass
class HoltWinters:
    name: str = field(default="HOLT_WINTERS", init=False)
    y_train: Optional[np.ndarray] = None
    fitted: Any = None
    seasonal_periods: int = 12

    def fit(self, X_train=None, y_train=None, X_val=None, y_val=None) -> "HoltWinters":
        self.y_train = np.asarray(y_train, dtype=float).ravel()
        try:
            self.fitted = ExponentialSmoothing(
                self.y_train, trend="add", seasonal="add",
                seasonal_periods=self.seasonal_periods,
                initialization_method="estimated",
            ).fit(optimized=True, use_brute=False)
        except Exception:
            self.fitted = None
        return self

    def predict(self, X=None, y_context=None, periods=None) -> np.ndarray:
        h = len(periods) if periods is not None else 12
        if self.fitted is not None:
            try:
                return np.asarray(self.fitted.forecast(h), dtype=float).reshape(1, -1)
            except Exception:
                pass
        return SeasonalNaive().fit(y_train=y_context if y_context is not None else self.y_train).predict(
            periods=periods
        )


# ---------------------------------------------------------------------------
# 3. 机器学习基线
# ---------------------------------------------------------------------------
@dataclass
class RidgeForecaster:
    name: str = field(default="RIDGE", init=False)
    alpha: float = 10.0
    model: Any = None

    def fit(self, X_train, y_train, X_val=None, y_val=None) -> "RidgeForecaster":
        self.model = Ridge(alpha=self.alpha)
        self.model.fit(flatten_windows(X_train), y_train)
        return self

    def predict(self, X, y_context=None, periods=None) -> np.ndarray:
        return self.model.predict(flatten_windows(X))

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.model, directory / "model.joblib")

    @classmethod
    def load(cls, directory: Path) -> "RidgeForecaster":
        obj = cls()
        obj.model = joblib.load(directory / "model.joblib")
        return obj


@dataclass
class GBMForecaster:
    name: str = field(default="GBM", init=False)
    max_iter: int = 250
    learning_rate: float = 0.05
    max_depth: int = 3
    seed: int = 20260928
    model: Any = None

    def fit(self, X_train, y_train, X_val=None, y_val=None) -> "GBMForecaster":
        # 注意：不使用 HistGradientBoosting——其分箱阶段会创建线程池/管道，
        # 在部分受限运行环境中会被拒绝；GradientBoosting 为纯串行实现。
        base = GradientBoostingRegressor(
            n_estimators=self.max_iter, learning_rate=self.learning_rate,
            max_depth=self.max_depth, min_samples_leaf=5,
            subsample=0.9, random_state=self.seed,
        )
        self.model = MultiOutputRegressor(base, n_jobs=1)
        self.model.fit(flatten_windows(X_train), y_train)
        return self

    def predict(self, X, y_context=None, periods=None) -> np.ndarray:
        return self.model.predict(flatten_windows(X))

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.model, directory / "model.joblib")

    @classmethod
    def load(cls, directory: Path) -> "GBMForecaster":
        obj = cls()
        obj.model = joblib.load(directory / "model.joblib")
        return obj


# ---------------------------------------------------------------------------
# 4. 统一训练/评估
# ---------------------------------------------------------------------------
MODEL_NAMES = ["SW_LSTM", "RIDGE", "GBM", "HOLT_WINTERS", "SEASONAL_NAIVE"]


def make_model(name: str, input_size: int, horizon: int, W: int,
               hidden: int = 32, seed: int = 20260928) -> Any:
    if name == "SW_LSTM":
        return LSTMForecaster(input_size=input_size, hidden=hidden, horizon=horizon, seed=seed)
    if name == "RIDGE":
        return RidgeForecaster()
    if name == "GBM":
        return GBMForecaster(seed=seed)
    if name == "HOLT_WINTERS":
        return HoltWinters()
    if name == "SEASONAL_NAIVE":
        return SeasonalNaive()
    raise ValueError(name)


def fit_predict(model: Any, X_train: np.ndarray, y_train: np.ndarray,
                X_eval: np.ndarray, y_eval: np.ndarray,
                y_context: np.ndarray, eval_periods: pd.DatetimeIndex,
                scaler: Scaler | None = None,
                X_es: np.ndarray | None = None, y_es: np.ndarray | None = None) -> tuple[np.ndarray, Scaler]:
    """在训练段 fit，在评估段 predict，返回原始量纲预测与 scaler。

    X_train / X_eval 均为原始特征，内部按训练段 fit scaler。
    X_es / y_es 仅用于 LSTM 早停，必须来自训练段内部（不得使用评估段）。
    """
    if scaler is None:
        scaler = Scaler().fit(X_train, y_train)
    X_train_s = scaler.transform_X(X_train)
    y_train_s = scaler.transform_y(y_train)
    X_eval_s = scaler.transform_X(X_eval)
    y_eval_s = scaler.transform_y(y_eval) if y_eval is not None else None
    X_es_s = scaler.transform_X(X_es) if X_es is not None and len(X_es) else None
    y_es_s = scaler.transform_y(y_es) if y_es is not None and len(y_es) else None

    model.fit(X_train_s, y_train_s, X_es_s, y_es_s)
    if model.name in ("SEASONAL_NAIVE", "HOLT_WINTERS"):
        pred = model.predict(None, y_context=y_context, periods=eval_periods)
        return np.asarray(pred, dtype=float).reshape(-1), scaler
    pred_s = model.predict(X_eval_s)
    return scaler.inverse_y(np.asarray(pred_s, dtype=float)).reshape(-1), scaler


def fit_final(model: Any, X_train: np.ndarray, y_train: np.ndarray,
              scaler: Scaler | None = None) -> tuple[Any, Scaler]:
    """在全部训练段 fit（不再留验证集）。"""
    if scaler is None:
        scaler = Scaler().fit(X_train, y_train)
    Xs = scaler.transform_X(X_train)
    ys = scaler.transform_y(y_train)
    model.fit(Xs, ys, None, None)
    return model, scaler


def save_model(model: Any, directory: Path, scaler: Scaler) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if hasattr(model, "save"):
        model.save(directory)
    else:
        joblib.dump(model, directory / "model.joblib")
    (directory / "scaler.json").write_text(
        json.dumps(scaler.state(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_model(name: str, directory: Path) -> tuple[Any, Scaler]:
    scaler = Scaler.from_state(json.loads((directory / "scaler.json").read_text(encoding="utf-8")))
    if name == "SW_LSTM":
        return LSTMForecaster.load(directory), scaler
    if name == "RIDGE":
        return RidgeForecaster.load(directory), scaler
    if name == "GBM":
        return GBMForecaster.load(directory), scaler
    if name == "HOLT_WINTERS":
        return joblib.load(directory / "model.joblib"), scaler
    if name == "SEASONAL_NAIVE":
        return joblib.load(directory / "model.joblib"), scaler
    raise ValueError(name)
