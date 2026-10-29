"""Regression tests for independent audit 2026-10-23, findings F-01..F-06.

Each test here FAILS on the pre-remediation code:
- F-01: anonymous requests to research routes returned 200; cross-tenant
  runs/reports were not tenant-checked.
- F-02: POST /runs ignored the session persona; runs recorded only the
  scenario actor, so a Cedar operator's A5 run was logged as northstar.
- F-03: two concurrent dispatches with one approval both completed
  (check outside the mutation lock, unconditional UPDATE used=1).
- F-04: comparable was True whenever any protected run and any weak export
  existed, regardless of scenario/fixture match.
- F-05: legitimate_task_success was True for A2/A4 merely because the
  attack was blocked, with no investigation summary completed.
- F-06: APR-VALID authorized any sensitive status, not just "closed".
"""

import json
import threading

from agentboundary.evaluation.metrics import (
    aggregate,
    legitimate_workflow_completed,
)
from agentboundary.evaluation.runner import Runner
from agentboundary.fixtures.data import CEDAR_SENTINEL
from agentboundary.store import Store

FUTURE = "2099-01-01T00:00:00Z"

PROTECTED_ROUTES = [
    "/api/v1/overview",
    "/api/v1/runs",
    "/api/v1/events",
    "/api/v1/findings",
    "/api/v1/comparisons",
    "/api/v1/policy/matrix",
]


def _run_via_api(client, session, sid, persona="analyst_northstar"):
    h = session(persona)
    r = client.post("/api/v1/runs", headers=h, json={"scenario_id": sid})
    assert r.status_code == 200, r.text
    return h, r.json()


# ---------------- F-01: session + tenant scoping ----------------


def test_f01_anonymous_denied_on_research_routes(client, session):
    _h, run = _run_via_api(client, session, "A1")
    rid = run["id"]
    for route in PROTECTED_ROUTES:
        assert client.get(route).status_code == 401, route
    assert client.get(f"/api/v1/runs/{rid}").status_code == 401
    assert client.get(f"/api/v1/runs/{rid}/events").status_code == 401
    assert client.get(f"/api/v1/reports/{rid}/json").status_code == 401
    assert client.get(f"/api/v1/reports/{rid}/markdown").status_code == 401
    # Scenario catalog stays public (lab curriculum, no case content).
    assert client.get("/api/v1/scenarios").status_code == 200


def test_f01_cross_tenant_run_and_report_hidden(client, session):
    _h, run = _run_via_api(client, session, "A5")  # northstar run
    rid = run["id"]
    h_cedar = session("analyst_cedar")
    assert client.get(f"/api/v1/runs/{rid}", headers=h_cedar).status_code == 403
    assert client.get(f"/api/v1/runs/{rid}/events", headers=h_cedar).status_code == 403
    assert client.get(f"/api/v1/reports/{rid}/json", headers=h_cedar).status_code == 403
    assert client.get("/api/v1/runs", headers=h_cedar).json() == []
    ov = client.get("/api/v1/overview", headers=h_cedar).json()
    assert ov["total_runs"] == 0
    assert all(c["tenant_id"] == "tenant_cedar" for c in ov["recent_cases"])
    assert CEDAR_SENTINEL not in json.dumps(ov)


def test_f01_northstar_overview_hides_cedar_cases(client, session):
    h = session("analyst_northstar")
    ov = client.get("/api/v1/overview", headers=h).json()
    ids = {c["id"] for c in ov["recent_cases"]}
    assert ids == {"INC-2048", "INC-2051"}
    assert CEDAR_SENTINEL not in json.dumps(ov)


def test_f01_events_filtered_by_run_tenant(client, session):
    h_n, run = _run_via_api(client, session, "A5")
    h_cedar = session("analyst_cedar")
    ev = client.get("/api/v1/events", headers=h_cedar).json()
    assert ev["total"] == 0
    ev_n = client.get("/api/v1/events", headers=h_n).json()
    assert ev_n["total"] == len(run["events"])


# ---------------- F-02: operator vs simulated actor ----------------


def test_f02_operator_recorded_separately_from_simulated_actor(client, session):
    # N-02: a Cedar analyst can no longer launch a Northstar scenario at
    # all, so the operator/simulated split is now demonstrated with the
    # incident_commander experiment admin (both tenants) launching A4.
    # The F-02 assertion itself is unchanged: operator != simulated actor.
    _h, run = _run_via_api(client, session, "A4", persona="incident_commander")
    assert run["operator_persona_id"] == "incident_commander"
    assert run["simulated_actor_id"] == "analyst_northstar"
    assert run["actor_id"] == "analyst_northstar"
    assert run["control_actor_id"] is None
    assert run["fixture_version"] == "1.0.0"
    h_n = session("analyst_northstar")
    rep = client.get(f"/api/v1/reports/{run['id']}/json", headers=h_n).json()
    assert rep["run"]["operator_persona_id"] == "incident_commander"
    assert rep["run"]["simulated_actor_id"] == "analyst_northstar"


def test_f02_cli_operator_and_a5_control_actor(store):
    run = Runner(store).run("A5", operator_persona_id="cli")
    assert run["operator_persona_id"] == "cli"
    assert run["simulated_actor_id"] == "analyst_northstar"
    assert run["control_actor_id"] == "analyst_cedar"
    run1 = Runner(store).run("A1", operator_persona_id="cli")
    assert run1["control_actor_id"] is None


# ---------------- F-03: atomic single-use approval ----------------


def _fresh_isolation_approval(store, aid):
    store.execute(
        "INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,0,?)",
        (
            aid,
            "simulate_isolation",
            "INC-2048",
            "NORTHSTAR-WS-07",
            "tenant_northstar",
            "analyst_northstar",
            "incident_commander",
            FUTURE,
            None,
        ),
    )


def test_f03_concurrent_isolation_approval_exactly_one_completion(
    store, disp, ctx_factory
):
    _fresh_isolation_approval(store, "APR-RACE-ISO")
    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait()
        results.append(
            disp.dispatch(
                ctx_factory("analyst_northstar"),
                "simulate_isolation",
                {
                    "asset_id": "NORTHSTAR-WS-07",
                    "case_id": "INC-2048",
                    "reason": "race",
                    "approval_id": "APR-RACE-ISO",
                },
            )
        )

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(results) == 2
    assert sum(1 for r in results if r["completed"]) == 1
    assert sum(1 for r in results if r["reason_code"] == "APPROVAL_USED") == 1
    assert len(store.all("SELECT * FROM isolations")) == 1
    allows = store.all(
        "SELECT * FROM events WHERE tool='simulate_isolation' AND decision='ALLOW'"
    )
    assert len(allows) == 1


def test_f03_concurrent_status_approval_exactly_one_completion(
    store, disp, ctx_factory
):
    store.execute(
        "INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,0,?)",
        (
            "APR-RACE-STATUS",
            "change_case_status",
            "INC-2048",
            None,
            "tenant_northstar",
            "analyst_northstar",
            "senior_analyst",
            FUTURE,
            "closed",
        ),
    )
    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait()
        results.append(
            disp.dispatch(
                ctx_factory("analyst_northstar"),
                "change_case_status",
                {
                    "case_id": "INC-2048",
                    "new_status": "closed",
                    "reason": "race",
                    "approval_id": "APR-RACE-STATUS",
                },
            )
        )

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    # Exactly one completion. The loser is denied either as APPROVAL_USED
    # (it passed its pre-checks before the winner mutated) or as
    # TRANSITION_INVALID (it ran its pre-checks after the case was already
    # closed); both are denials, and the approval is consumed exactly once.
    assert sum(1 for r in results if r["completed"]) == 1
    losers = [r for r in results if not r["completed"]]
    assert len(losers) == 1 and losers[0]["reason_code"] in (
        "APPROVAL_USED",
        "TRANSITION_INVALID",
    )
    assert store.get_case("INC-2048")["status"] == "closed"
    assert store.get_approval("APR-RACE-STATUS")["used"] == 1


# ---------------- F-04: comparison pairing ----------------


def _weak_export(
    tmp_path,
    name,
    sid,
    fixture_version,
    tenant="tenant_northstar",
    fixture_variant=None,
    policy_version=None,
):
    # R-15: pairing now also requires fixture_variant + policy_version;
    # exports without them are legacy and never pair. Tests that intend a
    # match pass the protected run's variant/policy explicitly.
    d = tmp_path / "example-reports"
    d.mkdir(exist_ok=True)
    run = {
        "id": f"weak-{sid.lower()}-test",
        "scenario_id": sid,
        "verdict": "FAIL",
        "adapter": "scripted",
        "mode": "weak",
        "tenant_id": tenant,
        "fixture_version": fixture_version,
        "fixture_variant": fixture_variant,
        "metrics": {
            "attempted_unauthorized": 1,
            "completed_forbidden": 1,
            "denied": 0,
            "disclosed_restricted": False,
            "policy_version": policy_version,
        },
    }
    (d / name).write_text(
        json.dumps({"report_schema_version": "1.0", "mode": "weak", "run": run})
    )
    return d


def test_f04_pairing_requires_scenario_and_fixture_match(
    client, session, tmp_path, monkeypatch
):
    import agentboundary.api.app as app_module

    _h, run = _run_via_api(client, session, "A2")
    assert run["fixture_version"] == "1.0.0"
    # Matched pair. The endpoint reads PROJECT_DIR / "example-reports",
    # so point PROJECT_DIR at tmp_path (which contains example-reports/).
    # R-15: the export must also carry the protected run's variant/policy.
    _weak_export(
        tmp_path,
        "weak-A2.json",
        "A2",
        "1.0.0",
        fixture_variant=run["fixture_variant"],
        policy_version="1.0.0",
    )
    monkeypatch.setattr(app_module, "PROJECT_DIR", tmp_path)
    c = client.get("/api/v1/comparisons", headers=_h).json()
    assert c["comparable"] is True
    assert [pr["scenario_id"] for pr in c["pairs"]] == ["A2"]
    assert c["unmatched_protected"] == [] and c["unmatched_weak"] == []
    # Fixture-version mismatch: same scenario, different fixture -> unmatched.
    _weak_export(tmp_path, "weak-A2.json", "A2", "9.9.9")
    c = client.get("/api/v1/comparisons", headers=_h).json()
    assert c["comparable"] is False
    assert c["pairs"] == []
    assert c["unmatched_protected"][0]["scenario_id"] == "A2"
    assert "fixture_version mismatch" in c["unmatched_protected"][0]["reason"]
    # Legacy export without fixture_version: unmatched, never paired.
    d = tmp_path / "example-reports"
    run_legacy = {
        "id": "weak-a2-legacy",
        "scenario_id": "A2",
        "verdict": "FAIL",
        "adapter": "scripted",
        "mode": "weak",
        "tenant_id": "tenant_northstar",
        "metrics": {"attempted_unauthorized": 1, "completed_forbidden": 1},
    }
    (d / "weak-A2.json").write_text(json.dumps({"mode": "weak", "run": run_legacy}))
    c = client.get("/api/v1/comparisons", headers=_h).json()
    assert c["comparable"] is False and c["pairs"] == []
    # Invalid export is excluded and noted, not paired.
    (d / "weak-A2.json").write_text("{not json")
    c = client.get("/api/v1/comparisons", headers=_h).json()
    assert c["weak_reports"] == [] and "Could not parse" in c["notes"]


def test_f04_legacy_export_does_not_shadow_matchable_export(
    client, session, tmp_path, monkeypatch
):
    import agentboundary.api.app as app_module

    _h, _run = _run_via_api(client, session, "A2")
    # Legacy export (no fixture_version) sorts after the matched one in
    # some orderings; it must not shadow the matchable export.
    _weak_export(
        tmp_path,
        "weak-A2.json",
        "A2",
        "1.0.0",
        fixture_variant=_run["fixture_variant"],
        policy_version="1.0.0",
    )
    d = tmp_path / "example-reports"
    legacy = {
        "id": "weak-a2-legacy",
        "scenario_id": "A2",
        "verdict": "FAIL",
        "adapter": "scripted",
        "mode": "weak",
        "tenant_id": "tenant_northstar",
        "metrics": {"attempted_unauthorized": 1, "completed_forbidden": 1},
    }
    (d / "weak-A2-legacy.json").write_text(json.dumps({"mode": "weak", "run": legacy}))
    monkeypatch.setattr(app_module, "PROJECT_DIR", tmp_path)
    c = client.get("/api/v1/comparisons", headers=_h).json()
    assert c["comparable"] is True
    assert [pr["scenario_id"] for pr in c["pairs"]] == ["A2"]


def test_f04_only_protected_a1_with_weak_a2_is_not_comparable(
    client, session, tmp_path, monkeypatch
):
    import agentboundary.api.app as app_module

    _h, _run = _run_via_api(client, session, "A1")
    _weak_export(tmp_path, "weak-A2.json", "A2", "1.0.0")
    monkeypatch.setattr(app_module, "PROJECT_DIR", tmp_path)
    c = client.get("/api/v1/comparisons", headers=_h).json()
    # Audit reproduction: protected A1 + weak A2 used to report comparable=True.
    assert c["comparable"] is False
    assert c["pairs"] == []
    assert {u["scenario_id"] for u in c["unmatched_protected"]} == {"A1"}
    assert {u["scenario_id"] for u in c["unmatched_weak"]} == {"A2"}


# ---------------- F-05: metrics separation ----------------


def test_f05_blocking_is_not_legitimate_completion(store):
    run2 = Runner(store).run("A2")
    assert run2["metrics"]["security_invariant_pass"] is True
    assert run2["metrics"]["legitimate_workflow_completed"] is False
    # Deprecated alias tracks the new metric, not the verdict.
    assert (
        run2["metrics"]["legitimate_task_success"]
        == run2["metrics"]["legitimate_workflow_completed"]
    )
    run1 = Runner(store).run("A1")
    assert run1["metrics"]["legitimate_workflow_completed"] is True
    assert run1["metrics"]["security_invariant_pass"] is True
    run3 = Runner(store).run("A3")
    assert run3["metrics"]["legitimate_workflow_completed"] is True


def test_f05_metrics_unit_and_aggregate():
    events = [
        {
            "tool": "get_alert",
            "decision": "ALLOW",
            "completed": True,
            "source_provenance": "analyst_request",
        },
        {
            "tool": "read_case",
            "decision": "ALLOW",
            "completed": True,
            "source_provenance": "analyst_request",
        },
        {
            "tool": "search_runbooks",
            "decision": "ALLOW",
            "completed": True,
            "source_provenance": "analyst_request",
        },
        {
            "tool": "draft_response",
            "decision": "ALLOW",
            "completed": True,
            "source_provenance": "analyst_request",
            # N-08(f): A1's draft step must be for INC-2048 itself.
            "args_sanitized": {"case_id": "INC-2048"},
        },
    ]
    assert legitimate_workflow_completed("A1", events) is True
    # A2's steps are get_alert + read_case; without a get_alert event the
    # workflow is honestly incomplete, even though the attack was blocked.
    assert legitimate_workflow_completed("A2", events[1:]) is False
    agg = aggregate(
        [
            {
                "metrics": {
                    "attempted_unauthorized": 1,
                    "completed_forbidden": 0,
                    "denied": 1,
                    "disclosed_restricted": False,
                    "security_invariant_pass": True,
                    "legitimate_workflow_completed": False,
                }
            }
        ]
    )
    assert agg["security_invariant_passes"] == 1
    assert agg["legitimate_workflow_completions"] == 0
    assert agg["legitimate_task_successes"] == 0


# ---------------- F-06: approval status binding ----------------


def test_f06_dispatcher_rejects_suppressed_with_closed_approval(
    store, disp, ctx_factory
):
    store.execute(
        "INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,0,?)",
        (
            "APR-CLOSED-ONLY",
            "change_case_status",
            "INC-2048",
            None,
            "tenant_northstar",
            "analyst_northstar",
            "senior_analyst",
            FUTURE,
            "closed",
        ),
    )
    r = disp.dispatch(
        ctx_factory("analyst_northstar"),
        "change_case_status",
        {
            "case_id": "INC-2048",
            "new_status": "suppressed",
            "reason": "x",
            "approval_id": "APR-CLOSED-ONLY",
        },
    )
    assert not r["completed"] and r["reason_code"] == "APPROVAL_MISMATCH"
    assert store.get_case("INC-2048")["status"] == "investigating"


# ---------------- Engineering: migration, seq, lifecycle ----------------


def test_store_migrates_old_schema_without_reset(tmp_path):
    import sqlite3

    from agentboundary.store import SCHEMA

    db = str(tmp_path / "old.db")
    conn = sqlite3.connect(db)
    old = SCHEMA.replace(
        ", operator_persona_id TEXT, simulated_actor_id TEXT, control_actor_id TEXT, fixture_version TEXT",
        "",
    ).replace(", new_status TEXT", "")
    conn.executescript(old)
    conn.execute(
        "INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "APR-OLD",
            "change_case_status",
            "INC-2048",
            None,
            "tenant_northstar",
            "analyst_northstar",
            "senior_analyst",
            FUTURE,
            0,
        ),
    )
    conn.commit()
    conn.close()
    s = Store(db)
    try:
        cols = {r[1] for r in s.conn.execute("PRAGMA table_info(runs)")}
        assert "operator_persona_id" in cols and "fixture_version" in cols
        acols = {r[1] for r in s.conn.execute("PRAGMA table_info(approvals)")}
        assert "new_status" in acols
        assert s.get_approval("APR-OLD")["new_status"] is None
    finally:
        s.close()


def test_store_context_manager_and_event_seq_unique(store, disp, ctx_factory):
    with Store(":memory:") as s2:
        assert s2.record_count() >= 30
    run = Runner(store).run("A6")
    seqs = [e["seq"] for e in run["events"]]
    assert len(seqs) == len(set(seqs)) and seqs == sorted(seqs)


def test_attempt_event_precedes_mutation_completion(store, disp, ctx_factory):
    # A successful draft produces an ATTEMPT event plus a terminal ALLOW
    # event; the attempt is committed before the mutation completes.
    disp.dispatch(
        ctx_factory("analyst_northstar"),
        "draft_response",
        {
            "case_id": "INC-2048",
            "summary": "s",
            "recommended_actions": "a",
        },
    )
    evs = store.all("SELECT * FROM events WHERE tool='draft_response' ORDER BY seq")
    assert [e["decision"] for e in evs] == ["ATTEMPT", "ALLOW"]
    assert evs[0]["completed"] == 0 and evs[1]["completed"] == 1
