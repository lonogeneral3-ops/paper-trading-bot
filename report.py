#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rapport du bot de paper trading : capital, P&L, positions, trades, vs buy-and-hold,
et graphique /workspace/paper-bot/equity.png.

Usage :  python report.py
Les prix sont rafraîchis (dernière bougie 1h close) pour valoriser le portefeuille,
sans passer de nouvel ordre.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.dates import DateFormatter  # noqa: E402
from datetime import datetime  # noqa: E402

from common import (  # noqa: E402
    ALLOCATION,
    EQUITY_PNG,
    INITIAL_CAPITAL,
    STATE_PATH,
    UNIVERSE,
    fetch_all_closed_klines,
    fmt_paris,
    last_closes,
    load_state,
    portfolio_snapshot,
)
from dashboard_html import DASHBOARD_HTML, generate_dashboard  # noqa: E402


def money(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "n/d"
    fmt = "{:+,.2f} $" if signed else "{:,.2f} $"
    return fmt.format(value).replace(",", " ")


def pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return "n/d"
    return f"{value:+.2f} %" if signed else f"{value:.2f} %"


def print_report(state: dict, snap: dict) -> None:
    print("=" * 72)
    print("  PAPER BOT — rapport (argent 100 % fictif, aucun ordre réel)")
    print("=" * 72)
    print(f"Horodatage du rapport     : {fmt_paris()} (Europe/Paris)")
    print(f"Démarrage du bot          : {state.get('started_at') or 'pas encore lancé'}")
    print(f"Fin prévue (7 jours)      : {state.get('ends_at') or '—'}")
    print(f"Dernière bougie traitée   : {state.get('last_processed_candle_close_paris') or '—'}")
    print(f"Dernier passage           : {state.get('last_run_at') or '—'}")
    print()
    print(f"Source des prix           : {state.get('data_source')}")
    if state.get("data_source_note"):
        print(f"  note                    : {state['data_source_note']}")
    print(f"Stratégie                 : {state.get('strategy')}")
    print(f"  {state.get('strategy_doc')}")
    print()
    print("-" * 72)
    print("CAPITAL")
    print("-" * 72)
    print(f"Capital de départ         : {money(INITIAL_CAPITAL)}")
    print(f"Capital actuel (equity)   : {money(snap['equity'])}")
    print(f"P&L                       : {money(snap['pnl'], signed=True)}  ({pct(snap['pnl_pct'])})")
    print(f"  dont cash               : {money(snap['cash_total'])}")
    print(f"  dont positions          : {money(snap['positions_value'])}")
    print(f"  P&L réalisé             : {money(snap['realized_pnl'], signed=True)}")
    print(f"  P&L latent              : {money(snap['unrealized_pnl'], signed=True)}")
    print()
    bh = snap.get("buy_and_hold_equity")
    bh_pnl = snap.get("buy_and_hold_pnl")
    print("-" * 72)
    print("COMPARAISON BUY & HOLD (même panier, acheté au premier run, conservé)")
    print("-" * 72)
    if bh is None:
        print("Pas encore de référence buy-and-hold (le bot n'a pas fait son premier run).")
    else:
        print(f"Valeur buy-and-hold       : {money(bh)}")
        print(f"P&L buy-and-hold          : {money(bh_pnl, signed=True)}  ({pct((bh_pnl / INITIAL_CAPITAL) * 100)})")
        diff = snap["equity"] - bh
        print(f"Bot vs buy-and-hold       : {money(diff, signed=True)}")
        if state.get("buy_and_hold", {}).get("entry_time"):
            print(f"Achat du panier B&H       : {state['buy_and_hold']['entry_time']}")
    print()
    print("-" * 72)
    print("POSITIONS PAR CRYPTO  (enveloppe de 1 000 $ fictifs chacune)")
    print("-" * 72)
    header = (
        f"{'Symbole':<10} {'Statut':<12} {'Prix':>12} {'Qté':>16} "
        f"{'Valeur':>12} {'P&L $':>12} {'P&L %':>9}"
    )
    print(header)
    print("-" * len(header))
    for symbol in UNIVERSE:
        a = snap["per_asset"][symbol]
        status = "EN POSITION" if a["in_position"] else "CASH"
        price = f"{a['price']:.6f}" if a["price"] is not None else "n/d"
        qty = f"{a['qty']:.8f}" if a["in_position"] else "—"
        print(
            f"{symbol:<10} {status:<12} {price:>12} {qty:>16} "
            f"{money(a['equity']):>12} {money(a['pnl'], signed=True):>12} {pct(a['pnl_pct']):>9}"
        )
        if a["in_position"] and a.get("entry_price") is not None:
            print(
                f"{'':10}   entrée {a['entry_price']:.6f}  le {a.get('entry_time') or '—'}  "
                f"latent {money(a['unrealized_pnl'], signed=True)}"
            )
    print()
    trades = state.get("trades") or []
    print("-" * 72)
    print(f"TRADES  (total : {len(trades)})")
    print("-" * 72)
    if not trades:
        print("Aucun trade pour l'instant.")
    else:
        last = trades[-15:]
        if len(trades) > 15:
            print(f"(affichage des 15 derniers sur {len(trades)})")
        print(
            f"{'Id':>4}  {'Date (Europe/Paris)':<25} {'Côté':<5} {'Symbole':<9} "
            f"{'Prix':>12} {'Qté':>16}"
        )
        for t in last:
            print(
                f"{t['id']:>4}  {str(t['time']):<25} {t['side']:<5} {t['symbol']:<9} "
                f"{t['price']:>12.6f} {t['qty']:>16.8f}"
            )
            print(f"      {t['reason']}")
    print()
    print(f"Fichiers : {STATE_PATH}")
    print(f"           {EQUITY_PNG}")
    print("=" * 72)


def make_chart(state: dict) -> Path:
    history = state.get("equity_history") or []
    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=120)

    def parse_times(rows):
        xs, eq, bh = [], [], []
        for row in rows:
            try:
                dt = datetime.fromisoformat(row["time"])
            except (TypeError, ValueError):
                continue
            xs.append(dt)
            eq.append(float(row["equity"]))
            bh_val = row.get("buy_and_hold_equity")
            bh.append(float(bh_val) if bh_val is not None else None)
        return xs, eq, bh

    xs, eq, bh = parse_times(history)
    ax.axhline(
        INITIAL_CAPITAL,
        color="#888888",
        linestyle="--",
        linewidth=1,
        label=f"Capital de départ ({INITIAL_CAPITAL:,.0f} $)".replace(",", " "),
    )
    if xs:
        ax.plot(xs, eq, color="#1f6feb", linewidth=2, marker="o", markersize=4, label="Bot (stratégie EMA 20/50)")
        if any(v is not None for v in bh):
            ax.plot(
                xs,
                bh,
                color="#bc4c00",
                linewidth=2,
                linestyle="--",
                marker="s",
                markersize=3.5,
                label="Buy & hold du même panier",
            )
        ax.xaxis.set_major_formatter(DateFormatter("%d/%m %Hh", tz=xs[0].tzinfo))
        fig.autofmt_xdate()
    else:
        ax.text(
            0.5,
            0.5,
            "Pas encore d'historique\n(lancer le bot une première fois)",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )

    ax.set_title("Paper trading — évolution du capital fictif (Europe/Paris)")
    ax.set_ylabel("Capital ($ fictifs)")
    ax.set_xlabel("Date (Europe/Paris)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    EQUITY_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(EQUITY_PNG)
    plt.close(fig)
    return EQUITY_PNG


def main() -> int:
    if not STATE_PATH.exists():
        print("Aucun état trouvé. Lance d'abord :  python bot.py --once")
        print(f"Chemin attendu : {STATE_PATH}")
        return 1

    state = load_state()
    try:
        klines = fetch_all_closed_klines()
        prices = last_closes(klines)
    except Exception as exc:  # noqa: BLE001
        print(f"Impossible de rafraîchir les prix ({exc}). Utilisation des derniers prix enregistrés.")
        prices = state.get("last_prices") or {}

    snap = portfolio_snapshot(state, prices)
    print_report(state, snap)
    path = make_chart(state)
    print(f"Graphique enregistré : {path}")
    dash = generate_dashboard(state, snap)
    print(f"Tableau de bord      : {dash}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
