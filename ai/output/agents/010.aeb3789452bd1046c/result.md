# Research Report: Checksum-Mismatch Handling for "zip exists, checksums missing"

## 1. Where the branch lives, and where checksums are computed/compared

File: `/Users/user/Documents/programming/Shell/archive_apps/archive_apps/archive.py`, function `run_archive` (whole function spans lines 32–182).

The dispatch on zip/checksum existence starts at line 76:

```python
76        if dest_zip.exists():
77            print("  ARCHIVE: found")
78
79            if dest_checksum.exists():
                  ...  # lines 79-110: "checksums file already exists" branch (verify against live app)
111            else:
112                print("  CHECKSUM: missing, creating…")
```

**The branch you asked about is the `else` at line 111–152** (checksums file missing while the zip exists):

```python
111            else:
112                print("  CHECKSUM: missing, creating…")
113                print(f"  zip: {fmt_size(dest_zip)}")
114
115                zip_checksums, czrc = checksums_from_zip(dest_zip)
116                if czrc == 1:
117                    print("  SKIPPED ⚠️: zip not readable or corrupt")
118                    continue
119                elif czrc == 2:
120                    n = zip_checksums.count("(unreadable)  ")
121                    if not unreadable_prompt(dest_zip, n):
122                        continue
123
124                zip_symlink_count = count_symlinks_from_zip(dest_zip)
125                zip_external_symlinks = external_symlinks_from_zip(dest_zip)
126                if not handle_external_symlinks(zipname, "existing zip", zip_symlink_count, zip_external_symlinks, ctx):
127                    continue
128
129                live_checksums = collect_app_manifest(app, "full")
130                live_manifest_hash = sha256_text(live_checksums)
131                print(f"  app: {fmt_size(app)}")
132
133                if zip_checksums == live_checksums:
134                    write_checksums(zip_checksums, checksumname, ctx)
135                    print("  CHECKSUM: written")
136                    print("  VERIFIED ✅: zip checksum matches current app")
137                else:
138                    print("  MISMATCH ❌: zip checksum does not match current app")
139                    choice = tty_read("  [o]verwrite zip / [b]oth / [s]kip: ", "s")
140                    if choice in ("o", "O"):
141                        remove_zip(zipname, cfg)
142                        archive_and_store_zip(app, versioned, zipname, live_manifest_hash, zipstem, ctx)
143                        write_checksums(live_checksums, checksumname, ctx)
144                    elif choice in ("b", "B"):
145                        write_checksums(zip_checksums, checksumname, ctx)
146                        suffix = time.strftime("%Y%m%d_%H%M%S")
147                        newzip = f"{name}.app@{mobile}{version}~{suffix}.zip"
148                        newcheck = f"{name}.app@{mobile}{version}~{suffix}.checksums.txt"
149                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem, ctx)
150                        write_checksums(live_checksums, newcheck, ctx)
151                    else:
152                        print("  SKIPPED")
153            continue
```

- Checksums for the **existing zip** are extracted via `checksums_from_zip(dest_zip)` (line 115) — from `archive_apps/zip_ops.py` (not read in full above, but imported at `archive.py:19`). Return value is `(manifest_text, rc)`; `rc==1` unreadable/corrupt (skip app), `rc==2` partially unreadable (goes through `unreadable_prompt`, `verify.py:99-124`).
- Checksums for the **live app** are computed via `collect_app_manifest(app, "full")` (line 129), defined in `app_ops.py:36-60`. It walks the app bundle, sha256-hashes every regular file (and symlink targets in "full" mode), sorted by locale collation, producing `"<sha256>  <relpath>"` lines joined by `\n`.
- Comparison is a plain string equality: `zip_checksums == live_checksums` (line 133) — no `verify_checksum_file_contents` call here (that helper, `verify.py:82-96`, is only used in the *other* branch at line 93, where an existing `.checksums.txt` file is compared, including its legacy-format fallback and self-upgrade). In this "missing checksums" branch there is no legacy-format comparison at all, since there's no checksum *file* to read — it's zip-content vs live-app directly.

Note there is a structurally near-identical branch for "checksum file exists but content differs" at lines 79–110 (the `if dest_checksum.exists():` case) that follows the exact same overwrite/both/skip pattern — worth noting since a fix might need to touch both spots.

## 2. What happens on match vs mismatch

- **Match** (line 133 `if zip_checksums == live_checksums:`): writes the checksums file using the zip's own extracted checksums (not recomputed from live app — though they're equal so it doesn't matter) via `write_checksums(zip_checksums, checksumname, ctx)` (line 134), prints `"  CHECKSUM: written"` and `"  VERIFIED ✅: zip checksum matches current app"`.
- **Mismatch** (`else` at line 137): prints `"  MISMATCH ❌: zip checksum does not match current app"`, then calls `tty_read` for an interactive choice (see #3 below).

`write_checksums` itself: `app_ops.py:188-191`

```python
188def write_checksums(content: str, checksumname: str, ctx: RunContext) -> None:
189    tmp = ctx.cfg.dest / (checksumname + ".tmp")
190    safe_write(content, tmp, ctx)
191    safe_mv(tmp, ctx.cfg.dest / checksumname, ctx)
```

It always writes to a `.tmp` file in `cfg.dest` first (via `safe_write`, `io.py:102-117`), then atomically-ish moves it into place with `safe_mv` (`io.py:120-142`), both of which have retry/fallback UI via `write_fail_menu` on failure.

## 3. Exact interactive prompt for the mismatch case

Function: `tty_read`, `archive_apps/io.py:13-20`:

```python
13def tty_read(prompt: str, default: str = "") -> str:
14    try:
15        with open("/dev/tty") as tty:
16            sys.stderr.write(prompt)
17            sys.stderr.flush()
18            return tty.readline().rstrip("\n") or default
19    except Exception:
20        return default
```

Call site, `archive_apps/archive.py:139` (and identically at line 97 in the other branch):

```python
choice = tty_read("  [o]verwrite zip / [b]oth / [s]kip: ", "s")
```

Literal prompt text: `"  [o]verwrite zip / [b]oth / [s]kip: "`, default `"s"` (skip) if input is empty or `/dev/tty` can't be opened (non-interactive/CI-safe default).

Branching, lines 140–152:
```python
if choice in ("o", "O"):
    ...
elif choice in ("b", "B"):
    ...
else:
    print("  SKIPPED")
```
Any value other than `o`/`O`/`b`/`B` (including the default `"s"`) falls into skip.

## 4. The `[b]oth` branch — exact file operations

Lines 144–150 (missing-checksum branch):

```python
144                    elif choice in ("b", "B"):
145                        write_checksums(zip_checksums, checksumname, ctx)
146                        suffix = time.strftime("%Y%m%d_%H%M%S")
147                        newzip = f"{name}.app@{mobile}{version}~{suffix}.zip"
148                        newcheck = f"{name}.app@{mobile}{version}~{suffix}.checksums.txt"
149                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem, ctx)
150                        write_checksums(live_checksums, newcheck, ctx)
```

Step by step:
1. **Old (existing, mismatched) zip is left completely untouched on disk** — no rename, no move, nothing happens to `dest_zip`/`zipname`. It stays at its original name `{name}.app@{mobile}{version}.zip`.
2. **Old zip's checksums file is written for the first time** (it didn't exist before this branch, by definition) at the *original* name `checksumname = f"{name}.app@{mobile}{version}.checksums.txt"`, using the content extracted **from the zip itself** (`zip_checksums`, the possibly-stale content) — via `write_checksums(zip_checksums, checksumname, ctx)` (line 145). So after this branch, the old mismatched zip finally gets a checksums file, but it records the zip's own (old/stale) hash, not the live app's.
3. A timestamp suffix is computed: `suffix = time.strftime("%Y%m%d_%H%M%S")` (line 146) — e.g. `20260903_143022`.
4. **New zip name**: `newzip = f"{name}.app@{mobile}{version}~{suffix}.zip"` (line 147) — i.e. original zip stem + `~` + timestamp + `.zip`. Note: `mobile` is `"mobile@"` or `""`, `version` unmodified, so full pattern is `{name}.app@[mobile@]{version}~{YYYYMMDD_HHMMSS}.zip`.
5. **New checksums name**: `newcheck = f"{name}.app@{mobile}{version}~{suffix}.checksums.txt"` (line 148) — same stem+suffix, `.checksums.txt` extension.
6. **New zip is created from the live/current app**: `archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem, ctx)` (line 149) — this is the actual snapshot/zip-creation routine (`app_ops.py:194-212`), which copies the live app into a workdir, zips it with `ditto`, and moves/copies the result into `cfg.dest / newzip` (optionally staging through `cfg.local_cache` first). `zipstem` here is the **original** stem (`zipname.removesuffix(".zip")`, set at `archive.py:63`), used only to compute the workdir cache path (`archive_workdir_path`, `app_ops.py:26-33`) — it does not affect the output filename, which is `newzip`.
7. **New checksums file is written from the freshly computed live-app manifest**: `write_checksums(live_checksums, newcheck, ctx)` (line 150) — `live_checksums` was computed earlier at line 129 via `collect_app_manifest(app, "full")`.

Result: two zip+checksum pairs end up on disk — the untouched old pair (`...@{version}.zip` / `...@{version}.checksums.txt`, the latter newly written but reflecting the *old* zip content) and a brand-new pair (`...@{version}~{timestamp}.zip` / matching `.checksums.txt`, reflecting the *current live app*).

The parallel `[b]oth` branch in the "checksum file already exists but content mismatches" case (lines 102–107) is simpler because the checksums file already existed and is untouched — no `write_checksums` call for the old pair:
```python
102                    elif choice in ("b", "B"):
103                        suffix = time.strftime("%Y%m%d_%H%M%S")
104                        newzip = f"{name}.app@{mobile}{version}~{suffix}.zip"
105                        newcheck = f"{name}.app@{mobile}{version}~{suffix}.checksums.txt"
106                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem, ctx)
107                        write_checksums(live_checksums, newcheck, ctx)
```

## 5. The `{stem}~{YYYYMMDD_HHMMSS}.zip` timestamp-suffix pattern

Documented in `CLAUDE.md` line 66: `| Timestamp-suffixed duplicate | `{stem}~{YYYYMMDD_HHMMSS}.zip` |` (also see line 54: `Mismatch → prompt interactively: [o]verwrite the zip (replace with current live app), [b]oth (keep existing zip + write new zip with a timestamp suffix), or [s]kip.`).

There is **no shared constant or helper function** for this — the format string `"%Y%m%d_%H%M%S"` is duplicated literally in two places in `archive.py` (lines 103 and 146), each immediately followed by identical f-string constructions for `newzip`/`newcheck`. This is the only place in the codebase using exactly this format; it is not factored into `utils.py`.

A related-but-different timestamp format exists in `verify.py:99-124` (`unreadable_prompt`), used for a "rename corrupt zip to `.bak.zip`" flow:
```python
107        bak = zip_path.with_suffix("." + time.strftime("%Y-%m-%d_%H-%M-%S") + ".bak.zip")
```
Note the different format (`%Y-%m-%d_%H-%M-%S`, hyphens/dashes instead of compact digits) and different suffix scheme (`.bak.zip` via `with_suffix`, not `~timestamp` appended to the stem). This shows the codebase isn't fully consistent about timestamp formatting — something to be aware of when adding a new `~hash-missmatch~{timestamp}` pattern; it should probably match the `archive.py` `%Y%m%d_%H%M%S` convention rather than `verify.py`'s.

Another timestamp usage: `verify.py:242` and `verify.py:257` use `"%Y-%m-%dT%H:%M:%S"` and `"%Y-%m-%d_%H-%M-%S"` respectively for checksum-index history/backup file naming — again inconsistent formats, again no shared helper.

`utils.py` has no timestamp-suffix helper at all — `fmt_duration` (lines 11–17) formats elapsed seconds as `H:MM:SS`/`MM:SS` for progress display, and `fmt_eta_target` (lines 20–30) formats an ETA clock time — neither is related to filename suffixing.

## 6. Existing "rename zip + checksums as a pair" logic / `safe_mv` usage

There is **no existing helper that renames/moves a zip together with its checksums file as a pair**. Searching the whole `archive_apps/` package for `safe_mv` usage found only 3 call sites, all unrelated to zip+checksums pair renaming:

- `verify.py:93` — inside `verify_checksum_file_contents` (lines 82-96), moving a `.tmp` file over the checksums file after a legacy-format upgrade.
- `verify.py:404` — inside `run_verify_all`, writing a freshly created checksums file (`tmp` → `checksumfile`).
- `app_ops.py:191` — inside `write_checksums` (shown in #2 above), moving the tmp checksums content into place.

`app_ops.py` and `archive.py` never call `safe_mv` on a `.zip` file at all — zip files are moved with plain `shutil.move` (see `archive_and_store_zip`, `app_ops.py:194-212`, lines 209 and 212) rather than the safer `safe_mv`/`write_fail_menu`-backed path used for checksum text files. There's also no `.rename()`/`shutil.move` call anywhere in `archive.py` or `app_ops.py` that renames an *existing* zip file in place (the closest analog is the `.bak.zip` rename in `verify.py:107-110`'s `unreadable_prompt`, which does `zip_path.rename(bak)` directly, not via `safe_mv`).

So a future "rename existing mismatched zip+checksums pair with a `~hash-missmatch~{timestamp}` suffix" feature would need to be written from scratch — there's a precedent for the *filename pattern* (`~{suffix}` appended before `.zip`/`.checksums.txt`, as in the `[b]oth` branches), and a precedent for *safely moving a checksums text file* (`safe_mv`, used only for text files so far), but no existing "move a zip + its sibling checksums file together" utility to reuse directly. `remove_zip` (`app_ops.py:181-185`) is the closest existing "operate on a zip's related files" helper, but it *deletes* rather than renames, and only handles the zip itself plus `.tmp` files in `local_cache`, not the checksums file:

```python
181def remove_zip(zipname: str, cfg: Config) -> None:
182    (cfg.dest / zipname).unlink(missing_ok=True)
183    if cfg.local_cache:
184        (cfg.local_cache / zipname).unlink(missing_ok=True)
185        (cfg.local_cache / (zipname + ".tmp")).unlink(missing_ok=True)
```

## 7. Structure of `run_archive` (archive.py:32-182) — where a new prompt would hook in

```
run_archive(ctx):
  32  cfg = ctx.cfg
  34  apps = glob /Applications/**/*.app (depth<=2), shuffled
  40  total = len(apps)
  44  for i, app in enumerate(apps, 1):        # main per-app loop
  47      resolve Info.plist (native or WrappedBundle "mobile@")
  55      if no plist: print SKIPPING, continue
  58      name, version = plist values (fallbacks)
  61      zipname / checksumname / zipstem / versioned computed
  68      live symlink scan + handle_external_symlinks (may `continue`)
  73      dest_zip, dest_checksum = cfg.dest / zipname, cfg.dest / checksumname

  76      if dest_zip.exists():
  79          if dest_checksum.exists():
                  # branch A: checksum file exists — verify_checksum_file_contents()
                  # mismatch → tty_read [o]/[b]/[s] prompt (lines 97-109)
 111          else:
                  # branch B: checksum file MISSING — the one this task is about
                  # (lines 111-152, detailed in §1 above)
                  # mismatch → tty_read [o]/[b]/[s] prompt (lines 139-152)
 153          continue                          # <-- end of app iteration for "zip exists" case

 155      # No zip yet — branch C: fresh archive (lines 155-180)
 159      live_checksums = collect_app_manifest(...)
 161      archive_and_store_zip(...)
 164      write_checksums(...)
 168      post-archive verification of the new zip against live_checksums

 182  print_external_symlink_summary(ctx)
```

Both `continue` (line 153) and the loop's natural fall-through happen **per app**, inside the single `for i, app in enumerate(apps, 1):` loop — there is no separate "after all apps" pass where an old zip could be swapped out later; each app is fully handled (including any interactive prompting) before moving to the next `app` in the same iteration.

For a new "ask if we should swap them out" prompt in the `[b]oth` branch specifically: the natural hook point is **immediately after line 150** (`write_checksums(live_checksums, newcheck, ctx)`) in branch B (lines 144-150), and likewise after line 107 in branch A (lines 102-107) if the two branches are to behave consistently — i.e., right after both the old-pair checksums are written/preserved and the new zip+checksums pair (`newzip`/`newcheck`) has been fully created, but still within the same iteration of the `for i, app in enumerate(apps, 1):` loop, before it falls through to `continue` (line 153) or the loop's next iteration. This is where `name`, `version`, `mobile`, `zipname`, `checksumname`, `newzip`, `newcheck`, `suffix`, `cfg`, and `ctx` are all still in scope, which a "rename the old mismatched pair with a `~hash-missmatch~{timestamp}` suffix" prompt/action would need.

## 8. Existing tests

There is **no unit/pytest test suite for `archive_apps` itself**. The only `test*` path is `/Users/user/Documents/programming/Shell/archive_apps/test/`, which is not code — it's a **data sandbox** (its own nested git repo, `test/.git/...`) containing ~140 `*.checksums.txt` files (e.g. `Chrome.app@147.0.7727.138.checksums.txt`, `Xcode.app@15.4@broken.checksums.txt`) plus a `_checksum_index_.txt`. This looks like a real `--dest` directory used for manual/live testing of the tool against actual installed apps (not automated tests, no `.zip` files present in the listing, no test runner config). It gives no insight into automated testing patterns for the mismatch/`[b]oth` flow.

The only actual Python test files in the repo (`find ... -iname "*test*.py"`) live under `scripts/°base/tests/` — these belong to a completely separate toolset (`git_split`, `git_remote_fix`, `save_decision`, `tag_backup`, `permission_check`, `commit_style_lib`, `ai_settings_sync`, etc.) and have nothing to do with `archive_apps`'s archive/verify/checksum logic. There is no `test_archive.py`, `test_app_ops.py`, `test_verify.py`, or `conftest.py` anywhere under `archive_apps/` or at the repo root targeting this package. Any new tests for the mismatch/`[b]oth`/hash-mismatch-rename flow would need to be written from scratch, likely as new files under a new top-level test directory (distinct from the existing `test/` sandbox, whose name would collide) — worth flagging to the user/parent agent since `test/` already exists but is not a code-test directory, so naming needs to be chosen carefully to avoid confusion or path collision.