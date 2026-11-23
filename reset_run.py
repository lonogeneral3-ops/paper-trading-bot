#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recommence l'expérience à zéro (argent fictif) en archivant l'ancienne.

  python reset_run.py --archive run-2026-11-23

- copie data/state.json, trades.csv, equity.csv, equity.png et config.json dans data/archive/<nom>/ ;
- crée un nouvel état : début = maintenant (heure de Paris), fin = début + 7 jours,
  tout en cash (1 000 € fictifs par actif), aucun trade, stratégie de config.json.
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timedelta

from bot import CONFIG_PATH, DATA, PARIS, ROOT, STATE_PATH, config_strategies, load_json, migrate, write_json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True)
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    dest = DATA / "archive" / a.archive
    if dest.exists():
        raise SystemExit(f"{dest} existe déjà")
    dest.mkdir(parents=True)
    for p in (STATE_PATH, DATA / "trades.csv", DATA / "equity.csv", ROOT / "equity.png", CONFIG_PATH):
        if p.exists():
            shutil.copy2(p, dest / p.name)
    old = load_json(STATE_PATH)
    cfg = load_json(CONFIG_PATH)
    now = datetime.now(PARIS).replace(microsecond=0)
    state = {
        "version": 3,
        "currency": "EUR",
        "started_at": now.isoformat(),
        "ends_at": (now + timedelta(days=a.days)).isoformat(),
        "assets": {}, "trades": [], "equity_history": [], "buy_and_hold": {"positions": {}},
        "strategy_changes": [],
        "strategy_current": config_strategies(cfg),
        "reset_note": {
            "time": now.isoformat(),
            "text": ("Expérience recommencée à zéro : 1 000 € fictifs par actif, tout en cash au départ, "
                     "achats seulement sur un nouveau signal de la stratégie. "
                     f"L'ancienne expérience (du {old.get('started_at')} au {old.get('last_run_at')}) est archivée "
                     f"dans data/archive/{a.archive}/."),
            "archive": f"data/archive/{a.archive}/",
            "previous_started_at": old.get("started_at"),
        },
    }
    state = migrate(state, cfg)
    write_json(STATE_PATH, state)
    print(f"Nouvelle expérience : {state['started_at']} → {state['ends_at']} ; archive : {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
