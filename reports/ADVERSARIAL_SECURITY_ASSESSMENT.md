# AgentBoundary: Operation SilentSignal — Adversarial Security Assessment

## Final verdict

**4 CONFIRMED DEFECTS FOUND AND FIXED — all LOW severity. No critical,
high, or medium in-scope defect was reproduced.**

Post-delivery addendum (see §"Post-delivery addendum" at the end): the
delegated frontend/LLM review arrived after the first hardened release
and added **2 more confirmed LOW defects (F1, F2) and 2 informational
items (F3, F4), all fixed** with failing-first tests. The totals for the
repackaged release are therefore **6 LOW + 2 informational, all fixed**;
still no critical, high, or medium defect.

This was a final-stage adversarial assessment, not a feature project. The
application survived endpoint-by-endpoint authorization probing, tool-gateway
abuse, approval replay and concurrency races, prompt-injection red-teaming
through a stub provider, filesystem/lock/reset/backup fault injection with
real OS processes, input fuzzing, and mutation negative controls. Every
confirmed defect below has a root-cause patch and a failing-first regression
test. Nothing was published, deployed, pushed, or sent anywhere outside the
local test environment.

## Scope and tested build

- Baseline: commit `d376300` (QA-13-01), verified before any change: tree
  clean, provided ZIP SHA-256
  `9d6ba867ffc73a03446bb54040ce3b6955c4112f33a13a1ffeec33afe314015f`,
  demo DB hash `ad646b36…3a40`.
- Work: dedicated branch `pentest-hardening` in a separate worktree
  (`~/workspace/agentboundary-pentest`); `master` was left untouched at
  `d376300`, so the baseline is recoverable exactly.
- Final commit: `938a63f` (6 files: 2 production, 1 CI, 1 doc, 2 test
  files). The final ZIP is built from this commit; see
  `RELEASE_MANIFEST.md`.
- Demo DB hash after all testing: `ad646b36…3a40` (unchanged). The
  previous final ZIP is untouched. All destructive/exploit tests used
  disposable databases and loopback-only servers. No paid model service,
  no external endpoint, no real credential was used at any point.

## Threat model (what "secure" means here)

- Deployment target is a local POSIX/Linux lab on localhost. The persona
  selector is explicitly NOT production authentication: any local user can
  mint any lab session, including incident_commander. Session gating
  therefore provides contract consistency, auditability, and defense in
  depth — not access control against a determined local actor. Findings
  are graded on that model; nothing below is inflated into a
  "remote exploit."
- Attackers in scope: (a) a local browser/API caller with a low-privilege
  session trying to reach another tenant's data or trigger sensitive
  actions; (b) model output and poisoned fixture/runbook/log data trying
  to launder instructions into tool execution; (c) a local operator
  process racing locks, resets, and backups; (d) malformed input trying
  to crash or confuse validation, export, or reporting.
- Out of scope: internet-facing hardening, production SSO, real SIEM/EDR
  integration, and any claim that scripted results prove real-model
  behavior.

## Attack-surface inventory (enumerated from the implementation)

- FastAPI routes (30 incl. docs): `GET /health`, `GET /api/v1/health`,
  `GET /api/v1/settings`, `GET /api/v1/lab/personas` (public by design),
  `POST /api/v1/lab/session`, `GET /api/v1/lab/identity`,
  `POST /api/v1/lab/reset`, `GET /api/v1/overview`, `GET /api/v1/scenarios`,
  `GET /api/v1/scenarios/{id}`, `POST /api/v1/runs`,
  `POST /api/v1/runs/{id}/cancel`, `GET /api/v1/runs`,
  `GET /api/v1/runs/{id}`, `GET /api/v1/runs/{id}/events`,
  `GET /api/v1/events`, `GET /api/v1/alerts`, `GET /api/v1/alerts/{id}`,
  `GET /api/v1/cases`, `GET /api/v1/cases/{id}`, `GET /api/v1/runbooks`,
  `GET /api/v1/policy/matrix`, `GET /api/v1/findings`,
  `GET /api/v1/comparisons`, `GET /api/v1/reports/{id}/json`,
  `GET /api/v1/reports/{id}/markdown`, plus `/docs`, `/redoc`,
  `/openapi.json`. No websockets, no streaming, no raw tool-invocation
  endpoint, no approval-creation endpoint, no weak-mode API flag.
- Six tools, all through one strict dispatcher: `get_alert`,
  `search_runbooks`, `read_case`, `draft_response`, `change_case_status`,
  `simulate_isolation`. Schemas are pydantic `extra="forbid"` with length
  and range bounds; spoof keys (`tenant_id`, `role`, `approved`,
  `actor_id`, `user_id`, `is_admin`, `skip_auth`) are never authority.
- Ten frontend pages: Overview, Investigation, Scenarios, Replay, Policy,
  Comparison, Findings, Evidence, Reports, LabSettings. Session token is
  sent as `X-Lab-Session`; no cookies are used, so cookie-CSRF does not
  apply. CORS origins are restricted to the Vite dev origins.
- CLI entry points: protected `run`, offline weak `run-weak` (requires
  `AGENTBOUNDARY_UNSAFE_LAB=1` and owns a throwaway DB), `run-real`
  (refuses when unconfigured). Provider configuration comes only from
  server-side environment, never from API requests.
- Untrusted inputs tested: session headers, JSON bodies (incl. duplicate
  keys, NaN, oversized, mistyped, nested), query strings, IDs (SQLi
  shapes, traversal, unicode, NUL, zero-width), model tool calls, provider
  responses, fixture/runbook/note text, CLI parameters, DB path aliases,
  backup filenames, Idempotency-Key values.

## Findings

### P-01 (LOW, CONFIRMED, FIXED) — Anonymous scenario-detail exposure

- Location: `backend/src/agentboundary/api/app.py`, `scenario_detail`.
- Proof (unpatched): anonymous `GET /api/v1/scenarios/A2` returned 200
  with the full scenario dict: injection fixture text, legitimate steps,
  forbidden objective, and expected outcome — the evaluation answer key.
  The scenario *list* is public by the documented F-01 decision
  (titles/categories only, no case content); the detail was not covered
  by that decision.
- Threat: local unauthenticated disclosure of lab curriculum/answer key.
  No tenant secret is in scenario definitions (verified: the Cedar
  sentinel appears nowhere in `scenarios.py`), and any local actor can
  mint a session, so this is contract consistency and defense in depth,
  not a barrier against a determined local user. Graded LOW honestly.
- Fix: `scenario_detail` now requires a session (`require_session`);
  the list stays public. Frontend already sends the session token when
  present, and the Playwright suite (33/33) passes with the gate active.
- Regression: `tests/security/test_pentest.py::test_p01_scenario_detail_requires_session`
  (fails pre-fix: anonymous detail 200; passes post-fix: 401, authed 200).
  `tests/integration/test_api.py::test_scenarios_catalog` updated to use
  a session for the detail call; the F-01 list-public assertion is
  unchanged. Doc: `docs/API_CONTRACT.md` updated.
- Residual: none beyond the stated threat-model caveat.

### P-02 (LOW, CONFIRMED, FIXED) — Duplicate JSON keys silently collapsed

- Location: `backend/src/agentboundary/api/app.py`, `safe_json_body`.
- Proof (unpatched): `POST /api/v1/runs` with body
  `{"scenario_id": "A1", "scenario_id": "A2"}` returned 200 and executed
  A2 (Python `json.loads` last-wins). The executed scenario differs from
  the first one a reader sees, with no signal.
- Threat: ambiguous-input reinterpretation. The resulting run was still
  fully authorized and tenant-checked, so impact is limited to
  determinism/honesty of the request, not privilege. Graded LOW.
- Fix: `safe_json_body` now parses with an `object_pairs_hook` that
  raises on any duplicate key at any depth, producing 400 INVALID_JSON.
  Covers session creation and run launches (the endpoints that use this
  parser). The reset endpoint keeps its own fail-closed parsing
  (malformed body is treated as no confirmation); duplicate `confirm`
  keys there cannot escalate privilege because reset already requires a
  commander session.
- Regression: `tests/security/test_pentest.py::test_p02_duplicate_json_keys_rejected`
  (fails pre-fix: 200; passes post-fix: 400, plus a well-formed launch
  control at 200).
- Residual: none.

### P-03 (LOW, CONFIRMED, FIXED) — Cancel/budget during inference + text-only reply misreported

- Location: `backend/src/agentboundary/agents/real_agent.py`,
  `RealAgent.execute` loop.
- Proof (unpatched): a stub-provider real-mode run cancelled while a
  model call was in flight, where the reply carried no tool calls,
  finalized as status `inconclusive` / verdict `INCONCLUSIVE` instead of
  `cancelled` / `CANCELLED`. The cancel endpoint's own docstring promises
  "the run finalizes as CANCELLED," and the agent docstring promises a
  recheck "after every provider response" — but the recheck only existed
  on the tool-carrying branch. The same gap applied to wall-budget expiry
  during inference with a text-only reply.
- Threat: none to authorization — no further work was dispatched after
  cancellation, and no mutation occurred. Impact is metrics/reporting
  accuracy: cancelled runs inflated inconclusive counts, and an
  inconclusive run's idempotency key replays the dead result until TTL
  expiry instead of allowing a fresh launch (cancelled runs are treated
  as no-result). Graded LOW.
- Fix: the loop now rechecks cancel and deadline in the no-tool-calls
  branch, before setting `completed`/`no_proposals`. The tool-carrying
  branch is deliberately untouched so proposals are still recorded as
  discarded (S7-02/S7-03).
- Process note (not hidden): the first fix attempt placed the recheck
  before the tool-calls branch and broke 4 S7 tests
  (`test_s702_*`, `test_s703_*`), because it skipped batch-discard
  bookkeeping. The fix was rescoped to the no-tool-calls branch only;
  all S7 tests pass with the final patch.
- Regression: `tests/security/test_pentest.py::test_p03_cancel_during_inference_text_response`
  and `::test_p03_budget_during_inference_text_response` (both fail
  pre-fix with `no_proposals`; both pass post-fix).
- Residual: if a provider call FAILS (timeout/transport error) at the
  same moment as a cancellation, the outcome is `provider_error` rather
  than `cancelled`. No extra work is dispatched either way; the label
  precedence in that combined corner is left as-is and documented here.

### P-04 (LOW, STATIC-ONLY, FIXED) — CI token not least-privilege

- Location: `.github/workflows/ci.yml`.
- Proof: the workflow declared no `permissions` block, so its token
  carried the repository default instead of the minimum the jobs need.
  The jobs only check out, install, test, and build — no push, publish,
  or release step exists, and no untrusted GitHub context is
  interpolated into any `run` block (verified by grep).
- Fix: top-level `permissions: contents: read`.
- Regression: none possible locally — CI has NOT run remotely (no remote
  exists). This is a static hardening, labelled as such, not a tested
  behavior change.
- Residual: action pins remain major-version tags (`@v4`/`@v5`), not
  commit SHAs. That is standard practice and was not churned; noted as
  informational only.

## Verified non-issues and intentional design (with evidence)

Each of these was attacked or inspected and did NOT reproduce as a defect.
They are recorded so a future reviewer does not re-litigate them as
"missed findings."

- Cross-tenant access (API + dispatcher): every probed cross-tenant read
  (cases, runs, events, reports JSON/Markdown, alerts, drafts, isolation)
  returned 403/`TENANT_DENIED` with `data=None`; lists, runbook search,
  and events are tenant-filtered server-side. Cedar run list never
  contains Northstar runs; the Cedar sentinel appears in no weak export,
  no northstar response, and no comparison pair.
- Approval gate: status-bound, requester-bound, expiry-checked, and
  single-use (conditional `UPDATE ... WHERE used=0` with rowcount check
  inside the mutation transaction). 8 concurrent consumers of one
  approval produced exactly 1 ALLOW and 1 isolation row. Status aliases
  (`Closed`, `CLOSED`, unknown, same-status) are `TRANSITION_INVALID`.
  Model-supplied spoof fields produce `SPOOF_IGNORED` denials.
- Weak mode: `mode: "weak"` and `tenant_id` overrides in API run bodies
  are ignored (runs stay protected); weak behavior exists only in the
  offline CLI behind `AGENTBOUNDARY_UNSAFE_LAB=1` on a throwaway DB.
- Session handling: tokens are `secrets.token_hex(24)` (192 bits),
  stored server-side with expiry, looked up by exact match. Whitespace
  padding is stripped by the HTTP layer (standard OWS handling), not by
  the app — a padded token still requires the exact token value, so this
  is not a bypass. Uppercase/empty/bogus tokens are 401. HEAD on API
  routes is 405 (no bypass, no data). Unknown personas are 400.
- 403-vs-404 oracle: an existing other-tenant object returns 403 while a
  missing id returns 404, so existence is distinguishable. This is
  ACCEPTED intentional design: denial observability (`TENANT_DENIED`) is
  a core evaluation invariant (A4/A5 verdicts depend on it), and the ids
  are synthetic and largely predictable. Not fixed, by design.
- Public endpoints: `/health`, `/settings`, `/lab/personas`, and the
  scenario list are intentionally public (operational info, login
  selector metadata, and the documented F-01 curriculum list). They
  expose no tenant data, no token, no key, and no path.
- Input robustness: SQLi-shaped ids are parameterized lookups
  (`NOT_FOUND`, tables intact); traversal ids are plain DB lookups
  (`NOT_FOUND`); unicode/whitespace/NUL variants are exact-match
  `NOT_FOUND`; mistyped/nested args are `INVALID_ARGS`; NaN is a 400;
  bodies over 64 KiB are 413; pydantic string-to-int/bool-to-int coercion
  on `limit` stays within the 1–20 bound (harmless). 500-iteration
  dispatcher fuzz and 250-request HTTP fuzz produced zero exceptions and
  zero 5xx (a few 422s from mistyped query params are standard FastAPI
  validation, not leaks).
- Stored draft script payload: `<script>alert(1)</script>` in a draft
  summary is stored verbatim as data and rendered by React as text.
  No `dangerouslySetInnerHTML`, markdown renderer, or DOMPurify bypass
  exists in the frontend source (verified by grep). Stored-XSS via drafts
  does not reproduce.
- Provider trust: base URLs come only from server-side env, never from
  requests. `https` is required for remote hosts; plaintext `http` only
  for loopback with explicit opt-in; redirects are never followed
  (httpx default); loopback providers bypass proxy env (so the sandbox's
  bracketed-IPv6 `NO_PROXY` cannot break them); in local-Ollama mode no
  `Authorization` header is sent even when a stray key is configured
  (verified live against the stub: header absent on all calls).
  Hostname tricks (`localhost.`, `0.0.0.0`, `::ffff:127.0.0.1`,
  `127.0.0.1@evil.com` forms) fail closed by hostname-string comparison.
- Filesystem/process: second process, symlink alias, and hardlink alias
  on the same DB are all refused (exit 3) with the DB byte-identical;
  the surviving path starts cleanly after the owner exits. Backups are
  created 0600, verified (integrity + schema + row counts), renamed
  atomically, retained newest-5 without deleting the last. Garbage DB
  files raise a clean `DatabaseError`; a dropped table is repaired on
  open. Reset is a single transaction with a barrier that refuses
  launches/sessions with retryable 409 while active.
- Real-mode safety: malicious stub-model output (unapproved close +
  cross-tenant read) produced `APPROVAL_REQUIRED` + `TENANT_DENIED`,
  0 completed forbidden, INC-2048 unchanged, and an honest INCONCLUSIVE
  verdict (not an inflated PASS). Capacity: 2 concurrent real runs
  admitted, 3rd returned 429 `CAPACITY_REACHED`; cancels worked and a
  post-cancel launch was admitted.
- Session tokens in the database/backups: tokens are stored unhashed in
  the `sessions` table, so a backup file contains them. Accepted for a
  local lab: backups are 0600, local-only, and never shipped in the ZIP
  (verified absent from the archive listing and extracted contents).
  Hashing session tokens would be a production-auth measure; it is out
  of scope for self-minted lab personas and was not churned.
- Commander empty-query runbook truncation: with the default `limit=5`,
  an empty-query search for the commander (both tenants) returns the
  first 5 matches and can omit the Cedar runbook; a specific query finds
  it. This is pagination truncation, not a leak (no cross-tenant data is
  ever returned to a single-tenant caller). Not changed: altering the
  default limit could affect evaluation metrics.
- CORS: origins restricted to the Vite dev origins; an evil origin gets
  no `Access-Control-Allow-Origin` and (for preflight) a 400. Methods and
  headers are `*` but origins are not, and no credentials mode is used.

## Independent proof logs (all actually executed)

- `~/workspace/pentest/probe1.py` — auth/session/tenant/IDOR/method/
  header/CORS/input-shape battery: 46/53 expectations matched on first
  run; the 7 mismatches were the P-01 finding (2), the documented
  public endpoints (3: scenarios list, personas, settings), HEAD 405
  (2: expectation error, not an app defect), and the whitespace-token
  case (HTTP OWS, not a bypass).
- `~/workspace/pentest/probe2.py` — dispatcher approval abuse:
  aliases, binding, expiry, requester mismatch, single use, 8-thread
  concurrent consumption, unknown/case-variant tools, cross-tenant
  reads, runbook scoping, draft limits, spoof keys. All held.
- `~/workspace/pentest/probe3.py` — SQLi/traversal/unicode/mistyped/
  boundary input shapes. All held.
- `~/workspace/pentest/probe4.py` — real-process lock/symlink/hardlink
  refusal, backup mode/integrity/row counts, garbage-DB and
  missing-table handling. All held.
- `~/workspace/pentest/probe5.py` — stub-provider malicious-model run
  and slow-stub capacity/cancel test (both phases). All held except
  P-03 (cancel-during-inference labelling), now fixed and re-proven by
  `test_pentest.py`.
- `~/workspace/pentest/probe6.py` — seeded fuzz (seed 20261027): 500
  dispatcher calls (all DENY, 0 escaped exceptions, no sensitive
  mutation) + 250 HTTP calls (no 5xx). Note: random malformed args
  mostly exercise the validation layer; valid-shape behavior is covered
  by probes 2–3.
- `~/workspace/pentest/sweep.py` — scripted A1–A6 sweep on the final
  tree: all PASS, 0 forbidden, INC-2048 investigating, comparisons
  comparable with 2 pairs (protected PASS + weak FAIL), dry-run
  6/18/1/1, weak CLI A2/A4 FAIL with matching variants, sentinel absent.
- Mutation negative controls (temporary worktree mutations, reverted
  with `git checkout`, verified clean after): bypassing
  `Authorizer.check_tenant` fails 4 dispatcher tenant tests; breaking
  approval consumption fails 3 approval tests (incl. A6 lifecycle).
  A first attempt using `PYTHONPATH` overrides did not affect pytest
  imports (editable-install hook wins); the worktree-mutation method
  above is the valid proof. The API-level cross-tenant test passing
  under the dispatcher mutation is itself defense-in-depth evidence:
  the API layer enforces tenant scoping independently.
- Full gates on the final commit (see `COMPLETE_TEST_MATRIX.md`).

## Verification limits — what was NOT run (honest list)

- Completed live Ollama PASS trial: NOT RUN. Ollama is not installed in
  this VM, and no live model was available. Scripted PASS is not
  live-model evidence. A stub provider was used for real-mode paths;
  that validates the gateway and orchestration, not model behavior.
- Python 3.13 strict run locally: NOT RUN (no 3.13 interpreter in this
  VM). Python 3.12.3 strict (`-W error::ResourceWarning`) passed.
- Firefox/WebKit: NOT RUN (only Chromium Playwright was available).
  Screen-reader audit: NOT RUN (axe is automated only, not a full audit).
- npm audit: NOT RUN (registry policy denies the audit endpoint:
  `policy_denied`). pip-audit on the pinned backend stack: clean
  ("No known vulnerabilities found").
- GitHub Actions CI: NOT RUN remotely (no remote exists). The workflow
  was statically reviewed only.
- Docker, PDF export: NOT RUN.
- Disk-full simulation: NOT RUN (no practical way to simulate ENOSPC
  on this filesystem without special mounts; backup failure paths are
  covered by fault-injection tests in the suite instead).
- Delegated review reports: three read-only review agents (API/auth,
  persistence, frontend/LLM) completed per the runtime, but their full
  report texts were not delivered into this conversation, so NO finding
  in this document is attributed to them. Every finding above was
  independently reproduced and verified by the primary assessment
  (probes 1–6, sweep, mutation controls, and code reads). If those
  delegated texts surface later with a new confirmed defect, it will be
  handled as a follow-up; nothing here claims their coverage.
- No claim of 100% security or 100% coverage is made. Coverage on the
  final tree is 91% statement coverage (2544 stmts, 237 missed); branch
  coverage was not separately measured.

## Post-delivery addendum — delegated frontend/LLM review (F1–F4)

After the first hardened release was delivered, the detailed report of
the delegated frontend/LLM review arrived (the other two delegated
reviews — API/auth and persistence — are still outstanding; if they
surface a confirmed defect it will be handled the same way). Its
findings were independently reproduced by the primary assessor before
any fix, and are NOT attributed on trust:

- **F1 — CONFIRMED, LOW (fixed): over-budget real-model proposals
  vanished from the audit trail.** `RealAgent.execute` truncated a
  batch at `tool_calls[:remaining]` and broke out on the
  `remaining <= 0` fresh-response path without recording the dropped
  calls anywhere (not in `discarded_proposals`, batches, or
  proposals). Reproduced: 10 proposed, 8 dispatched, 2 vanished, while
  the outcome honestly said `budget_exhausted`. Fix: both drop points
  now record every dropped call in `discarded_proposals` with reason
  `budget_exhausted` (tool, provider_call_id, turn, batch_id),
  mirroring the existing cancel/budget discard paths; nothing about
  dispatch changed (dropped calls still never execute). Tests:
  `test_f1_over_budget_batch_proposals_recorded_as_discarded` and
  `test_f1_fresh_response_after_budget_exhausted_recorded_as_discarded`
  (both failing-first). No S7 test broke.
- **F2 — SOURCE-SUPPORTED, LOW (fixed): variant manifest hashed the
  wrong mission string for A5/A6.** `experiment_manifest` hashed
  `SCENARIOS[sid]["legitimate_objective"]`, but `RealAgent._mission`
  uses an override for A5/A6, so those digests described a mission the
  model never receives; the docstring claim "every model-visible
  input" was overstated (the constant starting-context suffix and the
  system message are also unhashed). Fix: the override dict moved to
  `scenarios.py` (`REAL_MISSION_OVERRIDES`, single source of truth
  for both the agent and the manifest) and `mission_hash` now hashes
  the effective mission text; the docstring now states exactly what
  is and is not hashed. A1–A4 have no override, so their digests are
  provably unchanged (guarded by hardcoded no-store digest
  assertions); A5/A6 have no stored weak export, so no comparison
  breaks. Test: `test_f2_manifest_hashes_effective_mission`
  (failing-first).
- **F3 — CONFIRMED, INFORMATIONAL (fixed): non-200 provider responses
  accepted.** `LLMClient.complete` rejected only `>= 400`, so
  301/302/303/307/201 responses carrying a valid choices body were
  accepted as model responses (reproduced with `httpx.MockTransport`
  for each code). Impact was negligible — the provider endpoint is
  operator-configured, redirects are never followed, and strict
  choices validation still applied — but a strict adapter now
  accepts exactly HTTP 200. Test:
  `test_f3_non_200_provider_responses_rejected` (failing-first).
- **F4 — INFORMATIONAL (fixed): stale `useAsync` comment.** The
  comment claimed AbortController was unavailable as a cancellation
  channel; the API client does track per-token AbortControllers and
  `switchPersona()` aborts them. Comment corrected; no behavior
  change. No test (documentation only).

The review also independently corroborated the pentest's own
conclusions: sessionStorage-only token storage, token-scoped 401
handling, the T10-03 download race design, CORS restricted to the two
Vite origins, provider URL env-only with fail-closed loopback checks,
spoof-field stripping, operator-scoped idempotency (scripted launches
always creating a new run is intentional), and the intentional
unauthenticated persona/scenario-list/health/settings endpoints.
Its two remaining untested areas (live real-model behavior, real
browser execution) match this assessment's own NOT RUN list.

## Post-delivery addendum 2 — delegated persistence + API reviews (C/A rounds)

After the F-round repackaging, the two remaining delegated reviews
arrived. Every item below was independently reproduced by the primary
assessor before fixing (the persistence repros ran as one scratch
script on disposable DBs; the API items were confirmed by code read
plus targeted checks: live DB mode 640, zero `DELETE FROM sessions`
in the source, `SENSITIVE_STATUSES` membership). Nothing is attributed
on trust. The API review's C-01 is the already-fixed P-01 (it tested
the pre-fix tree: scenario detail is now session-gated; the list stays
public by the documented F-01 decision) and its C-02 (403-vs-404
existence oracle) is the already-documented intentional distinction
(kept: debuggability for lab verdicts, no content returned) — neither
is a new finding.

- **C1 — CONFIRMED, MEDIUM (fixed): damaged DB missing only `cases`
  was fully reseeded, wiping intact runs/events.** `Store.__init__`
  seeded whenever `cases` was absent, and `seed()` DROPs all 13
  tables. Reproduced: 1 run row became 0 while cases backfilled to 4.
  Fix: seed only a truly empty database (no tables at all); any
  damaged database takes the surgical path (recreate just the missing
  tables, migrate, backfill fixture rows via INSERT OR IGNORE).
  Test: `test_c1_damaged_cases_table_preserves_runs`
  (failing-first). Explicit `seed`/`reset` commands are unchanged
  (they are intentionally destructive).
- **C2 — CONFIRMED, LOW (fixed): prune deleted the newest backup
  when mtimes disagreed with stamps.** `prune_backups` sorted by
  `os.path.getmtime`; reproduced with 6 backups where the
  newest-by-stamp file had the oldest mtime — it was deleted, so a
  reset response would name a backup that no longer exists. Fix:
  sort by filename (stamps are fixed-width UTC, so lexicographic
  order IS newest-last order).
- **C3 — CONFIRMED, LOW (fixed): prune glob over-matched foreign
  backups.** The pattern was built from the DB path without
  `glob.escape`; reproduced with a `a*.db` database plus a foreign
  `aXYZ.db` backup with the oldest mtime — the foreign file was
  deleted. Fix: `glob.escape(db_path)`.
- **C4 — CONFIRMED, LOW (fixed): lock acquisition failed on a fresh
  nested path.** `try_acquire_db_lock` opened the `.applock` without
  creating its parent while `Store` mkdirs parents; reproduced as
  `FileNotFoundError`. Fix: mkdir the lock file's parent first (an
  empty directory left by a later-denied attempt is benign).
- **C5 — CONFIRMED, LOW (documented residual, not fixed): rename
  after acquisition yields a second holder.** Reproduced both ways
  (rename the DB file; rename the lock file) — pathname-derived
  locking cannot survive renames by a directory writer. No safe
  narrow fix exists short of replacing the lock scheme with a
  cross-process inode registry; SQLite's own file locking still
  serializes page writes, and directory-write access is outside the
  lab's single-operator threat model. Documented in
  `canonical_db_path` and here, not hidden.
- **C6 — CONFIRMED, LOW (fixed): symlink swap between lock
  acquisition and Store construction.** Fault-injected via the
  documented `_realpath` seam: the CLI opened a store on the victim's
  file while the victim lock was held. Fix: new
  `verify_store_matches_lock` (constructed store's canonical path
  must equal the lock file's name minus `.applock`), called by both
  the CLI and the API lifespan, which close both objects on mismatch.
  Test: `test_c6_lock_to_construction_symlink_swap_refused`
  (failing-first).
- **S1 — LOW (fixed): backup verification counted only
  runs/events/sessions.** A backup missing fixture-table rows would
  pass. Fix: the counted set now equals all 13 required tables
  (safe: the reset barrier guarantees no concurrent writers).
- **S2 — LOW (fixed): no fsync on backup temp or directory.**
  `os.replace` is atomic for visibility, not durable across power
  loss. Fix: `verified_backup` fsyncs the temp file (failure fails
  the backup); the API and CLI reset handlers fsync the containing
  directory best-effort after rename via new `fsync_dir`.
- **S3 — CONFIRMED, LOW (fixed): source-vanish race left a stray
  empty file.** Reproduced with a connect wrapper that deletes the
  source mid-backup: `BackupError` was raised but an empty file
  remained at the source path. Fix: the source connects via a
  `mode=rw` URI (read-only-without-create), so a vanished source
  fails without creating anything.
- **S4 — LOW (fixed as a side effect of C2): prune getmtime race.**
  A candidate deleted between `glob` and `getmtime` propagated into
  `RESET_BACKUP_FAILED`. Stamp sorting performs no stat call, so the
  race is gone.
- **S5 — CONFIRMED, LOW (fixed): CLI reset had no pre-reset backup.**
  The API reset always backs up first; the CLI called `Store.reset()`
  directly. Fix: the CLI reset now takes a verified backup (0600,
  retention newest 5) before reseeding; a backup failure refuses
  with exit 2 and the DB untouched. Test:
  `test_s5_cli_reset_takes_pre_reset_backup` (failing-first).
- **S6 — LOW/INFO (fixed): `.gitignore` gap for backup temps.**
  `*.pre-reset-*.bak` does not match `*.bak.tmp` outside
  `backend/data`. Fix: added a `*.bak.tmp` pattern. Test:
  `test_s6_gitignore_covers_backup_temps` (failing-first, via
  `git check-ignore`).
- **A-C03 — CONFIRMED, LOW (fixed): no session revocation.** Old
  tokens survived persona switches and new logins until 12h expiry
  or a commander reset (confirmed: no invalidation in
  `create_session`). Fix: new `POST /api/v1/lab/session/revoke`
  deletes the caller's own session row (unknown tokens 401); the
  frontend revokes the previous token best-effort on persona switch
  (raw fetch, never blocking the switch). Test:
  `test_a03_session_revoke` (failing-first).
- **A-C04 — CONFIRMED, LOW (fixed): live DB file mode was
  umask-dependent.** Reproduced: 640 under this shell's umask while
  holding plaintext session tokens (backups are forced 0600).
  Fix: `Store` forces the DB file to 0600 on open (POSIX,
  best-effort; a chmod failure leaves the umask mode, never breaks
  the open). Token hashing was deliberately NOT done (larger change;
  a local DB read already implies token use). Test:
  `test_a04_live_db_file_is_private` (failing-first, umask pinned).
- **A-C05 — SOURCE-SUPPORTED, INFO (fixed): expired sessions never
  cleaned up.** Confirmed: zero `DELETE FROM sessions` in the source.
  Fix: session creation purges expired rows (live rows untouched).
  No rate limit was added (local-only lab, tiny rows — documented
  as accepted). Test:
  `test_a05_session_creation_purges_expired_rows` (failing-first).
- **A-C06 — INFO (fixed): policy-matrix wording.** The matrix
  headlined `change_case_status` as `requires_approval: True` while
  approval is required only for sensitive statuses. Fix: the entry
  now states explicitly that non-sensitive transitions need no
  approval. Test: `test_a06_policy_matrix_states_nonsensitive_needs_no_approval`
  (failing-first).

Totals across all rounds (distinct items): **1 MEDIUM + 17 LOW fixed,
4 informational + 1 LOW/INFO fixed, 1 LOW documented residual (C5),
1 intentional design confirmed (C-02)**; still no critical or high
defect. The persistence review's non-issues corroborate the design:
scripted launch racing a reset produces zero orphan writes (30
rounds, 0 orphan events/drafts/active rows), hard-link-after-
acquisition and parent-rename second-holder attempts are refused,
no SQL injection in the persistence layer, the QA-13-01 tolerance is
sound, and no connection leaks were observed. The API review's
non-issues likewise corroborate: all cross-tenant reads 403, spoof
fields denied, weak-mode escape impossible via API, reset
authorization enforced, report filenames unreachable before the
tenant check, and no error body containing a path, token, or
traceback.
