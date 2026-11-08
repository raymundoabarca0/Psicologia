"""Descarga de velas para el experimento de señales en paper.

Fuentes:
- BTC: BTCUSDT del espejo público de datos de Binance (sin API key).
- Oro: XAU/USD y euro: EUR/USD de Twelve Data (precio real de forex), desde el
  2026-11-06. La API key la inyecta el proxy del entorno en las peticiones a
  api.twelvedata.com; si se corre fuera de ese entorno, se puede poner en la
  variable TWELVEDATA_API_KEY.
- Las señales antiguas (PAXGUSDT, EURUSDT) se siguen evaluando con Binance, en
  los mismos precios con los que se dieron. PAXG y EURUSDT son sustitutos con una
  pequeña diferencia frente a XAU/USD y EUR/USD.
"""

from __future__ import annotations

import os
import time

import pandas as pd
import requests

BASE = "https://data-api.binance.vision/api/v3"
TD_BASE = "https://api.twelvedata.com"
ASSETS = {"BTC": "BTCUSDT", "ORO": "XAU/USD", "EUR": "EUR/USD"}
# Sustitutos de Binance usados hasta el 2026-11-05 (para comparar o si Twelve Data falla).
BINANCE_PROXY = {"XAU/USD": "PAXGUSDT", "EUR/USD": "EURUSDT"}

TD_SYMBOLS = {"XAU/USD", "EUR/USD"}   # además, cualquier símbolo con "/" va a Twelve Data
TD_INTERVAL = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
               "1h": "1h", "4h": "4h", "1d": "1day"}
TD_PAGE = 5000            # máximo de velas por petición
TD_PER_MIN = 7            # el plan basic permite 8 por minuto; dejamos 1 de margen
_td_calls: list[float] = []


class MarketDataError(RuntimeError):
    pass


def _bar_delta(interval: str) -> pd.Timedelta:
    return pd.Timedelta(interval.replace("m", "min").replace("1d", "1D"))


def klines(symbol: str, interval: str, *, limit: int = 1000,
           start: pd.Timestamp | None = None) -> pd.DataFrame:
    """Velas CERRADAS (se descarta la vela en curso), índice en UTC.

    Sin `start`: las últimas `limit` velas. Con `start`: todas desde `start` hasta ahora.
    """
    if symbol in TD_SYMBOLS or "/" in symbol:
        return _twelvedata(symbol, interval, limit=limit, start=start)
    return _binance(symbol, interval, limit=limit, start=start)


def _binance(symbol: str, interval: str, *, limit: int,
             start: pd.Timestamp | None) -> pd.DataFrame:
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if start is not None:
        params["startTime"] = int(start.timestamp() * 1000)
    rows = []
    while True:
        r = requests.get(f"{BASE}/klines", params=params, timeout=20)
        r.raise_for_status()
        page = r.json()
        rows.extend(page)
        if start is None or len(page) < limit:
            break
        params["startTime"] = page[-1][0] + 1
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume", "ct",
                                     "qv", "n", "tb", "tq", "i"])
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True)
    df.index.name = "timestamp"
    now_ms = pd.Timestamp.now(tz="UTC").timestamp() * 1000
    df = df[df["ct"] < now_ms]  # solo velas cerradas
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def _td_throttle() -> None:
    """Respeta el límite por minuto del plan gratuito."""
    now = time.monotonic()
    while _td_calls and now - _td_calls[0] > 60:
        _td_calls.pop(0)
    if len(_td_calls) >= TD_PER_MIN:
        time.sleep(60 - (now - _td_calls[0]) + 1)
        return _td_throttle()
    _td_calls.append(time.monotonic())


def _td_get(params: dict) -> list[dict]:
    params = {**params, "timezone": "UTC", "order": "ASC", "format": "JSON"}
    headers = {}
    key = os.environ.get("TWELVEDATA_API_KEY")
    if key:
        headers["Authorization"] = f"apikey {key}"
    for attempt in range(3):
        _td_throttle()
        r = requests.get(f"{TD_BASE}/time_series", params=params, headers=headers, timeout=30)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code == 200 and data.get("status") == "ok":
            return data["values"]
        msg = data.get("message", r.text[:200])
        if data.get("code") == 429 or r.status_code == 429:   # límite por minuto
            time.sleep(61)
            continue
        if "No data is available" in str(msg):
            return []
        raise MarketDataError(f"Twelve Data {params.get('symbol')} {params.get('interval')}: {msg}")
    raise MarketDataError("Twelve Data: límite de peticiones superado varias veces")


# Hora del servidor de MetaTrader del usuario: UTC+2. Las velas de 4h y diarias de oro y
# euro se arman con velas de 1h para que coincidan con las de su MetaTrader (Twelve Data
# corta el día y el 4h en otra zona horaria).
MT_OFFSET = pd.Timedelta(hours=2)


def _drop_weekend(df: pd.DataFrame) -> pd.DataFrame:
    """Twelve Data rellena el fin de semana con velas planas: se quitan.

    Forex cierra el viernes a las 17:00 de Nueva York y abre el domingo a las 17:00.
    """
    ny = df.index.tz_convert("America/New_York")
    wd, hr = ny.weekday, ny.hour
    closed = ((wd == 4) & (hr >= 17)) | (wd == 5) | ((wd == 6) & (hr < 17))
    return df[~closed]


def _resample_mt(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    rule = "4h" if interval == "4h" else "1D"
    # Las velas empiezan a las 00:00, 04:00, ... del servidor (UTC+2).
    shifted = df.copy()
    shifted.index = shifted.index + MT_OFFSET
    out = shifted.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                      "close": "last", "volume": "sum"}).dropna()
    out.index = out.index - MT_OFFSET
    return out


def _twelvedata(symbol: str, interval: str, *, limit: int,
                start: pd.Timestamp | None) -> pd.DataFrame:
    if interval in ("4h", "1d"):
        hours = 24 if interval == "1d" else 4
        if start is None:   # horas de mercado necesarias (+ fines de semana y margen)
            start = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours * (limit + 2) * 7 / 5 + 72)
        h1 = _twelvedata(symbol, "1h", limit=0, start=start - pd.Timedelta(hours=hours))
        out = _resample_mt(h1, interval)
        out = out[out.index + _bar_delta(interval) <= pd.Timestamp.now(tz="UTC")]
        if limit and start is not None:
            out = out[out.index >= start - pd.Timedelta(hours=hours)]
        return out.tail(limit) if limit else out
    if interval not in TD_INTERVAL:
        raise MarketDataError(f"Intervalo no soportado en Twelve Data: {interval}")
    base = {"symbol": symbol, "interval": TD_INTERVAL[interval]}
    rows: list[dict] = []
    if start is None:
        # Pedimos velas de más para cubrir un fin de semana (se quitan después).
        weekend = int(pd.Timedelta(hours=50) / _bar_delta(interval)) + 1
        rows = _td_get({**base, "outputsize": min(limit + 1 + weekend, TD_PAGE)})
    else:
        cursor = pd.Timestamp(start).tz_convert("UTC") if pd.Timestamp(start).tzinfo \
            else pd.Timestamp(start, tz="UTC")
        step = _bar_delta(interval) * (TD_PAGE - 1)
        now = pd.Timestamp.now(tz="UTC")
        while cursor < now:
            end = min(cursor + step, now)
            rows.extend(_td_get({**base, "outputsize": TD_PAGE,
                                 "start_date": f"{cursor:%Y-%m-%d %H:%M:%S}",
                                 "end_date": f"{end:%Y-%m-%d %H:%M:%S}"}))
            cursor = end
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], dtype=float,
                            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["datetime"]).dt.tz_localize("UTC")
    df.index.name = "timestamp"
    df = df[~df.index.duplicated()].sort_index()
    if "volume" not in df:
        df["volume"] = 0.0   # forex no trae volumen
    df = _drop_weekend(df[["open", "high", "low", "close", "volume"]].astype(float))
    # Solo velas cerradas: la vela en curso termina después de ahora.
    df = df[df.index + _bar_delta(interval) <= pd.Timestamp.now(tz="UTC")]
    if start is None and limit:
        df = df.tail(limit)
    return df
