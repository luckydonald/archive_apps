# Timeout + preset flags for the checksum-mismatch prompt

## Context

When `archive-apps` finds that an archived zip's checksum no longer matches the
live app, it stops and asks interactively:

```
[o]verwrite zip / [b]oth / [s]kip:
```

(`archive_apps/archive.py:116` and `:158`, both via `tty_read`). If `[b]oth` is
chosen, a second interactive prompt asks whether to swap the new archive in as
canonical (`_offer_hash_mismatch_swap`, `archive.py:32-48`, added in the most
recent commit).

Both prompts block forever on a plain `tty.readline()` (`io.py:13-20` — there is
no timeout mechanism anywhere in the codebase). The user runs this tool
periodically and unattended, and a single pending prompt currently stalls the
entire run indefinitely. The goal is to make unattended runs self-recovering
(time out to a safe default, then circle back once a human is actually
available) and to let a fully-unattended run configure its answers up front so
it never has to block at all.

Concretely:
1. Both prompts get a 60s timeout. On timeout, treat the answer as `skip` (or
   "don't swap") for now, but remember the app and retry it — blocking, no
   timeout — after every other app has been processed. This way one slow
   decision doesn't stall apps behind it, and nothing is silently dropped.
2. New keyword flags let the choices be preset up front, so a scheduled/cron
   run never has to prompt (and never times out) at all:
   - `--on-mismatch=overwrite|both|skip` presets the first prompt.
   - `--mismatch-swap=yes|no` presets the swap follow-up. Per user decision,
     this is **required** whenever `--on-mismatch=both` is set (there would
     otherwise be no way to answer the swap follow-up non-interactively), but
     can also be set independently to preset the swap answer for a live/
     interactive `[b]oth` choice without presetting the top-level choice.
3. The `[b]oth` label changes to `[b]oth (version previous)` to reflect what
   it now does (keep the previous zip as a separate versioned/tagged archive
   rather than silently overwriting it).

## Design

### `archive_apps/io.py`
Add a new function alongside `tty_read` (leave `tty_read` itself untouched —
`write_fail_menu` and `unreadable_prompt` keep using it as-is):

```python
import select

def tty_read_timeout(prompt: str, default: str, timeout: float) -> tuple[str, bool]:
    """Like tty_read, but gives up after `timeout` seconds. Returns (answer, timed_out)."""
    try:
        with open("/dev/tty") as tty:
            sys.stderr.write(prompt)
            sys.stderr.flush()
            ready, _, _ = select.select([tty], [], [], timeout)
            if not ready:
                sys.stderr.write("\n")
                return default, True
            return tty.readline().rstrip("\n") or default, False
    except Exception:
        return default, False
```

`select.select` on the already-open tty file object is the natural fit here
(the file is a real fd from `open("/dev/tty")`), and mirrors this codebase's
existing deadline/poll style used in `lock.py`'s `_mkdir_lock`.

### `archive_apps/cli.py`
- `Config` gains two fields:
  ```python
  on_mismatch: str | None       # None | "overwrite" | "both" | "skip"
  mismatch_swap: str | None     # None | "yes" | "no"
  ```
- `RunContext` gains two deferred-queue fields, plus two small task dataclasses
  (defined here since `RunContext` needs their type, and `archive.py` already
  imports `Config`/`RunContext` from `cli.py` — not the other way around):
  ```python
  @dataclass
  class MismatchTask:
      label: str
      app: Path
      name: str
      mobile: str
      version: str
      versioned: str
      zipname: str
      checksumname: str
      zipstem: str
      live_manifest_hash: str
      live_checksums: str
      zip_checksums: str | None   # set only when the checksum file didn't exist yet

  @dataclass
  class SwapTask:
      label: str
      name: str
      mobile: str
      version: str
      zipname: str
      checksumname: str
      newzip: str
      newcheck: str
      suffix: str
  ```
  ```python
  deferred_mismatches: list[MismatchTask] = field(default_factory=list)
  deferred_swaps: list[SwapTask] = field(default_factory=list)
  ```
- `parse_args()`: follow the existing `--external-symlink-policy=` pattern
  (plain string, validated against a fixed tuple, `sys.exit(1)` on bad value):
  ```python
  elif arg.startswith("--on-mismatch="):
      val = arg[len("--on-mismatch="):]
      if val not in ("overwrite", "both", "skip"):
          print(f"Error: unknown --on-mismatch value: {val}", file=sys.stderr)
          sys.exit(1)
      on_mismatch = val
  elif arg.startswith("--mismatch-swap="):
      val = arg[len("--mismatch-swap="):]
      if val not in ("yes", "no"):
          print(f"Error: unknown --mismatch-swap value: {val}", file=sys.stderr)
          sys.exit(1)
      mismatch_swap = val
  ```
  Post-loop validation, alongside the existing `--verify-zip` combo check:
  ```python
  if on_mismatch == "both" and mismatch_swap is None:
      print("Error: --on-mismatch=both requires --mismatch-swap=yes|no", file=sys.stderr)
      sys.exit(1)
  ```
  Add corresponding `-h` help lines next to the `--external-symlink-policy`
  entry.

### `archive_apps/archive.py`
- Add `MISMATCH_PROMPT_TIMEOUT_SECONDS = 60` near the top.
- Add a small helper that picks blocking vs timed reads:
  ```python
  def _prompt_with_optional_timeout(prompt, default, timeout):
      if timeout is None:
          return tty_read(prompt, default), False
      return tty_read_timeout(prompt, default, timeout)
  ```
- Rewrite `_offer_hash_mismatch_swap` to take `ctx` and a `timeout`, honor
  `cfg.mismatch_swap` when set (no prompt at all), and defer to
  `ctx.deferred_swaps` on timeout instead of just returning:
  ```python
  def _offer_hash_mismatch_swap(name, mobile, version, zipname, checksumname,
                                 newzip, newcheck, suffix, ctx, timeout) -> None:
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
              ctx.deferred_swaps.append(SwapTask(f"{name} {version}", name, mobile, version,
                                                  zipname, checksumname, newzip, newcheck, suffix))
              return
          do_swap = answer in ("y", "Y")
      if not do_swap:
          return
      mismatch_zip, mismatch_check = tagged_names(name, mobile, version, f"hash-mismatch~{suffix}")
      if swap_hash_mismatch_pair(cfg, zipname, checksumname, newzip, newcheck, mismatch_zip, mismatch_check):
          print(f"  SWAPPED ✅: {zipname} is now the live-matching archive; old content kept as {mismatch_zip}")
      else:
          print("  SWAP SKIPPED: layout left unchanged")
  ```
- Extract the duplicated `[o]/[b]/[s]` branch (currently inline at both
  `archive.py:116-128` and `:158-171`) into one `_resolve_mismatch(task,
  ctx, timeout)` function, using the label
  `"  [o]verwrite zip / [b]oth (version previous) / [s]kip: "`, honoring
  `cfg.on_mismatch` when set, and deferring to `ctx.deferred_mismatches` on
  timeout:
  ```python
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
          _offer_hash_mismatch_swap(task.name, task.mobile, task.version, task.zipname,
                                     task.checksumname, newzip, newcheck, suffix, ctx, timeout)
      else:
          print("  SKIPPED")
  ```
- Both call sites become (identical shape, `zip_checksums=None` at the first
  site, `zip_checksums=zip_checksums` at the second):
  ```python
  print("  MISMATCH ❌: archived checksum does not match current app")
  task = MismatchTask(
      label=f"{name} {version}", app=app, name=name, mobile=mobile, version=version,
      versioned=versioned, zipname=zipname, checksumname=checksumname, zipstem=zipstem,
      live_manifest_hash=live_manifest_hash, live_checksums=live_checksums, zip_checksums=None,
  )
  _resolve_mismatch(task, ctx, MISMATCH_PROMPT_TIMEOUT_SECONDS)
  ```
- After the main `for i, app in enumerate(apps, 1):` loop ends, before the
  existing `print_external_symlink_summary(ctx)` call, add the blocking
  retry pass:
  ```python
  if ctx.deferred_mismatches or ctx.deferred_swaps:
      n = len(ctx.deferred_mismatches) + len(ctx.deferred_swaps)
      print(f"\n{n} deferred prompt(s) from earlier timeouts — resolving now (will wait for input):")
      for task in ctx.deferred_mismatches:
          print(f"RESOLVING: {task.label}")
          _resolve_mismatch(task, ctx, timeout=None)
      for task in ctx.deferred_swaps:
          print(f"SWAP?: {task.label}")
          _offer_hash_mismatch_swap(task.name, task.mobile, task.version, task.zipname,
                                     task.checksumname, task.newzip, task.newcheck, task.suffix,
                                     ctx, timeout=None)
  ```
  `timeout=None` routes through `_prompt_with_optional_timeout` straight to
  the existing plain blocking `tty_read`, so `timed_out` is always `False`
  here — no risk of re-deferring into an infinite loop.

### Imports
- `archive.py` needs `tty_read_timeout` from `.io`, and `MismatchTask`,
  `SwapTask` from `.cli`.

## Out of scope (flagged, not touched)
- `archive_apps/__main__.py:59-61` calls `main()` unconditionally at module
  scope *and* again under `if __name__ == "__main__":` — a pre-existing
  double-invocation quirk unrelated to this change. Not touching it here;
  worth a separate fix if the user wants it.
- The third, prompt-less mismatch case at `archive.py:196-197` ("freshly
  created zip doesn't match the app it was just zipped from") has no
  interactive prompt today and isn't changed.
- No new flag for the timeout duration itself — the user asked specifically
  for "a minute", so it's a plain constant (`MISMATCH_PROMPT_TIMEOUT_SECONDS`
  in `archive.py`) rather than another flag.

## Verification
- `python -m py_compile archive_apps/*.py` (or just `./main.py --help`) to
  confirm nothing is syntactically broken and the new `--on-mismatch=` /
  `--mismatch-swap=` lines show up in `-h`.
- `./main.py --on-mismatch=both` (no `--mismatch-swap`) → should error out
  immediately with the "requires --mismatch-swap=yes|no" message, before
  touching `/Applications`.
- Manual end-to-end pass since there's no automated test suite for this path
  (confirmed — `test/` is just fixture `.checksums.txt` files, not a pytest
  suite): pick one already-archived app in a scratch destination directory,
  hand-edit its `.checksums.txt` to force a mismatch, then:
  - Run with no flags and let the first prompt sit unanswered for 60s →
    confirm it prints the timeout message, prints "SKIPPED"-equivalent
    behavior for that run, continues to other apps, then re-prompts
    (blocking) in the deferred-retry pass at the end.
  - Run with `--on-mismatch=overwrite` → confirm no prompt appears and the
    zip is overwritten immediately.
  - Run with `--on-mismatch=both --mismatch-swap=no` → confirm both prompts
    are skipped, a new tagged zip/checksum pair appears, and no swap happens.
  - Confirm the live prompt text now reads
    `[o]verwrite zip / [b]oth (version previous) / [s]kip:`.
