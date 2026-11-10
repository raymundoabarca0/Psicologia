import sys, numpy as np, pandas as pd
exec(open(__file__.replace('oro_5m_regla_usuario.py', 'oro_5m_reglas.py')).read().split('# S1:')[0])   # reutiliza datos, indicadores y run()/report()
c15 = c.resample("15min").last().dropna()
t15 = np.sign(ema(c15, 20) - ema(c15, 50)).shift(1).reindex(df.index, method="ffill")
t5 = np.sign(e20 - e50)
for nbars in (6, 12):
    rh_ = h.shift(1).rolling(nbars).max(); rl_ = l.shift(1).rolling(nbars).min()
    width = (rh_ - rl_)
    sl = (c > rh_) & (t5 > 0) & (t15 > 0); ss = (c < rl_) & (t5 < 0) & (t15 < 0)
    for wname, (a, b) in {"09:00-18:30 serv": (7*60, 16*60+30), "15:00-18:30 serv": (13*60, 16*60+30)}.items():
        in_win[:] = (mins >= a) & (mins < b)
        for stop_name, sd in (("medio rango", width / 2), ("rango completo", width)):
            report(f"Tu regla: rango {nbars*5}min, {wname}, stop {stop_name}", run("u", sl, ss, sd.clip(lower=1.0), 2.0))
