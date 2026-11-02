# Todos

Source: `sync_todo` MCP, calendar `TODO: Today` (`calendar_id` 7), pulled 2026-10-08. Each item ends with its todo `uid`.
To complete one: tick the box and call `mcp__sync_todo__complete_todo(calendar_id=7, uid=<uid>)`.

- [x] fix the codestyle not loading for /plan. — `todo:268ba6c5-56d0-4879-9a52-50c3c9ede70c` _(done)_
  > Use the official anthropic skill creator skill to help you.
- [x] the Make sure a file mention like (@ai/somefile.txt) gets detected to not include the ).I guess the try combinations algortithm (….txt) does not exist, ….txt does exist) would work here, too. — `todo:66f35747-cd41-4646-aee5-989858265baf` _(done)_
- [x] Allow referenced file auto-commit in more git states: — `todo:b7a5299c-3989-4bc1-bef3-b12418b8249b` _(done)_
  > • for the linked file in query (@ai/whatever) detection & committing hook
  > • staged and previously commited files
  > • still must adhere to .gitignore
- [x] also link `/skill` calls to their `ai/skills/…/SKILL.md` — `todo:be604b2a-0d90-4b41-973b-d57bc48e0772` _(done)_
  > • obviously the skill must exist
- [x] add skill to use `download_ref.py` — `todo:e7df2be3-4ad7-41c4-8aab-d3a2acd1508b` _(done)_
  > So at least `--no-ide.`

## Synced from CalDAV

- [x] Strip `Note: The user's next message may contain a correction or preference. Pay close attention — if they explain what went wrong or how they'd prefer you to work, consider saving that to memory for future sessions.` from plan decisions. — `todo:5e80abad-4a70-4e79-b210-14ac7b639f88` _(done)_
- [x] Have a rebase or merge use git triggers to re-sync per-file subproject symlinks. — `todo:6f2b2450-103d-4be5-b029-bbe95c3e5501` _(done)_
  > for now skip this todo (it is already being worked on in the base repository itself, don't do it from another project)
- [x] have a `.run/.subprojectIgnore` file, defining files to not link into subprojects. — `todo:58a06dbd-33b8-48fe-b392-9f5a67b935cc` _(done)_
- [x] `ai/memories/MEMORY.md` is skipped in commit — `todo:b8ae433f-4258-4549-b98c-cc3ceded8903` _(done)_
  > • but it’s written and then a dirty file
  > • figure out why; I even got you an example:
  > • DockerTgBot
  > • claude possibly running from the `sync_todo` subdirectory.
  > • The files themselves were eventually squashed into b6bab629bce68382369588a25f448afaaf66c6b8.
  > • backup tags should exist with possibly the original commit
  > • search for filename in commit msg
  > • I manually added the `ai/memories/MEMORY.md` in 3927b1d4cc654ec54bba23997c7f448e193b4cab there.
- [x] have the sync ai settings script show a propper diff — `todo:51f4adc0-dc22-43c4-92cf-4bf9475b9ba1` _(done)_
  > Both for dry run and the actual execution. This is to catch errors if the wrong file was detected as newest, and the changes are removed by syncing an older file over it. This allows the AI agent or user to detect that.
- [x] have the show-plan-confirm-action for claude also sync the plan once more — `todo:7eb9a977-d3d3-4ba0-9889-39732d4c7f1a` _(done)_
  > Sometimes it uses echo or python scripts to edit the plan file, also usually not mentioning the full path in one go, but `CLAUDE_PLAN_DIR + PLAN_NAME + ‘.md’` or something weird.
  > Hence it’s best to write & commit it once more. You can also use the plan decision hook for that, if that’s better.
- [x] add missing `mcp__bugsink__*` permissions — `todo:9adc5376-530b-4020-9cf4-6f7e55ff3ac1` _(done)_
  > Add to @ai/settings/settings.json:
  > ```json
  > // TODO: fix quotes
  > “mcp__bugsink__list_events”,
  > “mcp__bugsink__get_event”,
  > “mcp__bugsink__get_stacktrace”,
  > “mcp__bugsink__test_connection”,
  > ```
- [x] checkout.sh: skip symlinked hooks in repair_git_lfs_hooks_path — `todo:56f6ee1a-63c7-4c77-9588-174c3f48d98d` _(done)_
  > `scripts/°base/init/checkout.sh` `repair_git_lfs_hooks_path()` rewrote symlinked hooks (e.g. `.git/hooks/pre-push` -> tracked `.hooks/pre-push.bash`) through the link, stripping the repo's own hook content on every Claude session start.
  > Fixed in luckydonald/docker-tg-bot with a `[ -L "$hook_file" ] && continue` guard plus `scripts/°base/tests/test_checkout_lfs_hooks.py`; bring the same change into luckydonald/base.
- [x] design auto-commit to be scoped only to the link paths, bypass hooks, skip during merges/rebases/detached HEAD, and safely fall back to staged-but-uncommitted if anything fails — `todo:163fb511-e999-42c1-b288-818da77d2e40` _(done)_
  > - ˋlink_subproject.pyˋ already does it now
  > - the other things should do that too
  > - ideally a shared python function
- [x] Remove the `_` prefix from private-style functions in `record-memory/hook.py` — `todo:fded287a-f92c-4f4f-a632-8b3f373eba44` _(done; prio 9₍₉₎ lowest)_
  > • code-style says no `_` prefix for ordinary identifiers; hook.py still has ~20 (`_commit`, `_sync_all`, `_git_root`, `_rm_targets`, …)
  > • rename them and their callers/tests
  > • or extract into a module instead of hiding them
  > • low prio, pure cleanup
- [x] for github links, which are turned into a git commit, keep a `latest` folder with symlinks. — `todo:3caf29dd-df53-4dd5-8f5f-3b99f41c0cf8` _(done)_
  > • It should link the individual files each
  >   • because existing files are not updated to new versions automatically.
  >   • however pulling a new file which writes a new commit will overwrite that file's latest symlink with the new symlink target
  > • Keep the directory structure up to the file symlink.
  >
  > #### Example
  >
  > 1. We instruct to download `https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/advanced-usage.md`
  > 2. It writes the file`ai/references/https/github.com/ChromeDevTools/chrome-devtools-mcp/blob/882f93e9a8809fe88eced35d793951fb456b7117/docs/advanced-usage.md` as expected
  >    - Note: the hash is likely different in a test today, this is the old file already in git.
  > 3. NEW: it creates a symlink for that branch.
  >    1. It creates the directory path recursively for the current branch
  >       - so like the existing output path in **2.** but instead of `blob/<commit-sha>` it uses the specified `blob/main/docs/`
  >         - probably you recalculate that path with `blob/main` instead.
  >     - basically `mkdir -p ai/references/https/github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/`
  >    2. it adds the symlink under that dir to the downloaded file (soft symlink)
  >       - in that folder created by **3.1.**
  >       - The symlink should be relative
  >         - use `../` repeateatly to get where it needs to go
  >         - `pathlib` does that for you already
  >       - basically `ln -s ../../882f93e9a8809fe88eced35d793951fb456b7117/docs/advanced-usage.md`
  >         - symlink goes from `blob/main/docs/advanced-usage.md` up to the `blob` dir,
  >         - then into the correct git hash one,
  >         - then down to that file there.
  >       - instead of `blob/<commit-sha>` it uses `blob/<branch>`
  >    - You may combine the steps **3.1** and **3.2** if that make sense
  >      - Use `pathlib.Path` for efficiency.
  >    - So the symlink will be at `ai/references/https/github.com/ChromeDevTools/chrome-devtools-mcp/blop/main/docs/advanced-usage.md`, pointing to the written file
  > 4. NEW: it creates a latest symlink
  >    - similarly to **3.**
  >    - instead of `blob/<commit-sha>` or `blob/<branch>` it uses `latest`
  >      - which is not a valid github URL, but helpful for a human.
  >    - So the symlink will be at `ai/references/https/github.com/ChromeDevTools/chrome-devtools-mcp/latest/docs/advanced-usage.md`, pointing to the written file
  >    - which is not a valid github URL, but helpful for a human.
  >
  > #### TL;DR:
  >
  > Path | What
  > --- | ---
  > `https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/advanced-usage.md` | URL
  > `ai/references/https/github.com/ChromeDevTools/chrome-devtools-mcp/blob/882f93e9a8809fe88eced35d793951fb456b7117/docs/advanced-usage.md` | download
  > `ai/references/https/github.com/ChromeDevTools/chrome-devtools-mcp/blop/main/docs/advanced-usage.md` | branch symlink
  > `ai/references/https/github.com/ChromeDevTools/chrome-devtools-mcp/latest/docs/advanced-usage.md` | latest symlink
- [x] Add a `ai/.subDir` file, instructing which `ai/query.md` etc. is to be used. — `todo:6bc531bc-61bf-46b2-9bd1-2955685b80db` _(done)_
  > • not present: as before
  > • present: contains the relative path from the git root to the subproject to use
  > • This would be an extension of the exisiting subproject detection in the path generation of `query.md` and generally the `ai/` folder to use
  > • That `ai/.subDir` file is added to `.gitignore`
- [x] make sure `?plain=1` and `?preview=1` is properly ignored for github links in `scripts/download_ref.py`. — `todo:71a4bb57-51ba-4875-91f2-d5b1451aa801` _(done)_
  > • e.g. https://github.com/mdn/content/blob/main/files/en-us/web/api/navigator/registerprotocolhandler/index.md?plain=1
- [x] add memory for storing telegram `user_id` to db or fixed integer size to be BIGINT. — `todo:2d6a17a2-5d9a-44d2-93a3-245ae8215388` _(done)_
  > • reference the specific `ai/references/` markdown file for this in the memory's body.
- [x] allow `/code-style` and suffix like `/code-style .md .py` or `/code-style md` in the query-autocommit hook to not be displayed — `todo:2eaeb8ce-67be-4878-a8df-3fb3311a4be8` _(done)_
  > • there's an array to fill
- [x] add `mcp__sync_todo__list_calendars` to allowed calls in `ai/settings/settings.json`. — `todo:87dac3b4-331e-4043-8f5b-cc5e45c113ab` _(done)_
- [x] add memory that if we stumble over preexisting errors in unittests or typing, those should be fixed as a separate commit automatically, too. No need to explicitly seach for those though. — `todo:8ae825eb-3ef2-4d84-8180-a937d7e2bb3c` _(done)_
- [x] Write memory to NEVER EVER run file searches from `/`. — `todo:d23bc543-c583-4dc1-a8ed-1141c92f6822` _(done)_
  > Also disallow `find / …` via `ai/settings/settings.json`.

## Moved from todo.md

Open (new CalDAV todos created 2026-10-22):

- [x] Add `squash unpushed` to ignored queries. — `todo:823f4001-2f8c-4a77-a2dd-f9d1d86a75d9` _(done)_
- [ ] Once the `# end if` plugin is released, remove the `# end …` rule from the `python.md` code style. — `todo:7f19ba8b-35fc-477b-8f41-c5f458e697fc` _(prio 9₍₉₎ lowest)_
- [x] Improve the Markdown (`md.md`) code style to actually automatically be loaded if `/plan` is executed. — `todo:360971fb-7080-4607-94bf-d13a523c30e9` _(done)_
- [x] Add the information about the currently selected file to the prompt log. — `todo:0b3a981b-3de7-4f89-aa1d-32471f137111` _(done)_
  > • File selected: [⧉ File `todo.md`](./todo.md)
  > • Single line: [⧉ File `todo.md`: 1 line selected](./todo.md#L190) — TODO: figure out if/how we can properly link a specific line.
  >   • Moving the file as title probably makes sense when rendered: <a class="selection multi" href="./todo.md#L190" title="File &lt;code&gt;todo.md&lt;/code&gt;">⧉ 1 line selected</a>
  >   • But it's not really readable... Can we set that with still using Markdown? Not sure if GitHub & GitLab render: [⧉ 1 line selected](./todo.md#L190){title="File `todo.md`"}
  > • Multiple lines: [⧉ File `todo.md`: 10 lines selected](./todo.md#L190-200) — TODO: figure out if/how we can properly link a specific line. See above with possibly shortening it.
- [x] Rename `query.md` to `prompt.md`. — `todo:a224a3e0-f8ab-47c5-9382-437b225227de` _(done; prio 9₍₉₎ lowest)_
  > • Make sure all script usages of that file will first see if they have to rename an old file.
  > • If `query.md` exists, and the `prompt.md` is missing or equal to the `base/base` version:
  >   • delete the unused `prompt.md` (= 1 commit)
  >   • rename `query.md` to `prompt.md` (= 1 commit)
  > • If both files exist and are equal in content:
  >   • check which file has the longer history (is older) in _this_ repo (so excluding commits from `base/base`).
  >   • delete the other (= 1 commit)
  >   • if `query.md` remains: rename (= 1 commit)

Closed (no CalDAV equivalent):

- [x] /plan I want to have "explore" commands written to the prompt log, similar to `Task Notification:`. _(done)_
  > Claude CLI writes:
  > ```log
  > Explore(Explore record-memory hook and commit logic)
  > ```
  > I think we could write it like this:
  >
  > @ai/°base/errors/9.expected.md
- [x] If `ai/.debug` file exists, all hooks shall write their payload to `ai/output/debug/`. Adapt paths for `°base` as usual. _(done)_
- [x] Record `/compact` results, too. _(done)_
  > For `/compact`, see @ai/°base/errors/10.md and @ai/°base/errors/10.expected.md
- [x] For the `Task Notification:` prompt update, from [5.expected.md](./errors/5.expected.md), the last line (tools, tokens, time) is missing. Implement it. _(done)_
- [x] Fix prompts-while-running for claude being lost. _(done)_
  > E.g. in this repo/prompt (blockquote me):
  > > Change the output dir for agent stuff to `ai/output/agents/NNN.task-id/` (+`output`)
- [x] Alright, let's modernize the question prompt log. _(done)_
  > Currently, we have question output to `query.md` like @ai/°base/errors/12.md
  > Instead I want it changed to @ai/°base/errors/12.expected.md
  >
  > Construct a unittest using `12.expected.md`'s `json` under **Input JSON (Claude)** as input and asserting the markdown under **`query.md` addition** as output.
  > For implementing, the sections **Summary of format options** and **Notes** may be helpful.
- [x] Additionally, using @ai/references/https/developers.openai.com/codex/mcp.md and @ai/references/https/github.com/7c/bugsink-mcp/blob/87ce8bba8d65b15004f80314fce5845543ae193b/README.md support MCP sync. _(done)_
  > While at it configure it directly with `envmcp` to use `ai/.env` of a repo, see @ai/references/https/github.com/griffithsbs/envmcp/blob/9dc9d6510aa07f999095b7bb5eed636428eebec5/README.md for that tool.
- [x] Tool to split AI stuff & `base` from a project (clean / unclean / history branches). _(done, "probably done, low prio")_
  > /plan I need to create a tool for splitting off AI stuff & `base` from a project, as that project is not supposed to have this base or AI mentions in it.
  > The general concept is that for a branch, AI versions can exist.
  > Generally, there's the clean branch with any name, but examples could be `feature/ABC-123/something/mr1`, `feature/ABC-123_something`, `ABC-1234_foo`, `bugfix/foo-crash` or just `i-did-a-thing`.
  > This now gets two additional branches, one for direct work and commits (unclean) and one for tracking commit relations etc. (history)
  >
  > type | branch name format | purpose
  > --- | --- | ---
  > clean | `{branch}` | the clean branch, not containing any mention of or commits from this base or anything related to AI assistant usage (prompts, refs, etc.). This one is save to release to the public or the customer.
  > unclean | `ai/UNCLEAN/{branch}` | this is the branch to work on. It will allow you to commit ai, non-ai (code), or a mix of both as you want, making actually editing code etc. easier.
  > history | `ai/history/{branch}` | this stores the metadata, and ai stuff, basically it's the left overs after you extract the clean parts from the unclean branch. So it contains every change which is not part of the code, so we can still reuse our AI instructions for later branches as well, e.g. `CLAUDE.md`. Also contains all metadata to sync the stripped down **clean** with the other branches.
  >
  > The general concept is to have those be synced automatically.
  > There's also a `ai/history/master` branch (or whatever the repo's main branch is, `master`, `main`, `mane`, etc.),
  > which will be holding the history of the AI stuff for after a **clean** variant was merged into the main branch. It then is the base for the next **unclean** and hence also the next **history** branch - while the main branch itself is the base for the new **clean** branch.
  >
  > #### `update-history-master`
  > The script needs a `update-history-master` command, which does create a new base history.
  > The master history is constructed like this in terms of commits:
  >
  > category | sorting | description
  > --- | --- | ---
  > `master` | comes first | all commits from the origin's current main branch)
  > base | after `master` | this are merge commits of `base/base` into the `ai/history/master`.
  > **history** | after `master` | commits of all **history** branches which **clean** branches were already merged into master.
  > merge | after `master` | this are empty commits marking/referencing the last (= merge) commit merge of an **clean** branch which had **history** into master, so it comes after the rebased commits of that **history** branch.
  >
  > The difficult part is that after an update of **clean `master`**, the **`master` history** shall be rebased onto that.
  > While that `master` is updated, we need to keep track of merges of **clean** branches which have an existing **history** or **unclean** variant, so we can cherry-pick those commits, too.
  >
  > With that general rebase strategy, and flattening the history of already-merged ai branches, it's gonna be difficult to support merging this `base`, and later on updates to the `base` to it occasionally.
  > How can we handle that gracefully?
  >
  > Additionally, there should be a `--force-merge=<branch name>` option (multiple), which would force a manual history branch merge before it is actually included in the clean master.
  >
  > It does roughly the following:
  > 1. checkout `master`
  > 2. check if `master` is up to date, if not, ask whether we should `git pull` (default: N)
  > 3. checkout `base`
  > 4. check if `base` is up to date, if not, ask whether we should `git pull` (default: N)
  > 5. check out `ai/history/master`
  > 6. rebase `ai/history/master` onto `master`
  > 7. merge the most recent `base/base` into `ai/history/master`.
  >
  > The problem to think about is how we handle `base/base` merges. Merges doesn't really like rebases...
  > Maybe the script manually rebases, processing the changes as usual until those would occur, then automatically merge the old merged commit of `base/base` freshly into `ai/history/master` (again), while applying the old conflict resolution once more (so if we can't rebase a merge, we instead recreate it).
  >
  > #### `sync-splits`
  > This subcommand allows to sync **clean**, **unclean** and **history** versions of a branch.
  > Those branches not created yet will be added.
  >
  > ##### Generating **clean**
  > Take **unclean** and strip all AI content, and outright drop ai-only commits.
  >
  > A branch's **clean** branch will start on the `master` branch, and add commits to that.
  >
  > ##### Generating **history**
  > Take **unclean** and strip all code content, but keep the commits even if empty.
  > Add metadata to commits or add specifically crafted metadata commits to store everything needed to sync an **clean** branch with an **history** branch back to **unclean**.
  >
  > A branch's **history** branch will start on the `ai/history/master`, and add commits to that.
  >
  > ##### Generating **unclean**
  > This is the most difficult one, as you need to merge **clean** and **history** back.
  >
  > Steps:
  > 1. Start from `history/master` (i.e. the specific commit of `history/master` the branches **history** is based on, so that all the previous AI stuff is contained.
  > 2. Cherry-pick the commits from **clean** and **history** in order.
  >
  > In that there can be different commits to process:
  > 1. code only
  >     - the commit exists only in **clean**, and there's no relating **history** for it
  >       - e.g. it is a quick commit added after the last sync, i.e. to hotfix something, or if ai was not needed.
  > 2. history only
  >     - this commit exist only in **history** and there's no **clean** commit matching.
  >       - e.g. just an update to `CLAUDE.md` without any code changes.
  > 3. code + history
  >    - the commit is in both other branches, and can be merged back into a single commit.
  >      - e.g. prompt/query file update + the actually implemented changes.
  >
  > A branch's **unclean** branch will start on the `ai/history/master`, and add commits to that.
  >
  > #### `rebase-branches-to-master`
  > This one takes all of the three branches and rebases it onto the current `master` variants.
  >
  > - **clean**
  >     - This one will be rebased onto the also **clean** `master` branch.
  > - **history**
  >     - This will be rebased onto the`ai/history/master` branch.
  > - **unclean**
  >     - This will be rebased onto the **history** branch just created.
  >
  > Also think about how to handle one or two of them branches missing.
- [x] Push checks for the split tool. _(done, "probably done, low prio")_
  > 1. branch push name check
  >    1. do not allow **unclean** or **history** format-named branches to be pushed to a remote called `origin`.
  > 2. branch push content check
  >    1. block ai or ai-containing commits to be pushed if the branch name is not **unclean** format.
  >    2. block code or code-containing commits to be pushed if the branch name is not **history** format.
  > 3. `ai/query.md` guard (base repo only)
  >    1. block any push from the `luckydonald/base` repo itself whose diff touches `ai/query.md` — this repo must log to `ai/°base/query.md` instead (see `resolve_log_path()` in `scripts/°base/ai/hooks/_lib.py`).
  >    2. implemented separately from checks 1–2: those live in `°split_lib/push_checks.py` (needs the full multi-ref-update/branch-name list from `split.py check-push`'s own stdin parsing), while this one runs as a `scripts/°base/git/hooks/push/check_base_query_md.py` script wired via `.pre-commit-config.yaml`'s `stages: [pre-push]` + `files: ^ai/query\.md$` — pre-commit's single computed `from_ref`/`to_ref` range is sufficient for a single-path check.
  >    3. **checks 1–2's own hook is currently NOT chained in** (2026-09-28): `classify_branch` treats any branch not named `ai/UNCLEAN/...`/`ai/history/...` as **clean** format, and `base`'s own primary branch (`base`) falls into that bucket — but `base` legitimately contains almost nothing but AI-tainted commits (it's the tool producing clean/unclean/history splits for *consuming* repos, not a split output itself), so `check_content_policy` rejected essentially every push to `origin`. Attempted chaining it via pre-commit's legacy-hook mechanism, hit this immediately on the first real push, and reverted `.git/hooks/pre-push.legacy` back to the git-lfs-only script rather than leave `base` unpushable. Needs an explicit exemption for `base`'s own primary branch (or scoping the check to only run when this repo is acting as a split *source* for another target) before re-chaining. See `bak/ed9dde08b7f4` (tag, also pushed to origin) for the pre-incident state if this needs re-investigation.
- [x] I mean it's a bit more difficult as the codex memory seems to be only global for all projects, so I guess we need to listen to explicit add/update/delete commands/hooks to make sure we're getting it right? _(done)_
- [x] Uh oh, `• Running 19 PostToolUse hooks`, which end up in `• PostToolUse hook (failed)` with `error: hook timed out after 600s`. _(done)_
- [x] Record the other choosable options of a /plan: _(done)_
  >
  > - [x] Deny (without reason)
  > - [x] Deny (with reason)
  >       - Special case for Copilot: It's not possible to exit planning mode without entering something into the "i wanna change something" field, so a empty-like answer (e.g. single whitespace) should be treated as _without reason_.
  > - [x] Accept (with note)
  >       - If available modifiers like:
  >         - [ ] Reset conversation history and implement — Codex
  >         - [x] Use Autopilot (some model which confirms stuff for you) — Claude, Copilot; no Codex equivalent.
  >
  > Command-approval decisions with typed feedback are recorded too: Claude from its transcript and Copilot from its session event log. Codex follow-up text remains an ordinary prompt and is already logged.
- [x] allow repo-local paths in the global `ai/settings/sync_todos.json`. — `todo:359cd2de-c272-4e9e-a4f6-d5dcc2aeea3a` _(done; prio 5₍₉₎ medium)_
  > • Rather implement `ai/settings/sync_todos.repo.json`, which is another task.
  > • Close this task once that other task is done, too.
- [x] if the last commit already is a clean todo commit, `--amend` the new commit. — `todo:f6e1cc84-5df5-4eb3-bc87-4c0b8e302134` _(done; prio 5₍₉₎ medium)_
- [x] change wording in /todo-loop That's the planning file will automatically be copied. — `todo:c2227a34-850b-488f-a9b3-9837f7f8f3d8` _(done)_
  > Currently is often understood as task to manually do for the agent, which is wrong as the hook does it.
- [x] add support for `ai/settings/sync_todos.repo.json`, — `todo:9996eda5-960b-41fa-9d26-cc9fb3922fa4` _(done)_
  > which is an override per repo, meant to be commited.
  > - the local version is not (it allows for linking to other repository, which is a detail of the current computer/file system/folder layout of the User; hence it is not universal and therefore not fit for git)
  > - passes in it must start with ˋ./ˋ and not navigate further up.
  >   - a simple ˋ"."ˋ is valid, too.
  >   - if possible to validate that with jsonSchema (regex? Startswith & contains?) directly, you may just forbid any ˋ/..ˋ in the path.
  > - otherwise pydantic + Path will validate that upon run.
  > - opposed to the local file, it does not write for every known keyboard would just start with an empty dict
  >   - however as ˋ{\n}ˋ to allow optimal diff when adding entries.
  >   - oh, obviously with the whole structure, plus json schema wrapping and whatever.
  >   - but like no service/folder/tag configured/templated yet, but actually fully empty.
  > - the initial empty file is automatically committed
  > - if the script finishes without any matching (all ˋpath: nullˋ) repo to write, it shall instruct to add oneself (the local repository and/or it's subproject(s)) into that ˋ.repoˋ file
- [x] todos.md script should include the priority if set. — `todo:a4424413-2c35-4623-95ef-2927a5a03281` _(done)_
  > In a way that the numbers make sense.
  > I'm always confused if one or nine is the high priority.
  > As that explanation should be near that number in the same line. It must be brief. Very brief. If possible one word. Or two. Brief!
- [x] When running the todo sync script, show open todo count — `todo:ed8607fe-9744-4eff-946d-a43b77c7764b` _(done)_
  > • Current: `[base] up to date (33 todos)`
  > • Wan
  > • Wanted: `[base] up to date (33 todos, 2 open)`
  > • This shall also exclude todos marked as:
  > • waiting on someone else
  >   • ~~\`STATUS:NEEDS-ACTION\`~~ this is wrongly labeled by **eM Client**
  >   • `STATUS:DELEGATED`
  > • deferred
  >   • `STATUS:CANCELLED`
- [x] investigate post-merge hook eating `query.md` rename — `todo:f409b002-dca6-40c9-b09f-3297d620ac18` _(done)_
  > - In DockerTgBot
  > - Commits ffca32d7f657178629c9a514c5696e387951167e and back until the merge at 401815b9cf83a6fb35543d346a3f72396f7772bb
  > - The merge commit has swallowed the root `ai/query.md` rename.
- [ ] copy `/move-ai-to-project` SKILL from `DockerTgBot` — `todo:5ea80aaf-cbfd-4595-8125-c7c39d0fe80f`
  > Commits to cherry pick (add `[DockerTgBot]` attribution):
  > - 6b7a9b60000c674ceecebae778b6b5dd6f454f33
  > - c2c1d8af9ed32e2c722e57ce20f1f9cc0cc3a97f
