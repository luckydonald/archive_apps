from __future__ import annotations

import hashlib
import locale
import posixpath
import stat
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from .progress import ProgressBar


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
