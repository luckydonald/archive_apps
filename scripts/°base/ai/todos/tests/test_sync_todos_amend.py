"""Amending a clean todo sync commit, tried in shallow clones of this very repo.

Run: uv run --with pytest --with 'pydantic>=2.6' --with 'mcp>=2.3' --with python-dotenv pytest scripts/°base/ai/todos/tests/test_sync_todos_amend.py

Every test works in a clone of its own, so they share no state and can run in parallel (`pytest -n auto`, needs `pytest-xdist`).
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

if "sync_todos" not in sys.modules:  # pydantic resolves its annotations through `sys.modules`, so there must be one module only
    _spec = importlib.util.spec_from_file_location("sync_todos", Path(__file__).resolve().parent.parent / "sync_todos.py")
    sys.modules["sync_todos"] = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(sys.modules["sync_todos"])
# end if
st = sys.modules["sync_todos"]

REPO_ROOT = Path(__file__).resolve().parents[5]
TODO_FILE = "ai/°base/todos.md"


def todo(uid, summary, **kw):
    return {"uid": uid, "summary": summary, "categories": [], "status": None, "percent_complete": None,
            "description": None, "parent_uid": None, **kw}
# end def


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    """One shallow clone of this repo (needs `file://`, a plain path ignores `--depth`), without a checkout."""
    seed = tmp_path_factory.mktemp("seed") / "seed"
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--no-checkout", f"file://{REPO_ROOT}", str(seed)], check=True)
    return seed
# end def


@pytest.fixture
def clone(seed, tmp_path):
    """A shallow clone of the seed for one test, with only the todo file checked out and no hooks, signing or identity trouble."""
    r = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--no-checkout", f"file://{seed}", str(r)], check=True)
    run = lambda *a: subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True, text=True).stdout
    for key, value in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false"), ("core.hooksPath", "/dev/null"), ("core.quotePath", "false")):
        run("config", key, value)
    # end for
    run("checkout", "HEAD", "--", TODO_FILE)
    assert run("rev-parse", "--is-shallow-repository").strip() == "true"
    return r, run
# end def


def cfg(r, **kw):
    return st.Config(projects=[st.Project(name="A", tags=["a"], path=str(r), todo_file=TODO_FILE, **kw)])
# end def


def sync(r, todos, **kw):
    st.sync(cfg(r), todos, None, False, **kw)
# end def


def count(run):
    return int(run("rev-list", "--count", "HEAD").strip())
# end def


def test_two_syncs_become_one_commit_with_both_bodies(clone):
    r, run = clone
    sync(r, [todo("1", "#a one")])
    n = count(run)
    assert run("log", "-1", "--format=%s").strip() == "[TODOs] synced todos for A."
    sync(r, [todo("1", "#a one", status="COMPLETED"), todo("2", "#a two")])
    assert count(run) == n
    assert run("log", "-1", "--format=%b").strip().split("\n") == [
        "- added: one — `todo:1`", "- ticked: one — `todo:1`", "- added: two — `todo:2`",
    ]
    assert run("show", "--name-only", "--format=", "HEAD").split() == [TODO_FILE]
# end def


def test_head_is_a_work_commit_so_a_new_commit_is_made(clone):
    r, run = clone
    n = count(run)
    assert run("log", "-1", "--format=%s").strip() != "[TODOs] synced todos for A."
    sync(r, [todo("1", "#a one")])
    assert count(run) == n + 1
# end def


def test_head_sync_commit_also_touched_another_file(clone):
    r, run = clone
    sync(r, [todo("1", "#a one")])
    (r / "other.txt").write_text("x")
    run("add", "other.txt")
    run("commit", "-q", "--amend", "--no-edit")
    n = count(run)
    sync(r, [todo("1", "#a one"), todo("2", "#a two")])
    assert count(run) == n + 1
    assert run("show", "--name-only", "--format=", "HEAD").split() == [TODO_FILE]
# end def


def test_pushed_sync_commit_is_never_rewritten(clone, tmp_path):
    r, run = clone
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "-C", str(remote), "config", "receive.shallowUpdate", "true"], check=True)  # the clone is shallow
    run("remote", "add", "pushed", str(remote))
    sync(r, [todo("1", "#a one")])
    run("push", "-q", "pushed", "HEAD:refs/heads/side")
    run("fetch", "-q", "pushed")
    pushed = run("rev-parse", "HEAD").strip()
    n = count(run)
    sync(r, [todo("1", "#a one"), todo("2", "#a two")])
    assert count(run) == n + 1
    assert run("rev-parse", "HEAD~1").strip() == pushed
# end def


def test_sync_commit_of_other_projects_is_not_amended(clone):
    r, run = clone
    sync(r, [todo("1", "#a one")])
    n = count(run)
    config = st.Config(projects=[
        st.Project(name="A", tags=["a"], path=str(r), todo_file=TODO_FILE),
        st.Project(name="B", tags=["b"], path=str(r), todo_file="ai/°base/b.md"),
    ])
    st.sync(config, [todo("1", "#a one two"), todo("2", "#b two")], None, False)
    assert count(run) == n + 1
    assert run("log", "-1", "--format=%s").strip() == "[TODOs] synced todos for A, B."
# end def


def test_different_prefix_is_not_amended(clone):
    r, run = clone
    sync(r, [todo("1", "#a one")])
    n = count(run)
    st.sync(cfg(r, commit_prefix="[x] "), [todo("1", "#a one"), todo("2", "#a two")], None, False)
    assert count(run) == n + 1
    assert run("log", "-1", "--format=%s").strip() == "[x] [TODOs] synced todos for A."
# end def


def test_purge_stays_its_own_commit_on_top_of_a_sync_commit(clone):
    r, run = clone
    sync(r, [todo("1", "#a one")])
    n = count(run)
    sync(r, [], purge_missing_=True)
    assert count(run) == n + 1
    assert run("log", "-1", "--format=%s").strip() == "[TODOs] purged missing todos for A."
    assert run("log", "-2", "--format=%s").split("\n")[1] == "[TODOs] synced todos for A."
# end def


def test_no_amend_makes_a_new_commit(clone):
    r, run = clone
    sync(r, [todo("1", "#a one")])
    n = count(run)
    sync(r, [todo("1", "#a one"), todo("2", "#a two")], amend=False)
    assert count(run) == n + 1
# end def


def test_a_sync_commit_that_is_the_shallow_root_is_not_amended(clone):
    """A root commit has no parent to diff against, so it looks like it touched every file: not provably clean, hence a new commit."""
    r, run = clone
    sync(r, [todo("1", "#a one")])
    (r / ".git" / "shallow").write_text(run("rev-parse", "HEAD").strip() + "\n")
    assert count(run) == 1
    sync(r, [todo("1", "#a one"), todo("2", "#a two")])
    assert count(run) == 2
# end def


@pytest.mark.parametrize("marker", ["MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge"])
def test_no_amend_while_a_merge_or_rebase_is_running(clone, marker):
    r, run = clone
    sync(r, [todo("1", "#a one")])
    subject = "[TODOs] synced todos for A."
    assert st.amendable(r, subject, [TODO_FILE])
    path = r / ".git" / marker
    path.mkdir() if marker == "rebase-merge" else path.write_text(run("rev-parse", "HEAD"))
    assert not st.amendable(r, subject, [TODO_FILE])
# end def
