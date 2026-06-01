# Prevent Accidental Memory Deletion

## Summary
Make repo memory authoritative during sync, and require explicit commit-message markers for intentional memory deletions. Add a helper script that performs a correctly formatted memory deletion commit.

## Key Changes
- Update `scripts/°base/ai/hooks/record-memory/hook.py`:
  - Never delete repo memory files because the Claude source directory/file is missing.
  - On `SessionStart`, recreate missing Claude source memory files from repo memory files using the existing hardlink/symlink strategy.
  - Keep `PostToolUse` source-to-repo sync for new or edited Claude memory files.
  - Treat a memory as intentionally deleted only when git history contains a deletion commit for that filename with a standalone marker line.

- Add commit-message enforcement:
  - New commit-msg hook under `scripts/°base/git/hooks/commit/`.
  - For staged deletions under `ai/memory/` or `ai/°base/memory/`, require one standalone marker line per deleted file:
    `Deleted Memory: <filename>.md`
  - Register the hook in `.pre-commit-config.yaml` and `.pre-commit-hooks.yaml`.
  - The hook should accept the marker as a standalone line anywhere in the commit message, but error text should recommend placing it as the final line after one empty line.

- Add a delete helper script:
  - Create `scripts/°base/ai/memory/delete.py`.
  - Usage: `python3 scripts/°base/ai/memory/delete.py <filename-or-path>`.
  - Resolve the current subproject the same way existing AI hooks do, including `ai/°base/memory` routing in the base repo.
  - Delete both the repo memory file and matching Claude source memory file when present.
  - Stage only the affected repo memory path and commit with:
    - Subject: `ai: delete memory <stem>`, passed through `base_ai_commit_subject()` so `[base] ` is added when appropriate.
    - Body: exactly one blank line, then final marker line `Deleted Memory: <filename>.md`.
  - Do not delete `MEMORY.md` automatically unless it is the explicit target.

## Tests
- Add memory sync tests proving:
  - Empty/missing Claude source does not delete tracked repo memories.
  - Repo memory files recreate missing Claude source files.
  - Fresh Claude memory files still sync into the repo and auto-commit.
  - A memory with a latest marked deletion in git history is not resurrected from stale local source.

- Add commit-msg/helper tests proving:
  - Memory deletion without `Deleted Memory: <filename>.md` fails.
  - Memory deletion with a standalone marker passes.
  - Multiple memory deletions require one marker per filename.
  - The delete helper creates the expected subject, blank line, final marker line, and deletes only the targeted memory.

- Run:
  - `python3 -m unittest scripts/°base/tests/test_ai_hooks_base_routing.py`
  - the new commit hook/helper test module
  - `python3 -m py_compile scripts/°base/ai/hooks/record-memory/hook.py scripts/°base/ai/memory/delete.py`

## Assumptions
- The bad `d1b384a` deletion is repaired separately by the user.
- The marker format is exactly `Deleted Memory: <filename>.md`.
- Helper-created deletion commits use the normal AI commit subject behavior, including optional `[base] ` prefix.
