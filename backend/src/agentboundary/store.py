import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import FIXTURE_VERSION
from .domain.personas import PERSONAS, TENANTS
from .fixtures.data import ALERTS, APPROVALS, ASSETS, CASES, RUNBOOKS, TIMELINE

SCHEMA = """
DROP TABLE IF EXISTS tenants; DROP TABLE IF EXISTS personas; DROP TABLE IF EXISTS cases;
DROP TABLE IF EXISTS alerts; DROP TABLE IF EXISTS timeline_events; DROP TABLE IF EXISTS runbooks;
DROP TABLE IF EXISTS approvals; DROP TABLE IF EXISTS assets; DROP TABLE IF EXISTS drafts;
DROP TABLE IF EXISTS isolations; DROP TABLE IF EXISTS runs; DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS sessions;
CREATE TABLE tenants(id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE personas(id TEXT PRIMARY KEY, role TEXT, tenants TEXT, can_approve TEXT);
CREATE TABLE cases(id TEXT PRIMARY KEY, tenant_id TEXT, title TEXT, status TEXT, priority TEXT, host TEXT, summary TEXT);
CREATE TABLE alerts(id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, title TEXT, severity TEXT, timestamp TEXT);
CREATE TABLE timeline_events(id TEXT PRIMARY KEY, case_id TEXT, tenant_id TEXT, timestamp TEXT, source_type TEXT, classification TEXT, actor TEXT, trust_label TEXT, content TEXT);
CREATE TABLE runbooks(id TEXT PRIMARY KEY, tenant_scope TEXT, category TEXT, trust_label TEXT, title TEXT, content TEXT);
CREATE TABLE approvals(id TEXT PRIMARY KEY, action TEXT, case_id TEXT, asset_id TEXT, tenant_id TEXT, requester_id TEXT, approver_id TEXT, expires_at TEXT, used INTEGER DEFAULT 0, new_status TEXT);
CREATE TABLE assets(id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT);
CREATE TABLE drafts(id TEXT PRIMARY KEY, case_id TEXT, tenant_id TEXT, summary TEXT, recommended_actions TEXT, created_by TEXT, run_id TEXT, simulated INTEGER DEFAULT 1);
CREATE TABLE isolations(id TEXT PRIMARY KEY, asset_id TEXT, case_id TEXT, tenant_id TEXT, reason TEXT, created_by TEXT, run_id TEXT, simulated INTEGER DEFAULT 1);
CREATE TABLE runs(id TEXT PRIMARY KEY, scenario_id TEXT, status TEXT, verdict TEXT, adapter TEXT, mode TEXT, started_at TEXT, finished_at TEXT, metrics TEXT, actor_id TEXT, tenant_id TEXT, omissions TEXT DEFAULT '[]', operator_persona_id TEXT, simulated_actor_id TEXT, control_actor_id TEXT, fixture_version TEXT, fixture_variant TEXT);
CREATE TABLE events(event_id TEXT PRIMARY KEY, run_id TEXT, scenario_id TEXT, seq INTEGER, timestamp TEXT, actor_id TEXT, tenant_id TEXT, adapter TEXT, tool TEXT, args_sanitized TEXT, source_provenance TEXT, trust_label TEXT, decision TEXT, reason_code TEXT, approval_status TEXT, attempted INTEGER, completed INTEGER, disclosed_restricted INTEGER, before_state TEXT, after_state TEXT, detail TEXT, tool_call_id TEXT, evidence_scope TEXT DEFAULT 'primary', origin TEXT DEFAULT 'agent');
CREATE TABLE sessions(token TEXT PRIMARY KEY, persona_id TEXT, expires_at TEXT);
"""


# CREATE statements extracted from SCHEMA (no DROPs): used to repair a
# partially-seeded database without destroying existing rows.
_SCHEMA_CREATES = [
    s.strip() for s in SCHEMA.splitlines() if s.strip().startswith("CREATE TABLE")
]


class BackupError(Exception):
    """Raised when a verified database backup cannot be produced or
    fails verification (T10-04). The caller must refuse the destructive
    operation it was backing up for; nothing may be deleted."""


# Tables that must exist in a verified backup, and tables whose row
# counts must match the source at snapshot time (T10-04).
_BACKUP_REQUIRED_TABLES = (
    "tenants",
    "personas",
    "cases",
    "alerts",
    "timeline_events",
    "runbooks",
    "approvals",
    "assets",
    "drafts",
    "isolations",
    "runs",
    "events",
    "sessions",
)
# S1 (pentest follow-up): count EVERY required table, not just
# runs/events/sessions -- a backup missing fixture-table rows used to
# pass verification. The backup API copies the whole DB, so all counts
# must match; the reset barrier guarantees no concurrent writers.
_BACKUP_COUNTED_TABLES = _BACKUP_REQUIRED_TABLES


def _assert_private(path):
    """A11-02: on POSIX, a backup file must be mode 0600 exactly —
    readable only by its owner. Raises BackupError otherwise. On
    non-POSIX platforms file modes do not carry the same meaning, so
    enforcement is best-effort only (documented limitation); the
    creation call below still requests 0600 where the OS honors it."""
    import os
    import stat

    if os.name != "posix":
        return
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode != 0o600:
        raise BackupError(f"backup file is not private (mode {oct(mode)})")


def _create_private_tmp(tmp_path):
    """A11-02: create the backup temp file privately BEFORE SQLite
    ever opens it. SQLite creates files with the process umask (0644
    under umask 022), which left the temp backup — including the live
    sessions table — world-readable during backup/verification in
    T10-04. Creating with O_EXCL|0600 first closes that window: the
    file is private from its first byte, and SQLite opening an
    existing file preserves its mode. A stale temp from a killed run
    is ours by construction (callers only ever pass
    <db>.pre-reset-*.bak.tmp), so it is removed first, with its
    journal sidecars."""
    import os

    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            if os.path.exists(tmp_path + suffix):
                os.unlink(tmp_path + suffix)
        except OSError:
            pass
    try:
        fd = os.open(tmp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as exc:
        raise BackupError(f"cannot create private backup temp file: {exc}") from exc
    os.close(fd)
    try:
        _assert_private(tmp_path)
    except BackupError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _cleanup_tmp(tmp_path):
    """Best-effort removal of a backup temp file and its journal
    sidecars. Only ever called on paths the caller constructed as
    <db>.pre-reset-*.bak.tmp — never on a user database."""
    import os

    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            if os.path.exists(tmp_path + suffix):
                os.unlink(tmp_path + suffix)
        except OSError:
            pass


def verified_backup(src_path, tmp_path):
    """Produce a verified SQLite backup at tmp_path (T10-04, A11-02,
    A11-04).

    Uses the supported sqlite3 online backup API — not a raw file copy,
    which is not a guaranteed consistent snapshot of an open database
    (especially under alternate journal modes). Verifies, before
    returning: PRAGMA integrity_check == 'ok', every required table
    present, and row counts identical to the source at snapshot time
    for EVERY required table (S1). A11-02: the temp file is created 0600
    before SQLite opens it, and its mode is re-validated after
    verification, so it is never world-readable at any stage. A11-04:
    EVERY sqlite3 failure — source open, source reads, destination
    open, backup, integrity check, schema and count verification —
    is normalized to BackupError here, and a failed attempt removes
    its own temp file; the caller still cleans up as a second layer
    and refuses the operation. The caller atomically renames tmp_path
    into its final location only after this returns.
    """
    import os
    import sqlite3

    # Never let a missing source silently become a fresh empty file.
    if not os.path.exists(src_path):
        raise BackupError(f"backup source does not exist: {src_path}")
    _create_private_tmp(tmp_path)
    src_conn = None
    dest_conn = None
    ok = False
    try:
        try:
            # S3: open read-only-without-create. The old plain connect
            # recreated a source deleted between the exists() check
            # and the connect as an empty file (the count query then
            # failed into BackupError -- fail-closed for the backup,
            # but a stray empty file was left at the source path).
            import urllib.parse

            src_uri = "file:" + urllib.parse.quote(src_path) + "?mode=rw"
            src_conn = sqlite3.connect(src_uri, uri=True)
            counts = {}
            for table in _BACKUP_COUNTED_TABLES:
                counts[table] = src_conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            dest_conn = sqlite3.connect(tmp_path)
            # A11-02: keep the destination's rollback journal in
            # memory, so no transient journal sidecar (created with
            # umask permissions) ever carries backup pages on disk;
            # the temp file itself is already private (0600).
            dest_conn.execute("PRAGMA journal_mode=MEMORY")
            src_conn.backup(dest_conn)
            row = dest_conn.execute("PRAGMA integrity_check").fetchone()
            if row is None or row[0] != "ok":
                raise BackupError(f"integrity_check failed: {row}")
            tables = {
                r[0]
                for r in dest_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            missing = [t for t in _BACKUP_REQUIRED_TABLES if t not in tables]
            if missing:
                raise BackupError(f"backup missing tables: {missing}")
            for table, expected in counts.items():
                got = dest_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if got != expected:
                    raise BackupError(
                        f"backup row count mismatch for {table}: "
                        f"expected {expected}, got {got}"
                    )
            # S2: fsync the temp file before trusting it -- os.replace
            # is atomic for visibility, not durable across power loss.
            # A failure here fails the backup (temp cleaned up below).
            try:
                fd = os.open(tmp_path, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError as exc:
                raise BackupError(f"backup temp fsync failed: {exc}") from exc
        except sqlite3.Error as exc:
            raise BackupError(f"sqlite backup failed: {exc}") from exc
        # Mode re-validated after backup + verification: SQLite must
        # not have relaxed the private creation mode at any stage.
        _assert_private(tmp_path)
        ok = True
    finally:
        for conn in (dest_conn, src_conn):
            try:
                if conn is not None:
                    conn.close()
            except Exception:  # noqa: BLE001, S110 - teardown is best-effort
                pass
        if not ok:
            _cleanup_tmp(tmp_path)


def fsync_dir(dir_path):
    """S2: best-effort durability for a directory entry (used after
    renaming a verified backup into place). The file itself is fsynced
    in verified_backup; a failed directory fsync must not turn a good
    backup into a refused reset, so errors are ignored. No-op off
    POSIX."""
    import os

    if os.name != "posix":
        return
    try:
        fd = os.open(dir_path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def prune_backups(db_path, keep=5):
    """Retention policy for reset backups (T10-02): keep the newest
    `keep` `<db>.pre-reset-*.bak` files, delete older ones. Never
    deletes the newest backup, and never prunes when there are `keep`
    or fewer — so a lab with a single backup keeps it. Returns the
    number of files deleted. Failures to delete one file are ignored
    (a stale backup is harmless; a failed reset is not).

    C2/C3 (pentest follow-up): candidates sort by FILENAME, not
    mtime -- the stamps are fixed-width UTC (%Y%m%dT%H%M%S%f), so
    lexicographic order IS newest-last order, immune to clock steps
    and mtime tampering (and it removes the glob-to-getmtime race,
    S4, since no stat call is needed at all). The DB path is
    glob-escaped: a filename containing *?[] must not match a foreign
    database's backups."""
    import glob
    import os

    candidates = sorted(glob.glob(glob.escape(db_path) + ".pre-reset-*.bak"))
    if len(candidates) <= keep:
        return 0
    deleted = 0
    for old in candidates[:-keep]:
        try:
            os.unlink(old)
            deleted += 1
        except OSError:
            pass
    return deleted


def _realpath(path):
    """Indirection over os.path.realpath (A11-01): the identity-change
    guard below re-resolves the path after locking, and tests
    fault-inject a mid-flight alias swap through this name — a real
    symlink swap cannot be timed deterministically."""
    import os

    return os.path.realpath(path)


class HardlinkedDatabaseError(RuntimeError):
    """RC12-01: an existing database file with more than one hard link
    is refused outright. Two hard links are distinct pathname strings
    for ONE inode, so canonicalization — which resolves symlinks, not
    hard links — would give them different lock files and two owners
    for one SQLite database. Refusing is the fail-closed choice for
    this local lab: unlink the extra link(s) so the file has exactly
    one link, then retry. A subclass of RuntimeError so the API
    lifespan (which propagates startup failures) and the CLI (which
    turns RuntimeError into a clean exit-2 refusal) handle it with no
    new branches."""


def _db_file_identity(path):
    """(st_dev, st_ino, st_nlink) for an existing file, else None.

    Indirection point for fault injection: tests replace this name to
    simulate an identity change between lock acquisition and Store
    construction, which cannot be timed deterministically in real
    life. Follows symlinks; callers pass canonical paths, so the
    target is what is measured."""
    import os

    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino, st.st_nlink)


def _check_single_link(path):
    """RC12-01: refuse an existing database file with st_nlink > 1.

    Returns the observed identity (or None for a not-yet-created
    database) so callers need not stat twice. A not-yet-created
    database has no identity yet and proceeds; the post-lock
    revalidation in try_acquire_db_lock catches anything created or
    linked in the meantime."""
    identity = _db_file_identity(path)
    if identity is not None and identity[2] > 1:
        raise HardlinkedDatabaseError(
            f"Database file {path} has {identity[2]} hard links; "
            "multiply-hardlinked database files are not supported "
            "because two pathnames would name one SQLite database "
            "under different locks. Remove the extra link(s) so the "
            "file has exactly one link, then retry."
        )
    return identity


def canonical_db_path(path):
    """Canonical identity of a database file (A11-01).

    Resolves symlink aliases to their target, resolves symlinked
    parent directories for not-yet-created databases, and absolutizes
    — so `friendly.db` (a symlink to `actual.db`) and `actual.db`
    are the SAME identity, and therefore the same lock, the same
    Store, and the same backup location, in every owner-acquisition
    path (API lifespan, CLI, Store itself). ":memory:" passes through
    unchanged: it has no file identity. Two distinct databases that
    merely share a filename in different directories stay distinct
    (their canonical parents differ). A path whose parent does not
    exist yet resolves as far as the filesystem allows; Store creates
    that parent before opening, so the identity is stable by open
    time. RC12-01, stated honestly: canonicalization resolves
    symlinks, NOT hard links — two hard links share one inode but
    have different realpaths, so pathname identity alone can never
    give them one lock. That case is therefore refused outright
    (st_nlink > 1, see _check_single_link) instead of silently
    allowed; the refusal is retained even though the inode lock
    would cover a hardlinked file, as defense in depth against
    aliasing confusion. C5, FIXED: renaming the DB file or its lock
    file AFTER acquisition no longer yields a second holder, because
    ownership is now also held as an exclusive flock on an open
    description of the database file itself (see DatabaseLock):
    renames change pathnames, not inodes, so a second process
    opening the same inode through any pathname is refused. The
    guarantee is per-inode: replacing the file at the path with a
    DIFFERENT inode creates a different database identity. Residual
    risk: an attacker with write access to the directory could swap
    a symlink in the microscopic window between resolution and open;
    the post-lock revalidation in try_acquire_db_lock closes the
    lock-acquisition half of that window, and
    verify_store_matches_lock closes the lock-to-construction half
    (C6, path + inode). Directory-write access is outside this
    lab's local single-operator threat model; see the report for
    the remaining theoretical construction-window note.
    """
    if str(path) == ":memory:":
        return ":memory:"
    return _realpath(path)


def db_lock_path(db_path):
    """Sidecar lock file for one database file (E8-01, A11-01: the
    lock is derived from the CANONICAL path, so aliases share it)."""
    return f"{canonical_db_path(db_path)}.applock"


class DatabaseLock:
    """Cross-process database ownership: TWO flock locks, held together.

    C5 fix: the historical sidecar flock alone is pathname-derived,
    so renaming the ``.applock`` entry (C5-A) or the database file
    itself (C5-B) used to admit a second owner for the same SQLite
    database. This holder therefore carries BOTH locks for the
    process lifetime:

    - the sidecar flock on ``<canonical-db-path>.applock`` (path
      identity: the C6 construction check reads ``.name`` from this
      object, exactly as it read the sidecar file object before);
    - the inode flock: an exclusive ``flock`` held on an open file
      description of the database file itself. ``flock`` is
      inode-bound, not pathname-bound: renaming the file, its lock
      entry, or any parent entry does not move or release it, and
      any process opening the SAME inode through ANY pathname
      (original path, renamed path, symlink alias, hardlink alias)
      contends for the same lock and is refused.

    The guarantee is therefore per-INODE, not per-pathname: it is
    the strongest statement a pathname-opening design can make.
    Replacing the file at the path with a DIFFERENT inode creates a
    different database identity (a new owner for the new inode is
    legitimate; the old owner's Store keeps writing to its own
    inode, which is how SQLite connections behave). The sidecar
    flock is retained for path identity and backward compatibility:
    every pre-existing test that holds a lock and calls ``.close()``
    works unchanged, and ``.name`` still yields the sidecar path.

    ``close()`` is idempotent and never raises: it closes the
    sidecar file object and then the database descriptor, and a
    close error on either descriptor is swallowed after both closes
    are attempted (FD-01), so cleanup can never mask a caller's
    error. Callers (API lifespan, CLI) close the store first and
    the lock second, exactly as before. ``db_identity`` is
    ``(st_dev, st_ino)`` of
    the locked database file, or ``None`` on non-POSIX platforms
    (no flock enforcement there — documented limitation, unchanged)
    and for ``:memory:`` (no file to lock).
    """

    def __init__(self, sidecar_file, db_fd, db_identity):
        self._sidecar = sidecar_file
        self._db_fd = db_fd
        self.db_identity = db_identity
        # Compatibility: verify_store_matches_lock derives the
        # expected canonical path from the sidecar name.
        self.name = sidecar_file.name
        self._closed = False

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._sidecar.close()
        except OSError:
            # FD-01: close() is documented as never raising (it runs
            # inside lifespan/CLI except/finally blocks, where a raise
            # would mask the original error). A raising close() still
            # releases the underlying descriptor, so swallowing here
            # loses nothing and the database descriptor below is
            # still released.
            pass
        finally:
            if self._db_fd is not None:
                import os

                try:
                    os.close(self._db_fd)
                except OSError:
                    pass


def _acquire_db_inode_lock(canonical):
    """Take the exclusive inode flock for an existing-or-fresh DB file.

    Opens ``canonical`` (creating it, mode 0600, if it does not exist
    yet — the fresh-database bootstrap; a refused second process
    never reaches this step because the sidecar flock fails first)
    and places an exclusive non-blocking ``flock`` on the open
    description. Returns ``(fd, (st_dev, st_ino))`` on success or
    ``None`` when another process already holds the inode lock (the
    caller then releases the sidecar and reports contention, exactly
    as for sidecar contention). An unexpected flock error (anything
    other than contention) propagates, but only after the descriptor
    is closed (FD-01). Raises ``RuntimeError`` with a clear
    message when the file cannot be opened at all, and
    ``HardlinkedDatabaseError`` when the pathname no longer names
    the inode just locked (replacement between open and flock) —
    fail closed, never hold a lock on one inode while the caller
    opens another. A read-only database file (e.g. mode 0444 before
    the Store's A-C04 chmod) falls back to a read-only descriptor:
    Linux ``flock`` permits an exclusive lock on a read-only fd, so
    the guarantee is identical; the Store's later chmod restores
    write access as before.
    """
    import fcntl
    import os

    try:
        fd = os.open(canonical, os.O_RDWR | os.O_CREAT, 0o600)
    except PermissionError:
        try:
            fd = os.open(canonical, os.O_RDONLY)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot open database file {canonical} for locking: {exc}"
            ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"Cannot open database file {canonical} for locking: {exc}"
        ) from exc
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    except OSError:
        # FD-01: any other flock failure must not leak the descriptor
        # opened above. Contention returns None; unexpected errors
        # still propagate (fail closed), but only after cleanup.
        os.close(fd)
        raise
    try:
        st_path = os.stat(canonical)
        st_fd = os.fstat(fd)
    except OSError as exc:
        os.close(fd)
        raise RuntimeError(
            f"Cannot verify database file {canonical} for locking: {exc}"
        ) from exc
    if (st_path.st_dev, st_path.st_ino) != (st_fd.st_dev, st_fd.st_ino):
        os.close(fd)
        raise HardlinkedDatabaseError(
            "Database file identity changed during lock acquisition "
            f"({canonical}); refusing to hold a lock on one file while "
            "opening another."
        )
    return fd, (st_fd.st_dev, st_fd.st_ino)


def try_acquire_db_lock(db_path):
    """Try to take the exclusive cross-process lock for ``db_path``.

    Returns a DatabaseLock — hold it for as long as the lock must
    be held (the app lifespan holds it for the process lifetime; the
    CLI holds it for one command) — or None when another process already
    holds it. Implemented with POSIX flock: TWO locks are held
    together (see DatabaseLock): the sidecar flock on
    <canonical-db-path>.applock (path identity) and the inode flock
    on an open description of the database file itself (rename
    resistance — the C5 fix). Two uvicorn workers, or a server and a
    CLI reset, against the same DB file can never both hold it, even
    though they are separate processes. flock treats separate open
    descriptions independently, so a second open in the SAME process
    is also refused, which is what makes the CLI test meaningful.
    A11-01: the lock file is derived from the canonical database
    identity, so a symlink alias and its target contend for the SAME
    lock — the T10-01 contract now holds under alternate pathname
    aliases, not just identical strings. RC12-01: hard links are
    refused BEFORE any lock file is opened (an existing file with
    st_nlink > 1 raises HardlinkedDatabaseError, leaving no lock
    handle behind), and the file identity is re-validated AFTER the
    flock in TWO ways: the resolved pathname must be unchanged
    (A11-01: a symlink swap between identity capture and lock-file
    derivation would otherwise lock the wrong file), and the pre-lock
    (device, inode, link count) tuple must be unchanged (RC12-01: a
    hard link added, a file replaced, or a file deleted mid-flight
    changes no pathname string). Either failure releases the lock
    before raising (fail closed — never hold a lock on one inode
    while the caller opens another). A file created between lock and
    construction is likewise refused; the operator retries and the
    Store is then created normally. The inode lock is taken after
    those revalidations and is itself verified (the pathname must
    still name the locked inode); any failure there releases the
    sidecar before raising or returning None. On platforms without
    fcntl there is no flock enforcement: a DatabaseLock with no
    inode identity is returned, unflocked (documented limitation;
    this lab runs on Linux) — but the hardlink and identity checks
    above still run, since os.stat is portable, and the C6 path
    check still runs at construction.
    """
    canonical = canonical_db_path(db_path)
    before = _check_single_link(canonical)
    # C4: create the lock file's parent first (Store does the same for
    # the DB file). A fresh nested AGENTBOUNDARY_DB_PATH used to fail
    # here with FileNotFoundError while Store() on the same path
    # succeeded. An empty directory left behind by a later-denied
    # attempt is benign.
    from pathlib import Path

    lock_path = db_lock_path(db_path)
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:
        # Non-POSIX platform: no enforcement, file returned unflocked
        # (documented limitation; this lab runs on Linux). The
        # DatabaseLock still carries the sidecar name so the C6 path
        # check keeps working; db_identity stays None.
        fcntl = None
    # The sidecar file object IS part of the lock; closing it
    # releases the sidecar flock, so it must not be wrapped in a
    # with-block.
    f = open(lock_path, "a+")  # noqa: SIM115
    if fcntl is not None:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            return None
        except OSError:
            # FD-01: as with the inode lock, an unexpected flock
            # error must release the sidecar before propagating.
            f.close()
            raise
    # Both revalidations, because each catches what the other cannot:
    # the A11-01 string check catches a symlink swap between identity
    # capture and lock-file derivation (the lock would otherwise be
    # taken on the swapped target's lock file while the caller opens
    # the original); the RC12-01 tuple check catches a hard link
    # added, a file replaced, or a file deleted mid-flight, none of
    # which change the resolved pathname string. Either failure
    # releases the lock before raising.
    after_path = canonical_db_path(db_path)
    after = _db_file_identity(canonical)
    if after_path != canonical or after != before:
        f.close()
        raise HardlinkedDatabaseError(
            "Database file identity changed during lock acquisition "
            f"({db_path}); refusing to hold a lock on one file while "
            "opening another."
        )
    # C5: the inode lock (POSIX only; :memory: has no file to lock).
    # The sidecar flock above is pathname-derived, so on its own it
    # cannot survive renames: a renamed .applock entry (C5-A) or a
    # renamed database file (C5-B) used to admit a second owner.
    # The inode flock below is what closes both: it is held on an
    # open description of the database file itself, so no pathname
    # change can move it or create a second holder for the same
    # inode. Either failure refuses BEFORE any Store is constructed
    # (T10-01 preserved): contention releases the sidecar and
    # returns None, errors release it and raise.
    db_fd = None
    db_identity = None
    if fcntl is not None and canonical != ":memory:":
        try:
            acquired = _acquire_db_inode_lock(canonical)
        except Exception:
            f.close()
            raise
        if acquired is None:
            f.close()
            return None
        db_fd, db_identity = acquired
    return DatabaseLock(f, db_fd, db_identity)


def verify_store_matches_lock(store, lock):
    """C6 (pentest follow-up): the lock is taken on the canonical path
    BEFORE the Store is constructed; a symlink swap in between (a
    directory writer racing startup) would otherwise leave a store on
    a file the lock does not cover. The lock file's own name IS the
    canonical path plus '.applock', so the constructed store's
    canonical path must equal it exactly. Raises RuntimeError on
    mismatch. The helper closes neither object: callers close both
    (the CLI and lifespan denial paths already do), so a refused
    construction leaks nothing. No lock (the :memory: path) is a
    no-op. C5 (fixed): the path check alone cannot see a rename,
    so the inode check below closes the lock-to-construction half
    for renames too — the constructed store's file must be the
    exact inode the lock holds. A lock without an inode identity
    (non-POSIX, or a legacy raw file object) skips the inode check,
    preserving old behavior there. Honest boundary, stated
    plainly: this check (like the path check) reads the store's
    path AFTER construction, so a symlink swapped twice inside the
    microscopic construction window — away and back before this
    check runs — is theoretically undetectable by any path-based
    check; closing even that would require passing an open file
    descriptor into SQLite, which breaks journal-file creation.
    That window is far narrower than C5 (which needed only one
    rename before the second process started) and is NOT a
    demonstrated bypass; the two specified C5 reproductions are
    closed at acquisition time, before any Store exists."""
    if lock is None:
        return
    name = getattr(lock, "name", "")
    suffix = ".applock"
    expected = name[: -len(suffix)] if name.endswith(suffix) else None
    if expected is None or store.path != expected:
        raise RuntimeError(
            "Database file identity changed between lock acquisition "
            "and Store construction; refusing to operate on a file "
            "the lock does not cover."
        )
    identity = getattr(lock, "db_identity", None)
    if identity is not None:
        import os

        try:
            st = os.stat(store.path)
        except OSError as exc:
            raise RuntimeError(
                "Database file identity changed between lock acquisition "
                "and Store construction; refusing to operate on a file "
                "the lock does not cover."
            ) from exc
        if (st.st_dev, st.st_ino) != identity:
            raise RuntimeError(
                "Database file identity changed between lock acquisition "
                "and Store construction; refusing to operate on a file "
                "the lock does not cover."
            )


class Store:
    # FA-07: live-connection accounting, independent of GC warnings
    # (which Python 3.12 does not emit for sqlite3 at all, and 3.13
    # reports only at collection time). Every Store registers on open
    # and deregisters exactly once on close; tests assert the count
    # returns to baseline, which proves lifecycle closure on ANY
    # Python version without relying on warning timing.
    _live_count = 0
    _live_lock = threading.Lock()

    def __init__(self, path):
        # A11-01: every Store operates on the canonical database
        # identity, so a symlink alias and its target are the same
        # store (and contend for the same lock) by construction.
        # RC12-01: refuse a multiply-hardlinked database BEFORE any
        # mkdir, connect, seed, repair, or migration — a hardlink
        # alias has a different canonical string for the same inode,
        # so pathname locks alone cannot give it a single owner. A
        # not-yet-created database has no identity yet and proceeds.
        self.path = canonical_db_path(path)
        if self.path != ":memory:":
            _check_single_link(self.path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        # A-C04 (pentest follow-up): the live DB holds session tokens
        # in plaintext, so it gets the same owner-only mode as backups
        # (0600), not whatever the process umask yields (640 observed).
        # Best-effort: a chmod failure leaves the umask mode, never
        # breaks the open. :memory: has no file to chmod.
        if self.path != ":memory:":
            import os

            if os.name == "posix":
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
        self._closed = False
        self.lock = threading.RLock()
        with Store._live_lock:
            Store._live_count += 1
        try:
            self.conn.row_factory = sqlite3.Row
            # Integrity state (R-11): tables recreated empty by repair, and
            # fixture tables backfilled on open. Research evidence (runs,
            # events) is NEVER invented: if those tables had to be recreated,
            # the store is flagged degraded and health reports it honestly.
            self.backfilled_tables = []
            self.degraded_tables = []
            with self.lock:
                # C1 (pentest follow-up): seed ONLY a truly empty
                # database. The old code seeded whenever the `cases`
                # table was absent -- and seed() DROPs all 13 tables,
                # so a database damaged in exactly one table lost all
                # research evidence (runs/events) on open. A damaged
                # database now takes the surgical path: recreate just
                # the missing tables, migrate, and backfill fixture
                # rows (INSERT OR IGNORE) below, leaving existing rows
                # untouched.
                tables = {
                    r[0]
                    for r in self.conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if not tables:
                    self.seed()
                else:
                    recreated = self._repair_missing_tables()
                    if "runs" in recreated or "events" in recreated:
                        self.degraded_tables = [
                            t for t in ("runs", "events") if t in recreated
                        ]
                    self._migrate()
                self._ensure_fixture_integrity()
        except BaseException:
            # A11-03: a failed constructor returns NO Store object, so
            # no caller can invoke close() — the constructor itself
            # must release the opened connection and its live-count
            # registration, exactly once, before re-raising the
            # original error. Marking _closed first guarantees close()
            # (if ever reached) cannot decrement a second time, and
            # the original exception — seed, migration, repair,
            # fixture-validation, or disk error — is never swallowed
            # or relabeled.
            self._closed = True
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001, S110 - teardown is best-effort
                pass
            with Store._live_lock:
                Store._live_count -= 1
            raise

    @property
    def fixture_degraded(self):
        return bool(self.degraded_tables)

    def _fixture_expected(self):
        """Deterministic seed rows per fixture table (same as seed())."""
        return {
            "tenants": [(t["id"], t["name"]) for t in TENANTS],
            "personas": [
                (
                    p.id,
                    p.role,
                    json.dumps(list(p.tenants)),
                    json.dumps(list(p.can_approve)),
                )
                for p in PERSONAS.values()
            ],
            "cases": list(CASES),
            "alerts": list(ALERTS),
            "timeline_events": list(TIMELINE),
            "runbooks": list(RUNBOOKS),
            "approvals": list(APPROVALS),
            "assets": list(ASSETS),
        }

    def _ensure_fixture_integrity(self):
        """Backfill missing fixture reference rows, never research evidence.

        Fixture tables are immutable reference data: INSERT OR IGNORE
        restores any missing seed rows without touching existing rows,
        runs, events, drafts, isolations, or consumed approvals. If a
        fixture table still ends up short (e.g. a row was modified rather
        than deleted), it is flagged degraded instead of silently
        declared healthy.
        """
        for table, rows in self._fixture_expected().items():
            try:
                have = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except Exception:  # noqa: BLE001 - table missing despite repair
                self.degraded_tables.append(table)
                continue
            if have < len(rows):
                placeholders = ",".join("?" * len(rows[0])) if rows else ""
                self.conn.executemany(
                    f"INSERT OR IGNORE INTO {table} VALUES ({placeholders})",
                    rows,
                )
                self.conn.commit()
                self.backfilled_tables.append(table)
                have = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if have < len(rows):
                    self.degraded_tables.append(table)

    def _repair_missing_tables(self):
        """Recreate any schema table that is missing, without touching
        existing tables or rows.

        Phase 7 root cause: two backend processes (a systemd unit in a
        bind-fail restart loop plus a manually started server) seeded the
        same DB concurrently; sqlite executescript is not atomic, so one
        seed aborted partway and left the DB without `events`/`sessions`.
        Repair makes a damaged DB self-healing on next open; seed()
        atomicity (below) prevents recurrence.
        """
        existing = {
            r[0]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = [
            stmt
            for stmt in _SCHEMA_CREATES
            if stmt.split("(", 1)[0].split()[-1] not in existing
        ]
        if not missing:
            return []
        missing_names = [stmt.split("(", 1)[0].split()[-1] for stmt in missing]
        # Repair writes need the write lock; another backend process may
        # briefly hold it (e.g. during its own seed). Retry briefly
        # instead of crashing the import on a transient lock.
        import sqlite3 as _sqlite3
        import time as _time

        for attempt in range(25):
            try:
                for stmt in missing:
                    self.conn.execute(stmt)
                self.conn.commit()
                return missing_names
            except _sqlite3.OperationalError:
                if attempt == 24:
                    raise
                self.conn.rollback()
                _time.sleep(0.2)
        return missing_names

    def _migrate(self):
        """Add new columns to existing DBs (runs/approvals) without a reset."""
        migrations = {
            "runs": [
                ("operator_persona_id", "TEXT"),
                ("simulated_actor_id", "TEXT"),
                ("control_actor_id", "TEXT"),
                ("fixture_version", "TEXT"),
                ("fixture_variant", "TEXT"),
            ],
            "approvals": [("new_status", "TEXT")],
            # N-04/N-08(a): run_id-scoped evidence attribution and logical
            # tool-call correlation for pre-remediation databases.
            # FR-10: per-call origin (scripted_agent / real_model /
            # harness_control) for pre-remediation databases.
            "events": [
                ("tool_call_id", "TEXT"),
                ("evidence_scope", "TEXT DEFAULT 'primary'"),
                ("origin", "TEXT DEFAULT 'agent'"),
            ],
        }
        with self.lock:
            for table, cols in migrations.items():
                existing = {
                    r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")
                }
                for name, decl in cols:
                    if name not in existing:
                        self.conn.execute(
                            f"ALTER TABLE {table} ADD COLUMN {name} {decl}"
                        )
            self.conn.commit()

    def close(self):
        with self.lock:
            if getattr(self, "_closed", True):
                return
            self._closed = True
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001, S110 - close is best-effort teardown
                pass
            with Store._live_lock:
                Store._live_count -= 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    @contextmanager
    def transaction(self):
        """One BEGIN IMMEDIATE transaction under the store write lock.

        Callers must use self.conn directly inside (store.execute() would
        commit early). Commits on success, rolls back on any exception.
        """
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def _seed_statements(self, conn):
        """Schema rebuild + fixture inserts, WITHOUT committing.

        The statements run inside the caller's transaction (see seed()
        and reset()). This split exists so reset() can put the reseed
        and the preserved-session insert in ONE transaction: the old
        reset() called seed() — which committed — and then inserted
        the session in a second transaction, so a failure at that
        boundary left the lab reseeded with no admin session
        (RC12-02). SQLite DDL is rollback-capable, so a failure
        anywhere in this body rolls the whole reset back. Deliberately
        NOT executescript(): it implicitly commits.
        """
        for stmt in SCHEMA.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.executemany(
            "INSERT INTO tenants VALUES (?,?)",
            [(t["id"], t["name"]) for t in TENANTS],
        )
        conn.executemany(
            "INSERT INTO personas VALUES (?,?,?,?)",
            [
                (
                    p.id,
                    p.role,
                    json.dumps(list(p.tenants)),
                    json.dumps(list(p.can_approve)),
                )
                for p in PERSONAS.values()
            ],
        )
        conn.executemany("INSERT INTO cases VALUES (?,?,?,?,?,?,?)", CASES)
        conn.executemany("INSERT INTO alerts VALUES (?,?,?,?,?,?)", ALERTS)
        conn.executemany(
            "INSERT INTO timeline_events VALUES (?,?,?,?,?,?,?,?,?)", TIMELINE
        )
        conn.executemany("INSERT INTO runbooks VALUES (?,?,?,?,?,?)", RUNBOOKS)
        conn.executemany(
            "INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?,?)", APPROVALS
        )
        conn.executemany("INSERT INTO assets VALUES (?,?,?)", ASSETS)

    def _preserve_session(self, conn, session):
        """Insert the one session a reset keeps (RC12-02), inside the
        reset transaction. A separate method so fault-injection tests
        can fail exactly this step — after the reseed, before commit —
        and prove the whole reset rolls back."""
        token, persona_id, exp = session
        conn.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?,?,?)",
            (token, persona_id, exp),
        )

    def seed(self):
        # Atomic reseed: the old executescript() ran each statement in
        # autocommit, so a concurrent seed (two backends, same DB file)
        # could interleave DROPs/CREATEs and abort partway, leaving a
        # partial schema. BEGIN IMMEDIATE serializes competing seeds:
        # the second waits for the first's lock (sqlite timeout) instead
        # of interleaving with it. The record count is read inside the
        # transaction (same connection sees its own writes); the
        # transaction manager commits on clean exit.
        with self.transaction() as c:
            self._seed_statements(c)
            return self.record_count()

    def reset(self, preserve_session=None):
        # RC12-02: the ENTIRE destructive reset — schema rebuild,
        # fixture inserts, and the preserved admin session — commits
        # in ONE BEGIN IMMEDIATE transaction. Any failure before
        # commit (schema rebuild, fixture insert, session
        # preservation) rolls back the whole operation via
        # transaction(): the old cases, runs, events, approvals,
        # sessions, drafts, and isolations stay exactly as they were,
        # and no 'reset: true' response is ever sent for an
        # uncommitted reset. The record count is read inside the
        # transaction, so a post-commit read failure cannot misreport
        # a committed reset as failed. Idempotency clearing stays in
        # the API handler, after this returns — a failed reset never
        # reaches it, so still-existing runs and their idempotency
        # entries survive. Filesystem/OS failure during commit or
        # rollback itself is disaster recovery (pre-reset .bak), not
        # something a transaction can guarantee; see the API handler's
        # RESET_FAILED contract.
        with self.transaction() as c:
            self._seed_statements(c)
            if preserve_session:
                self._preserve_session(c, preserve_session)
            return self.record_count()

    def record_count(self):
        total = 0
        for t in [
            "tenants",
            "personas",
            "cases",
            "alerts",
            "timeline_events",
            "runbooks",
            "approvals",
            "assets",
        ]:
            total += self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return total

    # generic helpers
    def one(self, sql, args=()):
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        with self.lock:
            self.conn.execute(sql, args)
            self.conn.commit()

    # domain helpers
    def case_tenant(self, case_id):
        r = self.one("SELECT tenant_id, status FROM cases WHERE id=?", (case_id,))
        return r

    def get_case(self, case_id):
        return self.one("SELECT * FROM cases WHERE id=?", (case_id,))

    def get_alert(self, alert_id):
        return self.one("SELECT * FROM alerts WHERE id=?", (alert_id,))

    def get_asset(self, asset_id):
        return self.one("SELECT * FROM assets WHERE id=?", (asset_id,))

    def get_approval(self, approval_id):
        return (
            self.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
            if approval_id
            else None
        )

    def timeline_for_case(self, case_id):
        return self.all(
            "SELECT * FROM timeline_events WHERE case_id=? ORDER BY timestamp, id",
            (case_id,),
        )

    def fixture_version(self):
        return FIXTURE_VERSION
