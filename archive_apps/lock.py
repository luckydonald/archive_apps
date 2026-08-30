"""Locking for the shared checksum index.

The destination can be local disk or a NAS mounted over SMB/NFS. flock-style
byte-range locks depend on the network filesystem correctly implementing
them; some configurations silently no-op rather than erroring, which would
defeat the whole scheme with no visible failure. mkdir (atomic create-or-
fail) is reliably atomic on essentially any filesystem, so it's used as the
fallback for anything not recognized as local — at the cost of needing a
staleness timeout instead of relying on the OS to release the lock when a
process dies.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

LOCAL_FSTYPES = {"apfs", "hfs"}
STALE_SECONDS = 5 * 60
ACQUIRE_TIMEOUT = 60
POLL_INTERVAL = 1


def dest_fstype(path: Path) -> str:
    """Best-effort filesystem type name for path (e.g. 'apfs', 'smbfs', 'nfs').

    macOS exposes no clean API for this; parse `mount`'s output instead.
    """
    try:
        out = subprocess.run(["mount"], capture_output=True, text=True, check=True).stdout
    except Exception:
        return ""
    resolved = str(path.resolve())
    best_type, best_len = "", -1
    for line in out.splitlines():
        if " on " not in line or "(" not in line:
            continue
        mnt, _, rest = line.split(" on ", 1)[1].partition(" (")
        mnt = mnt.rstrip("/")
        if resolved != mnt and not resolved.startswith(mnt + "/"):
            continue
        if len(mnt) <= best_len:
            continue
        best_len = len(mnt)
        best_type = rest.split(",", 1)[0].strip().rstrip(")")
    return best_type


@contextlib.contextmanager
def _flock_lock(dest: Path) -> Iterator[bool]:
    lockfile = dest / "_checksum_index_.flock"
    try:
        fh = open(lockfile, "a")
    except OSError:
        yield False
        return
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
    except OSError:
        fh.close()
        yield False
        return
    try:
        yield True
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def _rm_lockdir(lockdir: Path) -> None:
    try:
        for child in lockdir.iterdir():
            child.unlink(missing_ok=True)
        lockdir.rmdir()
    except OSError:
        pass


@contextlib.contextmanager
def _mkdir_lock(dest: Path) -> Iterator[None]:
    lockdir = dest / "_checksum_index_.lockdir"
    deadline = time.monotonic() + ACQUIRE_TIMEOUT
    while True:
        try:
            os.mkdir(lockdir)
            break
        except FileExistsError:
            pass
        try:
            age = time.time() - lockdir.stat().st_mtime
        except OSError:
            continue
        if age > STALE_SECONDS:
            print(f"LOCK: breaking stale lock {lockdir.name} ({age:.0f}s old)", file=sys.stderr)
            _rm_lockdir(lockdir)
            continue
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"could not acquire checksum-index lock at {lockdir} within {ACQUIRE_TIMEOUT}s"
            )
        time.sleep(POLL_INTERVAL)

    try:
        (lockdir / "info").write_text(
            f"pid={os.getpid()}\nhost={socket.gethostname()}\ntime={time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
        )
    except OSError:
        pass

    try:
        yield
    finally:
        _rm_lockdir(lockdir)


@contextlib.contextmanager
def checksum_index_lock(dest: Path) -> Iterator[None]:
    if dest_fstype(dest) in LOCAL_FSTYPES:
        with _flock_lock(dest) as ok:
            if ok:
                yield
                return
    with _mkdir_lock(dest):
        yield
