# Paper bot — trading fictif

Bot de paper trading qui suit une stratégie simple sur des cryptos, des actions et des
indices boursiers, avec des **enveloppes fictives de 1 000 $ par actif**.

**Argent 100 % fictif. Aucun compte, aucune clé API, aucun ordre réel.
Ceci n'est pas un conseil en investissement.**

- Tableau de bord : <https://lonogeneral3-ops.github.io/paper-trading-bot/>
  (le même que le fichier local `mon-dashboard-trading.html`)
- Compte GitHub utilisé : `lonogeneral3-ops`

## Fonctionnement

Le bot tourne chaque heure via GitHub Actions (`Paper trading bot`, cron `7 * * * *`,
plus lancement manuel). Chaque passage traite les bougies 1h **terminées** pas encore vues,
au prix de clôture, puis enregistre `data/state.json`, `data/trades.csv`, `data/equity.csv`.
Après le 30 novembre 2026 à 22:40 (heure de Paris), plus aucun trade n'est passé.

- Cryptos (BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, DOT) : Binance.US
  (repli Binance, puis Kraken), 24 h/24.
- Actions (Apple, Nvidia, Microsoft, Tesla, LVMH, TotalEnergies) et indices
  (S&P 500 `^GSPC`, Nasdaq 100 `^NDX`, CAC 40 `^FCHI`) : Yahoo Finance, API publique
  « chart ». Il n'y a des bougies que pendant les heures de Bourse : aucun trade la nuit
  ni le week-end. Les indices sont simulés comme s'ils s'achetaient directement.
  Les cours en € font varier l'enveloppe de 1 000 $ du même pourcentage (sans change).
- Le bot publie aussi `data/market/*.json` (historique Yahoo, toutes les 6 h) pour le
  testeur de stratégies du tableau de bord, car Yahoo ne se lit pas depuis un fichier local.

## Réglages : `config.json`

- `strategy` : stratégie globale (`id` + `params`).
- `assets` : liste des actifs (ajouter une ligne = nouvelle enveloppe fictive, qui commence
  à trader à la bougie suivante). `strategy` d'un actif = exception pour cet actif.

## Changer de stratégie (sans code)

Onglet **Actions** → **Changer de stratégie** → **Run workflow**, choisir la stratégie,
l'actif (« tous » ou un seul) et éventuellement les réglages, puis **Run workflow**.
Lien direct : <https://github.com/lonogeneral3-ops/paper-trading-bot/actions/workflows/change-strategy.yml>

Rien n'est effacé : les positions sont gardées, le changement est noté dans
`data/state.json` (`strategy_changes`), et les nouvelles règles s'appliquent aux bougies
qui se terminent après le changement.

## Stratégies (`strategies.py`, mêmes règles que le testeur du tableau de bord)

| id | Nom | Réglages par défaut | Règle |
|---|---|---|---|
| `ema` | Croisement EMA | rapide=20 lente=50 | investi tant que EMA rapide > EMA lente, vend quand elle passe dessous |
| `rsi` | RSI | periode=14 bas=30 haut=70 | achète si RSI < bas, vend si RSI > haut |
| `boll` | Cassure de Bollinger | periode=20 ecart=2 | achète si prix > bande haute, vend si prix < moyenne |
| `macd` | MACD | rapide=12 lente=26 signal=9 | investi si MACD > signal, vend sinon |
| `dca` | Achat régulier | n=7 | n achats égaux du cash restant, répartis jusqu'à la fin, jamais de vente |
| `bh` | Acheter et garder | — | achète tout le cash, ne revend jamais |

Sans frais (0 %). Positions longues uniquement, sans effet de levier.
