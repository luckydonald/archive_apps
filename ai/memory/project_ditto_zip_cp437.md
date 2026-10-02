---
name: project_ditto_zip_cp437
description: "ditto -c -k stores filenames as UTF-8 bytes without setting the ZIP UTF-8 flag, causing Python zipfile to decode as CP437"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5a3cfe6e-8819-4251-a731-0ed779ed8bc4
---

`ditto -c -k` (Apple's zip tool) writes filenames as raw UTF-8 bytes but does NOT set bit 11 (the UTF-8 flag) in the ZIP general-purpose bit field. Python's `zipfile` module sees no UTF-8 flag and falls back to CP437 decoding, garbling any non-ASCII characters (e.g. curly quotes `"` → `ΓÇ£`).

**Why:** This caused `checksums_from_zip` to produce `rel` paths with CP437-mangled characters that never matched the UTF-8 paths from `_collect_app_manifest`, producing false MISMATCH for any app with non-ASCII characters in its file names (e.g. Velja).

**How to apply:** Fixed in `checksums_from_zip` via `_fix_zip_name(info)` (committed 2026-06-22). If touching zip filename handling elsewhere in the script, apply the same round-trip: `info.filename.encode('cp437').decode('utf-8')` when `not (info.flag_bits & 0x800)`. See [[project_checksums_locale_sort]].
