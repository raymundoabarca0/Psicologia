import numpy as np
import pandas as pd

from paper_signals.analyze import candle_patterns, chart_patterns


def mk(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="h", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(volume=0.0)


def base(n=30):
    return [(100 + i % 3, 101.5 + i % 3, 99 + i % 3, 100.5 + i % 3) for i in range(n)]


def test_hammer_and_engulfing():
    rows = base() + [(101, 101.2, 100.0, 100.2), (100.0, 101.3, 99.9, 101.2)]
    assert any("envolvente alcista" in p for p in candle_patterns(mk(rows)))
    rows = base() + [(100.6, 101.3, 97.0, 101.2)]
    assert any("martillo" in p for p in candle_patterns(mk(rows)))


def test_structure_up_and_breakout():
    legs = [(100, 110), (110, 106), (106, 116), (116, 112), (112, 122), (122, 119), (119, 130)]
    close = np.concatenate([np.linspace(a, b, 8, endpoint=False) for a, b in legs])
    rows = [(c - .2, c + .5, c - .5, c) for c in close]
    pats = chart_patterns(mk(rows))
    assert any("estructura alcista" in p for p in pats)
    assert any("ruptura alcista" in p for p in pats)
