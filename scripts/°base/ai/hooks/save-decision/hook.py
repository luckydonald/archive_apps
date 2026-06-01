#!/usr/bin/env python3
"""PostToolUse hook for AskUserQuestion: append the asked question(s) and the
picked answer to ai/query.md as a markdown blockquote, then commit.

Usage: hook.py [ai_tool_name]   (currently unused; accepted for parity with save-prompt)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _lib import append_and_commit, read_payload, resolve_log_path, slugify  # noqa: E402


def _flatten_answer(tool_response) -> str:
    """Best-effort flatten of ``tool_response`` to a human-readable string.

    Accepts:
      - a bare string (used verbatim),
      - a ``{answers: {q: a}}`` shape (newline-joined values),
      - any other shape (JSON-serialised fallback).
    """
    if tool_response is None:
        return ""
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, dict):
        answers = tool_response.get("answers")
        if isinstance(answers, dict):
            return "\n".join(str(v) for v in answers.values())
    return json.dumps(tool_response, ensure_ascii=False)


def _render_block(tool_input: dict, answer: str) -> str:
    questions = tool_input.get("questions") or []
    out: list[str] = []

    for i, q in enumerate(questions):
        if i > 0:
            out.append("> \n")
        out.append(f"> {q.get('question', '')}\n")
        for opt in q.get("options") or []:
            label = opt.get("label", "")
            if label:
                out.append(f"> - {label}\n")

    if answer:
        lines = answer.splitlines() or [""]
        out.append(f"> → {lines[0]}\n")
        for cont in lines[1:]:
            out.append(f">   {cont}\n")

    out.append("> ```json\n")
    pretty = json.dumps(tool_input, indent=2, ensure_ascii=False)
    for line in pretty.splitlines():
        out.append(f"> {line}\n")
    out.append("> ```\n")
    out.append("> \n")
    out.append("\n")
    return "".join(out)


def main() -> int:
    payload = read_payload()
    tool_input = payload.get("tool_input") or {}
    if not tool_input and isinstance(payload.get("questions"), list):
        tool_input = {"questions": payload.get("questions") or []}
    questions = tool_input.get("questions") or []
    if not questions:
        return 0

    answer = _flatten_answer(payload.get("tool_response"))
    block = _render_block(tool_input, answer)

    first_question = questions[0].get("question", "") if isinstance(questions[0], dict) else ""
    slug = slugify(first_question, fallback="decision")

    log_path = resolve_log_path("ai/query.md", "ai/°base/query.md")
    append_and_commit(
        log_path,
        block,
        commit_template_relpath="ai/commit-templates/decision.md",
        default_commit_msg=f"ai: save decision {slug}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
