---
name: project_single_file_removed
description: archive_apps.py (single-file version) removed 2026-11-12; Makefile ran it by mistake, so package-only features never reached the user's normal runs
metadata:
  type: project
---

The single-file `archive_apps.py` was removed on 2026-11-12; the `archive_apps/` package is the only implementation, and the `Makefile` runs it as `python -m archive_apps` (via the `RUN` variable).

**Why:** The Makefile (added 2026-10-02) executed `archive_apps.py`, while features from commits `9a81b38`, `c7ac70b` and `939ab47` (mismatch swap prompt, timeouts and presets, Finder colors) landed only in the package, so the user believed requested features had never landed. A parity check (subagent, 2026-11-12) found the package to be a strict superset of the single file.

**How to apply:** Do not recreate a second implementation. When the user says a feature "never landed", check which entry point they actually run (`Makefile`, `main.py`, installed `archive-apps`). `rsync` is preferred for the local-cache SEND step (`app_ops.send_file`) at the user's request. Known behaviour differences vs the old file: pure-Python size/discovery/hash instead of `du`/`find`/`shasum`/`PlistBuddy`. See [[project_shell_script_removed]].
