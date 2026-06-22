---
title: Fix locale sort mismatch causing MISMATCH for all App Store apps
file: ai/errors/13.md
---

## Context

When archiving a fresh app (no existing zip), the script computes a `live_checksums` manifest, creates the zip, reads back `zip_checksums` from the zip, and compares them with `[[ "$zip_checksums" == "$live_checksums" ]]` (line 1224). This always fails for App Store and iOS-on-Mac (mobile@) apps, printing `MISMATCH ❌: archived checksum does not match original app`.

**Root cause**: the two manifest generators use different locale sort orders.

- `_collect_app_manifest` (line 442): never calls `locale.setlocale()` → Python default is C locale → `locale.strxfrm` is identity → sort by Unicode code points.
- `checksums_from_zip` (line 828): calls `locale.setlocale(locale.LC_ALL, '')` → sets system locale (en_US.UTF-8 on macOS) → `locale.strxfrm` uses ICU collation → different order.

App Store apps universally contain `_CodeSignature/` and `_MASReceipt/` directories. The `_` character (code point 95, between `Z`=90 and `a`=97) sorts *after* uppercase-named directories in C locale but *before* them in en_US. Result: both manifests contain the same lines, but in different order → string comparison fails.

## Changes

### 1. Mandatory — `checksums_from_zip`, line 828

```python
# before
locale.setlocale(locale.LC_ALL, '')
results.sort(key=lambda x: locale.strxfrm(x.split('  ', 1)[1]))

# after
locale.setlocale(locale.LC_COLLATE, 'C')
results.sort(key=lambda x: locale.strxfrm(x.split('  ', 1)[1]))
```

`LC_COLLATE, 'C'` pins sort to C locale, matching `_collect_app_manifest`'s effective behavior. Using `LC_COLLATE` rather than `LC_ALL` is intentionally narrower — the `strftime` progress-bar calls earlier in the same heredoc have already completed and don't need to change.

### 2. Optional safety — `_collect_app_manifest`, before the `os.walk` loop (line ~451)

Add one line after the variable declarations to make the C-locale dependency explicit:

```python
locale.setlocale(locale.LC_COLLATE, 'C')
```

Protects against edge cases where the calling environment sets `LC_ALL` in a way that Python inherits it.

## Backward compatibility

`.checksums.txt` files on disk are almost always written from `_collect_app_manifest` output (line 1213, the common new-archive path). Those files are in C-locale sort order and will continue to verify correctly.

A small number of checksum files may have been written via `checksums_from_zip` output (the "zip exists, checksum missing" path at line 1169, or `--verify` mode at line 1046) using the buggy en_US sort. After the fix those files will produce a `MISMATCH ❌` prompt — the user can choose `[o]verwrite` to regenerate them correctly.

## Verification

After applying the fix, delete an existing zip for a known App Store app (e.g. one with `_CodeSignature/`) and re-run the script. The output should show `CREATED ✅` instead of `MISMATCH ❌`.

Quick sanity check to confirm the locale difference is the cause:
```bash
python3 -c "
import locale
paths = ['Contents/MacOS/App', 'Contents/_CodeSignature/CodeResources', 'Contents/Resources/x']
locale.setlocale(locale.LC_ALL, '')
print('en_US:', sorted(paths, key=locale.strxfrm))
locale.setlocale(locale.LC_COLLATE, 'C')
print('C:    ', sorted(paths, key=locale.strxfrm))
"
```
Before the fix the two lines should differ. After applying both changes they will agree.
