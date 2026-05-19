"""
Auto-installs pre-commit hooks when this package is imported.
Runs automatically if you do `python -m hooks` or `python -c 'import hooks'`
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _list_hooks():
    try:
        repo_root = Path(__file__).parent.parent
        hooks = repo_root / '.git' / 'hooks'
        installed = []
        for hook in hooks.iterdir():
            if not hook.is_file():
                continue
            # end if
            if hook.name.endswith(".sample"):
                continue
            # end if
            installed.append(hook)
        # end for

        print(f"Installed git        hooks: {[h.name for h in installed]}", file=sys.stderr)

        installed_precommit = []
        for file in installed:
            with open(file, "r") as f:
                txt = f.read()
                if not 'pre-commit' in txt:
                    continue
                # end if
            # end with
            installed_precommit.append(file)
        # end for

        print(f"Installed pre-commit hooks: {[h.name for h in installed_precommit]}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: could not read installed hooks: {e}", file=sys.stderr)
    # end try
# end def


def _install_hooks():
    """Install pre-commit hooks during package import/installation."""
    _list_hooks()
    try:
        repo_root = Path(__file__).parent.parent

        # Clear any explicit core.hooksPath config that might interfere
        subprocess.run(
            ["git", "config", "--unset-all", "core.hooksPath"],
            cwd=repo_root,
            capture_output=True,
        )

        # Install pre-commit hooks
        result = subprocess.run(
            [sys.executable, "-m", "pre_commit", "install", "--hooks-type", "commit-msg"],
            cwd=repo_root,
            capture_output=True,
        )

        if result.returncode == 0:
            print("✓ Pre-commit hooks installed", file=sys.stderr)
        else:
            print(
                f"Warning: pre-commit hooks installation had issues: {result.stderr.decode()}",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"Warning: could not install pre-commit hooks: {e}", file=sys.stderr)
    # end try
    _list_hooks()
# end def

_install_hooks()
