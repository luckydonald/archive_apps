---
name: feedback-lplp-never-drop-ai-autocommits
description: "Under the lplp commit style, never drop stray `ai:` auto-commits — fold them all into the upcoming code commit, even if they look like smoke-test debris."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f9f6509b-5c3e-4b0f-9b0b-654fa6f96547
---

When the lplp commit style ([[skill-lplp]]) is active and there are chained `ai:` auto-commits (`ai: updated prompt`, `ai: save decision …`, `ai: save plan …`) preceding the work being committed, **merge them into the new code commit**. Do not drop them, even if their content looks like smoke-test artifacts or noisy verification data.

**Why:** Explicit user correction during the make-hooks-monorepo-aware session — when I proposed `git reset --hard` to drop four smoke-test auto-commits, the user replied "don't drop but merge." The lplp skill already encodes this ("they probably should be included, too") but I'd reached for the destructive shortcut anyway. The user's reasoning is consistent: auto-commit content is part of the project history regardless of how trivial it looks, and folding (not dropping) is the right reflex.

**How to apply:** When the last *N* commits are all `ai:` auto-commits and you're about to commit new code, soft-reset back past all of them (`git reset --soft <last-real-code-commit>`) to collapse everything into the index, then commit it as one new code commit using the lplp message format. Never `git reset --hard` past auto-commits.
