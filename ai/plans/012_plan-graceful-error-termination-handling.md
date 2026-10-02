# Plan: graceful error/termination handling

## Context
Two failures in `ai/errors/18.txt` and `19.txt` (the Makefile runs the single-file `archive_apps.py`, so both it and the `archive_apps/` package need the fix):

- **18**: `rm_retry` calls `sys.exit(1)` after 5 failed attempts. It runs inside the `atexit` cleanup, so `SystemExit` aborts the rest of cleanup, including the other `.archive_apps.*` dirs and the system-temp sweep. The exit code is also turned into an error.
- **19**: Ctrl-C raises `sys.exit(1)` from the signal handler. `_cleanup` then runs `merge_checksum_index`. A second signal (or any interrupt) lands inside it, between `index_file.rename(backup)` and the new index being written (`verify.py:260-269`). Result: `_checksum_index_.txt` is gone (only a `.bak`), and the scratch file is left over. The next run's recovery merges the scratch into an empty "current" and writes an index containing only the partial entries. That is the missing-SHA-list symptom.

Your assumption holds for the verify index. Per-app `.checksums.txt` files are written per app with tmp+mv, so they are not at risk, apart from leftover `.tmp` files.

## Changes

1. **Make the index merge crash-safe** (`merge_checksum_index`, `verify.py:212`; mirror in `archive_apps.py`)
   - Write the merged content to the tmp file first, then back up the old index with `shutil.copy2` (not rename), then `os.replace(tmp, index_file)`. The index file is never absent, and replacement is atomic.
   - Keep the history-log append before the replace. Keep the scratch file until the replace succeeds.

2. **Signal handling** (`__main__.py:49`; `archive_apps.py:~1750`)
   - Replace the `sys.exit(1)` lambda with a handler that raises `KeyboardInterrupt` for SIGINT and `SystemExit(130/143)` for SIGTERM, so the exit code is meaningful.
   - At the start of `_cleanup`, set SIGINT/SIGTERM to `SIG_IGN`. Cleanup (index merge, tmp removal) then cannot be interrupted midway. Print one line, "cleaning up, please wait…", so a user who hits Ctrl-C again knows why nothing happens.
   - Make `_cleanup` idempotent via a guard flag.

3. **`rm_retry` must not exit** (`io.py:161`; `archive_apps.py:~465`)
   - Return `bool`. On final failure, print the ERROR line and return `False`; remove `sys.exit(1)`.
   - Retry harder before giving up: on failure, try `chflags -R nouchg` and `chmod -R u+rwX` on the path, then retry. These are the usual causes on SMB/macOS (locked flags, read-only app files).
   - Callers in `app_ops.py` (lines 137, 146, 178) keep working. They already don't use a return value, but check each for a case where continuing after a failed delete would be wrong.
   - In `_cleanup`, wrap each step in its own `try/except Exception`, so one failed dir doesn't skip the rest. Print a summary of leftovers ("N leftover work dirs, will be retried next run"). Cleanup then globs `.archive_apps.*` again at the next start, so leftovers are retried automatically. Confirm that `run_archive` and verify do this at start; if not, add it.

4. **Orphan scratch recovery for archive mode**: `run_verify_all` already recovers `_checksum_index_.*.tmp` leftovers. Verify that a run interrupted in step 2 now leaves either a complete index or a recoverable scratch, and never an empty or partial index.

5. **Sync `archive_apps.py`** with the package changes (identical logic; it uses PlistBuddy, which is unrelated). Do not touch the `*.bak.sh` files.

## Verification
- Add tests under `test/` (a pytest file if a harness exists; otherwise a script) covering:
  - `merge_checksum_index` with `os.replace` monkeypatched to raise: the original index is still intact and the scratch file is still present.
  - `rm_retry` on an undeletable path (a dir with `chflags uchg`) returns `False` without raising `SystemExit`, and `_cleanup` still processes the other dirs.
- Manual: run `./main.py --verify-new <tmpdest>` on a dir with a few zips, press Ctrl-C mid-run and then again during cleanup. Check that `_checksum_index_.txt` exists and is non-empty, and that no traceback is printed. Run it again and confirm the recovery merge is correct.
- Same manual check with `archive_apps.py` via `make verify-new` against a scratch destination (not the real share).
