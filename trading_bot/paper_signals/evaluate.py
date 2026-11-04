"""Evalúa las señales registradas en signals.csv contra los precios reales (velas 1h).

Reglas (conservadoras, iguales para todas las señales):
- Solo cuentan velas que empiezan DESPUÉS de registrar la señal.
- market: entra a la apertura de la primera vela 1h posterior (+ slippage).
- limit: entra si el precio toca el nivel antes de `expires_utc`; si no, "expirada".
- En la vela de entrada solo se comprueba el stop (si también se tocó el stop,
  se asume que saltó). El take-profit cuenta desde la vela siguiente.
- Si en una vela se tocan stop y take-profit, cuenta el STOP.
- Gap más allá del stop: sale a la apertura.
- manual_close_utc: cierre a mercado decidido después (nunca con fecha pasada).
- Comisión 0,1% por lado; slippage 0,05% en mercado/stop.
- Capital simulado 100 USD; riesgo 1% del equity por operación; sin
  apalancamiento (nocional total <= equity).

Uso:  python -m paper_signals.evaluate
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from paper_signals.market import klines

HERE = Path(__file__).parent
SIGNALS = HERE / "signals.csv"
REPORT = HERE / "REPORTE.md"
CAPITAL = 100.0
RISK_PCT = 1.0
FEE = 0.001
SLIP = 0.0005
CASH_BUFFER = 0.02


@dataclass
class Path_:
    status: str                    # pendiente | expirada | abierta | tp | stop | gap_stop | manual
    fill_time: pd.Timestamp | None = None
    fill_price: float | None = None
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    mark_price: float | None = None


def _simulate(sig: pd.Series, bars: pd.DataFrame) -> Path_:
    long = sig.direction == "long"
    sgn = 1 if long else -1
    created = pd.Timestamp(sig.created_utc)
    expires = pd.Timestamp(sig.expires_utc)
    manual = pd.Timestamp(sig.manual_close_utc) if pd.notna(sig.manual_close_utc) else None
    bars = bars[bars.index >= created.ceil("h")]
    if bars.empty:
        return Path_("pendiente")

    stop, tp, entry = float(sig.stop), float(sig.take_profit), float(sig.entry)
    p = None
    for t, b in bars.iterrows():
        if p is None:  # sin entrar todavía
            if manual is not None and t >= manual:
                return Path_("cancelada")
            if sig.entry_type == "market":
                fill = b.open * (1 + sgn * SLIP)
            else:
                if t >= expires:
                    return Path_("expirada")
                touched = b.low <= entry if long else b.high >= entry
                if not touched:
                    continue
                fill = min(b.open, entry) if long else max(b.open, entry)
            p = Path_("abierta", t, fill)
            # En la vela de entrada solo el stop (peor caso).
            if (b.low <= stop) if long else (b.high >= stop):
                p.status, p.exit_time, p.exit_price = "stop", t, stop * (1 - sgn * SLIP)
                return p
            continue

        if manual is not None and t >= manual:
            p.status, p.exit_time, p.exit_price = "manual", t, b.open * (1 - sgn * SLIP)
            return p
        gap = b.open <= stop if long else b.open >= stop
        hit_stop = b.low <= stop if long else b.high >= stop
        hit_tp = b.high >= tp if long else b.low <= tp
        if gap:
            p.status, p.exit_time, p.exit_price = "gap_stop", t, b.open * (1 - sgn * SLIP)
            return p
        if hit_stop:
            p.status, p.exit_time, p.exit_price = "stop", t, stop * (1 - sgn * SLIP)
            return p
        if hit_tp:
            p.status, p.exit_time, p.exit_price = "tp", t, tp
            return p
    if p is not None:
        p.mark_price = float(bars.close.iloc[-1])
    return p or Path_("pendiente")


def evaluate() -> pd.DataFrame:
    sigs = pd.read_csv(SIGNALS)
    if "manual_close_utc" not in sigs:
        sigs["manual_close_utc"] = pd.NA
    start = pd.Timestamp(sigs.created_utc.min()).floor("h")
    bars = {s: klines(s, "1h", start=start) for s in sigs.symbol.unique()}
    paths = {r.id: _simulate(r, bars[r.symbol]) for r in sigs.itertuples(index=False)
             for r in [pd.Series(r._asdict())]}

    # Tamaños secuenciales por orden de entrada (equity realizado hasta ese momento).
    rows, closed = [], []          # closed: (exit_time, pnl)
    open_notional: list[tuple[pd.Timestamp | None, float]] = []
    order = sorted((s for s in sigs.itertuples() if paths[s.id].fill_time is not None),
                   key=lambda s: paths[s.id].fill_time)
    sized = {}
    for s in order:
        p = paths[s.id]
        eq = CAPITAL + sum(pnl for et, pnl in closed if et <= p.fill_time)
        used = sum(n for et, n in open_notional if et is None or et > p.fill_time)
        per_unit = abs(p.fill_price - s.stop) + (p.fill_price + s.stop) * FEE + s.stop * SLIP
        qty = eq * RISK_PCT / 100 / per_unit
        cap = max(0.0, eq * (1 - CASH_BUFFER) - used) / (p.fill_price * (1 + FEE))
        qty = min(qty, cap)
        sgn = 1 if s.direction == "long" else -1
        fees = qty * p.fill_price * FEE
        if p.exit_price is not None:
            fees += qty * p.exit_price * FEE
            pnl = sgn * qty * (p.exit_price - p.fill_price) - fees
            closed.append((p.exit_time, pnl))
        else:
            pnl = sgn * qty * (p.mark_price - p.fill_price) - fees  # no realizado
        open_notional.append((p.exit_time, qty * p.fill_price))
        risk = eq * RISK_PCT / 100
        sized[s.id] = dict(qty=qty, pnl=pnl, fees=fees, r=pnl / risk if risk else 0.0)

    for s in sigs.itertuples():
        p = paths[s.id]
        z = sized.get(s.id, {})
        rows.append({
            "id": s.id, "creada": s.created_utc[:16], "activo": s.asset,
            "dir": s.direction, "tipo": s.entry_type, "entrada": s.entry, "stop": s.stop,
            "tp": s.take_profit, "estado": p.status,
            "ejecutada": f"{p.fill_price:,.2f}" if p.fill_price else "-",
            "salida": f"{p.exit_price:,.2f}" if p.exit_price else
                      (f"(mark {p.mark_price:,.2f})" if p.mark_price else "-"),
            "pnl_usd": round(z.get("pnl", 0.0), 3), "R": round(z.get("r", 0.0), 2),
            "comisiones": round(z.get("fees", 0.0), 3),
        })
    return pd.DataFrame(rows)


def main() -> None:
    df = evaluate()
    done = df[df.estado.isin(["tp", "stop", "gap_stop", "manual"])]
    open_ = df[df.estado == "abierta"]
    realized = done.pnl_usd.sum()
    wins, losses = done[done.pnl_usd > 0], done[done.pnl_usd <= 0]
    pf = wins.pnl_usd.sum() / -losses.pnl_usd.sum() if len(losses) and losses.pnl_usd.sum() else float("nan")
    lines = [
        "# Experimento de señales en paper — reporte",
        "",
        f"Generado: {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC · capital simulado "
        f"{CAPITAL:.0f} USD · riesgo {RISK_PCT}% por operación · sin apalancamiento",
        "",
        df.to_markdown(index=False),
        "",
        f"- Operaciones cerradas: {len(done)} (ganadoras {len(wins)}, perdedoras {len(losses)})",
        f"- P&L realizado: {realized:+.2f} USD ({realized / CAPITAL * 100:+.2f}%)",
        f"- P&L abierto (no realizado): {open_.pnl_usd.sum():+.2f} USD",
        f"- Profit factor: {pf:.2f}" if pf == pf else "- Profit factor: n/d",
        f"- Comisiones: {df.comisiones.sum():.2f} USD",
        f"- Equity estimado: {CAPITAL + realized + open_.pnl_usd.sum():.2f} USD",
        "",
        "Muestra pequeña: con pocas operaciones el resultado NO distingue habilidad de suerte.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
