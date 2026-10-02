---
name: project_checksums_locale_sort
description: "checksums_from_zip previously used system locale sort (en_US) while _collect_app_manifest used C locale, causing ordering mismatches"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5a3cfe6e-8819-4251-a731-0ed779ed8bc4
---

`checksums_from_zip` called `locale.setlocale(locale.LC_ALL, '')` before sorting, switching to the system locale (en_US.UTF-8 on macOS). `_collect_app_manifest` never set the locale, so it sorted under Python's default C locale. On macOS these two collation orders differ for `_`-prefixed paths (`_CodeSignature/`, `_MASReceipt/`) present in every App Store app.

**Why:** Both manifests contained the same lines but in different order, so the verbatim string comparison always failed for App Store apps.

**How to apply:** Fixed 2026-06-22 — both functions now explicitly call `locale.setlocale(locale.LC_COLLATE, 'C')` before any `locale.strxfrm`-based sort. If adding new manifest-comparison code, always pin `LC_COLLATE` to `'C'` explicitly rather than relying on Python's default. See [[project_ditto_zip_cp437]].
