# -*- coding: utf-8 -*-
"""Génère le tableau de bord HTML autonome (sans CDN, un seul fichier)."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from common import (
    INITIAL_CAPITAL,
    ROOT,
    UNIVERSE,
    fmt_paris,
)

DASHBOARD_DIR = ROOT / "dashboard"
DASHBOARD_HTML = DASHBOARD_DIR / "index.html"
DOCS_DIR = ROOT / "docs"
DOCS_HTML = DOCS_DIR / "index.html"


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _money(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "n/d"
    text = f"{value:+,.2f}" if signed else f"{value:,.2f}"
    return text.replace(",", " ") + " $"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/d"
    return f"{value:+.2f} %"


def _tone(value: float | None) -> str:
    if value is None:
        return "neutral"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "neutral"


def _svg_chart(history: list[dict], width: int = 920, height: int = 340) -> str:
    """Courbe d'equity en SVG, sans bibliothèque externe."""
    pad_l, pad_r, pad_t, pad_b = 64, 20, 20, 52
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    rows = []
    for row in history or []:
        try:
            dt = datetime.fromisoformat(str(row["time"]))
            eq = float(row["equity"])
        except (TypeError, ValueError, KeyError):
            continue
        bh = row.get("buy_and_hold_equity")
        try:
            bh_v = float(bh) if bh is not None else None
        except (TypeError, ValueError):
            bh_v = None
        rows.append((dt, eq, bh_v))

    if not rows:
        return (
            f'<svg viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="Pas encore d\'historique">'
            f'<rect x="0" y="0" width="{width}" height="{height}" rx="12" fill="#f4f6f8"/>'
            f'<text x="{width/2}" y="{height/2}" text-anchor="middle" '
            f'fill="#5c6770" font-size="15" font-family="system-ui,sans-serif">'
            f"Pas encore d'historique — le bot n'a fait aucun cycle.</text></svg>"
        )

    ys = [INITIAL_CAPITAL] + [r[1] for r in rows] + [r[2] for r in rows if r[2] is not None]
    y_min, y_max = min(ys), max(ys)
    if y_max - y_min < 1:
        y_min -= 5
        y_max += 5
    margin = (y_max - y_min) * 0.12
    y_min -= margin
    y_max += margin

    def x_at(i: int) -> float:
        if len(rows) == 1:
            return pad_l + plot_w / 2
        return pad_l + (i / (len(rows) - 1)) * plot_w

    def y_at(val: float) -> float:
        return pad_t + (y_max - val) / (y_max - y_min) * plot_h

    def path_for(getter) -> str:
        pts = []
        for i, row in enumerate(rows):
            val = getter(row)
            if val is None:
                continue
            pts.append(f"{'M' if not pts else 'L'}{x_at(i):.1f},{y_at(val):.1f}")
        return " ".join(pts)

    # Grille horizontale (4 lignes)
    grid = []
    labels = []
    for i in range(5):
        val = y_min + (y_max - y_min) * i / 4
        y = y_at(val)
        grid.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width-pad_r}" y2="{y:.1f}" '
            f'stroke="#e4e8ec" stroke-width="1"/>'
        )
        labels.append(
            f'<text x="{pad_l-10}" y="{y:.1f}" text-anchor="end" dominant-baseline="middle" '
            f'fill="#5c6770" font-size="11" font-family="system-ui,sans-serif">'
            f"{val:,.0f}".replace(",", " ")
            + "</text>"
        )

    # Quelques dates en abscisse
    tick_idx = list(range(len(rows)))
    if len(rows) > 6:
        step = max(1, (len(rows) - 1) // 5)
        tick_idx = list(range(0, len(rows), step))
        if tick_idx[-1] != len(rows) - 1:
            tick_idx.append(len(rows) - 1)
    xlabels = []
    for i in tick_idx:
        dt = rows[i][0]
        y = height - 18
        xlabels.append(
            f'<text x="{x_at(i):.1f}" y="{y}" text-anchor="middle" '
            f'fill="#5c6770" font-size="11" font-family="system-ui,sans-serif">'
            f'{_esc(dt.strftime("%d/%m %Hh"))}</text>'
        )

    y0 = y_at(INITIAL_CAPITAL)
    baseline = (
        f'<line x1="{pad_l}" y1="{y0:.1f}" x2="{width-pad_r}" y2="{y0:.1f}" '
        f'stroke="#8b95a0" stroke-width="1.2" stroke-dasharray="5 4"/>'
    )
    bot_path = path_for(lambda r: r[1])
    bh_path = path_for(lambda r: r[2])

    dots = []
    for i, row in enumerate(rows):
        dots.append(
            f'<circle cx="{x_at(i):.1f}" cy="{y_at(row[1]):.1f}" r="3.2" fill="#1f6feb"/>'
        )

    legend = (
        f'<g font-family="system-ui,sans-serif" font-size="12">'
        f'<line x1="{pad_l}" y1="{height-6}" x2="{pad_l+22}" y2="{height-6}" '
        f'stroke="#1f6feb" stroke-width="2.5"/>'
        f'<text x="{pad_l+28}" y="{height-2}" fill="#1a2330">Bot (EMA 20/50)</text>'
        f'<line x1="{pad_l+160}" y1="{height-6}" x2="{pad_l+182}" y2="{height-6}" '
        f'stroke="#bc4c00" stroke-width="2.5" stroke-dasharray="6 4"/>'
        f'<text x="{pad_l+188}" y="{height-2}" fill="#1a2330">Buy &amp; hold du même panier</text>'
        f'<line x1="{pad_l+400}" y1="{height-6}" x2="{pad_l+422}" y2="{height-6}" '
        f'stroke="#8b95a0" stroke-width="1.2" stroke-dasharray="5 4"/>'
        f'<text x="{pad_l+428}" y="{height-2}" fill="#1a2330">Capital de départ (10 000 $)</text>'
        f"</g>"
    )

    bh_line = (
        f'<path d="{_esc(bh_path)}" fill="none" stroke="#bc4c00" '
        f'stroke-width="2.2" stroke-dasharray="7 5"/>'
        if bh_path
        else ""
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Courbe du capital fictif du bot vs buy-and-hold">'
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="12" fill="#ffffff"/>'
        + "".join(grid)
        + baseline
        + "".join(labels)
        + bh_line
        + f'<path d="{_esc(bot_path)}" fill="none" stroke="#1f6feb" stroke-width="2.5"/>'
        + "".join(dots)
        + "".join(xlabels)
        + legend
        + "</svg>"
    )


def generate_dashboard(state: dict, snap: dict) -> Path:
    """Écrit un HTML autonome dans /workspace/paper-bot/dashboard/index.html."""
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    pnl = snap.get("pnl")
    pnl_pct = snap.get("pnl_pct")
    equity = snap.get("equity")
    bh = snap.get("buy_and_hold_equity")
    bh_pnl = snap.get("buy_and_hold_pnl")
    vs_bh = (equity - bh) if (equity is not None and bh is not None) else None
    trades = state.get("trades") or []
    per_asset = snap.get("per_asset") or {}

    pos_rows = []
    for symbol in UNIVERSE:
        a = per_asset.get(symbol) or {}
        in_pos = bool(a.get("in_position"))
        status = "En position" if in_pos else "Cash"
        price = f"{a['price']:.6f}" if a.get("price") is not None else "n/d"
        qty = f"{a['qty']:.8f}" if in_pos else "—"
        entry = ""
        if in_pos and a.get("entry_price") is not None:
            entry = (
                f"Entrée {a['entry_price']:.6f}"
                + (f" le {_esc(a.get('entry_time') or '—')}" if a.get("entry_time") else "")
            )
        tone = _tone(a.get("pnl"))
        pos_rows.append(
            "<tr>"
            f"<td><strong>{_esc(symbol)}</strong></td>"
            f"<td><span class='pill {('open' if in_pos else 'flat')}'>{status}</span></td>"
            f"<td class='num'>{_esc(price)}</td>"
            f"<td class='num'>{_esc(qty)}</td>"
            f"<td class='num'>{_esc(_money(a.get('equity')))}</td>"
            f"<td class='num {_tone(a.get('pnl'))}'>{_esc(_money(a.get('pnl'), signed=True))}</td>"
            f"<td class='num {tone}'>{_esc(_pct(a.get('pnl_pct')))}</td>"
            f"<td class='muted'>{entry}</td>"
            "</tr>"
        )

    trade_rows = []
    if not trades:
        trade_rows.append(
            "<tr><td colspan='6' class='muted'>Aucun trade pour l'instant.</td></tr>"
        )
    else:
        for t in reversed(trades):
            side = t.get("side") or ""
            side_cls = "up" if side == "BUY" else "down"
            price_s = f"{float(t['price']):.6f}" if t.get("price") is not None else "n/d"
            qty_s = f"{float(t['qty']):.8f}" if t.get("qty") is not None else "n/d"
            trade_rows.append(
                "<tr>"
                f"<td class='num'>{_esc(t.get('id'))}</td>"
                f"<td>{_esc(t.get('time'))}</td>"
                f"<td><span class='pill {side_cls}'>{_esc(side)}</span></td>"
                f"<td><strong>{_esc(t.get('symbol'))}</strong></td>"
                f"<td class='num'>{_esc(price_s)}</td>"
                f"<td class='num'>{_esc(qty_s)}</td>"
                f"</tr><tr class='reason'><td></td><td colspan='5'>{_esc(t.get('reason') or '')}</td></tr>"
            )

    open_count = sum(1 for s in UNIVERSE if (per_asset.get(s) or {}).get("in_position"))
    chart = _svg_chart(state.get("equity_history") or [])

    page = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta http-equiv="refresh" content="60"/>
  <title>Paper bot — suivi fictif</title>
  <style>
    :root {{
      --bg: #f3f5f7;
      --card: #ffffff;
      --ink: #1a2330;
      --muted: #5c6770;
      --line: #e4e8ec;
      --blue: #1f6feb;
      --up: #0a7a3e;
      --up-bg: #e7f7ee;
      --down: #b42318;
      --down-bg: #fdecea;
      --warn: #8a5a00;
      --warn-bg: #fff6e0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.45;
    }}
    header {{
      background: var(--ink);
      color: #fff;
      padding: 22px 24px 20px;
    }}
    header h1 {{
      margin: 0 0 6px;
      font-size: 1.45rem;
      font-weight: 650;
    }}
    header p {{ margin: 0; color: #c9d1d9; font-size: 0.95rem; }}
    .banner {{
      background: var(--warn-bg);
      color: var(--warn);
      padding: 10px 24px;
      font-size: 0.92rem;
      border-bottom: 1px solid #f0e0b0;
    }}
    main {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 22px 18px 48px;
    }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 16px 16px 14px;
      box-shadow: 0 1px 2px rgba(16,24,40,.04);
    }}
    .card h2 {{
      margin: 0 0 12px;
      font-size: 0.95rem;
      font-weight: 650;
    }}
    .label {{
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: .04em;
      color: var(--muted);
      margin: 0 0 4px;
    }}
    .value {{ font-size: 1.45rem; font-weight: 700; margin: 0; }}
    .sub {{ margin: 4px 0 0; color: var(--muted); font-size: 0.88rem; }}
    .up {{ color: var(--up); }}
    .down {{ color: var(--down); }}
    .neutral {{ color: var(--ink); }}
    .pill {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 0.8rem;
      font-weight: 600;
      background: #eef1f4;
    }}
    .pill.open, .pill.up {{ background: var(--up-bg); color: var(--up); }}
    .pill.flat {{ background: #eef1f4; color: var(--muted); }}
    .pill.down {{ background: var(--down-bg); color: var(--down); }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }}
    th, td {{
      text-align: left;
      padding: 8px 8px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: .03em;
      color: var(--muted);
      font-weight: 650;
    }}
    td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    tr.reason td {{
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 0.82rem;
      padding-top: 0;
      padding-bottom: 10px;
    }}
    .muted {{ color: var(--muted); }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 8px 24px;
      font-size: 0.9rem;
    }}
    .meta dt {{ color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: .03em; }}
    .meta dd {{ margin: 0 0 8px; }}
    footer {{
      margin-top: 22px;
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .chart-wrap {{ overflow-x: auto; }}
  </style>
</head>
<body>
  <header>
    <h1>Paper bot — suivi du capital fictif</h1>
    <p>Stratégie {_esc(state.get("strategy") or "EMA 20/50, bougies 1h, long only")} · dernière bougie {_esc(state.get("last_processed_candle_close_paris") or state.get("last_run_at") or fmt_paris())} (Europe/Paris)</p>
  </header>
  <div class="banner">
    Argent 100 % fictif — aucun compte, aucun ordre réel, aucune clé API.
    Ceci n'est pas un conseil en investissement.
  </div>
  <main>
    <section class="kpis">
      <div class="card">
        <p class="label">Capital actuel</p>
        <p class="value">{_esc(_money(equity))}</p>
        <p class="sub">sur {_esc(_money(INITIAL_CAPITAL))} de départ</p>
      </div>
      <div class="card">
        <p class="label">P&amp;L du bot</p>
        <p class="value {_tone(pnl)}">{_esc(_money(pnl, signed=True))}</p>
        <p class="sub {_tone(pnl_pct)}">{_esc(_pct(pnl_pct))}</p>
      </div>
      <div class="card">
        <p class="label">Buy &amp; hold (même panier)</p>
        <p class="value">{_esc(_money(bh))}</p>
        <p class="sub {_tone(bh_pnl)}">{_esc(_money(bh_pnl, signed=True))} depuis le départ</p>
      </div>
      <div class="card">
        <p class="label">Bot vs buy &amp; hold</p>
        <p class="value {_tone(vs_bh)}">{_esc(_money(vs_bh, signed=True))}</p>
        <p class="sub">{open_count} position(s) ouverte(s) · {len(trades)} trade(s)</p>
      </div>
    </section>

    <section class="card" style="margin-bottom:18px">
      <h2>Évolution du capital vs buy-and-hold</h2>
      <div class="chart-wrap">{chart}</div>
    </section>

    <section class="card" style="margin-bottom:18px">
      <h2>Positions par crypto (1 000 $ fictifs chacun)</h2>
      <div style="overflow-x:auto">
        <table>
          <thead>
            <tr>
              <th>Symbole</th>
              <th>Statut</th>
              <th class="num">Prix</th>
              <th class="num">Quantité</th>
              <th class="num">Valeur</th>
              <th class="num">P&amp;L $</th>
              <th class="num">P&amp;L %</th>
              <th>Détail</th>
            </tr>
          </thead>
          <tbody>
            {"".join(pos_rows)}
          </tbody>
        </table>
      </div>
    </section>

    <section class="card" style="margin-bottom:18px">
      <h2>Historique des trades ({len(trades)})</h2>
      <div style="overflow-x:auto">
        <table>
          <thead>
            <tr>
              <th class="num">Id</th>
              <th>Date (Europe/Paris)</th>
              <th>Côté</th>
              <th>Symbole</th>
              <th class="num">Prix</th>
              <th class="num">Quantité</th>
            </tr>
          </thead>
          <tbody>
            {"".join(trade_rows)}
          </tbody>
        </table>
      </div>
    </section>

    <section class="card">
      <h2>Paramètres</h2>
      <dl class="meta">
        <div>
          <dt>Démarrage</dt>
          <dd>{_esc(state.get("started_at") or "—")}</dd>
        </div>
        <div>
          <dt>Fin prévue (7 jours)</dt>
          <dd>{_esc(state.get("ends_at") or "—")}</dd>
        </div>
        <div>
          <dt>Dernière bougie traitée</dt>
          <dd>{_esc(state.get("last_processed_candle_close_paris") or "—")}</dd>
        </div>
        <div>
          <dt>Dernier passage du bot</dt>
          <dd>{_esc(state.get("last_run_at") or "—")}</dd>
        </div>
        <div>
          <dt>Source des prix</dt>
          <dd>{_esc(state.get("data_source") or "—")}</dd>
        </div>
        <div>
          <dt>Frais</dt>
          <dd>Sans frais, sans effet de levier</dd>
        </div>
      </dl>
      <p class="muted" style="margin:8px 0 0">{_esc(state.get("strategy_doc") or "")}</p>
      <p class="muted" style="margin:8px 0 0">{_esc(state.get("data_source_note") or "")}</p>
    </section>

    <footer>
      Fichier généré automatiquement après chaque cycle horaire du bot.
      Cette page se rafraîchit toute seule toutes les 60 secondes si elle est ouverte dans un navigateur.
      Les chiffres sont figés jusqu'au prochain cycle (clôture d'une bougie 1h).
    </footer>
  </main>
</body>
</html>
"""
    for dest in (DASHBOARD_HTML, DOCS_HTML):
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".html.tmp")
        tmp.write_text(page, encoding="utf-8")
        tmp.replace(dest)
        if dest.parent.name == "docs":
            nojekyll = dest.parent / ".nojekyll"
            if not nojekyll.exists():
                nojekyll.write_text("", encoding="utf-8")
    return DASHBOARD_HTML


if __name__ == "__main__":
    from common import fetch_all_closed_klines, last_closes, load_state, portfolio_snapshot, STATE_PATH

    if not STATE_PATH.exists():
        raise SystemExit("Aucun état. Lance d'abord : python bot.py --once")
    state = load_state()
    try:
        prices = last_closes(fetch_all_closed_klines())
    except Exception:
        prices = state.get("last_prices") or {}
    path = generate_dashboard(state, portfolio_snapshot(state, prices))
    print(path)
