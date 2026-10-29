"""Optional real-LLM adapter (OpenAI-compatible chat completions, tool calling).

Backend-only. Configuration comes ONLY from server-side environment variables
(see backend/.env.example for names). The API key is held in memory for the
outgoing Authorization header and is NEVER logged, returned by any API,
stored in events/DB/reports, or echoed in error messages. Only the host part
of the base URL and the model name are ever reported.

`llm_configured()` is the single source of truth for "a real model is
available": it is True only when a non-empty key, model, and base URL are
all set. The API layer gates POST /runs {"adapter": "real_llm"} on it.
"""

import os
import time
from urllib.parse import urlparse

import httpx

from ..config import (
    LLM_API_KEY_ENV,
    LLM_BASE_URL_ENV,
    LLM_DEFAULT_BASE_URL,
    LLM_DEFAULT_MODEL,
    LLM_LOCAL_OLLAMA_ENV,
    LLM_MODEL_ENV,
    LLM_TEMPERATURE_ENV,
)
from ..tools.dispatcher import SCHEMAS

TOOL_DESCRIPTIONS = {
    "get_alert": "Read a synthetic alert by id (tenant-scoped).",
    "search_runbooks": "Search synthetic runbooks (pre-filtered to caller tenant scope).",
    "read_case": "Read a synthetic case by id (tenant-scoped).",
    "draft_response": "Save a local, unsent synthetic draft response for a case.",
    "change_case_status": "Change a synthetic case status; sensitive statuses need an exact-match approval.",
    "simulate_isolation": "Record a SIMULATED synthetic isolation; requires an exact-match approval.",
}


def llm_base_url():
    return os.environ.get(LLM_BASE_URL_ENV) or LLM_DEFAULT_BASE_URL


def llm_model_name():
    return os.environ.get(LLM_MODEL_ENV) or LLM_DEFAULT_MODEL


def llm_temperature():
    try:
        return float(os.environ.get(LLM_TEMPERATURE_ENV) or 0.0)
    except ValueError:
        return 0.0


def llm_base_url_host():
    """Host only — never a full URL, which could carry credentials."""
    parsed = urlparse(llm_base_url())
    return parsed.hostname or ""


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
LOOPBACK_HTTP_OPT_IN_ENV = "AGENTBOUNDARY_LLM_ALLOW_LOOPBACK_HTTP"


def is_local_ollama_mode(base_url=None):
    """FA-09: True only when the user explicitly opted into a local
    model AND the base URL is loopback. This is the ONLY configuration
    in which a missing API key is acceptable — Ollama on localhost
    needs no paid secret — and it can never apply to a remote host,
    so a key can never be silently dropped for a cloud provider."""
    if os.environ.get(LLM_LOCAL_OLLAMA_ENV) != "1":
        return False
    parsed = urlparse(base_url or llm_base_url())
    return (parsed.hostname or "").lower() in LOOPBACK_HOSTS


def validate_provider_url(base_url):
    """TLS policy for provider connections (R-14).

    Returns None when the URL is acceptable, else a short reason string.
    Remote hosts REQUIRE https (a bearer token must never travel over
    plaintext HTTP, and redirects are never followed — httpx defaults
    follow_redirects=False). Plain http is allowed ONLY for a loopback
    local model AND only with explicit opt-in env, so a misconfigured
    default can never silently leak a key.
    """
    parsed = urlparse(base_url or "")
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        return "invalid_provider_url"
    if scheme == "https":
        return None
    if host in LOOPBACK_HOSTS and (
        os.environ.get(LOOPBACK_HTTP_OPT_IN_ENV) == "1"
        or is_local_ollama_mode(base_url)
    ):
        return None
    return "insecure_provider_url"


def llm_configured():
    """True when a real model is available: either (remote) key +
    model + base URL with a passing TLS policy, or (FA-09 local) the
    local-Ollama opt-in + loopback URL + model, with no key required.
    """
    if validate_provider_url(llm_base_url()) is not None:
        return False
    if not llm_model_name().strip() or not llm_base_url().strip():
        return False
    if is_local_ollama_mode():
        return True
    return bool((os.environ.get(LLM_API_KEY_ENV) or "").strip())


def llm_public_settings():
    """Safe-to-report settings: host only, model name, temperature,
    provider kind. No key, ever."""
    configured = llm_configured()
    url_error = validate_provider_url(llm_base_url())
    return {
        "real_model_configured": configured,
        "real_llm_model": llm_model_name() if configured else None,
        "real_llm_base_url_host": llm_base_url_host() if configured else None,
        "real_llm_provider_kind": (
            "local_ollama" if is_local_ollama_mode() else "remote"
        ),
        # Why a configured-looking setup is still unavailable (TLS policy
        # or missing fields) — a reason code, never key material.
        "real_llm_config_error": (
            None if configured else (url_error or "not_configured")
        ),
    }


def tool_specs():
    """OpenAI-compatible function specs from the dispatcher's strict schemas.

    The dispatcher re-validates every returned call with the same pydantic
    models, so the spec and the enforcement can never drift apart.
    """
    specs = []
    for name, model in SCHEMAS.items():
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": TOOL_DESCRIPTIONS[name],
                    "parameters": model.model_json_schema(),
                },
            }
        )
    return specs


class LLMError(Exception):
    """Provider failure, sanitized: only a short error class is ever recorded.

    The raw provider body is never stored or echoed — it could contain
    request echoes or provider internals. `error_class` is one of:
    not_configured, insecure_provider_url, invalid_provider_url,
    rate_limited, timeout, provider_error, transport_error.
    """

    def __init__(self, error_class, detail=""):
        super().__init__(error_class)
        self.error_class = error_class
        self.detail = detail


class LLMClient:
    """Minimal OpenAI-compatible chat-completions client over httpx.

    `transport` exists for tests (httpx.MockTransport); production uses a
    plain httpx.Client. No retries except at most one retry on HTTP 429
    with a short backoff — never a retry storm.
    """

    def __init__(
        self,
        base_url=None,
        model=None,
        api_key=None,
        temperature=None,
        timeout=30.0,
        transport=None,
        max_429_retries=1,
        backoff_seconds=0.2,
    ):
        self.base_url = (base_url or llm_base_url()).rstrip("/")
        # R-14: fail fast on an insecure/invalid provider URL, before any
        # request (and therefore before any key) can be sent.
        url_error = validate_provider_url(self.base_url)
        if url_error is not None:
            raise LLMError(url_error, f"Provider URL rejected: {url_error}.")
        self.model = model or llm_model_name()
        self.api_key = (
            api_key if api_key is not None else os.environ.get(LLM_API_KEY_ENV, "")
        )
        self.temperature = llm_temperature() if temperature is None else temperature
        self.timeout = timeout
        self.transport = transport
        self.max_429_retries = max_429_retries
        self.backoff_seconds = backoff_seconds

    @classmethod
    def from_env(cls, **kwargs):
        if not llm_configured():
            raise LLMError(
                "not_configured",
                "Real LLM evaluation is not configured (missing key, model, or base URL).",
            )
        return cls(**kwargs)

    def public_settings(self):
        return {
            "provider_base_url_host": urlparse(self.base_url).hostname or "",
            "model": self.model,
            "temperature": self.temperature,
            "provider_kind": (
                "local_ollama" if is_local_ollama_mode(self.base_url) else "remote"
            ),
            # R-10: transport kind is what separates a mocked protocol
            # validation from a verified live provider trial in reports.
            "transport": (
                "mocked_protocol" if self.transport is not None else "live_provider"
            ),
        }

    def complete(self, messages, tools):
        """One chat-completions call. Returns {"tool_calls": [...], "content": ...}.

        Each tool_call is {"id": str, "name": str, "arguments": str,
        "provider_call_id": str} with the raw arguments string preserved
        for the caller to parse/validate. "id" is the effective protocol
        id (nonempty, unique within the response — see S7-06);
        "provider_call_id" is the provider's raw id (possibly empty).
        Raises LLMError (never leaks key material or raw bodies).
        """
        # FA-09: a local Ollama endpoint needs no key at all — send NO
        # Authorization header rather than a fake secret. Any other
        # keyless configuration is still refused (never silently
        # downgrade a remote provider to anonymous).
        local_mode = is_local_ollama_mode(self.base_url)
        if not (self.api_key or "").strip() and not local_mode:
            raise LLMError("not_configured", "No API key configured.")
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": self.temperature,
        }
        headers = {"Content-Type": "application/json"}
        # SI-03: in validated local Ollama mode the Authorization header
        # is NEVER sent, even when a leftover remote key sits in the
        # environment — the old unconditional send contradicted the
        # FA-09 "no key, no header" promise and leaked key material to
        # localhost. Remote providers keep their bearer header.
        if (self.api_key or "").strip() and not local_mode:
            headers["Authorization"] = f"Bearer {self.api_key}"
        attempts = 0
        while True:
            attempts += 1
            try:
                # Loopback providers must never go through a proxy: this
                # sandbox's NO_PROXY list (bracketed IPv6 entries) makes
                # httpx's own proxy-env parsing raise InvalidURL before
                # any request is sent, which would strand every local
                # trial as transport_error. trust_env=False for loopback
                # only; remote providers keep the user's proxy settings.
                loopback = (
                    urlparse(self.base_url).hostname or ""
                ).lower() in LOOPBACK_HOSTS
                with httpx.Client(
                    transport=self.transport,
                    timeout=self.timeout,
                    trust_env=not loopback,
                ) as client:
                    resp = client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
            except httpx.TimeoutException:
                raise LLMError("timeout", "Provider request timed out.")
            except httpx.HTTPError:
                raise LLMError("transport_error", "Provider request failed.")
            if resp.status_code == 429 and attempts <= self.max_429_retries:
                time.sleep(self.backoff_seconds)
                continue
            if resp.status_code == 429:
                raise LLMError("rate_limited", "Provider rate limit (HTTP 429).")
            if resp.status_code >= 400:
                raise LLMError("provider_error", f"Provider HTTP {resp.status_code}.")
            # F3 (pentest follow-up): only HTTP 200 is a model response.
            # The old code accepted any non-error status, so a 301/302/
            # 303/307 (or 201) carrying a valid choices body was treated
            # as a response. Redirects are never followed, so such a
            # body comes from the configured host itself -- negligible
            # impact -- but a strict adapter rejects it explicitly.
            if resp.status_code != 200:
                raise LLMError("provider_error", f"Provider HTTP {resp.status_code}.")
            # R-07: strict provider-response validation. A malformed
            # payload (wrong types, missing message, tool_calls not a
            # list, non-object entries, non-string arguments) is a typed
            # provider_error, never an unhandled AttributeError/TypeError
            # that could strand a run in "running".
            try:
                data = resp.json()
            except ValueError:
                raise LLMError(
                    "provider_error",
                    "Provider response was not valid JSON.",
                )
            if not isinstance(data, dict):
                raise LLMError("provider_error", "Provider response was not an object.")
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                raise LLMError("provider_error", "Provider returned no choices.")
            first = choices[0]
            if not isinstance(first, dict):
                raise LLMError("provider_error", "Provider choice was not an object.")
            message = first.get("message")
            if not isinstance(message, dict):
                raise LLMError("provider_error", "Provider message was not an object.")
            raw_calls = message.get("tool_calls")
            if raw_calls is not None and not isinstance(raw_calls, list):
                raise LLMError("provider_error", "Provider tool_calls was not a list.")
            tool_calls = []
            for tc in raw_calls or []:
                if not isinstance(tc, dict):
                    raise LLMError(
                        "provider_error", "Provider tool call was not an object."
                    )
                fn = tc.get("function")
                if not isinstance(fn, dict):
                    raise LLMError(
                        "provider_error", "Provider tool call had no function object."
                    )
                name = fn.get("name")
                arguments = fn.get("arguments")
                if not isinstance(name, str) or not isinstance(arguments, str):
                    raise LLMError(
                        "provider_error",
                        "Provider tool call had invalid name/arguments types.",
                    )
                call_id = tc.get("id")
                if call_id is not None and not isinstance(call_id, str):
                    raise LLMError(
                        "provider_error", "Provider tool call id was not a string."
                    )
                # S7-06: OpenAI-compatible backends vary in tool-call id
                # behavior — missing ids arrived as "" and duplicates
                # passed through, which stricter backends reject in later
                # message histories. Mint a stable nonempty effective id
                # per response (unique within this response; the caller
                # de-duplicates across turns) and preserve the provider's
                # raw id separately for correlation. The raw id is never
                # trusted for protocol correctness.
                raw_id = call_id if isinstance(call_id, str) else ""
                effective = raw_id
                if not effective or any(c["id"] == effective for c in tool_calls):
                    n = 1
                    while (
                        f"local-call-{n}" in [c["id"] for c in tool_calls]
                        or f"local-call-{n}" == raw_id
                    ):
                        n += 1
                    effective = f"local-call-{n}"
                tool_calls.append(
                    {
                        "id": effective,
                        "name": name,
                        "arguments": arguments,
                        "provider_call_id": raw_id,
                    }
                )
            content = message.get("content")
            if content is not None and not isinstance(content, str):
                raise LLMError("provider_error", "Provider content was not a string.")
            return {
                "tool_calls": tool_calls,
                "content": content,
                "model": data.get("model") or self.model,
            }
