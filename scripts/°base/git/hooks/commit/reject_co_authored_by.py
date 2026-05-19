#!/usr/bin/env python3
"""Reject commit messages containing Co-Authored-By trailers."""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Expected exactly one commit message filename.", file=sys.stderr)
        return 2

    message = Path(args[0]).read_text(encoding="utf-8")
    return 0 if "Co-Authored-By" not in message else 1


if __name__ == "__main__":
    raise SystemExit(main())
