from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from bot.config import CostsConfig, RiskConfig
from bot.execution.order_validator import MarketRules
from bot.models import AccountSnapshot, Signal
from bot.risk.limits import RiskState
from bot.risk.manager import RiskManager

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def btc_rules():
    return MarketRules(symbol="BTC/USDT", step_size=Decimal("0.00001"),
                       tick_size=Decimal("0.01"), min_qty=Decimal("0.00001"),
                       min_notional=Decimal("5"))


@pytest.fixture
def costs():
    return CostsConfig(fee_rate=0.001, slippage_rate=0.0005, spread_rate=0.0002)


@pytest.fixture
def risk_cfg():
    return RiskConfig()


def make_signal(**kw) -> Signal:
    base = dict(symbol="BTC/USDT", side="buy", entry_price=50_000.0, stop_price=49_000.0,
                bar_timestamp=NOW, strategy="test", take_profit_price=53_000.0)
    base.update(kw)
    return Signal(**base)


def make_account(equity=10_000.0, free=None, positions=None) -> AccountSnapshot:
    return AccountSnapshot(equity=equity, free_quote=equity if free is None else free,
                           positions=positions or {})


@pytest.fixture
def manager(risk_cfg, costs, now):
    return RiskManager(risk_cfg, costs, RiskState.fresh(10_000.0, now, "UTC"))
