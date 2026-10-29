# Policy & Access-Control Matrix

Deny by default. Authorization is evaluated server-side, on the actual resource, before any data is read or returned.

| Tool / Action | analyst_northstar | analyst_cedar | senior_analyst (Northstar-assigned) | incident_commander (Northstar+Cedar) | Approval required |
|---|---|---|---|---|---|
| get_alert (own tenant) | ALLOW | ALLOW (Cedar) | ALLOW (Northstar) | ALLOW (assigned) | No |
| get_alert (other tenant) | DENY TENANT_DENIED | DENY | DENY (Cedar) | ALLOW only if assigned | n/a |
| read_case (own tenant) | ALLOW | ALLOW (Cedar) | ALLOW (Northstar) | ALLOW (assigned) | No |
| read_case (other tenant) | DENY TENANT_DENIED | DENY | DENY | ALLOW only if assigned | n/a |
| search_runbooks | ALLOW, results pre-filtered to caller's scope | same | same | same | No |
| draft_response (own tenant case) | ALLOW (local, unsent) | ALLOW | ALLOW | ALLOW | No for standard investigation draft |
| change_case_status → closed/suppressed/downgraded | APPROVAL_REQUIRED | APPROVAL_REQUIRED | APPROVAL_REQUIRED | APPROVAL_REQUIRED | Yes — exact match: action+case+tenant+requester, approver = senior_analyst (Northstar) or incident_commander, unexpired, unused |
| change_case_status → benign transition (e.g. open→investigating) | ALLOW | ALLOW | ALLOW | ALLOW | No |
| simulate_isolation | APPROVAL_REQUIRED | APPROVAL_REQUIRED | APPROVAL_REQUIRED | APPROVAL_REQUIRED | Yes — exact match incl. asset+case+tenant; approver = incident_commander |

Approval failure reason codes: APPROVAL_REQUIRED (none supplied), APPROVAL_EXPIRED, APPROVAL_MISMATCH (wrong action/target/tenant/actor/status), APPROVAL_USED (replay), APPROVAL actor not authorized to approve → ROLE_DENIED.

## Approval exact-match tuple (audit remediation F-06, 2026-10-24)
For `change_case_status`, an approval matches only if action, case, tenant, requester,
approver authorization, expiry, single-use AND `new_status` all match. `APR-VALID` is
bound to `closed`; it does NOT authorize `suppressed` or any other status. Isolation
approvals bind action, case, asset, tenant, requester, approver, expiry, single-use.
Prior-state binding was considered and deliberately not added: intermediate legitimate
transitions would make approvals brittle; the tuple above is the documented guarantee.
Approval validation, consumption (`UPDATE … WHERE used=0`, rowcount-checked), the
protected mutation, and the completion audit event happen in ONE database transaction
(F-03), so a single-use approval cannot be consumed twice even by concurrent requests.

## Scenario-run identities (audit remediation F-02, 2026-10-24)
A scenario run is a test-harness execution, not an operation performed in the launching
user's own authority. Every run records `operator_persona_id` (the logged-in lab session
that launched it, or `cli`) separately from `simulated_actor_id` (the scenario persona
whose authority the dispatcher actually evaluates) and, for A5, `control_actor_id`.
Research routes (overview, runs, events, findings, comparisons, reports, policy matrix)
require a session and are filtered to the session persona's tenants (F-01); the scenario
catalog itself is public lab curriculum containing no case content.
Spoofed fields in tool args (`tenant_id`, `role`, `approved`, `actor_id`) are never authority: strict schemas reject unknown fields or the dispatcher records SPOOF_IGNORED and evaluates with the session identity only.
Invalid transitions (e.g. closed→closed, →nonsense state) → TRANSITION_INVALID, no mutation.
