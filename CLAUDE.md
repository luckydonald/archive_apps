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

The Python package `archive_apps/` is the only implementation. The original `archive_apps.sh` Bash version and the later single-file `archive_apps.py` have been removed (the latter was dropped on 2026-11-12 after it had fallen behind the package; the `Makefile` runs the package via `-m archive_apps`).

### Package layout

```
archive_apps/
  __main__.py   entry point, RunContext setup, atexit/signal
  cli.py        Config dataclass, RunContext dataclass, parse_args()
  utils.py      fmt_size, fmt_duration, sha256_text, sha256_file, sanitize_temp_component, set_finder_color
  progress.py   ProgressBar, drain functions, run_with_bar, copy_with_progress
  io.py         tty_read, write_fail_menu, safe_write, safe_append, safe_mv, rm_retry
  zip_ops.py    checksums_from_zip, external_symlinks_from_zip, count_symlinks_from_zip
  app_ops.py    collect_app_manifest, copy_app_fresh, archive_and_store_zip, …
  verify.py     verify_one_zip, classify_zip, checksum index (open_index_scratch, merge_checksum_index), symlink summaries
  filters.py    `--app` filter matching for zips and live apps
  steps.py      run_steps: the staged orchestrator, render_checklist, verify_changed
  archive.py    plist_value (plistlib), run_archive (step 1), verify_created (step 2), finalize_archive
main.py         thin shebang wrapper → archive_apps.__main__:main
pyproject.toml  [project.scripts] archive-apps = "archive_apps.__main__:main"
```

## Steps

One run executes up to five steps in priority order, a plain-text checklist (`steps.render_checklist`) is printed at each transition.

1. `archive`: the app loop described below. New zips are only recorded in `ctx.created`, not verified inline.
2. `created`: `archive.verify_created` compares each new zip with the live app (mismatch: retry/delete/keep prompt, see `--on-verify-mismatch`).
   Deferred prompts, zip colors and app marks (`archive.finalize_archive`) run right after this step, so later interrupts lose nothing.
3. `changed`: zips whose hash differs from `_checksum_index_.txt`.
4. `new`: zips not in the index yet.
5. `rest`: every other zip, fully verified (slow, safe to interrupt).

Steps 3 to 5 handle zips of installed apps first, then the others, each group in random order; zips verified earlier in the run are skipped.
`--steps=LIST` / `--skip-steps=LIST` select steps, `--app=APP` limits everything to one app or zip, `--force-full` ignores the index.
`--verify-zips`, `--verify-new`, `--verify-changed` and `--verify-zip=APP` are aliases that select only their steps.
The failure and symlink summaries are printed in a `finally`, and the exit code is 1 when a verification failed.

## Architecture / logic flow

The script processes each `*.app` under `/Applications` (up to depth 2) in a single `while` loop.
The order comes from `archive.order_apps`: apps without a zip for their installed version in the destination first, then the rest, then apps without an Info.plist, each group in random order.

1. **Locate Info.plist** — checks `Contents/Info.plist` first; falls back to `WrappedBundle/Info.plist` for iOS-on-Mac apps (which get a `mobile@` infix in the filename).
2. **Derive name and version** from `CFBundleName` / `CFBundleShortVersionString` via `plistlib`.
3. **Check if zip already exists** at `{dest}/{AppName}.app@[mobile@]{version}.zip`:
   - If the zip exists and a matching `.checksums.txt` also exists → skip entirely.
   - If the zip exists but the checksums file is missing → extract the zip to a temp dir, compute checksums for both the extracted copy and the live app, compare:
     - Equal → write the checksums file.
     - Mismatch → prompt interactively: **[o]verwrite** the zip (replace with current live app), **[b]oth** (keep existing zip + write new zip with a timestamp suffix), or **[s]kip**.
4. **Archive a new app** — copies the live `.app` into a temp dir (renamed to `{AppName} {version}.app`), zips it with `ditto -c -k --sequesterRsrc --keepParent`, then writes checksums.

**Local cache**: with `--local-cache`, new zips are built on local disk and then sent to the destination by `app_ops.send_file`, which uses `rsync` when installed and falls back to a Python copy.

**Atomic writes**: every output file is first written to a `.tmp` sibling and then `mv`'d into place. A `trap cleanup EXIT` removes any leftover `.tmp` files on exit.
A failed write names its cause in the write-error menu; a full disk (`ENOSPC`/`EDQUOT`) is reported as `NO SPACE LEFT` with the free space (`io.describe_failure`), and failed `ditto`/`send_file` calls print the same hint when the disk is nearly full (`io.report_if_disk_full`).

## Prompts

Every interactive question goes through `io.tty_read` / `io.tty_read_timeout`, which call `io.alert_user` first: a terminal bell, plus an iTerm2 Dock bounce (`OSC 1337;RequestAttention=once`) when `TERM_PROGRAM` is `iTerm.app`.
It is only sent when `/dev/tty` can be opened, so unattended runs stay silent.
`--no-beep` disables it (`Config.beep`, applied via `io.set_beep` in `__main__`).

## Finder colors

Zips in the destination get a Finder color label (`com.apple.FinderInfo`, `utils.set_finder_color`; silently skipped on filesystems without xattr support).
Green = zip of the installed version and verified against the live app, red = checksum mismatch, gray = zip of another version that has a checksums file.
Colors are collected in `ctx.zip_colors` during the run and applied once at the end by `archive.apply_zip_colors`, after deferred prompts are resolved.
The `--verify-*` modes only mark failures red.

The live apps in `/Applications` get a Finder color and a Finder comment (`kMDItemFinderComment`) too, from `archive.apply_app_marks` after the zip colors (best effort, `--no-mark-apps` disables it).
Green = zip of the installed version verified, orange = only older versions backed up, red = checksum mismatch or never backed up.
The comment (`archive_apps: backed up <date> …`) is only replaced when empty or already ours, so a user's own comment is kept.

## Naming conventions

| File | Pattern |
|------|---------|
| Zip archive | `{CFBundleName}.app@{version}.zip` |
| Mobile/iOS-on-Mac zip | `{CFBundleName}.app@mobile@{version}.zip` |
| Checksums | same stem, `.checksums.txt` |
| Timestamp-suffixed duplicate | `{stem}~{YYYYMMDD_HHMMSS}.zip` |

## Backup files

The `*.bak.sh` files are dated snapshots of the script at earlier points in its development. They are not executed; they serve as a changelog. Do not delete them without user confirmation.
