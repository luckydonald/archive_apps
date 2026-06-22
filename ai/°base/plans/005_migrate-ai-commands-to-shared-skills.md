# Migrate AI Commands To Shared Skills

## Summary
- Make `.agents/skills` the canonical skill source, since Codex repo skills are discovered there per OpenAI’s Codex skills docs.
- Generate proper Claude skill wrappers under `.claude/skills`, plus tiny Claude slash-command shims under `.claude/commands`.
- Remove full-body duplication between Claude and Codex; only `.agents/skills/<name>/SKILL.md` contains the real workflow text.

## Key Changes
- Create canonical skills:
  - `.agents/skills/commit-with-lplp-style/SKILL.md`
- Migrate the current full command bodies into the canonical commit-style skill.
- Replace `.claude/commands/*.md` with small compatibility shims that tell Claude to use the matching skill.
- Add `.claude/skills/<name>/SKILL.md` wrappers with the same `name` and `description`, a generated-file marker, and a short instruction to read the canonical `.agents/skills/<name>/SKILL.md`.
- Remove `.codex/commands/*.md` duplicates and stop generating Codex command copies, because Codex can use `.agents/skills` directly.

## Sync Script
- Update `scripts/°base/ai/settings/sync.py`:
  - Replace `_sync_commands()` with `_sync_skills_and_claude_commands()`.
  - Parse `name` and `description` from each canonical `.agents/skills/*/SKILL.md`.
  - Generate or check Claude skill wrappers and Claude command shims.
  - Overwrite only files with the generated marker or known migrated files.
  - Report stale/missing generated files in `--check --explain`.
- Keep existing hook/settings synchronization behavior unchanged.
- If `.agents` is still non-writable during implementation, normalize it to a normal tracked directory mode before creating `.agents/skills`.

## Test Plan
- Add unit tests in `scripts/°base/tests/test_ai_settings_sync.py` for:
  - canonical skill frontmatter parsing,
  - Claude skill wrapper rendering,
  - Claude command shim rendering,
  - sync check detecting stale generated wrappers,
  - no Codex command copy generation.
- Run:
  - `python3 -m unittest scripts/°base/tests/test_ai_settings_sync.py`
  - `python3 scripts/°base/ai/settings/sync.py --check --explain`

## Assumptions
- Claude project skills are available from `.claude/skills`, based on the installed Claude changelog and current `Skill(...)` permissions in `.claude/settings.json`.
- Codex repo skills should live in `.agents/skills`, per OpenAI Codex docs: https://developers.openai.com/codex/skills
- Claude slash commands should remain for muscle memory, but only as wrappers; the canonical workflow text lives once.
