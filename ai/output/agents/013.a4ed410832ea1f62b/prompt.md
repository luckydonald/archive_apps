In the repo /Users/user/Documents/programming/Shell/archive_apps, I need to understand the CLI flag parsing conventions and RunContext/Config plumbing to plan adding a new flag.

Please investigate and report:

1. In archive_apps/cli.py: full contents of the `Config` dataclass, the `RunContext` dataclass, and `parse_args()`. List every existing flag (long form, short form if any, default value, help text) verbatim with line numbers.

2. How Config/RunContext values flow from parse_args() into archive_apps/archive.py's `run_archive` and into archive_apps/app_ops.py functions — i.e., is Config passed as a single object through the call chain, or are individual fields threaded through? Show the function signatures involved (run_archive, and whichever app_ops.py functions handle a single app's archiving/mismatch-resolution) with file:line.

3. Search the whole archive_apps/ package (grep) for any existing keyword/enum-like CLI flags (e.g. flags that take a fixed set of string choices via argparse `choices=[...]`) to see the established pattern for that style of flag, and how such a value is validated/typed (str, Enum, Literal, etc.) in cli.py.

4. Look at archive_apps/__main__.py for how RunContext is constructed and how signal/atexit handlers work, since a re-queue-at-end feature run after the main loop finishes will need to hook in somewhere before final cleanup/exit.

5. Check the test/ directory (currently untracked per git status) and any existing tests under a tests/ dir if present, to see if there's an existing test pattern for the mismatch-prompt logic that a future implementation should follow (just report what's there, don't run anything destructive).

Report file:line references and exact code quotes. Do not modify anything — read-only research only.