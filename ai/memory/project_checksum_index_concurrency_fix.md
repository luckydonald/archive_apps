---
name: project_checksum_index_concurrency_fix
description: 2026-08-30 fix for lost progress in _checksum_index_.txt when multiple archive_apps runs (backup + --verify-*, or two --verify-* runs) execute concurrently
metadata:
  node_type: memory
  type: project
  originSessionId: 38eb1bc9-858b-49b9-b13f-cf9f3c8beb89
  modified: 2026-08-30T18:27:47.397Z
---

Fixed a bug where `_checksum_index_.txt` lost entries when two `archive_apps` invocations touched the same destination concurrently (e.g. a scheduled backup run overlapping a `--verify-*` run, or two `--verify-*` runs overlapping). Root cause: all writers shared one fixed-name scratch file (`_checksum_index_.txt.tmp`), truncated it at startup, and the exit/cleanup trap acted on it unconditionally even for runs that never created it — so one process could truncate or steal another's in-progress scratch file, and the final "sort scratch, rename over index" step was a blind overwrite rather than a merge (lost-update race between finishing runs).

**Fix, applied identically to `archive_apps.py` and the `archive_apps/` package** (see `archive_apps/lock.py`, `merge_checksum_index()` in `verify.py`/`archive_apps.py`):
- Each `--verify-*` run gets a uniquely-named scratch file (`tempfile.mkstemp`), so appends need no locking.
- All writes to the shared index go through a lock-protected, key-by-filename merge (`checksum_index_lock()` + `merge_checksum_index()`), never a blind overwrite.
- Locking picks `fcntl.flock` on local filesystems (apfs/hfs, detected via parsing `mount` output — macOS has no clean fs-type API) or a staleness-timeout `mkdir`-based lock otherwise, since flock's SMB/NFS reliability can't be assumed — see [[feedback_design_preferences]].
- A hash replacement for an existing filename key is never silently dropped: recorded to `_checksum_index_.history.log` and printed, and the prior index is snapshotted to a timestamped `.bak` (pruned to the last 5 unless `--keep-temp`) before every overwrite.
- Startup auto-merges any orphaned scratch file left by a killed prior run, printing its full contents first — replacing the old 3-prompt interactive recovery flow.

Also see [[project_shell_script_removed]] (the `.sh` implementation was retired rather than given this same fix) and [[feedback_testing_archive_apps]] (how to test either Python implementation in isolation, including the import-shadowing gotcha discovered while validating this fix).
