# Make checksum verification symlink-aware and defensively handle escaping links

## Summary
- Fix the checksum mismatch by making zip and live-app manifest generation use the same object model: regular files plus symlink entries.
- Store symlink entries in the primary `.checksums.txt` going forward.
- Preserve compatibility with existing legacy checksum files that contain only regular files.
- Add defensive detection for symlinks whose resolved target escapes the `.app` bundle, and require an explicit user choice to continue.

## Key Changes
- Update manifest generation in [archive_apps.sh](/Users/user/Documents/programming/Shell/archive_apps/archive_apps.sh):
  - Live app manifest: include `find -type f` entries and `find -type l` entries.
  - Zip manifest: include regular file entries and zip symlink entries; do not treat symlinks as regular files.
  - Symlink checksum rule: hash the symlink target text returned by `readlink` as raw bytes, and emit the usual `sha256  relative/path` line.
  - Keep one canonical sort order by relative path so live and zip manifests compare byte-for-byte.
- Change fresh archive behavior:
  - Write `.checksums.txt` using the new symlink-aware manifest.
  - Post-archive verification compares the zip manifest against the live manifest in symlink-aware mode.
- Keep backward compatibility for existing archives:
  - When `.checksums.txt` matches the symlink-aware manifest, treat it as current format.
  - When it matches the legacy regular-files-only manifest, treat it as valid legacy format.
  - After a successful legacy match, rewrite `.checksums.txt` to the new symlink-aware format so old archives migrate forward opportunistically.
- Add defensive external-symlink detection:
  - Detect symlinks in live apps whose resolved target is outside the app root.
  - Detect equivalent symlink entries in zips during verification and recovery checks.
  - Treat escaping symlinks as unsafe and print each path, link target, and resolved target.
- Add a run-wide policy flag:
  - `--external-symlink-policy=skip|abort|archive`
  - `skip`: skip that app/archive and continue the run.
  - `abort`: stop the whole script immediately with non-zero exit.
  - `archive`: continue anyway and allow checksum/write/verify to proceed.
- Default behavior without the flag:
  - If interactive, prompt per affected app: `skip`, `abort`, or `archive anyway`, defaulting to `skip`.
  - If non-interactive, default to `skip`.

## Public Interfaces
- `.checksums.txt` changes semantics for newly written files: it now covers both regular files and symlink entries.
- Existing legacy `.checksums.txt` files remain readable and are auto-upgraded after a successful verification.
- New CLI option:
  - `--external-symlink-policy=skip|abort|archive`
- Update `--help` text to document the new option and its default behavior.

## Test Plan
- Fresh archive of `ntfy.app`: checksum file is written in symlink-aware format and immediate verification passes.
- Fresh archive of `Pages.app`: immediate verification passes despite framework symlinks.
- Fresh archive of `MQTT Explorer.app`: immediate verification passes and includes the Electron framework symlinks.
- Fresh archive of an app with no symlinks: checksum output stays stable and verification passes.
- Existing archive with legacy regular-files-only `.checksums.txt`: verification succeeds, then rewrites the checksum file to the new symlink-aware format.
- Existing archive already using the new format: verification succeeds and the checksum file is unchanged.
- App or zip containing an escaping symlink:
  - interactive run prompts with `skip`, `abort`, `archive`;
  - `skip` skips only that app;
  - `abort` exits non-zero;
  - `archive` proceeds;
  - non-interactive run skips by default.
- Verify/recovery/index flows still work when `.checksums.txt` is rewritten during migration.

## Assumptions
- Symlink support should live in the primary checksum file rather than a companion file.
- “Support symlinks” means preserving archive fidelity: verify the symlink object itself, not a dereferenced copy of its target file.
- Escaping symlinks are unusual and risky enough to require explicit opt-in before archiving or accepting them.
