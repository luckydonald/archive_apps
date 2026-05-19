# Interactive GitHub Remote Username Rewriter

## Summary
Implement a single-file executable Python CLI at `ai/scripts/git_remote_fix.py` that scans the current git repo, shows an interactive full-screen TUI for fetch/push remotes, lets the user choose where to insert or replace `username@` and where to append `.git`, previews the final URL changes, and only then applies them with `git remote set-url`.

The script should use `prompt_toolkit` for the TUI. Because the repo has no Python packaging metadata, the script should self-bootstrap: on startup, if `prompt_toolkit` import fails and `uv` is available, rerun itself via `uv run --with prompt_toolkit python <script> ...`; if that rerun fails, print the exact fallback command and exit non-zero.

## Key Changes
- Add `ai/scripts/git_remote_fix.py` with:
  - shebang and executable entrypoint
  - `argparse` support for `--username` and `--theme {rounded,boxy}`
  - startup bootstrap for missing `prompt_toolkit`
  - git repo detection via `git rev-parse --show-toplevel`
  - remote discovery via `git remote`, `git remote get-url <name>`, and `git remote get-url --push <name>`
- Model the UI as a 3-level tree:
  - level 1: remote name
  - level 2: `fetch` and `push` URL rows
  - level 3: optional `Add .git suffix` child under each eligible URL row
  - plus footer actions: `Check all`, `Check none`, `Preview changes`, `Cancel`
- Treat URL rows as eligible only when they match `https://[userinfo@]github.com/<owner>/<repo>[.git]`.
  - Non-HTTPS, non-`github.com`, or local-path remotes are shown but disabled.
  - Always render both fetch and push rows, even if they currently have the same URL.
- Default username textbox value:
  - `--username` if provided
  - else first existing GitHub HTTPS remote username found in current remotes
  - else `git config --get github.user`
  - else `git config --get user.name`
  - else empty string
- Default selection rules:
  - URL row starts checked only if the URL is eligible and currently has no username.
  - `.git` child starts checked only if the URL is eligible and currently lacks `.git`.
  - If only the `.git` child is selected, the URL row renders as partial.
  - Existing different usernames are preserved by default; they change only if the user explicitly checks that URL row.
- Rewrite behavior:
  - parse with `urllib.parse`
  - if a URL row is selected, replace any existing userinfo with the entered username
  - if the `.git` child is selected and the path lacks `.git`, append `.git`
  - preserve scheme, host, owner, repo path, and fetch/push distinction
  - never touch disabled rows
  - never remove `.git`, never convert SSH remotes, never rewrite non-`github.com` hosts in v1
- TUI behavior:
  - full-screen `prompt_toolkit` app
  - default theme: `rounded`; `boxy` is the alternate glyph set
  - theme changes only glyphs and icons, not behavior
  - focus order: username input -> tree -> footer actions
  - keys:
    - `Tab` and `Shift-Tab`: change focus
    - `Up` and `Down`: move current row
    - `Space`: toggle current checkbox or action
    - `Enter`: activate focused footer action
    - `a`: check all
    - `n`: check none
    - `q` or `Esc`: cancel
  - use `prompt_toolkit` cursor support for the username field
- Preview and apply flow:
  - `Preview changes` opens a second screen or pane listing only changed entries as `remote / fetch|push: old -> new`
  - actions on preview screen: `Apply`, `Back`, `Cancel`
  - `Apply` runs only the necessary commands:
    - `git remote set-url <remote> <new_url>` for fetch
    - `git remote set-url --push <remote> <new_url>` for push
  - skip commands where the URL is unchanged

## Test Plan
- Add unit tests for:
  - GitHub HTTPS URL eligibility detection
  - username extraction and defaulting helpers
  - URL rewrite cases:
    - no username and no `.git`
    - existing username and missing `.git`
    - wrong username replaced when selected
    - existing correct username preserved when URL row is not selected
    - non-GitHub and local-path URLs untouched
- Add integration tests using temp git repos:
  - distinct fetch and push URLs update independently
  - disabled rows do not produce `git remote set-url`
  - preview contains only changed rows
  - apply step updates `.git/config` as expected
- Manual smoke scenarios:
  - current repo with `origin` and `empty`
  - one remote already fully correct
  - one remote with local-path fetch and GitHub push
  - missing `prompt_toolkit` path triggers `uv run --with prompt_toolkit ...`

## Assumptions
- The script name is `ai/scripts/git_remote_fix.py`.
- v1 supports only the effective fetch URL and effective push URL reported by `git remote get-url`; multi-valued `remote.<name>.url` or multiple `pushurl` entries are out of scope.
- `uv` is expected to be present for auto-bootstrap; if not, the script fails with an exact install or run command.
- No repo-level `pyproject.toml` or package layout is added; this remains a standalone script.
- `rounded` is the default visual theme.
