#!/usr/bin/env python3
"""PostToolUse hook for Write and ExitPlanMode: snapshot the plan into
``ai/plans/NNN_slug.md`` (or ``ai/°base/plans/...`` inside the base meta-repo)
and commit just that file.

Fires on:
- ``Write`` — when the plan file (~/.claude/plans/*.md) is written during
  plan mode; each distinct version gets its own commit.
- ``ExitPlanMode`` — when the user approves the plan; deduplicated so
  identical content doesn't produce a second commit.

Session tracking (keyed by session_id in a temp-dir state file):
- First write → allocate NNN, create ``NNN_slug.md``, commit.
- Later writes in the same session → reuse NNN; rename file if slug changed;
  new commit each time (no amending).
- ExitPlanMode → same dedup: skip if identical to last committed content.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _lib import (  # noqa: E402
    append_and_commit,
    dump_debug_payload,
    find_interjected_text,
    flush_pending_rejections,
    is_cross_tool_duplicate,
    read_payload,
    render_decision_block,
    resolve_log_path,
    slugify,
    stage_and_commit,
)
from importlib import import_module  # noqa: E402

commit_message = import_module("°commit_style_lib").commit_message

_STATE_FILE = Path(tempfile.gettempdir()) / "save-plan-state.json"


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    temporary = _STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    temporary.replace(_STATE_FILE)


def update_session_state(session_id: str, changes: dict) -> None:
    """Merge into the latest state so parallel saves preserve each session."""
    with _STATE_FILE.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = _load_state()
        state.setdefault(session_id, {}).update(changes)
        _save_state(state)


# ---------------------------------------------------------------------------
# Plan extraction
# ---------------------------------------------------------------------------

def _plan_from_response(tool_response) -> str:
    """Extract plan text from the ExitPlanMode tool_response dict."""
    if tool_response is None:
        return ""
    if isinstance(tool_response, dict):
        plan = tool_response.get("plan") or ""
        if plan.strip():
            return plan.strip()
        file_path = tool_response.get("filePath") or ""
        if file_path:
            p = Path(file_path)
            if p.is_file():
                return p.read_text(encoding="utf-8").strip()
        return ""
    if isinstance(tool_response, str):
        return tool_response.strip()
    return ""


def _plan_from_write(tool_input: dict) -> str:
    """Extract plan text when the Write/create tool writes the harness's plan
    file: Claude's ``~/.claude/plans/*.md`` or Copilot's
    ``~/.copilot/session-state/<session_id>/plan.md``."""
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not is_plan_file_path(file_path):
        return ""
    return (tool_input.get("content") or tool_input.get("file_text") or "").strip()


def _plan_from_edit(tool_input: dict) -> str:
    """Extract plan text when the Edit/edit tool patches the harness's plan
    file: Claude's ``~/.claude/plans/*.md`` or Copilot's
    ``~/.copilot/session-state/<session_id>/plan.md``."""
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not is_plan_file_path(file_path):
        return ""
    try:
        return Path(file_path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def is_plan_file_path(file_path: str) -> bool:
    """True for Claude's ``.../.claude/plans/*.md`` (the harness's default),
    ``<CLAUDE_CONFIG_DIR>/plans/*.md`` when the config dir has been relocated
    (e.g. multi-account setups like ``~/.config/claude/accounts/<name>``,
    which moves ``plans/`` along with the rest of the config), or Copilot's
    ``~/.copilot/session-state/<session_id>/plan.md``."""
    if not file_path:
        return False
    if re.search(r"/\.claude/plans/[^/]+\.md$", file_path):
        return True
    if re.search(r"/\.copilot/session-state/[^/]+/plan\.md$", file_path):
        return True
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        plans_dir = Path(config_dir).expanduser() / "plans"
        path = Path(file_path)
        if path.parent == plans_dir and path.suffix == ".md":
            return True
    return False


def plan_from_disk(payload: dict, session: dict | None) -> str:
    """Current text of Claude's plan file, read fresh from disk.

    Bash edits (``echo``, a Python script) fire no ``Write``/``Edit`` hook, so at
    ``ExitPlanMode`` neither ``tool_input.plan`` nor ``tool_response.plan`` is
    guaranteed to match the file. Uses ``tool_response.filePath`` when it is a
    plan file, else the session's recorded ``source`` name in the plans dir.
    Returns ``""`` if the file is missing or unreadable.
    """
    tool_response = payload.get("tool_response")
    file_path = ""
    if isinstance(tool_response, dict):
        file_path = tool_response.get("filePath") or ""
    # end if
    if not is_plan_file_path(file_path):
        file_path = ""
        source = (session or {}).get("source") or ""
        if source:
            config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()
            file_path = str(config_dir / "plans" / source)
        # end if
    # end if
    if not file_path:
        return ""
    # end if
    try:
        return Path(file_path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    # end try
# end def


def _plan_from_copilot_session(payload: dict) -> str:
    """Fallback for Copilot's ``exit_plan_mode`` tool: its ``tool_response``
    doesn't carry the full plan text (that lives in the session's own
    ``plan.md``, already captured by a prior Write/create event). Read it
    directly via the session id when the response has no usable plan."""
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return ""
    plan_path = Path.home() / ".copilot" / "session-state" / session_id / "plan.md"
    if not plan_path.is_file():
        return ""
    return plan_path.read_text(encoding="utf-8").strip()


def _plan_from_codex_stop(payload: dict) -> str:
    """Extract the final proposed plan from a Codex Stop hook payload."""
    if payload.get("hook_event_name") not in {"Stop", "stop"}:
        return ""
    text = payload.get("last_assistant_message") or ""
    m = re.search(r"<proposed_plan>\s*(.*?)\s*</proposed_plan>", text, re.S)
    if not m:
        return ""
    return m.group(1).strip()


def _codex_session_files(session_id: str) -> list[Path]:
    sessions_dir = Path.home() / ".codex" / "sessions"
    if not sessions_dir.is_dir():
        return []
    if session_id:
        files = list(sessions_dir.rglob(f"*{session_id}.jsonl"))
        if files:
            return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
        return []
    return sorted(sessions_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]


def _text_from_codex_message_content(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _proposed_plan_from_text(text: str) -> str:
    m = re.search(r"<proposed_plan>\s*(.*?)\s*</proposed_plan>", text or "", re.S)
    return m.group(1).strip() if m else ""


def _plan_from_codex_transcript(session_id: str) -> str:
    """Extract the latest completed Codex Plan item from the session transcript."""
    latest_final_message = ""
    for path in _codex_session_files(session_id):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload") if isinstance(record, dict) else None
            if not isinstance(payload, dict):
                continue

            if payload.get("type") == "item_completed":
                item = payload.get("item")
                if isinstance(item, dict) and item.get("type") == "Plan":
                    text = item.get("text") or ""
                    if text.strip():
                        return text.strip()

            if not latest_final_message and record.get("type") == "response_item":
                if payload.get("type") == "message" and payload.get("role") == "assistant":
                    latest_final_message = _text_from_codex_message_content(payload.get("content"))

        plan = _proposed_plan_from_text(latest_final_message)
        if plan:
            return plan
    return ""


def _latest_query_entry(text: str) -> str:
    marker = re.compile(r"(?m)^[›❯⩼] ")
    matches = list(marker.finditer(text))
    if not matches:
        return ""
    entry = text[matches[-1].start():].strip()
    return entry[2:].strip()


def _plan_from_codex_query_log() -> str:
    """Fallback for forwarded-plan prompts logged before the Codex Stop hook runs."""
    log_path = resolve_log_path("ai/prompt.md", "ai/°base/prompt.md")
    if not log_path.is_file():
        return ""
    entry = _latest_query_entry(log_path.read_text(encoding="utf-8"))
    if "A previous agent produced the plan below" not in entry:
        return ""
    m = re.search(r"(?m)^# .*\Z", entry, re.S)
    return m.group(0).strip() if m else ""


def _plan_from_codex_sources(payload: dict) -> str:
    if payload.get("hook_event_name") not in {"Stop", "stop"}:
        return ""
    return (
        _plan_from_codex_transcript(str(payload.get("session_id") or ""))
        or _plan_from_codex_stop(payload)
        or _plan_from_codex_query_log()
    )


# ---------------------------------------------------------------------------
# Plan decision recording (Claude only for now -- see
# ai/°base/plans/067_plan-record-plan-and-command-approval-decision-options-and-v.md's
# Phase 4/Phase 3 for how each signal below was confirmed against real
# ExitPlanMode payloads.
#
# Denial recording (Deny / Deny with reason) has no hook of its own -- no
# `PreToolUse`/`PostToolUse`/`Stop` ever fires for a rejected `ExitPlanMode`
# call -- so it's handled by `_lib.flush_pending_rejections`, called from the
# top of every git-committing hook's `main()` (including this one's), rather
# than from any single hook here. See `_lib.PLAN_REJECTION_SPEC` and the
# module docstring on `_lib.flush_pending_rejections` for the full design.
# ---------------------------------------------------------------------------

_COPILOT_DECISIONS_STATE_FILE = Path(tempfile.gettempdir()) / "save-plan-copilot-decisions-state.json"


def _record_claude_plan_acceptance(payload: dict) -> None:
    """Append a `prompt.md` entry for an accepted Claude `ExitPlanMode` call.

    Three outcomes, all confirmed to share the exact same `tool_response`
    shape (`{plan, isAgent, filePath}`) -- distinguished only by two signals
    that live outside `tool_response` entirely:
    - `payload["permission_mode"] == "auto"` marks the "Yes, and use auto
      mode" modifier (confirmed reliable: a plain-accept retest in the same
      session read back `"default"` instead, ruling out a stale leftover).
    - A sibling `text` block in the raw transcript (`_lib.find_interjected_text`)
      carries any note typed via `shift+tab`/`Tab`-amend -- never a hook
      field, and not specific to `ExitPlanMode` (confirmed general across
      `Edit`/`Bash`/`Read` too).
    """
    tool_use_id = payload.get("tool_use_id", "")
    note = find_interjected_text(payload.get("transcript_path", ""), tool_use_id)

    if note:
        label, detail = "Plan accepted:", note
    elif payload.get("permission_mode") == "auto":
        label, detail = "Plan accepted, auto mode.", None
    else:
        label, detail = "Plan accepted.", None

    log_path = resolve_log_path("ai/prompt.md", "ai/°base/prompt.md")
    append_and_commit(
        log_path,
        render_decision_block(label, detail),
        commit_template_relpath="ai/commit-templates/decision",
        default_commit_msg="ai: save plan decision",
    )


def _load_recorded_copilot_decision_ids() -> set[str]:
    try:
        return set(json.loads(_COPILOT_DECISIONS_STATE_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_recorded_copilot_decision_ids(ids: set[str]) -> None:
    _COPILOT_DECISIONS_STATE_FILE.write_text(json.dumps(sorted(ids)), encoding="utf-8")


def _copilot_session_events(session_id: str) -> list[dict]:
    if not session_id:
        return []
    path = Path.home() / ".copilot" / "session-state" / session_id / "events.jsonl"
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def _record_copilot_plan_blocks(blocks: list[str]) -> None:
    if not blocks:
        return
    append_and_commit(
        resolve_log_path("ai/prompt.md", "ai/°base/prompt.md"),
        "".join(blocks),
        commit_template_relpath="ai/commit-templates/decision",
        default_commit_msg="ai: save plan decision",
    )


def _record_copilot_plan_acceptances(payload: dict) -> None:
    """Record Copilot's real `/plan` accepts from its session event log.

    Copilot emits no ExitPlanMode-style hook event for menu options 1 and 2.
    Its append-only ``events.jsonl`` instead records ``session.mode_changed``
    from ``plan`` to ``interactive`` (ordinary accept) or ``autopilot``. This
    runs from Stop, after that choice is visible in the event log.
    """
    if payload.get("hook_event_name") not in {"Stop", "stop"}:
        return
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "")
    recorded = _load_recorded_copilot_decision_ids()
    blocks: list[str] = []
    for index, event in enumerate(_copilot_session_events(session_id)):
        if event.get("type") != "session.mode_changed":
            continue
        data = event.get("data")
        if not isinstance(data, dict) or data.get("previousMode") != "plan":
            continue
        new_mode = data.get("newMode")
        if new_mode not in {"interactive", "autopilot"}:
            continue
        decision_id = f"accept:{session_id}:{index}:{new_mode}"
        if decision_id in recorded:
            continue
        label = "Plan accepted, autopilot." if new_mode == "autopilot" else "Plan accepted."
        blocks.append(render_decision_block(label, None))
        recorded.add(decision_id)

    _record_copilot_plan_blocks(blocks)
    if blocks:
        _save_recorded_copilot_decision_ids(recorded)


def _record_copilot_exit_only(payload: dict) -> None:
    """Record Copilot's option 3, which has an explicit post-tool marker.

    The same mode transition as an ordinary acceptance (``plan`` to
    ``interactive``) accompanies this option, so mark that transition as
    consumed before a later Stop scan can mistake it for an acceptance.
    """
    tool_response = payload.get("tool_response") or {}
    session_log = tool_response.get("sessionLog") if isinstance(tool_response, dict) else ""
    if "exit_only" not in session_log:
        return
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "")
    tool_use_id = str(payload.get("tool_use_id") or "")
    decision_id = f"exit-only:{session_id}:{tool_use_id}"
    recorded = _load_recorded_copilot_decision_ids()
    if decision_id in recorded:
        return
    _record_copilot_plan_blocks([render_decision_block("Plan exited.", None)])
    recorded.add(decision_id)
    for index, event in enumerate(_copilot_session_events(session_id)):
        data = event.get("data") if isinstance(event, dict) else None
        if event.get("type") == "session.mode_changed" and isinstance(data, dict) and data.get("previousMode") == "plan" and data.get("newMode") == "interactive":
            recorded.add(f"accept:{session_id}:{index}:interactive")
    _save_recorded_copilot_decision_ids(recorded)


# ---------------------------------------------------------------------------
# Prefix helpers
# ---------------------------------------------------------------------------
# Todo capture
# ---------------------------------------------------------------------------

_TODO_CHECKBOXES = {
    "done": "[x]",
    "completed": "[x]",
    "in_progress": "[ ]",
    "pending": "[ ]",
    "blocked": "[ ]",
}
_TODO_SUFFIXES = {
    "in_progress": " *(in progress)*",
    "blocked": " *(blocked)*",
}
_TODOS_HEADING = "## Todos"


def _normalize_todos(tool_input: dict) -> list[dict]:
    """Normalize a TodoWrite (Claude) / update_todo (Copilot) tool_input into
    a flat list of ``{"text": str, "status": str}`` items.

    Claude's TodoWrite: ``todos: [{content, status, activeForm}]``.
    Copilot's update_todo schema isn't pinned down by the docs at
    implementation time, so several plausible field names are accepted
    defensively (``items``/``todo_list`` as list containers; ``title``/
    ``task``/``description`` as text fields).
    """
    raw = (
        tool_input.get("todos")
        or tool_input.get("items")
        or tool_input.get("todo_list")
        or []
    )
    if not isinstance(raw, list):
        return []
    todos: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = (
            item.get("content")
            or item.get("title")
            or item.get("task")
            or item.get("description")
            or ""
        ).strip()
        if not text:
            continue
        status = str(item.get("status") or "pending").strip().lower()
        todos.append({"text": text, "status": status})
    return todos


def _render_todos_markdown(todos: list[dict]) -> str:
    """Render normalized todos into a ``## Todos`` markdown section (no
    trailing section separator). Returns "" when there are no todos."""
    if not todos:
        return ""
    lines = [_TODOS_HEADING, ""]
    for item in todos:
        status = item["status"]
        checkbox = _TODO_CHECKBOXES.get(status, "[ ]")
        suffix = _TODO_SUFFIXES.get(status, "")
        lines.append(f"- {checkbox} {item['text']}{suffix}")
    return "\n".join(lines)


def _apply_todos_section(plan_text: str, todos_md: str) -> str:
    """Idempotently replace-or-append the ``## Todos`` section in a saved plan
    snapshot: replaces an existing section (heading through the next
    top-level ``## `` heading or EOF), or appends one at the end."""
    plan_text = plan_text.rstrip("\n")
    pattern = re.compile(
        rf"(?ms)^{re.escape(_TODOS_HEADING)}\s*$.*?(?=^## |\Z)"
    )
    if pattern.search(plan_text):
        new_text = pattern.sub(lambda _m: todos_md + "\n", plan_text, count=1)
    else:
        new_text = plan_text + "\n\n" + todos_md + "\n"
    return new_text.rstrip("\n") + "\n"


# ---------------------------------------------------------------------------

def next_prefix(plans_dir: Path, git_root: Path) -> str:
    relative_dir = plans_dir.relative_to(git_root)
    entries = subprocess.check_output(["git", "worktree", "list", "--porcelain", "-z"], cwd=git_root)
    highest = 0
    for record in entries.split(b"\0\0"):
        entry, *attributes = record.split(b"\0")
        if not entry.startswith(b"worktree ") or b"bare" in attributes:
            continue
        directory = Path(os.fsdecode(entry.removeprefix(b"worktree "))) / relative_dir
        for plan in directory.glob("[0-9]*_*.md"):
            match = re.match(r"^(\d+)_", plan.name)
            if match and plan.is_file():
                highest = max(highest, int(match.group(1)))
    return f"{highest + 1:03d}"


@contextmanager
def plan_number_lock(git_root: Path) -> Iterator[None]:
    common_dir = subprocess.check_output(["git", "rev-parse", "--git-common-dir"], cwd=git_root)
    lock_path = git_root / os.fsdecode(common_dir.removesuffix(b"\n")) / "save-plan-number.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _commit(paths: list[str], msg: str) -> None:
    # Deleted paths are already staged by _git_rm; `stage_and_commit` still commits those.
    msg = commit_message("ai/commit-templates/plan", msg)
    stage_and_commit(paths, msg)


def _git_rm(path: str) -> None:
    subprocess.run(["git", "rm", "--force", "--", path], capture_output=True)


# ---------------------------------------------------------------------------
# Todo capture handler
# ---------------------------------------------------------------------------

def _apply_todos_and_commit(session_id: str, todos: list[dict]) -> int:
    """Shared tail end of todo capture: inject `todos` into the session's
    already-saved plan snapshot (if any) as a ``## Todos`` section, and
    commit. Silently no-ops when there's no session, no saved plan snapshot
    yet, or no todos to render -- this is a best-effort enrichment, not a
    plan-creation path.

    Commit message is `ai: Todo added` the first time the section is
    created, `ai: Todo updated` on every later change.
    """
    if not session_id:
        return 0
    state = _load_state()
    session = state.get(session_id)
    if not session:
        return 0
    relpath = session.get("relpath")
    if not relpath:
        return 0
    plan_path = Path(relpath)
    if not plan_path.is_file():
        return 0

    todos_md = _render_todos_markdown(todos)
    if not todos_md:
        return 0

    current = plan_path.read_text(encoding="utf-8")
    heading_existed = bool(re.search(rf"(?ms)^{re.escape(_TODOS_HEADING)}\s*$", current))
    updated = _apply_todos_section(current, todos_md)
    if updated == current:
        return 0

    plan_path.write_text(updated, encoding="utf-8")
    _commit([relpath], "ai: Todo updated" if heading_existed else "ai: Todo added")
    return 0


def _handle_todo_capture(session_id: str, tool_input: dict) -> int:
    """On TodoWrite/update_todo, inject the current (complete) todo list
    into the session's saved plan snapshot."""
    return _apply_todos_and_commit(session_id, _normalize_todos(tool_input))


def _handle_task_tool_capture(
    session_id: str, tool_name: str, tool_input: dict, tool_response: dict
) -> int:
    """On TaskCreate/TaskUpdate, accumulate per-session task state.

    Unlike TodoWrite/update_todo (which resend the *entire* current list
    every call), TaskCreate/TaskUpdate each mutate a single task -- so the
    full list has to be tracked across calls in the session state file
    (`tasks: {taskId: {"text": str, "status": str}}`), keyed the same way
    `prefix`/`relpath` already are.
    """
    if not session_id:
        return 0
    state = _load_state()
    session = state.setdefault(session_id, {})
    tasks: dict = session.setdefault("tasks", {})

    if tool_name == "TaskCreate":
        task_id = str((tool_response.get("task") or {}).get("id") or "")
        if not task_id:
            return 0
        text = tool_input.get("subject") or (tool_response.get("task") or {}).get("subject") or ""
        tasks[task_id] = {"text": text, "status": "pending"}
    else:  # TaskUpdate
        task_id = str(tool_input.get("taskId") or tool_response.get("taskId") or "")
        if not task_id:
            return 0
        if tool_input.get("status") == "deleted":
            tasks.pop(task_id, None)
        else:
            entry = tasks.setdefault(task_id, {"text": "", "status": "pending"})
            if tool_input.get("subject"):
                entry["text"] = tool_input["subject"]
            if tool_input.get("status"):
                entry["status"] = tool_input["status"]

    update_session_state(session_id, {"tasks": tasks})
    return _apply_todos_and_commit(session_id, list(tasks.values()))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ai_tool = sys.argv[1] if len(sys.argv) > 1 else "claude"
    payload = read_payload()
    if is_cross_tool_duplicate(ai_tool):
        return 0
    flush_pending_rejections(payload)
    dump_debug_payload(payload, "save-plan")
    session_id = payload.get("session_id", "")
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool_name in ("TodoWrite", "update_todo"):
        return _handle_todo_capture(session_id, tool_input)
    if tool_name in ("TaskCreate", "TaskUpdate"):
        tool_response = payload.get("tool_response") or {}
        return _handle_task_tool_capture(session_id, tool_name, tool_input, tool_response)

    if ai_tool == "copilot":
        _record_copilot_plan_acceptances(payload)
        if tool_name == "exit_plan_mode":
            _record_copilot_exit_only(payload)

    plan = ""
    if ai_tool == "codex":
        plan = _plan_from_codex_sources(payload)
    elif tool_name in ("Write", "create"):
        plan = _plan_from_write(tool_input)
    elif tool_name in ("Edit", "edit"):
        plan = _plan_from_edit(tool_input)
    elif tool_name in ("ExitPlanMode", "exit_plan_mode"):
        if ai_tool == "claude":
            plan = plan_from_disk(payload, _load_state().get(session_id))
        # end if
        if not plan:
            plan = (tool_input.get("plan") or "").strip()
        if not plan:
            plan = _plan_from_response(payload.get("tool_response"))
        if not plan:
            plan = _plan_from_copilot_session(payload)
        if plan and ai_tool == "claude":
            _record_claude_plan_acceptance(payload)
    # Stop for Claude: no plan extraction — Write/ExitPlanMode already handled it.

    if not plan:
        return 0

    sentinel = resolve_log_path("ai/plans/.dir", "ai/°base/plans/.dir")
    plans_dir = sentinel.parent
    plans_dir.mkdir(parents=True, exist_ok=True)
    git_root = Path.cwd()

    state = _load_state()
    session = state.get(session_id) if session_id else None
    # session shape: {"prefix": "004", "relpath": "ai/°base/plans/004_slug.md",
    #                 "source": "sprightly-mixing-iverson.md", "done": bool,
    #                 "tasks": {taskId: {"text": str, "status": str}}}
    # `tasks` may exist without `prefix`/`relpath` yet (TaskCreate/TaskUpdate
    # firing before any plan has been saved this session) -- only a `prefix`
    # means there's an actual plan snapshot to treat as "the session".
    if session and not session.get("prefix"):
        session = None

    # When Write fires after ExitPlanMode committed the previous plan (same session),
    # treat it as a brand-new plan and allocate a fresh prefix.
    if session and tool_name in ("Write", "create") and session.get("done"):
        session = None

    new_slug = slugify(plan, fallback="plan")
    body = plan if plan.endswith("\n") else plan + "\n"

    if session:
        prefix = session["prefix"]
        old_relpath = session["relpath"]
        old_path = Path(old_relpath)

        # Skip identical content.
        if old_path.is_file() and old_path.read_text(encoding="utf-8").strip() == plan:
            if tool_name in ("ExitPlanMode", "exit_plan_mode") and session_id:
                update_session_state(session_id, {"done": True})
            return 0

        new_path = plans_dir / f"{prefix}_{new_slug}.md"
        new_relpath = str(new_path.relative_to(git_root))
        if old_relpath != new_relpath:
            with plan_number_lock(git_root):
                new_path.write_text(body, encoding="utf-8")
                _git_rm(old_relpath)
            _commit([old_relpath, new_relpath], f"ai: save plan {prefix}_{new_slug}")
        else:
            new_path.write_text(body, encoding="utf-8")
            _commit([new_relpath], f"ai: save plan {prefix}_{new_slug}")

        update_session_state(session_id, {"relpath": new_relpath})

    else:
        # New session: allocate NNN and create the file.
        with plan_number_lock(git_root):
            prefix = next_prefix(plans_dir, git_root)
            out_path = plans_dir / f"{prefix}_{new_slug}.md"
            out_path.write_text(body, encoding="utf-8")
        relpath = str(out_path.relative_to(git_root))
        _commit([relpath], f"ai: save plan {prefix}_{new_slug}")

        if session_id:
            # Capture the harness plan filename as metadata alongside any existing tasks.
            source = Path(tool_input.get("file_path") or tool_input.get("path") or "").name
            update_session_state(session_id, {"prefix": prefix, "relpath": relpath, "source": source, "done": False})

    # After ExitPlanMode fires, mark this plan session done so that a subsequent
    # Write (new /plan command in the same Claude session) allocates a fresh prefix.
    if tool_name in ("ExitPlanMode", "exit_plan_mode") and session_id:
        update_session_state(session_id, {"done": True})

    return 0


if __name__ == "__main__":
    sys.exit(main())
