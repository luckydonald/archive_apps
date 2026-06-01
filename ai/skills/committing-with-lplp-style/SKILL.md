---
name: "committing-with-lplp-style"
description: "Activates the lplp-pipbuck commit style for the current session. Commits after every completed task, amends the last commit if its message is an `ai:` auto-commit (`ai: updated prompt`, `ai: save decision …`, or `ai: save plan …`), writes messages via ai/git/pending-commit.md, never commits unrelated files. Use when the user opts in to this style at session start, or explicitly asks to enable it."
---

# lplp Commit Style

Adopt these rules for every commit made this session:

1. **Commit after every completed task.** Never leave work uncommitted.

2. **Check the last 2 commits before committing:**
   - Last message matches one of the `ai:` auto-commit patterns — `ai: updated prompt`, `ai: save decision <slug>`, or `ai: save plan <NNN>_<slug>` → **amend** it.
   - Otherwise → create a new commit.
   - If more than one chained past commits are `ai:` auto-commits (`ai: updated prompt`, `ai: save decision …`, and/or `ai: save plan …`) they probably should be included, too.
     - In that case the `/rebase-ai-prompt-commits` command/skill describes how to rebase & include them.

3. **Always write the message to `ai/git/pending-commit.md` first** like this:
   1. run exactly the whitelisted command `rm ai/git/pending-commit.md || echo 'was gone'`, which makes sure it's not gonna cause "stale unread file" issues.
   2. Write to `ai/git/pending-commit.md` using the preferred Built-in/MCP tool.
   3. Pass it to the commit with `-F ai/git/pending-commit.md`. Never inline the message in the command, to avoid the need for user confirmations.

4. **Message format:**
   ```md
   [scope] category: ai: Run: <short one-line summary>

   <multiline body: what changed, why, key decisions>
   ```
   Scope examples: `[.idea]`, `[git]` (gitignore etc.), `[github]` (workflows, issue templates, …), `[frontend]`, `[db]`, [stdb]` (spacetimedb), `[api]`, `[backend]`, `[docker]`, `[coolify]`, `[infra]`, … 
   Both summary and body may contain pure-markdown for formatting. 

5. **Stage only files changed by the current task.** Never stage `ai/git/pending-commit.md` (it is gitignored) or unrelated files.

6. Once this skill is activated, keep commiting after every completed task automatically without asking again.
   If the user responds with a simple `commit` or similar (`commit plz`, `keep commiting`, etc.), this means they want to remind you, to follow the "keep automatically commiting" instruction, which you should already anyway.
