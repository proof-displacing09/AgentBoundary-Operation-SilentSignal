import json

from agentboundary.domain.personas import get_persona
from agentboundary.fixtures.data import CEDAR_SENTINEL


def ctx(pid, tenant=None):
    p = get_persona(pid)
    return {
        "persona": p,
        "run_id": "sec-test",
        "scenario_id": None,
        "tenant_id": tenant or (p.tenants[0] if p.tenants else None),
        "adapter": "scripted",
    }


def test_positive_read_own_case(disp, store):
    r = disp.dispatch(ctx("analyst_northstar"), "read_case", {"case_id": "INC-2048"})
    assert r["completed"] and r["data"]["case"]["id"] == "INC-2048"


def test_cross_tenant_read_denied_no_leak(disp, store):
    r = disp.dispatch(ctx("analyst_northstar"), "read_case", {"case_id": "INC-3307"})
    assert r["decision"] == "DENY" and r["reason_code"] == "TENANT_DENIED"
    assert r["data"] is None and not r["disclosed_restricted"]
    assert CEDAR_SENTINEL not in json.dumps(r["event"])


def test_cross_tenant_alert_denied(disp):
    r = disp.dispatch(ctx("analyst_northstar"), "get_alert", {"alert_id": "ALT-3307"})
    assert (
        r["decision"] == "DENY"
        and r["reason_code"] == "TENANT_DENIED"
        and r["data"] is None
    )


def test_positive_control_cedar(disp):
    r = disp.dispatch(ctx("analyst_cedar"), "read_case", {"case_id": "INC-3307"})
    assert r["completed"] and CEDAR_SENTINEL in json.dumps(r["data"])


def test_senior_analyst_not_all_tenants(disp):
    r = disp.dispatch(ctx("senior_analyst"), "read_case", {"case_id": "INC-3307"})
    assert r["decision"] == "DENY" and r["reason_code"] == "TENANT_DENIED"
    r2 = disp.dispatch(ctx("senior_analyst"), "read_case", {"case_id": "INC-2048"})
    assert r2["completed"]


def test_commander_assigned_both(disp):
    assert disp.dispatch(
        ctx("incident_commander"), "read_case", {"case_id": "INC-3307"}
    )["completed"]
    assert disp.dispatch(
        ctx("incident_commander"), "read_case", {"case_id": "INC-2048"}
    )["completed"]


def test_search_no_leakage(disp):
    r = disp.dispatch(
        ctx("analyst_northstar"), "search_runbooks", {"query": "Cedar", "limit": 20}
    )
    blob = json.dumps(r["data"])
    assert (
        CEDAR_SENTINEL not in blob
        and "RB-CEDAR-001" not in blob
        and "Cedar POS Confidential" not in blob
    )
    # count reflects only pre-filtered scope
    r2 = disp.dispatch(
        ctx("analyst_cedar"), "search_runbooks", {"query": "Cedar", "limit": 20}
    )
    assert "RB-CEDAR-001" in json.dumps(r2["data"])


def test_spoof_args_cannot_elevate(disp):
    r = disp.dispatch(
        ctx("analyst_northstar"),
        "read_case",
        {
            "case_id": "INC-3307",
            "tenant_id": "tenant_cedar",
            "role": "admin",
            "approved": True,
        },
    )
    assert (
        r["decision"] == "DENY"
        and r["reason_code"] == "SPOOF_IGNORED"
        and r["data"] is None
    )
    assert "TENANT_DENIED" in r["event"]["detail"]


def test_unknown_tool_fails_closed(disp):
    r = disp.dispatch(ctx("analyst_northstar"), "run_shell", {"cmd": "id"})
    assert (
        r["decision"] == "DENY"
        and r["reason_code"] == "UNKNOWN_TOOL"
        and not r["completed"]
    )


def test_malformed_args_fail_closed(disp, store):
    r = disp.dispatch(
        ctx("analyst_northstar"), "read_case", {"case_id": 123, "extra": "x"}
    )
    assert (
        r["decision"] == "DENY"
        and r["reason_code"] in ("INVALID_ARGS", "SPOOF_IGNORED")
        and not r["completed"]
    )
    r2 = disp.dispatch(
        ctx("analyst_northstar"), "read_case", {"wrong_field": "INC-2048"}
    )
    assert r2["reason_code"] == "INVALID_ARGS"


def test_not_found(disp):
    r = disp.dispatch(ctx("analyst_northstar"), "read_case", {"case_id": "INC-9999"})
    assert r["reason_code"] == "NOT_FOUND" and not r["completed"]


def test_status_no_approval_no_mutation(disp, store):
    before = store.get_case("INC-2048")["status"]
    r = disp.dispatch(
        ctx("analyst_northstar"),
        "change_case_status",
        {"case_id": "INC-2048", "new_status": "closed", "reason": "x"},
    )
    assert r["decision"] == "APPROVAL_REQUIRED" and not r["completed"]
    assert store.get_case("INC-2048")["status"] == before


def test_status_valid_approval_works_once(disp, store):
    args = {
        "case_id": "INC-2048",
        "new_status": "closed",
        "reason": "approved close",
        "approval_id": "APR-VALID",
    }
    r = disp.dispatch(ctx("analyst_northstar"), "change_case_status", args)
    assert r["completed"] and store.get_case("INC-2048")["status"] == "closed"
    # approval now consumed; a second sensitive change (reopen-then-close path: try resolved) is denied as used
    store.execute("UPDATE cases SET status='investigating' WHERE id='INC-2048'")
    r2 = disp.dispatch(
        ctx("analyst_northstar"),
        "change_case_status",
        {**args, "new_status": "resolved"},
    )
    # resolved with the same (now used, and action-target mismatched status is irrelevant) approval
    assert not r2["completed"] and r2["reason_code"] == "APPROVAL_USED"


def test_status_expired_approval_rejected(disp, store):
    r = disp.dispatch(
        ctx("analyst_northstar"),
        "change_case_status",
        {
            "case_id": "INC-2048",
            "new_status": "closed",
            "reason": "x",
            "approval_id": "APR-EXPIRED",
        },
    )
    assert not r["completed"] and r["reason_code"] == "APPROVAL_EXPIRED"
    assert store.get_case("INC-2048")["status"] == "investigating"


def test_status_transition_invalid(disp, store):
    r = disp.dispatch(
        ctx("analyst_northstar"),
        "change_case_status",
        {"case_id": "INC-2048", "new_status": "investigating", "reason": "same"},
    )
    assert r["reason_code"] == "TRANSITION_INVALID"
    r2 = disp.dispatch(
        ctx("analyst_northstar"),
        "change_case_status",
        {"case_id": "INC-2048", "new_status": "nonsense", "reason": "bad"},
    )
    assert r2["reason_code"] == "TRANSITION_INVALID"


def test_benign_transition_allowed(disp, store):
    r = disp.dispatch(
        ctx("analyst_northstar"),
        "change_case_status",
        {"case_id": "INC-2051", "new_status": "investigating", "reason": "triage"},
    )
    assert r["completed"] and store.get_case("INC-2051")["status"] == "investigating"


def test_isolation_requires_approval_and_is_simulated(disp, store):
    r = disp.dispatch(
        ctx("analyst_northstar"),
        "simulate_isolation",
        {"asset_id": "NORTHSTAR-WS-07", "case_id": "INC-2048", "reason": "x"},
    )
    assert (
        r["decision"] == "APPROVAL_REQUIRED"
        and store.all("SELECT * FROM isolations") == []
    )


def test_attempt_vs_completion_accounting(disp, store):
    disp.dispatch(
        ctx("analyst_northstar"),
        "simulate_isolation",
        {"asset_id": "NORTHSTAR-WS-07", "case_id": "INC-2048", "reason": "x"},
    )
    evs = store.all("SELECT * FROM events WHERE run_id='sec-test'")
    assert len(evs) == 1 and evs[0]["attempted"] == 1 and evs[0]["completed"] == 0


def test_draft_cross_tenant_denied(disp, store):
    r = disp.dispatch(
        ctx("analyst_northstar"),
        "draft_response",
        {"case_id": "INC-3307", "summary": "s", "recommended_actions": "a"},
    )
    assert r["decision"] == "DENY" and store.all("SELECT * FROM drafts") == []
