import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


def db_path() -> str:
    return os.environ.get(
        "AGENTBOUNDARY_DB_PATH", str(BACKEND_DIR / "data" / "agentboundary.db")
    )


HOST = os.environ.get("AGENTBOUNDARY_HOST", "127.0.0.1")  # localhost by default
PORT = int(os.environ.get("AGENTBOUNDARY_PORT", "8000"))
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
UNSAFE_ENV = "AGENTBOUNDARY_UNSAFE_LAB"

# Real-LLM adapter configuration (server-side environment only).
# These are NAMES only; values — especially AGENTBOUNDARY_LLM_API_KEY —
# must never be logged, returned by any API, or stored in runs/events.
LLM_BASE_URL_ENV = "AGENTBOUNDARY_LLM_BASE_URL"
LLM_MODEL_ENV = "AGENTBOUNDARY_LLM_MODEL"
LLM_API_KEY_ENV = "AGENTBOUNDARY_LLM_API_KEY"
LLM_TEMPERATURE_ENV = "AGENTBOUNDARY_LLM_TEMPERATURE"
# FA-09: explicit opt-in for a free LOCAL model via Ollama's
# OpenAI-compatible endpoint (loopback only, no paid key). Setting this
# to "1" is a trust choice: loopback HTTP is allowed and no API key is
# required — but ONLY when the base URL host is loopback (see
# llm_adapter.is_local_ollama_mode). Never set for a remote host.
LLM_LOCAL_OLLAMA_ENV = "AGENTBOUNDARY_LLM_LOCAL_OLLAMA"
LLM_DEFAULT_BASE_URL = "https://api.openai.com/v1"
LLM_DEFAULT_MODEL = "gpt-4o-mini"  # a default only, not a claim it was used
