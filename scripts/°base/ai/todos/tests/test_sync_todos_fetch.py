"""Run: uv run --with pytest --with 'pydantic>=2.6' --with 'mcp>=2.3' --with python-dotenv pytest scripts/°base/ai/todos/tests/test_sync_todos_fetch.py"""
import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any

import httpx2
import pytest
from mcp.shared.exceptions import MCPError

path = Path(__file__).resolve().parent.parent / "sync_todos.py"
spec = importlib.util.spec_from_file_location("sync_todos", path)
st = importlib.util.module_from_spec(spec)
sys.modules["sync_todos"] = st
spec.loader.exec_module(st)

URL = "https://todo.example.com/api/mcp/"
TOKEN = "sytd_secret"


def handshake_error() -> ExceptionGroup:
    return ExceptionGroup("unhandled errors in a TaskGroup", [MCPError(-32603, "Server returned an error response", {"detail": "boot"})])
# end def


def auth_error() -> ExceptionGroup:
    request = httpx2.Request("POST", URL)
    return ExceptionGroup("unhandled errors in a TaskGroup", [httpx2.HTTPStatusError(f"401 for {URL} {TOKEN}", request=request, response=httpx2.Response(401, request=request))])
# end def


def failing_then(errors: list[BaseException], result: list[dict[str, Any]], calls: list[int]) -> Any:
    async def fake(url: str, token: str, calendar_id: int) -> list[dict[str, Any]]:
        calls.append(calendar_id)
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]
        # end if
        return result
    # end def

    return fake
# end def


def test_describe_names_code_message_and_data_without_url_or_token() -> None:
    text = st.describe_fetch_error(handshake_error(), URL, TOKEN)
    assert "code=-32603" in text and "Server returned an error response" in text and "boot" in text
    assert "\n" not in text
    leaked = st.describe_fetch_error(ExceptionGroup("g", [RuntimeError(f"{URL} with {TOKEN}")]), URL, TOKEN)
    assert URL not in leaked and TOKEN not in leaked and "<url>" in leaked and "<token>" in leaked
# end def


def test_transient_errors_are_retried_until_it_works(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
    # end def

    monkeypatch.setattr(st, "fetch_todos", failing_then([handshake_error(), handshake_error()], [{"uid": "a"}], calls))
    monkeypatch.setattr(st.asyncio, "sleep", fake_sleep)
    assert asyncio.run(st.fetch_todos_with_retry(URL, TOKEN, 7)) == [{"uid": "a"}]
    assert len(calls) == 3 and slept == [2.0, 5.0]
# end def


def test_gives_up_after_the_last_delay_with_a_one_line_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def no_sleep(seconds: float) -> None:
        return None
    # end def

    monkeypatch.setattr(st, "fetch_todos", failing_then([handshake_error()] * 5, [], calls))
    monkeypatch.setattr(st.asyncio, "sleep", no_sleep)
    with pytest.raises(st.FetchError) as raised:
        asyncio.run(st.fetch_todos_with_retry(URL, TOKEN, 7, delays=(0.0,)))
    # end with
    assert len(calls) == 2
    assert "code=-32603" in str(raised.value) and "\n" not in str(raised.value)
# end def


def test_auth_errors_are_not_retried_and_do_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(st, "fetch_todos", failing_then([auth_error()], [], calls))
    with pytest.raises(st.FetchError) as raised:
        asyncio.run(st.fetch_todos_with_retry(URL, TOKEN, 7))
    # end with
    assert len(calls) == 1
    assert "HTTP 401" in str(raised.value) and TOKEN not in str(raised.value) and URL not in str(raised.value)
# end def
