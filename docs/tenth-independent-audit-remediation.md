# Tenth independent audit remediation (T10-01..T10-04)

> Superseded by the eleventh-audit remediation — see
> `docs/eleventh-independent-audit-remediation.md`. This document
> is preserved unchanged as the tenth release's record.

Auditor: independent review of the ninth-audit archive
(`AgentBoundary_Operation_SilentSignal_Ninth_Audit_Verified_Source.zip`,
SHA-256
`8ad77ff987cf8448f0946f238ad55adb00f62e40f3b4b4393cb15a07b699f2cc`).
The auditor reproduced 272 backend tests passing + 2 skips on Python
3.13.5 (Muse reports 274 on its development host; the 2-test gap is
the documented isolation skips, not a behavior difference). Frontend
and live Ollama were NOT independently rerun by the auditor. No new
tool-side tenant-authorization bypass was demonstrated.

All four findings are FIXED below. Nothing was weakened: no test was
deleted, xfailed, or replaced by a trivial assertion. Where a test
file was touched, it was only to add coverage.

## T10-01 (HIGH) — Store initialization could mutate a live database before the lock

**Repro (auditor's, confirmed in code):** `create_app()` built a
`Store(path)` before the lifespan acquired `<db>.applock`. Store
construction seeds, repairs, and migrates — so a second app, denied
at lifespan, had already refilled a deleted runbook fixture row
(6 -> 5 -> 6) in the first app's live database.

**Fix — ownership by construction order, not by convention:**

- `create_app(store=None, path=None)` now distinguishes two
  contracts, documented on the function:
  - *Caller-owned* (`store=` given, the form all tests use): the
    caller already constructed — and therefore seeded/repaired — the
    store. The app performs no construction-time mutation; lifespan
    still takes the lock and refuses to run (closing the caller's
    store, N9-02) if denied.
  - *App-owned* (`store` omitted, the production path): the Store is
    NOT constructed in `create_app` at all. Lifespan acquires the
    exclusive flock FIRST, then constructs the Store (seed/repair/
    migration under the lock), then runs startup recovery. A denied
    second instance touches nothing: no file is created, no row is
    refilled, no schema is repaired. A construction failure after
    lock acquisition releases the lock instead of leaking it.
- A guard middleware answers 503 `APP_NOT_STARTED` (never a 500
  `AttributeError`) if a request arrives before lifespan built the
  store — e.g. serving with lifespan disabled.
- CLI commands that mutate the main DB (`seed`, `reset`, `run`,
  `run-all`, `run-real`) now take the cross-process lock on the PATH
  before constructing any Store (`_acquire_main_store`), returning
  exit code 2 on refusal. `run-weak` is unaffected: it owns a fresh
  throwaway DB. The E8 in-process contract (`cli_main(["reset"]) ==
  2` while a server holds the DB) is preserved — `main()` returns
  ints; only the `__main__` entry point turns them into exit codes.
- A denied app object is now reusable: pre-fix, its store was closed
  by the failed lifespan and then reused closed on a later entry
  (health broke, teardown leaked). Post-fix, the successful entry
  constructs a fresh store.

**Regression tests** (`backend/tests/security/test_tenth_audit.py`):

- `test_t1001_denied_second_app_does_not_mutate_db` — the auditor's
  exact repro (delete a row 6 -> 5, construct B, deny B, verify
  count/checksum/runs unchanged and A still healthy), then the same
  B object starts after A exits and legitimately repairs (5 -> 6,
  no duplicate ids, no evidence loss).
- `test_t1001_two_first_time_starts_only_one_succeeds` — two
  first-time starts against an empty DB: one succeeds with a
  complete 48-record seed, the other is denied without changing a
  byte, and it starts cleanly afterwards with no duplicate seeding.
- `test_t1001_two_real_processes_lock` — two REAL uvicorn processes
  (not threads): B exits nonzero without touching the DB while A
  runs; A stays healthy; after A stops, B starts and repairs.
- `test_t1001_cli_refuses_before_constructing_store` — CLI
  `reset`/`seed` against a server-held DB return 2 with the deleted
  row still deleted and the checksum unchanged; after the server
  stops, CLI `seed` repairs.
- `test_t1001_app_without_lifespan_returns_503` — a bare client
  (no lifespan) gets 503 `APP_NOT_STARTED`, and construction alone
  creates no file.

**Failing-first proof:** with only the source files reverted
(`api/app.py`, `cli.py`, `store.py`, `.gitignore`), the new backend
suite failed 11 of 12 (the one pass is the T10-04 content lock,
whose raw-copy backup was already correct for a quiescent DB); with
the fix, 12/12 pass. The two-process test failed pre-fix precisely
because B's import-time Store construction refilled the deleted row
before its lifespan denial.

**Non-POSIX limitation (honest):** the exclusive lock is a POSIX
`flock` on `<db>.applock`. On non-POSIX hosts the lock file is
still created but exclusivity is not enforced by the OS; the
construction-order fix still holds (a denied lifespan still builds
nothing), but two processes could both pass admission. This is the
same limitation the E8 lock always had, now documented here rather
than implied.

## T10-02 (MEDIUM) — Reset backups were not Git-ignored and held session tokens

**Repro (auditor's, confirmed):** privileged reset wrote
`<db>.pre-reset-<timestamp>.bak` into `backend/data/`, which
`.gitignore` did not cover (it covered `*.db` only). A scratch
`git status` listed the backup as untracked; opening it showed a
prior run and a live lab-session token. Repeated resets created
unbounded backups.

**Fix:**

- `.gitignore` gains narrowly scoped patterns — no overbroad
  wildcards that could hide genuine fixtures/docs:
  `backend/data/*.bak`, `*.pre-reset-*.bak`,
  `backend/data/*.db-wal`, `backend/data/*.db-shm`,
  `backend/data/*.db-journal`, `backend/data/*.tmp`.
- Backups are written with private permissions (`os.chmod 0o600`
  where supported; failure to chmod does not fail the reset, since
  the file is still the operator's own lab state).
- Retention policy (`store.prune_backups`, keep newest 5): after a
  successful backup, older `<db>.pre-reset-*.bak` files beyond the
  newest 5 are deleted. Pruning never runs when there are 5 or
  fewer, so a lab with a single backup keeps it — the last
  recoverable backup is never silently deleted. The reset response
  now reports `pruned_backups` (additive field) alongside `backup`.
- The reset response still returns only the backup BASENAME, never
  an absolute path (pre-existing behavior, kept).
- Packaging: the release ZIP is built from `git archive` (tracked
  files only) plus the screenshots directory, so untracked `.bak`
  files cannot enter it; the release checklist verifies
  `unzip -l` shows no `.bak`/`.db` entries.

**Regression tests:**

- `test_t1002_gitignore_covers_backups` — asserts the patterns are
  present in `.gitignore`, and when run inside a git checkout,
  asserts `git check-ignore` actually matches each artifact path.
- `test_t1002_scratch_repo_ignores_backup` — self-contained: a
  fresh `git init` repo using this `.gitignore` shows the backup
  ignored while a genuine doc file is listed (skipped only when no
  git binary exists to run the check).
- `test_t1002_reset_backup_permissions_retention_restore` — 7 stale
  backups + a reset leaves exactly 5 (newest), `pruned_backups ==
  3`, the new backup is 0600 on POSIX, its name is basename-only,
  no `.tmp` remains, and copying the backup back to a `.db` file
  restores the pre-reset run and session token.

## T10-03 (MEDIUM, source-supported race) — Report download could outlive a persona switch

**Repro (auditor's, source-level; NOT browser-reproduced by the
auditor):** `downloadReport()` untracked its AbortController on
response headers, before `await res.blob()` and before clicking the
download link. A persona switch in that window could no longer
abort the download, so the previous tenant's report could finish
under the new persona.

**Fix (`frontend/src/lib/api.ts`):**

- The controller stays tracked until the body is fully consumed;
  cleanup lives in a `finally`, never before `blob()`.
- `blob()` rejections from an abort are converted to
  `ApiError(0, 'ABORTED', ...)` (previously only the fetch-stage
  abort was converted; a blob-stage abort would have surfaced as a
  raw DOMException).
- Immediately before triggering the browser download, the stored
  token is rechecked against the token the download started with.
  On mismatch the stale blob is discarded: no file, no success
  result, no previous-tenant artifact in the new persona's view.
- Object URLs are revoked via a short `setTimeout` deferral instead
  of immediately after `click()`, so the browser has captured the
  file first (immediate revocation can cancel the download in some
  browsers). On the discard path no URL is ever created.
- The late-401 path is unchanged: the token-scoped handler still
  receives the download's own token (R-12), so a late 401 cannot
  clear the new session.

**Regression tests:**

- Vitest (`frontend/tests/tenth-audit.test.ts`): (a) switch during
  a gated body discards (recheck path — no `createObjectURL` call);
  (b) abort during a gated body rejects ABORTED (tracking path);
  (c) control without a switch succeeds and clicks the anchor;
  (d) late 401 still reports through the token-scoped handler.
  Failing-first: with only `api.ts` reverted, (a) and (b) fail
  (the old report downloads) while (c)/(d) pass.
- Playwright (`frontend/e2e/report-download.spec.ts`, real
  browser): a fetch-level gate holds the Northstar report body
  after headers; the test switches to Cedar in that window,
  releases the old body, and asserts NO download event fires, no
  "Downloaded" toast appears, and Cedar stays selected; then it
  switches back Northstar -> Cedar -> Northstar and the same run's
  report downloads normally. Failing-first: with only `api.ts`
  reverted, the old report DID download after the switch
  (observed `"downloaded"`); with the fix, none.

## T10-04 (MEDIUM robustness; NOT a confirmed corruption incident) — Reset used a raw file copy of an open DB

**Repro status (auditor's words):** source-supported concern, NOT
independently reproduced as corrupt backup bytes. The old code
copied the open database with `shutil.copy2`. The real-model reset
barrier blocked jobs but not other writers — session creation
writes to the same DB — so a raw copy was not a proven consistent
online snapshot (especially under alternate journal modes).

**Fix:**

- `store.verified_backup(src_path, tmp_path)` uses the supported
  `sqlite3 Connection.backup` API (a real online backup, correct
  under WAL as well as rollback-journal modes). It verifies before
  returning: `PRAGMA integrity_check == 'ok'`, all 13 schema tables
  present, and runs/events/sessions row counts identical to the
  source at snapshot time. A missing source is refused without
  creating an empty file. Any failure raises `BackupError`.
- The reset endpoint writes to `<db>.pre-reset-<stamp>.bak.tmp`,
  verifies, then atomically renames (`os.replace`) into place;
  any failure removes the tmp file and refuses the reset with 500
  `RESET_BACKUP_FAILED` — no partial reset, old DB untouched.
- The backup runs off the event loop (`asyncio.to_thread`), so a
  large database backup cannot stall all other API traffic while
  the reset barrier is held.
- Barrier semantics, now defined and tested: DURING a reset,
  session creation and launches of either adapter fail fast with a
  retryable 409 `RESET_IN_PROGRESS` (the client retries after the
  reset). They serialize neither behind the backup nor into it —
  so the snapshot sees zero concurrent writers by construction,
  and the verification counts are stable. The barrier is released
  in the reset's `finally`, so a 409 can never deadlock. Legacy
  raw-copy backups (if any exist from earlier releases) remain
  ordinary SQLite files and can still be restored by copying them
  back to a `.db` path; they are simply no longer produced.
- `shutil.copy2` no longer appears in the reset path (the import
  was removed).

**Regression tests:**

- `test_t1004_reset_backup_is_verified_sqlite_backup` — A1+A2+A3
  runs, then reset: the backup passes an independent read-only
  integrity/schema/count check and restores as a working lab DB
  with all 3 runs.
- `test_t1004_session_and_launch_blocked_during_reset` — a real
  uvicorn server thread with a blocked backup: session creation
  and scripted launch both get 409 `RESET_IN_PROGRESS` mid-reset,
  then succeed after it.
- `test_t1004_backup_failure_refuses_reset_old_db_usable` — a
  backup that raises refuses with 500, creates no `.bak`/`.tmp`,
  and the old DB keeps serving (a further launch succeeds).
- `test_t1004_interrupted_backup_cleans_tmp_old_db_usable` — a
  backup that writes a partial tmp file then fails still cleans
  the tmp file and leaves the old DB untouched.

## Final gates (all actually run)

- Backend: **286 pytest passed** (274 + 12 new), ruff check +
  format clean, full-source coverage **91% (2417 stmts, 208
  missed)**, strict ResourceWarning run 286 passed, pip-audit clean.
  One transient note, recorded not hidden: an earlier coverage run
  on the pre-format tree showed 1 failed / 285 passed, but the
  failing test name was not captured in the tail output, and the
  failure did NOT recur in three subsequent full runs on the final
  tree (coverage, plain, ResourceWarning — all 286 passed). It is
  treated as a transient timing flake under coverage slowdown; if it
  recurs it must be investigated, not ignored.
- Frontend: tsc 0 errors, **40 Vitest passed** (36 + 4 new),
  build passes, **Playwright 33/33** (incl. the new report-download
  race spec and the a11y/axe specs), axe 0 critical/serious on all
  10 pages.
- Live scripted sweep (disposable backend, fresh temp DB): A1–A6
  all PASS, 0 forbidden, 0 out-of-mission, INC-2048 investigating,
  comparisons comparable with A2 + A4 pairs, security matrix
  matches, weak A2/A4 FAIL with matching variants, sentinel absent
  from weak exports.
- Screenshots: 15 recaptured; all widths equal their viewport
  labels; Overview 320 + Scenarios 390 inspected, clean.
- Clean-clone test: GREEN from the release commit (fresh `git
  archive` extract): backend 284 passed + 2 documented isolation
  skips, ruff clean, npm ci OK, tsc 0, Vitest 40, build passes,
  Playwright 33/33, clone scripted A1 PASS (`v3-0d3251e9314abf7e`,
  0 out-of-mission actions). The commit was amended only to record
  this line; no code, test, or fixture changed after the clone run,
  so the clone result stands for the final tree.

## Still NOT RUN (honest list)

- Completed live PASS trial on a real local model, and any live
  local-model trial at all in this release: Ollama is NOT installed
  in this VM (replaced since the fifth audit; only the workspace
  persists), so no local trial could be attempted. The fifth-audit
  partial trials stand as the last live-model evidence.
- Python 3.13 warning re-run (no 3.13 interpreter here, only 3.12.3).
- Firefox/WebKit, screen-reader audit, npm audit (registry policy
  block), GitHub Actions CI, Docker, PDF export.
- No claim of zero possible defects is made.
