import textwrap

import pytest

from bot.config import (BotConfig, ConfigError, RiskConfig, TradingMode, load_config,
                        load_secrets, resolve_trading_mode)


def test_defaults_are_safe():
    cfg = BotConfig()
    assert cfg.live_trading is False
    assert cfg.risk.risk_per_trade_pct <= 1.0
    assert cfg.risk.leverage == 1.0
    assert resolve_trading_mode(cfg, env={}) is TradingMode.PAPER


@pytest.mark.parametrize("field,value", [
    ("risk_per_trade_pct", 1.5),
    ("max_daily_loss_pct", 5.0),
    ("max_drawdown_pct", 20.0),
    ("max_open_positions", 10),
    ("max_trades_per_day", 100),
    ("leverage", 3.0),
])
def test_config_cannot_loosen_hard_limits(field, value):
    with pytest.raises(ValueError, match="límite duro"):
        RiskConfig(**{field: value})


def test_config_can_tighten_limits():
    cfg = RiskConfig(risk_per_trade_pct=0.5, max_open_positions=1)
    assert cfg.risk_per_trade_pct == 0.5


@pytest.mark.parametrize("yaml_flag,env,expected", [
    (False, {}, TradingMode.PAPER),
    (True, {}, TradingMode.PAPER),
    (False, {"LIVE_TRADING": "true"}, TradingMode.PAPER),
    (True, {"LIVE_TRADING": "false"}, TradingMode.PAPER),
    (True, {"LIVE_TRADING": "yes"}, TradingMode.PAPER),
    (True, {"LIVE_TRADING": "TRUE"}, TradingMode.LIVE),
    (True, {"LIVE_TRADING": "true"}, TradingMode.LIVE),
])
def test_live_requires_both_flags(yaml_flag, env, expected):
    assert resolve_trading_mode(BotConfig(live_trading=yaml_flag), env=env) is expected


def test_unknown_keys_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("risk:\n  risk_per_trade: 0.5\n")  # typo
    with pytest.raises(ConfigError):
        load_config(p)


def test_api_keys_not_allowed_in_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("exchange:\n  api_key: abc\n")
    with pytest.raises(ConfigError):
        load_config(p)


def test_example_config_loads():
    cfg = load_config("config/config.example.yaml")
    assert cfg.live_trading is False


def test_load_full_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent("""
        live_trading: false
        exchange:
          symbols: [BTC/USDT]
          timeframe: 1h
        risk:
          risk_per_trade_pct: 0.5
    """))
    cfg = load_config(p)
    assert cfg.exchange.timeframe == "1h"
    assert cfg.risk.risk_per_trade_pct == 0.5


def test_symbols_must_match_quote():
    with pytest.raises(ValueError):
        BotConfig.model_validate({"exchange": {"symbols": ["BTC/EUR"]}})


def test_secrets_never_printed():
    s = load_secrets(TradingMode.PAPER, env={"BINANCE_TESTNET_API_KEY": "SUPERSECRET",
                                             "BINANCE_TESTNET_API_SECRET": "X"})
    assert s.api_key == "SUPERSECRET"
    assert "SUPERSECRET" not in repr(s) and "SUPERSECRET" not in str(s)


def test_paper_mode_never_uses_live_keys():
    env = {"BINANCE_API_KEY": "live", "BINANCE_TESTNET_API_KEY": "test"}
    assert load_secrets(TradingMode.PAPER, env=env).api_key == "test"
    assert load_secrets(TradingMode.LIVE, env=env).api_key == "live"
