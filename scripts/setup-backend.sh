#!/usr/bin/env bash
# AgentBoundary backend setup: create venv (if missing) and install the pinned
# stack + the package itself (editable, so `uvicorn agentboundary.api.app:app`
# resolves from backend/src). Safe to re-run; never touches the demo database.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

if [ ! -x .venv/bin/python ]; then
  echo "Creating backend/.venv ..."
  python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt
# Register the package itself (editable, no extra deps beyond requirements.txt).
.venv/bin/pip install -e . --no-deps -q
echo "Backend ready: $ROOT/backend/.venv"
.venv/bin/python --version
.venv/bin/python -m pytest --version 2>/dev/null | head -1
