---
name: feedback_testing_archive_apps
description: How to run and write tests for the archive_apps package (pytest invocation, safe imports, fake destination)
metadata:
  node_type: memory
  type: feedback
  originSessionId: 5a3cfe6e-8819-4251-a731-0ed779ed8bc4
  modified: 2026-08-30T18:26:59.135Z
---

The single-file `archive_apps.py` was removed 2026-11-12 (see [[project_single_file_removed]]), so there is no import-shadowing gotcha any more: `import archive_apps` loads the package.

**Testing the package:** run tests with `uv run --with pytest python -m pytest tests` (plain `pytest` does not put the repo root on `sys.path`). Importing the package is safe on its own — `main()` only runs under `if __name__ == "__main__":`, so no archive/verify side effects happen just from importing. To exercise real behavior without touching real data, build a fake destination dir with `zipfile` (top-level entry must be `SomeName.app/...` or `checksums_from_zip` treats it as unreadable) and construct `RunContext(cfg=...)` directly (see `tests/test_termination.py`) rather than going through `parse_args`.

**Why:** The import-shadowing and `sys.modules`/dataclass pitfalls were hit while testing the [[project_checksum_index_concurrency_fix]] work and only applied to the single file.
