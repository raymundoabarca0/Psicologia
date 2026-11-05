"""Validación de órdenes antes de enviarlas al exchange.

Regla: la orden se valida tal cual se va a enviar. El validador NO corrige
nada en silencio (p. ej. no redondea): si la cantidad no respeta el step, la
orden se rechaza. El redondeo correcto se hace antes, de forma explícita, con
quantize_qty/quantize_price.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal

from bot.models import OrderRequest
from bot.risk.sizing import floor_to_step

# Binance: newClientOrderId debe cumplir ^[\.A-Z\:/a-z0-9_-]{1,36}$
_CLIENT_ID_RE = re.compile(r"^[.A-Za-z:/0-9_-]{1,36}$")
_VALID_TYPES = {"market", "limit", "stop_loss", "stop_loss_limit"}


@dataclass(frozen=True)
class MarketRules:
    symbol: str
    step_size: Decimal          # incremento mínimo de cantidad
    tick_size: Decimal          # incremento mínimo de precio
    min_qty: Decimal
    min_notional: Decimal
    max_qty: Decimal | None = None

    @classmethod
    def from_ccxt_market(cls, market: dict, precision_mode_tick_size: bool = True) -> "MarketRules":
        """Construye las reglas a partir de un mercado de ccxt (exchange.markets[symbol]).

        Con precisionMode TICK_SIZE (el de Binance en ccxt) `precision` contiene el
        step/tick directamente; con DECIMAL_PLACES contiene número de decimales.
        """
        prec = market.get("precision") or {}
        limits = market.get("limits") or {}

        def to_step(p) -> Decimal:
            if p is None:
                raise ValueError(f"{market.get('symbol')}: falta precisión en el mercado")
            if precision_mode_tick_size:
                return Decimal(str(p))
            return Decimal(1).scaleb(-int(p))

        amount_lim = limits.get("amount") or {}
        cost_lim = limits.get("cost") or {}
        step = to_step(prec.get("amount"))
        tick = to_step(prec.get("price"))
        if step <= 0 or tick <= 0:
            raise ValueError(f"{market.get('symbol')}: step/tick inválidos")
        return cls(
            symbol=market["symbol"],
            step_size=step,
            tick_size=tick,
            min_qty=Decimal(str(amount_lim.get("min") or 0)),
            min_notional=Decimal(str(cost_lim.get("min") or 0)),
            max_qty=Decimal(str(amount_lim["max"])) if amount_lim.get("max") else None,
        )


@dataclass(frozen=True)
class ValidationOutcome:
    ok: bool
    errors: tuple[str, ...]


def _is_multiple(value: Decimal, step: Decimal) -> bool:
    return (value % step) == 0


def quantize_qty(qty: float | Decimal, step: Decimal) -> Decimal:
    """Redondea la cantidad HACIA ABAJO al step (nunca aumenta el riesgo)."""
    return floor_to_step(qty, step)


def quantize_price(price: float | Decimal, tick: Decimal, mode: str = "nearest") -> Decimal:
    rounding = {"down": ROUND_DOWN, "up": ROUND_UP, "nearest": ROUND_HALF_UP}[mode]
    d = Decimal(str(price))
    return (d / tick).to_integral_value(rounding=rounding) * tick


def make_client_order_id(prefix: str, strategy: str, symbol: str,
                         bar_timestamp: datetime, purpose: str) -> str:
    """ID determinista: la misma señal (estrategia, símbolo, vela, propósito)
    produce SIEMPRE el mismo ID, así un reintento no duplica la orden: el
    exchange rechaza un clientOrderId repetido.

    purpose: 'entry', 'stop', 'tp', 'exit', ...
    """
    if bar_timestamp.tzinfo is None:
        raise ValueError("bar_timestamp debe tener zona horaria")
    raw = f"{strategy}|{symbol}|{bar_timestamp.isoformat()}|{purpose}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
    cid = f"{prefix}-{purpose[:4]}-{digest}"
    assert _CLIENT_ID_RE.match(cid), cid
    return cid


def validate_order(
    order: OrderRequest,
    rules: MarketRules,
    *,
    last_price: float,
    free_quote: float,
    free_base: float,
    max_price_deviation_pct: float,
    fee_rate: float,
) -> ValidationOutcome:
    errors: list[str] = []

    if order.symbol != rules.symbol:
        errors.append(f"símbolo {order.symbol} no coincide con reglas de {rules.symbol}")
    if order.side not in ("buy", "sell"):
        errors.append(f"side inválido: {order.side}")
    if order.type not in _VALID_TYPES:
        errors.append(f"tipo inválido: {order.type}")
    if not _CLIENT_ID_RE.match(order.client_order_id or ""):
        errors.append(f"client_order_id inválido: {order.client_order_id!r}")
    if not (math.isfinite(last_price) and last_price > 0):
        errors.append(f"último precio inválido: {last_price}")
        return ValidationOutcome(False, tuple(errors))

    # --- Cantidad ---
    qty = order.quantity
    if not isinstance(qty, Decimal) or not qty.is_finite() or qty <= 0:
        errors.append(f"cantidad inválida: {qty}")
        return ValidationOutcome(False, tuple(errors))
    if not _is_multiple(qty, rules.step_size):
        errors.append(f"cantidad {qty} no es múltiplo del step {rules.step_size}")
    if qty < rules.min_qty:
        errors.append(f"cantidad {qty} < mínimo {rules.min_qty}")
    if rules.max_qty is not None and qty > rules.max_qty:
        errors.append(f"cantidad {qty} > máximo {rules.max_qty}")

    # --- Precios ---
    needs_price = order.type in ("limit", "stop_loss_limit")
    needs_stop = order.type in ("stop_loss", "stop_loss_limit")
    for name, val, needed in (("price", order.price, needs_price),
                              ("stop_price", order.stop_price, needs_stop)):
        if needed and val is None:
            errors.append(f"{order.type} requiere {name}")
        elif not needed and val is not None:
            errors.append(f"{order.type} no admite {name}")
        elif val is not None:
            if not val.is_finite() or val <= 0:
                errors.append(f"{name} inválido: {val}")
            elif not _is_multiple(val, rules.tick_size):
                errors.append(f"{name} {val} no es múltiplo del tick {rules.tick_size}")
    if errors:
        return ValidationOutcome(False, tuple(errors))

    last = Decimal(str(last_price))
    is_stop = needs_stop
    if is_stop:
        # Los stops protegen posiciones largas: deben ser ventas por debajo del precio.
        if order.side != "sell":
            errors.append("solo se admiten stops de venta (posiciones largas, sin cortos)")
        if order.stop_price >= last:
            errors.append(f"stop {order.stop_price} debe estar por debajo del precio actual {last}")
        if order.price is not None and order.price > order.stop_price:
            errors.append("en stop-limit de venta el límite debe ser <= trigger")
        ref_price = order.price if order.price is not None else order.stop_price
    else:
        ref_price = order.price if order.price is not None else last
        deviation = abs(ref_price - last) / last * 100
        if deviation > Decimal(str(max_price_deviation_pct)):
            errors.append(f"precio {ref_price} se desvía {deviation:.2f}% del último "
                          f"({last}); máximo {max_price_deviation_pct}%")
        if order.type == "market":
            # Para mercado, asumimos el peor caso razonable para el saldo.
            ref_price = last * (1 + Decimal(str(max_price_deviation_pct)) / 100) \
                if order.side == "buy" else last

    notional = qty * ref_price
    if notional < rules.min_notional:
        errors.append(f"nocional {notional:.8f} < mínimo {rules.min_notional}")

    # --- Saldo ---
    if order.side == "buy":
        required = notional * (1 + Decimal(str(fee_rate)))
        if required > Decimal(str(free_quote)):
            errors.append(f"saldo insuficiente: requiere {required:.8f}, libre {free_quote}")
    else:
        if qty > Decimal(str(free_base)):
            errors.append(f"cantidad {qty} > saldo base libre {free_base}")

    return ValidationOutcome(not errors, tuple(errors))
