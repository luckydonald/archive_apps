import os
import stat
from pathlib import Path

from archive_apps import app_ops


def _fake_rsync(bindir: Path, exit_code: int = 0) -> None:
    bindir.mkdir(exist_ok=True)
    script = bindir / "rsync"
    script.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do last="$a"; done\n'
        'for a in "$@"; do case "$a" in --*) ;; *) first="${first:-$a}";; esac; done\n'
        'printf "  50%%\\r 100%%\\n"\n'
        f'[ {exit_code} -eq 0 ] && cp "$first" "$last"\n'
        f"exit {exit_code}\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def _setup(tmp_path, monkeypatch, tty: bool, rsync: int | None):
    src = tmp_path / "a.zip.tmp"
    src.write_bytes(b"payload")
    dst = tmp_path / "out.tmp"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    if rsync is not None:
        _fake_rsync(bindir, rsync)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}/bin")
    monkeypatch.setattr(app_ops.sys.stderr, "isatty", lambda: tty, raising=False)
    return src, dst


def test_rsync_used_when_available(tmp_path, monkeypatch):
    src, dst = _setup(tmp_path, monkeypatch, tty=False, rsync=0)
    app_ops.send_file(src, dst)
    assert dst.read_bytes() == b"payload"


def test_rsync_with_progress_bar_on_tty(tmp_path, monkeypatch):
    src, dst = _setup(tmp_path, monkeypatch, tty=True, rsync=0)
    app_ops.send_file(src, dst)
    assert dst.read_bytes() == b"payload"


def test_python_copy_without_rsync(tmp_path, monkeypatch):
    src, dst = _setup(tmp_path, monkeypatch, tty=False, rsync=None)
    app_ops.send_file(src, dst)
    assert dst.read_bytes() == b"payload"


def test_fallback_when_rsync_fails(tmp_path, monkeypatch, capsys):
    src, dst = _setup(tmp_path, monkeypatch, tty=False, rsync=1)
    dst.write_bytes(b"partial")
    app_ops.send_file(src, dst)
    assert dst.read_bytes() == b"payload"
    assert "falling back" in capsys.readouterr().out
