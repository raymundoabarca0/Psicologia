from datetime import datetime, timezone
from decimal import Decimal

import pytest

from bot.execution.order_validator import (MarketRules, make_client_order_id, quantize_price,
                                           quantize_qty, validate_order)
from bot.models import OrderRequest

CID = "tb-entr-0123456789abcdef01234567"


def order(**kw):
    base = dict(symbol="BTC/USDT", side="buy", type="limit", quantity=Decimal("0.01"),
                client_order_id=CID, price=Decimal("50000.00"))
    base.update(kw)
    return OrderRequest(**base)


def check(o, rules, last=50_000.0, free_quote=10_000.0, free_base=1.0, dev=1.0):
    return validate_order(o, rules, last_price=last, free_quote=free_quote,
                          free_base=free_base, max_price_deviation_pct=dev, fee_rate=0.001)


def test_valid_limit_buy(btc_rules):
    r = check(order(), btc_rules)
    assert r.ok, r.errors


def test_valid_market_buy(btc_rules):
    assert check(order(type="market", price=None), btc_rules).ok


def test_valid_stop_loss_limit(btc_rules):
    o = order(side="sell", type="stop_loss_limit", stop_price=Decimal("49000.00"),
              price=Decimal("48755.00"))
    assert check(o, btc_rules).ok


@pytest.mark.parametrize("kw,msg", [
    (dict(quantity=Decimal("0.000015")), "step"),
    (dict(quantity=Decimal("0")), "cantidad inválida"),
    (dict(quantity=Decimal("-1")), "cantidad inválida"),
    (dict(quantity=Decimal("NaN")), "cantidad inválida"),
    (dict(quantity=Decimal("0.00005")), "nocional"),        # 2.5 USDT < 5
    (dict(price=Decimal("50000.001")), "tick"),
    (dict(price=Decimal("51000.00")), "desvía"),            # +2% > 1%
    (dict(price=Decimal("48000.00")), "desvía"),
    (dict(price=None), "requiere price"),
    (dict(type="market"), "no admite price"),
    (dict(quantity=Decimal("1")), "saldo insuficiente"),     # 50k > 10k
    (dict(client_order_id="x" * 40), "client_order_id"),
    (dict(client_order_id="has space"), "client_order_id"),
    (dict(type="foo"), "tipo inválido"),
    (dict(symbol="ETH/USDT"), "no coincide"),
])
def test_invalid_orders_rejected(btc_rules, kw, msg):
    r = check(order(**kw), btc_rules)
    assert not r.ok
    assert any(msg in e for e in r.errors), r.errors


def test_market_buy_uses_worst_case_price_for_balance(btc_rules):
    # 0.2 BTC * 50k = 10k exactos; con deviation+fee ya no alcanza.
    o = order(type="market", price=None, quantity=Decimal("0.2"))
    assert not check(o, btc_rules).ok


def test_stop_must_be_below_price(btc_rules):
    o = order(side="sell", type="stop_loss", price=None, stop_price=Decimal("50500.00"))
    r = check(o, btc_rules)
    assert not r.ok and any("por debajo" in e for e in r.errors)


def test_buy_stops_rejected(btc_rules):
    o = order(side="buy", type="stop_loss", price=None, stop_price=Decimal("49000.00"))
    assert not check(o, btc_rules).ok


def test_stop_limit_price_must_not_exceed_trigger(btc_rules):
    o = order(side="sell", type="stop_loss_limit", stop_price=Decimal("49000.00"),
              price=Decimal("49100.00"))
    assert not check(o, btc_rules).ok


def test_sell_needs_base_balance(btc_rules):
    o = order(side="sell", type="market", price=None, quantity=Decimal("0.5"))
    assert not check(o, btc_rules, free_base=0.1).ok
    assert check(o, btc_rules, free_base=0.5).ok


@pytest.mark.parametrize("last", [0, -1, float("nan"), float("inf")])
def test_bad_last_price_rejects(btc_rules, last):
    assert not check(order(), btc_rules, last=last).ok


def test_quantize_helpers():
    assert quantize_qty(0.0123456, Decimal("0.0001")) == Decimal("0.0123")
    assert quantize_price(100.005, Decimal("0.01"), "down") == Decimal("100.00")
    assert quantize_price(100.001, Decimal("0.01"), "up") == Decimal("100.01")


def test_client_order_id_is_deterministic_and_unique():
    ts = datetime(2026, 1, 1, 4, tzinfo=timezone.utc)
    a = make_client_order_id("tb", "ema", "BTC/USDT", ts, "entry")
    b = make_client_order_id("tb", "ema", "BTC/USDT", ts, "entry")
    c = make_client_order_id("tb", "ema", "BTC/USDT", ts, "stop")
    d = make_client_order_id("tb", "ema", "ETH/USDT", ts, "entry")
    assert a == b                        # reintento -> mismo ID -> sin duplicados
    assert len({a, c, d}) == 3
    assert len(a) <= 36


def test_client_order_id_requires_tz():
    with pytest.raises(ValueError):
        make_client_order_id("tb", "s", "BTC/USDT", datetime(2026, 1, 1), "entry")


def test_rules_from_ccxt_market():
    m = {"symbol": "BTC/USDT", "precision": {"amount": 1e-05, "price": 0.01},
         "limits": {"amount": {"min": 1e-05, "max": 9000.0}, "cost": {"min": 5.0}}}
    r = MarketRules.from_ccxt_market(m)
    assert r.step_size == Decimal("0.00001") and r.tick_size == Decimal("0.01")
    assert r.min_notional == Decimal("5.0") and r.max_qty == Decimal("9000.0")
    r2 = MarketRules.from_ccxt_market({**m, "precision": {"amount": 5, "price": 2}},
                                      precision_mode_tick_size=False)
    assert r2.step_size == Decimal("0.00001")
    with pytest.raises(ValueError):
        MarketRules.from_ccxt_market({**m, "precision": {}})
