import numpy as np
import pandas as pd

from paper_signals.analyze import trend_meter, volatility_meter


def frame(close, spread):
    idx = pd.date_range("2026-01-01", periods=len(close), freq="h", tz="UTC")
    c = pd.Series(close, index=idx, dtype=float)
    sp = pd.Series(spread, index=idx, dtype=float)
    return pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c + sp, "low": c - sp,
                         "close": c, "volume": 0.0})


def test_trend_meter_signs():
    up = frame(np.linspace(100, 200, 300), 0.5)
    down = frame(np.linspace(200, 100, 300), 0.5)
    assert trend_meter(up)["score"] >= 60
    assert trend_meter(down)["score"] <= -60
    assert -100 <= trend_meter(up)["score"] <= 100


def test_volatility_meter_percentile():
    calm_then_wild = frame(np.full(300, 100.0), np.r_[np.full(280, 0.2), np.full(20, 3.0)])
    wild_then_calm = frame(np.full(300, 100.0), np.r_[np.full(280, 3.0), np.full(20, 0.2)])
    assert volatility_meter(calm_then_wild)["percentil"] > 85
    assert volatility_meter(wild_then_calm)["percentil"] < 20
