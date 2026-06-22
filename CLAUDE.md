# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`archive_apps.sh` is a macOS-only Bash script that snapshots installed `.app` bundles from `/Applications` into versioned zip archives. It is intended to be run periodically so older app versions can be recovered after updates.

## Running the script

```bash
# Archive to default destination (/Users/Shared/App Versions)
./archive_apps.sh

# Archive to a custom destination
./archive_apps.sh /path/to/destination

# Stage zips on fast local disk, then copy to destination; local copy is retained
./archive_apps.sh --local-cache /Volumes/…/data

# --local-cache without a value defaults to /Users/Shared/App Versions
./archive_apps.sh --local-cache

# Disable local cache explicitly (same as omitting the flag)
./archive_apps.sh --local-cache=none /Volumes/…/data

# Help
./archive_apps.sh --help
```

No build step, no dependencies to install. Requires macOS (`ditto`, `PlistBuddy`, `shasum` are all system tools).

## Architecture / logic flow

The script processes each `*.app` under `/Applications` (up to depth 2) in a single `while` loop:

1. **Locate Info.plist** — checks `Contents/Info.plist` first; falls back to `WrappedBundle/Info.plist` for iOS-on-Mac apps (which get a `mobile@` infix in the filename).
2. **Derive name and version** from `CFBundleName` / `CFBundleShortVersionString` via `PlistBuddy`.
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