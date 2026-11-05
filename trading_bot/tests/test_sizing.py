from decimal import Decimal

import pytest

from bot.risk.sizing import floor_to_step, position_size_long, worst_case_loss_per_unit

STEP = Decimal("0.00001")


def size(**kw):
    base = dict(equity=10_000, entry=50_000, stop=49_000, risk_pct=1.0,
                max_notional=1e12, step=STEP, fee_rate=0.001, slippage_rate=0.0005)
    base.update(kw)
    return position_size_long(**base)


def test_risk_never_exceeds_budget():
    r = size()
    assert r.worst_case_loss <= 100.0
    # Debe aprovechar casi todo el presupuesto (no ser absurdamente pequeño).
    assert r.worst_case_loss > 99.0
    assert r.capped_by == "risk"


def test_no_fee_case_matches_textbook_formula():
    r = size(fee_rate=0, slippage_rate=0)
    # 100 USDT / 1000 USDT por unidad = 0.1 BTC
    assert r.quantity == Decimal("0.1")


def test_wider_stop_means_smaller_position():
    near = size(stop=49_500).quantity
    far = size(stop=45_000).quantity
    assert far < near


def test_quantity_is_rounded_down_to_step():
    r = size(equity=10_001.37)
    assert r.quantity % STEP == 0
    assert r.worst_case_loss <= 100.0137


def test_capped_by_max_notional():
    # Stop muy cercano -> la fórmula de riesgo pediría un nocional enorme.
    r = size(stop=49_950, max_notional=3_000)
    assert r.capped_by == "max_notional"
    assert r.notional * 1.001 <= 3_000 + 1e-6
    assert r.worst_case_loss < 100


@pytest.mark.parametrize("kw", [
    dict(stop=50_000), dict(stop=51_000),   # stop >= entrada
    dict(equity=0), dict(equity=-5), dict(entry=0), dict(stop=0),
    dict(risk_pct=0), dict(entry=float("nan")), dict(equity=float("inf")),
])
def test_invalid_inputs_raise(kw):
    with pytest.raises(ValueError):
        size(**kw)


def test_tiny_account_returns_zero_not_rounded_up():
    r = size(equity=1, step=Decimal("0.001"))
    assert r.quantity == 0


def test_floor_to_step():
    assert floor_to_step(0.123456789, Decimal("0.001")) == Decimal("0.123")
    assert floor_to_step(0.1239999, Decimal("0.001")) == Decimal("0.123")
    assert floor_to_step(-1, Decimal("0.001")) == 0
    with pytest.raises(ValueError):
        floor_to_step(1, Decimal(0))


def test_worst_case_includes_costs():
    assert worst_case_loss_per_unit(100, 90, 0, 0) == pytest.approx(10)
    assert worst_case_loss_per_unit(100, 90, 0.001, 0.0005) > 10
