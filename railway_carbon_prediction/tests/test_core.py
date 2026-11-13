import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from carbon_prediction.anomaly_v2 import detect_breakpoint, detect_new_point_v2  # noqa: E402
from carbon_prediction.data import build_all_history  # noqa: E402
from carbon_prediction.dataset import Scaler, build_windows  # noqa: E402
from carbon_prediction.gra import _gra_r  # noqa: E402
from carbon_prediction.metrics import evaluate, mase  # noqa: E402


def test_gra_identical_series_is_one():
    y = np.array([10, 11, 13, 12, 15, 16, 18, 17, 19, 20, 22, 21], dtype=float)
    r, xi = _gra_r(y, y.copy(), rho=0.5, method="initial")
    assert abs(r - 1.0) < 1e-9
    assert np.allclose(xi, 1.0)


def test_metrics_perfect_prediction():
    y = np.arange(24, dtype=float) + 100
    m = evaluate(y, y.copy(), y)
    assert m["MAE"] == 0
    assert m["RMSE"] == 0
    assert m["MASE"] == 0


def test_window_shapes_no_crossing():
    n, W, H, F = 40, 6, 3, 2
    y = np.arange(n, dtype=float)
    X = np.arange(n * F, dtype=float).reshape(n, F)
    ws = build_windows(y, X, W, H)
    assert ws.X.shape == (n - W - H + 1, W, F)
    assert ws.y.shape == (n - W - H + 1, H)
    assert len(ws.origins) == len(ws.X)


def test_scaler_fit_boundary():
    rng = np.random.default_rng(0)
    X_train = rng.normal(size=(10, 3, 2))
    y_train = rng.normal(size=(10, 2))
    X_test = X_train + 100
    s = Scaler().fit(X_train, y_train)
    before = s.transform_X(X_test).copy()
    _ = s.transform_X(X_train)
    after = s.transform_X(X_test)
    assert np.allclose(before, after)


def test_history_row_count_and_caliber():
    act, em, quality, external = build_all_history()
    assert len(em) == 252
    assert set(em["org_id"].unique()) == {"JLG", "SNF", "YPF"}
    assert (em["total_comparable_tco2"] >= 0).all()
    # 2025 肃宁/原平热力口径还原后，可比热力应大于报表热力
    act_2025 = act[(act["period"].astype(str) >= "2025-01-01") & (act["var_id"] == "HEAT")]
    assert len(act_2025) > 0


def test_non_jlg_has_no_traction_or_turnover():
    act, _, _, _ = build_all_history()
    for org in ("SNF", "YPF"):
        sub = act[act["org_id"] == org]
        assert "ELEC_TRAC" not in set(sub["var_id"])
        assert "TURNOVER" not in set(sub["var_id"])
        elec = sub[sub["var_id"].isin(["ELEC_TOTAL", "ELEC_AUX"])].pivot(
            index="period", columns="var_id", values="value"
        )
        assert len(elec) > 0
        assert (elec["ELEC_AUX"] - elec["ELEC_TOTAL"]).abs().max() < 1e-6
    jlg = act[act["org_id"] == "JLG"]
    assert "ELEC_TRAC" in set(jlg["var_id"])
    assert "TURNOVER" in set(jlg["var_id"])


def test_breakpoint_detects_synthetic_step():
    y = np.r_[np.full(24, 100.0), np.full(24, 50.0)]
    bp = detect_breakpoint(y)
    assert bp["detected"] is True
    assert bp["index"] == 24
    assert bp["shift_pct"] < -40


def test_new_point_v2_flags_extreme_value():
    periods = pd.date_range("2019-01-01", periods=36, freq="MS")
    history = pd.Series(np.full(36, 100.0))
    rec = detect_new_point_v2("JLG", "ELEC_TOTAL", "2022-01", 999999,
                              history, periods)
    assert rec is not None
    assert rec["level"] == "严重异常"
    assert "z=" in rec["evidence"]
