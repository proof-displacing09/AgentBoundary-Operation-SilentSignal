# Second-Audit Remediation — 2026-10-25 (master-prompt release)

Scope: the second audit's remaining findings N-01–N-08, the real-LLM adapter,
frontend completeness, Playwright/browser verification, reproducible startup,
and CI. Verdicts are the parent agent's after independently re-running every
suite and live check — not copied from implementer reports.

## Per-finding verdicts
| Finding | Verdict | Evidence |
|---|---|---|
| N-01 Cross-run evaluator interference (concurrency) | **FIXED** | Runner counts isolations `WHERE run_id=?`; A1/A2/A3/A6 verdicts derive from the run's own events. Tests: `test_n01_parallel_a6_runs_score_independently` (barrier-synchronized, looped 10×, both PASS, exactly 1 own isolation each), `test_n01_concurrent_a2_and_a6_no_interference`. Live API check: 2 parallel A6 POSTs, both PASS, each exactly 1 own ALLOW isolation. |
| N-02 Cross-tenant launch / POST-vs-GET inconsistency | **FIXED** | `POST /runs` 403s `TENANT_DENIED` when the scenario tenant is outside the operator's tenants, creating no run. `incident_commander` (both tenants in the server-side persona model, never from request JSON) is the designated experiment admin; POST/GET/list agree. Tests: `test_n02_cedar_launch_denied_no_run_created`, `test_n02_northstar_launch_and_get_agree`, `test_n02_incident_commander_cross_tenant_launch`, `test_n02_list_visibility_consistent`. |
| N-03 Any session can erase the lab | **FIXED** | API reset is `incident_commander`-only (403 otherwise, 401 without session), requires `{"confirm": true}` (else 400 `CONFIRMATION_REQUIRED`, nothing deleted), and supports admin-only `{"dry_run": true}` counts preview. CLI reset unchanged (local operator tool). Frontend: reset disabled with explanation for others; dry-run preview then confirm for the admin. Tests: `test_n03_*` (6 tests). |
| N-04 A5 positive-control Cedar metadata in Northstar runs | **FIXED** | New `events.evidence_scope` (`primary` / `control_only`, safe migration); non-admin viewers get control events replaced by one non-sensitive reference entry, out-of-scope resource ids in event args redacted to `"REDACTED"` (tenant looked up from the store), and run-level `control_actor_id` nulled for non-admins (parent tightening + test `test_n04_parent_run_payload_hides_control_actor`). Commander sees full evidence. Whole-payload string checks for INC-3307 / tenant_cedar / analyst_cedar / sentinel in tests and live checks. |
| N-05 Stale React data on persona change / async races | **FIXED** | Central `useAsync` keyed on `sessionVersion` with generation tokens; page content remounts per session (`key={sessionVersion}`); stored sessions validated via `/lab/identity` before data renders; 401 clears page state. Tests: `frontend/tests/session-isolation.test.tsx` (delayed old response, immediate clearing, 401 routing, token-at-click-time) + Playwright spec 2 (delayed `/overview`, Cedar-after-Northstar, reload). |
| N-06 Unclosed SQLite ResourceWarnings | **FIXED on Python 3.12; NOT VERIFIED on 3.13** | Warning-as-error run (`python -W error::ResourceWarning -m pytest -q`): 127 passed, zero SQLite warnings. One real leak fixed (unclosed stores in a fixture test). Python 3.13 is not available in this environment, so the second audit's 3.13 warnings could not be re-checked — stated, not claimed. |
| N-07 Contradictory documentation | **FIXED** | Current-facing docs synchronized in this release: README results table (129 / 22 / 91% on 1376 stmts / Playwright 19), `docs/validation-and-limitations.md` current table, `docs/code-walkthrough.md` test count. Dated history in `docs/PROGRESS.md` test log and `docs/remediation-2026-10-24.md` remains, explicitly timestamped/superseded. `docs/API_CONTRACT.md` is the single current contract (adapter, `tool_call_id`, `evidence_scope`, reset, launch rule). |
| N-08 Evidence quality / robustness | **FIXED** | (a) A1 legitimacy requires the draft to target INC-2048 exactly. (b) Unauthorized classification uses scenario ground truth + logical calls, not denial alone. (c) Stable `tool_call_id` shared by ATTEMPT + terminal events; metrics count logical calls. (d) `/events` ordered by DB `seq`. (e) Weak-export validation rejects bad adapter/omissions/mode/corrupt JSON. (f) `/health` + `/settings` no longer expose `last_run`. (g) PASS/FAIL/INCONCLUSIVE/ERROR kept distinct; zero-proposal and provider-error real runs are INCONCLUSIVE/ERROR, never PASS. (h) Attempt-before-transaction + atomic mutation/approval/consumption/completion preserved. |

F-01–F-06 protections preserved: all prior regression tests pass (only
contract-intended updates: launch tenant rule, reset confirm/admin, health
`last_run` removal, A1 draft exactness).

## Later phases in this release (summary; details in their docs)
- **Phase 3 — real-LLM adapter** (`docs/real-llm-evaluation.md`): backend-only
  OpenAI-compatible tool-calling adapter + `RealAgent` loop through the same
  dispatcher; 16 mocked-protocol tests; live evaluation **NOT RUN** (no key).
- **Phase 4 — frontend completeness**: adapter badges + mode filter, real-LLM
  path with honest not-configured state, provider status (host/model only),
  no `last_run` usage, no weak-mode control anywhere.
- **Phase 5 — browser verification** (`docs/ui-qa.md`): Playwright 19/19,
  axe 0 critical/serious on 4 pages, 12 screenshots reviewed, 2 real defects
  fixed (focusable scroll regions; Overview recent-runs misinformation).
- **Phase 6 — release testing**: repo-owned `scripts/` (setup/start/stop/
  systemd install), clean-clone gates green, `.github/workflows/ci.yml`
  (CI itself NOT RUN — no runner here), pip-audit clean, `npm audit`
  unavailable in sandbox (registry proxy 403). One minor defect found and
  fixed in Phase 7: malformed JSON bodies returned 500; now 400 `INVALID_JSON`
  (test `test_phase6_malformed_json_returns_400_not_500`).
- **Phase 7 — concurrent-seed defect (found by the final Playwright run,
  fixed before release):** a systemd backend in a bind-fail restart loop
  plus a manually started server seeded the same demo DB concurrently;
  sqlite `executescript` is not atomic, so one seed aborted partway and
  left the DB without `events`/`sessions` (sessions then 500'd). Fixes:
  `Store.seed()` now runs inside one `BEGIN IMMEDIATE` transaction, and
  `Store.__init__` repairs any missing schema table without touching
  existing rows (with a lock-retry for transient contention). The damaged
  demo DB was repaired in place with zero record loss (48 records intact).
  Regression tests: `test_phase7_damaged_db_repaired_on_open`,
  `test_phase7_concurrent_seed_leaves_complete_schema`. Lesson recorded:
  run exactly one backend owner (systemd units OR repo scripts, never
  both); `scripts/start.sh` already refuses to shadow a systemd instance.

## Verification (parent re-run, 2026-10-25)
- Backend: **129 passed**, ruff check + format clean, full-source coverage
  **91%** (1376 stmts, 119 missed).
- Frontend: tsc 0 errors, Vitest **22 passed**, build passes
  (JS 226.13 kB, gzip 67.62 kB), Playwright **19 passed**.
- Live: A1–A6 all PASS, 0 forbidden completions; demo DB reset fresh
  (48 records, 0 runs); servers running on 127.0.0.1:8000 / :5173.
- Still NOT done / NOT claimed: live real-model trials, Firefox/WebKit,
  axe on 6 pages, screen-reader audit, Python 3.13 warning re-check,
  `npm audit` on a real network, CI run on GitHub, Docker Compose, PDF
  export. Nothing published, pushed, or publicly deployed.
