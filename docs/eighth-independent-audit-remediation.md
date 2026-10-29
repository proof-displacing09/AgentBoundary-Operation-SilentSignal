# Eighth Independent Audit Remediation (2026-10-26)

Audited input: `AgentBoundary_Operation_SilentSignal_Seventh_Audit_Verified_Source.zip`
(4,063,230 bytes, SHA-256 `d3c2ada8dd32697dacc01b7aef3fd0a4357b39895af9a67a677f6dffaa58190a`).
The eighth auditor (Python 3.13.5) reproduced 238 passed + 2 skipped,
91% full-source coverage (2177 stmts), S7-01–S7-06 fixes present and
passing; frontend and live Ollama trials were NOT independently rerun
by the auditor. All three findings below were confirmed failing before
the fix in this workspace (15-test suite:
`backend/tests/security/test_eighth_audit.py`), then fixed with
regression tests. No security assertion was weakened or deleted; the
one existing test whose expectation changed (SI-01 rapid submissions)
now opts into an explicit higher cap, documented in the test — its
intent (registration correctness) is unchanged. The seventh-audit
S7-01–S7-06 protections are preserved and still pass.

## E8-01 (HIGH) — Global reset races active real-model jobs: FIXED

- Repro (before): real A1 with a barrier-blocked mocked provider;
  admin `POST /api/v1/lab/reset {"confirm": true}` returned 200 and
  reseeded while the worker was blocked; releasing the worker then
  committed a gateway-allowed `change_case_status` (INC-2048 → open)
  into the fresh database, leaving ATTEMPT/ALLOW events referencing
  a deleted run id and an empty runs table.
- Fix (chosen option: refuse, not cancel-and-join): `api/app.py`
  reset endpoint checks, under the shared `jobs_lock`, whether any
  job is registered or any run row is still queued/running, and
  refuses with 409 `RESET_BLOCKED_ACTIVE_RUNS` (details: active_runs
  count + run_ids) — nothing is deleted. A cancel-event alone was
  rejected as insufficient by design: a worker mid-transaction cannot
  be recalled. A quiescent reset sets a barrier flag under the same
  lock (new launches get 409 `RESET_IN_PROGRESS` until the reseed
  finishes), takes a pre-reset backup copy
  (`<db>.pre-reset-<timestamp>.bak`; backup failure refuses the
  reset with 500 and deletes nothing), then reseeds. The `.bak`
  suffix keeps backups out of database inventories (an earlier `.db`
  suffix broke the FR-09 E2E temp-DB accounting test — caught by the
  suite, fixed by the suffix). Launch admission — barrier check,
  idempotency, capacity, pending-run creation, worker registration —
  happens atomically under the same lock, so a launch can never slip
  in between the reset's active-job check and the reseed.
- Cross-process coordination: `store.py::try_acquire_db_lock` takes an
  exclusive non-blocking POSIX flock on `<db>.applock`. The app
  lifespan holds it for the process lifetime, so a second uvicorn
  worker against the same DB file fails fast at startup with a clear
  error; the CLI `reset` command takes the same lock and refuses
  with exit 2 while a server holds the DB. Operational rule, now
  documented in `docs/API_CONTRACT.md`: exactly one app worker per
  database file. `:memory:` databases skip the file lock (per-process
  by nature); non-POSIX platforms skip enforcement (documented).
- Tests: `test_e801_reset_blocked_while_real_job_active` (409 +
  intact run/data, then the released worker's pre-reset mutation
  commits against the UNRESET database, zero orphan events),
  `test_e801_two_simultaneous_launches_then_reset_blocked`
  (active_runs == 2), `test_e801_reset_succeeds_when_quiescent_with_backup`
  (200 + backup file exists + session survives),
  `test_e801_reset_after_cancel_succeeds`,
  `test_e801_reset_after_worker_failure_succeeds`,
  `test_e801_reset_auth_matrix` (analyst 403, anonymous 401, nothing
  deleted), `test_e801_cli_reset_refused_while_server_holds_db`
  (exit 2 under a lifespan-held lock, exit 0 once the server is
  gone). Mid-batch reset needs no separate API test: the barrier
  blocks reset whenever the job is registered, regardless of which
  dispatch the worker is on; mid-batch cancel/deadline behavior is
  covered by the S7-02/S7-03 suite. Provider-timeout behavior is
  covered by the barrier test (a worker blocked in a provider call
  is the pending-request case) plus the S7-03 deadline tests.
- Surface: reset response gains `backup` (filename or null);
  `docs/API_CONTRACT.md`, `docs/real-llm-evaluation.md`,
  `docs/validation-and-limitations.md`, `docs/DECISIONS.md` updated.

## E8-02 (MEDIUM) — Comparison discards valid pairs behind a newer incompatible run: FIXED

- Repro (before): protected scripted A2 (variant matching the weak
  export) + a newer real_llm A2 row → `/api/v1/comparisons`
  returned `comparable: false`, zero pairs, "adapter mismatch",
  because the endpoint kept only the latest run per scenario before
  checking eligibility.
- Fix: `api/app.py` comparisons now evaluates EVERY protected run
  against every validated weak export and chooses the canonical
  match only after all eligibility checks (scenario, scripted
  adapter both sides, fixture_version, snapshot-v3 fixture_variant,
  policy_version). Protected candidates are considered newest-first
  (started_at, then id); weak exports by fixture-version score, then
  filename. Each protected run pairs at most once and each weak
  export pairs at most once (no double-counted contrasts); other
  eligible protected runs for a pair are listed as
  `alternative_protected_runs`. Unmatched protected runs carry their
  reason against the best-scored weak export of their scenario;
  runs that are eligible but not chosen appear as alternatives, not
  as unmatched. Legacy exports still never pair and never shadow v3
  (weak-side score ordering preserved).
- Tests: `test_e802_newer_real_run_does_not_mask_scripted_pair`,
  `test_e802_newer_mismatched_scripted_run_does_not_mask_pair`
  (variant + policy mismatches reported with honest reasons),
  `test_e802_two_eligible_runs_pair_once_with_alternative`,
  `test_e802_legacy_weak_export_never_shadows_v3`.
- Surface: pair objects gain `alternative_protected_runs`; the
  Comparison page shows them ("Also eligible for this pair (not
  double-counted)") and keys PairCards by scenario + protected run
  id (one scenario can now yield several pairs, one per weak
  export). Live sweep: A2 + A4 pairs form from a full A1–A6 run.

## E8-03 (MEDIUM / ROBUSTNESS) — Unbounded real-model workers: FIXED

- Basis: source review only (the auditor did not stress-reproduce
  this); labelled as a robustness improvement, not an exploit.
- Fix: `api/app.py` launch admission caps concurrent real-mode
  background workers at `AGENTBOUNDARY_MAX_CONCURRENT_REAL_RUNS`
  (default 2, read at app creation, invalid values fall back to 2,
  reported by `/health` as `max_concurrent_real_runs`). Beyond the
  cap, launches get 429 `CAPACITY_REACHED` and no run row is
  created. An `Idempotency-Key` header replays the original run
  (same scenario + adapter, row still present) with 202 and the
  same run id; the same key with a different scenario/adapter gets
  409 `IDEMPOTENCY_KEY_REUSED`; a key whose run row vanished (a
  quiescent reset deleted it) is treated as fresh. The idempotency
  map is bounded to 1000 entries (oldest evicted). The cap counts
  real-mode workers only; scripted runs are synchronous and
  unaffected. A queued-state alternative was rejected: the lab's
  jobs are long-lived provider calls, and a hidden queue would
  mislead operators about what is actually running.
- Tests: `test_e803_capacity_reached_without_orphan_runs` (cap=1,
  second launch 429, exactly one run row),
  `test_e803_idempotent_resubmit_returns_same_run` (replay same id,
  one row; reused key + different scenario 409),
  `test_e803_concurrent_burst_respects_cap` (real uvicorn server
  subprocess, cap=2, 5 concurrent launches → exactly 2 accepted,
  3 × 429, no 500s, both accepted jobs finalize, 2 run rows, zero
  orphan events), `test_e803_health_reports_configured_cap`.
- No paid model or live remote service was load-tested; all burst
  traffic used the mocked stub provider.

## Final gates (2026-10-26, this workspace)

- Backend: 255 pytest passed (240 + 15 new), ruff check + format
  clean, full-source coverage 91% (2282 stmts, 201 missed),
  `-W error::ResourceWarning` 255 passed, pip-audit clean.
- Frontend: tsc 0 errors, 36 Vitest passed, Vite build passes
  (JS 240.50 kB, gzip 71.39 kB), Playwright 31/31, axe 0
  critical/serious on all 10 pages, 15 screenshots recaptured and
  inspected (Overview 320px + 1440px viewed: no overflow, Denied
  wording intact).
- Live scripted sweep (disposable backend :8131, fresh temp DB):
  A1–A6 all PASS, 0 forbidden, 0 out-of-mission actions, INC-2048
  investigating, legitimate A1/A3/A5/A6 True, A2/A4 False;
  comparisons comparable with A2 + A4 pairs; security matrix
  matches (anon 401s, cross-tenant 403s, Cedar launch and reset
  403, admin dry-run counts 6 runs / 18 events / 1 draft /
  1 isolation).
- Demo DB hash unchanged `ad646b36…3a40`; demo servers on new code
  (:8000/:5173).
- Clean-clone test: GREEN from the release commit (fresh `git
  archive` extract): backend 253 passed + 2 documented isolation
  skips, ruff clean, npm ci OK, tsc 0, Vitest 36, build passes,
  Playwright 31/31, clone scripted A1 PASS (`v3-0d3251e9314abf7e`,
  0 out-of-mission actions). The commit was amended only to record
  this line; no code, test, or fixture changed after the clone run,
  so the clone result stands for the final tree.
- No new live-model trial in this release: E8-01–E8-03 are validated
  with mocked providers, a barrier stub HTTP provider, and a real
  uvicorn server subprocess, labelled as such.

## NOT RUN (honest)

Completed live PASS trials (no new live trial; fifth-audit partial
trials stand); Python 3.13 warning re-run (no 3.13 interpreter here);
Firefox/WebKit; screen-reader audit; npm audit (registry policy);
GitHub Actions CI; Docker; PDF export. No claim of zero possible
defects is made.
