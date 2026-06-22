#!/usr/bin/env sh
# Normalize PATH for Git hooks launched by IDE/Xcode Git processes.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.pyenv/shims:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:$PATH"

exec "$@"
