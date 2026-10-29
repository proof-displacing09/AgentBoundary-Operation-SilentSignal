#!/usr/bin/env bash
# Start AgentBoundary locally: backend (uvicorn) + frontend (Vite dev server),
# both bound to 127.0.0.1 ONLY. Nothing here is public or cloud-facing.
#
#   scripts/start.sh          start both servers in the background
#   scripts/stop.sh           stop them again
#
# PID file + logs live under /tmp/agentboundary/ (ephemeral by design; the
# demo DATABASE lives in backend/data/agentboundary.db and is NOT touched by
# start/stop — a normal restart preserves runs, events and case state).
# If you prefer auto-restart across reboots, see scripts/install-systemd.sh
# (note: /etc/systemd units are wiped when this VM is replaced; reinstalling
# them is one command — see README "Startup & hosting caveat").
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="/tmp/agentboundary"
PID_FILE="$RUN_DIR/agentboundary.pid"
mkdir -p "$RUN_DIR"

if [ -f "$PID_FILE" ]; then
  if kill -0 "$(cut -d' ' -f1 "$PID_FILE")" 2>/dev/null; then
    echo "Already running (see $PID_FILE). Run scripts/stop.sh first."
    exit 1
  fi
  rm -f "$PID_FILE"
fi

# Refuse to shadow a systemd-managed instance on the same ports.
if curl -fsS -o /dev/null http://127.0.0.1:8000/api/v1/health 2>/dev/null; then
  echo "ERROR: something already serves http://127.0.0.1:8000 (systemd unit?)."
  echo "Stop it first (systemctl stop agentboundary-backend agentboundary-frontend) or use scripts/stop.sh."
  exit 1
fi

if [ ! -x "$ROOT/backend/.venv/bin/uvicorn" ]; then
  echo "Backend venv missing. Run scripts/setup-backend.sh first."
  exit 1
fi
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "Frontend node_modules missing. Run scripts/setup-frontend.sh first."
  exit 1
fi

cd "$ROOT/backend"
nohup "$ROOT/backend/.venv/bin/uvicorn" agentboundary.api.app:app \
  --host 127.0.0.1 --port 8000 >"$RUN_DIR/backend.log" 2>&1 &
BACK_PID=$!
cd "$ROOT/frontend"
nohup npm run dev -- --host 127.0.0.1 --port 5173 >"$RUN_DIR/frontend.log" 2>&1 &
FRONT_PID=$!
echo "$BACK_PID $FRONT_PID" >"$PID_FILE"

# Wait for both to answer (backend health, frontend page).
for i in $(seq 1 30); do
  curl -fsS -o /dev/null http://127.0.0.1:8000/api/v1/health 2>/dev/null && break
  sleep 1
done
for i in $(seq 1 30); do
  curl -fsS -o /dev/null http://127.0.0.1:5173/ 2>/dev/null && break
  sleep 1
done
echo "Backend:  http://127.0.0.1:8000 (pid $BACK_PID, log $RUN_DIR/backend.log)"
echo "Frontend: http://127.0.0.1:5173 (pid $FRONT_PID, log $RUN_DIR/frontend.log)"
curl -fsS http://127.0.0.1:8000/api/v1/health; echo
curl -fsS -o /dev/null -w "Frontend HTTP %{http_code}\n" http://127.0.0.1:5173/
