"""Estudio de "HTF Level Breakout": base, mejoras una a una y combinación elegida
solo con 2023-2024 (validada en 2025-2026). Uso: python -m backtest.htf_estudio"""
from __future__ import annotations

import itertools
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from backtest.htf_breakout import BParams, frame, run, with_
from backtest.oro_estudio import metrics, monte_carlo
from backtest.oro_liquidez import Prepared, load_csv

IS0, IS1, OOS0 = "2023-01-01", "2025-01-01", "2025-01-01"
OUT = os.path.join(os.path.dirname(__file__), "resultados_htf")
_P = None


def _init(path):
    global _P
    _P = Prepared(load_csv(path))


def trades(kw):
    f = frame(run(_P, with_(BParams(), **kw)))
    return f[f.entry_time >= IS0].reset_index(drop=True) if not f.empty else f


def ev(item):
    name, kw = item
    f = trades(kw)
    last = str(_P.idx[-1].date())
    a, b = f[f.entry_time < IS1], f[f.entry_time >= OOS0]
    return {"nombre": name, "cambios": kw, "IS": metrics(a, IS0, IS1), "OOS": metrics(b, OOS0, last),
            "riesgo_usd_oz_mediano_OOS": round(float(b.risk.median()), 2) if len(b) else None,
            "usd_por_op_0.01lote_OOS": round(float(b.usd.mean()), 2) if len(b) else None}


VARIANTES = [
    ("BASE (script tal cual)", {}),
    ("sin cierre por hora", {"timeExit": False}),
    ("tendencia EMA200 1H", {"useTrend": True}),
    ("solo sesión Londres/NY", {"useSess": True}),
    ("ruptura ≥ 0,25 ATR", {"minBreakAtr": 0.25}),
    ("ruptura ≥ 0,5 ATR", {"minBreakAtr": 0.5}),
    ("cierre fuerte (30% extremo)", {"strongClose": 0.7}),
    ("no perseguir (≤ 1 ATR del nivel)", {"maxEntryAtr": 1.0}),
    ("stop ≤ 4 ATR", {"slMaxAtr": 4.0}),
    ("stop entre 1 y 4 ATR", {"slMinAtr": 1.0, "slMaxAtr": 4.0}),
    ("retesteo del nivel (8 velas)", {"retest": 8}),
    ("retesteo del nivel (16 velas)", {"retest": 16}),
    ("break-even a 1R", {"useBE": True}),
    ("RR 1,5", {"rr": 1.5}),
    ("RR 3", {"rr": 3.0}),
    ("pivotes 3/3", {"pivL": 3, "pivR": 3}),
    ("pivotes 10/10", {"pivL": 10, "pivR": 10}),
    ("stop primero (pesimista)", {"stopFirst": True}),
    ("sin costos", {"spread": 0.0, "slippage": 0.0}),
]

GRID = {
    "useTrend": [False, True],
    "useSess": [False, True],
    "minBreakAtr": [0.0, 0.25],
    "slMaxAtr": [0.0, 4.0],
    "retest": [0, 8],
    "rr": [1.5, 2.0, 3.0],
}


def main(path):
    os.makedirs(OUT, exist_ok=True)
    _init(path)
    res = {}
    with ProcessPoolExecutor(4, initializer=_init, initargs=(path,)) as pool:
        res["variantes"] = list(pool.map(ev, VARIANTES))
        keys = list(GRID)
        combos = [dict(zip(keys, c)) for c in itertools.product(*GRID.values())]
        grid = list(pool.map(ev, [(str(k), k) for k in combos], chunksize=4))
    d = pd.DataFrame([{**g["cambios"], "IS": g["IS"].get("expectativa_R"), "IS_n": g["IS"]["ops"],
                       "OOS": g["OOS"].get("expectativa_R"), "OOS_n": g["OOS"]["ops"]} for g in grid])
    d.to_csv(os.path.join(OUT, "grid.csv"), index=False)
    ok = d[d.IS_n >= 80]
    best = ok.sort_values("IS", ascending=False).iloc[0]
    chosen = {k: (bool(best[k]) if isinstance(GRID[k][0], bool) else type(GRID[k][0])(best[k])) for k in keys}
    res["grid"] = {"combinaciones": len(d), "correlacion_rangos_IS_OOS": round(d.IS.rank().corr(d.OOS.rank()), 3),
                   "%OOS_positivas": round(100 * (d.OOS > 0).mean(), 1), "elegida_con_IS": chosen,
                   "elegida": ev(("elegida", chosen))}
    last = str(_P.idx[-1].date())
    for nm, kw in (("base", {}), ("elegida", chosen)):
        f = trades(kw)
        f.to_csv(os.path.join(OUT, f"operaciones_{nm}.csv"), index=False)
        res[f"por_año_{nm}"] = {int(y): metrics(g, f"{y}-01-01", f"{y+1}-01-01") for y, g in f.groupby(f.entry_time.dt.year)}
        res[f"salidas_{nm}"] = f.reason.value_counts().to_dict()
        res[f"por_lado_{nm}"] = {("compras" if k > 0 else "ventas"): metrics(g, IS0, last) for k, g in f.groupby("side")}
        oos = f[f.entry_time >= OOS0]
        res[f"monte_carlo_OOS_{nm}"] = monte_carlo(oos.r.to_numpy(), oos.usd.to_numpy())
        res[f"usd_oz_{nm}"] = {int(y): {"usd_medio_por_op": round(g.usd.mean(), 2), "riesgo_mediano": round(g.risk.median(), 2),
                                        "peor_op": round(g.usd.min(), 2), "mejor_op": round(g.usd.max(), 2)}
                               for y, g in f.groupby(f.entry_time.dt.year)}
    json.dump(res, open(os.path.join(OUT, "resultados.json"), "w"), ensure_ascii=False, indent=1, default=str)
    print("listo")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/xauusd_15m_utc.csv")
