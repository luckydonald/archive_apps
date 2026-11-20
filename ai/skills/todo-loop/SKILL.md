---
name: "todo-loop"
description: "Work on exactly ONE open todo of a project, the next unchecked `- [ ]` item of its todo file (intel, plan, implement, commit, tick, complete on CalDAV, sync, rebase), then stop so the user can /clear and run it again for the next one. Todos are synced from CalDAV into the todo file (calendar 7 by default). Use whenever the user asks to do the next todo, work on the todos / `ai/todos.md` / the TODO list of a project, or says 'go through the todos'."
---

# Todo loop (one todo per run)

Does the **next open todo** of one project, then stops so the user can `/clear` and run it again. Never start a second todo in the same run. Todos live on CalDAV (see the `sync-todo-mcp` skill) and are mirrored into the project's todo file by `scripts/sync_todos.py`.

## Setup

1. Sync first: run `uv run scripts/°base/ai/todos/sync_todos.py` from the repo root, without `--purge-*`, so the todo files hold the current CalDAV state. It commits its own `[TODOs] synced todos …` commits.
2. Work out the project (tag or name, from the user's message or a named todo file). If none is named, or the current project has no open todo, choose automatically: the current project first, then its subprojects and the other projects of `ai/settings/sync_todos.json` that have a `path` in the committed `ai/settings/sync_todos.repo.json` or the gitignored `ai/settings/sync_todos.local.json` (a project without any path is out of scope, never touch it), taking the first one that has an open `- [ ]` item; never stop to ask which project. When the project is not the one the session started in, the hooks still write the run's prompt and plan commits into the session project's `ai/`, which the Rebase step of "The todo" cleans up. Then work out its todo file, calendar id (default `7`), Bugsink ids and commit scope prefix. All come from the repo `CLAUDE.md` ("Todo-list identifiers", "Issue-tracker identifiers") and the project's own `CLAUDE.md`.
3. Load `/commit-with-lplp-style` and `/code-style`.
4. Read the todo file and take the first open `- [ ]` item, unless another is clearly more urgent (crash, blocker). A subtask comes before its parent; skip items that say so. Tell the user which todo (uid, summary) you take, and why if it is not the first.
   Skip in progress `- […]` items unless you are resuming the todo this worktree/agent marked in progress.
5. Mark the chosen todo in progress, so parallel agents skip it. No research needed, run exactly this:
   - Call the MCP tool `mcp__sync_todo__update_todo` with `{"calendar_id": <calendar id>, "uid": "<uid>", "changes": {"status": "IN-PROCESS"}}`.
   - Tell the user you marked it in progress.

## The todo

1. **Intel** (normal mode): in a linked worktree, start after the in-progress status has synced. Reproduce and understand using the MCPs and throwaway scripts in the scratchpad. No project edits yet. If the todo holds several bugs, make them subtasks first (`create_todo` with `parent_uid` and the project tag) and work on the first only.
2. **Plan**: enter plan mode, write the plan (findings, files, tests, new i18n keys) into the plan file that plan mode gives you, wait for the user's accept. Corrections are decisions. The hook copies that plan file into the project's `ai/plans/` automatically for you.
3. **Implement**: code plus tests, as plain new commits (no rebase yet). Run the project's full test suite and lint/build; on red, fix, commit, rerun until green. Update the project's `CLAUDE.md` if behaviour worth knowing changed.
4. **Close**: tick the checkbox, call the MCP tool `mcp__sync_todo__complete_todo` with `{"calendar_id": <calendar id>, "uid": "<uid>"}`, then `uv run scripts/°base/ai/todos/sync_todos.py --project <project>` from the repo root, without `--purge-*`. Re-read the todo file afterwards, since the sync may have rewritten it.
5. **Rebase**: tag the prior HEAD with `scripts/tag_backup.py`, then interactively rebase the `ai:` auto-commits and fix commits into one work commit (message from `ai/git/pending-commit.md`). Also squash a directly preceding plan commit, and the `[TODOs] synced todos …` commit written after completing the todo (whatever todos it changed) into the work commit. The sync of step 1 folds the same way into the previous completed task's commit if that one is not pushed yet, and into this task's work commit if no unpushed one precedes it (`/commit-with-lplp-style`, "Todo syncs": a sync of the current project always squashes into an older or the next task, and with several projects per repository it may be re-ordered next to your tasks). Verify `git diff <bak-tag> HEAD` is empty. If the project is not the one the session started in, do this as the last rewrite of the run with `/move-ai-to-project` instead, which also moves the `ai:` prompt and plan files into the edited project's `ai/`, and verify that `git diff <bak-tag> HEAD` shows only those moves. Your commit message must include the ```- `todo:{uuid}`: {new state}``` near the end, one per line if multiple.
6. **Stop**: report in a few lines (todo done, commit hash, tests run, what needs a deploy to verify, leftovers), name the next open todo (content & `todo:{uuid}`), and end the turn.

## Rules

- One commit per todo; never commit unrelated files.
- Follow the project's `CLAUDE.md` (e.g. sync_todo: new UI strings in all six `frontend/src/i18n/locales/*.json`, bot strings in `i18n/langs/*.py`).
- Never delete or clean up data (duplicate todos, files), reset, or push unasked; report it instead.

## No open todo left

Only when no project (including subprojects) has an open todo: check Bugsink for new unresolved issues (see `bugsink-triage`; skip if the project has none), `create_todo` for each, and stop. Otherwise report that everything is done.
