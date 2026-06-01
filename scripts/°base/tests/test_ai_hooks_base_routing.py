from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROMPT_HOOK = ROOT / "scripts" / "°base" / "ai" / "hooks" / "save-prompt" / "hook.py"
PLAN_HOOK = ROOT / "scripts" / "°base" / "ai" / "hooks" / "save-plan" / "hook.py"
MEMORY_HOOK = ROOT / "scripts" / "°base" / "ai" / "hooks" / "record-memory" / "hook.py"


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def init_repo(repo: Path, origin: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "tester@example.com")
    run_git(repo, "config", "user.name", "Test User")
    run_git(repo, "remote", "add", "origin", origin)
    (repo / "README.md").write_text("test repo\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "init")


def run_hook(
    repo: Path,
    hook: Path,
    payload: dict,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> None:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, str(hook), *args],
        cwd=repo,
        env=env,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"hook failed with {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def last_subject(repo: Path) -> str:
    return run_git(repo, "log", "-1", "--pretty=%s").stdout.strip()


class AiHooksBaseRoutingTests(unittest.TestCase):
    def test_codex_prompt_in_base_repo_with_only_origin_routes_and_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")

            run_hook(repo, PROMPT_HOOK, {"prompt": "Capture this prompt"}, "codex")

            self.assertEqual(
                (repo / "ai" / "°base" / "query.md").read_text(encoding="utf-8"),
                "› Capture this prompt\n\n",
            )
            self.assertFalse((repo / "ai" / "query.md").exists())
            self.assertEqual(last_subject(repo), "[base] ai: updated prompt")

    def test_codex_plan_in_base_repo_routes_and_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            session_id = f"test-{uuid.uuid4()}"

            run_hook(
                repo,
                PLAN_HOOK,
                {
                    "hook_event_name": "Stop",
                    "session_id": session_id,
                    "last_assistant_message": (
                        "<proposed_plan>\n"
                        "# Base Route Plan\n"
                        "Write the routed plan artifact.\n"
                        "</proposed_plan>"
                    ),
                },
                "codex",
            )

            plan_path = repo / "ai" / "°base" / "plans" / "001_base-route-plan.md"
            self.assertEqual(
                plan_path.read_text(encoding="utf-8"),
                "# Base Route Plan\nWrite the routed plan artifact.\n",
            )
            self.assertFalse((repo / "ai" / "plans").exists())
            self.assertEqual(last_subject(repo), "[base] ai: save plan 001_base-route-plan")

    def test_codex_plan_ignores_post_tool_use_stdout_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")

            run_hook(
                repo,
                PLAN_HOOK,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": f"test-{uuid.uuid4()}",
                    "tool_name": "ExitPlanMode",
                    "tool_response": "Exit code: 0\nstdout from some command\n",
                },
                "codex",
            )

            self.assertFalse((repo / "ai" / "°base" / "plans").exists())
            self.assertEqual(last_subject(repo), "init")

    def test_codex_plan_uses_session_transcript_plan_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            home = Path(tmp) / "home"
            session_id = f"test-{uuid.uuid4()}"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            session_dir = home / ".codex" / "sessions" / "2026" / "05" / "27"
            session_dir.mkdir(parents=True)
            session_file = session_dir / f"rollout-2026-05-27T14-20-27-{session_id}.jsonl"
            session_file.write_text(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "item_completed",
                            "item": {
                                "type": "Plan",
                                "text": "# Transcript Plan\n\nUse the Codex plan event.\n",
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            run_hook(
                repo,
                PLAN_HOOK,
                {"hook_event_name": "Stop", "session_id": session_id},
                "codex",
                extra_env={"HOME": str(home)},
            )

            plan_path = repo / "ai" / "°base" / "plans" / "001_transcript-plan.md"
            self.assertEqual(
                plan_path.read_text(encoding="utf-8"),
                "# Transcript Plan\n\nUse the Codex plan event.\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: save plan 001_transcript-plan")

    def test_codex_plan_falls_back_to_forwarded_plan_query_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            query_path = repo / "ai" / "°base" / "query.md"
            query_path.parent.mkdir(parents=True)
            query_path.write_text(
                "› A previous agent produced the plan below to accomplish the user's task.\n"
                "Implement the plan in a fresh context.\n\n"
                "# Forwarded Plan\n\n"
                "Save this markdown plan.\n\n",
                encoding="utf-8",
            )

            run_hook(
                repo,
                PLAN_HOOK,
                {"hook_event_name": "Stop", "session_id": f"test-{uuid.uuid4()}"},
                "codex",
            )

            plan_path = repo / "ai" / "°base" / "plans" / "001_forwarded-plan.md"
            self.assertEqual(
                plan_path.read_text(encoding="utf-8"),
                "# Forwarded Plan\n\nSave this markdown plan.\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: save plan 001_forwarded-plan")

    def test_claude_write_plan_still_captures_claude_plan_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            home = Path(tmp) / "home"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            plan_file = home / ".claude" / "plans" / "test-plan.md"

            run_hook(
                repo,
                PLAN_HOOK,
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": f"test-{uuid.uuid4()}",
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": str(plan_file),
                        "content": "# Claude Write Plan\n\nKeep Claude behavior.\n",
                    },
                },
                "claude",
            )

            plan_path = repo / "ai" / "°base" / "plans" / "001_claude-write-plan.md"
            self.assertEqual(
                plan_path.read_text(encoding="utf-8"),
                "# Claude Write Plan\n\nKeep Claude behavior.\n",
            )
            self.assertEqual(last_subject(repo), "[base] ai: save plan 001_claude-write-plan")

    def test_memory_in_base_repo_routes_and_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            home = Path(tmp) / "home"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            encoded = str(repo).replace("/", "-")
            src_dir = home / ".claude" / "projects" / encoded / "memory"
            src_dir.mkdir(parents=True)
            (src_dir / "note.md").write_text("remember this\n", encoding="utf-8")

            run_hook(
                repo,
                MEMORY_HOOK,
                {"hook_event_name": "SessionStart"},
                extra_env={"HOME": str(home)},
            )

            self.assertEqual(
                (repo / "ai" / "°base" / "memory" / "note.md").read_text(encoding="utf-8"),
                "remember this\n",
            )
            self.assertFalse((repo / "ai" / "memory").exists())
            self.assertEqual(last_subject(repo), "[base] ai: record memory note")

    def test_memory_session_start_restores_missing_claude_source_from_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            home = Path(tmp) / "home"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            memory_file = repo / "ai" / "°base" / "memory" / "note.md"
            memory_file.parent.mkdir(parents=True)
            memory_file.write_text("repo is durable\n", encoding="utf-8")
            run_git(repo, "add", str(memory_file.relative_to(repo)))
            run_git(repo, "commit", "-m", "seed memory")

            run_hook(
                repo,
                MEMORY_HOOK,
                {"hook_event_name": "SessionStart"},
                extra_env={"HOME": str(home)},
            )

            encoded = str(repo).replace("/", "-")
            src_file = home / ".claude" / "projects" / encoded / "memory" / "note.md"
            self.assertEqual(src_file.read_text(encoding="utf-8"), "repo is durable\n")
            self.assertEqual(last_subject(repo), "seed memory")

    def test_memory_session_start_does_not_resurrect_marked_deleted_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            home = Path(tmp) / "home"
            init_repo(repo, "https://luckydonald@github.com/luckydonald/base.git")
            memory_file = repo / "ai" / "°base" / "memory" / "old.md"
            memory_file.parent.mkdir(parents=True)
            memory_file.write_text("old memory\n", encoding="utf-8")
            run_git(repo, "add", str(memory_file.relative_to(repo)))
            run_git(repo, "commit", "-m", "seed old memory")
            run_git(repo, "rm", str(memory_file.relative_to(repo)))
            run_git(
                repo,
                "commit",
                "-m",
                "ai: delete memory old",
                "-m",
                "Deleted Memory: old.md",
            )
            encoded = str(repo).replace("/", "-")
            src_file = home / ".claude" / "projects" / encoded / "memory" / "old.md"
            src_file.parent.mkdir(parents=True)
            src_file.write_text("stale local memory\n", encoding="utf-8")

            run_hook(
                repo,
                MEMORY_HOOK,
                {"hook_event_name": "SessionStart"},
                extra_env={"HOME": str(home)},
            )

            self.assertFalse(memory_file.exists())
            self.assertFalse(src_file.exists())
            self.assertEqual(last_subject(repo), "ai: delete memory old")

    def test_prompt_in_repo_named_base_with_different_origin_is_unprefixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "base"
            init_repo(repo, "https://github.com/example/consumer.git")

            run_hook(repo, PROMPT_HOOK, {"prompt": "Capture downstream prompt"}, "codex")

            self.assertEqual(
                (repo / "ai" / "query.md").read_text(encoding="utf-8"),
                "› Capture downstream prompt\n\n",
            )
            self.assertFalse((repo / "ai" / "°base" / "query.md").exists())
            self.assertEqual(last_subject(repo), "ai: updated prompt")


if __name__ == "__main__":
    unittest.main()
