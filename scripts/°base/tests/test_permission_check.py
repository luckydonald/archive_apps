from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3] / ".claude" / "hooks"
MODULE_PATH = ROOT / "permission-check.py"
SPEC = importlib.util.spec_from_file_location("permission_check", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def run_hook(command: str, tool_name: str = "Bash") -> dict:
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"command": command}})
    result = subprocess.run(
        [sys.executable, str(MODULE_PATH)],
        input=payload,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def is_denied(output: dict) -> bool:
    return (
        output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
    )


class CheckGitAddTests(unittest.TestCase):
    def _deny(self, args: list[str]):
        argv = ["git", "add"] + args
        self.assertIsNotNone(MODULE.check_git_add(argv))

    def _allow(self, args: list[str]):
        argv = ["git", "add"] + args
        self.assertIsNone(MODULE.check_git_add(argv))

    def test_flag_A_short(self):
        self._deny(["-A"])

    def test_flag_all_long(self):
        self._deny(["--all"])

    def test_flag_u_short(self):
        self._deny(["-u"])

    def test_flag_update_long(self):
        self._deny(["--update"])

    def test_dot_path(self):
        self._deny(["."])

    def test_root_path(self):
        self._deny([":/"])

    def test_explicit_file(self):
        self._allow(["src/foo.py"])

    def test_multiple_explicit_files(self):
        self._allow(["src/foo.py", "src/bar.py"])

    def test_no_args(self):
        self._allow([])

    def test_flag_mixed_with_explicit_file(self):
        # -A anywhere in args should still deny
        self._deny(["-A", "src/foo.py"])


class CollectCommitMessagesTests(unittest.TestCase):
    def test_short_m_flag(self):
        msgs = MODULE.collect_commit_messages(["git", "commit", "-m", "hello"])
        self.assertEqual(msgs, ["hello"])

    def test_long_message_flag_space(self):
        msgs = MODULE.collect_commit_messages(["git", "commit", "--message", "hello"])
        self.assertEqual(msgs, ["hello"])

    def test_long_message_flag_equals(self):
        msgs = MODULE.collect_commit_messages(["git", "commit", "--message=hello"])
        self.assertEqual(msgs, ["hello"])

    def test_multiple_m_flags(self):
        msgs = MODULE.collect_commit_messages(
            ["git", "commit", "-m", "subject", "-m", "body"]
        )
        self.assertEqual(msgs, ["subject", "body"])

    def test_file_flag_short(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("message from file")
            path = f.name
        msgs = MODULE.collect_commit_messages(["git", "commit", "-F", path])
        self.assertEqual(msgs, ["message from file"])

    def test_file_flag_long_equals(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("message from file")
            path = f.name
        msgs = MODULE.collect_commit_messages(["git", "commit", f"--file={path}"])
        self.assertEqual(msgs, ["message from file"])

    def test_file_flag_stdin_skipped(self):
        msgs = MODULE.collect_commit_messages(["git", "commit", "-F", "-"])
        self.assertEqual(msgs, [])

    def test_file_flag_unreadable_skipped(self):
        msgs = MODULE.collect_commit_messages(
            ["git", "commit", "-F", "/nonexistent/path/msg.txt"]
        )
        self.assertEqual(msgs, [])

    def test_m_and_file_combined(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("from file")
            path = f.name
        msgs = MODULE.collect_commit_messages(
            ["git", "commit", "-m", "from -m", "-F", path]
        )
        self.assertEqual(msgs, ["from -m", "from file"])

    def test_m_flag_at_end_without_value(self):
        # Edge case: -m with no following arg
        msgs = MODULE.collect_commit_messages(["git", "commit", "-m"])
        self.assertEqual(msgs, [])


class CheckGitCommitTests(unittest.TestCase):
    def test_clean_message_allowed(self):
        argv = ["git", "commit", "-m", "fix: do the thing"]
        self.assertIsNone(MODULE.check_git_commit(argv))

    def test_co_authored_by_trailer_denied(self):
        argv = ["git", "commit", "-m", "fix\n\nCo-Authored-By: User <u@example.com>"]
        self.assertIsNotNone(MODULE.check_git_commit(argv))

    def test_co_authored_by_case_insensitive(self):
        argv = ["git", "commit", "-m", "fix\n\nco-authored-by: User <u@example.com>"]
        self.assertIsNotNone(MODULE.check_git_commit(argv))

    def test_co_authored_by_in_second_m_flag(self):
        argv = [
            "git", "commit",
            "-m", "fix: subject",
            "-m", "Co-Authored-By: User <u@example.com>",
        ]
        self.assertIsNotNone(MODULE.check_git_commit(argv))

    def test_co_authored_by_without_colon_allowed(self):
        # Prose mention without colon is not a trailer — should not be denied
        argv = ["git", "commit", "-m", "fix: add Co-Authored-By detection logic"]
        self.assertIsNone(MODULE.check_git_commit(argv))

    def test_co_authored_by_heredoc_caught_by_shlex_path(self):
        # When shlex parses `git commit -m "$(cat <<'EOF'\n...\nEOF\n)"`, the entire
        # $(cat ...) becomes the literal -m value — including any Co-Authored-By:
        # trailer inside the heredoc body. collect_commit_messages sees it directly,
        # without needing the raw-string fast path.
        # We test check_git_commit with shlex-parsed argv to prove the shlex path
        # catches it on its own.
        import shlex
        cmd = (
            "git commit -m \"$(cat <<'EOF'\n"
            "      [base] ai: Run: add PermissionRequest hooks\n"
            "\n"
            "      Replace generic deny-list entries.\n"
            "      Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
            "      EOF\n"
            "      )\""
        )
        argv = shlex.split(cmd)
        # Confirm shlex did not error and yielded the unexpanded $(...) as the -m value
        self.assertEqual(argv[:3], ["git", "commit", "-m"])
        self.assertIn("Co-Authored-By:", argv[3])
        # The shlex path (collect_commit_messages) must catch it
        self.assertIsNotNone(MODULE.check_git_commit(argv))

    def test_co_authored_by_in_file_denied(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("fix: thing\n\nCo-Authored-By: User <u@example.com>\n")
            path = f.name
        argv = ["git", "commit", "-F", path]
        self.assertIsNotNone(MODULE.check_git_commit(argv))


class IntegrationTests(unittest.TestCase):
    """End-to-end tests via subprocess (full stdin→stdout pipeline)."""

    def test_git_add_A_denied(self):
        self.assertTrue(is_denied(run_hook("git add -A")))

    def test_git_add_dot_denied(self):
        self.assertTrue(is_denied(run_hook("git add .")))

    def test_git_add_explicit_file_allowed(self):
        self.assertFalse(is_denied(run_hook("git add src/foo.py")))

    def test_git_commit_clean_allowed(self):
        self.assertFalse(is_denied(run_hook('git commit -m "fix: thing"')))

    def test_git_commit_with_trailer_denied(self):
        self.assertTrue(
            is_denied(run_hook('git commit -m "fix\n\nCo-Authored-By: X <x@x.com>"'))
        )

    def test_git_commit_heredoc_with_trailer_denied(self):
        # Simulates Claude's heredoc commit pattern. shlex parses successfully but
        # yields the unexpanded $(cat <<'EOF'...) expression as the -m value, so
        # collect_commit_messages never sees the actual message text. The raw-string
        # fast path catches it by scanning the full command string directly.
        heredoc_cmd = (
            "git commit -m \"$(cat <<'EOF'\n"
            "fix: something\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n"
            "EOF\n)\""
        )
        self.assertTrue(is_denied(run_hook(heredoc_cmd)))

    def test_git_commit_heredoc_without_trailer_allowed(self):
        heredoc_cmd = (
            "git commit -m \"$(cat <<'EOF'\n"
            "fix: something clean\n"
            "EOF\n)\""
        )
        self.assertFalse(is_denied(run_hook(heredoc_cmd)))

    def test_git_commit_heredoc_prose_mention_allowed(self):
        # Body mentions "Co-Authored-By detection" as prose — no colon, not a trailer.
        # This is the exact pattern that slipped through before the fix was applied.
        heredoc_cmd = (
            "git commit -m \"$(cat <<'EOF'\n"
            "      [base] ai: Run: add PermissionRequest hooks for git add and Co-Authored-By policy\n"
            "\n"
            "      Replace generic deny-list entries for `git add .` / `git add -A` with a\n"
            "      `PermissionRequest` hooks that returns rich denial reasons. Also adds\n"
            "      Co-Authored-By detection for `git commit` messages (via -m, --message=,\n"
            "      or -F file). The commit-msg hooks remains as final fallback.\n"
            "      EOF\n"
            "      )\""
        )
        self.assertFalse(is_denied(run_hook(heredoc_cmd)))

    def test_git_commit_compound_command_with_trailer_denied(self):
        # Compound `git add ... && git commit -m "..."` — the command does not start
        # with "git commit", so startswith() would miss it. The substring check catches it.
        cmd = (
            "git add scripts/°base/ai/hooks/save-decision/hook.py .claude/settings.json "
            "&& git commit -m \"$(cat <<'EOF'\n"
            "      ai: add PostToolUse hooks to log AskUserQuestion decisions\n"
            "\n"
            "      Records each plan-mode question, its options, and the selected answer\n"
            "      to ai/decisions.md after AskUserQuestion resolves.\n"
            "\n"
            "      Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>\n"
            "      EOF\n"
            "      )\""
        )
        self.assertTrue(is_denied(run_hook(cmd)))

    def test_non_bash_tool_allowed(self):
        out = run_hook("git add -A", tool_name="Edit")
        self.assertFalse(is_denied(out))

    def test_non_git_command_allowed(self):
        self.assertFalse(is_denied(run_hook("ls -la")))

    def test_deny_output_contains_reason(self):
        out = run_hook("git add -A")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("explicit file paths", reason)

    def test_co_authored_by_deny_output_contains_reason(self):
        out = run_hook('git commit -m "fix\n\nCo-Authored-By: X <x@x.com>"')
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("Co-Authored-By", reason)
        self.assertNotIn("settings.json", reason)


if __name__ == "__main__":
    unittest.main()
