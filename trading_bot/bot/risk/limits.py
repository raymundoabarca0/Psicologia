"""Estado de riesgo de la cuenta: pérdida diaria, drawdown y contadores.

- Pérdida diaria: equity actual vs equity al inicio del día (incluye P&L no
  realizado). Si cae >= max_daily_loss_pct -> pausa hasta el día siguiente.
- Drawdown: equity actual vs máximo histórico de equity. Si cae >=
  max_drawdown_pct -> HALT permanente; solo se levanta con reinicio manual.

El estado es serializable (to_dict/from_dict) para persistirlo entre reinicios:
reiniciar el bot NO resetea el contador diario ni el máximo de equity.
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo


class RiskStatus(enum.Enum):
    OK = "ok"
    DAILY_HALT = "daily_halt"
    PERMANENT_HALT = "permanent_halt"


@dataclass
class RiskState:
    peak_equity: float
    day: date
    day_start_equity: float
    trades_today: int = 0
    daily_halted: bool = False
    permanently_halted: bool = False
    halt_reason: str | None = None

    @classmethod
    def fresh(cls, equity: float, now: datetime, tz: str) -> "RiskState":
        if equity <= 0:
            raise ValueError("equity inicial debe ser > 0")
        return cls(peak_equity=equity, day=local_day(now, tz), day_start_equity=equity)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["day"] = self.day.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RiskState":
        d = dict(d)
        d["day"] = date.fromisoformat(d["day"])
        return cls(**d)


def local_day(now: datetime, tz: str) -> date:
    if now.tzinfo is None:
        raise ValueError("Se requieren datetimes con zona horaria (UTC)")
    return now.astimezone(ZoneInfo(tz)).date()


def drawdown_pct(equity: float, peak: float) -> float:
    return 0.0 if peak <= 0 else max(0.0, (peak - equity) / peak * 100.0)


def daily_loss_pct(equity: float, day_start: float) -> float:
    return 0.0 if day_start <= 0 else max(0.0, (day_start - equity) / day_start * 100.0)


def update_state(
    state: RiskState,
    equity: float,
    now: datetime,
    *,
    tz: str,
    max_daily_loss_pct: float,
    max_drawdown_pct: float,
) -> RiskStatus:
    """Actualiza el estado con el equity actual y devuelve el estado de riesgo."""
    if not (equity == equity) or equity < 0:  # NaN o negativo
        state.permanently_halted = True
        state.halt_reason = f"equity inválido: {equity}"
        return RiskStatus.PERMANENT_HALT

    today = local_day(now, tz)
    if today > state.day:
        # Nuevo día: se resetean contador y pausa diaria (NO el halt permanente).
        state.day = today
        state.day_start_equity = equity
        state.trades_today = 0
        state.daily_halted = False

    if equity > state.peak_equity:
        state.peak_equity = equity

    if state.permanently_halted:
        return RiskStatus.PERMANENT_HALT

    dd = drawdown_pct(equity, state.peak_equity)
    if dd >= max_drawdown_pct:
        state.permanently_halted = True
        state.halt_reason = (f"drawdown {dd:.2f}% >= {max_drawdown_pct}% "
                             f"(pico {state.peak_equity:.2f}, equity {equity:.2f})")
        return RiskStatus.PERMANENT_HALT

    dl = daily_loss_pct(equity, state.day_start_equity)
    if dl >= max_daily_loss_pct:
        if not state.daily_halted:
            state.halt_reason = (f"pérdida diaria {dl:.2f}% >= {max_daily_loss_pct}% "
                                 f"(inicio día {state.day_start_equity:.2f}, equity {equity:.2f})")
        state.daily_halted = True

    return RiskStatus.DAILY_HALT if state.daily_halted else RiskStatus.OK
