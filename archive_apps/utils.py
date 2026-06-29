from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path


def fmt_duration(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def fmt_eta_target(now_ts: float, remaining: float) -> str:
    remaining = max(0, int(remaining))
    target_ts = int(now_ts) + remaining
    day_offset = remaining // 86400
    fmt = "%H:%M:%S" if day_offset == 0 else "%H:%M"
    label = ""
    if day_offset == 1:
        label = " (+1 day)"
    elif day_offset > 1:
        label = f" (+{day_offset} days)"
    return time.strftime(fmt, time.localtime(target_ts)) + label


def fmt_size(path: Path) -> str:
    if path.is_file():
        total: float = path.stat().st_size
    else:
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    for unit in ("B", "K", "M", "G", "T"):
        if total < 1024 or unit == "T":
            return f"{total:.1f}{unit}"
        total /= 1024
    return "0B"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sanitize_temp_component(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9.@_-]+", "_", value)
    value = value.strip("_")
    return value or "app"
