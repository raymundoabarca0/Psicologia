"""Resumen técnico de BTC y oro (diario y 4h) para preparar las señales.

Uso:  python -m paper_signals.analyze
"""

from __future__ import annotations

import pandas as pd

from bot.strategy import indicators as ind
from paper_signals.market import ASSETS, klines


def fp(v: float) -> str:
    """Formato de precio según su magnitud (BTC 2 decimales, EUR 5)."""
    return f"{v:,.2f}" if abs(v) >= 100 else f"{v:,.5f}"


def swings(df: pd.DataFrame, k: int = 3, n: int = 4) -> tuple[list, list]:
    """Máximos/mínimos fractales confirmados (k velas a cada lado)."""
    h, l = df["high"], df["low"]
    hi = h[(h == h.rolling(2 * k + 1, center=True).max())].dropna()
    lo = l[(l == l.rolling(2 * k + 1, center=True).min())].dropna()
    fmt = lambda s: [f"{fp(v)} ({t:%m-%d %H}h)" for t, v in s.iloc[-n:].items()]
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
        f"cierre {fp(last.close)} | O {fp(last.open)} H {fp(last.high)} L {fp(last.low)}",
        f"EMA20 {fp(e20)} | EMA50 {fp(e50)} | EMA200 {fp(e200)} -> tendencia {trend}",
        f"RSI14 {r:.1f} | ADX14 {adx:.1f} | ATR14 {fp(a)} ({a / c.iloc[-1] * 100:.2f}%)",
        f"rango 20 velas: {fp(lo20)} - {fp(hi20)}",
        f"máximos swing: {sh}",
        f"mínimos swing: {sl}",
        "últimas 8 velas (cierre): " + ", ".join(fp(v) for v in c.iloc[-8:]),
    ]
    return "\n".join(lines)


def main() -> None:
    import sys
    tfs = sys.argv[1:] or ["1d", "4h"]   # p. ej.: python -m paper_signals.analyze 1h 15m
    for name, sym in ASSETS.items():
        for tf in tfs:
            print(summary(f"{name} ({sym})", klines(sym, tf, limit=400), tf))
            print()


if __name__ == "__main__":
    main()
