"""Resumen técnico de BTC y oro (diario y 4h) para preparar las señales.

Uso:  python -m paper_signals.analyze
"""

from __future__ import annotations

import pandas as pd

from bot.strategy import indicators as ind
from paper_signals.market import ASSETS, klines


def swings(df: pd.DataFrame, k: int = 3, n: int = 4) -> tuple[list, list]:
    """Máximos/mínimos fractales confirmados (k velas a cada lado)."""
    h, l = df["high"], df["low"]
    hi = h[(h == h.rolling(2 * k + 1, center=True).max())].dropna()
    lo = l[(l == l.rolling(2 * k + 1, center=True).min())].dropna()
    fmt = lambda s: [f"{v:,.2f} ({t:%m-%d %H}h)" for t, v in s.iloc[-n:].items()]
    return fmt(hi), fmt(lo)


def summary(name: str, df: pd.DataFrame, tf: str) -> str:
    c = df["close"]
    e20, e50, e200 = (ind.ema(c, n).iloc[-1] for n in (20, 50, 200))
    r = ind.rsi(c, 14).iloc[-1]
    a = ind.atr(df, 14).iloc[-1]
    adx = ind.adx(df, 14).iloc[-1]
    hi20, lo20 = df["high"].iloc[-20:].max(), df["low"].iloc[-20:].min()
    sh, sl = swings(df)
    last = df.iloc[-1]
    trend = ("alcista" if c.iloc[-1] > e50 > e200 else
             "bajista" if c.iloc[-1] < e50 < e200 else "mixta/lateral")
    lines = [
        f"## {name} {tf}  (última vela cerrada {df.index[-1]:%Y-%m-%d %H:%M} UTC)",
        f"cierre {last.close:,.2f} | O {last.open:,.2f} H {last.high:,.2f} L {last.low:,.2f}",
        f"EMA20 {e20:,.2f} | EMA50 {e50:,.2f} | EMA200 {e200:,.2f} -> tendencia {trend}",
        f"RSI14 {r:.1f} | ADX14 {adx:.1f} | ATR14 {a:,.2f} ({a / c.iloc[-1] * 100:.2f}%)",
        f"rango 20 velas: {lo20:,.2f} - {hi20:,.2f}",
        f"máximos swing: {sh}",
        f"mínimos swing: {sl}",
        "últimas 8 velas (cierre): " + ", ".join(f"{v:,.0f}" for v in c.iloc[-8:]),
    ]
    return "\n".join(lines)


def main() -> None:
    for name, sym in ASSETS.items():
        for tf in ("1d", "4h"):
            print(summary(f"{name} ({sym})", klines(sym, tf, limit=400), tf))
            print()


if __name__ == "__main__":
    main()
