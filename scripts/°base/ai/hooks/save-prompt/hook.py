#!/usr/bin/env python3
"""UserPromptSubmit hook: append the user's prompt to ai/prompt.md and commit.

For Codex, also catch up direct user shell-command turns found in the session
transcript and save their output under ai[/°base]/output/commands/.

Usage: hook.py [ai_tool_name]   (default: unknown)

Task notifications (<task-notification> XML) are intercepted and written as a
compact markdown summary block. Agent results are saved to ai/agents/NNN.task-id/
and Explore results to ai/output/explore/NNN.task-id/ (or °base equivalents).
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import compact_result
from _lib import (
    append_and_commit,
    base_ai_commit_subject,
    dump_debug_payload,
    flush_pending_rejections,
    is_cross_tool_duplicate,
    read_payload,
    resolve_log_path,
    slugify,
    stage_and_commit,
    combine,
    either_order,
)

PREFIXES = {"claude": "❯", "codex": "›", "copilot": "◆"}
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
# Copilot CLI's `/plan` mode prepends this literal marker to the submitted
# prompt rather than having the user type a slash command; rendered using the
# same `/plan ...` convention already used for Claude's literal `/plan` prompts.
COPILOT_PLAN_MARKER = "[[PLAN]] "
# Harness-injected autonomous-continuation nudge, not something the user
# typed — must never be logged as a real prompt.
HARNESS_TASK_COMPLETE_REMINDER_PREFIX = (
    "You have not yet marked the task as complete using the task_complete tool."
)
# Harness-injected `/loop` autonomous-tick boilerplate (ScheduleWakeup's
# `<<autonomous-loop-dynamic>>` sentinel, or CronCreate's `<<autonomous-loop>>`
# equivalent): fixed instructional text re-sent verbatim on every tick, not
# something the user typed. Matched by header only, not the full body, since
# the trailing wording differs between the dynamic-pacing and cron variants.
LOOP_TICK_HEADER_RE = re.compile(r"\A#\s+Autonomous loop tick\b[^\n]*")


def _strip_copilot_plan_prompt(prompt: str) -> str:
    if prompt.startswith(COPILOT_PLAN_MARKER):
        return "/plan " + prompt[len(COPILOT_PLAN_MARKER):]
    return prompt

# Single-command prompts we never want to log: internal tooling invocations
# and the most common "please commit now" reminders.
# Claude uses /skill-name, Codex $skill-name.

SKILL_PREFIXES = set('$/')
COMMIT_SKILL = 'commit-with-lplp-style'
COMMIT_SKILLS = combine(SKILL_PREFIXES, COMMIT_SKILL, join='')

SQUASH_INSTRUCTIONS = {
    'commit',
    'squash', 'rebase', 'fold',
    'push',
    *COMMIT_SKILLS,
}

SKIP_PROMPTS = {
    # skills
    *COMMIT_SKILLS,
    *combine(SKILL_PREFIXES, 'todo-loop', join=''),
    *combine(SKILL_PREFIXES, 'code-style', join=''),
    *combine(SKILL_PREFIXES, 'commit-lplp-style', join=''),  # old names
    # common textual phrases for that skill.
    *either_order(
        {
            'yes', 'yes,', 'always',
            'please', 'pls', 'plz',
            'now',
            '',
        },
        {
            "keep committing",
            # squashing/cleanup
            *combine(
                SQUASH_INSTRUCTIONS,
                {
                    '',
                    'it',
                    'ai', '`ai:`', '`ai: `',
                    'todo', 'todos', '`[TODO]`', '`[TODOs]',
                    'unpushed',
                    *combine(
                        combine({'', 'it'}, {'', 'with'}),
                        {'lplp style', '/commit-with-lplp-style'}
                    )
                }
            ),
        },
    ),
    # bumping the AI to continue
    "continue", "go on", "bump",
    # loop
    *combine({'continue', 'resume'}, 'loop'),
    # confirmations
    "yes", "ok", "okay",
    # fix it
    "yes, fix this", "fix", "fix this", "fix it",
    # misc commands
    "/rename",
    "/compact",
}

# Commands skipped with any arguments, e.g. `/code-style .md .py` or `/code-style md`.
SKIP_PROMPT_COMMANDS = {
    "/code-style",
    "$code-style",
}


# The skip check is case-insensitive, so the lists above are written in lowercase.
# Using `str.casefold()` instead of `str.lower()` so `'Ä ä ẞ ß'` -> `'ae ae ss ss'` (instead of 'ä ä ß ß') for more robust matching.
_SKIP_PROMPTS_FOLDED = {prompt.casefold() for prompt in SKIP_PROMPTS}
_SKIP_PROMPT_COMMANDS_FOLDED = {command.casefold() for command in SKIP_PROMPT_COMMANDS}


def is_skipped_prompt(prompt: str) -> bool:
    stripped = prompt.strip().casefold()
    if stripped in _SKIP_PROMPTS_FOLDED:
        return True
    return stripped.split(maxsplit=1)[0] in _SKIP_PROMPT_COMMANDS_FOLDED


class PromptLogEntry(NamedTuple):
    text: str
    preformatted: bool = False
    extra_paths: tuple[Path, ...] = ()


class IdeContext(NamedTuple):
    path: str
    first_line: int | None = None
    last_line: int | None = None


# Claude Code records the IDE state as `selected_lines_in_ide` / `opened_file_in_ide` attachments right behind the
# user record (same `promptId` as the hook payload's `prompt_id`) in the session transcript, not in the prompt text.
CLAUDE_IDE_ATTACHMENT_TYPES = ("selected_lines_in_ide", "opened_file_in_ide")
CLAUDE_TRANSCRIPT_POLL_ATTEMPTS = 5
CLAUDE_TRANSCRIPT_POLL_SECONDS = 0.2
# Codex's IDE extension wraps the real request in a context block.
CODEX_IDE_CONTEXT_RE = re.compile(
    r"\A\s*# Context from my IDE setup:\s*(?P<context>.*?)\s*## My request for Codex:\s*(?P<request>.*)\Z",
    re.DOTALL,
)
CODEX_IDE_ACTIVE_FILE_RE = re.compile(r"(?m)^## Active file:\s*(.+?)\s*$")


class CommandExecution(NamedTuple):
    command: str
    exit_code: str
    duration: str
    output: str


def _parse_user_shell_command(text: str) -> CommandExecution | None:
    """Parse Codex's transcript-only direct-shell-command envelope.

    This is intentionally strict: Codex documents transcript_path as a
    convenience rather than a stable hook interface, so an unfamiliar shape
    must be ignored instead of producing partial or misleading artifacts.
    """
    match = re.fullmatch(
        r"<user_shell_command>\n"
        r"<command>\n(.*?)\n</command>\n"
        r"<result>\n(.*)\n</result>\n"
        r"</user_shell_command>",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return None

    result = re.fullmatch(
        r"Exit code: ([^\n]*)\n"
        r"Duration: ([^\n]*)\n"
        r"Output:\n(.*)",
        match.group(2),
        flags=re.DOTALL,
    )
    if not result:
        return None
    return CommandExecution(
        command=match.group(1),
        exit_code=result.group(1),
        duration=result.group(2),
        output=result.group(3),
    )


def _user_input_texts(obj: dict) -> tuple[str, list[str]] | None:
    """Return (turn_id, input_text values) for a transcript user message."""
    if obj.get("type") != "response_item":
        return None
    message = obj.get("payload")
    if (
        not isinstance(message, dict)
        or message.get("type") != "message"
        or message.get("role") != "user"
    ):
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    texts = [
        item.get("text", "")
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "input_text"
        and isinstance(item.get("text"), str)
    ]
    metadata = message.get("internal_chat_message_metadata_passthrough")
    turn_id = metadata.get("turn_id", "") if isinstance(metadata, dict) else ""
    return turn_id, texts


def _commands_before_current_prompt(payload: dict, prompt: str) -> list[CommandExecution]:
    """Return direct shell commands since the preceding ordinary user prompt."""
    transcript_path = payload.get("transcript_path")
    current_turn_id = payload.get("turn_id")
    if not isinstance(transcript_path, str) or not transcript_path:
        return []
    if not isinstance(current_turn_id, str) or not current_turn_id:
        return []

    pending: list[CommandExecution] = []
    try:
        with open(transcript_path, encoding="utf-8") as transcript:
            for line in transcript:
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                user_message = _user_input_texts(obj)
                if user_message is not None:
                    turn_id, texts = user_message
                    parsed = [
                        command
                        for text in texts
                        if (command := _parse_user_shell_command(text)) is not None
                    ]
                    if parsed:
                        pending.extend(parsed)
                        continue
                    if turn_id == current_turn_id and prompt in texts:
                        return pending

                event = obj.get("payload") if obj.get("type") == "event_msg" else None
                if isinstance(event, dict) and event.get("type") == "user_message":
                    # This is the stable transcript marker for an ordinary
                    # user prompt. Direct shell-command turns have no such
                    # event, so only commands after this boundary remain.
                    pending.clear()
    except OSError:
        return []
    return []


def _queued_commands_before_current_prompt(payload: dict) -> list[str]:
    """Return queued/interjected prompt texts sent while Claude was still
    mid-turn ("type ahead" queueing -- spliced into the ongoing turn's
    context rather than starting a fresh one) since the last genuine
    top-level prompt, up to (not including) the current one.

    These never trigger their own UserPromptSubmit event -- the harness
    doesn't start a new turn for them -- so without this scan they're never
    seen or logged at all. They show up in the transcript as a
    `type: "attachment"` record with `attachment.type == "queued_command"`
    (holding the full text), not as a normal `type: "user"` turn. Mirrors
    Codex's `_commands_before_current_prompt` above, just for this
    Claude-specific envelope shape and boundary marker (`promptId` instead of
    `turn_id`).
    """
    transcript_path = payload.get("transcript_path")
    current_prompt_id = payload.get("prompt_id")
    if not isinstance(transcript_path, str) or not transcript_path:
        return []
    # end if
    if not isinstance(current_prompt_id, str) or not current_prompt_id:
        return []
    # end if

    pending: list[str] = []
    try:
        with open(transcript_path, encoding="utf-8") as transcript:
            for line in transcript:
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                # end try

                if obj.get("type") == "attachment":
                    attachment = obj.get("attachment")
                    if isinstance(attachment, dict) and attachment.get("type") == "queued_command":
                        text = attachment.get("prompt")
                        if isinstance(text, str) and text.strip():
                            pending.append(text)
                        # end if
                        continue
                    # end if
                # end if

                if obj.get("type") == "user" and "promptId" in obj:
                    if obj.get("promptId") == current_prompt_id:
                        return pending
                    # end if
                    # A genuine top-level prompt turn boundary -- anything
                    # queued before it already belongs to that turn, already
                    # captured by save-prompt's own normal logging for it.
                    pending = []
                # end if
            # end for
        # end with
    except OSError:
        return []
    # end try
    return []
# end def


def _capture_claude_queued_commands(payload: dict, prefix: str, log_path: Path) -> None:
    for text in _queued_commands_before_current_prompt(payload):
        append_and_commit(
            log_path,
            f"{prefix} {text}\n\n",
            commit_template_relpath="ai/commit-templates/prompt",
            default_commit_msg="ai: updated prompt",
        )
    # end for
# end def


def _next_command_number(commands_dir: Path) -> int:
    if not commands_dir.exists():
        return 1
    numbers = [
        int(match.group(1))
        for path in commands_dir.iterdir()
        if path.is_file() and (match := re.fullmatch(r"(\d+)\.log", path.name))
    ]
    return max(numbers, default=0) + 1


def _code_fence(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _render_command_execution(
    prefix: str,
    execution: CommandExecution,
    output_file: Path,
    rel_output: str,
) -> str:
    command_lines = execution.command.splitlines() or [""]
    summary = html.escape(f"$ {command_lines[0]}")
    if len(command_lines) > 1:
        summary += " …"
    fence = _code_fence(execution.command)
    command_block = "\n".join([f"$ {command_lines[0]}", *command_lines[1:]])
    output_chars = len(execution.output)
    return (
        f"{prefix} Command executed.\n"
        "> <details><summary>\n"
        ">\n"
        f">> <code>{summary}</code>\n"
        ">\n"
        "> (click to expand)\n"
        ">\n"
        "> </summary>\n"
        ">\n"
        ">> **Command**\n"
        ">\n"
        f"> {fence}console\n"
        + "".join(f"> {line}\n" if line else ">\n" for line in command_block.splitlines())
        + f"> {fence}\n"
        ">\n"
        f">> Exit code: <kbd>{html.escape(execution.exit_code)}</kbd>"
        f" · Duration: `{html.escape(execution.duration)}`\n"
        f">> {_markdown_file_link('Output', output_chars, _human_size(str(output_file)), rel_output)}\n"
        ">\n"
        "> </details>\n"
        ">\n"
        "\n"
    )


def _capture_codex_commands(payload: dict, prompt: str, prefix: str, log_path: Path) -> None:
    commands = _commands_before_current_prompt(payload, prompt)
    if not commands:
        return

    commands_dir = log_path.parent / "output" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    first_number = _next_command_number(commands_dir)
    output_files: list[Path] = []
    blocks: list[str] = []
    for offset, execution in enumerate(commands):
        number = first_number + offset
        output_file = commands_dir / f"{number:03d}.log"
        output_file.write_text(execution.output, encoding="utf-8")
        output_files.append(output_file)
        blocks.append(
            _render_command_execution(
                prefix,
                execution,
                output_file,
                f"output/commands/{output_file.name}",
            )
        )

    last_number = first_number + len(commands) - 1
    if first_number == last_number:
        commit_message = f"ai: command {first_number:03d} result"
    else:
        commit_message = f"ai: commands {first_number:03d}-{last_number:03d} results"
    append_and_commit(
        log_path,
        "".join(blocks),
        commit_template_relpath="ai/commit-templates/prompt",
        default_commit_msg=commit_message,
        extra_paths=tuple(output_files),
    )


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


def render_ide_context(context: IdeContext, log_path: Path, cwd: Path) -> str:
    """Render a `> • [⧉ File …](link)` line for the file (and lines) selected in the IDE."""
    file_path = Path(context.path)
    if not file_path.is_absolute():
        file_path = cwd / file_path
    # end if
    if file_path.is_relative_to(cwd):
        target = Path(os.path.relpath(file_path, log_path.parent)).as_posix()
    else:
        target = file_path.as_posix()
    # end if
    target = quote(target, safe="/°")
    label = f"⧉ File `{file_path.name}`"
    if context.first_line is not None and context.last_line is not None:
        first, last = sorted((context.first_line, context.last_line))
        count = last - first + 1
        label += f": {count} line{'' if count == 1 else 's'} selected"
        target += f"#L{first}" if first == last else f"#L{first}-{last}"
    # end if
    return f"> • [{label}]({target})"
# end def


def find_claude_ide_context(payload: dict) -> IdeContext | None:
    """Look up the IDE selection or opened file Claude attached to the prompt in the session transcript."""
    transcript_path = payload.get("transcript_path")
    prompt_id = payload.get("prompt_id")
    if not transcript_path or not prompt_id:
        return None
    # end if
    for attempt in range(CLAUDE_TRANSCRIPT_POLL_ATTEMPTS):
        if attempt:
            time.sleep(CLAUDE_TRANSCRIPT_POLL_SECONDS)
        # end if
        try:
            lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        # end try
        attachments = claude_prompt_attachments(lines, prompt_id)
        if attachments is None:
            continue
        # end if
        by_type = {attachment.get("type"): attachment for attachment in attachments}
        selection = by_type.get("selected_lines_in_ide")
        if selection and selection.get("filename"):
            return IdeContext(selection["filename"], selection.get("lineStart"), selection.get("lineEnd"))
        # end if
        opened = by_type.get("opened_file_in_ide")
        if opened and opened.get("filename"):
            return IdeContext(opened["filename"])
        # end if
        return None
    # end for
    return None
# end def


def claude_prompt_attachments(lines: list[str], prompt_id: str) -> list[dict] | None:
    """The attachments directly behind the prompt's user record, or `None` while the record is not written yet."""
    for index, line in enumerate(lines):
        if prompt_id not in line:
            continue
        # end if
        try:
            record = json.loads(line)
        except ValueError:
            continue
        # end try
        if record.get("type") != "user" or record.get("promptId") != prompt_id:
            continue
        # end if
        attachments: list[dict] = []
        for following in lines[index + 1:]:
            try:
                follow_record = json.loads(following)
            except ValueError:
                break
            # end try
            if follow_record.get("type") != "attachment":
                break
            # end if
            attachment = follow_record.get("attachment") or {}
            if attachment.get("type") in CLAUDE_IDE_ATTACHMENT_TYPES:
                attachments.append(attachment)
            # end if
        # end for
        return attachments
    # end for
    return None
# end def


def split_codex_ide_context(prompt: str) -> tuple[str, IdeContext | None]:
    """Split Codex's `# Context from my IDE setup:` block off the prompt, returns `(request, active file)`.

    Anything unrecognized returns the prompt untouched, so no user text is ever lost.
    """
    codex = CODEX_IDE_CONTEXT_RE.match(prompt)
    if not codex or not codex.group("request").strip():
        return prompt, None
    # end if
    active = CODEX_IDE_ACTIVE_FILE_RE.search(codex.group("context"))
    return codex.group("request").strip(), IdeContext(active.group(1)) if active else None
# end def


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


def _online_prompt_issue_url(repository: str, issue_number: str) -> str:
    if not repository or not issue_number:
        return ""
    return f"https://github.com/{repository}/issues/{issue_number}"


def _online_prompt_artifact_text(
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
            (
                f"Trigger: @{trigger_username or 'unknown'}"
                f" ({trigger_display_name or 'unknown'}) via {trigger_phrase or 'unknown'}"
            ),
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

    artifact_path = log_path.parent / "plans" / "000_online_prompt.md"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    issue_url = _online_prompt_issue_url(repository, issue_number)
    artifact_path.write_text(
        _online_prompt_artifact_text(
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
        "subagent_type": _text("subagent-type"),
        "status": _text("status"),
        "summary": _text("summary"),
        "result": _text("result"),
        "output_file": _text("output-file"),
        "subagent_tokens": _text("usage/subagent_tokens") or _text("usage/subagent-tokens"),
        "tool_uses": _text("usage/tool_uses") or _text("usage/tool-uses"),
        "duration_ms": _text("usage/duration_ms") or _text("usage/duration-ms"),
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


def _extract_explore_description(output_file: str, tool_use_id: str = "") -> str:
    """Return the description string if the task is an Explore subagent, else ''."""

    def _iter_dicts(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from _iter_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from _iter_dicts(child)

    fallback = ""
    try:
        with open(output_file, encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for item in _iter_dicts(obj):
                    if item.get("type") != "tool_use":
                        continue
                    name = item.get("name", "")
                    inp = item.get("input", {})
                    if name == "Explore":
                        desc = inp.get("description", "")
                        if tool_use_id and item.get("id") == tool_use_id:
                            return desc
                        if not fallback:
                            fallback = desc
                    elif name == "Agent" and inp.get("subagent_type", "").lower() == "explore":
                        desc = inp.get("description", "") or inp.get("prompt", "")[:120]
                        if tool_use_id and item.get("id") == tool_use_id:
                            return desc
                        if not fallback:
                            fallback = desc
    except OSError:
        pass
    return fallback


def _human_tokens(n_str: str) -> str:
    try:
        n = int(n_str)
    except ValueError:
        return n_str
    if n < 1000:
        return str(n)
    return f"{n / 1000:.3g}k"


def _human_duration_ms(ms_str: str) -> str:
    try:
        ms = int(ms_str)
    except ValueError:
        return ms_str
    s = ms // 1000
    m, s = divmod(s, 60)
    if m and s:
        return f"{m}m {s}s"
    if m:
        return f"{m}m"
    return f"{s}s"


def _char_count(path: str) -> int:
    try:
        return len(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def _is_raw_bash_log(path: str) -> bool:
    """Return True if the file is raw shell output rather than a JSONL conversation log."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    json.loads(line)
                    return False
                except json.JSONDecodeError:
                    return True
    except OSError:
        pass
    return False


def _tail_text(path: str, max_chars: int = 3000) -> str:
    """Return the last max_chars characters of a file, with a leading ellipsis if truncated."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) <= max_chars:
        return text
    return "…\n" + text[-max_chars:]


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


def _next_loop_tick_number(loop_dir: Path) -> int:
    if not loop_dir.exists():
        return 1
    numbers = [
        int(m.group(1))
        for path in loop_dir.iterdir()
        if path.is_file() and (m := re.match(r"^(\d+)_", path.name))
    ]
    return max(numbers, default=0) + 1


def _reserve_loop_tick_file(log_path: Path, text: str) -> Path:
    """Return the file holding this exact tick's boilerplate text, reusing an
    existing byte-identical file instead of writing a new one on every tick
    (the harness normally resends the same text unchanged each time)."""
    loop_dir = log_path.parent / "output" / "loop"
    if loop_dir.exists():
        for existing in sorted(loop_dir.glob("*.md")):
            try:
                if existing.read_text(encoding="utf-8") == text:
                    return existing
            except OSError:
                continue
    loop_dir.mkdir(parents=True, exist_ok=True)
    number = _next_loop_tick_number(loop_dir)
    target = loop_dir / f"{number:03d}_{slugify(text, fallback='tick')}.md"
    target.write_text(text, encoding="utf-8")
    return target


def _render_loop_tick_entry(prefix: str, text: str, log_path: Path) -> tuple[str, Path] | None:
    """If ``text`` is the harness's autonomous-/loop-tick boilerplate, write it
    (or reuse a prior byte-identical copy) under output/loop/ and return a
    short linked entry instead of logging the full text again. Returns
    ``None`` for any other prompt text."""
    stripped = text.strip()
    if not LOOP_TICK_HEADER_RE.match(stripped):
        return None
    target = _reserve_loop_tick_file(log_path, stripped)
    header_line = next((line.strip() for line in stripped.splitlines() if line.strip()), "")
    label = header_line.lstrip("#").strip() or "Loop tick"
    rel_target = target.relative_to(log_path.parent).as_posix()
    link = _markdown_file_link(label, len(stripped), _human_size(str(target)), rel_target)
    return f"{prefix} {link}\n\n", target


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


def _parse_compact_autoloads(prompt: str) -> str:
    """Parse ⎿ lines from a compact prompt into a markdown autoload list."""
    lines = []
    for line in prompt.splitlines():
        stripped = line.strip()
        if not stripped.startswith("⎿"):  # ⎿
            continue
        item = stripped[1:].strip()
        if item.lower() == "compacted":
            continue
        m = re.match(r"^Read (.+?) \((\d+) lines?\)$", item)
        if m:
            lines.append(f"- Read `{m.group(1)}` (`{m.group(2)}` lines)")
            continue
        m = re.match(r"^Referenced file (.+)$", item)
        if m:
            lines.append(f"- Referenced file `{m.group(1)}`")
            continue
        m = re.match(r"^Plan file referenced \((.+)\)$", item)
        if m:
            lines.append(f"- Plan file referenced (`{m.group(1)}`)")
            continue
        m = re.match(r"^Skills restored \((.+)\)$", item)
        if m:
            lines.append(f"- Skills restored (`{m.group(1)}`)")
            continue
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n" if lines else ""


def _handle_compact_prompt(
    prefix: str,
    prompt: str,
    payload: dict[str, object],
    log_path: Path,
    commit_template_relpath: str,
    default_commit_msg: str,
) -> bool:
    """If prompt is a /compact result with ⎿ lines, write autoloads and a summary entry."""
    stripped = prompt.strip()
    if not stripped.startswith("/compact") or "⎿" not in stripped:
        return False

    autoloads_text = _parse_compact_autoloads(prompt)
    result_dir = compact_result.reserve_artifact_directory(
        log_path,
        payload,
        "autoloads.md",
        autoloads_text,
    )
    if result_dir is None:
        return True
    dir_name = result_dir.name
    autoloads_file = result_dir / "autoloads.md"
    autoloads_file.write_text(autoloads_text, encoding="utf-8")

    cwd = Path.cwd()
    autoloads_rel = str(autoloads_file.relative_to(cwd))
    stage_and_commit([autoloads_rel], base_ai_commit_subject(f"ai: compact {dir_name} autoloads"))

    rel_autoloads = f"output/compact/{dir_name}/autoloads.md"
    autoload_chars = len(autoloads_text)
    content = (
        f"{prefix} Conversation compacted:\n"
        f"> - {_markdown_file_link('Autoload', autoload_chars, _human_size(str(autoloads_file)), rel_autoloads)}\n"
        "\n"
    )
    append_and_commit(
        log_path,
        content,
        commit_template_relpath=commit_template_relpath,
        default_commit_msg=default_commit_msg,
    )
    return True


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
) -> bool:
    """If prompt contains a task notification, write agent files and a summary entry.

    Returns True when handled; caller should skip the normal append.
    """
    info = _parse_task_notification(prompt)
    if not info or not info["task_id"]:
        return False

    explore_description = _extract_explore_description(info["output_file"], info["tool_use_id"])
    is_explore = bool(explore_description or info.get("subagent_type", "").lower() == "explore")

    if is_explore:
        explore_dir = log_path.parent / "output" / "explore"
        num = _next_agent_number(explore_dir)
        dir_name = f"{num:03d}.{info['task_id']}"
        result_dir = explore_dir / dir_name
        result_dir.mkdir(parents=True, exist_ok=True)

        result_file = result_dir / "result.md"
        result_file.write_text(info["result"], encoding="utf-8")

        rel_result = f"output/explore/{dir_name}/result.md"
        result_chars = len(info["result"])
        log_chars = _char_count(info["output_file"])
        log_size = _human_size(info["output_file"])
        usage = (
            f"> - `{info['tool_uses']}` tools"
            f" · `{_human_tokens(info['subagent_tokens'])}` tokens"
            f" · `{_human_duration_ms(info['duration_ms'])}`\n"
        )
        content = (
            f"{prefix} Exploration <kbd>finished</kbd>:\n"
            f"> - > {explore_description}\n"
            f"> - {_markdown_file_link('Answer', result_chars, _human_size(str(result_file)), rel_result)}\n"
            f"> - {_markdown_file_link('Raw log', log_chars, log_size, info['output_file'])}\n"
            f"{usage}"
            "\n"
        )
        append_and_commit(
            log_path,
            content,
            commit_template_relpath="ai/commit-templates/prompt",
            default_commit_msg=f"ai: explore {dir_name} result",
            extra_paths=(result_file,),
        )
        return True

    agents_dir = log_path.parent / "output" / "agents"
    num = _next_agent_number(agents_dir)
    dir_name = f"{num:03d}.{info['task_id']}"
    agent_dir = agents_dir / dir_name
    agent_dir.mkdir(parents=True, exist_ok=True)

    agent_prompt = _extract_agent_prompt(info["output_file"], info["tool_use_id"])
    result_text = info["result"]

    # Background bash tasks produce raw stdout, not JSONL — _extract_agent_prompt returns "".
    # Fall back to the summary as the query and the log tail as the result.
    if not agent_prompt and info["output_file"] and _is_raw_bash_log(info["output_file"]):
        agent_prompt = info["summary"]
        if not result_text:
            result_text = _tail_text(info["output_file"])

    prompt_file = agent_dir / "prompt.md"
    result_file = agent_dir / "result.md"
    prompt_file.write_text(agent_prompt, encoding="utf-8")
    result_file.write_text(result_text, encoding="utf-8")

    rel_prompt = f"output/agents/{dir_name}/prompt.md"
    rel_result = f"output/agents/{dir_name}/result.md"
    query_chars = len(agent_prompt)
    result_chars = len(result_text)
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
        commit_template_relpath="ai/commit-templates/prompt",
        default_commit_msg=f"ai: agent {dir_name} results",
        extra_paths=(prompt_file, result_file),
    )
    return True


def main() -> int:
    ai_tool = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    prefix = PREFIXES.get(ai_tool, DEFAULT_PREFIX)

    payload = read_payload()
    if is_cross_tool_duplicate(ai_tool):
        return 0
    flush_pending_rejections(payload)
    dump_debug_payload(payload, "save-prompt")
    prompt = payload.get("prompt") or payload.get("user_prompt") or ""
    if not prompt and isinstance(payload.get("tool_input"), dict):
        prompt = payload["tool_input"].get("prompt") or ""
    if not prompt.strip():
        return 0
    log_path = resolve_log_path("ai/prompt.md", "ai/°base/prompt.md")
    if ai_tool == "codex":
        _capture_codex_commands(payload, prompt, prefix, log_path)
    elif ai_tool == "claude":
        _capture_claude_queued_commands(payload, prefix, log_path)
    ide_context: IdeContext | None = None
    if ai_tool == "claude":
        ide_context = find_claude_ide_context(payload)
    elif ai_tool == "codex":
        prompt, ide_context = split_codex_ide_context(prompt)
    # end if
    ide_line = render_ide_context(ide_context, log_path, Path(payload.get("cwd") or ".")) if ide_context else ""
    if is_skipped_prompt(prompt):
        return 0
    if prompt.strip().startswith(HARNESS_TASK_COMPLETE_REMINDER_PREFIX):
        return 0
    preformatted_prompt = False
    entry = PromptLogEntry(prompt)
    if ai_tool == "copilot":
        prompt = _strip_copilot_plan_prompt(prompt)
        entry = PromptLogEntry(prompt)
    elif ai_tool == "codex":
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

    if _handle_compact_prompt(
        prefix, prompt, payload, log_path,
        commit_template_relpath="ai/commit-templates/prompt",
        default_commit_msg="ai: updated prompt",
    ):
        return 0

    remaining_after_task = ""
    if "<task-notification>" in prompt:
        remaining_after_task = re.sub(
            r"<task-notification>.*?</task-notification>", "", prompt, flags=re.DOTALL
        ).strip()

    if _handle_task_notification(prefix, prompt, log_path):
        if remaining_after_task:
            loop_tick = _render_loop_tick_entry(prefix, remaining_after_task, log_path)
            trailing_content, trailing_extra_paths = (
                loop_tick if loop_tick else (f"{prefix} {remaining_after_task}\n\n", None)
            )
            append_and_commit(
                log_path,
                trailing_content,
                commit_template_relpath="ai/commit-templates/prompt",
                default_commit_msg="ai: updated prompt",
                extra_paths=(trailing_extra_paths,) if trailing_extra_paths else (),
            )
        return 0

    loop_tick = None if preformatted_prompt else _render_loop_tick_entry(prefix, prompt, log_path)
    if loop_tick:
        content, loop_extra_path = loop_tick
        extra_paths = entry.extra_paths + (loop_extra_path,)
    else:
        content = f"{prompt}\n\n" if preformatted_prompt else f"{prefix} {prompt}\n\n"
        if ide_line:
            content = content.rstrip("\n") + f"\n{ide_line}\n\n"
        # end if
        extra_paths = entry.extra_paths
    append_and_commit(
        log_path,
        content,
        commit_template_relpath="ai/commit-templates/prompt",
        default_commit_msg="ai: updated prompt",
        extra_paths=extra_paths,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
