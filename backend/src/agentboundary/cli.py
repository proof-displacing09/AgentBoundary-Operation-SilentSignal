"""CLI: seed | reset | run --scenario A1 | run-all | run-weak --scenario A2|A4 --out file | run-real --scenario A2

Weak mode: REQUIRES env AGENTBOUNDARY_UNSAFE_LAB=1, runs on a SEPARATE temp DB,
named omissions only. There is deliberately no API equivalent.

Real-LLM mode: run-real requires a configured provider — either a remote
provider (server-side env AGENTBOUNDARY_LLM_API_KEY + optional BASE_URL/
MODEL) or a free local Ollama model (AGENTBOUNDARY_LLM_LOCAL_OLLAMA=1 with
a loopback BASE_URL, no key needed). Without either, the command refuses
cleanly with exit 2 and a "not configured" message. The key is never
printed.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .agents.llm_adapter import LLMError, llm_configured
from .config import UNSAFE_ENV, db_path
from .evaluation.runner import Runner
from .evaluation.scenarios import SCENARIOS
from .store import (
    BackupError,
    Store,
    fsync_dir,
    prune_backups,
    try_acquire_db_lock,
    verified_backup,
    verify_store_matches_lock,
)


def _acquire_main_store():
    """T10-01: main-DB exclusivity for mutating CLI commands. The
    cross-process lock (sidecar flock + database-inode flock, C5)
    is taken before any Store is constructed, so a CLI command can
    never seed, repair, or migrate a database a server already owns.
    Returns (store, lock), or
    (None, None) with a refusal message when the lock is held — the
    caller then returns exit code 2 (main() returns ints; only the
    __main__ entry point turns that into a process exit code).
    Callers must close the store, then the lock, in a finally block
    (see _release_main_store)."""
    path = db_path()
    lock = None
    if path and path != ":memory:":
        try:
            lock = try_acquire_db_lock(path)
        except RuntimeError as exc:
            # A11-01: the database path identity changed mid-flight
            # (e.g. a symlink swap during lock acquisition). RC12-01:
            # the file is multiply hardlinked, or its identity changed
            # after locking. Fail closed with the same exit-2 refusal,
            # never construct a Store on a file the lock does not cover.
            print(f"Refused: {exc}", file=sys.stderr)
            return None, None
        if lock is None:
            print(
                f"Refused: another AgentBoundary process (server) "
                f"currently holds {path}. Stop it first, then retry.",
                file=sys.stderr,
            )
            return None, None
        constructed = None
        try:
            constructed = Store(path)
            # C6: a symlink swap between lock acquisition and Store
            # construction used to leave a store on a file the lock
            # does not cover. Refuse closed on mismatch.
            verify_store_matches_lock(constructed, lock)
            store = constructed
        except RuntimeError as exc:
            # RC12-01: a hard link created between lock acquisition
            # and Store construction — release the lock we just took
            # and refuse, rather than operating on a file the lock
            # does not exclusively cover. Non-RuntimeError failures
            # (e.g. disk errors) still propagate as before. A store
            # constructed before the refusal (C6 mismatch) is closed
            # too; a failed construction leaves nothing to close.
            if constructed is not None:
                constructed.close()
            lock.close()
            print(f"Refused: {exc}", file=sys.stderr)
            return None, None
        return store, lock
    return Store(path), None


def _release_main_store(store, lock):
    try:
        store.close()
    finally:
        if lock is not None:
            lock.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="agentboundary")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    sub.add_parser("reset")
    p_run = sub.add_parser("run")
    p_run.add_argument("--scenario", required=True)
    sub.add_parser("run-all")
    p_weak = sub.add_parser("run-weak")
    p_weak.add_argument("--scenario", required=True)
    p_weak.add_argument("--out", default=None)
    p_real = sub.add_parser("run-real")
    p_real.add_argument("--scenario", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "seed":
        s, lock = _acquire_main_store()
        if s is None:
            return 2
        try:
            n = s.record_count()
            print(f"Seeded (or already present): {n} records at {s.path}")
            return 0
        finally:
            _release_main_store(s, lock)
    if args.cmd == "reset":
        # E8-01/T10-01: the CLI reset is the same destructive operation
        # as the API reset, so it takes the same cross-process lock —
        # and, since T10-01, it takes it BEFORE constructing the Store.
        # If a server holds this database, the CLI refuses (exit 2)
        # without having seeded or repaired anything — stop the server
        # (or point the CLI at a different database) and retry.
        s, lock = _acquire_main_store()
        if s is None:
            return 2
        try:
            # S5: mirror the API reset -- a verified pre-reset backup
            # first (0600, retention newest 5). A backup failure
            # refuses with exit 2 and the DB untouched. :memory:
            # databases have no file to back up and skip this step.
            backup_path = None
            pruned = 0
            if s.path != ":memory:":
                import sqlite3
                import stat
                from datetime import UTC, datetime

                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
                backup_path = f"{s.path}.pre-reset-{stamp}.bak"
                tmp_path = backup_path + ".tmp"
                try:
                    verified_backup(s.path, tmp_path)
                    os.replace(tmp_path, backup_path)
                    if (
                        os.name == "posix"
                        and stat.S_IMODE(os.stat(backup_path).st_mode) != 0o600
                    ):
                        try:
                            os.chmod(backup_path, 0o600)
                        except OSError:
                            pass
                        if stat.S_IMODE(os.stat(backup_path).st_mode) != 0o600:
                            try:
                                os.unlink(backup_path)
                            except OSError:
                                pass
                            raise BackupError("final backup could not be made private")
                    fsync_dir(os.path.dirname(backup_path) or ".")
                    pruned = prune_backups(s.path, keep=5)
                except (BackupError, OSError, sqlite3.Error) as exc:
                    for suffix in ("", "-wal", "-shm", "-journal"):
                        try:
                            os.unlink(tmp_path + suffix)
                        except OSError:
                            pass
                    print(
                        f"Refused: pre-reset backup failed: {exc}",
                        file=sys.stderr,
                    )
                    return 2
            n = s.reset()
            if backup_path is not None:
                print(
                    f"Reset complete: {n} records "
                    f"(backup: {os.path.basename(backup_path)}, pruned: {pruned})"
                )
            else:
                print(f"Reset complete: {n} records")
            return 0
        finally:
            _release_main_store(s, lock)
    if args.cmd == "run":
        if args.scenario not in SCENARIOS:
            print("Unknown scenario", file=sys.stderr)
            return 2
        s, lock = _acquire_main_store()
        if s is None:
            return 2
        try:
            run = Runner(s, weak=False).run(args.scenario, operator_persona_id="cli")
            print(json.dumps(run, indent=2))
            return 0
        finally:
            _release_main_store(s, lock)
    if args.cmd == "run-all":
        s, lock = _acquire_main_store()
        if s is None:
            return 2
        try:
            runner = Runner(s, weak=False)
            out = [runner.run(sid, operator_persona_id="cli") for sid in SCENARIOS]
            print(
                json.dumps(
                    [
                        {
                            "id": r["id"],
                            "scenario_id": r["scenario_id"],
                            "verdict": r["verdict"],
                            "metrics": r["metrics"],
                        }
                        for r in out
                    ],
                    indent=2,
                )
            )
            return 0
        finally:
            _release_main_store(s, lock)
    if args.cmd == "run-real":
        if args.scenario not in SCENARIOS:
            print("Unknown scenario", file=sys.stderr)
            return 2
        if not llm_configured():
            print(
                "NOT CONFIGURED: real LLM evaluation requires server-side env "
                "AGENTBOUNDARY_LLM_API_KEY (plus optional AGENTBOUNDARY_LLM_BASE_URL / "
                "AGENTBOUNDARY_LLM_MODEL). See backend/.env.example. No provider call was made.",
                file=sys.stderr,
            )
            return 2
        s, lock = _acquire_main_store()
        if s is None:
            return 2
        try:
            run = Runner(s, weak=False, adapter="real_llm").run(
                args.scenario, operator_persona_id="cli"
            )
            print(json.dumps(run, indent=2))
            return 0
        except LLMError as e:
            print(f"Real LLM run failed: {e.error_class}", file=sys.stderr)
            return 1
        finally:
            _release_main_store(s, lock)
    if args.cmd == "run-weak":
        if os.environ.get(UNSAFE_ENV) != "1":
            print(
                f"REFUSED: run-weak requires env {UNSAFE_ENV}=1 (explicit unsafe-lab opt-in).",
                file=sys.stderr,
            )
            return 2
        if args.scenario not in ("A2", "A4"):
            print("run-weak supports only A2 and A4.", file=sys.stderr)
            return 2
        tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 - path must outlive the handle; Store opens it separately
            prefix="agentboundary-weak-", suffix=".db", delete=False
        )
        tmp.close()
        s = Store(tmp.name)  # separate throwaway DB, seeded with the same fixtures
        try:
            run = Runner(s, weak=True).run(args.scenario, operator_persona_id="cli")
            payload = {"report_schema_version": "2.0", "mode": "weak", "run": run}
            text = json.dumps(payload, indent=2)
            if args.out:
                Path(args.out).write_text(text)
                print(
                    f"Weak run exported to {args.out}: scenario={run['scenario_id']} verdict={run['verdict']} omissions={run.get('omissions')}"
                )
            else:
                print(text)
            return 0
        finally:
            # Close the store, then delete the throwaway DB file itself.
            s.close()
            try:
                os.unlink(tmp.name)
            except FileNotFoundError:
                pass
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
