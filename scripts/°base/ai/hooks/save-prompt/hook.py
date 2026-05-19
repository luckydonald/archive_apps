#!/usr/bin/env python3
"""UserPromptSubmit hook: append the user's prompt to ai/query.md and commit.

Usage: hook.py [ai_tool_name]   (default: unknown)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _lib import append_and_commit, read_payload, resolve_log_path  # noqa: E402

PREFIXES = {"claude": "❯", "codex": "›"}
DEFAULT_PREFIX = "⩼"

# Single-command prompts we never want to log: internal tooling invocations
# and the most common "please commit now" reminders.
SKIP_PROMPTS = {
    "/committing-with-lplp-style",
    "/rebase-ai-prompt-commits",
    "/rename",
    "commit", "Commit",
    "yes commit", "commit please", "commit pls", "commit plz",
    "keep committing", "always commit",
}


def main() -> int:
    ai_tool = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    prefix = PREFIXES.get(ai_tool, DEFAULT_PREFIX)

    payload = read_payload()
    prompt = payload.get("prompt") or ""
    if not prompt.strip():
        return 0
    if prompt.strip() in SKIP_PROMPTS:
        return 0

    log_path = resolve_log_path("ai/query.md", "ai/°base/query.md")
    append_and_commit(
        log_path,
        f"{prefix} {prompt}\n\n",
        commit_template_relpath="ai/commit-templates/prompt.md",
        default_commit_msg="ai: updated prompt",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
