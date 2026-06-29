# Plan: Rewrite archive_apps.sh as archive_apps.py

## Context

`archive_apps.sh` is a 1 417-line Bash script that snapshots macOS `.app` bundles into versioned zip archives. It already uses Python inline (`python3 - ... <<'PYEOF'`) for all the CPU-heavy work (hashing, zip inspection, symlink detection, manifest generation). The rewrite consolidates everything into a single Python file, eliminating the shell wrapper entirely and making the code easier to test and extend.

`archive_apps.sh` stays untouched (it becomes the latest `.bak.sh` equivalent). The new file is `archive_apps.py`.

---

## Structure

**Single file** — `archive_apps.py`, runnable directly via `uv`:

```
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
```

No PyPI dependencies — everything is stdlib + macOS system tools (`ditto`, `rsync`).

**Sections within the file, top to bottom:**

1. Shebang + uv inline metadata
2. Imports
3. `Config` dataclass (all resolved settings)
4. `ProgressBar` class (replaces all `_render_progress_bar / _clear_progress_bar / _print_elapsed / _*_progress_bar_filter` functions; drives subproc output via a background thread)
5. Atomic write helpers: `safe_write`, `safe_append`, `safe_mv`, `write_fail_menu` (replaces `safe_write / safe_mv / safe_append / _write_fail_menu / _tty_read`)
6. `rm_retry` with DELETE progress
7. Zip-inspection helpers: `checksums_from_zip`, `external_symlinks_from_zip`, `count_symlinks_from_zip` (the Python already lived in heredocs; just promote to real functions)
8. Live-app helpers: `collect_app_manifest`, `collect_external_live_symlinks`, `count_live_symlinks`
9. Copy/zip pipeline: `copy_app_fresh`, `repair_app_copy`, `ensure_archive_copy`, `archive_app_to_zip`, `archive_and_store_zip`
10. Verify helpers: `verify_checksum_file_contents`, `unreadable_prompt`
11. Symlink summary state + helpers
12. `run_verify_all` — `--verify-zips/new/changed` block
13. `run_verify_zip` — `--verify-zip=APP` block
14. `run_archive` — main `/Applications` loop
15. `parse_args` → returns `Config`
16. `main` + `if __name__ == '__main__'`

---

## Key translation decisions

All external tool invocations (`ditto`, `rsync`, `PlistBuddy`, `shasum`, `find`, `du`, `stat`, `date`, …) are kept as `subprocess` calls. Each one gets a `# TODO: replace with <pure-Python equivalent>` comment so the path to full stdlib is clear.

| Bash | Python subprocess call | TODO note |
|------|------------------------|-----------|
| `PlistBuddy -c "Print :Key"` | `subprocess.run(['…'])` | `plistlib.load()` (stdlib) |
| `shasum -a 256` | `subprocess.run(['shasum', …])` | `hashlib.sha256()` |
| `find … | wc -l` | `subprocess.run(['find', …])` | `sum(1 for p in Path(x).rglob('*') if p.is_file())` |
| `ditto -V` copy (COPY bar) | `subprocess.Popen`, drain stderr in background thread feeding `ProgressBar` |
| `ditto -c -k` zip (ZIP bar) | same — ditto is still called; no Python zipfile replacement (resource forks) |
| `rsync --progress` (SEND bar) | same — rsync is still called |
| `trap cleanup EXIT` | `atexit.register(cleanup)` + `signal.signal(SIGINT/SIGTERM, …)` |
| `_tty_read` | `open('/dev/tty').readline()` with fallback default |
| `printf '\r…' >&2` | `sys.stderr.write('\r…')` |
| Bash arrays `_preserve_tmps` | Python `list` |
| `safe_write` readback check | same pattern with `Path.read_text()` |

### Progress bar threading model

The three filter functions (`_progress_bar_filter`, `_rsync_progress_bar_filter`, `_rsync_file_progress_bar_filter`) are currently pipeline consumers — the shell pipes ditto/rsync output into them. In Python we use `subprocess.Popen` and drain the pipe on a daemon thread:

```python
proc = subprocess.Popen([...], stderr=subprocess.PIPE)
bar = ProgressBar("COPY", total, start=time.time())
def _drain():
    for line in proc.stderr:
        if line.startswith(b'copying '):
            bar.tick()
threading.Thread(target=_drain, daemon=True).start()
proc.wait()
bar.done()
```

`ProgressBar.done()` clears the line and prints the elapsed time.

### Same-filesystem detection (cp clone flag)

```python
same_fs = os.stat(dest).st_dev == os.stat('/Applications').st_dev
```

When true, copy uses `subprocess.run(['ditto', app, workapp])` without `-V` and with clone semantics (ditto copies resource forks either way; the bash `-cR` flag was for `cp`, not ditto — so in Python we always use ditto and drop the `cp_flags` distinction).

Actually: re-reading the bash, `cp_flags=(-cR)` when same-fs — `-c` is the clone flag for `cp`. But `_copy_archive_app_fresh` only uses `cp` when `use_bar=0 OR cp_flags contains -c`. When same-fs AND there's a bar, it still uses `ditto -V`. So the clone path only triggers when either there's no tty (no bar) or same-fs+no-bar. In Python, we can always use ditto since it's correct in all cases; when same-fs and no-bar we can keep `cp -cR` for the speed win.

### `_collect_app_manifest` sort

Already correct Python (locale C collation). Just becomes a regular function.

### ZIP64 workaround

The `_find_zip64_offset` / `_hash_at_offset` functions move verbatim from the heredoc into real Python functions. No changes to logic.

---

## Files modified

- **Create**: `archive_apps.py` (new, ~1 100 lines)
- **Leave unchanged**: `archive_apps.sh` (remains as the reference/fallback)
- **Update**: `CLAUDE.md` — add `archive_apps.py` section (uv shebang, how to run)

---

## Implementation order (sequential, commit each phase)

1. **Scaffold** — shebang, imports, `Config`, `parse_args`, `main` stub that prints config and exits
2. **Progress bar + elapsed** — `ProgressBar` class + drain-thread model, tested by running a dummy ditto copy
3. **Atomic writes + rm_retry** — `safe_write/append/mv`, `write_fail_menu`, `rm_retry`
4. **Zip helpers** — `checksums_from_zip`, `external_symlinks_from_zip`, `count_symlinks_from_zip` (move from heredocs verbatim, test with a zip from `test/`)
5. **Live-app helpers** — `collect_app_manifest`, `collect_external_live_symlinks`, `count_live_symlinks`
6. **Copy/zip pipeline** — `copy_app_fresh`, `repair_app_copy`, `ensure_archive_copy`, `archive_app_to_zip`, `archive_and_store_zip`
7. **Verify helpers + `run_verify_zip`** — `verify_checksum_file_contents`, `unreadable_prompt`, `run_verify_zip`
8. **`run_verify_all`** — all three `--verify-zips/new/changed` modes + index management
9. **`run_archive`** — main loop, plistlib plist reading, full decision tree
10. **Cleanup + wire-up** — atexit, SIGINT, external symlink summary, final testing

---

## Verification

```bash
# Smoke test: help text
./archive_apps.py --help

# Spot-check a known zip against its checksum file
./archive_apps.py --verify-zip="Xcode.app@15.4.zip" /path/to/dest

# Full verify against test fixtures (no /Applications scan)
./archive_apps.py --verify-zips /path/to/dest

# Dry-run main loop against a scratch destination
mkdir /tmp/aa_test
./archive_apps.py /tmp/aa_test
```

Output format, exit codes, and all file naming conventions are identical to the shell version. Run both side-by-side on the same dest to confirm identical behaviour.
