#!/bin/bash
# Petit serveur local pour consulter le tableau de bord.
# Usage : ./serve.sh [port]     (défaut 8765)
#         ./serve.sh stop
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
DIR="$ROOT/dashboard"
PID_FILE="$ROOT/dashboard-server.pid"
PORT="${1:-8765}"

if [ "${1:-}" = "stop" ]; then
  if [ -f "$PID_FILE" ]; then
    pid="$(cat "$PID_FILE")"
    kill "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "Serveur du tableau de bord arrêté (PID $pid)."
  else
    echo "Aucun serveur de tableau de bord n'est lancé."
  fi
  exit 0
fi

mkdir -p "$DIR"
if [ ! -f "$DIR/index.html" ]; then
  echo "Pas encore de tableau de bord. Lance d'abord : $ROOT/venv/bin/python $ROOT/bot.py --once"
  exit 1
fi

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Déjà en cours (PID $(cat "$PID_FILE")) : http://127.0.0.1:$PORT/"
  exit 0
fi

cd "$DIR"
# --bind 127.0.0.1 : consultation locale sur la machine du bot uniquement
nohup "$ROOT/venv/bin/python" -m http.server "$PORT" --bind 127.0.0.1 \
  >> "$ROOT/logs/dashboard-server.log" 2>&1 &
echo $! > "$PID_FILE"
echo "Tableau de bord disponible sur http://127.0.0.1:$PORT/"
echo "Fichier : $DIR/index.html"
echo "Arrêt    : $ROOT/serve.sh stop"
