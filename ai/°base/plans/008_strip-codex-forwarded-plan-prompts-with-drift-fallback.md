# Strip Codex Forwarded Plan Prompts With Drift Fallback

## Summary
Prevent only Codex implementation-start prompts from duplicating a just-saved plan in `ai/°base/query.md`. Use exact boilerplate detection first; if the boilerplate text changed, fall back to matching the latest saved plan file and warn that the stripper may need an update.

## Key Changes
- In `scripts/°base/ai/hooks/save-prompt/hook.py`, run prompt normalization only when `ai_tool == "codex"`; Claude stays unchanged.
- Normal path: detect the known Codex forwarded-plan prefix verbatim, strip that prefix plus the embedded plan, and log only any user-authored text after the plan.
- Fallback path: when the exact prefix is not found, compare the prompt against the latest numbered `NNN_*.md` plan file under the resolved `ai[/°base]/plans` directory.
- Treat the latest plan file as matchable only when it is plan-like: at least `1024` bytes and at least `8` newline characters.
- If the prompt contains that plan text and the match succeeds, strip through the end of the matched plan and preserve only trailing user-authored text.
- On fallback-based stripping, print a warning to stderr saying the Codex forwarded-plan prompt prefix may have changed and the hook should be updated.
- If stripping leaves no meaningful prompt text, exit without writing `query.md` or creating an `ai: updated prompt` commit.
- Do not change `scripts/°base/ai/hooks/save-plan/hook.py`.

## Tests
- Codex exact-prefix prompt containing only the saved plan: assert no query file is created and HEAD is unchanged.
- Codex exact-prefix prompt plus a real instruction after the saved plan: assert only the instruction is logged with `›`.
- Codex changed-prefix prompt where latest plan-file matching succeeds: assert the duplicate plan is stripped and stderr contains the update warning.
- Codex changed-prefix prompt where the latest plan file is tiny: assert no file-based stripping happens.
- Claude prompt with the same text: assert it is logged unchanged.
- Run `python3 -m unittest scripts/°base/tests/test_ai_hooks_base_routing.py -v` and `python3 -m py_compile scripts/°base/ai/hooks/save-prompt/hook.py`.

## Assumptions
- “Latest plan file” means highest numbered `NNN_*.md`, not filesystem mtime.
- The file-based fallback is only for Codex prompt-prefix drift, not a general prompt deduplicator.
- Existing duplicated prompt entries are not rewritten.
- Existing dirty decision files are unrelated and must be left untouched.
