from __future__ import annotations

import plistlib
import random
import time
from pathlib import Path

from .app_ops import (
    archive_and_store_zip, collect_app_manifest, collect_external_live_symlinks,
    count_live_symlinks, delete_validated_workdir, remove_zip, write_checksums,
)
from .cli import RunContext
from .io import tty_read
from .utils import fmt_size, sha256_text
from .verify import (
    handle_external_symlinks, print_external_symlink_summary,
    unreadable_prompt, verify_checksum_file_contents,
)
from .zip_ops import checksums_from_zip, count_symlinks_from_zip, external_symlinks_from_zip


def plist_value(plist_path: Path, key: str) -> str | None:
    try:
        with open(plist_path, "rb") as f:
            data = plistlib.load(f)
        v = data.get(key)
        return str(v) if v is not None else None
    except Exception:
        return None


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
                    choice = tty_read("  [o]verwrite zip / [b]oth / [s]kip: ", "s")
                    if choice in ("o", "O"):
                        remove_zip(zipname, cfg)
                        archive_and_store_zip(app, versioned, zipname, live_manifest_hash, zipstem, ctx)
                        write_checksums(live_checksums, checksumname, ctx)
                    elif choice in ("b", "B"):
                        suffix = time.strftime("%Y%m%d_%H%M%S")
                        newzip = f"{name}.app@{mobile}{version}~{suffix}.zip"
                        newcheck = f"{name}.app@{mobile}{version}~{suffix}.checksums.txt"
                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem, ctx)
                        write_checksums(live_checksums, newcheck, ctx)
                    else:
                        print("  SKIPPED")

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
                    choice = tty_read("  [o]verwrite zip / [b]oth / [s]kip: ", "s")
                    if choice in ("o", "O"):
                        remove_zip(zipname, cfg)
                        archive_and_store_zip(app, versioned, zipname, live_manifest_hash, zipstem, ctx)
                        write_checksums(live_checksums, checksumname, ctx)
                    elif choice in ("b", "B"):
                        write_checksums(zip_checksums, checksumname, ctx)
                        suffix = time.strftime("%Y%m%d_%H%M%S")
                        newzip = f"{name}.app@{mobile}{version}~{suffix}.zip"
                        newcheck = f"{name}.app@{mobile}{version}~{suffix}.checksums.txt"
                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem, ctx)
                        write_checksums(live_checksums, newcheck, ctx)
                    else:
                        print("  SKIPPED")
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
        else:
            print("  SKIPPED ⚠️: zip not readable for post-archive verification")

    print_external_symlink_summary(ctx)
