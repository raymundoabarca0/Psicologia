"""Descarga de velas para el experimento de señales en paper.

Fuente: espejo público de datos de Binance (sin API key).
- BTC: BTCUSDT.
- Oro: PAXGUSDT (token respaldado 1:1 por una onza troy de oro; sigue a XAU/USD
  con una pequeña prima o descuento). Es un sustituto, no el XAU/USD de forex.
"""

from __future__ import annotations

import pandas as pd
import requests

BASE = "https://data-api.binance.vision/api/v3"
ASSETS = {"BTC": "BTCUSDT", "ORO": "PAXGUSDT"}


def klines(symbol: str, interval: str, *, limit: int = 1000,
           start: pd.Timestamp | None = None) -> pd.DataFrame:
    """Velas CERRADAS (se descarta la vela en curso)."""
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
