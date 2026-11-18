"""Estudio completo de la estrategia Oro 1H/15m Liquidez v4.

Uso (desde trading_bot/):
    python -m backtest.oro_estudio data/xauusd_15m_utc.csv

Pasos: base, filtros uno por uno, walk-forward (optimiza 2023-2024, valida
2025-2026 sin tocar), sensibilidad ±20%, Monte Carlo y simulación de la cuenta
del usuario (100 USD, 0,01 lote, máx. 10% por operación).
Guarda todo en backtest/resultados_oro/ (json + csv).
"""

from __future__ import annotations

import itertools
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, fields

import numpy as np
import pandas as pd

from backtest.oro_liquidez import Params, Prepared, load_csv, run, with_

IS_START, IS_END = "2023-01-01", "2025-01-01"
OOS_START = "2025-01-01"
OUT = os.path.join(os.path.dirname(__file__), "resultados_oro")
R_MODE = dict(maxRiskPct=0.0)  # evaluar la estrategia en R, sin límite de cuenta

_DF: pd.DataFrame | None = None
_PREP: dict = {}


def _init(path: str):
    global _DF
    _DF = load_csv(path)


def _prep(end: str | None) -> Prepared:
    if end not in _PREP:
        _PREP[end] = Prepared(_DF if end is None else _DF[_DF.index < end])
    return _PREP[end]


def trades_of(p: Params, end: str | None = None) -> pd.DataFrame:
    f = run(_prep(end), p).frame()
    if f.empty:
        return f
    return f[f.entry_time >= IS_START].reset_index(drop=True)


def split(f: pd.DataFrame, a: str, b: str | None = None) -> pd.DataFrame:
    if f.empty:
        return f
    m = f.entry_time >= a
    if b:
        m &= f.entry_time < b
    return f[m]


# ───────────────────────── Métricas ─────────────────────────
def metrics(f: pd.DataFrame, start: str, end: str) -> dict:
    if f.empty:
        return {"ops": 0}
    r = f.r.to_numpy()
    wins, losses = r[r > 0], r[r <= 0]
    cum = np.cumsum(r)
    dd = float(np.max(np.maximum.accumulate(np.r_[0, cum])[1:] - cum)) if len(r) else 0.0
    days = pd.bdate_range(start, pd.Timestamp(end) - pd.Timedelta(days=1))
    daily = f.groupby(f.exit_time.dt.tz_convert(None).dt.normalize()).r.sum().reindex(days, fill_value=0.0)
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0
    streak = mx = 0
    for x in r:
        streak = streak + 1 if x <= 0 else 0
        mx = max(mx, streak)
    return {
        "ops": int(len(r)),
        "acierto_%": round(100 * len(wins) / len(r), 1),
        "profit_factor": round(wins.sum() / -losses.sum(), 2) if losses.sum() < 0 else None,
        "expectativa_R": round(float(r.mean()), 3),
        "error_std_R": round(float(r.std(ddof=1) / np.sqrt(len(r))), 3) if len(r) > 1 else None,
        "total_R": round(float(r.sum()), 1),
        "dd_max_R": round(dd, 1),
        "sharpe": round(sharpe, 2),
        "racha_perdedora": mx,
    }


def per_year(f: pd.DataFrame) -> dict:
    out = {}
    for y, g in f.groupby(f.entry_time.dt.year):
        out[int(y)] = metrics(g, f"{y}-01-01", f"{y + 1}-01-01")
    return out


def account(p: Params, start: str, end: str | None) -> dict:
    """Cuenta del usuario: arranca con 100 USD en `start`, 0,01 lote, máx. 10%."""
    d = _DF[_DF.index < end] if end else _DF
    warm = d[d.index >= pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=40)]
    res = run(Prepared(warm), with_(p, maxRiskPct=10.0, capital=100.0, qtyOz=1.0))
    f = res.frame()
    f = f[f.entry_time >= start] if not f.empty else f
    eq = np.r_[100.0, 100.0 + f.usd.cumsum().to_numpy()] if not f.empty else np.array([100.0])
    peak = np.maximum.accumulate(eq)
    return {
        "ops": int(len(f)),
        "saldo_final_usd": round(float(eq[-1]), 2),
        "saldo_minimo_usd": round(float(eq.min()), 2),
        "dd_max_%": round(float(((peak - eq) / peak).max() * 100), 1),
        "señales_saltadas_por_riesgo>10%": res.skipped_risk,
        "quebrada": bool(eq.min() < p.minEquity),
        "riesgo_medio_%_por_op": round(float((f.risk / (f.equity_after - f.usd)).mean() * 100), 1) if not f.empty else None,
    }


# ───────────────────────── Pasos ─────────────────────────
def _eval(args):
    name, kw, end = args
    p = with_(Params(**R_MODE), **kw)
    f = trades_of(p, end)
    out = {"nombre": name, "cambios": kw, "IS": metrics(split(f, IS_START, IS_END), IS_START, IS_END)}
    if end is None:
        out["OOS"] = metrics(split(f, OOS_START), OOS_START, str(_DF.index[-1].date()))
    return out


FILTERS = [
    ("BASE (script tal cual)", {}),
    ("sin vela de confirmación", {"useConfirm": False}),
    ("sin rango Asia", {"useAsia": False}),
    ("sin rupturas (solo barridos)", {"useBreakout": False}),
    ("sin barridos (solo rupturas)", {"useSweep": False}),
    ("sin zonas 50%", {"useZones": False}),
    ("sin filtro de noticias", {"useNews": False}),
    ("sin filtro de volatilidad", {"useVol": False}),
    ("sin filtro de tendencia 1H", {"useTrendFilter": False}),
    ("sin evitar PDH/PDL", {"avoidLevels": False}),
    ("sin sesión Londres/NY", {"useSess": False}),
    ("solo compras", {"allowShorts": False}),
    ("sin break-even", {"useBE": False}),
    ("break-even + trailing", {"useTrail": True}),
    ("solo trailing (sin BE)", {"useBE": False, "useTrail": True}),
    ("trailing sin TP", {"useTrail": True, "useTp": False}),
    ("TP 1,5R", {"rrTarget": 1.5}),
    ("TP 3R", {"rrTarget": 3.0}),
    ("con Supertrend 1H", {"useHtfSt": True}),
    ("con ADX 1H en rupturas", {"useAdx": True}),
    ("con pivotes 15m", {"usePivots": True}),
]

GRID = {
    "rrTarget": [1.5, 2.0, 2.5, 3.0],
    "atrMult": [1.5, 2.0, 2.5],
    "confirmBars": [2, 3, 5],
    "minAtrRatio": [0.5, 0.7, 0.9],
    "stopBuffer": [0.1, 0.2, 0.3],
}

SENS = ["emaTrendLen", "confirmBars", "rangeLen", "rangeAtrMult", "breakWindow", "minAtrRatio",
        "nearLevelAtr", "atrLen", "atrMult", "stopBuffer", "rrTarget", "beR"]


def walk_forward(pool) -> dict:
    keys = list(GRID)
    combos = list(itertools.product(*GRID.values()))
    jobs = [(str(c), dict(zip(keys, c)), IS_END) for c in combos]
    rows = list(pool.map(_eval, jobs, chunksize=4))
    table = {tuple(r["cambios"][k] for k in keys): r["IS"] for r in rows}

    def exp(c):
        m = table[c]
        return m["expectativa_R"] if m.get("ops", 0) >= 100 else -9.0

    def robust(c):  # promedio de la combinación y sus vecinas (meseta, no pico)
        vals = [exp(c)]
        for j, k in enumerate(keys):
            vs = GRID[k]
            pos = vs.index(c[j])
            for q in (pos - 1, pos + 1):
                if 0 <= q < len(vs):
                    vals.append(exp(c[:j] + (vs[q],) + c[j + 1:]))
        return float(np.mean(vals))

    best_raw = max(combos, key=exp)
    best_rob = max(combos, key=robust)
    pos_share = float(np.mean([exp(c) > 0 for c in combos]))
    out = {"combinaciones": len(combos), "%_combinaciones_IS_positivas": round(100 * pos_share, 1)}
    for name, c in (("mejor_IS_bruta", best_raw), ("mas_robusta_IS", best_rob)):
        kw = dict(zip(keys, c))
        full = _eval((name, kw, None))
        out[name] = {"parametros": kw, "IS": full["IS"], "OOS": full["OOS"],
                     "score_meseta_IS": round(robust(c), 3)}
    return out


def sensitivity(pool, base_kw: dict) -> list:
    base = with_(Params(**R_MODE), **base_kw)
    jobs = []
    for k in SENS:
        v = getattr(base, k)
        for f in (0.8, 1.2):
            nv = type(v)(round(v * f)) if isinstance(v, int) else round(v * f, 3)
            if nv == v:
                nv = v - 1 if f < 1 else v + 1
            jobs.append((f"{k} {'-' if f < 1 else '+'}20% ({nv})", {**base_kw, k: nv}, None))
    jobs.insert(0, ("referencia", base_kw, None))
    return list(pool.map(_eval, jobs))


def monte_carlo(r: np.ndarray, usd: np.ndarray, n=1000, seed=7) -> dict:
    rng = np.random.default_rng(seed)
    dd_r, streaks, end_r, dd_usd, ruin = [], [], [], [], 0
    for _ in range(n):
        ix = rng.integers(0, len(r), len(r))  # remuestreo con reemplazo
        s = r[ix]
        cum = np.cumsum(s)
        dd_r.append(np.max(np.maximum.accumulate(np.r_[0, cum])[1:] - cum))
        end_r.append(cum[-1])
        k = mx = 0
        for x in s:
            k = k + 1 if x <= 0 else 0
            mx = max(mx, k)
        streaks.append(mx)
        if len(usd):
            u = 100 + np.cumsum(usd[rng.integers(0, len(usd), len(usd))])
            pk = np.maximum.accumulate(np.r_[100, u])[1:]
            dd_usd.append(np.max((pk - u) / pk) * 100)
            ruin += u.min() < 20
    q = lambda a, p: round(float(np.percentile(a, p)), 1)
    out = {
        "simulaciones": n, "ops_por_simulacion": int(len(r)),
        "dd_R_mediana": q(dd_r, 50), "dd_R_peor_5%": q(dd_r, 95), "dd_R_peor_1%": q(dd_r, 99),
        "racha_perdedora_mediana": q(streaks, 50), "racha_perdedora_peor_5%": q(streaks, 95),
        "total_R_p5": q(end_r, 5), "total_R_mediana": q(end_r, 50), "total_R_p95": q(end_r, 95),
        "prob_total_R_negativo_%": round(100 * float(np.mean(np.array(end_r) < 0)), 1),
    }
    if len(usd):
        out.update({"cuenta100_dd_%_mediana": q(dd_usd, 50), "cuenta100_dd_%_peor_5%": q(dd_usd, 95),
                    "cuenta100_prob_quiebra_%": round(100 * ruin / n, 1)})
    return out


def main(path: str):
    _init(path)
    os.makedirs(OUT, exist_ok=True)
    last = str(_DF.index[-1].date())
    res: dict = {"datos": {"archivo": path, "desde": str(_DF.index[0]), "hasta": str(_DF.index[-1]),
                           "velas": len(_DF)},
                 "costos": {k: getattr(Params(), k) for k in ("spread", "slippage", "commPct")}}

    base = trades_of(Params(**R_MODE))
    base.to_csv(os.path.join(OUT, "operaciones_base.csv"), index=False)
    res["base"] = {"total": metrics(base, IS_START, last), "IS": metrics(split(base, IS_START, IS_END), IS_START, IS_END),
                   "OOS": metrics(split(base, OOS_START), OOS_START, last), "por_año": per_year(base),
                   "por_tipo": {k: metrics(g, IS_START, last) for k, g in base.groupby("kind")},
                   "por_lado": {("compras" if k > 0 else "ventas"): metrics(g, IS_START, last) for k, g in base.groupby("side")}}
    # Mismos costos que el .pine (0,01% por lado + 3 ticks) como contraste
    pine = trades_of(with_(Params(**R_MODE), spread=0.0, slippage=0.03, commPct=0.01))
    res["base_costos_del_pine"] = metrics(pine, IS_START, last)
    res["base_sin_costos"] = metrics(trades_of(with_(Params(**R_MODE), spread=0.0, slippage=0.0)), IS_START, last)
    print("base listo", flush=True)

    with ProcessPoolExecutor(4, initializer=_init, initargs=(path,)) as pool:
        res["filtros"] = list(pool.map(_eval, [(n, kw, None) for n, kw in FILTERS]))
        print("filtros listos", flush=True)
        res["walk_forward"] = walk_forward(pool)
        print("walk-forward listo", flush=True)
        chosen = res["walk_forward"]["mas_robusta_IS"]["parametros"]
        res["sensibilidad_base"] = sensitivity(pool, {})
        res["sensibilidad_robusta"] = sensitivity(pool, chosen)
        print("sensibilidad lista", flush=True)

    for name, kw in (("base", {}), ("robusta", chosen)):
        f = trades_of(with_(Params(**R_MODE), **kw))
        oos = split(f, OOS_START)
        acc_f = run(Prepared(_DF), with_(Params(), **kw, maxRiskPct=0.0)).frame()
        usd = split(acc_f, OOS_START).usd.to_numpy() if not acc_f.empty else np.array([])
        res[f"monte_carlo_OOS_{name}"] = monte_carlo(oos.r.to_numpy(), usd)
        res[f"cuenta_usuario_{name}"] = {"2023-2026": account(with_(Params(), **kw), IS_START, None),
                                         "solo 2025-2026": account(with_(Params(), **kw), OOS_START, None)}
    with open(os.path.join(OUT, "resultados.json"), "w") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    print("listo:", os.path.join(OUT, "resultados.json"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/xauusd_15m_utc.csv")
