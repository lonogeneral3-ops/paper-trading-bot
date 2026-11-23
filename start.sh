#!/bin/bash
# Démarre le bot de paper trading (boucle 7 jours, redémarrage auto en cas de crash).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
mkdir -p logs data dashboard
PYTHON="$ROOT/venv/bin/python"
PID_FILE="$ROOT/supervisor.pid"
BOT_PID="$ROOT/bot.pid"
STOP_FLAG="$ROOT/data/STOP"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Le bot tourne déjà (superviseur PID $(cat "$PID_FILE"))."
  exit 0
fi
if [ -f "$BOT_PID" ] && kill -0 "$(cat "$BOT_PID")" 2>/dev/null; then
  echo "Le bot tourne déjà (PID $(cat "$BOT_PID"))."
  exit 0
fi

rm -f "$STOP_FLAG"
export PYTHONUNBUFFERED=1

# Superviseur : relance le bot s'il plante, sauf arrêt volontaire (code 0 ou fichier STOP).
nohup bash -c "
  while true; do
    date \"+%Y-%m-%dT%H:%M:%S%z  superviseur : lancement de bot.py\" >> \"$ROOT/logs/supervisor.log\"
    \"$PYTHON\" \"$ROOT/bot.py\"
    code=\$?
    if [ -f \"$STOP_FLAG\" ]; then
      echo \"\$(date '+%Y-%m-%dT%H:%M:%S%z')  STOP demandé, pas de relance (code \$code).\" >> \"$ROOT/logs/supervisor.log\"
      break
    fi
    if [ \$code -eq 0 ]; then
      echo \"\$(date '+%Y-%m-%dT%H:%M:%S%z')  Arrêt normal (fin des 7 jours ou signal).\" >> \"$ROOT/logs/supervisor.log\"
      break
    fi
    echo \"\$(date '+%Y-%m-%dT%H:%M:%S%z')  Sortie code \$code, relance dans 15 s.\" >> \"$ROOT/logs/supervisor.log\"
    sleep 15
  done
" >> "$ROOT/logs/supervisor.log" 2>&1 &

echo $! > "$PID_FILE"
# Laisser bot.py écrire bot.pid
sleep 0.4
echo "Bot démarré."
echo "  Superviseur PID : $(cat "$PID_FILE")"
if [ -f "$BOT_PID" ]; then
  echo "  Bot PID         : $(cat "$BOT_PID")"
fi
echo "  Journaux        : $ROOT/logs/bot.log"
echo "  Tableau de bord : $ROOT/dashboard/index.html"
