"""Run: uv run --with pytest --with 'pydantic>=2.6' --with 'mcp>=2.3' --with python-dotenv pytest scripts/°base/ai/todos/tests/test_sync_todos.py"""
import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_path = Path(__file__).resolve().parent.parent / "sync_todos.py"
_spec = importlib.util.spec_from_file_location("sync_todos", _path)
st = importlib.util.module_from_spec(_spec)
sys.modules["sync_todos"] = st
_spec.loader.exec_module(st)

PROJECTS = [
    st.Project(name="Bot", tags=["SyncTodoBot", "SyncTodoList"], path="."),
    st.Project(name="Base", tags=["base"], path="."),
]


def todo(uid, summary, **kw):
    return {"uid": uid, "summary": summary, "categories": [], "status": None, "percent_complete": None,
            "description": None, "parent_uid": None, **kw}
# end def


def test_assign_by_prefix_category_and_parent():
    todos = [
        todo("a", "#synctodobot fix"),
        todo("b", "other", categories=["Category: base"]),
        todo("c", "child", parent_uid="a"),
        todo("d", "nobody"),
        todo("e", "x", categories=["#SyncTodoList"]),
    ]
    out = st.assign(todos, PROJECTS)
    assert [t["uid"] for t in out["Bot"]] == ["a", "c", "e"]
    assert [t["uid"] for t in out["Base"]] == ["b"]
# end def


@pytest.mark.parametrize("status,pct,box,state", [
    ("COMPLETED", None, "x", "_(done)_"),
    ("CANCELLED", None, "-", "_(cancelled)_"),
    ("IN-PROCESS", 40, "…", "_(in process, 40%)_"),
    ("NEEDS-ACTION", 0, "!", "_(needs action)_"),
    (None, None, " ", ""),
])
def test_checkbox_and_state(status, pct, box, state):
    assert st.checkbox_and_state(todo("a", "t", status=status, percent_complete=pct)) == (box, state)
# end def


@pytest.mark.parametrize("status,is_open", [
    ("COMPLETED", False), ("CANCELLED", False), ("DELEGATED", False),
    ("NEEDS-ACTION", True), ("IN-PROCESS", True), (None, True),
])
def test_count_open_skips_done_cancelled_and_delegated(status, is_open):
    assert st.count_open([todo("a", "t", status=status)]) == int(is_open)
# end def


def test_up_to_date_line_shows_the_open_count(tmp_path, capsys):
    r, _ = _repo(tmp_path, "a")
    cfg = st.Config(projects=[st.Project(name="A", tags=["a"], path=str(r))])
    todos = [todo("1", "#a one"), todo("2", "#a two", status="IN-PROCESS"), todo("3", "#a three", status="DELEGATED")]
    st.sync(cfg, todos, None, False, use_git=False)
    capsys.readouterr()
    st.sync(cfg, todos, None, False, use_git=False)
    assert "[A] up to date (3 todos, 2 open)" in capsys.readouterr().out
# end def


@pytest.mark.parametrize("priority,text", [
    (None, ""), (0, ""), (10, ""), ("5", ""),
    (1, "prio 1₍₉₎ highest"), (2, "prio 2₍₉₎ high"), (4, "prio 4₍₉₎ high"), (5, "prio 5₍₉₎ medium"),
    (6, "prio 6₍₉₎ low"), (8, "prio 8₍₉₎ low"), (9, "prio 9₍₉₎ lowest"),
])
def test_priority_text(priority, text):
    assert st.priority_text(todo("a", "t", priority=priority)) == text
# end def


@pytest.mark.parametrize("kw,state", [
    ({"priority": 1}, "_(prio 1₍₉₎ highest)_"),
    ({"priority": 9, "status": "COMPLETED"}, "_(done; prio 9₍₉₎ lowest)_"),
    ({"priority": 1, "status": "IN-PROCESS", "percent_complete": 40}, "_(in process, 40%; prio 1₍₉₎ highest)_"),
    ({"priority": 0, "status": "COMPLETED"}, "_(done)_"),
])
def test_priority_joins_the_status_bracket(kw, state):
    assert st.checkbox_and_state(todo("a", "t", **kw))[1] == state
# end def


def test_render_shows_the_priority_after_the_uid():
    lines = st.render(todo("a", "do it", priority=9), PROJECTS[0])
    assert lines == ["- [ ] do it — `todo:a` _(prio 9₍₉₎ lowest)_"]
# end def


def test_merge_refreshes_priority_and_keeps_notes():
    text = "# Todos\n\n- [ ] it — `todo:a` _(prio 9₍₉₎ lowest)_ (hand note)\n"
    new, _ = st.merge(text, [todo("a", "it", priority=1)], PROJECTS[0])
    assert "- [ ] it — `todo:a` (hand note) _(prio 1₍₉₎ highest)_" in new
    again, report = st.merge(new, [todo("a", "it", priority=1)], PROJECTS[0])
    assert again == new and report == []
    gone, _ = st.merge(new, [todo("a", "it", status="COMPLETED")], PROJECTS[0])
    assert "- [x] it — `todo:a` (hand note) _(done)_" in gone
# end def


def test_describe_changes_reports_a_priority_change():
    old = "- [ ] it — `todo:a` _(prio 9₍₉₎ lowest)_\n"
    new = "- [ ] it — `todo:a` _(prio 1₍₉₎ highest)_\n"
    assert st.describe_changes(old, new) == ["priority: it (prio 9₍₉₎ lowest -> prio 1₍₉₎ highest)"]
    done = "- [x] it — `todo:a` _(done; prio 1₍₉₎ highest)_\n"
    assert st.describe_changes(new, done) == ["ticked: it"]
# end def


def test_render_strips_tag_and_adds_description():
    lines = st.render(todo("a", "#SyncTodoBot do it", description="l1\nl2"), PROJECTS[0], 2)
    assert lines == ["  - [ ] do it — `todo:a`", "    > l1", "    > l2"]
# end def


def test_merge_keeps_handwritten_and_is_idempotent():
    text = "# Todos\n\nNotes here.\n- [ ] old — `todo:a` _(missing)_ (hand note)\n  > keep me\n"
    todos = [todo("a", "old", status="COMPLETED"), todo("b", "new", parent_uid="a"), todo("c", "root")]
    new, report = st.merge(text, todos, PROJECTS[0])
    assert "Notes here." in new and "  > keep me" in new
    assert "- [x] old — `todo:a` (hand note) _(done)_" in new
    assert "  - [ ] new — `todo:b`" in new  # child under its parent
    assert st.SECTION in new and "- [ ] root — `todo:c`" in new
    again, report2 = st.merge(new, todos, PROJECTS[0])
    assert again == new and report2 == []
# end def


def test_purge_missing_only_when_gone_from_caldav():
    text = "- [ ] gone — `todo:z`\n  > d\n- [ ] moved — `todo:y`\n"
    new, report = st.purge_missing(text, {"y"})
    assert "todo:z" not in new and "todo:y" in new and report == ["purged missing z"]
# end def


def test_purge_complete_keeps_parent_with_open_child():
    text = ("- [x] p — `todo:p`\n  > d\n  - [x] c1 — `todo:c1`\n  - [ ] c2 — `todo:c2`\n"
            "- [x] q — `todo:q`\n  - [x] q1 — `todo:q1`\n- [ ] r — `todo:r`\n")
    new, report = st.purge_complete(text, {"p", "c1", "q", "q1"})
    assert "todo:q" not in new and "todo:c1" not in new and "todo:p`" in new and "todo:c2" in new and "todo:r" in new
    assert sorted(report) == ["purged completed c1", "purged completed q", "purged completed q1"]
# end def


def test_completed_not_in_file_is_ignored_unless_included():
    todos = [todo("a", "done", status="COMPLETED"), todo("b", "open")]
    new, _ = st.merge("# Todos\n", todos, PROJECTS[0])
    assert "todo:a" not in new and "todo:b" in new
    new, _ = st.merge("# Todos\n", todos, PROJECTS[0], include_completed=True)
    assert "todo:a" in new
    # already in the file: still refreshed
    new, _ = st.merge("- [ ] done — `todo:a`\n", todos, PROJECTS[0])
    assert "- [x] done — `todo:a` _(done)_" in new
# end def


def test_local_tick_is_reported_not_pushed():
    new, report = st.merge("- [x] a — `todo:a`\n", [todo("a", "a", status="NEEDS-ACTION")], PROJECTS[0])
    assert report == ["local tick not on CalDAV (not pushed): a"]
    assert new.startswith("- [!] a")
# end def


def test_config_rejects_duplicates_and_unknown_keys():
    p = {"name": "A", "tags": ["x"], "path": "."}
    with pytest.raises(ValueError):
        st.Config.model_validate({"projects": [p, {**p, "name": "B", "tags": ["X"]}]})
    # end with
    with pytest.raises(ValueError):
        st.Config.model_validate({"projects": [p], "bogus": 1})
    # end with
# end def


def test_checked_in_schema_and_config_are_current():
    assert st.SCHEMA_PATH.read_text() == st.schema_text()
    assert st.LOCAL_SCHEMA_PATH.read_text() == st.local_schema_text()
    st.load_config(st.DEFAULT_CONFIG, st.LOCAL_CONFIG.with_name("does-not-exist.json"), write_local=False)
# end def


def test_parse_result_per_item_blocks():
    blocks = [SimpleNamespace(type="text", text=json.dumps(todo(u, u))) for u in "ab"]
    res = SimpleNamespace(structuredContent=None, content=blocks)
    assert [t["uid"] for t in st.parse_result(res)] == ["a", "b"]
    res = SimpleNamespace(structuredContent={"result": [todo("c", "c")]}, content=[])
    assert st.parse_result(res)[0]["uid"] == "c"
# end def


def test_collect_pages():
    every = [todo(f"u{i:03}", f"t{i}") for i in range(7)]
    calls = []

    async def paged(offset, limit):
        calls.append((offset, limit))
        return every[offset:offset + limit]

    assert [t["uid"] for t in asyncio.run(st.collect_pages(paged, 3))] == [t["uid"] for t in every]
    assert calls == [(0, 3), (3, 3), (6, 3)]
    calls.clear()
    assert len(asyncio.run(st.collect_pages(paged, 7))) == 7  # an exact multiple needs one empty page to know it is over
    assert calls == [(0, 7), (7, 7)]

    async def ignores_paging(offset, limit):  # an older server sends everything every time
        return every

    assert len(asyncio.run(st.collect_pages(ignores_paging, 7))) == 7
# end def


def _repo(tmp_path, name):
    import subprocess
    r = tmp_path / name
    (r / "ai").mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True, text=True).stdout
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    run("config", "commit.gpgsign", "false")
    (r / "ai" / "todos.md").write_text("# Todos\n")
    (r / "other.txt").write_text("x")
    run("add", ".")
    run("commit", "-q", "-m", "init")
    return r, run
# end def


def test_commit_per_repo_only_written_files(tmp_path):
    r, run = _repo(tmp_path, "r")
    (r / "other.txt").write_text("staged but unrelated")
    run("add", "other.txt")
    cfg = st.Config(projects=[
        st.Project(name="A", tags=["a"], path=str(r)),
        st.Project(name="B", tags=["b"], path=str(r), todo_file="ai/b.md"),
    ])
    st.sync(cfg, [todo("1", "#a one"), todo("2", "#b two")], None, False)
    assert run("log", "-1", "--format=%s").strip() == "[TODOs] synced todos for A, B."
    assert run("show", "--name-only", "--format=").split() == ["ai/b.md", "ai/todos.md"]
    assert run("diff", "--cached", "--name-only").split() == ["other.txt"]
    n = run("rev-list", "--count", "HEAD").strip()
    st.sync(cfg, [todo("1", "#a one"), todo("2", "#b two")], None, False)  # idempotent: no new commit
    assert run("rev-list", "--count", "HEAD").strip() == n
# end def


def test_no_git_and_dry_run_do_not_commit(tmp_path):
    r, run = _repo(tmp_path, "r")
    cfg = st.Config(projects=[st.Project(name="A", tags=["a"], path=str(r))])
    st.sync(cfg, [todo("1", "#a one")], None, False, use_git=False)
    assert "todo:1" in (r / "ai" / "todos.md").read_text()
    assert run("log", "-1", "--format=%s").strip() == "init"
    (r / "ai" / "todos.md").write_text("# Todos\n")
    st.sync(cfg, [todo("1", "#a one")], None, True)
    assert run("log", "-1", "--format=%s").strip() == "init"
# end def


def test_prefix_per_project_and_subfolder_commits_in_git_root(tmp_path):
    r, run = _repo(tmp_path, "mono")
    (r / "sub" / "ai").mkdir(parents=True)
    (r / "sub" / "ai" / "todos.md").write_text("# Todos\n")
    run("add", ".")
    run("commit", "-q", "-m", "sub")
    cfg = st.Config(commit_prefix="[root] ", projects=[
        st.Project(name="Root", tags=["r"], path=str(r)),
        st.Project(name="Sub", tags=["s"], path=str(r / "sub"), commit_prefix="[sub] "),
    ])
    st.sync(cfg, [todo("1", "#r one"), todo("2", "#s two")], None, False)
    subjects = run("log", "-2", "--format=%s").split("\n")[:2]
    assert sorted(subjects) == ["[root] [TODOs] synced todos for Root.", "[sub] [TODOs] synced todos for Sub."]
    assert run("show", "--name-only", "--format=", "HEAD").split() in (["ai/todos.md"], ["sub/ai/todos.md"])
# end def


def test_purges_are_separate_commits(tmp_path):
    r, run = _repo(tmp_path, "r")
    (r / "ai" / "todos.md").write_text("# Todos\n- [ ] gone — `todo:z`\n- [ ] was open — `todo:a`\n- [ ] keep — `todo:b`\n")
    run("add", ".")
    run("commit", "-q", "-m", "seed")
    cfg = st.Config(commit_prefix="[x] ", projects=[st.Project(name="A", tags=["a"], path=str(r))])
    todos = [todo("a", "#a was open", status="COMPLETED"), todo("b", "#a keep")]
    st.sync(cfg, todos, None, False, purge_missing_=True, purge_complete_=True)
    assert run("log", "-4", "--format=%s").split("\n")[:3] == [
        "[x] [TODOs] purged completed todos for A.",
        "[x] [TODOs] purged missing todos for A.",
        "[x] [TODOs] synced todos for A.",
    ]
    assert (r / "ai" / "todos.md").read_text() == "# Todos\n- [ ] keep — `todo:b`\n"
# end def


def test_verbose_logs_comparisons_and_commit_logs_hash(tmp_path, capsys, monkeypatch):
    r, run = _repo(tmp_path, "r")
    cfg = st.Config(projects=[st.Project(name="A", tags=["a"], path=str(r))])
    todos = [todo("12345678-x", "#a one"), todo("abcdef00-x", "#a two", status="COMPLETED"), todo("ffffffff-x", "nobody")]
    st.sync(cfg, todos, None, False)
    quiet = capsys.readouterr().out
    head = run("rev-parse", "--short=9", "HEAD").strip()
    assert f"committed {head} in" in quiet and "  . " not in quiet
    monkeypatch.setattr(st, "VERBOSE", True)
    st.sync(cfg, todos, None, False)
    loud = capsys.readouterr().out
    assert "assign 12345678" in loud and "-> nobody" in loud and "12345678: unchanged" in loud
    assert "abcdef00: completed and not in the file, ignored" in loud
    assert "nothing staged" not in loud  # nothing was written, so no commit stage ran
# end def


def test_resolve_roots_uses_the_git_root_not_a_folder_name(tmp_path):
    repo = tmp_path / "checkout-with-any-name"
    script = repo / "scripts" / "°base" / "ai" / "todos" / "sync_todos.py"
    script.parent.mkdir(parents=True)
    script.write_text("")
    import subprocess
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    root, config, schema, local, local_schema = st.resolve_roots(str(script))
    assert root.resolve() == repo.resolve()
    assert config.parent == root / "ai" / "settings"
    assert config.name == "sync_todos.json" and local.name == "sync_todos.local.json"
    assert schema.name == "sync_todos.schema.json" and local_schema.name == "sync_todos-local.schema.json"
# end def


def test_loaded_from_the_repo_points_at_ai_settings():
    assert st.DEFAULT_CONFIG == st.REPO_ROOT / "ai" / "settings" / "sync_todos.json"
    assert st.LOCAL_CONFIG == st.REPO_ROOT / "ai" / "settings" / "sync_todos.local.json"
# end def


def _tracked(tmp_path, **project):
    tracked = tmp_path / "sync_todos.json"
    tracked.write_text(json.dumps({"commit_prefix": "[g] ", "projects": [{"name": "A", "tags": ["a"], **project}, {"name": "B", "tags": ["b"]}]}))
    return tracked
# end def


def test_load_config_generates_null_entries_and_keeps_existing_values(tmp_path):
    tracked, local = _tracked(tmp_path), tmp_path / "sync_todos.local.json"
    local.write_text(json.dumps({"projects": {"A": {"path": "~/x", "commit_prefix": "[a] "}}}))
    cfg = st.load_config(tracked, local)
    a, b = cfg.projects
    assert (a.path, a.commit_prefix) == ("~/x", "[a] ")
    assert (b.path, b.commit_prefix) == (None, None)
    written = json.loads(local.read_text())
    assert written["projects"] == {"A": {"path": "~/x", "commit_prefix": "[a] "}, "B": {"path": None, "commit_prefix": None}}
# end def


def test_load_config_local_prefix_beats_tracked_per_project_prefix(tmp_path):
    tracked, local = _tracked(tmp_path, commit_prefix="[tracked] "), tmp_path / "local.json"
    local.write_text(json.dumps({"projects": {"A": {"path": ".", "commit_prefix": "[local] "}, "B": {"path": "."}}}))
    a, _ = st.load_config(tracked, local).projects
    assert a.commit_prefix == "[local] "
    local.write_text(json.dumps({"projects": {"A": {"path": "."}, "B": {"path": "."}}}))
    a, _ = st.load_config(tracked, local).projects
    assert a.commit_prefix == "[tracked] "
# end def


def test_load_config_refuses_a_path_in_the_tracked_file(tmp_path):
    with pytest.raises(ValueError, match="path"):
        st.load_config(_tracked(tmp_path, path="/Users/me/a"), tmp_path / "local.json", write_local=False)
# end def


def test_project_without_path_is_skipped_but_still_claims_its_tags(tmp_path, capsys):
    r, _ = _repo(tmp_path, "a")
    cfg = st.Config(projects=[st.Project(name="A", tags=["a"], path=str(r)), st.Project(name="B", tags=["b"])])
    st.sync(cfg, [todo("1", "#b one"), todo("2", "#a two")], None, False, use_git=False)
    assert "[B] skipped, no path" in capsys.readouterr().err
    assert "two" in (r / "ai" / "todos.md").read_text()
    assert not (tmp_path / "ai").exists()
# end def


TEMPLATE = st.TEMPLATE_PATH.read_text(encoding="utf-8")
OLD_BLOCK = "# Todos\n\n## Synced from CalDAV\n\n- [ ] kept — `todo:a`\n  > note\n"


def test_template_exists_next_to_the_real_script():
    assert st.TEMPLATE_PATH.name == "todos.template.md"
    assert st.TEMPLATE_PATH.parent == Path(st.__file__).resolve().parent
    assert TEMPLATE.splitlines()[-2] == st.SECTION
# end def


def test_new_todo_file_text_fills_the_placeholders():
    project = st.Project(name="Bot", tags=["x"], path="sync_todo")
    text = st.new_todo_file_text(project, 7)
    assert "{{" not in text
    assert "calendar_id=7" in text and "--project Bot" in text
    script = Path(st.__file__).resolve()
    assert f"`{os.path.relpath(script, project.root())} --project Bot" in text
    root_project = st.Project(name="Root", tags=["y"], path=".")
    assert f"`{os.path.relpath(script, root_project.root())} --project Root" in st.new_todo_file_text(root_project, 7)
# end def


def test_upgrade_whole_file_keeps_the_synced_lines():
    new = st.upgrade_old_template(OLD_BLOCK, "NEW\n\n" + st.SECTION + "\n\n")
    assert new == f"NEW\n\n{st.SECTION}\n\n- [ ] kept — `todo:a`\n  > note\n"
    assert st.upgrade_old_template(new, "NEW\n\n" + st.SECTION + "\n\n") == new  # not "For Agents" yet, but no old header either
# end def


def test_upgrade_bare_header_only():
    assert st.upgrade_old_template("# Todos\n\n", TEMPLATE) == TEMPLATE.rstrip("\n") + "\n\n"
# end def


def test_upgrade_keeps_manual_stuff_on_top():
    text = "Some notes\n\n- a manual item\n\n\n" + OLD_BLOCK
    new = st.upgrade_old_template(text, TEMPLATE)
    assert new.startswith("Some notes\n\n- a manual item\n\n# Todos\n\n## For Agents")
    assert new.endswith(f"{st.SECTION}\n\n- [ ] kept — `todo:a`\n  > note\n")
    assert st.LEGACY_SECTION not in new
# end def


def test_upgrade_leaves_new_and_foreign_files_alone():
    assert st.upgrade_old_template(TEMPLATE, TEMPLATE) == TEMPLATE
    assert st.upgrade_old_template("# Notes\n\n- x\n", TEMPLATE) == "# Notes\n\n- x\n"
    handwritten = "# Todos\n\nMy own intro.\n\n- [ ] thing\n"
    assert st.upgrade_old_template(handwritten, TEMPLATE) == handwritten
# end def


def test_upgrade_is_idempotent_and_merge_lands_under_the_section():
    project = st.Project(name="Bot", tags=["SyncTodoBot"], path=".")
    once = st.upgrade_old_template(OLD_BLOCK, st.new_todo_file_text(project, 7))
    assert st.upgrade_old_template(once, st.new_todo_file_text(project, 7)) == once
    merged, _ = st.merge(once, [todo("n", "#SyncTodoBot new one")], project)
    assert merged.index(st.SECTION) < merged.index("new one")
    assert merged.count(st.SECTION) == 1
# end def


def test_merge_accepts_the_legacy_section_heading():
    project = st.Project(name="Bot", tags=["SyncTodoBot"], path=".")
    merged, _ = st.merge(OLD_BLOCK, [todo("n", "#SyncTodoBot new one")], project)
    assert st.SECTION not in merged and merged.count(st.LEGACY_SECTION) == 1
# end def


# --- description refresh and --project selection

def test_changed_description_replaces_the_old_block_and_reports_dropped_lines():
    text = "## Todos synced from CalDAV\n\n- [ ] Link — `todo:a`\n  > GitHub - old text\n- [ ] next — `todo:b`\n"
    todos = [todo("a", "Link", description="- https://example.com\nGitHub - old text, now longer"), todo("b", "next")]
    new, report = st.merge(text, todos, PROJECTS[0])
    assert new == (
        "## Todos synced from CalDAV\n\n- [ ] Link — `todo:a`\n  > - https://example.com\n  > GitHub - old text, now longer\n"
        "- [ ] next — `todo:b`\n"
    )
    assert any("description changed" in line and "a" in line for line in report)
    assert any("dropped" in line and "GitHub - old text" in line for line in report)
    assert st.merge(new, todos, PROJECTS[0])[0] == new  # second run: nothing left to do
# end def


def test_notes_above_an_unchanged_description_stay():
    text = "- [ ] t — `todo:a`\n  > Done: my own note\n  > from CalDAV\n  > line two\n"
    new, report = st.merge(text, [todo("a", "t", description="from CalDAV\nline two")], PROJECTS[0])
    assert new == text
    assert report == []
# end def


def test_notes_below_an_unchanged_description_stay():
    text = "- [ ] t — `todo:a`\n  > from CalDAV\n  > Done: my own note\n- [ ] next — `todo:b`\n"
    todos = [todo("a", "t", description="from CalDAV"), todo("b", "next")]
    new, report = st.merge(text, todos, PROJECTS[0])
    assert new == text
    assert not any("description" in line for line in report)
# end def


def test_changed_description_with_a_note_replaces_it_and_says_so():
    text = "- [ ] t — `todo:a`\n  > old\n  > Done: my own note\n"
    new, report = st.merge(text, [todo("a", "t", description="new")], PROJECTS[0])
    assert new == "- [ ] t — `todo:a`\n  > new\n"
    assert any("dropped" in line and "Done: my own note" in line for line in report)
# end def


def test_a_description_does_not_touch_the_children_below():
    text = "- [ ] p — `todo:a`\n  > old\n  - [ ] child — `todo:b`\n    > child text\n"
    todos = [todo("a", "p", description="new"), todo("b", "child", parent_uid="a", description="child text")]
    new, _ = st.merge(text, todos, PROJECTS[0])
    assert new == "- [ ] p — `todo:a`\n  > new\n  - [ ] child — `todo:b`\n    > child text\n"
# end def


def test_project_is_selected_by_name_or_tag_ignoring_case():
    config = SimpleNamespace(projects=PROJECTS)
    assert [p.name for p in st.select_projects(config, None)] == ["Bot", "Base"]
    assert [p.name for p in st.select_projects(config, "bot")] == ["Bot"]
    assert [p.name for p in st.select_projects(config, "SYNCTODOLIST")] == ["Bot"]
# end def


def test_an_unknown_project_is_an_error_naming_the_known_ones():
    with pytest.raises(ValueError, match="no project 'nope'.*Bot.*Base"):
        st.select_projects(SimpleNamespace(projects=PROJECTS), "nope")
    # end with
# end def


@pytest.mark.parametrize("flag", ["--include-completed", "--include-complete"])
def test_include_completed_has_two_spellings(flag):
    assert st.build_parser().parse_args([flag]).include_completed is True
    assert st.build_parser().parse_args([]).include_completed is False
# end def


@pytest.mark.parametrize("flag", ["--purge-complete", "--purge-completed"])
def test_purge_complete_has_two_spellings(flag):
    assert st.build_parser().parse_args([flag]).purge_complete is True
    assert st.build_parser().parse_args([]).purge_complete is False
# end def


def test_an_unknown_flag_is_still_an_error():
    with pytest.raises(SystemExit):
        st.build_parser().parse_args(["--include-finished"])
    # end with
# end def


# --- --reset-todo-file

MESSY = """# My notes

Some prose that is not a todo.

1. a numbered list
2. is not one either

## Old section
- [ ] open one — `todo:a`
  > its description
  > second row
* [x] done star
  continuation line that is not a quote row
• [!] urgent bullet
    - [-] nested cancelled
      > nested quote
```
- [ ] inside a code fence still looks like a todo
```
- not a checkbox
> loose quote with no todo above
"""


def test_reset_text_keeps_only_todo_like_lines_below_the_template():
    template = "# Todos\n\n## Todos synced from CalDAV\n\n"
    new, report = st.reset_text(MESSY, template)
    assert new == (
        template
        + "- [ ] open one — `todo:a`\n  > its description\n  > second row\n"
        + "* [x] done star\n"
        + "• [!] urgent bullet\n"
        + "    - [-] nested cancelled\n      > nested quote\n"
        + "- [ ] inside a code fence still looks like a todo\n"
    )
    assert any("dropped" in line and "Some prose" in line for line in report)
    assert any("dropped" in line and "continuation line" in line for line in report)
    assert not any("open one" in line for line in report)
# end def


def test_reset_text_is_idempotent_and_handles_a_file_without_todos():
    template = "# Todos\n\n## Todos synced from CalDAV\n\n"
    once, _ = st.reset_text(MESSY, template)
    assert st.reset_text(once, template)[0] == once
    assert st.reset_text("just prose\n", template)[0] == template
# end def


def test_reset_flag_is_parsed():
    assert st.build_parser().parse_args(["--reset-todo-file"]).reset_todo_file is True
    assert st.build_parser().parse_args([]).reset_todo_file is False
# end def


def _reset_cfg(r):
    return st.Config(commit_prefix="[x] ", projects=[st.Project(name="A", tags=["a"], path=str(r))])
# end def


def test_reset_rebuilds_the_file_then_syncs_in_two_commits(tmp_path):
    r, run = _repo(tmp_path, "r")
    (r / "ai" / "todos.md").write_text("# Notes\nprose\n- [ ] old title — `todo:a`\n  > kept row\n- [ ] hand written\n")
    run("add", ".")
    run("commit", "-q", "-m", "seed")
    cfg = _reset_cfg(r)
    st.sync(cfg, [todo("a", "#a new title", description="kept row"), todo("b", "#a brand new")], "A", False, reset_todo_file=True)
    assert run("log", "-3", "--format=%s").split("\n")[:2] == ["[x] [TODOs] synced todos for A.", "[x] [TODOs] reset todo file for A."]
    text = (r / "ai" / "todos.md").read_text()
    assert text.startswith(st.new_todo_file_text(cfg.projects[0], cfg.calendar_id))
    assert "prose" not in text and "# Notes" not in text
    assert "- [ ] new title — `todo:a`\n  > kept row\n" in text
    assert "- [ ] hand written\n" in text and "brand new" in text
# end def


@pytest.mark.parametrize("dirty", ["modified", "untracked"])
def test_reset_refuses_a_file_with_uncommitted_changes(tmp_path, dirty):
    r, run = _repo(tmp_path, "r")
    if dirty == "modified":
        (r / "ai" / "todos.md").write_text("# Todos\n- [ ] unsaved\n")
    else:
        (r / "ai" / "b.md").write_text("- [ ] new file\n")
    # end if
    project = st.Project(name="A", tags=["a"], path=str(r), todo_file="ai/b.md" if dirty == "untracked" else "ai/todos.md")
    with pytest.raises(ValueError, match="uncommitted"):
        st.sync(st.Config(projects=[project]), [], "A", False, reset_todo_file=True)
    # end with
    assert "unsaved" in (r / "ai" / "todos.md").read_text() or dirty == "untracked"
# end def


def test_reset_refuses_outside_a_git_repo(tmp_path):
    (tmp_path / "ai").mkdir()
    (tmp_path / "ai" / "todos.md").write_text("- [ ] x\n")
    with pytest.raises(ValueError, match="git"):
        st.sync(st.Config(projects=[st.Project(name="A", tags=["a"], path=str(tmp_path))]), [], "A", False, reset_todo_file=True)
    # end with
# end def


def test_reset_needs_a_project_and_git():
    config = st.Config(projects=PROJECTS)
    with pytest.raises(ValueError, match="--project"):
        st.sync(config, [], None, False, reset_todo_file=True)
    # end with
    with pytest.raises(ValueError, match="git"):
        st.sync(config, [], "Bot", False, use_git=False, reset_todo_file=True)
    # end with
# end def


def test_reset_dry_run_checks_nothing_and_writes_nothing(tmp_path):
    r, run = _repo(tmp_path, "r")
    (r / "ai" / "todos.md").write_text("# Todos\nprose\n- [ ] dirty\n")
    before = (r / "ai" / "todos.md").read_text()
    st.sync(_reset_cfg(r), [], "A", True, reset_todo_file=True)
    assert (r / "ai" / "todos.md").read_text() == before
# end def


def test_describe_changes_names_what_happened_to_the_todos():
    old = (
        "# Todos\n\n## Todos synced from CalDAV\n\n"
        "- [ ] Fix tagging — `todo:a`\n  > old note\n"
        "  - [ ] child one — `todo:a1`\n"
        "- [x] Done one — `todo:b` _(done)_\n"
        "- [ ] Old title — `todo:c`\n"
        "- [ ] Going — `todo:d`\n"
        "- [ ] Working — `todo:e`\n"
        "- [ ] Unchanged — `todo:f`\n"
        "- [ ] Dropped — `todo:h`\n"
        "- [-] Shelved — `todo:i` _(cancelled)_\n"
        "- [-] Old shelf — `todo:j` _(cancelled)_\n"
    )
    new = (
        "# Todos\n\n## Todos synced from CalDAV\n\n"
        "- [ ] Fix tagging — `todo:a`\n  > new note\n"
        "  - [x] child one — `todo:a1` _(done)_\n"
        "  - [ ] child two — `todo:a2`\n"
        "- [ ] Done one — `todo:b`\n"
        "- [ ] New title — `todo:c`\n"
        "- [ ] Working — `todo:e` _(in process, 40%)_\n"
        "- [ ] Unchanged — `todo:f`\n"
        "- [ ] Brand new — `todo:g`\n"
        "- [-] Dropped — `todo:h` _(cancelled)_\n"
        "- [ ] Shelved — `todo:i`\n"
        "- [-] New shelf — `todo:j` _(cancelled)_\n"
        "- [-] Born cancelled — `todo:k` _(cancelled)_\n"
    )
    assert st.describe_changes(old, new) == [
        "description changed: Fix tagging",
        "ticked: Fix tagging / child one",
        "added: Fix tagging / child two",
        "unticked: Done one",
        "renamed: Old title -> New title",
        "state: Working (none -> in process, 40%)",
        "added: Brand new",
        "cancelled: ~~Dropped~~",
        "reopened: Shelved",
        "renamed: ~~Old shelf~~ -> ~~New shelf~~",
        "added: ~~Born cancelled~~ (cancelled)",
        "removed: Going",
    ]
    assert st.describe_changes(old, old) == []
    assert st.describe_changes("# Todos\n", "# Todos\nsome note\n") == []  # (hand-written lines are not todos)
# end def


def test_the_commit_body_lists_what_changed_and_the_subject_stays(tmp_path):
    r, run = _repo(tmp_path, "r")
    cfg = st.Config(projects=[st.Project(name="A", tags=["a"], path=str(r))])
    st.sync(cfg, [todo("1", "#a one"), todo("2", "#a two", parent_uid="1")], None, False)
    assert run("log", "-1", "--format=%s").strip() == "[TODOs] synced todos for A."
    assert run("log", "-1", "--format=%b").strip().split("\n") == ["- added: one", "- added: one / two"]
    st.sync(cfg, [todo("1", "#a one", status="COMPLETED"), todo("2", "#a two renamed", parent_uid="1")], None, False, amend=False)
    assert run("log", "-1", "--format=%b").strip().split("\n") == ["- ticked: one", "- renamed: two -> two renamed"]
# end def


def test_purge_commits_list_the_removed_todos_and_several_projects_are_prefixed(tmp_path):
    r, run = _repo(tmp_path, "r")
    (r / "ai" / "todos.md").write_text("# Todos\n- [ ] gone — `todo:z`\n- [ ] was open — `todo:a`\n")
    run("add", ".")
    run("commit", "-q", "-m", "seed")
    cfg = st.Config(projects=[st.Project(name="A", tags=["a"], path=str(r)), st.Project(name="B", tags=["b"], path=str(r), todo_file="ai/b.md")])
    st.sync(cfg, [todo("a", "#a was open", status="COMPLETED"), todo("n", "#b newer")], None, False, purge_missing_=True, purge_complete_=True)
    subjects = run("log", "-4", "--format=%s").split("\n")[:3]
    assert subjects == ["[TODOs] purged completed todos for A.", "[TODOs] purged missing todos for A.", "[TODOs] synced todos for A, B."]
    assert run("log", "-1", "--format=%b").strip() == "- removed: was open"
    assert run("log", "-2", "--format=%b").split("\n\n")[1].strip() == "- removed: gone"
    assert run("log", "-3", "--format=%b").split("\n\n")[2].strip().split("\n") == [
        "- [A] ticked: was open", "- [B] added: newer",
    ]
# end def


def test_a_long_list_is_cut_after_thirty_lines(tmp_path):
    r, run = _repo(tmp_path, "r")
    cfg = st.Config(projects=[st.Project(name="A", tags=["a"], path=str(r))])
    st.sync(cfg, [todo(str(n), f"#a todo {n}") for n in range(34)], None, False)
    body = run("log", "-1", "--format=%b").strip().split("\n")
    assert len(body) == 31 and body[0] == "- added: todo 0" and body[-1] == "- ... and 4 more"
# end def


def test_missing_ai_folder_is_created_in_a_git_repo(tmp_path):
    r, run = _repo(tmp_path, "r")
    (r / "ai" / "todos.md").unlink()
    run("rm", "-q", "-r", "--cached", "ai")
    (r / "ai").rmdir()
    cfg = st.Config(projects=[st.Project(name="A", tags=["a"], path=str(r))])
    st.sync(cfg, [todo("1", "#a one")], None, True)  # dry run creates nothing
    assert not (r / "ai").exists()
    st.sync(cfg, [todo("1", "#a one")], None, False)
    assert "todo:1" in (r / "ai" / "todos.md").read_text()
    assert run("log", "-1", "--format=%s").strip() == "[TODOs] synced todos for A."
# end def


def test_missing_ai_folder_is_skipped_outside_git_or_without_root(tmp_path, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    cfg = st.Config(projects=[
        st.Project(name="Plain", tags=["a"], path=str(plain)),
        st.Project(name="Gone", tags=["b"], path=str(tmp_path / "gone")),
    ])
    st.sync(cfg, [todo("1", "#a one"), todo("2", "#b two")], None, False)
    assert not (plain / "ai").exists()
    assert not (tmp_path / "gone").exists()
    err = capsys.readouterr().err
    assert "[Plain] skipped" in err and "not in a git repo" in err
    assert "[Gone] skipped" in err
# end def


def _linked_repo(tmp_path):
    r, run = _repo(tmp_path, "r")
    (r / "scripts").mkdir()
    (r / "scripts" / "tool.py").write_text("x = 1\n")
    run("add", ".")
    run("commit", "-q", "-m", "tool")
    cfg = st.Config(projects=[st.Project(name="A", tags=["a"], path=str(r))])
    return r, run, cfg
# end def


def test_existing_files_become_links_relative_to_the_todo_file(tmp_path):
    r, run, cfg = _linked_repo(tmp_path)
    todos = [todo("1", "#a run `scripts/tool.py` or `scripts/gone.py` or `no_slash`", description="see @scripts/tool.py#L3 now")]
    st.sync(cfg, todos, None, False, use_git=False)
    text = (r / "ai" / "todos.md").read_text()
    assert "run [`scripts/tool.py`](../scripts/tool.py) or `scripts/gone.py` or `no_slash`" in text
    assert "> see [@`scripts/tool.py`](../scripts/tool.py)[#L3](../scripts/tool.py#L3) now" in text
# end def


def test_linked_files_do_not_make_the_next_sync_differ(tmp_path, capsys):
    r, run, cfg = _linked_repo(tmp_path)
    todos = [todo("1", "#a run `scripts/tool.py`", description="see `scripts/tool.py`")]
    st.sync(cfg, todos, None, False, use_git=False)
    first = (r / "ai" / "todos.md").read_text()
    capsys.readouterr()
    assert st.sync(cfg, todos, None, False, use_git=False) == 0
    assert (r / "ai" / "todos.md").read_text() == first
    assert "description changed" not in capsys.readouterr().out
# end def


def test_mention_in_a_fenced_description_is_listed_after_the_fence(tmp_path):
    r, run, cfg = _linked_repo(tmp_path)
    st.sync(cfg, [todo("1", "#a one", description="```\ncat @scripts/tool.py\n```")], None, False, use_git=False)
    text = (r / "ai" / "todos.md").read_text()
    assert "> cat @scripts/tool.py" in text
    assert "[@`scripts/tool.py`](../scripts/tool.py)" in text.split("> cat @scripts/tool.py\n", 1)[-1]
# end def


def test_add_files_commits_mentioned_files_only_with_the_flag(tmp_path):
    r, run, cfg = _linked_repo(tmp_path)
    (r / "scripts" / "tool.py").write_text("x = 2\n")
    todos = [todo("1", "#a run `scripts/tool.py`")]
    st.sync(cfg, todos, None, False)
    assert run("status", "--porcelain", "--", "scripts/tool.py").strip() == "M scripts/tool.py"
    st.sync(cfg, todos, None, False, add_files=True)
    assert run("status", "--porcelain", "--", "scripts/tool.py").strip() == ""
    assert run("log", "-1", "--format=%s", "--", "scripts/tool.py").strip().endswith("referenced file for task added.")
# end def


def test_add_files_dry_run_commits_nothing(tmp_path):
    r, run, cfg = _linked_repo(tmp_path)
    (r / "scripts" / "tool.py").write_text("x = 2\n")
    st.sync(cfg, [todo("1", "#a run `scripts/tool.py`")], None, True, add_files=True)
    assert run("status", "--porcelain", "--", "scripts/tool.py").strip() == "M scripts/tool.py"
# end def


def test_without_the_base_hooks_mentions_stay_plain(tmp_path, monkeypatch):
    r, run, cfg = _linked_repo(tmp_path)
    monkeypatch.setattr(st, "reffiles", lambda: None)
    st.sync(cfg, [todo("1", "#a run `scripts/tool.py`")], None, False, use_git=False)
    assert "run `scripts/tool.py` —" in (r / "ai" / "todos.md").read_text()
# end def


def _layers(tmp_path, repo=None, local=None, **project):
    tracked = _tracked(tmp_path, **project)
    repo_file, local_file = tmp_path / "sync_todos.repo.json", tmp_path / "sync_todos.local.json"
    if repo is not None:
        repo_file.write_text(json.dumps(repo))
    # end if
    if local is not None:
        local_file.write_text(json.dumps(local))
    # end if
    return tracked, repo_file, local_file
# end def


def test_repo_config_layers_between_tracked_and_local(tmp_path):
    repo = {"commit_prefix": "[r] ", "calendar_id": 9, "projects": {"A": {"path": "./a", "commit_prefix": "[ra] "}, "B": {"path": "."}}}
    tracked, repo_file, local = _layers(tmp_path, repo, {"projects": {"A": {"path": None}, "B": {"path": "/x/b", "commit_prefix": "[lb] "}}})
    cfg = st.load_config(tracked, local, repo=repo_file)
    a, b = cfg.projects
    assert (cfg.commit_prefix, cfg.calendar_id) == ("[r] ", 9)
    assert (a.path, a.path_source, a.commit_prefix) == ("./a", "repo", "[ra] ")
    assert (b.path, b.path_source, b.commit_prefix) == ("/x/b", "local", "[lb] ")
# end def


def test_repo_projects_can_add_or_override_projects(tmp_path):
    tracked, repo_file, local = _layers(tmp_path, {"projects": {"A": {"tags": ["a", "aa"], "todo_file": "x.md"}, "C": {"tags": ["c"], "path": "./c"}}})
    a, b, c = st.load_config(tracked, local, write_local=False, repo=repo_file).projects
    assert (a.tags, a.todo_file) == (["a", "aa"], "x.md")
    assert (c.name, c.tags, c.path) == ("C", ["c"], "./c")
    tracked, repo_file, local = _layers(tmp_path, {"projects": {"C": {"path": "./c"}}})
    with pytest.raises(ValueError, match="tags"):
        st.load_config(tracked, local, write_local=False, repo=repo_file)
    # end with
    tracked, repo_file, local = _layers(tmp_path, {"projects": {"C": {"tags": ["a"]}}})
    with pytest.raises(ValueError, match="tag"):
        st.load_config(tracked, local, write_local=False, repo=repo_file)
    # end with
# end def


@pytest.mark.parametrize("path", ["..", "../x", "./a/../b", "/abs", "~/x", "foo/bar", ".."])
def test_repo_path_must_stay_inside(path):
    with pytest.raises(ValueError):
        st.RepoProject(path=path)
    # end with
# end def


@pytest.mark.parametrize("path", [".", "./sub", "./a/b"])
def test_repo_path_accepts_inside_paths(path):
    assert st.RepoProject(path=path).path == path
# end def


def test_projects_with_a_repo_path_are_not_added_to_local(tmp_path):
    tracked, repo_file, local = _layers(tmp_path, {"projects": {"A": {"path": "."}}})
    st.load_config(tracked, local, repo=repo_file)
    assert json.loads(local.read_text())["projects"] == {"B": {"path": None, "commit_prefix": None}}
# end def


def test_hint_flag_counts_from_any_file(tmp_path):
    tracked, repo_file, local = _layers(tmp_path, {"projects": {"B": {"no-add-to-repo-hint": True}}}, {"projects": {"A": {"no-add-to-repo-hint": True}}})
    a, b = st.load_config(tracked, local, write_local=False, repo=repo_file).projects
    assert a.no_add_to_repo_hint and b.no_add_to_repo_hint
    local.write_text(json.dumps({"projects": {"A": {"no-add-to-repo-hint": True}}}))
    st.load_config(tracked, local)
    assert json.loads(local.read_text())["projects"]["A"] == {"path": None, "commit_prefix": None, "no-add-to-repo-hint": True}
# end def


def test_repo_schema_is_current_and_has_the_path_pattern():
    assert st.REPO_SCHEMA_PATH.read_text() == st.repo_schema_text()
    assert json.loads(st.repo_schema_text())["$defs"]["RepoProject"]["properties"]["path"]["pattern"] == st.REPO_PATH_PATTERN
# end def


def test_ensure_repo_file_creates_and_commits_once(tmp_path):
    r, run = _repo(tmp_path, "e")
    repo_file = r / "ai" / "settings" / "sync_todos.repo.json"
    st.ensure_repo_file(repo_file, "[p] ", dry_run=True, use_git=True)
    assert not repo_file.exists()
    st.ensure_repo_file(repo_file, "[p] ", dry_run=False, use_git=True)
    assert repo_file.read_text() == '{\n  "$schema": "./sync_todos-repo.schema.json",\n  "projects": {\n  }\n}\n'
    assert run("log", "-1", "--format=%s").strip() == "[p] [TODOs] added sync_todos.repo.json."
    st.ensure_repo_file(repo_file, "[p] ", dry_run=False, use_git=True)
    assert run("rev-list", "--count", "HEAD").strip() == "2"
    other = r / "ai" / "settings" / "other.repo.json"
    st.ensure_repo_file(other, "[p] ", dry_run=False, use_git=False)
    assert other.exists() and run("status", "--porcelain", "--", str(other)).startswith("??")
# end def


def test_migrate_local_paths_moves_inside_paths_only(tmp_path, monkeypatch):
    r, run = _repo(tmp_path, "m")
    monkeypatch.setattr(st, "REPO_ROOT", r)
    repo_file, local = r / "ai" / "settings" / "sync_todos.repo.json", tmp_path / "sync_todos.local.json"
    st.ensure_repo_file(repo_file, "", dry_run=False, use_git=True)
    tracked = tmp_path / "sync_todos.json"
    tracked.write_text(json.dumps({"projects": [{"name": n, "tags": [n.lower()]} for n in "ABCD"]}))
    local.write_text(json.dumps({"projects": {
        "A": {"path": str(r / "sub"), "commit_prefix": "[a] "},
        "B": {"path": "."},
        "C": {"path": str(tmp_path / "elsewhere")},
        "D": {"path": "~/d"},
    }}))
    cfg = st.load_config(tracked, local, repo=repo_file)
    assert st.movable(cfg, repo_file) == {"A": "./sub", "B": "."}
    assert st.migrate_local_paths(cfg, repo_file, local, {"A", "B", "C"}, dry_run=True, use_git=True) == ["A", "B"]
    assert json.loads(repo_file.read_text())["projects"] == {}
    assert st.migrate_local_paths(cfg, repo_file, local, {"A", "B", "C"}, dry_run=False, use_git=True) == ["A", "B"]
    assert repo_file.read_text() == st.dump_json(json.loads(repo_file.read_text()))
    assert json.loads(repo_file.read_text())["projects"] == {"A": {"path": "./sub", "commit_prefix": "[a] "}, "B": {"path": "."}}
    assert json.loads(local.read_text())["projects"]["A"] == {"path": None, "commit_prefix": None}
    assert json.loads(local.read_text())["projects"]["C"]["path"] == str(tmp_path / "elsewhere")
    assert run("log", "-1", "--format=%s").strip() == "[TODOs] moved local project paths into sync_todos.repo.json for A, B."
    cfg = st.load_config(tracked, local, repo=repo_file)
    assert [(p.name, p.path, p.path_source) for p in cfg.projects[:2]] == [("A", "./sub", "repo"), ("B", ".", "repo")]
    assert st.movable(cfg, repo_file) == {}
# end def


def test_migrate_keeps_an_existing_repo_path(tmp_path, monkeypatch):
    r, _ = _repo(tmp_path, "k")
    monkeypatch.setattr(st, "REPO_ROOT", r)
    tracked, repo_file, local = _layers(tmp_path, {"projects": {"A": {"path": "./x"}}}, {"projects": {"A": {"path": "."}}})
    cfg = st.load_config(tracked, local, repo=repo_file)
    assert (cfg.projects[0].path, cfg.projects[0].path_source) == (".", "local")
    assert st.movable(cfg, repo_file) == {}
# end def


def test_hint_lists_projects_once_with_lines_in_all_three_files(tmp_path, monkeypatch):
    r, _ = _repo(tmp_path, "h")
    monkeypatch.setattr(st, "REPO_ROOT", r)
    tracked, repo_file, local = _layers(tmp_path, {"projects": {}}, {"projects": {"A": {"path": "."}, "B": {"path": "."}}})
    cfg = st.load_config(tracked, local, repo=repo_file)
    moves = st.movable(cfg, repo_file)
    out = st.add_to_repo_hint(cfg, moves, tracked, repo_file, local)
    assert sum("could be committed" in line for line in out) == 1
    assert [line.strip() for line in out if line.endswith("):")] == ["A (path .):", "B (path .):"]
    assert f"    {tracked}:1" in out or any(line.startswith(f"    {tracked}:") for line in out)
    assert any(line.startswith(f"    {repo_file}:") and line.endswith("(add here)") for line in out)
    assert any(line.startswith(f"    {local}:") and "(add here)" not in line for line in out)
    assert all(str(p) in "\n".join(out) for p in (tracked, repo_file, local))
    cfg.projects[0].no_add_to_repo_hint = True
    out = st.add_to_repo_hint(cfg, moves, tracked, repo_file, local)
    assert [line.strip() for line in out if line.endswith("):")] == ["B (path .):"]
    cfg.projects[1].no_add_to_repo_hint = True
    assert st.add_to_repo_hint(cfg, moves, tracked, repo_file, local) == []
# end def


def test_all_skipped_prints_the_instruction(tmp_path, capsys):
    cfg = st.Config(projects=[st.Project(name="A", tags=["a"])])
    st.sync(cfg, [todo("1", "#a one")], None, False, use_git=False)
    assert st.REPO_CONFIG.name in capsys.readouterr().err
    r, _ = _repo(tmp_path, "s")
    cfg = st.Config(projects=[st.Project(name="A", tags=["a"], path=str(r))])
    st.sync(cfg, [todo("1", "#a one")], None, False, use_git=False)
    assert st.REPO_CONFIG.name not in capsys.readouterr().err
# end def
