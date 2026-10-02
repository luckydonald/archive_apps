---
name: project_shell_script_removed
description: archive_apps.sh (the Bash implementation) was deleted 2026-08-30 — the Python package is now the sole active implementation
metadata:
  node_type: memory
  type: project
  originSessionId: 38eb1bc9-858b-49b9-b13f-cf9f3c8beb89
  modified: 2026-08-30T18:27:07.306Z
---

`archive_apps.sh` was removed from the repo on 2026-08-30 (commit "Remove archive_apps.sh; Python package is the active implementation"). Only `archive_apps.py` (single-file fallback) and the `archive_apps/` package remain, and CLAUDE.md was updated to stop describing the shell script.

**Why:** User's own call — "the .sh should be removed anyway, as .py is the future" — made while scoping [[project_checksum_index_concurrency_fix]], since fixing a bug in code slated for deletion wasn't worth the effort.

**How to apply:** Don't propose changes to `archive_apps.sh` — it no longer exists. Any future bug fix or feature only needs to touch `archive_apps.py` and `archive_apps/`, and both must keep producing identical CLI output (per CLAUDE.md). The `old/*.bak.sh` changelog snapshots were explicitly left alone (CLAUDE.md protects them from deletion without confirmation) — do not treat their continued presence as an oversight.
