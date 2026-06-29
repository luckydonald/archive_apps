#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""archive_apps.py — snapshot macOS .app bundles into versioned zip archives."""

from __future__ import annotations

import atexit
import hashlib
import locale
import os
import posixpath
import random
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class Config:
    dest: Path
    local_cache: Path | None
    verify_mode: str           # "none" | "zips" | "new" | "changed"
    verify_zip_arg: str        # "" or the --verify-zip= value
    verify_abort: bool
    keep_temp: bool
    external_symlink_policy: str   # "archive" | "skip" | "abort"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> Config:
    verify_mode = "none"
    verify_zip_arg = ""
    dest_arg = ""
    local_cache_arg: str | None = None   # None = unset
    external_symlink_policy = "archive"
    verify_abort = False
    keep_temp = False

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            print("Usage: archive_apps.py [options] [destination]")
            print("  --verify-zip=APP  verify zip(s) for a specific app or exact zip file")
            print("                    APP forms: Xcode / Xcode.app / /Applications/Xcode.app")
            print("                              Xcode.app@15.4.zip / full/path/to/Foo.zip")
            print("                    matches all version zips for that app; exits after verifying")
            print("  --verify-zips     extract and verify all zips against their checksum files")
            print("  --verify-new      verify only zips/checksums not yet in the checksum index")
            print("  --verify-changed  verify zips whose index hash differs from current file")
            print("  --verify-abort    stop immediately on the first verification failure")
            print("  --keep-temp       preserve temp workdirs and leftover .tmp files for reuse")
            print("  --local-cache[=path]")
            print("                    stage new zips on local disk, then move to destination;")
            print("                    local temp is deleted after transfer (no copy retained)")
            print("                    path defaults to /Users/Shared/App Versions")
            print("                    magic values: default (same as omitting path), none (disable)")
            print("  --external-symlink-policy=archive|skip|abort")
            print("                    handling for symlinks that resolve outside the app bundle")
            print("                    default: archive, with an end-of-run warning summary")
            print("  destination       archive directory (default: /Users/Shared/App Versions)")
            sys.exit(0)
        elif arg == "--verify-zip":
            print("Error: --verify-zip requires a value: --verify-zip=APP", file=sys.stderr)
            sys.exit(1)
        elif arg.startswith("--verify-zip="):
            verify_zip_arg = arg[len("--verify-zip="):]
        elif arg == "--verify-zips":
            verify_mode = "zips"
        elif arg == "--verify-new":
            verify_mode = "new"
        elif arg == "--verify-changed":
            verify_mode = "changed"
        elif arg == "--verify-abort":
            verify_abort = True
        elif arg == "--keep-temp":
            keep_temp = True
        elif arg in ("--local-cache", "--local-cache=", "--local-cache=default"):
            local_cache_arg = "/Users/Shared/App Versions"
        elif arg == "--local-cache=none":
            local_cache_arg = ""
        elif arg.startswith("--local-cache="):
            local_cache_arg = arg[len("--local-cache="):]
        elif arg.startswith("--external-symlink-policy="):
            val = arg[len("--external-symlink-policy="):]
            if val not in ("archive", "skip", "abort"):
                print(f"Error: unknown --external-symlink-policy value: {val}", file=sys.stderr)
                sys.exit(1)
            external_symlink_policy = val
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}", file=sys.stderr)
            sys.exit(1)
        else:
            dest_arg = arg
        i += 1

    if verify_zip_arg and verify_mode != "none":
        print("Error: --verify-zip cannot be combined with --verify-zips/--verify-new/--verify-changed", file=sys.stderr)
        sys.exit(1)

    dest = Path(dest_arg or "/Users/Shared/App Versions").resolve()
    dest.mkdir(parents=True, exist_ok=True)

    local_cache: Path | None = None
    if local_cache_arg is not None and local_cache_arg != "":
        lc = Path(local_cache_arg).resolve()
        lc.mkdir(parents=True, exist_ok=True)
        if lc == dest:
            print("Error: --local-cache path must differ from the destination", file=sys.stderr)
            sys.exit(1)
        local_cache = lc

    return Config(
        dest=dest,
        local_cache=local_cache,
        verify_mode=verify_mode,
        verify_zip_arg=verify_zip_arg,
        verify_abort=verify_abort,
        keep_temp=keep_temp,
        external_symlink_policy=external_symlink_policy,
    )


# ---------------------------------------------------------------------------
# Global mutable state (mirrors bash globals)
# ---------------------------------------------------------------------------

_cfg: Config          # set in main()
_preserve_tmps: list[Path] = []
_verify_failure_summary: list[tuple[str, str]] = []
_external_symlink_summary: list[str] = []


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------

def _fmt_duration(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def _fmt_eta_target(now_ts: float, remaining: float) -> str:
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
            eta = _fmt_duration(remaining)
            eta_target = _fmt_eta_target(now, remaining)
        elif self.current >= self.total:
            eta = "00:00"
            eta_target = _fmt_eta_target(now, 0)
        sys.stderr.write(
            f"\r  {self.label} [{bar}] {self.current}/{self.total}"
            f" ({pct}%, eta {eta} @ {eta_target})"
        )
        sys.stderr.flush()

    def done(self) -> None:
        if self._tty:
            elapsed = time.time() - self.start
            sys.stderr.write(f"\r\033[K  {self.label} done in {_fmt_duration(elapsed)}\n")
            sys.stderr.flush()


def _drain_ditto_stderr(proc: subprocess.Popen, bar: ProgressBar) -> None:
    """Background thread: parse ditto -V stderr and tick the progress bar."""
    assert proc.stderr is not None
    for raw in proc.stderr:
        line = raw.decode("utf-8", "replace")
        if line.startswith("copying "):
            bar.tick()


def _drain_rsync_stderr(proc: subprocess.Popen, bar: ProgressBar) -> None:
    """Background thread: parse rsync --progress stderr (file count mode)."""
    assert proc.stderr is not None
    for raw in proc.stderr:
        line = raw.decode("utf-8", "replace").replace("\r", "\n").strip()
        m = re.search(r"to-check=(\d+)/(\d+)", line)
        if m:
            checked = int(m.group(1))
            bar.set(min(checked, bar.total))


def _drain_rsync_file_stderr(proc: subprocess.Popen, bar: ProgressBar) -> None:
    """Background thread: parse rsync --progress stderr (single-file % mode)."""
    assert proc.stderr is not None
    for raw in proc.stderr:
        line = raw.decode("utf-8", "replace").replace("\r", "\n").strip()
        m = re.search(r"(\d+)%", line)
        if m:
            bar.set(int(m.group(1)))


def _run_with_bar(
    cmd: list[str],
    bar: ProgressBar,
    drain_fn,
    *,
    cwd: Path | None = None,
) -> int:
    """Run cmd, drain its stderr through drain_fn into bar, return exit code."""
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


# ---------------------------------------------------------------------------
# Atomic write helpers
# ---------------------------------------------------------------------------

def _tty_read(prompt: str, default: str = "") -> str:
    try:
        with open("/dev/tty") as tty:
            sys.stderr.write(prompt)
            sys.stderr.flush()
            return tty.readline().rstrip("\n") or default
    except Exception:
        return default


def _write_fail_menu(desc: str, content_or_src: str, orig_dst: Path, mode: str) -> Path | None:
    """
    Interactive recovery menu for write failures.
    Returns the (possibly new) destination Path to retry, or None to skip.
    """
    cur_dst = orig_dst
    has_alternate = False
    tmp_fallback = Path("/tmp") / orig_dst.name

    while True:
        print(f"  WRITE ERROR: {desc}", file=sys.stderr)
        print("  [a] retry (default)", file=sys.stderr)
        if has_alternate:
            print(f" [a'] retry original path ({orig_dst})", file=sys.stderr)
        print("  [b] save somewhere else", file=sys.stderr)
        print("  [c] skip (try /tmp, else print)", file=sys.stderr)
        print("  [d] exit", file=sys.stderr)
        choice = _tty_read("  Choice [a]: ", "c")
        choice = choice or "a"

        if choice == "a":
            return cur_dst
        elif choice == "a'" and has_alternate:
            cur_dst = orig_dst
            has_alternate = False
            return cur_dst
        elif choice == "b":
            new = _tty_read("  New path: ", "")
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
                    _preserve_tmps.append(Path(content_or_src))

            if choice == "d":
                confirm = _tty_read("  Type 'sure' to confirm exit: ", "")
                if confirm == "sure":
                    sys.exit(1)
                continue
            return None


def safe_append(line: str, file: Path) -> None:
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
        result = _write_fail_menu(f"append to {file.name}", line, file, "append")
        if result is None:
            return
        dst = result


def safe_write(content: str, file: Path) -> None:
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
        result = _write_fail_menu(f"write {file.name}", content, file, "write")
        if result is None:
            return
        dst = result


def safe_mv(src: Path, dst: Path) -> None:
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
        result = _write_fail_menu(f"write {dst.name}", str(src), dst, "mv")
        if result is None:
            return
        target = result


# ---------------------------------------------------------------------------
# rm_retry
# ---------------------------------------------------------------------------

def rm_retry(path: Path) -> None:
    for attempt in range(1, 6):
        if not path.exists():
            return

        # TODO: replace with Python os.walk / Path.rglob
        r = subprocess.run(
            ["find", str(path), "-depth", "-print"],
            capture_output=True, text=True,
        )
        entries = [l for l in r.stdout.splitlines() if l]
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


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def _cleanup() -> None:
    global _cfg
    try:
        cfg = _cfg
    except NameError:
        return

    index_tmp = cfg.dest / "_checksum_index_.txt.tmp"
    if index_tmp.exists():
        try:
            subprocess.run(
                ["sort", "-k2", str(index_tmp), "-o", str(index_tmp)],
                check=False,
            )
            if not cfg.keep_temp:
                index_tmp.unlink(missing_ok=True)
        except Exception:
            pass

    if cfg.keep_temp:
        return

    for f in cfg.dest.glob("*.zip.tmp"):
        f.unlink(missing_ok=True)
    for f in cfg.dest.glob("*.checksums.txt.tmp"):
        if f not in _preserve_tmps:
            f.unlink(missing_ok=True)
    for d in cfg.dest.glob(".archive_apps.*"):
        if d.is_dir():
            rm_retry(d)
    import tempfile as _tempfile
    for d in Path(_tempfile.gettempdir()).glob(".archive_apps.*"):
        if d.is_dir():
            rm_retry(d)


# ---------------------------------------------------------------------------
# Utility: sha256 of a string
# ---------------------------------------------------------------------------

def _sha256_text(text: str) -> str:
    # TODO: already pure Python; just hashlib.sha256
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Utility: sanitize temp path component
# ---------------------------------------------------------------------------

def _supports_xattr(path: Path) -> bool:
    import ctypes, errno as _errno
    _lib = ctypes.CDLL(None, use_errno=True)
    name = b"com.apple.archive_apps.probe\x00"
    ret = _lib.setxattr(str(path).encode("utf-8"), name, ctypes.c_char_p(b""), 0, 0, 0)
    if ret == -1:
        return ctypes.get_errno() != _errno.ENOTSUP
    _lib.removexattr(str(path).encode("utf-8"), name, 0)
    return True


def _sanitize_temp_component(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9.@_-]+", "_", value)
    value = value.strip("_")
    return value or "app"


def _archive_workdir_path(archive_stem: str, manifest_hash: str) -> Path:
    safe = _sanitize_temp_component(archive_stem)
    base = _cfg.local_cache if _cfg.local_cache else _cfg.dest
    if not _supports_xattr(base):
        import tempfile as _tempfile
        base = Path(_tempfile.gettempdir())
    return base / f".archive_apps.{safe}.{manifest_hash}"


# ---------------------------------------------------------------------------
# ZIP helpers
# ---------------------------------------------------------------------------

def _fix_zip_name(info: zipfile.ZipInfo) -> str:
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return info.filename


def _find_zip64_offset(fp, info: zipfile.ZipInfo):
    extra = info.extra or b""
    i = 0
    while i + 4 <= len(extra):
        tag, size = struct.unpack_from("<HH", extra, i)
        i += 4
        if tag == 0x0001:
            n = (min(size, len(extra) - i) // 8) * 8
            for j in range(0, n, 8):
                v = struct.unpack_from("<Q", extra, i + j)[0]
                try:
                    fp.seek(v)
                    if fp.read(4) == b"PK\x03\x04":
                        return v
                except Exception:
                    pass
        i += size
    return None


def _hash_at_offset(fp, info: zipfile.ZipInfo, header_offset: int) -> str | None:
    import zlib as _zlib
    fp.seek(header_offset + 26)
    fname_len, extra_len = struct.unpack("<HH", fp.read(4))
    fp.seek(header_offset + 30 + fname_len + extra_len)
    sha = hashlib.sha256()
    remaining = info.compress_size
    if info.compress_type == 0:
        while remaining > 0:
            chunk = fp.read(min(65536, remaining))
            if not chunk:
                return None
            sha.update(chunk)
            remaining -= len(chunk)
    elif info.compress_type == 8:
        d = _zlib.decompressobj(-15)
        while remaining > 0:
            chunk = fp.read(min(65536, remaining))
            if not chunk:
                return None
            sha.update(d.decompress(chunk))
            remaining -= len(chunk)
        sha.update(d.flush())
    else:
        return None
    return sha.hexdigest()


def _hash_via_unzip(zpath: str, entry_name: str) -> str | None:
    proc = subprocess.Popen(
        ["unzip", "-p", zpath, entry_name],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    sha = hashlib.sha256()
    assert proc.stdout is not None
    while True:
        chunk = proc.stdout.read(65536)
        if not chunk:
            break
        sha.update(chunk)
    proc.stdout.close()
    proc.wait()
    return sha.hexdigest() if proc.returncode == 0 else None


def checksums_from_zip(zip_path: Path, mode: str = "full") -> tuple[str, int]:
    """
    Compute per-file SHA-256 manifest for a zip's .app contents.
    Returns (manifest_text, rc) where rc: 0=ok, 1=unreadable, 2=partial.
    """
    zpath = str(zip_path)
    # sanity: readable?
    try:
        with open(zpath, "rb") as f:
            if f.read(4) == b"":
                return "", 1
    except Exception:
        return "", 1

    tty = sys.stderr.isatty()

    try:
        with zipfile.ZipFile(zpath) as z:
            all_entries = [(info, _fix_zip_name(info)) for info in z.infolist()]
            app_prefix = None
            for _info, name in all_entries:
                parts = name.split("/")
                if (not name.endswith("/") and "__MACOSX" not in name
                        and len(parts) > 1 and parts[0].endswith(".app")):
                    app_prefix = parts[0] + "/"
                    break
            if app_prefix is None:
                return "", 1

            entries = [
                (info, name) for info, name in all_entries
                if not name.endswith("/")
                and "__MACOSX" not in name
                and name.startswith(app_prefix)
            ]
            total = len(entries)
            step = max(1, total // 200)
            start = time.time()
            bar = ProgressBar("VERIFY", total, start) if tty else None

            results: list[str] = []
            unreadable: list[str] = []

            for idx, (info, name) in enumerate(entries, 1):
                rel = name[len(app_prefix):]
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                is_link = stat.S_IFMT(unix_mode) == stat.S_IFLNK
                if is_link and mode != "full":
                    continue
                try:
                    if is_link:
                        target = z.read(info).rstrip(b"\n")
                        results.append(hashlib.sha256(target).hexdigest() + "  " + rel)
                    else:
                        sha = hashlib.sha256()
                        with z.open(info) as f:
                            while True:
                                chunk = f.read(65536)
                                if not chunk:
                                    break
                                sha.update(chunk)
                        results.append(sha.hexdigest() + "  " + rel)
                except Exception:
                    h = None
                    if not is_link:
                        true_offset = _find_zip64_offset(z.fp, info)
                        if true_offset is not None:
                            try:
                                h = _hash_at_offset(z.fp, info, true_offset)
                            except Exception:
                                pass
                        if h is None:
                            h = _hash_via_unzip(zpath, info.filename)
                    if h is not None:
                        results.append(h + "  " + rel)
                    else:
                        unreadable.append(rel)
                        results.append("(unreadable)  " + rel)

                if bar and (idx % step == 0 or idx == total):
                    bar.tick(idx - bar.current)

            if bar:
                bar.done()

            locale.setlocale(locale.LC_COLLATE, "C")
            results.sort(key=lambda x: locale.strxfrm(x.split("  ", 1)[1]))
            manifest = "\n".join(results)
            if unreadable:
                print(f"{len(unreadable)} entries could not be read", file=sys.stderr)
                return manifest, 2
            return manifest, 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return "", 1


def external_symlinks_from_zip(zip_path: Path) -> str:
    """Return tab-separated lines: rel\\ttarget\\tresolved for external symlinks."""
    zpath = str(zip_path)
    try:
        with open(zpath, "rb") as f:
            if f.read(4) == b"":
                return ""
    except Exception:
        return ""
    try:
        with zipfile.ZipFile(zpath) as z:
            app_prefix = None
            for name in z.namelist():
                parts = name.split("/")
                if (not name.endswith("/") and "__MACOSX" not in name
                        and len(parts) > 1 and parts[0].endswith(".app")):
                    app_prefix = parts[0]
                    break
            if app_prefix is None:
                return ""
            app_root = "/" + app_prefix
            entries = []
            for info in z.infolist():
                if (info.filename.endswith("/") or "__MACOSX" in info.filename
                        or not info.filename.startswith(app_prefix + "/")):
                    continue
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(mode) != stat.S_IFLNK:
                    continue
                rel = info.filename[len(app_prefix) + 1:]
                target = z.read(info).rstrip(b"\n").decode("utf-8", "surrogateescape")
                link_dir = posixpath.dirname("/" + info.filename)
                resolved = posixpath.normpath(posixpath.join(link_dir, target))
                if not resolved.startswith(app_root + "/") and resolved != app_root:
                    entries.append((rel, target, resolved))
            locale.setlocale(locale.LC_COLLATE, "C")
            entries.sort(key=lambda item: locale.strxfrm(item[0]))
            return "\n".join(f"{r}\t{t}\t{v}" for r, t, v in entries)
    except Exception:
        return ""


def count_symlinks_from_zip(zip_path: Path) -> int:
    zpath = str(zip_path)
    try:
        with zipfile.ZipFile(zpath) as z:
            app_prefix = None
            for name in z.namelist():
                parts = name.split("/")
                if (not name.endswith("/") and "__MACOSX" not in name
                        and len(parts) > 1 and parts[0].endswith(".app")):
                    app_prefix = parts[0]
                    break
            if app_prefix is None:
                return 0
            count = 0
            for info in z.infolist():
                if (info.filename.endswith("/") or "__MACOSX" in info.filename
                        or not info.filename.startswith(app_prefix + "/")):
                    continue
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(mode) == stat.S_IFLNK:
                    count += 1
            return count
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Live-app helpers
# ---------------------------------------------------------------------------

def collect_app_manifest(app: Path, mode: str = "full") -> str:
    app_root = str(app.resolve())
    lines: list[tuple[str, str]] = []
    locale.setlocale(locale.LC_COLLATE, "C")

    for root, dirs, files in os.walk(app_root, topdown=True, followlinks=False):
        dirs.sort(key=locale.strxfrm)
        names = sorted(dirs + files, key=locale.strxfrm)
        for name in names:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, app_root)
            st = os.lstat(path)
            if stat.S_ISREG(st.st_mode):
                sha = hashlib.sha256()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        sha.update(chunk)
                lines.append((rel, f"{sha.hexdigest()}  {rel}"))
            elif mode == "full" and stat.S_ISLNK(st.st_mode):
                target = os.readlink(path).encode("utf-8", "surrogateescape")
                sha = hashlib.sha256(target).hexdigest()
                lines.append((rel, f"{sha}  {rel}"))

    lines.sort(key=lambda item: locale.strxfrm(item[0]))
    return "\n".join(line for _, line in lines)


def collect_external_live_symlinks(app: Path) -> str:
    app_root = str(app.resolve())
    entries = []
    locale.setlocale(locale.LC_COLLATE, "C")

    for root, dirs, files in os.walk(app_root, topdown=True, followlinks=False):
        dirs.sort(key=locale.strxfrm)
        names = sorted(dirs + files, key=locale.strxfrm)
        for name in names:
            path = os.path.join(root, name)
            try:
                st = os.lstat(path)
            except FileNotFoundError:
                continue
            if not stat.S_ISLNK(st.st_mode):
                continue
            rel = os.path.relpath(path, app_root)
            target = os.readlink(path)
            resolved = os.path.realpath(path)
            try:
                common = os.path.commonpath([app_root, resolved])
            except ValueError:
                common = None
            if common != app_root:
                entries.append((rel, target, resolved))

    entries.sort(key=lambda item: locale.strxfrm(item[0]))
    return "\n".join(f"{r}\t{t}\t{v}" for r, t, v in entries)


def count_live_symlinks(app: Path) -> int:
    count = 0
    for root, dirs, files in os.walk(str(app.resolve()), topdown=True, followlinks=False):
        for name in dirs + files:
            path = os.path.join(root, name)
            try:
                if stat.S_ISLNK(os.lstat(path).st_mode):
                    count += 1
            except FileNotFoundError:
                pass
    return count


# ---------------------------------------------------------------------------
# Copy / zip pipeline
# ---------------------------------------------------------------------------

def _count_files(path: Path) -> int:
    # TODO: replace with sum(1 for p in path.rglob('*') if p.is_file())
    r = subprocess.run(
        ["find", str(path), "-not", "-type", "d"],
        capture_output=True, text=True,
    )
    return len([l for l in r.stdout.splitlines() if l])


def copy_app_fresh(app: Path, workapp: Path) -> None:
    total = _count_files(app)
    tty = sys.stderr.isatty()
    if tty and total > 0:
        bar = ProgressBar("COPY", total)
        _run_with_bar(["ditto", "-V", str(app), str(workapp)], bar, _drain_ditto_stderr)
    else:
        subprocess.run(["ditto", str(app), str(workapp)], check=True)


def repair_app_copy(app: Path, workapp: Path) -> None:
    total = _count_files(app)
    tty = sys.stderr.isatty()

    # TODO: replace rsync with a pure Python directory-sync routine
    if tty and total > 0:
        bar = ProgressBar("COPY", total)
        _run_with_bar(
            ["rsync", "-a", "--delete", "--extended-attributes", "--progress",
             str(app) + "/", str(workapp) + "/"],
            bar, _drain_rsync_stderr,
        )
    else:
        subprocess.run(
            ["rsync", "-a", "--delete", "--extended-attributes",
             str(app) + "/", str(workapp) + "/"],
            check=True,
        )


def ensure_archive_copy(app: Path, versioned: str, workdir: Path) -> None:
    workapp = workdir / versioned
    workdir.mkdir(parents=True, exist_ok=True)

    if workapp.exists() and not workapp.is_dir():
        rm_retry(workapp)

    if workapp.is_dir():
        print("  COPY: reusing preserved temp copy")
        try:
            repair_app_copy(app, workapp)
            return
        except Exception:
            print("  COPY WARN: preserved temp copy repair failed; recreating")
            rm_retry(workapp)

    copy_app_fresh(app, workapp)


def archive_app_to_zip(
    app: Path, versioned: str, dest_zip: Path,
    manifest_hash: str, archive_stem: str,
) -> None:
    workdir = _archive_workdir_path(archive_stem, manifest_hash)
    ensure_archive_copy(app, versioned, workdir)

    total = _count_files(app)
    tty = sys.stderr.isatty()

    if tty and total > 0:
        bar = ProgressBar("ZIP ", total)
        _run_with_bar(
            ["ditto", "-V", "-c", "-k", "--sequesterRsrc", "--keepParent",
             versioned, str(dest_zip)],
            bar, _drain_ditto_stderr,
            cwd=workdir,
        )
    else:
        subprocess.run(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
             versioned, str(dest_zip)],
            cwd=str(workdir), check=True,
        )


def delete_validated_workdir(archive_stem: str, manifest_hash: str) -> None:
    workdir = _archive_workdir_path(archive_stem, manifest_hash)
    if workdir.is_dir():
        rm_retry(workdir)


def _remove_zip(zipname: str) -> None:
    ((_cfg.local_cache or _cfg.dest) and None)  # silence unused warning
    (_cfg.dest / zipname).unlink(missing_ok=True)
    if _cfg.local_cache:
        (_cfg.local_cache / zipname).unlink(missing_ok=True)
        (_cfg.local_cache / (zipname + ".tmp")).unlink(missing_ok=True)


def _write_checksums(content: str, checksumname: str) -> None:
    tmp = _cfg.dest / (checksumname + ".tmp")
    safe_write(content, tmp)
    safe_mv(tmp, _cfg.dest / checksumname)


def archive_and_store_zip(
    app: Path, versioned: str, zipname: str,
    manifest_hash: str, archive_stem: str,
) -> None:
    staging = _cfg.local_cache if _cfg.local_cache else _cfg.dest
    tmp = staging / (zipname + ".tmp")
    archive_app_to_zip(app, versioned, tmp, manifest_hash, archive_stem)

    if _cfg.local_cache:
        dest_tmp = _cfg.dest / (zipname + ".tmp")
        tty = sys.stderr.isatty()
        # TODO: replace rsync send with shutil.copy2 or a streaming copy with progress
        if tty:
            bar = ProgressBar("SEND", 100)
            _run_with_bar(
                ["rsync", "--progress", str(tmp), str(dest_tmp)],
                bar, _drain_rsync_file_stderr,
            )
        else:
            subprocess.run(["rsync", str(tmp), str(dest_tmp)], check=True)
        shutil.move(str(dest_tmp), str(_cfg.dest / zipname))
        tmp.unlink(missing_ok=True)
    else:
        shutil.move(str(tmp), str(_cfg.dest / zipname))


# ---------------------------------------------------------------------------
# Verify helpers
# ---------------------------------------------------------------------------

def verify_checksum_file_contents(
    checksumfile: Path, actual_full: str, actual_legacy: str,
) -> bool:
    existing = checksumfile.read_text().rstrip("\n")
    if existing == actual_full:
        print("  VERIFIED ✅: checksum matches")
        return True
    if existing == actual_legacy:
        print("  VERIFIED ✅: legacy checksum matches; upgrading")
        tmp = Path(str(checksumfile) + ".tmp")
        safe_write(actual_full, tmp)
        safe_mv(tmp, checksumfile)
        return True
    print("  FAILED ❌: checksum differs")
    return False


def unreadable_prompt(zip_path: Path, n: int) -> bool:
    """Return True to continue processing, False to skip."""
    print(f"  PARTIAL ⚠️: {n} entries could not be read")
    choice = _tty_read("  [a]ignore / [b]stop / [c]rename to .bak.zip / [d]delete: ", "a")
    choice = choice or "a"
    if choice in ("b", "B"):
        sys.exit(1)
    elif choice in ("c", "C"):
        bak = zip_path.with_suffix("." + time.strftime("%Y-%m-%d_%H-%M-%S") + ".bak.zip")
        try:
            zip_path.rename(bak)
            print(f"  RENAMED: {bak.name}")
        except Exception:
            print("  RENAME FAILED; ignoring")
            return True
        return False
    elif choice in ("d", "D"):
        try:
            zip_path.unlink()
            print(f"  DELETED: {zip_path.name}")
        except Exception:
            print("  DELETE FAILED; ignoring")
            return True
        return False
    print("  IGNORING: proceeding with partial checksums")
    return True


# ---------------------------------------------------------------------------
# External symlink summary
# ---------------------------------------------------------------------------

def _record_external_symlink_summary(app_label: str, source_label: str, entries: str) -> None:
    if not entries:
        return
    _external_symlink_summary.append(f"__APP__\t{app_label}\t{source_label}")
    for line in entries.splitlines():
        if line:
            _external_symlink_summary.append(line)


def _handle_external_symlinks(
    app_label: str, source_label: str, total_count: int, entries: str,
) -> bool:
    external_count = len([l for l in entries.splitlines() if l]) if entries else 0
    print(f"  SYMLINKS: checked {source_label}; found {total_count} symlink(s), {external_count} external")
    if not entries:
        return True
    _record_external_symlink_summary(app_label, source_label, entries)
    print(f"  SYMLINK WARN: external target(s) detected; policy={_cfg.external_symlink_policy}")
    if _cfg.external_symlink_policy == "archive":
        return True
    elif _cfg.external_symlink_policy == "skip":
        print("  SKIPPED ⚠️: external symlink policy")
        return False
    else:  # abort
        print("  ABORTED ❌: external symlink policy")
        sys.exit(1)


def _print_external_symlink_summary() -> None:
    if not _external_symlink_summary:
        return
    print()
    print("External symlink summary:")
    for line in _external_symlink_summary:
        if line.startswith("__APP__\t"):
            _, app_label, source_label = line.split("\t", 2)
            print(f"  {app_label} [{source_label}]")
        else:
            parts = line.split("\t", 2)
            rel = parts[0] if parts else line
            tgt = parts[1] if len(parts) > 1 else ""
            res = parts[2] if len(parts) > 2 else ""
            print(f"    {rel} -> {tgt}")
            print(f"      resolved: {res}")


# ---------------------------------------------------------------------------
# Verify-failure summary
# ---------------------------------------------------------------------------

def _record_verify_failure(zipname: str, reason: str) -> None:
    _verify_failure_summary.append((zipname, reason))


def _print_verify_failure_summary() -> None:
    if not _verify_failure_summary:
        return
    print()
    print("Verification failure summary:")
    for zipname, reason in _verify_failure_summary:
        print(f"  {zipname}")
        print(f"    {reason}")


# ---------------------------------------------------------------------------
# --verify-zip (spot-check one app)
# ---------------------------------------------------------------------------

def _resolve_verify_zip_arg(arg: str) -> list[Path]:
    if arg.endswith(".zip"):
        if "/" in arg:
            p = Path(arg)
        else:
            p = _cfg.dest / arg
        if p.is_file():
            return [p]
        print(f"Error: zip not found: {p}", file=sys.stderr)
        sys.exit(1)

    if ".app/" in arg:
        appname = Path(arg.split(".app/")[0] + ".app").name.removesuffix(".app")
    elif arg.endswith(".app"):
        appname = Path(arg).name.removesuffix(".app")
    else:
        appname = arg

    # TODO: replace find with Path.glob
    r = subprocess.run(
        ["find", str(_cfg.dest), "-maxdepth", "1", "-name", f"{appname}.app@*.zip"],
        capture_output=True, text=True,
    )
    found = sorted(Path(l) for l in r.stdout.splitlines() if l)
    if not found:
        print(f"Error: no zips found for app '{appname}' in {_cfg.dest}", file=sys.stderr)
        sys.exit(1)
    return found


def run_verify_zip() -> None:
    zips = _resolve_verify_zip_arg(_cfg.verify_zip_arg)
    total = len(zips)
    width = len(str(total))
    print(f"Verifying {total} zip(s) [--verify-zip]…")

    for i, zip_path in enumerate(zips, 1):
        idx = str(i).zfill(width)
        zipname = zip_path.name
        checksumfile = zip_path.with_suffix("").with_name(zip_path.stem + ".checksums.txt")

        print(f"VERIFY {idx}/{total}: {zipname}")
        # TODO: replace du -sh with os.stat / sum of sizes
        r = subprocess.run(["du", "-sh", str(zip_path)], capture_output=True, text=True)
        zip_size = r.stdout.split()[0] if r.stdout else "?"
        print(f"  zip: {zip_size}")

        manifest, czrc = checksums_from_zip(zip_path)
        if czrc == 1:
            print("  SKIPPED ⚠️: zip not readable or corrupt")
            continue
        elif czrc == 2:
            n = manifest.count("(unreadable)  ")
            if not unreadable_prompt(zip_path, n):
                continue

        zip_symlink_count = count_symlinks_from_zip(zip_path)
        zip_external_symlinks = external_symlinks_from_zip(zip_path)
        if not _handle_external_symlinks(zipname, "verify zip", zip_symlink_count, zip_external_symlinks):
            continue

        if checksumfile.is_file():
            actual_legacy, _ = checksums_from_zip(zip_path, "legacy")
            if not verify_checksum_file_contents(checksumfile, manifest, actual_legacy):
                _record_verify_failure(zipname, "checksum file differs")
                if _cfg.verify_abort:
                    print("  ABORTED ❌: verification failed (--verify-abort)")
                    _print_verify_failure_summary()
                    sys.exit(1)
        else:
            print("  CHECKSUM: no checksum file found")

    _print_verify_failure_summary()
    if _verify_failure_summary:
        sys.exit(1)
    sys.exit(0)


# ---------------------------------------------------------------------------
# --verify-zips / --verify-new / --verify-changed
# ---------------------------------------------------------------------------

def run_verify_all() -> None:
    index_file = _cfg.dest / "_checksum_index_.txt"
    index_tmp = _cfg.dest / "_checksum_index_.txt.tmp"

    if index_tmp.exists():
        print(f"RECOVERY: Found leftover temp file: {index_tmp.name}")
        ans = _tty_read("  Restore it? [Y/n]: ", "n")
        if ans.lower() not in ("n", ""):
            rc_live = len(index_file.read_text().splitlines()) if index_file.exists() else 0
            ans2 = _tty_read(f"  Existing file: {rc_live} lines. Merge? [Y/n]: ", "n")
            if ans2.lower() not in ("n", ""):
                tmp_lines_text = index_tmp.read_text().splitlines()
                live_lines_text = index_file.read_text().splitlines() if index_file.exists() else []
                merged = sorted(set(tmp_lines_text + live_lines_text))
                rc_tmp = len(tmp_lines_text)
                rc_dup = rc_tmp + rc_live - len(merged)
                print(f"  Temporary file: {rc_tmp} lines")
                print(f"  Existing file:  {rc_live} lines")
                print(f"  Merge duplicates: {rc_dup} lines")
                print(f"  Resulting file: {len(merged)} lines")
                ans3 = _tty_read("  Continue? [Y/n]: ", "n")
                if ans3.lower() not in ("n", ""):
                    import tempfile
                    fd, tmp_path = tempfile.mkstemp(
                        prefix="_checksum_index_.", suffix=".tmp", dir=str(_cfg.dest)
                    )
                    os.close(fd)
                    Path(tmp_path).write_text("\n".join(merged) + "\n")
                    safe_mv(Path(tmp_path), index_file)
                    print("  RECOVERY ✅: merged and written")
                    ans4 = _tty_read("  Delete temp file? [Y/n]: ", "n")
                    if ans4.lower() not in ("n", ""):
                        index_tmp.unlink(missing_ok=True)
                        print("  RECOVERY: temp file deleted")

    try:
        index_tmp.write_text("")
    except Exception:
        print(f"ERROR: cannot create index file at {index_tmp} — check that {index_tmp.parent} is writable", file=sys.stderr)
        sys.exit(1)

    # TODO: replace find with Path.glob
    r = subprocess.run(
        ["find", str(_cfg.dest), "-maxdepth", "1", "-name", "*.zip"],
        capture_output=True, text=True,
    )
    zips = sorted(Path(l) for l in r.stdout.splitlines() if l)
    total = len(zips)
    width = len(str(total))
    print(f"Verifying {total} zip(s) [--verify-{_cfg.verify_mode}]…")

    for i, zip_path in enumerate(zips, 1):
        idx = str(i).zfill(width)
        zipname = zip_path.name
        checksumfile = _cfg.dest / (zip_path.stem + ".checksums.txt")
        checksumname = checksumfile.name
        print(f"VERIFY {idx}/{total}: {zipname}")

        current_zip_hash = ""
        zip_stored = ""
        cs_stored = ""
        if _cfg.verify_mode != "zips" and index_file.exists():
            for line in index_file.read_text().splitlines():
                if line.endswith(f"  {zipname}"):
                    zip_stored = line.split()[0]
                if line.endswith(f"  {checksumname}"):
                    cs_stored = line.split()[0]

        if _cfg.verify_mode == "new":
            if zip_stored:
                print(f"  zip: {zip_stored}")
            else:
                print("  CACHE-MISS 🔸: zip")
            if cs_stored:
                print(f"  app: {cs_stored}")
            else:
                print("  CACHE-MISS 🔸: app")
            if zip_stored and cs_stored:
                print("  INDEXED ✅: already verified")
                safe_append(f"{zip_stored}  {zipname}", index_tmp)
                safe_append(f"{cs_stored}  {checksumname}", index_tmp)
                continue

        elif _cfg.verify_mode == "changed":
            # TODO: replace shasum with hashlib
            r2 = subprocess.run(
                ["shasum", "-a", "256", str(zip_path)],
                capture_output=True, text=True,
            )
            current_zip_hash = r2.stdout.split()[0] if r2.returncode == 0 else ""
            if current_zip_hash:
                print(f"  zip: {current_zip_hash}")
            else:
                print("  CACHE-MISS 🔸: zip")
            if zip_stored and current_zip_hash != zip_stored:
                print("  CHANGED 🔸: zip")
            cs_current = ""
            if checksumfile.exists():
                r3 = subprocess.run(
                    ["shasum", "-a", "256", str(checksumfile)],
                    capture_output=True, text=True,
                )
                cs_current = r3.stdout.split()[0] if r3.returncode == 0 else ""
                if cs_current:
                    print(f"  app: {cs_current}")
                else:
                    print("  CACHE-MISS 🔸: app")
                if cs_stored and cs_current != cs_stored:
                    print("  CHANGED 🔸: app")
            else:
                print("  CACHE-MISS 🔸: app")
            if (current_zip_hash and current_zip_hash == zip_stored
                    and cs_current and cs_current == cs_stored):
                print("  UNCHANGED ✅: hash matches index")
                safe_append(f"{current_zip_hash}  {zipname}", index_tmp)
                safe_append(f"{cs_current}  {checksumname}", index_tmp)
                continue

        # TODO: replace du -sh with os.stat
        rdu = subprocess.run(["du", "-sh", str(zip_path)], capture_output=True, text=True)
        zip_size = rdu.stdout.split()[0] if rdu.stdout else "?"
        print(f"  zip: {zip_size}")

        manifest, czrc = checksums_from_zip(zip_path)
        if czrc == 1:
            print("  SKIPPED ⚠️: zip not readable or corrupt")
            continue
        elif czrc == 2:
            n = manifest.count("(unreadable)  ")
            if not unreadable_prompt(zip_path, n):
                continue

        zip_symlink_count = count_symlinks_from_zip(zip_path)
        zip_external_symlinks = external_symlinks_from_zip(zip_path)
        if not _handle_external_symlinks(zipname, "verify zip", zip_symlink_count, zip_external_symlinks):
            continue

        if checksumfile.exists():
            actual_legacy, _ = checksums_from_zip(zip_path, "legacy")
            if not verify_checksum_file_contents(checksumfile, manifest, actual_legacy):
                _record_verify_failure(zipname, "checksum file differs")
                if _cfg.verify_abort:
                    print("  ABORTED ❌: verification failed (--verify-abort)")
                    _print_verify_failure_summary()
                    sys.exit(1)
                continue
        else:
            print("  CHECKSUM: missing, creating…")
            tmp = Path(str(checksumfile) + ".tmp")
            safe_write(manifest, tmp)
            safe_mv(tmp, checksumfile)
            print("  CHECKSUM: written")

        if not current_zip_hash:
            # TODO: replace shasum with hashlib
            r4 = subprocess.run(
                ["shasum", "-a", "256", str(zip_path)],
                capture_output=True, text=True,
            )
            current_zip_hash = r4.stdout.split()[0] if r4.returncode == 0 else ""
        safe_append(f"{current_zip_hash}  {zipname}", index_tmp)
        if checksumfile.exists():
            r5 = subprocess.run(
                ["shasum", "-a", "256", str(checksumfile)],
                capture_output=True, text=True,
            )
            cs_hash = r5.stdout.split()[0] if r5.returncode == 0 else ""
            safe_append(f"{cs_hash}  {checksumname}", index_tmp)

    subprocess.run(
        ["sort", "-k2", str(index_tmp), "-o", str(index_tmp)],
        check=False,
    )
    safe_mv(index_tmp, index_file)
    print(f"INDEX: written → {index_file.name}")
    _print_verify_failure_summary()


# ---------------------------------------------------------------------------
# Main archive loop
# ---------------------------------------------------------------------------

def _plist_value(plist_path: Path, key: str) -> str | None:
    # TODO: replace with plistlib.load(open(plist_path, 'rb'))[key]
    r = subprocess.run(
        ["/usr/libexec/PlistBuddy", "-c", f"Print :{key}", str(plist_path)],
        capture_output=True, text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else None


def run_archive() -> None:
    # TODO: replace find with Path('/Applications').rglob('*.app')
    r = subprocess.run(
        ["find", "/Applications", "-maxdepth", "2", "-name", "*.app", "-type", "d"],
        capture_output=True, text=True,
    )
    apps = [Path(l) for l in r.stdout.splitlines() if l]
    random.shuffle(apps)

    total = len(apps)
    width = len(str(total))
    print(f"Checking {total} app(s)…")

    for i, app in enumerate(apps, 1):
        idx = str(i).zfill(width)

        plist = app / "Contents/Info.plist"
        mobile = ""
        if not plist.is_file():
            plist = app / "WrappedBundle/Info.plist"
            mobile = "mobile@"
        if not plist.is_file():
            print(f"ARCHIVING {idx}/{total}: {app}")
            # TODO: replace du -sh with os.stat
            rdu = subprocess.run(["du", "-sh", str(app)], capture_output=True, text=True)
            print(f"  app: {rdu.stdout.split()[0] if rdu.stdout else '?'}")
            print("  SKIPPING ⚠️: no Info.plist")
            continue

        name = _plist_value(plist, "CFBundleName") or app.stem
        version = _plist_value(plist, "CFBundleShortVersionString") or "unknown"

        zipname = f"{name}.app@{mobile}{version}.zip"
        checksumname = f"{name}.app@{mobile}{version}.checksums.txt"
        zipstem = zipname.removesuffix(".zip")
        versioned = f"{name} {version}.app"

        print(f"ARCHIVING {idx}/{total}: {zipname}")

        live_symlink_count = count_live_symlinks(app)
        live_external_symlinks = collect_external_live_symlinks(app)
        if not _handle_external_symlinks(zipname, "live app", live_symlink_count, live_external_symlinks):
            continue

        dest_zip = _cfg.dest / zipname
        dest_checksum = _cfg.dest / checksumname

        if dest_zip.exists():
            print("  ARCHIVE: found")

            if dest_checksum.exists():
                print("  CHECKSUM: found")
                rdu = subprocess.run(["du", "-sh", str(app)], capture_output=True, text=True)
                print(f"  app: {rdu.stdout.split()[0] if rdu.stdout else '?'}")
                rdu2 = subprocess.run(["du", "-sh", str(dest_zip)], capture_output=True, text=True)
                print(f"  zip: {rdu2.stdout.split()[0] if rdu2.stdout else '?'}")

                zip_symlink_count = count_symlinks_from_zip(dest_zip)
                zip_external_symlinks = external_symlinks_from_zip(dest_zip)
                if not _handle_external_symlinks(zipname, "existing zip", zip_symlink_count, zip_external_symlinks):
                    continue

                live_checksums = collect_app_manifest(app, "full")
                live_checksums_legacy = collect_app_manifest(app, "legacy")
                live_manifest_hash = _sha256_text(live_checksums)

                if verify_checksum_file_contents(dest_checksum, live_checksums, live_checksums_legacy):
                    print("  VERIFIED ✅: archived checksum matches current app")
                else:
                    print("  MISMATCH ❌: archived checksum does not match current app")
                    choice = _tty_read("  [o]verwrite zip / [b]oth / [s]kip: ", "s")
                    if choice in ("o", "O"):
                        _remove_zip(zipname)
                        archive_and_store_zip(app, versioned, zipname, live_manifest_hash, zipstem)
                        _write_checksums(live_checksums, checksumname)
                    elif choice in ("b", "B"):
                        suffix = time.strftime("%Y%m%d_%H%M%S")
                        newzip = f"{name}.app@{mobile}{version}~{suffix}.zip"
                        newcheck = f"{name}.app@{mobile}{version}~{suffix}.checksums.txt"
                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem)
                        _write_checksums(live_checksums, newcheck)
                    else:
                        print("  SKIPPED")

            else:
                print("  CHECKSUM: missing, creating…")
                rdu2 = subprocess.run(["du", "-sh", str(dest_zip)], capture_output=True, text=True)
                print(f"  zip: {rdu2.stdout.split()[0] if rdu2.stdout else '?'}")

                zip_checksums, czrc = checksums_from_zip(dest_zip)
                if czrc == 1:
                    print("  SKIPPED ⚠️: zip not readable or corrupt")
                    continue
                elif czrc == 2:
                    n = zip_checksums.count("(unreadable)  ")
                    if not unreadable_prompt(dest_zip, n):
                        continue

                zip_symlink_count = count_symlinks_from_zip(dest_zip)
                zip_external_symlinks = external_symlinks_from_zip(dest_zip)
                if not _handle_external_symlinks(zipname, "existing zip", zip_symlink_count, zip_external_symlinks):
                    continue

                live_checksums = collect_app_manifest(app, "full")
                live_manifest_hash = _sha256_text(live_checksums)
                rdu = subprocess.run(["du", "-sh", str(app)], capture_output=True, text=True)
                print(f"  app: {rdu.stdout.split()[0] if rdu.stdout else '?'}")

                if zip_checksums == live_checksums:
                    _write_checksums(zip_checksums, checksumname)
                    print("  CHECKSUM: written")
                    print("  VERIFIED ✅: zip checksum matches current app")
                else:
                    print("  MISMATCH ❌: zip checksum does not match current app")
                    choice = _tty_read("  [o]verwrite zip / [b]oth / [s]kip: ", "s")
                    if choice in ("o", "O"):
                        _remove_zip(zipname)
                        archive_and_store_zip(app, versioned, zipname, live_manifest_hash, zipstem)
                        _write_checksums(live_checksums, checksumname)
                    elif choice in ("b", "B"):
                        _write_checksums(zip_checksums, checksumname)
                        suffix = time.strftime("%Y%m%d_%H%M%S")
                        newzip = f"{name}.app@{mobile}{version}~{suffix}.zip"
                        newcheck = f"{name}.app@{mobile}{version}~{suffix}.checksums.txt"
                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem)
                        _write_checksums(live_checksums, newcheck)
                    else:
                        print("  SKIPPED")
            continue

        # No zip yet
        print("  ARCHIVE: missing")
        rdu = subprocess.run(["du", "-sh", str(app)], capture_output=True, text=True)
        print(f"  app: {rdu.stdout.split()[0] if rdu.stdout else '?'}")

        live_checksums = collect_app_manifest(app, "full")
        live_manifest_hash = _sha256_text(live_checksums)
        archive_and_store_zip(app, versioned, zipname, live_manifest_hash, zipstem)
        print("  ZIP+HASH: created")
        rdu2 = subprocess.run(["du", "-sh", str(dest_zip)], capture_output=True, text=True)
        print(f"  zip: {rdu2.stdout.split()[0] if rdu2.stdout else '?'}")
        _write_checksums(live_checksums, checksumname)
        print("  CHECKSUM: written for app")

        print("  CHECKSUM: verifying zip...")
        zip_checksums, czrc = checksums_from_zip(dest_zip)
        if czrc == 0:
            zip_symlink_count = count_symlinks_from_zip(dest_zip)
            zip_external_symlinks = external_symlinks_from_zip(dest_zip)
            if not _handle_external_symlinks(zipname, "new zip", zip_symlink_count, zip_external_symlinks):
                continue
            if zip_checksums == live_checksums:
                print("  CREATED ✅: archived checksum matches app")
                delete_validated_workdir(zipstem, live_manifest_hash)
            else:
                print("  MISMATCH ❌: archived checksum does not match original app")
        else:
            print("  SKIPPED ⚠️: zip not readable for post-archive verification")

    _print_external_symlink_summary()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    global _cfg
    _cfg = parse_args(argv if argv is not None else sys.argv[1:])

    atexit.register(_cleanup)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda s, f: sys.exit(1))

    if _cfg.verify_zip_arg:
        run_verify_zip()
    elif _cfg.verify_mode != "none":
        run_verify_all()
    else:
        run_archive()


if __name__ == "__main__":
    main()
