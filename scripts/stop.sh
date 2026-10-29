#!/usr/bin/env bash
# Stop servers started by scripts/start.sh. Never deletes the demo database.
set -uo pipefail
PID_FILE="/tmp/agentboundary/agentboundary.pid"
if [ ! -f "$PID_FILE" ]; then
  echo "Not running via scripts/start.sh (no $PID_FILE)."
  exit 0
fi
read -r BACK_PID FRONT_PID <"$PID_FILE"
kill "$BACK_PID" "$FRONT_PID" 2>/dev/null || true
sleep 2
kill -9 "$BACK_PID" "$FRONT_PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "Stopped (backend pid $BACK_PID, frontend pid $FRONT_PID)."
