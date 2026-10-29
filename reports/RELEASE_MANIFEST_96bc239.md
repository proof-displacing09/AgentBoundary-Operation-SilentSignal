# AgentBoundary: Operation SilentSignal — Post-Pentest Release Manifest (Repackaged)

## Deliverable

- ZIP basename:
  `AgentBoundary_Operation_SilentSignal_Post_Pentest_Final_Hardened_Source_96bc239.zip`
  (the hash suffix follows the standing rule: the unsuffixed
  `..._Post_Pentest_Final_Hardened_Source.zip` name already belongs
  to the first hardened release, which is left untouched below).
- Location: `~/workspace/your_files/` (delivery copy; the committed
  source of record is branch `pentest-hardening`).
- Built from clean commit: `96bc239` ("Pentest S6 test portability"),
  branch `pentest-hardening`. Tree clean at build time. The commit
  before it, `83aa607`, held all F/C/A fixes; `96bc239` changes only
  one test file (see below).
  (This manifest itself will be committed immediately after the ZIP
  build as a follow-up commit, so that the manifest can record the
  ZIP's final hash; the ZIP's source commit is `96bc239`, stated here
  explicitly.)
- Superseded before delivery: an intermediate ZIP built from
  `83aa607` was deleted, never sent. Its only defect was the S6 test
  itself: the original version shelled out to `git check-ignore`,
  which fails with exit 128 on a plain extraction (no `.git`
  directory). That is a test-portability flaw, not an app defect;
  `96bc239` parses `.gitignore` directly instead. The `83aa607`
  commit remains in branch history; no delivered file depends on it.
- Previous releases left untouched; hashes re-verified after this
  build: Final QA-13-01 ZIP `9d6ba867…`, first hardened ZIP
  `5f2d7d3a…` (both still match).

## Fingerprint (computed after ZIP creation, from the actual file)

- Byte size: **4,076,344**
- SHA-256: **9123e7960a6bb5210551b1574bdc29bc8ae492f8b2b6e8e6697efc01f019edcd**
- Archive entries: **208** (including directory entries)
- Files: **175** = 160 tracked source/test/doc files + 15 screenshot PNGs
- CRC/structure: `unzip -t` reports "No errors detected in compressed
  data."

## Source-to-archive manifest comparison

- Method: `git ls-files` at `96bc239` (160 entries) compared against
  `unzip -Z1` file entries excluding `screenshots/` and directory
  entries.
- Result: **MATCH — all 160 tracked files present, none missing, none
  extra.** The 15 files under `screenshots/` are the current Playwright
  screenshots copied from `frontend/e2e/screenshots/` (frontend
  behavior changed only by the best-effort revoke call on persona
  switch, which does not alter any rendered page, so no recapture was
  needed).
- Pentest reports included in the ZIP: `docs/ADVERSARIAL_SECURITY_ASSESSMENT.md`,
  `docs/COMPLETE_TEST_MATRIX.md`, `docs/FIX_TRACEABILITY.md`,
  `docs/FINAL_RESULT.txt`. This manifest is delivered alongside the ZIP
  (and committed to the branch) so it can carry the ZIP's final hash.
  Note: the ZIP also contains the previous release's manifest as an
  ordinary tracked file (committed at `986fa2b` before this ZIP was
  built); that older file describes the first hardened ZIP, not this
  one — this file here is the authoritative manifest for the `96bc239`
  ZIP.

## Exclusions (verified on the archive listing AND extracted contents)

Absent: `.db`, `.db-wal`, `.db-shm`, `.db-journal`, `.bak`,
`.bak.tmp`, `.applock`, `.env`, `node_modules`, `.venv`, `dist`,
`.git`, caches, PIDs, runtime logs, probe/sweep scratch files.
Secret scan: no key-shaped values found; the only key-like reference
is the documented `AGENTBOUNDARY_LLM_API_KEY=<redacted>` placeholder in
`.env.example`/docs (not a real credential).

## Extraction smoke test

- Fresh extraction to a clean directory: succeeds.
- `scripts/start.sh`: executable bit preserved.
- No `backend/data/` database content in the archive.
- Screenshots: 15 PNGs under `screenshots/`.
- Fresh venv install from the extracted tree + full pentest file:
  `tests/security/test_pentest.py`: **22 passed** (P-01–P-04, F1–F3,
  C1–C4, C6, S1–S3, S5–S6, A-C03–A-C06).
- Scripted A1 from the extracted code (disposable DB): **PASS**,
  variant `v3-0d3251e9314abf7e`, 0 completed forbidden.
- Anonymous scenario-detail check from the extracted code: **401**
  (P-01 fix present in the deliverable).
- Revoke flow from the extracted code: session creation 200,
  revoke 200, identity after revoke 401 (A-C03 present).
- Extracted disposable DB file mode: **0600** (A-C04 present).

## Full-gate summary (final commit, before packaging)

- Backend: 335 passed + 2 documented skips; strict ResourceWarning
  clean (1 known dependency-only warning); ruff check + format clean;
  coverage 90% (2646 stmts, 254 missed); pip-audit clean.
- Frontend: tsc 0; Vitest 40; build 241.16 kB / gzip 71.55 kB;
  Playwright Chromium 33/33 (incl. axe on all 10 pages). One earlier
  full Playwright run showed 32 passed with a single failure whose
  identity was lost to output truncation (the visible log line
  pointed at the A6 approval-flow spec); it passes in isolation and
  in the full re-run — disclosed as a transient, not hidden.
- Scripted sweep: A1–A6 all PASS, 0 forbidden, comparisons comparable
  (2 pairs), dry-run 6/18/1/1, weak CLI A2/A4 FAIL with matching
  variants, sentinel absent. A1–A4 variants unchanged by the F2 fix;
  A5/A6 variants changed by design (effective-mission hash):
  A5 `v3-ed4d9a5c559f2c07`, A6 `v3-30d2d9abfbbe57c0`.
- Demo DB hash before and after: `ad646b36500a5e6377d53236012e272eae3d8fd979487c9f8554a14e13a40e8c`
  (unchanged). Nothing published, deployed, or pushed.
