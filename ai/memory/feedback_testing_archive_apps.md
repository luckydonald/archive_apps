---
name: feedback_testing_archive_apps
description: How to safely test functions from archive_apps.sh without triggering the main loop
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5a3cfe6e-8819-4251-a731-0ed779ed8bc4
---

Never `source archive_apps.sh` or `bash archive_apps.sh` to test an individual function — the script has an unconditional main loop at the bottom that immediately runs and archives all apps.

**Why:** Accidentally sourcing the script in a test command triggered three simultaneous archive runs, wrote unwanted zips to `/Users/Shared/App Versions`, and had to be killed with `kill -9`.

**How to apply:** Test the Python heredoc functions by copying them inline into a `python3 - args <<'PYEOF' … PYEOF` invocation, or grep out the heredoc and pipe it. Never invoke the shell script as a side-effect of loading a function.
