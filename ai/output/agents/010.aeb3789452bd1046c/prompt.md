In this repo (/Users/user/Documents/programming/Shell/archive_apps), I need to understand the exact code flow for handling a checksum mismatch when archiving an app whose zip already exists but whose `.checksums.txt` is missing.

Specifically look at archive_apps/app_ops.py, archive_apps/verify.py, archive_apps/archive.py, archive_apps/io.py (write_fail_menu, tty_read), and archive_apps/utils.py (sanitize_temp_component, fmt_duration, sha256*).

I need to know, in detail:
1. Where in the code the "zip exists, checksums file missing" branch happens, and where it computes checksums for the extracted (existing) zip vs the live app and compares them.
2. What exactly happens on match (writes checksums file) vs mismatch (prompts interactively).
3. The exact interactive prompt code for the mismatch case — the [o]verwrite / [b]oth / [s]kip options. Get exact function name(s), line numbers, and the literal prompt text/menu.
4. For the "[b]oth" branch specifically: exactly what file operations occur — what happens to the existing (old, mismatched) zip file, what name/path the NEW zip (current live app snapshot) is written to (I believe it's the old stem + a timestamp suffix, need exact format string), and whether/how checksums files are written for each (old zip's checksums file, new zip's checksums file).
5. Any existing timestamp-suffix naming pattern used elsewhere in the code (the `{stem}~{YYYYMMDD_HHMMSS}.zip` pattern mentioned in CLAUDE.md) — find the exact code that generates this suffix, including the datetime format string and any existing constants/helpers for it.
6. Any existing code that renames/moves a zip along with its checksums file as a pair (useful for a future feature that needs to rename an existing mismatched zip + checksums pair together, appending a `~hash-missmatch~{timestamp}` suffix to it). Look for safe_mv usage in app_ops.py or archive.py.
7. The overall structure of run_archive in archive.py — how it iterates apps and calls into the per-app archive logic, so I understand where the new "ask if we should swap them out" prompt would need to hook in after writing the new version in the "both" branch.
8. Any existing tests directory (`test/` was mentioned as new/untracked) — check if there are existing tests for this mismatch/both flow to understand testing patterns.

For each item, give me the file path, function name, and line number range, plus the relevant code snippets verbatim. This is a research task only — do not write or edit any files, just report back your findings in detail (this can be a longer, thorough report since it needs to inform an implementation plan).