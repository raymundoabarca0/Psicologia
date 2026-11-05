"""Tipos de datos compartidos entre módulos."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop_loss", "stop_loss_limit"]


@dataclass(frozen=True)
class Signal:
    """Propuesta de la estrategia. La estrategia NUNCA envía órdenes: solo propone."""

    symbol: str
    side: Side
    entry_price: float          # precio de referencia (último cierre / precio actual)
    stop_price: float           # obligatorio
    bar_timestamp: datetime     # vela que generó la señal (para IDs idempotentes)
    strategy: str
    take_profit_price: float | None = None
    trailing_stop_pct: float | None = None   # % por debajo del máximo alcanzado


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: Decimal
    entry_price: float
    stop_price: float


@dataclass(frozen=True)
class AccountSnapshot:
    """Foto del estado de la cuenta (valorada a mercado)."""

    equity: float                       # efectivo + posiciones a precio actual
    free_quote: float                   # saldo libre en la moneda de cotización
    positions: dict[str, Position] = field(default_factory=dict)

    @property
    def exposure(self) -> float:
        return sum(float(p.quantity) * p.entry_price for p in self.positions.values())


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: Side
    type: OrderType
    quantity: Decimal
    client_order_id: str
    price: Decimal | None = None        # límite (limit / stop_loss_limit)
    stop_price: Decimal | None = None   # trigger (stop_loss / stop_loss_limit)
