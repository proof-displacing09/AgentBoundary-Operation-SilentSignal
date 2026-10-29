"""Twelfth independent release-candidate audit regressions (RC12-01, RC12-02).

Disposable tmp databases only; the demo DB is never touched.
RC12-01 uses real separate OS processes where the finding is about
process-level ownership under pathname aliases, and fault injection
for the mid-acquisition race. RC12-02 uses fault injection inside
the real reset transaction (never a wholesale replacement of
Store.reset, which would bypass the code under test) plus one
stub-provider real-mode run for the idempotency-preservation gate.

New-symbol imports (HardlinkedDatabaseError, _db_file_identity) are
resolved via getattr inside the tests that need them, so a pre-fix
tree fails these tests instead of failing collection — the stash
round-trip stays a real failing-first proof.
"""

import glob
import hashlib
import http.server
import json
import os
import socket
import socketserver
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from agentboundary.store import Store

_posix_only = pytest.mark.skipif(
    os.name != "posix", reason="hardlink ownership checks are POSIX-only"
)


def _raw(db_path, sql, args=()):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


def _runbook_count(db_path):
    return _raw(db_path, "SELECT COUNT(*) FROM runbooks")


def _db_sha(db_path):
    return hashlib.sha256(Path(db_path).read_bytes()).hexdigest()


def _case_status(db_path, case_id="INC-2048"):
    return _raw(db_path, "SELECT status FROM cases WHERE id=?", (case_id,))


def _table_counts(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in (
                "runs",
                "events",
                "sessions",
                "drafts",
                "isolations",
                "approvals",
                "cases",
            )
        }
    finally:
        conn.close()


def _api_client(tmp_path, name="api.db"):
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    store = Store(str(tmp_path / name))
    client = TestClient(create_app(store=store), raise_server_exceptions=False)
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


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _repo_root():
    return Path(__file__).parents[3]


def _serve_uvicorn(db_path, port, log_path):
    """Real uvicorn subprocess on a disposable DB (portable pattern)."""
    env = dict(os.environ)
    env["AGENTBOUNDARY_DB_PATH"] = str(db_path)
    env["PYTHONPATH"] = str(_repo_root() / "backend" / "src")
    # The handle must outlive this call: uvicorn writes to it for the
    # server's lifetime; _stop_proc closes it.
    log = open(log_path, "wb")  # noqa: SIM115
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
        cwd=str(_repo_root() / "backend"),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return proc, log


def _wait_healthy(port, timeout=30):
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=5, trust_env=False) as c:
                if c.get(f"http://127.0.0.1:{port}/api/v1/health").status_code == 200:
                    return True
        except httpx.ConnectError:
            time.sleep(0.25)
    return False


def _stop_proc(proc, log):
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:  # noqa: BLE001 - teardown is best-effort
        try:
            proc.kill()
        except Exception:  # noqa: BLE001, S110
            pass
    try:
        log.close()
    except Exception:  # noqa: BLE001, S110
        pass


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


# ---------------- RC12-01: hard links ----------------


@_posix_only
def test_rc1201_hardlink_aliases_refused_at_lock_and_store(tmp_path):
    """Auditor repro, lock level: real.db and a hard link to the same
    inode must NOT both obtain ownership (pre-fix both
    try_acquire_db_lock calls succeeded). Both paths are refused with
    a hard-link explanation, no .applock is created by a refused
    attempt, no Store connection leaks, and after the extra link is
    removed the ordinary path works again."""
    import agentboundary.store as store_module

    err_cls = getattr(store_module, "HardlinkedDatabaseError", None)
    assert err_cls is not None, "HardlinkedDatabaseError missing (pre-fix)"
    real = tmp_path / "real.db"
    alias = tmp_path / "hardlink.db"
    Store(str(real)).close()
    os.link(real, alias)
    assert os.stat(real).st_ino == os.stat(alias).st_ino
    assert os.stat(real).st_nlink == 2
    baseline = Store._live_count
    before = _db_sha(real)
    for path in (real, alias):
        with pytest.raises(err_cls, match="hard links"):
            store_module.try_acquire_db_lock(str(path))
    with pytest.raises(err_cls, match="hard links"):
        Store(str(alias))
    assert Store._live_count == baseline
    assert glob.glob(str(tmp_path / "*.applock")) == []
    assert _db_sha(real) == before
    assert _runbook_count(real) == 6
    # Recovery: removing the extra link restores single-link use.
    os.unlink(alias)
    lock = store_module.try_acquire_db_lock(str(real))
    assert lock is not None
    lock.close()
    Store(str(real)).close()
    assert _runbook_count(real) == 6


@_posix_only
def test_rc1201_two_testclient_lifespans_hardlink_denied(tmp_path):
    """Auditor repro, lifespan level: with a hardlinked DB, NEITHER
    an app on the real path NOR an app on the alias may start (the
    fix refuses the file itself, not just the second owner). The
    refused apps must not mutate any row, and after the extra link is
    removed the same alias app object starts and is healthy."""
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    real = tmp_path / "actual.db"
    alias = tmp_path / "hardlink.db"
    Store(str(real)).close()
    os.link(real, alias)
    before = _db_sha(real)
    with (
        pytest.raises(RuntimeError, match="hard links"),
        TestClient(create_app(path=str(real))),
    ):
        pass
    with (
        pytest.raises(RuntimeError, match="hard links"),
        TestClient(create_app(path=str(alias))),
    ):
        pass
    assert _runbook_count(real) == 6
    assert _db_sha(real) == before
    assert glob.glob(str(tmp_path / "*.applock")) == []
    os.unlink(alias)
    with TestClient(create_app(path=str(alias))) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert _runbook_count(real) == 6


@_posix_only
def test_rc1201_two_real_processes_hardlink_denied_then_recovers(tmp_path):
    """RC12-01(D): two REAL OS processes. A server on the real path
    and a server on the hardlink alias must BOTH fail startup without
    touching the DB; after the extra link is removed, a server on the
    alias starts and repairs the deleted fixture row."""
    import httpx

    real = tmp_path / "actual.db"
    alias = tmp_path / "hardlink.db"
    Store(str(real)).close()
    conn = sqlite3.connect(str(real))
    row = conn.execute("SELECT id FROM runbooks LIMIT 1").fetchone()[0]
    conn.execute("DELETE FROM runbooks WHERE id=?", (row,))
    conn.commit()
    conn.close()
    assert _runbook_count(real) == 5
    os.link(real, alias)
    before = _db_sha(real)
    for name, path in (("real", real), ("alias", alias)):
        port = _free_port()
        proc, log = _serve_uvicorn(path, port, tmp_path / f"uv-{name}.log")
        try:
            deadline = time.time() + 30
            while time.time() < deadline and proc.poll() is None:
                time.sleep(0.25)
            assert proc.poll() is not None, f"{name} server kept running"
            assert proc.returncode != 0, f"{name} server exited cleanly"
            with (
                httpx.Client(timeout=5, trust_env=False) as c,
                pytest.raises(httpx.ConnectError),
            ):
                c.get(f"http://127.0.0.1:{port}/api/v1/health")
            assert _runbook_count(real) == 5
            assert _db_sha(real) == before
            log_text = Path(tmp_path / f"uv-{name}.log").read_text(errors="replace")
            assert "hard links" in log_text
        finally:
            _stop_proc(proc, log)
    # Recovery: the extra link is gone, so the SURVIVING file (real)
    # works again — starting on the deleted alias path would seed a
    # fresh database instead, which is not the recovery being proven.
    os.unlink(alias)
    port = _free_port()
    proc, log = _serve_uvicorn(real, port, tmp_path / "uv-recovered.log")
    try:
        assert _wait_healthy(port), "real-path server never started after unlink"
        assert _runbook_count(real) == 6
    finally:
        _stop_proc(proc, log)


@_posix_only
def test_rc1201_cli_hardlink_refused_then_recovers(tmp_path, monkeypatch):
    """CLI reset/seed against a hardlinked database must refuse (exit
    2) without mutating; after the extra link is removed, the same
    CLI seed repairs legitimately."""
    from agentboundary.cli import main as cli_main

    real = tmp_path / "actual.db"
    monkeypatch.setenv("AGENTBOUNDARY_DB_PATH", str(real))
    Store(str(real)).close()
    conn = sqlite3.connect(str(real))
    row = conn.execute("SELECT id FROM runbooks LIMIT 1").fetchone()[0]
    conn.execute("DELETE FROM runbooks WHERE id=?", (row,))
    conn.commit()
    conn.close()
    assert _runbook_count(real) == 5
    alias = tmp_path / "hardlink.db"
    os.link(real, alias)
    before = _db_sha(real)
    assert cli_main(["reset"]) == 2
    assert cli_main(["seed"]) == 2
    assert _runbook_count(real) == 5
    assert _db_sha(real) == before
    os.unlink(alias)
    assert cli_main(["seed"]) == 0
    assert _runbook_count(real) == 6


@_posix_only
def test_rc1201_identity_change_during_lock_fails_closed(tmp_path, monkeypatch):
    """Fault-injected link-count change between lock acquisition and
    revalidation: the acquisition must raise (fail closed) and
    release the lock, so a subsequent acquisition succeeds.
    _db_file_identity is called twice per acquisition (pre-check,
    post-lock revalidation); the stub serves a clean identity first,
    then a 2-link identity, then clean identities."""
    import agentboundary.store as store_module

    identity_fn = getattr(store_module, "_db_file_identity", None)
    assert identity_fn is not None, "_db_file_identity missing (pre-fix)"
    real = tmp_path / "race.db"
    Store(str(real)).close()
    st = os.stat(real)
    clean = (st.st_dev, st.st_ino, 1)
    calls = [clean, (st.st_dev, st.st_ino, 2)]

    def flipping(path):
        if calls:
            return calls.pop(0)
        return clean

    monkeypatch.setattr(store_module, "_db_file_identity", flipping)
    with pytest.raises(RuntimeError, match="identity changed"):
        store_module.try_acquire_db_lock(str(real))
    # The failed acquisition released its lock: a clean one succeeds.
    lock = store_module.try_acquire_db_lock(str(real))
    assert lock is not None
    lock.close()


@_posix_only
def test_rc1201_symlink_and_ordinary_paths_still_work(tmp_path):
    """RC12-01 gate (d): the hardlink refusal must not break the
    paths that should work — a symlink alias (A11) and an ordinary
    single-link path each open separately when no competing owner
    exists, and distinct databases stay distinct."""
    real = tmp_path / "actual.db"
    alias = tmp_path / "friendly.db"
    Store(str(real)).close()
    alias.symlink_to(real)
    assert real.samefile(alias)
    Store(str(alias)).close()
    assert _runbook_count(real) == 6
    other = tmp_path / "other.db"
    Store(str(other)).close()
    assert _runbook_count(other) == 6
    assert os.stat(real).st_ino != os.stat(other).st_ino


# ---------------- RC12-02: atomic reset ----------------


def _run_a1_and_snapshot(store, client):
    """Run scripted A1 via the API and snapshot the lab state that a
    failed reset must preserve byte-for-byte (logically)."""
    h = _session_header(client)
    r = client.post("/api/v1/runs", headers=h, json={"scenario_id": "A1"})
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]
    db_path = store.path
    counts = _table_counts(db_path)
    assert counts["runs"] == 1 and counts["events"] > 0
    return h, run_id, counts


def test_rc1202_session_preservation_failure_rolls_back(tmp_path):
    """Auditor repro, fixed behavior: a failure AFTER the reseed but
    BEFORE the preserved-session insert must roll back the ENTIRE
    reset (pre-fix: 500 unstructured, runs/events/sessions erased).
    The response is structured RESET_FAILED with no filesystem path,
    the old lab state is intact, the pre-reset backup exists and is
    0600 and contains the old run, no temp artifacts remain, the
    reset barrier is cleared, and a retry succeeds."""
    store, client = _api_client(tmp_path)
    try:
        with client:
            h, run_id, counts = _run_a1_and_snapshot(store, client)
            inc_before = _case_status(store.path)
            orig = store._preserve_session

            def boom(conn, session):
                raise RuntimeError("injected session-preservation failure")

            store._preserve_session = boom
            try:
                resp = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
            finally:
                store._preserve_session = orig
            assert resp.status_code == 500, resp.text
            body = resp.json()
            assert body["error"]["code"] == "RESET_FAILED", resp.text
            assert str(tmp_path) not in resp.text
            assert "lab.db" not in resp.text
            assert _table_counts(store.path) == counts
            assert _case_status(store.path) == inc_before == "investigating"
            assert store.one("SELECT id FROM runs WHERE id=?", (run_id,)) is not None
            assert glob.glob(str(tmp_path / "*.tmp")) == []
            backups = glob.glob(str(tmp_path / "*.bak"))
            assert len(backups) == 1
            assert _mode(backups[0]) == 0o600
            assert _raw(backups[0], "SELECT COUNT(*) FROM runs") == 1
            assert _raw(backups[0], "SELECT COUNT(*) FROM events") > 0
            # Barrier cleared: a new session can be created, and the
            # rolled-back admin session still works.
            assert (
                client.post(
                    "/api/v1/lab/session",
                    json={"persona_id": "analyst_northstar"},
                ).status_code
                == 200
            )
            assert client.get("/api/v1/overview", headers=h).status_code == 200
            # Retry with no process restart: succeeds, 48 records.
            resp = client.post("/api/v1/lab/reset", headers=h, json={"confirm": True})
            assert resp.status_code == 200, resp.text
            assert resp.json()["records"] == 48
            assert _raw(store.path, "SELECT COUNT(*) FROM runs") == 0
            assert _raw(store.path, "SELECT COUNT(*) FROM sessions") == 1
    finally:
        _close_store(store)


@pytest.mark.parametrize("fault", ["seed-immediate", "post-seed"])
def test_rc1202_reset_failure_variants_roll_back(tmp_path, fault):
    """RC12-02 gate (a), API level: failures during schema rebuild
    (immediate) and after the reseed (final step) both roll back the
    whole reset and return structured RESET_FAILED; a retry then
    succeeds."""
    store, client = _api_client(tmp_path)
    try:
        with client:
            h, run_id, counts = _run_a1_and_snapshot(store, client)
            orig = store._seed_statements
            if fault == "seed-immediate":

                def failing(conn):
                    raise RuntimeError("injected schema-rebuild failure")

            else:

                def failing(conn):
                    orig(conn)
                    raise RuntimeError("injected post-seed failure")

            store._seed_statements = failing
            try:
                resp = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
            finally:
                store._seed_statements = orig
            assert resp.status_code == 500, resp.text
            assert resp.json()["error"]["code"] == "RESET_FAILED", resp.text
            assert _table_counts(store.path) == counts
            assert store.one("SELECT id FROM runs WHERE id=?", (run_id,)) is not None
            assert glob.glob(str(tmp_path / "*.tmp")) == []
            resp = client.post("/api/v1/lab/reset", headers=h, json={"confirm": True})
            assert resp.status_code == 200, resp.text
            assert resp.json()["records"] == 48
    finally:
        _close_store(store)


def test_rc1202_store_reset_rolls_back_directly(tmp_path):
    """RC12-02 at the Store layer, independent of the API handler: a
    Store.reset whose session preservation raises leaves the old
    rows readable on the SAME connection after rollback, and a later
    reset on the same Store succeeds."""
    store = Store(str(tmp_path / "direct.db"))
    try:
        store.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "run-old",
                "A1",
                "completed",
                "PASS",
                "scripted",
                "protected",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:01:00Z",
                "{}",
                "cli",
                "northstar",
                "[]",
                "incident_commander",
                None,
                None,
                "1.0.0",
                "v3-test",
            ),
        )
        assert _raw(store.path, "SELECT COUNT(*) FROM runs") == 1
        orig = store._preserve_session

        def boom(conn, session):
            raise RuntimeError("injected session-preservation failure")

        store._preserve_session = boom
        try:
            with pytest.raises(RuntimeError):
                store.reset(preserve_session=("tok", "incident_commander", None))
        finally:
            store._preserve_session = orig
        assert _raw(store.path, "SELECT COUNT(*) FROM runs") == 1
        assert _raw(store.path, "SELECT COUNT(*) FROM cases") == 4
        n = store.reset(preserve_session=("tok", "incident_commander", None))
        assert n == 48
        assert _raw(store.path, "SELECT COUNT(*) FROM runs") == 0
        assert _raw(store.path, "SELECT COUNT(*) FROM sessions") == 1
    finally:
        _close_store(store)


def test_rc1202_successful_reset_contract(tmp_path):
    """RC12-02 gate (b)/(c): an ordinary successful reset gives 48
    synthetic records and preserves ONLY the calling admin session;
    the pre-reset backup is valid, 0600, and contains the old run."""
    store, client = _api_client(tmp_path)
    try:
        with client:
            h, run_id, _ = _run_a1_and_snapshot(store, client)
            other = _session_header(client, "analyst_northstar")
            resp = client.post("/api/v1/lab/reset", headers=h, json={"confirm": True})
            assert resp.status_code == 200, resp.text
            assert resp.json()["records"] == 48
            assert resp.json()["reset"] is True
            counts = _table_counts(store.path)
            assert counts["runs"] == 0
            assert counts["events"] == 0
            assert counts["drafts"] == 0
            assert counts["isolations"] == 0
            assert counts["sessions"] == 1
            assert client.get("/api/v1/overview", headers=h).status_code == 200
            assert client.get("/api/v1/overview", headers=other).status_code == 401
            backups = glob.glob(str(tmp_path / "*.bak"))
            assert len(backups) == 1
            assert _mode(backups[0]) == 0o600
            assert _raw(backups[0], "SELECT COUNT(*) FROM runs") == 1
            assert _raw(backups[0], "SELECT id FROM runs LIMIT 1") == run_id
    finally:
        _close_store(store)


# -- RC12-02 gate: a failed reset must not invalidate idempotency --


class _ImmediateStub:
    """Minimal stub provider: every request returns the same
    gateway-allowed open proposal immediately (no barrier)."""

    def __init__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                body = json.dumps(
                    {
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
                                                # Same approval-gated proposal
                                                # the eighth-audit stub uses:
                                                # it is never executed
                                                # without an approval, so
                                                # the run terminates with
                                                # the lab state unchanged.
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
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()


def _poll_terminal(client, headers, run_id, timeout=60):
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
    # just after the terminal row commit; wait for it so the
    # lifecycle guard sees a quiescent process at teardown.
    deadline = time.time() + 5
    while time.time() < deadline:
        if Store._live_count <= 1:
            break
        time.sleep(0.05)
    return last


def test_rc1202_failed_reset_preserves_idempotency(tmp_path, monkeypatch):
    """RC12-02: idempotency records are cleared ONLY after a
    successful commit. A real-mode run launched with an
    Idempotency-Key, followed by a failed reset, must still replay
    the original run id; after a successful reset the same key
    launches fresh (the run row is gone)."""
    stub = _ImmediateStub()
    try:
        monkeypatch.setenv("AGENTBOUNDARY_LLM_LOCAL_OLLAMA", "1")
        monkeypatch.setenv(
            "AGENTBOUNDARY_LLM_BASE_URL", f"http://127.0.0.1:{stub.port}/v1"
        )
        monkeypatch.setenv("AGENTBOUNDARY_LLM_MODEL", "rc12-stub")
        monkeypatch.delenv("AGENTBOUNDARY_LLM_API_KEY", raising=False)
        store, client = _api_client(tmp_path)
        try:
            with client:
                h = _session_header(client)
                key = {**h, "Idempotency-Key": "rc12-idem-1"}
                r1 = client.post(
                    "/api/v1/runs",
                    headers=key,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r1.status_code == 202, r1.text
                run_id = r1.json()["id"]
                terminal = _poll_terminal(client, h, run_id)
                assert terminal["status"] not in ("error", "cancelled"), terminal
                orig = store._preserve_session

                def boom(conn, session):
                    raise RuntimeError("injected session-preservation failure")

                store._preserve_session = boom
                try:
                    resp = client.post(
                        "/api/v1/lab/reset", headers=h, json={"confirm": True}
                    )
                finally:
                    store._preserve_session = orig
                assert resp.status_code == 500, resp.text
                assert resp.json()["error"]["code"] == "RESET_FAILED", resp.text
                assert (
                    store.one("SELECT id FROM runs WHERE id=?", (run_id,)) is not None
                )
                # Idempotency survived the failed reset: replay.
                r2 = client.post(
                    "/api/v1/runs",
                    headers=key,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r2.status_code == 202, r2.text
                assert r2.json()["id"] == run_id
                assert _raw(store.path, "SELECT COUNT(*) FROM runs") == 1
                # Successful reset clears it: the same key launches fresh.
                resp = client.post(
                    "/api/v1/lab/reset", headers=h, json={"confirm": True}
                )
                assert resp.status_code == 200, resp.text
                r3 = client.post(
                    "/api/v1/runs",
                    headers=key,
                    json={"scenario_id": "A1", "adapter": "real_llm"},
                )
                assert r3.status_code == 202, r3.text
                assert r3.json()["id"] != run_id
                _poll_terminal(client, h, r3.json()["id"])
        finally:
            _close_store(store)
    finally:
        stub.shutdown()
