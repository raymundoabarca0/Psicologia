"""Evalúa las señales registradas en signals.csv contra los precios reales (velas 1m).

Reglas (conservadoras, iguales para todas las señales):
- Solo cuentan velas que empiezan DESPUÉS de registrar la señal.
- market: entra a la apertura de la primera vela 1m posterior (+ slippage).
- limit: entra si el precio toca el nivel antes de `expires_utc`; si no, "expirada".
- En la vela de entrada solo se comprueba el stop (si también se tocó el stop,
  se asume que saltó). El take-profit cuenta desde la vela siguiente.
- Si en una vela se tocan stop y take-profit, cuenta el STOP.
- Gap más allá del stop: sale a la apertura.
- manual_close_utc: cierre a mercado decidido después (nunca con fecha pasada).
- gestion = "parcial" (incluye "proteger"): al tocar +1R se cierra la MITAD de la
  posición en +1R (orden límite) y el stop del resto pasa a la entrada; al ganar
  +1,5R el stop del resto pasa a +0,5R. La otra mitad busca el take-profit.
- prob: probabilidad estimada (0-1) de que la operación termine en ganancia. El
  reporte compara las probabilidades con los resultados (calibración, Brier).
- gestion = "proteger" (regla escrita en la señal ANTES de entrar): al ganar +1R
  el stop pasa a la entrada (+ spread); al ganar +1,5R pasa a +0,5R. Se calcula
  con el máximo/mínimo de cada vela cerrada y se aplica desde la vela siguiente.
- Costos tipo broker de CFD (MetaTrader): spread típico por activo, sin comisión.
  Cada lado paga medio spread; las salidas por stop y las órdenes a mercado
  pagan además medio spread de deslizamiento. Los take-profit (límite) no.
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
# Spread típico en precio (XAUUSD ~0,30 USD, EURUSD ~1,2 pips, BTCUSD ~25 USD).
SPREAD = {"PAXGUSDT": 0.30, "EURUSDT": 0.00012, "BTCUSDT": 25.0,
          "XAU/USD": 0.30, "EUR/USD": 0.00012}
CASH_BUFFER = 0.02
BAR = "1m"   # granularidad de la simulación (señales de 15m necesitan velas finas)


@dataclass
class Path_:
    status: str                    # pendiente | expirada | abierta | tp | stop | gap_stop | manual
    fill_time: pd.Timestamp | None = None
    fill_price: float | None = None
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    mark_price: float | None = None
    partial_price: float | None = None   # mitad cerrada en +1R (gestion = parcial)


def _simulate(sig: pd.Series, bars: pd.DataFrame) -> Path_:
    long = sig.direction == "long"
    sgn = 1 if long else -1
    created = pd.Timestamp(sig.created_utc)
    expires = pd.Timestamp(sig.expires_utc)
    manual = pd.Timestamp(sig.manual_close_utc) if pd.notna(sig.manual_close_utc) else None
    bars = bars[bars.index >= created.ceil(BAR.replace("m", "min"))]
    if bars.empty:
        return Path_("pendiente")

    stop, tp, entry = float(sig.stop), float(sig.take_profit), float(sig.entry)
    half = SPREAD[sig.symbol] / 2
    one_r = abs(entry - stop)
    gestion = str(sig.get("gestion", "") or "").strip()
    protect = gestion in ("proteger", "parcial")
    partial = gestion == "parcial"
    moved = False
    p = None
    for t, b in bars.iterrows():
        if p is None:  # sin entrar todavía
            if manual is not None and t >= manual:
                return Path_("cancelada")
            if sig.entry_type == "market":
                fill = b.open + sgn * 2 * half
            else:
                if t >= expires:
                    return Path_("expirada")
                touched = b.low <= entry if long else b.high >= entry
                if not touched:
                    continue
                fill = (min(b.open, entry) if long else max(b.open, entry)) + sgn * half
            p = Path_("abierta", t, fill)
            # En la vela de entrada solo el stop (peor caso).
            if (b.low <= stop) if long else (b.high >= stop):
                p.status, p.exit_time, p.exit_price = "stop", t, stop - sgn * 2 * half
                return p
            continue

        if manual is not None and t >= manual:
            p.status, p.exit_time, p.exit_price = "manual", t, b.open - sgn * 2 * half
            return p
        gap = b.open <= stop if long else b.open >= stop
        hit_stop = b.low <= stop if long else b.high >= stop
        hit_tp = b.high >= tp if long else b.low <= tp
        if gap:
            p.status, p.exit_time, p.exit_price = "gap_stop", t, b.open - sgn * 2 * half
            return p
        if hit_stop:
            status = "stop_protegido" if moved else "stop"
            p.status, p.exit_time, p.exit_price = status, t, stop - sgn * 2 * half
            return p
        if hit_tp:
            p.status, p.exit_time, p.exit_price = "tp", t, tp - sgn * half
            return p
        if partial and p.partial_price is None:
            lvl = entry + sgn * one_r
            if (b.high >= lvl) if long else (b.low <= lvl):
                p.partial_price = lvl - sgn * half
        if protect:
            best = (b.high - entry) if long else (entry - b.low)
            new = None
            if best >= 1.5 * one_r:
                new = entry + sgn * 0.5 * one_r
            elif best >= one_r:
                new = entry + sgn * 2 * half
            if new is not None and ((new > stop) if long else (new < stop)):
                stop, moved = new, True
    if p is not None:
        p.mark_price = float(bars.close.iloc[-1])
    return p or Path_("pendiente")


def evaluate() -> pd.DataFrame:
    sigs = pd.read_csv(SIGNALS)
    if "manual_close_utc" not in sigs:
        sigs["manual_close_utc"] = pd.NA
    # Velas desde la primera señal de cada símbolo (Twelve Data limita las peticiones).
    starts = sigs.groupby("symbol").created_utc.min()
    bars = {s: klines(s, BAR, start=pd.Timestamp(t).floor("h")) for s, t in starts.items()}
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
        per_unit = abs(p.fill_price - s.stop) + SPREAD[s.symbol]   # peor caso
        qty = eq * RISK_PCT / 100 / per_unit
        cap = max(0.0, eq * (1 - CASH_BUFFER) - used) / p.fill_price
        qty = min(qty, cap)
        sgn = 1 if s.direction == "long" else -1
        # Costo implícito (spread pagado), ya incluido en los precios de ejecución.
        fees = qty * SPREAD[s.symbol] / 2 * (2 if p.exit_price is not None else 1)
        last = p.exit_price if p.exit_price is not None else p.mark_price
        if p.partial_price is not None:
            pnl = sgn * qty / 2 * (p.partial_price - p.fill_price) + \
                  sgn * qty / 2 * (last - p.fill_price)
        else:
            pnl = sgn * qty * (last - p.fill_price)
        if p.exit_price is not None:
            closed.append((p.exit_time, pnl))
        else:
            pnl -= fees  # no realizado: falta pagar la salida
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
            "parcial": f"{p.partial_price:,.2f}" if p.partial_price else "-",
            "prob": getattr(s, "prob", float("nan")),
            "pnl_usd": round(z.get("pnl", 0.0), 3), "R": round(z.get("r", 0.0), 2),
            "costo_spread": round(z.get("fees", 0.0), 3),
        })
    return pd.DataFrame(rows)


def _calibration(done: pd.DataFrame) -> str:
    """Compara la probabilidad estimada con el resultado (ganó = P&L > 0)."""
    d = done[pd.to_numeric(done.prob, errors="coerce").notna()]
    if d.empty:
        return "- Calibración: aún no hay operaciones cerradas con probabilidad estimada"
    prob = pd.to_numeric(d.prob)
    won = (d.pnl_usd > 0).astype(float)
    brier = ((prob - won) ** 2).mean()
    return (f"- Calibración ({len(d)} ops): probabilidad media estimada {prob.mean():.0%} "
            f"vs acierto real {won.mean():.0%} · Brier {brier:.3f} "
            "(0 = perfecto; 0,25 = como tirar una moneda)")


def main() -> None:
    df = evaluate()
    done = df[df.estado.isin(["tp", "stop", "stop_protegido", "gap_stop", "manual"])]
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
        f"- Costo de spread (ya incluido en el P&L): {df.costo_spread.sum():.2f} USD",
        f"- Equity estimado: {CAPITAL + realized + open_.pnl_usd.sum():.2f} USD",
        _calibration(done),
        "",
        "Muestra pequeña: con pocas operaciones el resultado NO distingue habilidad de suerte.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
