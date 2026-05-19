#!/usr/bin/env python3
"""Hardlink Claude memory files into the project tree and auto-commit them.

Source:  ~/.claude/projects/<encoded-subproject-path>/memory/<name>.md
Target:  <subproject>/ai/memory/<name>.md
         (or <base>/ai/°base/memory/<name>.md inside the base meta-repo)

Fires on:
  - PostToolUse(Write|Edit): sync the single file the tool just touched, if
    it lives inside the source memory dir.
  - SessionStart: bulk-sync every `*.md` under the source memory dir as a
    catch-up.

Linking strategy mirrors `scripts/°base/memories/hardlink_memories.sh` but for
single files: hardlink first, fall back to symlink when hardlinks aren't
supported (e.g. the project and Claude state live on different filesystems).
Bind mounts are skipped — they only make sense at directory granularity.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _lib import (  # noqa: E402
    _chdir_to_git_root,
    _is_inside_base_repo,
    _subproject_root,
    read_payload,
)


def _encoded_project_dir(subproject: Path) -> Path:
    """Claude Code stores per-project state at ~/.claude/projects/<encoded>/,
    where <encoded> is the absolute project path with `/` replaced by `-`."""
    encoded = str(subproject).replace("/", "-")
    return Path.home() / ".claude" / "projects" / encoded


def _memory_dirs(subproject: Path) -> tuple[Path, Path]:
    src = _encoded_project_dir(subproject) / "memory"
    rel = "ai/°base/memory" if _is_inside_base_repo(subproject) else "ai/memory"
    return src, subproject / rel


def _same_inode(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_ino == b.stat().st_ino and a.stat().st_dev == b.stat().st_dev
    except OSError:
        return False


def _sync_file(src: Path, dst: Path) -> bool:
    """Make ``dst`` a hardlink (or symlink fallback) of ``src``.
    Returns True if something changed; False if already in sync."""
    if not src.is_file():
        # Source went away — remove dst so the working tree mirrors reality.
        if dst.is_symlink() or dst.exists():
            dst.unlink()
            return True
        return False

    if dst.is_symlink():
        try:
            if dst.resolve() == src.resolve():
                return False
        except OSError:
            pass
    elif dst.exists() and _same_inode(dst, src):
        return False

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        dst.unlink()

    try:
        os.link(src, dst)
    except OSError:
        # Cross-filesystem or other hardlink restriction → symlink fallback.
        os.symlink(src, dst)
    return True


def _sync_all(src_dir: Path, dst_dir: Path) -> list[str]:
    """Sync every `*.md` in src_dir into dst_dir, and remove any orphaned
    `*.md` files in dst_dir that no longer exist in src_dir."""
    changed: list[str] = []
    src_names: set[str] = set()
    if src_dir.is_dir():
        for src in sorted(src_dir.glob("*.md")):
            src_names.add(src.name)
            if _sync_file(src, dst_dir / src.name):
                changed.append(src.name)
    if dst_dir.is_dir():
        for dst in sorted(dst_dir.glob("*.md")):
            if dst.name in src_names:
                continue
            if _sync_file(src_dir / dst.name, dst):
                changed.append(dst.name)
    return changed


def _commit(dst_dir_rel: str, names: list[str]) -> None:
    if not names:
        return
    subprocess.run(["git", "add", "--", dst_dir_rel], capture_output=True)
    if len(names) == 1:
        msg = f"ai: record memory {Path(names[0]).stem}"
    else:
        head = ", ".join(Path(n).stem for n in names[:3])
        extra = f" (+{len(names) - 3} more)" if len(names) > 3 else ""
        msg = f"ai: record memories {head}{extra}"
    subprocess.run(["git", "commit", "--only", dst_dir_rel, "-m", msg], capture_output=True)


def _git_root() -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def _is_bind_mount(p: Path) -> bool:
    """Best-effort detect of a bind mount at ``p``."""
    try:
        result = subprocess.run(
            ["mountpoint", "-q", str(p)], capture_output=True
        )
        return result.returncode == 0
    except (OSError, FileNotFoundError):
        # `mountpoint` is Linux-only. Fall back to stat: a mountpoint sits on
        # a different device than its parent directory.
        try:
            return p.stat().st_dev != p.parent.stat().st_dev
        except OSError:
            return False


# ─────────────────────────────────────────────────────────────────────────────
# DANGER ZONE — legacy whole-folder link cleanup.
#
# The functions below remove the whole-folder memory link planted by
# `scripts/°base/memories/hardlink_memories.sh` so the new per-file hardlinks
# don't duplicate state. Sounds innocent — it isn't. Things you must NOT
# "simplify":
#
# 1. `_legacy_link_candidates` uses `.absolute()`, not `.resolve()`.
#    `.resolve()` follows symlinks, so a candidate `<root>/.claude/memory` that
#    IS a symlink to the source dir resolves to the source itself — and we'd
#    happily delete it.
#
# 2. `_uninstall_legacy` checks the symlink case FIRST and short-circuits with
#    `legacy.unlink()` (which removes the symlink, not its target). Don't move
#    this check below the directory branches, and don't replace `unlink` with
#    anything that recurses.
#
# 3. NEVER `shutil.rmtree()` (or `rm -rf`) a path that has the same inode as
#    the source dir. Directory hardlinks share the inode and ALL contents —
#    rmtree walks into the shared inode and removes the source files too.
#    Past me did this; the only reason it isn't catastrophic is that those
#    memories were already committed to git on the destination side and we
#    could `git checkout` them back. Don't rely on that next time.
#
# Bind mounts and directory hardlinks therefore return `None` and warn the user
# to run `unlink_memories.sh` interactively. That script has the sudo/systemd/
# fstab unwind logic; this hook does not, deliberately.
# ─────────────────────────────────────────────────────────────────────────────


def _legacy_link_candidates(subproject: Path) -> list[Path]:
    """Plausible legacy locations where ``hardlink_memories.sh`` would have
    planted a whole-folder link to the source memory dir.

    Uses ``absolute()`` (not ``resolve()``) — see the DANGER ZONE notice above.
    The candidate must be the legacy entry itself, not what its symlink
    follows to."""
    seen: set[Path] = set()
    out: list[Path] = []
    git_root = _git_root()
    for base in (subproject, git_root):
        if base is None:
            continue
        legacy = (base / ".claude" / "memory").absolute()
        if legacy in seen:
            continue
        seen.add(legacy)
        out.append(legacy)
    return out


def _uninstall_legacy(legacy: Path, src_dir: Path) -> bool | None:
    """Remove a legacy whole-folder link at ``legacy`` pointing at ``src_dir``.

    See the DANGER ZONE notice above before changing this function.

    Only the symlink case is removed automatically — that's what
    ``hardlink_memories.sh`` falls back to when directory hardlinks aren't
    allowed (macOS always; Linux outside root). Bind mounts and directory
    hardlinks need `unlink_memories.sh` to undo safely.

    Returns:
      - ``True``  → a symlink was unlinked,
      - ``False`` → nothing legacy-shaped is here (path missing, real
        unrelated directory, etc.),
      - ``None``  → bind mount or directory hardlink detected; caller warns
        and leaves it alone.
    """
    # Symlink case FIRST — don't reorder. `.unlink()` removes the symlink
    # entry itself, not the directory it points at.
    if legacy.is_symlink():
        try:
            if legacy.resolve() == src_dir.resolve():
                legacy.unlink()
                return True
        except OSError:
            pass
        return False

    if not legacy.exists():
        return False

    # Past this point `legacy` is a real (non-symlink) filesystem entry.
    # Defense in depth: never act on the source dir itself, even if some
    # exotic path equivalence got us here.
    try:
        if legacy.resolve() == src_dir.resolve():
            return False
    except OSError:
        pass

    if _is_bind_mount(legacy):
        return None

    # Directory hardlink: same inode as source. We CANNOT remove this from
    # here. `os.rmdir` only works on empty dirs; `shutil.rmtree` would follow
    # the shared inode and delete the source contents. Hand off to the user.
    if legacy.is_dir() and _same_inode(legacy, src_dir):
        return None

    return False


def _uninstall_legacy_all(subproject: Path, src_dir: Path) -> None:
    for legacy in _legacy_link_candidates(subproject):
        result = _uninstall_legacy(legacy, src_dir)
        if result is True:
            print(
                f"record-memory: removed legacy whole-folder memory symlink at {legacy}",
                file=sys.stderr,
            )
        elif result is None:
            print(
                f"record-memory: a bind mount or directory hardlink remains at {legacy}; "
                f"the new per-file hooks won't disturb it, but it duplicates memory "
                f"state in your repo. Run `scripts/°base/memories/unlink_memories.sh` "
                f"to remove it.",
                file=sys.stderr,
            )


def main() -> int:
    if _git_root() is None:
        return 0
    subproject = _subproject_root()
    src_dir, dst_dir = _memory_dirs(subproject)
    _chdir_to_git_root()
    dst_dir_rel = str(dst_dir.relative_to(Path.cwd()))

    payload = read_payload()
    event = payload.get("hook_event_name") or ""

    if event == "PostToolUse":
        tool_input = payload.get("tool_input") or {}
        raw = tool_input.get("file_path") or ""
        if not raw:
            return 0
        src_file = Path(raw).resolve()
        try:
            rel = src_file.relative_to(src_dir.resolve())
        except (OSError, ValueError):
            return 0
        if _sync_file(src_file, dst_dir / rel):
            _commit(dst_dir_rel, [str(rel)])
        return 0

    # SessionStart (and any other event) — full catch-up sync.
    # Clean up any legacy whole-folder link planted by `hardlink_memories.sh`
    # so the new per-file hardlinks don't duplicate memory state in the repo.
    _uninstall_legacy_all(subproject, src_dir)
    changed = _sync_all(src_dir, dst_dir)
    _commit(dst_dir_rel, changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
