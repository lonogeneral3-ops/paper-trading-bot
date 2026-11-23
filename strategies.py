# -*- coding: utf-8 -*-
"""
Stratégies du bot (argent 100 % fictif).

Ce sont EXACTEMENT les mêmes règles que l'onglet « Tester des stratégies » du
tableau de bord local (mon-dashboard-trading.html) : mêmes indicateurs, mêmes
paramètres par défaut, mêmes signaux.

Chaque stratégie renvoie, pour chaque bougie, un signal :
    "achat"  → acheter avec tout le cash disponible de cet actif
    "vente"  → tout revendre
    un nombre → acheter pour ce montant en $ (achat régulier)
    None     → ne rien faire

➕ Pour ajouter une stratégie : écrire une fonction signaux_xxx(closes, p, ctx)
   et l'ajouter dans STRATEGIES (et dans le tableau de bord pour la tester).
"""
from __future__ import annotations

import math


# --- Indicateurs (identiques au JavaScript du tableau de bord) ------------------

def EMA(v: list[float], n: int) -> list[float | None]:
    n = int(n)
    k = 2.0 / (n + 1)
    out: list[float | None] = [None] * len(v)
    e = None
    for i in range(len(v)):
        if i < n - 1:
            continue
        if e is None:
            e = sum(v[:n]) / n
        else:
            e = v[i] * k + e * (1 - k)
        out[i] = e
    return out


def SMA(v: list[float], n: int) -> list[float | None]:
    n = int(n)
    out: list[float | None] = [None] * len(v)
    s = 0.0
    for i in range(len(v)):
        s += v[i]
        if i >= n:
            s -= v[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def STD(v: list[float], n: int) -> list[float | None]:
    n = int(n)
    m = SMA(v, n)
    out: list[float | None] = [None] * len(v)
    for i in range(len(v)):
        if m[i] is None:
            continue
        s = sum((v[j] - m[i]) ** 2 for j in range(i - n + 1, i + 1))
        out[i] = math.sqrt(s / n)
    return out


def RSI(v: list[float], n: int) -> list[float | None]:
    n = int(n)
    out: list[float | None] = [None] * len(v)
    g = l = 0.0
    for i in range(1, len(v)):
        d = v[i] - v[i - 1]
        up, dn = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            g += up
            l += dn
            if i == n:
                g /= n
                l /= n
                out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
        else:
            g = (g * (n - 1) + up) / n
            l = (l * (n - 1) + dn) / n
            out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


# --- Signaux ---------------------------------------------------------------------

def signaux_ema(c, p, ctx):
    f, s = EMA(c, p["rapide"]), EMA(c, p["lente"])
    return [None if f[i] is None or s[i] is None else "achat" if f[i] > s[i] else "vente" if f[i] < s[i] else None
            for i in range(len(c))]


def signaux_rsi(c, p, ctx):
    r = RSI(c, p["periode"])
    return [None if x is None else "achat" if x < p["bas"] else "vente" if x > p["haut"] else None for x in r]


def signaux_boll(c, p, ctx):
    m, sd = SMA(c, p["periode"]), STD(c, p["periode"])
    out = []
    for i, x in enumerate(c):
        if m[i] is None:
            out.append(None)
        elif x > m[i] + p["ecart"] * sd[i]:
            out.append("achat")
        elif x < m[i]:
            out.append("vente")
        else:
            out.append(None)
    return out


def signaux_macd(c, p, ctx):
    f, s = EMA(c, p["rapide"]), EMA(c, p["lente"])
    macd = [f[i] - s[i] if f[i] is not None and s[i] is not None else None for i in range(len(c))]
    sig: list[float | None] = [None] * len(c)
    first = next((i for i, x in enumerate(macd) if x is not None), -1)
    if first >= 0:
        e = EMA(macd[first:], p["signal"])
        for k, val in enumerate(e):
            sig[first + k] = val
    return [None if macd[i] is None or sig[i] is None else "achat" if macd[i] > sig[i] else "vente"
            for i in range(len(c))]


def signaux_dca(c, p, ctx):
    """Achat régulier. En direct : n achats de (cash au départ de la stratégie / n),
    répartis régulièrement dans le temps entre le changement de stratégie et la fin du test.
    Le bot gère le calendrier (voir bot.py) ; ici on renvoie juste le montant."""
    out = [None] * len(c)
    amt = ctx.get("dca_amount")
    if amt:
        out[-1] = amt
    return out


def signaux_bh(c, p, ctx):
    # Acheter et garder : on achète (tout le cash) et on ne revend jamais.
    return ["achat"] * len(c)


STRATEGIES = {
    "ema": {"nom": "Croisement de moyennes EMA", "fn": signaux_ema,
            "params": {"rapide": 20, "lente": 50},
            "explication": "Achète quand la tendance courte passe au-dessus de la tendance longue, revend quand elle repasse en dessous."},
    "rsi": {"nom": "RSI (survente / surachat)", "fn": signaux_rsi,
            "params": {"periode": 14, "bas": 30, "haut": 70},
            "explication": "Achète quand l'actif a beaucoup baissé (RSI sous 30), revend quand il a beaucoup monté (RSI au-dessus de 70)."},
    "boll": {"nom": "Cassure de Bollinger", "fn": signaux_boll,
             "params": {"periode": 20, "ecart": 2.0},
             "explication": "Achète quand le prix sort par le haut de son couloir habituel, revend quand il retombe au milieu du couloir."},
    "macd": {"nom": "MACD", "fn": signaux_macd,
             "params": {"rapide": 12, "lente": 26, "signal": 9},
             "explication": "Achète quand l'élan du prix repart à la hausse (MACD au-dessus de sa ligne signal), revend quand il faiblit."},
    "dca": {"nom": "Achat régulier (DCA)", "fn": signaux_dca,
            "params": {"n": 7},
            "explication": "Achète un petit morceau à intervalles réguliers, quel que soit le prix, sans jamais revendre."},
    "bh": {"nom": "Acheter et garder", "fn": signaux_bh,
           "params": {},
           "explication": "Achète tout de suite et ne revend jamais."},
}


def full_params(strategy_id: str, params: dict | None) -> dict:
    base = dict(STRATEGIES[strategy_id]["params"])
    for k, v in (params or {}).items():
        if k in base:
            base[k] = type(base[k])(v) if not isinstance(base[k], float) else float(v)
    return base


def label(strategy_id: str, params: dict | None) -> str:
    p = full_params(strategy_id, params)
    name = STRATEGIES[strategy_id]["nom"]
    if not p:
        return name
    return name + " (" + ", ".join(f"{k}={v:g}" if isinstance(v, (int, float)) else f"{k}={v}" for k, v in p.items()) + ")"


def validate(strategy_id: str, params: dict) -> list[str]:
    errs = []
    p = full_params(strategy_id, params)
    if strategy_id == "ema" and not (2 <= p["rapide"] < p["lente"] <= 400):
        errs.append("EMA : il faut 2 ≤ rapide < lente ≤ 400")
    if strategy_id == "rsi" and not (2 <= p["periode"] <= 100 and 1 <= p["bas"] < p["haut"] <= 99):
        errs.append("RSI : il faut 2 ≤ période ≤ 100 et 1 ≤ bas < haut ≤ 99")
    if strategy_id == "boll" and not (5 <= p["periode"] <= 200 and 0.5 <= p["ecart"] <= 4):
        errs.append("Bollinger : il faut 5 ≤ période ≤ 200 et 0,5 ≤ écart ≤ 4")
    if strategy_id == "macd" and not (2 <= p["rapide"] < p["lente"] <= 200 and 2 <= p["signal"] <= 50):
        errs.append("MACD : il faut 2 ≤ rapide < lente ≤ 200 et 2 ≤ signal ≤ 50")
    if strategy_id == "dca" and not (2 <= p["n"] <= 100):
        errs.append("DCA : il faut 2 ≤ n ≤ 100")
    return errs
