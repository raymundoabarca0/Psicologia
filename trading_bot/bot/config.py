"""Carga y validación de la configuración.

- Los parámetros viven en un YAML (config/config.yaml).
- Los secretos (API keys, tokens) SOLO vienen de variables de entorno / .env.
- Cualquier clave desconocida en el YAML es un error (evita typos silenciosos).
- Los límites de riesgo se validan contra bot.risk.hard_limits.
- El modo real requiere DOS llaves: `live_trading: true` en el YAML Y la
  variable de entorno LIVE_TRADING=true. Si falta cualquiera -> modo simulado.
"""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bot.risk import hard_limits as HL
from bot.utils.timeframes import timeframe_to_timedelta


class ConfigError(ValueError):
    """La configuración es inválida o insegura."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExchangeConfig(_Strict):
    name: Literal["binance"] = "binance"
    symbols: tuple[str, ...] = ("BTC/USDT", "ETH/USDT")
    quote_currency: str = "USDT"
    timeframe: str = "4h"
    # En modo paper: "testnet" usa el testnet del exchange; "simulated" usa el
    # broker simulado local con precios reales.
    paper_backend: Literal["testnet", "simulated"] = "testnet"
    request_timeout_ms: int = Field(default=10_000, ge=1_000, le=60_000)

    @model_validator(mode="after")
    def _check(self) -> "ExchangeConfig":
        if not self.symbols:
            raise ValueError("exchange.symbols no puede estar vacío")
        for s in self.symbols:
            if "/" not in s or not s.endswith("/" + self.quote_currency):
                raise ValueError(f"símbolo {s!r} no cotiza en {self.quote_currency}")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("exchange.symbols tiene duplicados")
        timeframe_to_timedelta(self.timeframe)  # lanza si es inválido
        return self


class RiskConfig(_Strict):
    risk_per_trade_pct: float = Field(default=1.0, gt=0)
    max_daily_loss_pct: float = Field(default=3.0, gt=0)
    max_drawdown_pct: float = Field(default=10.0, gt=0)
    max_open_positions: int = Field(default=3, ge=1)
    max_trades_per_day: int = Field(default=4, ge=1)
    max_position_pct_of_equity: float = Field(default=33.0, gt=0)
    # Distancia al stop permitida (en % del precio de entrada). Stops demasiado
    # ajustados generan tamaños enormes y el slippage domina; demasiado lejanos
    # suelen indicar una señal errónea.
    min_stop_distance_pct: float = Field(default=0.3, gt=0)
    max_stop_distance_pct: float = Field(default=20.0, gt=0)
    # Zona horaria en la que se reinicia el "día" para el límite diario.
    day_reset_timezone: str = "UTC"
    leverage: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def _within_hard_limits(self) -> "RiskConfig":
        checks = [
            ("risk_per_trade_pct", self.risk_per_trade_pct, HL.MAX_RISK_PER_TRADE_PCT),
            ("max_daily_loss_pct", self.max_daily_loss_pct, HL.MAX_DAILY_LOSS_PCT),
            ("max_drawdown_pct", self.max_drawdown_pct, HL.MAX_DRAWDOWN_PCT),
            ("max_open_positions", self.max_open_positions, HL.MAX_OPEN_POSITIONS),
            ("max_trades_per_day", self.max_trades_per_day, HL.MAX_TRADES_PER_DAY),
            ("max_position_pct_of_equity", self.max_position_pct_of_equity,
             HL.MAX_POSITION_PCT_OF_EQUITY),
            ("leverage", self.leverage, HL.MAX_LEVERAGE),
        ]
        for name, value, limit in checks:
            if value > limit:
                raise ValueError(
                    f"risk.{name}={value} supera el límite duro {limit}. "
                    "La configuración solo puede ser más estricta que los límites duros."
                )
        if self.min_stop_distance_pct >= self.max_stop_distance_pct:
            raise ValueError("min_stop_distance_pct debe ser < max_stop_distance_pct")
        return self


class CostsConfig(_Strict):
    """Costes usados para dimensionar (peor caso) y en el backtest."""

    fee_rate: float = Field(default=0.001, ge=0, le=0.01)        # 0.1% por lado
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.02)  # 0.05%
    spread_rate: float = Field(default=0.0002, ge=0, le=0.02)    # 0.02% (ida y vuelta)


class OrdersConfig(_Strict):
    max_price_deviation_pct: float = Field(default=1.0, gt=0)
    # Para stop-limit de venta: el límite se coloca este % por debajo del trigger.
    stop_limit_buffer_pct: float = Field(default=0.5, gt=0, le=5)
    client_order_id_prefix: str = Field(default="tb", pattern=r"^[A-Za-z0-9]{1,6}$")

    @model_validator(mode="after")
    def _check(self) -> "OrdersConfig":
        if self.max_price_deviation_pct > HL.MAX_PRICE_DEVIATION_PCT:
            raise ValueError(
                f"orders.max_price_deviation_pct supera el límite duro {HL.MAX_PRICE_DEVIATION_PCT}"
            )
        return self


class DataConfig(_Strict):
    data_dir: str = "data"
    # Una vela cuyo retorno (o mecha) supere este % se considera anómala.
    max_bar_move_pct: float = Field(default=25.0, gt=0)
    # Velas recientes sin huecos necesarias para poder operar.
    required_clean_bars: int = Field(default=250, ge=10)
    # Datos desactualizados: última vela cerrada más antigua que N timeframes.
    max_staleness_bars: float = Field(default=1.5, gt=0)


class SafetyConfig(_Strict):
    kill_switch_file: str = "KILL"
    halt_file: str = "HALTED"
    max_consecutive_errors: int = Field(default=5, ge=1)
    # Pausa si el rango de la última vela supera N veces el ATR.
    volatility_pause_atr_multiple: float = Field(default=4.0, gt=1)


class AlertsConfig(_Strict):
    channel: Literal["telegram", "email", "none"] = "telegram"


class BotConfig(_Strict):
    live_trading: bool = False
    exchange: ExchangeConfig = ExchangeConfig()
    risk: RiskConfig = RiskConfig()
    costs: CostsConfig = CostsConfig()
    orders: OrdersConfig = OrdersConfig()
    data: DataConfig = DataConfig()
    safety: SafetyConfig = SafetyConfig()
    alerts: AlertsConfig = AlertsConfig()


class TradingMode(enum.Enum):
    PAPER = "paper"
    LIVE = "live"


def resolve_trading_mode(cfg: BotConfig, env: Mapping[str, str] | None = None) -> TradingMode:
    """Modo real SOLO si el YAML y la variable de entorno lo piden explícitamente."""
    env = os.environ if env is None else env
    env_flag = env.get("LIVE_TRADING", "").strip().lower() == "true"
    if cfg.live_trading and env_flag:
        return TradingMode.LIVE
    return TradingMode.PAPER


@dataclass(frozen=True)
class Secrets:
    api_key: str | None
    api_secret: str | None
    telegram_token: str | None
    telegram_chat_id: str | None

    def __repr__(self) -> str:  # nunca imprimir secretos en logs
        def mask(v: str | None) -> str:
            return "None" if not v else "***"
        return (f"Secrets(api_key={mask(self.api_key)}, api_secret={mask(self.api_secret)}, "
                f"telegram_token={mask(self.telegram_token)}, "
                f"telegram_chat_id={mask(self.telegram_chat_id)})")

    __str__ = __repr__


def load_secrets(mode: TradingMode, env: Mapping[str, str] | None = None) -> Secrets:
    env = os.environ if env is None else env
    prefix = "BINANCE_" if mode is TradingMode.LIVE else "BINANCE_TESTNET_"
    return Secrets(
        api_key=env.get(prefix + "API_KEY") or None,
        api_secret=env.get(prefix + "API_SECRET") or None,
        telegram_token=env.get("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=env.get("TELEGRAM_CHAT_ID") or None,
    )


def load_config(path: str | Path) -> BotConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"No existe el archivo de configuración: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError("La raíz del YAML debe ser un mapa")
    try:
        return BotConfig.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError
        raise ConfigError(str(exc)) from exc


def load_dotenv_if_present(path: str | Path = ".env") -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    if Path(path).exists():
        load_dotenv(path, override=False)
