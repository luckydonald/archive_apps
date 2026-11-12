# Mark the live apps with a Finder comment and color

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

## Context

Todo: "write to the description of the real app file, when it was last updated. Also set the color to red if never was updated, orange if an old version is updated, and green if it is the current version and the hashes matches. If there's a mismatch, gray."
Answers from the user: the comment holds the date of the backup and the success state, a checksum mismatch is orange too (so gray is not used for apps), writing to the live app is best effort.
Today only the zips in the destination get Finder colors (`archive.apply_zip_colors`, `utils.set_finder_color`); the apps in `/Applications` are untouched.
The sync of todos failed this session (no `ai/.env`, `sync_todo` MCP down), so the todo is taken from the local `ai/todos.md` and must be completed on CalDAV afterwards.

## Behaviour

Per archived app (those with an `Info.plist`), after the deferred prompts are resolved, mark the `.app` bundle:

| State | Color | Comment |
|-------|-------|---------|
| Zip of the installed version exists and its final zip color is green | green | `archive_apps: backed up <YYYY-MM-DD HH:MM> (version X), verified` |
| Final zip color is red (checksum mismatch, left unresolved) | orange | `archive_apps: backed up <date> (version X), checksum MISMATCH` |
| No zip of the installed version, but zips with a `.checksums.txt` of other versions exist | orange | `archive_apps: version X not backed up; newest backup is <older version> from <date>` |
| No zip of this app at all (or the run skipped it) | red | `archive_apps: never backed up` |

"Date of backup" is the mtime of the zip in the destination (newest one for the old-version case).
Finder comment is `com.apple.metadata:kMDItemFinderComment`, a binary plist holding a string.
It is only overwritten when it is empty or already starts with `archive_apps:`, so a comment the user wrote is never destroyed.
Every failure (permissions on `/Applications`, no xattr support) is silent, like `set_finder_color`.
New flag `--no-mark-apps` turns the marking off (Config field `mark_apps`, default on).

## Files

- `archive_apps/utils.py`: add `FINDER_ORANGE = 7`, `set_finder_comment(path, text) -> bool` and `get_finder_comment(path) -> str | None` (ctypes `setxattr`/`getxattr` like the color helpers, `plistlib` binary format).
- `archive_apps/cli.py`: `Config.mark_apps`, `--no-mark-apps`; `RunContext.app_zips: dict[Path, tuple[str, str, str, str]]` (app → name, mobile, version, zipname).
- `archive_apps/archive.py`: record `ctx.app_zips[app]` right after `zipname` is derived in `run_archive`; new `apply_app_marks(ctx)` called after `apply_zip_colors(ctx)`; pure helper `app_mark_state(...)` that returns `(color, comment)` from the final `ctx.zip_colors`, the zip's mtime and the destination glob `{name}.app@{mobile}*.zip` (only with a matching checksums file, skipping `~` duplicates), so it is unit-testable.
- `CLAUDE.md`: extend the "Finder colors" section with the app marks.
- `tests/test_app_marks.py`: state table (green, mismatch → orange, old version → orange, none → red), comment is not overwritten when foreign, is replaced when ours, round trip of `set_finder_comment`/`get_finder_comment` on a tmp file.

## Out of scope

The second open todo (random sort) looks already done: `run_archive` calls `random.shuffle(apps)`.
It gets its own run, which will verify that and tick it.

## Verification

- `uv run --with pytest python -m pytest tests`.
- Run against a scratch destination with a copy of a small app to check the Finder label and comment (`xattr -p com.apple.metadata:kMDItemFinderComment`), and `--no-mark-apps` leaving the app untouched.
