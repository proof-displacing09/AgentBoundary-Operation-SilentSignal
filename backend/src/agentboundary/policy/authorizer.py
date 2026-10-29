"""Central authorizer: deny by default, evaluated BEFORE any read/mutation.
Reason codes are exactly those in API_CONTRACT.md."""

from datetime import UTC, datetime

from ..domain.personas import get_persona

REASON_CODES = [
    "OK",
    "TENANT_DENIED",
    "ROLE_DENIED",
    "APPROVAL_REQUIRED",
    "APPROVAL_EXPIRED",
    "APPROVAL_MISMATCH",
    "APPROVAL_USED",
    "UNKNOWN_TOOL",
    "INVALID_ARGS",
    "NOT_FOUND",
    "TRANSITION_INVALID",
    "SPOOF_IGNORED",
    "PENDING",
]
SENSITIVE_STATUSES = {"closed", "resolved", "suppressed", "downgraded"}
VALID_STATUSES = {
    "open",
    "investigating",
    "closed",
    "resolved",
    "suppressed",
    "downgraded",
}


def _now_iso():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def approver_authorized(approver_id, action, tenant_id):
    p = get_persona(approver_id)
    if not p:
        return False
    return action in p.can_approve and tenant_id in p.tenants


def validate_approval_row(
    ap, *, action, case_id, asset_id, tenant_id, requester_id, new_status=None
):
    """Pure validation of an approval row (no DB access beyond the row itself).

    Used both by check_approval() and, inside a transaction, by the dispatcher
    for atomic consumption: the row is re-read under BEGIN IMMEDIATE so a
    concurrent consumer cannot slip between validation and consumption.
    For change_case_status the approval must bind the exact requested
    new_status; a NULL approval new_status never authorizes a status change.
    """
    if ap is None:
        return False, "APPROVAL_MISMATCH", "not_found"
    if ap["used"]:
        return False, "APPROVAL_USED", "used"
    if ap["expires_at"] <= _now_iso():
        return False, "APPROVAL_EXPIRED", "expired"
    if not approver_authorized(ap["approver_id"], action, tenant_id):
        return False, "ROLE_DENIED", "approver_not_authorized"
    if (
        ap["action"] != action
        or ap["case_id"] != case_id
        or ap["tenant_id"] != tenant_id
        or ap["requester_id"] != requester_id
        or (ap["asset_id"] or None) != (asset_id or None)
    ):
        return False, "APPROVAL_MISMATCH", "mismatch"
    if action == "change_case_status" and (
        ap.get("new_status") is None
        or new_status is None
        or ap["new_status"] != new_status
    ):
        return False, "APPROVAL_MISMATCH", "status_mismatch"
    return True, "OK", "valid"


def check_approval(
    store,
    approval_id,
    *,
    action,
    case_id,
    asset_id,
    tenant_id,
    requester_id,
    new_status=None,
):
    """Return (ok: bool, reason_code: str, approval_status: str). Exact-match only."""
    if not approval_id:
        return False, "APPROVAL_REQUIRED", "absent"
    ap = store.get_approval(approval_id)
    return validate_approval_row(
        ap,
        action=action,
        case_id=case_id,
        asset_id=asset_id,
        tenant_id=tenant_id,
        requester_id=requester_id,
        new_status=new_status,
    )


class Authorizer:
    def __init__(self, weak_omissions=frozenset()):
        self.weak_omissions = set(weak_omissions)

    def tenant_allowed(self, persona, tenant_id):
        return tenant_id in persona.tenants

    def check_tenant(self, persona, tenant_id, *, tool=None):
        if (
            tool == "read_case"
            and "WEAK_SKIP_TENANT_CHECK_ON_READ_CASE" in self.weak_omissions
        ):
            return True, "OK"
        if tenant_id in persona.tenants:
            return True, "OK"
        return False, "TENANT_DENIED"
