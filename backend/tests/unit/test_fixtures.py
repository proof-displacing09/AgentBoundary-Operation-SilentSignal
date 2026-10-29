from agentboundary.fixtures.data import CEDAR_SENTINEL
from agentboundary.store import Store


def test_record_count_at_least_30(store):
    assert store.record_count() >= 30


def test_required_cases_exist(store):
    for cid in ("INC-2048", "INC-2051", "INC-3307", "INC-3310"):
        assert store.get_case(cid) is not None
    assert CEDAR_SENTINEL in store.get_case("INC-3307")["summary"]


def test_timeline_for_inc2048(store):
    ev = store.timeline_for_case("INC-2048")
    assert len(ev) >= 8
    poisoned = [e for e in ev if e["classification"] == "poisoned_log_field"]
    assert len(poisoned) == 1 and poisoned[0]["trust_label"] == "untrusted"


def test_fixture_determinism_and_reset(tmp_path):
    # N-06: close both stores (previously leaked connections at GC).
    a = Store(str(tmp_path / "a.db"))
    b = Store(str(tmp_path / "b.db"))
    try:
        assert a.all("SELECT * FROM cases ORDER BY id") == b.all(
            "SELECT * FROM cases ORDER BY id"
        )
        assert a.all("SELECT * FROM approvals ORDER BY id") == b.all(
            "SELECT * FROM approvals ORDER BY id"
        )
        a.execute("UPDATE cases SET status='closed' WHERE id='INC-2048'")
        a.reset()
        assert a.get_case("INC-2048")["status"] == "investigating"
    finally:
        a.close()
        b.close()


def test_fake_ips_and_domains(store):
    blob = " ".join(e["content"] for e in store.all("SELECT * FROM timeline_events"))
    assert "192.0.2." in blob and ".example" in blob


def test_approval_fixtures_cover_variants(store):
    ids = {r["id"] for r in store.all("SELECT * FROM approvals")}
    assert {
        "APR-EXPIRED",
        "APR-WRONG-TENANT",
        "APR-WRONG-REQUESTER",
        "APR-WRONG-ACTION",
        "APR-WRONG-TARGET",
        "APR-USED",
        "APR-VALID",
    } <= ids
    assert len(ids) >= 8  # includes APR-WRONG-APPROVER
