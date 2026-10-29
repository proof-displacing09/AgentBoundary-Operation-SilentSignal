# AgentBoundary: Operation SilentSignal — Final Personal Backup Manifest (revised)

## Backup identity

- **Archive:**
  `AgentBoundary_Operation_SilentSignal_FINAL_PERSONAL_BACKUP_20261027_FD01_Fixed.zip`
- **Source:** branch `c5-remediation`, packaging commit `264fedd`
  (docs-only report commit), clean tree at packaging time.
  Application-code commit `6debffd` (FD-01 fix: production lock
  code + `test_fd_leak.py`). The commit between `6debffd` and the
  packaging commit changed documentation only (this report),
  verified by zero backend/frontend diff.
- **Contents:** 169 tracked source/test/doc files + 15 screenshot
  PNGs under `screenshots/` + this manifest +
  `WINDOWS_SETUP.md` = **186 files**. Layout: repository root,
  plus `screenshots/`. Production and test code in this archive
  are byte-identical to commit `264fedd`; the two packaging
  documents above were added at packaging time and are not
  tracked source files.
- **What is inside:** full backend (FastAPI + SQLite) and
  frontend (React/TS/Vite) source; six SOC scenarios A1–A6;
  synthetic fixtures for the fictional MDR Nightwatch Security
  (tenants Northstar Logistics / Cedar Retail Group, flagship
  case INC-2048); all tests including the pentest regressions,
  the C5 two-process regressions, and the FD-01 descriptor-
  cleanup regressions; startup/config scripts
  (`scripts/start.sh`, executable); package lockfiles;
  `.env.example` (variable NAMES only, no values); licensing and
  setup documentation; the consolidated security assessment
  report (corrected — see below) plus supporting reports and
  the superseded prior report copy under `reports/`.
- **Supersession:** this archive supersedes the Phase 1 personal
  backup (`..._FINAL_PERSONAL_BACKUP_20261027_9b5d489.zip`,
  SHA `eaa024ab…`) as the user's laptop copy. The Phase 1
  archive itself was left untouched in the environment.

## What changed since the Phase 1 backup (2026-10-27)

1. **FD-01 FIXED (LOW, code).** Exceptional-path file-descriptor
   leak in database lock acquisition: `fcntl.flock` raising a
   non-`BlockingIOError` `OSError` no longer leaks the inode
   descriptor (`_acquire_db_inode_lock`) or the sidecar file
   object (`try_acquire_db_lock`); `DatabaseLock.close()` truly
   never raises (a sidecar close error is swallowed after both
   closes are attempted). Impact was a resource leak on exotic
   failure paths only — NOT a lock bypass. Failing-first proof:
   `tests/security/test_fd_leak.py` (3 tests) failed on the
   pre-fix tree, passes post-fix. FD-01 is NOT one of the
   original 24 engagement findings; it was found by auditing the
   C5 fix itself during the Phase 1 backup audit.
2. **Report reconciliation FIXED (documentation).** The four
   stale C5-residual statements (§D.9 old tally + "Remaining
   known defects" bullet, §E timeline wording, §G.3 threat-model
   wording, §G.5 "correct claim" sentence) are now labeled
   historical in place, with current totals stated alongside.
   Historical numbers are preserved, not erased. The FD-01
   addendum, the §D.2 register row, and the §F.20 gates record
   the correction. Current totals: **24 original findings fixed
   + FD-01 fixed = 25 items addressed, 0 known open in-scope
   findings.**
3. **Nothing else changed.** No feature, scenario, tool, policy,
   or fixture changed. Frontend code is byte-identical to the
   Phase 1 backup tree.

## Verification performed on this exact archive

- `unzip -t` CRC: clean.
- SHA-256, byte size, and archive entry count: recorded in the
  delivery message that accompanies this archive. (This file
  predates packaging and therefore cannot self-contain the
  archive's own hash.)
- Manifest match: all 169 tracked files from commit `264fedd`
  are present; the only extras are the 15 screenshots and the
  two packaging documents named above.
- Exclusions verified (none present): `.git`, `.venv`,
  `node_modules`, `dist`, build caches, live `.env`, live/demo/
  test databases, `.applock` files, SQLite journals/WAL/SHM,
  session tokens, credentials, private evidence, and absolute
  private paths.
- Secret scan: clean except placeholder values (an ellipsis
  placeholder in docs, `"<redacted>"` test fixtures — no real
  keys or tokens).
- Extraction smoke on the delivered package: see "Extraction
  smoke results" below.
- Full-suite evidence reused accurately: backend 347 passed +
  2 documented skips (strict warnings) was run on the tree whose
  application code is identical to this archive; the extraction
  smoke below was run on this exact archive. Frontend gates on
  the same tree: tsc 0, Vitest 40/40, build 241.16 kB / gzip
  71.55 kB, Playwright 33/33.

## Extraction smoke results

- Pentest regression file: 22 passed. C5 regression file:
  9 passed. FD-01 regression file: 3 passed. Total security
  tests from extraction: 34 passed.
- Scripted A1: PASS, variant `v3-0d3251e9314abf7e`,
  0 completed forbidden actions.
- Anonymous scenario detail: 401. Session revoke flow: create
  200, revoke 200, identity-after-revoke 401.
- Extracted disposable database file mode: 0600.
- `scripts/start.sh` and all 6 scripts: executable on extraction.

## What is NOT in this backup (read before Phase 2)

- **Demo database: NOT included, deliberately.** The live demo
  database holds 3 expired session tokens (2026-10-25) and no
  runs, drafts, isolations, or events — only the 48 synthetic
  fixture records, which a fresh database reproduces exactly
  from code on first start. Session tokens are never exported.
  Its fate (keep vs. delete) remains a separate Phase 2
  decision; nothing about it was decided by building this
  archive.
- **Ollama trial evidence: NOT included, deliberately, and kept
  in a SEPARATE archive.** The sanitized evidence archive
  (`AgentBoundary_Ollama_Trial_Evidence_SANITIZED_PRIVATE_20261027.zip`,
  delivered alongside this source ZIP) holds the 7 runs / 18
  events from the three trial databases with sessions excluded
  and values scrubbed. It is private and must not be published
  with the source. The raw trial databases themselves were not
  modified and are not in either archive.
- **No other unique runs exist in the environment.** All
  `demo-backup-*.db` copies are fixture-identical to the demo
  database (0 runs, 3 expired sessions each) and all test/sweep
  databases are disposable by design.

## Known limitations (unchanged from the consolidated report)

- Completed live Ollama PASS trial: NOT RUN (the trial evidence
  in the separate archive is partial: ERROR/INCONCLUSIVE only,
  plus one scripted PASS). Native Windows backend hosting: NOT
  verified — use WSL2 (see `WINDOWS_SETUP.md`). Firefox/WebKit,
  screen-reader audit, npm audit, remote CI, Docker, PDF export,
  Python 3.13: NOT RUN.
- Theoretical construction-window double symlink swap (see
  report §G.2); per-inode (not per-pathname) lock guarantee;
  same-effective-uid OS trust boundary; non-POSIX unflocked
  limitation.
- This source ZIP is not a portable virtual environment;
  dependencies install from lockfiles on first setup.

## Provenance and non-actions

- Nothing was deleted to make this backup. Nothing was
  published, deployed, pushed to any remote, or shared with any
  third party. No paid services were used. No Phase 2 deletion
  has been authorized or performed.
