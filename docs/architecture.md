# Architecture

## Modules
- `backend/src/agentboundary/domain/` — tenants, personas, assignments (pure data + types).
- `fixtures/` — deterministic synthetic seed (fixed IDs/timestamps, fixed seed) + reset. ~30+ records across 2 tenants.
- `policy/` — central authorizer. Single entry point; deny by default; returns decision + reason code. Search filtering happens here, before serialization.
- `tools/` — fixed registry of 6 typed tools + dispatcher: schema validation → identity from server session → policy → approval → execute (synthetic DB only) → audit. Attempt is logged before the gate; completion is recorded only after execution.
- `agents/` — scripted adapter (deterministic proposals). Optional real-model adapter interface; NOT RUN without a configured provider.
- `evaluation/` — scenario definitions A1–A6, runner, evaluator (reads DB state), metrics, JSON/Markdown report exporters (schema version `agentboundary.report/1`).
- `api/` — FastAPI routes per API_CONTRACT.md. The API exposes runs/cases/reports — never raw tool invocation, never a weak-mode switch.
- `frontend/` — React TS SPA; untrusted client; all authorization is re-checked server-side on every request.

## Data flow
Session (server-held persona) → run request (scenario ID only, allowlisted) → scripted agent proposes tool calls → dispatcher gates each call → audit events (attempt/policy/completion/disclosure) → evaluator compares expected vs observed DB state → run record → UI/reports.

## Trust boundaries
1. Model/agent output = untrusted proposals. 2. Retrieved telemetry/notes = lower-trust data, labeled with provenance everywhere. 3. UI = untrusted client. 4. Only the dispatcher + policy + approval service + DB are trusted control plane.

## Persistence ownership (E8-01, T10-01, A11-01–A11-04, RC12-01–RC12-02)
- **One owner per database.** `store.canonical_db_path()` resolves a database path to its canonical identity (symlinks resolved, parents resolved, absolutized; `:memory:` passes through) before any lock file is opened or Store constructed. `try_acquire_db_lock()` takes a POSIX `flock` on `<canonical>.applock` and then re-resolves the path: if the identity changed mid-flight it releases the lock and raises (fail closed). The API lifespan holds the lock for the process lifetime and constructs an app-owned Store only after holding it; CLI commands that mutate the main DB take the same lock on the path before constructing anything and refuse (exit 2) while a server holds it. A denied instance leaves the database byte-identical and stays reusable. An existing file with more than one hard link is refused outright (RC12-01) in the lock path, in `Store.__init__` before any connect, and in the CLI — hard links share one inode under different canonical strings, so they can never share one lock; the operator removes the extra link and retries.
- **Exception-safe construction.** `Store.__init__` wraps all post-connect initialization (seed, repair, migration, fixture validation) so a failure closes the opened connection and releases the live-count registration exactly once before re-raising the original error. `close()` is idempotent; a per-test guard asserts the live count returns to baseline.
- **Verified, private reset backups.** `store.verified_backup()` creates the temp file privately (`O_CREAT|O_EXCL`, 0600) before SQLite opens it, copies with the sqlite3 online backup API with the destination journal in memory, then verifies integrity, all 13 schema tables, and runs/events/sessions row counts, re-validates the temp mode, and only then lets the caller atomically rename it into place. Every sqlite3 failure is normalized to `BackupError`; a failed attempt removes its own temp file and sidecars, the reset endpoint removes them again in a `finally`, and the reset is refused with structured `RESET_BACKUP_FAILED` (no filesystem path in the response) with the original database untouched. The endpoint re-validates the final file's mode after rename and removes it if it cannot be made private. Retention keeps the newest 5 backups per DB.
- **Atomic reset.** `Store.reset()` runs the schema rebuild, fixture inserts, and preserved-session insert inside one `BEGIN IMMEDIATE` transaction (RC12-02): any failure before commit rolls the whole destructive reset back, and the endpoint answers structured `RESET_FAILED` (distinct from `RESET_BACKUP_FAILED`) with the previous state intact, the backup retained, the barrier cleared, and idempotency untouched — only a successful reset clears idempotency.
