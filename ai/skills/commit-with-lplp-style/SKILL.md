---
name: "commit-with-lplp-style"
description: "Activates the lplp-pipbuck commit style for the current session. Commits after every completed task, amends nearby `ai:` prompt/decision auto-commits into the work commit, preserves plan commits as separate history, writes messages via ai/git/pending-commit.md, and never commits unrelated files. Use when the user opts in to this style at session start, or explicitly asks to enable it."
---

# lplp Commit Style

Adopt these rules for every commit made this session:

1. **Commit after every completed task.** Never leave work uncommitted.

2. **Check the last 2 commits before committing:**
   - Last message matches one of the auto-commit patterns below → **amend** it.
   - Otherwise → create a new commit.
   - If more than one chained past commit is an auto-commit, include those too.

   Auto-commit patterns — fold into the preceding code commit **by default**:
   - `ai: updated prompt` — user prompt saved to `ai/query.md`
   - `ai: save decision <slug>` — resolved `AskUserQuestion`
   - `ai: agent <id> results` — subagent result record
   - `ai: record memory <slug>` — memory file written (e.g. `ai: record memory MEMORY`, `ai: record memory feedback_commit_amend_over_reset`)
   - `ai: Plan …`, `ai: Plan Update …`, `ai: save plan <NNN>_<slug>` — plan files

   **When to keep a commit separate instead of folding:**
   - A plan commit is followed by one or more `ai: Plan Update …` commits for the same plan number — folding would erase the revision history of the plan. Keep each version as its own commit.
   - A prompt commit (`ai: updated prompt`) represents a clearly new or unrelated topic — it started a different task, not a continuation of the preceding code commit.
   - When in doubt, fold. The goal is readable history, not preserving every auto-save.

   If a `git reset --soft HEAD~N` accidentally included commits that should stay separate, restore them with `git reset --soft <original-hash>` before committing.
   Prefer `--amend` over `HEAD~1`.

3. **Always write the message to `ai/git/pending-commit.md` first** like this:
   1. run exactly the whitelisted command `rm ai/git/pending-commit.md || echo 'was gone'`, which makes sure it's not gonna cause "stale unread file" issues.
   2. Write to `ai/git/pending-commit.md` using the preferred Built-in/MCP tool.
   3. Pass it to the commit with `-F ai/git/pending-commit.md`. Never inline the message in the command, to avoid the need for user confirmations.

4. **Message format:**
   ```md
   [where] component-or-topic: ai: Run: <short one-line summary><sentence-separator>

   <multiline body: what changed, why, key decisions>
   ```
   Where examples: `[.idea]`, `[git]` (gitignore etc.), `[github]` (workflows, issue templates, …), `[frontend]`, `[db]`, `[stdb]` (spacetimedb), `[api]`, `[backend]`, `[docker]`, `[coolify]`, `[infra]`, …
   The word or phrase after `[where]` is a component, feature, subsystem, or topic, not a Conventional Commit type. Do not use `feat`, `fix`, `chore`, `docs`, `test`, or `refactor` there unless that word is literally the component or topic being changed.
   Good examples:
   - `[frontend] admin: ai: Run: Implemented user deletion UI.`
   - `[backend] models: ai: Run: Added models for cool feature.`
   - <code>[backend] cool feature: ai: Run: Added the `cool` model.</code>
   - `[git] ignore rules: ai: Run: Ignored generated cache files.`
   Bad examples:
   - `[frontend] fix: ai: Run: Implement user deletion UI`
   - `[backend] feat: ai: Run: Added cool feature models`
   End every commit summary with a sentence separator: `.`, `:`, `,`, `!`, or `?`.
   Usually use `.` when the summary stands on its own and the body only adds context. Use `:` when the subject needs the body/details that follow to complete the thought.
   Both summary and body may contain pure-markdown for formatting.

   For normal use, multiple `[where]` parts can be written as one bracket with pipes, e.g. `[backend|frontend]`.

   For the base repo itself, use `[base] [optional source repo] topic: ai: …`. Recent examples include `[base] git hooks: ai: …`, `[base] ai/hooks: ai: …`, `[base] [AllMyStorage] skills: ai: …`, and `[base] [userscripts] gitignore: …`.

5. **Stage only files changed by the current task.** Never stage `ai/git/pending-commit.md` (it is gitignored) or unrelated files.

6. Once this skill is activated, keep commiting after every completed task automatically without asking again.
   If the user responds with a simple `commit` or similar (`commit plz`, `keep commiting`, etc.), this means they want to remind you, to follow the "keep automatically committing" instruction, which you should already anyway.

## Cleaning up stray `ai:` auto-commits

Use this procedure before merging or review when the branch has stray prompt/decision commits mixed into the history.

Handles these hook-created commits:

- **`ai: updated prompt`** — one per user prompt; touches only `ai/query.md` or `ai/°base/query.md`.
- **`ai: save decision <slug>`** — one per resolved `AskUserQuestion`; touches only `ai/query.md` or `ai/°base/query.md`. The slug is derived from the first question's text.
- **`ai: agent <id> results`** — subagent result record; touches only agent result files.
- **`ai: record memory <slug>`** — memory file written; touches only files under the memory directory.
- **Plan commits** — `ai: Plan …`, `ai: Plan Update …`, or `ai: save plan <NNN>_<slug>`; touches only `ai/plans/<NNN>_*.md` or `ai/°base/plans/<NNN>_*.md`. Keep separate when there are multiple versions of the same plan (the sequence records how the plan evolved). A lone plan commit with no follow-up updates may be folded into its implementation.

### Procedure

**1. Audit the branch**

```bash
git log --oneline origin/<upstream>..HEAD
for sha in <shas>; do
  echo "$sha $(git log -1 --format='%s' $sha): $(git show --name-only --format='' $sha | tr '\n' ' ')"
done
```

**2. Plan groups**

- **`ai: updated prompt`**, **`ai: save decision <slug>`**, **`ai: agent <id> results`**, and **`ai: record memory <slug>`** commits → fix up under the **preceding** code commit by default. Exception: a prompt commit that clearly starts a different/unrelated task should stay as its own `pick`.
- **Plan commits** → fix up into the implementation commit if the plan was never revised (no `ai: Plan Update …` follow-ups for the same plan number). If the plan was revised multiple times, keep each version as a separate `pick` — the sequence is the history.
- **Mislabeled commits** → flag commits whose message does not match the files they actually changed. Rename them as part of the rebase instead of silently folding them the wrong way.

**3. Write renamed commit messages** to `ai/git/rebase-msg-<sha>.md` for any commits needing a label fix.

**4. Write the rebase todo script**

```bash
cat > /tmp/git-rebase-todo.sh << 'SCRIPT'
cat > "$1" << 'REBASE'
pick <code-commit>
fixup <prompt-commit>          # ai: updated prompt; backward-fold
fixup <decision-commit>        # ai: save decision <slug>; backward-fold
fixup <agent-commit>           # ai: agent <id> results; backward-fold
fixup <memory-commit>          # ai: record memory <slug>; backward-fold
exec git commit --amend -F ai/git/rebase-msg-<sha>.md
pick <plan-commit>             # plan with follow-up updates: keep separate
# fixup <plan-commit>         # lone plan (no updates): may fold into implementation
pick <next-code-commit>
fixup <prompt-commit>
...
REBASE
SCRIPT
chmod +x /tmp/git-rebase-todo.sh
```

Put `exec git commit --amend -F ...` after all fixups for that group to rename the squashed result.

**5. Run**

```bash
GIT_SEQUENCE_EDITOR=/tmp/git-rebase-todo.sh git rebase -i origin/<upstream>
```

**6. Optional — rewrite HEAD as branch summary**

Write to `ai/git/pending-commit.md`:

```md
[scope] category: ai: Run: <summary>

Branch `<name>` based on `origin/<upstream>` @ <sha>.

- bullet: key decisions
- bullet: what changed and why
```

Then:

```bash
git commit --amend -F ai/git/pending-commit.md
```
