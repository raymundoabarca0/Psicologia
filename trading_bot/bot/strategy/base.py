"""Interfaz de estrategias.

Una estrategia transforma velas en un DataFrame de señales, con una fila por
vela. Todo se calcula con datos hasta el CIERRE de esa vela; el motor (backtest
o en vivo) ejecuta en la APERTURA de la vela siguiente. Así no hay look-ahead.

Columnas de salida:
    entry       bool   proponer entrada larga en la siguiente apertura
    exit        bool   cerrar la posición en la siguiente apertura
    stop_dist   float  distancia del stop inicial (en precio) bajo la entrada
    tp_dist     float  distancia del take-profit sobre la entrada (NaN = sin TP)
    trail_pct   float  trailing stop en % bajo el máximo alcanzado (NaN = sin trailing)
    atr         float  ATR (para la pausa por volatilidad)

El mismo código se usa en backtest, paper y real: en vivo se toma la última fila.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

import pandas as pd

SIGNAL_COLUMNS = ["entry", "exit", "stop_dist", "tp_dist", "trail_pct", "atr"]


class Strategy(ABC):
    name: ClassVar[str]
    # Rejilla pequeña de parámetros para walk-forward (pocos = menos overfitting).
    param_grid: ClassVar[list[dict[str, Any]]]
    # Velas necesarias antes de que las señales sean válidas.
    warmup: ClassVar[int] = 250

    def __init__(self, **params):
        self.params = params

    @abstractmethod
    def signals(self, df: pd.DataFrame) -> pd.DataFrame: ...

    def __repr__(self) -> str:
        return f"{self.name}({self.params})"

    @staticmethod
    def _finalize(out: pd.DataFrame, warmup: int) -> pd.DataFrame:
        out = out[SIGNAL_COLUMNS].copy()
        out["entry"] = out["entry"].fillna(False).astype(bool)
        out["exit"] = out["exit"].fillna(False).astype(bool)
        out.iloc[:warmup, out.columns.get_loc("entry")] = False
        # Sin stop válido no hay entrada.
        out.loc[~(out["stop_dist"] > 0), "entry"] = False
        return out
