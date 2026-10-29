# UI QA — Playwright, screenshots, accessibility (2026-10-26, tenth-audit release)

## Tenth-audit changes (T10-03 frontend fix)

The one user-visible behavior change is the report-download race
fix: download cancellation now tracks through `blob()` and the
session token is rechecked immediately before the browser is handed
the file, so a persona switch mid-download discards the old tenant's
report instead of completing it. Verified three ways: 4 new Vitest
tests (switch-during-body, abort-during-body, control success, late
401), a new real-browser Playwright spec with a fetch-level gate
(headers resolve, body held, switch to Cedar, release — no download
event, no success toast, Cedar stays selected; switch back to
Northstar and the same run downloads normally), and failing-first
proof for both (old code downloads the stale report in both
harnesses). Object URLs are now revoked on a short deferral so the
browser captures the file first. Playwright 33/33 (32 + the new race
spec); axe 0 critical/serious on all 10 pages still holds. The 15
release screenshots were recaptured and re-verified: all widths equal
their viewport labels, Overview 320px + Scenarios 390px viewed (no
overflow; the 320px persona-select truncation is the same native
in-control truncation present in prior releases, full value on open).

## Ninth-audit changes (N9-06)

No application UI code changed for N9-01–N9-04 (all backend +
test-harness); the visible verification is therefore regression
evidence, not redesign. Playwright 32/32 (31 + one new keyboard test:
Tab from the top of Overview reaches interactive controls — persona
selector, nav links, buttons — and never lands on a non-interactive
element). Axe 0 critical/serious on all 10 pages still holds. The 15
release screenshots are byte-identical to the eighth release (the E2E
seed is deterministic) and were re-verified: Overview 320px + Scenarios
390px viewed (no overflow, Denied wording intact, no clipped labels
beyond the native 320px select truncation also present in prior
releases). The Comparison page was inspected one-off with two live
matched pairs (A2 + A4): 1440px clean; fresh-context 320px clean
(sidebar starts collapsed, both pairs render, no clipping). An initial
mid-session-resize capture showed the nav drawer overlapping content;
traced to sidebar state persisting across a viewport resize inside one
browser session, not a fresh-load defect (an open drawer overlaying
content is its designed behavior; it starts collapsed on mobile), so
no code change was made — recorded here so the observation is not
mistaken for an ignored defect. Frontend error surfacing re-verified
in code: 429/409 messages (capacity, reset refusal, idempotency reuse)
surface verbatim via ApiError, 401 routes back to persona selection
with in-flight requests aborted, and reset 409s keep their
active-run-count message.

# UI QA — Playwright, screenshots, accessibility (2026-10-26, eighth-audit release)

## Eighth-audit changes (E8-02)

Comparison PairCards now show "Also eligible for this pair
(not double-counted)" with the alternative protected run ids from the
API's `alternative_protected_runs` field, and pair keys include the
protected run id (one scenario can now yield several pairs, one per
weak export — a scenario-only key would collide). No layout or styling
changes otherwise. Playwright 31/31 and axe 0 critical/serious on all
10 pages still hold; overflow spec green at 320/390/768/1440. 15
screenshots recaptured and inspected (Overview 320px + 1440px viewed:
no overflow, Denied wording intact, no clipping). Vitest suite still
36; build output unchanged (240.50 kB / gzip 71.39 kB).

# UI QA — Playwright, screenshots, accessibility (2026-10-25, seventh-audit release)

## Seventh-audit changes (S7-01/S7-05)

Overview's Denied tile now reads "All tool calls denied by policy or
validation" (it counts every gateway denial, not only blocked attacks);
the post-exposure tile is renamed "Post-exposure forbidden proposals"
(proposals, not proof of blocking) with new "Targeted forbidden calls
blocked" and "Out-of-mission runs" tiles; Replay, Reports, Investigation
and Comparison show out-of-mission actions where present, and the
duplicate legacy-alias completion lines were removed (the authoritative
headline is shown once). The new trial outcome OUT_OF_MISSION is
labeled "Out of mission (clean-control deviation)". Playwright 31/31
and axe 0 critical/serious on all 10 pages still hold; overflow spec
green at 320/390/768/1440. 15 screenshots recaptured and inspected
(Overview 320px + 1440px viewed: new Denied wording, no clipping or
overflow). New Vitest tests: S7-05 label tests + OUT_OF_MISSION label
(suite now 36).

# UI QA — Playwright, screenshots, accessibility (2026-10-25, sixth-audit release)

## Sixth-audit changes (SI-06)

Scenario Studio's unconfigured real-model copy now offers both paths
("local Ollama model (no API key required)" and "remote provider with
a server-side API key, never entered here"); Lab Settings setup text
likewise names the keyless local option. Playwright 31/31 and axe 0
critical/serious on all 10 pages still hold; overflow spec green at
320/390/768/1440. 15 screenshots recaptured and inspected (the
Scenarios/LabSettings copy changes are visible, no clipping or
overflow). New Vitest tests: SI-06 keyless-Ollama copy tests (suite
now 34).

# UI QA — Playwright, screenshots, accessibility (2026-10-25, fifth-audit release)

## Fifth-audit changes (FA-08)

Overview now renders 6 primary KPI cards (Total runs, Attempted
unauthorized, Denied, Completed forbidden, Legitimate workflow
completions, Tenant leaks) for both backend-total and mode-filtered
views; all secondary metrics (scenarios run, security invariant
passes, model-origin counts, trial outcomes, legacy aliases,
inconclusive) moved into a `<details>` "Research metrics (full
detail…)" disclosure. Replay renders a "Causal timeline (model
responses, not dispatcher order)" card for real runs (exposure state
+ confirmed turn, per-batch proposed tools with nested observation
delivery state/coverage, draft grounding line); scripted runs get a
note that their proposals are predetermined. Playwright 31/31 and axe
0 critical/serious on all 10 pages still hold; overflow spec green
at 320/390/768/1440. 15 screenshots recaptured (widths == viewports)
and inspected: the 320px Overview shows the 6 KPI cards, the
collapsed research disclosure, and readable sections with no
clipping; the Replay causal card was visually verified against a
live-API real run (FA-01 batch shape). New Vitest test: FA-08
Overview primary-KPI + disclosure test (suite now 32).

# UI QA — Playwright, screenshots, accessibility (2026-10-25, fourth-audit release)

## Playwright E2E (31 passed, 0 failed, 0 skipped)

Fourth-audit addition: `frontend/e2e/overflow.spec.ts` (4) — all 10 pages
× 320 / 390×844 / 768×1024 / 1440×900 with `scrollWidth <= clientWidth + 1`
and no element past `innerWidth + 1` outside a deliberately scrollable
container. This spec caught the FR-06 defect (mobile screenshots were
537px wide at 320/390 viewports) and now guards the fix. Spec counts:
`lab.spec.ts` (11), `a11y.spec.ts` (10 — all pages), `isolation.spec.ts`
(1), `screenshots.spec.ts` (5), `overflow.spec.ts` (4).

Fourth-audit demo-DB note: the demo DB was migrated once when the new
code first opened it (events table gains the `origin` column; hash
`302dcf58…01aa63` → `4496a4b3…ecf7` at migration, then `ad646b36…3a40`
after one verification lab session added a sessions row). Fixture rows,
runs (0), events (0) and INC-2048 (`investigating`) are unchanged; a
full backend suite run against a copy of the demo DB left its hash
unchanged.

## Playwright E2E — third-audit release (27 passed, 0 failed, 0 skipped)
Command: `cd frontend && npm run test:e2e` (Chromium headless shell 156).
Since the R-06 fix, Playwright starts its OWN backend/frontend on
run-specific free ports with a unique temp DB (`reuseExistingServer:
false`, `AGENTBOUNDARY_DB_PATH` scoped to the test subprocess) — it never
touches the demo backend or demo DB. Specs: `frontend/e2e/lab.spec.ts`
(11), `frontend/e2e/a11y.spec.ts` (10 — all pages), `frontend/e2e/
isolation.spec.ts` (1), `frontend/e2e/screenshots.spec.ts` (5). All use
the real backend + real frontend with event-based waits. Covered: cold
start after privileged reset, persona switch with a delayed `/overview`
response (no stale Northstar data mid-flight or after reload), A1 to PASS
with real Replay events, A2 leaving INC-2048 `investigating` (page state,
not badge text), A6 APPROVAL_REQUIRED → ALLOW → APPROVAL_USED order,
cross-tenant denial with no case body and no sentinel, honest "Not
comparable" comparisons, report JSON / Markdown downloads parsed for real
content, expired-session handling, analyst-vs-commander reset,
keyboard-only A1 run (Tab, visible focus, Enter), and E2E isolation
(own temp DB/ports; resets stay inside it).

Demo-DB preservation proof: full suite run with the demo DB present —
demo DB SHA-256 identical before and after
(`302dcf584074beed2c8d3038b2428bf0ede88e5efac06c61b820f348cb01aa63`),
0 runs / 0 events / 2 sessions throughout. Backend regression
`test_e2e_isolation_leaves_demo_copy_untouched` additionally proves the
forced-failure path (occupied port → loud failure, demo copy untouched).

## Screenshots (15, all opened and reviewed)
Under `frontend/e2e/screenshots/`: overview / scenarios / replay ×
1440×900, 1920×1080, 768×1024, 390×844, 320px. Included in this release's
ZIP under `screenshots/` as real captures (not renders). Fourth-audit
recapture: every PNG width now equals its viewport (320, 390, 768, 1440,
1920) — the third-release mobile shots were all 537px wide because of
the FR-06 overflow, and the "no overflow" claim from that release was
wrong; the overflow spec above now enforces it. Desktop is clean
and hierarchical; tablet collapses to a top bar + 2-column grids; mobile
stacks to one column with no clipping, overlap, horizontal overflow, or
nav collisions at 320px. Tool-call IDs wrap mid-token on narrow screens
(acceptable for mono IDs). The shell badge now reads LOCAL SYNTHETIC LAB
(FR-11); per-run badges still correctly say SCRIPTED LAB SIMULATION.

## Defects found by inspection and fixed
1. Axe serious `scrollable-region-focusable`: JSON `<pre>` blocks were not
   keyboard-focusable → added `tabIndex={0}` + `aria-label` to all four
   (Settings, Evidence detail, Policy approval rules, Replay event JSON).
   Axe re-run: 4/4 pass.
2. Overview recent-runs misinformation: the `/overview` `recent_runs`
   projection lacks adapter/identity fields, so the page showed
   "Operator: not recorded / Adapter: unknown" and the Scripted filter
   emptied the list → Overview now joins each projection to its full
   `/runs` record; `RunIdentities` renders a neutral note only when a
   payload carries no identity fields at all. Covered by a new Vitest test
   and Playwright assertions; verified in re-captured screenshots.
3. Raw trial-outcome enums in the UI (third-audit review): Overview KPI
   cards showed `Trial outcome: SCRIPTED_BOUNDARY_HELD` and
   `TrialOutcomeBadge` rendered the raw enum → both now use the
   plain-language `trialOutcomeLabel()` mapping; verified in re-captured
   320px and desktop screenshots ("Trial: Scripted boundary held").

## Accessibility
axe-core Playwright on overview, scenarios, settings, replay-with-real-run:
**zero critical/serious violations**, no rules suppressed. Keyboard pass:
Tab navigation reaches scenario run buttons with visible focus; Enter runs
A1. `prefers-reduced-motion` is respected by the design tokens. NOT RUN:
axe on the other 6 pages, screen-reader audit, Firefox/WebKit.

## Known UI limitations
- The stock Chromium binary lives only in this VM's Playwright cache; a clean
  checkout elsewhere needs `npx playwright install chromium` (or the
  documented GCS workaround).
- No weak-mode control exists anywhere (grep-verified); the only weak-mode
  mentions are explanatory "no weak-mode control" copy.
