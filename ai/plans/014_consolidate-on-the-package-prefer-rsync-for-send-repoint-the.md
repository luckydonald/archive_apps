# Consolidate on the package: prefer `rsync` for SEND, repoint the Makefile, remove `archive_apps.py`

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

## Context

The repo holds two implementations of the same CLI: the package `archive_apps/` and the single file `archive_apps.py`.
The Makefile runs the single file (`Makefile:24`, `SCRIPT ?= …/archive_apps.py`), so every feature added to the package since `9a81b38` (swap prompt, timeouts and presets, Finder colors) never reached the user's normal workflow.
A read-only comparison of both implementations found the package to be a strict superset of the single file: nothing in the single file is missing from the package.
The user decided to keep only the package.
The user also wants `rsync` kept as the SEND method (local-cache to destination) when it is installed, since the package replaced it by a pure Python copy.

## Steps (one commit each, in this order)

1. **Prefer `rsync` for the SEND step** (`archive_apps/app_ops.py`, `archive_and_store_zip`).
   - When `cfg.local_cache` is set, `shutil.which("rsync")` is found and stderr is a tty, run `rsync --progress <tmp> <dest_tmp>` through `run_with_bar` with `ProgressBar("SEND", 100)` and `drain_rsync_file_stderr`; all three already exist in `progress.py` and `drain_rsync_file_stderr` is currently unused.
   - Without a tty run plain `rsync <tmp> <dest_tmp>` via `subprocess.run`, like the single file did.
   - If `rsync` is missing, or exits non-zero, fall back to the current `copy_with_progress` (tty) / `shutil.copy2` path, after removing a partial `dest_tmp`, and print one line saying it fell back.
   - Add a small helper `send_file(src, dst)` in `app_ops.py` so the choice is testable and `archive_and_store_zip` stays short.
   - Keep `rsync` out of the destination-less path (no local cache means a plain `shutil.move`, unchanged).
2. **Point the Makefile at the package.**
   - `Makefile:24` becomes `SCRIPT ?= -m archive_apps`-style invocation; concretely replace `"$(PYTHON)" "$(SCRIPT)"` in the six targets with `"$(PYTHON)" -m archive_apps` run from `$(SCRIPT_DIR)`, and drop the `SCRIPT` variable.
   - Check first whether the gitignored `.env.Makefile` sets `SCRIPT=` (the agent could not read it; ask the user to check or read it with permission), and mention `.env.Makefile.example`.
3. **Remove `archive_apps.py`** (`git rm`, recoverable from history; tag the prior HEAD with `scripts/tag_backup.py` first as usual).
4. **Fix docs and stale references.**
   - `CLAUDE.md`: drop line 23 (coexist/fallback), the `PlistBuddy (single-file …)` mention at line 49, and the "single-file does not implement this" sentence at line 65 in the Finder colors section; add the SEND/rsync note to the architecture section.
   - `.run/(default dir).run.xml` still points at the long-gone `archive_apps.sh`: report it to the user and ask whether to delete or repoint it (not touched unasked).
   - Memory: update `feedback_testing_archive_apps.md` and `project_checksum_index_concurrency_fix.md`, which still describe the single file (the import-shadowing gotcha goes away once the file is gone).
   - Leave `old/*.bak.sh` alone (CLAUDE.md says not to delete without confirmation).

## Behaviour differences to tell the user about (not changed in this plan)

- App discovery: `glob("**/*.app")` filtered to depth 2 walks the whole `/Applications` tree and includes symlinked `.app` dirs; the single file used `find -maxdepth 2 -type d`. Candidate follow-up: replace by a depth-limited walk.
- Size lines: `fmt_size` sums file bytes, the single file used `du -sh` (disk blocks).
- Verify modes: `sha256_file` raises on an unreadable file instead of returning an empty hash.
- The package exits 1 after verification failures, which fails a `make` target.
- The package uses `plistlib` instead of `PlistBuddy`.

## Tests

- New `tests/test_send_file.py`: `send_file` with a fake `rsync` on `PATH` (a tiny script that copies and prints `50%`/`100%`) succeeds and the destination matches; with no `rsync` on `PATH` the Python copy is used; with a failing fake `rsync` it falls back and leaves no partial file; non-tty uses plain `rsync`.
- Existing `tests/` stay green (`uv run --with pytest python -m pytest tests`).

## Verification

- Run the suite as above.
- `make -n archive` and `make -n verify-zips` to see the new command lines, then `make verify-zips` against the real destination (read-only verification) to confirm the Makefile works with the package.
- Manual `--local-cache` run with one app to see the rsync SEND bar, if the user wants a live check (it writes a zip into the destination).

## Open points

- `.env.Makefile` may still override `SCRIPT`; needs checking before step 2.
- The `sync_todo` MCP is still down, so this work has no todo to complete; it is a new topic and can be added as a todo once the MCP is back.
