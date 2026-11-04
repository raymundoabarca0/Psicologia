from datetime import datetime, timedelta, timezone

import pytest

from bot.risk.limits import RiskState, RiskStatus, update_state

T0 = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)


def upd(state, equity, now=T0, tz="UTC"):
    return update_state(state, equity, now, tz=tz, max_daily_loss_pct=3.0, max_drawdown_pct=10.0)


def test_ok_within_limits():
    s = RiskState.fresh(10_000, T0, "UTC")
    assert upd(s, 9_800) is RiskStatus.OK


def test_daily_loss_triggers_daily_halt():
    s = RiskState.fresh(10_000, T0, "UTC")
    assert upd(s, 9_700) is RiskStatus.DAILY_HALT
    # Recuperar dentro del mismo día NO reactiva el bot.
    assert upd(s, 10_000, T0 + timedelta(hours=1)) is RiskStatus.DAILY_HALT


def test_daily_halt_resets_next_day():
    s = RiskState.fresh(10_000, T0, "UTC")
    s.trades_today = 4
    upd(s, 9_650)
    assert upd(s, 9_650, T0 + timedelta(days=1)) is RiskStatus.OK
    assert s.trades_today == 0
    assert s.day_start_equity == 9_650


def test_drawdown_measured_from_peak_and_is_permanent():
    s = RiskState.fresh(10_000, T0, "UTC")
    day = T0
    # Sube a 12_000 a lo largo de varios días.
    for i, eq in enumerate([10_500, 11_000, 11_500, 12_000]):
        day = T0 + timedelta(days=i + 1)
        assert upd(s, eq, day) is RiskStatus.OK
    assert s.peak_equity == 12_000
    # Baja poco a poco (sin superar el 3% diario) hasta -10% desde el pico.
    eq = 12_000
    status = RiskStatus.OK
    while status is not RiskStatus.PERMANENT_HALT:
        day += timedelta(days=1)
        eq *= 0.98
        status = upd(s, eq, day)
    assert eq <= 12_000 * 0.90
    # Ni un nuevo día ni la recuperación quitan el halt permanente.
    assert upd(s, 20_000, day + timedelta(days=5)) is RiskStatus.PERMANENT_HALT
    assert s.permanently_halted


def test_nan_equity_halts():
    s = RiskState.fresh(10_000, T0, "UTC")
    assert upd(s, float("nan")) is RiskStatus.PERMANENT_HALT


def test_state_roundtrip():
    s = RiskState.fresh(10_000, T0, "UTC")
    s.trades_today = 2
    assert RiskState.from_dict(s.to_dict()) == s


def test_timezone_day_boundary():
    # 23:30 UTC del 15 = 17:30 en Ciudad de México (mismo día);
    # 06:30 UTC del 16 = 00:30 del 16 en CDMX -> nuevo día.
    tz = "America/Mexico_City"
    s = RiskState.fresh(10_000, datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc), tz)
    s.trades_today = 3
    upd(s, 10_000, datetime(2026, 1, 16, 5, 0, tzinfo=timezone.utc), tz=tz)
    assert s.trades_today == 3
    upd(s, 10_000, datetime(2026, 1, 16, 6, 30, tzinfo=timezone.utc), tz=tz)
    assert s.trades_today == 0


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        RiskState.fresh(10_000, datetime(2026, 1, 1), "UTC")
