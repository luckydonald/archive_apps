# Merge the `--verify-*` modes into the main run as staged steps

## Context

Today a normal run only archives (and verifies each new zip inline), while `--verify-zips/-new/-changed/-zip=APP` are separate programs that exit after verifying.
Goal: one run does everything in priority order, so current apps and their backups come first and the slow, thorough checks come last, where interrupting is cheap.
The old flags become aliases for selecting steps.

## Stages

A normal run executes these in order.
Each later stage is lower priority, so it is more acceptable to Ctrl-C it.

1. **archive**: the existing app loop (apps without a zip first, `archive.order_apps`).
   Creates missing zips and checksums, and compares existing zips against the live app as before.
   The inline post-creation verification is removed from this loop.
   Each created zip is recorded in `ctx.created` as a `VerifyMismatchTask`, which already holds every field needed.
2. **created**: verify the zips created in step 1 (extract manifest, compare with `live_checksums`, external-symlink check).
   Mismatch handling is unchanged: `_resolve_verify_mismatch` with retry/delete/keep, the 60s timeout and the deferral.
   Verified zips are appended to the index scratch file, so later stages skip them.
3. **changed**: zips whose index entry exists but whose current zip/checksums hash differs, then
4. **new**: zips (or checksums files) missing from `_checksum_index_.txt`, then
5. **rest**: all remaining zips, fully verified (extract and compare).

Stages 3 to 5 are today's `run_verify_all` body.
Within each stage, zips of currently installed apps come first, then the others in random order.
The random order means an interrupted stage 5 still makes progress across runs, like the earlier "random sort" todo.

Deferred prompts, zip colors and app marks run once, right after stage 2 (instead of at the very end).
Reason: stages 3 to 5 can take very long and are meant to be interruptible, and nothing user-facing should be lost when they are.
This deviates from "verify before the timeout-retry stuff", so say so if you want it the other way round.
Stages 3 to 5 only mark failures red directly (`set_finder_color`), as `--verify-*` does now.
The failure summary, external symlink summary and exit code 1 on failures stay at the very end, in a `finally`, so Ctrl-C still prints them.
The index merge on interrupt already works through `__main__._make_cleanup`, with `ctx.index_scratch` set for the whole run.

## Progress display

Plain text, no curses or cursor tricks.
A checklist is printed at the start and at each stage transition, and the stage details follow below it:

```
Steps:
  [x] 1 archive   12 created, 98 up to date
  [>] 2 created   3/12 …
  [ ] 3 changed
  [ ] 4 new
  [ ] 5 rest      (safe to interrupt)
```

Skipped steps show `[-]`.
`render_checklist(states)` is a pure function so it can be tested.

## CLI

- `--steps=archive,created,changed,new,rest` (default: all) and `--skip-steps=…` are the proper selection flags.
- Aliases, which select only those steps, as before:
  - `--verify-changed` = `changed`
  - `--verify-new` = `new`
  - `--verify-zips` = `changed,new,rest`, so every zip is checked, and without archiving.
  - `--verify-zip=APP` = `changed,new,rest` limited to the zips of that app or zip file (reuses `resolve_verify_zip_arg`), always fully verified and ignoring the index, as today.
- Several aliases combine as a union of steps, and the old "cannot be combined" error goes away.
- `--verify-abort` is unchanged.
- Update `--help`.

## Code changes

- `cli.py`: replace `verify_mode`/`verify_zip_arg` with `steps: frozenset[str]` and `verify_target: str`. Add `ctx.created`.
- `verify.py`:
  - Split `run_verify_all` into `open_index_scratch(ctx)` (leftover recovery and `mkstemp`), `classify_zips(zips, index, ...)` (pure: changed/new/rest, installed apps first) and `verify_one_zip(zip_path, ctx, index_tmp)`.
  - Delete `run_verify_zip` and the `sys.exit` calls at the end of the verify runs.
  - Keep `merge_checksum_index`.
- `archive.py`: drop the inline verify block and record the task in `ctx.created`. Add `verify_created(ctx)`. Make `run_archive` return instead of finishing the run.
- New `steps.py`: `run_steps(ctx)` as the orchestrator (checklist, ordering, `finally` summaries and exit code). `__main__.main` calls it.
- `CLAUDE.md`: update the package layout, the logic flow and the flags.

## Tests (`tests/`, run with `uv run --with pytest python -m pytest tests`)

- Step parsing: defaults, `--skip-steps`, each alias, and alias unions.
- `classify_zips`: changed/new/rest split and installed-apps-first ordering, with a fake index.
- `render_checklist` output.
- Orchestrator: with the verify functions stubbed, stages run in order, skipped stages are not called, and a failure gives exit code 1 plus the summary.
- Existing tests (`test_app_order`, `test_termination`, …) must stay green.

## Verification

- Full pytest run.
- Manual run against a scratch destination (`./main.py /tmp/dest`, with `--steps=changed,new,rest` and `--verify-zip=Xcode` against a copy of a few zips), checking the order, the checklist and a Ctrl-C during stage 5 (summary printed, index merged).
- The untracked `test/` directory in the repo is not part of this and is left alone.

## Commits

Plain commits per logical step (CLI and steps, verify split, orchestrator, tests and docs), then the usual backup tag and squash into one work commit.
