"""Resumen técnico de BTC, oro y euro para preparar las señales.

Incluye un medidor de tendencia (trend meter, -100..+100) y un medidor de volatilidad
(percentil del ATR14 en las últimas 200 velas), patrones de velas y figuras del gráfico
(estructura, doble techo/piso, triángulo, ruptura de rango) y un tablero final.

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


def _bar(frac: float, n: int = 10) -> str:
    k = max(0, min(n, round(frac * n)))
    return "▮" * k + "▯" * (n - k)


def volatility_meter(df: pd.DataFrame, lookback: int = 200) -> dict:
    """Medidor de volatilidad: ATR14 en % del precio y su percentil en las últimas
    `lookback` velas (0 = la más baja del periodo, 100 = la más alta)."""
    atr_pct = ind.atr(df, 14) / df["close"] * 100
    hist = atr_pct.dropna().iloc[-lookback:]
    now = float(hist.iloc[-1])
    pct = float((hist <= now).mean() * 100)
    if pct < 20:
        label = "baja (compresión: suele venir un movimiento fuerte)"
    elif pct < 60:
        label = "normal"
    elif pct < 85:
        label = "alta (stops más amplios, lote menor)"
    else:
        label = "extrema (riesgo de latigazos; mejor esperar)"
    return {"atr_pct": now, "percentil": pct, "label": label, "bar": _bar(pct / 100)}


def trend_meter(df: pd.DataFrame) -> dict:
    """Medidor de tendencia de -100 (bajista fuerte) a +100 (alcista fuerte).

    Suma 8 votos de +1/-1/0: precio vs EMA20, EMA50 y EMA200; EMA20 vs EMA50;
    EMA50 vs EMA200; pendiente de la EMA20 (vs 5 velas atrás); RSI14 (>55 / <45);
    histograma MACD 12-26-9. El ADX14 dice si hay fuerza (<20 = sin fuerza)."""
    c = df["close"]
    e20, e50, e200 = ind.ema(c, 20), ind.ema(c, 50), ind.ema(c, 200)
    macd = ind.ema(c, 12) - ind.ema(c, 26)
    hist = macd - ind.ema(macd, 9)
    r = ind.rsi(c, 14).iloc[-1]
    sgn = lambda x: int(x > 0) - int(x < 0)
    votes = [sgn(c.iloc[-1] - e20.iloc[-1]), sgn(c.iloc[-1] - e50.iloc[-1]),
             sgn(c.iloc[-1] - e200.iloc[-1]), sgn(e20.iloc[-1] - e50.iloc[-1]),
             sgn(e50.iloc[-1] - e200.iloc[-1]), sgn(e20.iloc[-1] - e20.iloc[-6]),
             1 if r > 55 else -1 if r < 45 else 0, sgn(hist.iloc[-1])]
    score = round(sum(votes) / len(votes) * 100)
    adx = float(ind.adx(df, 14).iloc[-1])
    if score >= 60:
        label = "alcista fuerte"
    elif score >= 25:
        label = "alcista"
    elif score > -25:
        label = "neutral / lateral"
    elif score > -60:
        label = "bajista"
    else:
        label = "bajista fuerte"
    if adx < 20:
        label += f" (sin fuerza, ADX {adx:.0f})"
    return {"score": score, "label": label, "adx": adx, "bar": _bar((score + 100) / 200)}


def candle_patterns(df: pd.DataFrame) -> list[str]:
    """Patrones de velas en las últimas velas cerradas (la última y sus 2 anteriores)."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    body = abs(c - o)
    avg = pd.Series(body).rolling(14).mean().to_numpy()
    out = []
    i = len(df) - 1
    rng = h[i] - l[i]
    if rng <= 0:
        return out
    up_w, lo_w = h[i] - max(o[i], c[i]), min(o[i], c[i]) - l[i]
    if body[i] <= 0.1 * rng:
        out.append("doji (indecisión)")
    elif lo_w >= 2 * body[i] and up_w <= max(body[i], 0.15 * rng):
        out.append("martillo / mecha larga abajo (rechazaron precios bajos)")
    elif up_w >= 2 * body[i] and lo_w <= max(body[i], 0.15 * rng):
        out.append("estrella fugaz / mecha larga arriba (rechazaron precios altos)")
    if body[i] >= 0.8 * rng and body[i] > 1.5 * avg[i]:
        out.append(f"vela grande {'alcista' if c[i] > o[i] else 'bajista'} (fuerza)")
    j = i - 1
    if c[j] < o[j] and c[i] > o[i] and c[i] >= o[j] and o[i] <= c[j] and body[i] > body[j]:
        out.append("envolvente alcista")
    if c[j] > o[j] and c[i] < o[i] and c[i] <= o[j] and o[i] >= c[j] and body[i] > body[j]:
        out.append("envolvente bajista")
    if h[i] < h[j] and l[i] > l[j]:
        out.append("inside bar (compresión: esperar ruptura)")
    k = i - 2
    small = body[j] <= 0.4 * avg[i]
    if c[k] < o[k] and body[k] > avg[i] and small and c[i] > o[i] and c[i] > (o[k] + c[k]) / 2:
        out.append("estrella de la mañana (giro alcista)")
    if c[k] > o[k] and body[k] > avg[i] and small and c[i] < o[i] and c[i] < (o[k] + c[k]) / 2:
        out.append("estrella de la tarde (giro bajista)")
    return out


def chart_patterns(df: pd.DataFrame, k: int = 3) -> list[str]:
    """Estructura y figuras simples con máximos/mínimos fractales (k velas a cada lado)."""
    h, l, c = df["high"], df["low"], df["close"]
    a = float(ind.atr(df, 14).iloc[-1])
    hi = h[(h == h.rolling(2 * k + 1, center=True).max())].dropna()
    lo = l[(l == l.rolling(2 * k + 1, center=True).min())].dropna()
    out = []
    if len(hi) >= 2 and len(lo) >= 2:
        h1, h2, l1, l2 = hi.iloc[-2], hi.iloc[-1], lo.iloc[-2], lo.iloc[-1]
        if h2 > h1 and l2 > l1:
            out.append("estructura alcista (máximos y mínimos más altos)")
        elif h2 < h1 and l2 < l1:
            out.append("estructura bajista (máximos y mínimos más bajos)")
        elif h2 < h1 and l2 > l1:
            out.append(f"triángulo / compresión entre {fp(l2)} y {fp(h2)}")
        else:
            out.append("estructura mixta")
        tol = 0.35 * a
        gap = lambda s: df.index.get_loc(s.index[-1]) - df.index.get_loc(s.index[-2])
        if abs(h2 - h1) <= tol and gap(hi) >= 5:
            neck = l[hi.index[-2]:hi.index[-1]].min()
            st = "confirmado" if c.iloc[-1] < neck else f"se confirma con cierre bajo {fp(neck)}"
            out.append(f"doble techo en ~{fp((h1 + h2) / 2)} ({st})")
        if abs(l2 - l1) <= tol and gap(lo) >= 5:
            neck = h[lo.index[-2]:lo.index[-1]].max()
            st = "confirmado" if c.iloc[-1] > neck else f"se confirma con cierre sobre {fp(neck)}"
            out.append(f"doble piso en ~{fp((l1 + l2) / 2)} ({st})")
    prev_hi, prev_lo = h.iloc[-21:-1].max(), l.iloc[-21:-1].min()
    if c.iloc[-1] > prev_hi:
        out.append(f"ruptura alcista del rango de 20 velas ({fp(prev_hi)})")
    elif c.iloc[-1] < prev_lo:
        out.append(f"ruptura bajista del rango de 20 velas ({fp(prev_lo)})")
    return out


def summary(name: str, df: pd.DataFrame, tf: str) -> str:
    c = df["close"]
    e20, e50, e200 = (ind.ema(c, n).iloc[-1] for n in (20, 50, 200))
    r = ind.rsi(c, 14).iloc[-1]
    a = ind.atr(df, 14).iloc[-1]
    adx = ind.adx(df, 14).iloc[-1]
    hi20, lo20 = df["high"].iloc[-20:].max(), df["low"].iloc[-20:].min()
    sh, sl = swings(df)
    last = df.iloc[-1]
    tm, vm = trend_meter(df), volatility_meter(df)
    trend = ("alcista" if c.iloc[-1] > e50 > e200 else
             "bajista" if c.iloc[-1] < e50 < e200 else "mixta/lateral")
    lines = [
        f"## {name} {tf}  (última vela cerrada {df.index[-1]:%Y-%m-%d %H:%M} UTC)",
        f"cierre {fp(last.close)} | O {fp(last.open)} H {fp(last.high)} L {fp(last.low)}",
        f"EMA20 {fp(e20)} | EMA50 {fp(e50)} | EMA200 {fp(e200)} -> tendencia {trend}",
        f"RSI14 {r:.1f} | ADX14 {adx:.1f} | ATR14 {fp(a)} ({a / c.iloc[-1] * 100:.2f}%)",
        f"TREND METER {tm['bar']} {tm['score']:+d} -> {tm['label']}",
        f"VOLATILIDAD  {vm['bar']} percentil {vm['percentil']:.0f} (ATR {vm['atr_pct']:.2f}%) -> {vm['label']}",
        f"VELAS: {'; '.join(candle_patterns(df)) or 'sin patrón claro'}",
        f"GRÁFICO: {'; '.join(chart_patterns(df)) or 'sin figura clara'}",
        f"rango 20 velas: {fp(lo20)} - {fp(hi20)}",
        f"máximos swing: {sh}",
        f"mínimos swing: {sl}",
        "últimas 8 velas (cierre): " + ", ".join(fp(v) for v in c.iloc[-8:]),
    ]
    return "\n".join(lines)


def main() -> None:
    import sys
    tfs = sys.argv[1:] or ["1d", "4h"]   # p. ej.: python -m paper_signals.analyze 1h 15m
    board = []
    for name, sym in ASSETS.items():
        for tf in tfs:
            df = klines(sym, tf, limit=400)
            print(summary(f"{name} ({sym})", df, tf))
            print()
            tm, vm = trend_meter(df), volatility_meter(df)
            board.append(f"{name:<4} {tf:>3} | tendencia {tm['score']:+4d} {tm['bar']} {tm['label']:<36.36}"
                         f" | volatilidad p{vm['percentil']:3.0f} {vm['bar']}")
    print("## TABLERO (trend meter -100..+100 | volatilidad: percentil del ATR en 200 velas)")
    print("\n".join(board))


if __name__ == "__main__":
    main()
