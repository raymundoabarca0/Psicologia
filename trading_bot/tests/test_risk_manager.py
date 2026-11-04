from datetime import timedelta
from decimal import Decimal

import pytest

from bot.config import RiskConfig
from bot.models import Position
from bot.risk.limits import RiskState
from bot.risk.manager import RiskManager
from tests.conftest import make_account, make_signal


def test_valid_signal_approved_and_risk_capped(manager, btc_rules, now):
    d = manager.evaluate_entry(make_signal(), make_account(), btc_rules, now)
    assert d.approved, d.reasons
    assert d.worst_case_loss <= 100.0          # 1% de 10_000
    assert d.quantity % btc_rules.step_size == 0
    assert d.notional <= 10_000 * 0.33 + 1e-6  # máx. 33% por posición


@pytest.mark.parametrize("kw,msg", [
    (dict(side="sell"), "largas"),
    (dict(stop_price=50_000), "stop"),
    (dict(stop_price=51_000), "stop"),
    (dict(stop_price=float("nan")), "inválido"),
    (dict(take_profit_price=None), "take-profit o trailing"),
    (dict(take_profit_price=49_500), "take-profit"),
    (dict(stop_price=49_990), "demasiado cerca"),
    (dict(stop_price=30_000), "demasiado lejos"),
    (dict(symbol="ETH/USDT"), "no coincide"),
    (dict(take_profit_price=None, trailing_stop_pct=0), "trailing"),
])
def test_bad_signals_rejected(manager, btc_rules, now, kw, msg):
    d = manager.evaluate_entry(make_signal(**kw), make_account(), btc_rules, now)
    assert not d.approved
    assert any(msg in r for r in d.reasons), d.reasons


def test_trailing_stop_accepted_instead_of_tp(manager, btc_rules, now):
    s = make_signal(take_profit_price=None, trailing_stop_pct=3.0)
    assert manager.evaluate_entry(s, make_account(), btc_rules, now).approved


def test_no_averaging_down(manager, btc_rules, now):
    pos = {"BTC/USDT": Position("BTC/USDT", Decimal("0.01"), 50_000, 49_000)}
    d = manager.evaluate_entry(make_signal(), make_account(positions=pos), btc_rules, now)
    assert not d.approved and "promediar" in d.reasons[0]


def test_max_open_positions(manager, btc_rules, now):
    pos = {s: Position(s, Decimal("1"), 10, 9) for s in ("A/USDT", "B/USDT", "C/USDT")}
    d = manager.evaluate_entry(make_signal(), make_account(positions=pos), btc_rules, now)
    assert not d.approved and "posiciones" in d.reasons[0]


def test_max_trades_per_day(manager, btc_rules, now):
    for _ in range(manager.max_trades):
        manager.record_entry()
    d = manager.evaluate_entry(make_signal(), make_account(), btc_rules, now)
    assert not d.approved and "diarias" in d.reasons[0]
    # Al día siguiente se puede volver a operar.
    d = manager.evaluate_entry(make_signal(), make_account(), btc_rules, now + timedelta(days=1))
    assert d.approved


def test_daily_loss_blocks_entries(manager, btc_rules, now):
    d = manager.evaluate_entry(make_signal(), make_account(equity=9_690), btc_rules, now)
    assert not d.approved and "pausa diaria" in d.reasons[0]


def test_drawdown_halts_permanently_and_calls_callback(risk_cfg, costs, btc_rules, now):
    calls = []
    state = RiskState.fresh(10_000, now, "UTC")
    state.peak_equity = 11_000
    m = RiskManager(risk_cfg, costs, state, on_permanent_halt=calls.append)
    d = m.evaluate_entry(make_signal(), make_account(equity=9_890), btc_rules, now)
    assert not d.approved and "halt permanente" in d.reasons[0]
    m.evaluate_entry(make_signal(), make_account(equity=9_890), btc_rules, now)
    assert len(calls) == 1  # se notifica una sola vez


def test_kill_switch_blocks(risk_cfg, costs, btc_rules, now):
    m = RiskManager(risk_cfg, costs, RiskState.fresh(10_000, now, "UTC"),
                    is_kill_switch_active=lambda: True)
    assert not m.evaluate_entry(make_signal(), make_account(), btc_rules, now).approved


def test_no_leverage_limited_by_free_balance(manager, btc_rules, now):
    # Equity 10k pero solo 500 libres (resto en otras posiciones).
    pos = {"ETH/USDT": Position("ETH/USDT", Decimal("3"), 3_000, 2_900)}
    d = manager.evaluate_entry(make_signal(), make_account(free=500, positions=pos),
                               btc_rules, now)
    assert d.approved
    assert d.notional <= 500


def test_exposure_full_rejects(manager, btc_rules, now):
    pos = {"ETH/USDT": Position("ETH/USDT", Decimal("3.4"), 3_000, 2_900)}
    d = manager.evaluate_entry(make_signal(), make_account(free=0, positions=pos),
                               btc_rules, now)
    assert not d.approved


def test_below_exchange_minimum_rejected_not_rounded_up(costs, now):
    from bot.execution.order_validator import MarketRules
    rules = MarketRules("BTC/USDT", Decimal("0.001"), Decimal("0.01"),
                        Decimal("0.001"), Decimal("10"))
    m = RiskManager(RiskConfig(), costs, RiskState.fresh(100, now, "UTC"))
    d = m.evaluate_entry(make_signal(), make_account(equity=100), rules, now)
    assert not d.approved
    assert any("mínimo" in r or "0 tras redondear" in r for r in d.reasons)


def test_effective_limits_never_exceed_hard_limits(manager):
    from bot.risk import hard_limits as HL
    assert manager.risk_pct <= HL.MAX_RISK_PER_TRADE_PCT
    assert manager.max_dd <= HL.MAX_DRAWDOWN_PCT
    assert manager.leverage <= HL.MAX_LEVERAGE


@pytest.mark.parametrize("equity", [1_000, 7_777.77, 10_000, 250_000])
@pytest.mark.parametrize("stop", [49_800, 48_000, 45_000, 41_000])
def test_property_risk_never_above_one_percent(risk_cfg, costs, btc_rules, now, equity, stop):
    m = RiskManager(risk_cfg, costs, RiskState.fresh(equity, now, "UTC"))
    d = m.evaluate_entry(make_signal(stop_price=stop), make_account(equity=equity),
                         btc_rules, now)
    if d.approved:
        assert d.worst_case_loss <= equity * 0.01 + 1e-9
        assert d.notional <= equity
