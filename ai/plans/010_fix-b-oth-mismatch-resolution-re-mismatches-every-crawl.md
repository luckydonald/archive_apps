# Fix: `[b]oth` mismatch resolution re-mismatches every crawl

## Context

`archive_apps/archive.py` (`run_archive`) has two near-identical checksum-mismatch
code paths, each offering `[o]verwrite / [b]oth / [s]kip`:

- **Branch A** (~line 79-109): the `.checksums.txt` already exists but its content
  doesn't match the live app.
- **Branch B** (~line 111-152): the `.checksums.txt` is missing, gets rebuilt from
  the zip's own contents, and *that* doesn't match the live app.

In both, choosing `[b]oth` writes a new zip+checksums pair that matches the live
app under a `~{timestamp}` suffixed name, but leaves the **canonical-named** pair
(`{name}.app@{mobile}{version}.zip` / `.checksums.txt`) pointing at the old,
stale content. If the live app doesn't change again before the next crawl, the
canonical pair still won't match it — the exact same `MISMATCH ❌` prompt fires
again, every run, forever.

The fix: after `[b]oth` finishes writing the new (live-matching) pair, ask the
user whether to **swap** — promote the new pair to the canonical name, and tag
the outgoing stale pair with `~hash-mismatch~{timestamp}`, e.g.
`Telegram.app@12.7~hash-mismatch~20260602_032921.zip`. Declining (or running
headless, where `tty_read` can't open `/dev/tty`) leaves today's `[b]oth`
behavior completely unchanged — this is purely additive.

Confirmed with the user:
- Applies to **both** branch A and branch B (same bug, same fix, for consistency).
- Tag spelling is **`hash-mismatch`** (standard spelling; the user's own example
  had a typo, "missmatch").

## Approach

### 1. `archive_apps/utils.py` — small shared helpers

`time` is already imported. Add near `sanitize_temp_component`:

```python
def now_suffix() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def tagged_names(name: str, mobile: str, version: str, tag: str) -> tuple[str, str]:
    stem = f"{name}.app@{mobile}{version}~{tag}"
    return f"{stem}.zip", f"{stem}.checksums.txt"
```

This replaces the duplicated inline `time.strftime("%Y%m%d_%H%M%S")` +
hand-built f-strings currently at `archive.py:103-105` and `archive.py:146-148`,
and is reused for the new `~hash-mismatch~{suffix}` tag too (three call sites
total instead of two hand-rolled ones).

### 2. `archive_apps/app_ops.py` — `swap_hash_mismatch_pair`

Add right after `remove_zip` (line 181-185), same category ("relocate a zip's
on-disk footprint"):

```python
def swap_hash_mismatch_pair(
    cfg: Config,
    zipname: str, checksumname: str,          # canonical names — currently stale
    newzip: str, newcheck: str,                # timestamped — currently live-matching
    mismatch_zipname: str, mismatch_checkname: str,  # tag names for the outgoing stale pair
) -> bool:
```

Behavior:
- Pre-flight: both source pairs must exist; none of the three tag/target paths
  may already exist. Abort (print, return `False`, touch nothing) otherwise —
  **`Path.rename` silently overwrites on POSIX**, so this check is load-bearing,
  not optional.
- Use plain `Path.rename` (not `safe_mv`) for all four moves — `safe_mv`
  (`io.py:120-142`) reads the whole source file into memory to verify a
  line-count readback, which is right for freshly-written text but wrong here:
  these are already-known-good files being relocated, and the zip in
  particular can be large binary data. `Path.rename` on the same filesystem is
  a single atomic syscall — matches the existing precedent in
  `verify.py:107-109` (`zip_path.rename(bak)`).
- Order: move old zip → tag name, then old checksums → tag name (rolling back
  the first if the second fails), then new zip → canonical name, then new
  checksums → canonical name (rolling back everything if either fails). Every
  rename is atomic and pre-flight-checked, so failures here should be rare
  (permissions / concurrent external change); if a late rename fails and
  rollback also fails, the degraded-but-safe outcome is: canonical name absent,
  old pair preserved under its tag, new pair preserved under its timestamp name
  — no data lost, and the next crawl just re-archives fresh (`dest_zip.exists()`
  is `False` → "No zip yet" branch). Document that outcome in a comment so it's
  not mistaken for a bug later.
- Mirror `remove_zip`'s defensive `cfg.local_cache` cleanup for stray
  `zipname`/`zipname.tmp` leftovers (cheap insurance; `local_cache` is only
  ever a staging area per `archive_and_store_zip`, never holds the finished
  canonical zip).

### 3. `archive_apps/archive.py` — prompt + wiring

Add one module-level helper above `run_archive`:

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

Default `"n"` matches this codebase's existing convention (`tty_read`'s
`default` arg is always the non-destructive choice — `"s"` for the two
existing mismatch prompts). `tty_read` already returns the default when
`/dev/tty` can't be opened, so headless/cron runs never trigger a swap.

Wire into both `[b]oth` blocks, replacing the inline suffix/name construction
and appending the swap offer as the last statement in each `elif` (both
branches already have every needed variable — `name`, `mobile`, `version`,
`zipname`, `checksumname`, `cfg` — in scope; no new plumbing required):

**Branch A** (`archive.py:102-107`):
```python
                    elif choice in ("b", "B"):
                        suffix = now_suffix()
                        newzip, newcheck = tagged_names(name, mobile, version, suffix)
                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem, ctx)
                        write_checksums(live_checksums, newcheck, ctx)
                        _offer_hash_mismatch_swap(name, mobile, version, zipname, checksumname, newzip, newcheck, suffix, cfg)
```

**Branch B** (`archive.py:144-150`) — identical addition after the existing
`write_checksums(live_checksums, newcheck, ctx)`, keeping the branch's extra
leading `write_checksums(zip_checksums, checksumname, ctx)` line untouched:
```python
                    elif choice in ("b", "B"):
                        write_checksums(zip_checksums, checksumname, ctx)
                        suffix = now_suffix()
                        newzip, newcheck = tagged_names(name, mobile, version, suffix)
                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem, ctx)
                        write_checksums(live_checksums, newcheck, ctx)
                        _offer_hash_mismatch_swap(name, mobile, version, zipname, checksumname, newzip, newcheck, suffix, cfg)
```

Imports to update in `archive.py`:
- `from .app_ops import (..., swap_hash_mismatch_pair)`
- `from .utils import fmt_size, now_suffix, sha256_text, tagged_names`
- Drop the top-level `import time` once both inline `time.strftime(...)` call
  sites are replaced (confirm no other `time.` usage remains in the file first).

### Out of scope (flagged, not part of this change)

`archive_apps.py` (the single-file fallback) has the identical bug pattern at
its own `[b]oth` branches. Not touched here — worth a separate follow-up if
wanted, since CLAUDE.md says both implementations should stay behaviorally
identical.

## Verification

No automated test suite exists for `archive_apps` today (`test/` is a real
data/checksums sandbox, not pytest). Verify manually:

1. Point `--local-cache=none` at a scratch `--dest` dir; run once normally
   against a small real installed `.app` to produce a real canonical pair.
2. Corrupt the canonical `.checksums.txt` (edit/append garbage) to force a
   mismatch — exercises **branch A**.
3. Re-run interactively: choose `b` at the mismatch prompt, then `y` at the
   new swap prompt. Confirm via `ls`: canonical pair now matches the live app
   (a follow-up run shows `VERIFIED ✅`, no prompt), and a
   `{App}.app@{version}~hash-mismatch~{timestamp}.zip` / `.checksums.txt` pair
   holds the old content.
4. Re-run the same scenario answering `N` (or pressing Enter) at the swap
   prompt — confirm layout is identical to today's pre-fix `[b]oth` behavior
   (canonical pair still stale, only the timestamped pair added).
5. Collision guard: pre-create a file at the expected `~hash-mismatch~{suffix}`
   path before answering `y`; confirm `SWAP ABORTED` and nothing changes.
6. Spot-check **branch B** wiring (delete just the canonical `.checksums.txt`
   so it's rebuilt-from-zip-and-mismatches) — same call path as branch A via
   `_offer_hash_mismatch_swap`/`swap_hash_mismatch_pair`, so this is mainly a
   scope/argument-order check, not a full independent scenario.

### Critical files
- `archive_apps/archive.py`
- `archive_apps/app_ops.py`
- `archive_apps/utils.py`
