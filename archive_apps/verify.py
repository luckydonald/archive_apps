from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

from .cli import Config, RunContext
from .io import safe_append, safe_mv, safe_write, tty_read
from .lock import checksum_index_lock
from .utils import FINDER_RED, fmt_size, set_finder_color, sha256_file
from .zip_ops import checksums_from_zip, count_symlinks_from_zip, external_symlinks_from_zip

_INDEX_BACKUP_KEEP = 5


def record_verify_failure(zipname: str, reason: str, ctx: RunContext) -> None:
    ctx.verify_failure_summary.append((zipname, reason))


def print_verify_failure_summary(ctx: RunContext) -> None:
    if not ctx.verify_failure_summary:
        return
    print()
    print("Verification failure summary:")
    for zipname, reason in ctx.verify_failure_summary:
        print(f"  {zipname}")
        print(f"    {reason}")


def record_external_symlink_summary(
    app_label: str, source_label: str, entries: str, ctx: RunContext,
) -> None:
    if not entries:
        return
    ctx.external_symlink_summary.append(f"__APP__\t{app_label}\t{source_label}")
    for line in entries.splitlines():
        if line:
            ctx.external_symlink_summary.append(line)


def handle_external_symlinks(
    app_label: str, source_label: str, total_count: int, entries: str, ctx: RunContext,
) -> bool:
    external_count = len([l for l in entries.splitlines() if l]) if entries else 0
    print(f"  SYMLINKS: checked {source_label}; found {total_count} symlink(s), {external_count} external")
    if not entries:
        return True
    record_external_symlink_summary(app_label, source_label, entries, ctx)
    cfg = ctx.cfg
    print(f"  SYMLINK WARN: external target(s) detected; policy={cfg.external_symlink_policy}")
    if cfg.external_symlink_policy == "archive":
        return True
    elif cfg.external_symlink_policy == "skip":
        print("  SKIPPED ⚠️: external symlink policy")
        return False
    else:
        print("  ABORTED ❌: external symlink policy")
        sys.exit(1)


def print_external_symlink_summary(ctx: RunContext) -> None:
    if not ctx.external_symlink_summary:
        return
    print()
    print("External symlink summary:")
    for line in ctx.external_symlink_summary:
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


def verify_checksum_file_contents(
    checksumfile: Path, actual_full: str, actual_legacy: str, ctx: RunContext,
) -> bool:
    existing = checksumfile.read_text().rstrip("\n")
    if existing == actual_full:
        print("  VERIFIED ✅: checksum matches")
        return True
    if existing == actual_legacy:
        print("  VERIFIED ✅: legacy checksum matches; upgrading")
        tmp = Path(str(checksumfile) + ".tmp")
        safe_write(actual_full, tmp, ctx)
        safe_mv(tmp, checksumfile, ctx)
        return True
    print("  FAILED ❌: checksum differs")
    return False


def unreadable_prompt(zip_path: Path, n: int) -> bool:
    """Return True to continue processing, False to skip."""
    print(f"  PARTIAL ⚠️: {n} entries could not be read")
    choice = tty_read("  [a]ignore / [b]stop / [c]rename to .bak.zip / [d]delete: ", "a")
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


def _parse_index_lines(text: str) -> dict[str, str]:
    """Parse '<hash>  <filename>' lines into {filename: hash}.

    Split on the first two-space run only — app names can contain spaces
    (e.g. "Google Chrome.app@…"), so splitting on whitespace/field 2 alone
    would break the key.
    """
    entries: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            continue
        hash_part, sep, name = line.partition("  ")
        if not sep:
            continue
        entries[name] = hash_part
    return entries


def merge_checksum_index(scratch_file: Path, ctx: RunContext) -> None:
    """Merge scratch_file's (hash, filename) entries into the shared checksum
    index under a lock, keyed by filename with scratch entries winning on
    conflict. A hash replacement is never silently dropped — it's recorded
    to a history log and printed — and the index is snapshotted before each
    overwrite, so nothing here is destructive even if this logic has a bug.
    """
    cfg = ctx.cfg
    if not scratch_file.exists():
        return
    incoming = _parse_index_lines(scratch_file.read_text())
    if not incoming:
        if not cfg.keep_temp:
            scratch_file.unlink(missing_ok=True)
        return

    index_file = cfg.dest / "_checksum_index_.txt"
    history_file = cfg.dest / "_checksum_index_.history.log"

    with checksum_index_lock(cfg.dest):
        current = _parse_index_lines(index_file.read_text()) if index_file.exists() else {}
        merged = dict(current)
        added = updated = 0
        history_lines: list[str] = []
        for name, new_hash in incoming.items():
            old_hash = current.get(name)
            if old_hash is None:
                added += 1
            elif old_hash != new_hash:
                updated += 1
                ts = time.strftime("%Y-%m-%dT%H:%M:%S")
                history_lines.append(f"[{ts}] {name}: {old_hash} -> {new_hash}")
                print(f"  HASH CHANGED: {name}: {old_hash} -> {new_hash}")
            merged[name] = new_hash
        unchanged = len(incoming) - added - updated

        if added == 0 and updated == 0:
            print(f"INDEX: unchanged → {index_file.name} ({unchanged} already current)")
        else:
            if history_lines:
                with open(history_file, "a") as f:
                    for line in history_lines:
                        f.write(line + "\n")

            lines = [f"{h}  {n}" for n, h in merged.items()]
            lines.sort(key=lambda line: line.split(None, 1)[-1])
            fd, tmp_path = tempfile.mkstemp(
                prefix="_checksum_index_.", suffix=".tmp", dir=str(cfg.dest)
            )
            os.close(fd)
            try:
                Path(tmp_path).write_text("\n".join(lines) + "\n" if lines else "")
                if index_file.exists():
                    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
                    disambiguator = f"{os.getpid()}{random.randint(0, 9999):04d}"
                    backup = cfg.dest / f"_checksum_index_.{ts}.{disambiguator}.bak"
                    shutil.copy2(index_file, backup)
                os.replace(tmp_path, index_file)  # atomic: index is never absent
            except BaseException:
                Path(tmp_path).unlink(missing_ok=True)
                raise

            if not cfg.keep_temp:
                for old_backup in sorted(cfg.dest.glob("_checksum_index_.*.bak"))[:-_INDEX_BACKUP_KEEP]:
                    old_backup.unlink(missing_ok=True)

            print(
                f"INDEX: written → {index_file.name} "
                f"({added} added, {updated} updated, {unchanged} unchanged)"
            )

    if not cfg.keep_temp:
        scratch_file.unlink(missing_ok=True)


def read_index(cfg: Config) -> dict[str, str]:
    """The shared checksum index as `{file name: sha256}`; empty when there is none yet."""
    index_file = cfg.dest / "_checksum_index_.txt"
    if not index_file.exists():
        return {}
    # end if
    return _parse_index_lines(index_file.read_text())
# end def


def open_index_scratch(ctx: RunContext) -> Path:
    """Merge scratch files left over by an interrupted run, then create this run's own scratch file in `ctx.index_scratch`."""
    cfg = ctx.cfg
    for leftover in sorted(cfg.dest.glob("_checksum_index_.*.tmp")):
        try:
            content = leftover.read_text()
        except OSError:
            continue
        # end try
        print(f"RECOVERY: found leftover scratch file {leftover.name} ({len(content.splitlines())} lines)")
        if content:
            print(content, end="" if content.endswith("\n") else "\n")
        # end if
        merge_checksum_index(leftover, ctx)
    # end for

    try:
        fd, scratch_path = tempfile.mkstemp(
            prefix="_checksum_index_.", suffix=".tmp", dir=str(cfg.dest)
        )
        os.close(fd)
    except OSError:
        print(
            f"ERROR: cannot create index scratch file in {cfg.dest} — check that it is writable",
            file=sys.stderr,
        )
        sys.exit(1)
    # end try
    ctx.index_scratch = Path(scratch_path)
    return ctx.index_scratch
# end def


def hash_cached(zip_path: Path, ctx: RunContext) -> str:
    """sha256 of a zip, computed once per run."""
    if zip_path not in ctx.hash_cache:
        ctx.hash_cache[zip_path] = sha256_file(zip_path)
    # end if
    return ctx.hash_cache[zip_path]
# end def


def checksum_file_of(zip_path: Path) -> Path:
    return zip_path.with_name(zip_path.stem + ".checksums.txt")
# end def


def record_in_index(zip_path: Path, ctx: RunContext) -> None:
    """Append the current hashes of a verified zip and its checksums file to this run's index scratch file."""
    if ctx.index_scratch is None:
        return
    # end if
    safe_append(f"{hash_cached(zip_path, ctx)}  {zip_path.name}", ctx.index_scratch, ctx)
    checksumfile = checksum_file_of(zip_path)
    if checksumfile.exists():
        safe_append(f"{sha256_file(checksumfile)}  {checksumfile.name}", ctx.index_scratch, ctx)
    # end if
# end def


def is_indexed(zip_path: Path, index: dict[str, str]) -> bool:
    """Whether the zip and its existing checksums file both have an entry in the index."""
    checksumfile = checksum_file_of(zip_path)
    return bool(index.get(zip_path.name) and index.get(checksumfile.name) and checksumfile.exists())
# end def


def classify_zip(zip_path: Path, index: dict[str, str], ctx: RunContext) -> str:
    """`"new"` (not indexed), `"changed"` (a hash differs from the index) or `"unchanged"`. Hashes the files of indexed zips."""
    if not is_indexed(zip_path, index):
        return "new"
    # end if
    checksumfile = checksum_file_of(zip_path)
    if hash_cached(zip_path, ctx) != index[zip_path.name]:
        return "changed"
    # end if
    if sha256_file(checksumfile) != index[checksumfile.name]:
        return "changed"
    # end if
    return "unchanged"
# end def


def verify_one_zip(zip_path: Path, ctx: RunContext) -> bool | None:
    """Verify a zip against its checksums file (written first when missing) and record it in the index.

    Returns `True` when verified, `False` on a mismatch (recorded, zip colored red) and `None` when it could not be checked.
    """
    cfg = ctx.cfg
    zipname = zip_path.name
    checksumfile = checksum_file_of(zip_path)
    print(f"  zip: {fmt_size(zip_path)}")

    manifest, czrc = checksums_from_zip(zip_path)
    if czrc == 1:
        print("  SKIPPED ⚠️: zip not readable or corrupt")
        return None
    elif czrc == 2:
        n = manifest.count("(unreadable)  ")
        if not unreadable_prompt(zip_path, n):
            return None
        # end if
    # end if

    zip_symlink_count = count_symlinks_from_zip(zip_path)
    zip_external_symlinks = external_symlinks_from_zip(zip_path)
    if not handle_external_symlinks(zipname, "verify zip", zip_symlink_count, zip_external_symlinks, ctx):
        return None
    # end if

    if checksumfile.exists():
        actual_legacy, _ = checksums_from_zip(zip_path, "legacy")
        if not verify_checksum_file_contents(checksumfile, manifest, actual_legacy, ctx):
            record_verify_failure(zipname, "checksum file differs", ctx)
            set_finder_color(zip_path, FINDER_RED)
            if cfg.verify_abort:
                print("  ABORTED ❌: verification failed (--verify-abort)")
                sys.exit(1)
            # end if
            return False
        # end if
    else:
        print("  CHECKSUM: missing, creating…")
        tmp = Path(str(checksumfile) + ".tmp")
        safe_write(manifest, tmp, ctx)
        safe_mv(tmp, checksumfile, ctx)
        print("  CHECKSUM: written")
    # end if

    record_in_index(zip_path, ctx)
    return True
# end def
