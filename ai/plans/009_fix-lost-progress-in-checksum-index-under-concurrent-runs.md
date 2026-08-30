# Fix lost progress in `_checksum_index_` under concurrent runs

## Context

`_checksum_index_.txt` is written only by the `--verify-zips` / `--verify-new`
/ `--verify-changed` code path (`run_verify_all` in the package, the
equivalent block in `archive_apps.py`). During a run, verified
`(hash, filename)` pairs are appended to a **fixed-name** scratch file,
`_checksum_index_.txt.tmp`, in the destination directory. At the end of the
run (or in the exit/cleanup trap), that scratch file is sorted and swapped in
for the real index via a rename.

This breaks under concurrency in three independent ways (confirmed by
reading `archive_apps.py` and `archive_apps/{__main__.py,verify.py}` — the
shell script `archive_apps.sh` has the identical bug but is being removed
rather than fixed, see Step 0):

1. **The scratch filename is shared, not per-run.** Two concurrent
   `--verify-*` invocations append to the *same* `_checksum_index_.txt.tmp`.
   Worse, each run truncates it at startup (`index_tmp.write_text("")`), so a
   second run starting while a first is still in progress wipes out
   everything the first has appended so far.
2. **The exit/cleanup trap is unconditional, even for plain archive runs.**
   `_make_cleanup()` (package) / `_cleanup()` (single-file) check
   `if index_tmp.exists()` with no regard for whether *this* process created
   it. A concurrent plain backup run (verify_mode "none") exiting while a
   `--verify-*` run is mid-flight grabs the other run's in-progress scratch
   file and — in the single-file version — **deletes it outright without
   ever merging it into the real index**, silently discarding that run's
   progress.
3. **The final swap is a blind overwrite, not a merge.** Every run's finish
   is "sort my scratch file, rename it over `index_file`" — no
   read-modify-write against the index's *current* contents. If run A
   finishes and writes the index, then run B (which started earlier, saw an
   older index) finishes and writes its own version, run B's write clobbers
   everything A added. Backup-and-rename makes each individual write atomic
   but does nothing to prevent this lost-update race, which is why the
   earlier backup/rename attempt didn't fix it.

The fix: give each run a private, uniquely-named scratch file (so appends
need no locking — only one process ever writes to it), and gate every
read-modify-write of the shared index behind a real lock that does a
key-based merge instead of a blind overwrite, plus keep a durable trail of
what changed (a history log of hash replacements, and timestamped snapshots
of the index itself) so nothing is silently lost even if the merge logic
itself ever has a bug.

## Step 0 — remove `archive_apps.sh` (separate commit)

`archive_apps.py` is the future; the shell script is being retired rather
than fixed. As its own commit, before the index-fix work:

- Delete `archive_apps.sh`.
- Update `CLAUDE.md`: drop the "Running the script" section and the
  `archive_apps.sh` column/mentions in "Architecture / logic flow" and
  "Naming conventions" (those sections describe behavior shared with the
  Python versions, so keep the prose, just stop citing the shell script as a
  parallel implementation). Leave the `*.bak.sh` files alone — CLAUDE.md
  already protects those ("do not delete without user confirmation") and
  that hasn't been given.

The index-fix work below only touches `archive_apps.py` and the
`archive_apps/` package.

## Design

### Per-run scratch file (no lock needed for appends)

Each `--verify-*` run creates its own scratch file via `mktemp`-equivalent
(`tempfile.mkstemp`, already used for the interactive-recovery path — reuse
it as the *primary* scratch file for the whole run, not just recovery). Only
this process ever writes to it, so the existing `safe_append` helper is
sufficient — no locking required for individual appends.

A plain archive-only run (verify_mode "none") never creates a scratch file,
and its cleanup must not touch anyone else's `_checksum_index_.*.tmp` files.
Track "do I own a scratch file" explicitly via a new
`RunContext.index_scratch: Path | None` field (package) / a module-level
global (single-file), and gate cleanup on that instead of on file existence.

### Locking: hybrid, chosen by destination filesystem type

The destination can be local disk or a NAS mounted over Samba/SMB. `flock`-
style byte-range locks depend on the SMB client/server correctly
implementing them — some configurations silently no-op rather than erroring,
which would defeat the whole scheme with no visible failure. `mkdir` (used
as a mutex: atomic create-or-fail) is reliably atomic on essentially any
filesystem, local or network, since directory-creation atomicity is far more
universally implemented than byte-range locking — the tradeoff is it doesn't
auto-release on a killed process, so it needs a staleness timeout instead of
relying on the OS.

Detect which to use once per run, from the destination's filesystem type:

- Parse `mount` output (both shell and Python shell out to the same `mount`
  command — macOS doesn't expose a clean fs-type API otherwise) to find the
  type of the mount point that owns `dest` (longest matching mount-point
  prefix, type is the first word inside the parentheses, e.g.
  `(apfs, local, ...)` / `(smbfs, ...)` / `(nfs, ...)`).
- Known-local types (`apfs`, `hfs`) → use the `flock`/`lockf` backend
  (`fcntl.flock` in Python; confirmed `/usr/bin/lockf` isn't needed since
  everything left in scope is Python).
- Anything else, including unrecognized types → use the `mkdir` backend.
  Treating "unknown" as "use the safe fallback" avoids needing to special-
  case every possible network fs name.

Both backends are exposed as one context manager, e.g.
`with checksum_index_lock(cfg.dest):`, used identically by every caller;
callers don't know or care which backend is active.

- **flock backend**: open (create if missing) `_checksum_index_.flock`,
  `fcntl.flock(fd, fcntl.LOCK_EX)` (blocks indefinitely — fine for a
  personal maintenance tool), do the work, close (releases automatically,
  including on `SIGKILL`).
- **mkdir backend**: lock directory `_checksum_index_.lockdir`. Loop:
  `os.mkdir(lockdir)` → success, write a small `info` file inside it
  (pid, hostname, ISO timestamp) for diagnostics, proceed, `shutil.rmtree`
  it when done. On `FileExistsError`, check the lock dir's mtime; if older
  than a generous threshold (e.g. 5 minutes — comfortably longer than a
  single merge should ever take), treat it as abandoned, remove it, and
  retry; otherwise sleep ~1s and retry, up to an overall timeout (e.g. 60s)
  after which raise a clear error rather than hanging forever.

### Merge algorithm (the "atomic append" + "atomic final reorder")

One function, `merge_checksum_index(scratch_file, ctx)`, does all writes to
the shared index. Called (a) at the normal end of `run_verify_all`, replacing
today's blind sort+rename, and (b) from the exit/cleanup path as a fallback
for interrupted runs, merging whatever this run's own scratch file
accumulated before it died. Calling it twice is harmless — the second call
finds an already-consumed/absent scratch file and no-ops.

Inside `checksum_index_lock(cfg.dest)`:

1. Read the current `_checksum_index_.txt` (if present) into a dict keyed by
   filename — split each line on the first two-space run (`hash<SP><SP>name`,
   the convention the code already uses for `grep -F "  $name"` lookups; app
   names can contain spaces, e.g. "Google Chrome.app@…", so keying on
   whitespace-split `$2` alone would be wrong).
2. Read the scratch file the same way.
3. For each key present in the scratch file:
   - If the key isn't in the current index, or its hash is unchanged →
     just set/keep it.
   - If the key *is* in the current index with a **different** hash → this
     is a real hash replacement (e.g. a re-verify found the zip's content
     changed). Keep the new hash as the current value in the index (still
     one line per key — lookups need a single unambiguous "current" value),
     but durably record the replacement rather than silently dropping the
     old value:
       - Append one line to a new companion file,
         `_checksum_index_.history.log` (plain append-only text log, never
         rewritten/pruned): `[<ISO8601 timestamp>] <filename>: <old_hash> -> <new_hash>`.
       - Also print `HASH CHANGED: <filename>: <old_hash> -> <new_hash>` to
         stdout at merge time for live visibility.
4. Before writing the new index, snapshot the current one (if it exists):
   rename `_checksum_index_.txt` to
   `_checksum_index_.<YYYY-MM-DD_HH-MM-SS>.<disambiguator>.bak` (a short
   random/pid suffix so two merges completing in the same second don't
   collide — same idea as the existing `{stem}~{YYYYMMDD_HHMMSS}.zip`
   duplicate-suffix convention).
5. Write the merged, sorted (`sort -k2` equivalent: sort by the filename
   portion) result to a fresh temp file and rename it onto
   `_checksum_index_.txt`.
6. Prune old backups: list `_checksum_index_.*.bak`, sorted by name
   (timestamp-sortable), and if `cfg.keep_temp` is false, delete all but the
   5 most recent. If `cfg.keep_temp` is true, skip pruning entirely (matches
   the existing flag's "preserve temp/leftover files" semantics).
7. Release the lock (end of `with` block).

### Startup recovery of orphaned scratch files — auto-merge, verbose, no prompts

Per earlier direction: no interactive prompts. At the start of a
`--verify-*` run, glob for leftover `_checksum_index_.*.tmp` files other than
the one this run is about to create (from a prior run killed before its exit
path ran). For each:

1. Print `RECOVERY: found leftover scratch file <name> (<N> lines)`.
2. Print its full contents directly (plain `print(path.read_text())` /
   `cat` — no pretty-printing, that only complicates recovery).
3. Run it through `merge_checksum_index`, which reports what changed
   (added/updated counts, plus any `HASH CHANGED` lines) as described above.
4. Delete the scratch file (keep it if `--keep-temp`).

## Files to change

- **`archive_apps/cli.py`** — add `index_scratch: Path | None = None` to
  `RunContext`.
- **`archive_apps/io.py`** or a new small module (e.g. `archive_apps/lock.py`)
  — the `checksum_index_lock()` context manager (fs-type detection + the two
  backends).
- **`archive_apps/verify.py`** — `run_verify_all` (lines 190–343):
  - Replace the fixed-name `index_tmp` + interactive recovery block with the
    auto-merge-and-report startup recovery step, then `mkstemp` a private
    scratch file for this run (store it on `ctx.index_scratch`).
  - Keep the existing per-zip `safe_append` calls, now targeting the private
    scratch file.
  - Replace the final `sort` + `safe_mv` with `merge_checksum_index(...)`.
  - Add `merge_checksum_index()` here (natural home next to the rest of the
    index logic); import it from `__main__.py`.
- **`archive_apps/__main__.py`** — `_make_cleanup()` (lines 16–46): gate on
  `ctx.index_scratch` instead of the fixed path, and call
  `merge_checksum_index` on it as the fallback for interrupted runs.
- **`archive_apps.py`** (single-file fallback) — mirror all of the above:
  `_cleanup()` (~line 467), the same `merge_checksum_index()` /
  `checksum_index_lock()` logic inlined (single-file has no module split),
  and the verify-all block (~lines 1198–1371). This file must keep producing
  output identical to the package per CLAUDE.md's "both implement the
  identical CLI."

No changes needed to `zip_ops.py`, `app_ops.py`, `archive.py`, `progress.py`,
`utils.py` — none of them touch the checksum index.

## Verification

1. **Filesystem-type detection**: run the `mount`-parsing helper against the
   current local dest (expect `apfs` → flock backend) and, if a network
   share is available to test against, confirm it's classified as needing
   the `mkdir` backend.
2. **Merge correctness**, exercised directly (import the function / run a
   small script — do not source the whole module in a way that runs the
   main loop, per existing project convention):
   - Union of keys from index + scratch, filenames containing spaces used as
     keys correctly.
   - Same key + same hash → single line, no history entry.
   - Same key + different hash → new value wins in the index, one line
     appended to `_checksum_index_.history.log`, `HASH CHANGED` printed.
   - A `.bak` snapshot of the pre-merge index is created; after 6+ merges
     without `--keep-temp`, only the 5 newest `.bak` files remain; with
     `--keep-temp`, all are kept.
3. **Concurrency reproduction**, in a scratch directory (not real
   `/Applications` / `/Users/Shared/App Versions`):
   - Two `--verify-new` runs overlapping in time against a dest with several
     zips → resulting index contains entries from both, not just whichever
     finished last.
   - `kill -9` one run mid-flight after it has appended some entries →
     confirm the orphaned scratch file is picked up and auto-merged (with
     full-content printout) on the next `--verify-*` invocation.
   - A plain archive run (no `--verify-*`) running concurrently with a
     `--verify-*` run → the archive run's exit must not touch or truncate
     the verify run's scratch file or the index.
   - Simulate lock contention (two processes both entering the merge at
     once) and confirm the mkdir-backend's staleness timeout doesn't fire
     spuriously during a normal-speed merge.
4. Confirm `archive_apps.py` and `archive_apps/` produce byte-for-byte
   identical `_checksum_index_.txt` / `.history.log` output for the same
   input scenario.
