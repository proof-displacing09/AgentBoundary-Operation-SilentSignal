import json

from agentboundary.fixtures.data import CEDAR_SENTINEL


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    d = r.json()
    assert (
        d["mode"] == "protected"
        and d["weak_mode_available_via_api"] is False
        and d["real_model_configured"] is False
    )


def test_session_allowlist(client, session):
    h = session("analyst_northstar")
    me = client.get("/api/v1/lab/identity", headers=h)
    assert me.status_code == 200 and me.json()["id"] == "analyst_northstar"
    bad = client.post(
        "/api/v1/lab/session", json={"persona_id": "attacker_fixture_author"}
    )
    assert bad.status_code == 400
    bad2 = client.post("/api/v1/lab/session", json={"persona_id": "root"})
    assert bad2.status_code == 400


def test_session_required(client):
    assert client.get("/api/v1/cases").status_code == 401
    assert client.post("/api/v1/runs", json={"scenario_id": "A1"}).status_code == 401


def test_cases_tenant_scoped(client, session):
    h = session("analyst_northstar")
    ids = [c["id"] for c in client.get("/api/v1/cases", headers=h).json()]
    assert ids == ["INC-2048", "INC-2051"]
    r = client.get("/api/v1/cases/INC-3307", headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "TENANT_DENIED"
    assert CEDAR_SENTINEL not in r.text and "Cedar POS anomaly" not in r.text
    h2 = session("analyst_cedar")
    assert client.get("/api/v1/cases/INC-3307", headers=h2).status_code == 200


def test_alerts_tenant_scoped(client, session):
    h = session("analyst_northstar")
    assert client.get("/api/v1/alerts/ALT-3307", headers=h).status_code == 403
    assert client.get("/api/v1/alerts/ALT-2048", headers=h).status_code == 200


def test_runbooks_prefiltered(client, session):
    h = session("analyst_northstar")
    blob = json.dumps(client.get("/api/v1/runbooks", headers=h).json())
    assert CEDAR_SENTINEL not in blob and "RB-CEDAR-001" not in blob


def test_scenarios_catalog(client, session):
    ids = [s["id"] for s in client.get("/api/v1/scenarios").json()]
    assert ids == ["A1", "A2", "A3", "A4", "A5", "A6"]
    # P-01 (pentest): the detail endpoint now requires a session; the
    # list above stays public by the documented F-01 decision.
    d = client.get("/api/v1/scenarios/A2", headers=session("analyst_northstar")).json()
    assert d["injection_fixture"] and "EVT-2048-05" in d["attacker_surface"]


def test_run_and_reports_via_api(client, session, store):
    h = session("analyst_northstar")
    r = client.post("/api/v1/runs", headers=h, json={"scenario_id": "A2"})
    assert r.status_code == 200
    run = r.json()
    assert run["verdict"] == "PASS" and run["metrics"]["completed_forbidden"] == 0
    assert store.get_case("INC-2048")["status"] == "investigating"
    ev = client.get(f"/api/v1/runs/{run['id']}/events", headers=h)
    assert ev.status_code == 200 and len(ev.json()) == len(run["events"])
    rep = client.get(f"/api/v1/reports/{run['id']}/json", headers=h)
    assert rep.status_code == 200 and rep.json()["run"]["id"] == run["id"]
    assert f"agentboundary-run-{run['id']}.json" in rep.headers.get(
        "content-disposition", ""
    )
    md = client.get(f"/api/v1/reports/{run['id']}/markdown", headers=h)
    assert md.status_code == 200 and "text/markdown" in md.headers["content-type"]


def test_no_weak_toggle_via_api(client, session, store):
    # N-02: a Cedar analyst can no longer launch A4 at all, so this test
    # now uses a Northstar session; its assertion is unchanged: explicitly
    # asking for weak mode still runs protected (field is not honored).
    h = session("analyst_northstar")
    r = client.post(
        "/api/v1/runs",
        headers=h,
        json={"scenario_id": "A4", "mode": "weak", "weak": True, "skip_auth": True},
    )
    run = r.json()
    assert (
        run["mode"] == "protected"
        and run["verdict"] == "PASS"
        and run["metrics"]["disclosed_restricted"] is False
    )


def test_no_raw_tool_endpoint(client, session):
    h = session("analyst_northstar")
    for path in ("/api/v1/tools/read_case", "/api/v1/tools", "/api/v1/dispatch"):
        assert client.post(
            path, headers=h, json={"case_id": "INC-3307"}
        ).status_code in (404, 405)


def test_overview_honest_empty_then_counts(client, session):
    h0 = session("analyst_northstar")
    ov = client.get("/api/v1/overview", headers=h0).json()
    assert (
        ov["total_runs"] == 0
        and ov["recent_runs"] == []
        and ov["attempted_unauthorized"] == 0
    )
    h = session("analyst_northstar")
    client.post("/api/v1/runs", headers=h, json={"scenario_id": "A1"})
    ov = client.get("/api/v1/overview", headers=h).json()
    assert ov["total_runs"] == 1 and ov["legitimate_task_successes"] == 1
    assert ov["legitimate_workflow_completions"] == 1
    assert ov["security_invariant_passes"] == 1


def test_policy_matrix_and_settings(client, session):
    h = session("analyst_northstar")
    m = client.get("/api/v1/policy/matrix", headers=h).json()
    actions = {a["action"] for a in m["actions"]}
    assert actions == {
        "get_alert",
        "search_runbooks",
        "read_case",
        "draft_response",
        "change_case_status",
        "simulate_isolation",
    }
    assert "SPOOF_IGNORED" in m["reason_codes"]
    s = client.get("/api/v1/settings").json()
    assert s["protected_mode"] is True


def test_reset_endpoint(client, session, store):
    # N-03: reset is now restricted to the incident_commander lab admin
    # and requires explicit {"confirm": true}.
    h = session("incident_commander")
    store.execute("UPDATE cases SET status='closed' WHERE id='INC-2048'")
    r = client.post("/api/v1/lab/reset", headers=h, json={"confirm": True})
    assert (
        r.status_code == 200 and r.json()["reset"] is True and r.json()["records"] >= 30
    )
    assert store.get_case("INC-2048")["status"] == "investigating"
    # session survives reset
    assert client.get("/api/v1/lab/identity", headers=h).status_code == 200


def test_comparisons_no_live_weak(client, session):
    h = session("analyst_northstar")
    c = client.get("/api/v1/comparisons", headers=h).json()
    assert "weak_reports" in c and "comparable" in c
    assert "never executes weak mode" in c["notes"] or "never" in c["notes"]
