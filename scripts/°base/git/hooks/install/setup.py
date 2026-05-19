#!/usr/bin/env python3
"""
Setup.py that installs pre-commit hooks during package setup.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from setuptools import find_packages, setup


def _install_hooks():
    """Install pre-commit hooks during setup."""
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
    except Exception as e:
        print(f"Warning: could not install pre-commit hooks: {e}", file=sys.stderr)


# Install hooks during setup
_install_hooks()

setup(
    packages=find_packages(),
)
