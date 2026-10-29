"""Tenth independent audit regressions (T10-01..T10-04).

Disposable tmp databases only; the demo DB is never touched. T10-01
and T10-04 tests use real uvicorn processes/threads where the finding
is about process-level ownership or concurrency; everything else is
in-process. Each test reproduces an audit repro (or the closest
honest equivalent) and asserts the FIXED behavior.
"""

import hashlib
import os
import socket
import sqlite3
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


def _runs_count(db_path):
    return _raw(db_path, "SELECT COUNT(*) FROM runs")


def _db_sha(db_path):
    return hashlib.sha256(Path(db_path).read_bytes()).hexdigest()


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


# ---------------- T10-01: lock before Store construction ----------------


def test_t1001_denied_second_app_does_not_mutate_db(tmp_path):
    """Auditor repro, exact: app A holds the lock; one runbook row is
    deleted (6 -> 5); app B constructed with the SAME path must not
    refill it, and B's denied lifespan must not touch anything. After
    A exits, B may start and legitimately repair (5 -> 6, no dupes,
    no evidence loss)."""
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    db = tmp_path / "shared.db"
    store_a, client_a = _api_client(tmp_path, "shared.db")
    try:
        with client_a:
            assert client_a.get("/api/v1/health").status_code == 200
            row = store_a.one("SELECT id FROM runbooks LIMIT 1")
            store_a.execute("DELETE FROM runbooks WHERE id=?", (row["id"],))
            assert _runbook_count(db) == 5
            before = _db_sha(db)

            # T10-01: construction alone must not mutate (pre-fix,
            # create_app(path=...) built a Store here and refilled 6).
            app_b = create_app(path=str(db))
            assert _runbook_count(db) == 5
            assert _db_sha(db) == before

            # Denied lifespan must not mutate either.
            with pytest.raises(RuntimeError), TestClient(app_b):
                pass
            assert _runbook_count(db) == 5
            assert _db_sha(db) == before
            assert _runs_count(db) == 0

            # App A is untouched and still healthy.
            assert client_a.get("/api/v1/health").status_code == 200
            assert _runbook_count(db) == 5
    finally:
        _close_store(store_a)

    # After A exits, the SAME app B object starts and repairs.
    with TestClient(app_b):
        assert _runbook_count(db) == 6
        assert _runs_count(db) == 0
    assert _runbook_count(db) == 6
    distinct = _raw(db, "SELECT COUNT(DISTINCT id) FROM runbooks")
    assert distinct == 6


def test_t1001_two_first_time_starts_only_one_succeeds(tmp_path):
    """Two simultaneous first-time starts against an empty DB: only
    one succeeds; the DB is initialized completely and consistently,
    with no partial seeding or duplication."""
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    db = tmp_path / "fresh.db"
    app_a = create_app(path=str(db))
    app_b = create_app(path=str(db))
    with TestClient(app_a) as client_a:
        assert client_a.get("/api/v1/health").json()["records"] == 48
        before = _db_sha(db)
        with pytest.raises(RuntimeError), TestClient(app_b):
            pass
        assert _db_sha(db) == before
    with TestClient(app_b) as client_b:
        assert client_b.get("/api/v1/health").json()["records"] == 48
    assert _runbook_count(db) == 6


def test_t1001_two_real_processes_lock(tmp_path):
    """T10-01(D): two REAL OS processes, not threads. Server B must
    fail startup without touching the DB; after A stops, B starts and
    repairs the deleted fixture row."""
    import httpx

    db = tmp_path / "proc.db"
    port_a = _free_port()
    port_b = _free_port()
    proc_a, log_a = _serve_uvicorn(db, port_a, tmp_path / "uv-a.log")
    try:
        assert _wait_healthy(port_a), "server A never became healthy"
        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT id FROM runbooks LIMIT 1").fetchone()[0]
        conn.execute("DELETE FROM runbooks WHERE id=?", (row,))
        conn.commit()
        conn.close()
        assert _runbook_count(db) == 5
        before = _db_sha(db)

        proc_b, log_b = _serve_uvicorn(db, port_b, tmp_path / "uv-b.log")
        try:
            deadline = time.time() + 30
            while time.time() < deadline and proc_b.poll() is None:
                time.sleep(0.25)
            assert proc_b.poll() is not None, "server B kept running"
            assert proc_b.returncode != 0, "server B exited cleanly"
            with (
                httpx.Client(timeout=5, trust_env=False) as c,
                pytest.raises(httpx.ConnectError),
            ):
                c.get(f"http://127.0.0.1:{port_b}/api/v1/health")
            assert _runbook_count(db) == 5
            assert _db_sha(db) == before
        finally:
            _stop_proc(proc_b, log_b)
        assert _wait_healthy(port_a), "server A did not stay healthy"
    finally:
        _stop_proc(proc_a, log_a)

    proc_b, log_b = _serve_uvicorn(db, port_b, tmp_path / "uv-b2.log")
    try:
        assert _wait_healthy(port_b), "server B never started after A stopped"
        assert _runbook_count(db) == 6
    finally:
        _stop_proc(proc_b, log_b)


def test_t1001_cli_refuses_before_constructing_store(tmp_path, monkeypatch):
    """CLI reset/seed against a server-held DB must refuse BEFORE
    constructing a Store: pre-fix, construction refilled the deleted
    row (5 -> 6) even though the command then exited 2. After the
    server stops, the same CLI seed repairs legitimately."""
    from agentboundary.cli import main as cli_main

    db = tmp_path / "cli.db"
    monkeypatch.setenv("AGENTBOUNDARY_DB_PATH", str(db))
    store, client = _api_client(tmp_path, "cli.db")
    try:
        with client:
            assert client.get("/api/v1/health").status_code == 200
            row = store.one("SELECT id FROM runbooks LIMIT 1")
            store.execute("DELETE FROM runbooks WHERE id=?", (row["id"],))
            assert _runbook_count(db) == 5
            before = _db_sha(db)
            assert cli_main(["reset"]) == 2
            assert _runbook_count(db) == 5
            assert _db_sha(db) == before
            assert cli_main(["seed"]) == 2
            assert _runbook_count(db) == 5
            assert _db_sha(db) == before
    finally:
        _close_store(store)
    assert cli_main(["seed"]) == 0
    assert _runbook_count(db) == 6


def test_t1001_app_without_lifespan_returns_503(tmp_path):
    """An app-owned app used without lifespan (store not yet built)
    answers 503 APP_NOT_STARTED, never a 500 AttributeError. A bare
    TestClient (no context manager) does not run lifespan, so this
    is the honest way to exercise the guard."""
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    app = create_app(path=str(tmp_path / "nolifespan.db"))
    assert not (tmp_path / "nolifespan.db").exists()
    client = TestClient(app)  # deliberately no `with` -> no lifespan
    r = client.get("/api/v1/health")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "APP_NOT_STARTED"
    # Construction alone created nothing on disk.
    assert not (tmp_path / "nolifespan.db").exists()


# ---------------- T10-02: backup tracking / privacy ----------------


def test_t1002_gitignore_covers_backups():
    """The repo .gitignore must cover reset backups and SQLite
    sidecars with narrow patterns (no overbroad wildcards that would
    hide genuine fixtures/docs). When run inside a git checkout,
    check-ignore must actually match them."""
    import subprocess

    root = _repo_root()
    text = (root / ".gitignore").read_text()
    for pattern in (
        "backend/data/*.bak",
        "*.pre-reset-*.bak",
        "backend/data/*.db-wal",
        "backend/data/*.db-shm",
        "backend/data/*.db-journal",
    ):
        assert pattern in text, f"missing .gitignore pattern: {pattern}"
    if (root / ".git").exists():
        for path in (
            "backend/data/agentboundary.db.pre-reset-20250101T000000000000.bak",
            "backend/data/agentboundary.db-wal",
            "backend/data/agentboundary.db-shm",
            "backend/data/agentboundary.db-journal",
        ):
            proc = subprocess.run(
                ["git", "check-ignore", "-v", path],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            assert proc.returncode == 0, f"not ignored: {path}: {proc.stdout}"


def test_t1002_scratch_repo_ignores_backup(tmp_path):
    """Self-contained git semantics: in a fresh repo using this
    .gitignore, a reset backup is ignored while a normal file is not.
    (Skipped only when no git binary exists to run the check.)"""
    import shutil
    import subprocess

    if shutil.which("git") is None:
        pytest.skip("git binary required to verify ignore semantics")
    repo = tmp_path / "repo"
    (repo / "backend" / "data").mkdir(parents=True)
    shutil.copy(_repo_root() / ".gitignore", repo / ".gitignore")
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    bak = (
        repo
        / "backend"
        / "data"
        / "agentboundary.db.pre-reset-20250101T000000000000.bak"
    )
    bak.write_bytes(b"fake backup with a session token")
    note = repo / "backend" / "data" / "notes.md"
    note.write_text("genuine doc")
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "pre-reset" not in status
    assert "notes.md" in status


def test_t1002_reset_backup_permissions_retention_restore(tmp_path):
    """Reset on a disposable DB: backup is restorable, private
    (0600 on POSIX), pruned to the newest 5, named by basename only,
    and leaves no .tmp behind."""
    import glob
    import shutil

    store, client = _api_client(tmp_path, "lab.db")
    try:
        with client:
            headers = _session_header(client)
            token = headers["X-Lab-Session"]
            r = client.post("/api/v1/runs", headers=headers, json={"scenario_id": "A1"})
            assert r.status_code == 200, r.text
            # Seven stale backups with staggered mtimes, then a reset.
            for i in range(7):
                fake = tmp_path / f"lab.db.pre-reset-2025010100000000000{i}.bak"
                fake.write_bytes(b"stale")
                os.utime(fake, (1000 + i * 100, 1000 + i * 100))
            r = client.post(
                "/api/v1/lab/reset", headers=headers, json={"confirm": True}
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["reset"] is True
            assert body["pruned_backups"] == 3
            assert "/" not in body["backup"]
            backups = sorted(glob.glob(str(tmp_path / "lab.db.pre-reset-*.bak")))
            assert len(backups) == 5
            new_backup = tmp_path / body["backup"]
            assert str(new_backup) in backups
            assert not (tmp_path / "lab.db.pre-reset-20250101000000000000.bak").exists()
            assert not (tmp_path / "lab.db.pre-reset-20250101000000000001.bak").exists()
            assert not (tmp_path / "lab.db.pre-reset-20250101000000000002.bak").exists()
            assert glob.glob(str(tmp_path / "*.tmp")) == []
            if os.name == "posix":
                assert os.stat(new_backup).st_mode & 0o777 == 0o600
            # Restore proof: the backup genuinely holds pre-reset state.
            restored = tmp_path / "restored.db"
            shutil.copy(new_backup, restored)
            check = Store(str(restored))
            try:
                assert check.one("SELECT COUNT(*) AS n FROM runs")["n"] == 1
                row = check.one("SELECT * FROM sessions WHERE token=?", (token,))
                assert row is not None
            finally:
                check.close()
    finally:
        _close_store(store)


# ---------------- T10-04: verified SQLite backups ----------------


def test_t1004_reset_backup_is_verified_sqlite_backup(tmp_path):
    """Reset backup must be a verified online backup: integrity ok,
    all tables present, runs/events/sessions counts matching the
    pre-reset state — and restorable as a working lab DB."""
    import shutil

    store, client = _api_client(tmp_path, "lab.db")
    try:
        with client:
            headers = _session_header(client)
            for sid in ("A1", "A2", "A3"):
                r = client.post(
                    "/api/v1/runs", headers=headers, json={"scenario_id": sid}
                )
                assert r.status_code == 200, r.text
            pre_runs = store.one("SELECT COUNT(*) AS n FROM runs")["n"]
            pre_events = store.one("SELECT COUNT(*) AS n FROM events")["n"]
            assert pre_runs == 3
            assert pre_events > 0
            r = client.post(
                "/api/v1/lab/reset", headers=headers, json={"confirm": True}
            )
            assert r.status_code == 200, r.text
            backup = tmp_path / r.json()["backup"]
            assert backup.exists()
            # Read-only verification, independent of the app Store.
            conn = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
            try:
                assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                for table in (
                    "cases",
                    "alerts",
                    "runbooks",
                    "runs",
                    "events",
                    "sessions",
                ):
                    assert table in tables
                assert (
                    conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == pre_runs
                )
                assert (
                    conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                    == pre_events
                )
                assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
            finally:
                conn.close()
            restored = tmp_path / "restored.db"
            shutil.copy(backup, restored)
            check = Store(str(restored))
            try:
                assert check.one("SELECT COUNT(*) AS n FROM runs")["n"] == 3
            finally:
                check.close()
    finally:
        _close_store(store)


def test_t1004_session_and_launch_blocked_during_reset(tmp_path, monkeypatch):
    """While a reset's verified backup is in progress, session
    creation and launches (either adapter) fail with a retryable 409
    — they must not write into the snapshot. After the reset, both
    work again. Driven over real HTTP against an in-process uvicorn
    server thread so requests are truly concurrent."""
    import httpx
    import uvicorn

    import agentboundary.api.app as app_module

    db = tmp_path / "conc.db"
    store = Store(str(db))
    app = app_module.create_app(store=store)
    port = _free_port()
    started = threading.Event()
    release = threading.Event()
    orig = app_module.verified_backup

    def blocking(src, tmp):
        started.set()
        assert release.wait(timeout=30), "reset backup was not released"
        return orig(src, tmp)

    monkeypatch.setattr(app_module, "verified_backup", blocking)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}/api/v1"
        assert _wait_healthy(port), "uvicorn thread never became healthy"
        with httpx.Client(timeout=30, trust_env=False) as c:
            r = c.post(f"{base}/lab/session", json={"persona_id": "incident_commander"})
            assert r.status_code == 200, r.text
            headers = {"X-Lab-Session": r.json()["session_token"]}
            # Sanity: sessions work before the reset.
            assert (
                c.post(
                    f"{base}/lab/session", json={"persona_id": "analyst_northstar"}
                ).status_code
                == 200
            )
            result = {}

            def do_reset():
                resp = c.post(
                    f"{base}/lab/reset", headers=headers, json={"confirm": True}
                )
                result["status"] = resp.status_code
                result["body"] = resp.json()

            reset_thread = threading.Thread(target=do_reset)
            reset_thread.start()
            assert started.wait(timeout=30), "reset backup never started"
            r = c.post(f"{base}/lab/session", json={"persona_id": "analyst_northstar"})
            assert r.status_code == 409
            assert r.json()["error"]["code"] == "RESET_IN_PROGRESS"
            r = c.post(f"{base}/runs", headers=headers, json={"scenario_id": "A1"})
            assert r.status_code == 409
            assert r.json()["error"]["code"] == "RESET_IN_PROGRESS"
            release.set()
            reset_thread.join(timeout=30)
            assert not reset_thread.is_alive()
            assert result["status"] == 200, result
            assert (
                c.post(
                    f"{base}/lab/session", json={"persona_id": "analyst_northstar"}
                ).status_code
                == 200
            )
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        _close_store(store)


def test_t1004_backup_failure_refuses_reset_old_db_usable(tmp_path, monkeypatch):
    """A backup write failure refuses the reset (500) and leaves the
    old DB fully usable: runs intact, further launches succeed, no
    backup and no partial file created."""
    import glob

    import agentboundary.api.app as app_module
    from agentboundary.store import BackupError

    db = tmp_path / "lab.db"
    store, client = _api_client(tmp_path, "lab.db")
    try:
        with client:
            headers = _session_header(client)
            r = client.post("/api/v1/runs", headers=headers, json={"scenario_id": "A1"})
            assert r.status_code == 200, r.text

            def failing(src, tmp):
                raise BackupError("simulated disk failure")

            monkeypatch.setattr(app_module, "verified_backup", failing)
            r = client.post(
                "/api/v1/lab/reset", headers=headers, json={"confirm": True}
            )
            assert r.status_code == 500
            assert r.json()["error"]["code"] == "RESET_BACKUP_FAILED"
            assert glob.glob(str(tmp_path / "*.bak")) == []
            assert glob.glob(str(tmp_path / "*.tmp")) == []
            assert _runs_count(db) == 1
            r = client.post("/api/v1/runs", headers=headers, json={"scenario_id": "A2"})
            assert r.status_code == 200, r.text
            assert _runs_count(db) == 2
    finally:
        _close_store(store)


def test_t1004_interrupted_backup_cleans_tmp_old_db_usable(tmp_path, monkeypatch):
    """A backup that writes a partial tmp file then fails must clean
    the tmp file and leave the old DB untouched (no partial reset)."""
    import glob
    from pathlib import Path as _Path

    import agentboundary.api.app as app_module
    from agentboundary.store import BackupError

    db = tmp_path / "lab.db"
    store, client = _api_client(tmp_path, "lab.db")
    try:
        with client:
            headers = _session_header(client)
            r = client.post("/api/v1/runs", headers=headers, json={"scenario_id": "A1"})
            assert r.status_code == 200, r.text

            def interrupted(src, tmp):
                _Path(tmp).write_bytes(b"partial backup bytes")
                raise BackupError("interrupted mid-backup")

            monkeypatch.setattr(app_module, "verified_backup", interrupted)
            r = client.post(
                "/api/v1/lab/reset", headers=headers, json={"confirm": True}
            )
            assert r.status_code == 500
            assert r.json()["error"]["code"] == "RESET_BACKUP_FAILED"
            assert glob.glob(str(tmp_path / "*.tmp")) == []
            assert glob.glob(str(tmp_path / "*.bak")) == []
            assert _runs_count(db) == 1
            assert client.get("/api/v1/health").status_code == 200
    finally:
        _close_store(store)
