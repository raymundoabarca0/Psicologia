"""Descarga de velas históricas paginada (ccxt) y guardado en Parquet.

Uso:
    python -m bot.data.downloader --symbol BTC/USDT --timeframe 4h --since 2020-01-01

Los datos públicos no requieren API key.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from bot.data.validator import ohlcv_to_frame
from bot.utils.retry import retry_call
from bot.utils.timeframes import timeframe_to_ms

log = logging.getLogger(__name__)


def _network_errors() -> tuple[type[BaseException], ...]:
    try:
        import ccxt
        return (ccxt.NetworkError, ccxt.RateLimitExceeded, ccxt.ExchangeNotAvailable)
    except ImportError:  # pragma: no cover
        return (ConnectionError, TimeoutError)


def fetch_ohlcv_history(
    exchange,
    symbol: str,
    timeframe: str,
    since: datetime,
    until: datetime,
    *,
    page_limit: int = 1000,
    retries: int = 4,
    sleep=None,
) -> pd.DataFrame:
    """Descarga velas en [since, until). `exchange` es una instancia de ccxt
    (o cualquier objeto con fetch_ohlcv compatible)."""
    if since.tzinfo is None or until.tzinfo is None:
        raise ValueError("since/until deben tener zona horaria")
    tf_ms = timeframe_to_ms(timeframe)
    cursor = int(since.timestamp() * 1000)
    end_ms = int(until.timestamp() * 1000)
    rows: list[list[float]] = []
    retry_kwargs = {"retries": retries, "retry_on": _network_errors()}
    if sleep is not None:
        retry_kwargs["sleep"] = sleep

    while cursor < end_ms:
        page = retry_call(exchange.fetch_ohlcv, symbol, timeframe,
                          since=cursor, limit=page_limit, **retry_kwargs)
        page = [r for r in page if cursor <= r[0] < end_ms]
        if not page:
            break
        rows.extend(page)
        last_ts = page[-1][0]
        if last_ts < cursor:  # pragma: no cover - protección contra bucles
            raise RuntimeError("El exchange devolvió velas sin progreso")
        cursor = last_ts + tf_ms
        log.info("%s %s: %d velas (hasta %s)", symbol, timeframe, len(rows),
                 pd.Timestamp(last_ts, unit="ms", tz="UTC"))

    if not rows:
        return ohlcv_to_frame([])
    return ohlcv_to_frame(rows)


def data_path(data_dir: str | Path, exchange_id: str, symbol: str, timeframe: str) -> Path:
    return Path(data_dir) / f"{exchange_id}_{symbol.replace('/', '')}_{timeframe}.parquet"


def save_frame(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def load_frame(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def main() -> None:  # pragma: no cover - CLI
    import ccxt

    ap = argparse.ArgumentParser(description="Descarga velas históricas")
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--timeframe", default="4h")
    ap.add_argument("--since", required=True, help="YYYY-MM-DD (UTC)")
    ap.add_argument("--until", default=None, help="YYYY-MM-DD (UTC), por defecto ahora")
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    ex = getattr(ccxt, args.exchange)({"enableRateLimit": True})
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    until = (datetime.fromisoformat(args.until).replace(tzinfo=timezone.utc)
             if args.until else datetime.now(timezone.utc))
    df = fetch_ohlcv_history(ex, args.symbol, args.timeframe, since, until)
    path = data_path(args.data_dir, args.exchange, args.symbol, args.timeframe)
    save_frame(df, path)
    log.info("Guardadas %d velas en %s", len(df), path)


if __name__ == "__main__":  # pragma: no cover
    main()
