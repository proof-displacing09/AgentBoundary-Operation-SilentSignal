# Ninth Independent Audit Remediation (2026-10-26)

Audited input: `AgentBoundary_Operation_SilentSignal_Eighth_Audit_Verified_Source.zip`
(4,077,467 bytes, SHA-256 `c384dc509ce777a8235f7f813aef1205115f97b0fe64d8597e68f17fddb2b431`).
The ninth auditor (Python 3.13) reproduced 252 passed + 2 skipped with
the subprocess burst test deselected (it hardcodes a `.venv` path and
port 8130); frontend and live Ollama trials were NOT independently
rerun by the auditor. All four findings below were confirmed failing
before the fix in this workspace (19-test suite:
`backend/tests/security/test_ninth_audit.py`, plus the rewritten
eighth-audit burst test), then fixed with regression tests. The
failing-first proof is a `git stash` round-trip of `api/app.py` only:
9 of the 19 new tests failed against the pre-fix code and all 19 pass
with the fix (the other 10 cover behavior that already held —
Runner-construction finalization, thread-start finalization,
running-row recovery, cancelled rows, E8-era replay/409/cap/reset
semantics — and are kept as regression locks). No security assertion
was weakened or deleted. The eighth-audit E8-01–E8-03 protections are
preserved and still pass.

## N9-01 (HIGH) — Worker Store failure strands a run and blocks reset: FIXED

- Repro (before, auditor's patch): `agentboundary.api.app.Store`
  patched to raise OSError in the background worker; POST real A1
  → 202; GET stayed `queued`/`INCONCLUSIVE` after the thread
  crashed; reset → 409 indefinitely; Python printed an unhandled
  worker-thread exception.
- Fix: the ENTIRE worker lifecycle is guarded — `Store(store.path)`
  moved inside `try/except/finally` (it previously sat outside, so
  an open failure skipped both finalization and the registry pop).
  Any failure finalizes the run as ERROR with a sanitized class
  (`worker_startup_error` when the worker's Store never opened,
  `worker_error` otherwise; no tracebacks or credentials in stored
  metrics), closes any Store that was opened, and pops the registry
  entry. Finalization falls back in order: the worker's own store, a
  fresh short-lived connection (closed after use), the app's healthy
  store (already open, `check_same_thread=False` + RLock-guarded, so
  thread-safe by construction). If every fallback fails, the run
  stays queued until N9-02 startup recovery marks it INTERRUPTED —
  never silently dropped, and a warning is logged for operators.
  A thread that fails to start reports ERROR in the launch response
  itself, never as a running job.
- Tests: `test_n901_worker_store_open_failure_finalizes_error`
  (auditor's always-raise patch; ERROR + finished_at + class, zero
  thread exceptions via a recording excepthook, no leaked Stores,
  reset → 200, then 2 fresh jobs launch within the cap after the
  patch is lifted),
  `test_n901_worker_store_schema_failure_finalizes_via_fresh_connection`
  (fail-once Store → fresh-connection finalization),
  `test_n901_runner_construction_failure_finalizes_via_worker_store`
  (fails only the worker's Runner construction — the handler's own
  Runner construction for `create_pending_run` comes first and must
  succeed),
  `test_n901_thread_start_failure_is_error_not_running`.

## N9-02 (HIGH) — Queued runs survive restart and block reset: FIXED

- Repro (before, auditor's steps): `Runner.create_pending_run`
  writes `queued` before `thread.start`; a fresh app lifespan left
  the row `queued` (lifespan recovered only `status='running'`),
  and reset → 409 with the orphaned run id and no worker to
  complete it.
- Fix: lifespan recovery now covers `status IN ('queued','running')`,
  after acquiring the database process lock and before accepting
  requests. No worker survives a whole-process restart, so both
  states are provably orphaned. Recovered runs become
  `interrupted` / `INCONCLUSIVE` with `error_class=interrupted`,
  `recovered_at` set, `started_at` and committed events preserved —
  never mislabeled a completed model trial. Completed, cancelled,
  error, and inconclusive rows are untouched. A denied second worker
  now also closes its store before raising, so the failed lifespan
  leaks no connection (previously the store stayed open in the
  embedding process).
- Tests: `test_n902_queued_row_recovered_as_interrupted` (plus reset
  → 200 in the same lifespan),
  `test_n902_running_and_completed_rows` (completed row
  byte-unchanged),
  `test_n902_queued_and_running_together_no_case_mutation` (both
  recovered, INC-2048 still `investigating`, zero orphan events),
  `test_n902_two_competing_workers_denied_no_data_loss` (second app
  denied by `.applock`, live-store count back to 1, first app still
  healthy, second app starts after the first exits),
  `test_n902_cancelled_row_does_not_block_reset`.

## N9-03 (MEDIUM) — Idempotency keys not scoped to operator: FIXED

- Repro (before, auditor's steps): Northstar analyst launches real
  A1 with key `reuse-me` → 202; Incident Commander with the same key
  → 202 with the SAME run id and `operator_persona_id=
  analyst_northstar`, instead of their own run.
- Fix and documented scope decision: keys are now
  (trusted operator persona id, header) pairs. The same operator
  under a fresh session replays — sessions are ephemeral tokens for
  the same lab operator, and raw session tokens are never stored —
  while a different operator never inherits another operator's run,
  however the header collides. Same operator + key + different
  scenario/adapter → 409 `IDEMPOTENCY_KEY_REUSED`. Replay happens
  before the capacity gate and consumes no slot. Keys expire after
  3600 s (`IDEMPOTENCY_TTL_SECONDS`, monkeypatchable to 0 in tests),
  are cleared by a successful reset, and are stale — launching fresh
  — when the prior run row is gone or the prior run ended in error
  or cancelled (no result to replay). Keys over 256 characters →
  400 `INVALID_REQUEST` with no run created. Tenant checks still run
  before admission, so operator scoping never bypasses tenant
  denial. Model configuration is server-global per process, so
  same-process replays share it by construction. The 1000-entry
  insertion-ordered bound is unchanged.
- Tests: `test_n903_same_operator_new_session_replays`,
  `test_n903_same_operator_different_request_409`,
  `test_n903_different_operator_same_key_independent` (also asserts
  per-operator attribution in GET /runs; lists are tenant-scoped by
  design, so the commander's Northstar-tenant run is visible to the
  Northstar analyst but attributed to the commander),
  `test_n903_different_tenant_still_denied`,
  `test_n903_replay_at_cap_returns_original`,
  `test_n903_reset_invalidates_key`,
  `test_n903_error_run_key_launches_fresh`,
  `test_n903_expired_key_launches_fresh`,
  `test_n903_key_length_bounded`.

## N9-04 (MEDIUM / TEST INFRASTRUCTURE) — Portable burst test: FIXED

- Basis: test-harness defect only; the auditor explicitly states
  this is NOT evidence the concurrency cap is defective.
- Fix: `test_e803_concurrent_burst_respects_cap` now runs the child
  under `sys.executable` (whatever interpreter runs pytest), on a
  free loopback port allocated per test (no fixed 8130, so
  concurrent suites cannot collide), with `PYTHONPATH` set
  explicitly to the repo's `backend/src` (works without an editable
  install), loopback-only binding, bounded health polling with an
  explicit healthy assertion, and the child's log attached to every
  burst assertion. Child and stub are terminated/closed on all
  paths. The burst still proves, on a real uvicorn server: 5
  concurrent launches, cap 2 → exactly 2 × 202 + 3 × 429
  `CAPACITY_REACHED`, both accepted jobs finalize, 2 run rows, zero
  orphan events.
- Test: `test_n904_concurrent_same_key_creates_one_run` (new, same
  portable pattern) proves 5 concurrent same-operator same-key
  launches create exactly one run, every caller getting 202 with
  the same id.

## Final gates (2026-10-26, this workspace)

- Backend: 274 pytest passed (255 + 19 new), ruff check + format
  clean, full-source coverage 92% (2317 stmts, 187 missed),
  `-W error::ResourceWarning` 274 passed, pip-audit clean.
- Frontend: tsc 0 errors, 36 Vitest passed, Vite build passes
  (JS 240.50 kB, gzip 71.39 kB), Playwright 32/32 (31 + new keyboard
  Tab-reachability test), axe 0 critical/serious on all 10 pages,
  15 screenshots re-verified (Overview 320px + Scenarios 390px
  viewed; Comparison inspected one-off at 1440 and fresh-context
  320 — both clean; see `docs/ui-qa.md` for the resize artifact
  that was investigated and ruled out).
- Live scripted sweep (disposable backend :8133, fresh temp DB):
  A1–A6 all PASS, 0 forbidden, 0 out-of-mission actions, INC-2048
  investigating, legitimate A1/A3/A5/A6 True, A2/A4 False;
  comparisons comparable with A2 + A4 pairs; security matrix
  matches (anon 401s, cross-tenant 403s, Cedar launch and reset
  403, admin dry-run counts 6 runs / 18 events / 1 draft /
  1 isolation); weak A2/A4 CLI exports FAIL with forbidden=1 and
  variants matching protected; sentinel absent from weak exports.
- Demo DB hash unchanged `ad646b36…3a40`; demo servers on new code
  (:8000/:5173).
- Clean-clone test: GREEN from the release commit (fresh `git
  archive` extract): backend 272 passed + 2 documented isolation
  skips, ruff clean, npm ci OK, tsc 0, Vitest 36, build passes,
  Playwright 32/32, clone scripted A1 PASS (`v3-0d3251e9314abf7e`,
  0 out-of-mission actions). The commit was amended only to record
  this line; no code, test, or fixture changed after the clone run,
  so the clone result stands for the final tree.
- No new live-model trial in this release: N9-01–N9-04 are validated
  with mocked providers, a barrier stub HTTP provider, and real
  uvicorn server subprocesses, labelled as such. Ollama is not
  installed in this VM (replaced since the fifth audit), so no local
  trial could be attempted.

## NOT RUN (honest)

Completed live PASS trials (no new live trial; fifth-audit partial
trials stand; Ollama absent here); Python 3.13 warning re-run (no
3.13 interpreter here); Firefox/WebKit; screen-reader audit; npm
audit (registry policy); GitHub Actions CI; Docker; PDF export. No
claim of zero possible defects is made.
