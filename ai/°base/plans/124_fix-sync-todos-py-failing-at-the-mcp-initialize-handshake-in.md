# Fix `sync_todos.py` failing at the MCP `initialize` handshake, in base and in DockerTgBot

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

## Context

`uv run scripts/°base/ai/todos/sync_todos.py` crashes in `fetch_todos` (`sync_todos.py:1084`) at `await session.initialize()` with `MCPError: Server returned an error response`.
The `sync_todo` MCP server failed to connect at session start too, so the todo-loop cannot sync or complete todos.
The script in DockerTgBot (`sync_todo/scripts/sync_todos.py`) is a symlink chain into `DockerTgBot/scripts/°base/ai/todos/sync_todos.py`, which is byte-identical to base's copy.
So one patch covers both repos, and no commit exists in DockerTgBot that base lacks.

## Findings so far (read-only)

- Client and server run the same SDK: `mcp` 2.3.0 in the uv cache of the script and in `sync_todo/uv.lock`, so a version mismatch is unlikely.
- The server's `initialize` does not authenticate. Token checks happen per tool call in `authed_session` (`mcp/server.py:91`), so a bad token cannot explain an error at `initialize`.
- Today (2026-11-19) the server changed a lot: migration `0049_token_kind` (`kind` column on `mcp_tokens`, `resolve_mcp_token` now filters on it), embed keys, CORS, and a CalDAV multiget rewrite.
  If the deployed container runs new code against an unmigrated DB, or is restarting mid-migration, requests fail server-side.
  That is still a hypothesis, because the live response is not known yet.
- A direct `curl` probe with the real token was denied by the permission classifier, so the live response body is still unseen.
- The script prints only the generic class message and hides `code`, `message` and `data` of the `MCPError` inside an `ExceptionGroup`, so the real cause is invisible.

## Step 1: Diagnose (needs your OK for the live part)

1. Run `uv run --project sync_todo/code python -m pytest tests/test_mcp_mount.py` in DockerTgBot, to confirm the current server code answers `initialize` with 200.
2. Get the live answer without me handling the token.
   Either approve a throwaway script in the scratchpad that reuses `sync_todos.py`'s own env loading and prints only `code`, `message` and `data` of the error (never the URL or token), or I give you a `sh run` card that does the same.
3. Check the Coolify deployment health and migration state through the `coolify` MCP, read-only, if the answer points at a server-side 5xx.

## Step 2: Fix, depending on the finding

- **Server not migrated or down (most likely):** a deploy or ops fix in DockerTgBot, with no script change for that part. I would report it and ask before touching Coolify.
- **Client/handshake problem:** fix in `scripts/°base/ai/todos/sync_todos.py` (`fetch_todos`), for example the protocol version or an HTTP client option.
- **Server bug:** fix in `sync_todo/code/sync_todo_control/main.py` or `mcp/server.py`, with a regression test next to `tests/test_mcp_mount.py`.

## Step 3: Make the failure readable (done in every case)

In `sync_todos.py`, catch the `ExceptionGroup` around `asyncio.run(fetch_todos(...))` in `main()` (`sync_todos.py:1555`) and print one line: the exception type, plus `code`, `message` and `data` for an `MCPError`, plus the host without credentials.
Return a non-zero exit code like the existing "not set" branch does (`return 2`).
Add a unit test in `scripts/°base/ai/todos/tests/` that feeds an `ExceptionGroup` holding an `MCPError` and checks the single-line output and that no token appears in it.

## Landing it in both repos with the same commit

1. Commit once in base, as `[base] todos: ai: Run: …`, through `ai/git/pending-commit.md` and `scripts/tag_backup.py`, then fold the `ai:` auto-commits.
2. Cherry-pick that exact commit into DockerTgBot with `git cherry-pick -x`, so the hash is recorded and the author stays the same.
   DockerTgBot's tree has many untracked files, so I touch only tracked paths and verify with `git status` first.
3. Any server-side change goes into DockerTgBot only, as its own commit, because base does not contain the server.

## Verification

- `uv run --project scripts/°base python -m unittest` for the tests under `scripts/°base/ai/todos/tests/`.
- Re-run `uv run scripts/°base/ai/todos/sync_todos.py` in base and in DockerTgBot, and expect either a normal sync or the new one-line error that names the cause.
- `git diff` between the two copies of `sync_todos.py` stays empty.
- Nothing is pushed.
