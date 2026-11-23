#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot de paper trading — argent 100 % FICTIF, aucun compte, aucun ordre réel.

À chaque passage (toutes les heures sur GitHub Actions) :
  1. lit config.json (actifs + stratégie choisie) ;
  2. récupère les bougies 1h publiques (cryptos : Binance.US ; Bourse : Yahoo Finance) ;
  3. pour chaque bougie TERMINÉE pas encore traitée, applique la stratégie en vigueur
     à ce moment-là (voir strategies.py) au prix de clôture ;
  4. enregistre l'état (data/state.json + CSV).

Chaque actif a sa propre enveloppe fictive (1 000 € par défaut). Le rendement en % de chaque
actif (coté en $ ou en €) est appliqué à son enveloppe en euros, sans conversion de change.
Au départ tout est en cash : le bot n'achète que sur un NOUVEAU signal d'achat. Un actif ajouté dans
config.json reçoit une nouvelle enveloppe et commence à trader à la bougie suivante.
Changer de stratégie ne réinitialise rien : les positions sont gardées et les nouvelles
règles s'appliquent aux bougies qui se terminent après le changement.

Usage : python bot.py --once
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import sources  # noqa: E402
import strategies as S  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")
DATA = ROOT / "data"
STATE_PATH = DATA / "state.json"
CONFIG_PATH = ROOT / "config.json"
MARKET_DIR = DATA / "market"
MARKET_REFRESH_SEC = 6 * 3600
HISTORY = 300                       # bougies utilisées pour calculer les indicateurs
INITIAL_STRATEGY = {"id": "ema", "params": {"rapide": 20, "lente": 50}}
GROUPS = ("crypto", "action", "indice")


def log(msg: str) -> None:
    print(f"{datetime.now(PARIS).isoformat(timespec='seconds')}  {msg}", flush=True)


def iso(ms_or_dt) -> str:
    dt = ms_or_dt if isinstance(ms_or_dt, datetime) else datetime.fromtimestamp(ms_or_dt / 1000, timezone.utc)
    return dt.astimezone(PARIS).isoformat(timespec="seconds")


def to_ms(s: str) -> int:
    return int(datetime.fromisoformat(s).timestamp() * 1000)


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


# --- Stratégie en vigueur -------------------------------------------------------------

def norm(strat: dict | None) -> dict | None:
    if not strat:
        return None
    return {"id": strat["id"], "params": S.full_params(strat["id"], strat.get("params"))}


def config_strategies(cfg: dict) -> dict:
    return {"global": norm(cfg["strategy"]),
            "overrides": {a["key"]: norm(a["strategy"]) for a in cfg["assets"] if a.get("strategy")}}


def sync_strategy_log(state: dict, cfg: dict) -> None:
    """Si config.json a été modifié à la main, on enregistre le changement dans l'historique."""
    want = config_strategies(cfg)
    have = state.get("strategy_current")
    if have == want:
        return
    now = iso(datetime.now(PARIS))
    old = have or {"global": INITIAL_STRATEGY, "overrides": {}}
    if old["global"] != want["global"]:
        state["strategy_changes"].append({"time": now, "scope": "tous", "old": old["global"], "new": want["global"],
                                          "by": "config.json"})
    for key in set(old["overrides"]) | set(want["overrides"]):
        if old["overrides"].get(key) != want["overrides"].get(key):
            state["strategy_changes"].append({"time": now, "scope": key, "old": old["overrides"].get(key),
                                              "new": want["overrides"].get(key), "by": "config.json"})
    state["strategy_current"] = want


def strategy_at(state: dict, key: str, close_ms: int) -> tuple[dict, int | None]:
    """Stratégie en vigueur pour `key` à la clôture `close_ms`, et depuis quand (ms)."""
    glob, overrides, since = INITIAL_STRATEGY, {}, None
    since_by = {}
    for ch in state.get("strategy_changes", []):
        t = to_ms(ch["time"])
        if t > close_ms:
            break
        if ch["scope"] == "tous":
            glob, overrides = ch["new"], {}
            since = t
            since_by = {}
        else:
            if ch["new"]:
                overrides[ch["scope"]] = ch["new"]
            else:
                overrides.pop(ch["scope"], None)
            since_by[ch["scope"]] = t
    if key in overrides:
        return norm(overrides[key]), since_by.get(key)
    return norm(glob), max([since or 0, since_by.get(key) or 0]) or None


# --- État -------------------------------------------------------------------------

def migrate(state: dict, cfg: dict) -> dict:
    if state.get("version", 1) < 2:
        last = state.get("last_processed_candle_open_ms")
        for key, a in state["assets"].items():
            a.setdefault("last_open_ms", last)
            a.setdefault("last_price", (state.get("last_prices") or {}).get(key))
            a.setdefault("envelope", state.get("allocation_per_asset", 1000.0))
            a.setdefault("added_at", state.get("started_at"))
        state.setdefault("strategy_changes", [])
        state["strategy_current"] = {"global": norm(INITIAL_STRATEGY), "overrides": {}}
        for h in state.get("equity_history", []):
            h.setdefault("capital", 10000.0)
            h.setdefault("groups", {"crypto": {"equity": h["equity"], "bh": h["buy_and_hold_equity"], "capital": 10000.0}})
        for t in state.get("trades", []):
            t.setdefault("group", "crypto")
            t.setdefault("label", t["symbol"].replace("USDT", ""))
            t.setdefault("strategy", "ema")
        state["version"] = 2
        state.pop("last_signals", None)
    state.setdefault("strategy_changes", [])
    for a in cfg["assets"]:
        key = a["key"]
        if key not in state["assets"]:
            env = float(a.get("envelope", 1000))
            state["assets"][key] = {"cash": env, "qty": 0.0, "entry_price": None, "entry_time": None, "entry_fee": 0.0,
                                    "realized_pnl": 0.0, "last_open_ms": None, "last_price": None, "envelope": env,
                                    "added_at": iso(datetime.now(PARIS))}
            log(f"Nouvel actif {key} : enveloppe fictive de {env:.0f} €")
        meta = state["assets"][key]
        meta.update({"label": a["label"], "name": a["name"], "group": a["group"], "currency": a.get("currency", "USD"),
                     "source_symbol": a["symbol"], "active": True})
    active = {a["key"] for a in cfg["assets"]}
    for key, a in state["assets"].items():
        if key not in active:
            a["active"] = False
    state["timeframe"] = cfg.get("timeframe", "1h")
    state["currency"] = cfg.get("currency", "EUR")
    state["fee_rate"] = float(cfg.get("fee_rate", 0.0))
    return state


def describe(strat: dict) -> str:
    return S.label(strat["id"], strat["params"])


def buy(state, key, amount, price, when, reason, strat_id, fee_rate):
    a = state["assets"][key]
    amount = min(amount, a["cash"])
    if amount <= 1e-9:
        return None
    fee = amount * fee_rate
    q = (amount - fee) / price
    old_q = a["qty"]
    a["entry_price"] = price if old_q <= 0 else (old_q * a["entry_price"] + q * price) / (old_q + q)
    if old_q <= 0:
        a["entry_time"] = when
    a["qty"] = old_q + q
    a["cash"] -= amount
    a["cost_basis"] = a.get("cost_basis", 0.0) * (old_q > 0) + amount
    return trade(state, key, "BUY", price, q, fee, amount - fee, when, reason, strat_id)


def sell(state, key, price, when, reason, strat_id, fee_rate):
    a = state["assets"][key]
    q = a["qty"]
    if q <= 0:
        return None
    notional = q * price
    fee = notional * fee_rate
    proceeds = notional - fee
    cost = a.get("cost_basis") or q * a["entry_price"]
    pnl = proceeds - cost
    a["realized_pnl"] = a.get("realized_pnl", 0.0) + pnl
    a["cash"] += proceeds
    a.update(qty=0.0, entry_price=None, entry_time=None, cost_basis=0.0)
    t = trade(state, key, "SELL", price, q, fee, notional, when, reason, strat_id)
    t["pnl"] = pnl
    return t


def trade(state, key, side, price, q, fee, notional, when, reason, strat_id):
    a = state["assets"][key]
    t = {"id": len(state["trades"]) + 1, "time": when, "symbol": key, "label": a["label"], "group": a["group"],
         "side": side, "price": price, "qty": q, "fee": fee, "notional": notional, "cash_after": a["cash"],
         "qty_after": a["qty"], "reason": reason, "strategy": strat_id, "equity_after": None}
    state["trades"].append(t)
    log(f"{side:4s} {a['label']:10s} prix={price:.6g} qty={q:.8g} — {reason}")
    return t


REASONS = {
    ("ema", "achat"): "Croisement haussier : l'EMA courte repasse au-dessus de la longue",
    ("ema", "vente"): "EMA courte passée sous la longue : tendance baissière",
    ("rsi", "achat"): "Le RSI vient de passer sous le seuil bas : actif très survendu",
    ("rsi", "vente"): "RSI au-dessus du seuil haut : l'actif a beaucoup monté",
    ("boll", "achat"): "Le prix vient de sortir par le haut de la bande de Bollinger",
    ("boll", "vente"): "Prix retombé sous le milieu de la bande de Bollinger",
    ("macd", "achat"): "Le MACD vient de repasser au-dessus de sa ligne signal : élan haussier",
    ("macd", "vente"): "MACD sous sa ligne signal : élan qui faiblit",
    ("bh", "achat"): "Acheter et garder : achat, puis on ne revend plus",
}


def process_candle(state, key, candles, i, ends_ms, fee_rate):
    """Applique la stratégie à la bougie candles[i] (terminée) de l'actif `key`."""
    a = state["assets"][key]
    k = candles[i]
    when = iso(k["ct"] + 1 if (k["ct"] + 1) % 1000 == 0 else k["ct"])
    price = k["c"]
    strat, since = strategy_at(state, key, k["ct"])
    sid, p = strat["id"], strat["params"]
    closes = [c["c"] for c in candles[max(0, i - HISTORY + 1): i + 1]]
    ctx = {}
    if sid == "dca":
        since = since or to_ms(state["started_at"])
        d = a.get("dca")
        if not d or d.get("since") != since or d.get("n") != p["n"]:
            d = a["dca"] = {"since": since, "n": int(p["n"]), "amount": a["cash"] / int(p["n"]), "done": 0}
        if d["done"] < d["n"] and a["cash"] > 1e-9:
            due = d["since"] + d["done"] * (ends_ms - d["since"]) / d["n"]
            if k["ct"] >= due:
                ctx["dca_amount"] = d["amount"]
    sig = S.STRATEGIES[sid]["fn"](closes, p, ctx)[-1]
    out = None
    if sig == "achat" and a["cash"] > 1e-9:
        out = buy(state, key, a["cash"], price, when, REASONS.get((sid, "achat"), "Signal d'achat"), sid, fee_rate)
    elif isinstance(sig, (int, float)) and not isinstance(sig, bool) and a["cash"] > 1e-9:
        out = buy(state, key, sig, price, when, f"Achat régulier n°{a['dca']['done'] + 1} sur {a['dca']['n']}", sid, fee_rate)
        a["dca"]["done"] += 1
    elif sig == "vente" and a["qty"] > 0:
        out = sell(state, key, price, when, REASONS.get((sid, "vente"), "Signal de vente"), sid, fee_rate)
    # Référence « acheter et garder » : achat unique à la 1re bougie tradée de l'actif.
    bh = state["buy_and_hold"].setdefault("positions", {})
    if key not in bh:
        env = a["envelope"]
        bh[key] = {"entry_price": price, "qty": env * (1 - fee_rate) / price, "fee": env * fee_rate,
                   "cash_residual": 0.0, "entry_time": when}
    a["last_open_ms"], a["last_price"], a["last_close_time"] = k["t"], price, when
    return out


def snapshot(state, when_ms) -> dict:
    groups = {g: {"equity": 0.0, "bh": 0.0, "capital": 0.0} for g in GROUPS}
    real = unreal = 0.0
    for key, a in state["assets"].items():
        if a.get("last_price") is None and a["qty"] <= 0:
            eq = a["cash"]
        else:
            eq = a["cash"] + a["qty"] * (a.get("last_price") or 0)
        pos = state["buy_and_hold"].get("positions", {}).get(key)
        bh = pos["qty"] * a["last_price"] + pos.get("cash_residual", 0) if (pos and a.get("last_price")) else a["envelope"]
        g = groups.setdefault(a.get("group", "crypto"), {"equity": 0.0, "bh": 0.0, "capital": 0.0})
        g["equity"] += eq
        g["bh"] += bh
        g["capital"] += a["envelope"]
        real += a.get("realized_pnl", 0.0)
        if a["qty"] > 0 and a.get("entry_price"):
            unreal += (a["last_price"] - a["entry_price"]) * a["qty"]
    eq = sum(g["equity"] for g in groups.values())
    return {"time": iso(when_ms), "time_ms": when_ms, "equity": eq,
            "buy_and_hold_equity": sum(g["bh"] for g in groups.values()),
            "capital": sum(g["capital"] for g in groups.values()), "realized_pnl": real, "unrealized_pnl": unreal,
            "groups": groups}


def write_csvs(state) -> None:
    fields = ["id", "time", "symbol", "label", "group", "side", "price", "qty", "fee", "notional", "pnl", "strategy", "reason"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(state["trades"])
    (DATA / "trades.csv").write_text(buf.getvalue(), encoding="utf-8")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time", "equity", "buy_and_hold_equity", "capital", "crypto", "action", "indice"])
    for h in state["equity_history"]:
        g = h.get("groups", {})
        w.writerow([h["time"], round(h["equity"], 4), round(h["buy_and_hold_equity"] or 0, 4), h.get("capital"),
                    *[round(g.get(x, {}).get("equity", 0), 4) for x in GROUPS]])
    (DATA / "equity.csv").write_text(buf.getvalue(), encoding="utf-8")


def refresh_market_cache(cfg) -> None:
    """Historique Yahoo pour le testeur de stratégies du tableau de bord (toutes les 6 h)."""
    for a in cfg["assets"]:
        if a["source"] != "yahoo":
            continue
        p = MARKET_DIR / f"{a['key']}.json"
        try:
            if p.exists() and time.time() - load_json(p).get("generated_at_ms", 0) / 1000 < MARKET_REFRESH_SEC:
                continue
            obj = sources.market_cache(a["symbol"])
            obj.update(key=a["key"], label=a["label"], group=a["group"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
            log(f"Historique {a['label']} mis à jour pour le testeur ({len(obj['1h'])} bougies 1h, {len(obj['15m'])} 15 min)")
        except Exception as e:  # noqa: BLE001
            log(f"Historique {a['label']} non mis à jour : {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-market-cache", action="store_true")
    args = ap.parse_args()
    cfg = load_json(CONFIG_PATH)
    state = migrate(load_json(STATE_PATH), cfg)
    sync_strategy_log(state, cfg)
    fee = state["fee_rate"]
    ends_ms = to_ms(state["ends_at"])
    now_ms = int(time.time() * 1000)

    # 1) récupérer les bougies de chaque actif
    data, errors, used = {}, {}, {}
    for a in cfg["assets"]:
        try:
            if a["source"] == "binance":
                c, src = sources.crypto_candles(a["symbol"])
            else:
                c, src, meta = sources.stock_candles(a["symbol"])
                state["assets"][a["key"]]["currency"] = meta.get("currency") or a.get("currency")
            data[a["key"]], used[a["key"]] = c, src
        except Exception as e:  # noqa: BLE001
            errors[a["key"]] = str(e)
            log(f"⚠️ {a['label']} : données indisponibles ({e})")
        time.sleep(0.1)
    state["data_sources"] = sorted(set(used.values()))
    state["data_source"] = " + ".join(state["data_sources"])
    state["data_errors"] = errors

    # 2) bougies à traiter, toutes actifs confondus, dans l'ordre chronologique
    events = []
    for key, c in data.items():
        a = state["assets"][key]
        if a["last_open_ms"] is None:
            # Nouvel actif : on note la dernière bougie terminée sans trader ;
            # il commencera à trader à la prochaine bougie (marché ouvert).
            a["last_open_ms"], a["last_price"] = c[-1]["t"], c[-1]["c"]
            a["last_close_time"] = iso(c[-1]["ct"] + 1 if (c[-1]["ct"] + 1) % 1000 == 0 else c[-1]["ct"])
            log(f"{a['label']} : prêt, premier trade possible à la prochaine bougie terminée")
            continue
        for i, k in enumerate(c):
            if k["t"] > a["last_open_ms"] and k["ct"] <= ends_ms:
                events.append((k["ct"], key, i))
    events.sort()
    n_trades = 0
    by_time: dict[int, list] = {}
    for ct, key, i in events:
        by_time.setdefault(ct, []).append((key, i))
    for ct in sorted(by_time):
        for key, i in by_time[ct]:
            if process_candle(state, key, data[key], i, ends_ms, fee):
                n_trades += 1
        snap = snapshot(state, ct + 1 if (ct + 1) % 1000 == 0 else ct)
        for t in state["trades"]:
            if t["equity_after"] is None:
                t["equity_after"] = snap["equity"]
        state["equity_history"].append(snap)
    if not events and not state["equity_history"]:
        state["equity_history"].append(snapshot(state, now_ms))
    state["last_run_at"] = iso(datetime.now(PARIS))
    if events:
        last = max(by_time)
        state["last_processed_candle_close_paris"] = iso(last + 1 if (last + 1) % 1000 == 0 else last)
    state["last_prices"] = {k: a.get("last_price") for k, a in state["assets"].items()}
    cur = snapshot(state, now_ms)
    state["summary"] = cur
    state["initial_capital"] = cur["capital"]
    state["strategy"] = describe(state["strategy_current"]["global"]) + " · bougies 1h"
    write_json(STATE_PATH, state)
    write_csvs(state)
    log(f"{len(events)} bougie(s) traitée(s), {n_trades} ordre(s) fictif(s). Capital fictif : {cur['equity']:.2f} € "
        f"sur {cur['capital']:.0f} € d'enveloppes (gain {cur['equity'] - cur['capital']:+.2f} €).")
    if not args.no_market_cache:
        refresh_market_cache(cfg)
    try:
        from report import make_chart
        make_chart(state)
    except Exception:  # noqa: BLE001
        log("Graphique PNG non généré :\n" + traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
