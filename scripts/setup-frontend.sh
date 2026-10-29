#!/usr/bin/env bash
# AgentBoundary frontend setup: clean, reproducible install from package-lock.json.
# Safe to re-run; never touches the backend or demo database.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"
npm ci
echo "Frontend ready: $ROOT/frontend/node_modules"
node --version
npm --version
