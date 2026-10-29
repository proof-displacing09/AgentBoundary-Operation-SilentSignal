# AgentBoundary Pentest — Fix Traceability

Baseline `d376300` → final commit `938a63f` (branch
`pentest-hardening`). Every row below was reproduced on the unpatched
tree first, then fixed and re-proven. "Pre-fix" means the new regression
test was run against the unpatched code and failed as expected.

## Pentest findings (this round)

### P-01 — Anonymous scenario-detail exposure (LOW)

- Finding: `GET /api/v1/scenarios/{id}` returned the full scenario dict
  (injection fixture, legitimate steps, forbidden objective, expected
  outcome) without any session.
- Failing-first test:
  `tests/security/test_pentest.py::test_p01_scenario_detail_requires_session`
  — pre-fix: anonymous detail 200 (FAIL); post-fix: 401, authed 200.
- Code change: `backend/src/agentboundary/api/app.py` —
  `scenario_detail` now calls `require_session` and returns the 401 on
  failure. The list endpoint is untouched (public by F-01 decision).
- Supporting changes: `tests/integration/test_api.py::test_scenarios_catalog`
  now uses a session for the detail call; `docs/API_CONTRACT.md`
  documents the detail-session requirement.
- Post-fix tests: new test passes; `test_f01_anonymous_denied_on_research_routes`
  (list still 200) passes; full suite 317+2; Playwright 33/33.
- Positive controls: authed detail returns the full dict unchanged;
  Scenario Studio works through the UI (Playwright).
- Residual risk: lab sessions are self-minted, so this is contract
  consistency + defense in depth, not a barrier against a determined
  local actor. Stated plainly in the assessment.

### P-02 — Duplicate JSON keys silently collapsed (LOW)

- Finding: `POST /api/v1/runs` with two `scenario_id` keys executed the
  second one with no signal (Python `json.loads` last-wins).
- Failing-first test:
  `tests/security/test_pentest.py::test_p02_duplicate_json_keys_rejected`
  — pre-fix: 200 executing A2 (FAIL); post-fix: 400 INVALID_JSON.
- Code change: `backend/src/agentboundary/api/app.py` —
  `safe_json_body` parses with an `object_pairs_hook` rejecting any
  duplicate key at any depth. Covers session creation and run launches.
- Post-fix tests: new test passes (including a well-formed launch
  control at 200); full suite 317+2.
- Positive controls: all existing API tests pass unchanged; the
  frontend never emits duplicate keys (`JSON.stringify`).
- Residual risk: none. The reset endpoint keeps its own fail-closed
  parsing (malformed → treated as no confirmation); duplicate `confirm`
  keys there cannot escalate privilege (commander session already
  required).

### P-03 — Cancel/budget during inference + text-only reply misreported (LOW)

- Finding: a real-mode run cancelled while a provider call was in
  flight, where the reply carried no tool calls, finalized as
  INCONCLUSIVE instead of CANCELLED (contradicting the cancel
  endpoint's promise). Same gap for wall-budget expiry during inference.
- Failing-first tests:
  `tests/security/test_pentest.py::test_p03_cancel_during_inference_text_response`
  and `::test_p03_budget_during_inference_text_response` — pre-fix:
  both report `no_proposals` (FAIL); post-fix: `cancelled` /
  `budget_exhausted`.
- Code change: `backend/src/agentboundary/agents/real_agent.py` —
  cancel and deadline are rechecked in the no-tool-calls branch, before
  setting `completed`/`no_proposals`. The tool-carrying branch is
  untouched so batch proposals are still recorded as discarded.
- Process disclosure: the first attempt placed the recheck before the
  tool-calls branch and broke 4 S7 tests (batch-discard bookkeeping was
  skipped). The fix was rescoped; all S7 tests pass with the final
  patch. This is why the full suite was re-run after the rescope
  (317+2, strict warnings clean).
- Post-fix tests: new tests pass; all seventh-audit S7 tests pass;
  full suite 317+2; stub-provider cancel/capacity probe re-confirmed.
- Positive controls: normal text-only completion still reports
  `completed`/`no_proposals` when no cancel/budget signal exists;
  tool-carrying cancellation still discards the batch properly.
- Residual risk: a provider call that FAILS concurrently with a
  cancellation reports `provider_error` rather than `cancelled`. No
  extra work is dispatched; label precedence in that combined corner is
  documented, not changed.

### P-04 — CI token not least-privilege (LOW, static-only)

- Finding: `.github/workflows/ci.yml` declared no `permissions` block.
- Code change: top-level `permissions: contents: read`. Jobs only
  check out, install, test, and build; no push/publish/release step
  exists; no untrusted context is interpolated into any `run` block.
- Tests: none possible locally — CI has NOT run remotely (no remote
  exists). Labelled static-only, not claimed as tested behavior.
- Residual risk: action pins remain major-version tags, not SHAs
  (standard practice, deliberately not churned).

## Post-delivery follow-up findings (delegated frontend/LLM review)

Each item below was independently reproduced by the primary assessor
after the first hardened release; none is attributed on trust. All
four were fixed with failing-first tests in
`tests/security/test_pentest.py` (except F4, documentation only).

### F1 — Over-budget real-model proposals silently dropped (LOW)

- Finding: `RealAgent.execute` truncated batches at
  `tool_calls[:remaining]` and broke on the `remaining <= 0`
  fresh-response path without recording the dropped calls anywhere.
- Failing-first tests: `test_f1_over_budget_batch_proposals_recorded_as_discarded`
  (10 proposed / 8 dispatched / 2 must be recorded) and
  `test_f1_fresh_response_after_budget_exhausted_recorded_as_discarded`
  (second response after budget spent) — both failed pre-fix
  (`discarded_proposals == []`), both pass post-fix.
- Code change: `backend/src/agentboundary/agents/real_agent.py` —
  both drop points append every dropped call to
  `discarded_proposals` with reason `budget_exhausted`, mirroring the
  existing cancel/budget discard paths. Dispatch behavior unchanged.
- Post-fix tests: new tests pass; all S7 cancel/budget tests pass;
  full suite 321+2.
- Positive controls: normal in-budget batches record nothing extra;
  cancel/budget mid-batch discards keep their own reasons.
- Residual risk: none. The assistant message history still contains
  only dispatched calls (correct — history reflects what happened);
  `discarded_proposals` is the audit record for the rest.

### F2 — Variant manifest hashed the wrong mission string for A5/A6 (LOW)

- Finding: `experiment_manifest` hashed
  `SCENARIOS[sid]["legitimate_objective"]` while `RealAgent._mission`
  uses an override for A5/A6; the docstring's "every model-visible
  input" claim was overstated.
- Failing-first test:
  `test_f2_manifest_hashes_effective_mission` — pre-fix, A5/A6
  `mission_hash` did not match the override text's hash; post-fix it
  does.
- Code change: override dict moved to
  `backend/src/agentboundary/evaluation/scenarios.py` as
  `REAL_MISSION_OVERRIDES` (single source of truth; `real_agent.py`
  keeps `_MISSIONS` as an alias import); `mission_hash` hashes the
  effective mission text; docstring now states exactly what is and is
  not hashed (constant suffix and system message are code constants,
  not fixture inputs, and remain outside the digest by design).
- Post-fix tests: new test passes, including the guard that A1–A4
  no-store digests are unchanged; full suite 321+2.
- Positive controls: A1–A4 digests byte-identical pre/post fix, so
  stored weak exports (A2/A4) still pair; A5/A6 have no stored weak
  export, so their digest change breaks no comparison.
- Residual risk: none introduced. Prompt-text-only code edits to the
  suffix/system message still do not change the digest — now
  documented as intended, not claimed otherwise.

### F3 — Non-200 provider responses accepted (INFORMATIONAL)

- Finding: `LLMClient.complete` rejected only `>= 400`; 301/302/303/
  307/201 responses with a valid choices body were accepted.
- Failing-first test:
  `test_f3_non_200_provider_responses_rejected` — pre-fix, all five
  codes returned tool calls; post-fix, all raise `LLMError`.
- Code change: `backend/src/agentboundary/agents/llm_adapter.py` —
  after the 429/`>= 400` handling, any status other than exactly 200
  raises `LLMError("provider_error", ...)`.
- Post-fix tests: new test passes; all existing adapter tests pass;
  full suite 321+2.
- Residual risk: none. No legitimate OpenAI-compatible backend
  returns a non-200 success for chat completions; the provider URL
  remains operator-configured and redirects are never followed.

### F4 — Stale `useAsync` comment (INFORMATIONAL, documentation only)

- Finding: the comment claimed AbortController was unavailable as a
  cancellation channel; the API client tracks per-token controllers
  and `switchPersona()` aborts them.
- Code change: `frontend/src/components/ui.tsx` comment corrected to
  describe the two-layer cancellation (per-token abort + generation
  token). No behavior change, no test.

## Historical rounds — regression status after pentest changes

All prior audit invariants were re-verified by the full suite on the
final commit (317 passed + 2 skipped, strict warnings clean) and by the
targeted probes in the assessment. Summary of what each round
established and its current status:

- F-01–F-06 (first audit): anonymous denial on research routes,
  tenant-scoped reads, evaluation honesty foundations — GREEN
  (test_f01_* pass; P-01 deliberately preserves the F-01 list-public
  decision and only gates the detail endpoint).
- N-01–N-08: run-scoped verdicts, launch tenant rule, privileged
  reset, control filtering, tool_call_id metrics — GREEN.
- R-01–R-18: input typing, fixture views, exposure ledger, trial
  outcomes, provider policy foundations — GREEN.
- FR-01–FR-12: false-success/false-denial elimination, variant
  hashing, report integrity — GREEN.
- FA-01–FA-09: exposure causality (confirmed delivery only), local
  Ollama key handling, store lifecycle — GREEN.
- SI-01–SI-06: real-mode job registry, worker lifecycle, capacity —
  GREEN (plus P-03's cancel-finalization correction).
- S7-01–S7-06: cancel/budget discard bookkeeping — GREEN (P-03's first
  attempt broke 4 of these; the rescoped fix restores all of them).
- E8-01–E8-03: reset barrier, concurrency cap, worker registration —
  GREEN (stub capacity/cancel probe re-confirms).
- N9-01–N9-04: worker lifecycle errors, startup recovery,
  operator-scoped idempotency, portable burst test — GREEN.
- T10-01–T10-04: lock-before-construction, backup privacy/retention,
  report-download race, verified backups — GREEN.
- A11-01–A11-04: canonical DB identity, private temp backup,
  exception-safe Store, error normalization — GREEN.
- RC12-01–RC12-02: hardlink refusal, atomic reset transaction — GREEN
  (re-proven with real processes in probe4).
- QA-13-01: atomic-rename tolerance in the A11-02 stress test — GREEN
  (test file unchanged by this pentest; its tolerance is preserved and
  its 0600/backup-integrity assertions still pass in the full suite).

No historical invariant was weakened to fix a pentest finding. The two
places where a pentest change touched historical behavior are P-01
(detail gating, with the F-01 list decision explicitly preserved) and
P-03 (cancel finalization, with the S7 discard paths explicitly
preserved) — both verified by the suites that own those invariants.

## Post-delivery follow-up findings, round 2 (delegated persistence + API reviews)

Each item was independently reproduced by the primary assessor after
the F-round repackaging; none is attributed on trust. All fixes carry
failing-first tests in `tests/security/test_pentest.py` (except the
C5 residual and the C-02 intentional design, which have no code
change).

### C1 — Damaged DB missing only `cases` fully reseeded (MEDIUM)

- Finding: `Store.__init__` seeded whenever `cases` was absent;
  `seed()` DROPs all 13 tables. Reproduced: 1 run row became 0.
- Failing-first test: `test_c1_damaged_cases_table_preserves_runs`
  (pre-fix runs == 0; post-fix runs == 1, cases == 4).
- Code change: `backend/src/agentboundary/store.py` — seed only when
  the database has no tables at all; otherwise repair + migrate +
  backfill fixture rows, leaving existing rows untouched.
- Post-fix tests: new test passes; all repair/migration suites pass;
  full suite 335+2.
- Positive controls: fresh DBs still seed identically; databases
  with `cases` present take the same path as before; explicit
  `seed`/`reset` commands are unchanged (intentionally destructive).
- Residual risk: none introduced. A database missing `cases` AND
  `runs`/`events` still flags `degraded_tables` honestly for the
  recreated evidence tables.

### C2/C3 — Prune stamp/mtime + glob-escape (LOW)

- Finding: mtime sort deleted the newest-by-stamp backup; unescaped
  glob deleted a foreign database's backup. Both reproduced.
- Failing-first tests: `test_c2_prune_keeps_newest_by_stamp_not_mtime`,
  `test_c3_prune_does_not_match_foreign_db_backups`.
- Code change: `prune_backups` sorts by filename and escapes the DB
  path in the glob. S4 (getmtime race) disappears with the sort.
- Post-fix tests: new tests pass; all reset/backup suites pass.

### C4 — Lock acquisition on fresh nested paths (LOW)

- Finding: `FileNotFoundError` on a fresh nested DB path.
- Failing-first test: `test_c4_lock_acquisition_creates_nested_parent`.
- Code change: `try_acquire_db_lock` mkdirs the lock file's parent
  first (the lock path is now computed once and reused).

### C5 — Rename after acquisition yields a second holder (LOW, documented residual)

- Finding: reproduced both ways (DB rename, lock-file rename).
  Pathname-derived locking cannot survive renames by a directory
  writer; no safe narrow fix exists short of replacing the lock
  scheme. SQLite still serializes page writes; the precondition is
  outside the single-operator threat model.
- Change: documented in `canonical_db_path` and the assessment.
  No code change, no test (a test would only re-prove the
  limitation, not a fix).

### C6 — Symlink swap between lock and construction (LOW)

- Finding: fault-injected swap left a store on the victim's file
  while the victim lock was held.
- Failing-first test:
  `test_c6_lock_to_construction_symlink_swap_refused` (pre-fix the
  CLI returned a store on the victim file; post-fix it refuses with
  (None, None) and the victim lock intact).
- Code change: new `verify_store_matches_lock` in `store.py`,
  called by the CLI (`_acquire_main_store`, which closes a
  constructed store on refusal) and the API lifespan (same).
- Post-fix tests: new test passes; all lock/alias suites pass.

### S1/S2/S3/S4 — Backup verification hardening (LOW)

- S1: counted tables now equal all 13 required tables (contract
  test `test_s1_backup_counts_all_required_tables`).
- S2: temp file fsynced in `verified_backup`; new best-effort
  `fsync_dir` called by both reset handlers after rename (test
  `test_s2_backup_fsyncs_temp_file`).
- S3: source connects via `mode=rw` URI (test
  `test_s3_source_vanish_leaves_no_stray_file`, with a connect
  wrapper that deletes the source mid-backup).
- S4: eliminated by the C2 stamp sort (no stat call remains).

### S5/S6 — CLI backup parity + gitignore (LOW)

- S5: CLI reset now takes a verified pre-reset backup (0600,
  retention 5) before reseeding; backup failure refuses exit 2 with
  the DB untouched (test `test_s5_cli_reset_takes_pre_reset_backup`).
  The API handler was deliberately NOT refactored (its sequence is
  eleventh-audit blessed; the CLI mirrors it).
- S6: `*.bak.tmp` added to `.gitignore` (test
  `test_s6_gitignore_covers_backup_temps` via `git check-ignore`).

### A-C03/A-C04/A-C05/A-C06 — Session lifecycle + matrix wording

- A-C03: new `POST /api/v1/lab/session/revoke` (caller's own row
  only) + frontend best-effort revoke on persona switch (raw fetch,
  never blocking). Test `test_a03_session_revoke`. The switch wiring
  did not break any Vitest session-isolation test (40/40).
- A-C04: `Store` forces the DB file to 0600 on open (POSIX,
  best-effort). Test `test_a04_live_db_file_is_private` (umask
  pinned to 022 in the test so the pre-fix 0644 fails first).
  Token hashing deliberately not done (see assessment).
- A-C05: session creation purges expired rows. Test
  `test_a05_session_creation_purges_expired_rows`. No rate limit
  added (documented as accepted for a local-only lab).
- A-C06: matrix entry now states non-sensitive transitions need no
  approval. Test `test_a06_policy_matrix_states_nonsensitive_needs_no_approval`.
  No field shape changed (frontend compatibility preserved).
