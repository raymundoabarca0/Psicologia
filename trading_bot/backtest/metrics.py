"""Métricas de rendimiento."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from backtest.engine import BacktestResult


def periods_per_year(index: pd.DatetimeIndex) -> float:
    step = pd.Series(index).diff().median()
    return pd.Timedelta(days=365) / step  # cripto opera 24/7


def max_drawdown_pct(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float(((peak - equity) / peak).max() * 100) if len(equity) else 0.0


def sharpe(equity: pd.Series) -> float:
    r = equity.pct_change().dropna()
    if len(r) < 2 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * math.sqrt(periods_per_year(equity.index)))


def sortino(equity: pd.Series) -> float:
    r = equity.pct_change().dropna()
    downside = r[r < 0]
    if len(downside) < 2 or downside.std() == 0:
        return 0.0
    dd = math.sqrt((downside ** 2).mean())
    return float(r.mean() / dd * math.sqrt(periods_per_year(equity.index)))


def cagr_pct(equity: pd.Series) -> float:
    years = (equity.index[-1] - equity.index[0]) / pd.Timedelta(days=365.25)
    if years <= 0 or equity.iloc[0] <= 0 or equity.iloc[-1] <= 0:
        return 0.0
    return float(((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) * 100)


def summarize(res: BacktestResult) -> dict:
    eq = res.equity
    pnls = np.array([t.pnl for t in res.trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    gross_loss = -losses.sum()
    return {
        "retorno_%": (eq.iloc[-1] / eq.iloc[0] - 1) * 100,
        "CAGR_%": cagr_pct(eq),
        "sharpe": sharpe(eq),
        "sortino": sortino(eq),
        "max_dd_%": max_drawdown_pct(eq),
        "profit_factor": (wins.sum() / gross_loss) if gross_loss > 0 else float("inf"),
        "operaciones": len(pnls),
        "win_rate_%": (len(wins) / len(pnls) * 100) if len(pnls) else 0.0,
        "R_medio": float(np.mean([t.r_multiple for t in res.trades])) if res.trades else 0.0,
        "comisiones": res.fees,
        "exposicion_%": res.exposure * 100,
        "halt": res.halted_at.strftime("%Y-%m-%d") if res.halted_at is not None else "-",
    }


def buy_and_hold(data: dict[str, pd.DataFrame], start, end, capital: float,
                 fee_rate: float) -> pd.Series:
    """Benchmark: capital repartido a partes iguales, comprado al inicio, sin rebalancear."""
    parts = []
    for df in data.values():
        c = df["close"][(df.index >= start) & (df.index < end)]
        parts.append(c / c.iloc[0] * (capital / len(data)) * (1 - fee_rate))
    return pd.concat(parts, axis=1).ffill().sum(axis=1)
