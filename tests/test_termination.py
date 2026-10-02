import os
from pathlib import Path

import pytest

from archive_apps import io as aio
from archive_apps import verify
from archive_apps.cli import Config, RunContext


def _ctx(dest: Path) -> RunContext:
    cfg = Config.__new__(Config)
    cfg.dest = dest
    cfg.keep_temp = False
    return RunContext(cfg=cfg)


def test_merge_failure_keeps_index_and_scratch(tmp_path, monkeypatch):
    (tmp_path / "_checksum_index_.txt").write_text("aaa  one.zip\n")
    scratch = tmp_path / "_checksum_index_.scratch.tmp"
    scratch.write_text("bbb  two.zip\n")

    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(KeyboardInterrupt):
        verify.merge_checksum_index(scratch, _ctx(tmp_path))
    assert (tmp_path / "_checksum_index_.txt").read_text() == "aaa  one.zip\n"
    assert scratch.exists()


def test_merge_success(tmp_path):
    (tmp_path / "_checksum_index_.txt").write_text("aaa  one.zip\n")
    scratch = tmp_path / "_checksum_index_.scratch.tmp"
    scratch.write_text("bbb  two.zip\n")
    verify.merge_checksum_index(scratch, _ctx(tmp_path))
    assert (tmp_path / "_checksum_index_.txt").read_text() == "aaa  one.zip\nbbb  two.zip\n"
    assert not scratch.exists()


def test_rm_retry_returns_false_not_exit(tmp_path, monkeypatch):
    d = tmp_path / "x"
    d.mkdir()
    monkeypatch.setattr(aio.time, "sleep", lambda s: None)
    monkeypatch.setattr(aio.shutil, "rmtree", lambda *a, **k: None)
    monkeypatch.setattr(aio, "_unlock_tree", lambda p: None)
    monkeypatch.setattr(aio.sys.stderr, "isatty", lambda: False, raising=False)
    assert aio.rm_retry(d) is False
