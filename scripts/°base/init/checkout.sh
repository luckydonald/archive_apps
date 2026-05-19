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
HOOKS_DIR="$REPO_ROOT/.git/hooks"

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

# ─── 2. Unset core.hooksPath if set ─────────────────────────────────────────
# Some tools (e.g. husky v9) set core.hooksPath which prevents .git/hooks from
# being used. We want .git/hooks to be the canonical hooks directory.
git config --unset-all core.hooksPath 2>/dev/null || true

# ─── 3. Install git-lfs hooks ───────────────────────────────────────────────
# git-lfs install writes its hooks (post-checkout, post-commit, post-merge, pre-push)
if command -v git-lfs >/dev/null 2>&1; then
  git lfs install --local >/dev/null 2>&1 || true
fi

# ─── 4. Install pre-commit hooks ────────────────────────────────────────────
# Installs commit-msg and pre-commit hooks types as configured in
# .pre-commit-config.yaml
if command -v pre-commit >/dev/null 2>&1; then
  pre-commit install --hook-type pre-commit >/dev/null 2>&1 || true
  pre-commit install --hook-type commit-msg >/dev/null 2>&1 || true
fi
