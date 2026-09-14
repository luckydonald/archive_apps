I now have everything needed. Here is the full report.

## 1. `archive_apps/cli.py` — `Config`, `RunContext`, `parse_args()`

File: `/Users/user/Documents/programming/Shell/archive_apps/archive_apps/cli.py`

**`Config` dataclass (lines 8-16):**
```python
8	@dataclass
9	class Config:
10	    dest: Path
11	    local_cache: Path | None
12	    verify_mode: str            # "none" | "zips" | "new" | "changed"
13	    verify_zip_arg: str         # "" or the --verify-zip= value
14	    verify_abort: bool
15	    keep_temp: bool
16	    external_symlink_policy: str   # "archive" | "skip" | "abort"
```

**`RunContext` dataclass (lines 19-25):**
```python
19	@dataclass
20	class RunContext:
21	    cfg: Config
22	    preserve_tmps: list[Path] = field(default_factory=list)
23	    verify_failure_summary: list[tuple[str, str]] = field(default_factory=list)
24	    external_symlink_summary: list[str] = field(default_factory=list)
25	    index_scratch: Path | None = None  # this run's private checksum-index scratch file, if any
```

**`parse_args(argv: list[str]) -> Config`** is a hand-rolled loop (NOT `argparse`), lines 28-122. Every flag, verbatim:

| Line(s) | Flag (long) | Short | Default | Help text (from `-h`) |
|---|---|---|---|---|
| 40, 41-59 | `-h` / `--help` | `-h` | n/a | prints full usage block, then `sys.exit(0)` |
| 61-63 | `--verify-zip` (bare, no `=`) | — | — | errors: `"Error: --verify-zip requires a value: --verify-zip=APP"` |
| 42-45, 64-65 | `--verify-zip=APP` | — | `verify_zip_arg = ""` | `"--verify-zip=APP  verify zip(s) for a specific app or exact zip file"` / `"                    APP forms: Xcode / Xcode.app / /Applications/Xcode.app"` / `"                              Xcode.app@15.4.zip / full/path/to/Foo.zip"` / `"                    matches all version zips for that app; exits after verifying"` |
| 46, 66-67 | `--verify-zips` | — | `verify_mode = "none"` | `"--verify-zips     extract and verify all zips against their checksum files"` |
| 47, 68-69 | `--verify-new` | — | (part of `verify_mode`) | `"--verify-new      verify only zips/checksums not yet in the checksum index"` |
| 48, 70-71 | `--verify-changed` | — | (part of `verify_mode`) | `"--verify-changed  verify zips whose index hash differs from current file"` |
| 49, 72-73 | `--verify-abort` | — | `verify_abort = False` | `"--verify-abort    stop immediately on the first verification failure"` |
| 50, 74-75 | `--keep-temp` | — | `keep_temp = False` | `"--keep-temp       preserve temp workdirs and leftover .tmp files for reuse"` |
| 51-55, 76-81 | `--local-cache[=path]` | — | `local_cache_arg = None` | `"--local-cache[=path]"` / `"                    stage new zips on local disk, then move to destination;"` / `"                    local temp is deleted after transfer (no copy retained)"` / `"                    path defaults to /Users/Shared/App Versions"` / `"                    magic values: default (same as omitting path), none (disable)"` |
| 56-58, 82-87 | `--external-symlink-policy=archive\|skip\|abort` | — | `external_symlink_policy = "archive"` | `"--external-symlink-policy=archive|skip|abort"` / `"                    handling for symlinks that resolve outside the app bundle"` / `"                    default: archive, with an end-of-run warning summary"` |
| 88-90 | any other `-*` | — | — | errors: `"Unknown option: {arg}"` |
| 59, 91-92 | positional `destination` | — | `dest_arg = ""` → `/Users/Shared/App Versions` | `"destination       archive directory (default: /Users/Shared/App Versions)"` |

Post-loop validation:
- Lines 95-100: `--verify-zip` cannot combine with `--verify-zips/--verify-new/--verify-changed` → error + exit(1).
- Lines 102-103: `dest` resolved and created (`mkdir(parents=True, exist_ok=True)`).
- Lines 105-112: `local_cache` resolved/created; errors if equal to `dest`.
- Lines 114-122: builds and returns the `Config`.

## 2. Config/RunContext flow into `archive.py` and `app_ops.py`

`Config` is **not** passed as individual fields — it's always threaded as a single object, either directly (`cfg: Config`) or wrapped inside `ctx: RunContext` (which holds `cfg` plus run-scoped mutable state). Call chain:

- `archive_apps/__main__.py:46`: `ctx = RunContext(cfg=cfg)` — the only place `Config` is wrapped into `RunContext`.
- `archive_apps/__main__.py:57`: `run_archive(ctx)`
- `archive_apps/archive.py:51`: `def run_archive(ctx: RunContext) -> None:` — receives whole `ctx`; line 52 does `cfg = ctx.cfg` to unpack when only config fields (not mutable run state) are needed for a given call.
- Inside `run_archive`, per-app work calls into `app_ops.py` functions, passing `ctx` (for functions needing progress/state) or `cfg` (for pure zip/checksum path helpers):
  - `archive_apps/archive.py:119` / `:124` / `:161` / `:167` / `:180`: `archive_and_store_zip(app, versioned, zipname, live_manifest_hash, zipstem, ctx)`
    - Signature: `archive_apps/app_ops.py:261-264`:
      ```python
      def archive_and_store_zip(
          app: Path, versioned: str, zipname: str,
          manifest_hash: str, archive_stem: str, ctx: RunContext,
      ) -> None:
      ```
  - `archive_apps/archive.py:120` / `:125` / `:153` / `:164` / `:168` / `:183`: `write_checksums(live_checksums/zip_checksums, checksumname, ctx)`
    - Signature: `archive_apps/app_ops.py:255`: `def write_checksums(content: str, checksumname: str, ctx: RunContext) -> None:`
  - `archive_apps/archive.py:118` / `:160`: `remove_zip(zipname, cfg)` — this one takes `cfg` directly, not `ctx`.
    - Signature: `archive_apps/app_ops.py:181`: `def remove_zip(zipname: str, cfg: Config) -> None:`
  - `archive_apps/archive.py:45` (inside `_offer_hash_mismatch_swap`, called from lines 126/169): `swap_hash_mismatch_pair(cfg, zipname, checksumname, newzip, newcheck, mismatch_zip, mismatch_check)` — also takes `cfg` directly.
    - Signature: `archive_apps/app_ops.py:195-200`:
      ```python
      def swap_hash_mismatch_pair(
          cfg: Config,
          zipname: str, checksumname: str,
          newzip: str, newcheck: str,
          mismatch_zipname: str, mismatch_checkname: str,
      ) -> bool:
      ```
  - `archive_apps/archive.py:195`: `delete_validated_workdir(zipstem, live_manifest_hash, ctx)` → `archive_apps/app_ops.py:175`: `def delete_validated_workdir(archive_stem: str, manifest_hash: str, ctx: RunContext) -> None:`
  - `archive_apps/app_ops.py:155` (`archive_app_to_zip`) and `:26` (`archive_workdir_path`) both accept `ctx`/`cfg` respectively and internally do `cfg = ctx.cfg` where needed (e.g. `archive_app_to_zip` line 155: `workdir = archive_workdir_path(archive_stem, manifest_hash, ctx.cfg)`).

**The mismatch-resolution prompt logic itself lives inline in `run_archive`**, not in a separate `app_ops.py` function — it's the `tty_read("  [o]verwrite zip / [b]oth / [s]kip: ", "s")` calls at `archive_apps/archive.py:116` and `:158`, each followed by an `if/elif/else` branch dispatching to `remove_zip`/`archive_and_store_zip`/`write_checksums`/`_offer_hash_mismatch_swap`. `_offer_hash_mismatch_swap` (lines 32-48) is the one small helper function that itself does a `tty_read` prompt and calls `swap_hash_mismatch_pair(cfg, ...)`.

Convention: single-field values (`cfg`) are threaded through only for the handful of low-level file-path helpers (`remove_zip`, `swap_hash_mismatch_pair`, `archive_workdir_path`) that don't need mutable run state; everything doing progress bars, temp-preservation bookkeeping, or verification-summary recording takes the full `ctx: RunContext` instead of unpacking individual `Config` fields as separate parameters.

## 3. Existing enum/keyword-style flags

This project does **not** use `argparse`, so there's no `choices=[...]` anywhere — grep for `choices=|Enum|Literal[` across `archive_apps/*.py` returned nothing. The established pattern for a fixed-set-of-strings flag is a **plain `str` field validated by a manual `if val not in (...)` check inside the parsing loop**, exemplified by `--external-symlink-policy`:

- Declared as `str` in `Config` with an inline comment documenting the legal values: `archive_apps/cli.py:16`: `external_symlink_policy: str   # "archive" | "skip" | "abort"`
- Validated at parse time, `archive_apps/cli.py:82-87`:
  ```python
  elif arg.startswith("--external-symlink-policy="):
      val = arg[len("--external-symlink-policy="):]
      if val not in ("archive", "skip", "abort"):
          print(f"Error: unknown --external-symlink-policy value: {val}", file=sys.stderr)
          sys.exit(1)
      external_symlink_policy = val
  ```
- No `Enum`/`Literal` typing is used downstream either — consumers just compare the raw string, e.g. `archive_apps/verify.py:54-60`:
  ```python
  if cfg.external_symlink_policy == "archive":
      return True
  elif cfg.external_symlink_policy == "skip":
      ...
  else:
      ...  # "abort"
  ```
- The same "no Enum" convention applies to `verify_mode` (`"none"|"zips"|"new"|"changed"`), which is set by separate boolean-like flags (`--verify-zips`, `--verify-new`, `--verify-changed`) rather than a single `--verify-mode=X` flag, and is likewise just compared as a raw string in `archive_apps/verify.py:327`, `:334`, `:349` and `archive_apps/__main__.py:54`.

A new keyword-style flag should follow the `--external-symlink-policy=` pattern: add a plain `str` field to `Config` with a comment enumerating legal values, validate with `if val not in (...)` at parse time in the `elif arg.startswith("--your-flag="):` branch, add a `-h` help line, and compare the raw string downstream — no Enum/Literal machinery exists to hook into.

## 4. `archive_apps/__main__.py` — RunContext construction and signal/atexit handling

Full relevant section, lines 16-61:
```python
16	def _make_cleanup(ctx: RunContext) -> Callable[[], None]:
17	    def _cleanup() -> None:
18	        cfg = ctx.cfg
19	        if ctx.index_scratch is not None:
20	            try:
21	                merge_checksum_index(ctx.index_scratch, ctx)
22	            except Exception:
23	                pass
24	
25	        if cfg.keep_temp:
26	            return
27	
28	        for f in cfg.dest.glob("*.zip.tmp"):
29	            f.unlink(missing_ok=True)
30	        for f in cfg.dest.glob("*.checksums.txt.tmp"):
31	            if f not in ctx.preserve_tmps:
32	                f.unlink(missing_ok=True)
33	        for d in cfg.dest.glob(".archive_apps.*"):
34	            if d.is_dir():
35	                rm_retry(d)
36	        # also clean up workdirs that were redirected to the system temp dir
37	        for d in Path(tempfile.gettempdir()).glob(".archive_apps.*"):
38	            if d.is_dir():
39	                rm_retry(d)
40	
41	    return _cleanup
42
43
44	def main(argv: list[str] | None = None) -> None:
45	    cfg = parse_args(argv if argv is not None else sys.argv[1:])
46	    ctx = RunContext(cfg=cfg)
47	
48	    atexit.register(_make_cleanup(ctx))
49	    for sig in (signal.SIGINT, signal.SIGTERM):
50	        signal.signal(sig, lambda s, f: sys.exit(1))
51	
52	    if cfg.verify_zip_arg:
53	        run_verify_zip(ctx)
54	    elif cfg.verify_mode != "none":
55	        run_verify_all(ctx)
56	    else:
57	        run_archive(ctx)
58	
59	main()
60	if __name__ == "__main__":
61	    main()
```
Key points for a "re-queue-at-end" feature:
- `RunContext` is built once at `__main__.py:46` right after `parse_args`, and is the single object threaded through every code path (`run_verify_zip` / `run_verify_all` / `run_archive`).
- `atexit.register(_make_cleanup(ctx))` (line 48) is registered **before** the dispatch to `run_archive`/etc., so `_cleanup` always runs last regardless of whether `main()` returns normally or `sys.exit()` is called from a signal handler (lines 49-50, both `SIGINT`/`SIGTERM` map to `sys.exit(1)`, which still triggers registered `atexit` callbacks).
- A re-queue-at-end hook has two natural insertion points:
  1. Directly in `run_archive` (`archive_apps/archive.py`) right after the per-app `for` loop, before `print_external_symlink_summary(ctx)` (line 201) — i.e., process any apps queued for retry using state stored on `ctx` (e.g. a new `ctx` list field appended to during the main loop when a mismatch prompt is deferred).
  2. Or as a step inside `_cleanup()` (lines 17-39) in `__main__.py`, using `ctx`'s existing fields — but note `_cleanup` currently only fires on process exit (normal or signal-interrupted) and already special-cases `cfg.keep_temp` to skip destructive cleanup; also note that if re-queueing needs a tty prompt, `_cleanup` still runs even after `Ctrl-C`, so prompting there could double-prompt or interact oddly with signal-interrupted state — the safer choice mirrors point 1 (end of `run_archive`'s loop, before the existing `print_external_symlink_summary(ctx)` call and before `main()` returns / atexit fires).
- Note `main()` currently has both an unconditional call `main()` at line 59 (module level, unguarded) and the `if __name__ == "__main__": main()` guard at lines 60-61 — this means `main()` runs twice if the module is executed as `__main__` directly (once unconditionally, once via the guard). This looks like a pre-existing bug/quirk worth flagging but is out of scope for the flag-adding task; worth double-checking with the user before touching `__main__.py` further, since a re-queue feature that hooks into `main()`'s flow would otherwise run twice too.

## 5. `test/` directory (untracked) and test patterns for mismatch-prompt logic

The untracked `test/` directory is **not** a Python test suite — there are no `test_*.py` files inside it, no pytest/unittest scaffolding, and no references to it from `pyproject.toml` (which only declares the `archive-apps` script entry point, no `[tool.pytest.ini_options]` or test deps).

Contents of `test/`:
- ~180 `*.checksums.txt` fixture files, one per sample app (e.g. `test/Xcode.app@15.4.checksums.txt`, `test/Claude.app@1.7196.0.checksums.txt`), including at least one deliberately-named "broken" variant: `test/Xcode.app@15.4@broken.checksums.txt`.
- `test/_checksum_index_.txt` — a fixture matching the checksum-index file format referenced in `archive_apps/verify.py` (`merge_checksum_index`, index_file usage around lines 315-349).
- `test/.git/` — its **own nested git repository** (separate from the parent repo), with its own history (`git -C test log --oneline`: `b2a080e update.`, `7e8ce52 oof`, `dc95fdc checksums`, `a34a546 init`) and no remote configured (`git -C test remote -v` returned nothing). This is why the parent repo's `git status` reports it as an untracked directory rather than tracked files — git treats a directory containing its own `.git` as a submodule-like boundary and won't descend into it.

Given this, there is **no existing automated test pattern in this repo** for the mismatch-prompt logic (the `tty_read("  [o]verwrite zip / [b]oth / [s]kip: ", "s")` branches in `archive_apps/archive.py:116` and `:158`, or `_offer_hash_mismatch_swap` at lines 32-48). `test/` appears to be a manually-curated fixture corpus of real-world `.checksums.txt` files (presumably for manually/ad-hoc exercising `run_verify_all`/`run_verify_zip` against realistic data, and possibly the nested `.git` history captures fixture-file edits over time to simulate mismatches), not something wired into any test runner. A future implementation adding a re-queue-at-end feature (or any new tested behavior) would need to introduce its own test scaffolding from scratch (e.g., a `tests/` dir with pytest, monkeypatching `tty_read` to script prompt responses, and possibly reusing files from `test/` as fixtures) — there is no pre-existing convention to follow here.