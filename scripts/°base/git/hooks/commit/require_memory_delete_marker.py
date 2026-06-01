#!/usr/bin/env python3
"""Require explicit commit-message markers for memory file deletions."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


MEMORY_DIRS = ("ai/memory/", "ai/°base/memory/")


def _deleted_memory_names() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=D", "-z", "--"],
        capture_output=True,
    )
    names: list[str] = []
    for raw in result.stdout.decode("utf-8", errors="surrogateescape").split("\0"):
        if not raw.endswith(".md"):
            continue
        if any(raw.startswith(prefix) for prefix in MEMORY_DIRS):
            names.append(Path(raw).name)
    return sorted(set(names))


def _message_lines(path: Path) -> set[str]:
    return set(path.read_text(encoding="utf-8").splitlines())


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Expected exactly one commit message filename.", file=sys.stderr)
        return 2

    lines = _message_lines(Path(args[0]))
    missing = [
        name for name in _deleted_memory_names() if f"Deleted Memory: {name}" not in lines
    ]
    if not missing:
        return 0

    print("Memory deletions require explicit commit-message markers.", file=sys.stderr)
    print("Place each marker as a standalone final line after one empty line:", file=sys.stderr)
    for name in missing:
        print(f"Deleted Memory: {name}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
