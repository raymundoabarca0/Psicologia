"""Backtest de seguimiento de tendencia en oro (XAU/USD) en 4h y diario, con costos.

Uso: python backtest/oro_tendencia.py <csv de velas de 1h de XAU/USD>
(el csv se baja con paper_signals.market.klines('XAU/USD', '1h', start=...)).

Las velas de 4h y diarias se arman desde 1h a la hora del servidor de MetaTrader (UTC+2).
Señal al cierre de la vela; entrada en la apertura de la siguiente. Si en una vela se tocan el
stop y el objetivo, cuenta el stop; un gap más allá del stop sale a la apertura.
Costo por operación: spread 0,34 + deslizamiento 0,15 = 0,49 USD por onza (restado en R).
Resultados en R (múltiplos del riesgo inicial).
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from paper_signals.market import _resample_mt  # noqa: E402

COST = 0.49


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(df, n):
    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(),
                    (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def simulate(df, entry_long, entry_short, stop_dist, exit_long=None, exit_short=None, rr=None):
    """Una posición a la vez. exit_*: salida al cierre (se ejecuta en la apertura siguiente)."""
    o, h, l, c = df.open.values, df.high.values, df.low.values, df.close.values
    el, es, sd = entry_long.values, entry_short.values, stop_dist.values
    xl = exit_long.values if exit_long is not None else np.zeros(len(df), bool)
    xs = exit_short.values if exit_short is not None else np.zeros(len(df), bool)
    trades, i, n = [], 0, len(df)
    while i < n - 1:
        side = 1 if el[i] else -1 if es[i] else 0
        risk = sd[i]
        if side == 0 or not np.isfinite(risk) or risk <= 0:
            i += 1
            continue
        j = i + 1
        entry = o[j]
        stop = entry - side * risk
        tp = entry + side * rr * risk if rr else None
        res, k = None, j
        while k < n:
            if (side == 1 and l[k] <= stop) or (side == -1 and h[k] >= stop):
                px = o[k] if (k > j and (o[k] - stop) * side < 0) else stop
                res = side * (px - entry) / risk
                break
            if tp is not None and ((side == 1 and h[k] >= tp) or (side == -1 and l[k] <= tp)):
                res = rr
                break
            if ((side == 1 and xl[k]) or (side == -1 and xs[k])) and k + 1 < n:
                res = side * (o[k + 1] - entry) / risk
                k += 1
                break
            k += 1
        if res is None:
            res = side * (c[-1] - entry) / risk
        trades.append((df.index[j], side, res - COST / risk))
        i = k + 1
    return pd.DataFrame(trades, columns=["time", "side", "R"])


def report(name, t):
    if t.empty:
        print(f"{name}: sin operaciones")
        return
    w, ls = t.R[t.R > 0].sum(), -t.R[t.R < 0].sum()
    years = t.groupby(t.time.dt.year).R.sum().round(1)
    eq = t.R.cumsum()
    dd = (eq.cummax() - eq).max()
    print(f"{name}\n  n={len(t)} ganadoras={100*(t.R>0).mean():.0f}% R/op={t.R.mean():+.2f} "
          f"total={t.R.sum():+.1f}R PF={w/ls if ls else float('inf'):.2f} caída máx={dd:.1f}R "
          f"| compras {t[t.side==1].R.sum():+.1f}R ventas {t[t.side==-1].R.sum():+.1f}R")
    print("  por año: " + ", ".join(f"{y}: {v:+.1f}R" for y, v in years.items()))


def main():
    h1 = pd.read_csv(sys.argv[1], index_col=0, parse_dates=True)
    h1.index = pd.to_datetime(h1.index, utc=True)
    d = _resample_mt(h1, "1d")
    f = _resample_mt(h1, "4h")
    print(f"Datos: {len(h1)} velas 1h ({h1.index[0]:%Y-%m-%d} a {h1.index[-1]:%Y-%m-%d}); "
          f"{len(f)} velas 4h; {len(d)} velas diarias\n")

    # T1. Ruptura de canal (Donchian) en diario, estilo "tortuga": entra al romper el máximo/mínimo
    # de 20 días, stop 2 ATR, sale al romper el canal contrario de 10 días.
    a = atr(d, 20)
    hi20, lo20 = d.high.shift(1).rolling(20).max(), d.low.shift(1).rolling(20).min()
    hi10, lo10 = d.high.shift(1).rolling(10).max(), d.low.shift(1).rolling(10).min()
    report("T1 D1 Donchian 20/10, stop 2 ATR, salida por canal",
           simulate(d, d.close > hi20, d.close < lo20, 2 * a, d.close < lo10, d.close > hi10))

    # T2. Cruce EMA20/50 en 4h a favor de la tendencia diaria (EMA50 vs EMA200 del diario);
    # stop 2 ATR de 4h; sale con el cruce contrario.
    up_d = (ema(d.close, 50) > ema(d.close, 200)).shift(1)
    trend = up_d.reindex(f.index, method="ffill").fillna(False).astype(bool)
    dn = ~trend & up_d.reindex(f.index, method="ffill").notna()
    e20, e50 = ema(f.close, 20), ema(f.close, 50)
    xup = (e20 > e50) & (e20.shift(1) <= e50.shift(1))
    xdn = (e20 < e50) & (e20.shift(1) >= e50.shift(1))
    a4 = atr(f, 14)
    report("T2 4h cruce EMA20/50 a favor del D1, stop 2 ATR, salida por cruce",
           simulate(f, xup & trend, xdn & dn, 2 * a4, xdn, xup))

    # T3. Retroceso a la EMA20 de 4h a favor de la tendencia (D1 y 4h alineados), objetivo fijo.
    up4, dn4 = e20 > e50, e20 < e50
    pb_l = (f.low <= e20) & (f.close > e20) & up4 & trend
    pb_s = (f.high >= e20) & (f.close < e20) & dn4 & dn
    for rr in (2.0, 3.0):
        report(f"T3 4h retroceso a EMA20 a favor de D1 y 4h, stop 1,5 ATR, objetivo {rr:g}R",
               simulate(f, pb_l, pb_s, 1.5 * a4, rr=rr))

    # Referencia: comprar y mantener desde el inicio.
    print(f"\nReferencia: comprar y mantener {d.close.iloc[0]:.0f} -> {d.close.iloc[-1]:.0f} "
          f"({(d.close.iloc[-1]/d.close.iloc[0]-1)*100:+.0f}%)")


if __name__ == "__main__":
    main()
