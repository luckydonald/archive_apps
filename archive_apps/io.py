from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from .cli import RunContext
from .progress import ProgressBar


def tty_read(prompt: str, default: str = "") -> str:
    try:
        with open("/dev/tty") as tty:
            sys.stderr.write(prompt)
            sys.stderr.flush()
            return tty.readline().rstrip("\n") or default
    except Exception:
        return default


def write_fail_menu(
    desc: str, content_or_src: str, orig_dst: Path, mode: str, ctx: RunContext,
) -> Path | None:
    cur_dst = orig_dst
    has_alternate = False
    tmp_fallback = Path("/tmp") / orig_dst.name

    while True:
        print(f"  WRITE ERROR: {desc}", file=sys.stderr)
        print("  [a] retry (default)", file=sys.stderr)
        if has_alternate:
            print(f"  [a'] retry original path ({orig_dst})", file=sys.stderr)
        print("  [b] save somewhere else", file=sys.stderr)
        print("  [c] skip (try /tmp, else print)", file=sys.stderr)
        print("  [d] exit", file=sys.stderr)
        choice = tty_read("  Choice [a]: ", "c")
        choice = choice or "a"

        if choice == "a":
            return cur_dst
        elif choice == "a'" and has_alternate:
            cur_dst = orig_dst
            has_alternate = False
            return cur_dst
        elif choice == "b":
            new = tty_read("  New path: ", "")
            if new:
                cur_dst = Path(new)
                has_alternate = True
                return cur_dst
        elif choice in ("c", "d"):
            try:
                if mode == "append":
                    with open(tmp_fallback, "a") as f:
                        f.write(content_or_src + "\n")
                    print(f"  SAVED ⚠️: {tmp_fallback}", file=sys.stderr)
                elif mode == "write":
                    tmp_fallback.write_text(content_or_src + "\n")
                    print(f"  SAVED ⚠️: {tmp_fallback}", file=sys.stderr)
                elif mode == "mv":
                    shutil.move(str(content_or_src), str(tmp_fallback))
                    print(f"  SAVED ⚠️: {tmp_fallback}", file=sys.stderr)
            except Exception:
                if mode in ("append", "write"):
                    print(content_or_src)
                else:
                    try:
                        print(Path(content_or_src).read_text())
                    except Exception:
                        pass
                    ctx.preserve_tmps.append(Path(content_or_src))

            if choice == "d":
                confirm = tty_read("  Type 'sure' to confirm exit: ", "")
                if confirm == "sure":
                    sys.exit(1)
                continue
            return None
    return None  # unreachable


def safe_append(line: str, file: Path, ctx: RunContext) -> None:
    dst = file
    while True:
        try:
            with open(dst, "a") as f:
                f.write(line + "\n")
            last = dst.read_text().splitlines()
            if last and last[-1] == line:
                return
            print(f"  WARN: readback mismatch (append {dst})", file=sys.stderr)
        except Exception:
            pass
        result = write_fail_menu(f"append to {file.name}", line, file, "append", ctx)
        if result is None:
            return
        dst = result


def safe_write(content: str, file: Path, ctx: RunContext) -> None:
    last_exp = (content + "\n").splitlines()[-1]
    dst = file
    while True:
        try:
            dst.write_text(content + "\n")
            last_act = dst.read_text().splitlines()
            if last_act and last_act[-1] == last_exp:
                return
            print(f"  WARN: readback mismatch (write {dst})", file=sys.stderr)
        except Exception:
            pass
        result = write_fail_menu(f"write {file.name}", content, file, "write", ctx)
        if result is None:
            return
        dst = result


def safe_mv(src: Path, dst: Path, ctx: RunContext) -> None:
    try:
        expected = len(src.read_bytes().splitlines())
    except Exception:
        expected = 0
    target = dst
    while True:
        try:
            shutil.move(str(src), str(target))
            try:
                actual = len(target.read_bytes().splitlines())
                if actual == expected:
                    return
            except Exception:
                return  # file moved, can't verify size — accept
            print(f"  WARN: readback mismatch after mv to {target}", file=sys.stderr)
            return
        except Exception:
            pass
        result = write_fail_menu(f"write {dst.name}", str(src), dst, "mv", ctx)
        if result is None:
            return
        target = result


def rm_retry(path: Path) -> None:
    for _attempt in range(1, 6):
        if not path.exists():
            return

        entries: list[str] = []
        for dirpath, dirnames, filenames in os.walk(str(path), topdown=False):
            for name in filenames + dirnames:
                entries.append(os.path.join(dirpath, name))
        entries.append(str(path))

        total = len(entries)
        tty = sys.stderr.isatty()
        if tty and total > 0:
            bar = ProgressBar("DELETE", total)
            for entry in entries:
                try:
                    p = Path(entry)
                    if p.is_dir() and not p.is_symlink():
                        p.rmdir()
                    else:
                        p.unlink(missing_ok=True)
                except Exception:
                    pass
                bar.tick()
            bar.done()
        else:
            shutil.rmtree(str(path), ignore_errors=True)

        if not path.exists():
            return
        time.sleep(1)

    print(f"ERROR: failed to remove {path} after 5 attempts", file=sys.stderr)
    sys.exit(1)
