import pandas as pd
import pytest

from paper_signals.evaluate import _simulate

T0 = pd.Timestamp("2026-11-05 00:00", tz="UTC")


def bars(rows):
    idx = pd.date_range(T0, periods=len(rows), freq="h")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def sig(**kw):
    base = dict(direction="short", entry_type="limit", entry=100.0, stop=105.0,
                take_profit=90.0, created_utc=str(T0 - pd.Timedelta(minutes=30)),
                expires_utc=str(T0 + pd.Timedelta(hours=48)), manual_close_utc=None)
    base.update(kw)
    return pd.Series(base)


def test_short_limit_fills_then_tp():
    p = _simulate(sig(), bars([(98, 99, 97, 98), (99, 100.5, 98, 99), (99, 99, 89, 90)]))
    assert p.status == "tp" and p.fill_price == 100 and p.exit_price == 90


def test_stop_first_when_both_hit():
    p = _simulate(sig(), bars([(99, 101, 98, 100), (100, 106, 89, 95)]))
    assert p.status == "stop" and p.exit_price > 105


def test_stop_in_fill_bar_counts():
    p = _simulate(sig(), bars([(99, 106, 98, 104)]))
    assert p.status == "stop"


def test_gap_through_stop_exits_at_open():
    p = _simulate(sig(), bars([(99, 101, 98, 100), (110, 111, 109, 110)]))
    assert p.status == "gap_stop" and p.exit_price == pytest.approx(110 * 1.0005)


def test_expires_if_not_touched():
    s = sig(expires_utc=str(T0 + pd.Timedelta(hours=2)))
    p = _simulate(s, bars([(95, 96, 94, 95)] * 5))
    assert p.status == "expirada"


def test_long_market_and_open_mark():
    s = sig(direction="long", entry_type="market", entry=0, stop=95, take_profit=120)
    p = _simulate(s, bars([(100, 101, 99, 100), (100, 102, 99, 101)]))
    assert p.status == "abierta" and p.fill_price == pytest.approx(100.05)
    assert p.mark_price == 101


def test_ignores_bars_before_signal():
    s = sig(created_utc=str(T0 + pd.Timedelta(hours=1, minutes=5)))
    p = _simulate(s, bars([(99, 106, 98, 104), (95, 96, 94, 95), (95, 96, 94, 95)]))
    assert p.status == "pendiente" or p.fill_time is None
