# Uso: python backtest/oro_5m_trend_meter.py <csv 5m XAU/USD> backtest/oro_5m_reglas.py
import sys, numpy as np, pandas as pd
src = open(sys.argv[2]).read().split('# S1:')[0]
sys.argv = [sys.argv[0], sys.argv[1]]
exec(src)
# Trend Meter (TradingView, Lij_MC): MACD 12/26/9 cruce, RSI13 > 50, RSI5 > 50
def rsi(s, n):
    d = s.diff(); up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)
macd = ema(c, 12) - ema(c, 26); sig = ema(macd, 9)
tm_up = (macd > sig) & (rsi(c, 13) > 50) & (rsi(c, 5) > 50)
tm_dn = (macd < sig) & (rsi(c, 13) < 50) & (rsi(c, 5) < 50)
tb1_up, tb1_dn = e20 > e50, e20 < e50
e240, e600 = ema(c, 240), ema(c, 600)
tb2_up, tb2_dn = e240 > e600, e240 < e600
day = pd.Series(df.index.date, index=df.index)
sub = df[(mins >= 13 * 60) & (mins < 13 * 60 + 30)]
rng = sub.groupby(sub.index.date); RH = day.map(rng.high.max()); RL = day.map(rng.low.min())
after = mins >= 13 * 60 + 30
fl = (c > RH) & after; fs = (c < RL) & after
fl = fl & ~fl.groupby(day).cumsum().shift(1, fill_value=0).astype(bool)
fs = fs & ~fs.groupby(day).cumsum().shift(1, fill_value=0).astype(bool)
stop = ((RH - RL) / 2).clip(lower=0.25)
print(f"Datos: {len(df)} velas 5m, {df.index[0]:%Y-%m-%d} a {df.index[-1]:%Y-%m-%d}\n")
V = {
 "S2c base (dirección 1h EMA20/50)": (fl & (trend1h > 0), fs & (trend1h < 0)),
 "S2c con dirección EMA240/600 en 5m": (fl & tb2_up, fs & tb2_dn),
 "S2c + 3 puntos del Trend Meter": (fl & (trend1h > 0) & tm_up, fs & (trend1h < 0) & tm_dn),
 "S2c + Trend Bar 1 (EMA20/50 5m)": (fl & (trend1h > 0) & tb1_up, fs & (trend1h < 0) & tb1_dn),
 "S2c + 3 puntos + Trend Bar 1": (fl & (trend1h > 0) & tm_up & tb1_up, fs & (trend1h < 0) & tm_dn & tb1_dn),
}
for k, (a, b) in V.items():
    report(k, run(k, a, b, stop, 2.0))
