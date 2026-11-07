"""Gráficos de las señales: qué espero que haga el mercado, por qué, y si se cumplió.

Cada imagen muestra velas de 4h, la entrada, el stop y el take-profit, el
escenario esperado (línea discontinua) y, a medida que pasan los días, las velas
reales posteriores a la señal con su estado (pendiente, ejecutada, TP o stop).

Uso:  python -m paper_signals.charts          -> genera paper_signals/charts/*.png
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from bot.strategy import indicators as ind  # noqa: E402
from paper_signals.analyze import fp  # noqa: E402
from paper_signals.evaluate import SIGNALS, evaluate  # noqa: E402
from paper_signals.market import klines  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "charts"
WATCH = HERE / "watch.json"

# Paleta (superficie clara). Velas: azul = sube, naranja = baja (no rojo/verde,
# que quedan reservados para stop/take-profit, siempre con etiqueta de texto).
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e6e5e1"
UP = "#2a78d6"
DOWN = "#eb6834"
STOP = "#d03b3b"
TP = "#0ca30c"
PATH = "#6250d6"
EMA_C = "#9a9893"
STATUS_TXT = {
    "pendiente": "PENDIENTE: el precio aún no llegó a la entrada",
    "expirada": "CADUCADA: el precio no llegó a la entrada (no se operó)",
    "cancelada": "CANCELADA antes de ejecutarse",
    "abierta": "EJECUTADA: posición abierta",
    "tp": "SE CUMPLIÓ: take-profit alcanzado",
    "stop": "NO SE CUMPLIÓ: saltó el stop-loss",
    "stop_protegido": "CERRADA con el stop protegido (ganancia asegurada o en cero)",
    "gap_stop": "NO SE CUMPLIÓ: el precio saltó el stop (gap)",
    "manual": "CERRADA manualmente",
    "vigilancia": "SIN SEÑAL: solo niveles en vigilancia",
}


def _candles(ax, df: pd.DataFrame, alpha: float = 1.0) -> None:
    w = (df.index[1] - df.index[0]) * 0.62 if len(df) > 1 else pd.Timedelta(hours=2.5)
    for t, r in df.iterrows():
        c = UP if r.close >= r.open else DOWN
        ax.vlines(t, r.low, r.high, color=c, linewidth=1, alpha=alpha, zorder=2)
        lo, hi = sorted((r.open, r.close))
        ax.bar(t, max(hi - lo, (r.high - r.low) * 0.02 or 1e-9), bottom=lo, width=w,
               color=c, alpha=alpha, edgecolor=SURFACE, linewidth=0.6, zorder=3)


def _level(ax, y, label, color, x_end, style="-") -> None:
    ax.axhline(y, color=color, linewidth=1.6, linestyle=style, zorder=4)
    ax.annotate(f" {label}  {fp(y)}", xy=(x_end, y), xytext=(4, 0), textcoords="offset points",
                va="center", ha="left", fontsize=9, color=INK, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.2", fc=SURFACE, ec=color, lw=1.2),
                annotation_clip=False, zorder=6)


def render(*, asset: str, symbol: str, title: str, created: pd.Timestamp, tf: str = "4h",
           levels: list[tuple[float, str, str, str]], path: list[tuple[pd.Timestamp, float]],
           why: str, expect: str, status: str, detail: str, out: Path) -> Path:
    bars = klines(symbol, tf, limit=500)
    ema200 = ind.ema(bars["close"], 200)
    before = bars[bars.index < created].iloc[-60:]
    after = bars[bars.index >= created.floor(tf.replace("m", "min"))]
    x_end = max(path[-1][0], after.index[-1] if len(after) else created) + pd.Timedelta(hours=8)

    fig, ax = plt.subplots(figsize=(11, 6.8), dpi=110)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.axvspan(created, x_end, color="#f0efec", zorder=0)
    _candles(ax, before)
    if len(after):
        _candles(ax, after)
    e = ema200[ema200.index >= before.index[0]]
    ax.plot(e.index, e.values, color=EMA_C, linewidth=1.3, zorder=2)
    ax.annotate(f" EMA200 ({tf})", xy=(e.index[-1], e.iloc[-1]), fontsize=8, color=INK_2,
                va="bottom")

    for y, label, kind, style in levels:
        color = {"stop": STOP, "tp": TP, "entry": INK, "watch": INK_2}[kind]
        _level(ax, y, label, color, x_end, style)

    px, py = zip(*path)
    ax.plot(px, py, color=PATH, linewidth=2.2, linestyle=(0, (5, 3)), zorder=5)
    ax.annotate("", xy=(px[-1], py[-1]), xytext=(px[-2], py[-2]),
                arrowprops=dict(arrowstyle="-|>", color=PATH, lw=2.2), zorder=5)
    ax.annotate("Escenario esperado", xy=(px[-1], py[-1]), xytext=(-14, 0),
                textcoords="offset points", fontsize=9, color=INK, fontweight="bold",
                ha="right", va="center",
                bbox=dict(boxstyle="round,pad=0.2", fc=SURFACE, ec="none"), zorder=7)
    ax.axvline(created, color=INK_2, linewidth=1, linestyle=":")
    ax.annotate(f"Señal {created:%d-%b %H:%M} UTC", xy=(created, 1), xycoords=("data", "axes fraction"),
                xytext=(4, -14), textcoords="offset points", fontsize=8, color=INK_2)

    ys = [*before.low, *before.high, *py, *(lv[0] for lv in levels), *after.low, *after.high]
    pad = (max(ys) - min(ys)) * 0.06
    ax.set_ylim(min(ys) - pad, max(ys) + pad)
    ax.set_xlim(before.index[0], x_end)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(colors=INK_2, labelsize=8)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%b" if tf in ("4h", "1d") else "%d-%b %H:%M"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fp(v)))

    fig.suptitle(title, x=0.06, y=0.975, ha="left", fontsize=14, fontweight="bold", color=INK)
    status_color = {"tp": TP, "stop": STOP, "gap_stop": STOP}.get(status, INK_2)
    fig.text(0.06, 0.915, STATUS_TXT[status] + (f" · {detail}" if detail else ""),
             fontsize=10.5, fontweight="bold", color=INK,
             bbox=dict(boxstyle="round,pad=0.3", fc=SURFACE, ec=status_color, lw=1.5))
    notes = ("POR QUÉ: " + why + "\nQUÉ ESPERO: " + expect)
    wrapped = "\n".join(textwrap.fill(p, 150) for p in notes.split("\n"))
    fig.text(0.06, 0.02, wrapped, fontsize=8.5, color=INK, va="bottom", linespacing=1.4)
    fig.subplots_adjust(left=0.06, right=0.84, top=0.87, bottom=0.25)
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    return out


def _tf(sig) -> str:
    tf = getattr(sig, "timeframe", None)
    return tf if isinstance(tf, str) and tf else "4h"


def _expected_path(sig, ref: float, created: pd.Timestamp) -> list:
    h = pd.Timedelta(_tf(sig).replace("m", "min"))
    if sig.entry_type == "limit":
        return [(created, ref), (created + 3 * h, sig.entry), (created + 16 * h, sig.take_profit)]
    return [(created, ref), (created + 14 * h, sig.take_profit)]


def chart_signals() -> list[Path]:
    sigs = pd.read_csv(SIGNALS)
    ev = evaluate().set_index("id")
    outs = []
    for s in sigs.itertuples():
        created = pd.Timestamp(s.created_utc)
        ref_bars = klines(s.symbol, "1h", limit=1000, start=created.floor("h") - pd.Timedelta(hours=1))
        ref = float(ref_bars.close.iloc[0])
        e = ev.loc[s.id]
        detail = ""
        if e.estado in ("tp", "stop", "stop_protegido", "gap_stop", "manual", "abierta"):
            detail = f"P&L {e.pnl_usd:+.2f} USD ({e.R:+.2f}R)"
            if e.estado == "abierta":
                detail += " no realizado"
        dirtxt = "Venta" if s.direction == "short" else "Compra"
        kind = "limitada" if s.entry_type == "limit" else "a mercado"
        levels = [(s.entry, "Entrada", "entry", "--"), (s.stop, "Stop-loss", "stop", "-"),
                  (s.take_profit, "Take-profit", "tp", "-")]
        if str(getattr(s, "gestion", "") or "") == "parcial":
            one_r = abs(s.entry - s.stop) * (1 if s.direction == "long" else -1)
            levels.append((s.entry + one_r, "Cierre 50% (+1R)", "tp", ":"))
        prob = getattr(s, "prob", None)
        if isinstance(prob, float) and prob == prob:
            detail = (detail + " · " if detail else "") + f"probabilidad estimada {prob:.0%}"
        expect = getattr(s, "expectativa", "") or ""
        outs.append(render(
            asset=s.asset, symbol=s.symbol, created=created, tf=_tf(s),
            title=f"#{s.id} {s.asset} ({s.symbol}) {_tf(s)} · {dirtxt} {kind} en {fp(s.entry)}",
            levels=levels, path=_expected_path(s, ref, created), why=s.rationale,
            expect=expect if isinstance(expect, str) else "", status=e.estado, detail=detail,
            out=OUT / f"senal_{s.id}_{s.asset}.png"))
    return outs


def chart_watch() -> list[Path]:
    if not WATCH.exists():
        return []
    outs = []
    for w in json.loads(WATCH.read_text(encoding="utf-8")):
        created = pd.Timestamp(w["created_utc"])
        h = pd.Timedelta(hours=4)
        path = [(created + i * h, p) for i, p in w["path"]]
        levels = [(lv["price"], lv["label"], "watch", "--") for lv in w["levels"]]
        outs.append(render(
            asset=w["asset"], symbol=w["symbol"], created=created,
            title=f"{w['asset']} ({w['symbol']}) 4h · Sin señal hoy, en vigilancia",
            levels=levels, path=path, why=w["why"], expect=w["expect"],
            status="vigilancia", detail="", out=OUT / f"vigilancia_{w['asset']}_{created:%Y%m%d_%H%M}.png"))
    return outs


def main() -> None:
    for p in chart_signals() + chart_watch():
        print(p)


if __name__ == "__main__":
    main()
