# Audit Remediation — 2026-10-24 (audit dated 2026-10-23)

Scope: all six audit findings plus the engineering concerns. Verdicts below are the
parent agent's, after independently re-running the suite, coverage, and live checks —
not copied from implementer reports.

## Per-finding verdicts
| Finding | Verdict | Evidence |
|---|---|---|
| F-01 Reporting API authorization | **FIXED** | Anonymous GET on overview/runs/events/findings/comparisons/policy-matrix → 401 (live). Northstar overview shows only Northstar cases; Cedar overview shows 0 Northstar runs. Tests: `test_f01_anonymous_denied_on_research_routes`, `test_f01_cross_tenant_run_and_report_hidden`, `test_f01_northstar_overview_hides_cedar_cases`, `test_f01_events_filtered_by_run_tenant`. |
| F-02 Operator vs simulated actor | **FIXED** | Live: Cedar operator launching A4 recorded `operator=analyst_cedar`, `simulated=analyst_northstar`; A5 records `control_actor=analyst_cedar`. Tests: `test_f02_operator_recorded_separately_from_simulated_actor`, `test_f02_cli_operator_and_a5_control_actor`. |
| F-03 Concurrent approval reuse | **FIXED** | Validation + conditional consumption + mutation + completion event in one `BEGIN IMMEDIATE` transaction. Tests: `test_f03_concurrent_isolation_approval_exactly_one_completion`, `test_f03_concurrent_status_approval_exactly_one_completion` (barrier-synchronized; exactly one ALLOW/mutation). Note: the status loser may be denied as TRANSITION_INVALID rather than APPROVAL_USED when it runs after the winner's mutation — both are denials with no second mutation, and the test asserts that invariant. |
| F-04 Comparison pairing | **FIXED** | Live: fresh weak A2 paired with protected A2 (same scenario + fixture 1.0.0) → `comparable: true`; other protected runs and the legacy unversioned weak A4 export listed as unmatched. The audit's exact reproduction (only protected A1 vs weak A2/A4) now returns `comparable: false`. Tests: `test_f04_pairing_requires_scenario_and_fixture_match`, `test_f04_only_protected_a1_with_weak_a2_is_not_comparable`, `test_f04_legacy_export_does_not_shadow_matchable_export`. |
| F-05 Metric separation | **FIXED** | Live A1–A6: 7 security-invariant passes (incl. a Cedar-operator A4 run) but only 4 legitimate workflow completions; A2 and A4 honestly report False. Tests: `test_f05_blocking_is_not_legitimate_completion`, `test_f05_metrics_unit_and_aggregate`. See docs/metrics-definitions.md for the per-scenario table. |
| F-06 Approval status binding | **FIXED** | `APR-VALID` is bound to `closed`; `suppressed` with it → APPROVAL_MISMATCH. Tests: `test_valid_approval_rejects_other_status`, `test_valid_approval_requires_new_status`, `test_f06_dispatcher_rejects_suppressed_with_closed_approval`. A6 still passes end-to-end. |

## Engineering concerns addressed
- Audit events: ATTEMPT recorded first (committed); mutation + completion event in one
  transaction; rollback + ERROR event on failure. Event `seq` from the inserted row's
  rowid, not `SELECT COUNT(*)+1` (`test_attempt_event_precedes_mutation_completion`,
  `test_store_context_manager_and_event_seq_unique`).
- SQLite lifecycle: `Store.close()` + context manager; conftest/CLI/lifespan close stores.
  Unclosed-SQLite warnings in the test run: 0 (only the pre-existing Starlette warning).
- Dead code: `evaluation/metrics.py` is now wired into the runner and overview, with unit
  tests; `cli.py` coverage 92% via in-process `cli.main()` tests (was 0%).
- Weak DB cleanup: run-weak closes and deletes its temp DB in a finally block; verified
  no `/tmp/agentboundary-weak-*.db` remains after runs, including a failed export.
- Dependency locking: `backend/requirements.txt` pinned from the actual venv.
- Coverage config: `pyproject.toml` sets coverage source to the full source tree, so the
  audit's denominator is now the default measurement.
- Not in this round (per user order): real-LLM adapter, Playwright E2E, axe audit,
  Docker/CI, PDF export, public deployment. The application remains NOT published and
  NOT publicly deployed.

## Verification (parent re-run, 2026-10-24)
- `pytest -q`: **83 passed, 0 failed** (was 61; +22 tests).
- `ruff check` + `ruff format --check`: clean. Frontend `tsc --noEmit`: 0 errors;
  Vitest: 5 passed; production build passes (JS 210.08 kB, gzip 63.77 kB).
- Full-source coverage (audit method, `coverage run -m pytest`): **92%** (1006 stmts,
  80 missed), up from the audit baseline of 82% (801 stmts). Per-module: app.py 86%,
  dispatcher 94%, runner 98%, authorizer 95%, cli.py 92%, metrics.py 92%.
- Live: A1–A6 all PASS under the new metrics; weak A2/A4 CLI exports work; demo DB
  reset to fresh 48 records after verification.
- Coverage documentation note: the pre-remediation baseline the user accepted is 82%
  (801 statements, full source tree). The 92% above uses the identical method after
  remediation; the earlier 91% figure used a traced-files-only denominator and is
  superseded.
