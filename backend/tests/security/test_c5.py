"""C5 (LOW, formerly documented residual): rename after lock
acquisition yields a second lock holder.

Two demonstrated variants, both proven with REAL INDEPENDENT OS
PROCESSES (uvicorn subprocesses), never threads or mocks:

- C5-A (lock-file rename): owner A holds flock on ``actual.db`` +
  ``actual.db.applock``. The ``.applock`` directory entry is renamed
  while A runs. Process B starts against the same DB path, creates a
  NEW ``.applock`` inode, and (on the vulnerable baseline) becomes a
  second owner of the same SQLite database.
- C5-B (database-file rename): owner A holds a pathname-derived
  lock. The database file itself is renamed (same directory, and
  separately across directories on the same filesystem). Process B
  starts against the relocated inode under its new pathname and (on
  the vulnerable baseline) obtains a different pathname-derived lock
  for the SAME SQLite inode.

Patched success condition (both variants): NO second owner can
construct a Store, seed, repair, migrate, launch, reset, or report
readiness for the same underlying database while A is active. B
must fail closed in bounded time with a clear error, must never
silently create a new authoritative owner, and must leave the
database byte-identical (no T10-01 pre-lock seeding/repair side
effect). After A exits, a legitimate owner can restart.

POSIX/Linux only: the fix relies on flock on an open file
description, which is inode-bound. Skipped on non-POSIX platforms
(the supported backend target is Linux; see the report).

Test hygiene: every server subprocess is terminated (then killed)
in a finally block; health polls and process waits are bounded;
httpx clients use ``trust_env=False`` (loopback proxy trap);
database snapshots use read-only SQLite URIs so the snapshot
itself cannot mutate the database.
"""

import hashlib
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.parse

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="C5 inode-lock tests require POSIX flock"
)

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
TABLES = [
    "tenants",
    "personas",
    "cases",
    "alerts",
    "timeline_events",
    "runbooks",
    "approvals",
    "assets",
    "drafts",
    "isolations",
    "runs",
    "events",
    "sessions",
]


def _free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def _client():
    return httpx.Client(timeout=10, trust_env=False)


def _db_snapshot(db_path):
    """Row counts per table (read-only) plus the file SHA-256.

    A refused second owner must leave every count and the file bytes
    unchanged; a seeding/repairing second owner would wipe sessions
    and runs even if fixture counts look identical afterwards.
    """
    uri = "file:" + urllib.parse.quote(str(db_path)) + "?mode=ro"
    counts = {}
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            for table in TABLES:
                try:
                    counts[table] = conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                except sqlite3.Error:
                    counts[table] = None
        finally:
            conn.close()
    except sqlite3.Error:
        counts = {"unreadable": True}
    digest = None
    try:
        with open(db_path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        digest = None
    return {"counts": counts, "sha": digest}


class _Server:
    """One real uvicorn subprocess owning one disposable database."""

    def __init__(self, db_path, tmp_path, tag):
        self.db_path = str(db_path)
        self.port = _free_port()
        self.log_path = str(tmp_path / f"{tag}.log")
        self.proc = None

    def start(self, expect_healthy=True, timeout=60):
        env = dict(os.environ, AGENTBOUNDARY_DB_PATH=self.db_path)
        logf = open(self.log_path, "wb")  # noqa: SIM115
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "agentboundary.api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=BACKEND_DIR,
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
        self._logf = logf
        if expect_healthy:
            self.wait_healthy(timeout=timeout)
        return self

    def wait_healthy(self, timeout=60):
        deadline = time.time() + timeout
        with _client() as client:
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    raise AssertionError(
                        f"server on port {self.port} exited early "
                        f"(code {self.proc.returncode}); log tail:\n" + self._log_tail()
                    )
                try:
                    if (
                        client.get(
                            f"http://127.0.0.1:{self.port}/api/v1/health"
                        ).status_code
                        == 200
                    ):
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.25)
        raise AssertionError(
            f"server on port {self.port} never became healthy; log tail:\n"
            + self._log_tail()
        )

    def wait_exit(self, timeout=30):
        """Wait for the process to exit; returns its exit code."""
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AssertionError(
                f"server on port {self.port} did not exit within "
                f"{timeout}s (still running); log tail:\n" + self._log_tail()
            )

    def is_healthy(self):
        try:
            with _client() as client:
                return (
                    client.get(
                        f"http://127.0.0.1:{self.port}/api/v1/health"
                    ).status_code
                    == 200
                )
        except httpx.HTTPError:
            return False

    def create_session(self, persona_id="analyst_northstar"):
        with _client() as client:
            resp = client.post(
                f"http://127.0.0.1:{self.port}/api/v1/lab/session",
                json={"persona_id": persona_id},
            )
            assert resp.status_code == 200, resp.text
            return resp.json()["session_token"]

    def _log_tail(self, nbytes=4000):
        try:
            with open(self.log_path, "rb") as fh:
                data = fh.read()
            return data[-nbytes:].decode("utf-8", "replace")
        except OSError:
            return "<log unreadable>"

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        try:
            self._logf.close()
        except Exception:  # noqa: BLE001, S110 - teardown is best-effort
            pass


def test_c5a_lock_file_rename_refuses_second_owner(tmp_path):
    """C5-A: renaming the .applock entry must not admit a second owner."""
    db = tmp_path / "actual.db"
    owner = _Server(db, tmp_path, "c5a-owner")
    second = None
    try:
        owner.start()
        owner.create_session()
        before = _db_snapshot(db)
        assert before["counts"]["sessions"] == 1
        # The attack: rename the lock-file directory entry out from
        # under the running owner. A still holds flock on the OLD
        # inode; a pathname-derived scheme would let B lock a fresh
        # inode and become a second owner.
        lock_path = str(db) + ".applock"
        moved_lock = lock_path + ".moved"
        os.rename(lock_path, moved_lock)
        assert not os.path.exists(lock_path)
        second = _Server(db, tmp_path, "c5a-second")
        second.start(expect_healthy=False)
        code = second.wait_exit(timeout=30)
        assert code != 0, (
            "second owner must fail closed (nonzero exit) after the "
            f"lock-file rename; got exit code {code} with log:\n" + second._log_tail()
        )
        assert not second.is_healthy()
        assert owner.is_healthy()
        after = _db_snapshot(db)
        assert after == before, (
            "refused second owner must not mutate the database: "
            f"before={before} after={after}"
        )
    finally:
        if second is not None:
            second.stop()
        owner.stop()
    # Recovery: after the legitimate owner exits, a fresh owner can
    # start on the same database (no stale permanent denial).
    retry = _Server(db, tmp_path, "c5a-retry")
    try:
        retry.start()
        assert retry.is_healthy()
    finally:
        retry.stop()


def test_c5b_db_rename_same_directory_refuses_second_owner(tmp_path):
    """C5-B (same directory): renaming the DB file must not admit a
    second owner for the same SQLite inode."""
    db = tmp_path / "owner.db"
    moved = tmp_path / "owner-moved.db"
    owner = _Server(db, tmp_path, "c5b-owner")
    second = None
    try:
        owner.start()
        owner.create_session()
        before = _db_snapshot(db)
        assert before["counts"]["sessions"] == 1
        os.rename(db, moved)
        assert not os.path.exists(db)
        assert owner.is_healthy()
        second = _Server(moved, tmp_path, "c5b-second")
        second.start(expect_healthy=False)
        code = second.wait_exit(timeout=30)
        assert code != 0, (
            "second owner must fail closed (nonzero exit) for the "
            f"relocated inode; got exit code {code} with log:\n" + second._log_tail()
        )
        assert not second.is_healthy()
        assert owner.is_healthy()
        after = _db_snapshot(moved)
        assert after == before, (
            "refused second owner must not mutate the relocated "
            f"database: before={before} after={after}"
        )
    finally:
        if second is not None:
            second.stop()
        owner.stop()
    os.rename(moved, db)
    retry = _Server(db, tmp_path, "c5b-retry")
    try:
        retry.start()
        assert retry.is_healthy()
    finally:
        retry.stop()


def test_c5b_db_rename_cross_directory_refuses_second_owner(tmp_path):
    """C5-B (cross directory): moving the DB to another directory on
    the same filesystem must not admit a second owner either."""
    other = tmp_path / "other"
    other.mkdir()
    db = tmp_path / "owner.db"
    moved = other / "owner.db"
    owner = _Server(db, tmp_path, "c5bx-owner")
    second = None
    try:
        owner.start()
        owner.create_session()
        before = _db_snapshot(db)
        assert before["counts"]["sessions"] == 1
        os.rename(db, moved)
        assert owner.is_healthy()
        second = _Server(moved, tmp_path, "c5bx-second")
        second.start(expect_healthy=False)
        code = second.wait_exit(timeout=30)
        assert code != 0, (
            "second owner must fail closed (nonzero exit) for the "
            f"cross-directory relocated inode; got exit code {code} "
            f"with log:\n" + second._log_tail()
        )
        assert not second.is_healthy()
        after = _db_snapshot(moved)
        assert after == before
    finally:
        if second is not None:
            second.stop()
        owner.stop()
    os.rename(moved, db)
    retry = _Server(db, tmp_path, "c5bx-retry")
    try:
        retry.start()
        assert retry.is_healthy()
    finally:
        retry.stop()


def test_c5_burst_exactly_one_owner(tmp_path):
    """Matrix 13: an 8-process startup burst on one DB yields exactly
    one owner; every loser fails without mutating the database."""
    db = tmp_path / "burst.db"
    servers = [_Server(db, tmp_path, f"burst-{i}") for i in range(8)]
    try:
        for srv in servers:
            srv.start(expect_healthy=False)
        deadline = time.time() + 60
        healthy = []
        while time.time() < deadline:
            healthy = [srv for srv in servers if srv.is_healthy()]
            exited = [srv for srv in servers if srv.proc.poll() is not None]
            if len(healthy) == 1 and len(exited) == 7:
                break
            time.sleep(0.25)
        healthy = [srv for srv in servers if srv.is_healthy()]
        assert len(healthy) == 1, (
            f"burst must yield exactly one healthy owner, got {len(healthy)}"
        )
        for srv in servers:
            if srv is not healthy[0]:
                code = srv.wait_exit(timeout=30)
                assert code != 0, f"loser must exit nonzero, got {code}"
        snap = _db_snapshot(db)
        assert snap["counts"]["runs"] == 0
    finally:
        for srv in servers:
            srv.stop()


def test_c5_different_databases_start_independently(tmp_path):
    """Matrix 10: the fix must not serialize a directory — two
    DIFFERENT database files in the same directory start at once."""
    a = _Server(tmp_path / "a.db", tmp_path, "diff-a")
    b = _Server(tmp_path / "b.db", tmp_path, "diff-b")
    try:
        a.start()
        b.start()
        assert a.is_healthy() and b.is_healthy()
    finally:
        b.stop()
        a.stop()


def test_c5_cli_refused_while_api_owner(tmp_path):
    """Matrix 8: a CLI mutating command against an API-owned database
    is refused (exit 2) before any Store construction."""
    db = tmp_path / "cli.db"
    owner = _Server(db, tmp_path, "cli-owner")
    try:
        owner.start()
        env = dict(os.environ, AGENTBOUNDARY_DB_PATH=str(db))
        proc = subprocess.run(
            [sys.executable, "-m", "agentboundary.cli", "seed"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert proc.returncode == 2, (
            f"CLI seed against an owned DB must exit 2, got "
            f"{proc.returncode}: {proc.stderr[-2000:]}"
        )
        assert "Refused" in proc.stderr
        assert owner.is_healthy()
    finally:
        owner.stop()


def test_c5_app_start_against_held_lock_refused(tmp_path):
    """Matrix 9 (same primitive as a CLI owner): while
    try_acquire_db_lock is held in-process, a server subprocess on
    the same database must fail closed — the API and CLI share one
    arbitration primitive, so holding it simulates a CLI owner."""
    from agentboundary.store import try_acquire_db_lock

    db = tmp_path / "held.db"
    lock = try_acquire_db_lock(str(db))
    assert lock is not None
    server = None
    try:
        server = _Server(db, tmp_path, "held-second")
        server.start(expect_healthy=False)
        code = server.wait_exit(timeout=30)
        assert code != 0
        assert not server.is_healthy()
    finally:
        if server is not None:
            server.stop()
        lock.close()
    retry = _Server(db, tmp_path, "held-retry")
    try:
        retry.start()
        assert retry.is_healthy()
    finally:
        retry.stop()


def test_c5_sigkill_releases_lock_no_stale_denial(tmp_path):
    """Matrix 12: after SIGKILL (no cleanup handlers run), the kernel
    releases the flock and a fresh owner starts; no stale denial."""
    db = tmp_path / "kill.db"
    owner = _Server(db, tmp_path, "kill-owner")
    owner.start()
    owner.create_session()
    before = _db_snapshot(db)
    owner.proc.kill()
    owner.proc.wait(timeout=15)
    try:
        owner._logf.close()
    except Exception:  # noqa: BLE001, S110 - teardown is best-effort
        pass
    owner.proc = None
    retry = _Server(db, tmp_path, "kill-retry")
    try:
        retry.start()
        assert retry.is_healthy()
        after = _db_snapshot(db)
        # The killed owner's session row survives; startup recovery
        # must not invent or erase research rows (no runs existed).
        assert after["counts"]["runs"] == 0
        assert after["counts"]["sessions"] == before["counts"]["sessions"]
    finally:
        retry.stop()


def test_c5_fresh_nested_db_starts_cleanly(tmp_path):
    """Matrix 11: a new database in a fresh nested directory starts
    cleanly with owner-only file permissions."""
    db = tmp_path / "fresh" / "nested" / "lab.db"
    server = _Server(db, tmp_path, "nested-owner")
    try:
        server.start()
        assert server.is_healthy()
        assert db.exists()
        assert oct(os.stat(db).st_mode & 0o777) == "0o600"
    finally:
        server.stop()
