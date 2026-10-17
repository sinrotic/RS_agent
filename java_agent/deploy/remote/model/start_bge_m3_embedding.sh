#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/bge_m3_embedding.pid"
LOG_FILE="$SCRIPT_DIR/bge_m3_embedding.log"

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
  if kill -0 "$pid" 2>/dev/null; then
    echo "bge-m3 embedding runtime already running: pid=$pid"
    exit 0
  fi
fi

nohup "$SCRIPT_DIR/run_bge_m3_embedding.sh" > "$LOG_FILE" 2>&1 < /dev/null &
pid=$!
printf '%s\n' "$pid" > "$PID_FILE"
echo "bge-m3 embedding runtime starting: pid=$pid log=$LOG_FILE"
