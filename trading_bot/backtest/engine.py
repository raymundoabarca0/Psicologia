"""Motor de backtest por eventos (vela a vela), multi-activo, con cartera común.

Reglas para evitar look-ahead:
- Las señales se calculan con datos hasta el CIERRE de la vela t.
- Entradas y salidas por señal se ejecutan en la APERTURA de t+1.
- Dentro de una vela no sabemos qué ocurrió antes (máximo o mínimo), así que si
  se tocan el stop y el take-profit en la misma vela se asume el STOP (peor caso).
- Si la apertura ya está por debajo del stop (gap), se sale a la apertura, no
  al stop.
- El trailing se actualiza con el máximo de la vela t y se aplica desde t+1.

El RiskManager y el OrderValidator son los MISMOS que usa el bot en vivo.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np
import pandas as pd

from bot.config import BotConfig, CostsConfig
from bot.execution.order_validator import MarketRules, make_client_order_id, validate_order
from bot.models import AccountSnapshot, OrderRequest, Position, Signal
from bot.risk.limits import RiskState, RiskStatus
from bot.risk.manager import RiskManager
from bot.utils.timeframes import timeframe_to_timedelta

log = logging.getLogger(__name__)


@dataclass
class _Pos:
    symbol: str
    qty: float
    entry_time: pd.Timestamp
    entry_price: float       # precio de ejecución (con slippage)
    stop: float
    initial_stop: float
    tp: float | None
    trail_pct: float | None
    highest: float
    entry_fee: float
    risk_amount: float       # pérdida estimada si salta el stop inicial


@dataclass
class Trade:
    symbol: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    qty: float
    pnl: float               # neto, con comisiones
    fees: float
    reason: str              # stop | gap_stop | tp | trail | signal | halt | end
    r_multiple: float


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[Trade]
    fees: float
    halted_at: pd.Timestamp | None = None
    halt_reason: str | None = None
    rejected: dict[str, int] = field(default_factory=dict)
    exposure: float = 0.0    # fracción de velas con alguna posición abierta


def scaled_costs(costs: CostsConfig, mult: float) -> CostsConfig:
    return CostsConfig(fee_rate=costs.fee_rate * mult,
                       slippage_rate=costs.slippage_rate * mult,
                       spread_rate=costs.spread_rate * mult)


class BacktestEngine:
    def __init__(self, cfg: BotConfig, rules: dict[str, MarketRules], *,
                 initial_capital: float, cost_mult: float = 1.0,
                 diagnostic_no_dd_halt: bool = False):
        """diagnostic_no_dd_halt: SOLO para análisis. Desactiva el apagado por
        drawdown para medir si la estrategia tiene ventaja a largo plazo. Nunca
        existe un equivalente en el bot real."""
        self.diagnostic_no_dd_halt = diagnostic_no_dd_halt
        self.cfg = cfg
        self.rules = rules
        self.capital0 = initial_capital
        self.costs = scaled_costs(cfg.costs, cost_mult)
        self.tf = pd.Timedelta(timeframe_to_timedelta(cfg.exchange.timeframe))
        half_spread = self.costs.spread_rate / 2
        self.buy_mult = 1 + self.costs.slippage_rate + half_spread
        self.sell_mult = 1 - self.costs.slippage_rate - half_spread

    # ------------------------------------------------------------------ run
    def run(self, data: dict[str, pd.DataFrame], signals: dict[str, pd.DataFrame],
            start: pd.Timestamp | None = None, end: pd.Timestamp | None = None,
            strategy_name: str = "bt") -> BacktestResult:
        symbols = list(data)
        index = data[symbols[0]].index
        for s in symbols[1:]:
            index = index.union(data[s].index)
        if start is not None:
            index = index[index >= start]
        if end is not None:
            index = index[index < end]
        if len(index) == 0:
            raise ValueError("Rango de backtest vacío")

        # Matrices alineadas (NaN donde un activo no tiene vela).
        cols = ["open", "high", "low", "close"]
        px = {s: data[s][cols].reindex(index).to_numpy() for s in symbols}
        sig = {s: signals[s].reindex(index) for s in symbols}
        sg_entry = {s: sig[s]["entry"].fillna(False).to_numpy(bool) for s in symbols}
        sg_exit = {s: sig[s]["exit"].fillna(False).to_numpy(bool) for s in symbols}
        sg_stop = {s: sig[s]["stop_dist"].to_numpy(float) for s in symbols}
        sg_tp = {s: sig[s]["tp_dist"].to_numpy(float) for s in symbols}
        sg_trail = {s: sig[s]["trail_pct"].to_numpy(float) for s in symbols}
        sg_atr = {s: sig[s]["atr"].to_numpy(float) for s in symbols}
        vol_mult = self.cfg.safety.volatility_pause_atr_multiple

        state = RiskState.fresh(self.capital0, index[0].to_pydatetime(),
                                self.cfg.risk.day_reset_timezone)
        rm = RiskManager(self.cfg.risk, self.costs, state)
        if self.diagnostic_no_dd_halt:
            rm.max_dd = float("inf")

        cash = self.capital0
        positions: dict[str, _Pos] = {}
        last_close: dict[str, float] = {}
        pending_entry: dict[str, int] = {}     # símbolo -> índice de la vela señal
        pending_exit: set[str] = set()
        trades: list[Trade] = []
        fees_total = 0.0
        equity = np.empty(len(index))
        rejected: dict[str, int] = {}
        halted_at = None
        halt_pending = False
        bars_exposed = 0

        def close_pos(p: _Pos, raw_price: float, t, reason: str, is_limit=False):
            nonlocal cash, fees_total
            fill = raw_price if is_limit else raw_price * self.sell_mult
            fee = p.qty * fill * self.costs.fee_rate
            cash += p.qty * fill - fee
            fees_total += fee
            pnl = p.qty * (fill - p.entry_price) - p.entry_fee - fee
            trades.append(Trade(p.symbol, p.entry_time, t, p.entry_price, fill, p.qty, pnl,
                                p.entry_fee + fee, reason,
                                pnl / p.risk_amount if p.risk_amount > 0 else 0.0))
            del positions[p.symbol]

        for i, t in enumerate(index):
            now = t.to_pydatetime()

            # 1) Halt permanente pendiente: cerrar todo a la apertura y terminar.
            if halt_pending:
                for s in list(positions):
                    o = px[s][i][0]
                    close_pos(positions[s], o if not math.isnan(o) else last_close[s], t, "halt")
                equity[i:] = cash
                break

            # 2) Salidas por señal a la apertura.
            for s in list(pending_exit):
                o = px[s][i][0]
                if s not in positions:
                    pending_exit.discard(s)   # ya se cerró (p. ej. por stop)
                elif not math.isnan(o):
                    close_pos(positions[s], o, t, "signal")
                    pending_exit.discard(s)

            # 3) Entradas a la apertura (el RiskManager decide).
            for s, si in list(pending_entry.items()):
                o = px[s][i][0]
                if math.isnan(o):
                    continue
                del pending_entry[s]
                stop_dist = sg_stop[s][si]
                tp_dist, trail = sg_tp[s][si], sg_trail[s][si]
                signal = Signal(
                    symbol=s, side="buy", entry_price=float(o), stop_price=float(o - stop_dist),
                    bar_timestamp=index[si].to_pydatetime(), strategy=strategy_name,
                    take_profit_price=float(o + tp_dist) if not math.isnan(tp_dist) else None,
                    trailing_stop_pct=float(trail) if not math.isnan(trail) else None,
                )
                mtm = cash + sum(p.qty * last_close[p.symbol] for p in positions.values())
                acct = AccountSnapshot(
                    equity=mtm, free_quote=cash,
                    positions={p.symbol: Position(p.symbol, Decimal(str(p.qty)),
                                                  p.entry_price, p.stop)
                               for p in positions.values()})
                d = rm.evaluate_entry(signal, acct, self.rules[s], now)
                if not d.approved:
                    key = re.sub(r"[\d.]+", "N", d.reasons[0].split(":")[0].split("(")[0]).strip()
                    rejected[key] = rejected.get(key, 0) + 1
                    continue
                order = OrderRequest(symbol=s, side="buy", type="market", quantity=d.quantity,
                                     client_order_id=make_client_order_id(
                                         "bt", strategy_name, s, signal.bar_timestamp, "entry"))
                v = validate_order(order, self.rules[s], last_price=float(o), free_quote=cash,
                                   free_base=0.0,
                                   max_price_deviation_pct=self.cfg.orders.max_price_deviation_pct,
                                   fee_rate=self.costs.fee_rate)
                if not v.ok:
                    rejected["validador"] = rejected.get("validador", 0) + 1
                    continue
                rm.record_entry()
                qty = float(d.quantity)
                fill = o * self.buy_mult
                fee = qty * fill * self.costs.fee_rate
                cash -= qty * fill + fee
                fees_total += fee
                positions[s] = _Pos(s, qty, t, fill, signal.stop_price, signal.stop_price,
                                    signal.take_profit_price, signal.trailing_stop_pct,
                                    float(o), fee, d.worst_case_loss)

            # 4) Stops / TP dentro de la vela (stop primero: peor caso).
            for s in list(positions):
                o, h, l, c = px[s][i]
                if math.isnan(o):
                    continue
                p = positions[s]
                is_trail = p.stop > p.initial_stop
                if o <= p.stop:
                    close_pos(p, o, t, "gap_stop")
                elif l <= p.stop:
                    close_pos(p, p.stop, t, "trail" if is_trail else "stop")
                elif p.tp is not None and h >= p.tp:
                    if o >= p.tp:
                        close_pos(p, o, t, "tp")
                    else:
                        close_pos(p, p.tp, t, "tp", is_limit=True)
                else:
                    p.highest = max(p.highest, h)
                    if p.trail_pct is not None:
                        p.stop = max(p.stop, p.highest * (1 - p.trail_pct / 100))

            # 5) Cierre de vela: equity a mercado y límites de riesgo.
            for s in symbols:
                c = px[s][i][3]
                if not math.isnan(c):
                    last_close[s] = c
            if positions:
                bars_exposed += 1
            eq = cash + sum(p.qty * last_close[p.symbol] for p in positions.values())
            equity[i] = eq
            status = rm.update_equity(eq, (t + self.tf).to_pydatetime())
            if status is RiskStatus.PERMANENT_HALT and halted_at is None:
                halted_at = t
                halt_pending = True
                pending_entry.clear()
                if i == len(index) - 1:
                    for s in list(positions):
                        close_pos(positions[s], last_close[s], t, "halt")
                continue

            # 6) Señales al cierre -> se ejecutan en la siguiente apertura.
            for s in symbols:
                o, h, l, c = px[s][i]
                if math.isnan(c):
                    continue
                if s in positions:
                    if sg_exit[s][i]:
                        pending_exit.add(s)
                elif sg_entry[s][i] and s not in pending_entry:
                    a = sg_atr[s][i]
                    if not (a > 0) or (h - l) > vol_mult * a:
                        rejected["pausa_volatilidad"] = rejected.get("pausa_volatilidad", 0) + 1
                        continue
                    pending_entry[s] = i
        else:
            # Fin del periodo: cerrar a último cierre para medir resultados.
            for s in list(positions):
                close_pos(positions[s], last_close[s], index[-1], "end")
            equity[-1] = cash

        eq_series = pd.Series(equity, index=index, name="equity")
        return BacktestResult(eq_series, trades, fees_total, halted_at,
                              state.halt_reason if halted_at is not None else None,
                              rejected, bars_exposed / len(index))
