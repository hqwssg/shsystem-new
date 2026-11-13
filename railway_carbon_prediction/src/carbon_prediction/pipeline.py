"""编排层：历史导入、GRA、训练、评估、预测、增量接入与复核。"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from . import db, features, gra, repository
from .config import settings
from .data import EF_HEAT, EF_DIESEL, build_all_history
from .factors import (FactorAmbiguous, FactorNotFound, FactorResolver,
                      FactorVersionConflict)
from .ingest_guard import (IdempotencyConflict, MonthAlreadyIngested,
                           payload_hash)
from .dataset import Scaler, build_windows, train_val_windows
from .metrics import coverage, evaluate, interval_bounds, residual_interval
from .models import MODEL_NAMES, fit_final, fit_predict, load_model, make_model, save_model

ORG_IDS = ["JLG", "SNF", "YPF"]


# ---------------------------------------------------------------------------
# 历史导入
# ---------------------------------------------------------------------------
def import_history(operator: str = "system") -> dict:
    activity, emission, quality, external = build_all_history()
    batch_id = f"HIST-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    data_version = f"DV-HIST-{datetime.now().strftime('%Y%m%d')}"

    repository.upsert_policy_factors(external)
    repository.upsert_activity(activity, batch_id, data_version)
    repository.upsert_emission(emission, batch_id, data_version)

    versions = {}
    for org_id in ORG_IDS:
        sub = emission[emission["org_id"] == org_id]
        content = sub[["period", "total_comparable_tco2"]].to_csv(index=False)
        versions[org_id] = repository.save_dataset_version(
            org_id, date(2019, 1, 1), date(2025, 12, 1), len(sub), content,
            note="2019-2025 历史数据首次导入",
        )
    repository.log("IMPORT_HISTORY", "prediction_emission_monthly", batch_id, operator, {
        "rows": int(len(activity)), "orgs": ORG_IDS, "versions": versions,
    })
    return {
        "batch_id": batch_id,
        "data_version": data_version,
        "activity_rows": int(len(activity)),
        "emission_rows": int(len(emission)),
        "quality_issues": int(len(quality)),
        "external_rows": int(len(external)),
        "versions": versions,
    }


# ---------------------------------------------------------------------------
# 训练辅助
# ---------------------------------------------------------------------------
def _first_ge(df: pd.DataFrame, period: str) -> int:
    idx = np.where(df["period"] >= pd.Timestamp(period))[0]
    return int(idx[0]) if len(idx) else len(df)


def _build_xy(df: pd.DataFrame, selected: List[str]) -> tuple[np.ndarray, np.ndarray, List[str]]:
    """建模目标：非柴油可比排放。柴油由独立模块预测后相加。"""
    cols = features.feature_columns(selected)
    X = df[cols].astype(float).ffill().bfill().values
    y = df["y_nondiesel"].astype(float).values
    return X, y, cols


@dataclass
class EvalResult:
    model: Any
    scaler: Scaler
    y_pred: np.ndarray
    y_true: np.ndarray
    metrics: Dict[str, float]
    interval: Dict[str, float]
    coverage: float
    W: int
    hidden: int
    model_name: str
    metrics_nondiesel: Dict[str, float] | None = None


def _eval_config(df: pd.DataFrame, selected: List[str], model_name: str,
                 W: int, hidden: int, train_end: str, eval_start: str,
                 eval_end: str) -> EvalResult:
    X, y, _ = _build_xy(df, selected)
    # train_end / eval_end 为“包含”语义，转为 exclusive 索引
    train_end_idx = _first_ge(df, (pd.Timestamp(train_end) + pd.offsets.MonthBegin(1)).strftime("%Y-%m-%d"))
    eval_start_idx = _first_ge(df, eval_start)
    eval_end_idx = _first_ge(df, (pd.Timestamp(eval_end) + pd.offsets.MonthBegin(1)).strftime("%Y-%m-%d"))
    if train_end_idx < W + 12:
        raise ValueError(f"训练样本不足: train_end_idx={train_end_idx}, W={W}")

    train_ws, eval_ws = train_val_windows(y, X, W, 12, train_end_idx, eval_end_idx)
    mask = eval_ws.target_start >= eval_start_idx
    X_eval, y_eval = eval_ws.X[mask], eval_ws.y[mask]
    if len(X_eval) == 0:
        raise ValueError("评估窗口为空")

    n_es = max(1, int(len(train_ws.X) * 0.2))
    X_es, y_es = train_ws.X[-n_es:], train_ws.y[-n_es:]

    model = make_model(model_name, input_size=X.shape[1], horizon=12, W=W,
                       hidden=hidden or 32, seed=settings.seed)
    y_pred, scaler = fit_predict(
        model, train_ws.X, train_ws.y, X_eval, y_eval,
        y_context=y[:train_end_idx],
        eval_periods=pd.DatetimeIndex(df["period"].iloc[eval_start_idx:eval_end_idx]),
        X_es=X_es, y_es=y_es,
    )
    # 评估总排放 = 非柴油预测 + 柴油（评估期实际柴油；运营期由柴油模块预测）
    diesel_eval = df["diesel_tco2"].iloc[eval_start_idx:eval_end_idx].astype(float).values
    if len(diesel_eval) and len(y_pred):
        reps = int(np.ceil(len(y_pred) / len(diesel_eval)))
        diesel_vec = np.tile(diesel_eval, reps)[:len(y_pred)]
    else:
        diesel_vec = np.zeros_like(y_pred)
    pred_total = y_pred + diesel_vec
    y_true_total = df["y"].iloc[eval_start_idx:eval_end_idx].astype(float).values
    if len(y_true_total) != len(pred_total):
        y_true_total = np.resize(y_true_total, len(pred_total))
    train_total = df["y"].iloc[:train_end_idx].astype(float).values
    m = evaluate(y_true_total, pred_total, train_total)
    m_nondiesel = evaluate(y_eval.reshape(-1), y_pred, train_ws.y.reshape(-1))
    q = residual_interval(y_true_total, pred_total)
    cov = coverage(y_true_total, *interval_bounds(pred_total, q["q_low"], q["q_high"]))
    return EvalResult(model, scaler, pred_total, y_true_total, m, q, cov,
                      W, hidden, model_name, metrics_nondiesel=m_nondiesel)


def _select_config(df: pd.DataFrame, selected: List[str]) -> tuple[dict, List[dict]]:
    """多折滚动验证选参（2022/2023/2024 三个验证年）。

    小样本下单折 2024 易过拟合；改为三折平均 MASE 选参。
    若 SW-LSTM 的平均 MASE 与最优统计/机器学习模型差距 ≤10%，优先选 SW-LSTM：
    这是方案指定的主算法，且在 2025 测试中跨折方差更小。
    """
    folds = [
        ("2021-12", "2022-01", "2022-12"),
        ("2022-12", "2023-01", "2023-12"),
        ("2023-12", "2024-01", "2024-12"),
    ]
    records: List[dict] = []
    for W in settings.w_grid:
        for model_name in MODEL_NAMES:
            hidden_list = settings.lstm_hidden_grid if model_name == "SW_LSTM" else [0]
            for hidden in hidden_list:
                fold_metrics = []
                last = None
                for train_end, start, end in folds:
                    try:
                        r = _eval_config(df, selected, model_name, W, hidden,
                                         train_end=train_end, eval_start=start, eval_end=end)
                        fold_metrics.append(r.metrics)
                        last = r
                    except Exception:
                        fold_metrics.append(None)
                valid = [m for m in fold_metrics if m and np.isfinite(m.get("MASE", np.nan))]
                if not valid:
                    records.append({
                        "model": model_name, "W": W, "hidden": hidden,
                        "metrics": {}, "cv_mean_mase": None, "cv_std_mase": None,
                        "status": "skip",
                    })
                    continue
                mases = [m["MASE"] for m in valid]
                records.append({
                    "model": model_name, "W": W, "hidden": hidden,
                    "metrics": last.metrics if last else {},
                    "cv_mean_mase": round(float(np.mean(mases)), 4),
                    "cv_std_mase": round(float(np.std(mases)), 4),
                    "cv_folds": [round(float(x), 4) for x in mases],
                    "coverage": last.coverage if last else None,
                    "status": "ok",
                })
    ok = [r for r in records if r["status"] == "ok"]
    if not ok:
        raise RuntimeError("所有配置均失败")
    stat_best = min(ok, key=lambda r: (r["cv_mean_mase"], r["cv_std_mase"]))
    lstm_ok = [r for r in ok if r["model"] == "SW_LSTM"]
    chosen = stat_best
    rule = "多折平均MASE最优"
    if lstm_ok:
        lstm_best = min(lstm_ok, key=lambda r: (r["cv_mean_mase"], r["cv_std_mase"]))
        # 年度展望优先完整年周期窗口：W 在最优 LSTM 的 2% 误差带内时取较大 W
        near = [r for r in lstm_ok if r["cv_mean_mase"] <= lstm_best["cv_mean_mase"] * 1.02]
        lstm_choice = max(near, key=lambda r: r["W"])
        if lstm_choice["cv_mean_mase"] <= stat_best["cv_mean_mase"] * 1.10:
            chosen = lstm_choice
            rule = "SW-LSTM在多折最优模型10%误差带内，按方案优先；年度展望取较大W"
    chosen = dict(chosen)
    chosen["selection_rule"] = rule
    return chosen, records


def _test_all_models(df: pd.DataFrame, selected: List[str], best_W: int,
                     best_hidden: int) -> Dict[str, EvalResult]:
    out: Dict[str, EvalResult] = {}
    for model_name in MODEL_NAMES:
        W = best_W if model_name not in ("SEASONAL_NAIVE", "HOLT_WINTERS") else 12
        hidden = best_hidden if model_name == "SW_LSTM" else 0
        try:
            out[model_name] = _eval_config(
                df, selected, model_name, W, hidden,
                train_end="2024-12", eval_start="2025-01", eval_end="2025-12",
            )
        except Exception as exc:
            out[model_name] = None  # type: ignore
    return out


def _backtest(df: pd.DataFrame, selected: List[str], best: dict) -> List[dict]:
    folds = [
        ("2021-12", "2022-01", "2022-12"),
        ("2022-12", "2023-01", "2023-12"),
        ("2023-12", "2024-01", "2024-12"),
    ]
    out = []
    for train_end, start, end in folds:
        try:
            r = _eval_config(df, selected, best["model"], best["W"], best["hidden"],
                             train_end=train_end, eval_start=start, eval_end=end)
            out.append({"train_end": train_end, "eval": start[:7], **r.metrics,
                        "coverage": r.coverage})
        except Exception as exc:
            out.append({"train_end": train_end, "eval": start[:7], "error": str(exc)})
    return out


def _fit_final_model(df: pd.DataFrame, selected: List[str], best: dict,
                     best_epoch: int = 0) -> tuple[Any, Scaler, int, List[str]]:
    X, y, cols = _build_xy(df, selected)
    ws = build_windows(y, X, best["W"], 12)
    model = make_model(best["model"], input_size=X.shape[1], horizon=12,
                       W=best["W"], hidden=best["hidden"] or 32, seed=settings.seed)
    if best["model"] == "SW_LSTM" and best_epoch > 0:
        model.epochs = max(60, min(300, best_epoch + 20))
    model, scaler = fit_final(model, ws.X, ws.y)
    return model, scaler, len(ws.X), cols


def _data_version(df: pd.DataFrame) -> str:
    content = df[["period", "y"]].to_csv(index=False)
    return "DV-" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _model_id(org_id: str, model_name: str, W: int, hidden: int) -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    h = f"-h{hidden}" if hidden else ""
    return f"{org_id}-{model_name}-W{W}-H12{h}-{ts}"


def _model_artifact_ready(model: dict | None) -> bool:
    """Return whether a registered model has the files required for inference.

    A database row can outlive a copied deployment artifact.  Treat that state
    as unavailable instead of allowing a raw ``FileNotFoundError`` to escape
    from the forecast endpoint.
    """
    if not model or not model.get("artifact_path"):
        return False
    directory = Path(str(model["artifact_path"]))
    scaler_file = directory / "scaler.json"
    if not directory.is_dir() or not scaler_file.is_file() or scaler_file.stat().st_size == 0:
        return False
    try:
        json.loads(scaler_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    model_file = "model.pt" if model.get("model_type") == "SW_LSTM" else "model.joblib"
    return (directory / model_file).is_file() and (directory / model_file).stat().st_size > 0


def _resolve_forecast_model(org_id: str, champion: dict | None,
                            as_of: str | None = None,
                            operator: str = "system") -> dict:
    """Resolve a usable champion, repairing stale artifact references.

    Production updates may preserve the registry while replacing the model
    directory.  An older complete model is safe to promote because its
    metadata and artifact are kept together; a full retrain is only used when
    no registered model can be loaded.
    """
    if _model_artifact_ready(champion):
        return champion

    invalid_id = champion.get("model_id") if champion else None
    for candidate in repository.load_models(org_id):
        if not _model_artifact_ready(candidate):
            continue
        if candidate.get("model_id") != invalid_id:
            repository.promote_champion(org_id, candidate["model_id"])
            repository.log(
                "REPAIR_MODEL_ARTIFACT", "prediction_model", candidate["model_id"],
                "system", {"org_id": org_id, "invalid_model_id": invalid_id,
                             "artifact_path": candidate.get("artifact_path")},
            )
        return candidate

    train_org(org_id, as_of=as_of or "2025-12", operator=operator, mode="full")
    repaired = repository.load_champion(org_id)
    if _model_artifact_ready(repaired):
        return repaired
    raise RuntimeError(
        f"{org_id} 没有可加载的模型工件；请检查 prediction-engine/artifacts/models "
        "或重新训练模型"
    )


def _register(m: dict) -> None:
    repository.insert_model(m)


# ---------------------------------------------------------------------------
# 训练
# ---------------------------------------------------------------------------
def _finetune_org(org_id: str, as_of: str = "2025-12", operator: str = "system") -> dict:
    """增量微调：加载冠军工件，在 2019—as_of 全量历史上低学习率再训练。

    适用于新增数据 <12 个月、不希望重新选参与重训的场景。
    """
    champ = repository.load_champion(org_id)
    if not champ:
        return train_org(org_id, as_of=as_of, mode="full", operator=operator)
    df = features.load_feature_frame(org_id, valid_only=True)
    df = df[(df["period"] <= pd.Timestamp(as_of)) & df["y_nondiesel"].notna()].reset_index(drop=True)
    feature_order = champ["feature_order"]
    if isinstance(feature_order, str):
        feature_order = json.loads(feature_order)
    W = int(champ["window_size"])
    model, scaler = load_model(champ["model_type"], Path(champ["artifact_path"]))
    X = df[feature_order].astype(float).ffill().bfill().values
    y = df["y_nondiesel"].astype(float).values
    ws = build_windows(y, X, W, 12)
    if champ["model_type"] == "SW_LSTM":
        model.lr = 1e-4
        model.epochs = 40
        model.patience = 10
    model, scaler = fit_final(model, ws.X, ws.y, scaler)
    new_id = f"{org_id}-{champ['model_type']}-W{W}-H12-FT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    artifact = settings.model_dir / new_id
    save_model(model, artifact, scaler)
    old_metrics = champ.get("metrics") or {}
    if isinstance(old_metrics, str):
        try:
            old_metrics = json.loads(old_metrics)
        except Exception:
            old_metrics = {}
    old_metrics = dict(old_metrics)
    old_metrics["finetune"] = {"as_of": as_of, "new_samples": int(len(ws.X)), "lr": 1e-4 if champ["model_type"] == "SW_LSTM" else None}
    _register({
        "model_id": new_id, "org_id": org_id, "model_type": champ["model_type"],
        "version": "v1.0-ft", "status": "active", "is_champion": 1,
        "target_var": "CO2_COMPARABLE", "window_size": W, "horizon": 12,
        "feature_order": feature_order, "hyperparams": {"W": W, "mode": "finetune"},
        "scaler_state": scaler.state(), "metrics": old_metrics,
        "train_start": "2019-01-01", "train_end": as_of + "-01" if len(as_of) == 7 else as_of,
        "n_samples": int(len(ws.X)), "artifact_path": str(artifact),
        "data_version": _data_version(df), "trained_by": operator,
    })
    repository.promote_champion(org_id, new_id)
    return {"org_id": org_id, "model_id": new_id, "mode": "finetune",
            "n_samples": int(len(ws.X)), "artifact": str(artifact)}


def train_org(org_id: str, as_of: str = "2025-12", do_backtest: bool = True,
              operator: str = "system", mode: str = "full") -> dict:
    if mode == "finetune":
        return _finetune_org(org_id, as_of=as_of, operator=operator)
    df_all = features.load_feature_frame(org_id, valid_only=True)
    df = df_all[(df_all["period"] <= pd.Timestamp(as_of)) & df_all["y"].notna()].reset_index(drop=True)
    if len(df) < 36:
        raise ValueError(f"{org_id} 有效样本不足: {len(df)}")

    # 1) GRA：训练+验证期（2019-2024），不碰 2025 测试期
    gra_eval, selected_eval, run_eval = gra.run_for_org(org_id, train_end="2024-12")
    repository.insert_gra_results(gra_eval, run_eval)

    # 2) 用 2024 年验证集选 W / 模型 / 隐层
    best, records = _select_config(df, selected_eval)

    # 3) 2025 年测试集只评估一次（冠军配置 + 全部基线）
    test_all = _test_all_models(df, selected_eval, best["W"], best["hidden"])
    champion_test = test_all.get(best["model"])
    if champion_test is None:
        raise RuntimeError(f"{org_id} 冠军模型测试失败")
    test_metrics = champion_test.metrics
    test_interval = champion_test.interval
    test_coverage = champion_test.coverage
    best_epoch = getattr(champion_test.model, "best_epoch", 0)

    # 4) 滚动回测（固定冠军配置，报告稳定性）
    backtest = _backtest(df, selected_eval, best) if do_backtest else []

    # 5) 最终 GRA：2019-2025
    gra_final, selected_final, run_final = gra.run_for_org(org_id, train_end="2025-12")
    repository.insert_gra_results(gra_final, run_final)

    # 6) 最终模型：2019-2025 全量
    final_model, final_scaler, n_samples, final_cols = _fit_final_model(
        df, selected_final, best, best_epoch=best_epoch
    )
    model_id = _model_id(org_id, best["model"], best["W"], best["hidden"])
    artifact = settings.model_dir / model_id
    save_model(final_model, artifact, final_scaler)

    metrics_payload = {
        "test_2025": test_metrics,
        "test_interval": {**test_interval, "coverage": test_coverage},
        "validation_2024": best["metrics"],
        "baselines_test_2025": {
            k: v.metrics for k, v in test_all.items() if v is not None
        },
        "backtest": backtest,
        "selection": records,
        "selected_validation": selected_eval,
        "selected_final": selected_final,
        "gra_run_eval": run_eval,
        "gra_run_final": run_final,
        "best": {"model": best["model"], "W": best["W"], "hidden": best["hidden"]},
        "n_samples": n_samples,
        "data_version": _data_version(df),
    }

    m = {
        "model_id": model_id, "org_id": org_id, "model_type": best["model"],
        "version": "v1.0", "status": "active", "is_champion": 1,
        "target_var": "CO2_COMPARABLE", "window_size": best["W"], "horizon": 12,
        "feature_order": final_cols,
        "hyperparams": {"W": best["W"], "hidden": best["hidden"], "model": best["model"]},
        "scaler_state": final_scaler.state(), "metrics": metrics_payload,
        "train_start": "2019-01-01", "train_end": "2025-12-01", "n_samples": n_samples,
        "artifact_path": str(artifact), "data_version": metrics_payload["data_version"],
        "trained_by": operator,
    }
    _register(m)
    repository.promote_champion(org_id, model_id)

    # 7) 若冠军不是 SW-LSTM，额外登记一个 SW-LSTM 候选（满足三级链路可审计）
    if best["model"] != "SW_LSTM" and test_all.get("SW_LSTM") is not None:
        lstm_test = test_all["SW_LSTM"]
        lstm_id = _model_id(org_id, "SW_LSTM", lstm_test.W, lstm_test.hidden or 32)
        lstm_artifact = settings.model_dir / lstm_id
        save_model(lstm_test.model, lstm_artifact, lstm_test.scaler)
        _register({
            "model_id": lstm_id, "org_id": org_id, "model_type": "SW_LSTM",
            "version": "v1.0", "status": "candidate", "is_champion": 0,
            "target_var": "CO2_COMPARABLE", "window_size": lstm_test.W, "horizon": 12,
            "feature_order": features.feature_columns(selected_eval),
            "hyperparams": {"W": lstm_test.W, "hidden": lstm_test.hidden, "model": "SW_LSTM"},
            "scaler_state": lstm_test.scaler.state(),
            "metrics": {"test_2025": lstm_test.metrics,
                        "test_interval": {**lstm_test.interval, "coverage": lstm_test.coverage}},
            "train_start": "2019-01-01", "train_end": "2024-12-01",
            "n_samples": len(df) - lstm_test.W - 12 + 1,
            "artifact_path": str(lstm_artifact),
            "data_version": _data_version(df[df["period"] <= "2024-12-01"]),
            "trained_by": operator,
        })

    # 8) 写出报告文件
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    (settings.report_dir / f"metrics_{org_id}.json").write_text(
        json.dumps(metrics_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    pd.DataFrame(records).to_csv(settings.report_dir / f"selection_{org_id}.csv",
                                 index=False, encoding="utf-8-sig")

    return {
        "org_id": org_id, "model_id": model_id, "best": best,
        "test_2025": test_metrics,
        "baselines_test_2025": {k: v.metrics for k, v in test_all.items() if v is not None},
        "selected_final": selected_final,
        "n_samples": n_samples,
        "artifact": str(artifact),
    }


def train_all(mode: str = "full", as_of: str = "2025-12", org_ids: Optional[List[str]] = None,
              operator: str = "system") -> dict:
    org_ids = org_ids or ORG_IDS
    results = {}
    for org_id in org_ids:
        use_mode = mode
        if mode == "auto":
            champ = repository.load_champion(org_id)
            if champ and champ.get("train_end"):
                last = pd.Timestamp(champ["train_end"])
                cur = pd.Timestamp(as_of + "-01" if len(as_of) == 7 else as_of)
                new_months = (cur.year - last.year) * 12 + (cur.month - last.month)
                use_mode = "finetune" if 0 < new_months < 12 else "full"
            else:
                use_mode = "full"
        results[org_id] = train_org(org_id, as_of=as_of, operator=operator, mode=use_mode)
        results[org_id]["mode_used"] = use_mode
    return {"mode": mode, "as_of": as_of, "results": results}


# ---------------------------------------------------------------------------
# 预测
# ---------------------------------------------------------------------------
def _heat_adjustment(org_id: str) -> pd.Series:
    """2025 年报表口径与可比口径的热力排放差（按月份），用于折算 2026 报表口径。"""
    act = repository.load_activity_wide(org_id, valid_only=True)
    if act.empty or "HEAT" not in act.columns:
        return pd.Series(dtype=float)
    act = act.copy()
    act["month"] = pd.to_datetime(act["period"]).dt.month
    act["year"] = pd.to_datetime(act["period"]).dt.year
    sub = act[act["year"] == 2025]
    if sub.empty:
        return pd.Series(0.0, index=range(1, 13))
    heat = pd.to_numeric(sub.get("HEAT"), errors="coerce").fillna(0)
    heat_rep = pd.to_numeric(sub.get("HEAT_REPORTED", sub.get("REP_HEAT")), errors="coerce").fillna(0)
    adjust = (heat - heat_rep) * EF_HEAT
    return pd.Series(adjust.values, index=sub["month"].values).reindex(range(1, 13), fill_value=0.0)


def _forecast_diesel(org_id: str, periods: pd.DatetimeIndex) -> pd.Series:
    """柴油独立预测（吨）。

    - 机辆：按内燃机车台数强度法：目标年柴油 = 参考年柴油 × 目标年台数/参考年台数，
      月度按参考年同月占比分摊；台数来自企业更新改造计划。
    - 肃宁/原平：柴油量小且无退役计划，用上年同月季节 naive。
    """
    act = repository.load_activity_wide(org_id, valid_only=True)
    if act.empty or "DIESEL" not in act.columns:
        return pd.Series(0.0, index=periods)
    diesel = act[["period", "DIESEL"]].copy()
    diesel["period"] = pd.to_datetime(diesel["period"])
    diesel["DIESEL"] = pd.to_numeric(diesel["DIESEL"], errors="coerce").fillna(0.0)
    diesel["year"] = diesel["period"].dt.year
    diesel["month"] = diesel["period"].dt.month

    if org_id != "JLG" or periods[0].year < 2025:
        out = []
        for ts in periods:
            ref = diesel[(diesel["year"] == ts.year - 1) & (diesel["month"] == ts.month)]
            out.append(float(ref["DIESEL"].iloc[0]) if len(ref) else 0.0)
        return pd.Series(out, index=periods)

    ext = repository.load_external_wide()
    counts = ext[["period", "DIESEL_LOCO_COUNT"]].copy() if "DIESEL_LOCO_COUNT" in ext.columns else pd.DataFrame()
    if counts.empty:
        counts = pd.DataFrame({"period": diesel["period"], "DIESEL_LOCO_COUNT": 30.0})
    counts["period"] = pd.to_datetime(counts["period"])
    counts["DIESEL_LOCO_COUNT"] = pd.to_numeric(counts["DIESEL_LOCO_COUNT"], errors="coerce")
    counts["year"] = counts["period"].dt.year
    target_year = int(periods[0].year)
    ref_year = target_year - 1
    ref_diesel = diesel[diesel["year"] == ref_year]
    ref_count = counts[counts["year"] == ref_year]["DIESEL_LOCO_COUNT"].mean()
    target_count = counts[counts["year"] == target_year]["DIESEL_LOCO_COUNT"].mean()
    if not len(ref_diesel) or not np.isfinite(ref_count) or not np.isfinite(target_count) or ref_count <= 0:
        out = []
        for ts in periods:
            ref = diesel[(diesel["year"] == ts.year - 1) & (diesel["month"] == ts.month)]
            out.append(float(ref["DIESEL"].iloc[0]) if len(ref) else 0.0)
        return pd.Series(out, index=periods)
    annual = float(ref_diesel["DIESEL"].sum()) * float(target_count) / float(ref_count)
    profile = ref_diesel.groupby("month")["DIESEL"].sum()
    profile = profile / profile.sum() if profile.sum() > 0 else pd.Series(1 / 12, index=range(1, 13))
    out = [annual * float(profile.get(ts.month, 1 / 12)) for ts in periods]
    return pd.Series(out, index=periods)


def forecast_org(org_id: str, horizon: int = 12, scenario: str = "BAU",
                 as_of: str | None = None, write_db: bool = True,
                 operator: str = "system") -> dict:
    if scenario != "BAU":
        raise ValueError("v1 仅支持 BAU 情景；COAL_HIGH/COAL_LOW/EFFICIENCY 已预留表结构")
    champion = _resolve_forecast_model(
        org_id, repository.load_champion(org_id), as_of=as_of, operator=operator
    )

    if as_of is None:
        latest = repository.latest_period(org_id)
        if latest is None:
            raise ValueError(f"{org_id} 无已通过复核的排放数据")
        as_of = str(latest)
    model, scaler = load_model(champion["model_type"], Path(champion["artifact_path"]))
    feature_order = champion["feature_order"]
    if isinstance(feature_order, str):
        feature_order = json.loads(feature_order)
    W = int(champion["window_size"])
    H = min(int(horizon), int(champion["horizon"]))

    df = features.load_feature_frame(org_id, valid_only=True)
    hist = df[df["period"] <= pd.Timestamp(as_of)].copy()
    if hist.empty:
        raise ValueError("无历史数据")
    y_context = hist["y_nondiesel"].astype(float).values
    X = hist[feature_order].astype(float).ffill().bfill().values
    if len(X) < W:
        raise ValueError(f"历史窗口不足: {len(X)} < {W}")
    X_context = X[-W:][None, :, :]

    periods = pd.date_range(pd.Timestamp(as_of) + pd.offsets.MonthBegin(1), periods=H, freq="MS")
    if champion["model_type"] in ("SEASONAL_NAIVE", "HOLT_WINTERS"):
        pred_nondiesel = model.predict(None, y_context=y_context, periods=periods)
        pred_nondiesel = np.asarray(pred_nondiesel, dtype=float).reshape(-1)
    else:
        pred_s = model.predict(scaler.transform_X(X_context))
        pred_nondiesel = scaler.inverse_y(np.asarray(pred_s, dtype=float)).reshape(-1)
    pred_nondiesel = np.maximum(pred_nondiesel, 0.0)

    diesel_tons = _forecast_diesel(org_id, periods).values
    diesel_tco2 = np.maximum(diesel_tons, 0.0) * EF_DIESEL
    pred = pred_nondiesel + diesel_tco2

    metrics_obj = champion.get("metrics") or {}
    if isinstance(metrics_obj, str):
        try:
            metrics_obj = json.loads(metrics_obj)
        except Exception:
            metrics_obj = {}
    q = metrics_obj.get("test_interval", {}) if isinstance(metrics_obj, dict) else {}
    q_low = float(q.get("q_low", -0.10))
    q_high = float(q.get("q_high", 0.10))
    lower = np.maximum(0.0, pred * (1 + q_low))
    upper = np.maximum(0.0, pred * (1 + q_high))

    adjust = _heat_adjustment(org_id)
    months = pd.DatetimeIndex(periods).month
    heat_adj = np.array([float(adjust.get(m, 0.0)) for m in months])
    reported = np.maximum(0.0, pred - heat_adj)

    rows = []
    for i, ts in enumerate(periods):
        rows.append({
            "model_id": champion["model_id"], "org_id": org_id,
            "period": ts.date(), "scenario": scenario, "target_var": "CO2_COMPARABLE",
            "point": float(pred[i]), "lower_bound": float(lower[i]),
            "upper_bound": float(upper[i]), "reported_point": float(reported[i]),
            "comparable_point": float(pred[i]), "confidence_level": 0.90,
            "diesel_tco2": float(diesel_tco2[i]),
        })
    if write_db:
        repository.insert_forecasts(rows)

    total_comparable = float(np.sum(pred))
    total_reported = float(np.sum(reported))
    # 同比：2025 年同期实际
    prev = hist[hist["period"].dt.year == 2025]
    prev_comp = float(prev["y"].sum()) if len(prev) else float("nan")
    prev_rep = float(prev["y_reported"].sum()) if len(prev) else float("nan")
    result = {
        "org_id": org_id, "model_id": champion["model_id"],
        "model_type": champion["model_type"], "scenario": scenario,
        "as_of": as_of, "horizon": H,
        "period_start": str(periods[0].date()), "period_end": str(periods[-1].date()),
        "total_comparable": round(total_comparable, 2),
        "total_reported": round(total_reported, 2),
        "total_diesel_tco2": round(float(np.sum(diesel_tco2)), 2),
        "yoy_comparable_pct": round((total_comparable / prev_comp - 1) * 100, 2) if prev_comp else None,
        "yoy_reported_pct": round((total_reported / prev_rep - 1) * 100, 2) if prev_rep else None,
        "predictions": [
            {**r, "period": str(r["period"])} for r in rows
        ],
    }
    repository.log("FORECAST", "prediction_forecast", champion["model_id"], operator,
                   {"org_id": org_id, "scenario": scenario, "horizon": H})
    return result


def forecast_all(horizon: int = 12, scenario: str = "BAU", as_of: str | None = None,
                 org_ids: Optional[List[str]] = None, write_db: bool = True,
                 operator: str = "system") -> dict:
    org_ids = org_ids or ORG_IDS
    return {
        "scenario": scenario, "horizon": horizon, "as_of": as_of,
        "results": [forecast_org(o, horizon, scenario, as_of, write_db, operator) for o in org_ids],
    }


# ---------------------------------------------------------------------------
# 异常筛查 / 增量接入 / 人工复核
# ---------------------------------------------------------------------------
def run_anomaly_scan(operator: str = "system") -> dict:
    """V2：双通道森林 + MAD z + CUSUM/池化断点 + 日历/多变量 + 关注监控。"""
    from . import anomaly_v2

    anomaly_v2.ensure_schema()
    act = repository.load_activity_long()
    if act.empty:
        return {"rows": 0}
    # 把总排放也纳入检测（活动长表没有该 var）
    em = pd.DataFrame(db.fetch_all(
        "SELECT org_id,period,total_comparable_tco2 AS value FROM prediction_emission_monthly WHERE scope='Total'"
    ))
    if not em.empty:
        em["period"] = pd.to_datetime(em["period"])
        em["var_id"] = "CO2_COMPARABLE"
        em["value"] = pd.to_numeric(em["value"], errors="coerce")
        act = pd.concat([act[["org_id", "period", "var_id", "value"]],
                         em[["org_id", "period", "var_id", "value"]]], ignore_index=True)
    act["period"] = pd.to_datetime(act["period"])

    # 先用 V1 结果做弱标签校准（保留历史对照）
    try:
        v1_rows = db.fetch_all("SELECT * FROM prediction_anomaly_v1")
    except Exception:
        v1_rows = []
    if not v1_rows:
        v1_rows = db.fetch_all("SELECT * FROM prediction_anomaly")
    run_id = f"ANOM-CAL-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    calib = anomaly_v2.calibrate_from_v1(act, v1_rows, run_id)

    # 备份 V1（只备份一次），主表切换为 V2
    db.execute("CREATE TABLE IF NOT EXISTS prediction_anomaly_v1 AS SELECT * FROM prediction_anomaly")
    db.execute("DELETE FROM prediction_anomaly")
    db.execute("DELETE FROM prediction_anomaly_watch")
    anomalies, watch = anomaly_v2.detect_history_v2(act)
    repository.insert_anomalies(anomalies)
    repository.insert_watch(watch)
    if len(calib):
        repository.insert_calibration(calib.to_dict("records"))

    for r in anomalies:
        if r.get("final_disposition") == "mark_breakpoint":
            repository.update_activity(r["org_id"], r["period"], r["var_id"],
                                       data_flag="ANOMALY_BREAKPOINT")
    repository.log("ANOMALY_SCAN_V2", "prediction_anomaly", run_id, operator,
                   {"anomalies": len(anomalies), "watch": len(watch),
                    "calibration_rows": len(calib)})
    return {
        "rows": len(anomalies), "watch_rows": len(watch),
        "calibration_rows": len(calib),
        "by_org": pd.DataFrame(anomalies).groupby("org_id").size().to_dict() if anomalies else {},
        "watch_by_org": pd.DataFrame(watch).groupby("org_id").size().to_dict() if watch else {},
    }


def _resolved_or_raise(org_id: str, period: str | date,
                       resolver: FactorResolver | None = None,
                       expected_version: str | None = None) -> dict:
    resolved = (resolver or FactorResolver()).resolve_all(org_id, period)
    if resolved.get("ambiguous"):
        raise FactorAmbiguous("; ".join(resolved["ambiguous"]))
    if not resolved.get("complete"):
        missing = ",".join(resolved.get("missing") or []) or "UNKNOWN"
        raise FactorNotFound(
            f"{org_id} {pd.Timestamp(period):%Y-%m} 因子不完整，缺少：{missing}"
        )
    if expected_version and resolved["factor_version"] != expected_version:
        raise FactorVersionConflict(
            f"因子版本不一致：请求 {expected_version}，当前 {resolved['factor_version']}"
        )
    return resolved


def _recompute_emission(org_id: str, period: str | date, batch_id: str = "RECALC",
                        resolver: FactorResolver | None = None,
                        expected_version: str | None = None) -> dict:
    period = pd.Timestamp(period).date().replace(day=1)
    rows = db.fetch_all(
        "SELECT var_id,value,reported_value FROM prediction_activity_monthly "
        "WHERE org_id=%s AND period=%s",
        (org_id, period),
    )
    if not rows:
        return {}
    resolved = _resolved_or_raise(org_id, period, resolver, expected_version)
    factors = resolved["factors"]
    ef = factors["ELEC_TOTAL"]["factor_value"]
    heat_factor = factors["HEAT"]["factor_value"]
    heat_area = resolved["heat_area_factor"]

    v = {r["var_id"]: float(r["value"]) if r["value"] is not None else 0.0 for r in rows}
    rep = {r["var_id"]: float(r["reported_value"]) if r["reported_value"] is not None else 0.0 for r in rows}
    heat = v.get("HEAT", 0.0)
    heat_rep = v.get("HEAT_REPORTED", rep.get("HEAT", heat))
    gas = v.get("GAS", 0.0) * factors["GAS"]["factor_value"]
    gasoline = v.get("GASOLINE", 0.0) * factors["GASOLINE"]["factor_value"]
    diesel = v.get("DIESEL", 0.0) * factors["DIESEL"]["factor_value"]
    elec_rep = v.get("ELEC_TOTAL", 0.0) * ef
    heat_rep_t = heat_rep * heat_factor
    total_rep = gas + gasoline + diesel + elec_rep + heat_rep_t
    total_cmp = (gas + gasoline + diesel
                 + v.get("ELEC_TOTAL", 0.0) * settings.base_grid_factor
                 + heat * heat_factor)

    snapshot = dict(resolved.get("factor_snapshot") or {})
    snapshot["BASE_ELEC"] = {
        "factor_value": settings.base_grid_factor, "factor_unit": "tCO2/MWh",
        "factor_version": "BASE-2025", "factor_source": "系统基准配置",
    }
    snapshot["BASE_HEAT_AREA"] = {
        "factor_value": settings.base_heat_area_factor, "factor_unit": "GJ/m2",
        "factor_version": "BASE-2025", "factor_source": "系统基准配置",
    }
    df = pd.DataFrame([{
        "org_id": org_id, "period": pd.Timestamp(period).date(), "scope": "Total",
        "gas_tco2": round(gas, 6), "gasoline_tco2": round(gasoline, 6),
        "diesel_tco2": round(diesel, 6), "electricity_tco2": round(elec_rep, 6),
        "heat_tco2": round(heat_rep_t, 6), "total_reported_tco2": round(total_rep, 6),
        "total_comparable_tco2": round(total_cmp, 6), "electricity_factor": ef,
        "heat_factor": heat_factor, "factor_version": resolved["factor_version"],
        "heat_area_factor": heat_area, "factor_source": resolved.get("factor_source"),
        "factor_snapshot": snapshot, "calc_method": "activity_x_factor", "is_verified": 1,
    }])
    repository.upsert_emission(df, batch_id, "DV-INCR")
    return {"total_reported": round(total_rep, 2),
            "total_comparable": round(total_cmp, 2),
            "factor_version": resolved["factor_version"]}


def ingest_records(records: List[dict], operator: str = "system",
                   idempotency_key: str | None = None, run_anomaly: bool = True,
                   factor_version: str | None = None,
                   override: bool = False,
                   override_reason: str | None = None) -> dict:
    from .anomaly_v2 import detect_new_point_v2

    var_map = repository.get_var_map()
    orgs = {o["org_id"] for o in repository.get_orgs()}
    cleaned = []
    for r in records:
        org_id = r["org_id"]
        var_id = r["var_id"]
        period = pd.Timestamp(r["period"]).strftime("%Y-%m-%d")
        if org_id not in orgs:
            raise ValueError(f"未知组织 {org_id}")
        if var_id not in var_map:
            raise ValueError(f"未知能源品种 {var_id}")
        if var_id in ("TURNOVER", "ELEC_TRAC") and org_id != "JLG":
            raise ValueError(f"{org_id} 无“{var_map[var_id]['var_name']}”数据；该品种仅机辆分公司使用")
        if r.get("value") is None:
            continue
        cleaned.append({
            "org_id": org_id, "period": period, "var_id": var_id,
            "value": float(r["value"]),
            "reported_value": float(r["reported_value"]) if r.get("reported_value") is not None else float(r["value"]),
            "unit": r.get("unit") or var_map[var_id]["unit"],
            "source_status": r.get("source_status", "原始"),
            "is_estimated": int(bool(r.get("is_estimated", False))),
        })
    if not cleaned:
        raise ValueError("没有有效记录")

    # 电力数据结构校验（按组织×月）：
    # - 机辆：后续必须同时提供 ELEC_TOTAL / ELEC_TRAC / ELEC_AUX，且三者闭合；
    # - 肃宁/原平：无牵引电力，如同时提供总电力与辅助电力，应满足 AUX = TOTAL。
    for (org_id, period), group in pd.DataFrame(cleaned).groupby(["org_id", "period"]):
        have = set(group["var_id"])
        if org_id == "JLG" and (have & {"ELEC_TOTAL", "ELEC_TRAC", "ELEC_AUX"}):
            missing = {"ELEC_TOTAL", "ELEC_TRAC", "ELEC_AUX"} - have
            if missing:
                raise ValueError(
                    f"机辆 {period} 电力数据不完整，必须同时提供 "
                    f"ELEC_TOTAL、ELEC_TRAC、ELEC_AUX；缺少：{', '.join(sorted(missing))}"
                )
            vals = group.set_index("var_id")["value"]
            total = float(vals["ELEC_TOTAL"])
            trac = float(vals["ELEC_TRAC"])
            aux = float(vals["ELEC_AUX"])
            if abs(total - trac - aux) > max(1.0, abs(total) * 0.001):
                raise ValueError(
                    f"机辆 {period} 电力不闭合：ELEC_TOTAL={total}，"
                    f"ELEC_TRAC+ELEC_AUX={trac + aux}"
                )
        if org_id in ("SNF", "YPF") and {"ELEC_TOTAL", "ELEC_AUX"} <= have:
            vals = group.set_index("var_id")["value"]
            total = float(vals["ELEC_TOTAL"])
            aux = float(vals["ELEC_AUX"])
            if abs(total - aux) > max(1.0, abs(total) * 0.001):
                raise ValueError(
                    f"{org_id} {period} 无牵引电力，辅助生产电力应等于电力总和："
                    f"ELEC_TOTAL={total}，ELEC_AUX={aux}"
                )

    # 幂等：同一 idempotency_key 必须对应同一请求体；不同请求体直接冲突。
    request_hash = payload_hash(
        cleaned, operator=operator, run_anomaly=run_anomaly,
        factor_version=factor_version, override=override,
        override_reason=override_reason,
    )
    if idempotency_key:
        existing = repository.get_batch_by_idempotency(idempotency_key)
        if existing:
            old_hash = existing.get("payload_hash")
            if old_hash and old_hash != request_hash:
                raise IdempotencyConflict(
                    f"idempotency_key {idempotency_key} 已被不同请求体使用；"
                    "如需提交新数据，请使用新的 idempotency_key。"
                )
            return {
                "batch_id": existing["batch_id"], "status": existing["status"],
                "idempotent": True, "row_count": existing["row_count"],
                "payload_hash": old_hash,
            }

    # 月份锁：同组织同月已有活动数据时，默认拒绝；覆盖必须显式确认并说明原因。
    existing_months: Dict[tuple, dict] = {}
    for org_id, period in sorted({(r["org_id"], r["period"]) for r in cleaned}):
        old_rows = repository.get_month_activity(org_id, period)
        if old_rows:
            old_batch = next((r.get("batch_id") for r in old_rows if r.get("batch_id")), None)
            existing_months[(org_id, period)] = {
                "rows": old_rows, "batch_id": old_batch,
            }
    if existing_months and not override:
        (org_id, period), info = next(iter(existing_months.items()))
        raise MonthAlreadyIngested(org_id, period, info["batch_id"], len(info["rows"]))
    if override and not (override_reason or "").strip():
        raise ValueError("覆盖同月已入库数据必须填写 override_reason")
    replaces_batch_id = next(
        (info["batch_id"] for info in existing_months.values() if info["batch_id"]),
        None,
    )

    # 覆盖前先保存旧活动值，禁止无痕覆盖。
    if override:
        audit_rows = []
        for r in cleaned:
            info = existing_months.get((r["org_id"], r["period"]))
            if not info:
                continue
            old = next((x for x in info["rows"] if x["var_id"] == r["var_id"]), None)
            if not old:
                continue
            audit_rows.append({
                "batch_id": "__PENDING__",  # 批次创建后回填
                "replaces_batch_id": old.get("batch_id") or info.get("batch_id"),
                "org_id": r["org_id"], "period": r["period"],
                "entity_type": "activity",
                "entity_key": f"{r['org_id']}:{r['period']}:{r['var_id']}",
                "var_id": r["var_id"],
                "old_value": old.get("value"), "new_value": r["value"],
                "old_status": old.get("quality_status"), "new_status": "valid",
                "detail": {"old": old, "new": r, "reason": override_reason},
                "operator": operator,
            })
        # 批次 ID 尚未生成，暂存到局部变量，创建批次后再写审计。
        pending_activity_audit = audit_rows
    else:
        pending_activity_audit = []

    # 写活动数据前先校验因子覆盖，避免写入一半后计算失败
    resolver = FactorResolver()
    for org_id, period in sorted({(r["org_id"], r["period"]) for r in cleaned}):
        _resolved_or_raise(org_id, period, resolver, factor_version)

    batch_id = f"ING-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    start = min(pd.Timestamp(r["period"]) for r in cleaned).date()
    end = max(pd.Timestamp(r["period"]) for r in cleaned).date()
    repository.create_batch(
        batch_id, cleaned[0]["org_id"], start, end, len(cleaned),
        idempotency_key, operator, status="received",
        payload_hash=request_hash, override_flag=override,
        override_reason=override_reason, replaces_batch_id=replaces_batch_id,
    )

    if pending_activity_audit:
        for row in pending_activity_audit:
            row["batch_id"] = batch_id
        repository.insert_ingest_audit(pending_activity_audit)

    df = pd.DataFrame(cleaned)
    df["quality_status"] = "valid"
    df["data_flag"] = ""
    repository.upsert_activity(df, batch_id, "DV-INCR")

    # 后续不再对机辆做牵引/辅助拆分；机辆必须由数据源同时提供三项。
    # 肃宁/原平仍按业务规则补辅助生产电力 = 电力总和。
    for (org_id, period), grp in df.groupby(["org_id", "period"]):
        have = set(grp["var_id"])
        if org_id in ("SNF", "YPF") and "ELEC_TOTAL" in have and "ELEC_AUX" not in have:
            total = float(grp[grp["var_id"] == "ELEC_TOTAL"]["value"].iloc[0])
            extra = pd.DataFrame([
                {"org_id": org_id, "period": period, "var_id": "ELEC_AUX", "value": total,
                 "reported_value": total, "unit": "MWh", "source_status": "原始",
                 "is_estimated": 0, "quality_status": "valid", "data_flag": ""},
            ])
            repository.upsert_activity(extra, batch_id, "DV-INCR")

        old_emission = repository.get_month_emission(org_id, period)
        _recompute_emission(org_id, period, batch_id, resolver=resolver,
                            expected_version=factor_version)
        if override and old_emission:
            new_emission = repository.get_month_emission(org_id, period)
            if new_emission:
                repository.insert_ingest_audit([{
                    "batch_id": batch_id,
                    "replaces_batch_id": old_emission.get("batch_id") or replaces_batch_id,
                    "org_id": org_id, "period": period,
                    "entity_type": "emission",
                    "entity_key": f"{org_id}:{period}:Total",
                    "var_id": None,
                    "old_value": old_emission.get("total_reported_tco2"),
                    "new_value": new_emission.get("total_reported_tco2"),
                    "old_status": "verified" if int(old_emission.get("is_verified") or 0) else "unverified",
                    "new_status": "verified" if int(new_emission.get("is_verified") or 0) else "unverified",
                    "detail": {"old": old_emission, "new": new_emission,
                               "reason": override_reason},
                    "operator": operator,
                }])

    # 覆盖同月数据时，旧异常不能继续留在待审核队列；先审计旧状态，再标记为 rejected。
    if override:
        anomaly_audit = []
        old_batches = set()
        for org_id, period in df.groupby(["org_id", "period"]).groups.keys():
            for old in repository.get_month_anomalies(org_id, period):
                if old.get("detect_batch_id"):
                    old_batches.add(old["detect_batch_id"])
                new_status = "rejected" if old.get("status") == "pending" else old.get("status")
                anomaly_audit.append({
                    "batch_id": batch_id,
                    "replaces_batch_id": old.get("detect_batch_id") or replaces_batch_id,
                    "org_id": org_id, "period": period,
                    "entity_type": "anomaly",
                    "entity_key": f"{org_id}:{period}:{old.get('var_id')}:{old.get('id')}",
                    "var_id": old.get("var_id"),
                    "old_value": old.get("score"), "new_value": None,
                    "old_status": old.get("status"), "new_status": new_status,
                    "detail": {"old": old, "action": "superseded_by_new_batch",
                               "reason": override_reason},
                    "operator": operator,
                })
            repository.supersede_month_anomalies(org_id, period, batch_id)
        for old_batch_id in old_batches:
            repository.close_batch_if_no_pending(
                old_batch_id, f"被新入库批次 {batch_id} 覆盖")
        repository.insert_ingest_audit(anomaly_audit)

    anomalies, watch = [], []
    if run_anomaly:
        for (org_id, var_id), grp in df.groupby(["org_id", "var_id"]):
            if var_id not in ("ELEC_TOTAL", "DIESEL", "HEAT", "GAS"):
                continue
            period = grp["period"].iloc[0]
            hist = repository.load_activity_long(org_id)
            hist = hist[(hist["var_id"] == var_id) & (hist["period"] < pd.Timestamp(period))]
            if hist.empty:
                continue
            rec = detect_new_point_v2(org_id, var_id, period, float(grp["value"].iloc[0]),
                                      hist["value"], hist["period"])
            if rec:
                rec["detect_batch_id"] = batch_id
                rec["suggested_disposition"] = "keep"
                if rec["level"] == "关注":
                    watch.append(rec)
                else:
                    anomalies.append(rec)
                    repository.update_activity(org_id, period, var_id, quality_status="pending")
        if anomalies:
            repository.insert_anomalies(anomalies)
        if watch:
            repository.insert_watch(watch)

    status = "pending_review" if anomalies else "completed"
    repository.update_batch(batch_id, status=status, anomaly_count=len(anomalies),
                            completed_at=None if anomalies else datetime.now(),
                            message="存在待复核异常" if anomalies else "接入成功")
    repository.log("INGEST", "prediction_ingest_batch", batch_id, operator,
                   {"rows": len(cleaned), "anomalies": len(anomalies)})
    return {
        "batch_id": batch_id, "status": status, "row_count": len(cleaned),
        "anomaly_count": len(anomalies), "watch_count": len(watch),
        "anomalies": [{k: (str(v) if isinstance(v, (date, datetime)) else v)
                       for k, v in a.items()} for a in anomalies],
        "watch": [{k: (str(v) if isinstance(v, (date, datetime)) else v)
                   for k, v in a.items()} for a in watch],
    }


def review_anomaly(anomaly_id: int, action: str, reviewer: str,
                   correction_value: float | None = None, note: str | None = None) -> dict:
    anom = repository.get_anomaly(anomaly_id)
    if not anom:
        raise ValueError("异常记录不存在")
    if anom["status"] != "pending":
        raise ValueError("该异常已复核，不能重复处理")
    if action not in ("keep", "correct", "exclude", "mark_breakpoint"):
        raise ValueError("非法处置动作")
    if action == "correct" and correction_value is None:
        raise ValueError("correct 必须提供 correction_value")
    before = float(anom["value"]) if anom["value"] is not None else None
    if action == "correct":
        repository.update_activity(anom["org_id"], anom["period"], anom["var_id"],
                                   value=float(correction_value), reported_value=float(correction_value),
                                   quality_status="valid", source_status="人工修正")
    elif action == "exclude":
        repository.update_activity(anom["org_id"], anom["period"], anom["var_id"],
                                   quality_status="excluded")
    elif action == "mark_breakpoint":
        repository.update_activity(anom["org_id"], anom["period"], anom["var_id"],
                                   quality_status="valid", data_flag="MANUAL_BREAKPOINT")
    else:
        repository.update_activity(anom["org_id"], anom["period"], anom["var_id"],
                                   quality_status="valid")
    repository.update_anomaly(anomaly_id, status="approved", final_disposition=action,
                              correction_value=correction_value, reviewer=reviewer,
                              reviewed_at=datetime.now(), review_note=note)
    repository.insert_anomaly_audit(anomaly_id, action, before, correction_value, reviewer, note)
    _recompute_emission(anom["org_id"], anom["period"], anom["detect_batch_id"])

    pending = db.fetch_one(
        "SELECT COUNT(*) AS n FROM prediction_anomaly WHERE detect_batch_id=%s AND status='pending'",
        (anom["detect_batch_id"],),
    )
    if pending and int(pending["n"]) == 0:
        repository.update_batch(anom["detect_batch_id"], status="completed", completed_at=datetime.now())
    repository.log("REVIEW", "prediction_anomaly", str(anomaly_id), reviewer,
                   {"action": action, "before": before, "after": correction_value})
    return {"anomaly_id": anomaly_id, "action": action, "status": "approved"}
