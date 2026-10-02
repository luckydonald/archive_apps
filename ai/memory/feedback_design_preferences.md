---
name: feedback_design_preferences
description: User's recurring design preferences for data-handling/recovery code in this repo — non-destructive by default, skeptical of unverifiable guarantees, prefers plain output over cosmetic tooling
metadata:
  node_type: memory
  type: feedback
  originSessionId: 38eb1bc9-858b-49b9-b13f-cf9f3c8beb89
  modified: 2026-08-30T18:27:34.219Z
---

Recurring preferences surfaced while designing [[project_checksum_index_concurrency_fix]], worth defaulting to for similar data-integrity/recovery work in this repo:

- **Never let a "fix" silently drop data, even data that looks like it should be superseded.** When a merge conflict meant a stored hash was about to be replaced, the user's instinct was "keep both / log the replacement," not "last-write-wins and discard the old value." Prefer append-only history logs or timestamped backups-before-overwrite over anything that overwrites the sole copy of prior state, even when the new value is presumed correct.
- **Question locking/atomicity guarantees on network filesystems rather than assuming POSIX semantics hold.** The destination directory in this repo can be a NAS over Samba/SMB; the user specifically pushed back on `flock`/`lockf` because SMB's byte-range lock support is inconsistently implemented, and wanted a filesystem-type-aware fallback (mkdir-based locking) rather than trusting the OS call to fail loudly if unsupported. Don't assume a locking or atomicity primitive that works on local APFS also works unmodified on the destinations this project actually targets.
- **Prefers direct/plain terminal output over pretty-printing for recovery flows.** Floated using `bat` for nicer file-content dumps during an auto-recovery step; on reflection rejected it ("that would make recovery annoying, direct print is good enough") — added tooling/formatting is not worth it in a code path whose whole point is fast, low-friction visibility into what's being recovered.
- **Comfortable trading interactive confirmation prompts for automated-but-verbose action**, once the underlying operation is provably safe/non-destructive (e.g. replaced a 3-prompt interactive merge-recovery flow with an unprompted auto-merge, as long as it prints full before-state and a change summary).

**How to apply:** When proposing a plan involving destructive-looking operations (overwrites, dedup, cleanup), default to a non-destructive variant (log the change, snapshot before overwrite) and mention the tradeoff, rather than assuming last-write-wins is fine. When a design leans on a filesystem/OS guarantee, check whether it needs to hold on a network mount, not just local disk.
