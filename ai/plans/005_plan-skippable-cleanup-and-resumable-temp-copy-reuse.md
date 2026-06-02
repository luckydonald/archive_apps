# Plan: Skippable Cleanup and Resumable Temp Copy Reuse

## Summary
Add a `--keep-temp` flag that preserves end-of-run temp state needed for resume, then switch archive temp-copy handling from random `mktemp` directories to deterministic work directories keyed by the app’s actual content manifest hash. Reuse happens by repairing an existing temp copy instead of recopying everything, using `rsync` to fix missing, wrong, and extra files before zipping.

## Key Changes
- Extend CLI parsing and `--help` output with `--keep-temp`.
- Split current `cleanup()` into two behaviors:
  - Always keep output-finalization behavior that promotes `_checksum_index_.txt.tmp` into `_checksum_index_.txt` on normal exit.
  - Make deletion behavior conditional on `--keep-temp`, so `.archive_apps.*` work dirs and leftover `*.tmp` siblings are preserved when requested.
- Replace random temp workdir creation in `_archive_app_to_zip()` with a deterministic workdir name derived from:
  - the archive stem / versioned app name for readability
  - a SHA-256 of `live_checksums` for actual-content identity
- Use a stable workdir pattern like `"$dest/.archive_apps.${zip_stem}.${manifest_hash}"`.
- Refactor archive creation so the live manifest is computed before choosing the temp workdir, then passed into the archive step instead of being recomputed ad hoc.
- Change copy behavior:
  - If the deterministic workdir does not exist, keep the current fast initial copy path (`cp -cR` on same device, fallback path otherwise).
  - If the workdir exists, repair it in place with `rsync -a --delete --extended-attributes --itemize-changes "$app/" "$workdir/$versioned/"`.
  - If the preserved workdir exists but its root app dir is missing, misnamed, or obviously unusable, recreate just that root inside the same deterministic workdir and continue.
- Keep zipping behavior unchanged apart from using the deterministic workdir as the source.
- Apply the same reusable-copy path to every archive-writing branch:
  - new archive creation
  - overwrite existing zip after mismatch
  - create “both” timestamped duplicate
- Preserve current default behavior when `--keep-temp` is not passed: temp workdirs are removed at exit, so the feature is opt-in only.

## Public Interface Changes
- New option: `--keep-temp`
  - Meaning: preserve temp workdirs and leftover `*.tmp` artifacts after the run so aborted copy work can be resumed later.
  - Default remains cleanup-on-exit.
- No archive naming changes.
- Internal temp naming becomes deterministic and content-based rather than random, but this is not a user-facing output contract beyond what `--keep-temp` exposes.

## Test Plan
- Help text shows `--keep-temp` and existing options still parse correctly.
- Default run still removes `.archive_apps.*` workdirs after a successful archive.
- `--keep-temp` preserves the deterministic workdir after a successful archive.
- With `--keep-temp`, abort during copy, rerun, and confirm the second run repairs/reuses the existing workdir instead of starting from a fresh random directory.
- Manually corrupt the preserved temp copy by deleting one file, changing one file, and adding one extra file; rerun and confirm `rsync` repairs all three cases and the resulting zip still verifies against the live manifest.
- Change the source app so its manifest changes; rerun and confirm a new deterministic workdir is selected and the old preserved workdir is ignored rather than reused incorrectly.
- Exercise overwrite and “both” branches to confirm they also use the resumable temp-copy path.

## Assumptions and Defaults
- “Actual hash” means hashing the existing full manifest text (`live_checksums`) with `_sha256_text`, not hashing the app bytes a second time.
- `rsync` is used for selective repair because the local `openrsync` supports the needed flags; this avoids custom file-diff logic.
- `--keep-temp` skips deletion only. It does not disable normal output finalization such as writing the checksum index.
- Leftover `.zip.tmp` and `.checksums.txt.tmp` files are preserved under `--keep-temp` but are not reused as authoritative inputs for future archive creation.
- Legacy random `.archive_apps.*` directories do not need migration logic; new deterministic ones are the only reusable workdirs.
