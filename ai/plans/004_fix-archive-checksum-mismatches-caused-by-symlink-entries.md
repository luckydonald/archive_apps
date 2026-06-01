# Fix archive checksum mismatches caused by symlink entries

## Summary
- Root cause: the script compares two different manifest scopes.
- The live-app manifest is built with `find -type f`, so it includes only regular files.
- The zip manifest from `checksums_from_zip` currently includes non-directory zip entries, which also picks up symlink entries.
- This is why fresh archives fail verification even when the archive itself is correct. I verified that for `ntfy.app`, extracting the zip and hashing regular files matches the live app; the mismatch comes from the extra zip entry `WrappedBundle`, which is a symlink.
- `Pages.app` is not a counterexample: it has many symlinks under `Contents/Frameworks`, so it fails for the same reason.

## Key Changes
- In [archive_apps.sh](/Users/user/Documents/programming/Shell/archive_apps/archive_apps.sh), split manifest generation into two explicit modes:
  - `files`: regular files only.
  - `files+symlinks`: regular files plus symlink entries.
- Keep the existing `{stem}.checksums.txt` semantics as `files` mode for compatibility.
- Add a second companion file for the symlink-aware manifest: `{stem}.checksums.symlinks.txt`.
- Update live-app manifest generation:
  - `files`: keep the current `find -type f` behavior.
  - `files+symlinks`: additionally collect `find -type l` entries, hash the symlink target bytes from `readlink`, and emit the same `sha256  relative/path` line format.
- Update `checksums_from_zip`:
  - Detect symlink entries from `ZipInfo.external_attr >> 16`.
  - `files`: skip symlink entries entirely.
  - `files+symlinks`: hash the symlink payload bytes and include them in the manifest.
- On fresh archival, write and verify both checksum files.
- On existing archives:
  - If only `.checksums.txt` exists, keep verifying it as-is.
  - If `.checksums.symlinks.txt` is missing, backfill it only after a successful live-vs-zip comparison in symlink-aware mode.
- Keep `_checksum_index_.txt` behavior unchanged except that it should also index the new symlink-aware checksum file when present.

## Public Interface
- Existing checksum filename stays unchanged: `{stem}.checksums.txt`.
- New companion checksum filename: `{stem}.checksums.symlinks.txt`.
- No CLI flags are added; the script maintains both checksum modes automatically.

## Test Plan
- Archive `ntfy.app` into a fresh destination and confirm:
  - both checksum files are written;
  - immediate post-archive verification passes.
- Archive `Pages.app` into a fresh destination and confirm:
  - both checksum files are written;
  - immediate post-archive verification passes.
- Archive an app with no symlinks and confirm both verification paths pass.
- Re-run the script on an existing archive that has only `.checksums.txt` and confirm:
  - no false mismatch prompt;
  - legacy checksum file is not rewritten unnecessarily;
  - symlink-aware checksum file is backfilled only after successful verification.
- Re-run on an archive that already has both checksum files and confirm both remain stable through normal verify and overwrite/both/skip flows.

## Assumptions
- `.checksums.txt` must remain backward-compatible and continue to mean “regular files only”.
- The new symlink-aware file uses the `.checksums.symlinks.txt` suffix.
- Locale-based ordering of checksum lines is left unchanged for compatibility with existing checksum files.
