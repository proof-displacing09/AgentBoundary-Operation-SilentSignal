"""Eleventh independent audit regressions (A11-01..A11-04).

Disposable tmp databases only; the demo DB is never touched. A11-01
uses two real OS processes where the finding is about process-level
ownership under pathname aliases; A11-02 samples temp backup
permissions while a backup is genuinely in progress; A11-03/A11-04
use fault injection. Each test reproduces an audit repro (or the
closest honest equivalent) and asserts the FIXED behavior.

New-symbol imports (canonical_db_path) are resolved via getattr
inside the tests that need them, so a pre-fix tree fails these tests
instead of failing collection — the stash round-trip stays a real
failing-first proof.
"""

import glob
import hashlib
import os
import socket
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from agentboundary.store import Store


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


class _ProxiedSrcConnection:
    """Proxy for a real sqlite3 connection with a slow or failing
    backup(). sqlite3.Connection is an immutable C type, so its
    backup() method cannot be monkeypatched; instead these tests
    patch sqlite3.connect to return this proxy for the SOURCE
    connection only (the first connect call inside verified_backup).
    Every other call delegates to the real connection, so counts,
    integrity checks, and closes behave exactly as in production."""

    def __init__(self, real, delay=0, error=None):
        self._real = real
        self._delay = delay
        self._error = error

    def execute(self, *args, **kwargs):
        return self._real.execute(*args, **kwargs)

    def close(self):
        return self._real.close()

    def backup(self, *args, **kwargs):
        if self._delay:
            time.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._real.backup(*args, **kwargs)


def _patch_src_connection(monkeypatch, delay=0, error=None):
    """Patch sqlite3.connect so its first call returns a proxied
    source connection (slow or failing backup) and later calls are
    real. Callers must install this immediately before the backup
    under test: any earlier sqlite3.connect (e.g. a _raw read) would
    consume the first-call slot."""
    real_connect = sqlite3.connect
    state = {"calls": 0}

    def patched(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        state["calls"] += 1
        if state["calls"] == 1:
            return _ProxiedSrcConnection(conn, delay=delay, error=error)
        return conn

    monkeypatch.setattr(sqlite3, "connect", patched)


# ---------------- A11-01: symlink aliases share one lock ----------------


def test_a1101_two_testclient_lifespans_alias_denied(tmp_path):
    """Auditor repro, exact: app A holds the lock on the real path;
    app B on a symlink alias to the SAME inode must be denied (pre-fix
    both returned /health 200). Denied B must not mutate any row, and
    A stays healthy."""
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    real = tmp_path / "actual.db"
    alias = tmp_path / "friendly.db"
    store_a, client_a = _api_client(tmp_path, "actual.db")
    try:
        with client_a:
            assert client_a.get("/api/v1/health").status_code == 200
            assert _runbook_count(real) == 6
            alias.symlink_to(real)
            assert real.samefile(alias)
            before = _db_sha(real)

            app_b = create_app(path=str(alias))
            with pytest.raises(RuntimeError), TestClient(app_b):
                pass
            assert _runbook_count(real) == 6
            assert _db_sha(real) == before
            assert client_a.get("/api/v1/health").status_code == 200
    finally:
        _close_store(store_a)

    # After A exits, the SAME alias app object starts and is healthy.
    with TestClient(app_b) as client_b:
        assert client_b.get("/api/v1/health").status_code == 200
        assert _runbook_count(real) == 6


def test_a1101_two_real_processes_alias_denied_then_alias_succeeds(tmp_path):
    """A11-01(D): two REAL OS processes. Server B on the symlink alias
    must fail startup without touching the DB while A (real path)
    runs; after A stops, B on the alias starts and repairs the deleted
    fixture row."""
    import httpx

    real = tmp_path / "actual.db"
    alias = tmp_path / "friendly.db"
    port_a = _free_port()
    port_b = _free_port()
    proc_a, log_a = _serve_uvicorn(real, port_a, tmp_path / "uv-a.log")
    try:
        assert _wait_healthy(port_a), "server A never became healthy"
        conn = sqlite3.connect(str(real))
        row = conn.execute("SELECT id FROM runbooks LIMIT 1").fetchone()[0]
        conn.execute("DELETE FROM runbooks WHERE id=?", (row,))
        conn.commit()
        conn.close()
        assert _runbook_count(real) == 5
        alias.symlink_to(real)
        assert real.samefile(alias)
        before = _db_sha(real)

        proc_b, log_b = _serve_uvicorn(alias, port_b, tmp_path / "uv-b.log")
        try:
            deadline = time.time() + 30
            while time.time() < deadline and proc_b.poll() is None:
                time.sleep(0.25)
            assert proc_b.poll() is not None, "alias server B kept running"
            assert proc_b.returncode != 0, "alias server B exited cleanly"
            with (
                httpx.Client(timeout=5, trust_env=False) as c,
                pytest.raises(httpx.ConnectError),
            ):
                c.get(f"http://127.0.0.1:{port_b}/api/v1/health")
            assert _runbook_count(real) == 5
            assert _db_sha(real) == before
            log_text = Path(tmp_path / "uv-b.log").read_text(errors="replace")
            assert "already holds" in log_text
        finally:
            _stop_proc(proc_b, log_b)
        assert _wait_healthy(port_a), "server A did not stay healthy"
    finally:
        _stop_proc(proc_a, log_a)

    proc_b, log_b = _serve_uvicorn(alias, port_b, tmp_path / "uv-b2.log")
    try:
        assert _wait_healthy(port_b), "alias server B never started after A stopped"
        assert _runbook_count(real) == 6
    finally:
        _stop_proc(proc_b, log_b)


def test_a1101_cli_alias_refused_while_server_holds_real(tmp_path, monkeypatch):
    """CLI reset/seed via the symlink alias against a server-held real
    path must refuse (exit 2) without mutating; after the server stops,
    the same CLI seed via the alias repairs legitimately."""
    from agentboundary.cli import main as cli_main

    real = tmp_path / "actual.db"
    alias = tmp_path / "friendly.db"
    monkeypatch.setenv("AGENTBOUNDARY_DB_PATH", str(alias))
    port_a = _free_port()
    proc_a, log_a = _serve_uvicorn(real, port_a, tmp_path / "uv-a.log")
    try:
        assert _wait_healthy(port_a), "server A never became healthy"
        conn = sqlite3.connect(str(real))
        row = conn.execute("SELECT id FROM runbooks LIMIT 1").fetchone()[0]
        conn.execute("DELETE FROM runbooks WHERE id=?", (row,))
        conn.commit()
        conn.close()
        assert _runbook_count(real) == 5
        alias.symlink_to(real)
        before = _db_sha(real)
        assert cli_main(["reset"]) == 2
        assert _runbook_count(real) == 5
        assert _db_sha(real) == before
        assert cli_main(["seed"]) == 2
        assert _runbook_count(real) == 5
        assert _db_sha(real) == before
    finally:
        _stop_proc(proc_a, log_a)

    assert cli_main(["seed"]) == 0
    assert _runbook_count(real) == 6


def test_a1101_canonical_identity_unit(tmp_path):
    """Canonical identity: alias == target; a new file under a
    symlinked directory resolves through the parent; :memory: passes
    through; distinct directories stay distinct."""
    import agentboundary.store as store_module

    fn = getattr(store_module, "canonical_db_path", None)
    assert fn is not None, "canonical_db_path missing (pre-fix)"
    real = tmp_path / "actual.db"
    alias = tmp_path / "friendly.db"
    Store(str(real)).close()
    alias.symlink_to(real)
    assert fn(str(alias)) == fn(str(real)) == os.path.realpath(real)
    assert fn(":memory:") == ":memory:"
    linkdir = tmp_path / "linkdir"
    linkdir.symlink_to(tmp_path, target_is_directory=True)
    assert fn(str(linkdir / "fresh.db")) == str(tmp_path / "fresh.db")
    other = tmp_path / "other.db"
    assert fn(str(other)) != fn(str(real))


def test_a1101_identity_change_during_lock_fails_closed(tmp_path, monkeypatch):
    """Fault-injected alias swap between resolution and lock: the
    acquisition must raise (fail closed) and release the lock, so a
    subsequent acquisition succeeds. try_acquire resolves the path
    three times per call (identity, lock path, revalidation), so the
    stub serves [A, A, B] for the failing call and [A, A, A] after."""
    import agentboundary.store as store_module

    real = tmp_path / "race.db"
    Store(str(real)).close()
    target_a = os.path.realpath(real)
    target_b = str(tmp_path / "swapped.db")
    calls = [target_a, target_a, target_b, target_a, target_a, target_a]

    def flipping(path):
        if calls:
            return calls.pop(0)
        return target_a

    monkeypatch.setattr(store_module, "_realpath", flipping, raising=False)
    with pytest.raises(RuntimeError, match="identity changed"):
        store_module.try_acquire_db_lock(str(real))
    # The failed acquisition released its lock: a clean one succeeds.
    lock = store_module.try_acquire_db_lock(str(real))
    assert lock is not None
    lock.close()


# ---------------- A11-02: temp backup private from creation ----------------


def test_a1102_verified_backup_tmp_is_private_under_umask_022(tmp_path):
    """Direct verified_backup under umask 022: the temp file must be
    0600 (pre-fix SQLite created it 0644), contain the live session
    row, and leave no journal sidecars behind."""
    if os.name != "posix":
        pytest.skip("POSIX file modes only")
    from agentboundary.store import verified_backup

    db = tmp_path / "lab.db"
    store = Store(str(db))
    try:
        store.execute(
            "INSERT INTO sessions VALUES (?,?,?)",
            ("tok-1", "incident_commander", "2999-01-01T00:00:00Z"),
        )
    finally:
        store.close()
    tmp = tmp_path / "lab.db.pre-reset-test.bak.tmp"
    old_umask = os.umask(0o022)
    try:
        verified_backup(str(db), str(tmp))
    finally:
        os.umask(old_umask)
    try:
        assert _mode(tmp) == 0o600
        assert _raw(tmp, "SELECT COUNT(*) FROM sessions") == 1
        assert _raw(tmp, "SELECT COUNT(*) FROM runs") == 0
        for suffix in ("-wal", "-shm", "-journal"):
            assert not os.path.exists(str(tmp) + suffix)
    finally:
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                os.unlink(str(tmp) + suffix)
            except OSError:
                pass


def test_a1102_reset_tmp_private_while_backup_in_progress(tmp_path, monkeypatch):
    """Delayed-backup regression (auditor method): while a real reset
    backup is in progress under umask 022, every observed temp file
    must already be 0600, no journal sidecar may appear, and the final
    backup must be 0600 with the session row intact and no temp left.
    Driven over real HTTP against an in-process uvicorn server thread
    (the tenth-audit concurrency pattern): a TestClient request run
    from a worker thread deadlocks the portal on the failure path,
    which hung the pre-fix run — the server thread + daemon reset
    thread cannot pin the process on any path."""
    if os.name != "posix":
        pytest.skip("POSIX file modes only")
    import httpx
    import uvicorn

    import agentboundary.api.app as app_module

    db = tmp_path / "lab.db"
    store = Store(str(db))
    app = app_module.create_app(store=store)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    old_umask = os.umask(0o022)
    result = {}
    try:
        assert _wait_healthy(port), "uvicorn thread never became healthy"
        base = f"http://127.0.0.1:{port}/api/v1"
        with httpx.Client(timeout=30, trust_env=False) as c:
            r = c.post(f"{base}/lab/session", json={"persona_id": "incident_commander"})
            assert r.status_code == 200, r.text
            headers = {"X-Lab-Session": r.json()["session_token"]}
            assert _raw(db, "SELECT COUNT(*) FROM sessions") == 1
            # Install the slow-backup proxy immediately before the
            # reset: any earlier sqlite3.connect would consume the
            # first-call slot the proxy relies on.
            _patch_src_connection(monkeypatch, delay=3)

            def do_reset():
                # Capture thread-side failures instead of leaking them
                # as "Exception in thread" noise after teardown: a
                # failure here must fail THIS test with a readable
                # assertion, never surface as collateral.
                try:
                    resp = c.post(
                        f"{base}/lab/reset", headers=headers, json={"confirm": True}
                    )
                    result["status"] = resp.status_code
                    result["body"] = resp.json()
                except Exception as exc:  # noqa: BLE001 - recorded, asserted below
                    result["thread_error"] = repr(exc)

            thread = threading.Thread(target=do_reset, daemon=True)
            thread.start()
            seen_tmp = False
            try:
                deadline = time.time() + 15
                while thread.is_alive() and time.time() < deadline:
                    for tmp in glob.glob(str(tmp_path / "*.bak.tmp")):
                        # Glob proves a temp existed at this instant.
                        # Its mode is checked whenever it can still be
                        # stat'ed — but a successful reset atomically
                        # renames it (os.replace) to the final .bak,
                        # so stat may raise FileNotFoundError between
                        # glob and stat even though nothing is wrong
                        # (QA-13-01: this exact race failed the test
                        # once in the post-twelfth audit run). That
                        # disappearance is tolerated ONLY here, and
                        # only because the end-of-test assertions
                        # below prove the rename was the successful
                        # one: exactly one final .bak, mode 0600, with
                        # the session row, reset 200, no temp left.
                        # Any other outcome still fails below, and a
                        # genuinely non-0600 mode still raises
                        # AssertionError (not FileNotFoundError).
                        seen_tmp = True
                        try:
                            assert _mode(tmp) == 0o600, (
                                f"temp backup not private: {tmp}"
                            )
                        except FileNotFoundError:
                            pass
                    for sidecar in glob.glob(str(tmp_path / "*.bak.tmp-*")):
                        raise AssertionError(f"backup sidecar on disk: {sidecar}")
                    time.sleep(0.05)
            finally:
                # Always join before server shutdown: a daemon thread
                # left in flight could raise after teardown and print
                # a confusing "Exception in thread" collateral. The
                # reset takes ~3s (slow-backup proxy), so this join
                # normally returns at once; a hung thread still fails
                # the test below instead of hanging the suite.
                thread.join(timeout=15)
            assert not thread.is_alive(), "reset thread did not finish"
            assert result.get("thread_error") is None, result
            assert seen_tmp, "never observed a temp backup during the reset"
            assert result.get("status") == 200, result
            assert result["body"]["reset"] is True
    finally:
        os.umask(old_umask)
        server.should_exit = True
        server_thread.join(timeout=15)
        _close_store(store)
    finals = glob.glob(str(tmp_path / "*.pre-reset-*.bak"))
    assert len(finals) == 1
    assert _mode(finals[0]) == 0o600
    assert _raw(finals[0], "SELECT COUNT(*) FROM sessions") == 1
    assert glob.glob(str(tmp_path / "*.bak.tmp")) == []
    assert glob.glob(str(tmp_path / "*.bak.tmp-*")) == []


# ---------------- A11-03: failed Store construction leaks nothing ----------------


@pytest.mark.parametrize(
    "method,needs_seed",
    [
        ("seed", False),
        ("_repair_missing_tables", True),
        ("_migrate", True),
        ("_ensure_fixture_integrity", True),
    ],
)
def test_a1103_failed_construction_releases_connection_and_count(
    tmp_path, monkeypatch, method, needs_seed
):
    """Auditor repro, generalized: forcing seed/migration/repair/
    fixture-validation to raise after connect must leave _live_count
    at baseline (pre-fix 0 -> 1) and a later good construction must
    succeed — for RuntimeError and for PermissionError alike."""
    db = tmp_path / "leak.db"
    if needs_seed:
        Store(str(db)).close()
    baseline = Store._live_count

    def boom(self, *args, **kwargs):
        raise RuntimeError("injected init failure")

    monkeypatch.setattr(Store, method, boom)
    with pytest.raises(RuntimeError, match="injected init failure"):
        Store(str(db))
    assert Store._live_count == baseline

    def boom_perm(self, *args, **kwargs):
        raise PermissionError("injected permission failure")

    monkeypatch.setattr(Store, method, boom_perm)
    with pytest.raises(PermissionError, match="injected permission failure"):
        Store(str(db))
    assert Store._live_count == baseline

    monkeypatch.undo()
    good = Store(str(db))
    try:
        assert _runbook_count(db) == 6
    finally:
        good.close()
    assert Store._live_count == baseline


def test_a1103_app_startup_fails_cleanly_then_succeeds(tmp_path, monkeypatch):
    """App-owned startup with a failing fixture check must fail
    cleanly (no leaked connection, lock released) and then start
    normally once the defect is removed."""
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    db = tmp_path / "appfail.db"
    baseline = Store._live_count

    def boom(self, *args, **kwargs):
        raise RuntimeError("injected fixture failure")

    monkeypatch.setattr(Store, "_ensure_fixture_integrity", boom)
    app = create_app(path=str(db))
    with pytest.raises(RuntimeError, match="injected fixture failure"), TestClient(app):
        pass
    assert Store._live_count == baseline

    monkeypatch.undo()
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
    assert Store._live_count == baseline


# ---------------- A11-04: sqlite errors keep the reset contract ----------------


def test_a1104_sqlite_error_in_backup_returns_structured_failure(tmp_path):
    """Auditor repro, exact: a backup function that writes a partial
    .tmp and raises sqlite3.OperationalError must yield structured
    RESET_BACKUP_FAILED (pre-fix: unstructured 500 + orphan .tmp),
    leave the DB byte-identical with INC-2048 investigating, clear
    the reset barrier, and allow a later successful reset."""
    from fastapi.testclient import TestClient

    import agentboundary.api.app as app_module
    from agentboundary.api.app import create_app

    db = tmp_path / "fail.db"
    store = Store(str(db))
    client = TestClient(create_app(store=store), raise_server_exceptions=False)
    orig_verified = app_module.verified_backup

    def faulty(src, tmp):
        Path(tmp).write_bytes(b"partial backup junk")
        raise sqlite3.OperationalError("injected disk I/O error")

    try:
        with client:
            headers = _session_header(client)
            # Baseline AFTER session creation: the session row itself
            # is a legitimate write; the failed reset must add none.
            before = _db_sha(db)
            app_module.verified_backup = faulty
            resp = client.post(
                "/api/v1/lab/reset", headers=headers, json={"confirm": True}
            )
            assert resp.status_code == 500, resp.text
            body = resp.json()
            assert body["error"]["code"] == "RESET_BACKUP_FAILED"
            assert str(tmp_path) not in resp.text
            assert _db_sha(db) == before
            assert _case_status(db) == "investigating"
            assert glob.glob(str(tmp_path / "*.bak.tmp")) == []
            assert glob.glob(str(tmp_path / "*.bak.tmp-*")) == []
            # Barrier cleared: a new session works immediately.
            headers2 = _session_header(client)
            assert headers2["X-Lab-Session"]
            # And a later ordinary reset succeeds.
            app_module.verified_backup = orig_verified
            resp2 = client.post(
                "/api/v1/lab/reset", headers=headers2, json={"confirm": True}
            )
            assert resp2.status_code == 200, resp2.text
            assert resp2.json()["reset"] is True
            assert glob.glob(str(tmp_path / "*.bak.tmp")) == []
    finally:
        app_module.verified_backup = orig_verified
        _close_store(store)


@pytest.mark.parametrize(
    "fault",
    ["database_error", "rename_oserror", "integrity_backup_error"],
)
def test_a1104_backup_failure_variants_keep_contract(tmp_path, monkeypatch, fault):
    """Each recognized backup failure kind — sqlite3.DatabaseError,
    os.replace OSError, BackupError from verification — must produce
    structured RESET_BACKUP_FAILED, no orphan temp, an unchanged DB,
    and a usable lab afterwards."""
    from fastapi.testclient import TestClient

    import agentboundary.api.app as app_module
    from agentboundary.api.app import create_app
    from agentboundary.store import BackupError

    db = tmp_path / f"variant-{fault}.db"
    store = Store(str(db))
    client = TestClient(create_app(store=store), raise_server_exceptions=False)
    try:
        with client:
            headers = _session_header(client)
            # Baseline AFTER session creation (see above).
            before = _db_sha(db)
            if fault == "database_error":

                def faulty(src, tmp):
                    Path(tmp).write_bytes(b"partial")
                    raise sqlite3.DatabaseError("injected database error")

                monkeypatch.setattr(app_module, "verified_backup", faulty)
            elif fault == "rename_oserror":

                def bad_replace(src, dst):
                    raise OSError("injected rename failure")

                monkeypatch.setattr(os, "replace", bad_replace)
            else:

                def faulty2(src, tmp):
                    Path(tmp).write_bytes(b"partial")
                    raise BackupError("integrity_check failed")

                monkeypatch.setattr(app_module, "verified_backup", faulty2)
            resp = client.post(
                "/api/v1/lab/reset", headers=headers, json={"confirm": True}
            )
            assert resp.status_code == 500, resp.text
            assert resp.json()["error"]["code"] == "RESET_BACKUP_FAILED"
            assert _db_sha(db) == before
            assert glob.glob(str(tmp_path / "*.bak.tmp")) == []
            assert glob.glob(str(tmp_path / "*.bak.tmp-*")) == []
            monkeypatch.undo()
            headers2 = _session_header(client)
            resp2 = client.post(
                "/api/v1/lab/reset", headers=headers2, json={"confirm": True}
            )
            assert resp2.status_code == 200, resp2.text
    finally:
        _close_store(store)


def test_a1104_verified_backup_normalizes_sqlite_errors_directly(tmp_path, monkeypatch):
    """verified_backup itself must normalize sqlite3 failures to
    BackupError (never leak a raw sqlite3.Error) and remove its own
    temp file; a missing source must refuse without creating a file."""
    from agentboundary.store import BackupError, verified_backup

    db = tmp_path / "norm.db"
    Store(str(db)).close()
    _patch_src_connection(
        monkeypatch, error=sqlite3.OperationalError("injected backup failure")
    )
    tmp = tmp_path / "norm.bak.tmp"
    with pytest.raises(BackupError, match="sqlite backup failed"):
        verified_backup(str(db), str(tmp))
    assert not os.path.exists(tmp)
    assert glob.glob(str(tmp_path / "*.bak.tmp*")) == []

    monkeypatch.undo()
    missing_tmp = tmp_path / "missing.bak.tmp"
    with pytest.raises(BackupError, match="does not exist"):
        verified_backup(str(tmp_path / "no-such.db"), str(missing_tmp))
    assert not os.path.exists(missing_tmp)
