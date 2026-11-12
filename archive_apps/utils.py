from __future__ import annotations

import ctypes
import errno
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


def supports_xattr(path: Path) -> bool:
    """Return True if the filesystem at path supports extended attributes.

    Uses setxattr(2) probe; ENOTSUP means the filesystem rejects xattrs
    (ExFAT, FAT32, some network mounts). Other errors are treated as
    "supported but permission denied" to avoid false negatives.
    """
    _lib = ctypes.CDLL(None, use_errno=True)
    name = b"com.apple.archive_apps.probe\x00"
    # macOS setxattr(path, name, value, size, position, options)
    ret = _lib.setxattr(str(path).encode("utf-8"), name, ctypes.c_char_p(b""), 0, 0, 0)
    if ret == -1:
        return ctypes.get_errno() != errno.ENOTSUP
    _lib.removexattr(str(path).encode("utf-8"), name, 0)
    return True


FINDER_GRAY = 1
FINDER_GREEN = 2
FINDER_RED = 6

_FINDER_INFO = b"com.apple.FinderInfo\x00"
_FINDER_INFO_SIZE = 32
_FINDER_COLOR_BYTE = 9
_FINDER_COLOR_MASK = 0b1110


def set_finder_color(path: Path, color: int) -> bool:
    """Set the Finder color label of path, keeping all other FinderInfo bytes.

    Returns True if the label is set afterwards. Purely cosmetic, so any failure
    (missing file, filesystem without xattr support, permissions) returns False
    instead of raising. Does not write when the label is already correct.
    """
    lib = ctypes.CDLL(None, use_errno=True)
    raw = str(path).encode("utf-8")
    buf = ctypes.create_string_buffer(_FINDER_INFO_SIZE)
    # macOS getxattr(path, name, value, size, position, options)
    lib.getxattr.restype = ctypes.c_ssize_t
    got = lib.getxattr(raw, _FINDER_INFO, buf, _FINDER_INFO_SIZE, 0, 0)
    if got == -1 and ctypes.get_errno() != errno.ENOATTR:
        return False
    info = bytearray(buf.raw)
    if got == -1:
        info = bytearray(_FINDER_INFO_SIZE)
    new = (info[_FINDER_COLOR_BYTE] & ~_FINDER_COLOR_MASK) | (color << 1)
    if got != -1 and info[_FINDER_COLOR_BYTE] == new:
        return True
    info[_FINDER_COLOR_BYTE] = new
    out = ctypes.create_string_buffer(bytes(info), _FINDER_INFO_SIZE)
    return lib.setxattr(raw, _FINDER_INFO, out, _FINDER_INFO_SIZE, 0, 0) == 0


def get_finder_color(path: Path) -> int | None:
    """Return the Finder color label (0-7) of path, or None if unreadable."""
    lib = ctypes.CDLL(None, use_errno=True)
    buf = ctypes.create_string_buffer(_FINDER_INFO_SIZE)
    lib.getxattr.restype = ctypes.c_ssize_t
    got = lib.getxattr(str(path).encode("utf-8"), _FINDER_INFO, buf, _FINDER_INFO_SIZE, 0, 0)
    if got == -1:
        return 0 if ctypes.get_errno() == errno.ENOATTR else None
    return (buf.raw[_FINDER_COLOR_BYTE] & _FINDER_COLOR_MASK) >> 1


def sanitize_temp_component(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9.@_-]+", "_", value)
    value = value.strip("_")
    return value or "app"


def now_suffix() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def tagged_names(name: str, mobile: str, version: str, tag: str) -> tuple[str, str]:
    stem = f"{name}.app@{mobile}{version}~{tag}"
    return f"{stem}.zip", f"{stem}.checksums.txt"
