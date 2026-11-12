# Colorize archived zips with Finder labels

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

## Context

Todo: "use xattr or something to colorize the zip files".
The user decided the meaning: green = current version and verified, gray = old version and verified, red = mismatch.
The mechanism is the native Finder label, written as `com.apple.FinderInfo` through ctypes (`utils.supports_xattr` already uses libc `setxattr`, so there is no new dependency).
Todo 2 (colors on the real app) and todo 3 (random sort, already done by `random.shuffle(apps)` in `archive.py:145`) are out of scope; I will report that todo 3 looks already done instead of ticking it.

## Design

New helpers in `archive_apps/utils.py`:

- `FinderColor` constants: gray=1, green=2, red=6 (label value; the byte stores it shifted left by one).
- `set_finder_color(path, color) -> bool`: reads the existing 32-byte `com.apple.FinderInfo` with `getxattr` (zeros if absent), replaces bits 1-3 of byte 9 and keeps all other bits, writes it back with `setxattr`.
  Returns `False` and stays silent on `ENOTSUP`, `ENOENT` or `EPERM` (ExFAT/network mounts), since a color is cosmetic and must never abort a run.
  Skips the call when the value is already right, so network filesystems are not written on every run.

Wiring in `archive_apps/archive.py` (`run_archive`), keyed by zip name in a new `ctx.zip_colors: dict[str, FinderColor]` and `ctx.seen_zipnames: set[str]` (fields on `RunContext` in `cli.py`):

- Every zip of the current run is added to `seen_zipnames`, including skipped ones.
- Verified paths set green: existing zip + checksum verified (`archive.py:201`), checksum written after a matching zip (`:237`), new zip created and matching (`:269`), and the retry success branch in `_resolve_verify_mismatch` (`:124`).
- Mismatch paths set red on the first report and are corrected afterwards when the resolution makes the zip match: the overwrite/both outcomes in `_resolve_mismatch` become green, keep/skip stay red, delete removes the file.
  Deferred prompts are resolved at the end of the run, so colors are applied in a final pass over `ctx.zip_colors` after the deferred resolution, not inline.
- Final pass at the end of `run_archive`, before the summaries: apply `ctx.zip_colors`, then gray every other `*.zip` in `cfg.dest` that has a matching `.checksums.txt` and is not in `seen_zipnames` (old versions of apps, which were verified when they were archived).
  Zips without a checksums file stay uncolored.
- Also apply the colors in `run_verify_zip` and `run_verify_all` (`verify.py`) when they verify a zip: green on success, red on failure.
- Mirror the same helper and calls in the single-file `archive_apps.py`, which is kept in sync as the fallback.

## Tests

New `tests/test_finder_color.py` (the `test/` dir is untracked user data, so tests go in `tests/`):

- Encode/decode round trip on a tmp file: color bits set, other FinderInfo bytes preserved, repeated call is a no-op.
- `set_finder_color` returns `False` without raising on a missing file.
- The final pass colors current zips green, a mismatch red, and an unseen zip with checksums gray, and leaves one without checksums alone (uses a fake `RunContext`/tmp dest).
- The single-file module imports with the same helper (import-shadowing gotcha from memory: import explicitly by path).

## Verification

- `uv run pytest tests`, plus the project lint if `Makefile` defines one.
- Manual run against a tmp dest with one real app copy, then `xattr -px com.apple.FinderInfo <zip>` and `mdls`/Finder to see the label.
- Update the `CLAUDE.md` package layout/notes: mention the colors and the `utils.py` helper.

## Open points to report

- The `sync_todo` MCP failed to connect and the sync script reported `SYNC_TODO_MCP_URL / SYNC_TODO_MCP_TOKEN not set`, so the todo cannot be completed on CalDAV from this run; I will tick the checkbox locally and say so.
