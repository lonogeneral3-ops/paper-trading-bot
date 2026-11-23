#!/bin/bash
# Arrête le bot (et le superviseur) proprement.
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$ROOT/data"
touch "$ROOT/data/STOP"

stop_pid() {
  local file="$1"
  local label="$2"
  if [ -f "$file" ]; then
    local pid
    pid="$(cat "$file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
      echo "Signal TERM envoyé à $label (PID $pid)."
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.3
      done
      if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
        echo "$label (PID $pid) forcé à l'arrêt."
      fi
    else
      echo "$label : processus $pid déjà arrêté."
    fi
    rm -f "$file"
  fi
}

# Tuer le superviseur d'abord pour qu'il ne relance pas, puis le bot.
stop_pid "$ROOT/supervisor.pid" "superviseur"
stop_pid "$ROOT/bot.pid" "bot"
echo "Bot arrêté."
