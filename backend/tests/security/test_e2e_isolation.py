"""R-06: Playwright E2E must never destroy (or even touch) the live demo DB.

Strategy (honest, no theatre): the test copies the CURRENT demo database
to a temp path, seeds that copy with a marker run + events, then runs the
real Playwright suite as a subprocess. The Playwright config starts its
OWN backend on run-specific free ports with its OWN temp database, so the
demo copy must be byte-identical afterwards — hash plus runs/events row
counts. A second, forced-failure run (the test backend's API port is
pre-occupied, so its server cannot bind) must also leave the copy
untouched and fail loudly instead of attaching to anything.

What the failure-path proof does and does NOT cover:
  * COVERS: occupied-port bind failure (fail loudly, no attachment, no
    demo-copy change) and post-run cleanup (no agentboundary-e2e-*.db
    file left anywhere under the repo tree). The occupant is a dummy
    HTTP server that RESPONDS: Playwright with reuseExistingServer:false
    then fails in ~3s with "already used ... set reuseExistingServer:true",
    exit 1 — verified by direct experiment.
  * DOES NOT COVER: a silent, non-responding port occupant. Observed
    2026-10-25: a listening-but-silent socket stalls Playwright's
    webServer URL poll indefinitely (pytest hit its 420s subprocess
    timeout with no failure), because the poll never receives a response
    to time out on. That is Playwright's wait behavior, not something
    this config can fix; the responding-occupant variant above is the
    honest, terminating failure injection.
  * DOES NOT COVER: killing the test backend mid-run (flaky by nature
    and deliberately not asserted here) or forcing a spec failure via
    environment (no such hook exists; a spec failure would still run
    global teardown, which is what removes the temp DB).
  * NOTE: this test proves the demo COPY is untouched. It cannot prove
    anything about the real demo DB file beyond the fact that the
    Playwright config never references it: the config's backend env sets
    AGENTBOUNDARY_DB_PATH to a tmpdir file, and the test backend never
    receives the demo path. The spec-level limit is documented in
    frontend/e2e/isolation.spec.ts.

Skipped gracefully when node/npx/Playwright are unavailable.
"""

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
FRONTEND_DIR = REPO / "frontend"
DEMO_DB = REPO / "backend" / "data" / "agentboundary.db"
RUNS_TABLE = "runs"
EVENTS_TABLE = "events"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _counts(path: Path) -> dict:
    with sqlite3.connect(str(path)) as c:
        return {
            "runs": c.execute(f"SELECT COUNT(*) FROM {RUNS_TABLE}").fetchone()[0],
            "events": c.execute(f"SELECT COUNT(*) FROM {EVENTS_TABLE}").fetchone()[0],
        }


def _seed_marker(path: Path) -> None:
    """Add one marker run + events to a demo copy, as the 'live evidence'
    whose survival the test asserts."""
    with sqlite3.connect(str(path)) as c:
        c.execute(
            "INSERT INTO runs (id, scenario_id, status, verdict, adapter, mode,"
            " started_at, finished_at, metrics, actor_id, tenant_id,"
            " operator_persona_id, simulated_actor_id, fixture_version)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "run-marker-r06",
                "A1",
                "completed",
                "PASS",
                "scripted",
                "protected",
                "2026-10-25T00:00:00Z",
                "2026-10-25T00:00:01Z",
                "{}",
                "analyst_northstar",
                "tenant_northstar",
                "analyst_northstar",
                "analyst_northstar",
                "1.0.0",
            ),
        )
        c.execute(
            "INSERT INTO events (event_id, run_id, scenario_id, seq, timestamp,"
            " actor_id, tenant_id, adapter, tool, args_sanitized, decision,"
            " reason_code, attempted, completed, disclosed_restricted)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "evt-marker-r06",
                "run-marker-r06",
                "A1",
                1,
                "2026-10-25T00:00:00Z",
                "analyst_northstar",
                "tenant_northstar",
                "scripted",
                "get_alert",
                "{}",
                "ALLOW",
                "OK",
                1,
                1,
                0,
            ),
        )
        c.commit()


def _playwright_env(api_port: int, web_port: int, keep_db: bool) -> dict:
    env = dict(os.environ)
    env["AGENTBOUNDARY_E2E_API_PORT"] = str(api_port)
    env["AGENTBOUNDARY_E2E_WEB_PORT"] = str(web_port)
    if keep_db:
        env["AGENTBOUNDARY_E2E_KEEP_DB"] = "1"
    else:
        env.pop("AGENTBOUNDARY_E2E_KEEP_DB", None)
    return env


def _run_playwright(
    env: dict, spec: str, timeout: int = 420
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["npx", "playwright", "test", spec],
        check=False,
        cwd=str(FRONTEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _require_playwright():
    if shutil.which("node") is None or shutil.which("npx") is None:
        pytest.skip("node/npx unavailable")
    if not (FRONTEND_DIR / "node_modules" / ".bin" / "playwright").exists():
        pytest.skip("Playwright not installed in frontend/node_modules")
    if not DEMO_DB.exists():
        pytest.skip("demo DB not present; nothing to protect")


def _repo_temp_dbs() -> list:
    return [p for p in REPO.rglob("agentboundary-e2e-*.db")]


def test_e2e_isolation_leaves_demo_copy_untouched(tmp_path):
    _require_playwright()
    demo_copy = tmp_path / "demo-copy.db"
    shutil.copyfile(DEMO_DB, demo_copy)
    _seed_marker(demo_copy)
    before_hash, before_counts = _sha(demo_copy), _counts(demo_copy)
    assert before_counts["runs"] >= 1 and before_counts["events"] >= 1

    # --- Passing run: full isolation spec against its own temp backend ---
    result = _run_playwright(
        _playwright_env(_free_port(), _free_port(), keep_db=True),
        "e2e/isolation.spec.ts",
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    assert _sha(demo_copy) == before_hash
    assert _counts(demo_copy) == before_counts

    # The run's own temp DB must exist under tmpdir (kept for inspection)
    # and never under the repo tree. FR-09: manifests are per main
    # process (agentboundary-e2e-manifest-<pid>.json); take the most
    # recently modified manifest whose DB still exists, so a stale
    # manifest from an earlier run can never be mistaken for this one.
    candidates = sorted(
        Path(tempfile.gettempdir()).glob("agentboundary-e2e-manifest-*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    manifests = [
        p
        for p in candidates
        if Path(json.loads(p.read_text()).get("dbPath", "")).exists()
    ]
    assert manifests, "isolated config did not publish a tmpdir manifest"
    manifest = json.loads(manifests[-1].read_text())
    temp_db = Path(manifest["dbPath"])
    assert temp_db.exists()
    assert str(temp_db).startswith(tempfile.gettempdir())
    assert REPO not in temp_db.parents
    assert _repo_temp_dbs() == []
    # The harness owns cleanup for the kept run.
    temp_db.unlink(missing_ok=True)
    manifests[-1].unlink(missing_ok=True)

    # --- Forced-failure run: API port pre-occupied -> must fail loudly ---
    # The occupant MUST respond to HTTP: a silent listener stalls
    # Playwright's webServer URL poll indefinitely (observed >420s), while
    # a responding occupant makes Playwright fail fast with "already used".
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread

    class _Dummy(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"dummy")

        def do_POST(self):
            self.send_response(501)
            self.end_headers()
            self.wfile.write(b"dummy")

        def log_message(self, *args):
            pass

    occupied = HTTPServer(("127.0.0.1", 0), _Dummy)
    occupied_port = occupied.server_address[1]
    occupied_thread = Thread(target=occupied.serve_forever, daemon=True)
    occupied_thread.start()
    try:
        failed = _run_playwright(
            _playwright_env(occupied_port, _free_port(), keep_db=False),
            "e2e/isolation.spec.ts",
        )
    finally:
        occupied.shutdown()
        occupied.server_close()
        occupied_thread.join(timeout=5)
    assert failed.returncode != 0, "occupied-port run must fail loudly, not attach"
    assert _sha(demo_copy) == before_hash
    assert _counts(demo_copy) == before_counts
    assert _repo_temp_dbs() == []


def _manifest_paths():
    return sorted(Path(tempfile.gettempdir()).glob("agentboundary-e2e-manifest-*.json"))


def test_fr09_two_concurrent_suites_use_separate_manifests_and_dbs():
    """FR-09: two Playwright suites started at the same time must each
    use and delete only their own temp DB and manifest. With
    KEEP_DB=1, teardown skips deletion so this harness can inspect
    both manifests, then owns cleanup itself."""
    _require_playwright()
    tmpdir = Path(tempfile.gettempdir())
    before_manifests = set(_manifest_paths())
    before_dbs = {p.name for p in tmpdir.glob("agentboundary-e2e-*.db")}
    env = dict(os.environ, AGENTBOUNDARY_E2E_KEEP_DB="1")
    # Staggered by 3s: each run takes ~30s, so they still overlap for
    # most of their lifetime, but their free-port allocations (bind
    # port 0, close, then bind the chosen port) cannot collide in the
    # same instant — a port race would fail a suite for reasons
    # unrelated to manifest isolation.
    import time

    procs = []
    for _ in range(2):
        procs.append(
            subprocess.Popen(
                ["npx", "playwright", "test", "e2e/isolation.spec.ts"],
                cwd=str(FRONTEND_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        )
        time.sleep(3)
    try:
        outs = [p.communicate(timeout=420)[0] for p in procs]
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
    for p, out in zip(procs, outs):
        assert p.returncode == 0, out[-4000:]
    new_manifests = [p for p in _manifest_paths() if p not in before_manifests]
    assert len(new_manifests) == 2, (
        f"expected exactly 2 new manifests, got {len(new_manifests)}: "
        f"{[p.name for p in new_manifests]}"
    )
    infos = [json.loads(p.read_text()) for p in new_manifests]
    db_paths = [Path(i["dbPath"]) for i in infos]
    api_ports = [i["apiPort"] for i in infos]
    web_ports = [i["webPort"] for i in infos]
    # Distinct identities, distinct databases, both under tmpdir.
    assert len({p.name for p in db_paths}) == 2
    assert len(set(api_ports)) == 2 and len(set(web_ports)) == 2
    for db in db_paths:
        assert db.exists()
        assert str(db).startswith(tempfile.gettempdir())
        assert REPO not in db.parents
    assert _repo_temp_dbs() == []
    # Harness-owned cleanup for the kept runs; nothing else removed.
    for p in new_manifests:
        p.unlink(missing_ok=True)
    for db in db_paths:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(db) + suffix).unlink(missing_ok=True)
    assert {p for p in _manifest_paths()} == before_manifests
    assert {p.name for p in tmpdir.glob("agentboundary-e2e-*.db")} == before_dbs
