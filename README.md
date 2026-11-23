# Paper bot — trading fictif

Bot de paper trading qui suit, pendant une semaine, une stratégie simple
(EMA 20/50 sur bougies d'une heure) sur 10 cryptos, avec 10 000 $ fictifs.

**Argent 100 % fictif. Aucun compte, aucune clé API, aucun ordre réel.
Ceci n'est pas un conseil en investissement.**

- Tableau de bord public (GitHub Pages) :
  <https://lonogeneral3-ops.github.io/paper-trading-bot/>
- Dépôt : <https://github.com/lonogeneral3-ops/paper-trading-bot>
- Compte GitHub utilisé : `lonogeneral3-ops`

Le bot tourne chaque heure via GitHub Actions (cron `7 * * * *`, plus lancement manuel).
Chaque cycle rattrape les bougies 1h closes pas encore traitées, met à jour l'état
et republie le tableau de bord. Après le 30 novembre 2026 à 22:40 (Europe/Paris),
plus aucun trade n'est passé.

## Stratégie

- Univers : BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, DOT (contre USDT)
- 1 000 $ fictifs par crypto, sans effet de levier
- Sans frais (0 % à l'achat comme à la vente)
- Achat si EMA 20 > EMA 50 (même si la tendance est déjà haussière, pas seulement
  sur un nouveau croisement)
- Vente si EMA 20 < EMA 50
- Décision à la clôture de chaque bougie 1h, au prix de clôture
- Début : 23 novembre 2026, 22:40 (Europe/Paris)
- Fin : 30 novembre 2026, 22:40 (Europe/Paris)

## Données de marché

Source principale : `https://api.binance.us/api/v3/klines` (publique, sans authentification).

Si cette API est bloquée (HTTP 451 / restriction géographique), le bot essaie dans l'ordre :

1. `https://api.binance.com/api/v3/klines`
2. `https://api.kraken.com/0/public/OHLC` (intervalle 60 minutes, toutes les paires de l'univers y compris BNB et DOGE/XDG)

Aucune clé n'est stockée dans ce dépôt.

## Fichiers d'état

- `data/state.json` — positions, cash, historique (reprise après un run manqué)
- `data/trades.csv` et `data/equity.csv`
- `dashboard/index.html` et `docs/index.html` — tableau de bord statique autonome
- `equity.png` — courbe du capital

## Commandes locales (optionnel)

```bash
./venv/bin/python bot.py --once   # un cycle, avec rattrapage
./venv/bin/python report.py       # rapport + graphique
./start.sh / ./stop.sh / ./restart.sh
./serve.sh                        # http://127.0.0.1:8765/
```
