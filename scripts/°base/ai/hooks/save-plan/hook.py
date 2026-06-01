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

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _lib import base_ai_commit_subject, read_payload, resolve_log_path, slugify  # noqa: E402

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
    _STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


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
    """Extract plan text when the Write tool writes to ~/.claude/plans/*.md."""
    file_path = tool_input.get("file_path") or ""
    if not re.search(r"/\.claude/plans/[^/]+\.md$", file_path):
        return ""
    return (tool_input.get("content") or "").strip()


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
    log_path = resolve_log_path("ai/query.md", "ai/°base/query.md")
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
# Prefix helpers
# ---------------------------------------------------------------------------

def _next_prefix(plans_dir: Path) -> str:
    highest = 0
    for entry in plans_dir.glob("[0-9]*_*.md"):
        m = re.match(r"^(\d+)_", entry.name)
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{highest + 1:03d}"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _commit(paths: list[str], msg: str) -> None:
    for p in paths:
        if Path(p).exists():
            subprocess.run(["git", "add", "--", p], capture_output=True)
        # Deleted paths are already staged by _git_rm; no add needed.
    msg = base_ai_commit_subject(msg)
    subprocess.run(["git", "commit", "--only", *paths, "-m", msg], capture_output=True)


def _git_rm(path: str) -> None:
    subprocess.run(["git", "rm", "--force", "--", path], capture_output=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ai_tool = sys.argv[1] if len(sys.argv) > 1 else "claude"
    payload = read_payload()
    session_id = payload.get("session_id", "")
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if ai_tool == "codex":
        plan = _plan_from_codex_sources(payload)
    elif tool_name == "Write":
        plan = _plan_from_write(tool_input)
    else:
        plan = (tool_input.get("plan") or "").strip()
        if not plan:
            plan = _plan_from_response(payload.get("tool_response"))

    if not plan:
        return 0

    sentinel = resolve_log_path("ai/plans/.dir", "ai/°base/plans/.dir")
    plans_dir = sentinel.parent
    plans_dir.mkdir(parents=True, exist_ok=True)

    state = _load_state()
    session = state.get(session_id) if session_id else None
    # session shape: {"prefix": "004", "relpath": "ai/°base/plans/004_slug.md",
    #                 "source": "sprightly-mixing-iverson.md"}

    new_slug = slugify(plan, fallback="plan")

    if session:
        prefix = session["prefix"]
        old_relpath = session["relpath"]
        old_path = Path(old_relpath)

        # Skip identical content.
        if old_path.is_file() and old_path.read_text(encoding="utf-8").strip() == plan:
            return 0

        new_relpath = str((plans_dir / f"{prefix}_{new_slug}.md").relative_to(Path.cwd()))
        new_path = plans_dir / f"{prefix}_{new_slug}.md"
        body = plan if plan.endswith("\n") else plan + "\n"

        if old_relpath != new_relpath:
            # Slug changed → rename: remove old, write new, commit both paths.
            _git_rm(old_relpath)
            new_path.write_text(body, encoding="utf-8")
            _commit([old_relpath, new_relpath], f"ai: save plan {prefix}_{new_slug}")
        else:
            # Same filename, updated content.
            new_path.write_text(body, encoding="utf-8")
            _commit([new_relpath], f"ai: save plan {prefix}_{new_slug}")

        session["relpath"] = new_relpath
        _save_state(state)

    else:
        # New session: allocate NNN and create the file.
        prefix = _next_prefix(plans_dir)
        out_path = plans_dir / f"{prefix}_{new_slug}.md"
        relpath = str(out_path.relative_to(Path.cwd()))
        body = plan if plan.endswith("\n") else plan + "\n"
        out_path.write_text(body, encoding="utf-8")
        _commit([relpath], f"ai: save plan {prefix}_{new_slug}")

        if session_id:
            # Capture the harness plan filename as metadata.
            source = Path(tool_input.get("file_path") or "").name
            state[session_id] = {"prefix": prefix, "relpath": relpath, "source": source}
            _save_state(state)

    return 0


if __name__ == "__main__":
    sys.exit(main())
