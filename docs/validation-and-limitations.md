# Validation & Limitations

> **Canonical current validation table.** This document is the single
> current-facing summary. Older dated tables are preserved below under
> explicit SUPERSEDED headings and must not be quoted as current.

## Actually run (2026-10-26, twelfth-audit remediation — current)
| Check | Tool / command | Result |
|---|---|---|
| Backend test suite | `pytest -q` (backend/.venv, Python 3.12.3) | **315 passed, 0 failed, 0 skipped** (303 + 12 new twelfth-audit tests), 1 Starlette TestClient deprecation warning (pre-existing, unrelated to SQLite) |
| Backend lint/format | `ruff check src tests`, `ruff format --check` | **All checks passed** |
| Backend coverage (full-source, audit method) | `coverage run -m pytest` | **91%** (2528 statements, 229 missed) |
| Resource warnings | `python -W error::ResourceWarning -m pytest -q` | **315 passed, zero SQLite warnings** (Python 3.12; Python 3.13 not available here — the twelfth auditor's selected run on the previous release passed 281 + 1 skipped with 2 deselected, not a full reproduction) |
| Frontend typecheck | `npx tsc --noEmit` (strict) | **0 errors** |
| Frontend unit tests | `npm test` (Vitest) | **40 passed** (unchanged from tenth — the A11 and RC12 fixes are backend-only, no new frontend tests; 36 + 4 tenth-audit download-race tests; incl. S7-05 label tests, OUT_OF_MISSION label, SI-06 keyless-Ollama copy tests, session-isolation races, real-LLM surfacing, Overview projection) |
| Frontend build | `npm run build` (Vite 6) | **Passes** — JS 241.02 kB (gzip 71.52 kB) |
| Playwright E2E | `npm run test:e2e` (Chromium headless shell, same host as servers) | **33 passed, 0 failed, 0 skipped** — lab flows, axe on all 10 pages, keyboard Tab reachability on Overview, isolation, overflow at 320/390/768/1440, screenshots at 5 viewports, report-download persona-switch race (tenth-audit) |
| Browser visual QA | Screenshots reviewed by the remediator | 15 PNGs under `frontend/e2e/screenshots/` (included in release ZIP as `screenshots/`, recaptured for this release); all widths equal their viewport labels; Overview 320px + Scenarios 390px inspected (no overflow; 320px persona-select truncation is the same native in-control truncation present in prior releases). Firefox/WebKit: NOT RUN. |
| Accessibility | axe-core Playwright on all 10 pages + keyboard test | **Zero critical/serious violations** on all 10 pages (no rules suppressed); Tab reaches interactive controls on Overview. Screen-reader audit: NOT RUN. |
| Live API integration | uvicorn on 127.0.0.1:8139 (disposable DB) + HTTP client | A1–A6 all **PASS**, 0 completed forbidden, 0 out-of-mission actions; security passes and legitimate workflow completions reported separately (A2/A4 honestly False); comparisons comparable with A2 + A4 pairs; reset dry-run would_delete exactly 6 runs / 18 events / 1 draft / 1 isolation |
| Worker failure (N9-01) | Patched Store/Runner + real API routes | Worker Store open failure (always-raise, auditor's patch) → run **ERROR** (`worker_startup_error`), no thread exception, no leaked Store, reset → 200, 2 fresh jobs launch within cap; fail-once schema failure → ERROR via fresh connection; Runner-construction failure → ERROR (`worker_error`); thread-start failure → launch response itself reports ERROR, never running |
| Restart recovery (N9-02) | Injected queued/running rows + fresh app lifespan | Queued row → **INTERRUPTED/INCONCLUSIVE** (started_at + evidence preserved); running row → same; completed row byte-unchanged; queued + running together → both recovered, INC-2048 still `investigating`, zero orphan events; reset after recovery → 200; second worker denied via `.applock` with no data loss and no leaked store; cancelled row never blocks reset |
| Operator idempotency (N9-03) | Real API routes, stub provider | Same operator + fresh session + same key → same run (one worker); same operator + different scenario → 409; different operator + same key → **independent run with own attribution** (never the first operator's id); Cedar tenant launch still 403 and does not consume the key; replay at cap → original, no slot consumed; reset invalidates the key; error-run key launches fresh; TTL-0 key launches fresh; 300-char key → 400, no run; 5 concurrent same-key launches (real server) → exactly one run |
| Portable burst test (N9-04) | Real uvicorn server, `sys.executable`, free loopback port, explicit PYTHONPATH | Burst of 5 concurrent launches, cap=2 → exactly 2 accepted, 3 × 429 `CAPACITY_REACHED`, no orphan runs, child log attached to assertions; no hardcoded `.venv` path or fixed port remains |
| Lock-before-construction (T10-01) | Real API routes + real uvicorn processes | Denied second app (same path) leaves runbook count, runs, and DB checksum byte-identical; two first-time starts: one initializes 48 records, the other is denied without changing a byte; two real processes: B exits nonzero while A stays healthy, then B starts and repairs after A stops; CLI reset/seed against a server-held DB return 2 with a deleted row still deleted; app without lifespan answers 503 `APP_NOT_STARTED`, construction alone creates no file |
| Verified reset backup (T10-04) | Real API routes + real uvicorn server thread | Backup passes independent read-only integrity/schema/count checks and restores with all runs; session creation and launches during a blocked backup get retryable 409 `RESET_IN_PROGRESS`, then succeed after the reset; backup-write failure and interrupted-backup failure both refuse with 500, clean any `.tmp`, and leave the old DB fully usable |
| Backup tracking/privacy (T10-02) | Real API route + git semantics | 7 stale backups + a reset leaves exactly the newest 5 (`pruned_backups == 3`), new backup is 0600 on POSIX, basename-only in the response, no `.tmp` remains, and the backup restores the pre-reset run + session; a scratch git repo using this `.gitignore` ignores the backup while listing a genuine doc file |
| Report-download race (T10-03) | Vitest (gated body) + real-browser Playwright (fetch-level gate) | Switch during a gated body discards the old report (no `createObjectURL`, no file); abort during a gated body rejects ABORTED; control succeeds; late 401 still token-scoped. In a real browser: Northstar body held after headers, switch to Cedar, release → NO download event, no success toast, Cedar stays selected; switch back to Northstar → the same run downloads normally. Failing-first proven in both harnesses (old code downloads the stale report) |
| Canonical database identity (A11-01) | Real API routes + real uvicorn processes + CLI | Symlink alias and target share one lock: two TestClient lifespans (real + alias) admit only the first; two real processes: alias server exits nonzero with 'already holds' while the real server stays healthy, then the alias server starts and repairs after the owner stops; CLI reset/seed via the alias refuse (exit 2) with a deleted row still deleted; canonical-identity unit checks (alias == target, symlinked parent, :memory: passthrough, distinct directories stay distinct); fault-injected identity change during lock acquisition raises and releases the lock. Failing-first proven (15 failed / 2 passed pre-fix across the new suite) |
| Private temp backup (A11-02) | Real API routes + delayed-backup sampling | Temp backup created 0600 before SQLite opens it under umask 022 (direct call and a real reset sampled throughout a 3-second backup: every observed temp 0600, no journal sidecar — destination journal kept in memory — final backup 0600 with the session row intact, no temp remains). Failing-first proven (pre-fix temp was 0644) |
| Constructor failure cleanup (A11-03) | Patched Store methods + real API routes | Forcing seed, repair, migration, or fixture validation to raise (RuntimeError and PermissionError) leaves `_live_count` at baseline and a later good construction succeeds with all 6 runbooks; app-owned startup with a failing fixture check fails cleanly (lock released) and then starts normally. Failing-first proven (pre-fix count stayed elevated, tripping the per-test live-count guard) |
| Structured backup failure (A11-04) | Real API routes + fault injection | A backup writing a partial `.tmp` and raising `sqlite3.OperationalError` yields structured 500 `RESET_BACKUP_FAILED` (no path in the response), DB byte-identical with INC-2048 `investigating`, no temp/sidecar left, barrier cleared, later reset succeeds. `DatabaseError`, rename OSError, and `BackupError` variants behave the same; `verified_backup` normalizes sqlite3 failures to `BackupError` and removes its own temp; missing source refuses without creating a file. Failing-first proven for the sqlite-error paths (rename-OSError and BackupError variants already passed pre-fix and are retained as contract locks) |
| Hardlink ownership (RC12-01) | Real API routes + real uvicorn processes + CLI + fault injection | An existing database file with `st_nlink > 1` is refused outright (new `HardlinkedDatabaseError`): both lock attempts and both lifespans on a hardlinked pair fail, no `.applock` created, DB byte-identical, live count at baseline; both real servers exit nonzero with 'hard links' in the log; CLI reset/seed exit 2 without mutating; unlinking the extra link restores the surviving path (server starts and repairs). Post-lock revalidation checks BOTH the resolved pathname (A11-01 string check, retained) and the (device, inode, link count) tuple; a fault-injected link-count change raises 'identity changed' and releases the lock. Symlink alias and ordinary path still work separately. Failing-first proven (part of 10 failed / 2 passed pre-fix across the new suite) |
| Atomic reset (RC12-02) | Real API routes + fault injection + stub-provider real-mode run | Schema rebuild, fixture inserts, and preserved-session insert commit in ONE `BEGIN IMMEDIATE` transaction: a fault in `_preserve_session`, at schema rebuild, or after the reseed rolls the whole reset back (runs/events/sessions/drafts/isolations/approvals/cases and INC-2048 `investigating` unchanged, run row present) and returns structured 500 `RESET_FAILED` (no path in the response), distinct from `RESET_BACKUP_FAILED`; no `.tmp` remains, exactly one 0600 `.bak` containing the old run, barrier cleared, retry succeeds with 48 records. Ordinary reset: 200, 48 records, exactly 1 session (the commander's). A failed reset does NOT clear idempotency (same key replays the original run); a successful reset does (same key launches fresh). Failing-first proven (part of 10 failed / 2 passed pre-fix) |
| API reset vs active job (E8-01) | Barrier stub provider + real API routes | Reset during a blocked provider call → **409 RESET_BLOCKED_ACTIVE_RUNS**, run + data intact, zero orphan events; two simultaneous jobs → 409 with active_runs=2; reset after cancel / after worker failure → 200; CLI reset refused (exit 2) while a server holds the DB |
| Comparison masking (E8-02) | Real API route + injected newer rows | Newer real A2, newer variant-mismatched scripted A2, and newer policy-mismatched scripted A2 do NOT mask the older matching scripted pair; two eligible runs pair once with the other listed as an alternative; legacy weak export never shadows v3 |
| Real-mode concurrency (E8-03) | Stub provider + real uvicorn server, cap=2 | Burst of 5 concurrent launches → exactly 2 accepted, 3 × 429 `CAPACITY_REACHED`, no orphan runs; sequential cap=1 → second launch 429 with no run row; `Idempotency-Key` replay returns the same run id (now operator-scoped, N9-03) |
| API cancellation during provider response | Stub provider delay 2s + cancel posted after the worker entered the provider call (S7-02 regression) | Run **CANCELLED**, case still `investigating`, zero mutations from the late proposal |
| Restart persistence | kill + restart backend via repo scripts | Demo DB hash unchanged (`ad646b36…3a40`); health ok, 48 records, fixture_integrity ok |
| Clean-clone install | Copy excluding .venv/node_modules/dist/DB/.git → repo scripts → full gates | See `docs/twelfth-independent-audit-remediation.md` (run from the release commit) |
| Cross-tenant / leakage probes | Direct API calls as analyst_northstar / analyst_cedar | Anonymous overview/launch → 401; INC-3307 → 403 TENANT_DENIED, INC-2048 as Cedar → 403, Cedar A1 launch → 403, Cedar global reset → 403; sentinel absent from weak A2/A4 exports and everywhere for non-admin viewers |
| Weak-mode gate | CLI with `AGENTBOUNDARY_UNSAFE_LAB=1` → weak A2/A4 exports in throwaway DB | Weak A2 FAIL (`WEAK_SKIP_APPROVAL_ON_CLOSE`), weak A4 FAIL (`WEAK_SKIP_TENANT_CHECK_ON_READ_CASE`); variants match protected (`v3-e98c08bd5fc784e3`, `v3-5653bdff72151740`); main DB INC-2048 verified still `investigating`. Refusal without the env flag is covered by the suite. |
| Report exports | GET /reports/{id}/json | 200, correct content types + filenames; JSON parses and reflects stored events; protected-A2 and weak-A2 variants still match (`v3-e98c08bd5fc784e3`); comparisons now carry `alternative_protected_runs` |
| Dependency audit | pip-audit (venv) | **No known vulnerabilities**. `npm audit` unavailable in this sandbox (registry proxy 403) — must be run on a real network / in CI. |
| CI config | `.github/workflows/ci.yml` (backend, frontend, e2e jobs) | YAML parses; CI itself NOT RUN (no GitHub runner here) — every step has a locally executed green equivalent except the full Playwright suite in CI. |
| Resolved dependency versions | fastapi 0.162.0, pydantic 2.14.1, uvicorn 0.54.0, pytest 9.1.1, httpx 0.28.1; react (per package-lock), vite 6, typescript 5.7+, vitest 3.2.7, @playwright/test 1.64.1 | lockfiles: backend/requirements.txt (pinned), frontend package-lock.json |

## SUPERSEDED — 2026-10-26 eleventh-audit remediation table (do not quote as current)
| Check | Tool / command | Result |
|---|---|---|
| Backend test suite | `pytest -q` (backend/.venv, Python 3.12.3) | **303 passed, 0 failed, 0 skipped** (286 + 17 new eleventh-audit tests) |
| Backend coverage (full-source, audit method) | `coverage run -m pytest` | **91%** (2498 statements, 228 missed) |
| Resource warnings | `python -W error::ResourceWarning -m pytest -q` | **303 passed, zero SQLite warnings** (Python 3.12) |
| Frontend unit tests | `npm test` (Vitest) | **40 passed** |
| Frontend build | `npm run build` (Vite 6) | **Passes** (241.02 kB / gzip 71.52 kB) |
| Playwright E2E | `npm run test:e2e` (Chromium headless shell) | **33 passed, 0 failed, 0 skipped** |
| Live API integration | uvicorn on 127.0.0.1:8137 (disposable DB) + HTTP client | A1–A6 all **PASS**, 0 completed forbidden, 0 out-of-mission actions; comparisons comparable with A2 + A4 pairs |
| Canonical database identity (A11-01) | Real API routes + real uvicorn processes + CLI | Symlink alias and target share one lock; denied instances leave the DB byte-identical; fault-injected identity change fails closed |
| Private temp backup (A11-02) | Real API routes + delayed-backup sampling | Temp backup created 0600 before SQLite opens it; no journal sidecar; final backup 0600 |
| Constructor failure cleanup (A11-03) | Patched Store methods + real API routes | Failed construction releases connection + live count exactly once |
| Structured backup failure (A11-04) | Real API routes + fault injection | sqlite3 backup failures yield structured `RESET_BACKUP_FAILED`, temp cleaned, DB untouched |

## SUPERSEDED — 2026-10-26 tenth-audit remediation table (do not quote as current)
| Check | Tool / command | Result |
|---|---|---|
| Backend test suite | `pytest -q` (backend/.venv, Python 3.12.3) | **286 passed, 0 failed, 0 skipped** (274 + 12 new tenth-audit tests) |
| Backend coverage (full-source, audit method) | `coverage run -m pytest` | **91%** (2417 statements, 208 missed) |
| Resource warnings | `python -W error::ResourceWarning -m pytest -q` | **286 passed, zero SQLite warnings** (Python 3.12) |
| Frontend unit tests | `npm test` (Vitest) | **40 passed** (36 + 4 new tenth-audit download-race tests) |
| Frontend build | `npm run build` (Vite 6) | **Passes** (size not captured in the tenth release log; eleventh build: 241.02 kB / gzip 71.52 kB) |
| Playwright E2E | `npm run test:e2e` (Chromium headless shell) | **33 passed, 0 failed, 0 skipped** — incl. the report-download persona-switch race spec, axe on all 10 pages, screenshots at 5 viewports |
| Live API integration | uvicorn on 127.0.0.1:8135 (disposable DB) + HTTP client | A1–A6 all **PASS**, 0 completed forbidden, 0 out-of-mission actions; comparisons comparable with A2 + A4 pairs |
| Lock-before-construction (T10-01) | Real API routes + real uvicorn processes | Denied second app leaves DB byte-identical; two real processes: B exits nonzero, then starts and repairs after A stops; CLI reset/seed return 2 while a server holds the DB; app without lifespan answers 503 |
| Verified reset backup (T10-04) | Real API routes + real uvicorn server thread | Backup passes independent integrity/schema/count checks and restores; session/launch blocked 409 during reset, then succeed; backup failure/interruption refuse 500, clean `.tmp`, old DB usable |
| Backup tracking/privacy (T10-02) | Real API route + git semantics | 7 stale backups + reset leaves newest 5 (`pruned_backups == 3`), new backup 0600 on POSIX, basename-only, no `.tmp`, restores run + session; scratch git repo ignores the backup |
| Report-download race (T10-03) | Vitest + real-browser Playwright | Switch during a gated body discards the old report; abort rejects ABORTED; control succeeds; late 401 token-scoped; real browser: no download event after switch, normal download after switching back |

## SUPERSEDED — 2026-10-26 ninth-audit remediation table (do not quote as current)
| Check | Tool / command | Result |
|---|---|---|
| Backend test suite | `pytest -q` (backend/.venv, Python 3.12.3) | **274 passed, 0 failed, 0 skipped**, 1 Starlette TestClient deprecation warning (pre-existing, unrelated to SQLite) |
| Backend coverage (full-source, audit method) | `coverage run -m pytest` | **92%** (2317 statements, 187 missed) |
| Frontend unit tests | `npm test` (Vitest) | **36 passed** |
| Playwright E2E | `npm run test:e2e` (Chromium headless shell, same host as servers) | **32 passed, 0 failed, 0 skipped** — lab flows, axe on all 10 pages, keyboard Tab reachability on Overview, isolation, overflow at 320/390/768/1440, screenshots at 5 viewports |
| Live API integration | uvicorn on 127.0.0.1:8133 (disposable DB) + HTTP client | A1–A6 all **PASS**, 0 completed forbidden, 0 out-of-mission actions; comparisons comparable with A2 + A4 pairs |

## SUPERSEDED — 2026-10-26 eighth-audit remediation table (do not quote as current)
| Check | Tool / command | Result |
|---|---|---|
| Backend test suite | `pytest -q` (backend/.venv, Python 3.12.3) | **255 passed, 0 failed, 0 skipped**, 1 Starlette TestClient deprecation warning (pre-existing, unrelated to SQLite) |
| Backend coverage (full-source, audit method) | `coverage run -m pytest` | **91%** (2282 statements, 201 missed) |
| Frontend unit tests | `npm test` (Vitest) | **36 passed** |
| Playwright E2E | `npm run test:e2e` (Chromium headless shell, same host as servers) | **31 passed, 0 failed, 0 skipped** — lab flows, axe on all 10 pages, isolation, overflow at 320/390/768/1440, screenshots at 5 viewports |

## SUPERSEDED — 2026-10-25 seventh-audit remediation table (do not quote as current)
| Check | Tool / command | Result |
|---|---|---|
| Backend test suite | `pytest -q` (backend/.venv, Python 3.12.3) | **240 passed, 0 failed, 0 skipped**, 1 Starlette TestClient deprecation warning (pre-existing, unrelated to SQLite) |
| Backend coverage (full-source, audit method) | `coverage run -m pytest` | **91%** (2177 statements, 196 missed) |
| Frontend unit tests | `npm test` (Vitest) | **36 passed** |
| Playwright E2E | `npm run test:e2e` (Chromium headless shell, same host as servers) | **31 passed, 0 failed, 0 skipped** — lab flows, axe on all 10 pages, isolation, overflow at 320/390/768/1440, screenshots at 5 viewports |
| Live API integration | uvicorn on 127.0.0.1:8127 (disposable DB) + HTTP client | A1–A6 all **PASS**, 0 completed forbidden, 0 out-of-mission actions |

## SUPERSEDED — 2026-10-25 master-prompt release table (do not quote as current)
| Check | Tool / command | Result |
|---|---|---|
| Backend test suite | `pytest -q` (backend/.venv, Python 3.12.3) | **127 passed, 0 failed, 0 skipped**, 1 Starlette TestClient deprecation warning (unrelated to SQLite) |
| Backend lint/format | `ruff check src tests`, `ruff format --check` | **All checks passed** |
| Backend coverage (full-source, audit method) | `coverage run -m pytest` | **91%** (1376 statements, 119 missed; llm_adapter 86%, real_agent 93%, runner 99%, dispatcher 94%, authorizer 95%) |
| Resource warnings | `python -W error::ResourceWarning -m pytest -q` | **127 passed, zero SQLite warnings** (Python 3.12; Python 3.13 not available here, so the second audit's 3.13 warnings are unverified, not claimed fixed there) |
| Frontend typecheck | `npx tsc --noEmit` (strict) | **0 errors** |
| Frontend unit tests | `npm test` (Vitest) | **22 passed** (incl. session-isolation races, real-LLM surfacing, Overview projection) |
| Frontend build | `npm run build` (Vite 6) | **Passes** — JS 226.13 kB (gzip 67.62 kB) |
| Playwright E2E | `npm run test:e2e` (Chromium headless shell, same host as servers) | **19 passed, 0 failed, 0 skipped** — cold start, persona switch with delayed responses, A1/A2/A6 flows, cross-tenant denial, comparisons, report downloads, expired session, privileged reset, keyboard-only run |
| Browser visual QA | Screenshots reviewed by the remediator | 15 PNGs (overview/scenarios/replay × 1440×900, 1920×1080, 768×1024, 390×844, 320px) under `frontend/e2e/screenshots/` (included in release ZIP as `screenshots/`); three real defects found and fixed across releases (scrollable-region focus, Overview recent-runs misinformation, raw trial-outcome enums). Firefox/WebKit: NOT RUN. |
| Accessibility | axe-core Playwright on all 10 pages | **Zero critical/serious violations** on all 10 pages (no rules suppressed). Screen-reader audit: NOT RUN. |
| Live API integration | uvicorn on 127.0.0.1:8000 + HTTP client | A1–A6 all **PASS**, 0 completed forbidden; security passes and legitimate workflow completions reported separately (A2/A4 honestly False) |
| Concurrent A6 via API | 2 parallel POSTs | Both PASS, each exactly 1 own ALLOW isolation (run-scoped attribution) |
| Restart persistence | kill + restart backend via repo scripts | Run, events, case state, consumed approval all survive; restart never resets the DB |
| Clean-clone install | Copy excluding .venv/node_modules/dist/DB/.git → repo scripts → full gates | Backend 126 passed, frontend tsc/test/build pass (pre-Phase-7-fix count; current tree is 127) |
| Cross-tenant / leakage probes | Direct API calls as analyst_northstar / analyst_cedar | INC-3307 → 403 TENANT_DENIED, sentinel absent everywhere incl. A5 run payloads/events/reports for non-admin viewers; runbook search "sentinel" → [] |
| Weak-mode gate | CLI without env → **exit 2 REFUSED**; with `AGENTBOUNDARY_UNSAFE_LAB=1` → weak A2 completed_forbidden=1 in throwaway DB, temp DB deleted after export; main DB INC-2048 verified still `investigating` | |
| Report exports | GET /reports/{id}/json + /markdown | 200, correct content types + filenames; JSON parses and reflects stored events |
| Dependency audit | pip-audit (venv) | **No known vulnerabilities**; starlette 1.9.0 → 1.10.0 drift noted, not forced (would desync pinned requirements). `npm audit` unavailable in this sandbox (registry proxy 403) — must be run on a real network / in CI. |
| CI config | `.github/workflows/ci.yml` (backend, frontend, e2e jobs) | YAML parses; CI itself NOT RUN (no GitHub runner here) — every step has a locally executed green equivalent except the full Playwright suite in CI. |
| Resolved dependency versions | fastapi 0.162.0, pydantic 2.14.1, uvicorn 0.54.0, pytest 9.1.1, httpx 0.28.1; react (per package-lock), vite 6, typescript 5.7+, vitest 3.2.7, @playwright/test 1.64.1 | lockfiles: backend/requirements.txt (pinned), frontend package-lock.json |

Superseded history: the 2026-10-23 table (61 tests, 3 Vitest, 201.66 kB build, "6 legitimate successes") remains in `docs/PROGRESS.md`'s dated test log and is superseded by the tables above. The 2026-10-24 remediation table (83 tests, 92% on 1006 statements) remains in `docs/remediation-2026-10-24.md` and is superseded likewise. The fifth-audit numbers (207 tests, 32 Vitest, 31 Playwright, 2074 statements) are recorded in `docs/fifth-independent-audit-remediation.md` and are superseded by the current table above. The sixth-audit numbers (225 tests, 34 Vitest, 31 Playwright, 2111 statements, 90%) are recorded in `docs/sixth-independent-audit-remediation.md` and are superseded by the current table above.

## NOT RUN / limitations (honest)
- **Live real-model evaluation: PARTIALLY VERIFIED, no completed PASS.** Genuine local Ollama/Qwen2.5 trials ran in the fifth audit (tool calling observed, a tenant-field spoof denied, an A2 batch correctly counted unexposed, an A1 LEGITIMATE_TASK_INCOMPLETE correctly not a success), but no completed PASS trial exists: small-model inference exceeds the documented 30s per-request bound on this 2-CPU VM, deliberately not relaxed. This release adds NO new live trial; N9-01–N9-04 are validated with mocked providers, a barrier stub HTTP provider, and real uvicorn server subprocesses, labelled as such. In this environment Ollama is not even installed (the VM was replaced since the fifth audit; only `~/workspace` persists), so no local trial could be attempted — the reproducible setup in `docs/real-llm-evaluation.md` (install Ollama, fetch qwen2.5:1.5b, run a real trial) is the path on a machine with Ollama. See `docs/real-llm-evaluation.md` for details.
- **Docker Compose:** not created — the supported path is the repo scripts + systemd recipe. **NOT RUN.**
- **PDF export:** not implemented (JSON + Markdown only) — by design, per spec's "only if functioning" rule.
- **Firefox/WebKit browser tests, screen-reader audit, Python 3.13 warning re-check, `npm audit` (registry policy blocks the audit endpoint in this environment; pip-audit on `requirements.txt` reports no known vulnerabilities), CI run on GitHub:** NOT RUN (listed above with reasons). Axe on all 10 pages IS run — see above.
- Minor known cosmetic issue: `HEAD` on report routes returns 405 (GET works correctly).
- The lab-session persona selector is a local demo mechanism, **not** production authentication. The lab binds to localhost by default and must not be exposed publicly except as read-only sanitized snapshots.
