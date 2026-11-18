"""Traducción a Python de `Oro_1H_15m_liquidez.pine` (v4) para backtest.

Reglas de fidelidad con TradingView:
- La señal se calcula al CIERRE de la vela de 15m; la orden de mercado se llena
  en la APERTURA de la vela siguiente (como `strategy.entry` sin process_orders_on_close).
- Tendencia 1H: EMA/Supertrend/ADX de la vela de 1H ANTERIOR ya cerrada
  (equivale a `request.security(..., expr[1], lookahead_on)`).
- PDH/PDL: máximo/mínimo del día ANTERIOR ya cerrado. Día de TradingView para
  oro/forex: 17:00 a 17:00 de Nueva York.
- Stop/TP dentro de la vela: misma regla del emulador de TradingView
  (si el máximo está más cerca de la apertura: apertura→máximo→mínimo→cierre).
- Break-even/trailing se calculan al cierre de la vela y valen desde la siguiente.

Diferencias conocidas (documentadas en el reporte):
- No se emulan `strategy.risk.max_intraday_loss` ni `max_drawdown`: con lote fijo
  de 0,01 y 100 USD cada stop ya pesa más que el 3% diario. Se evalúa en R.
- Costos propios tipo broker (spread + slippage), no la comisión % del script.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache

import numpy as np
import pandas as pd

NY = "America/New_York"


# ───────────────────────── Parámetros ─────────────────────────
@dataclass(frozen=True)
class Params:
    # Tendencia 1H
    emaTrendLen: int = 200
    useTrendFilter: bool = True
    useHtfSt: bool = False
    useAdx: bool = False
    adxMin: float = 20.0
    # Liquidez
    useSweep: bool = True
    useAsia: bool = True
    asiaSess: str = "1900-0200"
    usePivots: bool = False
    pivLen: int = 5
    useConfirm: bool = True
    confirmBars: int = 3
    useZones: bool = True
    # Rupturas
    useBreakout: bool = True
    rangeLen: int = 20
    rangeAtrMult: float = 3.0
    breakWindow: int = 12
    useSt15: bool = False
    stFactor: float = 3.0
    stLen: int = 10
    # Filtros
    allowShorts: bool = True
    useSess: bool = True
    sess: str = "0200-1200"
    useNews: bool = True
    useVol: bool = True
    minAtrRatio: float = 0.7
    maxTrades: int = 2
    avoidLevels: bool = True
    nearLevelAtr: float = 0.5
    # Salidas
    atrLen: int = 14
    atrMult: float = 2.0
    stopBuffer: float = 0.2
    useTp: bool = True
    rrTarget: float = 2.0
    useBE: bool = True
    beR: float = 1.0
    useTrail: bool = False
    # Costos (USD por onza)
    spread: float = 0.30      # se paga una vez por operación (ida y vuelta)
    slippage: float = 0.10    # en la entrada (mercado) y en salidas por stop
    commPct: float = 0.0      # comisión % por lado (el .pine usa 0.01)
    # Cuenta del usuario (simulación en USD)
    capital: float = 100.0
    qtyOz: float = 1.0        # 0,01 lote = 1 onza
    maxRiskPct: float = 10.0  # si el stop cuesta más que esto, no se entra (0 = sin límite: modo R)
    minEquity: float = 20.0   # debajo de esto no alcanza el margen de 0,01 lote: cuenta quebrada


@dataclass
class Trade:
    side: int            # +1 largo, -1 corto
    kind: str            # "Barrido" / "Ruptura"
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    entry: float
    stop0: float
    tp: float
    risk: float          # distancia al stop desde el cierre de la señal (1R del script)
    exit_time: pd.Timestamp | None = None
    exit: float = np.nan
    reason: str = ""
    pnl_oz: float = 0.0  # USD por onza, después de costos
    r: float = 0.0       # resultado neto en R
    usd: float = 0.0     # resultado en USD con la cuenta del usuario
    equity_after: float = np.nan


@dataclass
class Result:
    params: Params
    trades: list[Trade] = field(default_factory=list)
    skipped_risk: int = 0   # señales no tomadas por superar el riesgo máximo

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([t.__dict__ for t in self.trades])


# ───────────────────────── Indicadores estilo Pine ─────────────────────────
def _sma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def _rma(x: np.ndarray, n: int) -> np.ndarray:
    """ta.rma: arranca con la SMA de las primeras n, luego alpha = 1/n."""
    out = np.full(len(x), np.nan)
    alpha = 1.0 / n
    s = np.nan
    vals = []
    for i, v in enumerate(x):
        if np.isnan(v):
            continue
        if np.isnan(s):
            vals.append(v)
            if len(vals) == n:
                s = float(np.mean(vals))
                out[i] = s
        else:
            s = alpha * v + (1 - alpha) * s
            out[i] = s
    return out


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    """ta.ema: arranca con la SMA de las primeras n, luego alpha = 2/(n+1)."""
    out = np.full(len(x), np.nan)
    alpha = 2.0 / (n + 1)
    if len(x) < n:
        return out
    s = float(np.mean(x[:n]))
    out[n - 1] = s
    for i in range(n, len(x)):
        s = alpha * x[i] + (1 - alpha) * s
        out[i] = s
    return out


def _tr(h, l, c):
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    tr[0] = h[0] - l[0]
    return tr


def _atr(h, l, c, n):
    return _rma(_tr(h, l, c), n)


def _supertrend(h, l, c, factor, n):
    atr = _atr(h, l, c, n)
    src = (h + l) / 2
    up0, lo0 = src + factor * atr, src - factor * atr
    m = len(c)
    upper, lower = np.full(m, np.nan), np.full(m, np.nan)
    st, d = np.full(m, np.nan), np.full(m, np.nan)
    for i in range(m):
        if np.isnan(atr[i]):
            continue
        pl = lower[i - 1] if i and not np.isnan(lower[i - 1]) else 0.0
        pu = upper[i - 1] if i and not np.isnan(upper[i - 1]) else 0.0
        lo = lo0[i] if (lo0[i] > pl or c[i - 1] < pl) else pl
        up = up0[i] if (up0[i] < pu or c[i - 1] > pu) else pu
        lower[i], upper[i] = lo, up
        if i == 0 or np.isnan(atr[i - 1]):
            di = 1
        elif st[i - 1] == pu:
            di = -1 if c[i] > up else 1
        else:
            di = 1 if c[i] < lo else -1
        d[i] = di
        st[i] = lo if di == -1 else up
    return st, d


def _adx(h, l, c, n=14):
    up = np.r_[np.nan, np.diff(h)]
    dn = -np.r_[np.nan, np.diff(l)]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pdm[0] = mdm[0] = np.nan
    tr = _rma(_tr(h, l, c), n)
    plus = 100 * _rma(pdm, n) / tr
    minus = 100 * _rma(mdm, n) / tr
    s = plus + minus
    return 100 * _rma(np.abs(plus - minus) / np.where(s == 0, 1, s), n)


def _session_mask(minutes: np.ndarray, sess: str) -> np.ndarray:
    a, b = sess.split("-")
    s = int(a[:2]) * 60 + int(a[2:])
    e = int(b[:2]) * 60 + int(b[2:])
    return (minutes >= s) & (minutes < e) if s < e else (minutes >= s) | (minutes < e)


def _pivots(x: np.ndarray, n: int, high: bool) -> np.ndarray:
    """ta.pivothigh/low(x, n, n): valor confirmado n velas después del pivote."""
    out = np.full(len(x), np.nan)
    for i in range(2 * n, len(x)):
        c = x[i - n]
        left, right = x[i - 2 * n:i - n], x[i - n + 1:i + 1]
        if high and c > left.max() and c >= right.max():
            out[i] = c
        if not high and c < left.min() and c <= right.min():
            out[i] = c
    return out


# ───────────────────────── Datos y precálculos ─────────────────────────
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    df = df.set_index("time_utc").sort_index()
    df = df[~df.index.duplicated()].astype(float)
    # Solo horario real del oro (como en MetaTrader): domingo 18:00 a viernes 17:00 NY,
    # sin la pausa diaria de 17:00 a 18:00 NY. Desde 2025 el proveedor trae velas
    # sintéticas en fin de semana que no existen en el broker.
    ny = df.index.tz_convert(NY)
    dow, hr = ny.dayofweek, ny.hour
    closed = (dow == 5) | ((dow == 6) & (hr < 18)) | ((dow == 4) & (hr >= 17)) | (hr == 17)
    return df[~closed]


class Prepared:
    """Columnas que dependen solo de los datos (y de pocos parámetros, en caché)."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.idx = df.index
        self.o, self.h = df["open"].to_numpy(), df["high"].to_numpy()
        self.l, self.c = df["low"].to_numpy(), df["close"].to_numpy()
        ny = df.index.tz_convert(NY)
        self.minutes = np.asarray(ny.hour * 60 + ny.minute)
        self.wednesday = np.asarray(ny.dayofweek == 2)
        # Día de TradingView para oro/forex: de 17:00 a 17:00 NY.
        dkey = (ny + pd.Timedelta(hours=7)).normalize().tz_localize(None)
        self.daykey = dkey.to_numpy()
        daily = pd.DataFrame({"h": self.h, "l": self.l, "k": dkey}).groupby("k").agg(h=("h", "max"), l=("l", "min"))
        prev = daily.shift(1)
        self.pdh = prev["h"].reindex(dkey).to_numpy()
        self.pdl = prev["l"].reindex(dkey).to_numpy()
        self.newday = np.r_[True, self.daykey[1:] != self.daykey[:-1]]
        self._cache: dict = {}

    def htf(self, ema_len: int):
        key = ("htf", ema_len)
        if key not in self._cache:
            hb = self.idx.floor("1h")
            g = pd.DataFrame({"o": self.o, "h": self.h, "l": self.l, "c": self.c}, index=hb).groupby(level=0)
            hr = pd.DataFrame({"h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last()})
            h, l, c = hr["h"].to_numpy(), hr["l"].to_numpy(), hr["c"].to_numpy()
            ema = _ema(c, ema_len)
            _, sd = _supertrend(h, l, c, 3.0, 10)
            adx = _adx(h, l, c, 14)
            vals = pd.DataFrame({"ema": ema, "dir": sd, "adx": adx, "close": c}, index=hr.index).shift(1)
            self._cache[key] = {k: vals[k].reindex(hb).to_numpy() for k in vals}
        return self._cache[key]

    def atr(self, n: int):
        key = ("atr", n)
        if key not in self._cache:
            a = _atr(self.h, self.l, self.c, n)
            self._cache[key] = (a, _sma(a, 96))
        return self._cache[key]

    def st15(self, f: float, n: int):
        key = ("st", f, n)
        if key not in self._cache:
            self._cache[key] = _supertrend(self.h, self.l, self.c, f, n)
        return self._cache[key]

    def rng(self, n: int):
        key = ("rng", n)
        if key not in self._cache:
            hi = pd.Series(self.h).rolling(n, min_periods=n).max().shift(1).to_numpy()
            lo = pd.Series(self.l).rolling(n, min_periods=n).min().shift(1).to_numpy()
            self._cache[key] = (hi, lo)
        return self._cache[key]

    def piv(self, n: int):
        key = ("piv", n)
        if key not in self._cache:
            self._cache[key] = (_pivots(self.h, n, True), _pivots(self.l, n, False))
        return self._cache[key]

    def sess(self, s: str):
        key = ("sess", s)
        if key not in self._cache:
            self._cache[key] = _session_mask(self.minutes, s)
        return self._cache[key]


# ───────────────────────── Motor ─────────────────────────
def _size_ok(p: Params, risk: float, equity: float) -> bool:
    if p.maxRiskPct <= 0:          # modo R: se evalúa la estrategia, no la cuenta
        return True
    if equity < p.minEquity:       # cuenta quebrada: ya no se puede operar
        return False
    return risk * p.qtyOz <= equity * p.maxRiskPct / 100

def _isnan(x: float) -> bool:
    return x != x


def run(prep: Prepared, p: Params) -> Result:
    o, h, l, c = prep.o, prep.h, prep.l, prep.c
    idx = prep.idx
    n = len(c)
    nan = float("nan")

    hv = prep.htf(p.emaTrendLen)
    hEma, hDir, hAdx, hClose = hv["ema"], hv["dir"], hv["adx"], hv["close"]
    atr, atrAvg = prep.atr(p.atrLen)
    st, stDir = prep.st15(p.stFactor, p.stLen) if (p.useSt15 or p.useTrail) else (np.full(n, nan),) * 2
    rngHi, rngLo = prep.rng(p.rangeLen)
    ph, pl = prep.piv(p.pivLen) if p.usePivots else (np.full(n, nan),) * 2
    inAsiaA = prep.sess(p.asiaSess)
    inSessA = prep.sess(p.sess) if p.useSess else np.ones(n, bool)
    news = (prep.sess("0815-0915") | (prep.wednesday & prep.sess("1345-1500"))) if p.useNews else np.zeros(n, bool)
    pdh, pdl, newday = prep.pdh, prep.pdl, prep.newday

    res = Result(p)
    equity = p.capital

    tradesToday = 0
    asHi = asLo = asHiF = asLoF = nan
    boxHi = boxLo = nan
    rangeEndBar = None
    boxStarted = False
    liqHi = liqLo = nan
    pLLow = pLHigh = pSHigh = pSLow = nan
    pLBar = pSBar = None
    prevIsRange = False

    pos = 0               # posición al cierre de la vela anterior / actual
    pending = None        # orden de entrada para la apertura siguiente
    tr: Trade | None = None
    curStop = curTp = nan
    entryRisk = nan

    for i in range(n):
        # ── 1) Apertura: llenar entrada pendiente ──
        if pending is not None:
            side, kind, sig_t, stop, tp, risk = pending
            pending = None
            fill = o[i] + side * p.slippage
            tr = Trade(side, kind, sig_t, idx[i], fill, stop, tp, risk)
            pos, curStop, curTp, entryRisk = side, stop, tp, risk

        # ── 2) Dentro de la vela: stop / take profit ──
        if pos != 0:
            hi_first = (h[i] - o[i]) <= (o[i] - l[i])
            exit_px, why = None, ""
            if pos > 0:
                tp_hit = not _isnan(curTp) and h[i] >= curTp
                sl_hit = l[i] <= curStop
                if o[i] <= curStop:
                    exit_px, why = o[i], "stop"
                elif not _isnan(curTp) and o[i] >= curTp:
                    exit_px, why = o[i], "tp"
                elif tp_hit and sl_hit:
                    exit_px, why = (curTp, "tp") if hi_first else (curStop, "stop")
                elif tp_hit:
                    exit_px, why = curTp, "tp"
                elif sl_hit:
                    exit_px, why = curStop, "stop"
            else:
                tp_hit = not _isnan(curTp) and l[i] <= curTp
                sl_hit = h[i] >= curStop
                if o[i] >= curStop:
                    exit_px, why = o[i], "stop"
                elif not _isnan(curTp) and o[i] <= curTp:
                    exit_px, why = o[i], "tp"
                elif tp_hit and sl_hit:
                    exit_px, why = (curStop, "stop") if hi_first else (curTp, "tp")
                elif tp_hit:
                    exit_px, why = curTp, "tp"
                elif sl_hit:
                    exit_px, why = curStop, "stop"
            if exit_px is not None:
                if why == "stop":
                    exit_px -= pos * p.slippage
                    if abs(curStop - tr.entry) <= 0.2 * tr.risk:
                        why = "break-even"
                    elif pos * (curStop - tr.entry) > 0:
                        why = "stop en ganancia"
                gross = pos * (exit_px - tr.entry)
                comm = p.commPct / 100 * (tr.entry + exit_px)
                tr.exit_time, tr.exit, tr.reason = idx[i], exit_px, why
                tr.pnl_oz = gross - p.spread - comm
                tr.r = tr.pnl_oz / tr.risk
                tr.usd = tr.pnl_oz * p.qtyOz
                equity += tr.usd
                tr.equity_after = equity
                res.trades.append(tr)
                tr, pos = None, 0
                curStop = curTp = nan

        # ── 3) Cierre de la vela: lógica del script ──
        if newday[i]:
            tradesToday = 0

        ci, hi_, lo_, a = c[i], h[i], l[i], atr[i]
        inAsia = inAsiaA[i]
        inAsiaPrev = inAsiaA[i - 1] if i else False

        # Rango asiático
        if inAsia and not inAsiaPrev:
            asHi, asLo, asHiF, asLoF = hi_, lo_, nan, nan
        elif inAsia:
            asHi, asLo = max(asHi, hi_), min(asLo, lo_)
        if not inAsia and inAsiaPrev:
            asHiF, asLoF = asHi, asLo

        # Acumulación
        rh, rl = rngHi[i], rngLo[i]
        isRange = (not _isnan(rh)) and (not _isnan(a)) and (rh - rl) <= p.rangeAtrMult * a
        if isRange:
            if not prevIsRange or not boxStarted:
                boxHi, boxLo, boxStarted = rh, rl, True
            else:
                boxHi, boxLo = max(boxHi, rh), min(boxLo, rl)
            rangeEndBar = i
        prevIsRange = isRange
        recentRange = rangeEndBar is not None and i - rangeEndBar <= p.breakWindow
        cprev = c[i - 1] if i else nan
        breakUp = recentRange and not _isnan(boxHi) and ci > boxHi and cprev <= boxHi
        breakDown = recentRange and not _isnan(boxLo) and ci < boxLo and cprev >= boxLo

        # Pivotes
        if not _isnan(ph[i]):
            liqHi = ph[i]
        if not _isnan(pl[i]):
            liqLo = pl[i]

        def below(lvl):
            return (not _isnan(lvl)) and lo_ < lvl and ci > lvl

        def above(lvl):
            return (not _isnan(lvl)) and hi_ > lvl and ci < lvl

        rawSweepLow = below(pdl[i]) or (p.useAsia and not inAsia and below(asLoF)) or (p.usePivots and below(liqLo))
        rawSweepHigh = above(pdh[i]) or (p.useAsia and not inAsia and above(asHiF)) or (p.usePivots and above(liqHi))
        if not _isnan(liqHi) and hi_ > liqHi:
            liqHi = nan
        if not _isnan(liqLo) and lo_ < liqLo:
            liqLo = nan

        # Tendencia 1H (vela anterior cerrada)
        he, hc, hd = hEma[i], hClose[i], hDir[i]
        htfBull = (hc > he) and (not p.useHtfSt or hd < 0)
        htfBear = (hc < he) and (not p.useHtfSt or hd > 0)
        adxOk = (not p.useAdx) or (hAdx[i] >= p.adxMin)
        trendLongOk = (not p.useTrendFilter) or htfBull
        trendShortOk = (not p.useTrendFilter) or htfBear

        eq = (pdh[i] + pdl[i]) / 2
        longSetupOk = p.useSweep and trendLongOk and ((not p.useZones) or ci <= eq)
        shortSetupOk = p.useSweep and p.allowShorts and trendShortOk and ((not p.useZones) or ci >= eq)

        # Barridos pendientes de confirmación
        if pLBar is not None and i > pLBar and (i - pLBar > p.confirmBars or lo_ < pLLow):
            pLBar = None
        if pSBar is not None and i > pSBar and (i - pSBar > p.confirmBars or hi_ > pSHigh):
            pSBar = None
        if rawSweepLow and longSetupOk:
            pLLow, pLHigh, pLBar = lo_, hi_, i
        if rawSweepHigh and shortSetupOk:
            pSHigh, pSLow, pSBar = hi_, lo_, i

        if p.useConfirm:
            longSweepNow = pLBar is not None and i > pLBar and ci > pLHigh
            shortSweepNow = pSBar is not None and i > pSBar and ci < pSLow
            sweepStopL, sweepStopS = pLLow, pSHigh
        else:
            longSweepNow = rawSweepLow and longSetupOk
            shortSweepNow = rawSweepHigh and shortSetupOk
            sweepStopL, sweepStopS = lo_, hi_

        nearOkLong = (not p.avoidLevels) or _isnan(pdh[i]) or ci >= pdh[i] or (pdh[i] - ci) >= p.nearLevelAtr * a
        nearOkShort = (not p.avoidLevels) or _isnan(pdl[i]) or ci <= pdl[i] or (ci - pdl[i]) >= p.nearLevelAtr * a

        sd = stDir[i]
        longBreak = p.useBreakout and breakUp and trendLongOk and adxOk and ((not p.useSt15) or sd < 0)
        shortBreak = p.useBreakout and p.allowShorts and breakDown and trendShortOk and adxOk and ((not p.useSt15) or sd > 0)

        volOk = (not p.useVol) or _isnan(atrAvg[i]) or a >= atrAvg[i] * p.minAtrRatio
        flat = pos == 0
        canTrade = flat and inSessA[i] and not news[i] and volOk and tradesToday < p.maxTrades
        longSignal = canTrade and nearOkLong and (longSweepNow or longBreak)
        shortSignal = canTrade and nearOkShort and (shortSweepNow or shortBreak) and not longSignal

        if longSignal and i + 1 < n:
            kind = "Barrido" if longSweepNow else "Ruptura"
            struct = (sweepStopL if longSweepNow else boxLo) - p.stopBuffer * a
            stop = min(max(struct, ci - p.atrMult * a), ci - 0.3 * a)
            risk = ci - stop
            tp = ci + p.rrTarget * risk if p.useTp else nan
            if risk > 0 and _size_ok(p, risk, equity):
                tradesToday += 1
                pLBar = None
                pending = (1, kind, idx[i], stop, tp, risk)
            elif risk > 0:
                res.skipped_risk += 1
        if shortSignal and i + 1 < n:
            kind = "Barrido" if shortSweepNow else "Ruptura"
            struct = (sweepStopS if shortSweepNow else boxHi) + p.stopBuffer * a
            stop = max(min(struct, ci + p.atrMult * a), ci + 0.3 * a)
            risk = stop - ci
            tp = ci - p.rrTarget * risk if p.useTp else nan
            if risk > 0 and _size_ok(p, risk, equity):
                tradesToday += 1
                pSBar = None
                pending = (-1, kind, idx[i], stop, tp, risk)
            elif risk > 0:
                res.skipped_risk += 1

        # Gestión: break-even y trailing (el stop nunca se afloja)
        if pos > 0:
            if p.useBE and hi_ >= tr.entry + p.beR * entryRisk:
                curStop = max(curStop, tr.entry + 0.05 * entryRisk)
            if p.useTrail and stDir[i] < 0:
                curStop = max(curStop, st[i])
        elif pos < 0:
            if p.useBE and lo_ <= tr.entry - p.beR * entryRisk:
                curStop = min(curStop, tr.entry - 0.05 * entryRisk)
            if p.useTrail and stDir[i] > 0:
                curStop = min(curStop, st[i])

    return res


def with_(p: Params, **kw) -> Params:
    return replace(p, **kw)
