# Plan: Progress bars for cp/ditto archiving operations

## Context

When archiving a large app (e.g. Xcode at 4.7 GB), the script does two slow
operations with zero feedback:
1. `cp -R "$app" "$tmpdir/$versioned"` — cross-volume copy from `/Applications` to NAS
2. `ditto -c -k … "$dest/$zipname.tmp"` — compress and zip to NAS

Both can take several minutes. The same pattern repeats at 5 identical call sites.
`ditto -V` emits one line per file to stderr — the same mechanism as the Python bar.

---

## Approach

### New helpers (add after `rm_retry`, ~line 64)

**`_progress_bar_filter <label> <total>`** — reads one line per file from stdin, writes `\r` bar to `/dev/stderr`:

```bash
_progress_bar_filter() {
    local label="$1" total="$2"
    awk -v total="$total" -v label="$label" '
        BEGIN { step = int(total/200); if (step < 1) step = 1 }
        { n++
          if (n % step == 0 || n == total) {
            pct    = int(n * 100 / total)
            filled = int(n * 40  / total)
            bar    = ""; for (i=0; i<filled; i++) bar = bar "="
            if (filled < 40) bar = bar ">"
            while (length(bar) < 40) bar = bar " "
            printf "\r  %s [%s] %d/%d (%d%%)", label, bar, n, total, pct > "/dev/stderr"
            fflush("/dev/stderr")
          }
        }
        END { printf "\r\033[K" > "/dev/stderr"; fflush("/dev/stderr") }
    '
}
```

**`_archive_app_to_zip <app> <versioned_name> <dest_zip.tmp>`** — replaces all 5 call sites:

```bash
_archive_app_to_zip() {
    local app="$1" versioned="$2" dest_zip="$3"
    local tmpdir total use_bar=0
    tmpdir=$(mktemp -d "$(dirname "$dest_zip")/.archive_apps.XXXXXX")
    total=$(find "$app" -not -type d | wc -l | tr -d ' ')
    [[ -t 2 && $total -gt 0 ]] && use_bar=1

    # Copy: ditto -V (with bar) for cross-volume; cp -cR (clonefile, instant) otherwise
    if [[ $use_bar -eq 1 && "${cp_flags[*]}" != *c* ]]; then
        { ditto -V "$app" "$tmpdir/$versioned"; } 2>&1 | _progress_bar_filter "COPY" "$total"
    else
        cp "${cp_flags[@]}" "$app" "$tmpdir/$versioned"
    fi

    # Zip: always potentially slow (CPU compression)
    if [[ $use_bar -eq 1 ]]; then
        { (cd "$tmpdir" && ditto -V -c -k --sequesterRsrc --keepParent "$versioned" "$dest_zip"); } 2>&1 | \
            _progress_bar_filter "ZIP " "$total"
    else
        (cd "$tmpdir" && ditto -c -k --sequesterRsrc --keepParent "$versioned" "$dest_zip")
    fi

    rm_retry "$tmpdir"
}
```

Key decisions:
- **Same-volume cp**: `cp_flags` contains `-c` (clonefile) → near-instant → skip bar, keep `cp -cR`
- **Cross-volume cp**: replace `cp -R` with `ditto -V` — handles resource forks identically, gives per-file stderr lines
- **`ditto -V -c -k`**: `-V` adds per-file lines to stderr; `2>&1` pipes them to `_progress_bar_filter`
- **`pipefail`** is already set globally — ditto failure propagates through the pipeline correctly
- **Precount** (`find … | wc -l`): fast relative to the multi-minute operations; same count reused for both bars

### Cleanup fix

`cleanup()` (EXIT trap) doesn't remove orphaned `.archive_apps.*` dirs. Add after existing rm lines (~line 50):

```bash
for _td in "$dest"/.archive_apps.*; do
    [[ -d "$_td" ]] && rm -rf "$_td"
done
```

### Call site replacement (5 instances: lines ~553, ~566, ~605, ~620, ~641)

Each block:
```bash
tmpdir=$(mktemp -d "$dest/.archive_apps.XXXXXX")
cp "${cp_flags[@]}" "$app" "$tmpdir/$versioned"
(cd "$tmpdir" && ditto -c -k --sequesterRsrc --keepParent "$versioned" "$dest/$XXX.tmp")
rm_retry "$tmpdir"
```
becomes:
```bash
_archive_app_to_zip "$app" "$versioned" "$dest/$XXX.tmp"
```

The `mv "$dest/$XXX.tmp" "$dest/$XXX"` stays at each call site unchanged.

### Bar appearance

```
  COPY [===================>                    ] 345/3812 (9%)
  ZIP  [========================================] 3812/3812 (100%)
```

---

## File to modify

- `archive_apps.sh` only

## Change summary

| What | Where |
|------|-------|
| Add `_progress_bar_filter` function | after `rm_retry` (~line 64) |
| Add `_archive_app_to_zip` function | after `_progress_bar_filter` |
| Add `.archive_apps.*` cleanup to `cleanup()` | ~line 50 |
| Replace 5× `tmpdir=…; cp; ditto; rm_retry` blocks | lines ~553, ~566, ~605, ~620, ~641 |

---

## Verification

```bash
# Archive a new app — should show COPY bar then ZIP bar:
./archive_apps.sh /tmp/test_dest

# Piped (no bar):
./archive_apps.sh /tmp/test_dest 2>/dev/null

# Same-volume dest (cp_flags=-cR): no COPY bar, ZIP bar only
```
