#!/usr/bin/env python3
"""UserPromptSubmit hook: append the user's prompt to ai/query.md and commit.

Usage: hook.py [ai_tool_name]   (default: unknown)

Task notifications (<task-notification> XML) are intercepted and written as a
compact markdown summary block. The agent prompt and result are saved to
ai/agents/NNN.task-id/ (or the °base equivalent) and linked from query.md.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _lib import append_and_commit, base_ai_commit_subject, read_payload, resolve_log_path  # noqa: E402

PREFIXES = {"claude": "❯", "codex": "›"}
DEFAULT_PREFIX = "⩼"
CODEX_FORWARDED_PLAN_PREFIX = (
    "A previous agent produced the plan below to accomplish the user's task. "
    "Implement the plan in a fresh context. Treat the plan as the source of user intent, "
    "re-read files as needed, and carry the work through implementation and verification."
)
PLAN_LIKE_MIN_BYTES = 1024
PLAN_LIKE_MIN_NEWLINES = 8
CODEX_SHORT_PLAN_PROMPT = "Implement the plan."
CLAUDE_GITHUB_WORKER_PREFIX = (
    "You are Claude, an AI assistant designed to help with GitHub issues and pull requests. "
    "Think carefully as you analyze the context and respond appropriately. "
    "Here's the context for your current task:"
)

# Single-command prompts we never want to log: internal tooling invocations
# and the most common "please commit now" reminders.
# Claude uses /skill-name, Codex $skill-name.
SKIP_PROMPTS = {
    "/commit-with-lplp-style",
    "$commit-with-lplp-style",
    "/rename",
    "commit", "Commit", "yes commit",
    "commit please", "commit pls", "commit plz",
    "please commit", "pls commit", "plz commit",
    "keep committing", "always commit",
    "continue", "go on",
}


class PromptLogEntry(NamedTuple):
    text: str
    preformatted: bool = False
    extra_paths: tuple[Path, ...] = ()


def _latest_numbered_plan(plans_dir: Path) -> Path | None:
    latest: tuple[int, Path] | None = None
    if not plans_dir.is_dir():
        return None
    for entry in plans_dir.glob("[0-9]*_*.md"):
        m = re.match(r"^(\d+)_", entry.name)
        if not m:
            continue
        number = int(m.group(1))
        if latest is None or number > latest[0]:
            latest = (number, entry)
    return latest[1] if latest else None


def _read_plan_like_text(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if len(text.encode("utf-8")) < PLAN_LIKE_MIN_BYTES:
        return ""
    if text.count("\n") < PLAN_LIKE_MIN_NEWLINES:
        return ""
    return text.strip()


def _plan_link_entry(plan_path: Path, trailing_text: str, *, cleared: bool = False) -> PromptLogEntry:
    relpath = f"./plans/{plan_path.name}"
    content = f"> › Implement the [Plan]({relpath})."
    if cleared:
        content = f"{content} <kbd>cleared</kbd>"
    trailing_text = trailing_text.strip()
    if trailing_text:
        content = f"{content}\n\n› {trailing_text}"
    return PromptLogEntry(content, preformatted=True)


def _strip_codex_forwarded_plan_prompt(prompt: str, plans_dir: Path) -> PromptLogEntry:
    """Remove Codex's implementation handoff prompt when it repeats a saved plan."""
    stripped = prompt.strip()
    exact_prefix = stripped.startswith(CODEX_FORWARDED_PLAN_PREFIX)
    search_text = stripped[len(CODEX_FORWARDED_PLAN_PREFIX):].lstrip() if exact_prefix else stripped

    latest_plan = _latest_numbered_plan(plans_dir)
    plan = _read_plan_like_text(latest_plan)
    if plan and stripped == CODEX_SHORT_PLAN_PROMPT:
        return _plan_link_entry(latest_plan, "")

    if plan:
        plan_at = search_text.find(plan)
        if plan_at >= 0:
            if not exact_prefix:
                print(
                    "Warning: stripped a Codex forwarded-plan prompt by saved-plan match; "
                    "the prompt prefix may have changed and the hook should be updated.",
                    file=sys.stderr,
                )
            return _plan_link_entry(latest_plan, search_text[plan_at + len(plan):], cleared=True)

    if exact_prefix and re.match(r"(?s)^#\s+\S.*", search_text):
        return PromptLogEntry("")
    return PromptLogEntry(prompt)


def _xmlish_tag_text(prompt: str, tag: str) -> str:
    m = re.search(rf"<{re.escape(tag)}>(.*?)</{re.escape(tag)}>", prompt, re.DOTALL)
    return m.group(1).strip() if m else ""


def _context_field_text(prompt: str, field: str) -> str:
    m = re.search(rf"(?m)^{re.escape(field)}:\s*(.*?)\s*$", prompt)
    return m.group(1).strip() if m else ""


def _remove_trigger_phrase(text: str, trigger_phrase: str) -> str:
    if not trigger_phrase:
        return text.strip()
    escaped = re.escape(trigger_phrase.strip())
    text = re.sub(rf"(?im)^\s*{escaped}\s*$", "", text)
    text = re.sub(rf"(?i)^\s*{escaped}\s+", "", text).lstrip()
    text = re.sub(rf"(?i)\s*{escaped}\s*$", "", text).rstrip()
    return text.strip()


def _quote_lines(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def _online_query_issue_url(repository: str, issue_number: str) -> str:
    if not repository or not issue_number:
        return ""
    return f"https://github.com/{repository}/issues/{issue_number}"


def _online_query_artifact_text(
    *,
    issue_title: str,
    issue_number: str,
    issue_url: str,
    event_type: str,
    trigger_username: str,
    trigger_display_name: str,
    trigger_phrase: str,
    trigger_comment: str,
    request: str,
) -> str:
    lines = [
        "# Online Query",
        "",
        f"Issue: #{issue_number} {issue_title}".rstrip(),
    ]
    if issue_url:
        lines.append(f"URL: {issue_url}")
    lines.extend(
        [
            f"Event type: {event_type or 'unknown'}",
            f"Trigger: @{trigger_username or 'unknown'}"
            f" ({trigger_display_name or 'unknown'}) via {trigger_phrase or 'unknown'}",
            "",
            "## Trigger Comment",
            "",
            trigger_comment or "(none)",
            "",
            "## Query",
            "",
            request,
            "",
        ]
    )
    return "\n".join(lines)


def _strip_claude_github_worker_prompt(prompt: str, log_path: Path) -> PromptLogEntry:
    """Collapse Claude GitHub action's stock worker prompt to the user request."""
    stripped = prompt.strip()
    if not stripped.startswith(CLAUDE_GITHUB_WORKER_PREFIX):
        return PromptLogEntry(prompt)

    trigger_phrase = _xmlish_tag_text(stripped, "trigger_phrase") or "@claude"
    trigger_comment = _xmlish_tag_text(stripped, "trigger_comment")
    issue_body = _xmlish_tag_text(stripped, "pr_or_issue_body")
    issue_title = _context_field_text(stripped, "Issue Title")
    issue_number = _xmlish_tag_text(stripped, "issue_number")
    event_type = _xmlish_tag_text(stripped, "event_type")
    repository = _xmlish_tag_text(stripped, "repository")
    trigger_username = _xmlish_tag_text(stripped, "trigger_username")
    trigger_display_name = _xmlish_tag_text(stripped, "trigger_display_name")

    request = _remove_trigger_phrase(trigger_comment, trigger_phrase)
    if not request:
        request = _remove_trigger_phrase(issue_body, trigger_phrase)
    if not request:
        return PromptLogEntry("")

    artifact_path = log_path.parent / "plans" / "000_online_query.md"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    issue_url = _online_query_issue_url(repository, issue_number)
    artifact_path.write_text(
        _online_query_artifact_text(
            issue_title=issue_title,
            issue_number=issue_number,
            issue_url=issue_url,
            event_type=event_type,
            trigger_username=trigger_username,
            trigger_display_name=trigger_display_name,
            trigger_phrase=trigger_phrase,
            trigger_comment=trigger_comment,
            request=request,
        ),
        encoding="utf-8",
    )

    issue_link = f"#{issue_number}" if issue_number else "unknown issue"
    if issue_url:
        issue_link = f"[#{issue_number}]({issue_url})"
    summary = (
        f"❯ [query](./plans/{artifact_path.name}) for issue {issue_link}:\n"
        f"type: `{event_type or 'unknown'}`\n"
        f"trigger: @{trigger_username or 'unknown'} ({trigger_display_name or 'unknown'}) "
        f"via _{trigger_phrase}_.\n"
        f"comment: {trigger_comment or '(none)'}\n"
        f"{request}"
    )
    return PromptLogEntry(_quote_lines(summary), preformatted=True, extra_paths=(artifact_path,))


def _parse_task_notification(prompt: str) -> dict | None:
    """Extract fields from a <task-notification> block. Returns None if absent."""
    m = re.search(r"<task-notification>(.*?)</task-notification>", prompt, re.DOTALL)
    if not m:
        return None
    try:
        root = ET.fromstring(f"<task-notification>{m.group(1)}</task-notification>")
    except ET.ParseError:
        return None

    def _text(tag: str) -> str:
        el = root.find(tag)
        return (el.text or "").strip() if el is not None else ""

    return {
        "task_id": _text("task-id"),
        "tool_use_id": _text("tool-use-id"),
        "status": _text("status"),
        "summary": _text("summary"),
        "result": _text("result"),
        "output_file": _text("output-file"),
        "subagent_tokens": _text("usage/subagent_tokens"),
        "tool_uses": _text("usage/tool_uses"),
        "duration_ms": _text("usage/duration_ms"),
    }


def _extract_agent_prompt(output_file: str, tool_use_id: str = "") -> str:
    """Read the agent's JSONL output file and return the Agent prompt string.

    Supports two layouts:
    - Parent-session JSONL: prompt is inside a tool_use / name=Agent / input.prompt entry.
    - Subagent JSONL: prompt is the first type=user message whose message.content is a plain string.
    """

    def _iter_dicts(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from _iter_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from _iter_dicts(child)

    tool_use_fallback = ""
    subagent_fallback = ""
    try:
        with open(output_file, encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Layout 1: parent-session tool_use Agent entry
                for item in _iter_dicts(obj):
                    if item.get("type") != "tool_use" or item.get("name") != "Agent":
                        continue
                    prompt = item.get("input", {}).get("prompt", "")
                    if not prompt:
                        continue
                    if tool_use_id and item.get("id") == tool_use_id:
                        return prompt
                    if not tool_use_fallback:
                        tool_use_fallback = prompt
                # Layout 2: subagent JSONL — first user message with plain string content
                if not subagent_fallback and obj.get("type") == "user":
                    content = obj.get("message", {}).get("content", "")
                    if isinstance(content, str) and content.strip():
                        subagent_fallback = content
    except OSError:
        pass
    return tool_use_fallback or subagent_fallback


def _char_count(path: str) -> int:
    try:
        return len(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def _human_size(path: str) -> str:
    """Return file size as a human-readable string, e.g. '2.1 MB', '47 KB', '512 B'."""
    try:
        size = Path(path).stat().st_size
    except OSError:
        return "? B"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.3g} {unit}"
        size /= 1024
    return "? B"  # unreachable


def _markdown_file_link(label: str, chars: int, size: str, target: str) -> str:
    return f"[{label} (`{chars}` chars, `{size}`)]({target})"


def _usage_summary(info: dict) -> str:
    tool_uses = info.get("tool_uses", "")
    tokens = info.get("subagent_tokens", "")
    duration_ms = info.get("duration_ms", "")
    if not tool_uses or not tokens or not duration_ms:
        return ""
    try:
        duration = f"{int(duration_ms) / 60000:g}"
    except ValueError:
        duration = duration_ms
    return f"> - `{tool_uses}` tools, `{tokens}` tokens, `{duration} s`\n"


def _next_agent_number(agents_dir: Path) -> int:
    """Return the next sequential 1-based agent number."""
    if not agents_dir.exists():
        return 1
    nums = [
        int(m.group(1))
        for d in agents_dir.iterdir()
        if d.is_dir() and (m := re.match(r"^(\d+)\.", d.name))
    ]
    return max(nums, default=0) + 1


def _handle_task_notification(
    prefix: str,
    prompt: str,
    log_path: Path,
    commit_template_relpath: str,
    default_commit_msg: str,
) -> bool:
    """If prompt contains a task notification, write agent files and a summary entry.

    Returns True when handled; caller should skip the normal append.
    """
    info = _parse_task_notification(prompt)
    if not info or not info["task_id"]:
        return False

    agents_dir = log_path.parent / "agents"
    num = _next_agent_number(agents_dir)
    dir_name = f"{num:03d}.{info['task_id']}"
    agent_dir = agents_dir / dir_name
    agent_dir.mkdir(parents=True, exist_ok=True)

    agent_prompt = _extract_agent_prompt(info["output_file"], info["tool_use_id"])
    prompt_file = agent_dir / "prompt.md"
    result_file = agent_dir / "result.md"
    prompt_file.write_text(agent_prompt, encoding="utf-8")
    result_file.write_text(info["result"], encoding="utf-8")

    cwd = Path.cwd()
    prompt_rel = str(prompt_file.relative_to(cwd))
    result_rel = str(result_file.relative_to(cwd))
    subprocess.run(["git", "add", "--", prompt_rel, result_rel], capture_output=True)
    subprocess.run(
        ["git", "commit", "--no-verify", "--only", prompt_rel, result_rel,
         "-m", base_ai_commit_subject(f"ai: agent {dir_name} results")],
        capture_output=True,
    )

    rel_prompt = f"agents/{dir_name}/prompt.md"
    rel_result = f"agents/{dir_name}/result.md"
    query_chars = len(agent_prompt)
    result_chars = len(info["result"])
    log_chars = _char_count(info["output_file"])
    log_size = _human_size(info["output_file"])

    content = (
        f"{prefix} Task Notification:\n"
        f"> - Task `{info['task_id']}` <kbd>{info['status']}</kbd>\n"
        f"> - Tool `{info['tool_use_id']}`\n"
        f"> - > {info['summary']}\n"
        f"> - {_markdown_file_link('Query', query_chars, _human_size(str(prompt_file)), rel_prompt)}\n"
        f"> - {_markdown_file_link('Answer', result_chars, _human_size(str(result_file)), rel_result)}\n"
        f"> - {_markdown_file_link('Raw log', log_chars, log_size, info['output_file'])}\n"
        f"{_usage_summary(info)}"
        "\n"
    )
    append_and_commit(
        log_path,
        content,
        commit_template_relpath=commit_template_relpath,
        default_commit_msg=default_commit_msg,
    )
    return True


def main() -> int:
    ai_tool = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    prefix = PREFIXES.get(ai_tool, DEFAULT_PREFIX)

    payload = read_payload()
    prompt = payload.get("prompt") or payload.get("user_prompt") or ""
    if not prompt and isinstance(payload.get("tool_input"), dict):
        prompt = payload["tool_input"].get("prompt") or ""
    if not prompt.strip():
        return 0
    if prompt.strip() in SKIP_PROMPTS:
        return 0

    log_path = resolve_log_path("ai/query.md", "ai/°base/query.md")
    preformatted_prompt = False
    entry = PromptLogEntry(prompt)
    if ai_tool == "codex":
        entry = _strip_codex_forwarded_plan_prompt(prompt, log_path.parent / "plans")
        prompt = entry.text
        preformatted_prompt = entry.preformatted
        if not prompt.strip():
            return 0
    elif ai_tool == "claude":
        entry = _strip_claude_github_worker_prompt(prompt, log_path)
        prompt = entry.text
        preformatted_prompt = entry.preformatted
        if not prompt.strip():
            return 0

    if _handle_task_notification(
        prefix, prompt, log_path,
        commit_template_relpath="ai/commit-templates/prompt.md",
        default_commit_msg="ai: updated prompt",
    ):
        return 0

    content = f"{prompt}\n\n" if preformatted_prompt else f"{prefix} {prompt}\n\n"
    append_and_commit(
        log_path,
        content,
        commit_template_relpath="ai/commit-templates/prompt.md",
        default_commit_msg="ai: updated prompt",
        extra_paths=entry.extra_paths,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
