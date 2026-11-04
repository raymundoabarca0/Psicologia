from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from bot.data.downloader import fetch_ohlcv_history
from bot.data.validator import check_tradeable, clean_ohlcv, ohlcv_to_frame

TF = "4h"
H4 = pd.Timedelta(hours=4)
START = pd.Timestamp("2026-01-01", tz="UTC")


def frame(n=300, start=START, price=100.0):
    idx = pd.date_range(start, periods=n, freq=H4)
    rng = np.random.default_rng(0)
    close = price * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = np.r_[price, close[:-1]]
    high = np.maximum(open_, close) * 1.002
    low = np.minimum(open_, close) * 0.998
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": 1.0}, index=idx)


def clean(df, now=None):
    return clean_ohlcv(df, TF, max_bar_move_pct=25.0, now=now)


def test_clean_data_untouched():
    df = frame()
    r = clean(df)
    assert len(r.df) == len(df) and not r.issues


def test_duplicates_removed():
    df = frame(10)
    df = pd.concat([df, df.iloc[[3]]])
    r = clean(df)
    assert len(r.df) == 10 and r.count("duplicate") == 1


def test_invalid_ohlc_removed():
    df = frame(10)
    df.iloc[2, df.columns.get_loc("high")] = df.iloc[2]["low"] * 0.5   # high < low
    df.iloc[5, df.columns.get_loc("close")] = np.nan
    df.iloc[7, df.columns.get_loc("open")] = -1
    r = clean(df)
    assert r.count("invalid") == 3 and len(r.df) == 7


def test_isolated_spike_removed_but_real_crash_kept():
    df = frame(20)
    # Pico aislado: x3 y vuelve.
    for c in ("close", "high"):
        df.iloc[5, df.columns.get_loc(c)] = df.iloc[4]["close"] * 3
    df.iloc[6, df.columns.get_loc("open")] = df.iloc[5]["close"]
    df.iloc[6, df.columns.get_loc("high")] = df.iloc[5]["close"]
    r = clean(df)
    assert df.index[5] in [i.timestamp for i in r.issues if i.kind == "anomaly"]

    # Desplome real y sostenido del 40%: todas las velas posteriores se conservan.
    df2 = frame(20)
    df2.iloc[10:, :4] *= 0.6
    df2.iloc[10, df2.columns.get_loc("open")] = df2.iloc[9]["close"]
    df2.iloc[10, df2.columns.get_loc("high")] = df2.iloc[9]["close"]
    r2 = clean(df2)
    assert len(r2.df) == 20


def test_extreme_wick_removed():
    df = frame(10)
    df.iloc[4, df.columns.get_loc("low")] = df.iloc[4]["low"] * 0.5
    r = clean(df)
    assert r.count("anomaly") == 1


def test_unclosed_candle_dropped():
    df = frame(10)
    now = df.index[-1] + pd.Timedelta(hours=1)   # la última vela sigue abierta
    r = clean(df, now=now.to_pydatetime())
    assert r.count("unclosed") == 1 and len(r.df) == 9


def test_gap_detected_and_blocks_trading():
    df = frame(300).drop(index=frame(300).index[[280, 281]])
    r = clean(df)
    assert r.count("gap") == 1
    now = (r.df.index[-1] + H4 + pd.Timedelta(minutes=1)).to_pydatetime()
    ok, reasons = check_tradeable(r.df, TF, now, required_clean_bars=100, max_staleness_bars=1.5)
    assert not ok and any("huecos" in x for x in reasons)


def test_tradeable_when_fresh_and_complete():
    df = frame(300)
    now = (df.index[-1] + H4 + pd.Timedelta(minutes=5)).to_pydatetime()
    ok, reasons = check_tradeable(df, TF, now, required_clean_bars=250, max_staleness_bars=1.5)
    assert ok, reasons


def test_stale_data_blocks_trading():
    df = frame(300)
    now = (df.index[-1] + H4 * 4).to_pydatetime()
    ok, reasons = check_tradeable(df, TF, now, required_clean_bars=250, max_staleness_bars=1.5)
    assert not ok and any("desactualizados" in x for x in reasons)


def test_not_enough_bars():
    df = frame(50)
    ok, _ = check_tradeable(df, TF, datetime.now(timezone.utc), required_clean_bars=250,
                            max_staleness_bars=1.5)
    assert not ok


def test_requires_tz_index():
    df = frame(5)
    df.index = df.index.tz_localize(None)
    with pytest.raises(ValueError):
        clean(df)


class FakeExchange:
    """Simula fetch_ohlcv paginado con un fallo de red transitorio."""

    def __init__(self, df, fail_first=True):
        self.rows = [[int(ts.timestamp() * 1000), *r] for ts, r in
                     zip(df.index, df[["open", "high", "low", "close", "volume"]].values.tolist())]
        self.fail_first = fail_first
        self.calls = 0

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=1000):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            import ccxt
            raise ccxt.NetworkError("timeout simulado")
        return [r for r in self.rows if r[0] >= since][:limit]


def test_downloader_paginates_and_retries():
    df = frame(250)
    ex = FakeExchange(df)
    since = df.index[0].to_pydatetime()
    until = (df.index[-1] + H4).to_pydatetime()
    out = fetch_ohlcv_history(ex, "BTC/USDT", TF, since, until, page_limit=100,
                              sleep=lambda s: None)
    assert len(out) == 250
    assert (out.index == df.index).all()
    assert ex.calls == 1 + 3  # 1 fallo + 3 páginas


def test_downloader_respects_until():
    df = frame(100)
    ex = FakeExchange(df, fail_first=False)
    out = fetch_ohlcv_history(ex, "BTC/USDT", TF, df.index[0].to_pydatetime(),
                              df.index[50].to_pydatetime(), page_limit=1000)
    assert len(out) == 50


def test_ohlcv_to_frame():
    df = ohlcv_to_frame([[0, 1, 2, 0.5, 1.5, 10]])
    assert df.index.tz is not None and df.iloc[0]["close"] == 1.5
