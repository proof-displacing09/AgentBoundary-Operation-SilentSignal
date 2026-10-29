import pytest

from agentboundary.domain.personas import get_persona
from agentboundary.store import Store
from agentboundary.tools.dispatcher import Dispatcher


@pytest.fixture(autouse=True)
def _guard_store_lifecycle():
    """FA-07 regression guard: every Store opened during a test must be
    closed by the end of that test. This is the version-independent
    form of the auditor's Python 3.13 ResourceWarning check (3.12 does
    not emit sqlite3 close warnings at all, so counting is the only
    portable proof). Production paths close in lifespan/finally; test
    paths close in fixtures or try/finally."""
    before = Store._live_count
    yield
    after = Store._live_count
    assert after == before, (
        f"Store lifecycle leak: {after - before} Store connection(s) "
        "opened during this test were never closed"
    )


@pytest.fixture()
def store(tmp_path):
    s = Store(str(tmp_path / "lab.db"))
    yield s
    s.close()


@pytest.fixture()
def disp(store):
    return Dispatcher(store)


def make_ctx(persona_id, run_id="test-run", scenario_id=None, tenant_id=None):
    p = get_persona(persona_id)
    return {
        "persona": p,
        "run_id": run_id,
        "scenario_id": scenario_id,
        "tenant_id": tenant_id or (p.tenants[0] if p.tenants else None),
        "adapter": "scripted",
    }


@pytest.fixture()
def ctx_factory():
    return make_ctx


@pytest.fixture()
def client(store):
    from fastapi.testclient import TestClient

    from agentboundary.api.app import create_app

    # FR-08: context-managed TestClient so the app lifespan runs on
    # teardown (startup recovery + store close). A bare TestClient never
    # ran lifespan shutdown, leaving the app's portal/threads behind.
    with TestClient(create_app(store=store)) as c:
        yield c


@pytest.fixture()
def session(client):
    def _make(persona_id="analyst_northstar"):
        r = client.post("/api/v1/lab/session", json={"persona_id": persona_id})
        assert r.status_code == 200, r.text
        return {"X-Lab-Session": r.json()["session_token"]}

    return _make
