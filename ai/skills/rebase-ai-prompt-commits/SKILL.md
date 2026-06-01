---
name: "rebase-ai-prompt-commits"
description: "Rebases the current branch to group stray `ai:` auto-commits — `ai: updated prompt` and `ai: save decision …` (both `ai/query.md`-only) and `ai: save plan …` (`ai/plans/<NNN>_*.md`-only) — into their neighboring code commits using non-interactive rebase. Fixes mislabeled commits. Optionally rewrites HEAD as a branch summary. Invoke on demand before merging or reviewing a branch."
---

# Rebase: Group stray `ai:` auto-commits

Handles three kinds of stray auto-commits produced by hooks:

- **`ai: updated prompt`** — one per user prompt; touches only `ai/query.md` / `ai/°base/query.md`.
- **`ai: save decision <slug>`** — one per resolved `AskUserQuestion`; same file as above. Slug is derived from the first question's text.
- **`ai: save plan <NNN>_<slug>`** — one per `ExitPlanMode`; touches only `ai/plans/<NNN>_*.md` / `ai/°base/plans/<NNN>_*.md`.

## Procedure

**1. Audit the branch**
```bash
git log --oneline origin/<upstream>..HEAD
for sha in <shas>; do
  echo "$sha $(git log -1 --format='%s' $sha): $(git show --name-only --format='' $sha | tr '\n' ' ')"
done
```

**2. Plan groups.** Direction depends on the commit type:

- **`ai: updated prompt`** and **`ai: save decision <slug>`** (both touch only `ai/query.md` / `ai/°base/query.md`) → fixup under the **preceding** code commit. The prompt/decision arrived during/after that work, so it folds *backward*.
- **`ai: save plan <NNN>_<slug>`** (only `ai/plans/<NNN>_*.md` / `ai/°base/plans/<NNN>_*.md`) → fixup under the **following** code commit (the implementation the plan describes). Since `fixup` only squashes into the immediately preceding `pick`, this requires **reordering** the plan commit in the todo to come right after its implementation commit.
- **Orphan plan commit** (no following code commit yet — e.g., a plan that was never implemented, or a test/smoke-test plan) → leave it as a normal `pick`; do not drop it.

Flag mislabeled commits (wrong message for actual file content).

**3. Write renamed commit messages** to `/ai/git/rebase-msg-<sha>.md` for any commits needing a label fix.

**4. Write the rebase todo script**
```bash
cat > /tmp/git-rebase-todo.sh << 'SCRIPT'
cat > "$1" << 'REBASE'
pick <code-commit-implementing-plan>
fixup <plan-commit>            # reordered: was BEFORE the code commit, now AFTER (forward-fold)
fixup <prompt-commit>          # `ai: updated prompt` — backward-fold as usual
fixup <decision-commit>        # `ai: save decision <slug>` — same direction as prompts
exec git commit --amend -F /ai/git/rebase-msg-<sha>.md
pick <next-code-commit>
fixup <prompt-commit>
...
REBASE
SCRIPT
chmod +x /tmp/git-rebase-todo.sh
```
Put `exec git commit --amend -F ...` **after** all fixups for that group to rename the squashed result.

**5. Run**
```bash
GIT_SEQUENCE_EDITOR=/tmp/git-rebase-todo.sh git rebase -i origin/<upstream>
```

**6. Optional — rewrite HEAD as branch summary**
Write to `ai/git/pending-commit.md`:
```
[scope] category: ai: Run: <summary>

Branch `<name>` based on `origin/<upstream>` @ <sha>.

- bullet: key decisions
- bullet: what changed and why
```
As you can see, Markdown shall be used here.

Then: `git commit --amend -F ai/git/pending-commit.md`
