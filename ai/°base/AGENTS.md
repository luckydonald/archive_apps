# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A reusable git base that consuming projects adopt via checkout, rebase, or merge from `base/base`. Its files — scripts, hooks, AI settings — live in consuming repos like normal files. Everything base-specific is namespaced under `°base` so it never collides with consuming-repo code.

## Commands

Run all tests (from repo root):
```bash
uv run --project scripts/°base python -m unittest discover -s scripts/°base/tests -v
```

Run a single test module:
```bash
uv run --project scripts/°base python -m unittest ai.scripts.tests.test_<name> -v
```

Sync AI tool settings (Claude ↔ Codex) and skills:
```bash
python3 scripts/°base/ai/settings/sync.py
```

Check sync without writing (used by pre-commit):
```bash
python3 scripts/°base/ai/settings/sync.py --check
```

## Architecture

### Directory layout

| Path | Purpose |
|---|---|
| `scripts/°base/` | All helpers; `°base` namespace keeps them from colliding |
| `ai/°base/` | AI artifacts for the base repo itself (queries, plans, memory) |
| `ai/skills/*/SKILL.md` | Canonical skill source; `sync.py` distributes wrappers |
| `ai/tool-settings/settings.json` | Tracked, tool-neutral settings (Claude + Codex share this) |
| `ai/tool-settings/settings.local.json` | Machine-local settings overlay (gitignored) |
| `.claude/settings.json` | Generated from `ai/tool-settings/`; do not edit directly |
| `.claude/hooks/permission-check.py` | PermissionRequest hook — enforces git commit policy |

### Settings + skills sync (`scripts/°base/ai/settings/sync.py`)

The single source of truth is `ai/tool-settings/settings.json`. Running `sync.py` renders it into `.claude/settings.json` (Claude) and `.codex/hooks.json` (Codex), adjusting async flags and tool-name arguments between the two formats. A pre-commit hook runs `sync.py --check` to block commits when the files drift.

Skills follow the same pattern: the canonical file is `ai/skills/<slug>/SKILL.md`. `sync.py` writes a thin wrapper at `.claude/skills/<slug>/SKILL.md` and `.agents/skills/<slug>/SKILL.md` that points back to the canonical path. Always edit the canonical file, then run `sync.py`.

### AI artifact routing (`scripts/°base/ai/hooks/_lib.py`)

Every Claude Code hook calls `resolve_log_path()`, which routes output based on whether it is running inside the base repo (`ai/°base/…`) or a consuming repo (`ai/…`). Detection: `_is_inside_base_repo()` — directory named `base` **and** origin URL matches `luckydonald/base`.

Hooks:

| Hook | Trigger | Output |
|---|---|---|
| `save-prompt/hook.py` | `UserPromptSubmit` | `ai/°base/query.md` |
| `save-decision/hook.py` | `AskUserQuestion` post | `ai/°base/query.md` |
| `save-plan/hook.py` | `Write`, `ExitPlanMode`, `Stop` | `ai/°base/plans/NNN_*.md` |
| `record-memory/hook.py` | `Write`, `Edit`, `SessionStart` | syncs memory hardlinks |

### Pre-commit hooks

- `reject_co_authored_by.py` — blocks `Co-Authored-By:` in commit messages (stage: commit-msg)
- `require_memory_delete_marker.py` — requires an explicit marker when memory files are deleted (stage: commit-msg)

### Commit format

```
[base] topic: ai: Run: Short summary.
```

`[base]` is the where-tag; `topic` is a component or subsystem name (not a Conventional Commit type like `feat` or `fix`).