from __future__ import annotations

import atexit
import signal
import sys
import tempfile
from pathlib import Path
from typing import Callable

from .archive import run_archive
from .cli import RunContext, parse_args
from .io import rm_retry
from .verify import merge_checksum_index, run_verify_all, run_verify_zip


def _make_cleanup(ctx: RunContext) -> Callable[[], None]:
    done = False

    def _cleanup() -> None:
        nonlocal done
        if done:
            return
        done = True
        # Cleanup must not be interruptible: a signal mid-merge could lose the index.
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal.SIG_IGN)
        cfg = ctx.cfg
        if ctx.index_scratch is not None:
            print("Cleaning up, please wait…", file=sys.stderr)
            try:
                merge_checksum_index(ctx.index_scratch, ctx)
            except BaseException as e:
                print(f"WARN: index merge failed ({e!r}); scratch kept for recovery", file=sys.stderr)

        if cfg.keep_temp:
            return

        leftovers = 0
        for pattern, keep in (("*.zip.tmp", ()), ("*.checksums.txt.tmp", ctx.preserve_tmps)):
            for f in cfg.dest.glob(pattern):
                if f in keep:
                    continue
                try:
                    f.unlink(missing_ok=True)
                except Exception as e:
                    print(f"WARN: could not remove {f}: {e}", file=sys.stderr)
        for base in (cfg.dest, Path(tempfile.gettempdir())):
            try:
                dirs = [d for d in base.glob(".archive_apps.*") if d.is_dir()]
            except Exception:
                continue
            for d in dirs:
                try:
                    if not rm_retry(d):
                        leftovers += 1
                except Exception as e:
                    leftovers += 1
                    print(f"WARN: could not remove {d}: {e}", file=sys.stderr)
        if leftovers:
            print(f"WARN: {leftovers} leftover work dir(s) not removed; they are reused or can be deleted manually", file=sys.stderr)

    return _cleanup


def _on_signal(signum: int, _frame: object) -> None:
    if signum == signal.SIGINT:
        raise KeyboardInterrupt
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> None:
    cfg = parse_args(argv if argv is not None else sys.argv[1:])
    ctx = RunContext(cfg=cfg)

    atexit.register(_make_cleanup(ctx))
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _on_signal)

    if cfg.verify_zip_arg:
        run_verify_zip(ctx)
    elif cfg.verify_mode != "none":
        run_verify_all(ctx)
    else:
        run_archive(ctx)


if __name__ == "__main__":
    main()
