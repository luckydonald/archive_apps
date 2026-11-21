"""Exercise plan numbering through the hook with real Git worktrees."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / "scripts" / "°base" / "ai" / "hooks" / "save-plan" / "hook.py"
PLANS = Path("ai/plans")


class SavePlanWorktreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.main = self.temp / "main"
        self.sibling = self.temp / "linked worktree"
        self.main.mkdir()
        self.git(self.main, "init", "-q")
        self.git(self.main, "config", "user.name", "Plan Hook Test")
        self.git(self.main, "config", "user.email", "plan-hook@example.test")
        self.git(self.main, "config", "core.hooksPath", str(self.temp / "no-hooks"))
        self.git(self.main, "commit", "--allow-empty", "-qm", "Initial commit")
        self.git(self.main, "worktree", "add", "-qb", "linked", str(self.sibling))
        self.source = self.temp / ".claude" / "plans" / "draft.md"
        self.source.parent.mkdir(parents=True)

    def git(self, checkout: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=checkout, check=True, capture_output=True)

    def save(self, checkout: Path, session: str, title: str) -> None:
        payload = {
            "session_id": session,
            "tool_name": "Write",
            "tool_input": {"file_path": str(self.source), "content": f"# {title}"},
        }
        result = subprocess.run(
            [sys.executable, str(HOOK)], cwd=checkout, input=json.dumps(payload), text=True,
            capture_output=True, timeout=20,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(checkout), "TMPDIR": str(self.temp)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def plan(self, checkout: Path, name: str, directory: Path = PLANS) -> None:
        path = checkout / directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    def test_main_checkout_counts_uncommitted_plan_in_linked_worktree(self) -> None:
        self.plan(self.main, "007_local.md")
        self.plan(self.sibling, "015_uncommitted.md")
        self.plan(self.sibling, "099_unrelated.md", Path("subproject/ai/plans"))

        self.save(self.main, "main-session", "Main Plan")
        self.save(self.sibling, "linked-session", "Linked Plan")

        self.assertTrue((self.main / PLANS / "016_main-plan.md").is_file())
        self.assertTrue((self.sibling / PLANS / "017_linked-plan.md").is_file())

    def test_preserves_issue_specific_directory_scope(self) -> None:
        issue_plans = Path("ai/by-issue/EX-1/plans")
        (self.main / "ai").mkdir()
        (self.main / "ai/.by-issue").write_text("EX-1\n", encoding="utf-8")
        self.plan(self.sibling, "005_issue.md", issue_plans)
        self.plan(self.sibling, "099_unrelated.md")

        self.save(self.main, "issue-session", "Issue Plan")

        self.assertTrue((self.main / issue_plans / "006_issue-plan.md").is_file())

    def test_parallel_saves_get_distinct_numbers_and_revisions_keep_them(self) -> None:
        with ThreadPoolExecutor(max_workers=2) as pool:
            main_save = pool.submit(self.save, self.main, "main-session", "Main Plan")
            linked_save = pool.submit(self.save, self.sibling, "linked-session", "Linked Plan")
            main_save.result()
            linked_save.result()

        main_plan, = (self.main / PLANS).glob("*_main-plan.md")
        linked_plan, = (self.sibling / PLANS).glob("*_linked-plan.md")
        main_prefix = main_plan.name.split("_", 1)[0]
        linked_prefix = linked_plan.name.split("_", 1)[0]
        self.assertEqual({main_prefix, linked_prefix}, {"001", "002"})

        self.save(self.main, "main-session", "Revised Main Plan")
        self.save(self.sibling, "linked-session", "Revised Linked Plan")

        self.assertEqual(list((self.main / PLANS).glob("*.md")), [self.main / PLANS / f"{main_prefix}_revised-main-plan.md"])
        self.assertEqual(list((self.sibling / PLANS).glob("*.md")), [self.sibling / PLANS / f"{linked_prefix}_revised-linked-plan.md"])
