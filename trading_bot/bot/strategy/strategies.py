"""Las tres estrategias candidatas (solo largas, pocos parámetros)."""

from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from bot.strategy import indicators as ind
from bot.strategy.base import Strategy


def _grid(**axes) -> list[dict]:
    keys = list(axes)
    return [dict(zip(keys, vals)) for vals in product(*axes.values())]


class TrendEMA(Strategy):
    """A. Seguimiento de tendencia: entra cuando EMA rápida > EMA lenta y ADX > umbral
    (en el momento en que la condición se activa). Stop inicial 2×ATR, trailing
    3×ATR; sale si la EMA rápida cruza por debajo de la lenta."""

    name = "A_trend_ema"
    param_grid = _grid(fast=[20, 50], slow=[100, 200], adx_min=[15, 25])

    def signals(self, df: pd.DataFrame) -> pd.DataFrame:
        p = {"fast": 50, "slow": 200, "adx_min": 20, "stop_atr": 2.0, "trail_atr": 3.0,
             **self.params}
        a = ind.atr(df, 14)
        ef, es = ind.ema(df["close"], p["fast"]), ind.ema(df["close"], p["slow"])
        regime = (ef > es) & (ind.adx(df, 14) > p["adx_min"]) & (df["close"] > ef)
        out = pd.DataFrame(index=df.index)
        out["entry"] = regime & ~regime.shift(1, fill_value=False)
        out["exit"] = ef < es
        out["stop_dist"] = p["stop_atr"] * a
        out["tp_dist"] = np.nan
        out["trail_pct"] = p["trail_atr"] * a / df["close"] * 100
        out["atr"] = a
        return self._finalize(out, max(self.warmup, p["slow"]))


class DonchianBreakout(Strategy):
    """B. Ruptura: entra si el cierre supera el máximo de las N velas anteriores.
    Stop inicial 2×ATR; sale si el cierre pierde el mínimo de las M velas
    anteriores; trailing de k×ATR como protección adicional."""

    name = "B_donchian"
    param_grid = _grid(entry_n=[20, 55], exit_n=[10, 20], trail_atr=[3.0, 5.0])

    def signals(self, df: pd.DataFrame) -> pd.DataFrame:
        p = {"entry_n": 20, "exit_n": 10, "stop_atr": 2.0, "trail_atr": 4.0, **self.params}
        a = ind.atr(df, 14)
        out = pd.DataFrame(index=df.index)
        out["entry"] = df["close"] > ind.donchian_high(df, p["entry_n"])
        out["exit"] = df["close"] < ind.donchian_low(df, p["exit_n"])
        out["stop_dist"] = p["stop_atr"] * a
        out["tp_dist"] = np.nan
        out["trail_pct"] = p["trail_atr"] * a / df["close"] * 100
        out["atr"] = a
        return self._finalize(out, max(60, p["entry_n"] + 15))


class RSIMeanReversion(Strategy):
    """C. Reversión a la media en tendencia alcista: entra si RSI(2) < umbral y el
    cierre está sobre la SMA 200. Sale si RSI(2) > rsi_exit; stop k×ATR;
    take-profit 3×ATR."""

    name = "C_rsi2_meanrev"
    param_grid = _grid(rsi_entry=[5, 10, 15], rsi_exit=[60, 70], stop_atr=[2.0, 3.0])

    def signals(self, df: pd.DataFrame) -> pd.DataFrame:
        p = {"rsi_entry": 10, "rsi_exit": 60, "stop_atr": 2.0, "tp_atr": 3.0,
             "trend_n": 200, **self.params}
        a = ind.atr(df, 14)
        r = ind.rsi(df["close"], 2)
        out = pd.DataFrame(index=df.index)
        out["entry"] = (r < p["rsi_entry"]) & (df["close"] > ind.sma(df["close"], p["trend_n"]))
        out["exit"] = r > p["rsi_exit"]
        out["stop_dist"] = p["stop_atr"] * a
        out["tp_dist"] = p["tp_atr"] * a
        out["trail_pct"] = np.nan
        out["atr"] = a
        return self._finalize(out, max(self.warmup, p["trend_n"]))


ALL_STRATEGIES: dict[str, type[Strategy]] = {
    s.name: s for s in (TrendEMA, DonchianBreakout, RSIMeanReversion)
}
