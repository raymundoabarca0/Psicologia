"""RiskManager: tiene la ÚLTIMA PALABRA sobre cualquier entrada.

Flujo obligatorio:  Estrategia -> RiskManager.evaluate_entry -> OrderValidator -> Executor

Principios:
- Por defecto se rechaza. Solo se aprueba si TODAS las comprobaciones pasan.
- Nunca se aumenta el tamaño pedido; solo se calcula según el stop o se rechaza.
- Las SALIDAS (stops, cierres, kill switch) no pasan por aquí: reducir riesgo
  siempre está permitido.
- Los límites efectivos son min(config, límite duro).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable

from bot.config import CostsConfig, RiskConfig
from bot.execution.order_validator import MarketRules
from bot.models import AccountSnapshot, Signal
from bot.risk import hard_limits as HL
from bot.risk.limits import RiskState, RiskStatus, update_state
from bot.risk.sizing import position_size_long

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    quantity: Decimal = Decimal(0)
    notional: float = 0.0
    worst_case_loss: float = 0.0
    reasons: tuple[str, ...] = ()

    @classmethod
    def reject(cls, *reasons: str) -> "RiskDecision":
        return cls(approved=False, reasons=tuple(reasons))


class RiskManager:
    def __init__(
        self,
        risk_cfg: RiskConfig,
        costs_cfg: CostsConfig,
        state: RiskState,
        *,
        on_permanent_halt: Callable[[str], None] | None = None,
        is_kill_switch_active: Callable[[], bool] = lambda: False,
    ):
        self.cfg = risk_cfg
        self.costs = costs_cfg
        self.state = state
        self._on_permanent_halt = on_permanent_halt
        self._kill = is_kill_switch_active
        self._halt_notified = state.permanently_halted

        # Límites efectivos (defensa en profundidad aunque la config ya se validó).
        self.risk_pct = min(risk_cfg.risk_per_trade_pct, HL.MAX_RISK_PER_TRADE_PCT)
        self.max_daily_loss = min(risk_cfg.max_daily_loss_pct, HL.MAX_DAILY_LOSS_PCT)
        self.max_dd = min(risk_cfg.max_drawdown_pct, HL.MAX_DRAWDOWN_PCT)
        self.max_positions = min(risk_cfg.max_open_positions, HL.MAX_OPEN_POSITIONS)
        self.max_trades = min(risk_cfg.max_trades_per_day, HL.MAX_TRADES_PER_DAY)
        self.max_pos_pct = min(risk_cfg.max_position_pct_of_equity, HL.MAX_POSITION_PCT_OF_EQUITY)
        self.leverage = min(risk_cfg.leverage, HL.MAX_LEVERAGE)

    # ------------------------------------------------------------------ estado
    def update_equity(self, equity: float, now: datetime) -> RiskStatus:
        status = update_state(
            self.state, equity, now,
            tz=self.cfg.day_reset_timezone,
            max_daily_loss_pct=self.max_daily_loss,
            max_drawdown_pct=self.max_dd,
        )
        if status is RiskStatus.PERMANENT_HALT and not self._halt_notified:
            self._halt_notified = True
            log.critical("HALT PERMANENTE: %s", self.state.halt_reason)
            if self._on_permanent_halt:
                self._on_permanent_halt(self.state.halt_reason or "halt")
        elif status is RiskStatus.DAILY_HALT:
            log.warning("Pausa diaria activa: %s", self.state.halt_reason)
        return status

    def record_entry(self) -> None:
        """Llamar cuando una entrada se ENVÍA (no solo cuando se llena), para que
        un error en la ejecución no permita sobreoperar."""
        self.state.trades_today += 1

    # ---------------------------------------------------------------- entradas
    def evaluate_entry(
        self,
        signal: Signal,
        account: AccountSnapshot,
        rules: MarketRules,
        now: datetime,
    ) -> RiskDecision:
        decision = self._evaluate(signal, account, rules, now)
        log.info("Riesgo %s %s: %s qty=%s riesgo=%.2f motivos=%s",
                 signal.strategy, signal.symbol,
                 "APROBADA" if decision.approved else "RECHAZADA",
                 decision.quantity, decision.worst_case_loss, list(decision.reasons))
        return decision

    def _evaluate(self, signal: Signal, account: AccountSnapshot,
                  rules: MarketRules, now: datetime) -> RiskDecision:
        # 1. Estados de parada
        if self._kill():
            return RiskDecision.reject("kill switch activo")
        status = self.update_equity(account.equity, now)
        if status is RiskStatus.PERMANENT_HALT:
            return RiskDecision.reject(f"halt permanente: {self.state.halt_reason}")
        if status is RiskStatus.DAILY_HALT:
            return RiskDecision.reject(f"pausa diaria: {self.state.halt_reason}")

        # 2. Forma de la señal
        if signal.side != "buy":
            return RiskDecision.reject("solo se permiten entradas largas (spot, sin cortos)")
        if signal.symbol != rules.symbol:
            return RiskDecision.reject("símbolo de la señal no coincide con las reglas de mercado")
        for name, v in (("entry_price", signal.entry_price), ("stop_price", signal.stop_price)):
            if v is None or not math.isfinite(v) or v <= 0:
                return RiskDecision.reject(f"{name} inválido: {v}")
        if signal.stop_price >= signal.entry_price:
            return RiskDecision.reject("el stop debe estar por debajo de la entrada")
        has_tp = signal.take_profit_price is not None
        has_trail = signal.trailing_stop_pct is not None
        if not (has_tp or has_trail):
            return RiskDecision.reject("falta take-profit o trailing stop")
        if has_tp and (not math.isfinite(signal.take_profit_price)
                       or signal.take_profit_price <= signal.entry_price):
            return RiskDecision.reject("take-profit debe estar por encima de la entrada")
        if has_trail and not (0 < signal.trailing_stop_pct < 100):
            return RiskDecision.reject("trailing_stop_pct fuera de rango")

        stop_dist_pct = (signal.entry_price - signal.stop_price) / signal.entry_price * 100
        if stop_dist_pct < self.cfg.min_stop_distance_pct:
            return RiskDecision.reject(
                f"stop demasiado cerca ({stop_dist_pct:.2f}% < {self.cfg.min_stop_distance_pct}%)")
        if stop_dist_pct > self.cfg.max_stop_distance_pct:
            return RiskDecision.reject(
                f"stop demasiado lejos ({stop_dist_pct:.2f}% > {self.cfg.max_stop_distance_pct}%)")

        # 3. Límites de cartera
        if signal.symbol in account.positions:
            return RiskDecision.reject("ya hay posición en este símbolo (sin promediar)")
        if len(account.positions) >= self.max_positions:
            return RiskDecision.reject(f"máximo de posiciones abiertas ({self.max_positions})")
        if self.state.trades_today >= self.max_trades:
            return RiskDecision.reject(f"máximo de operaciones diarias ({self.max_trades})")
        if account.equity <= 0:
            return RiskDecision.reject("equity no positivo")

        # 4. Tamaño
        exposure_room = account.equity * self.leverage - account.exposure
        max_notional = min(
            account.equity * self.max_pos_pct / 100.0,
            exposure_room,
            account.free_quote,  # sin apalancamiento: solo saldo libre real
        )
        if max_notional <= 0:
            return RiskDecision.reject("sin margen de exposición / saldo libre")

        sizing = position_size_long(
            equity=account.equity,
            entry=signal.entry_price,
            stop=signal.stop_price,
            risk_pct=self.risk_pct,
            max_notional=max_notional,
            step=rules.step_size,
            fee_rate=self.costs.fee_rate,
            slippage_rate=self.costs.slippage_rate + self.costs.spread_rate / 2,
        )
        if sizing.quantity <= 0:
            return RiskDecision.reject("tamaño calculado es 0 tras redondear")
        if sizing.quantity < rules.min_qty:
            return RiskDecision.reject(
                f"tamaño {sizing.quantity} < mínimo del exchange {rules.min_qty} "
                "(no se redondea hacia arriba: superaría el riesgo)")
        if Decimal(str(sizing.notional)) < rules.min_notional:
            return RiskDecision.reject(
                f"nocional {sizing.notional:.2f} < mínimo del exchange {rules.min_notional}")

        # 5. Verificación final: el riesgo real nunca supera el presupuesto.
        budget = account.equity * self.risk_pct / 100.0
        if sizing.worst_case_loss > budget * (1 + 1e-9):
            return RiskDecision.reject(
                f"riesgo {sizing.worst_case_loss:.4f} supera presupuesto {budget:.4f}")

        return RiskDecision(
            approved=True,
            quantity=sizing.quantity,
            notional=sizing.notional,
            worst_case_loss=sizing.worst_case_loss,
            reasons=(f"limitado por {sizing.capped_by}",),
        )
