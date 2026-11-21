import builtins
import io
import sys

import pytest

from archive_apps import io as aio
from archive_apps.cli import parse_args


@pytest.fixture(autouse=True)
def _beep_on():
    aio.set_beep(True)
    yield
    aio.set_beep(True)


def test_bell_only_in_generic_terminal(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    out = io.StringIO()
    aio.alert_user(out)
    assert out.getvalue() == "\a"


def test_iterm2_also_requests_attention(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    out = io.StringIO()
    aio.alert_user(out)
    assert out.getvalue() == "\a\033]1337;RequestAttention=once\a"


def test_disabled_is_silent(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    aio.set_beep(False)
    out = io.StringIO()
    aio.alert_user(out)
    assert out.getvalue() == ""


def test_no_beep_flag(tmp_path):
    dest = str(tmp_path / "dest")
    assert parse_args([dest]).beep is True
    assert parse_args(["--no-beep", dest]).beep is False


class FakeTty(io.StringIO):
    """Stands in for /dev/tty: reads come from the initial value, writes are collected separately."""

    def __init__(self, answer: str):
        super().__init__(answer)
        self.written = ""

    def write(self, s: str) -> int:
        self.written += s
        return len(s)


def test_tty_read_rings_before_prompt(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    tty = FakeTty("b\n")
    monkeypatch.setattr(builtins, "open", lambda path, *a, **k: tty if path == "/dev/tty" else io.StringIO())
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    assert aio.tty_read("Choice: ", "a") == "b"
    assert tty.written == "\a"
    assert err.getvalue() == "Choice: "
