"""Utilidades para timeframes estilo ccxt ('1m', '15m', '1h', '4h', '1d')."""

from __future__ import annotations

import re
from datetime import timedelta

_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
_RE = re.compile(r"^(\d+)([mhdw])$")


def timeframe_to_timedelta(tf: str) -> timedelta:
    m = _RE.match(tf)
    if not m or int(m.group(1)) <= 0:
        raise ValueError(f"Timeframe inválido: {tf!r}")
    return timedelta(**{_UNITS[m.group(2)]: int(m.group(1))})


def timeframe_to_ms(tf: str) -> int:
    return int(timeframe_to_timedelta(tf).total_seconds() * 1000)
