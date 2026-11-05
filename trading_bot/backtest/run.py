"""Ejecuta el walk-forward de las tres estrategias y genera el reporte.

Uso:
    python -m backtest.run --capital 100
"""

from __future__ import annotations

import argparse
import json
import logging
from decimal import Decimal
from pathlib import Path

import pandas as pd

from backtest.engine import BacktestEngine
from backtest.metrics import buy_and_hold, max_drawdown_pct, sharpe, summarize
from backtest.walk_forward import walk_forward
from bot.config import RiskConfig, load_config
from bot.data.downloader import data_path, load_frame
from bot.data.validator import clean_ohlcv
from bot.execution.order_validator import MarketRules
from bot.strategy.strategies import ALL_STRATEGIES

# Filtros reales de Binance Spot (exchangeInfo, consultado 2026-11-04).
BINANCE_RULES = {
    "BTC/USDT": MarketRules("BTC/USDT", Decimal("0.00001"), Decimal("0.01"),
                            Decimal("0.00001"), Decimal("5"), Decimal("9000")),
    "ETH/USDT": MarketRules("ETH/USDT", Decimal("0.0001"), Decimal("0.01"),
                            Decimal("0.0001"), Decimal("5"), Decimal("9000")),
}


def load_data(cfg) -> dict[str, pd.DataFrame]:
    out = {}
    for s in cfg.exchange.symbols:
        df = load_frame(data_path(cfg.data.data_dir, "binance", s, cfg.exchange.timeframe))
        r = clean_ohlcv(df, cfg.exchange.timeframe, max_bar_move_pct=cfg.data.max_bar_move_pct,
                        drop_anomalies=False)
        kinds = pd.Series([i.kind for i in r.issues]).value_counts().to_dict()
        logging.info("%s: %d velas, incidencias %s", s, len(r.df), kinds)
        out[s] = r.df
    return out


def yearly(equity: pd.Series) -> pd.Series:
    e = equity.resample("YE").last()
    first = equity.iloc[0]
    return (e / e.shift(1).fillna(first) - 1) * 100


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/config.example.yaml")
    ap.add_argument("--capital", type=float, default=100.0)
    ap.add_argument("--out", default="reports")
    ap.add_argument("--risk-pct", type=float, default=None,
                    help="riesgo por operación (solo puede ser <= límite duro)")
    ap.add_argument("--diagnostic-no-dd-halt", action="store_true",
                    help="SOLO análisis: sin apagado por drawdown")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("bot.risk.manager").setLevel(logging.CRITICAL + 1)

    cfg = load_config(args.config)
    if args.risk_pct is not None:
        risk = RiskConfig.model_validate({**cfg.risk.model_dump(),
                                          "risk_per_trade_pct": args.risk_pct})
        cfg = cfg.model_copy(update={"risk": risk})
    data = load_data(cfg)
    out = Path(args.out)
    out.mkdir(exist_ok=True)

    rows, yearly_rows, choices_out, curves = [], {}, {}, {}
    oos_range = None
    for mult in (1.0, 2.0):
        engine = BacktestEngine(cfg, BINANCE_RULES, initial_capital=args.capital, cost_mult=mult,
                                diagnostic_no_dd_halt=args.diagnostic_no_dd_halt)
        for name, cls in ALL_STRATEGIES.items():
            logging.info("Walk-forward %s (costes x%.0f)...", name, mult)
            res, choices = walk_forward(cls, data, engine)
            m = summarize(res)
            m.update(estrategia=name, costes=f"x{mult:.0f}")
            m["rechazos"] = res.rejected
            rows.append(m)
            oos_range = (res.equity.index[0], res.equity.index[-1])
            if mult == 1.0:
                yearly_rows[name] = yearly(res.equity)
                curves[name] = res.equity
                choices_out[name] = [
                    {"prueba": f"{c.test_start:%Y-%m-%d}→{c.test_end:%Y-%m-%d}",
                     "params": c.params, "sharpe_train": round(c.train_sharpe, 2),
                     "trades_train": c.train_trades} for c in choices]
                pd.DataFrame([t.__dict__ for t in res.trades]).to_csv(
                    out / f"trades_{name}.csv", index=False)

    start, end = oos_range
    bh = buy_and_hold(data, start, end + pd.Timedelta(hours=4), args.capital, cfg.costs.fee_rate)
    curves["buy_and_hold"] = bh
    yearly_rows["buy_and_hold"] = yearly(bh)
    rows.append({"estrategia": "buy_and_hold 50/50", "costes": "x1",
                 "retorno_%": (bh.iloc[-1] / bh.iloc[0] - 1) * 100,
                 "sharpe": sharpe(bh), "max_dd_%": max_drawdown_pct(bh)})

    table = pd.DataFrame(rows).set_index(["estrategia", "costes"])
    table.to_csv(out / "summary.csv")
    pd.DataFrame(yearly_rows).to_csv(out / "yearly.csv")
    pd.DataFrame(curves).to_csv(out / "equity_curves.csv")
    (out / "walk_forward_params.json").write_text(json.dumps(choices_out, indent=2,
                                                             ensure_ascii=False))
    pd.set_option("display.width", 250, "display.max_columns", 30)
    print(f"\nPeriodo fuera de muestra: {start:%Y-%m-%d} → {end:%Y-%m-%d}, "
          f"capital inicial {args.capital}, riesgo/op {cfg.risk.risk_per_trade_pct}%"
          + ("  [DIAGNÓSTICO: sin halt por drawdown]" if args.diagnostic_no_dd_halt else ""))
    print(table.drop(columns=["rechazos"]).round(2).to_string())
    print("\nRetorno por año (%) — costes x1")
    print(pd.DataFrame(yearly_rows).round(1).to_string())
    print("\nRechazos (x1/x2):")
    for r in rows[:-1]:
        print(f"  {r['estrategia']} {r['costes']}: {r['rechazos']}")


if __name__ == "__main__":
    main()
