
# Shared Claude/Codex Settings Sync

## Summary

Build a bidirectional sync layer so Claude and Codex share one normalized settings model while still allowing edits in either native config. The sync will
cover tracked settings and local settings, run automatically on session start and pre-commit, and preserve Codex prompt logging by wiring the existing ›
support into Codex hooks.

## Key Changes

- Add a neutral settings source:
    - ai/tool-settings/settings.json for tracked shared rules.
    - ai/tool-settings/settings.local.json for ignored local overrides.
    - ai/tool-settings/sync-state.local.json for per-entry hashes/mtimes used by last-writer conflict handling.
- Add scripts/°base/ai/settings/sync.py with:
    - --apply: import native edits, merge, and render tool configs.
    - --check: fail if native/generated files are out of sync.
    - --explain: print what changed and which source won.
- Sync native files both ways:
    - Claude: .claude/settings.json, .claude/settings.local.json, .claude/commands/*.md.
    - Codex: .codex/hooks.json, Codex command docs, and any Codex-specific generated policy files needed by the installed CLI.
- Use stable per-rule IDs so additions, edits, and deletions can be compared entry-by-entry instead of overwriting whole files.

## Behavior

- Merge policy: last writer wins where detectable.
  - Prefer sync-state entry changes.
  - For tracked files, use git diff --unified=0 as a line-level fallback when state is missing.
  - For local untracked files, use sync-state plus file mtime.
  - Propagate deletions only when the entry existed in the previous sync state; absence in a newly discovered file is not treated as deletion.
  - If both sides changed the same entry and ordering cannot be determined, stop with a conflict report.
- Hook parity:
  - Existing save-prompt Codex prefix support becomes active through Codex UserPromptSubmit.
  - save-decision accepts Claude AskUserQuestion and Codex request-user-input payloads.
  - save-plan gains Codex support by extracting <proposed_plan>...</proposed_plan> from Codex stop/final-message hook payloads.
  - Shared permission hook continues blocking unsafe git add and Co-Authored-By, and is adapted for Codex’s hook payload/output format.
- Automation:
  - Add sync to Claude and Codex SessionStart hooks.
  - Add a pre-commit hook that runs sync/check and fails if files changed so the user can review and stage explicit paths.
  - Keep scripts/°base/init/checkout.sh idempotent and have it install/update the pre-commit hook as today.

## Tests

- Unit-test parsing and rendering for Claude settings, Claude local settings, Codex hooks, neutral base, and neutral local files.
- Round-trip tests:
  - Add a Claude allow/deny/hook entry and verify Codex output updates.
  - Add a Codex hook/policy entry and verify Claude output updates.
  - Add local-only entries and verify they stay ignored but active.
- Conflict tests for last-writer, tracked git-diff fallback, local mtime fallback, and ambiguous conflict reporting.
- Hook payload tests for Claude and Codex prompt logging, decision logging, plan capture, and permission denial output.
- Pre-commit/check test that fails on unsynced generated files.

## Assumptions

- .claude/settings.local.json stays ignored via the existing *.local.* rule.
- The current › prompt prefix is intentional; it only needs a Codex hook invocation.
- Codex v0.133.0 hook format is compatible enough with Claude’s event names to share hook scripts after small payload/output adapters.
- Codex memory parity will be limited to discovered Codex memory locations; if no project memory source exists, memory sync no-ops rather than inventing
files.
