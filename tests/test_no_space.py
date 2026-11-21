from __future__ import annotations

import errno
from pathlib import Path
from unittest import mock

from archive_apps import io as aio
from archive_apps.cli import RunContext


def test_is_no_space() -> None:
    assert aio.is_no_space(OSError(errno.ENOSPC, "No space left on device"))
    assert aio.is_no_space(OSError(errno.EDQUOT, "Disc quota exceeded"))
    assert not aio.is_no_space(PermissionError(errno.EACCES, "denied"))
    assert not aio.is_no_space(None)


def test_free_space_text_never_raises(tmp_path: Path) -> None:
    assert "free" in aio.free_space_text(tmp_path / "missing" / "deeper" / "file.txt")


def test_safe_write_reports_no_space(tmp_path: Path, capsys) -> None:
    target = tmp_path / "x.checksums.txt.tmp"
    ctx = mock.Mock(spec=RunContext)
    with mock.patch.object(Path, "write_text", side_effect=OSError(errno.ENOSPC, "No space left on device")), \
            mock.patch.object(aio, "tty_read", return_value="c"):
        aio.safe_write("abc", target, ctx)
    err = capsys.readouterr().err
    assert "NO SPACE LEFT" in err
    assert "WRITE ERROR" in err


def test_safe_write_other_error_shows_reason(tmp_path: Path, capsys) -> None:
    ctx = mock.Mock(spec=RunContext)
    with mock.patch.object(Path, "write_text", side_effect=PermissionError(errno.EACCES, "denied")), \
            mock.patch.object(aio, "tty_read", return_value="c"):
        aio.safe_write("abc", tmp_path / "x.txt", ctx)
    err = capsys.readouterr().err
    assert "NO SPACE LEFT" not in err
    assert "PermissionError" in err
