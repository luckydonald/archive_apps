#!/usr/bin/env python3
"""Shared helpers for the prompt-log hooks (save-prompt, save-decision).

Both hooks append a markdown entry to a per-repo prompt log (typically
`ai/prompt.md`) and auto-commit only that file, while preserving any user-staged
edits to the same file via :mod:`merge_staged`.
"""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Callable, NamedTuple, Literal

# Sibling-module import (this package can't be imported as a real package
# because parent dirs contain non-ASCII / hyphenated names).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_staged import merge as _merge_lines  # noqa: E402
from importlib import import_module  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "git"))
stage_and_commit = import_module("°scoped_commit_lib").stage_and_commit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
migrate_query_to_prompt = import_module("migrate_query_to_prompt")

_commit_style = import_module("°commit_style_lib")
base_ai_commit_subject = _commit_style.base_ai_commit_subject
_commit_message = _commit_style.commit_message
_is_inside_base_repo = _commit_style._is_inside_base_repo
_read_by_issue = _commit_style._read_by_issue
_ai_root = _commit_style._ai_root


def combine(
    a: str | Iterable[str],
    b: str | Iterable[str],
    *,
    join: Literal['', ' '] | str = ' ',
) -> set[str]:
    if isinstance(a, str) and isinstance(b, str):
        # depending on the other being empty: `a + join + b` OR `a` / `b`
        return {a + join + b if a and b else a or b}
    if isinstance(a, Iterable):
        return {
            *(combine(_a, b, join=join) for _a in a)
        }
    # second if -> so we know isinstance(a, str)
    assert isinstance(a, str), repr(a)
    # because also first if -> we know isinstance(b, Iterable) because they can't both be str
    assert isinstance(b, Iterable), repr(b)
    return {
        *(combine(a, _b, join=join) for _b in b)
    }

def either_order(
    a: str | Iterable[str],
    b: str | Iterable[str],
    *,
    join: Literal['', ' '] | str = ' ',
) -> set[str]:
    return {
        *(combine(a, b, join=join)),
        *(combine(b, a, join=join)),
    }



def read_payload() -> dict:
    """Parse the JSON payload from stdin, returning ``{}`` on any error."""
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def _ai_prefix_root() -> tuple[Path, str]:
    """Return (ai_root, ai_prefix), where ai_prefix is ``ai/°base``
    inside the base repo itself and plain ``ai`` in a consuming repo."""
    subproject = _ai_root()
    git_root_str = _git_text("rev-parse", "--show-toplevel")
    git_root = Path(git_root_str) if git_root_str else subproject
    is_base = _is_inside_base_repo(subproject) or _is_inside_base_repo(git_root)
    ai_prefix = "ai/°base" if is_base else "ai"
    return subproject, ai_prefix


def dump_debug_payload(payload: dict, hook_name: str) -> None:
    """If ai[/°base]/.debug exists, write payload JSON to ai[/°base]/output/debug/."""
    subproject, ai_prefix = _ai_prefix_root()
    if not (subproject / ai_prefix / ".debug").is_file():
        return
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S_%f")
    debug_dir = subproject / ai_prefix / "output" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / f"{ts}-{hook_name}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _pending_decisions_dir() -> Path:
    subproject, ai_prefix = _ai_prefix_root()
    d = subproject / ai_prefix / "output" / ".pending-decisions"
    d.mkdir(parents=True, exist_ok=True)
    return d


PENDING_DECISION_STALE_SECONDS = 30 * 60  # orphan-cleanup threshold, see sweep_pending_decisions


def _pending_decision_path(session_id: str, tool_use_id: str) -> Path:
    # session_id/tool_use_id are opaque harness-generated tokens (never
    # containing path separators in practice), joined so a sweep can tell
    # which session a marker belongs to -- see sweep_pending_decisions.
    return _pending_decisions_dir() / f"{session_id or 'unknown'}__{tool_use_id}.md"


def write_pending_decision(session_id: str, tool_use_id: str, rendered_block: str) -> None:
    """Persist a pre-rendered markdown block for an in-flight AskUserQuestion
    call, keyed by ``session_id``+``tool_use_id``. Claude Code fires no
    PostToolUse, PostToolUseFailure, or PermissionDenied hook when the user
    manually declines the question (e.g. via "chat about this"), so the
    question would otherwise be lost. Written at PreToolUse time, before the
    answer is known; deleted by :func:`delete_pending_decision` if the call is
    answered normally, or picked up by :func:`sweep_pending_decisions` if it
    isn't."""
    if not tool_use_id:
        return
    _pending_decision_path(session_id, tool_use_id).write_text(rendered_block, encoding="utf-8")


def delete_pending_decision(session_id: str, tool_use_id: str) -> None:
    """Remove the pending marker for a now-answered AskUserQuestion call."""
    if not tool_use_id:
        return
    _pending_decision_path(session_id, tool_use_id).unlink(missing_ok=True)


def sweep_pending_decisions(session_id: str) -> None:
    """Append+commit any leftover pending-decision markers (AskUserQuestion
    calls the user canceled instead of answering) to prompt.md, then delete
    them. Safe to call often: a no-op when nothing needs sweeping.

    Two Claude Code instances can share the same working directory (two
    terminals in the same non-worktree checkout), each with its own
    in-flight, not-yet-answered question. To avoid one session's Stop hook
    misclassifying *another still-live session's* question as canceled, this
    only sweeps: (a) markers belonging to ``session_id`` itself, and (b)
    markers from *any* session old enough (`PENDING_DECISION_STALE_SECONDS`)
    that the owning session almost certainly crashed/exited without ever
    reaching its own Stop -- a live session resolves its single in-flight
    question (answered or swept) within one turn, far under that threshold."""
    pending_dir = _pending_decisions_dir()
    own_prefix = f"{session_id or 'unknown'}__"
    now = time.time()

    to_sweep: list[Path] = []
    for marker in sorted(pending_dir.glob("*.md")):
        if marker.name.startswith(own_prefix):
            to_sweep.append(marker)
            continue
        try:
            age = now - marker.stat().st_mtime
        except OSError:
            continue
        if age >= PENDING_DECISION_STALE_SECONDS:
            to_sweep.append(marker)

    blocks: list[str] = []
    for marker in to_sweep:
        try:
            text = marker.read_text(encoding="utf-8")
        except OSError:
            marker.unlink(missing_ok=True)
            continue
        if not marker.name.startswith(own_prefix):
            text = re.sub(
                r"(Question canceled \(chat about this\))\.\n",
                r"\1, stale -- orphaned session.\n",
                text,
                count=1,
            )
        blocks.append(text)
        marker.unlink(missing_ok=True)
    if not blocks:
        return
    log_path = resolve_log_path("ai/prompt.md", "ai/°base/prompt.md")
    append_and_commit(
        log_path,
        "".join(blocks),
        commit_template_relpath="ai/commit-templates/decision",
        default_commit_msg="ai: save canceled decision",
    )


_REJECTION_PREFIX = "The user doesn't want to proceed with this tool use."
_REJECTION_REASON_RE = re.compile(r"user said:\n(.*)\Z", re.S)
# Claude Code appends this boilerplate to a typed deny reason; it is not something the user wrote.
_REJECTION_CORRECTION_NOTE_RE = re.compile(r"\s*Note: The user's next message may contain a correction or preference\..*\Z", re.S)


def _merge_transcript_records(
    records: list[dict], tool_uses: dict[str, tuple[str, dict]], events: dict[str, dict]
) -> None:
    """Pair ``tool_use``/``tool_result`` blocks from ``records`` into
    ``events``, mutating ``tool_uses``/``events`` in place so this can be
    called incrementally across multiple batches of records (see
    :func:`load_transcript_tool_events`)."""
    for obj in records:
        message = obj.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue

        if obj.get("type") == "assistant":
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_id = block.get("id")
                    if tool_id:
                        tool_uses[tool_id] = (block.get("name") or "", block.get("input") or {})
            continue

        if obj.get("type") != "user":
            continue
        for index, block in enumerate(content):
            if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                continue
            tool_id = block.get("tool_use_id")
            if not tool_id:
                continue
            raw_content = block.get("content")
            note = None
            if index + 1 < len(content):
                sibling = content[index + 1]
                if isinstance(sibling, dict) and sibling.get("type") == "text":
                    note = sibling.get("text")
            name, tool_input = tool_uses.get(tool_id, ("", {}))
            events[tool_id] = {
                "tool_name": name,
                "tool_input": tool_input,
                "is_error": bool(block.get("is_error")),
                "content": raw_content if isinstance(raw_content, str) else "",
                "note": note,
            }


def _transcript_cache_path(transcript_path: str) -> Path:
    digest = hashlib.sha1(transcript_path.encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"transcript-scan-cache-{digest}.json"


def _load_transcript_cache(cache_path: Path) -> dict:
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_transcript_cache_atomic(cache_path: Path, data: dict) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=str(cache_path.parent), prefix=cache_path.name + ".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_name, cache_path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)


def _try_write_transcript_cache(cache_path: Path, data: dict) -> None:
    """Best-effort, non-blocking persist of a freshly-computed transcript
    cache. Skips (never blocks, never raises) if another process currently
    holds the write lock, or if the persisted cache already reflects an
    offset `>=` ours -- see the plan doc's "efficiency" section for why a
    plain last-writer-wins overwrite isn't safe here (a long-preempted writer
    could otherwise regress a newer cache) but a full lock-held-across-parse
    also isn't needed (only the tiny compare+write step needs it)."""
    lock_path = cache_path.with_name(cache_path.name + ".lock")
    try:
        lock_file = open(lock_path, "a")
    except OSError:
        return
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            current = _load_transcript_cache(cache_path)
            if current.get("offset", 0) >= data["offset"]:
                return
            _write_transcript_cache_atomic(cache_path, data)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def _read_new_transcript_records(transcript_path: str, offset: int) -> tuple[list[dict], int]:
    """Read and parse complete lines starting at byte ``offset``. Returns
    ``(records, new_offset)`` where ``new_offset`` is the byte position right
    after the last fully-consumed line -- any trailing partial line (a writer
    mid-flush) is left unconsumed for the next call."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
    except OSError:
        return [], offset
    if not chunk:
        return [], offset
    last_newline = chunk.rfind(b"\n")
    if last_newline == -1:
        return [], offset
    consumed = chunk[:last_newline + 1]
    new_offset = offset + len(consumed)
    records: list[dict] = []
    for line in consumed.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records, new_offset


def load_transcript_tool_events(transcript_path: str) -> dict[str, dict]:
    """Parse a session transcript JSONL into ``{tool_use_id: event}``, one
    entry per ``tool_use``/``tool_result`` pair found, where ``event`` is::

        {"tool_name": str, "tool_input": dict, "is_error": bool,
         "content": str, "note": str | None}

    ``content`` is the ``tool_result`` block's own text (only ever a plain
    string for a denied call -- Claude Code's synthetic rejection message).
    ``note`` is a sibling ``{"type": "text", ...}`` content entry immediately
    following the ``tool_result`` block in the same transcript message, when
    present: confirmed (repeatedly, across `ExitPlanMode`, `Edit`, `Bash`,
    `Read`) to be how Claude Code delivers *any* message the user sends while
    a tool call is in flight -- not a field specific to one tool or dialog,
    and never exposed to any hook directly. Both `note` and a denial's typed
    reason (see :func:`rejection_reason`) exist only here, in the raw
    transcript -- there is no hook-visible field for either.

    Every hook payload already carries ``payload["transcript_path"]``, so no
    extra plumbing is needed to call this.

    Backed by a small disk cache keyed off ``transcript_path`` (session
    transcripts are append-only for the life of a session), since this now
    gets called from nearly every git-committing hook via
    :func:`flush_pending_rejections` instead of just one. The cache is a pure
    memoization of a deterministic function over an immutable byte prefix --
    see :func:`_try_write_transcript_cache` for why the write side still
    needs a small guard even so.
    """
    if not transcript_path:
        return {}
    try:
        current_size = Path(transcript_path).stat().st_size
    except OSError:
        return {}

    cache_path = _transcript_cache_path(transcript_path)
    cache = _load_transcript_cache(cache_path)
    offset = cache.get("offset", 0) if isinstance(cache.get("offset"), int) else 0
    cached_size = cache.get("size", 0) if isinstance(cache.get("size"), int) else 0
    pending_raw = cache.get("pending_tool_uses") or {}
    events: dict[str, dict] = dict(cache.get("events") or {})
    tool_uses: dict[str, tuple[str, dict]] = {
        tid: (v[0], v[1])
        for tid, v in pending_raw.items()
        if isinstance(v, list) and len(v) == 2
    }

    if current_size < cached_size:
        # Transcript shrank (truncated/rotated) -- shouldn't normally
        # happen, but be defensive and rescan from scratch.
        offset, tool_uses, events = 0, {}, {}

    records, new_offset = _read_new_transcript_records(transcript_path, offset)
    if records:
        _merge_transcript_records(records, tool_uses, events)

    if new_offset != offset:
        _try_write_transcript_cache(cache_path, {
            "offset": new_offset,
            "size": current_size,
            "pending_tool_uses": {tid: list(v) for tid, v in tool_uses.items()},
            "events": events,
        })

    return events


def find_interjected_text(transcript_path: str, tool_use_id: str) -> str | None:
    """Return the note/instructions the user typed while ``tool_use_id``'s
    tool call was in flight, if any -- see :func:`load_transcript_tool_events`
    for what this actually is and why it's only ever found here."""
    if not tool_use_id:
        return None
    return load_transcript_tool_events(transcript_path).get(tool_use_id, {}).get("note")


def is_rejection(content: str) -> bool:
    """True when ``content`` is Claude Code's synthetic tool-rejection
    message (denying any tool call, not just `ExitPlanMode`)."""
    return content.startswith(_REJECTION_PREFIX)


def rejection_reason(content: str) -> str | None:
    """Extract the typed deny reason from a rejection message, or ``None``
    when the user denied without typing one (a different, shorter message
    with no ``"user said:"`` clause -- see :func:`is_rejection`)."""
    match = _REJECTION_REASON_RE.search(content)
    if not match:
        return None
    reason = _REJECTION_CORRECTION_NOTE_RE.sub("", match.group(1)).strip()
    return reason or None


def _filter_rejections(
    events: dict[str, dict], tool_names: frozenset[str] | set[str], already_recorded: set[str]
) -> list[dict]:
    """Filter an already-parsed ``{tool_use_id: event}`` map (from
    :func:`load_transcript_tool_events`) for denied calls to any of
    ``tool_names``, skipping ``tool_use_id``s already in ``already_recorded``.
    Returns ``{"tool_use_id", "tool_name", "tool_input", "reason"}`` dicts
    (``reason`` is ``None`` for a denial without one)."""
    results = []
    for tool_id, event in events.items():
        if tool_id in already_recorded:
            continue
        if event["tool_name"] not in tool_names:
            continue
        if not event["is_error"] or not is_rejection(event["content"]):
            continue
        results.append({
            "tool_use_id": tool_id,
            "tool_name": event["tool_name"],
            "tool_input": event["tool_input"],
            "reason": rejection_reason(event["content"]),
        })
    return results


def find_tool_rejections(
    transcript_path: str, tool_names: set[str], already_recorded: set[str]
) -> list[dict]:
    """Scan the transcript for denied calls to any of ``tool_names``, skipping
    ``tool_use_id``s already in ``already_recorded``. Returns a list of
    ``{"tool_use_id", "tool_name", "tool_input", "reason"}`` dicts (``reason``
    is ``None`` for a denial without one) in transcript order.

    No hook fires for a denied tool call (`PreToolUse` doesn't exist for most
    gated tools including `ExitPlanMode`; `PostToolUse` only fires on
    success; `Stop` was observed unreliable) -- callers should invoke this
    from whatever hook reliably fires *next* in the session (empirically
    `UserPromptSubmit`), tracking `tool_use_id`s already recorded across
    calls in a state file to avoid double-recording. Most git-committing
    hooks should prefer :func:`flush_pending_rejections` instead, which
    covers both plan and command denials from a single transcript parse and
    handles the commit/state-file race -- this is kept for direct/one-off use.
    """
    return _filter_rejections(load_transcript_tool_events(transcript_path), tool_names, already_recorded)


def render_decision_block(label: str, detail: str | None) -> str:
    """Render a simple ``❯ {label}`` decision block, with ``detail`` (if any)
    quoted below it line by line. Shared by every hook that records a
    plan/command accept or deny into the prompt log."""
    out = [f"❯ {label}\n"]
    if detail:
        for line in detail.splitlines():
            out.append(f"> {line}\n" if line else ">\n")
    out.append("\n")
    return "".join(out)


CLAUDE_COMMAND_TOOLS = frozenset({"Bash", "shell", "unified_exec", "Write", "Edit", "Read", "apply_patch"})

_PLAN_REJECTIONS_STATE_FILE = Path(tempfile.gettempdir()) / "save-plan-rejections-state.json"
_COMMAND_REJECTIONS_STATE_FILE = Path(tempfile.gettempdir()) / "save-command-decision-state.json"


def _render_plan_rejection(rejection: dict) -> str:
    reason = rejection.get("reason")
    if reason:
        return render_decision_block("Plan denied:", reason)
    return render_decision_block("Plan denied.", None)


def command_label(tool_name: str) -> str:
    return f"`{tool_name}`" if tool_name else "a tool"


def _render_command_rejection(rejection: dict) -> str:
    return render_decision_block(f"Command denied: {command_label(rejection['tool_name'])}", rejection.get("reason"))


class RejectionSpec(NamedTuple):
    tool_names: frozenset[str]
    state_file: Path
    render: Callable[[dict], str]
    commit_msg: str


PLAN_REJECTION_SPEC = RejectionSpec(
    tool_names=frozenset({"ExitPlanMode"}),
    state_file=_PLAN_REJECTIONS_STATE_FILE,
    render=_render_plan_rejection,
    commit_msg="ai: save plan decision",
)

COMMAND_REJECTION_SPEC = RejectionSpec(
    tool_names=CLAUDE_COMMAND_TOOLS,
    state_file=_COMMAND_REJECTIONS_STATE_FILE,
    render=_render_command_rejection,
    commit_msg="ai: save command decision",
)


def _load_id_set(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return set()
    return set(data) if isinstance(data, list) else set()


def _save_id_set(path: Path, ids: set[str]) -> None:
    path.write_text(json.dumps(sorted(ids)), encoding="utf-8")


def _flush_rejection_spec(spec: RejectionSpec, events: dict[str, dict]) -> None:
    """Commit every not-yet-recorded rejection for one spec, one commit each,
    guarded by a non-blocking lock so two concurrent hook processes can't
    both commit the same rejection -- see the plan doc's "where the real race
    is" section. Skips (never blocks) if another process currently holds the
    lock; that process is, by construction, clearing the entire backlog for
    this spec right now, not just one item, so skipping is safe."""
    lock_path = spec.state_file.with_name(spec.state_file.name + ".lock")
    try:
        lock_file = open(lock_path, "a")
    except OSError:
        return
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            already_recorded = _load_id_set(spec.state_file)
            rejections = _filter_rejections(events, spec.tool_names, already_recorded)
            if not rejections:
                return
            log_path = resolve_log_path("ai/prompt.md", "ai/°base/prompt.md")
            for rejection in rejections:
                append_and_commit(
                    log_path,
                    spec.render(rejection),
                    commit_template_relpath="ai/commit-templates/decision",
                    default_commit_msg=spec.commit_msg,
                )
                already_recorded.add(rejection["tool_use_id"])
                _save_id_set(spec.state_file, already_recorded)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def flush_pending_rejections(payload: dict) -> None:
    """Scan the transcript once for both plan (`ExitPlanMode`) and command
    (`CLAUDE_COMMAND_TOOLS`) denials not yet recorded, and commit each one
    individually -- one commit per denial, never batched, so denials
    interleave correctly with whatever other commits land between them.

    Call this from every git-committing hook's ``main()``, right after the
    ``is_cross_tool_duplicate`` guard and before that hook's own work, so a
    pending denial commits before that hook's own next commit instead of
    landing after it. See the plan doc (`ai/°base/plans/001_...md` at the
    time this was written) for the full design rationale."""
    transcript_path = payload.get("transcript_path") or ""
    if not transcript_path:
        return
    events = load_transcript_tool_events(transcript_path)
    for spec in (PLAN_REJECTION_SPEC, COMMAND_REJECTION_SPEC):
        _flush_rejection_spec(spec, events)


def slugify(text: str, *, max_len: int = 60, fallback: str = "untitled") -> str:
    """First non-empty line → lowercase, non-alphanumeric runs → ``-``, capped."""
    line = ""
    for raw in (text or "").splitlines():
        candidate = raw.strip().lstrip("#").strip()
        if candidate:
            line = candidate
            break
    if not line:
        return fallback
    slug = re.sub(r"[^a-z0-9]+", "-", line.lower()).strip("-")[:max_len].rstrip("-")
    return slug or fallback


def _git_text(*args: str, cwd: Path | str | None = None) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
    return (result.stdout or "").strip()


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True).stdout or b""


def running_copilot() -> bool:
    """True when this process is actually running under Copilot CLI, per its
    own env markers. Unlike Claude's/Codex's markers, these are set directly
    by the Copilot CLI process itself for every hook invocation."""
    return bool(os.environ.get("COPILOT_CLI") or os.environ.get("COPILOT_AGENT_SESSION_ID"))


def is_cross_tool_duplicate(ai_tool: str) -> bool:
    """True when this hook invocation is a redundant duplicate caused by
    Copilot CLI's unconditional cross-read of `.claude/settings.json`
    alongside its own native `.github/hooks/*.json` config: when both files
    define a hook for the same event, Copilot runs *both*, once per config
    source. The two firings differ only in the baked-in ``ai_tool`` CLI
    argument (``'copilot'`` from the native config, ``'claude'``/``'codex'``
    from the cross-read Claude config) — this detects the mismatch so the
    caller can skip the redundant one.

    Detection is intentionally narrow: it only fires when the environment
    unambiguously marks the *actually running* harness as Copilot
    (``COPILOT_CLI``/``COPILOT_AGENT_SESSION_ID``), since ambient variables
    like ``CLAUDE_CODE_SSE_PORT`` can leak into a Copilot CLI process from
    the surrounding shell/IDE and are not reliable signals on their own.
    Returns ``False`` (never a duplicate) for Claude, Codex, and any other
    harness, and for manual/test invocations where no such env var is set.
    """
    running_copilot_ = running_copilot()
    return running_copilot_ and ai_tool != "copilot"


def _claude_config_dir() -> Path:
    """Claude Code's config root: ``~/.claude`` by default, or
    ``$CLAUDE_CONFIG_DIR`` when relocated (e.g. multi-account setups like
    ``~/.config/claude/accounts/<name>`` used to keep separate logins)."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir).expanduser()
    return Path.home() / ".claude"


_PROJECT_DIR_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _project_dir_name_override() -> str | None:
    """``CLAUDE_CODE_PROJECT_DIR_NAME`` pins Claude Code's per-project state
    directory name, but Claude Code itself only honors it when
    ``CLAUDE_CONFIG_DIR`` is also set in the environment, and only when it
    matches ``^[A-Za-z0-9_-]{1,64}$`` (verified against the installed CLI:
    ``/home/user/.local/share/claude/versions/*``). Mirroring both
    conditions here keeps this repo's own hooks looking in the same
    directory Claude Code actually wrote to — e.g. for a monorepo subfolder
    seeded with ``.claude-project.env`` by ``link-subproject-claude.sh``,
    where the subfolder's own encoded cwd path is not what Claude used."""
    if not os.environ.get("CLAUDE_CONFIG_DIR"):
        return None
    name = os.environ.get("CLAUDE_CODE_PROJECT_DIR_NAME")
    if name and _PROJECT_DIR_NAME_RE.match(name):
        return name
    return None


def _encoded_project_dir(subproject: Path) -> Path:
    """Claude Code stores per-project state at
    ``<config-dir>/projects/<encoded>/``, where <encoded> is either the
    ``CLAUDE_CODE_PROJECT_DIR_NAME`` override (see
    :func:`_project_dir_name_override`) or, by default, the absolute
    project path with all non-alphanumeric characters (including `/` and
    `_`) replaced by `-`."""
    override = _project_dir_name_override()
    encoded = override or re.sub(r"[^a-zA-Z0-9]", "-", str(subproject))
    return _claude_config_dir() / "projects" / encoded


def _subproject_root() -> Path:
    """The directory Claude was launched from. Claude Code sets
    ``CLAUDE_PROJECT_DIR`` for hook commands; manual invocations and the test
    suite fall back to the current working directory."""
    raw = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(raw).resolve()


def _chdir_to_git_root() -> Path:
    root = _git_text("rev-parse", "--show-toplevel")
    if not root:
        sys.exit(1)
    os.chdir(root)
    return Path(root)


def resolve_log_path(default_relpath: str, base_relpath: str) -> Path:
    """Return the absolute AI-artifact path under the *subproject* root (with
    the base-repo reroute and optional ``by-issue/<KEY>/`` sub-directory
    applied) and cd to the git root so subsequent git operations resolve
    relpaths uniformly. Creates parent directories as needed.

    When ``ai[/°base]/.subDir`` exists, the path is taken under that
    subproject (relative to the git root) instead of the launch directory.

    When ``ai[/°base]/.by-issue`` exists and contains an issue key such as
    ``PROJ-1234``, every path is routed through
    ``ai[/°base]/by-issue/PROJ-1234/…`` instead of ``ai[/°base]/…``."""
    subproject = _subproject_root()
    ai_root = _ai_root()
    git_root = _chdir_to_git_root()
    is_base = _is_inside_base_repo(subproject) or _is_inside_base_repo(git_root)
    ai_prefix = "ai/°base" if is_base else "ai"
    relpath = base_relpath if is_base else default_relpath

    issue = _read_by_issue(ai_root, ai_prefix)
    if issue:
        # Insert by-issue/<KEY>/ immediately after the ai prefix.
        rest = relpath[len(ai_prefix) + 1:]  # strip "ai[/°base]/"
        relpath = f"{ai_prefix}/by-issue/{issue}/{rest}"

    log_path = (ai_root / relpath).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.name == migrate_query_to_prompt.CURRENT_NAME:
        migrate_legacy_log(log_path.parent)
    return log_path


def migrate_legacy_log(directory: Path) -> None:
    """Rename an old `query.md` next to the log to `prompt.md`, see ``migrate_query_to_prompt``. Never breaks the hook."""
    try:
        migrate_query_to_prompt.migrate_dir(directory, subject=base_ai_commit_subject)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"could not migrate the old query.md in {directory}: {e}", file=sys.stderr)


def legacy_log_path(log_path: Path) -> Path | None:
    """The old `query.md` that still exists beside `log_path` (when migrating was not possible), which keeps getting every entry, too."""
    if log_path.name != migrate_query_to_prompt.CURRENT_NAME:
        return None
    legacy = log_path.with_name(migrate_query_to_prompt.LEGACY_NAME)
    if not legacy.exists():
        return None
    if log_path.exists() and legacy.samefile(log_path):
        return None
    return legacy


def _staged_snapshot(relpath: str) -> tuple[Path, Path] | None:
    """If ``relpath`` is staged with content different from HEAD, snapshot the
    HEAD and staged blobs to temp files. Returns ``(base_tmp, staged_tmp)`` or
    ``None`` when there is nothing to preserve."""
    staged_line = _git_text("ls-files", "--stage", relpath)
    if not staged_line:
        return None
    staged_hash = staged_line.split()[1]

    head_line = _git_text("ls-tree", "HEAD", relpath)
    head_hash = head_line.split()[2] if head_line else ""
    if staged_hash == head_hash:
        return None

    base_tmp = Path(tempfile.mkstemp(prefix="prompt-log-base-")[1])
    staged_tmp = Path(tempfile.mkstemp(prefix="prompt-log-staged-")[1])
    base_tmp.write_bytes(_git_bytes("cat-file", "blob", head_hash) if head_hash else b"")
    staged_tmp.write_bytes(_git_bytes("cat-file", "blob", staged_hash))
    return base_tmp, staged_tmp


def _restore_staged(snap: tuple[Path, Path], relpath: str) -> None:
    base_tmp, staged_tmp = snap
    try:
        new_head_bytes = _git_bytes("show", f"HEAD:{relpath}")
        new_head_lines = new_head_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)
        base_lines = base_tmp.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        staged_lines = staged_tmp.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

        merged = _merge_lines(base_lines, staged_lines, new_head_lines)
        merged_path = Path(tempfile.mkstemp(prefix="prompt-log-merged-")[1])
        try:
            merged_path.write_text("".join(merged), encoding="utf-8")
            new_blob = _git_text("hash-object", "-w", str(merged_path))
            if new_blob:
                subprocess.run(
                    ["git", "update-index", "--cacheinfo", f"100644,{new_blob},{relpath}"],
                    capture_output=True,
                )
        finally:
            merged_path.unlink(missing_ok=True)
    finally:
        base_tmp.unlink(missing_ok=True)
        staged_tmp.unlink(missing_ok=True)


def append_and_commit(
    log_path: Path,
    content: str,
    *,
    commit_template_relpath: str,
    default_commit_msg: str,
    extra_paths: tuple[Path, ...] = (),
) -> None:
    """Append ``content`` to ``log_path``, commit only those AI artifact files,
    then re-apply any user-staged edits to the log on top of the new HEAD.

    Files mentioned in ``content`` (``@path`` or backtick-quoted) that exist on
    disk get a markdown-link summary appended and are auto-staged/committed --
    see ``°reffiles_lib``."""
    relpath = str(log_path.relative_to(Path.cwd()))
    extra_relpaths = [str(path.relative_to(Path.cwd())) for path in extra_paths]
    snap = _staged_snapshot(relpath)
    legacy = legacy_log_path(log_path)
    legacy_relpath = str(legacy.relative_to(Path.cwd())) if legacy else None
    legacy_snap = _staged_snapshot(legacy_relpath) if legacy_relpath else None

    reffiles_lib = import_module("°reffiles_lib")
    content, resolved_mentions = reffiles_lib.process_referenced_files(
        content, _ai_root(), log_path
    )

    for target in (log_path, legacy):
        if target is None:
            continue
        with target.open("a", encoding="utf-8") as f:
            f.write(content)

    msg = _commit_message(commit_template_relpath, default_commit_msg)
    stage_and_commit([relpath, *([legacy_relpath] if legacy_relpath else []), *extra_relpaths], msg)

    if snap is not None:
        _restore_staged(snap, relpath)
    if legacy_snap is not None and legacy_relpath:
        _restore_staged(legacy_snap, legacy_relpath)

    reffiles_lib.stage_and_commit_mentions(resolved_mentions)
