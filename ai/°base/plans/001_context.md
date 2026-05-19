# Context

During plan mode, Claude writes the plan file with the `Write` tool (shown
as "Updated plan — Wrote N lines to ~/.claude/plans/<name>.md").  The current
`save-plan` hook only fires on `ExitPlanMode`, so if Claude updates the plan
multiple times the intermediate versions are never committed.  Hooking `Write`
gives us the plan content even earlier and as a redundant safety net.

The `Write` PostToolUse payload already contains everything we need:
- `tool_input.file_path` — absolute path to the written file
- `tool_input.content`  — the full file content (no file read needed)

# Approach

## 1. Extend the hook matcher in `settings.json`

Change the `ExitPlanMode` PostToolUse entry matcher to `Write|ExitPlanMode`
so the same hook script receives both events.

File: `.claude/settings.json`

## 2. Add `_plan_from_write()` to `save-plan/hook.py`

```python
def _plan_from_write(tool_input: dict) -> str:
    file_path = tool_input.get("file_path") or ""
    if not re.search(r"/\.claude/plans/[^/]+\.md$", file_path):
        return ""
    return (tool_input.get("content") or "").strip()
```

Filters on `/.claude/plans/*.md` so the hook ignores every other Write call.

## 3. Wire it into `main()`

```python
tool_name = payload.get("tool_name", "")
if tool_name == "Write":
    plan = _plan_from_write(tool_input)
else:                              # ExitPlanMode
    plan = _plan_from_response(payload.get("tool_response"))
```

## 4. Deduplication — avoid double-commits

Both Write and ExitPlanMode fire for the same planning session.  Before
committing, compare the plan text against the content of the most-recently
numbered file in `plans_dir`.  Skip if identical.

```python
def _already_saved(plans_dir: Path, plan: str) -> bool:
    files = sorted(plans_dir.glob("[0-9]*_*.md"))
    if not files:
        return False
    return files[-1].read_text(encoding="utf-8").strip() == plan
```

# Files to modify

- `scripts/°base/ai/hooks/save-plan/hook.py` — add `_plan_from_write()`,
  `_already_saved()`, update `main()`
- `.claude/settings.json` — change matcher from `ExitPlanMode` to
  `Write|ExitPlanMode`

# Verification

1. Start `/plan`, write a plan, approve it → only **one** `ai: save plan` commit
   despite both Write and ExitPlanMode firing.
2. Start `/plan`, write a plan, then write it again with different content →
   two `ai: save plan` commits (Write fires twice with different content).
3. No spurious commits when unrelated files are written.
