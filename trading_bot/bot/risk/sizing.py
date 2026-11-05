"""Tamaño de posición basado en la distancia al stop-loss.

Idea: si el stop salta, la pérdida (incluyendo comisiones y slippage en el peor
caso) no debe superar `risk_pct` del equity.

    pérdida_por_unidad = (entrada_efectiva - stop_efectivo)
                         + comisión_entrada + comisión_salida
    cantidad = (equity * risk_pct) / pérdida_por_unidad

La cantidad se redondea SIEMPRE hacia abajo al step del exchange. Nunca hacia
arriba: eso superaría el riesgo permitido.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal


@dataclass(frozen=True)
class SizingResult:
    quantity: Decimal
    worst_case_loss: float      # pérdida estimada si salta el stop (en quote)
    notional: float             # cantidad * precio de entrada efectivo
    capped_by: str | None       # "risk", "max_notional" o None si qty=0


def floor_to_step(value: float | Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("step debe ser > 0")
    d = Decimal(str(value))
    if d <= 0:
        return Decimal(0)
    return (d / step).to_integral_value(rounding=ROUND_DOWN) * step


def worst_case_loss_per_unit(entry: float, stop: float, fee_rate: float,
                             slippage_rate: float) -> float:
    """Pérdida por unidad para una posición larga si se ejecuta el stop."""
    eff_entry = entry * (1 + slippage_rate)
    eff_exit = stop * (1 - slippage_rate)
    return (eff_entry - eff_exit) + eff_entry * fee_rate + eff_exit * fee_rate


def position_size_long(
    *,
    equity: float,
    entry: float,
    stop: float,
    risk_pct: float,
    max_notional: float,
    step: Decimal,
    fee_rate: float,
    slippage_rate: float,
) -> SizingResult:
    for name, v in (("equity", equity), ("entry", entry), ("stop", stop),
                    ("risk_pct", risk_pct), ("max_notional", max_notional)):
        if not math.isfinite(v):
            raise ValueError(f"{name} no es finito: {v}")
    if equity <= 0 or entry <= 0 or stop <= 0 or risk_pct <= 0:
        raise ValueError("equity, entry, stop y risk_pct deben ser > 0")
    if stop >= entry:
        raise ValueError(f"En largo el stop ({stop}) debe estar por debajo de la entrada ({entry})")

    loss_per_unit = worst_case_loss_per_unit(entry, stop, fee_rate, slippage_rate)
    risk_budget = equity * risk_pct / 100.0
    eff_entry = entry * (1 + slippage_rate)

    qty_risk = risk_budget / loss_per_unit
    # La comisión de entrada también consume saldo: la incluimos en el tope.
    qty_notional = max(0.0, max_notional) / (eff_entry * (1 + fee_rate))
    capped_by = "risk" if qty_risk <= qty_notional else "max_notional"
    qty = floor_to_step(min(qty_risk, qty_notional), step)

    if qty <= 0:
        return SizingResult(Decimal(0), 0.0, 0.0, None)
    q = float(qty)
    return SizingResult(
        quantity=qty,
        worst_case_loss=q * loss_per_unit,
        notional=q * eff_entry,
        capped_by=capped_by,
    )
