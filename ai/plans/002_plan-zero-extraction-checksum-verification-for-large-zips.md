# Plan: Zero-extraction checksum verification for large zips

## Context

4.5 GB Xcode zip lives on NAS. HDD has only 2 GB free. Current verification:
1. copies zip to `$TMPDIR` on HDD (4.5 GB — already over budget)
2. extracts it there (~30 GB for Xcode)

Extracting to NAS is also off the table: NAS file versioning would record
every created/deleted file from the extraction (hundreds of thousands for
Xcode).

**Required solution:** hash zip entries on-the-fly, never write them to disk.

---

## Approach: Python streaming in `checksums_from_zip()`

Python 3 ships on macOS and its `zipfile` module can iterate zip entries as
streams. We replace the copy→extract→find→shasum pipeline with a Python
one-liner that reads each entry and hashes it in 64 KB chunks, writing
nothing to disk.

### New `checksums_from_zip()` function

```bash
checksums_from_zip() {
    local zip="$1"
    # Fast readability probe — fails on Synology dataless files before
    # starting the expensive Python read
    if ! head -c 4 "$zip" > /dev/null 2>/dev/null; then
        return 1
    fi
    python3 - "$zip" <<'PYEOF'
import sys, zipfile, hashlib

zpath = sys.argv[1]
try:
    with zipfile.ZipFile(zpath) as z:
        app_prefix = None
        for name in z.namelist():
            parts = name.split('/')
            if not name.endswith('/') and '__MACOSX' not in name \
               and len(parts) > 1 and parts[0].endswith('.app'):
                app_prefix = parts[0] + '/'
                break

        if app_prefix is None:
            sys.exit(1)

        results = []
        for info in z.infolist():
            name = info.filename
            if name.endswith('/') or '__MACOSX' in name:
                continue
            if not name.startswith(app_prefix):
                continue
            rel = name[len(app_prefix):]
            sha = hashlib.sha256()
            with z.open(info) as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    sha.update(chunk)
            results.append(sha.hexdigest() + '  ' + rel)

        results.sort(key=lambda x: x.split('  ', 1)[1])
        print('\n'.join(results))
except Exception as e:
    print('Error: ' + str(e), file=sys.stderr)
    sys.exit(1)
PYEOF
}
```

**Disk usage: 0 bytes written.** Reads from NAS, hashes in RAM, prints to
stdout. No tmpdir needed.

### Sort order note

Existing checksums were produced by `find | sort -z | shasum`. Python's
default `str.sort()` on ASCII paths produces identical byte order to POSIX
`sort`. For app bundles (always ASCII paths) this is equivalent. ✓

### Inline extraction sites → also converted

The three inline `tmpcheck` extract-and-hash blocks in the verify loop and
main CHECKSUM:missing path (lines ~304, ~428) use the same pattern. Replace
those with a call to the updated `checksums_from_zip()` or inline the same
`head` probe + Python call.

Current inline pattern (lines ~304, ~428):
```bash
tmpcheck=$(mktemp -d)
cp "$zip" "$tmpcheck/archive.zip"     # eliminated
ditto -x -k "$tmpcheck/archive.zip" "$tmpcheck"  # eliminated
zipapp=$(find "$tmpcheck" -maxdepth 1 -name "*.app" -type d | head -1)
actual=$(find "$zipapp" -type f -print0 | sort -z | \
    xargs -0 shasum -a 256 | sed "s|$zipapp/||")
rm_retry "$tmpcheck"
```

Replace with:
```bash
if ! actual=$(checksums_from_zip "$zip"); then
    echo "  SKIPPED ⚠️: zip not readable or corrupt"
    continue
fi
```

This unifies three independent extraction sites into one helper call.

---

## Archiving path (secondary improvement)

The 5 archiving sites copy the app into a tmpdir in `$dest`, then zip from there
(to get `AppName version.app` as the internal zip entry name). On APFS this
is a CoW clone (cheap). On a NAS dest, it's a full byte-copy of the app
(30 GB for Xcode).

**Optional fix:** zip directly from `/Applications/AppName.app`:
```bash
ditto -c -k --sequesterRsrc --keepParent "$app" "$dest/$zipname.tmp"
```

Eliminates the intermediate copy entirely. Internal zip entry changes from
`AppName version.app` to `AppName.app` — the zip filename already carries the
version. Checksum comparison is unaffected (both sides strip the top-level dir
name). **Decide before implementing.**

---

## Files to modify

- `archive_apps.sh` only

## Change summary

| Change | Lines affected |
|--------|---------------|
| Rewrite `checksums_from_zip()` to use Python streaming | ~183–200 |
| Replace verify-loop inline extract block with `checksums_from_zip()` call | ~295–320 |
| Replace main-loop CHECKSUM:missing inline extract with `checksums_from_zip()` call | ~420–445 |
| (Optional) Remove app copy in 5 archiving sites | ~399–502 |

---

## Verification

```bash
# 1. Streaming checksum matches extraction-based checksum on a small zip
mkdir /tmp/test_dest
./archive_apps.sh /tmp/test_dest 2>&1 | grep -m1 'CREATED ✅'
# Note the app+version, e.g. "Signal.app@7.4.0"
./archive_apps.sh --verify-zips /tmp/test_dest 2>&1 | grep -E 'VERIFIED|FAILED'

# 2. Confirm no tmpcheck dirs created during verify
ls /tmp/test_dest/.verify_* 2>/dev/null || echo "no tmps ✓"

# 3. (When on NAS) run --verify-new on dest; confirm it completes
#    without disk-full errors on HDD
```
