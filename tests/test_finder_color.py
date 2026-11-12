from pathlib import Path

from archive_apps.archive import apply_zip_colors
from archive_apps.cli import Config, RunContext
from archive_apps.utils import (
    FINDER_GRAY, FINDER_GREEN, FINDER_RED, get_finder_color, set_finder_color,
)


def _ctx(dest: Path) -> RunContext:
    cfg = Config.__new__(Config)
    cfg.dest = dest
    return RunContext(cfg=cfg)


def test_set_and_get_roundtrip(tmp_path):
    f = tmp_path / "a.zip"
    f.write_bytes(b"x")
    assert get_finder_color(f) == 0
    assert set_finder_color(f, FINDER_GREEN)
    assert get_finder_color(f) == FINDER_GREEN
    assert set_finder_color(f, FINDER_GREEN)  # no-op repeat
    assert set_finder_color(f, FINDER_RED)
    assert get_finder_color(f) == FINDER_RED


def test_missing_file_returns_false(tmp_path):
    assert set_finder_color(tmp_path / "nope.zip", FINDER_GREEN) is False


def test_apply_zip_colors(tmp_path):
    for name in ("cur.zip", "bad.zip", "old.zip", "nochk.zip", "seen.zip"):
        (tmp_path / name).write_bytes(b"x")
    for name in ("cur", "bad", "old", "seen"):
        (tmp_path / f"{name}.checksums.txt").write_text("")
    ctx = _ctx(tmp_path)
    ctx.zip_colors = {"cur.zip": FINDER_GREEN, "bad.zip": FINDER_RED}
    ctx.seen_zipnames = {"cur.zip", "bad.zip", "seen.zip"}
    apply_zip_colors(ctx)
    assert get_finder_color(tmp_path / "cur.zip") == FINDER_GREEN
    assert get_finder_color(tmp_path / "bad.zip") == FINDER_RED
    assert get_finder_color(tmp_path / "old.zip") == FINDER_GRAY
    assert get_finder_color(tmp_path / "nochk.zip") == 0
    assert get_finder_color(tmp_path / "seen.zip") == 0
