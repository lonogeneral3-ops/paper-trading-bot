# Paper bot — trading fictif

Bot de paper trading qui suit une stratégie simple sur des cryptos, des actions et des
indices boursiers, avec des **enveloppes fictives de 1 000 € par actif** (19 actifs = 19 000 € fictifs).
Le rendement en % de chaque actif (coté en $ ou en €) est appliqué à son enveloppe en euros, **sans conversion de change**.
Au départ tout est en cash : le bot n'achète que sur un **nouveau** signal d'achat de sa stratégie.

**Argent 100 % fictif. Aucun compte, aucune clé API, aucun ordre réel.
Ceci n'est pas un conseil en investissement.**

- Tableau de bord : <https://lonogeneral3-ops.github.io/paper-trading-bot/>
  (le même que le fichier local `mon-dashboard-trading.html`)
- Compte GitHub utilisé : `lonogeneral3-ops`

## Fonctionnement

Le bot tourne chaque heure via GitHub Actions (`Paper trading bot`, cron `7 * * * *`,
plus lancement manuel). Chaque passage traite les bougies 1h **terminées** pas encore vues,
au prix de clôture, puis enregistre `data/state.json`, `data/trades.csv`, `data/equity.csv`.
L'expérience dure 7 jours à partir de `started_at` (voir `data/state.json`) ; ensuite plus aucun trade.
L'expérience précédente (23 → 24 novembre 2026, en $ et avec achats immédiats) est archivée dans
`data/archive/run-2026-11-23/`. Recommencer à zéro : `python reset_run.py --archive <nom>`.

- Cryptos (BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, DOT) : Binance.US
  (repli Binance, puis Kraken), 24 h/24.
- Actions (Apple, Nvidia, Microsoft, Tesla, LVMH, TotalEnergies) et indices
  (S&P 500 `^GSPC`, Nasdaq 100 `^NDX`, CAC 40 `^FCHI`) : Yahoo Finance, API publique
  « chart ». Il n'y a des bougies que pendant les heures de Bourse : aucun trade la nuit
  ni le week-end. Les indices sont simulés comme s'ils s'achetaient directement.
- Le bot publie aussi `data/market/*.json` (historique Yahoo, toutes les 6 h) pour le
  testeur de stratégies du tableau de bord, car Yahoo ne se lit pas depuis un fichier local.

## Réglages : `config.json`

- `strategy` : stratégie globale (`id` + `params`).
- `assets` : liste des actifs (ajouter une ligne = nouvelle enveloppe fictive, qui commence
  à trader à la bougie suivante). `strategy` d'un actif = exception pour cet actif.

## Changer de stratégie (sans code)

Depuis le tableau de bord : bouton « 🔀 Changer la stratégie » (une clé GitHub « fine-grained »
limitée à ce dépôt, permission Actions : Read and write, est demandée une seule fois).
Ou sur GitHub :

Onglet **Actions** → **Changer de stratégie** → **Run workflow**, choisir la stratégie,
l'actif (« tous » ou un seul) et éventuellement les réglages, puis **Run workflow**.
Lien direct : <https://github.com/lonogeneral3-ops/paper-trading-bot/actions/workflows/change-strategy.yml>

Rien n'est effacé : les positions sont gardées, le changement est noté dans
`data/state.json` (`strategy_changes`), et les nouvelles règles s'appliquent aux bougies
qui se terminent après le changement.

## Stratégies (`strategies.py`, mêmes règles que le testeur du tableau de bord)

| id | Nom | Réglages par défaut | Règle |
|---|---|---|---|
| `ema` | Croisement EMA | rapide=20 lente=50 | achète au croisement haussier (EMA rapide repasse au-dessus de la lente), vend quand elle repasse dessous |
| `rsi` | RSI | periode=14 bas=30 haut=70 | achète quand le RSI passe sous « bas », vend si RSI > haut |
| `boll` | Cassure de Bollinger | periode=20 ecart=2 | achète quand le prix passe au-dessus de la bande haute, vend si prix < moyenne |
| `macd` | MACD | rapide=12 lente=26 signal=9 | achète quand le MACD repasse au-dessus du signal, vend s'il est dessous |
| `dca` | Achat régulier | n=7 | n achats égaux du cash restant, répartis jusqu'à la fin, jamais de vente |
| `bh` | Acheter et garder | — | achète tout le cash au premier passage, ne revend jamais |

Sans frais (0 %). Positions longues uniquement, sans effet de levier.
