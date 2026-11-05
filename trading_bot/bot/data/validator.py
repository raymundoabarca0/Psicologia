"""Validación de datos de mercado (velas OHLCV).

Se descartan (nunca se "arreglan" ni se rellenan con datos inventados):
- velas duplicadas (se conserva la primera),
- velas con OHLC incoherente, NaN o precios <= 0,
- velas con movimientos anómalos (retorno o mecha > max_bar_move_pct),
- la vela actual aún no cerrada (evita look-ahead / repintado).

Los huecos (velas faltantes) se reportan. `check_tradeable` se niega a operar si
hay huecos en la ventana reciente o si los datos están desactualizados.

Formato esperado: DataFrame con índice DatetimeIndex UTC (apertura de la vela) y
columnas open, high, low, close, volume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from bot.utils.timeframes import timeframe_to_timedelta

COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass
class DataIssue:
    kind: str           # duplicate | invalid | anomaly | gap | unclosed
    timestamp: pd.Timestamp
    detail: str = ""


@dataclass
class ValidationResult:
    df: pd.DataFrame
    issues: list[DataIssue] = field(default_factory=list)

    def count(self, kind: str) -> int:
        return sum(1 for i in self.issues if i.kind == kind)


def ohlcv_to_frame(rows: list[list[float]]) -> pd.DataFrame:
    """Convierte la salida de ccxt fetch_ohlcv ([[ms, o, h, l, c, v], ...])."""
    df = pd.DataFrame(rows, columns=["timestamp", *COLUMNS])
    df.index = pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True)
    df.index.name = "timestamp"
    return df.astype(float)


def clean_ohlcv(
    df: pd.DataFrame,
    timeframe: str,
    *,
    max_bar_move_pct: float,
    now: datetime | None = None,
    drop_anomalies: bool = True,
) -> ValidationResult:
    """drop_anomalies=True (operativa en vivo): las velas anómalas se descartan, lo
    que deja un hueco y bloquea la operativa: lo más conservador.
    drop_anomalies=False (backtest con datos históricos del propio exchange): se
    marcan pero se CONSERVAN. Descartar un desplome real (p. ej. 19-may-2021)
    ocultaría los stops que saltaron y haría el backtest optimista."""
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas: {missing}")
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError("El índice debe ser DatetimeIndex con zona horaria (UTC)")

    tf = pd.Timedelta(timeframe_to_timedelta(timeframe))
    issues: list[DataIssue] = []
    df = df[COLUMNS].copy().sort_index()

    # Duplicados
    dup = df.index.duplicated(keep="first")
    for ts in df.index[dup]:
        issues.append(DataIssue("duplicate", ts))
    df = df[~dup]

    # Desalineadas respecto al timeframe
    misaligned = (df.index.as_unit("ns").asi8 % tf.as_unit("ns").value) != 0
    for ts in df.index[misaligned]:
        issues.append(DataIssue("invalid", ts, "timestamp no alineado al timeframe"))
    df = df[~misaligned]

    # Vela no cerrada
    if now is not None:
        now_ts = pd.Timestamp(now).tz_convert("UTC")
        unclosed = (df.index + tf) > now_ts
        for ts in df.index[unclosed]:
            issues.append(DataIssue("unclosed", ts))
        df = df[~unclosed]

    # OHLC inválido
    o, h, l, c, v = (df[k] for k in COLUMNS)
    invalid = (
        df.isna().any(axis=1)
        | ~np.isfinite(df.to_numpy()).all(axis=1)
        | (o <= 0) | (h <= 0) | (l <= 0) | (c <= 0) | (v < 0)
        | (h < np.maximum(o, c)) | (l > np.minimum(o, c)) | (h < l)
    )
    for ts in df.index[invalid]:
        issues.append(DataIssue("invalid", ts, "OHLC incoherente o no finito"))
    df = df[~invalid]

    # Anomalías:
    #  - pico aislado: el cierre salta > umbral respecto al anterior y la vela
    #    siguiente vuelve cerca del nivel previo (típico de un dato erróneo).
    #    Un desplome REAL que se mantiene NO se descarta (lo gestiona el
    #    circuit breaker de volatilidad, que pausa la operativa).
    #  - mecha extrema dentro de la vela (> umbral).
    thr = max_bar_move_pct / 100.0
    if len(df) > 0:
        close = df["close"]
        prev, nxt = close.shift(1), close.shift(-1)
        jump = (close / prev - 1).abs() > thr
        reverted = (nxt / prev - 1).abs() < thr / 2
        spike = (jump & reverted).fillna(False)
        wick_up = df["high"] / np.maximum(df["open"], close) - 1
        wick_dn = 1 - df["low"] / np.minimum(df["open"], close)
        bad = spike | (wick_up > thr) | (wick_dn > thr)
        for ts in df.index[bad]:
            issues.append(DataIssue("anomaly", ts, f"movimiento anómalo > {max_bar_move_pct}%"))
        if drop_anomalies:
            df = df[~bad]

    # Huecos
    if len(df) > 1:
        diffs = df.index.to_series().diff().iloc[1:]
        for ts, d in diffs[diffs > tf].items():
            n_missing = int(d / tf) - 1
            issues.append(DataIssue("gap", ts, f"faltan {n_missing} velas antes"))

    return ValidationResult(df=df, issues=issues)


def check_tradeable(
    df: pd.DataFrame,
    timeframe: str,
    now: datetime,
    *,
    required_clean_bars: int,
    max_staleness_bars: float,
) -> tuple[bool, list[str]]:
    """¿Se puede operar con estos datos ya limpios? Devuelve (ok, motivos)."""
    reasons: list[str] = []
    tf = pd.Timedelta(timeframe_to_timedelta(timeframe))
    if len(df) < required_clean_bars:
        return False, [f"solo {len(df)} velas; se requieren {required_clean_bars}"]

    last_open = df.index[-1]
    last_close_time = last_open + tf
    age = pd.Timestamp(now).tz_convert("UTC") - last_close_time
    if age > tf * max_staleness_bars:
        reasons.append(f"datos desactualizados: última vela cerró hace {age}")
    if age < pd.Timedelta(0):
        reasons.append("la última vela aún no ha cerrado")

    window = df.index[-required_clean_bars:]
    expected = pd.date_range(window[0], periods=required_clean_bars, freq=tf)
    if len(window) != len(expected) or not (window == expected).all():
        reasons.append(f"huecos en las últimas {required_clean_bars} velas")

    return (not reasons), reasons
