"""Walk-forward: optimizar en una ventana de entrenamiento y evaluar FUERA de muestra.

Para cada ventana:
  1. Entrenamiento [T - train, T): se prueban todos los parámetros de la rejilla y
     se elige el de mejor Sharpe (con un mínimo de operaciones).
  2. Prueba [T, T + test): se usan esos parámetros en datos que el optimizador
     NUNCA vio.
Las ventanas de prueba se encadenan en UNA sola simulación con capital continuo.
Solo esa curva fuera de muestra cuenta como resultado.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtest.engine import BacktestEngine, BacktestResult
from backtest.metrics import sharpe
from bot.strategy.base import Strategy


@dataclass
class WindowChoice:
    train_start: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    params: dict
    train_sharpe: float
    train_trades: int


def make_windows(first: pd.Timestamp, last: pd.Timestamp, train: pd.DateOffset,
                 test: pd.DateOffset) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    out = []
    test_start = first + train
    while test_start < last:
        test_end = min(test_start + test, last)
        out.append((test_start - train, test_start, test_end))
        test_start = test_end
    return out


def walk_forward(
    strategy_cls: type[Strategy],
    data: dict[str, pd.DataFrame],
    engine: BacktestEngine,
    *,
    train: pd.DateOffset = pd.DateOffset(years=2),
    test: pd.DateOffset = pd.DateOffset(months=6),
    min_train_trades: int = 10,
) -> tuple[BacktestResult, list[WindowChoice]]:
    first = max(df.index[0] for df in data.values())
    last = min(df.index[-1] for df in data.values())
    windows = make_windows(first, last, train, test)

    # Las señales de cada combinación se calculan una vez sobre toda la serie:
    # los indicadores son causales, así que la vela t solo ve datos <= t.
    cache: dict[int, dict[str, pd.DataFrame]] = {}
    for k, params in enumerate(strategy_cls.param_grid):
        strat = strategy_cls(**params)
        cache[k] = {s: strat.signals(df) for s, df in data.items()}

    choices: list[WindowChoice] = []
    oos_parts: dict[str, list[pd.DataFrame]] = {s: [] for s in data}
    for tr_start, te_start, te_end in windows:
        best = None
        for k, params in enumerate(strategy_cls.param_grid):
            res = engine.run(data, cache[k], start=tr_start, end=te_start,
                             strategy_name=strategy_cls.name)
            n = len(res.trades)
            score = sharpe(res.equity) if n >= min_train_trades else float("-inf")
            if best is None or score > best[0]:
                best = (score, k, n)
        score, k, n = best
        choices.append(WindowChoice(tr_start, te_start, te_end,
                                    strategy_cls.param_grid[k], score, n))
        for s in data:
            sig = cache[k][s]
            oos_parts[s].append(sig[(sig.index >= te_start) & (sig.index < te_end)])

    oos_signals = {s: pd.concat(parts) for s, parts in oos_parts.items()}
    oos_start, oos_end = windows[0][1], windows[-1][2]
    result = engine.run(data, oos_signals, start=oos_start, end=oos_end,
                        strategy_name=strategy_cls.name)
    return result, choices
