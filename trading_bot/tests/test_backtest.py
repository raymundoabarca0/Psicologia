"""Tests del motor de backtest: si el motor miente, los resultados no valen nada."""

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestEngine
from backtest.metrics import max_drawdown_pct, summarize
from backtest.walk_forward import make_windows
from bot.config import BotConfig
from bot.execution.order_validator import MarketRules
from bot.strategy.base import SIGNAL_COLUMNS
from bot.strategy.strategies import ALL_STRATEGIES

H4 = pd.Timedelta(hours=4)
SYM = "BTC/USDT"
RULES = {SYM: MarketRules(SYM, Decimal("0.00001"), Decimal("0.01"), Decimal("0.00001"),
                          Decimal("5"))}


def bars(ohlc: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(ohlc), freq=H4, tz="UTC")
    return pd.DataFrame(ohlc, columns=["open", "high", "low", "close"], index=idx).assign(volume=1.0)


def sigs(df, entries=(), exits=(), stop=5.0, tp=np.nan, trail=np.nan, atr=5.0):
    s = pd.DataFrame(index=df.index, columns=SIGNAL_COLUMNS)
    s["entry"] = False
    s["exit"] = False
    s.iloc[list(entries), 0] = True
    s.iloc[list(exits), 1] = True
    s["stop_dist"], s["tp_dist"], s["trail_pct"], s["atr"] = stop, tp, trail, atr
    return s


def engine(cost_free=True, **kw):
    cfg = BotConfig()
    if cost_free:
        cfg = cfg.model_copy(update={"costs": cfg.costs.model_copy(
            update={"fee_rate": 0.0, "slippage_rate": 0.0, "spread_rate": 0.0})})
    return BacktestEngine(cfg, RULES, initial_capital=10_000, **kw)


FLAT = (100, 101, 99, 100)


def test_entry_executes_at_next_open_not_signal_close():
    df = bars([FLAT, FLAT, (110, 111, 109, 110), (110, 111, 109, 110)])
    res = engine().run({SYM: df}, {SYM: sigs(df, entries=[1], tp=1000)})
    assert res.trades[0].entry_time == df.index[2]
    assert res.trades[0].entry_price == pytest.approx(110)


def test_stop_assumed_first_when_stop_and_tp_same_bar():
    df = bars([FLAT, FLAT, (100, 120, 80, 100), FLAT])
    res = engine().run({SYM: df}, {SYM: sigs(df, entries=[1], stop=5, tp=10)})
    assert res.trades[0].reason == "stop"
    assert res.trades[0].exit_price == pytest.approx(95)
    assert res.trades[0].pnl < 0


def test_gap_below_stop_exits_at_open():
    df = bars([FLAT, FLAT, FLAT, (80, 81, 79, 80), (80, 81, 79, 80)])
    res = engine().run({SYM: df}, {SYM: sigs(df, entries=[1], stop=5, tp=50)})
    t = res.trades[0]
    assert t.reason == "gap_stop" and t.exit_price == pytest.approx(80)
    assert t.r_multiple < -1  # el gap supera el riesgo planificado: se reporta así


def test_risk_per_trade_respected_without_gap():
    df = bars([FLAT, FLAT, (100, 101, 90, 92), FLAT])
    res = engine(cost_free=False).run({SYM: df}, {SYM: sigs(df, entries=[1], stop=5, tp=50)})
    assert -res.trades[0].pnl <= 10_000 * 0.01 + 1e-6


def test_costs_make_flat_round_trip_lose():
    df = bars([FLAT] * 6)
    res = engine(cost_free=False).run({SYM: df}, {SYM: sigs(df, entries=[1], exits=[3], tp=50)})
    assert len(res.trades) == 1 and res.trades[0].reason == "signal"
    assert res.trades[0].pnl < 0 and res.fees > 0
    assert res.equity.iloc[-1] < 10_000


def test_trailing_stop_ratchets_up_and_uses_previous_bar():
    df = bars([FLAT, FLAT, (100, 120, 99, 119), (119, 119, 107, 108), FLAT])
    res = engine().run({SYM: df}, {SYM: sigs(df, entries=[1], stop=5, trail=10.0)})
    t = res.trades[0]
    # Máximo 120 -> trailing 108; la vela siguiente toca 107 -> sale a 108.
    assert t.reason == "trail" and t.exit_price == pytest.approx(108)


def test_no_lookahead_future_data_does_not_change_past():
    rng = np.random.default_rng(1)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 800)))
    o = np.r_[100, close[:-1]]
    df = bars(list(zip(o, np.maximum(o, close) * 1.01, np.minimum(o, close) * 0.99, close)))
    strat = ALL_STRATEGIES["B_donchian"]()
    full = engine().run({SYM: df}, {SYM: strat.signals(df)})
    # Alterar violentamente el futuro (a partir de la vela 600).
    df2 = df.copy()
    df2.iloc[600:, :4] *= 3
    alt = engine().run({SYM: df2}, {SYM: strat.signals(df2)})
    cut = df.index[599]
    pd.testing.assert_series_equal(full.equity[:cut], alt.equity[:cut])


@pytest.mark.parametrize("name", list(ALL_STRATEGIES))
def test_strategies_are_causal(name):
    rng = np.random.default_rng(2)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 700)))
    o = np.r_[100, close[:-1]]
    df = bars(list(zip(o, np.maximum(o, close) * 1.01, np.minimum(o, close) * 0.99, close)))
    strat = ALL_STRATEGIES[name]()
    full = strat.signals(df)
    part = strat.signals(df.iloc[:500])
    pd.testing.assert_frame_equal(full.iloc[:500], part)


def test_drawdown_halt_closes_everything_and_stops():
    # Pérdidas repetidas: cada entrada salta su stop.
    pattern = [FLAT, FLAT, (100, 100, 90, 91)] * 30
    df = bars(pattern)
    entries = [i for i in range(len(df)) if i % 3 == 1]
    res = engine().run({SYM: df}, {SYM: sigs(df, entries=entries, stop=5, tp=50)})
    assert res.halted_at is not None
    assert max_drawdown_pct(res.equity) < 12  # se detiene cerca del 10%
    last_trade = max(t.exit_time for t in res.trades)
    assert all(t.entry_time <= res.halted_at for t in res.trades)
    assert last_trade <= res.halted_at + H4


def test_summary_runs():
    df = bars([FLAT] * 6)
    m = summarize(engine().run({SYM: df}, {SYM: sigs(df, entries=[1], exits=[3], tp=50)}))
    assert m["operaciones"] == 1


def test_walk_forward_windows_never_overlap_test_with_train():
    w = make_windows(pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2026-11-01", tz="UTC"),
                     pd.DateOffset(years=2), pd.DateOffset(months=6))
    for tr_start, te_start, te_end in w:
        assert tr_start < te_start < te_end
    for a, b in zip(w, w[1:]):
        assert a[2] == b[1]  # pruebas consecutivas, sin solapes
