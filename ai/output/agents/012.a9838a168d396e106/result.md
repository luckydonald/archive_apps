I now have full detail. Here's the report.

## 1. `archive_apps/io.py` — `tty_read` and `write_fail_menu`

**`tty_read`** (io.py:13-20):
```python
def tty_read(prompt: str, default: str = "") -> str:
    try:
        with open("/dev/tty") as tty:
            sys.stderr.write(prompt)
            sys.stderr.flush()
            return tty.readline().rstrip("\n") or default
    except Exception:
        return default
```
- Signature: `(prompt: str, default: str = "") -> str`.
- Opens `/dev/tty` directly (bypasses redirected stdin), writes the prompt to `sys.stderr`, then does a **blocking** `tty.readline()`. No timeout mechanism at all — a plain blocking read. Any exception (e.g. no tty available) falls back to `default`.

**`write_fail_menu`** (io.py:23-81):
```python
def write_fail_menu(
    desc: str, content_or_src: str, orig_dst: Path, mode: str, ctx: RunContext,
) -> Path | None:
    cur_dst = orig_dst
    has_alternate = False
    tmp_fallback = Path("/tmp") / orig_dst.name

    while True:
        print(f"  WRITE ERROR: {desc}", file=sys.stderr)
        print("  [a] retry (default)", file=sys.stderr)
        if has_alternate:
            print(f"  [a'] retry original path ({orig_dst})", file=sys.stderr)
        print("  [b] save somewhere else", file=sys.stderr)
        print("  [c] skip (try /tmp, else print)", file=sys.stderr)
        print("  [d] exit", file=sys.stderr)
        choice = tty_read("  Choice [a]: ", "c")
        choice = choice or "a"
        ...
```
(full body as read above, lines 23-81). This is unrelated to the checksum-mismatch menu — it's for write/mv failures — but it is the other example of a `tty_read`-driven menu loop in the codebase, useful as a style reference. It has no timeout either.

**The "[o]verwrite / [b]oth / [s]kip" menu text does not live in io.py at all** — it's inline in `archive.py` (see #2 below), not a separate rendering function. `write_fail_menu`'s own menu text is `[a]/[a']/[b]/[c]/[d]`, unrelated wording.

## 2. `archive_apps/app_ops.py` + `archive_apps/archive.py` — checksum-mismatch prompt

The mismatch prompt fires in **two places** inside `run_archive` (archive.py), both with the identical prompt string:

```python
choice = tty_read("  [o]verwrite zip / [b]oth / [s]kip: ", "s")
```
- archive.py:116 (checksum file exists but mismatches)
- archive.py:158 (checksum file was missing, rebuilt from zip, and that also mismatches)

Branch at archive.py:116-128 (checksum existed, mismatched):
```python
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
                        suffix = now_suffix()
                        newzip, newcheck = tagged_names(name, mobile, version, suffix)
                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem, ctx)
                        write_checksums(live_checksums, newcheck, ctx)
                        _offer_hash_mismatch_swap(name, mobile, version, zipname, checksumname, newzip, newcheck, suffix, cfg)
                    else:
                        print("  SKIPPED")
```

Branch at archive.py:157-171 (checksum file rebuilt from zip, then mismatched against live app) — structurally identical, `[b]` branch differs slightly (writes `zip_checksums` under the old canonical checksum name first, since none existed):
```python
                else:
                    print("  MISMATCH ❌: zip checksum does not match current app")
                    choice = tty_read("  [o]verwrite zip / [b]oth / [s]kip: ", "s")
                    if choice in ("o", "O"):
                        remove_zip(zipname, cfg)
                        archive_and_store_zip(app, versioned, zipname, live_manifest_hash, zipstem, ctx)
                        write_checksums(live_checksums, checksumname, ctx)
                    elif choice in ("b", "B"):
                        write_checksums(zip_checksums, checksumname, ctx)
                        suffix = now_suffix()
                        newzip, newcheck = tagged_names(name, mobile, version, suffix)
                        archive_and_store_zip(app, versioned, newzip, live_manifest_hash, zipstem, ctx)
                        write_checksums(live_checksums, newcheck, ctx)
                        _offer_hash_mismatch_swap(name, mobile, version, zipname, checksumname, newzip, newcheck, suffix, cfg)
                    else:
                        print("  SKIPPED")
```

Note: `choice == "s"` (or anything not `o/O/b/B`) falls into the `else: print("  SKIPPED")` — this is the branch that a timeout should also hit, i.e. timeout-default should route through the same `else` (or explicitly through `"s"`).

**The swap-prompt** added in commit `9258b9a` — `_offer_hash_mismatch_swap` (archive.py:32-48):
```python
def _offer_hash_mismatch_swap(
    name: str, mobile: str, version: str,
    zipname: str, checksumname: str,
    newzip: str, newcheck: str,
    suffix: str, cfg: Config,
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
This is called only from inside the `[b]oth` branch, after writing both the new tagged zip/checksums pair. It defaults to `"n"` (non-destructive default, matching codebase convention noted in the commit message).

`swap_hash_mismatch_pair` itself lives in app_ops.py:195-252 (shown in full above) — a pre-checked, collision-safe rename-based swap with rollback on partial failure.

Note on naming inconsistency to be aware of: this function is called `_offer_hash_mismatch_swap` but is actually defined/used in `archive.py`, not `app_ops.py`; `app_ops.py` only has the lower-level `swap_hash_mismatch_pair` rename logic. (User's item 2 asked to check app_ops.py — the branching/prompt logic itself is entirely in `archive.py`; app_ops.py only supplies the rename primitive.)

## 3. `archive_apps/archive.py` — `run_archive` main loop; no queue/deferred concept exists

Loop structure (archive.py:63 onward):
```python
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
    ...
    continue   # (several early-exit points via `continue`)
```

It's a plain `for i, app in enumerate(apps, 1)` loop over a pre-shuffled, pre-globbed list (`apps`) built once up front (archive.py:53-57). There is **no** queue, deferred list, retry-list, or "process again at end" concept anywhere in the codebase:

- Searched `queue|defer|process again|requeue|re-queue|retry_list|pending` across all of `archive_apps/*.py` — **zero matches**.
- `continue` statements (e.g. archive.py:75, 90, 106, 137, 146, 172, 192) are used purely to skip an app for the remainder of the current run — nothing accumulates them into a list for a later re-pass.
- `__main__.py` just calls `run_archive(ctx)` once; no outer retry loop either.

So a "timeout-to-skip with re-queueing" feature would be new territory: you'd need to introduce something like a `deferred: list[Path]` collected during the main `for` loop, then a second pass after it (or append `app` back to `apps`/a local list and extend the loop, since `enumerate` over a static list won't naturally support append-and-continue — you'd likely switch to a `while` loop over an explicit queue, or do `apps.append(app)` if iterating destructively via `.pop(0)`).

## 4. `archive_apps/cli.py` — `Config` dataclass and `parse_args()`

**`Config`** (cli.py:8-16):
```python
@dataclass
class Config:
    dest: Path
    local_cache: Path | None
    verify_mode: str            # "none" | "zips" | "new" | "changed"
    verify_zip_arg: str         # "" or the --verify-zip= value
    verify_abort: bool
    keep_temp: bool
    external_symlink_policy: str   # "archive" | "skip" | "abort"
```

**`RunContext`** (cli.py:19-25), for completeness since it's passed everywhere alongside `Config`:
```python
@dataclass
class RunContext:
    cfg: Config
    preserve_tmps: list[Path] = field(default_factory=list)
    verify_failure_summary: list[tuple[str, str]] = field(default_factory=list)
    external_symlink_summary: list[str] = field(default_factory=list)
    index_scratch: Path | None = None  # this run's private checksum-index scratch file, if any
```

**Existing flags** (all parsed manually in a `while i < len(argv)` loop, cli.py:28-93; no argparse):
- `-h` / `--help`
- `--verify-zip=APP` (value required; bare `--verify-zip` errors)
- `--verify-zips`
- `--verify-new`
- `--verify-changed`
- `--verify-abort`
- `--keep-temp`
- `--local-cache`, `--local-cache=`, `--local-cache=default`, `--local-cache=none`, `--local-cache=<path>`
- `--external-symlink-policy=archive|skip|abort` (validated against a fixed enum, errors on unknown value)
- positional `destination` argument (unprefixed arg → `dest_arg`)

**Naming convention**: `--verb-noun` or `--noun-verb`, kebab-case, boolean flags are bare (`--verify-abort`, `--keep-temp`), and enum-valued flags use `--flag=value` with validation against an explicit tuple (see `--external-symlink-policy=`). This is the closest existing precedent for a new `--on-mismatch=...`/`--mismatch-policy=...`-style flag.

**No existing flag presets a mismatch resolution.** There is no `--on-mismatch`, `--mismatch-policy`, `--non-interactive`, `--yes`, `--assume-*`, or similar "skip the interactive prompt" flag anywhere in `cli.py` or used elsewhere via `tty_read` defaults. The only "non-interactive default" pattern in the codebase is `tty_read`'s own `default` parameter, which is used when `/dev/tty` is unavailable (e.g., non-interactive stdin) — there's no CLI flag to override that default value; the default is hardcoded per call-site (`"s"` for the o/b/s menu, `"n"` for the swap-confirmation, `"c"` for write_fail_menu, `"a"` for unreadable_prompt).

## 5. `select.select` / `signal.alarm` / other timeout-capable input mechanisms

Searched `progress.py`, `io.py`, and the whole `archive_apps/*.py` tree for `select\.select|signal\.alarm|SIGALRM|timeout`:

- **`io.py`**: no matches at all — `tty_read` is a plain blocking `readline()` with no timeout support of any kind.
- **`progress.py`**: no matches — it only does `time.time()`-based ETA math for the progress bar rendering; no terminal-input handling at all.
- The only hit anywhere in the codebase is the word "timeout" appearing in a **docstring comment** in `lock.py:9` ("staleness timeout instead of relying on the OS...") and the numeric constants `STALE_SECONDS = 5 * 60` / `ACQUIRE_TIMEOUT = 60` / `POLL_INTERVAL = 1` (lock.py:26-28) used in `_mkdir_lock`'s polling loop (lock.py:88-110) — this is a lock-acquisition polling timeout using `time.monotonic()` deadlines and `time.sleep(POLL_INTERVAL)`, not a terminal-input timeout, but it is the one place in the codebase that demonstrates the project's style for implementing a deadline/timeout loop (poll with `time.monotonic()` and compare against a deadline, sleeping between checks).
- `__main__.py` imports `signal` (line 4) but only for `signal.SIGINT`/`signal.SIGTERM` handlers (`main()`, lines 49-50) — not `SIGALRM`, and not for timeouts.

**Conclusion**: there is no existing timeout-capable read primitive in this codebase (no `select.select` on the tty fd, no `signal.alarm`/`SIGALRM` handler installed anywhere). A 60s-timeout-to-skip on `tty_read`'s blocking `tty.readline()` would need to be built from scratch — most straightforwardly via `select.select([tty], [], [], 60)` before calling `tty.readline()` inside `tty_read` (io.py:13-20), since the tty file object is already opened there and `select` composes cleanly with a raw file descriptor without needing signal-based interruption of a blocking read.