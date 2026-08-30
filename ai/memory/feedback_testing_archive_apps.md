---
name: feedback_testing_archive_apps
description: How to safely test functions from archive_apps.py / archive_apps/ without triggering the main archive loop
metadata:
  node_type: memory
  type: feedback
  originSessionId: 5a3cfe6e-8819-4251-a731-0ed779ed8bc4
  modified: 2026-08-30T18:26:59.135Z
---

`archive_apps.sh` was removed 2026-08-30 (see [[project_shell_script_removed]]) — the Python package and `archive_apps.py` are now the only implementations, and `bash`-sourcing risk no longer applies.

**Testing archive_apps.py (single file):** `import archive_apps` from the repo root will NOT load this file — a same-named package (`archive_apps/`) shadows it, since Python prefers a regular package over a sibling module of the same name on the same path. Load it explicitly instead:

```python
import importlib.util, sys
spec = importlib.util.spec_from_file_location("archive_apps_single", "archive_apps.py")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod   # required: dataclass field resolution needs this in sys.modules before exec
spec.loader.exec_module(mod)
```

Importing either the file (via the loader above) or the package (`import archive_apps`) is safe on its own — `main()` only runs under `if __name__ == "__main__":`, so no archive/verify side effects happen just from loading. To exercise real behavior without touching real data, build a fake destination dir with `zipfile` (top-level entry must be `SomeName.app/...` or `checksums_from_zip` treats it as unreadable) and set `mod._cfg` / `RunContext(cfg=...)` directly rather than going through `parse_args`.

**Why:** Hit both issues live while testing the [[project_checksum_index_concurrency_fix]] work — silently got the wrong module (the package, missing single-file-only helpers) on the first attempt, and a plain `module_from_spec` + `exec_module` crashed inside `dataclasses` because `sys.modules` wasn't populated yet.
