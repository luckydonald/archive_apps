from __future__ import annotations

import hashlib
import locale
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from .cli import Config, RunContext
from .io import rm_retry, safe_mv, safe_write
from .progress import (
    ProgressBar, copy_with_progress,
    drain_ditto_stderr, drain_rsync_stderr, run_with_bar,
)
from .utils import fmt_size, sanitize_temp_component, sha256_text, supports_xattr


def count_files(path: Path) -> int:
    return sum(1 for p in path.rglob("*") if not p.is_dir())


def archive_workdir_path(archive_stem: str, manifest_hash: str, cfg: Config) -> Path:
    safe = sanitize_temp_component(archive_stem)
    base = cfg.local_cache if cfg.local_cache else cfg.dest
    if not supports_xattr(base):
        # workdir must be on an xattr-capable filesystem to preserve resource forks;
        # fall back to the system temp dir (APFS on macOS)
        base = Path(tempfile.gettempdir())
    return base / f".archive_apps.{safe}.{manifest_hash}"


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


def copy_app_fresh(app: Path, workapp: Path) -> None:
    total = count_files(app)
    if sys.stderr.isatty() and total > 0:
        bar = ProgressBar("COPY", total)
        run_with_bar(["ditto", "-V", str(app), str(workapp)], bar, drain_ditto_stderr)
    else:
        subprocess.run(["ditto", str(app), str(workapp)], check=True)


def repair_app_copy(app: Path, workapp: Path) -> None:
    total = count_files(app)
    if sys.stderr.isatty() and total > 0:
        bar = ProgressBar("COPY", total)
        run_with_bar(
            ["rsync", "-a", "--delete", "--extended-attributes", "--progress",
             str(app) + "/", str(workapp) + "/"],
            bar, drain_rsync_stderr,
        )
    else:
        subprocess.run(
            ["rsync", "-a", "--delete", "--extended-attributes",
             str(app) + "/", str(workapp) + "/"],
            check=True,
        )


def ensure_archive_copy(app: Path, versioned: str, workdir: Path, ctx: RunContext) -> None:
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
    manifest_hash: str, archive_stem: str, ctx: RunContext,
) -> None:
    workdir = archive_workdir_path(archive_stem, manifest_hash, ctx.cfg)
    ensure_archive_copy(app, versioned, workdir, ctx)

    total = count_files(app)
    if sys.stderr.isatty() and total > 0:
        bar = ProgressBar("ZIP ", total)
        run_with_bar(
            ["ditto", "-V", "-c", "-k", "--sequesterRsrc", "--keepParent",
             versioned, str(dest_zip)],
            bar, drain_ditto_stderr,
            cwd=workdir,
        )
    else:
        subprocess.run(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
             versioned, str(dest_zip)],
            cwd=str(workdir), check=True,
        )


def delete_validated_workdir(archive_stem: str, manifest_hash: str, ctx: RunContext) -> None:
    workdir = archive_workdir_path(archive_stem, manifest_hash, ctx.cfg)
    if workdir.is_dir():
        rm_retry(workdir)


def remove_zip(zipname: str, cfg: Config) -> None:
    (cfg.dest / zipname).unlink(missing_ok=True)
    if cfg.local_cache:
        (cfg.local_cache / zipname).unlink(missing_ok=True)
        (cfg.local_cache / (zipname + ".tmp")).unlink(missing_ok=True)


def write_checksums(content: str, checksumname: str, ctx: RunContext) -> None:
    tmp = ctx.cfg.dest / (checksumname + ".tmp")
    safe_write(content, tmp, ctx)
    safe_mv(tmp, ctx.cfg.dest / checksumname, ctx)


def archive_and_store_zip(
    app: Path, versioned: str, zipname: str,
    manifest_hash: str, archive_stem: str, ctx: RunContext,
) -> None:
    cfg = ctx.cfg
    staging = cfg.local_cache if cfg.local_cache else cfg.dest
    tmp = staging / (zipname + ".tmp")
    archive_app_to_zip(app, versioned, tmp, manifest_hash, archive_stem, ctx)

    if cfg.local_cache:
        dest_tmp = cfg.dest / (zipname + ".tmp")
        if sys.stderr.isatty():
            copy_with_progress(tmp, dest_tmp)
        else:
            shutil.copy2(str(tmp), str(dest_tmp))
        shutil.move(str(dest_tmp), str(cfg.dest / zipname))
        tmp.unlink(missing_ok=True)
    else:
        shutil.move(str(tmp), str(cfg.dest / zipname))
