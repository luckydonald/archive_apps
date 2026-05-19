› /plan Implement a python script for @ai/template/by-feature/git_remote_fix/init.md
› Name it `git_remote_fix` though, copy your plan to @ai/template/by-feature/git_remote_fix/plan.md , then continue implementing `git_remote_fix.py`.
› Commit after milestones and steps done, format '[base] ai: run: <message>'. Rather do many commits than too little.

› I moved the tests for that script into ai/scripts/tests, document with a README.md in that folder how to launch it.

› Write TTD tests:
1. The name field and select and check all/none should be all reachable via up/down move as well
2. start with input focus at name field (last character upon focus)
3. There's 2 spaces too much after the username, the ending `│` is two chars to much to the right.
4. down arrow goes to multi-select
5. up arrow from top multi-select goes back to username field
6. up arrow in multi-select should to the next item, scroll if needed
7. scrollable area is git username edit field and the multiselect, only excluding the gray hotkey footer (Tab focus, Up/down move, …)
8. The indicator has correct color
9. Wrong color for `code` stuff (i.e. `.git` or `<remote name>` are wrongly blue; should be highlight color [aka. pink])
10. Wrong color for active checkboxes (are in green/aqua; should be highlight color [aka. pink])
11. do not colorize _partial_ and _disabled_ icons, unless focused.
12. do not colorize parent selection icons, unless directly focused.
13. down arrow from last multi-select item goes to Check all (indicator moves there too.)
14. the `▎` / `▁` indicator (`ai/template/by-feature/git_remote_fix/init.md`, _cursor blink_ sections) are not implemented it seems.
15. That cursor (and when blink is off, the character there) shall be colored in the highlight color (pink)
16. The icons of check all/none should not be colorized if not focused.
17. between `Check all` and `Check none` should not be an empty line.
18. Tab and shift-tab to switch between input groups is good, keep.
19. The `a check all`, `n check none`, `q cancel` should not be available (= not shown or strikethrough) when in the text edit field.
20. The text edit border color on focus is green/aqua, not pink (highlight).
21. write the key codes as `tab)  focus`, `A)  check all`, `Q|ESC)  cancel`, `Enter) next element/submit` etc.
22. Enter in the text field shall go to the multi-select, too.
23. Shortly (`0.25s`) invert hotkeys upon clicking them, like the macOS menu bar does.
24. Add a [ Submit → ] button, as 4th group. Again embedded into the up/down and the tab logic.
25. The submit button is all-colorized (pink) on focus, and inverts for `0.25s` after clicking before we go to the next "page".
26. Use `↑` (`UPWARDS ARROW`) and `↓` (`DOWNWARDS ARROW`) instead of `Up` and `Down` for moveing the focus
27. If in edit field, add `←` (`LEFTWARDS ARROW`) and `→` (`RIGHTWARDS ARROW`) for moving the cursor
28. (Removed)
29. Use `␛` (`SYMBOL FOR ESCAPE`) for escape.
30. Use `MATHEMATICAL MONOSPACE SMALL` characters for alphanumeric-single-char keys, (i.e. for `q` show `𝚚` (`MATHEMATICAL MONOSPACE SMALL Q`: `𝚚`))
31. Use `⏎` (`RETURN SYMBOL`) for Enter
32. Use `⇥` (`RIGHTWARDS ARROW TO BAR`) for Tab
33. Use `⟯` (`MATHEMATICAL RIGHT FLATTENED PARENTHESIS`) instead of the normal `)` between character and label.

› Already better. But there's still stuff to fixx; let's do round 3:
1. Add a `r) refresh` command, which redraws the whole gui, in case something got stuck

› Let's do round 3 of fixes (cont'd):
- remember to start with _Writing and committing TTD tests_
2. I would expect `r` to completely clear the screen and draw it all from scratch, based on the current state.
3. When quickly going past two lines always get stuck displaying something else:
   - a) origin checkbox
     - Directly under `Select the remote urls to change:`
     1) unfocused
        - unfocused should: `     ◎ empty`
        - unfocused actual: `⋑      e◎ ty`
     2) focused
        - focused should: `⋑    ◎ empty`
        - focused actual: `⋑    ◎ e◎ ty`
     - Both issues appear after passing over it once.
   - b) check all
     - The first of the two
     - but not "check none"
     1) unfocused
        - unfocused should: `    ◉ Check all`
        - unfocused actual: `⋑      h◉ Check all`
     2) focused
        - focused should: `⋑   ◉ Check all`
        - focused actual: `⋑   ◉ Check all all`
   - c) Text box
     - Direct after `Enter the git username to use:`
       1) unfocused
          - unfocused should (1/3): `  ╭───┬────────────────────────────────────────╮`
          - unfocused should (2/3): `  │ ✎ │ luckydonald                            │`
          - unfocused should (3/3): `  ╰━━━┷━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯`
          - unfocused actual (1/3): `  ╭╭───┬────────────────────────────────────────╮`
          - unfocused actual (2/3): `  │ ✎ │ luckydonald                              │`
          - unfocused actual (3/3): `  ╰━━━┷━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯`
       2) focused
          - focused should: _(same as **unfocused should**)_
          - focused actual (1/3): `  ╭╭───╭───┬────────────────────────────────────────╮`
          - focused actual (2/3): `  │ ✎ │ luckydoonal▁▁                            │`
          - focused actual (3/3): `  ╰━━━┷━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯`
4. 2nd level _active_ state has wrong icon. Here's a full test sequence:
   1. Given a push or fetch, which has a `.git` suffix, both currently turned off
   2. Observe:
      1. State: push: off, suffix off
      2. both have the `○` icon. (correct)
   3. Toggle the _suffix_ option _on_
   4. Observe:
      1. State: push: off, suffix on
      2. `◒` push and `●` suffix (correct)
   5. Toggle the _fetch/push_ option _on_
   6. Observe:
      1. State: push: on, suffix on
      2. `●` push and `●` suffix (correct)
   7. Toggle the _suffix_ option _off_ again.
   8. Observe:
      1. State: push: on, suffix off
      2. `◒` push and `○` suffix (incorrect!)
      - Correct would be:  `●` push and `○` suffix (`init.md` spec)
      - Implement instead: `◓` push and `○` suffix (actually better)
   - Write this as test first (accepting both `◓` and `●` for step 8.), then fix it.

› Let's do round 3 of fixes (cont'd 2):
- remember to start with _Writing and committing TTD tests_.
- commit after each step where it makes sense
- at least commit after each todo number below, you can commit more often.
5. now it seems to refresh everything on every input, leading to a lot of flickering.
   - At least limit it to the current focused/unfocused elements, so a local refresh only
   - and only if it's the problematic ones (text bar, each first level remote name, Check all)
6. still 2 spaces/chars too much inside the text box, extend top/bottom border by 2 characters
7. Make the text box grow up to the end of the terminal (padding -2 cols) if more text is entered
8. If more text is entered into the text box, 'scroll' the text, via `…` symbol in the front/back as needed.
   - The empty space to add (blinking `▁`) should always still have space at the end
9. Fix the text field cursor not blinking once per second but being static.

› Let's do round 3 of fixes (cont'd 3):
- remember to start with _Writing and committing TTD tests_.
- commit after each step where it makes sense
- at least commit after each todo number below, you can commit more often.
10. `^C` should do the same as `q`, too.
11. It's not really redrawing those components correctly. I really want to refresh exactly those elements as requested.
    1. Pointer to the start row index
    2. Command to move pointer to the beginning of the row
    3. Clear the current row
    4. re-write the current row
    5. Repeat from **1.** for every row.
12. The blinking finally works, but the then updated text is printed 1 character too much to the right.
    - so pos `- 1` or something.
13. Moving up/down via scroll wheel no longer works, this was working before.
14. The level-2 checkboxes (suffix) are colorized even if they are not selected, fix that
15. Scrolling text field + checkboxes when the focus gets out of visible bounding box does not work
    - preferably keeping the current input field centered-ish
    - of course the ends should end up at the end, no overscroll

› Let's do round 4 of fixes:
- remember to start with _Writing and committing TTD tests_.
- commit after each step where it makes sense
- commit message here in the `base` repo shall be as follows:
  - always start with `[base] ai: run: `
  - a short summary
  - followed by the fix round and the step
  - linebreak
  - followed by a detailed in the second+ lines of the summary, with as many lines as needed.
- at least commit after each TODO number below, you can commit more often.
1. The custom element re-render of the level-1 (remote) checkboxes seems to write on the line above where it would need to and this shift everything below by one line to high.
   - at least the differential updates seems to actually run for their own lines (even if those are not yet matching the old ones)
   - maybe the shift is also a factor, as a further down remote checkbox is way further off.
   - see also 2.
2. leaving the text box eats 3 rows.
   - but it then writes it to the correct horizontal position
   - after already deleting (hence shifting the content up by) 3 lines
   - probably the row-clear is actually removing the linebreak (or similar) as well, instead of clearing the line but letting it exist as empty row.
3. The text box rendering does not start in the first column. Is the "move-to-line-start" command wrong?
4. write a test which tests those
   - for a few constructed git payloads (see the `init.md` examples)
   - for a few terminal heights
   1. record that output buffer
   2. then move down once
   3. move back up
   4. compare that it's still the same
   - possibly you need to use a library which can merge/simulate the terminal (especially the escape-sequence cursor jumping stuff) to give a "fully rendered"/"fully merged" result to compare in `3.4.`
   - repeat the test with moving down and back up 2 times.
   - repeat the test with moving down all the way to the end (check none) and back up.
   - that way you can immediately test if the rendering is wrong.

› Instead of that homegrown terminal emulator `FakeOutput` and more `Fake*` classes in the tests ( @ai/scripts/tests/test_git_remote_fix_tui_tdd.py ) use `pyte`:
- with local documentation available at:
  - @ai/references/https/pyte.readthedocs.io/en/0.8.1-dev/tutorial.html.md
  - @ai/references/https/pyte.readthedocs.io/en/0.8.1-dev/api.html.md
- Probably `stream.feed(…)`, `screen.cursor.x/y`, `screen.cursor.attrs` and `screen.display` might be helpful.
› While extracting those terminal tests, move them to their own file for clarity.
› well, I expect the tests to fail, that's why we switch parsers, so we can actually fix the output. Commit before attempting to dive into those issues first.
