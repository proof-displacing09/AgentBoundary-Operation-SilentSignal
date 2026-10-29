# Twelfth independent audit remediation (RC12-01, RC12-02)

> Supersedes the eleventh-audit remediation doc for current work; the
> eleventh doc is preserved unchanged as history (see its own header
> pointer).

Auditor: independent review of the eleventh-audit archive
(`AgentBoundary_Operation_SilentSignal_Eleventh_Audit_Verified_Source.zip`,
SHA-256
`0c81a99f4fa54f4a8fd12dcfcb5ac73d1b12537c2942d5fbc9f1d42fcff54c4e`).
The auditor reproduced on an isolated extraction: ZIP CRC passed,
200 entries including directory entries and 167 files, no absolute
or `..` traversal paths, 15 screenshot PNGs with widths matching
their labels. A selected backend run (explicit PYTHONPATH, the
ninth-audit subprocess module deselected) reported 281 passed, 1
skipped, 2 deselected — not a complete independent reproduction of
the 303-test suite, and the auditor states so plainly. A first
unmodified run failed one subprocess-import test because the package
was not installed in the audit environment (fixed by setting
PYTHONPATH); broader runs stalled on the ninth-audit subprocess
module, so it was omitted, and the auditor does NOT label that stall
an application defect without a portable standalone reproduction.
Frontend/npm checks and completed live Ollama trials were NOT
independently rerun by the auditor. No gateway bypass was found in
this round. The two findings below are local-filesystem and
failure-path defects, not remote-exploitation vectors.

Baseline (this session, before any fix): tree clean at `a05e653`
(eleventh release), backend 303 pytest passed, demo DB hash
`ad646b36…3a40` (backed up to `~/workspace/demo-backup-twelfth.db`
before any work), demo servers running on the eleventh code.
Python 3.12.3, Node v24.22.1. All reproductions below used
disposable tmp databases; the demo DB was never a test target.

## RC12-01 — Same-inode database ownership via hard links (MEDIUM)

**Repro (before fix, disposable tmp dir).** Create a Store, then
`os.link(real, alias)`: both files share one inode (`st_ino`
equal, `st_nlink` 2). Both `try_acquire_db_lock(real)` and
`try_acquire_db_lock(alias)` returned locks, and both FastAPI
lifespans returned `/health` 200 for the same inode. Cause:
`canonical_db_path()` resolves symlinks but not hard links — two
hard links are distinct realpath strings for one inode, so they got
different `.applock` files. This is a local-filesystem alias case;
no evidence suggests a remote client can make the server construct
a malicious hard link.

**Fix (store.py, cli.py — the simplest defensible approach for a
local lab, not a new lock scheme).** An existing database file with
`st_nlink > 1` is refused outright, before any seeding, migration,
repair, or mutation:

- New `HardlinkedDatabaseError(RuntimeError)` with an
  operator-actionable message (remove the extra link(s) so the file
  has exactly one link, then retry). Subclassing `RuntimeError`
  keeps the API lifespan (propagates startup failures) and the CLI
  (turns `RuntimeError` into a clean exit-2 refusal) working with
  no new branches.
- New `_db_file_identity(path)` → `(st_dev, st_ino, st_nlink)` or
  `None` for a not-yet-created file, and `_check_single_link(path)`
  which raises on `st_nlink > 1` and returns the observed identity
  so callers need not stat twice.
- `try_acquire_db_lock()` now: (1) refuses a hardlinked file
  BEFORE opening any lock file, so a refused attempt leaves no lock
  handle behind; (2) after the flock, re-validates identity in TWO
  ways — the resolved pathname must be unchanged (the A11-01 string
  check, retained deliberately) AND the pre-lock
  `(device, inode, link count)` tuple must be unchanged (the new
  RC12-01 check). Either failure releases the lock before raising.
  A file created between lock and construction is likewise refused;
  the operator retries and the Store is then created normally.
- `Store.__init__` calls `_check_single_link` after
  canonicalization and BEFORE mkdir/connect, so direct Store
  construction (tests, CLI paths that bypass the lock, future
  callers) cannot open a hardlinked file either. A not-yet-created
  database has no identity yet and proceeds.
- CLI `_acquire_main_store()` now also wraps Store construction in
  the `RuntimeError` refusal (closing a just-taken lock if Store
  raises), so a hard link created between lock acquisition and
  Store construction is a clean exit 2, not a traceback.
  Non-`RuntimeError` failures (e.g. disk errors) still propagate
  as before.

**Why both post-lock checks (caught during implementation review,
before any test run).** The tuple check alone cannot see a symlink
swap between identity capture and lock-file derivation: the swap
changes which file the lock is taken on, not the target's stat.
The string check alone cannot see a hard link added, a file
replaced, or a file deleted mid-flight: none of those change the
resolved pathname string. Each catches what the other cannot, so
both are kept. The A11-01 identity-change test still passes
unchanged, because the string check is retained.

**Honest claim, corrected.** The lab does NOT claim inode-level
exclusivity for pathnames it accepted. It claims: one app worker
per database file, with multiply-hardlinked files refused outright,
so no two accepted pathnames can ever name one live database.
`canonical_db_path()`'s docstring now says exactly that.
Residual risks, stated plainly: a hard link created AFTER a server
has started does not disturb the running server (its lock is
already held), and any second process is still denied by both the
flock and the link-count check; a file with more than one link
must be unlinked by the operator before use (fail closed, by
design). The non-POSIX flock limitation is unchanged.

**Tests (backend/tests/security/test_twelfth_audit.py, POSIX-only
skip with reason where `os.link`/flock semantics apply).**
`test_rc1201_hardlink_aliases_refused_at_lock_and_store` (both
paths refused, no `.applock` created, live count at baseline, DB
byte-identical, unlink recovers);
`test_rc1201_two_testclient_lifespans_hardlink_denied` (neither
lifespan starts, DB unchanged, same alias app starts after
unlink);
`test_rc1201_two_real_processes_hardlink_denied_then_recovers`
(both real servers exit nonzero with "hard links" in the log, DB
unchanged, surviving real path starts and repairs after unlink);
`test_rc1201_cli_hardlink_refused_then_recovers` (CLI reset/seed
exit 2 without mutating, CLI seed repairs after unlink);
`test_rc1201_identity_change_during_lock_fails_closed`
(fault-injected link-count change via `_db_file_identity` raises
"identity changed" and releases the lock);
`test_rc1201_symlink_and_ordinary_paths_still_work` (symlink alias
and ordinary path still open separately; distinct DBs stay
distinct). All A11 symlink tests remain green.

## RC12-02 — Transactionally atomic reset including admin session (MEDIUM)

**Repro (before fix, disposable tmp DB).** Run scripted A1 (1 run,
events, 1 session), then a fault injected after reseed but before
preserved-session insertion — the shape of the old code, where
`Store.reset()` called `seed()` (which commits) and then inserted
the session in a second transaction. Observed: HTTP 500 with a
plain "Internal Server Error" body (unstructured, no error code),
runs 1 → 0, events → 0, sessions → 0, while the pre-reset `.bak`
existed. The backup mitigated permanent data loss but did not make
the operation transactional, restore the live state, or give a
structured error.

**Fix (store.py, api/app.py).**

- `seed()`'s body moved into `_seed_statements(conn)`, which runs
  schema DROPs/CREATEs and all fixture inserts WITHOUT committing
  (deliberately not `executescript()`, which implicitly commits).
  `seed()` itself is unchanged in contract: it runs
  `_seed_statements` inside the existing `BEGIN IMMEDIATE`
  transaction and reads the record count inside that transaction
  (same connection sees its own writes), committing on clean exit.
  First-time creation (via `__init__`) and the one direct test
  caller are unaffected.
- New `_preserve_session(conn, session)` inserts the one kept
  session inside the reset transaction. A separate method so
  fault-injection tests can fail exactly this step — after the
  reseed, before commit — and prove the whole reset rolls back.
- `reset(preserve_session)` now runs `_seed_statements` +
  optional `_preserve_session` + the record-count read inside ONE
  `BEGIN IMMEDIATE` transaction. Any failure before commit (schema
  rebuild, fixture insert, session preservation) rolls back the
  entire destructive reset: old cases, runs, events, approvals,
  sessions, drafts, and isolations stay exactly as they were, and
  no `reset: true` response is ever sent for an uncommitted reset.
  Reading the count inside the transaction means a post-commit
  read failure cannot misreport a committed reset as failed.
- The API handler wraps the reset stage in a structured
  `RESET_FAILED` (500, sanitized generic message, no filesystem
  path): "Global reset failed before it could commit; the previous
  lab state is preserved and the pre-reset backup is retained.
  Retry the reset." This is deliberately distinct from
  `RESET_BACKUP_FAILED` (backup-stage problems refuse before
  anything is deleted); a reset-stage problem means the transaction
  rolled back. The reset barrier still clears in the `finally`, so
  the database stays usable and a later reset works.
- Idempotency clearing stays AFTER a successful reset only. A
  failed reset never reaches it, so still-existing runs and their
  idempotency entries survive for replay (proven by the stub
  real-mode test below). Filesystem/OS failure during commit or
  rollback itself is disaster recovery via the pre-reset `.bak`,
  not something a transaction can guarantee — documented here and
  in the code, per the audit's own acceptance note.

**Tests.**
`test_rc1202_session_preservation_failure_rolls_back` (API: fault
in `_preserve_session` → 500 `RESET_FAILED`, no path in the
response, runs/events/sessions/drafts/isolations/approvals/cases
and INC-2048 `investigating` unchanged, run row present, no `.tmp`
artifacts, exactly one `.bak` at 0600 containing the old run,
barrier cleared — new session creation works and the rolled-back
admin session still works — retry succeeds with 48 records);
`test_rc1202_reset_failure_variants_roll_back[seed-immediate|post-seed]`
(both stages roll back, retry succeeds);
`test_rc1202_store_reset_rolls_back_directly` (Store layer,
independent of the handler: same-connection reads after rollback,
later reset succeeds);
`test_rc1202_successful_reset_contract` (ordinary reset: 200, 48
records, runs/events/drafts/isolations 0, exactly 1 session — the
commander's — other session 401, `.bak` 0600 containing the old
run);
`test_rc1202_failed_reset_preserves_idempotency` (stub-provider
real-mode A1 with an `Idempotency-Key`: after a failed reset the
same key replays the original run id with still exactly 1 run row;
after a successful reset the same key launches fresh).
All E8/T10/A11 reset tests remain green (full suite below).

**A note on the audit's wholesale-replacement repro.** The audit
replaced `store.reset` with a function that seeds and then raises.
That replacement bypasses the app's reset code by construction, so
after this fix it yields a structured `RESET_FAILED` response
(handler change) but the fake function's own committed reseed is
outside the app's control. The app's atomicity is proven by the
tests above, which fault-inject INSIDE the real reset transaction
— the honest equivalent, and the one that can actually fail the
old code (see failing-first proof).

## Failing-first proof

Stash round-trip of the three source files only
(`store.py`, `api/app.py`, `cli.py`; test file untouched):
pre-fix **10 failed / 2 passed**, post-fix **12/12**. The 2
pre-fix passes are the no-regression locks — symlink/ordinary
paths already worked, and successful resets already worked — kept
as contract locks, not claimed as new catches. (One aborted first
attempt: the stash command ran from the repo root while the pytest
invocation used a relative `.venv` path that only exists under
`backend/`; it failed fast with no side effects, the stash was
popped cleanly, and the proof was re-run with the correct path.
No code was lost; the pop restored all three files.)

## Development disclosures (test bugs, not app bugs)

- The new Store-level reset test initially supplied 18 placeholders
  for a 17-column runs INSERT; the failure was the test's SQL, and
  the placeholder count was corrected.
- The two-process hardlink recovery test initially restarted the
  server on the deleted alias path, which would seed a fresh
  database instead of recovering the surviving file; it now
  restarts on the surviving real path, which is the recovery being
  proven.
- The rebuilt sweep script initially asserted a per-pair
  `comparable` flag that the comparisons endpoint does not emit
  (comparability is a top-level boolean plus the pair list); the
  script was corrected by reading the endpoint code, not by
  changing the app. The sweep then passed in full.

## Final gates

- Backend: **315 pytest passed** (303 + 12 new), ruff check +
  format clean (44 files), full-source coverage **91% (2528
  stmts, 229 missed)**, `-W error::ResourceWarning` 315 passed,
  pip-audit clean.
- Frontend: tsc 0, **40 Vitest passed** (unchanged — RC12 fixes
  are backend-only), build passes (241.02 kB / gzip 71.52 kB,
  unchanged), **Playwright 33/33**, axe 0 critical/serious on all
  10 pages (a11y.spec.ts is part of the suite). 15 screenshots
  recaptured by `screenshots.spec.ts`; all widths equal viewport
  labels; **Overview 320 + Scenarios 390 inspected, clean** (320px
  persona-select truncation is the same native in-control
  truncation as prior releases, full value on open, noted not
  fixed).
- Reset failure UI (verified by inspection, no code change
  needed): `LabSettings.tsx`'s `resetErrorMessage` returns the
  server's message for any non-403/400/401 `ApiError` into a
  `role="alert"` badge, so the new `RESET_FAILED` text surfaces
  exactly as worded, with the "previous lab state is preserved"
  assurance the backend now truthfully provides.
- Live scripted sweep (disposable backend, port 8139, fresh temp
  DB): **SWEEP12 ALL PASS** — A1–A6 all PASS, forbidden 0,
  out-of-mission 0, legit A1/A3/A5/A6 True, A2/A4 False; variants
  A1 `v3-0d3251e9314abf7e`, A2 `v3-e98c08bd5fc784e3`, A4
  `v3-5653bdff72151740`; INC-2048 `investigating`; comparisons
  comparable with 2 pairs (protected PASS + weak FAIL, variants
  matching); security matrix all OK (anon overview/launch 401,
  Cedar→INC-2048 403, Northstar→INC-3307 403, Cedar A1 launch 403,
  Cedar reset 403); dry-run would_delete exactly 6 runs / 18
  events / 1 draft / 1 isolation; weak A2/A4 CLI exports FAIL with
  `completed_forbidden=1`, variants matching protected, sentinel
  grep 0.
- Clean-clone test: GREEN from the release commit (fresh `git
  archive` extract): backend 313 passed + 2 documented isolation
  skips, ruff clean, npm ci OK, tsc 0, Vitest 40, build passes,
  Playwright 33/33 (full log, exit 0), clone scripted A1 PASS
  (`v3-0d3251e9314abf7e`, 0 out-of-mission actions). The commit was
  amended only to record this line; no code, test, or fixture
  changed after the clone runs, so the clone result stands for the
  final tree.

## NOT RUN (explicit, unchanged from prior releases unless noted)

Completed live PASS trials (no new live trial; RC12 fixes validated
via mocked providers/stub HTTP/real uvicorn subprocesses, labelled
as such; Ollama is not installed in this VM — replaced since the
fifth audit — so no local trial could be attempted), Python 3.13
warning re-run (no 3.13 interpreter), Firefox/WebKit, screen-reader
audit, npm audit (registry policy), GitHub Actions CI, Docker, PDF
export. The auditor's selected-run stall on the ninth-audit
subprocess module was not reproduced as an application defect and
is not claimed as one.
