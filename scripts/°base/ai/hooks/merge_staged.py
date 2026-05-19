#!/usr/bin/env python3
"""Apply the diff (base → staged) onto new_head.

End-of-file insertions are placed at the actual end of result, i.e. after
any content new_head already appended — so the final order is:

    [previous content]  [new_head's append]  [staged additions]

Usage (CLI): merge_staged.py <base> <staged> <new_head> <out>
Exit 0 on success.
"""
from __future__ import annotations

import difflib
import sys
from pathlib import Path


def _read_lines(path: str | Path) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except FileNotFoundError:
        return []


def merge(base: list[str], staged: list[str], new_head: list[str]) -> list[str]:
    result = list(new_head)
    base_len = len(base)
    offset = 0  # how many lines result has grown/shrunk relative to base so far

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, base, staged, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue

        # End-of-file operations (i1 >= base_len) go at the very end of result
        # so they land after whatever new_head already appended.
        if i1 >= base_len:
            pos = len(result)
            end_pos = pos
        else:
            pos = i1 + offset
            end_pos = i2 + offset

        if tag == "insert":
            result[pos:pos] = staged[j1:j2]
            offset += j2 - j1
        elif tag == "delete":
            del result[pos:end_pos]
            offset -= i2 - i1
        elif tag == "replace":
            result[pos:end_pos] = staged[j1:j2]
            offset += (j2 - j1) - (i2 - i1)

    return result


def _main() -> int:
    if len(sys.argv) != 5:
        print(f"Usage: {sys.argv[0]} <base> <staged> <new_head> <out>", file=sys.stderr)
        return 1

    base = _read_lines(sys.argv[1])
    staged = _read_lines(sys.argv[2])
    new_head = _read_lines(sys.argv[3])

    Path(sys.argv[4]).write_text("".join(merge(base, staged, new_head)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
