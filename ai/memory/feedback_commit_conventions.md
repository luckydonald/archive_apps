---
name: feedback_commit_conventions
description: Repo-enforced commit conventions — no Co-Authored-By trailer, and an ai-settings-sync pre-commit hook that must be run (not bypassed) when it fails
metadata:
  node_type: memory
  type: feedback
  originSessionId: 38eb1bc9-858b-49b9-b13f-cf9f3c8beb89
  modified: 2026-08-30T18:27:17.928Z
---

This repo's pre-commit hooks reject commits with a `Co-Authored-By:` trailer ("Reject Co-Authored-By in commit messages" hook) — omit that trailer (and the `Claude-Session:` line) entirely when committing here, rather than including it as the default Claude Code commit template suggests.

There's also an `ai-settings-sync` pre-commit hook that fails the commit if `ai/tool-settings/settings.local.json`, `.claude/settings.local.json`, or `.codex/rules/generated.local.rules` are out of sync. Fix is to run `./scripts/°base/ai/settings/sync.py` (regenerates those files) and re-commit — never `--no-verify` past it.

There's a separate automated workflow already active in this repo (outside anything I did) that auto-commits plan-mode decisions and saved plans under `ai: save decision ...` / `ai: save plan ...` messages into `ai/query.md` and plan files — these appear in `git log` as a side effect of using AskUserQuestion / the plan file, not something to clean up or be alarmed by.

**Why:** First attempted commit in this repo failed on both hooks in sequence (settings sync, then Co-Authored-By) during [[project_checksum_index_concurrency_fix]].

**How to apply:** In this repo, always commit with a plain message (no trailer), and if a commit fails on `ai-settings-sync`, run the sync script and retry before assuming something is broken.
