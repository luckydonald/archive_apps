from __future__ import annotations

import plistlib
import random
import sys
from pathlib import Path

from .app_ops import (
    archive_and_store_zip, collect_app_manifest, collect_external_live_symlinks,
    count_live_symlinks, delete_validated_workdir, remove_checksum, remove_zip,
    swap_hash_mismatch_pair, write_checksums,
)
from .cli import MismatchTask, RunContext, SwapTask, VerifyMismatchTask
from .io import tty_read, tty_read_timeout
from .utils import fmt_size, now_suffix, sha256_text, tagged_names
from .verify import (
    handle_external_symlinks, print_external_symlink_summary,
    print_verify_failure_summary, record_verify_failure,
    unreadable_prompt, verify_checksum_file_contents,
)
from .zip_ops import checksums_from_zip, count_symlinks_from_zip, external_symlinks_from_zip

MISMATCH_PROMPT_TIMEOUT_SECONDS = 60


def plist_value(plist_path: Path, key: str) -> str | None:
    try:
        with open(plist_path, "rb") as f:
            data = plistlib.load(f)
        v = data.get(key)
        return str(v) if v is not None else None
    except Exception:
        return None


def _prompt_with_optional_timeout(prompt: str, default: str, timeout: float | None) -> tuple[str, bool]:
    if timeout is None:
        return tty_read(prompt, default), False
    return tty_read_timeout(prompt, default, timeout)


def _offer_hash_mismatch_swap(
    name: str, mobile: str, version: str,
    zipname: str, checksumname: str,
    newzip: str, newcheck: str,
    suffix: str, ctx: RunContext, timeout: float | None,
) -> None:
    cfg = ctx.cfg
    if cfg.mismatch_swap is not None:
        do_swap = cfg.mismatch_swap == "yes"
    else:
        answer, timed_out = _prompt_with_optional_timeout(
            "  Swap in the new archive as the canonical version "
            "(old kept as ~hash-mismatch~)? [y/N]: ", "n", timeout,
        )
        if timed_out:
            print(f"  TIMED OUT after {MISMATCH_PROMPT_TIMEOUT_SECONDS}s — will re-ask at end of run")
            ctx.deferred_swaps.append(SwapTask(
                f"{name} {version}", name, mobile, version,
                zipname, checksumname, newzip, newcheck, suffix,
            ))
            return
        do_swap = answer in ("y", "Y")
    if not do_swap:
        return
    mismatch_zip, mismatch_check = tagged_names(name, mobile, version, f"hash-mismatch~{suffix}")
    if swap_hash_mismatch_pair(cfg, zipname, checksumname, newzip, newcheck, mismatch_zip, mismatch_check):
        print(f"  SWAPPED ✅: {zipname} is now the live-matching archive; old content kept as {mismatch_zip}")
    else:
        print("  SWAP SKIPPED: layout left unchanged")


def _resolve_mismatch(task: MismatchTask, ctx: RunContext, timeout: float | None) -> None:
    cfg = ctx.cfg
    if cfg.on_mismatch is not None:
        choice = {"overwrite": "o", "both": "b", "skip": "s"}[cfg.on_mismatch]
        timed_out = False
    else:
        choice, timed_out = _prompt_with_optional_timeout(
            "  [o]verwrite zip / [b]oth (version previous) / [s]kip: ", "s", timeout,
        )
    if timed_out:
        print(f"  TIMED OUT after {MISMATCH_PROMPT_TIMEOUT_SECONDS}s — will re-ask at end of run")
        ctx.deferred_mismatches.append(task)
        return
    if choice in ("o", "O"):
        remove_zip(task.zipname, cfg)
        archive_and_store_zip(task.app, task.versioned, task.zipname, task.live_manifest_hash, task.zipstem, ctx)
        write_checksums(task.live_checksums, task.checksumname, ctx)
    elif choice in ("b", "B"):
        if task.zip_checksums is not None:
            write_checksums(task.zip_checksums, task.checksumname, ctx)
        suffix = now_suffix()
        newzip, newcheck = tagged_names(task.name, task.mobile, task.version, suffix)
        archive_and_store_zip(task.app, task.versioned, newzip, task.live_manifest_hash, task.zipstem, ctx)
        write_checksums(task.live_checksums, newcheck, ctx)
        _offer_hash_mismatch_swap(
            task.name, task.mobile, task.version, task.zipname,
            task.checksumname, newzip, newcheck, suffix, ctx, timeout,
        )
    else:
        print("  SKIPPED")


def _resolve_verify_mismatch(task: VerifyMismatchTask, ctx: RunContext, timeout: float | None) -> None:
    cfg = ctx.cfg
    if cfg.on_verify_mismatch is not None:
        choice = {"retry": "r", "delete": "d", "keep": "k"}[cfg.on_verify_mismatch]
        timed_out = False
    else:
        choice, timed_out = _prompt_with_optional_timeout(
            "  [r]etry now / [d]elete zip+checksum / [k]eep as-is: ", "k", timeout,
        )
    if timed_out:
        print(f"  TIMED OUT after {MISMATCH_PROMPT_TIMEOUT_SECONDS}s — will re-ask at end of run")
        ctx.deferred_verify_mismatches.append(task)
        return
    if choice in ("r", "R"):
        remove_zip(task.zipname, cfg)
        archive_and_store_zip(task.app, task.versioned, task.zipname, task.live_manifest_hash, task.zipstem, ctx)
        write_checksums(task.live_checksums, task.checksumname, ctx)
        zip_checksums, czrc = checksums_from_zip(cfg.dest / task.zipname)
        if czrc == 0 and zip_checksums == task.live_checksums:
            print("  RETRIED ✅: archived checksum now matches app")
            delete_validated_workdir(task.zipstem, task.live_manifest_hash, ctx)
        else:
            record_verify_failure(task.zipname, "post-creation checksum mismatch persisted after retry", ctx)
            print("  MISMATCH ❌: still does not match after retry — leaving as-is")
    elif choice in ("d", "D"):
        remove_zip(task.zipname, cfg)
        remove_checksum(task.checksumname, cfg)
        record_verify_failure(task.zipname, "post-creation checksum mismatch — zip+checksum deleted, will re-archive next run", ctx)
        print("  DELETED: zip+checksum removed; will re-archive fresh next run")
    else:
        record_verify_failure(task.zipname, "post-creation checksum mismatch — left as-is", ctx)
        print("  KEPT: left as-is (see verification failure summary)")


def run_archive(ctx: RunContext) -> None:
    cfg = ctx.cfg
    apps = [
        p for p in Path("/Applications").glob("**/*.app")
        if p.is_dir() and len(p.relative_to("/Applications").parts) <= 2
    ]
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
            print(f"  app: {fmt_size(app)}")
            print("  SKIPPING ⚠️: no Info.plist")
            continue

        name = plist_value(plist, "CFBundleName") or app.stem
        version = plist_value(plist, "CFBundleShortVersionString") or "unknown"

        zipname = f"{name}.app@{mobile}{version}.zip"
        checksumname = f"{name}.app@{mobile}{version}.checksums.txt"
        zipstem = zipname.removesuffix(".zip")
        versioned = f"{name} {version}.app"

        print(f"ARCHIVING {idx}/{total}: {zipname}")

        live_symlink_count = count_live_symlinks(app)
        live_external_symlinks = collect_external_live_symlinks(app)
        if not handle_external_symlinks(zipname, "live app", live_symlink_count, live_external_symlinks, ctx):
            continue

        dest_zip = cfg.dest / zipname
        dest_checksum = cfg.dest / checksumname

        if dest_zip.exists():
            print("  ARCHIVE: found")

            if dest_checksum.exists():
                print("  CHECKSUM: found")
                print(f"  app: {fmt_size(app)}")
                print(f"  zip: {fmt_size(dest_zip)}")

                zip_symlink_count = count_symlinks_from_zip(dest_zip)
                zip_external_symlinks = external_symlinks_from_zip(dest_zip)
                if not handle_external_symlinks(zipname, "existing zip", zip_symlink_count, zip_external_symlinks, ctx):
                    continue

                live_checksums = collect_app_manifest(app, "full")
                live_checksums_legacy = collect_app_manifest(app, "legacy")
                live_manifest_hash = sha256_text(live_checksums)

                if verify_checksum_file_contents(dest_checksum, live_checksums, live_checksums_legacy, ctx):
                    print("  VERIFIED ✅: archived checksum matches current app")
                else:
                    print("  MISMATCH ❌: archived checksum does not match current app")
                    task = MismatchTask(
                        label=f"{name} {version}", app=app, name=name, mobile=mobile, version=version,
                        versioned=versioned, zipname=zipname, checksumname=checksumname, zipstem=zipstem,
                        live_manifest_hash=live_manifest_hash, live_checksums=live_checksums,
                        zip_checksums=None,
                    )
                    _resolve_mismatch(task, ctx, MISMATCH_PROMPT_TIMEOUT_SECONDS)

            else:
                print("  CHECKSUM: missing, creating…")
                print(f"  zip: {fmt_size(dest_zip)}")

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
                if not handle_external_symlinks(zipname, "existing zip", zip_symlink_count, zip_external_symlinks, ctx):
                    continue

                live_checksums = collect_app_manifest(app, "full")
                live_manifest_hash = sha256_text(live_checksums)
                print(f"  app: {fmt_size(app)}")

                if zip_checksums == live_checksums:
                    write_checksums(zip_checksums, checksumname, ctx)
                    print("  CHECKSUM: written")
                    print("  VERIFIED ✅: zip checksum matches current app")
                else:
                    print("  MISMATCH ❌: zip checksum does not match current app")
                    task = MismatchTask(
                        label=f"{name} {version}", app=app, name=name, mobile=mobile, version=version,
                        versioned=versioned, zipname=zipname, checksumname=checksumname, zipstem=zipstem,
                        live_manifest_hash=live_manifest_hash, live_checksums=live_checksums,
                        zip_checksums=zip_checksums,
                    )
                    _resolve_mismatch(task, ctx, MISMATCH_PROMPT_TIMEOUT_SECONDS)
            continue

        # No zip yet
        print("  ARCHIVE: missing")
        print(f"  app: {fmt_size(app)}")

        live_checksums = collect_app_manifest(app, "full")
        live_manifest_hash = sha256_text(live_checksums)
        archive_and_store_zip(app, versioned, zipname, live_manifest_hash, zipstem, ctx)
        print("  ZIP+HASH: created")
        print(f"  zip: {fmt_size(dest_zip)}")
        write_checksums(live_checksums, checksumname, ctx)
        print("  CHECKSUM: written for app")

        print("  CHECKSUM: verifying zip...")
        zip_checksums, czrc = checksums_from_zip(dest_zip)
        if czrc == 0:
            zip_symlink_count = count_symlinks_from_zip(dest_zip)
            zip_external_symlinks = external_symlinks_from_zip(dest_zip)
            if not handle_external_symlinks(zipname, "new zip", zip_symlink_count, zip_external_symlinks, ctx):
                continue
            if zip_checksums == live_checksums:
                print("  CREATED ✅: archived checksum matches app")
                delete_validated_workdir(zipstem, live_manifest_hash, ctx)
            else:
                print("  MISMATCH ❌: archived checksum does not match original app")
                task = VerifyMismatchTask(
                    label=f"{name} {version}", app=app, versioned=versioned,
                    zipname=zipname, checksumname=checksumname, zipstem=zipstem,
                    live_manifest_hash=live_manifest_hash, live_checksums=live_checksums,
                )
                _resolve_verify_mismatch(task, ctx, MISMATCH_PROMPT_TIMEOUT_SECONDS)
        else:
            print("  SKIPPED ⚠️: zip not readable for post-archive verification")

    if ctx.deferred_mismatches or ctx.deferred_swaps or ctx.deferred_verify_mismatches:
        n = len(ctx.deferred_mismatches) + len(ctx.deferred_swaps) + len(ctx.deferred_verify_mismatches)
        print(f"\n{n} deferred prompt(s) from earlier timeouts — resolving now (will wait for input):")
        for task in ctx.deferred_mismatches:
            print(f"RESOLVING: {task.label}")
            _resolve_mismatch(task, ctx, timeout=None)
        for task in ctx.deferred_swaps:
            print(f"SWAP?: {task.label}")
            _offer_hash_mismatch_swap(
                task.name, task.mobile, task.version, task.zipname,
                task.checksumname, task.newzip, task.newcheck, task.suffix,
                ctx, timeout=None,
            )
        for task in ctx.deferred_verify_mismatches:
            print(f"RESOLVING: {task.label}")
            _resolve_verify_mismatch(task, ctx, timeout=None)

    print_external_symlink_summary(ctx)
    print_verify_failure_summary(ctx)
    if ctx.verify_failure_summary:
        sys.exit(1)
