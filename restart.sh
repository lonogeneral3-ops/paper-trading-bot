#!/bin/bash
# Redémarre le bot en reprenant l'état disque (positions, trades, historique).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
"$ROOT/stop.sh"
sleep 0.5
rm -f "$ROOT/data/STOP"
"$ROOT/start.sh"
