# Uso: python backtest/oro_5m_reglas.py <csv de velas de 5m de XAU/USD>  (se baja con paper_signals.market.klines)
"""Backtest rápido de reglas de 5 minutos en XAU/USD (Twelve Data), con costos.

Entradas solo de 13:00 a 16:30 UTC (15:00-18:30 del servidor). Se entra a la apertura de la
vela siguiente a la señal. Stop y objetivo con high/low; si ambos caen en la misma vela, cuenta
el stop. Cierre forzado a las 18:00 UTC (20:00 del servidor). Una operación a la vez.
Costo por operación: spread 0,34 + deslizamiento 0,15 = 0,49 USD por onza (se resta en R).
"""
import sys
import numpy as np
import pandas as pd

COST = 0.49
df = pd.read_csv(sys.argv[1], index_col=0, parse_dates=True)
df.index = pd.to_datetime(df.index, utc=True)
c, h, l, o = df.close, df.high, df.low, df.open
ema = lambda s, n: s.ewm(span=n, adjust=False).mean()
tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
d = c.diff()
rsi2 = 100 - 100 / (1 + d.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
                    / (-d.clip(upper=0)).ewm(alpha=1 / 2, adjust=False).mean())
# Contexto de 1h (sin mirar el futuro: se usa la última vela de 1h ya cerrada)
c1h = c.resample("1h").last().dropna()
h20, h50 = ema(c1h, 20), ema(c1h, 50)
trend1h = np.sign(h20 - h50).shift(1).reindex(df.index, method="ffill")
mins = df.index.hour * 60 + df.index.minute
in_win = (mins >= 13 * 60) & (mins < 16 * 60 + 30)

def run(name, sig_long, sig_short, stop_dist, rr):
    trades, i, n = [], 0, len(df)
    idx = df.index
    while i < n - 1:
        sl_, ss_ = sig_long.iloc[i], sig_short.iloc[i]
        if in_win[i] and (sl_ or ss_):
            side = 1 if sl_ else -1
            j = i + 1
            if idx[j].date() != idx[i].date() or (idx[j] - idx[i]) > pd.Timedelta("15min"):
                i += 1; continue
            entry = o.iloc[j]; risk = stop_dist.iloc[i]
            if not np.isfinite(risk) or risk <= 0:
                i += 1; continue
            stop = entry - side * risk; tp = entry + side * rr * risk
            res = None
            k = j
            while k < n:
                if idx[k].date() != idx[j].date() or idx[k].hour * 60 + idx[k].minute >= 18 * 60:
                    res = side * (c.iloc[k - 1] - entry) / risk; break
                hit_stop = l.iloc[k] <= stop if side == 1 else h.iloc[k] >= stop
                hit_tp = h.iloc[k] >= tp if side == 1 else l.iloc[k] <= tp
                if hit_stop:
                    gap = (o.iloc[k] - stop) * side < 0 and k > j
                    res = side * ((o.iloc[k] if gap else stop) - entry) / risk; break
                if hit_tp:
                    res = rr; break
                k += 1
            if res is None:
                res = side * (c.iloc[-1] - entry) / risk
            res -= COST / risk
            trades.append((idx[j], side, res, risk))
            i = k + 1
        else:
            i += 1
    t = pd.DataFrame(trades, columns=["time", "side", "R", "risk"])
    return t

def report(name, t):
    if t.empty:
        print(f"{name}: sin operaciones"); return
    half = len(t) // 2
    def stats(x):
        w = x.R[x.R > 0].sum(); ls = -x.R[x.R < 0].sum()
        return f"n={len(x):3d} win={100*(x.R>0).mean():4.0f}% R/op={x.R.mean():+.3f} total={x.R.sum():+6.1f}R PF={w/ls if ls else float('inf'):.2f}"
    print(f"{name:<38} TODO {stats(t)}\n{'':<38} 1ª mitad {stats(t.iloc[:half])}\n{'':<38} 2ª mitad {stats(t.iloc[half:])}  | stop medio {t.risk.mean():.2f} USD, costo medio {COST/t.risk.mean():.2f}R")

# S1: retroceso a la EMA20 a favor de la tendencia de 1h; vela que cierra de vuelta
touch_l = (l <= e20) & (c > e20) & (c > o)
touch_s = (h >= e20) & (c < e20) & (c < o)
s1l = touch_l & (trend1h > 0) & (e20 > e50)
s1s = touch_s & (trend1h < 0) & (e20 < e50)
# S2: ruptura del rango 13:00-13:30 UTC (apertura de Londres-NY tardía) con filtro 1h
day = pd.Series(df.index.date, index=df.index)
sub = df[(mins >= 13 * 60) & (mins < 13 * 60 + 30)]
rng = sub.groupby(sub.index.date)
rh, rl = rng.high.max(), rng.low.min()
RH = day.map(rh); RL = day.map(rl)
after = mins >= 13 * 60 + 30
first_l = (c > RH) & after; first_s = (c < RL) & after
# solo la primera ruptura del día
fl = first_l & ~first_l.groupby(day).cumsum().shift(1, fill_value=0).astype(bool)
fs = first_s & ~first_s.groupby(day).cumsum().shift(1, fill_value=0).astype(bool)
s2l = fl & (trend1h > 0); s2s = fs & (trend1h < 0)
s2stop = (RH - RL).clip(lower=0.5)
# S3: RSI(2) extremo a favor de la tendencia (comprar caída en alcista)
s3l = (rsi2 < 10) & (c > e200) & (trend1h > 0)
s3s = (rsi2 > 90) & (c < e200) & (trend1h < 0)

print(f"Datos: {len(df)} velas de 5m, {df.index[0]:%Y-%m-%d} a {df.index[-1]:%Y-%m-%d}\n")
for rr in (1.5, 2.0):
    report(f"S1 retroceso EMA20 (stop 1,5 ATR, {rr}R)", run("s1", s1l, s1s, 1.5 * atr, rr))
    report(f"S2 ruptura rango 13:00-13:30 ({rr}R)", run("s2", s2l, s2s, s2stop, rr))
    report(f"S3 RSI2 extremo + tendencia ({rr}R)", run("s3", s3l, s3s, 1.5 * atr, rr))
    print()
# referencia: entradas al azar en la ventana (mismo stop/rr) para ver el costo puro
rng_ = np.random.default_rng(1)
rand = pd.Series(rng_.random(len(df)) < 0.01, index=df.index)
report("AZAR (referencia, 2R)", run("r", rand & (rng_.random(len(df)) < .5), rand, 1.5 * atr, 2.0))

print("\n-- variantes de S2 --")
for rr in (1.5, 2.0):
    report(f"S2 sin filtro 1h ({rr}R)", run("s2b", fl, fs, s2stop, rr))
    report(f"S2 stop = mitad del rango ({rr}R)", run("s2c", s2l, s2s, s2stop / 2, rr))
