# When calculating the number for the new plan, take into account all (other) worktrees.

**Todo** `todo:d5dd94eb-49ac-4a74-bf4d-39114bf055e7`  
**Commit style** `/commit-with-lplp-style` is active.

> When calculating the number for the new plan, take into account all (other) worktrees.

The todo is marked in progress in CalDAV and the local mirror. In a scratch repository, the current hook chose `008` even though a sibling worktree already contained an uncommitted `015` plan. The expected number was `016`.

- Update the [save-plan hook](/Users/user/.paseo/worktrees/1mpb7kvi/idiotic-llama/scripts/°base/ai/hooks/save-plan/hook.py:513) to use the highest plan number in the corresponding directory across all registered Git worktrees. This preserves the existing numbering scope for subprojects and issue-specific plan directories.
- Use a lock shared by the worktrees while allocating a number and writing the plan, so simultaneous saves get distinct numbers. Revisions will keep their original number.
- Test with real linked worktrees, including an uncommitted plan in a worktree whose path contains spaces, concurrent saves, and revisions. Run the full test suite and repository checks before closing the todo. No i18n changes are needed.
