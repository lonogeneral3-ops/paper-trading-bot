#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Change la stratégie du bot (argent fictif) sans toucher au code.

Lancé par le workflow GitHub « Changer de stratégie », ou à la main :
  python change_strategy.py --strategie rsi --actif tous --parametres "periode=14 bas=30 haut=70"
  python change_strategy.py --strategie ema --actif BTCUSDT            # seulement pour le Bitcoin
  python change_strategy.py --strategie global --actif BTCUSDT         # BTC revient à la stratégie globale

Rien n'est effacé : les positions sont gardées, l'historique est conservé, et le
changement est noté dans data/state.json (strategy_changes). Les nouvelles règles
s'appliquent aux bougies qui se terminent après le changement.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import strategies as S  # noqa: E402
from bot import CONFIG_PATH, PARIS, STATE_PATH, config_strategies, load_json, migrate, norm, sync_strategy_log, write_json  # noqa: E402


def parse_params(txt: str) -> dict:
    out = {}
    for part in re.split(r"[\s,;]+", (txt or "").strip()):
        if not part:
            continue
        if "=" not in part:
            raise SystemExit(f"Paramètre mal écrit : « {part} » (format attendu : nom=valeur)")
        k, v = part.split("=", 1)
        out[k.strip().lower()] = float(v.replace(",", ".")) if "." in v or "," in v else int(v)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategie", required=True, help="ema, rsi, boll, macd, dca, bh (ou 'global' pour un actif)")
    ap.add_argument("--actif", default="tous")
    ap.add_argument("--parametres", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cfg = load_json(CONFIG_PATH)
    keys = {x["key"]: x for x in cfg["assets"]}
    labels = {x["label"].lower(): x["key"] for x in cfg["assets"]}
    actif = a.actif.strip()
    if actif.lower() != "tous":
        actif = keys.get(actif, {}).get("key") or labels.get(actif.lower()) or keys.get(actif.upper(), {}).get("key")
        if not actif:
            raise SystemExit(f"Actif inconnu : {a.actif}. Choix possibles : tous, " + ", ".join(keys))
    sid = a.strategie.strip().lower()
    if sid == "global":
        if actif == "tous":
            raise SystemExit("« global » ne s'utilise qu'avec un actif précis.")
        new = None
    else:
        if sid not in S.STRATEGIES:
            raise SystemExit(f"Stratégie inconnue : {sid}. Choix : " + ", ".join(S.STRATEGIES))
        params = parse_params(a.parametres)
        unknown = set(params) - set(S.STRATEGIES[sid]["params"])
        if unknown:
            raise SystemExit(f"Paramètre(s) inconnu(s) pour {sid} : {', '.join(unknown)}. "
                             f"Possibles : {', '.join(S.STRATEGIES[sid]['params']) or 'aucun'}")
        errs = S.validate(sid, params)
        if errs:
            raise SystemExit(" ; ".join(errs))
        new = norm({"id": sid, "params": params})

    state = migrate(load_json(STATE_PATH), cfg)
    sync_strategy_log(state, cfg)          # rattrape d'éventuelles modifications manuelles
    cur = config_strategies(cfg)
    old = cur["global"] if actif == "tous" else cur["overrides"].get(actif)
    if old == new and not (actif == "tous" and cur["overrides"]):
        print(f"Rien à changer : {'tous les actifs' if actif == 'tous' else actif} suit déjà cette stratégie.")
        return 0
    if actif == "tous":
        cfg["strategy"] = new
        for x in cfg["assets"]:
            x["strategy"] = None          # « tous » remet chaque actif sur la stratégie globale
    else:
        keys[actif]["strategy"] = new
    now = datetime.now(PARIS).isoformat(timespec="seconds")
    entry = {"time": now, "scope": actif, "old": old, "new": new, "by": "workflow Changer de stratégie"}
    lbl = (lambda s: S.label(s["id"], s["params"]) if s else "stratégie globale")
    print(f"{'[ESSAI] ' if a.dry_run else ''}{'Tous les actifs' if actif == 'tous' else actif} : "
          f"{lbl(old)}  →  {lbl(new)}  (à partir de la prochaine bougie, positions gardées)")
    if a.dry_run:
        print("Essai seulement : rien n'est enregistré.")
        return 0
    state["strategy_changes"].append(entry)
    write_json(CONFIG_PATH, cfg)
    state["strategy_current"] = config_strategies(cfg)
    state["strategy"] = S.label(state["strategy_current"]["global"]["id"], state["strategy_current"]["global"]["params"]) + " · bougies 1h"
    write_json(STATE_PATH, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
