# Plan: three open `base` todos

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

## Context

`/todo-loop` normally does one todo per run.
This run was asked to plan all three open todos of `base` at once (`ai/°base/todos.md`), so each gets its own work commit, in the order below.
The fourth open item (`7f19ba8b`, "Once the `# end if` plugin is released…", prio 9) is blocked on an external release and stays untouched.

## Todo 1: Disallow `find / …` (`8c6ed776`)

Findings:

- Already done in `aa1f5ada1`: `ai/settings/settings.json:399-400` denies `find /` and `find / :*`, and the generated `.claude/settings.json:391-392` carries `Bash(find /)` and `Bash(find / :*)`.
- Remaining gap to verify: whether `find / -name x` (and `find /Users …`-style roots, `find -L /`, `find  /` with two spaces) match the `find / :*` rule. Check how the `:*` prefix rule is matched against `find / -name x` in a throwaway Claude Code permission test.

Steps:

1. Run `find / -maxdepth 1` and `find / -name x` once to confirm both are denied. Only the denial is exercised, so nothing is searched.
2. If a form slips through, add the missing deny entry to `ai/settings/settings.json` and run `scripts/°base/ai/settings/sync.py` to regenerate `.claude/settings.json`.
3. If everything is already denied, no code change: just tick, complete and sync the todo, and mention the verification in the commit body.

## Todo 2: `download_ref.py` prefers the "Edit this page on GitHub" source (`7f53d54c`)

Findings:

- `scripts/download_ref.py` wraps `scripts/°base/ai/references/°dllink_lib/`.
- `cli.main` runs `resolve_plan` → `markdown_plan_if_available` (tries `.md`-style URL rewrites) → `download`, which falls back to `html_to_markdown` when `plan.convert_html` is set (`planner.py`, `html.py`).
- `providers/` already knows how to turn GitHub URLs into raw download plans (`github_plan`).

Design:

- New helper `edit_link_markdown_plan(plan, html, output_root, fetch)` in `planner.py`, called from `download()` after the HTML response arrived and before `html_to_markdown`.
- New `EditLinkParser` in `html.py` (stdlib `HTMLParser`, like `RevisionParser`): finds the first `<a href>` whose text matches `Edit (this page )?(on GitHub)` case-insensitively, or that carries a GitHub `/edit/<branch>/<path>` href.
- Rewrite `/edit/` to `/blob/` and hand the URL to `github_plan`, which yields the raw URL. Only accept the result if the path ends in `.md`, `.mdx` or `.rst`-free markdown (so `.rst`/`.ipynb` sources still fall back to HTML).
- Fetch the raw file. On HTTP 200 and `looks_markdown`, use it, keep the output path of the original page, and log `rewrite: <page> -> <raw url>`. On any miss, log and fall back to the HTML converter as before.
- Order: the existing `.md` candidate guessing stays first (cheap, no HTML needed); the edit link is the second stage, the HTML converter the last.

Tests (`scripts/°base/tests/test_download_link.py`, offline fake `fetch`):

- Page with an "Edit this page on GitHub" link to an `.md` file → raw content written, one extra fetch.
- Link to a non-markdown file, a non-GitHub link, a 404 raw file, and no link at all → HTML converter result unchanged.

## Todo 3: `/todo-loop` marks the todo in progress inside a git worktree (`1382d491`)

Findings:

- `scripts/°base/ai/todos/sync_todos.py` already renders `IN-PROCESS` as checkbox `[…]` with `_(in process[, N%])_` (`checkbox_and_state`), and `update_line` rewrites existing lines with it.
- `count_open` and the todo-loop's "first open `- [ ]` item" already skip such items.
- So the sync side mostly exists. The gap is the skill text, plus a test that proves the state round-trips.
- `mcp__sync_todo__update_todo` accepts `changes.status = "IN-PROCESS"`.

Steps:

1. `.claude/skills/todo-loop/SKILL.md`, setup step 4 and "The todo": when the session runs in a git worktree (`git rev-parse --git-dir` differs from `--git-common-dir`), right after choosing the todo call `update_todo(calendar_id, uid, {status: "IN-PROCESS"})` and run the sync for the project, so other agents see `[…]` and skip it. Tell the user it was marked. Also say: skip items already `[…]` unless this worktree set them.
2. In "Close", `complete_todo` replaces the state, so nothing extra is needed there.
3. Add a unit test in the existing sync_todos tests: an `IN-PROCESS` todo renders `- […] … _(in process)_`, and `update_line` turns an existing `- [ ]` line into it and back to `- [x]` on `COMPLETED`. Fix the sync only if the test shows a gap.
4. Mirror the wording in `ai/°base/AGENTS.md` only if it describes the todo-loop flow (check first).

## Verification

- `uv run --project scripts/°base python -m unittest scripts/°base/tests/test_download_link.py` plus the sync_todos test module (run with `uv`, not system python).
- Full base test suite via the command in `ai/°base/AGENTS.md`.
- Manual: `scripts/download_ref.py --no-git-add --no-git-commit` on a docs page with an edit link, into a scratch output root.
- Todo 3: set a scratch todo `IN-PROCESS` via MCP, run the sync, confirm `[…]` in `todos.md`, then delete nothing and revert its status.

## Commits and closing

Three work commits in the order 1, 2, 3, each followed by `complete_todo` and a project sync, folded per the lplp procedure (tag backup first, `git diff <bak-tag> HEAD` empty).
