"""FD-01 (LOW): exceptional-path file-descriptor cleanup in database
lock acquisition.

The C5 inode-lock fix (commit ``b35db7b``) caught only
``BlockingIOError`` from ``fcntl.flock``. If ``flock`` raised any
OTHER ``OSError`` (EINVAL, ENOLCK, or any unexpected flock failure),
the descriptor stayed open:

- ``_acquire_db_inode_lock``: the raw ``os.open`` descriptor was
  never closed on a non-``BlockingIOError`` flock failure. Raw
  descriptors are not garbage-collected, so the leak is
  deterministic and observable via ``/proc/self/fd``.
- ``try_acquire_db_lock`` (sidecar): the sidecar file object was
  never closed on a non-``BlockingIOError`` flock failure. Under
  CPython the frame teardown usually closes it, but any reference
  that escapes (a retained traceback, a wrapper holding the file)
  keeps it open — so the test holds a reference to make the leak
  deterministic instead of relying on collector timing.
- ``DatabaseLock.close()``: the docstring promises "idempotent and
  never raises", but a sidecar ``close()`` error propagated out of
  ``close()`` — which runs inside lifespan/CLI ``except`` and
  ``finally`` blocks, where a raise would mask the original error.

These tests are failing-first by construction: on the pre-fix code
all three fail (leaked descriptor / unclosed file / propagated
raise); on the fixed code all three pass. The fix preserves every
other behavior: contention still returns ``None``, unexpected flock
errors still propagate (fail closed, after cleanup), and the C5
rename protections are untouched (see ``test_c5.py``).

POSIX/Linux only: ``flock`` and ``/proc/self/fd`` do not exist on
the documented non-POSIX path (see the report).
"""

import builtins
import errno
import os

import pytest

from agentboundary.store import (
    DatabaseLock,
    _acquire_db_inode_lock,
    try_acquire_db_lock,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="FD-01 tests require POSIX flock"
)


def _live_fds():
    return set(os.listdir("/proc/self/fd"))


def _raise_flock(*args, **kwargs):
    raise OSError(errno.EINVAL, "Invalid argument (fault-injected)")


def test_inode_flock_unexpected_error_closes_fd(tmp_path, monkeypatch):
    """Raw descriptor from _acquire_db_inode_lock must not leak when
    flock raises a non-BlockingIOError OSError."""
    import fcntl

    db_file = tmp_path / "leak.db"
    db_file.write_bytes(b"")
    monkeypatch.setattr(fcntl, "flock", _raise_flock)
    before = _live_fds()
    with pytest.raises(OSError):
        _acquire_db_inode_lock(str(db_file))
    after = _live_fds()
    assert after == before, f"leaked descriptors: {sorted(after - before)}"


def test_sidecar_flock_unexpected_error_closes_file(tmp_path, monkeypatch):
    """Sidecar file object from try_acquire_db_lock must be closed
    when its flock raises a non-BlockingIOError OSError, even when
    the caller holds a reference to the file object."""
    import fcntl

    real_open = builtins.open
    held = []

    def tracking_open(path, *args, **kwargs):
        f = real_open(path, *args, **kwargs)
        if str(path).endswith(".applock"):
            held.append(f)
        return f

    monkeypatch.setattr(builtins, "open", tracking_open)
    monkeypatch.setattr(fcntl, "flock", _raise_flock)
    db_file = tmp_path / "leak.db"
    with pytest.raises(OSError):
        try_acquire_db_lock(str(db_file))
    assert held, "expected the sidecar open to be observed"
    assert held[0].closed, "sidecar file object left open on flock error"


class _RealisticSidecar:
    """Models a real file object: close() marks itself closed even
    when it raises (e.g. a flush failure during close)."""

    def __init__(self):
        self.name = "x.applock"
        self.closed = False
        self.close_calls = 0

    def close(self):
        self.closed = True
        self.close_calls += 1
        raise OSError("simulated sidecar close failure")


def test_close_never_raises_and_closes_db_fd(tmp_path):
    """DatabaseLock.close() must never raise (per its docstring)
    and must still close the database descriptor when the sidecar
    close raises; a second close() must be a silent no-op."""
    import fcntl  # noqa: F401  (documents the POSIX-only context)

    probe = tmp_path / "probe.db"
    probe.write_bytes(b"")
    db_fd = os.open(str(probe), os.O_RDWR)
    sidecar = _RealisticSidecar()
    lock = DatabaseLock(sidecar, db_fd, (1, 2))
    lock.close()  # must not raise on the fixed code
    assert sidecar.close_calls == 1
    with pytest.raises(OSError):
        os.fstat(db_fd)  # descriptor is closed
    lock.close()  # idempotent no-op, still must not raise
    assert sidecar.close_calls == 1
