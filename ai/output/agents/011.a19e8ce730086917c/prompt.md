Repo: /Users/user/Documents/programming/Shell/archive_apps — a macOS tool that snapshots .app bundles into versioned zips (archive_apps/ package: archive.py, app_ops.py, io.py, verify.py, zip_ops.py, cli.py, utils.py, progress.py). Read CLAUDE.md at the repo root for full architecture context before designing.

## The bug being fixed

In archive_apps/archive.py, function run_archive, there are two near-identical "checksum mismatch" code paths, both offering an `[o]verwrite / [b]oth / [s]kip` prompt via `tty_read`:

**Branch A** (checksums file already exists but doesn't match live app), lines ~79-109:
```python
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
```

**Branch B** (checksums file missing, gets reconstructed from the zip contents), lines ~111-152:
```python
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
```

**The problem**: in the `[b]oth` branch, the canonical-named pair (`{name}.app@{mobile}{version}.zip` / `.checksums.txt`) is left pointing at the OLD/stale content (the existing zip's own checksums, not the live app's), while the NEW content that actually matches the live app gets stashed under a `~{suffix}` timestamped name. So next crawl, the canonical pair's checksum file still doesn't match the live app (if the live app hasn't changed further) — the exact same mismatch prompt fires again, indefinitely, every crawl.

## The fix the user wants

Confirmed via AskUserQuestion with the user (both decisions are final, do not re-ask):
1. Apply the fix to **both** branch A and branch B (same underlying bug in both).
2. The old zip's rename tag should be **`~hash-mismatch~{suffix}`** (standard spelling, not the double-s "missmatch" the user originally typo'd in their request).

After the `[b]oth` branch finishes creating the new (live-app-matching) pair at `newzip`/`newcheck`, prompt the user (via `tty_read`, using the same `[y/N]`-style pattern already used elsewhere in this codebase — default must be "no"/non-destructive, so headless/cron runs that can't open `/dev/tty` don't silently rename anything) asking whether to swap: make the new content become the canonical-named pair, and rename the OLD (still-canonical-named, stale) pair to carry a `~hash-mismatch~{timestamp}` tag, e.g. `Telegram.app@12.7~hash-mismatch~20260602_032921.zip` (and matching `.checksums.txt`).

If the user confirms:
- Old `zipname`/`checksumname` (currently at the canonical path, stale content) → renamed to `{name}.app@{mobile}{version}~hash-mismatch~{suffix}.zip` / `.checksums.txt`.
- New `newzip`/`newcheck` (currently at the `~{suffix}` timestamped path, live-app-matching content) → renamed to the canonical `zipname`/`checksumname`.

If the user declines (or the prompt can't be answered), leave everything exactly as today's `[b]oth` behavior already does (no change to existing behavior in that case).

## Relevant supporting code already read (do not re-explore these — use them as ground truth)

`archive_apps/app_ops.py`:
- `remove_zip(zipname, cfg)` (lines 181-185): `(cfg.dest / zipname).unlink(missing_ok=True)`, plus best-effort cleanup of `cfg.local_cache / zipname` and `cfg.local_cache / (zipname + ".tmp")` if `cfg.local_cache` is set. This is the only existing precedent for "operate on a zip's footprint across dest + local_cache", but it deletes, not renames.
- `write_checksums(content, checksumname, ctx)` (lines 188-191): writes to `ctx.cfg.dest / (checksumname + ".tmp")` via `safe_write`, then `safe_mv`s it into place.
- `archive_and_store_zip(app, versioned, zipname, manifest_hash, archive_stem, ctx)` (lines 194-212): stages the zip in `cfg.local_cache` if set (else directly in `cfg.dest`), then does a plain `shutil.move` (not `safe_mv`) to place the final zip at `cfg.dest / zipname`. Notably, **`cfg.local_cache` is only ever a staging/tmp area for zips — the finished zip always ends up solely in `cfg.dest`**, so a rename/swap of already-archived zips only needs to touch `cfg.dest` (though mirroring `remove_zip`'s defensive local_cache cleanup for stray `.tmp` leftovers is cheap insurance and consistent with existing style).

`archive_apps/io.py`:
- `tty_read(prompt, default="")` (lines 13-20): opens `/dev/tty` directly (bypasses stdin), returns `default` on any failure (non-interactive) or empty input. This is the right primitive for the new "swap? [y/N]" prompt.
- `safe_mv(src, dst, ctx)` (lines 120-142): moves a file via `shutil.move`, then does a **readback verification by calling `src.read_bytes()` before the move and comparing line counts after** — this is designed for small text files (checksums.txt) and would be wasteful/memory-heavy if reused on multi-hundred-MB or multi-GB zip files (it reads the whole file into memory to count lines). On failure it drops into `write_fail_menu(desc, str(src), dst, "mv", ctx)` for interactive retry/relocate/skip/exit.
- `write_fail_menu` (lines 23-81): the interactive retry/relocate/skip/exit menu backing `safe_write`/`safe_append`/`safe_mv`.
- **Design decision needed**: should renaming an already-finished zip file use plain `shutil.move`/`Path.rename` (consistent with how `archive_and_store_zip` already places finished zips — no `safe_mv` wrapping) or something with retry? Recommend plain move for zips (matching existing convention, avoiding the expensive readback on large binaries), but checksums.txt renames can reasonably reuse `safe_mv` (matches `write_checksums`'s existing pattern, and checksums files are tiny). Decide and justify in the plan.

`archive_apps/utils.py`: has `fmt_size`, `fmt_duration`, `sha256_text`, `sha256_file`, `sanitize_temp_component` — no existing timestamp-suffix helper. The `time.strftime("%Y%m%d_%H%M%S")` suffix format is currently duplicated inline at two call sites in archive.py (the two `[b]oth` branches) with no shared constant/helper — note a different, incompatible timestamp format (`%Y-%m-%d_%H-%M-%S`) is used elsewhere in verify.py for an unrelated `.bak.zip` rename flow and checksum-index history, so don't conflate the two; the new `~hash-mismatch~{suffix}` tag should reuse the archive.py convention (`%Y%m%d_%H%M%S`), and should reuse the SAME `suffix` value already computed for `newzip`/`newcheck` in that iteration (contemporaneous — avoids inventing a second, confusingly-different timestamp for the same event).

There is no existing "rename a zip+checksums pair as a unit" helper anywhere in the codebase — this will be new code, likely a new function in `app_ops.py` (near `remove_zip`/`write_checksums`), imported into `archive.py`.

No automated test suite exists for `archive_apps` (only a `test/` directory that's actually a data sandbox of real checksum files, not pytest tests, and unrelated tests under `scripts/°base/tests/` for a different toolset). Note this in the plan's verification section — testing will need to be manual (dry-run against `test/` or a scratch dest dir) or the plan can propose minimal new pytest coverage if it fits naturally; don't over-engineer test infrastructure for this fix.

## What I need from you

A detailed, concrete implementation plan (not code, but specific enough to execute directly) covering:
1. The new helper function's exact signature, location, and step-by-step body (what gets renamed, in what order, using which primitive — `shutil.move` vs `safe_mv` — and why), including collision-safety (never silently clobber an existing file at a rename target) and a sane partial-failure story (what state the world is in if a rename fails halfway, and whether that's acceptable or needs explicit rollback/ordering to make it safe).
2. Exact prompt text and default for the new "swap?" `tty_read` call, and exactly where it's inserted in both branch A and branch B (line-anchored to the snippets above).
3. Whether/how `suffix` needs to be plumbed into branch A (it currently only exists inside the `elif choice in ("b", "B")` block — check whether it's already in scope where the new swap-prompt code needs it, in both branches).
4. Any shared constant/helper worth extracting for the `~hash-mismatch~{suffix}` and `~{suffix}` filename patterns given they're about to appear in more places (optional — only if it clearly reduces duplication without over-engineering).
5. A verification/testing section: how to manually exercise this end-to-end (e.g., construct a scratch `--dest` dir with a zip whose checksum won't match a real installed app, run the tool, choose 'b' then 'y', inspect resulting filenames) plus any small targeted pytest worth adding for the new helper in isolation (pure file-rename logic, mockable with tmp_path).

Do not explore further — you have everything needed above. Focus on producing the plan.