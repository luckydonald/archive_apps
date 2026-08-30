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
    def _cleanup() -> None:
        cfg = ctx.cfg
        if ctx.index_scratch is not None:
            try:
                merge_checksum_index(ctx.index_scratch, ctx)
            except Exception:
                pass

        if cfg.keep_temp:
            return

        for f in cfg.dest.glob("*.zip.tmp"):
            f.unlink(missing_ok=True)
        for f in cfg.dest.glob("*.checksums.txt.tmp"):
            if f not in ctx.preserve_tmps:
                f.unlink(missing_ok=True)
        for d in cfg.dest.glob(".archive_apps.*"):
            if d.is_dir():
                rm_retry(d)
        # also clean up workdirs that were redirected to the system temp dir
        for d in Path(tempfile.gettempdir()).glob(".archive_apps.*"):
            if d.is_dir():
                rm_retry(d)

    return _cleanup


def main(argv: list[str] | None = None) -> None:
    cfg = parse_args(argv if argv is not None else sys.argv[1:])
    ctx = RunContext(cfg=cfg)

    atexit.register(_make_cleanup(ctx))
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda s, f: sys.exit(1))

    if cfg.verify_zip_arg:
        run_verify_zip(ctx)
    elif cfg.verify_mode != "none":
        run_verify_all(ctx)
    else:
        run_archive(ctx)


if __name__ == "__main__":
    main()
