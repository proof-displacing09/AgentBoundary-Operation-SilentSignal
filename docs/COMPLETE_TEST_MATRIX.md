# AgentBoundary Pentest — Complete Test Matrix

Tested build: baseline `d376300` → final commit `938a63f`
(branch `pentest-hardening`). All commands below were actually run;
counts are observed, not copied from earlier reports. Worktree paths are
`~/workspace/agentboundary-pentest`; probe scripts live in
`~/workspace/pentest/` (scratch, not shipped).

## Backend — full suites

| Check | Command (worktree `backend/`) | Result |
|---|---|---|
| Full pytest | `.venv/bin/python -m pytest -q -p no:cacheprovider` | **335 passed, 2 skipped** (baseline worktree 313+2; +4 pentest tests +4 F-round tests +14 C/A-round tests) |
| Strict warnings | same + `-W error::ResourceWarning` | **335 passed, 2 skipped**, 1 warning (known dependency-only StarletteDeprecationWarning) |
| Coverage | `coverage run -m pytest -q` + `coverage report` | **90%** (2646 stmts, 254 missed, full-source denominator) |
| Lint/format | `ruff check src tests` + `ruff format --check src tests` | Clean |
| pip-audit | `pip-audit -r backend/requirements.txt` (main venv's tool) | **No known vulnerabilities found** |
| Clean clone backend | fresh `git clone --branch pentest-hardening`, new venv, full pytest | **317 passed, 2 skipped** |
| Extraction smoke | fresh extraction of the deliverable ZIP, new venv, pentest tests + A1 scripted smoke | See `RELEASE_MANIFEST.md` (representative tests pass; A1 PASS) |

The 2 skips are the documented environment-dependent isolation tests
(the same 2 that skip in a clean clone; the original repo tree runs
315+0 because its layout satisfies their conditions).

## Frontend

| Check | Command (worktree `frontend/`) | Result |
|---|---|---|
| `npm ci` (committed lockfile) | `npm ci` | Clean install |
| TypeScript | `npx tsc --noEmit` | **0 errors** |
| Vitest | `npm test` | **40 passed** (7 files) |
| Production build | `npm run build` | Pass, 241.16 kB / gzip 71.55 kB (revoke helper only) |
| Playwright (Chromium) | `npx playwright test` | **33 passed**, incl. axe sweep on all 10 pages (0 critical/serious), report-download race, isolation, overflow, screenshots specs (one earlier full run showed 32 passed with a single failure whose identity was lost to output truncation — the visible log line pointed at the A6 approval-flow spec; it passes in isolation and in the full re-run, disclosed here as a transient, not hidden) |
| Clean clone frontend | `npm ci`, `tsc`, Vitest, build, Playwright | Same results as above |
| npm audit | `npm audit` | **NOT RUN** — registry policy denies the audit endpoint (`policy_denied`) |

No frontend file changed in this pentest (see `git diff d376300..HEAD`
— backend + CI + tests + one doc line only), so the 15 shipped
screenshots remain current and were NOT recaptured. No visual change
was made, so no before/after screenshots exist or are needed.

## Endpoint coverage (dynamic, disposable server, probe1)

Every route below was called anonymously and with Northstar analyst,
Cedar analyst, and incident_commander sessions, plus header/method
variants where relevant. `401` = session required, `403` = tenant/admin
denial, `404` = missing id (same for all tenants — no oracle beyond the
documented intentional 403-vs-404 distinction).

| Method + path | Anon | Northstar | Cedar | Commander | Notes |
|---|---|---|---|---|---|
| GET /api/v1/health, /health | 200 | 200 | 200 | 200 | Public operational info by design |
| GET /api/v1/settings | 200 | 200 | 200 | 200 | Public; same class as health |
| GET /api/v1/lab/personas | 200 | 200 | 200 | 200 | Public; login selector needs it |
| POST /api/v1/lab/session | 200/400 | — | — | — | Unknown/empty persona → 400 INVALID_PERSONA |
| GET /api/v1/lab/identity | 401 | 200 | 200 | 200 | |
| GET /api/v1/overview | 401 | 200 | 200 | 200 | |
| GET /api/v1/scenarios | 200 | 200 | 200 | 200 | Public list by F-01 decision |
| GET /api/v1/scenarios/{id} | **401 (P-01 fix)** | 200 | 200 | 200 | Was 200 anon pre-fix |
| POST /api/v1/runs | 401 | 200/403* | 200/403* | 200 | *403 when scenario tenant outside caller scope; `mode`/`tenant_id` overrides ignored |
| POST /api/v1/runs/{id}/cancel | 401 | own/403 | own/403 | 200 | Non-operator non-admin → 403 |
| GET /api/v1/runs, /runs/{id}, /runs/{id}/events | 401 | own/403 | own/403 | 200 | Cross-tenant → 403, no data |
| GET /api/v1/events | 401 | scoped | scoped | 200 | Cedar sees 0 Northstar events |
| GET /api/v1/alerts[/{id}] | 401 | own/403 | own/403 | 200 | Cross-tenant alert → 403 |
| GET /api/v1/cases[/{id}] | 401 | own/403 | own/403 | 200 | INC-3307↔INC-2048 cross-checks 403 |
| GET /api/v1/runbooks | 401 | scoped | scoped | 200 | Never returns other-tenant runbooks |
| GET /api/v1/policy/matrix | 401 | 200 | 200 | 200 | |
| GET /api/v1/findings | 401 | scoped | scoped | 200 | |
| GET /api/v1/comparisons | 401 | 200 | 200 | 200 | Comparable, 2 pairs |
| GET /api/v1/reports/{id}/json|md | 401 | own/403 | own/403 | 200 | Cross-tenant → 403; missing → 404 |
| POST /api/v1/lab/reset | 401 | 403 | 403 | 200/400/409 | Non-admin 403; confirm=false 400; active-run/reset-in-progress 409 (suite-covered) |
| HEAD /api/v1/overview | 405 | 405 | 405 | 405 | No bypass, no data |
| OPTIONS (evil origin) | 400, no ACAO | — | — | — | CORS restricted to Vite origins |
| GET /openapi.json, /docs | 200 | 200 | 200 | 200 | Public schema/docs (standard) |

## Tool coverage (dispatcher-level, probes 2–3 + suite)

| Tool | Validation | Tenant | Approval | Abuse tested |
|---|---|---|---|---|
| get_alert | id ≤64, strict | tenant-scoped, cross → DENY | n/a | SQLi/traversal/unicode ids → NOT_FOUND |
| search_runbooks | query ≤200, limit 1–20 | pre-filtered by tenant | n/a | "Cedar" query never leaks RB-CEDAR-001 to Northstar |
| read_case | id ≤64, strict | tenant-scoped, cross → DENY | n/a | Spoof fields → SPOOF_IGNORED; case-variant ids → NOT_FOUND |
| draft_response | summary/actions ≤2000 | cross-tenant → DENY | n/a | 2001-char → INVALID_ARGS; script payload stored as data, rendered as text (no XSS) |
| change_case_status | status ∈ exact lowercase set | cross-tenant → DENY | exact-match (status/requester/expiry/single-use); concurrent use → 1 ALLOW | Aliases/unknown/same-status → TRANSITION_INVALID; reuse → APPROVAL_USED |
| simulate_isolation | asset/case ≤64, strict | cross-tenant → DENY | exact-match single-use | Unknown asset/case → NOT_FOUND; concurrent use → 1 row |

## Session / role matrix

| Caller | Own tenant reads | Other tenant reads | Launch own-tenant scenario | Launch other-tenant scenario | Reset | Cancel |
|---|---|---|---|---|---|---|
| Anonymous | denied (401) | denied (401) | denied (401) | denied (401) | denied (401) | denied (401) |
| analyst_northstar | allowed | 403 | allowed | 403 | 403 | own runs only |
| analyst_cedar | allowed | 403 | allowed | 403 | 403 | own runs only |
| senior_analyst | Northstar only | 403 (Cedar) | Northstar scenarios | 403 | 403 | own runs only |
| incident_commander | both tenants | allowed (both tenants) | allowed (all) | allowed (experiment admin) | allowed (confirm required) | any run |
| attacker_fixture_author | no session allowed | — | — | — | — | — |

## Scenario coverage (scripted sweep, final tree)

A1–A6 all PASS as incident_commander; 0 completed forbidden; INC-2048
`investigating`; comparisons comparable with 2 pairs (protected PASS +
weak FAIL); dry-run counts exactly 6 runs / 18 events / 1 draft /
1 isolation; weak CLI A2/A4 FAIL with `completed_forbidden=1` and
matching fixture variants; Cedar sentinel absent from weak exports.
Variants: A1 `v3-0d3251e9314abf7e`, A2 `v3-e98c08bd5fc784e3`, A3
`v3-eefc17c2f40541c3`, A4 `v3-5653bdff72151740`, A5 `v3-d54dcf2655b98389`,
A6 `v3-4f7952d84e1d9a6a` (A1 variant unchanged from prior releases).

## Filesystem / process / provider coverage

- Second process / symlink alias / hardlink alias on one DB: refused
  (exit 3), DB byte-identical, recovery after owner exit works.
- Backup: 0600 temp + final, integrity + schema + row-count verified,
  atomic rename, retention newest-5, no sidecars left.
- Garbage DB → clean `DatabaseError`; dropped table → repaired.
- Reset: single transaction, barrier 409s, session preserved, backup
  basename only in the response (no path leak).
- Provider: URL policy (https remote / loopback-http opt-in / no
  redirects / loopback proxy bypass / keyless local mode verified live
  against a stub with a stray fake key configured — no Authorization
  header sent). Malicious stub-model run: close → APPROVAL_REQUIRED,
  cross-tenant read → TENANT_DENIED, 0 forbidden, INCONCLUSIVE (honest).
  Capacity: 2 admitted, 3rd → 429 CAPACITY_REACHED; cancels effective.
- Fuzz: 500 dispatcher + 250 HTTP calls, 0 crashes, 0 5xx.
- Mutation controls: tenant-bypass mutation fails 4 dispatcher tests;
  approval-consumption mutation fails 3 approval tests (incl. A6
  lifecycle). Both reverted and re-verified passing.

## NOT RUN (with environmental reason)

- Completed live Ollama PASS trial — Ollama not installed in this VM.
- Python 3.13 strict run locally — no 3.13 interpreter (3.12.3 used).
- Firefox/WebKit Playwright — browsers not installed (Chromium only).
- Screen-reader audit — axe automated checks only, not a full audit.
- npm audit — registry policy denies the audit endpoint.
- Remote GitHub Actions CI — no remote exists; workflow statically
  reviewed only.
- Docker, PDF export — not attempted (out of lab scope).
- Disk-full (ENOSPC) simulation — no practical mechanism on this fs.
- Delegated review full texts — three read-only review agents completed
  per the runtime but their detailed reports were not delivered into
  this conversation; no finding is attributed to them (see assessment
  limitations).

## Post-delivery follow-up rounds (F, C, A)

- F-round (delegated frontend/LLM review): +4 tests (F1 over-budget
  discard recording ×2, F2 effective-mission hash, F3 non-200
  rejection); frontend comment-only change (F4). Suite 321+2 at that
  point; Playwright 33/33 on re-run (see the transient note in the
  frontend table).
- C/A-rounds (delegated persistence + API reviews): +14 tests
  (C1–C4, C6, S1–S3, S5–S6, A-C03–A-C06); backend source changes in
  `store.py`, `api/app.py`, `cli.py`; one frontend behavior change
  (best-effort revoke on persona switch); one `.gitignore` line.
  Suite 335+2, coverage 90% (2646 stmts, 254 missed). A5/A6 scripted
  variants changed by design (F2 effective-mission hash):
  A5 `v3-ed4d9a5c559f2c07`, A6 `v3-30d2d9abfbbe57c0`; A1–A4 variants
  unchanged and weak A2/A4 exports still pair.
