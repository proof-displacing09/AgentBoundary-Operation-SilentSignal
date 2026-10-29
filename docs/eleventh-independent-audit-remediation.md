> Superseded by the twelfth-audit remediation (docs/twelfth-independent-audit-remediation.md); this document is preserved unchanged as history.

# Eleventh independent audit remediation (A11-01..A11-04)

Auditor: independent review of the tenth-audit archive
(`AgentBoundary_Operation_SilentSignal_Tenth_Audit_Verified_Source.zip`,
SHA-256
`d7b3e63d2ea1477e27d11ac8ccd3348cf2ff9443e47eee24e6cc3777628685ed`).
The auditor reproduced 284 backend tests passing + 2
environment-dependent skips on Python 3.13.5 (Muse reports 286 on
its development host; the 2-test gap is the documented isolation
skips, not a behavior difference). Frontend/npm checks and completed
live Ollama tests were NOT independently rerun by the auditor. The
tenth-audit lock-before-initialization, reset backup, and report
download cancellation code is present and was not undone. No new
tool-side tenant-authorization bypass was demonstrated.

All four findings are FIXED below. Nothing was weakened: no test was
deleted, xfailed, or replaced by a trivial assertion, no scoring
definition changed, and no warning was suppressed.

## A11-01 (HIGH) — Symlink aliases bypassed the single-database lock

**Repro (auditor's, confirmed in code):** the lock file was derived
from the *unnormalized* database path string (`<db>.applock`), so
`actual.db` and `friendly.db` (a symlink to `actual.db`) got
*different* lock files. Two FastAPI lifespans on the same SQLite
inode both returned `/health` 200 simultaneously, breaking the
explicit exactly-one-process-per-file contract. The T10-01 fix held
only for identical path strings, not for alternate pathnames naming
the same file.

**Fix — canonical identity before anything is opened:**

- `store.canonical_db_path()` resolves a database path to its
  canonical identity before any lock file is opened or Store is
  constructed: symlinks (file and parent-directory) resolved,
  absolutized. `friendly.db` and `actual.db` are now the SAME
  identity — same lock, same Store, same backup location — in every
  owner-acquisition path: API lifespan, CLI, and `Store` itself
  (which canonicalizes its own path on construction;
  `:memory:` passes through unchanged, and distinct databases that
  merely share a filename in different directories stay distinct).
- `db_lock_path()` derives the sidecar from the canonical path.
- `try_acquire_db_lock()` re-resolves the path after a successful
  flock and must still see the same canonical identity; if it
  changed mid-flight (a symlink swap during acquisition) the lock
  is released and `RuntimeError` is raised — fail closed, never
  holding a lock on one inode while opening another. The CLI turns
  that refusal into the same clean exit 2 as a held lock.
- The T10-01 guarantees are preserved, not relaxed: lock before
  construction, lock held for the process lifetime, N9-02 recovery,
  POSIX flock semantics, and the documented non-POSIX limitation.

**Regression tests** (`backend/tests/security/test_eleventh_audit.py`):

- `test_a1101_two_testclient_lifespans_alias_denied` — the
  auditor's exact repro (real path + symlink alias, both lifespans):
  B is denied, runbook count and DB checksum are unchanged, A stays
  healthy, and the same alias app object starts cleanly after A
  exits.
- `test_a1101_two_real_processes_alias_denied_then_alias_succeeds`
  — two REAL uvicorn processes: B on the alias exits nonzero
  (log shows "already holds") without touching the DB while A
  runs; after A stops, B on the alias starts and repairs the
  deleted fixture row.
- `test_a1101_cli_alias_refused_while_server_holds_real` — CLI
  `reset`/`seed` via the alias against a server-held real path
  return 2 with the deleted row still deleted and the checksum
  unchanged; after the server stops, CLI `seed` via the alias
  repairs.
- `test_a1101_canonical_identity_unit` — alias == target, a new
  file under a symlinked directory resolves through the parent,
  `:memory:` passes through, distinct directories stay distinct.
- `test_a1101_identity_change_during_lock_fails_closed` —
  fault-injected alias swap between resolution and lock (via the
  `_realpath` indirection, since a real swap cannot be timed
  deterministically): acquisition raises, the lock is released, and
  a subsequent acquisition succeeds.

**Failing-first proof:** with only the source files reverted
(`api/app.py`, `cli.py`, `store.py`), all five alias tests failed
pre-fix — TestClient alias denial, two-process alias denial (B kept
running through the full 30-second poll, the bug itself),
CLI-alias refusal, canonical-identity unit, and identity-change
guard — and all pass with the fix.

**Residual risk (honest):** an attacker with write access to the
database directory could swap a symlink in the microscopic window
between canonical resolution and the Store's open. The post-lock
revalidation closes the lock-acquisition half of that window;
directory-write access by an attacker is outside this local
single-operator lab's threat model, and the limitation is stated
here rather than hidden.

## A11-02 (MEDIUM SECURITY) — Temporary backup was world-readable

**Repro (auditor's, via the real reset API under umask 022):**
`<db>.pre-reset-*.bak.tmp` had mode 0644 — SQLite creates files
with the process umask — while the final `.bak` became 0600 only
after verification and rename. During a potentially long
backup/verification, another local user with filesystem access
could read the temp backup, which contains the live sessions table
and investigation metadata.

**Fix — private from creation, verified at every stage:**

- `verified_backup()` creates the temp file with
  `os.open(O_CREAT|O_EXCL|O_WRONLY, 0600)` *before* SQLite opens
  it. Opening an existing file preserves its mode, so the temp is
  private from its first byte under any umask (0600 has no
  group/other bits for a umask to strip; a pathological umask that
  strips owner bits fails the backup rather than proceeding with a
  broken file). A stale temp from a killed run is removed first
  (callers only ever pass `<db>.pre-reset-*.bak.tmp`).
- The mode is validated (`_assert_private`, POSIX only) immediately
  after creation and again after backup + verification, and the
  reset endpoint re-validates the final file's mode after the
  atomic rename — a final file that cannot be made private is
  removed (the original DB is untouched, so the snapshot is
  expendable) instead of being left world-readable.
- The destination's rollback journal is kept in memory
  (`PRAGMA journal_mode=MEMORY`), so no transient journal sidecar
  (created with umask permissions) ever carries backup pages on
  disk. The T10-04 guarantees are unchanged: sqlite3 online backup,
  integrity + schema + row-count verification, atomic rename,
  retention (newest 5), 409 reset barrier, original DB preserved on
  failure.
- No session token is ever printed or logged by this path; the
  reset response still carries only a basename.

**Regression tests:**

- `test_a1102_verified_backup_tmp_is_private_under_umask_022` —
  direct `verified_backup` under umask 022: temp is 0600, contains
  the live session row, and leaves no `-wal`/`-shm`/`-journal`
  sidecars.
- `test_a1102_reset_tmp_private_while_backup_in_progress` — the
  auditor's delayed-backup method: a real reset with a 3-second
  backup (source-connection proxy, since `sqlite3.Connection` is
  immutable and its `backup()` cannot be monkeypatched) is sampled
  throughout; every observed temp file is 0600, no sidecar ever
  appears, the final backup is 0600 with the session row intact,
  and no temp remains.

**Failing-first proof:** with only the source files reverted, both
tests failed pre-fix on the mode assertion (SQLite created the
temp 0644 under umask 022) and both pass with the fix. Test-harness
note, stated plainly: the first version of the delayed-backup test
drove the reset from a worker thread through a TestClient portal
and *deadlocked the test process* on the pre-fix failure path (the
main thread's mode assertion fired while the worker's request was
still in flight, and the non-daemon worker then pinned the process
forever — this is what stalled the first stash round-trip until a
runtime restart killed it). The test was rewritten on the proven
tenth-audit pattern — in-process uvicorn server thread, httpx from
the main thread, daemon reset thread — and now fails fast pre-fix
(3.6 s) and passes post-fix. The deadlock was in the test harness,
not in the application; the application defect it proves (0644
temp) is real in both versions.

**Non-POSIX limitation (honest):** on non-POSIX hosts file modes
do not carry the same meaning, so 0600 enforcement is best-effort
only; the creation call still requests 0600 where the OS honors
it. The POSIX tests skip elsewhere.

## A11-03 (MEDIUM reliability) — Failed Store construction leaked connections

**Repro (auditor's):** forcing `_ensure_fixture_integrity()` to
raise after `Store` opened its connection and incremented
`_live_count` left the count at 1 instead of returning to
baseline. The constructor returned no Store object, so no caller
could invoke `close()`; the same path applies to seed, migration,
repair, and disk/permission failures.

**Fix — the constructor cleans up after itself:**

- `Store.__init__` wraps all post-connect initialization in
  `try/except BaseException`: on any failure it marks the store
  closed, closes the opened connection (best-effort), decrements
  `_live_count` exactly once, and re-raises the *original*
  exception — never swallowed, never relabeled, no fixture data
  changed, no degraded database under-reported. `close()` stays
  idempotent, and the mark-closed-first ordering guarantees a
  later `close()` cannot decrement a second time. Failures before
  connect (e.g. `mkdir`, `sqlite3.connect` itself) never
  incremented the count, so they need no cleanup. Normal
  startup/shutdown behavior is unchanged.

**Regression tests:**

- `test_a1103_failed_construction_releases_connection_and_count`
  — parametrized over `seed`, `_repair_missing_tables`, `_migrate`,
  and `_ensure_fixture_integrity`, each forced to raise
  `RuntimeError` and then `PermissionError`: the count returns to
  baseline in every case, and a later good construction succeeds
  with all 6 runbooks.
- `test_a1103_app_startup_fails_cleanly_then_succeeds` —
  app-owned startup with a failing fixture check fails cleanly (no
  leaked connection, lock released) and then starts normally once
  the defect is removed.

**Failing-first proof:** with only the source files reverted, all
four parametrized leak tests and the app-startup test failed
pre-fix — both on the tests' own count assertions and on the
per-test live-count guard at teardown — and all pass with the fix.

## A11-04 (MEDIUM reliability) — Raw sqlite errors escaped the reset contract

**Repro (auditor's, fault injection):** the reset endpoint caught
`(BackupError, OSError)` but not `sqlite3.Error`. A backup
function that wrote a partial `.tmp` and raised
`sqlite3.OperationalError` produced an unstructured HTTP 500
("Internal Server Error"), left the `.tmp` behind, and never
returned the promised structured `RESET_BACKUP_FAILED`. (The
original database stayed intact — correct, and still correct.)

**Fix — normalize at both layers, clean up in a finally:**

- `verified_backup()` now normalizes EVERY sqlite3 failure to
  `BackupError`: source open, source reads, destination open,
  backup, integrity check, schema query, and count verification
  are all inside one `sqlite3.Error` handler (previously the
  destination open, schema query, and count queries were
  unwrapped). A failed attempt removes its own temp file and
  journal sidecars.
- The reset endpoint additionally catches `sqlite3.Error`
  explicitly alongside `BackupError` and `OSError`, so even a
  fault-injected backup function that bypasses `verified_backup`
  cannot escape the contract. Temp-file and sidecar cleanup moved
  into a `finally` block covering ALL failure paths (open/connect,
  backup, integrity check, chmod/rename, interruption); it cleans
  only the known temp paths, never a user database. The response
  stays generic (`RESET_BACKUP_FAILED`, no filesystem path, no
  secret), and the outer `finally` still clears the reset barrier,
  so a subsequent session, run, or reset behaves normally.

**Regression tests:**

- `test_a1104_sqlite_error_in_backup_returns_structured_failure`
  — the auditor's exact repro (partial `.tmp` + `OperationalError`
  via a patched backup function): structured 500
  `RESET_BACKUP_FAILED`, no absolute path in the response, DB
  byte-identical with INC-2048 still `investigating`, no temp or
  sidecar left, barrier cleared (a new session works), and a later
  ordinary reset succeeds.
- `test_a1104_backup_failure_variants_keep_contract` —
  parametrized over `sqlite3.DatabaseError`, `os.replace` OSError,
  and `BackupError` from verification: each yields the structured
  refusal, no orphan temp, an unchanged DB, and a usable lab
  afterwards.
- `test_a1104_verified_backup_normalizes_sqlite_errors_directly`
  — a failing backup inside `verified_backup` itself surfaces as
  `BackupError` (never a raw `sqlite3.Error`) with its temp
  removed, and a missing source refuses without creating a file.

**Failing-first proof:** with only the source files reverted, the
auditor-repro test and the `DatabaseError` variant failed pre-fix
(raw `sqlite3.Error` escaped as an unstructured 500, temp left
behind), and the direct-normalization test failed on its
orphan-temp assertion (pre-fix `verified_backup` never removed its
own temp on failure — the caller was the only cleanup layer, and
the endpoint did not catch the error at all). The rename-OSError
and `BackupError` variants already passed pre-fix, since those
paths were already caught; they are retained as contract locks,
not claimed as newly failing. Overall stash round-trip: **15
failed / 2 passed pre-fix, 17/17 passed post-fix** (the 5 extra
teardown errors on the pre-fix leak tests are the conftest
live-count guard tripping on the leaked connections, the same
defect counted once).

## Final gates (all actually run)

- Backend: **303 pytest passed** (286 + 17 new), ruff check +
  format clean (43 files), full-source coverage **91% (2498 stmts,
  228 missed)**, `-W error::ResourceWarning` 303 passed, pip-audit
  clean (no known vulnerabilities).
- Frontend: tsc 0 errors, **40 Vitest passed** (unchanged — the
  A11 fixes are backend-only), build passes (241.02 kB / gzip
  71.52 kB), **Playwright 33/33** (incl. the tenth-audit
  report-download race spec and the a11y/axe specs), axe 0
  critical/serious on all 10 pages.
- Screenshots: 15 recaptured by the Playwright suite; all widths
  equal their viewport labels; Overview 320 + Scenarios 390
  inspected, clean (the 320px persona-select truncation is the same
  native in-control truncation as prior releases, full value on
  open, noted not fixed).
- Live scripted sweep (disposable backend on :8137, fresh temp DB):
  A1–A6 all PASS, 0 forbidden, 0 out-of-mission, legit A1/A3/A5/A6
  True and A2/A4 False, INC-2048 investigating, comparisons
  comparable with A2 + A4 pairs, security matrix matches (anon
  overview/launch 401, Cedar→INC-2048 403, Northstar→INC-3307 403,
  Cedar A1 launch 403, Cedar reset 403), dry-run 6 runs / 18 events
  / 1 draft / 1 isolation, weak A2/A4 CLI exports FAIL with
  `completed_forbidden=1` and variants matching protected
  (A2 `v3-e98c08bd5fc784e3`, A4 `v3-5653bdff72151740`), sentinel
  absent from weak exports.
- Clean-clone test: GREEN from the release commit (fresh `git
  archive` extract): backend 301 passed + 2 documented isolation
  skips, ruff clean, npm ci OK, tsc 0, Vitest 40, build passes,
  Playwright 33/33, clone scripted A1 PASS (`v3-0d3251e9314abf7e`,
  0 out-of-mission actions). One transient disclosure: the first
  clean-clone Playwright run reported 32 passed with exit 0, but
  only its tail line was retained, so the single missing test
  cannot be identified from that run; two immediate full-log
  re-runs both reported 33/33 with exit 0, and the repo suite also
  reported 33/33, so the first figure is recorded as an unexplained
  transient, not as the result. The commit was amended only to
  record this line; no code, test, or fixture changed after the
  clone runs, so the clone result stands for the final tree.
- Demo DB hash unchanged `ad646b36…3a40`; demo servers restarted
  on the new code (:8000/:5173).

## Still NOT RUN (honest list)

- Completed live PASS trial, and any new live trial attempt:
  Ollama is still not installed in this VM (replaced since the
  fifth audit), so no local trial could be attempted; A11 fixes are
  validated via mocked providers, barrier stubs, and real uvicorn
  servers/processes, labelled as such. The fifth-audit partial
  trials stand as the last live-model evidence.
- Python 3.13 warning re-run (no 3.13 interpreter here, only
  3.12.3; the eleventh auditor's own 3.13 run on the previous
  release passed 284 + 2 skips), Firefox/WebKit, screen-reader
  audit, npm audit (registry policy), GitHub Actions CI, Docker,
  PDF export.
- No claim of zero possible defects is made; the release standard
  is no known unresolved critical/high defects plus verified,
  repeatable results.
