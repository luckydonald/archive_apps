#!/usr/bin/env bash
# scripts/°base/init/git-lfs-full-path.sh
#
# Make repo-local Git LFS filters call the absolute git-lfs binary. IDEs can run
# Apple's/Xcode's git with a restricted PATH during checkout, and Git LFS filters
# run before hooks can repair PATH.

set -euo pipefail

git rev-parse --show-toplevel >/dev/null

TOOL_PATH_PREFIX="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.pyenv/shims:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin"
export PATH="$TOOL_PATH_PREFIX:$PATH"

if ! GIT_LFS_PATH="$(command -v git-lfs 2>/dev/null)"; then
  echo "git-lfs was not found on PATH." >&2
  exit 2
fi

case "$GIT_LFS_PATH" in
  /*) ;;
  *)
    echo "git-lfs path is not absolute: $GIT_LFS_PATH" >&2
    exit 2
    ;;
esac

git config --local filter.lfs.clean "$GIT_LFS_PATH clean -- %f"
git config --local filter.lfs.smudge "$GIT_LFS_PATH smudge -- %f"
git config --local filter.lfs.process "$GIT_LFS_PATH filter-process"
git config --local filter.lfs.required true

echo "Configured local Git LFS filters to use $GIT_LFS_PATH"
