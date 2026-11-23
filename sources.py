# -*- coding: utf-8 -*-
"""Sources de prix publiques, sans clé API (lecture seule, aucun compte).

- Cryptos : Binance.US /api/v3/klines (repli api.binance.com, puis Kraken OHLC).
- Actions et indices : Yahoo Finance, API publique « chart »
  (query1.finance.yahoo.com/v8/finance/chart, repli query2).

Chaque bougie : {"t": ouverture ms, "ct": clôture ms, "o","h","l","c"}.
Seules les bougies TERMINÉES sont renvoyées. Pour la Bourse, il n'existe des
bougies que pendant les heures d'ouverture : la nuit et le week-end, il n'y a
donc aucune nouvelle bougie, et donc aucun trade.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

UA = {"User-Agent": "Mozilla/5.0 (paper-trading-bot; argent fictif; lecture seule)"}
H = 3_600_000
KRAKEN_PAIR = {"BTCUSDT": "XBTUSDT"}
# Fin de séance normale, heure locale de la Bourse (la dernière bougie peut être plus courte).
SESSION_END = {"America/New_York": (16, 0), "Europe/Paris": (17, 30)}


class SourceError(RuntimeError):
    pass


def get_json(url: str, retries: int = 3) -> object:
    err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if e.code in (400, 404, 451):
                break
        except Exception as e:  # noqa: BLE001
            err = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise SourceError(f"{url} → {err}")


# --- Cryptos ----------------------------------------------------------------------

def _binance(base: str, symbol: str, limit: int) -> list[dict]:
    raw = get_json(f"{base}/api/v3/klines?symbol={symbol}&interval=1h&limit={limit}")
    now = int(time.time() * 1000)
    out = [{"t": int(k[0]), "ct": int(k[6]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4])}
           for k in raw]
    return [k for k in out if k["ct"] < now]


def _kraken(symbol: str) -> list[dict]:
    pair = KRAKEN_PAIR.get(symbol, symbol)
    raw = get_json(f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=60")
    if raw.get("error"):
        raise SourceError(str(raw["error"]))
    series = next(v for k, v in raw["result"].items() if k != "last")
    now = int(time.time() * 1000)
    out = [{"t": int(r[0]) * 1000, "ct": int(r[0]) * 1000 + H - 1, "o": float(r[1]), "h": float(r[2]),
            "l": float(r[3]), "c": float(r[4])} for r in series]
    return [k for k in out if k["ct"] < now]


def crypto_candles(symbol: str, limit: int = 300) -> tuple[list[dict], str]:
    errors = []
    for name, fn in (("Binance.US", lambda: _binance("https://api.binance.us", symbol, limit)),
                     ("Binance", lambda: _binance("https://api.binance.com", symbol, limit)),
                     ("Kraken", lambda: _kraken(symbol)[-limit:])):
        try:
            c = fn()
            if len(c) >= 60:
                return c, name
            errors.append(f"{name}: seulement {len(c)} bougies")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    raise SourceError(f"{symbol} : " + " | ".join(errors))


# --- Actions / indices (Yahoo Finance) ---------------------------------------------

def yahoo_raw(symbol: str, interval: str, rng: str) -> dict:
    q = urllib.parse.quote(symbol)
    errors = []
    for host in ("query1", "query2"):
        try:
            j = get_json(f"https://{host}.finance.yahoo.com/v8/finance/chart/{q}?interval={interval}&range={rng}")
            res = (j.get("chart") or {}).get("result")
            if res:
                return res[0]
            errors.append(f"{host}: {(j.get('chart') or {}).get('error')}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{host}: {e}")
    raise SourceError(f"Yahoo {symbol} : " + " | ".join(errors))


def yahoo_candles_from_raw(res: dict, interval_ms: int) -> list[dict]:
    """Bougies terminées uniquement, sur la grille de la séance (on écarte le point
    « cours de clôture » que Yahoo ajoute hors grille en fin de journée)."""
    ts = res.get("timestamp") or []
    q = (res.get("indicators") or {}).get("quote", [{}])[0]
    tzname = res.get("meta", {}).get("exchangeTimezoneName", "America/New_York")
    tz = ZoneInfo(tzname)
    end_h, end_m = SESSION_END.get(tzname, (16, 0))
    now = int(time.time() * 1000)
    rows, day_first = [], {}
    for i, t in enumerate(ts):
        o, h, l, c = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close"))
        if None in (o, h, l, c):
            continue
        tms = int(t) * 1000
        local = datetime.fromtimestamp(t, tz)
        day = local.date()
        first = day_first.setdefault(day, tms)
        if (tms - first) % interval_ms != 0:
            continue  # point hors grille (clôture du jour)
        session_end = int(local.replace(hour=end_h, minute=end_m, second=0, microsecond=0).timestamp() * 1000)
        ct = min(tms + interval_ms, session_end) - 1
        if ct >= now:
            continue  # bougie en cours
        rows.append({"t": tms, "ct": ct, "o": float(o), "h": float(h), "l": float(l), "c": float(c)})
    return rows


def stock_candles(symbol: str) -> tuple[list[dict], str, dict]:
    res = yahoo_raw(symbol, "1h", "60d")
    c = yahoo_candles_from_raw(res, H)
    if len(c) < 60:
        raise SourceError(f"Yahoo {symbol} : seulement {len(c)} bougies")
    meta = res.get("meta", {})
    return c, "Yahoo Finance", {"currency": meta.get("currency"), "exchange": meta.get("fullExchangeName"),
                                 "timezone": meta.get("exchangeTimezoneName")}


def market_cache(symbol: str) -> dict:
    """Historique compact pour le testeur de stratégies du tableau de bord
    (Yahoo n'autorise pas la lecture directe depuis un fichier ouvert en local)."""
    out = {"symbol": symbol, "generated_at_ms": int(time.time() * 1000), "source": "Yahoo Finance"}
    for iv, rng, ms in (("1h", "6mo", H), ("15m", "60d", 900_000)):
        res = yahoo_raw(symbol, iv, rng)
        c = yahoo_candles_from_raw(res, ms)
        out["currency"] = res.get("meta", {}).get("currency")
        out[iv] = [[k["t"], k["ct"], round(k["o"], 6), round(k["h"], 6), round(k["l"], 6), round(k["c"], 6)] for k in c]
        time.sleep(0.3)
    return out
