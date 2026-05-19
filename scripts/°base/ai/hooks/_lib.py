#!/usr/bin/env python3
"""Shared helpers for the prompt-log hooks (save-prompt, save-decision).

Both hooks append a markdown entry to a per-repo prompt log (typically
`ai/query.md`) and auto-commit only that file, while preserving any user-staged
edits to the same file via :mod:`merge_staged`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Sibling-module import (this package can't be imported as a real package
# because parent dirs contain non-ASCII / hyphenated names).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_staged import merge as _merge_lines  # noqa: E402


def read_payload() -> dict:
    """Parse the JSON payload from stdin, returning ``{}`` on any error."""
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


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


def _git_text(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    return (result.stdout or "").strip()


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True).stdout or b""


def _is_inside_base_repo(subproject_root: Path) -> bool:
    """True iff we are inside the `base` meta-repo: subproject directory named
    `base`, remotes are exactly `empty` and `origin`, origin pointing at
    luckydonald/base.

    In a stand-alone consuming repo, subproject_root == git_root and the name
    won't be `base`, so this returns False. In a monorepo, subproject_root is
    the per-project directory below the git root and again won't match.
    """
    if subproject_root.name != "base":
        return False
    remotes = sorted(_git_text("remote").split())
    if remotes != ["empty", "origin"]:
        return False
    return bool(re.search(r"luckydonald/base(\.git)?$", _git_text("remote", "get-url", "origin")))


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
    the base-repo reroute applied) and cd to the git root so subsequent git
    operations resolve relpaths uniformly. Creates parent directories as
    needed."""
    subproject = _subproject_root()
    _chdir_to_git_root()
    relpath = base_relpath if _is_inside_base_repo(subproject) else default_relpath
    log_path = (subproject / relpath).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path


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


def _commit_message(template_relpath: str, default_msg: str) -> str:
    # Templates live alongside the AI artifacts, so they're subproject-scoped
    # (relevant in monorepos where cwd is the git root, not the subproject).
    template = _subproject_root() / template_relpath
    if not template.is_file():
        return default_msg
    text = template.read_text(encoding="utf-8").replace("\n", "").replace("\r", "").strip()
    return text or default_msg


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
) -> None:
    """Append ``content`` to ``log_path``, commit only that file, then re-apply
    any user-staged edits to the same file on top of the new HEAD."""
    relpath = str(log_path.relative_to(Path.cwd()))
    snap = _staged_snapshot(relpath)

    with log_path.open("a", encoding="utf-8") as f:
        f.write(content)

    msg = _commit_message(commit_template_relpath, default_commit_msg)
    # `git commit --only` requires the path to be tracked, so make sure the
    # file is in the index first. Idempotent on already-tracked files.
    subprocess.run(["git", "add", "--", relpath], capture_output=True)
    subprocess.run(["git", "commit", "--only", relpath, "-m", msg], capture_output=True)

    if snap is not None:
        _restore_staged(snap, relpath)
