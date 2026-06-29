from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from re import search as re_search

from .utils import fmt_duration, fmt_eta_target


class ProgressBar:
    """Renders an in-place progress bar on stderr."""

    def __init__(self, label: str, total: int, start: float | None = None):
        self.label = label.rstrip()
        self.total = total
        self.current = 0
        self.start = start or time.time()
        self._lock = threading.Lock()
        self._tty = sys.stderr.isatty()

    def tick(self, n: int = 1) -> None:
        with self._lock:
            self.current = min(self.current + n, self.total)
            if self._tty:
                self._render()

    def set(self, n: int) -> None:
        with self._lock:
            self.current = min(n, self.total)
            if self._tty:
                self._render()

    def _render(self) -> None:
        pct = self.current * 100 // self.total if self.total else 100
        filled = self.current * 40 // self.total if self.total else 40
        bar = "=" * filled
        if filled < 40:
            bar += ">"
        bar = bar.ljust(40)
        eta = "--:--"
        eta_target = "--:--:--"
        now = time.time()
        elapsed = now - self.start
        if self.current > 0 and elapsed > 0 and self.total:
            remaining = (self.total - self.current) * elapsed / self.current
            eta = fmt_duration(remaining)
            eta_target = fmt_eta_target(now, remaining)
        elif self.current >= self.total:
            eta = "00:00"
            eta_target = fmt_eta_target(now, 0)
        sys.stderr.write(
            f"\r  {self.label} [{bar}] {self.current}/{self.total}"
            f" ({pct}%, eta {eta} @ {eta_target})"
        )
        sys.stderr.flush()

    def done(self) -> None:
        if self._tty:
            elapsed = time.time() - self.start
            sys.stderr.write(f"\r\033[K  {self.label} done in {fmt_duration(elapsed)}\n")
            sys.stderr.flush()


def drain_ditto_stderr(proc: subprocess.Popen, bar: ProgressBar) -> None:
    assert proc.stderr is not None
    for raw in proc.stderr:
        if raw.decode("utf-8", "replace").startswith("copying "):
            bar.tick()


def drain_rsync_stderr(proc: subprocess.Popen, bar: ProgressBar) -> None:
    assert proc.stderr is not None
    for raw in proc.stderr:
        line = raw.decode("utf-8", "replace").replace("\r", "\n").strip()
        m = re_search(r"to-check=(\d+)/(\d+)", line)
        if m:
            bar.set(min(int(m.group(1)), bar.total))


def drain_rsync_file_stderr(proc: subprocess.Popen, bar: ProgressBar) -> None:
    assert proc.stderr is not None
    for raw in proc.stderr:
        line = raw.decode("utf-8", "replace").replace("\r", "\n").strip()
        m = re_search(r"(\d+)%", line)
        if m:
            bar.set(int(m.group(1)))


def run_with_bar(
    cmd: list[str],
    bar: ProgressBar,
    drain_fn,
    *,
    cwd: Path | None = None,
) -> int:
    proc = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        cwd=str(cwd) if cwd else None,
    )
    t = threading.Thread(target=drain_fn, args=(proc, bar), daemon=True)
    t.start()
    proc.wait()
    t.join()
    bar.done()
    return proc.returncode


def copy_with_progress(src: Path, dst: Path, label: str = "SEND") -> None:
    """Copy src → dst in 1 MB chunks, showing a 0-100% progress bar."""
    total = src.stat().st_size
    bar = ProgressBar(label, 100)
    copied = 0
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        while chunk := fin.read(1 << 20):
            fout.write(chunk)
            copied += len(chunk)
            bar.set(int(copied * 100 / total) if total else 100)
    bar.done()
