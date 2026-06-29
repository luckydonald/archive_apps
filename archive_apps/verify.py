from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

from .cli import RunContext
from .io import safe_append, safe_mv, safe_write, tty_read
from .utils import fmt_size, sha256_file
from .zip_ops import checksums_from_zip, count_symlinks_from_zip, external_symlinks_from_zip


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


def resolve_verify_zip_arg(arg: str, cfg) -> list[Path]:
    if arg.endswith(".zip"):
        p = Path(arg) if "/" in arg else cfg.dest / arg
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

    found = sorted(cfg.dest.glob(f"{appname}.app@*.zip"))
    if not found:
        print(f"Error: no zips found for app '{appname}' in {cfg.dest}", file=sys.stderr)
        sys.exit(1)
    return found


def run_verify_zip(ctx: RunContext) -> None:
    zips = resolve_verify_zip_arg(ctx.cfg.verify_zip_arg, ctx.cfg)
    total = len(zips)
    width = len(str(total))
    print(f"Verifying {total} zip(s) [--verify-zip]…")

    for i, zip_path in enumerate(zips, 1):
        idx = str(i).zfill(width)
        zipname = zip_path.name
        checksumfile = zip_path.with_name(zip_path.stem + ".checksums.txt")

        print(f"VERIFY {idx}/{total}: {zipname}")
        print(f"  zip: {fmt_size(zip_path)}")

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
        if not handle_external_symlinks(zipname, "verify zip", zip_symlink_count, zip_external_symlinks, ctx):
            continue

        if checksumfile.is_file():
            actual_legacy, _ = checksums_from_zip(zip_path, "legacy")
            if not verify_checksum_file_contents(checksumfile, manifest, actual_legacy, ctx):
                record_verify_failure(zipname, "checksum file differs", ctx)
                if ctx.cfg.verify_abort:
                    print("  ABORTED ❌: verification failed (--verify-abort)")
                    print_verify_failure_summary(ctx)
                    sys.exit(1)
        else:
            print("  CHECKSUM: no checksum file found")

    print_verify_failure_summary(ctx)
    if ctx.verify_failure_summary:
        sys.exit(1)
    sys.exit(0)


def run_verify_all(ctx: RunContext) -> None:
    cfg = ctx.cfg
    index_file = cfg.dest / "_checksum_index_.txt"
    index_tmp = cfg.dest / "_checksum_index_.txt.tmp"

    if index_tmp.exists():
        print(f"RECOVERY: Found leftover temp file: {index_tmp.name}")
        ans = tty_read("  Restore it? [Y/n]: ", "n")
        if ans.lower() not in ("n", ""):
            rc_live = len(index_file.read_text().splitlines()) if index_file.exists() else 0
            ans2 = tty_read(f"  Existing file: {rc_live} lines. Merge? [Y/n]: ", "n")
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
                ans3 = tty_read("  Continue? [Y/n]: ", "n")
                if ans3.lower() not in ("n", ""):
                    fd, tmp_path = tempfile.mkstemp(
                        prefix="_checksum_index_.", suffix=".tmp", dir=str(cfg.dest)
                    )
                    os.close(fd)
                    Path(tmp_path).write_text("\n".join(merged) + "\n")
                    safe_mv(Path(tmp_path), index_file, ctx)
                    print("  RECOVERY ✅: merged and written")
                    ans4 = tty_read("  Delete temp file? [Y/n]: ", "n")
                    if ans4.lower() not in ("n", ""):
                        index_tmp.unlink(missing_ok=True)
                        print("  RECOVERY: temp file deleted")

    try:
        index_tmp.write_text("")
    except Exception:
        print(
            f"ERROR: cannot create index file at {index_tmp}"
            f" — check that {index_tmp.parent} is writable",
            file=sys.stderr,
        )
        sys.exit(1)

    zips = sorted(cfg.dest.glob("*.zip"))
    total = len(zips)
    width = len(str(total))
    print(f"Verifying {total} zip(s) [--verify-{cfg.verify_mode}]…")

    for i, zip_path in enumerate(zips, 1):
        idx = str(i).zfill(width)
        zipname = zip_path.name
        checksumfile = cfg.dest / (zip_path.stem + ".checksums.txt")
        checksumname = checksumfile.name
        print(f"VERIFY {idx}/{total}: {zipname}")

        current_zip_hash = ""
        zip_stored = ""
        cs_stored = ""
        if cfg.verify_mode != "zips" and index_file.exists():
            for line in index_file.read_text().splitlines():
                if line.endswith(f"  {zipname}"):
                    zip_stored = line.split()[0]
                if line.endswith(f"  {checksumname}"):
                    cs_stored = line.split()[0]

        if cfg.verify_mode == "new":
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
                safe_append(f"{zip_stored}  {zipname}", index_tmp, ctx)
                safe_append(f"{cs_stored}  {checksumname}", index_tmp, ctx)
                continue

        elif cfg.verify_mode == "changed":
            current_zip_hash = sha256_file(zip_path)
            if current_zip_hash:
                print(f"  zip: {current_zip_hash}")
            else:
                print("  CACHE-MISS 🔸: zip")
            if zip_stored and current_zip_hash != zip_stored:
                print("  CHANGED 🔸: zip")
            cs_current = ""
            if checksumfile.exists():
                cs_current = sha256_file(checksumfile)
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
                safe_append(f"{current_zip_hash}  {zipname}", index_tmp, ctx)
                safe_append(f"{cs_current}  {checksumname}", index_tmp, ctx)
                continue

        print(f"  zip: {fmt_size(zip_path)}")

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
        if not handle_external_symlinks(zipname, "verify zip", zip_symlink_count, zip_external_symlinks, ctx):
            continue

        if checksumfile.exists():
            actual_legacy, _ = checksums_from_zip(zip_path, "legacy")
            if not verify_checksum_file_contents(checksumfile, manifest, actual_legacy, ctx):
                record_verify_failure(zipname, "checksum file differs", ctx)
                if cfg.verify_abort:
                    print("  ABORTED ❌: verification failed (--verify-abort)")
                    print_verify_failure_summary(ctx)
                    sys.exit(1)
                continue
        else:
            print("  CHECKSUM: missing, creating…")
            tmp = Path(str(checksumfile) + ".tmp")
            safe_write(manifest, tmp, ctx)
            safe_mv(tmp, checksumfile, ctx)
            print("  CHECKSUM: written")

        if not current_zip_hash:
            current_zip_hash = sha256_file(zip_path)
        safe_append(f"{current_zip_hash}  {zipname}", index_tmp, ctx)
        if checksumfile.exists():
            cs_hash = sha256_file(checksumfile)
            safe_append(f"{cs_hash}  {checksumname}", index_tmp, ctx)

    # Sort by filename (second whitespace-delimited field), matching 'sort -k2'
    lines = [l for l in index_tmp.read_text().splitlines() if l]
    lines.sort(key=lambda line: line.split(None, 1)[-1])
    index_tmp.write_text("\n".join(lines) + "\n")
    safe_mv(index_tmp, index_file, ctx)
    print(f"INDEX: written → {index_file.name}")
    print_verify_failure_summary(ctx)
