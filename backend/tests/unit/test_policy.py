from agentboundary.policy.authorizer import approver_authorized, check_approval

BASE = {
    "action": "change_case_status",
    "case_id": "INC-2048",
    "asset_id": None,
    "tenant_id": "tenant_northstar",
    "requester_id": "analyst_northstar",
    # F-06: approvals are bound to the exact requested new_status.
    "new_status": "closed",
}


def test_valid_exact_approval(store):
    ok, code, _status = check_approval(store, "APR-VALID", **BASE)
    assert ok and code == "OK"


def test_absent_approval(store):
    ok, code, _ = check_approval(store, None, **BASE)
    assert not ok and code == "APPROVAL_REQUIRED"


def test_fake_approval(store):
    ok, code, _ = check_approval(store, "APR-DOES-NOT-EXIST", **BASE)
    assert not ok and code == "APPROVAL_MISMATCH"


def test_expired(store):
    ok, code, _ = check_approval(store, "APR-EXPIRED", **BASE)
    assert not ok and code == "APPROVAL_EXPIRED"


def test_wrong_tenant(store):
    ok, code, _ = check_approval(store, "APR-WRONG-TENANT", **BASE)
    assert not ok and code in ("APPROVAL_MISMATCH", "ROLE_DENIED")


def test_wrong_requester(store):
    ok, code, _ = check_approval(store, "APR-WRONG-REQUESTER", **BASE)
    assert not ok and code == "APPROVAL_MISMATCH"


def test_wrong_action(store):
    ok, code, _ = check_approval(store, "APR-WRONG-ACTION", **BASE)
    assert not ok and code == "APPROVAL_MISMATCH"


def test_wrong_target(store):
    ok, code, _ = check_approval(store, "APR-WRONG-TARGET", **BASE)
    assert not ok and code == "APPROVAL_MISMATCH"


def test_used(store):
    ok, code, _ = check_approval(store, "APR-USED", **BASE)
    assert not ok and code == "APPROVAL_USED"


def test_wrong_approver(store):
    ok, code, _ = check_approval(store, "APR-WRONG-APPROVER", **BASE)
    assert not ok and code == "ROLE_DENIED"


def test_approver_authorization_matrix():
    assert approver_authorized(
        "senior_analyst", "change_case_status", "tenant_northstar"
    )
    assert not approver_authorized(
        "senior_analyst", "change_case_status", "tenant_cedar"
    )
    assert not approver_authorized(
        "senior_analyst", "simulate_isolation", "tenant_northstar"
    )
    assert approver_authorized(
        "incident_commander", "simulate_isolation", "tenant_cedar"
    )
    assert not approver_authorized(
        "analyst_northstar", "change_case_status", "tenant_northstar"
    )


def test_valid_approval_rejects_other_status(store):
    # F-06: APR-VALID is bound to "closed"; it must not authorize "suppressed".
    ok, code, _ = check_approval(
        store, "APR-VALID", **{**BASE, "new_status": "suppressed"}
    )
    assert not ok and code == "APPROVAL_MISMATCH"


def test_valid_approval_requires_new_status(store):
    # F-06: a change_case_status approval check without a requested status
    # cannot match; the approval's new_status binding must be enforced.
    base = {k: v for k, v in BASE.items() if k != "new_status"}
    ok, code, _ = check_approval(store, "APR-VALID", **base)
    assert not ok and code == "APPROVAL_MISMATCH"
