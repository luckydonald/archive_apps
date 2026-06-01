# Make checksum verification symlink-aware and warn on escaping links

## Summary
- Fix the checksum mismatch by making zip and live-app manifest generation cover the same object set: regular files plus symlink entries.
- Keep archive creation as-is: preserve symlinks as symlinks, not dereferenced copies.
- Detect symlinks whose resolved target escapes the `.app` bundle, but default to archiving anyway.
- Improve readability by collecting those warnings and printing a consolidated end-of-run summary instead of only noisy inline output.

## Key Changes
- Update manifest generation in [archive_apps.sh](/Users/user/Documents/programming/Shell/archive_apps/archive_apps.sh):
  - Live app manifest includes `find -type f` and `find -type l`.
  - Zip manifest includes regular file entries and zip symlink entries, skipping directories and `__MACOSX`.
  - Symlink checksum rule: hash the symlink target text from `readlink` as raw bytes and emit `sha256  relative/path`.
  - Sort all manifest lines by relative path so live and zip manifests compare byte-for-byte.
- Change `.checksums.txt` semantics going forward:
  - Newly written files are symlink-aware.
  - Existing legacy files that contain only regular files remain accepted.
  - After a successful legacy verification, rewrite `.checksums.txt` to the symlink-aware format so archives migrate forward automatically.
- Add escaping-symlink detection:
  - For live apps, resolve each symlink and detect targets outside the app root.
  - For zip verification, inspect symlink entries and detect escaping targets relative to the archived app root.
  - Continue archiving/verifying by default, but record each affected app and symlink for a final warning summary.
- Add run-wide policy flag:
  - `--external-symlink-policy=archive|skip|abort`
  - `archive` is the default.
  - `skip` skips affected apps.
  - `abort` stops the run on the first affected app.
- Default behavior without the flag:
  - Interactive and non-interactive runs both default to `archive`.
  - Inline logging for escaping symlinks should stay brief.
  - At the end of the run, print a clear summary block listing every app that had escaping symlinks, with each path, link target, and resolved target.

## Public Interfaces
- `.checksums.txt` becomes symlink-aware for newly written files.
- Existing legacy `.checksums.txt` files remain readable and are auto-upgraded after successful verification.
- New CLI option:
  - `--external-symlink-policy=archive|skip|abort`
- Update `--help` text to document the option and that the default is `archive` with an end-of-run warning summary.

## Test Plan
- Fresh archive of `ntfy.app`, `Pages.app`, and `MQTT Explorer.app`: immediate verification passes and `.checksums.txt` includes symlink entries.
- Fresh archive of an app with no symlinks: verification still passes and checksum output remains stable.
- Existing archive with legacy regular-files-only `.checksums.txt`: verification succeeds, then rewrites the checksum file to the symlink-aware format.
- Existing archive already using the new format: verification succeeds and the checksum file is unchanged.
- App containing an escaping symlink:
  - default run archives it and emits only a concise inline notice;
  - end-of-run summary lists the escaping symlink details;
  - `--external-symlink-policy=skip` skips it;
  - `--external-symlink-policy=abort` exits non-zero immediately.

## Assumptions
- The primary checksum file should represent the actual archived object graph, including symlinks.
- Escaping symlinks are unusual enough to warrant explicit reporting, but not severe enough to block archival by default.
- End-of-run aggregation is preferred over repeated per-app warning noise for readability.
