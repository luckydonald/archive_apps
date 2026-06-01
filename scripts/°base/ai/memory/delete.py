#!/usr/bin/env python3
"""Delete one AI memory and create the required marked deletion commit."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from _lib import (  # noqa: E402
    _chdir_to_git_root,
    _is_inside_base_repo,
    _subproject_root,
    base_ai_commit_subject,
)


def _encoded_project_dir(subproject: Path) -> Path:
    encoded = str(subproject).replace("/", "-")
    return Path.home() / ".claude" / "projects" / encoded


def _memory_dirs(subproject: Path) -> tuple[Path, Path]:
    src = _encoded_project_dir(subproject) / "memory"
    rel = "ai/°base/memory" if _is_inside_base_repo(subproject) else "ai/memory"
    return src, subproject / rel


def _git_text(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    return (result.stdout or "").strip()


def _tracked(path: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", path],
        capture_output=True,
    )
    return result.returncode == 0


def _unlink(path: Path) -> None:
    if path.is_symlink() or path.exists():
        path.unlink()


def _usage() -> str:
    return "Usage: python3 scripts/°base/ai/memory/delete.py <filename-or-path>"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(_usage(), file=sys.stderr)
        return 2

    name = Path(args[0]).name
    if not name.endswith(".md") or name in {"", ".", ".."}:
        print("Memory name must be a markdown filename ending in .md.", file=sys.stderr)
        return 2

    subproject = _subproject_root()
    src_dir, dst_dir = _memory_dirs(subproject)
    _chdir_to_git_root()

    dst = dst_dir / name
    dst_rel = str(dst.relative_to(Path.cwd()))
    if not _tracked(dst_rel):
        print(f"Memory is not tracked: {dst_rel}", file=sys.stderr)
        return 1

    _unlink(dst)
    _unlink(src_dir / name)

    subprocess.run(["git", "add", "--", dst_rel], check=True)
    subject = base_ai_commit_subject(f"ai: delete memory {Path(name).stem}")
    marker = f"Deleted Memory: {name}"
    result = subprocess.run(
        ["git", "commit", "--only", dst_rel, "-m", subject, "-m", marker],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr or result.stdout)
        return result.returncode

    commit = _git_text("rev-parse", "--short", "HEAD")
    print(f"Deleted memory {name} in {commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
