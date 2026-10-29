#!/usr/bin/env bash
# Install the AgentBoundary systemd units (auto-restart, localhost only).
# EPHEMERAL BY DESIGN: /etc/systemd/system is wiped when this VM is replaced,
# so these units do NOT survive a VM replacement. That is a hosting caveat,
# not an app defect: re-running this one script restores them, and the demo
# database (backend/data/agentboundary.db) survives independently.
# Requires root (or sudo) because it writes /etc/systemd/system.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NPM_BIN="$(command -v npm)"
if [ "$(id -u)" -ne 0 ]; then
  echo "Re-run as root or via sudo: sudo $0"
  exit 1
fi
sed -e "s#__ROOT__#$ROOT#g" "$ROOT/scripts/dev-systemd/agentboundary-backend.service" \
  > /etc/systemd/system/agentboundary-backend.service
sed -e "s#__ROOT__#$ROOT#g" -e "s#__NPM__#$NPM_BIN#g" \
  "$ROOT/scripts/dev-systemd/agentboundary-frontend.service" \
  > /etc/systemd/system/agentboundary-frontend.service
systemctl daemon-reload
systemctl enable --now agentboundary-backend agentboundary-frontend
sleep 3
systemctl is-active agentboundary-backend agentboundary-frontend
echo "Installed. Restore after a VM replacement with: sudo $ROOT/scripts/install-systemd.sh"
