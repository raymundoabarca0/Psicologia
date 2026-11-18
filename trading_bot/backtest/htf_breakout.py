"""Traducción a Python de "HTF Level Breakout" (Pine v6) + variantes para filtrar
rupturas falsas.

Lógica original (HTF = diario, gráfico de 15m):
- Al empezar un día nuevo (y sin posición): niveles = máximo y mínimo del día anterior.
- La primera vela que TOCA un nivel guarda S1 (su máximo si es el de arriba, su mínimo
  si es el de abajo) y desactiva el otro lado.
- Entrada cuando una vela posterior CIERRA más allá del nivel y de S1 (ruptura).
- Stop en el último pivote (5,5) contrario; TP = RR × riesgo; cierre forzado a las
  22:00 UTC+3. Máximo una operación por día.

Mismas reglas de fidelidad que `oro_liquidez.py` (señal al cierre, entrada en la
apertura siguiente, stop/TP con la regla intrabar de TradingView).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from backtest.oro_liquidez import Prepared, Trade, _isnan, _pivots


@dataclass(frozen=True)
class BParams:
    pivL: int = 5
    pivR: int = 5
    rr: float = 2.0
    timeExit: bool = True
    exitHourUtc: int = 19          # 22:00 UTC+3
    exitMin: int = 0
    # Costos (USD por onza)
    spread: float = 0.30
    slippage: float = 0.10
    stopFirst: bool = False
    # ── Mejoras (todas apagadas = script original) ──
    useTrend: bool = False         # solo a favor de EMA 200 de 1H (vela cerrada)
    trendLen: int = 200
    useSess: bool = False          # solo entradas en Londres/NY
    sess: str = "0200-1200"        # hora de Nueva York
    minBreakAtr: float = 0.0       # el cierre debe pasar el nivel por al menos k ATR
    strongClose: float = 0.0       # cierre en el x% extremo de la vela (0.7 = 30% superior)
    slMinAtr: float = 0.0          # saltar si el stop está a menos de k ATR
    slMaxAtr: float = 0.0          # saltar si el stop está a más de k ATR (0 = sin límite)
    retest: int = 0                # >0: esperar retroceso al nivel (orden límite) por N velas
    maxEntryAtr: float = 0.0       # no perseguir: cierre a no más de k ATR del nivel
    useBE: bool = False
    beR: float = 1.0


def _sess(minutes: np.ndarray, s: str) -> np.ndarray:
    a, b = s.split("-")
    st, en = int(a[:2]) * 60 + int(a[2:]), int(b[:2]) * 60 + int(b[2:])
    return (minutes >= st) & (minutes < en) if st < en else (minutes >= st) | (minutes < en)


def run(prep: Prepared, p: BParams) -> list[Trade]:
    o, h, l, c, idx = prep.o, prep.h, prep.l, prep.c, prep.idx
    n = len(c)
    nan = float("nan")
    key = ("piv", p.pivL, p.pivR)
    if key not in prep._cache:
        if p.pivL == p.pivR:
            prep._cache[key] = (_pivots(h, p.pivL, True), _pivots(l, p.pivL, False))
        else:
            prep._cache[key] = _pivots_lr(h, l, p.pivL, p.pivR)
    ph, pl = prep._cache[key]
    atr, _ = prep.atr(14)
    hv = prep.htf(p.trendLen)
    inSess = _sess(prep.minutes, p.sess) if p.useSess else np.ones(n, bool)
    hours_utc = np.asarray(idx.hour)
    mins_utc = np.asarray(idx.minute)

    trades: list[Trade] = []
    lastPH = lastPL = nan
    levH = levL = nan
    hiAct = loAct = False
    s1H = s1L = nan
    s1HSet = s1LSet = False
    pos = 0
    pending = None
    tr = None
    curStop = curTp = nan
    closeNext = False
    limitOrder = None  # (side, price, stop, tp, risk, expira_en_i, signal_time)

    for i in range(n):
        # ── Apertura ──
        if closeNext and pos != 0:
            px = o[i] - pos * p.slippage
            _close(tr, idx[i], px, "hora", p)
            trades.append(tr)
            tr, pos, curStop, curTp = None, 0, nan, nan
        closeNext = False
        if pending is not None:
            side, sig_t, stop, tp, risk = pending
            pending = None
            tr = Trade(side, "Ruptura", sig_t, idx[i], o[i] + side * p.slippage, stop, tp, risk)
            pos, curStop, curTp = side, stop, tp

        # Orden límite de retesteo (vale desde la vela siguiente a la señal)
        if limitOrder is not None and pos == 0:
            side, lpx, stop, tp, risk, exp_i, sig_t = limitOrder
            if i > exp_i:
                limitOrder = None
            elif (side > 0 and l[i] <= lpx) or (side < 0 and h[i] >= lpx):
                fill = min(o[i], lpx) if side > 0 else max(o[i], lpx)
                tr = Trade(side, "Retesteo", sig_t, idx[i], fill, stop, tp, abs(fill - stop))
                pos, curStop, curTp = side, stop, tp
                limitOrder = None

        # ── Dentro de la vela: stop / TP ──
        if pos != 0:
            hi_first = (h[i] - o[i]) <= (o[i] - l[i])
            if p.stopFirst:
                hi_first = pos < 0
            ex = None
            if pos > 0:
                tpH, slH = h[i] >= curTp, l[i] <= curStop
                if o[i] <= curStop:
                    ex = (o[i], "stop")
                elif o[i] >= curTp:
                    ex = (o[i], "tp")
                elif tpH and slH:
                    ex = (curTp, "tp") if hi_first else (curStop, "stop")
                elif tpH:
                    ex = (curTp, "tp")
                elif slH:
                    ex = (curStop, "stop")
            else:
                tpH, slH = l[i] <= curTp, h[i] >= curStop
                if o[i] >= curStop:
                    ex = (o[i], "stop")
                elif o[i] <= curTp:
                    ex = (o[i], "tp")
                elif tpH and slH:
                    ex = (curStop, "stop") if hi_first else (curTp, "tp")
                elif tpH:
                    ex = (curTp, "tp")
                elif slH:
                    ex = (curStop, "stop")
            if ex is not None:
                px, why = ex
                if why == "stop":
                    px -= pos * p.slippage
                    if pos * (curStop - tr.entry) >= 0:
                        why = "break-even"
                _close(tr, idx[i], px, why, p)
                trades.append(tr)
                tr, pos, curStop, curTp = None, 0, nan, nan

        # ── Cierre de la vela ──
        if not _isnan(ph[i]):
            lastPH = ph[i]
        if not _isnan(pl[i]):
            lastPL = pl[i]
        inTrade = pos != 0 or pending is not None

        if prep.newday[i] and not inTrade:
            levH, levL = prep.pdh[i], prep.pdl[i]
            hiAct = loAct = True
            s1H = s1L = nan
            s1HSet = s1LSet = False
            limitOrder = None

        a = atr[i]
        if not inTrade and limitOrder is None:
            trendL = (not p.useTrend) or hv["close"][i] > hv["ema"][i]
            trendS = (not p.useTrend) or hv["close"][i] < hv["ema"][i]
            rngbar = h[i] - l[i]
            if hiAct and not _isnan(levH):
                if h[i] >= levH and not s1HSet:
                    s1H, s1HSet, loAct = h[i], True, False
                if s1HSet and c[i] > levH and c[i] > s1H:
                    sl = lastPL
                    if not _isnan(sl):
                        ok = trendL and inSess[i]
                        ok &= (c[i] - levH) >= p.minBreakAtr * a
                        ok &= p.strongClose <= 0 or (rngbar > 0 and (c[i] - l[i]) / rngbar >= p.strongClose)
                        ok &= p.maxEntryAtr <= 0 or (c[i] - levH) <= p.maxEntryAtr * a
                        risk = c[i] - sl
                        ok &= risk > 0 or (p.slMinAtr == 0 and p.slMaxAtr == 0)
                        ok &= risk >= p.slMinAtr * a
                        ok &= p.slMaxAtr <= 0 or risk <= p.slMaxAtr * a
                        if ok and risk != 0:
                            if p.retest > 0:
                                r2 = levH - sl
                                if r2 > 0:
                                    limitOrder = (1, levH, sl, levH + r2 * p.rr, r2, i + p.retest, idx[i])
                            elif i + 1 < n:
                                pending = (1, idx[i], sl, c[i] + risk * p.rr, abs(risk))
                    hiAct = False
            if loAct and not _isnan(levL) and pending is None and limitOrder is None:
                if l[i] <= levL and not s1LSet:
                    s1L, s1LSet, hiAct = l[i], True, False
                if s1LSet and c[i] < levL and c[i] < s1L:
                    sl = lastPH
                    if not _isnan(sl):
                        ok = trendS and inSess[i]
                        ok &= (levL - c[i]) >= p.minBreakAtr * a
                        ok &= p.strongClose <= 0 or (rngbar > 0 and (h[i] - c[i]) / rngbar >= p.strongClose)
                        ok &= p.maxEntryAtr <= 0 or (levL - c[i]) <= p.maxEntryAtr * a
                        risk = sl - c[i]
                        ok &= risk > 0 or (p.slMinAtr == 0 and p.slMaxAtr == 0)
                        ok &= risk >= p.slMinAtr * a
                        ok &= p.slMaxAtr <= 0 or risk <= p.slMaxAtr * a
                        if ok and risk != 0:
                            if p.retest > 0:
                                r2 = sl - levL
                                if r2 > 0:
                                    limitOrder = (-1, levL, sl, levL - r2 * p.rr, r2, i + p.retest, idx[i])
                            elif i + 1 < n:
                                pending = (-1, idx[i], sl, c[i] - risk * p.rr, abs(risk))
                    loAct = False

        # Break-even (opcional)
        if p.useBE and pos != 0 and tr is not None:
            if pos > 0 and h[i] >= tr.entry + p.beR * tr.risk:
                curStop = max(curStop, tr.entry + 0.05 * tr.risk)
            if pos < 0 and l[i] <= tr.entry - p.beR * tr.risk:
                curStop = min(curStop, tr.entry - 0.05 * tr.risk)

        # Cierre por hora (22:00 UTC+3 = 19:00 UTC): se ejecuta en la apertura siguiente
        if p.timeExit and pos != 0 and hours_utc[i] == p.exitHourUtc and mins_utc[i] == p.exitMin:
            closeNext = True

    return trades


def _close(tr: Trade, t, px: float, why: str, p: BParams):
    tr.exit_time, tr.exit, tr.reason = t, px, why
    tr.pnl_oz = tr.side * (px - tr.entry) - p.spread
    tr.r = tr.pnl_oz / tr.risk if tr.risk > 0 else np.nan
    tr.usd = tr.pnl_oz  # 1 onza = 0,01 lote


def _pivots_lr(h, l, left, right):
    ph, pl = np.full(len(h), np.nan), np.full(len(l), np.nan)
    for i in range(left + right, len(h)):
        k = i - right
        if h[k] > h[k - left:k].max() and h[k] >= h[k + 1:i + 1].max():
            ph[i] = h[k]
        if l[k] < l[k - left:k].min() and l[k] <= l[k + 1:i + 1].min():
            pl[i] = l[k]
    return ph, pl


def frame(trades: list[Trade]) -> pd.DataFrame:
    return pd.DataFrame([t.__dict__ for t in trades])


def with_(p: BParams, **kw) -> BParams:
    return replace(p, **kw)
