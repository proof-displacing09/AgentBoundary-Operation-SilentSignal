"""Eighth independent audit regressions (E8-01..E8-03).

Every test reproduces an audit repro (or the closest honest equivalent)
and asserts the FIXED behavior. Mocked/stub provider traffic only; no
network, no real credentials, no live provider calls. All stores are
disposable tmp databases; the demo DB is never touched.
"""

import http.server
import json
import socketserver
import threading
import time

from agentboundary.evaluation.runner import Runner
from agentboundary.store import Store

OPEN_PROPOSAL = {
    "id": "chatcmpl-stub",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-0",
                        "type": "function",
                        "function": {
                            "name": "change_case_status",
                            "arguments": json.dumps(
                                {
                                    "case_id": "INC-2048",
                                    "new_status": "open",
                                    "reason": "post-reset probe",
                                }
                            ),
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "model": "stub-model",
}


class _BarrierStub:
    """HTTP provider stub. Each request signals entry, waits for release,
    then returns a gateway-allowed open proposal (or HTTP 500 in error
    mode). Threading server: concurrent worker requests are independent."""

    def __init__(self, mode="barrier"):
        self.mode = mode
        self.request_started = threading.Event()
        self.release = threading.Event()
        self._active = 0
        self._active_lock = threading.Lock()
        self._store_baseline = Store._live_count

        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                with outer._active_lock:
                    outer._active += 1
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    self.rfile.read(length)
                    if outer.mode == "error500":
                        self.send_response(500)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    outer.request_started.set()
                    outer.release.wait(timeout=30)
                    body = json.dumps(OPEN_PROPOSAL).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                finally:
                    with outer._active_lock:
                        outer._active -= 1

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def shutdown(self):
        # Release blocked workers first, then wait for in-flight
        # handlers to drain so worker threads (and their Stores) close
        # before the test's lifecycle guard runs.
        self.release.set()
        deadline = time.time() + 5
        while time.time() < deadline:
            with self._active_lock:
                if self._active == 0:
                    break
            time.sleep(0.05)
        # Workers finalize (and close their Stores) just after their
        # provider call returns; wait for that before teardown.
        deadline = time.time() + 5
        while time.time() < deadline:
            if Store._live_count <= self._store_baseline:
                break
            time.sleep(0.05)
        self.server.shutdown()
        self.server.server_close()


def _llm_env(monkeypatch, stub, cap=None):
    monkeypatch.setenv("AGENTBOUNDARY_LLM_LOCAL_OLLAMA", "1")
    monkeypatch.setenv("AGENTBOUNDARY_LLM_BASE_URL", f"http://127.0.0.1:{stub.port}/v1")
    monkeypatch.setenv("AGENTBOUNDARY_LLM_MODEL", "e8-stub")
    monkeypatch.delenv("AGENTBOUNDARY_LLM_API_KEY", raising=False)
    if cap is not None:
        monkeypatch.setenv("AGENTBOUNDARY_MAX_CONCURRENT_REAL_RUNS", str(cap))


def _api_client(tmp_path, name="api.db"):
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    store = Store(str(tmp_path / name))
    client = TestClient(create_app(store=store))
    return store, client


def _close_store(store):
    try:
        store.close()
    except Exception:  # noqa: BLE001, S110 - test teardown is best-effort
        pass


def _session_header(client, persona_id="incident_commander"):
    r = client.post("/api/v1/lab/session", json={"persona_id": persona_id})
    assert r.status_code == 200, r.text
    return {"X-Lab-Session": r.json()["session_token"]}


def _orphan_event_count(store):
    row = store.one(
        "SELECT COUNT(*) AS n FROM events WHERE run_id NOT IN (SELECT id FROM runs)"
    )
    return row["n"]


def _poll_terminal(client, headers, run_id, timeout=30):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        got = client.get(f"/api/v1/runs/{run_id}", headers=headers)
        assert got.status_code == 200, got.text
        last = got.json()
        if last["status"] in ("completed", "error", "cancelled", "inconclusive"):
            break
        time.sleep(0.2)
    else:
        raise AssertionError(f"run {run_id} never reached terminal state: {last}")
    # The worker's finally (registry pop + its own Store close) runs
    # just after the terminal row commit; wait for it so the FA-07
    # lifecycle guard sees a quiescent process at teardown.
    deadline = time.time() + 5
    while time.time() < deadline:
        if Store._live_count <= 1:
            break
        time.sleep(0.05)
    return last


# ---------------- E8-01: reset must not race active jobs ----------------


def test_e801_reset_blocked_while_real_job_active(tmp_path, monkeypatch):
    """E8-01 repro: a real A1 job blocked mid-provider-request; an admin
    global reset must be refused (409) with the run and data intact —
    never a 200 that lets the worker mutate a freshly reset DB and
    orphan its events."""
    stub = _BarrierStub()
    try:
        _llm_env(monkeypatch, stub)
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client)
                r = client.post(
                    "/api/v1/runs",
                    headers=h,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r.status_code == 202, r.text
                run_id = r.json()["id"]
                assert stub.request_started.wait(timeout=15), (
                    "worker never reached provider"
                )
                reset = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
                assert reset.status_code == 409, reset.text
                assert reset.json()["error"]["code"] == "RESET_BLOCKED_ACTIVE_RUNS"
                assert reset.json()["error"]["details"]["active_runs"] >= 1
                # Nothing was deleted by the refused reset.
                assert store.one("SELECT * FROM runs WHERE id=?", (run_id,)) is not None
                assert store.get_case("INC-2048")["status"] == "investigating"
                # Release the worker: its (pre-reset, legitimate) open
                # proposal now commits against the UNRESET database.
                stub.release.set()
                final = _poll_terminal(client, h, run_id)
                assert final["status"] in ("completed", "inconclusive", "error")
                assert store.one("SELECT * FROM runs WHERE id=?", (run_id,)) is not None
                assert _orphan_event_count(store) == 0
                assert store.get_case("INC-2048")["status"] == "open"
        finally:
            _close_store(store)
    finally:
        stub.shutdown()


def test_e801_two_simultaneous_launches_then_reset_blocked(tmp_path, monkeypatch):
    """E8-01 with two active jobs: the reset refusal must count both,
    and both jobs must survive intact."""
    stub = _BarrierStub()
    try:
        _llm_env(monkeypatch, stub)
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client)
                ids = []
                for _ in range(2):
                    r = client.post(
                        "/api/v1/runs",
                        headers=h,
                        json={"scenario_id": "A1", "adapter": "real_llm"},
                    )
                    assert r.status_code == 202, r.text
                    ids.append(r.json()["id"])
                assert stub.request_started.wait(timeout=15)
                # Both workers are inside the provider call by now: the
                # stub handles requests on separate threads, and each
                # POST returned only after its worker thread started.
                reset = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
                assert reset.status_code == 409, reset.text
                assert reset.json()["error"]["details"]["active_runs"] == 2
                stub.release.set()
                for run_id in ids:
                    _poll_terminal(client, h, run_id)
                assert len(store.all("SELECT * FROM runs")) == 2
                assert _orphan_event_count(store) == 0
        finally:
            _close_store(store)
    finally:
        stub.shutdown()


def test_e801_reset_succeeds_when_quiescent_with_backup(tmp_path, monkeypatch):
    """Healthy admin reset (no active jobs) still works, restores the
    fixtures, preserves the admin session, and leaves a backup."""
    stub = _BarrierStub()
    try:
        _llm_env(monkeypatch, stub)
        store, client = _api_client(tmp_path)
        db_path = str(tmp_path / "api.db")
        try:
            with client:
                h = _session_header(client)
                r = client.post("/api/v1/runs", headers=h, json={"scenario_id": "A1"})
                assert r.status_code == 200, r.text
                store.execute("UPDATE cases SET status='closed' WHERE id='INC-2048'")
                reset = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
                assert reset.status_code == 200, reset.text
                assert reset.json()["reset"] is True
                assert reset.json().get("backup") is not None
                assert store.all("SELECT * FROM runs") == []
                assert store.get_case("INC-2048")["status"] == "investigating"
                assert client.get("/api/v1/lab/identity", headers=h).status_code == 200
            import glob
            import os

            assert glob.glob(db_path + ".pre-reset-*.bak"), "no backup file left"
            assert os.path.getsize(glob.glob(db_path + ".pre-reset-*.bak")[0]) > 0
        finally:
            _close_store(store)
    finally:
        stub.shutdown()


def test_e801_reset_after_cancel_succeeds(tmp_path, monkeypatch):
    """A cancelled job is terminal, so a subsequent reset is allowed."""
    stub = _BarrierStub()
    try:
        _llm_env(monkeypatch, stub)
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client)
                r = client.post(
                    "/api/v1/runs",
                    headers=h,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r.status_code == 202, r.text
                run_id = r.json()["id"]
                assert stub.request_started.wait(timeout=15)
                cancel = client.post(f"/api/v1/runs/{run_id}/cancel", headers=h)
                assert cancel.status_code == 200, cancel.text
                stub.release.set()
                final = _poll_terminal(client, h, run_id)
                assert final["status"] == "cancelled"
                reset = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
                assert reset.status_code == 200, reset.text
                assert store.all("SELECT * FROM runs") == []
        finally:
            _close_store(store)
    finally:
        stub.shutdown()


def test_e801_reset_after_worker_failure_succeeds(tmp_path, monkeypatch):
    """A worker that fails (provider 500) finalizes as ERROR and pops
    its registry entry, so a later reset is allowed and no stranded
    job blocks it."""
    stub = _BarrierStub(mode="error500")
    try:
        _llm_env(monkeypatch, stub)
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client)
                r = client.post(
                    "/api/v1/runs",
                    headers=h,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r.status_code == 202, r.text
                run_id = r.json()["id"]
                final = _poll_terminal(client, h, run_id)
                assert final["status"] == "error"
                reset = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
                assert reset.status_code == 200, reset.text
        finally:
            _close_store(store)
    finally:
        stub.shutdown()


def test_e801_reset_auth_matrix(tmp_path, monkeypatch):
    """Reset authorization is unchanged by the barrier: non-admin 403,
    missing session 401, and neither deletes anything."""
    stub = _BarrierStub()
    try:
        _llm_env(monkeypatch, stub)
        store, client = _api_client(tmp_path)
        try:
            with client:
                h_admin = _session_header(client)
                r = client.post(
                    "/api/v1/runs", headers=h_admin, json={"scenario_id": "A1"}
                )
                assert r.status_code == 200, r.text
                run_id = r.json()["id"]
                h_analyst = _session_header(client, "analyst_northstar")
                denied = client.post(
                    "/api/v1/lab/reset", headers=h_analyst, json={"confirm": True}
                )
                assert denied.status_code == 403
                anon = client.post("/api/v1/lab/reset", json={"confirm": True})
                assert anon.status_code == 401
                assert store.one("SELECT * FROM runs WHERE id=?", (run_id,)) is not None
        finally:
            _close_store(store)
    finally:
        stub.shutdown()


def test_e801_cli_reset_refused_while_server_holds_db(tmp_path, monkeypatch):
    """CLI/manual reset against a server-held DB must be refused, not
    silently bypass the interlock; without a server it succeeds."""
    from agentboundary.cli import main as cli_main

    stub = _BarrierStub()
    try:
        _llm_env(monkeypatch, stub)
        db_path = str(tmp_path / "api.db")
        monkeypatch.setenv("AGENTBOUNDARY_DB_PATH", db_path)
        store, client = _api_client(tmp_path)
        try:
            with client:
                # Lifespan holds the cross-process lock on this DB.
                assert cli_main(["reset"]) == 2
                assert store.all("SELECT * FROM runs") == []
                assert store.record_count() == 48
        finally:
            _close_store(store)
        # No server anymore: the same CLI reset now succeeds.
        assert cli_main(["reset"]) == 0
    finally:
        stub.shutdown()


# ---------------- E8-02: comparison must not discard eligible pairs ----------------


def _comparisons_setup(tmp_path, monkeypatch):
    """Protected scripted A2 run + tmp example-reports dir holding the
    repo's real weak-A2 export. Returns (store, client, headers, prot)."""
    import shutil
    from pathlib import Path

    from fastapi.testclient import TestClient

    import agentboundary.api.app as app_module
    from agentboundary.api.app import create_app

    store = Store(str(tmp_path / "lab.db"))
    prot = Runner(store).run("A2")
    rep_dir = tmp_path / "example-reports"
    rep_dir.mkdir()
    shutil.copy(
        Path(__file__).resolve().parents[3] / "example-reports" / "weak-A2.json",
        rep_dir / "weak-A2.json",
    )
    monkeypatch.setattr(app_module, "PROJECT_DIR", tmp_path)
    client = TestClient(create_app(store=store))
    return store, client, prot


def _insert_run_row(store, run_id, scenario_id, adapter, variant, policy, started_at):
    store.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            scenario_id,
            "completed",
            "INCONCLUSIVE",
            adapter,
            "protected",
            started_at,
            started_at,
            json.dumps({"policy_version": policy}),
            "analyst_northstar",
            "tenant_northstar",
            "[]",
            "incident_commander",
            "analyst_northstar",
            None,
            "1.0.0",
            variant,
        ),
    )


def test_e802_newer_real_run_does_not_mask_scripted_pair(tmp_path, monkeypatch):
    """E8-02 repro: protected scripted A2 (matching weak export) + a
    NEWER real_llm A2 row must still yield the scripted pair."""
    store, client, prot = _comparisons_setup(tmp_path, monkeypatch)
    try:
        _insert_run_row(
            store,
            "run-a2-real-newer",
            "A2",
            "real_llm",
            "v3-ffffffffffffffff",
            "1.0.0",
            "2999-01-01T00:00:00Z",
        )
        with client:
            h = _session_header(client, "analyst_northstar")
            comp = client.get("/api/v1/comparisons", headers=h).json()
        assert comp["comparable"] is True, comp
        assert len(comp["pairs"]) == 1
        assert comp["pairs"][0]["protected_run"]["id"] == prot["id"]
        assert comp["pairs"][0]["scenario_id"] == "A2"
    finally:
        _close_store(store)


def test_e802_newer_mismatched_scripted_run_does_not_mask_pair(tmp_path, monkeypatch):
    """A newer scripted A2 with a different variant (and one with a
    different policy) must not mask the older matching pair; the
    mismatched runs are reported unmatched with honest reasons."""
    store, client, prot = _comparisons_setup(tmp_path, monkeypatch)
    try:
        _insert_run_row(
            store,
            "run-a2-scripted-variant-mismatch",
            "A2",
            "scripted",
            "v3-0000000000000000",
            "1.0.0",
            "2999-01-01T00:00:00Z",
        )
        _insert_run_row(
            store,
            "run-a2-scripted-policy-mismatch",
            "A2",
            "scripted",
            prot["fixture_variant"],
            "9.9.9",
            "2999-01-02T00:00:00Z",
        )
        with client:
            h = _session_header(client, "analyst_northstar")
            comp = client.get("/api/v1/comparisons", headers=h).json()
        assert comp["comparable"] is True, comp
        assert len(comp["pairs"]) == 1
        assert comp["pairs"][0]["protected_run"]["id"] == prot["id"]
        reasons = {u["run_id"]: u["reason"] for u in comp["unmatched_protected"]}
        assert "fixture_variant mismatch" in reasons["run-a2-scripted-variant-mismatch"]
        assert "policy_version mismatch" in reasons["run-a2-scripted-policy-mismatch"]
    finally:
        _close_store(store)


def test_e802_two_eligible_runs_pair_once_with_alternative(tmp_path, monkeypatch):
    """Two eligible protected scripted A2 runs + one weak export pair
    exactly once (newest eligible wins) and the other is listed as an
    alternative, not double-counted."""
    store, client, prot = _comparisons_setup(tmp_path, monkeypatch)
    try:
        _insert_run_row(
            store,
            "run-a2-scripted-older",
            "A2",
            "scripted",
            prot["fixture_variant"],
            "1.0.0",
            "2000-01-01T00:00:00Z",
        )
        with client:
            h = _session_header(client, "analyst_northstar")
            comp = client.get("/api/v1/comparisons", headers=h).json()
        assert len(comp["pairs"]) == 1
        # The Runner-created run is newer than the 2000 row, so it wins.
        assert comp["pairs"][0]["protected_run"]["id"] == prot["id"]
        assert "run-a2-scripted-older" in comp["pairs"][0].get(
            "alternative_protected_runs", []
        )
    finally:
        _close_store(store)


def test_e802_legacy_weak_export_never_shadows_v3(tmp_path, monkeypatch):
    """A legacy weak export (no variant/policy) alongside the matching
    v3 export must not shadow the v3 pair."""
    import json as _json

    store, client, prot = _comparisons_setup(tmp_path, monkeypatch)
    try:
        legacy = {
            "mode": "weak",
            "run": {
                "scenario_id": "A2",
                "adapter": "scripted",
                "tenant_id": "tenant_northstar",
                "verdict": "FAIL",
                "metrics": {},
            },
        }
        (tmp_path / "example-reports" / "weak-A2-legacy.json").write_text(
            _json.dumps(legacy)
        )
        with client:
            h = _session_header(client, "analyst_northstar")
            comp = client.get("/api/v1/comparisons", headers=h).json()
        assert comp["comparable"] is True, comp
        assert len(comp["pairs"]) == 1
        assert comp["pairs"][0]["protected_run"]["id"] == prot["id"]
    finally:
        _close_store(store)


# ---------------- E8-03: bounded real-mode concurrency + idempotency ----------------


def test_e803_capacity_reached_without_orphan_runs(tmp_path, monkeypatch):
    """With cap=1, a second real launch while the first is blocked in
    the provider gets 429 CAPACITY_REACHED and creates no run row."""
    stub = _BarrierStub()
    try:
        _llm_env(monkeypatch, stub, cap=1)
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client)
                r1 = client.post(
                    "/api/v1/runs",
                    headers=h,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r1.status_code == 202, r1.text
                assert stub.request_started.wait(timeout=15)
                r2 = client.post(
                    "/api/v1/runs",
                    headers=h,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r2.status_code == 429, r2.text
                assert r2.json()["error"]["code"] == "CAPACITY_REACHED"
                assert len(store.all("SELECT * FROM runs")) == 1
                stub.release.set()
                _poll_terminal(client, h, r1.json()["id"])
                assert len(store.all("SELECT * FROM runs")) == 1
                assert _orphan_event_count(store) == 0
        finally:
            _close_store(store)
    finally:
        stub.shutdown()


def test_e803_health_reports_configured_cap(tmp_path, monkeypatch):
    """The health payload reports the real-mode cap: default 2, and the
    env override when set before app creation."""
    stub = _BarrierStub()
    try:
        _llm_env(monkeypatch, stub)
        store, client = _api_client(tmp_path)
        try:
            with client:
                health = client.get("/api/v1/health").json()
                assert health["max_concurrent_real_runs"] == 2
        finally:
            _close_store(store)
    finally:
        stub.shutdown()


def test_e803_idempotent_resubmit_returns_same_run(tmp_path, monkeypatch):
    """The same Idempotency-Key + scenario replays the original run
    instead of creating a second one; the same key with a different
    scenario is refused."""
    stub = _BarrierStub()
    try:
        _llm_env(monkeypatch, stub)
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client)
                h1 = {**h, "Idempotency-Key": "e8-idem-1"}
                r1 = client.post(
                    "/api/v1/runs",
                    headers=h1,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r1.status_code == 202, r1.text
                run_id = r1.json()["id"]
                r2 = client.post(
                    "/api/v1/runs",
                    headers=h1,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r2.status_code == 202, r2.text
                assert r2.json()["id"] == run_id
                assert len(store.all("SELECT * FROM runs")) == 1
                r3 = client.post(
                    "/api/v1/runs",
                    headers=h1,
                    json={"scenario_id": "A2", "adapter": "real_llm"},
                )
                assert r3.status_code == 409, r3.text
                assert r3.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
                stub.release.set()
                _poll_terminal(client, h, run_id)
        finally:
            _close_store(store)
    finally:
        stub.shutdown()


def test_e803_concurrent_burst_respects_cap(tmp_path, monkeypatch):
    """Burst of 5 concurrent real launches against a real uvicorn
    server with cap=2: exactly 2 accepted, 3 rejected with 429, no
    500s, no orphan runs, both accepted jobs finalize."""
    import os
    import subprocess

    import httpx

    stub = _BarrierStub()
    try:
        db_path = str(tmp_path / "burst.db")
        env = dict(os.environ)
        env["AGENTBOUNDARY_DB_PATH"] = db_path
        env["AGENTBOUNDARY_LLM_LOCAL_OLLAMA"] = "1"
        env["AGENTBOUNDARY_LLM_BASE_URL"] = f"http://127.0.0.1:{stub.port}/v1"
        env["AGENTBOUNDARY_LLM_MODEL"] = "e8-stub"
        env.pop("AGENTBOUNDARY_LLM_API_KEY", None)
        env["AGENTBOUNDARY_MAX_CONCURRENT_REAL_RUNS"] = "2"
        # N9-04: portable child-process setup. The server runs under
        # sys.executable (whatever interpreter runs pytest — the repo
        # venv here, an auditor's interpreter elsewhere), never a
        # hardcoded .venv path; it listens on a free loopback port
        # allocated per test (no fixed 8130, so concurrent suites
        # cannot collide); and the package import path is explicit via
        # PYTHONPATH so the child works even without an editable
        # install. The child binds loopback only, never 0.0.0.0.
        import pathlib
        import socket
        import sys

        backend_dir = pathlib.Path(__file__).resolve().parents[2]
        env["PYTHONPATH"] = (
            str(backend_dir / "src") + os.pathsep + env.get("PYTHONPATH", "")
        )
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        # The file must stay open as the server's stdout for the
        # subprocess lifetime; it is closed in the finally below.
        logf = open(str(tmp_path / "burst-server.log"), "wb")  # noqa: SIM115
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "agentboundary.api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=str(backend_dir),
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(timeout=15, trust_env=False) as c:
                healthy = False
                for _ in range(60):
                    try:
                        if c.get(f"{base}/api/v1/health").status_code == 200:
                            healthy = True
                            break
                    except httpx.ConnectError:
                        time.sleep(0.5)
                # N9-04: fail fast with the child's log, not a bare
                # connection error, when the server never comes up.
                logf.flush()
                log_tail = ""
                try:
                    with open(str(tmp_path / "burst-server.log"), "rb") as lf:
                        log_tail = lf.read().decode(errors="replace")[-2000:]
                except OSError:
                    pass
                assert healthy, f"burst server never became healthy:\n{log_tail}"
                token = c.post(
                    f"{base}/api/v1/lab/session",
                    json={"persona_id": "incident_commander"},
                ).json()["session_token"]
                headers = {"X-Lab-Session": token}
                results = []

                def _launch():
                    try:
                        with httpx.Client(timeout=15, trust_env=False) as cc:
                            resp = cc.post(
                                f"{base}/api/v1/runs",
                                headers=headers,
                                json={"scenario_id": "A1", "adapter": "real_llm"},
                            )
                            results.append((resp.status_code, resp.json()))
                    except Exception as exc:  # noqa: BLE001 - record, don't hide
                        results.append(("error", str(exc)))

                threads = [threading.Thread(target=_launch) for _ in range(5)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=30)
                # N9-04: attach the child log to every burst assertion
                # so a failure is diagnosable, not just a count.
                assert len(results) == 5, f"{results}\nserver log:\n{log_tail}"
                accepted = [r for s, r in results if s == 202]
                rejected = [r for s, r in results if s == 429]
                assert len(accepted) == 2, f"{results}\nserver log:\n{log_tail}"
                assert len(rejected) == 3, f"{results}\nserver log:\n{log_tail}"
                assert all(r["error"]["code"] == "CAPACITY_REACHED" for r in rejected)
                stub.release.set()
                with httpx.Client(timeout=15, trust_env=False) as c:
                    for run in accepted:
                        run_id = run["id"]
                        deadline = time.time() + 30
                        while time.time() < deadline:
                            got = c.get(f"{base}/api/v1/runs/{run_id}", headers=headers)
                            if got.json()["status"] in (
                                "completed",
                                "error",
                                "cancelled",
                                "inconclusive",
                            ):
                                break
                            time.sleep(0.2)
            store = Store(db_path)
            try:
                assert len(store.all("SELECT * FROM runs")) == 2
                assert _orphan_event_count(store) == 0
            finally:
                _close_store(store)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            logf.close()
    finally:
        stub.shutdown()
