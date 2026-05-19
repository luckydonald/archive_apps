#!/usr/bin/env bash
# scripts/°base/init/link-subproject-claude.sh
#
# Idempotent per-subfolder setup for the monorepo case: creates a relative
# symlink at <cwd>/.claude pointing at the monorepo-root <git-root>/.claude.
# This lets Claude Code's settings.json discovery find the shared hooks/perms
# when Claude is launched from inside a subfolder of a monorepo that has the
# `base` repo merged at its top level.
#
# Run once from inside the subfolder:
#
#   cd monorepo/some_project
#   ../scripts/°base/init/link-subproject-claude.sh
#
# Safe to run multiple times — exits cleanly when the symlink already points
# at the right place.

set -euo pipefail

sub_dir="$(pwd -P)"
git_root="$(cd "$(git rev-parse --show-toplevel)" && pwd -P)"
root_claude="$git_root/.claude"

if [ "$sub_dir" = "$git_root" ]; then
  echo "$sub_dir is the git root — no symlink needed." >&2
  exit 0
fi

if [ ! -d "$root_claude" ]; then
  echo "no $root_claude — did you merge base/base at the repo root?" >&2
  exit 1
fi

target="$sub_dir/.claude"

if [ -L "$target" ]; then
  # Already a symlink — verify it points at the root .claude/, leave alone if so.
  resolved="$(cd "$sub_dir" && cd "$(readlink "$target")" 2>/dev/null && pwd || true)"
  if [ "$resolved" = "$root_claude" ]; then
    echo "$target already linked to $root_claude"
    exit 0
  fi
  echo "$target is a symlink but points elsewhere ($(readlink "$target")) — refusing to clobber." >&2
  exit 1
fi

if [ -e "$target" ]; then
  echo "$target exists and is not a symlink — refusing to clobber." >&2
  exit 1
fi

# Build a relative path from sub_dir up to root_claude so the symlink stays
# valid across machines and inside containers with different mount points.
rel="$(python3 -c 'import os, sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$root_claude" "$sub_dir")"
ln -s "$rel" "$target"
echo "linked $target -> $rel"
