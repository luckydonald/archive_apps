from pathlib import Path

import pytest

import archive_apps.archive as archive
from archive_apps.archive import find_renamed_match
from archive_apps.cli import Config, MismatchTask, RunContext
from archive_apps.utils import FINDER_GREEN

LIVE = "abc  ./Foo.app/x\n"


def _task(dest: Path) -> MismatchTask:
    return MismatchTask(
        label="Foo 2.0", app=dest / "Foo.app", name="Foo", mobile="", version="2.0",
        versioned="Foo 2.0.app", zipname="Foo.app@2.0.zip", checksumname="Foo.app@2.0.checksums.txt",
        zipstem="Foo.app@2.0", live_manifest_hash="h", live_checksums=LIVE, zip_checksums=None,
    )


def _pair(dest: Path, stem: str, checksums: str, zip_too: bool = True) -> None:
    if zip_too:
        (dest / f"{stem}.zip").write_bytes(b"x")
    (dest / f"{stem}.checksums.txt").write_text(checksums)


def _ctx(dest: Path) -> RunContext:
    cfg = Config.__new__(Config)
    cfg.dest = dest
    cfg.on_mismatch = None
    return RunContext(cfg=cfg)


def test_matches_suffixed_zip(tmp_path):
    _pair(tmp_path, "Foo.app@2.0~20261119_120000", LIVE)
    assert find_renamed_match(tmp_path, _task(tmp_path)) == "Foo.app@2.0~20261119_120000.zip"


def test_ignores_different_checksums(tmp_path):
    _pair(tmp_path, "Foo.app@2.0~20261119_120000", "other\n")
    assert find_renamed_match(tmp_path, _task(tmp_path)) is None


def test_ignores_hash_mismatch_zip(tmp_path):
    _pair(tmp_path, "Foo.app@2.0~hash-mismatch~20261119_120000", LIVE)
    assert find_renamed_match(tmp_path, _task(tmp_path)) is None


def test_ignores_checksums_without_zip(tmp_path):
    _pair(tmp_path, "Foo.app@2.0~20261119_120000", LIVE, zip_too=False)
    assert find_renamed_match(tmp_path, _task(tmp_path)) is None


def test_resolve_skips_without_prompt(tmp_path, monkeypatch):
    _pair(tmp_path, "Foo.app@2.0~20261119_120000", LIVE)

    def boom(*a, **k):
        raise AssertionError("must not prompt")

    monkeypatch.setattr(archive, "tty_read", boom)
    monkeypatch.setattr(archive, "tty_read_timeout", boom)
    ctx = _ctx(tmp_path)
    archive._resolve_mismatch(_task(tmp_path), ctx, 60)
    assert ctx.zip_colors == {"Foo.app@2.0~20261119_120000.zip": FINDER_GREEN}


def test_resolve_still_prompts_without_match(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "tty_read_timeout", lambda *a, **k: ("s", False))
    ctx = _ctx(tmp_path)
    archive._resolve_mismatch(_task(tmp_path), ctx, 60)
    assert ctx.zip_colors == {}
