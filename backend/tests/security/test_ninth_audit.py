"""Ninth independent audit regressions (N9-01..N9-04).

Mocked/stub provider traffic only; disposable tmp databases; the demo
DB is never touched. Each test reproduces an audit repro (or the
closest honest equivalent) and asserts the FIXED behavior.
"""

import json
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
                                    "reason": "n9 probe",
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


def _stub_server(mode="barrier"):
    import http.server
    import socketserver

    state = {
        "request_started": threading.Event(),
        "release": threading.Event(),
        "active": 0,
        "lock": threading.Lock(),
    }

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            with state["lock"]:
                state["active"] += 1
            try:
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                if mode == "error500":
                    self.send_response(500)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                state["request_started"].set()
                state["release"].wait(timeout=30)
                body = json.dumps(OPEN_PROPOSAL).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            finally:
                with state["lock"]:
                    state["active"] -= 1

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def shutdown():
        state["release"].set()
        deadline = time.time() + 5
        while time.time() < deadline:
            with state["lock"]:
                if state["active"] == 0:
                    break
            time.sleep(0.05)
        deadline = time.time() + 5
        while time.time() < deadline:
            if Store._live_count <= 0:
                break
            time.sleep(0.05)
        server.shutdown()
        server.server_close()

    return server, state, shutdown


def _llm_env(monkeypatch, port, cap=None):
    monkeypatch.setenv("AGENTBOUNDARY_LLM_LOCAL_OLLAMA", "1")
    monkeypatch.setenv("AGENTBOUNDARY_LLM_BASE_URL", f"http://127.0.0.1:{port}/v1")
    monkeypatch.setenv("AGENTBOUNDARY_LLM_MODEL", "n9-stub")
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
    return store.one(
        "SELECT COUNT(*) AS n FROM events WHERE run_id NOT IN (SELECT id FROM runs)"
    )["n"]


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
    deadline = time.time() + 5
    while time.time() < deadline:
        if Store._live_count <= 1:
            break
        time.sleep(0.05)
    return last


# ---------------- N9-01: worker Store failure must not strand a run ----------------


def test_n901_worker_store_open_failure_finalizes_error(tmp_path, monkeypatch):
    """N9-01 repro (auditor's patch, always-raise): the worker's Store
    construction raises, yet the run must become ERROR (not stay
    queued), no thread exception may escape, no Store may leak, and
    reset must succeed afterwards — with 2 fresh jobs launchable
    within the cap once the patch is lifted."""
    import agentboundary.api.app as app_module

    server, state, shutdown = _stub_server()
    try:
        _llm_env(monkeypatch, server.server_address[1])
        store, client = _api_client(tmp_path)
        real_store_cls = app_module.Store

        class _AlwaysFailStore:
            def __init__(self, *args, **kwargs):
                raise OSError("synthetic worker Store failure")

        thread_errors = []
        old_hook = threading.excepthook
        threading.excepthook = lambda args: thread_errors.append(args)
        try:
            with client:
                h = _session_header(client)
                monkeypatch.setattr(app_module, "Store", _AlwaysFailStore)
                r = client.post(
                    "/api/v1/runs",
                    headers=h,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r.status_code == 202, r.text
                run_id = r.json()["id"]
                final = _poll_terminal(client, h, run_id)
                assert final["status"] == "error", final
                assert final["verdict"] == "ERROR"
                assert final["finished_at"] is not None
                assert final["metrics"].get("error_class") == "worker_startup_error", (
                    final["metrics"]
                )
                assert thread_errors == [], thread_errors
                # Registry popped + row terminal: reset succeeds.
                reset = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
                assert reset.status_code == 200, reset.text
                # Lift the patch: 2 fresh jobs launch within the cap.
                monkeypatch.setattr(app_module, "Store", real_store_cls)
                ids = []
                for _ in range(2):
                    rr = client.post(
                        "/api/v1/runs",
                        headers=h,
                        json={"scenario_id": "A1", "adapter": "real_llm"},
                    )
                    assert rr.status_code == 202, rr.text
                    ids.append(rr.json()["id"])
                assert state["request_started"].wait(timeout=15)
                state["release"].set()
                for rid in ids:
                    _poll_terminal(client, h, rid)
                assert len(store.all("SELECT * FROM runs")) == 2
                assert _orphan_event_count(store) == 0
        finally:
            threading.excepthook = old_hook
            _close_store(store)
    finally:
        shutdown()


def test_n901_worker_store_schema_failure_finalizes_via_fresh_connection(
    tmp_path, monkeypatch
):
    """N9-01 schema-init variant: the first Store() call raises (a
    seed/repair failure), later calls succeed — finalization must use
    the fresh connection and the run must still become ERROR."""
    import agentboundary.api.app as app_module

    server, _state, shutdown = _stub_server()
    try:
        _llm_env(monkeypatch, server.server_address[1])
        store, client = _api_client(tmp_path)
        real_store_cls = app_module.Store
        calls = {"n": 0}

        class _FailOnceStore:
            def __init__(self, *args, **kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise OSError("synthetic schema initialization failure")
                self._inner = real_store_cls(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        try:
            with client:
                h = _session_header(client)
                monkeypatch.setattr(app_module, "Store", _FailOnceStore)
                r = client.post(
                    "/api/v1/runs",
                    headers=h,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r.status_code == 202, r.text
                run_id = r.json()["id"]
                final = _poll_terminal(client, h, run_id)
                assert final["status"] == "error", final
                assert final["metrics"].get("error_class") == "worker_startup_error"
                assert calls["n"] >= 2
                reset = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
                assert reset.status_code == 200, reset.text
        finally:
            _close_store(store)
    finally:
        shutdown()


def test_n901_runner_construction_failure_finalizes_via_worker_store(
    tmp_path, monkeypatch
):
    """N9-01 early-init variant: Store opens, but Runner construction
    raises — the worker's own store must finalize the run as ERROR
    (worker_error) with no leaked Store."""
    import agentboundary.api.app as app_module

    server, _state, shutdown = _stub_server()
    try:
        _llm_env(monkeypatch, server.server_address[1])
        store, client = _api_client(tmp_path)
        real_runner_cls = app_module.Runner
        calls = {"n": 0}

        class _FailOnceRunner:
            # Construction 1 is the request handler's Runner (used for
            # create_pending_run); construction 2 is the worker's. Fail
            # only the worker's, which is the N9-01 early-init case.
            def __init__(self, *args, **kwargs):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise RuntimeError("synthetic Runner init failure")
                self._inner = real_runner_cls(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        try:
            with client:
                h = _session_header(client)
                monkeypatch.setattr(app_module, "Runner", _FailOnceRunner)
                r = client.post(
                    "/api/v1/runs",
                    headers=h,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r.status_code == 202, r.text
                run_id = r.json()["id"]
                final = _poll_terminal(client, h, run_id)
                assert final["status"] == "error", final
                assert final["metrics"].get("error_class") == "worker_error"
                reset = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
                assert reset.status_code == 200, reset.text
        finally:
            _close_store(store)
    finally:
        shutdown()


def test_n901_thread_start_failure_is_error_not_running(tmp_path, monkeypatch):
    """A background thread that never starts must not be reported as
    a successfully running job: the launch response itself must carry
    the ERROR state, and reset must succeed."""
    import threading as threading_module

    server, _state, shutdown = _stub_server()
    try:
        _llm_env(monkeypatch, server.server_address[1])
        store, client = _api_client(tmp_path)
        real_thread = threading_module.Thread
        calls = {"n": 0}

        class _OneShotFailThread(real_thread):
            def start(self):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("synthetic thread start failure")
                return super().start()

        try:
            with client:
                h = _session_header(client)
                # Patch only after the client portal exists, so the
                # first new thread afterwards is the worker thread.
                monkeypatch.setattr(threading_module, "Thread", _OneShotFailThread)
                r = client.post(
                    "/api/v1/runs",
                    headers=h,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                monkeypatch.setattr(threading_module, "Thread", real_thread)
                assert r.status_code == 202, r.text
                assert r.json()["status"] == "error", r.json()
                assert r.json()["job"]["status"] == "error"
                assert calls["n"] == 1
                reset = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
                assert reset.status_code == 200, reset.text
        finally:
            _close_store(store)
    finally:
        shutdown()


# ---------------- N9-02: restart recovery covers queued + running ----------------


def test_n902_queued_row_recovered_as_interrupted(tmp_path):
    """N9-02 repro: a queued pending run (crash window between
    create_pending_run and thread.start) becomes INTERRUPTED on
    startup, and reset is then allowed."""
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    store = Store(str(tmp_path / "lab.db"))
    try:
        pending_id = Runner(store).create_pending_run(
            "A1", operator_persona_id="incident_commander"
        )
        pending_row = store.one("SELECT * FROM runs WHERE id=?", (pending_id,))
        assert pending_row["status"] == "queued"
        started_at = pending_row["started_at"]
        # One lifespan per Store: recovery and the reset both happen
        # inside the same client context (lifespan exit closes the store).
        with TestClient(create_app(store=store)) as client:
            row = store.one("SELECT * FROM runs WHERE id=?", (pending_id,))
            assert row["status"] == "interrupted", row
            assert row["verdict"] == "INCONCLUSIVE"
            assert row["started_at"] == started_at
            assert row["finished_at"] is not None
            metrics = json.loads(row["metrics"])
            assert metrics["error_class"] == "interrupted"
            assert metrics["recovered_at"] is not None
            h = _session_header(client)
            reset = client.post("/api/v1/lab/reset", headers=h, json={"confirm": True})
            assert reset.status_code == 200, reset.text
    finally:
        _close_store(store)


def test_n902_running_and_completed_rows(tmp_path):
    """Running rows recover as INTERRUPTED; completed rows are left
    completely unchanged by startup recovery."""
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    store = Store(str(tmp_path / "lab.db"))
    try:
        done = Runner(store).run("A1", operator_persona_id="incident_commander")
        done_before = store.one("SELECT * FROM runs WHERE id=?", (done["id"],))
        pending_id = Runner(store).create_pending_run(
            "A1", operator_persona_id="incident_commander"
        )
        store.execute("UPDATE runs SET status='running' WHERE id=?", (pending_id,))
        with TestClient(create_app(store=store)):
            row = store.one("SELECT * FROM runs WHERE id=?", (pending_id,))
            assert row["status"] == "interrupted"
            assert row["verdict"] == "INCONCLUSIVE"
            after = store.one("SELECT * FROM runs WHERE id=?", (done["id"],))
            assert after["status"] == done_before["status"]
            assert after["verdict"] == done_before["verdict"]
            assert after["metrics"] == done_before["metrics"]
            assert after["finished_at"] == done_before["finished_at"]
    finally:
        _close_store(store)


def test_n902_queued_and_running_together_no_case_mutation(tmp_path):
    """Simultaneous queued + running orphans both recover; recovery
    touches no case state and leaves no orphan events."""
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    store = Store(str(tmp_path / "lab.db"))
    try:
        q_id = Runner(store).create_pending_run(
            "A1", operator_persona_id="incident_commander"
        )
        r_id = Runner(store).create_pending_run(
            "A2", operator_persona_id="incident_commander"
        )
        store.execute("UPDATE runs SET status='running' WHERE id=?", (r_id,))
        with TestClient(create_app(store=store)) as client:
            for rid in (q_id, r_id):
                row = store.one("SELECT * FROM runs WHERE id=?", (rid,))
                assert row["status"] == "interrupted", row
            assert store.get_case("INC-2048")["status"] == "investigating"
            assert _orphan_event_count(store) == 0
            h = _session_header(client)
            assert (
                client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                ).status_code
                == 200
            )
    finally:
        _close_store(store)


def test_n902_two_competing_workers_denied_no_data_loss(tmp_path):
    """A second app on the same DB file is denied by .applock at
    startup with no data loss; after the first app exits, the second
    can start (lock released)."""
    import pytest
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    store1 = Store(str(tmp_path / "lab.db"))
    store2 = None
    try:
        done = Runner(store1).run("A1", operator_persona_id="incident_commander")
        with TestClient(create_app(store=store1)) as client1:
            assert client1.get("/api/v1/health").status_code == 200
            store2 = Store(str(tmp_path / "lab.db"))
            with (
                pytest.raises(RuntimeError, match="already holds this database"),
                TestClient(create_app(store=store2)),
            ):
                pass
            # Denied worker leaked nothing and harmed nothing: its
            # store was closed by the failed lifespan.
            assert Store._live_count == 1  # only store1 remains open
            assert (
                store1.one("SELECT * FROM runs WHERE id=?", (done["id"],))["status"]
                == "completed"
            )
            assert client1.get("/api/v1/health").status_code == 200
        # First app exited: the lock is released. A fresh store on the
        # same path starts the second app (one Store per lifespan).
        store3 = Store(str(tmp_path / "lab.db"))
        try:
            with TestClient(create_app(store=store3)) as client2:
                assert client2.get("/api/v1/health").status_code == 200
        finally:
            _close_store(store3)
    finally:
        _close_store(store1)
        if store2 is not None:
            _close_store(store2)


def test_n902_cancelled_row_does_not_block_reset(tmp_path):
    """Cancelled is terminal: a cancelled row never blocks reset."""
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    store = Store(str(tmp_path / "lab.db"))
    try:
        pending_id = Runner(store).create_pending_run(
            "A1", operator_persona_id="incident_commander"
        )
        store.execute(
            "UPDATE runs SET status='cancelled', verdict='CANCELLED' WHERE id=?",
            (pending_id,),
        )
        with TestClient(create_app(store=store)) as client:
            h = _session_header(client)
            assert (
                client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                ).status_code
                == 200
            )
    finally:
        _close_store(store)


# ---------------- N9-03: operator-scoped idempotency ----------------


def test_n903_same_operator_new_session_replays(tmp_path, monkeypatch):
    """Same operator, fresh session, same key + request -> the same
    run (one worker). Scope decision: persona, not session token."""
    server, state, shutdown = _stub_server()
    try:
        _llm_env(monkeypatch, server.server_address[1])
        store, client = _api_client(tmp_path)
        try:
            with client:
                h1 = _session_header(client, "analyst_northstar")
                r1 = client.post(
                    "/api/v1/runs",
                    headers={**h1, "Idempotency-Key": "n9-reuse"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r1.status_code == 202, r1.text
                run_id = r1.json()["id"]
                # Fresh session, same persona.
                h2 = _session_header(client, "analyst_northstar")
                assert h2 != h1
                r2 = client.post(
                    "/api/v1/runs",
                    headers={**h2, "Idempotency-Key": "n9-reuse"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r2.status_code == 202, r2.text
                assert r2.json()["id"] == run_id
                assert len(store.all("SELECT * FROM runs")) == 1
                state["release"].set()
                final = _poll_terminal(client, h1, run_id)
                assert final["operator_persona_id"] == "analyst_northstar"
        finally:
            _close_store(store)
    finally:
        shutdown()


def test_n903_same_operator_different_request_409(tmp_path, monkeypatch):
    """Same operator + key, different scenario -> 409, no new run."""
    server, state, shutdown = _stub_server()
    try:
        _llm_env(monkeypatch, server.server_address[1])
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client, "analyst_northstar")
                r1 = client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "n9-reuse"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r1.status_code == 202, r1.text
                r2 = client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "n9-reuse"},
                    json={"scenario_id": "A2", "adapter": "real_llm"},
                )
                assert r2.status_code == 409, r2.text
                assert r2.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
                assert len(store.all("SELECT * FROM runs")) == 1
                state["release"].set()
                _poll_terminal(client, h, r1.json()["id"])
        finally:
            _close_store(store)
    finally:
        shutdown()


def test_n903_different_operator_same_key_independent(tmp_path, monkeypatch):
    """N9-03 repro: a different operator with the same header key must
    get an INDEPENDENT run with their own attribution — never the
    first operator's run id."""
    server, state, shutdown = _stub_server()
    try:
        _llm_env(monkeypatch, server.server_address[1])
        store, client = _api_client(tmp_path)
        try:
            with client:
                h_north = _session_header(client, "analyst_northstar")
                r1 = client.post(
                    "/api/v1/runs",
                    headers={**h_north, "Idempotency-Key": "reuse-me"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r1.status_code == 202, r1.text
                id1 = r1.json()["id"]
                assert r1.json()["operator_persona_id"] == "analyst_northstar"
                h_cmd = _session_header(client, "incident_commander")
                r2 = client.post(
                    "/api/v1/runs",
                    headers={**h_cmd, "Idempotency-Key": "reuse-me"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r2.status_code == 202, r2.text
                id2 = r2.json()["id"]
                assert id2 != id1
                assert r2.json()["operator_persona_id"] == "incident_commander"
                assert len(store.all("SELECT * FROM runs")) == 2
                # GET list attribution agrees per operator. Lists are
                # tenant-scoped by design (N-04), so the commander's
                # Northstar-tenant run IS visible to the Northstar
                # analyst — but attributed to the commander, never
                # inherited as the analyst's own run.
                north_list = client.get("/api/v1/runs", headers=h_north).json()
                assert any(
                    r["id"] == id1 and r["operator_persona_id"] == "analyst_northstar"
                    for r in north_list
                )
                assert any(
                    r["id"] == id2 and r["operator_persona_id"] == "incident_commander"
                    for r in north_list
                )
                state["release"].set()
                _poll_terminal(client, h_north, id1)
                _poll_terminal(client, h_cmd, id2)
        finally:
            _close_store(store)
    finally:
        shutdown()


def test_n903_different_tenant_still_denied(tmp_path, monkeypatch):
    """Operator scoping never bypasses tenant checks: a Cedar analyst
    launching a Northstar scenario with a fresh key gets 403, and the
    Northstar analyst can then use the same key independently."""
    server, state, shutdown = _stub_server()
    try:
        _llm_env(monkeypatch, server.server_address[1])
        store, client = _api_client(tmp_path)
        try:
            with client:
                h_cedar = _session_header(client, "analyst_cedar")
                denied = client.post(
                    "/api/v1/runs",
                    headers={**h_cedar, "Idempotency-Key": "n9-tenant"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert denied.status_code == 403, denied.text
                h_north = _session_header(client, "analyst_northstar")
                ok = client.post(
                    "/api/v1/runs",
                    headers={**h_north, "Idempotency-Key": "n9-tenant"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert ok.status_code == 202, ok.text
                assert ok.json()["operator_persona_id"] == "analyst_northstar"
                assert len(store.all("SELECT * FROM runs")) == 1
                state["release"].set()
                _poll_terminal(client, h_north, ok.json()["id"])
        finally:
            _close_store(store)
    finally:
        shutdown()


def test_n903_replay_at_cap_returns_original(tmp_path, monkeypatch):
    """Replay while at capacity returns the original run without
    consuming a slot; a genuinely new launch still gets 429."""
    server, state, shutdown = _stub_server()
    try:
        _llm_env(monkeypatch, server.server_address[1], cap=1)
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client, "analyst_northstar")
                r1 = client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "n9-cap"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r1.status_code == 202, r1.text
                assert state["request_started"].wait(timeout=15)
                replay = client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "n9-cap"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert replay.status_code == 202, replay.text
                assert replay.json()["id"] == r1.json()["id"]
                fresh = client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "n9-cap-other"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert fresh.status_code == 429, fresh.text
                assert len(store.all("SELECT * FROM runs")) == 1
                state["release"].set()
                _poll_terminal(client, h, r1.json()["id"])
        finally:
            _close_store(store)
    finally:
        shutdown()


def test_n903_reset_invalidates_key(tmp_path, monkeypatch):
    """After a quiescent reset, the same operator + key launches a
    fresh run — reset cannot resurrect a stale run."""
    server, state, shutdown = _stub_server()
    try:
        _llm_env(monkeypatch, server.server_address[1])
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client, "incident_commander")
                r1 = client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "n9-reset"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r1.status_code == 202, r1.text
                state["release"].set()
                _poll_terminal(client, h, r1.json()["id"])
                reset = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
                assert reset.status_code == 200, reset.text
                r2 = client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "n9-reset"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r2.status_code == 202, r2.text
                assert r2.json()["id"] != r1.json()["id"]
                state["release"].set()
                _poll_terminal(client, h, r2.json()["id"])
        finally:
            _close_store(store)
    finally:
        shutdown()


def test_n903_error_run_key_launches_fresh(tmp_path, monkeypatch):
    """A key whose run ended in ERROR is stale: the next launch with
    the same key + request is a fresh run, not a replay of failure."""
    server, _state, shutdown = _stub_server(mode="error500")
    try:
        _llm_env(monkeypatch, server.server_address[1])
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client, "analyst_northstar")
                r1 = client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "n9-err"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r1.status_code == 202, r1.text
                assert _poll_terminal(client, h, r1.json()["id"])["status"] == "error"
                r2 = client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "n9-err"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r2.status_code == 202, r2.text
                assert r2.json()["id"] != r1.json()["id"]
                assert _poll_terminal(client, h, r2.json()["id"])["status"] == "error"
                assert len(store.all("SELECT * FROM runs")) == 2
        finally:
            _close_store(store)
    finally:
        shutdown()


def test_n903_expired_key_launches_fresh(tmp_path, monkeypatch):
    """With TTL forced to 0, a replay is expired on arrival and
    launches fresh — proving the expiry path, not just the bound."""
    import agentboundary.api.app as app_module

    server, state, shutdown = _stub_server()
    try:
        _llm_env(monkeypatch, server.server_address[1])
        monkeypatch.setattr(app_module, "IDEMPOTENCY_TTL_SECONDS", 0)
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client, "analyst_northstar")
                r1 = client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "n9-ttl"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r1.status_code == 202, r1.text
                r2 = client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "n9-ttl"},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r2.status_code == 202, r2.text
                assert r2.json()["id"] != r1.json()["id"]
                assert len(store.all("SELECT * FROM runs")) == 2
                state["release"].set()
                _poll_terminal(client, h, r1.json()["id"])
                _poll_terminal(client, h, r2.json()["id"])
        finally:
            _close_store(store)
    finally:
        shutdown()


def test_n903_key_length_bounded(tmp_path, monkeypatch):
    """An over-long Idempotency-Key is a 400 and creates no run."""
    server, _state, shutdown = _stub_server()
    try:
        _llm_env(monkeypatch, server.server_address[1])
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client, "analyst_northstar")
                r = client.post(
                    "/api/v1/runs",
                    headers={**h, "Idempotency-Key": "k" * 300},
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r.status_code == 400, r.text
                assert r.json()["error"]["code"] == "INVALID_REQUEST"
                assert store.all("SELECT * FROM runs") == []
        finally:
            _close_store(store)
    finally:
        shutdown()


# ---------------- N9-04: portable concurrent same-key test ----------------


def test_n904_concurrent_same_key_creates_one_run(tmp_path, monkeypatch):
    """Portable real-server test (sys.executable, free loopback port,
    explicit PYTHONPATH): 5 concurrent same-operator same-key launches
    create exactly one run; every caller gets 202 with the same id."""
    import os
    import pathlib
    import socket
    import subprocess
    import sys

    import httpx

    server, state, shutdown = _stub_server()
    try:
        db_path = str(tmp_path / "burst9.db")
        backend_dir = pathlib.Path(__file__).resolve().parents[2]
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        env = dict(os.environ)
        env["AGENTBOUNDARY_DB_PATH"] = db_path
        env["AGENTBOUNDARY_LLM_LOCAL_OLLAMA"] = "1"
        env["AGENTBOUNDARY_LLM_BASE_URL"] = (
            f"http://127.0.0.1:{server.server_address[1]}/v1"
        )
        env["AGENTBOUNDARY_LLM_MODEL"] = "n9-stub"
        env.pop("AGENTBOUNDARY_LLM_API_KEY", None)
        env["AGENTBOUNDARY_MAX_CONCURRENT_REAL_RUNS"] = "2"
        env["PYTHONPATH"] = (
            str(backend_dir / "src") + os.pathsep + env.get("PYTHONPATH", "")
        )
        logf = open(str(tmp_path / "burst9-server.log"), "wb")  # noqa: SIM115
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
            healthy = False
            with httpx.Client(timeout=15, trust_env=False) as c:
                for _ in range(60):
                    try:
                        if c.get(f"{base}/api/v1/health").status_code == 200:
                            healthy = True
                            break
                    except httpx.ConnectError:
                        time.sleep(0.5)
                logf.flush()
                log_tail = ""
                try:
                    with open(str(tmp_path / "burst9-server.log"), "rb") as lf:
                        log_tail = lf.read().decode(errors="replace")[-2000:]
                except OSError:
                    pass
                assert healthy, f"burst server never became healthy:\n{log_tail}"
                token = c.post(
                    f"{base}/api/v1/lab/session",
                    json={"persona_id": "analyst_northstar"},
                ).json()["session_token"]
                headers = {"X-Lab-Session": token, "Idempotency-Key": "n9-burst"}
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
                assert len(results) == 5, f"{results}\nserver log:\n{log_tail}"
                assert all(s == 202 for s, _ in results), (
                    f"{results}\nserver log:\n{log_tail}"
                )
                ids = {r["id"] for _, r in results}
                assert len(ids) == 1, f"concurrent same-key created {ids}"
                state["release"].set()
                run_id = ids.pop()
                with httpx.Client(timeout=15, trust_env=False) as c:
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
                assert len(store.all("SELECT * FROM runs")) == 1
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
        shutdown()
