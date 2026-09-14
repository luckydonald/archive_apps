In the repo /Users/user/Documents/programming/Shell/archive_apps, I need a detailed understanding of the checksum-mismatch interactive prompt flow, so we can add a timeout-to-skip behavior with re-queueing, plus a preset flag.

Please investigate and report back with:

1. In archive_apps/io.py: the full implementation of `tty_read` and `write_fail_menu` — exact signatures, how they read from the terminal, whether there's any existing timeout support, and how the "[o]verwrite / [b]oth / [s]kip" menu text is currently rendered (exact wording/strings, file:line).

2. In archive_apps/app_ops.py (and archive.py if relevant): where the checksum-mismatch prompt is triggered — the full function(s) involved, how the user's choice ('o'/'b'/'s') is used to branch logic, especially the recent "[b]oth" behavior that was changed to add a "swap prompt" making the live-matching archive canonical and tagging the stale one `~hash-mismatch~` (see git log commit 9258b9a "mismatch handling: Added a swap prompt after [b]oth resolves a checksum mismatch"). Show exact code for this branch.

3. In archive_apps/archive.py: the `run_archive` main loop — how it iterates over apps (the `while`/`for` loop mentioned in CLAUDE.md), whether there's any existing concept of a queue, deferred list, or "process again at the end" pattern anywhere in the codebase (search app_ops.py, archive.py, __main__.py). Report exact loop structure and variable names.

4. In archive_apps/cli.py: the full `Config` dataclass and `parse_args()` function — all existing CLI flags, their names/patterns (to see the flag-naming convention, e.g. `--something`), and whether any flag already exists for presetting a mismatch resolution (e.g. something like `--on-mismatch`, `--mismatch-policy`, etc.) or any other "non-interactive default" flag pattern used elsewhere in the tool.

5. Check archive_apps/progress.py and io.py for any existing use of `select.select`, `signal.alarm`, or other timeout-capable input mechanisms in this codebase (needed for implementing a 60s timeout on a blocking terminal read).

Report file:line references and exact relevant code snippets/quotes for all of the above. Do not modify anything — this is read-only research.