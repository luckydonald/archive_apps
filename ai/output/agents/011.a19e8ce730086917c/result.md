Now I have the complete picture. Here is the implementation plan.

## Implementation Plan

### 1. New helper function — `swap_hash_mismatch_pair`

**Location**: `archive_apps/app_ops.py`, immediately after `remove_zip` (line 181-185) and before `write_checksums` (line 188) — it belongs next to `remove_zip` since it's the same category of operation ("relocate a zip's on-disk footprint"), and it's used for the same "resolve a checksum mismatch" workflow as the surrounding functions.

**Signature**:
```python
def swap_hash_mismatch_pair(
    cfg: Config,
    zipname: str, checksumname: str,          # canonical names — currently stale content
    newzip: str, newcheck: str,                # timestamped names — currently live-matching content
    mismatch_zipname: str, mismatch_checkname: str,  # target tag names for the outgoing stale pair
) -> bool:
```
Returns `True` iff the swap fully completed; `False` (with an explanatory print) if it aborted or failed, in which case the on-disk layout must be left either fully unchanged or fully restored (see partial-failure story below) — never a silent half-swapped state.

**Why `cfg`, not `ctx`**: mirrors `remove_zip(zipname, cfg)` exactly — this is a pure filesystem-relocation operation with no need for `write_fail_menu`/interactive retry machinery (that's reserved for `safe_write`/`safe_mv`, which this deliberately does not use — see next point).

**Why `Path.rename`, not `safe_mv`**: `safe_mv` (`archive_apps/io.py:120-142`) is designed for "I just produced new content, verify it landed correctly" — it does `src.read_bytes().splitlines()` before the move and re-reads the destination after, comparing line counts. That's the right tool for `write_checksums` (new content) but wrong here: the files being moved are already-known-good, previously-archived files; we're relocating them, not writing/verifying new content. Using `safe_mv` on the zip would additionally be actively harmful — it reads the entire (potentially multi-GB) zip into memory to count `\n` bytes for a comparison that's meaningless on binary data. Plain `Path.rename` matches the existing precedent for exactly this kind of operation: `verify.py:107-109` already does `zip_path.rename(bak)` for its `.bak.zip` rename flow. Use `Path.rename` (not `shutil.move`) for both the zip and the checksums file — same directory, same filesystem, so `rename` is a single atomic syscall (a directory-entry update, not a data copy), and it's clearer intent than `shutil.move`.

**Critical collision-safety detail**: POSIX `rename()` (and therefore `Path.rename`) will *silently overwrite* an existing file at the destination — it does not raise. So this helper must explicitly `.exists()`-check every rename target *before* calling `.rename()`, rather than relying on `.rename()` to fail. This is different from `verify.py`'s `zip_path.rename(bak)`, which is safe only because `bak`'s timestamp suffix makes collisions practically impossible — our helper doesn't get that guarantee for free (a `~hash-mismatch~{suffix}` target could theoretically already exist if invoked twice in the same second, or if a previous swap failed and left it there) so it must check explicitly.

**Step-by-step body**:

```python
def swap_hash_mismatch_pair(
    cfg: Config,
    zipname: str, checksumname: str,
    newzip: str, newcheck: str,
    mismatch_zipname: str, mismatch_checkname: str,
) -> bool:
    dest = cfg.dest
    old_zip, old_check = dest / zipname, dest / checksumname
    new_zip, new_check = dest / newzip, dest / newcheck
    tag_zip, tag_check = dest / mismatch_zipname, dest / mismatch_checkname

    # Pre-flight: sources must exist, targets must not (never clobber).
    if not old_zip.exists() or not old_check.exists():
        print(f"  SWAP ABORTED ⚠️: canonical pair incomplete ({zipname})")
        return False
    if not new_zip.exists() or not new_check.exists():
        print(f"  SWAP ABORTED ⚠️: new pair incomplete ({newzip})")
        return False
    if tag_zip.exists() or tag_check.exists():
        print(f"  SWAP ABORTED ⚠️: target already exists ({mismatch_zipname})")
        return False

    # Phase A: move the stale canonical-named pair aside, out of the way.
    try:
        old_zip.rename(tag_zip)
    except Exception as e:
        print(f"  SWAP FAILED ⚠️: could not tag old zip: {e}")
        return False
    try:
        old_check.rename(tag_check)
    except Exception as e:
        print(f"  SWAP FAILED ⚠️: could not tag old checksums: {e}")
        try:
            tag_zip.rename(old_zip)  # roll back phase A
        except Exception:
            print(f"  ROLLBACK FAILED ⚠️: {mismatch_zipname} now holds the old zip; manual fix needed")
        return False

    # Phase B: promote the timestamped/live-matching pair to the canonical name.
    try:
        new_zip.rename(old_zip)
    except Exception as e:
        print(f"  SWAP FAILED ⚠️: could not promote new zip: {e}")
        _rollback_phase_a(tag_zip, tag_check, old_zip, old_check)
        return False
    try:
        new_check.rename(old_check)
    except Exception as e:
        print(f"  SWAP FAILED ⚠️: zip promoted but checksums promotion failed: {e}")
        try:
            old_zip.rename(new_zip)  # undo phase B zip promotion
            _rollback_phase_a(tag_zip, tag_check, old_zip, old_check)
        except Exception:
            print(f"  ROLLBACK FAILED ⚠️: layout inconsistent — inspect {zipname}, {newzip}, {mismatch_zipname} manually")
        return False

    if cfg.local_cache:
        (cfg.local_cache / zipname).unlink(missing_ok=True)
        (cfg.local_cache / (zipname + ".tmp")).unlink(missing_ok=True)

    return True
```

with a tiny module-private helper `_rollback_phase_a(tag_zip, tag_check, old_zip, old_check)` that does the two reverse renames wrapped in a single try/except, to avoid repeating that block. (The `cfg.local_cache` cleanup mirrors `remove_zip`'s defensive style — per the ground-truth note, `local_cache` never actually holds the finished canonical zip, so this is cheap insurance against stray leftovers, not a correctness requirement.)

**Partial-failure story** (this is the key design justification, worth stating explicitly in code comments):
- All four renames operate on the same directory/filesystem, so each individual `Path.rename` call is atomic (a single syscall) — there is no "half-written file" risk mid-rename.
- The pre-flight existence/collision checks make the four renames themselves extremely unlikely to fail (permission errors or a concurrent external modification are the only realistic causes at that point).
- If Phase A fails on the second rename, the first is rolled back immediately — full restoration.
- If Phase A fully succeeds but Phase B fails: worst case (rollback also fails) leaves the canonical name empty (`zipname`/`checksumname` don't exist), the stale pair safely preserved under the mismatch tag, and the live-matching pair still intact under its timestamped name — **no data is ever lost**. On the *next* crawl, `run_archive` will simply take the "No zip yet" branch (line 156) and re-archive fresh from the live app, since `dest_zip.exists()` is `False`. That's self-healing, if mildly wasteful (one redundant archive), and is an acceptable degraded outcome — not a corruption. This should be called out explicitly in a code comment so a future reader doesn't mistake it for a bug.

### 2. Shared filename helper (addresses plan item 4)

**Location**: `archive_apps/utils.py`, alongside `sanitize_temp_component`.

Two small additions, since the `~{suffix}` pattern is about to appear in 3 places (existing `newzip`/`newcheck` in both branches, plus the new `mismatch_zip`/`mismatch_check`) with zero existing abstraction:

```python
def now_suffix() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def tagged_names(name: str, mobile: str, version: str, tag: str) -> tuple[str, str]:
    stem = f"{name}.app@{mobile}{version}~{tag}"
    return f"{stem}.zip", f"{stem}.checksums.txt"
```

`utils.py` already imports `time` (line 7), so no new import needed there. In `archive.py`, replace the two inline `suffix = time.strftime(...)` + manual f-string pairs with:
```python
suffix = now_suffix()
newzip, newcheck = tagged_names(name, mobile, version, suffix)
```
and build the mismatch-tag pair with:
```python
mismatch_zip, mismatch_check = tagged_names(name, mobile, version, f"hash-mismatch~{suffix}")
```
which naturally produces `Telegram.app@12.7~hash-mismatch~20260602_032921.zip` as specified. This is optional-but-clearly-justified per the instructions (removes duplication that's about to triple), not over-engineering — it's two small pure functions, no new abstraction layers.

### 3. New shared prompt function in `archive.py`

Rather than duplicating the "ask to swap, then call the helper" logic in both branches A and B (which are otherwise near-identical, the exact bug pattern this fix is remedying), add one module-level function in `archive_apps/archive.py` itself, above `run_archive`:

```python
def _offer_hash_mismatch_swap(
    name: str, mobile: str, version: str,
    zipname: str, checksumname: str,
    newzip: str, newcheck: str,
    suffix: str, cfg,
) -> None:
    choice = tty_read(
        "  Swap in the new archive as the canonical version "
        "(old kept as ~hash-mismatch~)? [y/N]: ", "n",
    )
    if choice not in ("y", "Y"):
        return
    mismatch_zip, mismatch_check = tagged_names(name, mobile, version, f"hash-mismatch~{suffix}")
    if swap_hash_mismatch_pair(cfg, zipname, checksumname, newzip, newcheck, mismatch_zip, mismatch_check):
        print(f"  SWAPPED ✅: {zipname} is now the live-matching archive; old content kept as {mismatch_zip}")
    else:
        print("  SWAP SKIPPED: layout left unchanged")
```

**Prompt text/default**: `"  Swap in the new archive as the canonical version (old kept as ~hash-mismatch~)? [y/N]: "`, default `"n"`, matching `tty_read`'s existing convention where the default argument is always the non-destructive choice (`"s"` for skip in the two existing mismatch prompts, `"a"` for ignore in `unreadable_prompt`). This satisfies the headless/cron requirement: `tty_read` returns the default (`"n"`) on any failure to open `/dev/tty`, so unattended runs never trigger the swap.

**New imports needed in `archive.py`**:
- `from .app_ops import (..., swap_hash_mismatch_pair)` — add to the existing `app_ops` import block (line 8-11).
- `from .utils import fmt_size, now_suffix, sha256_text, tagged_names` — extend the existing `utils` import (line 14).
- `time` import (line 5) can be dropped from `archive.py` once both `time.strftime(...)` call sites are replaced by `now_suffix()` — check no other use of `time` remains in the file (a `grep -n "time\." archive_apps/archive.py` after editing should show none, and `time` import removed only if so).

### 4. Exact insertion points (line-anchored)

**Branch A** — insert the call at the end of the `elif choice in ("b", "B"):` block, i.e. right after the existing line 107 (`write_checksums(live_checksums, newcheck, ctx)`), still indented inside that `elif`, before the sibling `else:` at line 108:
```python
                    elif choice in ("b", "B"):
                        suffix = now_suffix()
                        newzip, newcheck = tagged_names(name, mobile, version, suffix)
                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem, ctx)
                        write_checksums(live_checksums, newcheck, ctx)
                        _offer_hash_mismatch_swap(name, mobile, version, zipname, checksumname, newzip, newcheck, suffix, cfg)
                    else:
```

**Branch B** — same pattern, inserted after the existing line 150 (`write_checksums(live_checksums, newcheck, ctx)`), before the sibling `else:` at line 151:
```python
                    elif choice in ("b", "B"):
                        write_checksums(zip_checksums, checksumname, ctx)
                        suffix = now_suffix()
                        newzip, newcheck = tagged_names(name, mobile, version, suffix)
                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem, ctx)
                        write_checksums(live_checksums, newcheck, ctx)
                        _offer_hash_mismatch_swap(name, mobile, version, zipname, checksumname, newzip, newcheck, suffix, cfg)
                    else:
```
Note branch B has one extra statement before the suffix line (`write_checksums(zip_checksums, checksumname, ctx)` — writing the *zip's own* checksums to the canonical name first) that doesn't exist in branch A; that line is unaffected by this fix and stays exactly where it is. The swap call goes after everything else in the `b` block in both cases, since the swap must only run once `newzip`/`newcheck` are fully written on disk (the helper's pre-flight check requires `new_zip.exists()`/`new_check.exists()`).

### 5. Scope of `suffix` (item 3 answer)

No plumbing is required in either branch. `suffix`, `newzip`, `newcheck`, `zipname`, `checksumname`, `name`, `mobile`, `version`, and `cfg` are all already lexically in scope at the point of insertion in both branches — the new call sites are just additional statements appended inside the existing `elif choice in ("b", "B"):` blocks, not a new scope. `cfg` itself is bound once at the top of `run_archive` (`cfg = ctx.cfg`, line 33) and is already in scope throughout the loop body.

### 6. Verification / testing

**No automated suite exists** for `archive_apps` (confirmed: `test/` is 173 real `.checksums.txt`/data files, not pytest; `pyproject.toml` has no `[tool.pytest.ini_options]` or pytest dependency; `scripts/°base/tests/` is for an unrelated toolset). Given that, the primary verification should be manual, with an optional minimal pytest addition only for the new pure-rename helper.

**Manual end-to-end exercise**:
1. Pick a small already-installed `.app` (e.g. something under a few MB) and a scratch `--dest` directory (e.g. `/private/tmp/claude-.../scratchpad/archive_test_dest`).
2. Run once normally to create a real canonical pair: `python -m archive_apps <scratchdest>` (or filter to just the one app if the tool supports narrowing — otherwise let it crawl and Ctrl-C after the target app is archived, or temporarily point `/Applications` glob... simplest: just let a full crawl happen once against the scratch dest since it's idempotent for already-archived apps).
3. Corrupt the checksum to simulate drift: `echo garbage >> "<scratchdest>/<App>.app@<version>.checksums.txt"` (or truncate/edit a hash) so the canonical checksums file no longer matches the live app — this exercises **branch A** (checksums file exists but content differs).
4. Re-run the tool interactively; at the mismatch prompt choose `b`; then at the new swap prompt choose `y`. Confirm via `ls` that:
   - The canonical `App.app@version.zip` / `.checksums.txt` now match the live app (re-run with everything unchanged afterward should show `VERIFIED ✅` with no prompt).
   - A `App.app@version~hash-mismatch~{suffix}.zip` / matching `.checksums.txt` pair exists holding the old content.
5. To exercise **branch B**, `rm` the canonical `.checksums.txt` only (leaving the zip whose *own* content still won't match a since-updated live app — trickiest to stage without a real app update; alternatively, take a zip from step 2, then modify a file inside the live `.app` bundle in a way that's reversible, e.g. touch/edit a non-critical resource, if safe to do so — or more simply, just accept that branches A and B share the identical swap code path via `_offer_hash_mismatch_swap`/`swap_hash_mismatch_pair`, so once branch A is verified end-to-end, branch B only needs a spot-check that the call site wiring (scope, argument order) is correct, not a full independent live-app mismatch scenario).
6. Test collision-safety: manually pre-create a file at the expected `~hash-mismatch~{suffix}` name before answering `y`, confirm the tool prints `SWAP ABORTED` and changes nothing else.
7. Test the default: at the swap prompt, just press Enter (or run non-interactively so `/dev/tty` isn't available) and confirm nothing is renamed — the `b` choice's existing (pre-fix) behavior is preserved untouched.

**Optional minimal pytest** (only if the user wants it — flag as optional, requires adding `pytest` as a dev dependency and a `tests/` directory + `[tool.pytest.ini_options]`/`testpaths` entry since neither exists):
- `tests/test_app_ops_swap.py`, using `tmp_path` to build a fake `Config(dest=tmp_path, local_cache=None, ...)` and touching 4 files (`old.zip`, `old.checksums.txt`, `new.zip`, `new.checksums.txt`) with distinguishable content (e.g. `b"OLD"` vs `b"NEW"`), then calling `swap_hash_mismatch_pair` directly and asserting:
  - Returns `True`; canonical-named files now contain `b"NEW"`; mismatch-tagged files now contain `b"OLD"`.
  - Collision case: pre-create the mismatch-tag target, assert `False` is returned and all 4 original files are byte-for-byte untouched.
  - Missing-source case: don't create `new.zip`, assert `False` and nothing renamed.
  - This is pure filesystem logic with no subprocess/network/`.app` dependency, so it's cheap and mockable — a reasonable, minimally-scoped addition that doesn't require standing up new test infrastructure beyond one file and one `pyproject.toml` stanza.

### 7. Out-of-scope note worth flagging to the user

`archive_apps.py` (the single-file fallback, lines ~1647 and ~1691) contains the identical bug pattern (same `[o]verwrite / [b]oth / [s]kip` prompt, same stale-canonical-name-left-behind issue). The task as specified scopes the fix to the package's `archive_apps/archive.py` only; mirroring the fix into the single-file fallback is a natural follow-up but was not requested and should be confirmed with the user separately before touching it.

### Critical Files for Implementation
- /Users/user/Documents/programming/Shell/archive_apps/archive_apps/archive.py
- /Users/user/Documents/programming/Shell/archive_apps/archive_apps/app_ops.py
- /Users/user/Documents/programming/Shell/archive_apps/archive_apps/utils.py
- /Users/user/Documents/programming/Shell/archive_apps/archive_apps/io.py
- /Users/user/Documents/programming/Shell/archive_apps/archive_apps/cli.py