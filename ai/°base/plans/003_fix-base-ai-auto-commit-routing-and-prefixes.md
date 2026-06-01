# Fix Base AI Auto-Commit Routing And Prefixes

## Summary
Fix the AI hook base-repo detection so this repository routes automated artifacts to `ai/°base/...` even when the repo only has `origin`, and ensure base-repo AI auto-commits use `[base] ` commit subjects.

## Key Changes
- Relax `scripts/°base/ai/hooks/_lib.py` base detection:
  - Keep the directory-name guard: active subproject must be named `base`.
  - Require `origin` to point to `luckydonald/base(.git)`.
  - Remove the brittle requirement that remotes must be exactly `empty` and `origin`.
- Add a shared commit-subject helper in `_lib.py`:
  - Prefix `[base] ` when the same base-repo detection is true.
  - Leave messages unchanged when not in the base repo or already prefixed.
- Apply the helper to all AI artifact auto-commits:
  - Prompt and decision commits via `append_and_commit`.
  - Plan commits in `save-plan/hook.py`.
  - Memory commits in `record-memory/hook.py`.

## Tests
- Add focused hook tests using temporary git repos:
  - Base repo named `base` with only `origin=https://luckydonald@github.com/luckydonald/base.git` writes Codex prompt logs to `ai/°base/query.md`.
  - The prompt commit subject becomes `[base] ai: updated prompt`.
  - Codex plan capture writes to `ai/°base/plans/...` and commits as `[base] ai: save plan ...`.
  - A consuming repo with a different `origin` still writes to `ai/query.md` and keeps unprefixed `ai:` commit messages.
- Keep existing AI settings sync tests passing.

## Assumptions
- The fix applies prospectively; it will not rewrite existing bad commits or move already committed `ai/query.md` / `ai/plans/...` artifacts.
- `[base] ` prefixing is intended only when working in the actual `luckydonald/base` repo, not in downstream repositories that merely contain `scripts/°base`.
