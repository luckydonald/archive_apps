# git_remote_fix script

## Table of contents

* [git_remote_fix script](#git_remote_fix-script)
  * [Table of contents](#table-of-contents)
  * [Prompt](#prompt)
  * [GUI examples:](#gui-examples)
    * [multiple, all off](#multiple-all-off)
      * [multiple, all off: style](#multiple-all-off-style)
      * [multiple, all off: _boxy_](#multiple-all-off-_boxy_)
      * [multiple, all off: _rounded_](#multiple-all-off-_rounded_)
    * [Multiple, default](#multiple-default)
      * [multiple, default: style](#multiple-default-style)
      * [multiple, default: _boxy_](#multiple-default-_boxy_)
      * [multiple, default: _rounded_](#multiple-default-_rounded_)
    * [Current selection](#current-selection)
      * [Current selection: style](#current-selection-style)
        * [current selection: style](#current-selection-style-1)
        * [current selection: _boxy_](#current-selection-_boxy_)
        * [current selection: _rounded_](#current-selection-_rounded_)
      * [Current selection: colors](#current-selection-colors)
    * [Text Box](#text-box)
      * [Text Box: style](#text-box-style)
        * [Text Box: _no blink_](#text-box-_no-blink_)
      * [text box: _cursor blink, within text_](#text-box-_cursor-blink-within-text_)
      * [text box: _cursor blink, after text_](#text-box-_cursor-blink-after-text_)
      * [text box: _cursor blink, in front of text_](#text-box-_cursor-blink-in-front-of-text_)
      * [text box: colors](#text-box-colors)
    * [Checkboxes](#checkboxes)
      * [Checkbox 1st Level (here: `git remote`)](#checkbox-1st-level-here-git-remote)
        * [Checkbox 1st Level: style: _boxy_](#checkbox-1st-level-style-_boxy_)
          * [Checkbox 1st Level: _boxy_, _unchecked_](#checkbox-1st-level-_boxy_-_unchecked_)
          * [Checkbox 1st Level: _boxy_, _checked_](#checkbox-1st-level-_boxy_-_checked_)
          * [Checkbox 1st Level: _boxy_, _partial_](#checkbox-1st-level-_boxy_-_partial_)
          * [Checkbox 1st Level: _boxy_, _disabled_](#checkbox-1st-level-_boxy_-_disabled_)
        * [Checkbox 1st Level: style: _rounded_](#checkbox-1st-level-style-_rounded_)
          * [Checkbox 1st Level: _rounded_, _unchecked_](#checkbox-1st-level-_rounded_-_unchecked_)
          * [Checkbox 1st Level: _rounded_, _checked_](#checkbox-1st-level-_rounded_-_checked_)
          * [Checkbox 1st Level: _rounded_, _partial_](#checkbox-1st-level-_rounded_-_partial_)
          * [Checkbox 1st Level: _rounded_, _disabled_](#checkbox-1st-level-_rounded_-_disabled_)
        * [Checkbox 1st Level: color](#checkbox-1st-level-color)
      * [Checkbox 2nd Level (here: url type, `"pull"` or `"push"`)](#checkbox-2nd-level-here-url-type-pull-or-push)
        * [Checkbox 2nd Level: style: _boxy_](#checkbox-2nd-level-style-_boxy_)
          * [Checkbox 2nd Level: _boxy_, _unchecked_](#checkbox-2nd-level-_boxy_-_unchecked_)
          * [Checkbox 2nd Level: _boxy_, _checked_](#checkbox-2nd-level-_boxy_-_checked_)
          * [Checkbox 2nd Level: _boxy_, _partial_](#checkbox-2nd-level-_boxy_-_partial_)
          * [Checkbox 2nd Level: _boxy_, _disabled_](#checkbox-2nd-level-_boxy_-_disabled_)
        * [Checkbox 2nd Level: style: _rounded_](#checkbox-2nd-level-style-_rounded_)
          * [Checkbox 2nd Level: _rounded_, _unchecked_](#checkbox-2nd-level-_rounded_-_unchecked_)
          * [Checkbox 2nd Level: _rounded_, _checked_](#checkbox-2nd-level-_rounded_-_checked_)
          * [Checkbox 2nd Level: _rounded_, _partial_](#checkbox-2nd-level-_rounded_-_partial_)
          * [Checkbox 2nd Level: _rounded_, _disabled_](#checkbox-2nd-level-_rounded_-_disabled_)
        * [Checkbox 2nd Level: color](#checkbox-2nd-level-color)
      * [Checkbox 3rd Level (here: url type, `"pull"` or `"push"`)](#checkbox-3rd-level-here-url-type-pull-or-push)
        * [Checkbox 3rd Level: style](#checkbox-3rd-level-style)
        * [Checkbox 3rd Level: color](#checkbox-3rd-level-color)
      * [Checkboxes: color](#checkboxes-color)
    * [Actions](#actions)
      * [Check all/none](#check-allnone)
        * [Check all/none: style](#check-allnone-style)
          * [Check all/none: _boxy_](#check-allnone-_boxy_)
          * [Check all/none: _rounded_](#check-allnone-_rounded_)
        * [Check all/none: style](#check-allnone-style-1)
          * [Check all/none: _rounded_](#check-allnone-_rounded_-1)
        * [Check all/none: style](#check-allnone-style-2)
<!-- TOC -->

## Prompt
› write me a scripts in ai/scripts which allows me to insert a username into a github remote url. It shall:
1. ask which urls to change in a togglable multi list
   - for each origin display the remote name, and then the fetch & pull url
   - default: all https://github.com without a username set yet) - as a multi select
   - Have the push/pull urls be displayed below, and selected automatically, too if they match
2. For each selected item, fix the url as specified (`username@` and/or `.git`)


## GUI examples:

### multiple, all off
#### multiple, all off: style
#### multiple, all off: _boxy_
```text
Enter the git username to use:
  ┌───┬──────────────────────────────────────────┐
  │ ✎ │ luckydonald                              │
  ╘═══╧══════════════════════════════════════════╛

Select the remote urls to change:

  ▽ origin
  ├─╴ □ fetch: https://github.com/luckydonald/base
  │   └─╴ □ Add .git suffix
  └─╴ □ push:  https://github.com/luckydonald/base.git

  ▽ empty
  ├─╴ □ fetch: https://someone@github.com/EmptyAAS/empty
  │   └─╴ □ Add .git suffix
  └─╴ □ push:  https://luckydonald@github.com/EmptyAAS/empty
      └─╴ □ Add .git suffix

  ▽ template
  ├─╴ ⬚ fetch: ../hoass_template
  └─╴ □ push:  https://github.com/luckydonald/hoass_plugin-template.git

  ▽ clock
  ├─╴ □ fetch: https://luckydonald@github.com/luckydonald/hoass_calendar-alarm-clock.git
  └─╴ □ push:  https://luckydonald@github.com/luckydonald/hoass_calendar-alarm-clock.git

 ▣ Check all
 ⊡ Check none
```
#### multiple, all off: _rounded_
```text
Enter the git username to use:
  ╭───┬──────────────────────────────────────────╮
  │ ✎ │  luckydonald                             │
  ╰━━━┷━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯

Select the remote urls to change:

  ◎ origin
  ├─╴ ○ fetch: https://github.com/luckydonald/base
  │   ╰─╴ ○ Add .git suffix
  ╰─╴ ○ push:  https://github.com/luckydonald/base.git

  ◎ empty
  ├─╴ ○ fetch: https://luckydonald@github.com/EmptyAAS/empty
  │   ╰─╴ ○ Add .git suffix
  ╰─╴ ○ push:  https://luckydonald@github.com/EmptyAAS/empty
      ╰─╴ ○ Add .git suffix

  ◎ template
  ├─╴ ◌ fetch: ../hoass_template
  ╰─╴ ○ push:  https://github.com/luckydonald/hoass_plugin-template.git

  ◎ clock
  ├─╴ ○ fetch: https://luckydonald@github.com/luckydonald/hoass_calendar-alarm-clock.git
  └─╴ ○ push:  https://luckydonald@github.com/luckydonald/hoass_calendar-alarm-clock.git

 ◉ Check all
 ◎ Check none
```


### Multiple, default
#### multiple, default: style
#### multiple, default: _boxy_
```text
Enter the git username to use:
  ┌───┬──────────────────────────────────────────┐
  │ ✎ │ luckydonald                              │
  ╘═══╧══════════════════════════════════════════╛

Select the remote urls to change:

  ⏷ origin
  ├─╴ ■ fetch: https://github.com/luckydonald/base
  │   └─╴ ■ Add .git suffix
  └─╴ ■ push:  https://github.com/luckydonald/base.git

  ⧩ empty
  ├─╴ ◪ fetch: https://luckydonald@github.com/EmptyAAS/empty
  │   └─╴ ■ Add .git suffix
  └─╴ ◪ push:  https://luckydonald@github.com/EmptyAAS/empty
      └─╴ ■ Add .git suffix

  ⧩ template
  ├─╴ ⬚ fetch: ../hoass_template
  └─╴ ■ push:  https://github.com/luckydonald/hoass_plugin-template.git

  ▽ clock
  ├─╴ □ fetch: https://luckydonald@github.com/luckydonald/hoass_calendar-alarm-clock.git
  └─╴ □ push:  https://luckydonald@github.com/luckydonald/hoass_calendar-alarm-clock.git

 ▣ Check all
 ⊡ Check none
```
#### multiple, default: _rounded_
```text
Select the remote urls to change:

  ◉ origin
  ├─╴ ● fetch: https://github.com/luckydonald/base
  │   ╰─╴ ● Add .git suffix
  ╰─╴ ● push:  https://github.com/luckydonald/base.git

  ◉ empty
  ├─╴ ◒ fetch: https://luckydonald@github.com/EmptyAAS/empty
  │   ╰─╴ ● Add .git suffix
  ╰─╴ ◒ push:  https://luckydonald@github.com/EmptyAAS/empty
      ╰─╴ ● Add .git suffix

  ◑ template
  ├─╴ ◌ fetch: ../hoass_template
  ╰─╴ ● push:  https://github.com/luckydonald/hoass_plugin-template.git

  ◎ clock
  ├─╴ ○ fetch: https://luckydonald@github.com/luckydonald/hoass_calendar-alarm-clock.git
  └─╴ ○ push:  https://luckydonald@github.com/luckydonald/hoass_calendar-alarm-clock.git

 ◉ Check all
 ◎ Check none
```

### Current selection
#### Current selection: style
##### current selection: style
##### current selection: _boxy_
```text
   ▣ origin
⪢  ▣ origin
   ▣ origin
```
##### current selection: _rounded_
```text
   ◉ origin
⋑  ◉ origin
   ◉ origin
```

#### Current selection: colors
- The index marker (`⪢⋑`) is colorized,
- the rest of the line stays as is.

### Text Box
The Text field has a blinking cursor
That one is the same for boxy and
#### Text Box: style
##### Text Box: _no blink_
Either not in the blink state (toggles 1x seconds),
or not the active element.
```text
  ┌──────────────┐
  │ luckydonald  │
  ╘══════════════╛
```

#### text box: _cursor blink, within text_
```py
text = "luckydonald"
position = 4
```
```text
  ┌──────────────┐
  │ luck▎donald  │
  ╘══════════════╛
```
#### text box: _cursor blink, after text_
```py
text = "luckydonald"
position = 12
```
```text
  ┌──────────────┐
  │ luckydonald▁ │
  ╘══════════════╛
```
#### text box: _cursor blink, in front of text_
```py
text = "luckydonald"
position = 0
```
```text
  ┌──────────────┐
  │ ▎uckydonald  │
  ╘══════════════╛
```
#### text box: colors
The border and the cursor are colorized (`┌─┬┐│╘╧═╛` and `▎▁`) id active.
The text stays default color.




### Checkboxes
#### Checkbox 1st Level (here: `git remote`)
##### Checkbox 1st Level: style: _boxy_
###### Checkbox 1st Level: _boxy_, _unchecked_
```
▽ origin
└─ …
```
###### Checkbox 1st Level: _boxy_, _checked_
```
⏷ origin
└─ …
```
###### Checkbox 1st Level: _boxy_, _partial_
```
⧩ origin
└─ …
```
###### Checkbox 1st Level: _boxy_, _disabled_
```
⥐ origin
└─ …
```
##### Checkbox 1st Level: style: _rounded_
###### Checkbox 1st Level: _rounded_, _unchecked_
```
◎ origin
╰─ …
```
###### Checkbox 1st Level: _rounded_, _checked_
```
◉ origin
╰─ …
```
###### Checkbox 1st Level: _rounded_, _partial_
```
◑ origin
╰─ …
```
###### Checkbox 1st Level: _rounded_, _disabled_
```
◠ origin
╰─ …
```
##### Checkbox 1st Level: color
- If selected, the checkbox symbol (`▽⏷⧩⥐`/`◎◉◑◠`) is colorized.
- For that special value, the remote value is `code`-like, so it's also always colorized.




#### Checkbox 2nd Level (here: url type, `"pull"` or `"push"`)
##### Checkbox 2nd Level: style: _boxy_
###### Checkbox 2nd Level: _boxy_, _unchecked_
```text
└─╴  push
    └─ …
```
###### Checkbox 2nd Level: _boxy_, _checked_
```text
└─╴ ■ push
    └─ …
```
###### Checkbox 2nd Level: _boxy_, _partial_
```text
└─╴ ◪ push
    └─ …
```
###### Checkbox 2nd Level: _boxy_, _disabled_
```text
└─╴ ⬚ push
    └─ …
```


##### Checkbox 2nd Level: style: _rounded_
###### Checkbox 2nd Level: _rounded_, _unchecked_
```text
╰─╴ ○ push
    ╰─ …
```
###### Checkbox 2nd Level: _rounded_, _checked_
```text
╰─╴ ● push
    ╰─ …
```
###### Checkbox 2nd Level: _rounded_, _partial_
```text
╰─╴ ◒ push
    ╰─ …
```
###### Checkbox 2nd Level: _rounded_, _disabled_
```text
╰─╴ ◌ push
    ╰─ …
```

##### Checkbox 2nd Level: color
- If selected, the checkbox symbol (`□■◪⬚`/`○●◒◌`) is colorized.
- For that special value, the value stays mostly default, only the actual URL is colorized and underlined.






#### Checkbox 3rd Level (here: url type, `"pull"` or `"push"`)
##### Checkbox 3rd Level: style
Same as 2nd level.

##### Checkbox 3rd Level: color
- If selected, the checkbox symbol (`□■◪⬚`/`○●◒◌`) is colorized.
- For that special value, the contains `.git` which should be colorized.


#### Checkboxes: color
- If selected, the checkbox symbol is colorized.
- Otherwise, the colorisation of the content is not modified.


### Actions
#### Check all/none
##### Check all/none: style
###### Check all/none: _boxy_
```text
 ▣ Check all
 ⊡ Check none
```

###### Check all/none: _rounded_
```text
 ◉ Check all
 ◎ Check none
```

##### Check all/none: style
- The icon (`▣⊡◉◎`) is always colorized
- The text label is only colorized if not everything is selected/deselected yet (i.e. activating it would have an effect)


```text
 ▣ Check all
 ⊡ Check none
```

###### Check all/none: _rounded_
```text
 ◉ Check all
 ◎ Check none
```

##### Check all/none: style
- The icon (`▣⊡◉◎`) is always colorized
- The text label is only colorized if not everything is selected/deselected yet (i.e. activating it would have an effect)
