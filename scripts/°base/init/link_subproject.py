#!/usr/bin/env python3
# scripts/°base/init/link_subproject.py
#
# Idempotent per-subfolder setup for the monorepo case: creates relative
# symlinks at <cwd>/.claude, <cwd>/.codex, <cwd>/ai/settings,
# <cwd>/ai/references, <cwd>/ai/skills, <cwd>/.mcp.json and <cwd>/.worktreeinclude
# pointing at their monorepo-root counterparts, each <cwd>/.run/*.run.xml pointing at its
# monorepo-root counterpart, an <cwd>/ai/.env -> <git_root>/ai/.env symlink
# (touching the monorepo-root ai/.env first if it doesn't exist yet, since
# it's gitignored and not seeded any other way), an <cwd>/AGENTS.md ->
# CLAUDE.md symlink (moving any pre-existing AGENTS.md into CLAUDE.md first,
# mirroring the root layout), an empty `.gitkeep` in each of the ai/{errors,
# output/{agents, explore},plans} scratch dirs, and seeds <cwd>/ai/prompt.md and
# <cwd>/CLAUDE.md from templates when they don't exist yet (copied, not
# symlinked, since they're meant to diverge per subproject). This lets
# Claude Code and Codex find the shared hooks/perms/MCP config when launched
# from inside a subfolder of a monorepo that has the `base` repo merged at
# its top level.
#
# Run configs listed in the monorepo-root `.run/.subprojectIgnore` (one
# `fnmatch` glob per line matched against the file name, `#` comments and blank
# lines allowed) are not linked; links that already exist are left alone.
#
# Because <cwd>/.claude is a symlink to the monorepo root's .claude, Claude
# Code's own native project-identity resolution (used for its auto-memory
# and session storage under ~/.claude/projects/<encoded>/) collapses back to
# the monorepo root instead of using this subfolder — memories saved from a
# session started here would otherwise silently attach to the wrong project.
# This script also seeds <cwd>/.claude-project.rc (named .rc, not .env, so
# it isn't swallowed by this repo's blanket `**/*.env*` .gitignore rule),
# exporting CLAUDE_CODE_PROJECT_DIR_NAME (and a CLAUDE_CONFIG_DIR
# passthrough, which Claude Code requires to be set for the override to take
# effect) pinned to a slug unique to this subfolder. **Source it before
# launching Claude Code here** — e.g. `source .claude-project.rc && claude`
# (or whichever launcher alias) — otherwise memory/session storage will
# attach to the parent project instead of this subfolder.
#
# Run once from inside the subfolder:
#
#   cd monorepo/some_project
#   ../scripts/°base/init/link_subproject.py
#
# `link_subproject.py --resync` (run from anywhere in the repo) is the git-hook
# mode: after a merge or rebase it adds missing `.worktreeinclude` and per-file
# `.run` links and drops dangling `.run` links in every subproject (a folder with
# a tracked `.claude` symlink), then commits just those paths.
#
# Safe to run multiple times — already-correct symlinks/seeded files are
# left alone. Anything pre-existing that would be clobbered by a symlink is
# moved aside first, as `{name}.YYYY-MM-DD_HH-MM-SS.bak.{ext}` (via `git mv`
# when tracked). New symlinks/seeded files (and moved files) are `git add`ed.

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import re
import subprocess
import sys
from datetime import datetime
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "git"))
scoped_commit_lib = import_module("°scoped_commit_lib")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai"))
migrate_query_to_prompt = import_module("migrate_query_to_prompt")

sub_dir: Path
git_root: Path


def git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    ).stdout.strip()
# end def


def realpath_of(path: Path) -> str:
    return os.path.realpath(path)
# end def


def relpath_of(target: Path, from_dir: Path) -> str:
    return os.path.relpath(target, from_dir)
# end def


def is_tracked(rel: str) -> bool:
    try:
        git(["ls-files", "--error-unmatch", "--", rel], sub_dir)
        return True
    except subprocess.CalledProcessError:
        return False
    # end try
# end def


def rev_parse_quiet(rev: str, cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--verify", "--quiet", rev],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None
# end def


def is_ancestor(ancestor: str, descendant: str, cwd: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(cwd), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
    )
    return result.returncode == 0
# end def


def git_dir(cwd: Path) -> Path:
    return Path(git(["rev-parse", "--git-dir"], cwd))
# end def


def env_symlink_committed(rel: str, target: Path) -> bool:
    # "tracked" means HEAD actually has this path, as a symlink whose stored
    # target text matches what's on disk right now — not just present in the
    # index, since a stale/different symlink could technically be tracked at
    # this path.
    if rev_parse_quiet(f"HEAD:./{rel}", sub_dir) is None:
        return False
    # end if
    result = subprocess.run(
        ["git", "-C", str(sub_dir), "cat-file", "-p", f"HEAD:./{rel}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout == os.readlink(sub_dir / rel)
# end def


def commit_env_symlink(rel: str) -> str:
    # `git add -f` since ai/.env is gitignored everywhere — the subproject
    # symlink gets tracked by forcing this one path in, not by carving a
    # gitignore exception (that approach already needed a fix once, see
    # `dc3dbe2`). `core.hooksPath=/dev/null` because this is a synthetic,
    # single-file bookkeeping commit, not a real authored change — a
    # consuming repo's own commit hooks (this one's `pre-commit` suite
    # included) shouldn't get a vote on it, same reasoning `history_master.py`
    # uses for its own internal replay commits.
    git(["add", "-f", "--", rel], sub_dir)
    git(
        ["-c", "core.hooksPath=/dev/null", "commit", "-m", f"link_subproject: track `{rel}` symlink.", "--", rel],
        sub_dir,
    )
    return git(["rev-parse", "HEAD"], sub_dir)
# end def


def verify_env_symlink(target: Path, source: Path) -> bool:
    return target.is_symlink() and realpath_of(target) == realpath_of(source)
# end def


def all_branch_and_tag_refs(cwd: Path) -> list[str]:
    output = git(["for-each-ref", "--format=%(refname)", "refs/heads", "refs/tags"], cwd)
    return [line for line in output.splitlines() if line]
# end def


def refs_reaching(sha: str, cwd: Path) -> list[str]:
    return [ref for ref in all_branch_and_tag_refs(cwd) if is_ancestor(sha, ref, cwd)]
# end def


def reachable_object_shas(cwd: Path) -> set[str]:
    output = git(["rev-list", "--objects", "--all"], cwd)
    return {line.split(" ", 1)[0] for line in output.splitlines() if line}
# end def


def loose_object_path(sha: str, cwd: Path) -> Path:
    return git_dir(cwd) / "objects" / sha[:2] / sha[2:]
# end def


def delete_loose_object_if_unreachable(sha: str | None, reachable: set[str], cwd: Path) -> None:
    if sha is None or sha in reachable:
        return
    # end if
    path = loose_object_path(sha, cwd)
    if path.is_file():
        path.unlink()
        print(f"purged unreachable object {sha}", file=sys.stderr)
    # end if
# end def


def replay_onto(commits: list[str], new_base: str, cwd: Path) -> str:
    # Replays `commits` (oldest first, none of them the purged commit itself)
    # onto `new_base` via a detached scratch branch, so the caller's actual
    # checkout/working tree is left alone throughout, then restores whatever
    # was checked out before this ran. Always runs with `cwd` = the repo
    # root, never the subproject dir — the subproject dir may not exist yet
    # at `new_base` (e.g. its very first tracked file was the purged
    # commit), and `git checkout` would otherwise fail to even start once
    # its cwd disappears from the working tree.
    scratch_ref = "refs/heads/_link_subproject_purge_scratch"
    try:
        original_checkout = git(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd)
    except subprocess.CalledProcessError:
        original_checkout = git(["rev-parse", "HEAD"], cwd)
    # end try

    git(["update-ref", scratch_ref, new_base], cwd)
    git(["checkout", "--quiet", "--detach", scratch_ref], cwd)
    try:
        for commit_sha in commits:
            result = subprocess.run(
                ["git", "-C", str(cwd), "-c", "core.hooksPath=/dev/null", "cherry-pick", commit_sha],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                subprocess.run(["git", "-C", str(cwd), "cherry-pick", "--abort"], capture_output=True)
                raise RuntimeError(
                    f"purge_commit_everywhere: replaying {commit_sha} onto {new_base} conflicted — manual recovery needed."
                )
            # end if
        # end for
        new_tip = git(["rev-parse", "HEAD"], cwd)
    finally:
        git(["checkout", "--quiet", original_checkout], cwd)
        subprocess.run(["git", "-C", str(cwd), "update-ref", "-d", scratch_ref], capture_output=True)
    # end try
    return new_tip
# end def


def purge_commit_everywhere(bad_sha: str, repo_rel_path: str) -> None:
    # Undoes a commit that failed post-commit verification, everywhere it's
    # reachable — including branches/tags that have since moved past it —
    # without ever running `git gc`/`git prune`/`git repack`. Never prints
    # object content, only shas/refs/paths. Operates with cwd = git_root
    # throughout (see `replay_onto`).
    cwd = git_root
    parent = rev_parse_quiet(f"{bad_sha}^", cwd)
    if parent is None:
        raise RuntimeError(f"purge_commit_everywhere: {bad_sha} has no parent — refusing to purge a root commit.")
    # end if

    affected_refs = refs_reaching(bad_sha, cwd)
    if not affected_refs:
        return
    # end if

    print(
        f"purging {bad_sha} from: {', '.join(affected_refs)} "
        f"(prior tips: {', '.join(rev_parse_quiet(r, cwd) or '?' for r in affected_refs)})",
        file=sys.stderr,
    )

    for ref in affected_refs:
        tip = rev_parse_quiet(ref, cwd)
        if tip == bad_sha:
            new_tip = parent
        else:
            descendants = [
                line
                for line in git(["rev-list", "--reverse", "--ancestry-path", f"{bad_sha}..{tip}"], cwd).splitlines()
                if line
            ]
            new_tip = replay_onto(descendants, parent, cwd)
        # end if

        if ref.startswith("refs/tags/"):
            tag_name = ref.removeprefix("refs/tags/")
            git(["tag", "-d", tag_name], cwd)
            git(["tag", tag_name, new_tip], cwd)
        else:
            git(["update-ref", ref, new_tip, tip], cwd)
        # end if
    # end for

    root_tree = rev_parse_quiet(f"{bad_sha}^{{tree}}", cwd)
    parent_repo_rel = os.path.dirname(repo_rel_path)
    ai_tree = rev_parse_quiet(f"{bad_sha}:{parent_repo_rel}", cwd) if parent_repo_rel else None
    blob_sha = rev_parse_quiet(f"{bad_sha}:{repo_rel_path}", cwd)

    reachable = reachable_object_shas(cwd)
    for candidate in (blob_sha, ai_tree, root_tree, bad_sha):
        delete_loose_object_if_unreachable(candidate, reachable, cwd)
    # end for
# end def


def backup_path(rel: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    parent = os.path.dirname(rel)
    base = os.path.basename(rel)
    stem, ext = os.path.splitext(base)
    bak_rel = os.path.join(parent, f"{stem}.{timestamp}.bak{ext}")

    if is_tracked(rel):
        git(["mv", "--", rel, bak_rel], sub_dir)
    else:
        (sub_dir / rel).rename(sub_dir / bak_rel)
    # end if
    print(f"backed up {sub_dir / rel} -> {sub_dir / bak_rel}", file=sys.stderr)
# end def


def link_path(rel: str, source: Path, *, backup: bool = True) -> bool:
    # returns whether a new symlink was created. With `backup=False` (the
    # git-hook re-sync) nothing pre-existing is ever moved or replaced:
    # a conflicting path is skipped with a warning instead.
    target = sub_dir / rel
    target_dir = target.parent

    if not source.exists():
        print(f"no {source} — skipping {rel}", file=sys.stderr)
        return False
    # end if

    target_dir.mkdir(parents=True, exist_ok=True)

    if target.is_symlink():
        if realpath_of(target) == realpath_of(source):
            print(f"{target} already linked to {source}")
            return False
        # end if
        if not backup:
            print(f"{target} is a symlink but points elsewhere ({os.readlink(target)}) — leaving it alone.", file=sys.stderr)
            return False
        # end if
        print(
            f"{target} is a symlink but points elsewhere ({os.readlink(target)}) — backing up.",
            file=sys.stderr,
        )
        backup_path(rel)
    elif target.exists():
        if not backup:
            print(f"{target} exists and is not a symlink — leaving it alone.", file=sys.stderr)
            return False
        # end if
        print(f"{target} exists and is not a symlink — backing up.", file=sys.stderr)
        backup_path(rel)
    # end if

    rel_link = relpath_of(source, target_dir)
    target.symlink_to(rel_link)
    print(f"linked {target} -> {rel_link}")
    git(["add", "--", rel], sub_dir)
    return True
# end def


def link_shared(rel: str) -> None:
    link_path(rel, git_root / rel)
# end def


def link_worktree_include(*, backup: bool = True) -> list[str]:
    rel = ".worktreeinclude"
    source = git_root / rel
    if source.is_file() and link_path(rel, source, backup=backup):
        return [rel]
    # end if
    return []
# end def


def copy_if_missing(rel: str, template_name: str) -> None:
    source = git_root / "scripts" / "°base" / "init" / "templates" / template_name
    target = sub_dir / rel

    if target.exists() or target.is_symlink():
        print(f"{target} already exists — leaving it alone.")
        return
    # end if

    if not source.exists():
        print(f"no {source} — skipping {rel}", file=sys.stderr)
        return
    # end if

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    print(f"seeded {target} from {source}")
    git(["add", "--", rel], sub_dir)
# end def


SUBPROJECT_IGNORE_NAME = ".subprojectIgnore"


def read_subproject_ignore() -> list[str]:
    # the patterns of `<git_root>/.run/.subprojectIgnore`: one `fnmatch` glob per
    # line, matched against the config's file name; blank lines and `#` comment
    # lines are skipped. A missing or unreadable file ignores nothing.
    try:
        text = (git_root / ".run" / SUBPROJECT_IGNORE_NAME).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    # end try
    stripped = (line.strip() for line in text.splitlines())
    return [line for line in stripped if line and not line.startswith("#")]
# end def


def is_subproject_ignored(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)
# end def


def link_run_configs(*, backup: bool = True) -> list[str]:
    # returns the sub_dir-relative paths of the symlinks newly created.
    run_dir = git_root / ".run"
    created: list[str] = []

    if not run_dir.is_dir():
        print(f"no {run_dir} — skipping .run configs", file=sys.stderr)
        return created
    # end if

    ignored = read_subproject_ignore()
    for f in sorted(run_dir.glob("*.run.xml")):
        if is_subproject_ignored(f.name, ignored):
            print(f"{f.name} is listed in {SUBPROJECT_IGNORE_NAME} — not linking.")
            continue
        # end if
        rel = f".run/{f.name}"
        if link_path(rel, git_root / rel, backup=backup):
            created.append(rel)
        # end if
    # end for
    return created
# end def


def prune_dangling_run_links() -> list[str]:
    # removes `<sub_dir>/.run/*.run.xml` symlinks that point into the
    # monorepo-root `.run/` but whose target no longer exists. Anything that
    # is not a symlink, or points elsewhere, is never touched. Returns the
    # sub_dir-relative paths removed.
    run_dir = sub_dir / ".run"
    root_run_dir = str(git_root / ".run") + os.sep
    removed: list[str] = []

    if not run_dir.is_dir():
        return removed
    # end if

    for f in sorted(run_dir.glob("*.run.xml")):
        if not f.is_symlink() or f.exists():
            continue
        # end if
        resolved = os.path.normpath(os.path.join(f.parent, os.readlink(f)))
        if not resolved.startswith(root_run_dir):
            continue
        # end if
        rel = f".run/{f.name}"
        if is_tracked(rel):
            git(["rm", "-f", "--quiet", "--", rel], sub_dir)
        else:
            f.unlink()
        # end if
        print(f"removed dangling {f}")
        removed.append(rel)
    # end for
    return removed
# end def


RESYNC_COMMIT_MESSAGE = "link_subproject: re-sync subproject links."


def find_subproject_dirs() -> list[Path]:
    # a subproject is a folder holding a tracked `.claude` symlink (mode
    # 120000), which is what `link_shared(".claude")` creates. NUL-delimited,
    # as the names can hold anything (emoji, spaces, `&`).
    raw = subprocess.run(
        ["git", "-C", str(git_root), "ls-files", "-z", "-s"], capture_output=True, text=True, check=True
    ).stdout
    found: list[Path] = []
    for entry in raw.split("\0"):
        meta, _, path = entry.partition("\t")
        if not meta.startswith("120000 ") or not path.endswith("/.claude"):
            continue
        # end if
        found.append(git_root / path.removesuffix("/.claude"))
    # end for
    return sorted(found)
# end def


def commit_blocker(event: str | None) -> str | None:
    return scoped_commit_lib.commit_blocker(event, git_root)
# end def


def commit_resync(paths: list[str], event: str | None) -> str | None:
    # commits exactly the re-synced link `paths` (git-root-relative, already staged) and nothing else.
    new_sha = scoped_commit_lib.commit_staged_paths(paths, RESYNC_COMMIT_MESSAGE, event=event, cwd=git_root)
    if new_sha:
        print(f"committed re-synced links as {new_sha}")
    # end if
    return new_sha
# end def


def resync_all(*, event: str | None = None, commit: bool = True) -> int:
    # git-hook entry point (after a merge or rebase): adds missing
    # `.worktreeinclude` and `.run` links and prunes dangling `.run` links.
    global sub_dir

    touched: list[str] = []
    for sub in find_subproject_dirs():
        sub_dir = sub
        try:
            changed = link_run_configs(backup=False) + prune_dangling_run_links()
            changed += link_worktree_include(backup=False)
        except (subprocess.CalledProcessError, OSError) as e:
            print(f"re-syncing {sub} failed: {e}", file=sys.stderr)
            continue
        # end try
        touched += [relpath_of(sub / rel, git_root) for rel in changed]
    # end for

    if not touched:
        print("subproject links already up to date.")
        return 0
    # end if
    if commit:
        commit_resync(touched, event)
    # end if
    return 0
# end def


def touch_scratch_gitkeeps() -> None:
    for rel in ("ai/errors", "ai/output/agents", "ai/output/explore", "ai/plans"):
        target = sub_dir / rel / ".gitkeep"
        if target.exists():
            print(f"{target} already exists — leaving it alone.")
            continue
        # end if
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        print(f"touched {target}")
        git(["add", "--", f"{rel}/.gitkeep"], sub_dir)
    # end for
# end def


def link_env() -> None:
    # symlinks <sub_dir>/ai/.env -> <git_root>/ai/.env, touching the
    # monorepo-root ai/.env first if it doesn't exist yet (it's gitignored, so
    # link_path's usual "no source — skipping" behavior would otherwise leave
    # this permanently unlinked). ai/.env is gitignored everywhere (root and
    # every subfolder) — the subproject symlink still gets tracked, but via
    # `git add -f` in the commit dance below, not a gitignore exception.
    rel = "ai/.env"
    source = git_root / rel

    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        source.touch()
        print(f"touched {source}")
    # end if

    target = sub_dir / rel
    target_dir = target.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    if target.is_symlink():
        if realpath_of(target) != realpath_of(source):
            print(
                f"{target} is a symlink but points elsewhere ({os.readlink(target)}) — leaving it alone.",
                file=sys.stderr,
            )
            return
        # end if
        if env_symlink_committed(rel, target):
            print(f"{target} already linked to {source} and committed.")
            return
        # end if
        print(f"{target} is already linked to {source} but not committed — committing.")
    elif target.exists():
        print(f"{target} exists and is not a symlink — leaving it alone.", file=sys.stderr)
        return
    else:
        rel_link = relpath_of(source, target_dir)
        target.symlink_to(rel_link)
        print(f"linked {target} -> {rel_link}")
    # end if

    # Commit dance: assert it's really the fresh symlink, force-add + commit
    # just this path, then re-verify before trusting it. If verification
    # fails, undo the commit everywhere it landed and leave the path
    # untracked again — never print the file's content anywhere in this path.
    if not verify_env_symlink(target, source):
        raise RuntimeError(f"{target} is not the expected symlink right before committing it")
    # end if

    new_sha = commit_env_symlink(rel)

    if verify_env_symlink(target, source):
        print(f"committed {target} as {new_sha}")
        return
    # end if

    print(f"{target} failed post-commit verification — undoing {new_sha}.", file=sys.stderr)
    repo_rel_path = relpath_of(target, git_root)
    purge_commit_everywhere(new_sha, repo_rel_path)
    git(["rm", "--cached", "--", rel], sub_dir)
    raise RuntimeError(f"{target}: post-commit verification failed, commit {new_sha} was purged; left untracked")
# end def


def link_agents_claude() -> None:
    agents = sub_dir / "AGENTS.md"
    claude = sub_dir / "CLAUDE.md"

    if agents.is_symlink():
        if claude.exists() and realpath_of(agents) == realpath_of(claude):
            print(f"{agents} already linked to {claude}")
            return
        # end if
        print(
            f"{agents} is a symlink but points elsewhere ({os.readlink(agents)}) — backing up.",
            file=sys.stderr,
        )
        backup_path("AGENTS.md")
    elif agents.exists():
        if claude.exists():
            print(f"{agents} and {claude} both exist — backing up {agents}.", file=sys.stderr)
            backup_path("AGENTS.md")
        else:
            print(f"moving {agents} -> {claude}", file=sys.stderr)
            if is_tracked("AGENTS.md"):
                git(["mv", "--", "AGENTS.md", "CLAUDE.md"], sub_dir)
            else:
                agents.rename(claude)
            # end if
        # end if
    # end if

    if not claude.exists():
        print(f"no {claude} — nothing to point AGENTS.md at, skipping.", file=sys.stderr)
        return
    # end if

    agents.symlink_to("CLAUDE.md")
    print(f"linked {agents} -> CLAUDE.md")
    git(["add", "--", "AGENTS.md", "CLAUDE.md"], sub_dir)
# end def


def project_dir_name_slug(rel: str) -> str:
    # a stable, Claude-Code-safe slug (matching ^[A-Za-z0-9_-]{1,64}$) unique
    # to this subfolder within the monorepo, for CLAUDE_CODE_PROJECT_DIR_NAME.
    # Non-matching characters become `-`; if the git-root-basename +
    # sanitized relative path would exceed 64 chars, it's truncated and
    # suffixed with an 8-hex-char sha1 of the absolute path to avoid
    # collisions.
    raw = f"{git_root.name}-{rel}"
    slug = re.sub(r"[^A-Za-z0-9_-]", "-", raw).strip("-")
    if len(slug) > 64:
        digest = hashlib.sha1(str(git_root / rel).encode()).hexdigest()[:8]
        slug = f"{slug[:55]}-{digest}"
    # end if
    return slug
# end def


def seed_claude_project_env() -> None:
    # writes <sub_dir>/.claude-project.rc (once; never overwrites an
    # existing one) so sourcing it before launching Claude Code here pins
    # CLAUDE_CODE_PROJECT_DIR_NAME to a slug unique to this subfolder,
    # working around Claude Code's own project-identity resolution
    # collapsing back to the monorepo root through the symlinked .claude
    # (see header). Named .rc rather than .env so it isn't swallowed by
    # this repo's blanket `**/*.env*` .gitignore rule.
    target = sub_dir / ".claude-project.rc"
    if target.exists():
        print(f"{target} already exists — leaving it alone.")
        return
    # end if

    rel = relpath_of(sub_dir, git_root)
    slug = project_dir_name_slug(rel)

    target.write_text(
        "# Generated by link_subproject.py — source before launching Claude Code here:\n"
        "#   source .claude-project.rc && claude\n"
        "# Without this, Claude Code's native memory/session storage attaches to the\n"
        "# monorepo root instead of this subfolder (its .claude is a symlink there).\n"
        'export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"\n'
        f'export CLAUDE_CODE_PROJECT_DIR_NAME="{slug}"\n'
    )
    print(f"seeded {target} (CLAUDE_CODE_PROJECT_DIR_NAME={slug})")
    git(["add", "--", ".claude-project.rc"], sub_dir)
# end def


def main() -> int:
    global sub_dir, git_root

    sub_dir = Path(os.path.realpath(os.getcwd()))
    git_root = Path(
        os.path.realpath(
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=sub_dir,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    )
    root_claude = git_root / ".claude"

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resync", action="store_true", help="re-sync the per-file links of every subproject (git hook mode)")
    parser.add_argument("--event", choices=["merge", "rebase"], help="the git hook calling this (post-merge, post-rewrite)")
    parser.add_argument("--no-commit", action="store_true", help="with --resync: only stage, do not commit")
    args = parser.parse_args()

    if args.resync:
        commit = not args.no_commit and os.environ.get("SUBPROJECT_RESYNC_COMMIT") != "0"
        return resync_all(event=args.event, commit=commit)
    # end if

    if sub_dir == git_root:
        print(f"{sub_dir} is the git root — no symlinks needed.", file=sys.stderr)
        return 0
    # end if

    if not root_claude.is_dir():
        print(f"no {root_claude} — did you merge base/base at the repo root?", file=sys.stderr)
        return 1
    # end if

    link_shared(".claude")
    link_shared(".codex")
    link_shared("ai/settings")
    link_shared("ai/references")
    link_shared("ai/skills")
    link_shared(".mcp.json")
    link_worktree_include()
    link_env()
    link_run_configs()
    touch_scratch_gitkeeps()
    migrate_query_to_prompt.migrate_dir(sub_dir / "ai")
    copy_if_missing("ai/prompt.md", "prompt.md")
    copy_if_missing("CLAUDE.md", "CLAUDE.md")
    link_agents_claude()
    seed_claude_project_env()
    return 0
# end def


if __name__ == "__main__":
    sys.exit(main())
# end if
