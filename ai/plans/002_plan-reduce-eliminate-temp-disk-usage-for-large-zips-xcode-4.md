# Plan: Reduce / eliminate temp disk usage for large zips (Xcode 4.5 GB)

## Context

The script fails on large zips because verification copies the zip to `$TMPDIR`
(4.5 GB) then extracts it there (30+ GB for Xcode) — all on the main boot
volume. Two separate problems, each fixable independently.

---

## Problem 1 — Redundant zip copy in verification (3 sites)

**Current pattern** (lines ~186, ~304, ~428):
```bash
tmpcheck=$(mktemp -d)
cp "$zip" "$tmpcheck/archive.zip"          # unnecessary full copy
ditto -x -k "$tmpcheck/archive.zip" "$tmpcheck"
```

The `cp` was added as a "dataless file" probe (Synology): if the file isn't
synced, `cp` fails fast. But `ditto -x -k` also fails on a dataless file, so
both errors map to the same SKIPPED outcome. The distinction can be preserved
more cheaply with a `head -c 4` probe.

**Fix:**
```bash
tmpcheck=$(mktemp -d)
if ! head -c 4 "$zip" > /dev/null 2>/dev/null; then
    rm_retry "$tmpcheck"
    echo "  SKIPPED ⚠️: not readable (possibly not synced locally)"
    continue   # (or return 1 in checksums_from_zip)
fi
if ! ditto -x -k "$zip" "$tmpcheck"; then
    rm_retry "$tmpcheck"
    echo "  SKIPPED ⚠️: zip corrupt (ditto extraction failed)"
    continue
fi
```

Savings: **one full copy of the zip eliminated** — 4.5 GB for Xcode.

---

## Problem 2 — Extraction lands on main-disk $TMPDIR

**Current:** `tmpcheck=$(mktemp -d)` → uses `$TMPDIR` (boot volume).
For Xcode, extracting to boot volume needs ~30 GB there.

**Fix:** Create the tmpcheck *on the dest volume* so extraction is local to
where the zip lives:
```bash
tmpcheck=$(mktemp -d "$dest/.verify_XXXXXX")
```

This applies to all three `tmpcheck=$(mktemp -d)` sites in the verify/
checksums paths. (Archiving's `tmpdir` already uses `"$dest/.archive_XXXXXX"`
so it's already correct.)

Savings: **extracted app no longer lands on boot volume** — 30 GB for Xcode.
Trade-off: if $dest is a NAS, writes are slightly slower, but the space
pressure on the main disk is gone.

---

## Problem 3 — App copy in archiving path (5 sites)

**Current pattern** (lines ~399, ~412, ~461, ~476, ~498):
```bash
tmpdir=$(mktemp -d "$dest/.archive_apps.XXXXXX")
cp "${cp_flags[@]}" "$app" "$tmpdir/$versioned"    # e.g. "Xcode 16.2.app"
(cd "$tmpdir" && ditto -c -k --sequesterRsrc --keepParent \
    "$versioned" "$dest/$zipname.tmp")
rm_retry "$tmpdir"
```

The copy exists only to rename the bundle to `AppName version.app` inside the
zip. If $dest is on the same APFS volume as /Applications, `cp -cR` is a CoW
clone (cheap). But on a NAS, it's a full 30 GB byte-copy.

**Fix:** Zip directly from `/Applications/AppName.app`, skip the copy entirely.
```bash
ditto -c -k --sequesterRsrc --keepParent "$app" "$dest/$zipname.tmp"
```

The zip name on disk (`AppName.app@version.zip`) still carries the version.
The **internal** name inside the zip changes from `AppName version.app` to
`AppName.app`. The checksums code already strips the top-level app name
(`sed "s|$zipapp/||"`) so this is checksum-compatible with existing archives.

Savings: **entire app copy eliminated** — saves ~30 GB of I/O for Xcode when
$dest is on a different filesystem (NAS). On local APFS it was already cheap
(CoW), but eliminating the tmpdir step simplifies the code significantly too.

⚠️ **One trade-off to decide:** internal zip entry name changes.

---

## Files to modify

- `archive_apps.sh` only

## Sites to touch

| Change | Sites |
|--------|-------|
| `head` probe + direct `ditto -x -k "$zip"` | `checksums_from_zip()` (~line 186), verify loop (~line 304), main loop CHECKSUM:missing (~line 428) |
| `mktemp -d "$dest/.verify_XXXXXX"` | same 3 tmpcheck sites |
| Remove `cp` + `tmpdir`, direct `ditto -c -k "$app"` | 5 archiving sites (~399, 412, 461, 476, 498) |

---

## Verification

```bash
# smoke test — one real app, local dest
./archive_apps.sh /tmp/test_dest 2>&1 | grep -E 'ARCHIVING|CREATED|VERIFIED|SKIPPED|ZIP'

# verify a zip directly
./archive_apps.sh --verify-zips /tmp/test_dest 2>&1 | grep -E 'VERIFY|VERIFIED|SKIPPED|EXTRACTED'

# confirm no stray tmps
ls /tmp/test_dest/.verify_* /tmp/test_dest/.archive_* 2>/dev/null || echo "clean"
```
