# Plan: Guarded file writes + recovery for NAS disconnects

## Context

When the laptop sleeps with the archive dest on a NAS, in-progress writes fail
with `echo: write error: Input/output error` (line 107 — an append to
`_checksum_index_.txt.tmp`). The cleanup trap then can't remove the .tmp
(`Resource busy`), leaving an empty `_checksum_index_.txt` and an orphaned
`.tmp`. The fix is guarded write helpers with interactive recovery menus,
readback verification, and startup recovery for orphaned .tmp files.

Trigger error: `ai/errors/5.md`

---

## Critical files

- `archive_apps.sh` — all changes go here

---

## 1  New helpers (add after `rm_retry`, before `checksums_from_zip`)

### Global state

```bash
_preserve_tmps=()   # tmps that must not be cleaned up (safe_mv c-fail)
```

Update `cleanup()` so it skips files in `_preserve_tmps` when removing
`*.checksums.txt.tmp`.

### `_write_fail_menu description content_or_src orig_dst mode`

Shared interactive loop used by all three helpers below.

- `mode` = `append` | `write` | `mv`
  - `append`/`write`: `content_or_src` = the string to (re)write
  - `mv`:            `content_or_src` = path of src file (still on disk)
- Tracks `cur_dst` (may be changed by option b); tracks `has_alternate` bool
  (whether cur_dst ≠ orig_dst) so option a' is shown only when relevant.
- Sets global `_WFAIL_DST` to the (possibly new) destination for the caller to
  use on retry.
- Returns: `0` = retry with `$_WFAIL_DST`, `1` = skip/handled, `2` = exit.

**Menu options:**

```
  WRITE ERROR: <description>
  [a] retry (default)
 [a'] retry original path          ← only shown when cur_dst ≠ orig_dst
  [b] save somewhere else
  [c] skip (try /tmp, else print)
  [d] exit
  Choice [a]:
```

Option behaviours:
- **a**: set `_WFAIL_DST=$cur_dst`, return 0
- **a'**: set `cur_dst=orig_dst`, set `has_alternate=0`, set `_WFAIL_DST=$cur_dst`, return 0
- **b**: `read` new path → set `cur_dst=new_path`, `has_alternate=1`, `_WFAIL_DST=$cur_dst`, return 0
- **c**:
  - `append`/`write`: try `printf '%s\n' "$content_or_src" >> /tmp/$(basename "$orig_dst")` or `>` (same as mode). On success print `SAVED ⚠️: /tmp/...`. On failure print content to terminal.
  - `mv`: try `mv "$content_or_src" "/tmp/$(basename "$orig_dst")"`. On success print `SAVED ⚠️: /tmp/...`. On failure `cat "$content_or_src"` to terminal; add `content_or_src` to `_preserve_tmps`.
  - Return 1 (continue operation).
- **d**: `printf "Type 'sure' to confirm exit: "`; if typed `sure`: do the same as c), then `exit 1`. If not typed, loop back to menu.
- Invalid input: loop back.

### `safe_append line file`

```
while true; do
    target="${_WFAIL_DST:-$file}"
    if printf '%s\n' "$line" >> "$target" 2>/dev/null; then
        last=$(tail -1 "$target" 2>/dev/null)
        [[ "$last" == "$line" ]] && return 0
        echo "  WARN: readback mismatch (append $target)" >&2
    fi
    _write_fail_menu "append to $(basename "$file")" "$line" "$file" "append"
    rc=$?; [[ $rc -eq 0 ]] || return $(( rc - 1 ))
done
```

### `safe_write content file`

Same shape as `safe_append` but uses `>` (truncate) instead of `>>`.
Readback: `tail -1 "$target"` vs last line of `$content`.

### `safe_mv src dst`

```
expected=$(wc -l < "$src" 2>/dev/null | tr -d ' ')
_WFAIL_DST="$dst"
while true; do
    target="$_WFAIL_DST"
    if mv "$src" "$target" 2>/dev/null; then
        actual=$(wc -l < "$target" 2>/dev/null | tr -d ' ')
        if [[ -s "$target" && "$actual" -eq "$expected" ]]; then
            return 0
        fi
        echo "  WARN: readback mismatch after mv to $target" >&2
        return 0    # src is gone; can't re-try mv; just warn and continue
    fi
    # mv failed; src still on disk
    _write_fail_menu "write $(basename "$dst")" "$src" "$dst" "mv"
    rc=$?; [[ $rc -eq 0 ]] || return $(( rc - 1 ))
done
```

Note: if mv succeeds but readback is wrong, warn and continue (src is gone so
retry is impossible). Menu only triggers when mv itself fails.

---

## 2  Recovery code (start of verify section, before the loop)

Runs whenever `verify_mode != "none"`.

### Logic

```
tmp_file="$dest/_checksum_index_.txt.tmp"
live_file="$dest/_checksum_index_.txt"

if [[ -f "$tmp_file" ]]; then
    echo "RECOVERY: Found leftover temp file: $(basename "$tmp_file")"
    printf "  Restore it? [Y/n]: "
    read -r choice < /dev/tty
    [[ "${choice:-y}" =~ ^[Nn]$ ]] && skip...

    live_lines=$([[ -f "$live_file" ]] && wc -l <"$live_file" | tr -d ' ' || echo 0)
    printf "  Existing file: $live_lines lines. Merge? [Y/n]: "
    read -r choice < /dev/tty
    [[ "${choice:-y}" =~ ^[Nn]$ ]] && skip...

    tmp_lines=$(wc -l < "$tmp_file" | tr -d ' ')
    merged=$(sort -u -k2 "$tmp_file" ${live_lines:+"$live_file"} 2>/dev/null)
    merged_lines=$(printf '%s\n' "$merged" | grep -c . || true)
    dup_lines=$(( tmp_lines + live_lines - merged_lines ))
    echo "  Temporary file: $tmp_lines lines"
    echo "  Existing file:  $live_lines lines"
    echo "  Merge duplicates: $dup_lines lines"
    echo "  Resulting file: $merged_lines lines"
    printf "  Continue? [Y/n]: "
    read -r choice < /dev/tty
    [[ "${choice:-y}" =~ ^[Nn]$ ]] && skip...

    # Write merged result via safe helper
    merged_tmp=$(mktemp "$dest/_checksum_index_.XXXXXX.tmp")
    printf '%s\n' "$merged" > "$merged_tmp"
    safe_mv "$merged_tmp" "$live_file"
    rm -f "$tmp_file"
    echo "  RECOVERY ✅: merged and written"
fi
```

---

## 3  Replace write sites

### Index appends (6 sites, all `echo "..." >> "$index_tmp"`)

Replace with `safe_append "..." "$index_tmp"`.

### Index sort + mv (end of verify loop)

```bash
sort -k2 "$index_tmp" -o "$index_tmp"
mv "$index_tmp" "$index_file"
```
→
```bash
if sort -k2 "$index_tmp" -o "$index_tmp" 2>/dev/null; then
    safe_mv "$index_tmp" "$index_file"
else
    echo "  WARN: sort of index failed; writing unsorted" >&2
    safe_mv "$index_tmp" "$index_file"
fi
echo "INDEX: written → $(basename "$index_file")"
```

### Checksums file writes (10 `echo/printf >` + 8 `mv` sites)

Each pattern:
```bash
printf '%s\n' "$content" > "$dest/$checksumname.tmp"
mv "$dest/$checksumname.tmp" "$dest/$checksumname"
```
→
```bash
safe_write "$content" "$dest/$checksumname.tmp"
safe_mv "$dest/$checksumname.tmp" "$dest/$checksumname"
```

Apply to all checksums write+mv pairs in:
- verify loop (CHECKSUM: missing, creating — line ~163)
- main loop CHECKSUM: missing path (all write+mv pairs ~lines 268–279)
- main loop o/b overwrite branches (~lines 226–250, 282–314)
- main loop ARCHIVE: missing new write (~lines 336–337)

### Zip files

Not in scope — ditto writes are huge and `ditto`'s own error handling is
sufficient. A failed ditto would leave the .zip.tmp, which cleanup removes.

### Cleanup trap

The `sort ... > "$dest/_checksum_index_.txt"` in the EXIT trap is non-interactive
(the user just hit Ctrl-C). Keep as-is but wrap in `|| true` so the trap itself
doesn't error. The `*.checksums.txt.tmp` removal loop must skip files in
`_preserve_tmps`:

```bash
for _f in "$dest"/*.checksums.txt.tmp; do
    [[ -f "$_f" ]] || continue
    _skip=0
    for _p in "${_preserve_tmps[@]+"${_preserve_tmps[@]}"}"; do
        [[ "$_f" == "$_p" ]] && _skip=1 && break
    done
    [[ $_skip -eq 1 ]] || rm -f "$_f"
done
```

---

## 4  Verification

1. Simulate NAS failure: run with dest on a local path and fill the disk mid-run
   (or use `ulimit -f` to limit file size), confirm the menu appears.
2. Manually create a `_checksum_index_.txt.tmp` at dest, run with `--verify-new`,
   confirm the recovery dialog fires and the merge is correct.
3. Run `./archive_apps.sh --verify-new /tmp/test_dest` end-to-end; confirm index
   is written correctly and no .tmp files are left.
