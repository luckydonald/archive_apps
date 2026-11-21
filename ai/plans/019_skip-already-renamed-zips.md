# skip already renamed zips

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

Todo `9d65516d-d00e-47a5-ba2b-bfdf64ed2c32`, quoted in full:

> skip already renamed zips
>
> ```
> RESOLVING: Telegram 13.2.0
> [o]verwrite zip / [b]oth (version previous) / [s]kip: _
> ```

## Context

When the canonical zip `Telegram.app@13.2.0.zip` does not match the live app, `archive.run_archive` creates a `MismatchTask` and asks `[o]verwrite / [b]oth / [s]kip`.
Answering `[b]oth` writes a second zip `Telegram.app@13.2.0~<YYYYMMDD_HHMMSS>.zip` (with checksums) that matches the live app.
If the follow-up swap question is declined, or the prompt timed out and is re-asked at the end, the canonical zip stays mismatching.
The next run therefore asks the same question again, although the live app is already backed up under the renamed (timestamp-suffixed) zip.

## Findings

- `archive._resolve_mismatch` is the only place that prompts, called from both mismatch branches of `run_archive` and from `finalize_archive` for deferred tasks.
- `utils.tagged_names` builds the suffixed names; the swap flow uses `~hash-mismatch~<ts>` for the old content, which must not count as a match.
- `MismatchTask.live_checksums` already holds the live manifest, so no extra hashing is needed.

## Change

- New helper `find_renamed_match(dest, task) -> str | None` in `archive_apps/archive.py`.
  It globs `{name}.app@{mobile}{version}~*.checksums.txt`, skips names containing `~hash-mismatch~`, requires the sibling `.zip` to exist, and compares the checksums file (trailing newline stripped) with `task.live_checksums`.
  Returns the zip name of the first match.
- At the top of `_resolve_mismatch`, before any prompt or preset: if a match is found, print `SKIPPED: already archived as <zipname>`, set `ctx.zip_colors[match]` to green, add it to `ctx.seen_zipnames`, and return.
  The canonical zip stays red, as it really mismatches; nothing is deleted or renamed.
- Update `CLAUDE.md` ("Architecture / logic flow", step 3) with one line about this skip.

## Tests

`tests/test_renamed_skip.py`, in a tmp dest dir:

- a suffixed zip + matching checksums → helper returns it, `_resolve_mismatch` does not prompt (patch `tty_read` to raise) and marks it green.
- suffixed zip with different checksums → no match, prompt still happens.
- `~hash-mismatch~` zip with matching checksums → ignored.
- suffixed checksums without the zip → ignored.

## Verification

`uv run --with pytest python -m pytest tests`, plus a manual dry check of the helper against a hand-built dest dir.

## Leftover

The live app's Finder mark (`app_mark_state`) still reads the canonical zip's color, so it stays red until the swap is accepted; not changed here.
