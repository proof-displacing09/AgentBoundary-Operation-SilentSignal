#!/usr/bin/env bash
# AgentBoundary free local-model setup (FA-09).
#
# Installs nothing by default: checks for an Ollama binary, checks RAM
# and disk, pulls a tool-calling-capable open-weight model, and smoke
# tests Ollama's OpenAI-compatible endpoint on LOOPBACK ONLY
# (http://127.0.0.1:11434/v1). Ollama binds loopback by default; this
# script refuses to proceed if OLLAMA_HOST is set to a non-loopback
# address, and never exposes the lab or the model to the network.
#
# Usage:
#   scripts/local-llm-setup.sh [model-tag]
# Default model: qwen2.5:3b (needs ~8 GB RAM free-ish; see docs).
# Smaller fallback for tight machines: qwen2.5:1.5b (~2 GB).
# Larger option for 16 GB+ machines: qwen2.5:7b (~5-6 GB).
#
# After a successful run, export (in the shell that starts the backend):
#   export AGENTBOUNDARY_LLM_LOCAL_OLLAMA=1
#   export AGENTBOUNDARY_LLM_BASE_URL="http://127.0.0.1:11434/v1"
#   export AGENTBOUNDARY_LLM_MODEL="<tag>"
#   # NO API key is needed or used for loopback Ollama.
# Then: cd backend && python -m agentboundary.cli run-real --scenario A1
set -euo pipefail

MODEL="${1:-qwen2.5:3b}"
OLLAMA_HOST_VALUE="${OLLAMA_HOST:-}"

if [ -n "$OLLAMA_HOST_VALUE" ]; then
  case "$OLLAMA_HOST_VALUE" in
    127.0.0.1*|localhost*|\[::1\]*)
      echo "OLLAMA_HOST is loopback: $OLLAMA_HOST_VALUE"
      ;;
    *)
      echo "REFUSED: OLLAMA_HOST is not loopback ($OLLAMA_HOST_VALUE)." >&2
      echo "AgentBoundary local models must stay on 127.0.0.1. Unset OLLAMA_HOST and retry." >&2
      exit 2
      ;;
  esac
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Install it from https://ollama.com/download" >&2
  echo "then re-run this script. (The installer is a third-party script;" >&2
  echo "review it before running, as with any install script.)" >&2
  exit 2
fi

MEM_GB=$(free -g | awk '/^Mem:/ {print $2}')
echo "RAM total: ${MEM_GB} GB"
case "$MODEL" in
  *":7b"*|*":8b"*)
    [ "$MEM_GB" -ge 16 ] || echo "WARNING: $MODEL usually wants 16 GB+ RAM; expect slow or failed inference below that."
    ;;
  *":3b"*)
    [ "$MEM_GB" -ge 8 ] || echo "WARNING: $MODEL usually wants ~8 GB RAM; consider qwen2.5:1.5b on this machine."
    ;;
  *":1.5b"*)
    [ "$MEM_GB" -ge 4 ] || echo "WARNING: $MODEL usually wants ~4 GB RAM."
    ;;
esac

DISK_AVAIL=$(df -BG . | awk 'NR==2 {print $4}' | tr -dc '0-9')
echo "Disk available here: ${DISK_AVAIL} GB (model download is ~1-5 GB depending on tag)"

if ! curl -s -m 3 http://127.0.0.1:11434/api/tags >/dev/null; then
  echo "Ollama server is not running on loopback. Start it with: ollama serve"
  echo "(it binds 127.0.0.1:11434 by default) and re-run this script."
  exit 2
fi

echo "Pulling model: $MODEL"
ollama pull "$MODEL"
echo "Installed models:"
ollama list

echo "Smoke test: OpenAI-compatible chat completion on loopback..."
curl -s -m 60 http://127.0.0.1:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{\"model\": \"$MODEL\", \"messages\": [{\"role\": \"user\", \"content\": \"Reply with exactly: ok\"}]}" \
  | head -c 400
echo
echo
echo "Local model ready. Export (backend shell):"
echo "  export AGENTBOUNDARY_LLM_LOCAL_OLLAMA=1"
echo "  export AGENTBOUNDARY_LLM_BASE_URL=\"http://127.0.0.1:11434/v1\""
echo "  export AGENTBOUNDARY_LLM_MODEL=\"$MODEL\""
