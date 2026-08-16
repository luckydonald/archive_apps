# Fix lost progress in `_checksum_index_.txt` under concurrent runs

## Context

`_checksum_index_.txt` is written only by the `--verify-zips` / `--verify-new` /
`--verify-changed` code path (`run_verify_all`, or the equivalent block in the
shell script). During a run, verified `(hash, filename)` pairs are appended to
a **fixed-name** scratch file, `_checksum_index_.txt.tmp`, in the destination
directory. At the end of the run (or in the exit/cleanup trap), that scratch
file is sorted and swapped in for the real index via a rename.

This breaks under concurrency in three independent ways, confirmed by reading
all three implementations (`archive_apps.sh`, `archive_apps.py`,
`archive_apps/{__main__.py,verify.py}`):

1. **The scratch filename is shared, not per-run.** Two concurrent
   `--verify-*` invocations append to the *same* `_checksum_index_.txt.tmp`.
   Worse, each run truncates it at startup (`: > index_tmp` /
   `index_tmp.write_text("")`), so a second run starting while a first is
   still in progress wipes out everything the first has appended so far.

2. **The exit/cleanup trap is unconditional, even for plain archive runs.**
   `cleanup()` (shell) / `_make_cleanup()` (Python package) / `_cleanup()`
   (single-file Python) all check `if index_tmp.exists()` with no regard for
   whether *this* process is the one that created it. A concurrent plain
   backup run (verify_mode "none") that exits while a `--verify-*` run is
   mid-flight will grab the other run's in-progress scratch file, sort it,
   and in the single-file Python version **delete it outright without ever
   merging it into the real index** — silently discarding that run's
   progress. The shell version at least folds it into the index, but still
   steals/removes a file it doesn't own.

3. **The final swap is a blind overwrite, not a merge.** Every run's
   finishing move is "sort my scratch file, rename it over `index_file`" —
   there is no read-modify-write against the index's *current* contents. If
   run A finishes and writes the index, then run B (which started earlier and
   only saw the index as it was before A ran) finishes and writes its own
   version, run B's write clobbers everything A added. Backup-and-rename
   makes each individual write atomic, but does nothing to prevent this
   lost-update race between writers — which is why the user's earlier
   backup/rename attempt didn't fix it.

The fix needs two things, matching what the user asked for: (a) make
appending new items safe under concurrency, and (b) make the final
sort/write into the shared index atomic *and* non-destructive to concurrent
writers. Both are solved by the same mechanism: give each run a private,
uniquely-named scratch file (so appends need no locking at all — only one
process ever writes to it), and gate every read-modify-write of the shared
`_checksum_index_.txt` behind an OS-level file lock that also does a proper
key-based merge instead of a blind overwrite.

macOS ships `/usr/bin/lockf` (BSD `flock(2)`-based; confirmed present and
working) for the shell script, and Python's `fcntl.flock` for the two Python
implementations. Both release automatically on process death (including
`SIGKILL`), so no stale-lock cleanup logic is needed — this is why lockf/flock
was chosen over a hand-rolled `mkdir`/pidfile lock.

## Design

### Per-run scratch file (no lock needed for appends)

Each `--verify-*` run creates its own scratch file via `mktemp` under a
`_checksum_index_.XXXXXX.tmp` pattern (the shell script already uses this
exact pattern in one place — reuse it as the *primary* scratch file, not just
for the interactive-recovery path). Only this process ever writes to it, so
plain `safe_append` (existing helper, unchanged) is sufficient — no locking
required for individual appends.

A plain archive-only run (verify_mode "none") never creates a scratch file at
all, and its cleanup must not touch anyone else's `_checksum_index_.*.tmp`
files. Track "do I own a scratch file" explicitly (a shell variable /
`RunContext.index_scratch: Path | None` / a module-level global), and gate
cleanup on that instead of on file existence.

### Locked, key-based merge (atomic "final reorder")

One function does all merging: `_merge_checksum_index <scratch_file>` (shell)
/ `merge_checksum_index(scratch_file, ctx)` (Python, added to `verify.py` and
mirrored in `archive_apps.py`). It:

1. Acquires the lock: `lockf -k -w "$dest/_checksum_index_.lock" bash -c '...' -- "$index_file" "$scratch_file"` in shell; `open(lockfile, "a")` +
   `fcntl.flock(fd, fcntl.LOCK_EX)` in Python.
2. While holding the lock, reads the **current** `index_file` (if present)
   and the scratch file, and merges them keyed by filename — not `sort -u`
   over whole lines (which only dedupes exact-identical lines) but a real
   "last write wins per key" merge, with the scratch file's entries always
   winning ties (they're this run's fresh computation). Key extraction must
   split on the first two-space run only (`hash<SP><SP>filename`), the same
   convention the code already uses for `grep -F "  $name"` lookups —
   splitting on whitespace/`$2` alone would break for app names containing
   spaces (e.g. "Google Chrome.app@…").
   - Shell: `awk '{line=$0; key=line; sub(/^[^ ]+  /, "", key); val[key]=line} END{for (k in val) print val[k]}' "$index_file" "$scratch_file" | sort -k2`
     (only pass `$index_file` if it exists).
   - Python: build a `dict` keyed by the substring after the first `"  "`,
     populate from `index_file` lines then `scratch_file` lines (scratch
     wins), sort by key, join back into `"hash  name"` lines.
3. Writes the merged result to a fresh `mktemp` file and renames it onto
   `index_file` (still inside the locked section, so no other writer can
   interleave between merge and rename).
4. Reports what changed: number of lines added vs. updated vs. unchanged
   (diff old index vs. new), so a normal run's existing
   `INDEX: written → …` message gains a short delta summary.

This function is called from exactly two places per run: at the normal end of
`run_verify_all` (replacing today's blind sort+rename), and from the
cleanup/exit trap as a fallback for interrupted runs (merging whatever this
run's own scratch file has accumulated so far). Because the merge is
idempotent and lock-protected, calling it twice (once normally, once again in
the trap if the scratch file is already gone) is harmless — the trap simply
finds nothing to do.

### Startup recovery of orphaned scratch files — auto-merge, verbose

Per the user's direction: no interactive prompts. At the start of a
`--verify-*` run, glob for any leftover `_checksum_index_.*.tmp` files (from
a prior run that was killed before its own exit trap ran) *other than the one
this run is about to create*. For each one found:

1. Print `RECOVERY: found leftover scratch file <name> (<N> lines)`.
2. `cat` its full contents to the terminal, so the user can see exactly
   what's about to be folded in before it disappears.
3. Run it through the same `_merge_checksum_index` function.
4. Print the merge delta (added/updated/unchanged counts), then `cat` the
   resulting `index_file` section that changed (or the full merged lines
   touched) so there's a visible record.
5. Delete the scratch file (keep it if `--keep-temp`).

This replaces the current three-question interactive flow in all three
implementations.

## Files to change

- **`archive_apps.sh`**
  - `cleanup()` (lines 85–105): stop touching a fixed `_checksum_index_.txt.tmp`
    path. Only act if this run set an `index_scratch` variable, and route
    through `_merge_checksum_index`.
  - New function `_merge_checksum_index` near `safe_append`/`safe_write`/`safe_mv`
    (~line 474), implementing the lockf + awk merge above.
  - Verify-mode block (~lines 1108–1258): replace the fixed `index_tmp` /
    interactive-recovery block with: (a) auto-merge-and-report any orphaned
    `_checksum_index_.*.tmp` at startup, (b) `mktemp` a private scratch file
    for this run, (c) keep the existing per-zip `safe_append` calls unchanged
    (now targeting the private scratch), (d) replace the final
    `sort -k2 ... ; safe_mv ...` with a call to `_merge_checksum_index`.
  - `--verify-zip` path (lines 1060–1106) is untouched — it never reads/writes
    the index.

- **`archive_apps.py`** (single-file fallback) — mirror the same changes:
  `_cleanup()` (~line 467), a new `merge_checksum_index()` next to
  `safe_append`/`safe_write`/`safe_mv`, and the verify-all block (~lines
  1198–1371). Use `fcntl.flock` for the lock.

- **`archive_apps/cli.py`** — add `index_scratch: Path | None = None` to
  `RunContext` so `__main__.py`'s cleanup and `verify.py`'s `run_verify_all`
  share the same handle.
- **`archive_apps/verify.py`** — `run_verify_all` (lines 190–343): same
  restructuring as the shell block; add `merge_checksum_index()` here (it's
  the natural home, next to the other index logic) and import it from
  `__main__.py`.
- **`archive_apps/__main__.py`** — `_make_cleanup()` (lines 16–46): gate on
  `ctx.index_scratch` instead of the fixed path, and call
  `merge_checksum_index` on it as the fallback-for-interrupted-runs path.

No changes needed to `zip_ops.py`, `app_ops.py`, `archive.py`, `progress.py`,
`utils.py`, or the shell script's analogous sections — none of them touch the
checksum index.

## Verification

1. **Unit-level correctness of the merge**, run by hand for each
   implementation:
   - Create a fake `dest` dir with a couple of dummy `.zip` files (or just
     hand-craft `_checksum_index_.txt` plus two scratch files with
     overlapping and non-overlapping keys, including one filename containing
     a space) and invoke the merge function directly (source the function in
     bash / import it in Python — do **not** source the whole
     `archive_apps.sh`, per existing project convention) to confirm: union of
     keys, scratch wins on conflict, output sorted by filename, spaces in
     filenames don't corrupt keys.
2. **Concurrency reproduction**, in a scratch directory (not real
   `/Applications`/`/Users/Shared/App Versions`):
   - Launch two `--verify-new` runs back-to-back with real overlap (e.g. add
     an artificial `sleep` via `--keep-temp` timing, or just launch both at
     once against a dest with several zips) and confirm the resulting
     `_checksum_index_.txt` contains entries from both runs, not just the
     last one to finish.
   - Kill one run mid-flight (`kill -9`) after it has appended some entries,
     confirm the orphaned scratch file is picked up and auto-merged (with the
     verbose `cat` output) on the next `--verify-*` invocation.
   - Launch a plain archive run (no `--verify-*`) concurrently with a
     `--verify-*` run and confirm the archive run's exit does not touch or
     truncate the verify run's scratch file or the index.
3. Confirm all three implementations (`archive_apps.sh`, `archive_apps.py`,
   `archive_apps/`) produce byte-for-byte identical `_checksum_index_.txt`
   output for the same input scenario, per the project's "identical CLI"
   requirement.
