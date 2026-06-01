from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "git" / "remote"
MODULE_PATH = ROOT / "fix_username.py"
SPEC = importlib.util.spec_from_file_location("git_remote_fix", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def git(args: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


class UrlHelperTests(unittest.TestCase):
    def test_parse_github_https_url_accepts_expected_shape(self) -> None:
        info = MODULE.parse_github_https_url("https://someone@github.com/owner/repo.git")
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.username, "someone")
        self.assertEqual(info.owner, "owner")
        self.assertEqual(info.repo, "repo")
        self.assertTrue(info.has_git_suffix)

    def test_parse_github_https_url_rejects_unsupported_shapes(self) -> None:
        self.assertIsNone(MODULE.parse_github_https_url("git@github.com:owner/repo.git"))
        self.assertIsNone(MODULE.parse_github_https_url("../template"))
        self.assertIsNone(MODULE.parse_github_https_url("https://example.com/owner/repo"))

    def test_rewrite_url_adds_username_and_git_suffix(self) -> None:
        rewritten = MODULE.rewrite_github_https_url(
            "https://github.com/owner/repo",
            username="luckydonald",
            set_username=True,
            add_git_suffix=True,
        )
        self.assertEqual(rewritten, "https://luckydonald@github.com/owner/repo.git")

    def test_rewrite_url_preserves_existing_username_when_not_selected(self) -> None:
        rewritten = MODULE.rewrite_github_https_url(
            "https://someone@github.com/owner/repo",
            username="luckydonald",
            set_username=False,
            add_git_suffix=True,
        )
        self.assertEqual(rewritten, "https://someone@github.com/owner/repo.git")

    def test_github_lfs_locksverify_key_canonicalizes_endpoint(self) -> None:
        key = MODULE.github_lfs_locksverify_key("https://someone@github.com/owner/repo")
        self.assertEqual(
            key,
            "lfs.https://someone@github.com/owner/repo.git/info/lfs.locksverify",
        )

    def test_github_lfs_locksverify_key_rejects_non_github_urls(self) -> None:
        self.assertIsNone(MODULE.github_lfs_locksverify_key("git@github.com:owner/repo.git"))
        self.assertIsNone(MODULE.github_lfs_locksverify_key("https://example.com/owner/repo.git"))

    def test_resolve_default_username_prefers_remote_username(self) -> None:
        remotes = [
            MODULE.RemoteSelection(
                name="origin",
                fetch=MODULE.make_url_selection("fetch", "https://github.com/owner/repo"),
                push=MODULE.make_url_selection("push", "https://someone@github.com/owner/repo.git"),
                push_is_explicit=True,
            )
        ]
        value = MODULE.resolve_default_username(None, remotes, lambda key: {"user.name": "fallback"}.get(key))
        self.assertEqual(value, "someone")

    def test_resolve_default_username_falls_back_to_git_config(self) -> None:
        remotes = [
            MODULE.RemoteSelection(
                name="origin",
                fetch=MODULE.make_url_selection("fetch", "https://github.com/owner/repo"),
                push=MODULE.make_url_selection("push", "https://github.com/owner/repo"),
                push_is_explicit=False,
            )
        ]
        value = MODULE.resolve_default_username(None, remotes, lambda key: {"user.name": "fallback"}.get(key))
        self.assertEqual(value, "fallback")


class ExecutionPlanTests(unittest.TestCase):
    def make_remote(
        self,
        *,
        name: str,
        fetch_url: str,
        push_url: str,
        push_is_explicit: bool,
    ):
        return MODULE.RemoteSelection(
            name=name,
            fetch=MODULE.make_url_selection("fetch", fetch_url),
            push=MODULE.make_url_selection("push", push_url),
            push_is_explicit=push_is_explicit,
        )

    def test_shared_push_can_stay_unchanged_when_only_fetch_changes(self) -> None:
        remote = self.make_remote(
            name="origin",
            fetch_url="https://github.com/owner/repo",
            push_url="https://github.com/owner/repo",
            push_is_explicit=False,
        )
        remote.fetch.change_username = True
        remote.fetch.add_git_suffix = True
        remote.push.change_username = False
        remote.push.add_git_suffix = False

        plan = MODULE.build_execution_plan([remote], "luckydonald")

        self.assertEqual(
            plan.commands,
            [
                ["git", "remote", "set-url", "origin", "https://luckydonald@github.com/owner/repo.git"],
                ["git", "remote", "set-url", "--push", "origin", "https://github.com/owner/repo"],
            ],
        )

    def test_shared_push_needs_only_fetch_command_when_targets_match(self) -> None:
        remote = self.make_remote(
            name="origin",
            fetch_url="https://github.com/owner/repo",
            push_url="https://github.com/owner/repo",
            push_is_explicit=False,
        )
        remote.fetch.set_all(True)
        remote.push.set_all(True)

        plan = MODULE.build_execution_plan([remote], "luckydonald")

        self.assertEqual(
            plan.commands,
            [["git", "remote", "set-url", "origin", "https://luckydonald@github.com/owner/repo.git"]],
        )

    def test_build_execution_plan_requires_username_for_selected_username_changes(self) -> None:
        remote = self.make_remote(
            name="origin",
            fetch_url="https://github.com/owner/repo",
            push_url="https://github.com/owner/repo.git",
            push_is_explicit=True,
        )
        with self.assertRaisesRegex(ValueError, "Enter a username"):
            MODULE.build_execution_plan([remote], "")


class IntegrationTests(unittest.TestCase):
    def make_repo(self) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="git-remote-fix-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(temp_dir)], check=False))
        git(["init"], temp_dir)
        git(["config", "user.name", "Tester"], temp_dir)
        git(["config", "user.email", "tester@example.com"], temp_dir)
        return temp_dir

    def test_apply_plan_updates_distinct_fetch_and_push_urls(self) -> None:
        repo = self.make_repo()
        git(["remote", "add", "origin", "https://github.com/owner/repo"], repo)
        git(["remote", "set-url", "--push", "origin", "https://github.com/owner/repo.git"], repo)

        remotes = MODULE.discover_remotes(repo)
        remote = remotes[0]
        remote.fetch.change_username = True
        remote.fetch.add_git_suffix = True
        remote.push.change_username = True
        remote.push.add_git_suffix = False

        plan = MODULE.build_execution_plan(remotes, "luckydonald")
        MODULE.apply_execution_plan(plan, repo)

        self.assertEqual(
            git(["remote", "get-url", "origin"], repo),
            "https://luckydonald@github.com/owner/repo.git",
        )
        self.assertEqual(
            git(["remote", "get-url", "--push", "origin"], repo),
            "https://luckydonald@github.com/owner/repo.git",
        )

    def test_apply_plan_can_pin_push_when_remote_started_shared(self) -> None:
        repo = self.make_repo()
        git(["remote", "add", "origin", "https://github.com/owner/repo"], repo)

        remotes = MODULE.discover_remotes(repo)
        remote = remotes[0]
        remote.fetch.change_username = True
        remote.fetch.add_git_suffix = True
        remote.push.change_username = False
        remote.push.add_git_suffix = False

        plan = MODULE.build_execution_plan(remotes, "luckydonald")
        MODULE.apply_execution_plan(plan, repo)

        self.assertEqual(
            git(["remote", "get-url", "origin"], repo),
            "https://luckydonald@github.com/owner/repo.git",
        )
        self.assertEqual(
            git(["remote", "get-url", "--push", "origin"], repo),
            "https://github.com/owner/repo",
        )

    def test_discover_remotes_keeps_non_github_urls_disabled(self) -> None:
        repo = self.make_repo()
        git(["remote", "add", "template", "../template"], repo)

        remotes = MODULE.discover_remotes(repo)
        remote = remotes[0]
        self.assertFalse(remote.fetch.eligible)
        self.assertFalse(remote.push.eligible)

    def test_apply_lfs_locksverify_fix_sets_local_config_for_github_https_remotes(self) -> None:
        repo = self.make_repo()
        git(["remote", "add", "origin", "https://github.com/owner/repo"], repo)
        git(["remote", "set-url", "--push", "origin", "https://someone@github.com/owner/repo.git"], repo)

        keys = MODULE.apply_lfs_locksverify_fix(repo)

        self.assertEqual(
            keys,
            [
                "lfs.https://github.com/owner/repo.git/info/lfs.locksverify",
                "lfs.https://someone@github.com/owner/repo.git/info/lfs.locksverify",
            ],
        )
        self.assertEqual(
            git(["config", "--local", "--get", keys[0]], repo),
            "false",
        )
        self.assertEqual(
            git(["config", "--local", "--get", keys[1]], repo),
            "false",
        )

    def test_apply_lfs_locksverify_fix_is_idempotent(self) -> None:
        repo = self.make_repo()
        git(["remote", "add", "origin", "https://github.com/owner/repo.git"], repo)

        first_keys = MODULE.apply_lfs_locksverify_fix(repo)
        second_keys = MODULE.apply_lfs_locksverify_fix(repo)

        self.assertEqual(first_keys, ["lfs.https://github.com/owner/repo.git/info/lfs.locksverify"])
        self.assertEqual(second_keys, [])


if __name__ == "__main__":
    unittest.main()
