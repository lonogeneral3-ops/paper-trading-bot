# -*- coding: utf-8 -*-
"""Fonctions partagées du bot de paper trading (argent 100 % fictif)."""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# --- Réglages ------------------------------------------------------------------

PARIS = ZoneInfo("Europe/Paris")

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
STATE_PATH = DATA_DIR / "state.json"
TRADES_CSV = DATA_DIR / "trades.csv"
EQUITY_CSV = DATA_DIR / "equity.csv"
EQUITY_PNG = ROOT / "equity.png"
STOP_FLAG = DATA_DIR / "STOP"
BOT_PID = ROOT / "bot.pid"

# Source publique, sans authentification.
# api.binance.com a renvoyé HTTP 451 (restriction géographique) depuis cette machine.
# Repli : api.binance.us, endpoint public /api/v3/klines, aucune clé API.
BINANCE_BASE = "https://api.binance.us"
KLINES_URL = BINANCE_BASE + "/api/v3/klines"

UNIVERSE = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
]

INITIAL_CAPITAL = 10_000.0
N_ASSETS = len(UNIVERSE)
ALLOCATION = INITIAL_CAPITAL / N_ASSETS  # 1 000 $ fictifs par crypto
FEE_RATE = 0.0  # pas de frais (demande de Loris) : 0 % à l'achat comme à la vente
EMA_FAST = 20
EMA_SLOW = 50
INTERVAL = "1h"
KLINE_LIMIT = 200
RUN_DAYS = 7
CANDLE_CLOSE_BUFFER_SEC = 20
REQUEST_TIMEOUT = 20

# On ACHÈTE si on n'est pas déjà en position ET que l'EMA 20 est au-dessus de l'EMA 50
# (tendance déjà haussière). On n'attend PAS un nouveau croisement.
# On VEND si on est en position ET que l'EMA 20 est au-dessous de l'EMA 50.
ENTRY_IF_TREND_ALREADY_UP = True

STRATEGY_NAME = "EMA 20/50, bougies 1h, long only"
STRATEGY_DOC = (
    "Moyennes mobiles exponentielles 20 et 50 sur bougies d'une heure, "
    "positions longues uniquement, sans effet de levier. "
    "Achat si EMA20 > EMA50 et qu'on n'est pas déjà investi "
    "(y compris si la tendance est déjà haussière, pas seulement sur un nouveau croisement). "
    "Vente si EMA20 < EMA50. Sans frais (0 %). "
    "Décisions prises à la clôture de la bougie 1h, au prix de clôture."
)


# --- Temps ---------------------------------------------------------------------

def now_paris() -> datetime:
    return datetime.now(PARIS)


def fmt_paris(dt: datetime | None = None) -> str:
    """Horodatage ISO avec le fuseau Europe/Paris."""
    if dt is None:
        dt = now_paris()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(PARIS)
    else:
        dt = dt.astimezone(PARIS)
    return dt.isoformat(timespec="seconds")


def ms_to_paris(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(PARIS)


# --- Fichiers ------------------------------------------------------------------

def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def stop_requested() -> bool:
    return STOP_FLAG.exists()


# --- HTTP public + sources de secours ------------------------------------------

class DataSourceError(RuntimeError):
    """Échec d'une source de prix publique (éventuellement blocage géographique)."""

    def __init__(self, message: str, blocked: bool = False) -> None:
        super().__init__(message)
        self.blocked = blocked


# Dernière source réellement utilisée par fetch_all_closed_klines (pour l'état / le journal).
LAST_FETCH_META: dict = {
    "name": "binance_us",
    "label": KLINES_URL,
    "note": (
        "api.binance.com renvoyait HTTP 451 (restriction géographique) ; "
        "source principale : api.binance.us, endpoint public /api/v3/klines, sans clé API. "
        "Repli : api.binance.com, puis Kraken public OHLC (intervalle 60 min)."
    ),
}

# Correspondance Binance → Kraken (DOGE s'appelle XDG chez Kraken).
KRAKEN_PAIR = {
    "BTCUSDT": "XBTUSDT",
    "ETHUSDT": "ETHUSDT",
    "SOLUSDT": "SOLUSDT",
    "BNBUSDT": "BNBUSDT",
    "XRPUSDT": "XRPUSDT",
    "ADAUSDT": "ADAUSDT",
    "DOGEUSDT": "DOGEUSDT",
    "AVAXUSDT": "AVAXUSDT",
    "LINKUSDT": "LINKUSDT",
    "DOTUSDT": "DOTUSDT",
}


def http_get_json(url: str, retries: int = 4) -> object:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "paper-bot/1.0 (fictitious trading, no account)"},
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            try:
                err_body = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                err_body = ""
            if exc.code in (451, 403):
                raise DataSourceError(
                    f"HTTP {exc.code} (bloqué) {url} {err_body}",
                    blocked=True,
                ) from exc
            last_err = exc
            time.sleep(min(2 ** attempt, 20))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = exc
            time.sleep(min(2 ** attempt, 20))
    raise DataSourceError(f"Échec HTTP après {retries} essais: {url} ({last_err})")


def _closed_only(candles: list[dict], symbol: str) -> list[dict]:
    closed = [c for c in candles if c["closed"]]
    if len(closed) < EMA_SLOW + 2:
        raise DataSourceError(
            f"Pas assez de bougies closes pour {symbol} ({len(closed)})"
        )
    closed.sort(key=lambda c: c["open_time_ms"])
    return closed


def _parse_binance_klines(raw: object, symbol: str) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise DataSourceError(f"Réponse klines inattendue pour {symbol}: {raw!r}")
    now_ms = int(time.time() * 1000)
    candles = []
    for row in raw:
        open_ms = int(row[0])
        close_ms = int(row[6])
        candles.append(
            {
                "open_time_ms": open_ms,
                "close_time_ms": close_ms,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "closed": now_ms >= close_ms,
            }
        )
    return _closed_only(candles, symbol)


def _parse_kraken_ohlc(raw: object, symbol: str) -> list[dict]:
    if not isinstance(raw, dict):
        raise DataSourceError(f"Réponse Kraken inattendue pour {symbol}: {raw!r}")
    if raw.get("error"):
        raise DataSourceError(f"Kraken error {symbol}: {raw['error']}")
    result = raw.get("result") or {}
    series = None
    for key, val in result.items():
        if key == "last":
            continue
        series = val
        break
    if not series:
        raise DataSourceError(f"Pas de série OHLC Kraken pour {symbol}: {list(result)}")
    now_ms = int(time.time() * 1000)
    candles = []
    for row in series:
        open_ms = int(row[0]) * 1000
        close_ms = open_ms + 3_600_000 - 1
        candles.append(
            {
                "open_time_ms": open_ms,
                "close_time_ms": close_ms,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[6]),
                "closed": now_ms >= close_ms,
            }
        )
    # Kraken peut renvoyer plus de 200 bougies : on aligne la profondeur sur Binance.
    candles = _closed_only(candles, symbol)
    return candles[-KLINE_LIMIT:]


def fetch_klines_from(source: str, symbol: str, limit: int = KLINE_LIMIT) -> list[dict]:
    if source == "binance_us":
        url = f"https://api.binance.us/api/v3/klines?symbol={symbol}&interval={INTERVAL}&limit={limit}"
        return _parse_binance_klines(http_get_json(url), symbol)
    if source == "binance_com":
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={INTERVAL}&limit={limit}"
        return _parse_binance_klines(http_get_json(url), symbol)
    if source == "kraken":
        pair = KRAKEN_PAIR[symbol]
        url = f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=60"
        return _parse_kraken_ohlc(http_get_json(url), symbol)
    raise DataSourceError(f"Source inconnue: {source}")


def fetch_klines(symbol: str, limit: int = KLINE_LIMIT) -> list[dict]:
    """Récupère des bougies 1h publiques. La bougie en cours (non close) est écartée."""
    data, _meta = fetch_all_closed_klines_with_meta()
    if symbol not in data:
        raise DataSourceError(f"Pas de données pour {symbol}")
    return data[symbol] if limit >= len(data[symbol]) else data[symbol][-limit:]


SOURCE_CHAIN = (
    ("binance_us", "https://api.binance.us/api/v3/klines"),
    ("binance_com", "https://api.binance.com/api/v3/klines"),
    ("kraken", "https://api.kraken.com/0/public/OHLC"),
)


def fetch_all_closed_klines_with_meta() -> tuple[dict[str, list[dict]], dict]:
    """Essaie les sources publiques dans l'ordre, une seule source pour tout l'univers."""
    global LAST_FETCH_META
    errors: dict[str, str] = {}
    for name, label in SOURCE_CHAIN:
        try:
            data: dict[str, list[dict]] = {}
            for i, symbol in enumerate(UNIVERSE):
                data[symbol] = fetch_klines_from(name, symbol)
                if i < len(UNIVERSE) - 1:
                    time.sleep(0.15)
            if len(data) != len(UNIVERSE):
                raise DataSourceError(f"Univers incomplet via {name}")
            meta = {
                "name": name,
                "label": label,
                "note": (
                    f"Source utilisée : {label} (publique, sans clé API). "
                    "Ordre de tentative : api.binance.us, puis api.binance.com, "
                    "puis Kraken public OHLC 1h."
                ),
            }
            LAST_FETCH_META = meta
            return data, meta
        except Exception as exc:  # noqa: BLE001
            errors[name] = str(exc)
            # Si la source est géo-bloquée, on passe tout de suite à la suivante.
            print(f"[source] {name} indisponible : {exc}", flush=True)
            continue
    raise RuntimeError(f"Impossible de récupérer les prix, toutes les sources ont échoué: {errors}")


def fetch_all_closed_klines() -> dict[str, list[dict]]:
    data, _meta = fetch_all_closed_klines_with_meta()
    return data


def ends_at_dt(state: dict) -> datetime | None:
    ends = state.get("ends_at")
    if not ends:
        return None
    try:
        dt = datetime.fromisoformat(str(ends))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PARIS)
    return dt


def slice_klines_through(
    klines_by_symbol: dict[str, list[dict]], open_ms: int
) -> dict[str, list[dict]]:
    """Coupe chaque série à la bougie `open_ms` incluse (pas de fuite d'information future)."""
    out: dict[str, list[dict]] = {}
    for sym, candles in klines_by_symbol.items():
        sliced = [c for c in candles if c["open_time_ms"] <= open_ms]
        if sliced:
            out[sym] = sliced
    return out


def pending_candle_open_times(
    klines_by_symbol: dict[str, list[dict]],
    last_processed_open_ms: int | None,
    ends_at: datetime | None,
) -> list[int]:
    """Bougies 1h closes pas encore traitées, dans l'ordre, avant la date de fin."""
    sets = [set(c["open_time_ms"] for c in candles) for candles in klines_by_symbol.values()]
    if not sets:
        return []
    common = set.intersection(*sets)
    close_by_open: dict[int, int] = {}
    for candles in klines_by_symbol.values():
        for c in candles:
            close_by_open[c["open_time_ms"]] = c["close_time_ms"]
    times = sorted(
        t for t in common if last_processed_open_ms is None or t > last_processed_open_ms
    )
    # Premier run (pas encore d'état) : on ne remonte pas 200 heures d'historique.
    if last_processed_open_ms is None and times:
        times = [times[-1]]
    pending: list[int] = []
    for t in times:
        close_dt = ms_to_paris(close_by_open[t])
        if ends_at is not None and close_dt > ends_at:
            continue
        pending.append(t)
    return pending


# --- Indicateurs ---------------------------------------------------------------

def ema(values: list[float], period: int) -> list[float | None]:
    """EMA classique : amorcée par la SMA des `period` premières valeurs."""
    if len(values) < period:
        return [None] * len(values)
    k = 2.0 / (period + 1)
    out: list[float | None] = [None] * (period - 1)
    acc = sum(values[:period]) / period
    out.append(acc)
    for price in values[period:]:
        acc = price * k + acc * (1.0 - k)
        out.append(acc)
    return out


def last_signal(closes: list[float]) -> dict:
    """Calcule EMA20/EMA50 sur la série de clôtures et le signal actuel."""
    fast = ema(closes, EMA_FAST)
    slow = ema(closes, EMA_SLOW)
    i = len(closes) - 1
    f, s = fast[i], slow[i]
    if f is None or s is None:
        raise RuntimeError("EMA incomplète")
    prev_f = fast[i - 1]
    prev_s = slow[i - 1]
    crossover = (
        prev_f is not None
        and prev_s is not None
        and prev_f <= prev_s
        and f > s
    )
    crossunder = (
        prev_f is not None
        and prev_s is not None
        and prev_f >= prev_s
        and f < s
    )
    return {
        "ema_fast": f,
        "ema_slow": s,
        "bullish": f > s,
        "bearish": f < s,
        "crossover": crossover,
        "crossunder": crossunder,
    }


# --- État ----------------------------------------------------------------------

def empty_asset() -> dict:
    return {
        "cash": ALLOCATION,
        "qty": 0.0,
        "entry_price": None,
        "entry_time": None,
        "entry_fee": 0.0,
        "realized_pnl": 0.0,
    }


def new_state() -> dict:
    return {
        "version": 1,
        "started_at": None,
        "ends_at": None,
        "data_source": KLINES_URL,
        "data_source_note": (
            "api.binance.com renvoyait HTTP 451 (restriction géographique) ; "
            "repli sur api.binance.us, endpoint public /api/v3/klines, sans clé API."
        ),
        "strategy": STRATEGY_NAME,
        "strategy_doc": STRATEGY_DOC,
        "entry_if_trend_already_up": ENTRY_IF_TREND_ALREADY_UP,
        "initial_capital": INITIAL_CAPITAL,
        "allocation_per_asset": ALLOCATION,
        "fee_rate": FEE_RATE,
        "timeframe": INTERVAL,
        "ema_fast": EMA_FAST,
        "ema_slow": EMA_SLOW,
        "universe": list(UNIVERSE),
        "last_processed_candle_open_ms": None,
        "last_processed_candle_close_paris": None,
        "last_run_at": None,
        "last_prices": {},
        "last_signals": {},
        "buy_and_hold": {
            "filled": False,
            "entry_time": None,
            "positions": {},
        },
        "assets": {symbol: empty_asset() for symbol in UNIVERSE},
        "trades": [],
        "equity_history": [],
    }


def load_state() -> dict:
    ensure_dirs()
    if not STATE_PATH.exists():
        return new_state()
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    for symbol in UNIVERSE:
        state.setdefault("assets", {}).setdefault(symbol, empty_asset())
    state.setdefault("trades", [])
    state.setdefault("equity_history", [])
    state.setdefault("last_prices", {})
    state.setdefault("last_signals", {})
    return state


def write_csvs(state: dict) -> None:
    """Réécrit les CSV à partir de l'état (source de vérité), pour rester cohérent."""
    trade_fields = [
        "id",
        "time",
        "symbol",
        "side",
        "price",
        "qty",
        "fee",
        "notional",
        "cash_after",
        "qty_after",
        "reason",
        "equity_after",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=trade_fields, extrasaction="ignore")
    writer.writeheader()
    for trade in state.get("trades", []):
        row = dict(trade)
        for key in ("price", "qty", "fee", "notional", "cash_after", "qty_after", "equity_after"):
            if key in row and isinstance(row[key], float):
                row[key] = f"{row[key]:.10f}" if key != "equity_after" else f"{row[key]:.4f}"
        writer.writerow(row)
    atomic_write_text(TRADES_CSV, buf.getvalue())

    eq_fields = [
        "time",
        "candle_open_ms",
        "equity",
        "buy_and_hold_equity",
        "cash_total",
        "positions_value",
        "unrealized_pnl",
        "realized_pnl",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=eq_fields, extrasaction="ignore")
    writer.writeheader()
    for row in state.get("equity_history", []):
        out = dict(row)
        for key in eq_fields:
            if key in ("time", "candle_open_ms"):
                continue
            if key in out and out[key] is not None:
                out[key] = f"{float(out[key]):.4f}"
        writer.writerow(out)
    atomic_write_text(EQUITY_CSV, buf.getvalue())


def save_state(state: dict) -> None:
    """Écriture atomique de l'état + export CSV."""
    ensure_dirs()
    text = json.dumps(state, ensure_ascii=False, indent=2)
    atomic_write_text(STATE_PATH, text)
    write_csvs(state)


# --- Valorisation --------------------------------------------------------------

def last_closes(klines_by_symbol: dict[str, list[dict]]) -> dict[str, float]:
    return {sym: candles[-1]["close"] for sym, candles in klines_by_symbol.items()}


def last_closed_open_ms(klines_by_symbol: dict[str, list[dict]]) -> int | None:
    times = [candles[-1]["open_time_ms"] for candles in klines_by_symbol.values()]
    if not times:
        return None
    return max(set(times), key=times.count)


def portfolio_snapshot(state: dict, prices: dict[str, float]) -> dict:
    cash_total = 0.0
    positions_value = 0.0
    realized = 0.0
    per_asset = {}
    for symbol in UNIVERSE:
        asset = state["assets"][symbol]
        price = prices.get(symbol)
        cash = float(asset["cash"])
        qty = float(asset["qty"])
        pos_val = qty * price if (price is not None and qty) else 0.0
        total = cash + pos_val
        entry = asset.get("entry_price")
        unreal = (
            (price - entry) * qty
            if (entry is not None and price is not None and qty)
            else 0.0
        )
        realized_i = float(asset.get("realized_pnl") or 0.0)
        pnl = total - ALLOCATION
        per_asset[symbol] = {
            "cash": cash,
            "qty": qty,
            "price": price,
            "position_value": pos_val,
            "equity": total,
            "entry_price": entry,
            "entry_time": asset.get("entry_time"),
            "unrealized_pnl": unreal,
            "realized_pnl": realized_i,
            "pnl": pnl,
            "pnl_pct": (pnl / ALLOCATION) * 100.0,
            "in_position": qty > 0,
        }
        cash_total += cash
        positions_value += pos_val
        realized += realized_i
    equity = cash_total + positions_value
    bh = buy_and_hold_value(state, prices)
    return {
        "equity": equity,
        "cash_total": cash_total,
        "positions_value": positions_value,
        "realized_pnl": realized,
        "unrealized_pnl": equity - INITIAL_CAPITAL - realized,
        "pnl": equity - INITIAL_CAPITAL,
        "pnl_pct": ((equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100.0,
        "buy_and_hold_equity": bh,
        "buy_and_hold_pnl": (bh - INITIAL_CAPITAL) if bh is not None else None,
        "per_asset": per_asset,
    }


def buy_and_hold_value(state: dict, prices: dict[str, float]) -> float | None:
    bh = state.get("buy_and_hold") or {}
    if not bh.get("filled"):
        return None
    total = 0.0
    for symbol, pos in bh.get("positions", {}).items():
        price = prices.get(symbol)
        if price is None:
            return None
        total += float(pos["qty"]) * price + float(pos.get("cash_residual") or 0.0)
    return total


def init_buy_and_hold(state: dict, prices: dict[str, float], when: str) -> None:
    """Achète une fois le panier égal pour la comparaison « acheter et garder »."""
    if state["buy_and_hold"].get("filled"):
        return
    positions = {}
    for symbol in UNIVERSE:
        price = prices[symbol]
        fee = ALLOCATION * FEE_RATE
        spent_on_asset = ALLOCATION - fee
        qty = spent_on_asset / price
        positions[symbol] = {
            "entry_price": price,
            "qty": qty,
            "fee": fee,
            "cash_residual": 0.0,
        }
    state["buy_and_hold"] = {
        "filled": True,
        "entry_time": when,
        "positions": positions,
        "note": (
            "Panier équipondéré de 1 000 $ fictifs par crypto, acheté au premier run "
            "au prix de clôture de la dernière bougie 1h, sans frais, puis conservé."
        ),
    }


# --- Ordres fictifs ------------------------------------------------------------

def apply_buy(state: dict, symbol: str, price: float, reason: str, when: str) -> dict:
    asset = state["assets"][symbol]
    cash = float(asset["cash"])
    if cash <= 0 or float(asset["qty"]) > 0:
        return {}
    fee = cash * FEE_RATE
    spent = cash - fee
    qty = spent / price
    asset["cash"] = 0.0
    asset["qty"] = qty
    asset["entry_price"] = price
    asset["entry_time"] = when
    asset["entry_fee"] = fee
    trade = {
        "id": len(state["trades"]) + 1,
        "time": when,
        "symbol": symbol,
        "side": "BUY",
        "price": price,
        "qty": qty,
        "fee": fee,
        "notional": spent,
        "cash_after": 0.0,
        "qty_after": qty,
        "reason": reason,
        "equity_after": None,
    }
    state["trades"].append(trade)
    return trade


def apply_sell(state: dict, symbol: str, price: float, reason: str, when: str) -> dict:
    asset = state["assets"][symbol]
    qty = float(asset["qty"])
    if qty <= 0:
        return {}
    notional = qty * price
    fee = notional * FEE_RATE
    proceeds = notional - fee
    # Coût réel de *cette* position (qty d'entrée × prix d'entrée).
    # On n'utilise pas ALLOCATION : dès le 2e aller-retour, le cash
    # réinvesti n'est plus forcément égal à l'enveloppe initiale de 1 000 $.
    # Les frais sont à 0 %, donc cost_basis == cash mobilisé à l'achat.
    entry_price = asset.get("entry_price")
    if entry_price is None:
        raise RuntimeError(f"Vente {symbol} sans prix d'entrée (état incohérent)")
    cost_basis = qty * float(entry_price)
    pnl = proceeds - cost_basis
    asset["realized_pnl"] = float(asset.get("realized_pnl") or 0.0) + pnl
    asset["cash"] = proceeds
    asset["qty"] = 0.0
    asset["entry_price"] = None
    asset["entry_time"] = None
    asset["entry_fee"] = 0.0
    trade = {
        "id": len(state["trades"]) + 1,
        "time": when,
        "symbol": symbol,
        "side": "SELL",
        "price": price,
        "qty": qty,
        "fee": fee,
        "notional": notional,
        "cash_after": proceeds,
        "qty_after": 0.0,
        "reason": reason,
        "equity_after": None,
    }
    state["trades"].append(trade)
    return trade


def already_processed(state: dict, klines_by_symbol: dict[str, list[dict]]) -> bool:
    candle_ms = last_closed_open_ms(klines_by_symbol)
    return (
        candle_ms is not None
        and state.get("last_processed_candle_open_ms") == candle_ms
    )


def decide_and_trade(state: dict, klines_by_symbol: dict[str, list[dict]]) -> list[dict]:
    """Applique la stratégie sur la dernière bougie close, une seule fois par bougie."""
    prices = last_closes(klines_by_symbol)
    candle_ms = last_closed_open_ms(klines_by_symbol)
    sample = next(iter(klines_by_symbol.values()))
    close_dt = ms_to_paris(sample[-1]["close_time_ms"])
    when = fmt_paris(close_dt)

    if state.get("last_processed_candle_open_ms") == candle_ms:
        return []

    if state.get("started_at") is None:
        start = now_paris()
        state["started_at"] = fmt_paris(start)
        state["ends_at"] = fmt_paris(start + timedelta(days=RUN_DAYS))

    init_buy_and_hold(state, prices, when)

    new_trades: list[dict] = []
    signals: dict[str, dict] = {}
    for symbol in UNIVERSE:
        candles = klines_by_symbol.get(symbol)
        if not candles:
            continue
        price = candles[-1]["close"]
        signal = last_signal([c["close"] for c in candles])
        signals[symbol] = {
            "ema_fast": signal["ema_fast"],
            "ema_slow": signal["ema_slow"],
            "bullish": signal["bullish"],
            "bearish": signal["bearish"],
            "crossover": signal["crossover"],
            "crossunder": signal["crossunder"],
            "close": price,
        }
        asset = state["assets"][symbol]
        in_pos = float(asset["qty"]) > 0

        if not in_pos and signal["bullish"]:
            if signal["crossover"]:
                reason = "Croisement haussier EMA20 au-dessus de EMA50"
            else:
                reason = (
                    "Tendance déjà haussière (EMA20 > EMA50) — entrée autorisée "
                    "même sans attendre un nouveau croisement"
                )
            trade = apply_buy(state, symbol, price, reason, when)
            if trade:
                new_trades.append(trade)
        elif in_pos and signal["bearish"]:
            if signal["crossunder"]:
                reason = "Croisement baissier EMA20 au-dessous de EMA50"
            else:
                reason = "Tendance devenue baissière (EMA20 < EMA50)"
            trade = apply_sell(state, symbol, price, reason, when)
            if trade:
                new_trades.append(trade)

    snap = portfolio_snapshot(state, prices)
    for trade in new_trades:
        trade["equity_after"] = snap["equity"]

    state["last_processed_candle_open_ms"] = candle_ms
    state["last_processed_candle_close_paris"] = when
    state["last_run_at"] = fmt_paris()
    state["last_prices"] = prices
    state["last_signals"] = signals
    state["equity_history"].append(
        {
            "time": when,
            "candle_open_ms": candle_ms,
            "equity": snap["equity"],
            "buy_and_hold_equity": snap["buy_and_hold_equity"],
            "cash_total": snap["cash_total"],
            "positions_value": snap["positions_value"],
            "unrealized_pnl": snap["unrealized_pnl"],
            "realized_pnl": snap["realized_pnl"],
        }
    )
    return new_trades


def run_ended(state: dict) -> bool:
    ends = state.get("ends_at")
    if not ends:
        return False
    try:
        end_dt = datetime.fromisoformat(ends)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=PARIS)
        return now_paris() >= end_dt
    except ValueError:
        return False


def seconds_until_next_close(buffer: int = CANDLE_CLOSE_BUFFER_SEC) -> float:
    now = time.time()
    next_close = (int(now) // 3600 + 1) * 3600
    return max(1.0, next_close + buffer - now)
