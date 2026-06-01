from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DELETE_HELPER = ROOT / "scripts" / "°base" / "ai" / "memory" / "delete.py"
MARKER_HOOK = (
    ROOT / "scripts" / "°base" / "git" / "hooks" / "commit" / "require_memory_delete_marker.py"
)


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "tester@example.com")
    run_git(repo, "config", "user.name", "Test User")
    run_git(repo, "remote", "add", "origin", "https://luckydonald@github.com/luckydonald/base.git")
    (repo / "README.md").write_text("test repo\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "init")


def add_memory(repo: Path, name: str) -> Path:
    path = repo / "ai" / "°base" / "memory" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{name}\n", encoding="utf-8")
    run_git(repo, "add", str(path.relative_to(repo)))
    run_git(repo, "commit", "-m", f"seed {name}")
    return path


def run_marker_hook(repo: Path, message: str) -> subprocess.CompletedProcess[str]:
    msg = repo / "COMMIT_EDITMSG"
    msg.write_text(message, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(MARKER_HOOK), str(msg)],
        cwd=repo,
        capture_output=True,
        text=True,
    )


class MemoryDeleteTests(unittest.TestCase):
    def test_marker_hook_rejects_memory_deletion_without_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo)
            path = add_memory(repo, "note.md")
            run_git(repo, "rm", str(path.relative_to(repo)))

            result = run_marker_hook(repo, "ai: delete memory note\n")

            self.assertEqual(result.returncode, 1)
            self.assertIn("Deleted Memory: note.md", result.stderr)

    def test_marker_hook_accepts_memory_deletion_with_standalone_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo)
            path = add_memory(repo, "note.md")
            run_git(repo, "rm", str(path.relative_to(repo)))

            result = run_marker_hook(
                repo,
                "ai: delete memory note\n\nDeleted Memory: note.md\n",
            )

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_marker_hook_requires_each_deleted_memory_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo)
            first = add_memory(repo, "one.md")
            second = add_memory(repo, "two.md")
            run_git(repo, "rm", str(first.relative_to(repo)), str(second.relative_to(repo)))

            result = run_marker_hook(
                repo,
                "ai: delete memories one, two\n\nDeleted Memory: one.md\n",
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("Deleted Memory: two.md", result.stderr)

    def test_delete_helper_removes_repo_and_source_and_formats_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            home = Path(tmp) / "home"
            init_repo(repo)
            path = add_memory(repo, "note.md")
            encoded = str(repo).replace("/", "-")
            src = home / ".claude" / "projects" / encoded / "memory" / "note.md"
            src.parent.mkdir(parents=True)
            src.write_text("source copy\n", encoding="utf-8")
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["CLAUDE_PROJECT_DIR"] = str(repo)

            result = subprocess.run(
                [sys.executable, str(DELETE_HELPER), "note.md"],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(path.exists())
            self.assertFalse(src.exists())
            message = run_git(repo, "log", "-1", "--pretty=%B").stdout.strip("\n")
            self.assertEqual(
                message,
                "[base] ai: delete memory note\n\nDeleted Memory: note.md",
            )


if __name__ == "__main__":
    unittest.main()
