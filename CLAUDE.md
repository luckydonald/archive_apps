# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A macOS-only tool that snapshots installed `.app` bundles from `/Applications` into versioned zip archives. It is intended to be run periodically so older app versions can be recovered after updates.

## Running the Python package

```bash
# Run directly (uv auto-installs Python if needed)
./main.py [options] [destination]

# Run as a module
python -m archive_apps [options] [destination]

# Install as a tool (then use 'archive-apps' from anywhere)
uv tool install .
archive-apps [options] [destination]
```

The package (`archive_apps/`) and the single-file version (`archive_apps.py`) coexist; both implement the identical CLI. `archive_apps.py` is kept as a standalone fallback.

(The original `archive_apps.sh` Bash implementation has been removed — the Python package is the actively developed version going forward.)

### Package layout

```
archive_apps/
  __main__.py   entry point, RunContext setup, atexit/signal
  cli.py        Config dataclass, RunContext dataclass, parse_args()
  utils.py      fmt_size, fmt_duration, sha256_text, sha256_file, sanitize_temp_component
  progress.py   ProgressBar, drain functions, run_with_bar, copy_with_progress
  io.py         tty_read, write_fail_menu, safe_write, safe_append, safe_mv, rm_retry
  zip_ops.py    checksums_from_zip, external_symlinks_from_zip, count_symlinks_from_zip
  app_ops.py    collect_app_manifest, copy_app_fresh, archive_and_store_zip, …
  verify.py     verify_checksum_file_contents, run_verify_zip, run_verify_all
  archive.py    plist_value (plistlib), run_archive
main.py         thin shebang wrapper → archive_apps.__main__:main
pyproject.toml  [project.scripts] archive-apps = "archive_apps.__main__:main"
```

## Architecture / logic flow

The script processes each `*.app` under `/Applications` (up to depth 2) in a single `while` loop:

1. **Locate Info.plist** — checks `Contents/Info.plist` first; falls back to `WrappedBundle/Info.plist` for iOS-on-Mac apps (which get a `mobile@` infix in the filename).
2. **Derive name and version** from `CFBundleName` / `CFBundleShortVersionString` via `plistlib` (Python package) or `PlistBuddy` (single-file `archive_apps.py`).
3. **Check if zip already exists** at `{dest}/{AppName}.app@[mobile@]{version}.zip`:
   - If the zip exists and a matching `.checksums.txt` also exists → skip entirely.
   - If the zip exists but the checksums file is missing → extract the zip to a temp dir, compute checksums for both the extracted copy and the live app, compare:
     - Equal → write the checksums file.
     - Mismatch → prompt interactively: **[o]verwrite** the zip (replace with current live app), **[b]oth** (keep existing zip + write new zip with a timestamp suffix), or **[s]kip**.
4. **Archive a new app** — copies the live `.app` into a temp dir (renamed to `{AppName} {version}.app`), zips it with `ditto -c -k --sequesterRsrc --keepParent`, then writes checksums.

**Atomic writes**: every output file is first written to a `.tmp` sibling and then `mv`'d into place. A `trap cleanup EXIT` removes any leftover `.tmp` files on exit.

## Naming conventions

| File | Pattern |
|------|---------|
| Zip archive | `{CFBundleName}.app@{version}.zip` |
| Mobile/iOS-on-Mac zip | `{CFBundleName}.app@mobile@{version}.zip` |
| Checksums | same stem, `.checksums.txt` |
| Timestamp-suffixed duplicate | `{stem}~{YYYYMMDD_HHMMSS}.zip` |

## Backup files

The `*.bak.sh` files are dated snapshots of the script at earlier points in its development. They are not executed; they serve as a changelog. Do not delete them without user confirmation.
