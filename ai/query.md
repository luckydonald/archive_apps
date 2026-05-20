# AI query log file

#### General AI development guidelines:
- Create `ai/PROGRESS.md`, and keep it updated when you complete steps.
- You may refer to `ai/refrences` for code examples of other plugins or extra documentation provided for this task.
- When writing code, follow these guidelines:
  - Always prefer the early-return pattern to reduce nesting of `if`s, etc.
  - Similarly, prefer `if …` -> `continue`/`return`/`break` early in loops over large nested blocks.
- _If_ the project requires a frontend, use Vue, TS, and SCSS for that.
  - Prefer using `<script setup lang="ts">` style single file components.
  - Use proper TypeScript type hinting.
- _If_ the project requires a backend, use modern Python `3.14+` for that.
  - Do proper type hinting with full type annotations.
  - For type-hinting, prefer the native types (e.g. `dict[str, int]` over the older `typing.*` aliases like `Dict[AnyStr, int]`)
  - Prefer async programming where possible.
  - For web stuff: `FastApi`
  - For postgres: typed `sqlalchemy`
    - For migrations: `alembic`
- Write tests for both frontend and backend parts.
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

❯ can't we making it use clonefile if supported? Sounds more efficient.

❯ Then use `CHECKSUM zip: exists` not `verified`, and do check it if `--verify-zips` is set (for all zips, not in the copy loop).
The checksum should be based on the zip's contents there. This is to confirm if the zip is written correctly. This would happen before the copy loop.

For normal operation, `CHECKSUM zip: found` is enough.
If there's no checksum, it should do `CHECKSUM zip: missing, creating…`, and do that (i think it does).

Then should be compared with that one of the actial Apllication, and then see if it's needs to be overwritten (asked) (i think it does).
when copying, that one can be used, and verifyied with the zip after writing, using the same logic as the initial loop.

❯ preceed the two loops with information of how many items need to be checked, and have a xxx/yyy in those.

❯  line 55: mapfile: command not found

❯ write it `VERIFY 001/123: file`, so that the verb comes first, archiving too.

❯ After the zip, show file size (human readable):

```txt
  Checking 153 app(s)…
  ARCHIVING 001/153: /Applications/Foo.app
    app: 12.4 MB
    SKIPPING ⚠️: no Info.plist
  ARCHIVING 002/153: Bar.app@2.1.zip
    ARCHIVE: found
    CHECKSUM: found
    app: 1.2 GB
    zip: 802 MB
    VERIFIED ✅: archived checksum matches current app
    MISSMATCH ❌: archived checksum does not match current app
  ARCHIVING 003/153: Baz.app@3.2.zip
    ARCHIVE: missing
    ZIP+HASH: created
    app: 998 KB
    zip: 332 KB
    CHECKSUM: written
    CREATED ✅: archived checksum matches app
    MISSMATCH ❌: archived checksum does not match original app

  And for --verify-zips with e.g. 42 zips:
  Verifying 42 zip(s)…
  VERIFY 01/42: Bar.app@2.1.zip
    EXTRACTED: done
    zip: 3.3 KB
    app:  45 KB
    VERIFIED ✅: checksum still matches expanded app.
    FAILED ❌: checksum differs
```
obviously it's always either VERIFIED or FAILED etc.

❯ when verifying checksums with the `--verify-zips` command, write a `_checksum_index_.txt`, where the checked zip and checksum files are added as checksums, too. That way we can create `--verify-changed` and `--verify-new`. For new, it will process all of those where app-zip and app-hash are not present in the root checksum file. For changed it calcualtes the hashes for the data dir, and all mismatches are checked again as well as the missing ones.

❯ I didn't see a `_checksum_index_.txt` be created? Only a `.tmp` one, but that seem to be deleted with `ctrl-c`...

❯ It doesn't seem to `INDEXED`-skip all of the apps... (only the mobile ones from the sample size of 3?)
For both cases write `app/zip: abcdef123...` and then `INDEXED ✅: already verified` or `CACHE-MISS 🔸: app` and/or `CACHE-MISS 🔸: zip`

❯ Uh, now it stops after 4 without a printed error? (the first one after pre-existing matching hashes)

❯ @ai/errors/4.md

❯ If you get `rm: /var/folders/jv/xthv_j4x7xx6rg_dgpyypqcr0000gn/T/tmp.MwCcfIfDGG: Directory not empty`, retry 5 times, 1s wait, then die

❯ Oh, fun new feature idea: Mark the files in Finder with the color labels. Probably `xattr` command or something. Actually, ignore this for now, will come back to this later.

❯ Another thought for another time, maybe-never: Freshly writing a zip file should write the checksums to the index too, so at least that would not be recomputed.

❯ /plan 
Check out @ai/errors/5.md , when I put the laptop to sleep, on the NAS connection.
That's a bit of a problem, now the index is an empty file, and at least some version of `.tmp` still exists.
1) guard writing 
   - both of those files
   - including a readback verification.
   - If it fails, ask to 
     - a)  retry (default selection)
          - this is for attempting the last write again
     - a') retry original (if you chose a different destination via _b)_, you can reset it and retry that one.
     - b)  save somewhere else
           - guarded as well, obviously, with same options
     - c)  skip
           - attempt one last time to write the file to tmp, and print the path if succeeded. Better than _not writing_.
           - if that fails too, print the contents to the terminal. Better than _literal nothing_.
           - contines operation as if it worked.
     - d)  exit
           - have the user confirm by typing 'sure' - if not, go back to the parent question.
           - this will still do the tmp/cat like c), but then exit with a status code.
2) Obviously don't remove the tmp file, if the write of the proper one failed (including _c)_).
3) Add recovery code, which will restore a tmp one to the live one, if present
   - ask for confirmation on each of the steps of that.
   1) Found a temp file, wanna restore that?
   2) actual file is empty, wanna merge?
   3) Temporary file: X lines\nExisting file: Y lines\nMerge duplicates: D lines\nResulting files: T lines\nWanna continue?

❯ Do not fill my disk pls.

❯ you tested?

❯ the dest dir is settable - and your plan outlined how to test - what's missing?

❯ /plan The script is failing for xcode.zip, which is `4.5 GB` (!).
What are ways to reduce or remove disk space usage?
I.e. copying the zip, extracting the zip.
What are options to do shizzle like that on-the-fly?

❯ Like, asume the 4GB zip is on the NAS, but my hdd has 2GB free.
Unzipping on the NAS is not an option, as it's keeping a file history, and creating & deleting the zip contents would spam the file version storage of the NAS.

❯ Why do we need to use the original name?

❯ Hold on - I wanted that cosmetic with the app version in the ZIP - why remove it now?

❯ Application name can be Unicode, right?

❯ HAve recovery ask to also delete the tmp file after successful merge

❯ Error: Bad magic number for file header
  SKIPPED ⚠️: zip not readable or corrupt

❯ I'd rather have it properly parse the zip? @ai/errors/6.md

