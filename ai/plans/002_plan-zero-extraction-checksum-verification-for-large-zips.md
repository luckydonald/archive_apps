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

        import locale
        locale.setlocale(locale.LC_ALL, '')
        results.sort(key=lambda x: locale.strxfrm(x.split('  ', 1)[1]))
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

Existing checksums were produced by `find | sort -z | shasum`. App names (and
paths inside bundles) can be Unicode. Python's `locale.strxfrm` with
`LC_ALL=''` picks up the system locale and matches macOS `sort`'s collation,
so the order will be identical for both ASCII and Unicode paths. ✓

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

## Archiving path — no change

The 5 archiving sites copy the app to a tmpdir in `$dest` to rename it
`AppName version.app` before zipping. This is intentional (version visible
when manually unzipping). The tmpdir lives in `$dest` so on APFS it's a
CoW clone; on NAS it's NAS-local. Leave as-is.

---

## Files to modify

- `archive_apps.sh` only

## Change summary

| Change | Lines affected |
|--------|---------------|
| Rewrite `checksums_from_zip()` to use Python streaming | ~183–200 |
| Replace verify-loop inline extract block with `checksums_from_zip()` call | ~295–320 |
| Replace main-loop CHECKSUM:missing inline extract with `checksums_from_zip()` call | ~420–445 |
| Archiving path | no change |

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
