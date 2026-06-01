# Fix Codex Plan Capture And Tool Arguments

## Summary
Fix only the Codex plan-capture bug while standardizing `save-plan` hook invocation to match the existing prompt/decision pattern: Claude calls `save-plan/hook.py 'claude'`, Codex calls `save-plan/hook.py 'codex'`. The latest user message was auto-committed as `cd860d1 [base] ai: updated prompt`; manually repaired bad artifacts stay untouched.

## Key Changes
- Update shared hook setup so `save-plan` commands include an explicit `'claude'` argument in `ai/tool-settings/settings.json` and generated `.claude/settings.json`.
- Extend settings sync tool-argument rewriting so `save-plan/hook.py 'claude'` renders as `save-plan/hook.py 'codex'` in `.codex/hooks.json`, same as `save-prompt` and `save-decision`.
- In `save-plan/hook.py`, read `sys.argv[1]` as `ai_tool`, defaulting to `claude` for compatibility.
- Preserve Claude behavior for `Write|ExitPlanMode`: continue reading Claude plan writes and `ExitPlanMode` payloads exactly as before.
- For `codex`, ignore generic `PostToolUse` payloads and capture plans only from Codex-specific sources:
  - Prefer latest Codex session transcript `item_completed` where `item.type == "Plan"`.
  - Fall back to `<proposed_plan>...</proposed_plan>` in the final assistant message.
  - Fall back to the latest query-log entry only when it clearly contains a forwarded plan prompt such as `A previous agent produced the plan below`.

## Tests
- Add settings-sync coverage proving `save-plan` gets `'codex'` in rendered Codex hooks and keeps `'claude'` for Claude.
- Add Codex regression coverage where `PostToolUse` has stdout-like `tool_response`; assert no plan file or commit is created.
- Add Codex transcript coverage using a real session-log-shaped `item_completed Plan` event; assert markdown plan content is saved.
- Add Codex query fallback coverage for the forwarded-plan prompt format seen in the bad commit.
- Add/keep Claude `Write` plan coverage to prove `~/.claude/plans/*.md` still works.

## Verification
- Run `python3 -m unittest scripts/°base/tests/test_ai_hooks_base_routing.py -v`.
- Run `python3 -m unittest scripts/°base/tests/test_ai_settings_sync.py -v`.
- Run `python3 -m py_compile scripts/°base/ai/hooks/save-plan/hook.py scripts/°base/ai/settings/sync.py`.
- Run settings sync apply mode so shared, Claude, and Codex hook files stay consistent.

## Assumptions
- Existing repaired commits are left untouched.
- Query-log fallback remains narrow so ordinary prompts cannot become plan files.
- Explicit tool argument migration is intentional for both Claude and Codex, matching the existing commit/prompt hook style.
