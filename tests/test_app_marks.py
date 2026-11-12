from pathlib import Path

from archive_apps.archive import app_mark_state, apply_app_marks
from archive_apps.cli import Config, RunContext
from archive_apps.utils import (
    FINDER_GREEN, FINDER_ORANGE, FINDER_RED, get_finder_color, get_finder_comment, set_finder_comment,
)


def _zip(dest: Path, name: str, checksums: bool = True) -> None:
    (dest / name).write_bytes(b"x")
    if checksums:
        (dest / name.replace(".zip", ".checksums.txt")).write_text("c")


def test_green_when_current_zip_verified(tmp_path):
    _zip(tmp_path, "Foo.app@2.0.zip")
    color, comment = app_mark_state(tmp_path, "Foo", "", "2.0", "Foo.app@2.0.zip", {"Foo.app@2.0.zip": FINDER_GREEN})
    assert color == FINDER_GREEN
    assert comment.startswith("archive_apps: backed up ") and comment.endswith("(version 2.0), verified")


def test_red_on_mismatch(tmp_path):
    _zip(tmp_path, "Foo.app@2.0.zip")
    color, comment = app_mark_state(tmp_path, "Foo", "", "2.0", "Foo.app@2.0.zip", {"Foo.app@2.0.zip": FINDER_RED})
    assert color == FINDER_RED
    assert "MISMATCH" in comment


def test_orange_when_only_old_version(tmp_path):
    _zip(tmp_path, "Foo.app@1.0.zip")
    _zip(tmp_path, "Foo.app@mobile@0.5.zip")
    _zip(tmp_path, "Foo.app@1.5~20200101_000000.zip")
    color, comment = app_mark_state(tmp_path, "Foo", "", "2.0", "Foo.app@2.0.zip", {})
    assert color == FINDER_ORANGE
    assert "newest backup is 1.0 from" in comment


def test_red_when_never_backed_up(tmp_path):
    _zip(tmp_path, "Bar.app@1.0.zip")
    _zip(tmp_path, "Foo.app@1.0.zip", checksums=False)
    assert app_mark_state(tmp_path, "Foo", "", "2.0", "Foo.app@2.0.zip", {}) == (
        FINDER_RED, "archive_apps: never backed up",
    )


def test_comment_roundtrip(tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"x")
    assert get_finder_comment(f) == ""
    assert set_finder_comment(f, "héllo")
    assert get_finder_comment(f) == "héllo"


def _ctx(dest: Path, app: Path) -> RunContext:
    cfg = Config.__new__(Config)
    cfg.dest = dest
    cfg.mark_apps = True
    ctx = RunContext(cfg=cfg)
    ctx.app_zips[app] = ("Foo", "", "2.0", "Foo.app@2.0.zip")
    return ctx


def test_apply_keeps_foreign_comment_and_replaces_own(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    app = tmp_path / "Foo.app"
    app.mkdir()
    ctx = _ctx(dest, app)
    set_finder_comment(app, "my note")
    apply_app_marks(ctx)
    assert get_finder_color(app) == FINDER_RED
    assert get_finder_comment(app) == "my note"
    set_finder_comment(app, "archive_apps: old")
    apply_app_marks(ctx)
    assert get_finder_comment(app) == "archive_apps: never backed up"


def test_no_mark_apps_leaves_app_alone(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    app = tmp_path / "Foo.app"
    app.mkdir()
    ctx = _ctx(dest, app)
    ctx.cfg.mark_apps = False
    apply_app_marks(ctx)
    assert get_finder_color(app) == 0
    assert get_finder_comment(app) == ""
