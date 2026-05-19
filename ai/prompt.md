# AI query log file

#### General AI development guidelines:
- You may refer to `ai/refrences` for code examples of other plugins or extra documentation provided for this task.
- When writing code, follow these guidelines:
  - Always prefer the early-return pattern to reduce nesting of `if`s, etc.
  - Similarly, prefer `if …` -> `continue`/`return`/`break` early in loops over large nested blocks.
- Language/stack-specific style constraints (Vue/TS frontend, Python backend, …), including test-writing expectations, now live in the `code-style` skill under `ai/skills/code-style/references/` — apply those instead of repeating them here.
- Remember to update the `/CHANGELOG.md` and `/README.md` if existent (including other pre-existing documentation).
- If you want to write Markdown summaries of the task you just did (only if specifically asked for by the user!) write those to `ai/summaries/` folder, and never into the root folder.
  - However, usually you don't need to write Markdown summaries.
- Please prefer to use the read file tool over weird constructs with `cat` etc. Terminal should not be needed for searches most of the time, either.

----

#### Previous user prompts:


❯ @ai/errors/1.md

❯ can we trigger and check the sync?

❯ can we hook into that Option A, _right-click the file in Finder → "Make Available Offline" (Synology Drive's FinderSync extension adds this menu item)_ directly?
I.e. **not** using applescript + UI scripting?

❯ dockcument the issue and what we found detailed at ai/docs/*.md.

❯ it shall include the location and intricite details of key discoveries along the way, too.

❯ Is the `EXISTS:` a checksum check? if so print that. Otherwise add that check.

❯ do a separate `CHECKSUM: match` or something.

❯ which checksum is written? The zip file? which source is checksummed? the `CHECKSUM: match` should be probably `CHECKSUM zip: match` and `CHECKSUM app: match`?

❯ @ai/errors/2.md

