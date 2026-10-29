> **SUPERSEDED — historical record only, do not quote as current.**
> This is the third-audit remediation report (commit `ea04cbd`, 156
> tests, 1814 statements). The canonical current validation table is
> `docs/validation-and-limitations.md` (sixth-audit remediation: 225
> tests, 34 Vitest, 31 Playwright, 2111 statements), and the
> sixth-audit findings record is
> `docs/sixth-independent-audit-remediation.md`. Figures below were
> true for their release and are preserved unchanged.

# Validation Report — Third-Audit Remediation Release (2026-10-25)

Commit: `ea04cbd` (+ this file). Previous release: `f20b50b`
(ZIP SHA-256 `5821805528bf72bcd46c8432cc7fd593ba052875cb08446674cdde2727db024a`).

## Environments

- Backend: Python 3.12.3, pytest 9.1.1, coverage 7.17.0, ruff (repo
  config), pip-audit 2.10.1.
- Frontend: Node v24.22.1, npm 10.9.4, TypeScript 5.7.2, Vite 6.0.7,
  Vitest 3.2.7, Playwright 1.64.1 (Chromium headless shell 156).
- All servers bound to 127.0.0.1 only. All test DBs disposable and
  separate from the demo DB.

## Commands and results (all executed, not inferred)

| Command | Result |
|---------|--------|
| `cd backend && .venv/bin/python -m pytest -q` | **156 passed, 0 failed** (1 warning, pre-existing) |
| `ruff check src tests` + `ruff format --check src tests` | All checks passed; 35 files formatted |
| `coverage run -m pytest -q && coverage report` (full source, `--source src/agentboundary`) | **90% (1814 stmts, 177 missed)** |
| `cd frontend && npx tsc --noEmit` | 0 errors |
| `npx vitest run` | **30 passed** (4 files) |
| `npm run build` | Passes (JS 233.18 kB, gzip 69.66 kB) |
| `npx playwright test` (isolated temp DB + free ports) | **27 passed** (lab 11, a11y 10, isolation 1, screenshots 5) |
| Axe (all 10 pages) | 0 critical, 0 serious |
| `pip-audit -r requirements.txt` | No known vulnerabilities found |
| `npm audit` | NOT RUN — registry policy blocks the audit endpoint in this environment |
| Live A1–A6 sweep (disposable backend, incident_commander session) | A1 run-a1-672e315b, A2 run-a2-b5eb562b, A3 run-a3-22e09a47, A4 run-a4-2c472217, A5 run-a5-dc472217, A6 run-a6-6e212007 — all PASS, attempted 0/1/1/1/1/2 = 6, completed_forbidden 0, INC-2048 `investigating` |
| Restart persistence (kill + restart on same DB) | Run + 5 events preserved; health ok, 48 records, fixture_integrity ok |
| Demo-DB preservation across full Playwright run | SHA-256 identical before/after: `302dcf584074beed2c8d3038b2428bf0ede88e5efac06c61b820f348cb01aa63` (0 runs, 0 events, 2 sessions) |
| Clean-clone test (fresh `git clone`, repo scripts only) | Backend 155 passed + 1 skipped (isolation test skips with reason when Playwright not installed), ruff clean, tsc 0, Vitest 30/30, build passes, clone server health ok (48 records), clone A1 PASS |
| Weak CLI exports (gated, temp DBs) | weak-A2 / weak-A4 regenerated, verdict FAIL / FORBIDDEN_COMPLETED; 0 temp DBs left |
| Secret scan of release ZIP | Clean (see packaging section) |

## Critical/high count

Zero known unresolved critical/high defects. R-01–R-18: all FIXED
(see `docs/third-independent-audit-remediation.md` for per-finding
evidence). F-01–F-06 and N-01–N-08 protections still pass.

## Screenshots (real captures, visually inspected)

15 PNGs under `screenshots/` in the release ZIP (overview / scenarios /
replay × 1440×900, 1920×1080, 768×1024, 390×844, 320px), captured by the
isolated E2E run and opened by the remediator. Findings: no
overlap/overflow/clipping at any width; two label defects found and fixed
during review (raw trial-outcome enums → plain-language labels).

## NOT RUN / BLOCKED (complete list)

- Live real-provider evaluation (no provider key; no spending
  authorized). Mocked-protocol adapter tests pass; they are not live
  trials and are never labeled as such.
- Firefox / WebKit Playwright browsers (Chromium only).
- Screen-reader audit.
- `npm audit` (registry policy block, above).
- GitHub Actions CI run (workflow YAML parses; no hosted run).
- Docker, PDF export (print-to-PDF path only, where labeled).
- Python 3.13 warning sweep (tests run on Python 3.12.3 here; the
  auditor reproduced the prior release on 3.13.5).

## Packaging

ZIP built from `git archive` of the committed tree (tracked files only —
no runtime DB, `.venv`, `node_modules`, `dist`, caches, or `.git`) plus
the 15 real screenshot PNGs under `screenshots/`. CRC verified on
extraction; secret scan clean (one documented false positive only in
the prior release's docs placeholder `AGENTBOUNDARY_LLM_API_KEY=
<redacted>`; this release's scan result is recorded with the ZIP hash
in the delivery message). Nothing pushed to GitHub, deployed, or
publicly hosted.
