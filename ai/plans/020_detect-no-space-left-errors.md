# detect no-space-left errors.

Todo: `todo:e5111b29-8a0a-4d66-8d3f-91330a088abc` (project archiveApps, calendar 7).

> detect no-space-left errors.
> - Currently just fails to write checksum files.

## Findings

- `io.safe_write`, `io.safe_append` and `io.safe_mv` catch every exception with a bare `except Exception: pass`, then open `write_fail_menu`, which only says "WRITE ERROR: write X.checksums.txt".
  The user never learns that the disk is full, and a retry ("a") just fails again.
- The same blind spot exists for the `ditto` copy/zip subprocesses and `app_ops.send_file`: rsync failure prints "rsync failed, falling back to a plain copy", and the fallback copy raises a raw `OSError` (errno `ENOSPC`).
- A full disk also tends to leave a truncated `.tmp` file behind that `safe_write` could mistake for success only if the readback matched, which it does not, so the failure path is the right place to hook in.

## Plan

1. `archive_apps/io.py`: add `is_no_space(exc)` (an `OSError` with errno `ENOSPC` or `EDQUOT`) and `free_space_text(path)` (`shutil.disk_usage` on the nearest existing parent, formatted with `utils.fmt_size`, never raises).
2. `write_fail_menu` gets an optional `reason: BaseException | str | None`.
   It prints the OS error text, and for a no-space error a clear "NO SPACE LEFT on the device of <dest>, N free" line plus the hint to free space and then pick retry.
3. `safe_write`, `safe_append` and `safe_mv` keep the caught exception and pass it as `reason`.
   Also remove the half-written `.tmp` on a no-space error, so a retry starts clean and the freed space is real.
4. `app_ops.send_file` and the ditto helpers (`copy_app_fresh`, `archive_app_to_zip`): on failure, check free space of the target and print the same no-space message when the disk is (nearly) full, so the root cause is named instead of a generic failure.
   Behaviour (exceptions, return values) stays the same, only the message is added.
5. Update `CLAUDE.md` (io.py bullet / a line under "Atomic writes") to mention the no-space detection.

## Tests (`tests/test_no_space.py`)

- `is_no_space` true for `OSError(errno.ENOSPC, ...)` and `EDQUOT`, false for `PermissionError`.
- `safe_write` with `Path.write_text` patched to raise ENOSPC: `write_fail_menu` is called with a reason that is detected as no-space, and the menu output contains "NO SPACE LEFT" (tty_read patched to answer `c`).
- `free_space_text` returns a string for a missing path and does not raise.

## Verification

`uv run --with pytest python -m pytest tests`, plus a manual check on a tiny RAM disk (`hdiutil`) is optional and not needed for the commit.
