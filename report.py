#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Résumé texte + graphique PNG (equity.png) du bot. Argent 100 % fictif."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GROUP_FR = {"crypto": "Cryptos", "action": "Actions", "indice": "Indices"}


def make_chart(state: dict) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter
    from zoneinfo import ZoneInfo
    hist = state.get("equity_history") or []
    xs = [datetime.fromisoformat(h["time"]) for h in hist]
    gain = [h["equity"] - h.get("capital", 10000) for h in hist]
    bh = [(h.get("buy_and_hold_equity") or h["equity"]) - h.get("capital", 10000) for h in hist]
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=110)
    ax.plot(xs, gain, label="Mon bot", color="#2563eb", lw=2)
    ax.plot(xs, bh, label="Acheter et garder", color="#6b7280", lw=1.5, ls="--")
    ax.axhline(0, color="#999", lw=0.8)
    ax.set_title("Gain fictif (€) — argent 100 % fictif")
    ax.xaxis.set_major_formatter(DateFormatter("%d/%m %Hh", tz=ZoneInfo("Europe/Paris")))
    ax.legend()
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    out = ROOT / "equity.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> int:
    s = json.loads((ROOT / "data" / "state.json").read_text(encoding="utf-8"))
    sm = s["summary"]
    print(f"Stratégie : {s.get('strategy')}")
    print(f"Dernier passage : {s.get('last_run_at')} (heure de Paris)")
    print(f"Capital fictif : {sm['equity']:.2f} € sur {sm['capital']:.0f} € (gain {sm['equity'] - sm['capital']:+.2f} €)")
    print(f"Acheter et garder : {sm['buy_and_hold_equity']:.2f} €")
    for g, v in sm["groups"].items():
        if v["capital"]:
            print(f"  {GROUP_FR.get(g, g)} : {v['equity']:.2f} € sur {v['capital']:.0f} € ({v['equity'] - v['capital']:+.2f} €)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
