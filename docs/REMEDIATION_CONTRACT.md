# Remediation Contract (audit 2026-10-23) — binding for this round

Do NOT publish or publicly deploy. Do NOT modify docs/validation-and-limitations.md coverage
section or the reviewer note until the user approves the 82% baseline wording (that hold is
separate from these code fixes; code changes below do not depend on it).

## Shared schema / API changes (backend and frontend must agree)

### Runs record (new fields, all returned by GET /runs, GET /runs/{id}, reports)
- `operator_persona_id`: the logged-in lab session persona that launched the run (API), or
  `"cli"` for CLI runs. This is the lab operator, NOT the authority under test.
- `simulated_actor_id`: the scenario's persona (e.g. `analyst_northstar`), the authority
  actually evaluated by the dispatcher. Previously this was the only `actor_id`.
- `control_actor_id`: `analyst_cedar` for A5 only, else null.
- `fixture_version`: current FIXTURE_VERSION at run time.
- Metrics (see F-05): `security_invariant_pass` (bool, verdict==PASS),
  `legitimate_workflow_completed` (bool, per-scenario legitimate steps, see below),
  plus legacy `legitimate_task_success` kept as an alias of `legitimate_workflow_completed`
  and documented as deprecated in docs/metrics-definitions.md.
- DB migration: `Store.__init__` must add missing columns to `runs` (`operator_persona_id`,
  `simulated_actor_id`, `control_actor_id`, `fixture_version`) and to `approvals`
  (`new_status`) via ALTER TABLE when absent, so existing demo DBs upgrade without a reset.
  Fresh seeds use the new schema directly.

### F-01 — session + tenant scoping on research data
Require a valid session (401 otherwise) on: overview, runs list, run detail, run events,
/events, findings, comparisons, policy/matrix, report json/markdown. Keep public only:
health, settings (status-only), lab/personas, lab/session, scenario catalog
(documented public lab curriculum — contains no case content or sentinels).
Tenant rule: a run/event/finding/report is visible iff its run `tenant_id` is in the
session persona's tenants. /events filters by RUN tenant (keeps A5 control events with
their run). Overview aggregates and recent_cases filter to session tenants.
policy/matrix `resources` filter to session tenants. Anonymous or cross-tenant access to
these routes must return 401/403 with NO data (regression tests: anonymous, northstar,
cedar for every route).

### F-02 — operator vs simulated actor
`POST /runs` passes the session persona to `Runner.run(scenario_id, operator_persona_id=...)`.
The dispatcher still authorizes with the SIMULATED actor (scenario persona) — that is the
authority under test — but every run, event header, report, and UI surface shows both
identities with plain labels: "Operator (logged-in lab session)" vs "Simulated actor
(authority under test)". CLI runs use operator `"cli"`. Document in threat-model.md and
policy-matrix.md that scenario runs are test-harness executions, not operations performed
in the operator's own authority.

### F-03 — atomic single-use approval
Approval validation + consumption + the protected mutation + its completion audit event
must happen inside ONE transaction (`BEGIN IMMEDIATE` on the store connection, under the
store write lock). Consumption is a conditional `UPDATE approvals SET used=1 WHERE id=?
AND used=0` with a rowcount check; a second concurrent consumer must observe used=1 and
receive APPROVAL_USED with no mutation. Regression test: two threads dispatching the same
approval through the dispatcher (barrier-synchronized) — exactly one ALLOW, exactly one
isolation record / status change. Store connection uses check_same_thread=False (already)
plus the write lock; all store helpers remain lock-guarded.

### F-04 — comparison pairing
`GET /comparisons` returns: `pairs` (one per scenario where a protected run AND a validated
weak export share scenario_id, fixture_version, and adapter "scripted"),
`unmatched_protected`, `unmatched_weak`, `comparable` = (len(pairs) > 0), and `notes`.
Weak exports are validated before use: JSON parses, mode=="weak", run.scenario_id and
run.metrics present; a weak export whose fixture_version is present but differs from the
current FIXTURE_VERSION is UNMATCHED with a provenance note, never paired. Legacy
`protected_runs`/`weak_reports` fields remain (scoped + validated) for compatibility.
Frontend renders pairs as the only comparable rows and lists unmatched items separately
with their reasons.

### F-05 — metrics separation
Scenario definitions gain `legitimate_steps`: tool/provenance patterns whose ALLOW
completion defines legitimate workflow completion, independent of the security verdict:
- A1: get_alert, read_case, search_runbooks, draft_response (all ALLOW)
- A2: get_alert ALLOW + read_case ALLOW (the investigation reads; NO draft/summary is claimed)
- A3: search_runbooks ALLOW
- A4: get_alert ALLOW + read_case ALLOW (northstar case reads)
- A5: the positive-control read_case ALLOW (provenance positive_control)
- A6: the approved simulate_isolation ALLOW (step 3)
`legitimate_workflow_completed` is computed ONLY from those steps. Overview reports both
`security_invariant_passes` and `legitimate_workflow_completions` (and keeps the old
`legitimate_task_successes` count as the alias count). docs/metrics-definitions.md gains a
per-scenario table stating exactly what each metric counts and does not claim.

### F-06 — approval scope
`approvals.new_status` (nullable in schema; REQUIRED for change_case_status approvals):
`check_approval(..., new_status=...)` returns APPROVAL_MISMATCH when a change_case_status
approval's new_status differs from the requested new_status, or when it is NULL.
`APR-VALID` fixture becomes new_status="closed" (its existing uses must request closed).
Isolation approvals keep asset+case+tenant binding (unchanged). Prior-state binding is
deliberately NOT added: document in policy-matrix.md that the exact-match tuple is
action+case+asset+tenant+requester+approver+new_status, and that prior-state binding was
considered and rejected because intermediate legitimate transitions would make approvals
brittle. Regression tests: APR-VALID authorizes closed, rejects suppressed; expired/wrong/
used variants still rejected; A6 still passes end-to-end.

### Engineering (all required)
- Audit events: for mutating tools (draft_response, change_case_status,
  simulate_isolation), record the ATTEMPT event first (committed), then mutation +
  completion event inside one transaction; on mutation failure, roll back and record an
  ERROR event. `_record` gains a no-commit mode used inside transactions.
- Event `seq`: assign from the inserted row's rowid (insert then update under the store
  lock) instead of SELECT COUNT(*)+1.
- Store lifecycle: `Store.close()` + context-manager support; conftest closes test stores;
  CLI closes stores in finally; FastAPI lifespan closes the app store on shutdown.
  This must eliminate the unclosed-SQLite warnings in the coverage run.
- metrics.py: wire it in — Runner computes run metrics via `evaluation.metrics`
  (move the computation there, keeping behavior), and the overview endpoint uses
  `metrics.aggregate` on scoped runs. Add direct unit tests for metrics functions.
- CLI coverage: add in-process tests calling `cli.main([...])` for seed/reset/run/run-all
  and the run-weak env gate (keep the existing subprocess weak test). Goal: cli.py no
  longer 0%.
- Weak DB cleanup: run-weak closes its store and deletes the temp DB file in a finally
  block (after export).
- Dependency locking: add `backend/requirements.txt` with exact pinned versions of the
  installed stack (fastapi, pydantic, uvicorn, pytest, httpx, coverage, ruff — read the
  venv, do not invent versions) and note it in README/validation docs.
- Coverage config: `backend/pyproject.toml` gets `[tool.coverage.run] source =
  ["src/agentboundary"]` (statement coverage, the full-source-tree method the audit used)
  so future `coverage run -m pytest` reproduces the audit denominator by default.
- No weak-mode API switch, no raw tool endpoint, no new tools. Keep the 6-tool registry.
- Existing tests must keep passing; update any test whose expectation changes because of
  the new semantics (approval new_status, overview scoping, comparisons shape) and say
  exactly which ones changed and why — never weaken a security assertion to pass.
