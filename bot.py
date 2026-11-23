#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot de paper trading — argent 100 % fictif, aucun compte, aucun ordre réel.

Toutes les heures, juste après la clôture d'une bougie 1h, le bot :
  1. récupère les prix publics (Binance.US, sans authentification) ;
  2. calcule les EMA 20 et 50 de chaque crypto ;
  3. achète si la tendance est haussière (EMA20 > EMA50) et qu'il n'est pas investi ;
  4. vend si la tendance redevient baissière (EMA20 < EMA50) ;
  5. enregistre l'état sur disque (reprise possible après un redémarrage).

Usage :
  python bot.py          # boucle pendant 7 jours
  python bot.py --once   # traite toutes les bougies 1h closes pas encore vues, puis s'arrête
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
import traceback
from pathlib import Path

# S'assurer que le dossier du projet est importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BOT_PID,
    LAST_FETCH_META,
    LOG_DIR,
    already_processed,
    decide_and_trade,
    ends_at_dt,
    ensure_dirs,
    fetch_all_closed_klines,
    fmt_paris,
    last_closed_open_ms,
    last_closes,
    load_state,
    ms_to_paris,
    now_paris,
    pending_candle_open_times,
    portfolio_snapshot,
    run_ended,
    save_state,
    seconds_until_next_close,
    slice_klines_through,
    stop_requested,
    STOP_FLAG,
)
from dashboard_html import generate_dashboard  # noqa: E402

_shutdown = False


def log(message: str) -> None:
    line = f"{fmt_paris()}  {message}"
    print(line, flush=True)
    ensure_dirs()
    with (LOG_DIR / "bot.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _handle_signal(signum, _frame) -> None:
    global _shutdown
    _shutdown = True
    log(f"Signal {signum} reçu, arrêt propre après cette étape.")


def write_pid() -> None:
    BOT_PID.write_text(str(os.getpid()), encoding="utf-8")


def _refresh_outputs(state: dict, klines: dict) -> None:
    """Régénère le tableau de bord (et le PNG s'il est disponible)."""
    prices = last_closes(klines) if klines else (state.get("last_prices") or {})
    snap = portfolio_snapshot(state, prices)
    try:
        path = generate_dashboard(state, snap)
        log(f"Tableau de bord mis à jour : {path}")
    except Exception:
        log("Erreur lors de la génération du tableau de bord :\n" + traceback.format_exc())
    try:
        from report import make_chart

        png = make_chart(state)
        log(f"Graphique enregistré : {png}")
    except Exception:
        log("Erreur lors de la génération du graphique :\n" + traceback.format_exc())


def one_pass(state: dict) -> dict:
    """Un cycle : rattrape toutes les bougies 1h closes non traitées, puis sauvegarde.

    Idempotent : une bougie déjà enregistrée n'est jamais rejouée.
    Après la date de fin (7 jours), aucune nouvelle bougie n'est tradée.
    """
    klines = fetch_all_closed_klines()
    meta = LAST_FETCH_META
    state["data_source"] = meta.get("label") or state.get("data_source")
    state["data_source_note"] = meta.get("note") or state.get("data_source_note")
    log(f"Source des prix : {state['data_source']}")

    ends = ends_at_dt(state)
    pending = pending_candle_open_times(
        klines, state.get("last_processed_candle_open_ms"), ends
    )

    if not pending:
        latest_ms = last_closed_open_ms(klines)
        close_label = (
            fmt_paris(ms_to_paris(klines[next(iter(klines))][-1]["close_time_ms"]))
            if klines
            else "?"
        )
        if ends is not None and now_paris() >= ends:
            log(
                f"Période de 7 jours terminée ({state.get('ends_at')}) — aucun nouveau trade."
            )
        elif already_processed(state, klines) or (
            latest_ms is not None
            and state.get("last_processed_candle_open_ms") == latest_ms
        ):
            log(f"Bougie {close_label} déjà traitée — rien à faire (reprise idempotente).")
        else:
            log(
                "Aucune bougie à traiter dans la fenêtre (peut-être déjà après la date de fin)."
            )
        _refresh_outputs(state, klines)
        return state

    all_new_trades: list[dict] = []
    for open_ms in pending:
        sliced = slice_klines_through(klines, open_ms)
        close_label = fmt_paris(ms_to_paris(sliced[next(iter(sliced))][-1]["close_time_ms"]))
        trades = decide_and_trade(state, sliced)
        save_state(state)
        all_new_trades.extend(trades)
        if trades:
            for trade in trades:
                log(
                    f"{trade['side']:4s} {trade['symbol']:8s}  qty={trade['qty']:.8f}  "
                    f"prix={trade['price']:.6f}  — {trade['reason']}  "
                    f"(bougie {close_label})"
                )
        else:
            log(f"Aucun ordre sur la bougie close {close_label} (open_ms={open_ms}).")

    prices = last_closes(slice_klines_through(klines, pending[-1]))
    snap = portfolio_snapshot(state, prices)
    log(
        f"Capital fictif : {snap['equity']:.2f} $  "
        f"(P&L {snap['pnl']:+.2f} $ / {snap['pnl_pct']:+.2f} %)  "
        f"| buy & hold : {snap['buy_and_hold_equity']:.2f} $  "
        f"| {len(pending)} bougie(s) traitée(s), {len(all_new_trades)} ordre(s)"
    )
    _refresh_outputs(state, slice_klines_through(klines, pending[-1]))
    return state


def sleep_interruptible(seconds: float) -> None:
    """Dort par tranches de 15 s pour voir un fichier STOP ou un signal."""
    deadline = time.time() + seconds
    while time.time() < deadline and not _shutdown and not stop_requested():
        time.sleep(min(15.0, deadline - time.time()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper trading bot (argent fictif)")
    parser.add_argument("--once", action="store_true", help="Un seul passage puis sortie")
    args = parser.parse_args()

    ensure_dirs()
    write_pid()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log("Démarrage du bot de paper trading (aucune clé API, aucun ordre réel).")
    state = load_state()

    if state.get("started_at") and run_ended(state):
        log(f"Les 7 jours sont écoulés (début {state['started_at']}, fin {state['ends_at']}). Arrêt.")
        return 0

    try:
        one_pass(state)
        # Recharger au cas où, et vérifier l'arrêt demandé pendant le fetch
        state = load_state()
    except Exception:
        log("Erreur pendant le passage :\n" + traceback.format_exc())
        if args.once:
            return 1
        sleep_interruptible(60)

    if args.once or _shutdown or stop_requested():
        log("Arrêt (--once, signal ou fichier STOP).")
        return 0

    while not _shutdown and not stop_requested():
        state = load_state()
        if run_ended(state):
            log(f"Fin des 7 jours (début {state['started_at']}, fin {state['ends_at']}). Arrêt propre.")
            return 0
        wait = seconds_until_next_close()
        log(f"Prochaine clôture de bougie dans {wait/60:.1f} min. En attente…")
        sleep_interruptible(wait)
        if _shutdown or stop_requested():
            break
        try:
            state = load_state()
            one_pass(state)
        except Exception:
            log("Erreur pendant le passage, nouvel essai dans 2 min :\n" + traceback.format_exc())
            sleep_interruptible(120)

    log("Arrêt du bot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
