"""Tests for `scripts/°base/init/link_subproject.py`'s `ai/.env` symlink
state machine and its post-commit-verification-failure purge routine.

Every test builds its own throwaway repo under a pytest/unittest tmp
directory — nothing here ever touches this actual repo's real branches or
tags.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _git_test_helpers import git, init_repo, make_commit  # noqa: E402

INIT_DIR = Path(__file__).resolve().parents[1] / "init"
sys.path.insert(0, str(INIT_DIR))
link_subproject = importlib.import_module("link_subproject")

REPO_ROOT = Path(__file__).resolve().parents[3]


def build_subproject_repo() -> tuple[TemporaryDirectory, Path, Path]:
    """A minimal throwaway repo with one commit and an (uncreated) `sub/`
    subfolder — enough for `link_env`/`purge_commit_everywhere` in isolation,
    without the cost of a full monorepo checkout.
    """
    tmp = TemporaryDirectory()
    repo_root = Path(tmp.name) / "repo"
    repo_root.mkdir()
    init_repo(repo_root)
    make_commit(repo_root, ".claude/keep", "init")
    sub_dir = repo_root / "sub"
    sub_dir.mkdir()
    return tmp, repo_root, sub_dir


def build_merged_monorepo_fixture() -> tuple[TemporaryDirectory, Path]:
    """A repo built the way `docs/README.md#all-code-for-c-as-a-single-copy-pastable-one`
    documents for adopting `base/base` — simplified to pull straight from
    this checkout instead of GitHub, and dropping the `user.name` check and
    `pre-commit install` (not relevant for a throwaway test repo) — so
    `main()` has genuine `.claude`/`ai/settings`/etc. targets to link
    against, the same as a real subproject would.
    """
    tmp = TemporaryDirectory()
    repo_root = Path(tmp.name) / "repo"
    repo_root.mkdir()
    git(["init", "-q", "-b", "mane"], repo_root)
    git(["config", "user.email", "test@example.com"], repo_root)
    git(["config", "user.name", "Test"], repo_root)
    git(["remote", "add", "base", str(REPO_ROOT)], repo_root)
    git(["fetch", "-q", "base", "base"], repo_root)
    git(["lfs", "install", "--local"], repo_root)
    # `FETCH_HEAD`, not `base/base`: when this checkout only has `base` as a
    # remote-tracking ref (any consumer repo), the fetch resolves it but
    # creates no `base/base` ref in the throwaway repo.
    git(["merge", "-q", "--allow-unrelated-histories", "--no-verify", "FETCH_HEAD"], repo_root)
    return tmp, repo_root
# end def


class LinkEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp, self.repo_root, self.sub_dir = build_subproject_repo()
        self.addCleanup(self.tmp.cleanup)
        link_subproject.sub_dir = self.sub_dir
        link_subproject.git_root = self.repo_root
    # end def

    def target(self) -> Path:
        return self.sub_dir / "ai" / ".env"
    # end def

    def test_fresh_subfolder_gets_symlinked_and_committed(self) -> None:
        link_subproject.link_env()

        target = self.target()
        self.assertTrue(target.is_symlink())
        self.assertEqual(os.path.realpath(target), os.path.realpath(self.repo_root / "ai" / ".env"))
        self.assertTrue(link_subproject.env_symlink_committed("ai/.env", target))
    # end def

    def test_rerun_on_an_already_committed_symlink_is_a_no_op(self) -> None:
        link_subproject.link_env()
        head_before = git(["rev-parse", "HEAD"], self.repo_root)

        link_subproject.link_env()
        head_after = git(["rev-parse", "HEAD"], self.repo_root)

        self.assertEqual(head_before, head_after)
    # end def

    def test_correct_but_uncommitted_symlink_gets_committed_on_rerun(self) -> None:
        (self.sub_dir / "ai").mkdir(parents=True)
        (self.repo_root / "ai").mkdir(exist_ok=True)
        (self.repo_root / "ai" / ".env").touch()
        rel_link = os.path.relpath(self.repo_root / "ai" / ".env", self.sub_dir / "ai")
        self.target().symlink_to(rel_link)

        self.assertFalse(link_subproject.env_symlink_committed("ai/.env", self.target()))

        link_subproject.link_env()

        self.assertTrue(link_subproject.env_symlink_committed("ai/.env", self.target()))
    # end def

    def test_regular_file_target_is_left_untouched(self) -> None:
        (self.sub_dir / "ai").mkdir(parents=True)
        self.target().write_text("SECRET=1")

        link_subproject.link_env()

        self.assertEqual(self.target().read_text(), "SECRET=1")
        staged = git(["diff", "--cached", "--name-only"], self.repo_root)
        self.assertEqual(staged, "", "nothing should have been staged")
    # end def

    def test_symlink_to_something_else_is_left_untouched(self) -> None:
        (self.sub_dir / "ai").mkdir(parents=True)
        other = self.repo_root / "other_target"
        other.write_text("nope")
        rel_link = os.path.relpath(other, self.sub_dir / "ai")
        self.target().symlink_to(rel_link)

        link_subproject.link_env()

        self.assertEqual(os.readlink(self.target()), rel_link)
        staged = git(["diff", "--cached", "--name-only"], self.repo_root)
        self.assertEqual(staged, "", "nothing should have been staged")
    # end def

    def test_post_commit_verification_failure_purges_the_commit(self) -> None:
        with mock.patch.object(link_subproject, "verify_env_symlink", side_effect=[True, False]):
            with self.assertRaises(RuntimeError):
                link_subproject.link_env()
            # end with
        # end with

        target = self.target()
        self.assertTrue(target.is_symlink())
        self.assertFalse(link_subproject.is_tracked("ai/.env"))

        log = git(["log", "--oneline"], self.repo_root)
        self.assertNotIn("link_subproject", log)
    # end def

    def test_purge_failure_never_prints_the_secret_env_content(self) -> None:
        secret = "SUPER_SECRET_TOKEN_MARKER"
        (self.repo_root / "ai").mkdir(exist_ok=True)
        (self.repo_root / "ai" / ".env").write_text(secret)

        import contextlib
        import io

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            with mock.patch.object(link_subproject, "verify_env_symlink", side_effect=[True, False]):
                with self.assertRaises(RuntimeError):
                    link_subproject.link_env()
                # end with
            # end with
        # end with

        self.assertNotIn(secret, captured.getvalue())
    # end def
# end class


class PurgeCommitEverywhereTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp, self.repo_root, self.sub_dir = build_subproject_repo()
        self.addCleanup(self.tmp.cleanup)
        link_subproject.sub_dir = self.sub_dir
        link_subproject.git_root = self.repo_root
        self.base_sha = git(["rev-parse", "HEAD"], self.repo_root)
    # end def

    def test_rewinds_a_branch_pointing_directly_at_the_bad_commit(self) -> None:
        bad_sha = make_commit(self.sub_dir, "ai/.env", "bad env symlink stand-in")

        link_subproject.purge_commit_everywhere(bad_sha, "sub/ai/.env")

        self.assertEqual(git(["rev-parse", "master"], self.repo_root), self.base_sha)
    # end def

    def test_rewrites_a_tag_pointing_at_the_bad_commit(self) -> None:
        bad_sha = make_commit(self.sub_dir, "ai/.env", "bad env symlink stand-in")
        git(["tag", "mytag"], self.repo_root)

        link_subproject.purge_commit_everywhere(bad_sha, "sub/ai/.env")

        self.assertEqual(git(["rev-parse", "mytag"], self.repo_root), self.base_sha)
    # end def

    def test_replays_descendants_committed_on_top_of_the_bad_commit(self) -> None:
        bad_sha = make_commit(self.sub_dir, "ai/.env", "bad env symlink stand-in")
        make_commit(self.sub_dir, "other/file.txt", "unrelated later work")

        link_subproject.purge_commit_everywhere(bad_sha, "sub/ai/.env")

        new_tip = git(["rev-parse", "master"], self.repo_root)
        self.assertTrue(link_subproject.is_ancestor(self.base_sha, new_tip, self.repo_root))
        self.assertFalse(link_subproject.is_ancestor(bad_sha, new_tip, self.repo_root))

        tree_files = git(["ls-tree", "-r", "--name-only", new_tip], self.repo_root).splitlines()
        self.assertNotIn("sub/ai/.env", tree_files)
        self.assertIn("sub/other/file.txt", tree_files)
    # end def

    def test_leaves_a_still_reachable_shared_blob_alone(self) -> None:
        content = "../../ai/.env"
        bad_sha = make_commit(self.sub_dir, "ai/.env", "bad env symlink stand-in", content=content)

        git(["branch", "sibling", self.base_sha], self.repo_root)
        git(["checkout", "-q", "sibling"], self.repo_root)
        make_commit(self.repo_root, "other_subproject/ai/.env", "identical content elsewhere", content=content)
        git(["checkout", "-q", "master"], self.repo_root)

        blob_sha = git(["rev-parse", f"{bad_sha}:sub/ai/.env"], self.repo_root)

        link_subproject.purge_commit_everywhere(bad_sha, "sub/ai/.env")

        result = subprocess.run(
            ["git", "-C", str(self.repo_root), "cat-file", "-e", blob_sha], capture_output=True
        )
        self.assertEqual(result.returncode, 0, "blob should still be reachable via the sibling branch")
    # end def

    def test_never_shells_out_to_gc_prune_or_repack(self) -> None:
        source = (INIT_DIR / "link_subproject.py").read_text()
        for forbidden in ('"gc"', '"prune"', '"repack"'):
            self.assertNotIn(forbidden, source)
        # end for
    # end def
# end class


class LinkSubprojectEndToEndTests(unittest.TestCase):
    def test_main_links_and_commits_against_a_real_merged_monorepo(self) -> None:
        tmp, repo_root = build_merged_monorepo_fixture()
        self.addCleanup(tmp.cleanup)
        sub_dir = repo_root / "some_project"
        sub_dir.mkdir()

        result = subprocess.run(
            [sys.executable, str(INIT_DIR / "link_subproject.py")],
            cwd=sub_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((sub_dir / ".claude").is_symlink())
        self.assertTrue((sub_dir / "ai" / ".env").is_symlink())
        self.assertEqual(os.readlink(sub_dir / ".worktreeinclude"), "../.worktreeinclude")

        # Everything link_subproject touched should be staged (or, for
        # ai/.env, already committed) — nothing left untracked or unstaged.
        status_lines = git(["status", "--porcelain"], repo_root).splitlines()
        for line in status_lines:
            self.assertFalse(line.startswith("??"), f"untracked leftover: {line}")
            self.assertEqual(line[1], " ", f"unstaged leftover: {line}")
        # end for

        # idempotent rerun
        rerun = subprocess.run(
            [sys.executable, str(INIT_DIR / "link_subproject.py")],
            cwd=sub_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
    # end def
# end class


HOOK_WRAPPER = Path(__file__).resolve().parents[1] / "git" / "hooks" / "post" / "resync_subproject_links.py"
EMOJI_RUN = "🅱️✨1 _ Tag & go.run.xml"


def build_resync_repo() -> tuple[TemporaryDirectory, Path, Path]:
    """A throwaway monorepo with a root `.run/` holding two configs and one
    already fully linked subproject `sub/` (a tracked `.claude` symlink plus
    the `.run` links), all committed.
    """
    tmp = TemporaryDirectory()
    repo_root = Path(tmp.name) / "repo"
    repo_root.mkdir()
    init_repo(repo_root)
    (repo_root / ".claude").mkdir()
    (repo_root / ".claude" / "keep").write_text("x")
    (repo_root / ".run").mkdir()
    (repo_root / ".run" / "a.run.xml").write_text("a")
    (repo_root / ".run" / EMOJI_RUN).write_text("e")
    sub_dir = repo_root / "sub"
    (sub_dir / ".run").mkdir(parents=True)
    (sub_dir / ".claude").symlink_to("../.claude")
    for name in ("a.run.xml", EMOJI_RUN):
        (sub_dir / ".run" / name).symlink_to(f"../../.run/{name}")
    # end for
    git(["add", "-A"], repo_root)
    git(["commit", "-m", "init"], repo_root)
    return tmp, repo_root, sub_dir
# end def


class ResyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp, self.repo_root, self.sub_dir = build_resync_repo()
        self.addCleanup(self.tmp.cleanup)
        link_subproject.git_root = Path(os.path.realpath(self.repo_root))
        link_subproject.sub_dir = self.sub_dir
        self.addCleanup(lambda: os.environ.pop("SUBPROJECT_RESYNC_COMMIT", None))
    # end def

    def head(self) -> str:
        return git(["rev-parse", "HEAD"], self.repo_root)
    # end def

    def committed_paths(self) -> list[str]:
        return git(["-c", "core.quotepath=off", "show", "--name-only", "--format=", "HEAD"], self.repo_root).splitlines()
    # end def

    def test_new_root_run_config_is_linked_and_committed(self) -> None:
        (self.repo_root / ".run" / "new b.run.xml").write_text("n")
        git(["add", "-A"], self.repo_root)
        git(["commit", "-m", "root adds config"], self.repo_root)
        before = self.head()

        link_subproject.resync_all()

        self.assertTrue((self.sub_dir / ".run" / "new b.run.xml").is_symlink())
        self.assertNotEqual(before, self.head())
        self.assertEqual(self.committed_paths(), ["sub/.run/new b.run.xml"])
        self.assertEqual(git(["log", "-1", "--format=%s"], self.repo_root), link_subproject.RESYNC_COMMIT_MESSAGE)
    # end def

    def test_ignored_root_run_configs_are_not_linked(self) -> None:
        (self.repo_root / ".run" / ".subprojectIgnore").write_text(
            "# root only\n\nroot only.run.xml\r\n  🅱️*.local.run.xml  \n"
        )
        for name in ("root only.run.xml", "🅱️x.local.run.xml", "kept.run.xml"):
            (self.repo_root / ".run" / name).write_text("n")
        # end for
        git(["add", "-A"], self.repo_root)
        git(["commit", "-m", "root adds configs"], self.repo_root)

        link_subproject.resync_all()

        self.assertEqual(self.committed_paths(), ["sub/.run/kept.run.xml"])
        self.assertFalse((self.sub_dir / ".run" / "root only.run.xml").exists())
        self.assertFalse((self.sub_dir / ".run" / "🅱️x.local.run.xml").is_symlink())
        self.assertFalse((self.sub_dir / ".run" / ".subprojectIgnore").exists())
    # end def

    def test_manual_run_skips_ignored_configs(self) -> None:
        (self.repo_root / ".run" / ".subprojectIgnore").write_text("a.run.xml\n")
        (self.repo_root / ".run" / "b.run.xml").write_text("b")
        (self.sub_dir / ".run" / "a.run.xml").unlink()

        created = link_subproject.link_run_configs()

        self.assertEqual(created, [".run/b.run.xml"])
        self.assertFalse((self.sub_dir / ".run" / "a.run.xml").exists())
    # end def

    def test_existing_link_of_a_now_ignored_config_is_left_alone(self) -> None:
        (self.repo_root / ".run" / ".subprojectIgnore").write_text("*.run.xml\n")
        before = self.head()

        link_subproject.resync_all()

        self.assertTrue((self.sub_dir / ".run" / "a.run.xml").is_symlink())
        self.assertTrue((self.sub_dir / ".run" / EMOJI_RUN).is_symlink())
        self.assertEqual(before, self.head())
    # end def

    def test_missing_ignore_file_ignores_nothing(self) -> None:
        self.assertEqual(link_subproject.read_subproject_ignore(), [])
        self.assertFalse(link_subproject.is_subproject_ignored("a.run.xml", []))
    # end def

    def test_dangling_link_to_a_removed_root_config_is_removed_and_committed(self) -> None:
        git(["rm", "-q", "--", f".run/{EMOJI_RUN}"], self.repo_root)
        git(["commit", "-m", "root removes config"], self.repo_root)

        link_subproject.resync_all()

        self.assertFalse((self.sub_dir / ".run" / EMOJI_RUN).is_symlink())
        self.assertEqual(self.committed_paths(), [f"sub/.run/{EMOJI_RUN}"])
        self.assertTrue((self.sub_dir / ".run" / "a.run.xml").is_symlink())
    # end def

    def test_foreign_link_and_regular_file_are_left_alone(self) -> None:
        (self.sub_dir / ".run" / "mine.run.xml").symlink_to("nowhere.xml")
        (self.sub_dir / ".run" / "a.run.xml").unlink()
        (self.sub_dir / ".run" / "a.run.xml").write_text("local copy")
        (self.repo_root / ".worktreeinclude").write_text("ai/.env\n")
        (self.sub_dir / ".worktreeinclude").write_text(".env.local\n")

        link_subproject.resync_all()

        self.assertTrue((self.sub_dir / ".run" / "mine.run.xml").is_symlink())
        self.assertEqual((self.sub_dir / ".run" / "a.run.xml").read_text(), "local copy")
        self.assertFalse((self.sub_dir / ".worktreeinclude").is_symlink())
        self.assertEqual((self.sub_dir / ".worktreeinclude").read_text(), ".env.local\n")
    # end def

    def test_up_to_date_repo_makes_no_commit_and_rerun_is_a_no_op(self) -> None:
        before = self.head()
        link_subproject.resync_all()
        self.assertEqual(before, self.head())

        (self.repo_root / ".run" / "c.run.xml").write_text("c")
        git(["add", "-A"], self.repo_root)
        git(["commit", "-m", "root adds c"], self.repo_root)
        link_subproject.resync_all()
        after_first = self.head()
        link_subproject.resync_all()
        self.assertEqual(after_first, self.head())
    # end def

    def test_only_folders_with_a_tracked_claude_symlink_are_subprojects(self) -> None:
        (self.repo_root / "plain").mkdir()
        (self.repo_root / "plain" / "f").write_text("x")
        git(["add", "-A"], self.repo_root)
        git(["commit", "-m", "plain folder"], self.repo_root)

        found = link_subproject.find_subproject_dirs()

        self.assertEqual([p.name for p in found], ["sub"])
    # end def

    def stage_new_config(self) -> None:
        (self.repo_root / ".run" / "z.run.xml").write_text("z")
        git(["add", "-A"], self.repo_root)
        git(["commit", "-m", "root adds z"], self.repo_root)
    # end def

    def test_commit_takes_only_the_links_and_keeps_other_staged_work(self) -> None:
        self.stage_new_config()
        (self.repo_root / "wip.txt").write_text("work in progress")
        git(["add", "wip.txt"], self.repo_root)

        link_subproject.resync_all()

        self.assertEqual(self.committed_paths(), ["sub/.run/z.run.xml"])
        self.assertEqual(git(["diff", "--cached", "--name-only"], self.repo_root), "wip.txt")
    # end def

    def assert_staged_not_committed(self, before: str) -> None:
        self.assertEqual(before, self.head())
        self.assertEqual(git(["diff", "--cached", "--name-only"], self.repo_root), "sub/.run/z.run.xml")
    # end def

    def test_no_commit_while_a_merge_is_in_progress(self) -> None:
        self.stage_new_config()
        before = self.head()
        gdir = Path(git(["rev-parse", "--absolute-git-dir"], self.repo_root))
        (gdir / "MERGE_HEAD").write_text(before + "\n")

        link_subproject.resync_all()

        self.assert_staged_not_committed(before)
    # end def

    def test_no_commit_on_a_detached_head(self) -> None:
        self.stage_new_config()
        git(["checkout", "-q", "--detach"], self.repo_root)
        before = self.head()

        link_subproject.resync_all()

        self.assert_staged_not_committed(before)
    # end def

    def test_no_commit_with_an_index_lock(self) -> None:
        gdir = Path(git(["rev-parse", "--absolute-git-dir"], self.repo_root))
        self.assertIsNone(link_subproject.commit_blocker(False))
        (gdir / "index.lock").write_text("")

        self.assertEqual(link_subproject.commit_blocker(False), "index.lock present")
    # end def

    def test_rebase_directory_blocks_only_the_non_rebase_events(self) -> None:
        gdir = Path(git(["rev-parse", "--absolute-git-dir"], self.repo_root))
        (gdir / "rebase-merge").mkdir()

        self.assertEqual(link_subproject.commit_blocker(False), "rebase-merge present")
        self.assertIsNone(link_subproject.commit_blocker("rebase"))
    # end def

    def test_merge_event_commits_a_single_parent_commit_despite_merge_head(self) -> None:
        self.stage_new_config()
        before = self.head()
        gdir = Path(git(["rev-parse", "--absolute-git-dir"], self.repo_root))
        (gdir / "MERGE_HEAD").write_text(before + "\n")

        link_subproject.resync_all(event="merge")

        self.assertEqual(git(["rev-parse", "HEAD^"], self.repo_root), before)
        self.assertEqual(git(["rev-list", "--parents", "-n1", "HEAD"], self.repo_root).count(" "), 1)
        self.assertEqual(self.committed_paths(), ["sub/.run/z.run.xml"])
        self.assertEqual(git(["status", "--porcelain"], self.repo_root), "")
    # end def

    def test_env_opt_out_only_stages(self) -> None:
        self.stage_new_config()
        before = self.head()

        result = subprocess.run(
            [sys.executable, str(INIT_DIR / "link_subproject.py"), "--resync"],
            cwd=self.repo_root, capture_output=True, text=True, env={**os.environ, "SUBPROJECT_RESYNC_COMMIT": "0"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_staged_not_committed(before)
    # end def

    def run_wrapper(self, rewrite_command: str | None) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k != "PRE_COMMIT_REWRITE_COMMAND"}
        if rewrite_command is not None:
            env["PRE_COMMIT_REWRITE_COMMAND"] = rewrite_command
        # end if
        return subprocess.run([sys.executable, str(HOOK_WRAPPER)], cwd=self.repo_root, capture_output=True, text=True, env=env)
    # end def

    def test_wrapper_ignores_amend(self) -> None:
        self.stage_new_config()
        before = self.head()

        result = self.run_wrapper("amend")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.head())
        self.assertFalse((self.sub_dir / ".run" / "z.run.xml").exists())
    # end def

    def test_wrapper_resyncs_after_merge_and_rebase(self) -> None:
        (self.repo_root / ".worktreeinclude").write_text("ai/.env\n")
        self.stage_new_config()
        result = self.run_wrapper(None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.committed_paths(), ["sub/.run/z.run.xml", "sub/.worktreeinclude"])
        self.assertEqual(os.readlink(self.sub_dir / ".worktreeinclude"), "../.worktreeinclude")

        (self.repo_root / ".run" / "y.run.xml").write_text("y")
        git(["add", "-A"], self.repo_root)
        git(["commit", "-m", "root adds y"], self.repo_root)
        result = self.run_wrapper("rebase")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.committed_paths(), ["sub/.run/y.run.xml"])
    # end def

    def test_wrapper_exits_zero_when_the_script_fails(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HOOK_WRAPPER)], cwd=self.tmp.name, capture_output=True, text=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("warning", result.stderr)
    # end def
# end class


if __name__ == "__main__":
    unittest.main()
# end if
