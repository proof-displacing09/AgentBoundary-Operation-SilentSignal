> **SUPERSEDED — historical record only, do not quote as current.**
> This checklist records the master-prompt release (127 tests, 22
> Vitest, 19 Playwright). The canonical current validation table is
> `docs/validation-and-limitations.md` (twelfth-audit remediation: 315
> tests, 40 Vitest, 33 Playwright, 2528 statements). Figures below
> were true for their release and are preserved unchanged.

# Release Checklist — master-prompt release (2026-10-25)

| Gate | Result |
|---|---|
| Backend pytest | 127 passed, 0 failed |
| Backend ruff check + format | Clean |
| Backend full-source coverage | 91% (1376 stmts, 119 missed) |
| ResourceWarning-as-error run | 127 passed, zero SQLite warnings (Python 3.12) |
| Frontend tsc / Vitest / build | 0 errors / 22 passed / passes (226.13 kB) |
| Playwright E2E | 19 passed (Chromium, same host) |
| Axe (4 pages) | 0 critical/serious |
| Screenshots reviewed | 12 PNGs, 2 defects fixed |
| Live A1–A6 | All PASS, 0 forbidden completions |
| Concurrent A6 (API) | Both PASS, 1 own isolation each |
| Restart persistence | Verified (run/events/state survive) |
| Clean-clone install | Gates green (126 backend at clone time; 127 current) |
| CI config | `.github/workflows/ci.yml` parses; CI run itself NOT RUN |
| pip-audit | No known vulnerabilities |
| npm audit | Unavailable in sandbox (proxy 403) — run on real network / in CI |
| ZIP integrity / secret scan | Verified at packaging (see final report) |
| Publication / deployment | NONE — no push, no remote, no public service |

## Explicitly NOT claimed
Live real-model trials, Firefox/WebKit, axe on 6 pages, screen-reader
audit, Python 3.13 warning re-check, Docker Compose, PDF export,
zero-possible-defects. The release has zero *known* critical/high defects
and zero failing required checks, per the gates above.
