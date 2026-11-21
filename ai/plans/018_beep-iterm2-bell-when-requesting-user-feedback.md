# Beep (iTerm2 + bell) when requesting user feedback

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

Todo: `80c6788f-79fd-4b48-91ee-ddb8b7835b36` (calendar 7, tags `archiveApps`, `python`, `programming`).

## Context

A run can sit on a prompt (verify mismatch menu, write-failure menu, hash-mismatch swap) while the user is in another window.
The prompt should get their attention with the terminal bell, and in iTerm2 with a Dock bounce.

## Findings

- Every interactive prompt goes through `tty_read` or `tty_read_timeout` in `archive_apps/io.py` (callers: `archive.py` `_prompt_with_optional_timeout`, `verify.py` mismatch menu, `write_fail_menu`).
  Both already open `/dev/tty` and silently fall back to the default when that fails, so a notification placed right after that `open` only fires when someone can actually answer.
- There is no existing bell or escape-sequence code.
- Flags are parsed by hand in `cli.py` (`--no-mark-apps` is the pattern to copy) and stored on the `Config` dataclass.
  `tty_read` has no access to `ctx`, so the setting needs to be module-level state.

## Changes

1. `archive_apps/io.py`: add `alert_user(tty)`.
   - Writes `\a` (BEL) to the `/dev/tty` handle, which has to be opened for writing (`"r+"`), so the bell still works when stderr is redirected.
   - If `os.environ.get("TERM_PROGRAM") == "iTerm.app"`, additionally writes `\033]1337;RequestAttention=once\a`, which bounces the Dock icon once.
   - Does nothing when disabled.
   - Add module state `_beep_enabled = True` plus `set_beep(enabled: bool)`.
   - Call `alert_user` in `tty_read` and `tty_read_timeout` right before the prompt is written.
2. `archive_apps/cli.py`: `Config.beep: bool = True`, flag `--no-beep` (help line next to `--no-mark-apps`).
3. `archive_apps/__main__.py`: call `io.set_beep(cfg.beep)` after parsing.
4. `CLAUDE.md`: one short paragraph under the architecture notes, saying prompts beep and that `--no-beep` disables it.

## Tests

New `tests/test_alert.py`, no real tty needed:

- `alert_user` on a `StringIO`: BEL only for a generic terminal, BEL plus the iTerm2 sequence with `TERM_PROGRAM=iTerm.app`, nothing after `set_beep(False)`.
- `parse_args(["--no-beep", ...])` sets `cfg.beep` to `False`, the default is `True`.
- `tty_read` with `builtins.open` monkeypatched to a fake tty: the bell is written before the prompt, and the answer still comes back.

Run the whole suite with `uv run --with pytest python -m pytest tests`.

## Verification

- The test suite above.
- Manual: run `./main.py` against a destination that triggers a prompt, in iTerm2 and in Terminal.app, and confirm the bell, the Dock bounce in iTerm2, and silence with `--no-beep`.
  I can't observe sound or Dock bounces from this session, so this one is yours.

## Notes

- Project `archiveApps` has no `path` in `sync_todos.local.json`, so the todo never reached `ai/todos.md`.
  On close I tick it on CalDAV with `complete_todo` and leave the sync config alone unless you tell me to add a path.
