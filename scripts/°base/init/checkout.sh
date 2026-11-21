#!/usr/bin/env bash
# scripts/°base/init/checkout.sh
#
# One-shot repo setup: installs git hooks (pre-commit framework + git-lfs)
# and cleans up stale yorkie hooks left behind by the old Vue CLI tooling.
#
# Intended to be run:
#   - By the Claude SessionStart hooks (automatic)
#   - After `git clone` / `git checkout` (manual or via post-checkout)
#   - Idempotent: safe to run multiple times.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
# In a linked worktree `.git` is a file and the hooks live in the shared common dir, so ask git instead of building the path.
HOOKS_DIR="$(git rev-parse --path-format=absolute --git-path hooks)"
COMMON_DIR="$(git rev-parse --path-format=absolute --git-common-dir)"
TOOL_PATH_PREFIX="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.pyenv/shims:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin"
export PATH="$TOOL_PATH_PREFIX:$PATH"

# ─── 0. Ensure required git origins are configured ──────────────────────────
REQUIRED_ORIGINS=(
  "base https://github.com/luckydonald/base.git"
  "empty https://github.com/EmptyAAS/empty.git"
)

ensure_required_origins() {
  local name url origin_url remote
  origin_url="$(git remote get-url origin 2>/dev/null || true)"
  for remote in "${REQUIRED_ORIGINS[@]}"; do
    name="${remote%% *}"
    url="${remote#* }"
    # Skip if origin already covers this URL (e.g. in the base repo itself)
    [ "$origin_url" = "$url" ] && continue
    if ! git remote get-url "$name" >/dev/null 2>&1; then
      echo "Adding missing remote '$name' -> $url"
      git remote add "$name" "$url"
    fi
  done
}

ensure_required_origins

# ─── 1. Remove stale yorkie hooks ───────────────────────────────────────────
# Yorkie is no longer installed. Its hooks reference node_modules/yorkie which
# doesn't exist. Remove them so they don't interfere with pre-commit or git-lfs.
remove_yorkie_hooks() {
  local hook_file
  for hook_file in "$HOOKS_DIR"/*; do
    [ -f "$hook_file" ] || continue
    # Skip .sample files
    [[ "$hook_file" == *.sample ]] && continue
    # Check if it's a yorkie hooks
    if head -2 "$hook_file" | grep -q '#yorkie'; then
      rm "$hook_file"
    fi
  done
}

remove_yorkie_hooks

HOOK_PATH='export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.pyenv/shims:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:$PATH"'

# ─── 2. Make generated hooks find user-installed tools ──────────────────────
# IDEs can invoke Apple's/Xcode's git with a restricted PATH. Add the common
# macOS install locations used by pyenv, uv, Homebrew, and user-local tools so
# hook commands match the normal interactive shell more closely.
add_path_to_pre_commit_hooks() {
  local hook_name hook_file tmp_file
  for hook_name in pre-commit commit-msg post-merge post-rewrite; do
    hook_file="$HOOKS_DIR/$hook_name"
    [ -f "$hook_file" ] || continue
    grep -q 'hook-impl' "$hook_file" || continue
    # Already patched: leave the hook alone (patching is idempotent, nothing is rewritten on later runs).
    grep -q 'AllMyStorage hook PATH' "$hook_file" && continue

    tmp_file="${hook_file}.tmp.$$"
    {
      IFS= read -r first_line || true
      printf '%s\n' "$first_line"
      printf '# AllMyStorage hook PATH for IDE/Xcode Git environments.\n'
      printf '%s\n' "$HOOK_PATH"
      cat
    } <"$hook_file" >"$tmp_file"
    chmod +x "$tmp_file"
    mv "$tmp_file" "$hook_file"
  done
}

# git-lfs installs hooks that fail when Apple's/Xcode's git runs them without
# Homebrew on PATH. Keep the LFS commands active, but make sure those hooks can
# find git-lfs from normal macOS install locations first.
repair_git_lfs_hooks_path() {
  local hook_name hook_file lfs_command
  # `post-merge.legacy` is where pre-commit parks git-lfs's `post-merge` stub once it installs its own.
  for hook_name in post-checkout post-commit post-merge pre-push post-merge.legacy; do
    hook_file="$HOOKS_DIR/$hook_name"
    [ -f "$hook_file" ] || continue
    # A symlinked hook is a tracked script of the repo (e.g. `.hooks/pre-push.bash`), not a git-lfs stub:
    # `cat >` would write through the link and overwrite the tracked file.
    [ -L "$hook_file" ] && continue
    if grep -q 'git lfs' "$hook_file" && grep -q 'git-lfs' "$hook_file"; then
      lfs_command="${hook_name%.legacy}"
      cat >"$hook_file" <<EOF
#!/bin/sh
# AllMyStorage hook PATH for IDE/Xcode Git environments.
$HOOK_PATH
command -v git-lfs >/dev/null 2>&1 || { echo >&2 "git-lfs was not found on PATH for the $lfs_command hook."; exit 2; }
git lfs $lfs_command "\$@"
EOF
      chmod +x "$hook_file"
    fi
  done
}

# ─── 2b. One setup at a time per repository ───────────────────────────────
# Every worktree and agent runs this script at session start, and all of them write the same shared hooks directory.
# `pre-commit install` truncates the hook before it rewrites it, so a second installer in that window finds an empty
# file, decides it is not a pre-commit script and parks it as `<hook>.legacy`. The result is a pre-commit script that
# runs itself in "migration mode" and fails every commit with "pre-commit's script is installed in migration mode".
# A `mkdir` lock (atomic, also on macOS without `flock`) keeps the installers apart; a lock older than 2 minutes is stale.
LOCK_DIR="$COMMON_DIR/checkout-hooks.lock"
acquire_hooks_lock() {
  local waited=0
  until mkdir "$LOCK_DIR" 2>/dev/null; do
    if [ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +2 2>/dev/null)" ]; then
      rmdir "$LOCK_DIR" 2>/dev/null || true
      continue
    fi
    waited=$((waited + 1))
    # Waited 60 s: another run is stuck, skip the hooks, the next session start repairs them.
    [ "$waited" -gt 120 ] && { echo "checkout.sh: hooks lock is busy, skipping hook setup" >&2; exit 0; }
    sleep 0.5
  done
  trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
}
acquire_hooks_lock

# A `<hook>.legacy` that is itself a pre-commit script (left by an earlier race) makes the hook call itself, so move it away.
heal_self_referencing_legacy_hooks() {
  local legacy
  for legacy in "$HOOKS_DIR"/*.legacy; do
    [ -f "$legacy" ] || continue
    if grep -q 'hook-impl' "$legacy"; then
      mv "$legacy" "${legacy%.legacy}.legacy.$(date +%Y-%m-%d).bak"
    fi
  done
}

# `pre-commit install` only when this hook type is missing or not a pre-commit script, so a running session never rewrites a good hook.
install_pre_commit_hook() {
  local hook_type="$1" hook_file="$HOOKS_DIR/$1"
  if [ -f "$hook_file" ] && grep -q 'hook-impl' "$hook_file" && grep -q -- "--hook-type=$hook_type" "$hook_file"; then
    return 0
  fi
  pre-commit install --hook-type "$hook_type" >/dev/null 2>&1 || true
}

# ─── 3. Unset core.hooksPath if set ─────────────────────────────────────────
# Some tools (e.g. husky v9) set core.hooksPath which prevents .git/hooks from
# being used. We want .git/hooks to be the canonical hooks directory.
git config --unset-all core.hooksPath 2>/dev/null || true

# ─── 4. Install git-lfs hooks ───────────────────────────────────────────────
# git-lfs install writes its hooks (post-checkout, post-commit, post-merge, pre-push)
if command -v git-lfs >/dev/null 2>&1; then
  git lfs install --local >/dev/null 2>&1 || true
  "$REPO_ROOT/scripts/°base/init/git-lfs-full-path.sh" >/dev/null 2>&1 || true
fi
repair_git_lfs_hooks_path

# GitHub's LFS lock API can reject pushes when credentials are valid for git
# push but not for lock verification. This repo does not use LFS locks, so keep
# the generated pre-push hook from checking them for local GitHub HTTPS remotes.
if command -v python3 >/dev/null 2>&1; then
  python3 "$REPO_ROOT/scripts/°base/git/remote/fix_username.py" --fix-lfs-locks-only >/dev/null 2>&1 || true
fi

# ─── 5. Install pre-commit hooks ────────────────────────────────────────────
# Installs the commit-msg, pre-commit, post-merge and post-rewrite hook types as configured in
# .pre-commit-config.yaml
if command -v pre-commit >/dev/null 2>&1; then
  heal_self_referencing_legacy_hooks
  install_pre_commit_hook pre-commit
  install_pre_commit_hook commit-msg
  # Re-link subproject shared files after a merge or rebase.
  install_pre_commit_hook post-merge
  install_pre_commit_hook post-rewrite
  add_path_to_pre_commit_hooks
fi
