#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Literal, Sequence
from urllib.parse import SplitResult, urlsplit, urlunsplit


PROMPT_TOOLKIT_PACKAGE = "prompt_toolkit"
BOOTSTRAP_ENV = "GIT_REMOTE_FIX_BOOTSTRAPPED"
DEFAULT_THEME_NAME = "rounded"
INPUT_WIDTH = 40
INPUT_BORDER_WIDTH = INPUT_WIDTH + 2
FLASH_FEEDBACK_SECONDS = 0.25
CURSOR_BAR = "▎"
CURSOR_BLOCK = "▁"
KEY_SEPARATOR = "⟯"
TAB_KEY = "⇥"
ENTER_KEY = "⏎"
ESCAPE_KEY = "␛"
UP_DOWN_KEYS = "↑|↓"
LEFT_RIGHT_KEYS = "←|→"
CHECK_ALL_KEY = "𝚊"
CHECK_NONE_KEY = "𝚗"
REFRESH_KEY = "𝚛"
CANCEL_KEYS = f"𝚚|{ESCAPE_KEY}"


class GitCommandError(RuntimeError):
    pass


@dataclass
class GitHubUrlInfo:
    original_url: str
    split: SplitResult
    username: str | None
    owner: str
    repo: str
    path_without_suffix: str
    has_git_suffix: bool


@dataclass
class RemoteUrlSelection:
    kind: Literal["fetch", "push"]
    original_url: str
    github: GitHubUrlInfo | None
    change_username: bool
    add_git_suffix: bool

    @property
    def eligible(self) -> bool:
        return self.github is not None

    @property
    def has_git_suffix_option(self) -> bool:
        return self.github is not None and not self.github.has_git_suffix

    def toggleable_count(self) -> int:
        if not self.eligible:
            return 0
        return 1 + int(self.has_git_suffix_option)

    def selected_count(self) -> int:
        if not self.eligible:
            return 0
        return int(self.change_username) + int(self.has_git_suffix_option and self.add_git_suffix)

    def state(self) -> SelectionState:
        if not self.eligible:
            return "disabled"
        if self.has_git_suffix_option and self.change_username and not self.add_git_suffix:
            return "active"
        selected = self.selected_count()
        total = self.toggleable_count()
        if selected == 0:
            return "unchecked"
        if selected == total:
            return "checked"
        return "partial"

    def set_all(self, value: bool) -> None:
        if not self.eligible:
            return
        self.change_username = value
        if self.has_git_suffix_option:
            self.add_git_suffix = value


@dataclass
class RemoteSelection:
    name: str
    fetch: RemoteUrlSelection
    push: RemoteUrlSelection
    push_is_explicit: bool

    def descendants(self) -> tuple[RemoteUrlSelection, RemoteUrlSelection]:
        return (self.fetch, self.push)

    def toggleable_count(self) -> int:
        return self.fetch.toggleable_count() + self.push.toggleable_count()

    def selected_count(self) -> int:
        return self.fetch.selected_count() + self.push.selected_count()

    def state(self) -> SelectionState:
        total = self.toggleable_count()
        if total == 0:
            return "disabled"
        selected = self.selected_count()
        if selected == 0:
            return "unchecked"
        if selected == total:
            return "checked"
        return "partial"

    def set_all(self, value: bool) -> None:
        self.fetch.set_all(value)
        self.push.set_all(value)


@dataclass
class UrlPreview:
    remote_name: str
    kind: Literal["fetch", "push"]
    old_url: str
    new_url: str


@dataclass
class ExecutionPlan:
    previews: list[UrlPreview]
    commands: list[list[str]]


@dataclass(frozen=True)
class ThemeGlyphs:
    name: str
    remote_icons: dict[str, str]
    item_icons: dict[str, str]
    select_all_icon: str
    select_none_icon: str
    cursor_marker: str
    input_top_left: str
    input_top_joint: str
    input_top_fill: str
    input_top_right: str
    input_mid_left: str
    input_mid_prompt: str
    input_mid_joint: str
    input_mid_right: str
    input_bottom_left: str
    input_bottom_joint: str
    input_bottom_fill: str
    input_bottom_right: str
    branch_mid: str
    branch_last: str
    vertical: str


THEMES: dict[str, ThemeGlyphs] = {
    "boxy": ThemeGlyphs(
        name="boxy",
        remote_icons={
            "unchecked": "▽",
            "checked": "⏷",
            "partial": "⧩",
            "disabled": "⥐",
        },
        item_icons={
            "unchecked": "□",
            "checked": "■",
            "active": "■",
            "partial": "◪",
            "disabled": "⬚",
        },
        select_all_icon="▣",
        select_none_icon="⊡",
        cursor_marker="⪢",
        input_top_left="┌",
        input_top_joint="┬",
        input_top_fill="─",
        input_top_right="┐",
        input_mid_left="│",
        input_mid_prompt="✎",
        input_mid_joint="│",
        input_mid_right="│",
        input_bottom_left="╘",
        input_bottom_joint="╧",
        input_bottom_fill="═",
        input_bottom_right="╛",
        branch_mid="├─╴",
        branch_last="└─╴",
        vertical="│",
    ),
    "rounded": ThemeGlyphs(
        name="rounded",
        remote_icons={
            "unchecked": "◎",
            "checked": "◉",
            "partial": "◑",
            "disabled": "◠",
        },
        item_icons={
            "unchecked": "○",
            "checked": "●",
            "active": "◓",
            "partial": "◒",
            "disabled": "◌",
        },
        select_all_icon="◉",
        select_none_icon="◎",
        cursor_marker="⋑",
        input_top_left="╭",
        input_top_joint="┬",
        input_top_fill="─",
        input_top_right="╮",
        input_mid_left="│",
        input_mid_prompt="✎",
        input_mid_joint="│",
        input_mid_right="│",
        input_bottom_left="╰",
        input_bottom_joint="┷",
        input_bottom_fill="━",
        input_bottom_right="╯",
        branch_mid="├─╴",
        branch_last="╰─╴",
        vertical="│",
    ),
}


@dataclass
class TreeRow:
    kind: Literal["remote", "url", "git"]
    remote_index: int
    url_kind: Literal["fetch", "push"] | None = None


@dataclass
class ActionItem:
    action_id: str
    label: str
    icon: str
    enabled: bool


SelectionState = Literal["unchecked", "checked", "partial", "disabled", "active"]


def run_command(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        raise GitCommandError(stderr or f"Command failed: {shlex.join(args)}")
    return result


def git_output(args: Sequence[str], *, cwd: Path, check: bool = True) -> str:
    return run_command(["git", *args], cwd=cwd, check=check).stdout.strip()


def git_output_lines(args: Sequence[str], *, cwd: Path, check: bool = True) -> list[str]:
    output = git_output(args, cwd=cwd, check=check)
    return [line for line in output.splitlines() if line.strip()]


def get_repo_root(cwd: Path) -> Path:
    return Path(git_output(["rev-parse", "--show-toplevel"], cwd=cwd))


def parse_github_https_url(url: str) -> GitHubUrlInfo | None:
    split = urlsplit(url)
    if split.scheme != "https" or (split.hostname or "").lower() != "github.com":
        return None
    if split.port not in (None, 443):
        return None
    path_parts = [part for part in split.path.split("/") if part]
    if len(path_parts) != 2:
        return None
    owner, repo = path_parts
    if not owner or not repo:
        return None
    has_git_suffix = repo.endswith(".git")
    repo_name = repo[:-4] if has_git_suffix else repo
    if not repo_name:
        return None
    return GitHubUrlInfo(
        original_url=url,
        split=split,
        username=split.username,
        owner=owner,
        repo=repo_name,
        path_without_suffix=f"/{owner}/{repo_name}",
        has_git_suffix=has_git_suffix,
    )


def rewrite_github_https_url(
    url: str,
    *,
    username: str,
    set_username: bool,
    add_git_suffix: bool,
) -> str:
    info = parse_github_https_url(url)
    if info is None:
        return url
    if set_username and not username:
        raise ValueError("Username is required when changing GitHub remote usernames.")

    split = info.split
    netloc = split.netloc
    if set_username:
        host = split.hostname or "github.com"
        if split.port is not None:
            host = f"{host}:{split.port}"
        netloc = f"{username}@{host}"

    path = info.path_without_suffix
    if info.has_git_suffix or add_git_suffix:
        path = f"{path}.git"

    return urlunsplit(split._replace(netloc=netloc, path=path))


def make_url_selection(kind: Literal["fetch", "push"], url: str) -> RemoteUrlSelection:
    github = parse_github_https_url(url)
    return RemoteUrlSelection(
        kind=kind,
        original_url=url,
        github=github,
        change_username=bool(github and not github.username),
        add_git_suffix=bool(github and not github.has_git_suffix),
    )


def discover_remotes(repo_root: Path) -> list[RemoteSelection]:
    names = git_output_lines(["remote"], cwd=repo_root)
    remotes: list[RemoteSelection] = []
    for name in names:
        configured_fetch_urls = git_output_lines(
            ["config", "--get-all", f"remote.{name}.url"],
            cwd=repo_root,
            check=False,
        )
        configured_push_urls = git_output_lines(
            ["config", "--get-all", f"remote.{name}.pushurl"],
            cwd=repo_root,
            check=False,
        )
        if len(configured_fetch_urls) > 1 or len(configured_push_urls) > 1:
            raise ValueError(
                f"Remote {name!r} uses multiple URLs. This script supports one fetch URL and one optional push URL."
            )
        fetch_url = git_output(["remote", "get-url", name], cwd=repo_root)
        push_url = git_output(["remote", "get-url", "--push", name], cwd=repo_root)
        remotes.append(
            RemoteSelection(
                name=name,
                fetch=make_url_selection("fetch", fetch_url),
                push=make_url_selection("push", push_url),
                push_is_explicit=bool(configured_push_urls),
            )
        )
    return remotes


def get_git_config_value(repo_root: Path, key: str) -> str | None:
    result = run_command(["git", "config", "--get", key], cwd=repo_root, check=False)
    value = result.stdout.strip()
    return value or None


def resolve_default_username(
    cli_username: str | None,
    remotes: Iterable[RemoteSelection],
    config_getter: Callable[[str], str | None],
) -> str:
    if cli_username:
        return cli_username
    for remote in remotes:
        for selection in remote.descendants():
            if selection.github and selection.github.username:
                return selection.github.username
    for key in ("github.user", "user.name"):
        value = config_getter(key)
        if value:
            return value
    return ""


def compute_target_url(selection: RemoteUrlSelection, username: str) -> str:
    if not selection.eligible:
        return selection.original_url
    if not selection.change_username and not selection.add_git_suffix:
        return selection.original_url
    return rewrite_github_https_url(
        selection.original_url,
        username=username,
        set_username=selection.change_username,
        add_git_suffix=selection.add_git_suffix,
    )


def requires_username(remotes: Iterable[RemoteSelection]) -> bool:
    return any(selection.change_username for remote in remotes for selection in remote.descendants())


def build_execution_plan(remotes: Sequence[RemoteSelection], username: str) -> ExecutionPlan:
    username = username.strip()
    if requires_username(remotes) and not username:
        raise ValueError("Enter a username before previewing or applying username changes.")

    previews: list[UrlPreview] = []
    commands: list[list[str]] = []
    for remote in remotes:
        old_fetch = remote.fetch.original_url
        old_push = remote.push.original_url
        new_fetch = compute_target_url(remote.fetch, username)
        new_push = compute_target_url(remote.push, username)

        if new_fetch != old_fetch:
            previews.append(UrlPreview(remote.name, "fetch", old_fetch, new_fetch))
        if new_push != old_push:
            previews.append(UrlPreview(remote.name, "push", old_push, new_push))

        if remote.push_is_explicit:
            if new_fetch != old_fetch:
                commands.append(["git", "remote", "set-url", remote.name, new_fetch])
            if new_push != old_push:
                commands.append(["git", "remote", "set-url", "--push", remote.name, new_push])
            continue

        if new_fetch == new_push:
            if new_fetch != old_fetch:
                commands.append(["git", "remote", "set-url", remote.name, new_fetch])
            continue

        if new_fetch != old_fetch:
            commands.append(["git", "remote", "set-url", remote.name, new_fetch])
        if new_push != new_fetch:
            commands.append(["git", "remote", "set-url", "--push", remote.name, new_push])

    return ExecutionPlan(previews=previews, commands=commands)


def apply_execution_plan(plan: ExecutionPlan, repo_root: Path) -> None:
    for command in plan.commands:
        run_command(command, cwd=repo_root)


def ensure_prompt_toolkit(argv: Sequence[str]) -> None:
    try:
        __import__(PROMPT_TOOLKIT_PACKAGE)
        return
    except ModuleNotFoundError as exc:
        if exc.name != PROMPT_TOOLKIT_PACKAGE:
            raise

    fallback_command = [
        "uv",
        "run",
        "--with",
        PROMPT_TOOLKIT_PACKAGE,
        "python",
        str(Path(__file__).resolve()),
        *argv,
    ]
    uv_binary = shutil.which("uv")
    if uv_binary and not os.environ.get(BOOTSTRAP_ENV):
        rerun_command = [uv_binary, *fallback_command[1:]]
        env = os.environ.copy()
        env[BOOTSTRAP_ENV] = "1"
        rerun = subprocess.run(rerun_command, check=False, env=env)
        if rerun.returncode == 0:
            raise SystemExit(0)

    print(
        "prompt_toolkit is required to run the interactive UI.\n"
        f"Run:\n  {shlex.join(fallback_command)}",
        file=sys.stderr,
    )
    raise SystemExit(1)


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def run_tui(
    remotes: list[RemoteSelection],
    *,
    theme: ThemeGlyphs,
    username: str,
) -> ExecutionPlan | None:
    from prompt_toolkit.application import Application, get_app
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.filters import Condition, has_focus
    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import DynamicContainer, HSplit, Layout, VSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.styles import Style
    try:
        from prompt_toolkit.keys import Keys
    except Exception:
        Keys = None
    scroll_down_key = getattr(Keys, "ScrollDown", "scrolldown") if Keys is not None else "scrolldown"
    scroll_up_key = getattr(Keys, "ScrollUp", "scrollup") if Keys is not None else "scrollup"

    @dataclass
    class UiState:
        remotes: list[RemoteSelection]
        theme: ThemeGlyphs
        username_buffer: Buffer
        selected_tree_index: int = 0
        tree_scroll_offset: int = 0
        action_index: int = 0
        preview_action_index: int = 0
        preview_plan: ExecutionPlan | None = None
        status_message: str = ""
        status_is_error: bool = False
        flash_target: str | None = None
        flash_until: float = 0.0

        def clear_status(self) -> None:
            self.status_message = ""
            self.status_is_error = False

        def set_status(self, message: str, *, is_error: bool = False) -> None:
            self.status_message = message
            self.status_is_error = is_error

        def tree_rows(self) -> list[TreeRow]:
            rows: list[TreeRow] = []
            for remote_index, remote in enumerate(self.remotes):
                rows.append(TreeRow("remote", remote_index))
                rows.append(TreeRow("url", remote_index, "fetch"))
                if remote.fetch.has_git_suffix_option:
                    rows.append(TreeRow("git", remote_index, "fetch"))
                rows.append(TreeRow("url", remote_index, "push"))
                if remote.push.has_git_suffix_option:
                    rows.append(TreeRow("git", remote_index, "push"))
            return rows

        def clamp_tree_index(self) -> None:
            rows = self.tree_rows()
            if not rows:
                self.selected_tree_index = 0
                return
            self.selected_tree_index = clamp(self.selected_tree_index, 0, len(rows) - 1)

        def current_tree_row(self) -> TreeRow | None:
            rows = self.tree_rows()
            if not rows:
                return None
            self.clamp_tree_index()
            return rows[self.selected_tree_index]

        def move_tree(self, delta: int) -> None:
            rows = self.tree_rows()
            if not rows:
                return
            self.selected_tree_index = clamp(self.selected_tree_index + delta, 0, len(rows) - 1)
            ensure_tree_selection_visible()
            self.clear_status()

        def last_tree_index(self) -> int:
            rows = self.tree_rows()
            return max(0, len(rows) - 1)

        def toggle_current_tree_row(self) -> None:
            row = self.current_tree_row()
            if row is None:
                return
            self.clear_status()
            remote = self.remotes[row.remote_index]
            if row.kind == "remote":
                total = remote.toggleable_count()
                if total == 0:
                    return
                remote.set_all(remote.selected_count() != total)
                return

            selection = getattr(remote, row.url_kind)
            if row.kind == "url":
                if selection.eligible:
                    selection.change_username = not selection.change_username
                return
            if selection.has_git_suffix_option:
                selection.add_git_suffix = not selection.add_git_suffix

        def current_username(self) -> str:
            return self.username_buffer.text.strip()

        def move_cursor(self, delta: int) -> None:
            position = self.username_buffer.cursor_position + delta
            self.username_buffer.cursor_position = clamp(position, 0, len(self.username_buffer.text))

        def insert_text(self, text: str) -> None:
            if not text:
                return
            position = self.username_buffer.cursor_position
            value = self.username_buffer.text
            self.username_buffer.text = f"{value[:position]}{text}{value[position:]}"
            self.username_buffer.cursor_position = position + len(text)

        def delete_before_cursor(self) -> None:
            position = self.username_buffer.cursor_position
            if position == 0:
                return
            value = self.username_buffer.text
            self.username_buffer.text = f"{value[:position - 1]}{value[position:]}"
            self.username_buffer.cursor_position = position - 1

        def delete_at_cursor(self) -> None:
            position = self.username_buffer.cursor_position
            value = self.username_buffer.text
            if position >= len(value):
                return
            self.username_buffer.text = f"{value[:position]}{value[position + 1:]}"
            self.username_buffer.cursor_position = position

        def can_check_all(self) -> bool:
            return any(
                selection.eligible and selection.selected_count() < selection.toggleable_count()
                for remote in self.remotes
                for selection in remote.descendants()
            )

        def can_check_none(self) -> bool:
            return any(
                selection.eligible and selection.selected_count() > 0
                for remote in self.remotes
                for selection in remote.descendants()
            )

        def check_all(self) -> None:
            for remote in self.remotes:
                remote.set_all(True)
            self.clear_status()

        def check_none(self) -> None:
            for remote in self.remotes:
                remote.set_all(False)
            self.clear_status()

        def build_preview(self) -> ExecutionPlan:
            return build_execution_plan(self.remotes, self.current_username())

        def can_submit(self) -> bool:
            try:
                plan = self.build_preview()
            except ValueError:
                return False
            return bool(plan.previews)

        def edit_actions(self) -> list[ActionItem]:
            return [
                ActionItem("check_all", "Check all", self.theme.select_all_icon, self.can_check_all()),
                ActionItem("check_none", "Check none", self.theme.select_none_icon, self.can_check_none()),
            ]

        def preview_actions(self) -> list[ActionItem]:
            return [
                ActionItem("apply", "Apply", "✔", bool(self.preview_plan and self.preview_plan.previews)),
                ActionItem("back", "Back", "↩", True),
                ActionItem("cancel", "Cancel", "✕", True),
            ]

        def set_flash(self, target: str | None) -> None:
            self.flash_target = target
            self.flash_until = time.monotonic() + FLASH_FEEDBACK_SECONDS if target else 0.0

        def is_flashing(self, target: str) -> bool:
            if self.flash_target != target:
                return False
            if time.monotonic() >= self.flash_until:
                self.flash_target = None
                self.flash_until = 0.0
                return False
            return True

    @dataclass(frozen=True)
    class RedrawSnapshot:
        focus_group: str
        tree_index: int
        tree_line_count: int
        action_index: int
        preview_action_index: int
        preview_mode: bool

    def append_row(target: StyleAndTextTuples, fragments: StyleAndTextTuples) -> None:
        if target:
            target.append(("", "\n"))
        target.extend(fragments)

    def flatten_fragments(fragments: StyleAndTextTuples) -> str:
        return "".join(text for _, text in fragments)

    def split_fragment_lines(fragments: StyleAndTextTuples) -> list[StyleAndTextTuples]:
        lines: list[StyleAndTextTuples] = [[]]
        for style_name, text in fragments:
            parts = text.split("\n")
            for index, part in enumerate(parts):
                if part:
                    lines[-1].append((style_name, part))
                if index != len(parts) - 1:
                    lines.append([])
        if lines and not lines[-1]:
            lines.pop()
        return lines

    def join_fragment_lines(lines: Sequence[StyleAndTextTuples]) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        for line in lines:
            append_row(fragments, list(line))
        return fragments

    def line_prefix(selected: bool) -> StyleAndTextTuples:
        if selected:
            return [("class:selected-marker", f"{theme.cursor_marker}  ")]
        return [("", "   ")]

    def remote_icon_style(state_name: SelectionState, *, selected: bool) -> str:
        if not selected:
            return ""
        return "class:selected-marker"

    def item_icon_style(state_name: SelectionState, *, selected: bool) -> str:
        if selected:
            return "class:selected-marker"
        if state_name in {"checked", "active"}:
            return "class:icon-active"
        return ""

    def git_icon_style(state_name: SelectionState, *, selected: bool) -> str:
        if selected:
            return "class:selected-marker"
        return ""

    def url_style(selection: RemoteUrlSelection) -> str:
        return "class:url" if selection.eligible else "class:url-disabled"

    def action_icon_style(*, selected: bool, flashing: bool) -> str:
        if flashing:
            return "class:flash"
        if selected:
            return "class:selected-marker"
        return ""

    def action_label_style(*, selected: bool, enabled: bool, flashing: bool) -> str:
        if flashing:
            return "class:flash"
        if selected and enabled:
            return "class:selected-marker"
        if not enabled:
            return "class:action-disabled"
        return ""

    def flash_feedback(target: str) -> None:
        state.set_flash(target)
        request_redraw(clear=True)
        time.sleep(FLASH_FEEDBACK_SECONDS)
        state.set_flash(None)
        request_redraw(clear=True)

    def key_hint(label: str) -> str:
        return f"{label}{KEY_SEPARATOR}  "

    def request_redraw(*, clear: bool) -> None:
        renderer = getattr(app, "renderer", None)
        clear_method = getattr(renderer, "clear", None)
        if clear and callable(clear_method):
            clear_method()
        invalidate = getattr(app, "invalidate", None)
        if callable(invalidate):
            invalidate()

    def cursor_to_row_start(output, row_index: int) -> bool:
        cursor_goto = getattr(output, "cursor_goto", None)
        if not callable(cursor_goto):
            return False
        try:
            cursor_goto(row=row_index, column=1)
            return True
        except TypeError:
            try:
                cursor_goto(row_index, 1)
                return True
            except TypeError:
                return False

    def rewrite_rows(row_updates: dict[int, str]) -> bool:
        if not row_updates:
            return False
        renderer = getattr(app, "renderer", None)
        output = getattr(renderer, "output", None)
        if output is None:
            return False
        erase_end_of_line = getattr(output, "erase_end_of_line", None)
        write = getattr(output, "write", None)
        flush = getattr(output, "flush", None)
        if not callable(erase_end_of_line) or not callable(write):
            return False
        columns = max(1, terminal_columns())

        for row_index, text in sorted(row_updates.items()):
            if not cursor_to_row_start(output, row_index):
                return False
            erase_end_of_line()
            write(text[:columns])

        if callable(flush):
            flush()
        return True

    def redraw_from_scratch() -> None:
        request_redraw(clear=True)

    def local_redraw() -> None:
        snapshot = capture_redraw_snapshot()
        previous_snapshot = redraw_state["snapshot"]
        if previous_snapshot is not None and rewrite_rows(collect_row_updates(previous_snapshot, snapshot)):
            redraw_state["snapshot"] = snapshot
            return
        redraw_state["snapshot"] = snapshot
        request_redraw(clear=False)

    def refresh_ui() -> None:
        redraw_from_scratch()

    def terminal_columns() -> int:
        return shutil.get_terminal_size(fallback=(80, 24)).columns

    def terminal_lines() -> int:
        return shutil.get_terminal_size(fallback=(80, 24)).lines

    def max_input_width() -> int:
        return max(INPUT_WIDTH, terminal_columns() - 12)

    def current_input_width() -> int:
        if len(state.username_buffer.text) + 1 > INPUT_WIDTH:
            return max_input_width()
        return INPUT_WIDTH

    def current_input_border_width() -> int:
        return current_input_width() + 2

    def cursor_is_visible() -> bool:
        return (time.monotonic() % 1.0) < 0.5

    def tree_visible_height() -> int:
        return max(1, terminal_lines() - 13)

    state = UiState(remotes=remotes, theme=theme, username_buffer=Buffer(multiline=False))
    state.username_buffer.text = username
    state.username_buffer.cursor_position = len(username)

    style = Style.from_dict(
        {
            "heading": "bold",
            "muted": "ansibrightblack",
            "selected-marker": "ansimagenta bold",
            "icon-active": "ansimagenta bold",
            "icon-disabled": "ansibrightblack",
            "remote-name": "ansimagenta bold",
            "url": "ansimagenta underline",
            "url-disabled": "ansibrightblack",
            "input-border": "ansibrightblack",
            "input-border-active": "ansimagenta bold",
            "action-icon": "ansimagenta bold",
            "action-disabled": "ansibrightblack",
            "code": "ansimagenta bold",
            "status": "ansiyellow",
            "error": "ansired bold",
            "preview-label": "ansimagenta bold",
            "preview-old": "ansibrightblack",
            "preview-new": "ansimagenta bold",
            "flash": "reverse ansimagenta bold",
        }
    )

    def get_input_border_style() -> str:
        try:
            app = get_app()
        except Exception:
            return "class:input-border"
        return "class:input-border-active" if app.layout.has_focus(username_window) else "class:input-border"

    def get_input_border_line(left: str, joint: str, fill: str, right: str) -> StyleAndTextTuples:
        style_name = get_input_border_style()
        return [
            ("", "  "),
            (style_name, left),
            (style_name, fill * 3),
            (style_name, joint),
            (style_name, fill * current_input_border_width()),
            (style_name, right),
        ]

    def get_username_fragments() -> StyleAndTextTuples:
        value = state.username_buffer.text
        position = clamp(state.username_buffer.cursor_position, 0, len(value))
        focused = app.layout.has_focus(username_window)
        width = current_input_width()
        blink_on = focused and cursor_is_visible()

        if not focused and len(value) <= width:
            return [("", value), ("", " " * max(0, width - len(value)))]

        ellipsis = "…"
        cursor_at_end = focused and position >= len(value)
        total_cells = len(value) + int(cursor_at_end)

        if total_cells <= width:
            start = 0
            end = len(value)
            show_prefix = False
            show_suffix = False
        elif not focused or cursor_at_end:
            show_prefix = True
            show_suffix = False
            visible_cells = max(1, width - 1)
            start = max(0, total_cells - visible_cells)
            end = len(value)
        elif position <= 0:
            show_prefix = False
            show_suffix = True
            visible_cells = max(1, width - 1)
            start = 0
            end = min(len(value), visible_cells)
        else:
            show_prefix = True
            show_suffix = True
            visible_cells = max(1, width - 2)
            max_start = max(1, len(value) - visible_cells - 1)
            start = clamp(position - (visible_cells // 2), 1, max_start)
            end = min(len(value), start + visible_cells)

        fragments: StyleAndTextTuples = []
        if show_prefix:
            fragments.append(("", ellipsis))

        if focused:
            if cursor_at_end:
                fragments.append(("", value[start:end]))
                fragments.append(("class:selected-marker", CURSOR_BLOCK if blink_on else " "))
            else:
                before_cursor = value[start:position]
                after_cursor = value[position + 1 : end]
                fragments.append(("", before_cursor))
                fragments.append(("class:selected-marker", CURSOR_BAR if blink_on else value[position]))
                fragments.append(("", after_cursor))
        else:
            fragments.append(("", value[start:end]))

        if show_suffix:
            fragments.append(("", ellipsis))

        visible_length = sum(len(text) for _, text in fragments)
        fragments.append(("", " " * max(0, width - visible_length)))
        return fragments

    def build_full_tree_text() -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        rows = state.tree_rows()
        if not rows:
            append_row(fragments, [("", "  No remotes found.")])
            return fragments

        tree_has_focus = app.layout.has_focus(tree_window)
        for index, row in enumerate(rows):
            if index > 0 and row.kind == "remote":
                fragments.append(("", "\n"))
            selected = tree_has_focus and index == state.selected_tree_index
            prefix = line_prefix(selected)
            remote = state.remotes[row.remote_index]

            if row.kind == "remote":
                remote_state = remote.state()
                append_row(
                    fragments,
                    prefix
                    + [
                        ("", "  "),
                        (remote_icon_style(remote_state, selected=selected), f"{theme.remote_icons[remote_state]} "),
                        ("class:remote-name", remote.name),
                    ],
                )
                continue

            selection = getattr(remote, row.url_kind)
            if row.kind == "url":
                branch = theme.branch_mid if row.url_kind == "fetch" else theme.branch_last
                row_state = selection.state()
                append_row(
                    fragments,
                    prefix
                    + [
                        ("", f"  {branch} "),
                        (item_icon_style(row_state, selected=selected), f"{theme.item_icons[row_state]} "),
                        ("", f"{selection.kind:<5}: "),
                        (url_style(selection), selection.original_url),
                    ],
                )
                continue

            child_prefix = f"  {theme.vertical}   " if row.url_kind == "fetch" else "      "
            git_state = "checked" if selection.add_git_suffix else "unchecked"
            append_row(
                fragments,
                prefix
                + [
                    ("", child_prefix + theme.branch_last + " "),
                    (git_icon_style(git_state, selected=selected), f"{theme.item_icons[git_state]} "),
                    ("", "Add "),
                    ("class:code", ".git"),
                    ("", " suffix"),
                ],
            )

        return fragments

    def get_edit_tree_text() -> StyleAndTextTuples:
        tree_lines = split_fragment_lines(build_full_tree_text())
        start = clamp(state.tree_scroll_offset, 0, max(0, len(tree_lines) - tree_visible_height()))
        state.tree_scroll_offset = start
        end = start + tree_visible_height()
        return join_fragment_lines(tree_lines[start:end])

    def render_actions(actions: list[ActionItem], current_index: int, focused: bool) -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        for index, action in enumerate(actions):
            selected = focused and current_index == index
            flashing = state.is_flashing(f"action:{action.action_id}")
            append_row(
                fragments,
                line_prefix(selected)
                + [
                    ("", " "),
                    (action_icon_style(selected=selected, flashing=flashing), f"{action.icon} "),
                    (action_label_style(selected=selected, enabled=action.enabled, flashing=flashing), action.label),
                ],
            )
        return fragments

    def get_edit_actions_text() -> StyleAndTextTuples:
        return render_actions(
            state.edit_actions(),
            state.action_index,
            app.layout.has_focus(edit_actions_window),
        )

    def get_submit_text() -> StyleAndTextTuples:
        focused = app.layout.has_focus(submit_window)
        flashing = state.is_flashing("submit")
        style_name = "class:flash" if flashing else ("class:selected-marker" if focused else "")
        return line_prefix(focused) + [
            ("", " "),
            (style_name, "[ Submit → ]"),
        ]

    def get_preview_text() -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        plan = state.preview_plan
        if not plan or not plan.previews:
            append_row(fragments, [("", "  No changes selected.")])
            return fragments
        for index, preview in enumerate(plan.previews):
            if index > 0:
                fragments.append(("", "\n"))
            append_row(
                fragments,
                [
                    ("", "  "),
                    ("class:preview-label", f"{preview.remote_name} / {preview.kind}: "),
                    ("class:preview-old", preview.old_url),
                ],
            )
            append_row(
                fragments,
                [
                    ("", "    -> "),
                    ("class:preview-new", preview.new_url),
                ],
            )
        return fragments

    def get_preview_actions_text() -> StyleAndTextTuples:
        return render_actions(
            state.preview_actions(),
            state.preview_action_index,
            app.layout.has_focus(preview_actions_window),
        )

    def get_status_text() -> StyleAndTextTuples:
        if not state.status_message:
            return [("", "")]
        return [("class:error" if state.status_is_error else "class:status", state.status_message)]

    def get_help_text() -> StyleAndTextTuples:
        if state.preview_plan is not None:
            text = "   ".join(
                [
                    f"{key_hint(TAB_KEY)}focus",
                    f"{key_hint(UP_DOWN_KEYS)}move",
                    f"{key_hint(ENTER_KEY)}next element/submit",
                    f"{key_hint(REFRESH_KEY)}refresh",
                    f"{key_hint(CANCEL_KEYS)}cancel",
                ]
            )
            return [("class:muted", text)]

        if app.layout.has_focus(username_window):
            text = "   ".join(
                [
                    f"{key_hint(TAB_KEY)}focus",
                    f"{key_hint(UP_DOWN_KEYS)}move",
                    f"{key_hint(LEFT_RIGHT_KEYS)}move cursor",
                    f"{key_hint(ENTER_KEY)}next element/submit",
                    f"{key_hint(REFRESH_KEY)}refresh",
                ]
            )
            return [("class:muted", text)]

        parts = [
            f"{key_hint(TAB_KEY)}focus",
            f"{key_hint(UP_DOWN_KEYS)}move",
        ]
        if app.layout.has_focus(tree_window):
            parts.append(f"{key_hint('Space')}toggle")
        parts.extend(
            [
                f"{key_hint(ENTER_KEY)}next element/submit",
                f"{key_hint(CHECK_ALL_KEY)}check all",
                f"{key_hint(CHECK_NONE_KEY)}check none",
                f"{key_hint(REFRESH_KEY)}refresh",
                f"{key_hint(CANCEL_KEYS)}cancel",
            ]
        )
        return [("class:muted", "   ".join(parts))]

    username_control = FormattedTextControl(get_username_fragments, focusable=True)
    try:
        setattr(username_control, "buffer", state.username_buffer)
    except Exception:
        pass
    username_window = Window(
        content=username_control,
        width=Dimension(min=INPUT_WIDTH),
        height=1,
        wrap_lines=False,
        dont_extend_width=True,
        always_hide_cursor=True,
    )
    tree_window = Window(
        content=FormattedTextControl(get_edit_tree_text, focusable=True),
        always_hide_cursor=True,
    )
    edit_actions_window = Window(
        content=FormattedTextControl(get_edit_actions_text, focusable=True),
        always_hide_cursor=True,
        height=Dimension(min=2, max=2),
    )
    submit_window = Window(
        content=FormattedTextControl(get_submit_text, focusable=True),
        always_hide_cursor=True,
        height=1,
    )
    preview_window = Window(
        content=FormattedTextControl(get_preview_text),
        always_hide_cursor=True,
    )
    preview_actions_window = Window(
        content=FormattedTextControl(get_preview_actions_text, focusable=True),
        always_hide_cursor=True,
        height=Dimension(min=3, max=3),
    )
    status_window = Window(FormattedTextControl(get_status_text), height=1)
    help_window = Window(FormattedTextControl(get_help_text), height=1)

    input_container = HSplit(
        [
            Window(
                FormattedTextControl(
                    lambda: get_input_border_line(
                        theme.input_top_left,
                        theme.input_top_joint,
                        theme.input_top_fill,
                        theme.input_top_right,
                    )
                ),
                height=1,
            ),
            VSplit(
                [
                    Window(
                        FormattedTextControl(
                            lambda: [
                                ("", "  "),
                                (get_input_border_style(), theme.input_mid_left),
                                (get_input_border_style(), f" {theme.input_mid_prompt} "),
                                (get_input_border_style(), f"{theme.input_mid_joint} "),
                            ]
                        ),
                        width=8,
                        height=1,
                    ),
                    username_window,
                    Window(
                        FormattedTextControl(
                            lambda: [(get_input_border_style(), f" {theme.input_mid_right}")]
                        ),
                        width=2,
                        height=1,
                    ),
                ],
                height=1,
            ),
            Window(
                FormattedTextControl(
                    lambda: get_input_border_line(
                        theme.input_bottom_left,
                        theme.input_bottom_joint,
                        theme.input_bottom_fill,
                        theme.input_bottom_right,
                    )
                ),
                height=1,
            ),
        ]
    )

    edit_body = HSplit(
        [
            Window(FormattedTextControl(lambda: [("class:heading", "Enter the git username to use:")]), height=1),
            input_container,
            Window(height=1, char=" "),
            Window(FormattedTextControl(lambda: [("class:heading", "Select the remote urls to change:")]), height=1),
            tree_window,
            Window(height=1, char=" "),
            edit_actions_window,
            Window(height=1, char=" "),
            status_window,
            submit_window,
        ]
    )

    footer_container = HSplit([help_window], height=1)

    edit_container = HSplit([edit_body, footer_container])

    preview_body = HSplit(
        [
            Window(FormattedTextControl(lambda: [("class:heading", "Preview changes:")]), height=1),
            preview_window,
            Window(height=1, char=" "),
            preview_actions_window,
            Window(height=1, char=" "),
            status_window,
        ]
    )

    preview_container = HSplit([preview_body, footer_container])

    root_container = DynamicContainer(lambda: preview_container if state.preview_plan is not None else edit_container)
    layout = Layout(root_container, focused_element=username_window)
    kb = KeyBindings()
    app: Application
    redraw_state: dict[str, RedrawSnapshot | None] = {"snapshot": None}

    def current_focus_group() -> str:
        current = app.layout.current_window
        if current == username_window:
            return "username"
        if current == tree_window:
            return "tree"
        if current == edit_actions_window:
            return "actions"
        if current == submit_window:
            return "submit"
        if current == preview_actions_window:
            return "preview-actions"
        return "other"

    def capture_redraw_snapshot() -> RedrawSnapshot:
        return RedrawSnapshot(
            focus_group=current_focus_group(),
            tree_index=state.selected_tree_index,
            tree_line_count=len(split_fragment_lines(get_edit_tree_text())),
            action_index=state.action_index,
            preview_action_index=state.preview_action_index,
            preview_mode=state.preview_plan is not None,
        )

    def tree_display_line_index_map() -> dict[int, int]:
        mapping: dict[int, int] = {}
        display_index = 0
        rows = state.tree_rows()
        for index, row in enumerate(rows):
            if index > 0 and row.kind == "remote":
                display_index += 1
            mapping[index] = display_index
            display_index += 1
        return mapping

    def total_tree_line_count() -> int:
        return len(split_fragment_lines(build_full_tree_text()))

    def ensure_tree_selection_visible() -> None:
        mapping = tree_display_line_index_map()
        line_index = mapping.get(state.selected_tree_index, 0)
        height = tree_visible_height()
        max_scroll = max(0, total_tree_line_count() - height)
        if line_index < state.tree_scroll_offset or line_index >= state.tree_scroll_offset + height:
            state.tree_scroll_offset = clamp(line_index - (height // 2), 0, max_scroll)

    def tree_screen_row(index: int) -> int | None:
        mapping = tree_display_line_index_map()
        line_index = mapping.get(index)
        if line_index is None:
            return None
        if not (state.tree_scroll_offset <= line_index < state.tree_scroll_offset + tree_visible_height()):
            return None
        return 7 + (line_index - state.tree_scroll_offset)

    def edit_actions_start_row() -> int:
        tree_line_count = len(split_fragment_lines(get_edit_tree_text()))
        return 8 + tree_line_count

    def submit_row() -> int:
        tree_line_count = len(split_fragment_lines(get_edit_tree_text()))
        return 12 + tree_line_count

    def help_row() -> int:
        tree_line_count = len(split_fragment_lines(get_edit_tree_text()))
        return 13 + tree_line_count

    def collect_row_updates(previous: RedrawSnapshot, current: RedrawSnapshot) -> dict[int, str]:
        if previous.preview_mode or current.preview_mode:
            return {}

        updates: dict[int, str] = {}

        if "username" in {previous.focus_group, current.focus_group}:
            updates[2] = flatten_fragments(
                get_input_border_line(
                    theme.input_top_left,
                    theme.input_top_joint,
                    theme.input_top_fill,
                    theme.input_top_right,
                )
            )
            updates[3] = flatten_fragments(
                [("", "  ")]
                + [(get_input_border_style(), theme.input_mid_left)]
                + [(get_input_border_style(), f" {theme.input_mid_prompt} ")]
                + [(get_input_border_style(), f"{theme.input_mid_joint} ")]
                + get_username_fragments()
                + [(get_input_border_style(), f" {theme.input_mid_right}")]
            )
            updates[4] = flatten_fragments(
                get_input_border_line(
                    theme.input_bottom_left,
                    theme.input_bottom_joint,
                    theme.input_bottom_fill,
                    theme.input_bottom_right,
                )
            )

        if "tree" in {previous.focus_group, current.focus_group}:
            tree_lines = [flatten_fragments(line) for line in split_fragment_lines(get_edit_tree_text())]
            for visible_index in range(max(previous.tree_line_count, current.tree_line_count)):
                updates[7 + visible_index] = tree_lines[visible_index] if visible_index < len(tree_lines) else ""

        if "actions" in {previous.focus_group, current.focus_group}:
            action_lines = [flatten_fragments(line) for line in split_fragment_lines(get_edit_actions_text())]
            for line_index, line in enumerate(action_lines):
                updates[edit_actions_start_row() + line_index] = line

        if "submit" in {previous.focus_group, current.focus_group}:
            updates[submit_row()] = flatten_fragments(get_submit_text())

        if previous.focus_group != current.focus_group or previous.preview_mode != current.preview_mode:
            updates[help_row()] = flatten_fragments(get_help_text())

        return updates

    def focus_next() -> None:
        if state.preview_plan is not None:
            app.layout.focus(preview_actions_window)
            local_redraw()
            return
        current = app.layout.current_window
        if current == username_window:
            app.layout.focus(tree_window)
            ensure_tree_selection_visible()
        elif current == tree_window:
            app.layout.focus(edit_actions_window)
        elif current == edit_actions_window:
            app.layout.focus(submit_window)
        else:
            app.layout.focus(username_window)
        local_redraw()

    def focus_previous() -> None:
        if state.preview_plan is not None:
            app.layout.focus(preview_actions_window)
            local_redraw()
            return
        current = app.layout.current_window
        if current == username_window:
            app.layout.focus(submit_window)
        elif current == tree_window:
            app.layout.focus(username_window)
        elif current == edit_actions_window:
            app.layout.focus(tree_window)
        else:
            app.layout.focus(edit_actions_window)
        local_redraw()

    def open_preview() -> None:
        state.clear_status()
        try:
            plan = state.build_preview()
        except ValueError as exc:
            state.set_status(str(exc), is_error=True)
            return
        if not plan.previews:
            state.set_status("No changes selected.", is_error=True)
            local_redraw()
            return
        state.preview_plan = plan
        state.preview_action_index = 0
        app.layout.focus(preview_actions_window)
        local_redraw()

    def leave_preview() -> None:
        state.preview_plan = None
        state.preview_action_index = 0
        state.clear_status()
        app.layout.focus(tree_window)
        ensure_tree_selection_visible()
        local_redraw()

    def activate_action(action_id: str) -> None:
        state.clear_status()
        if action_id == "check_all":
            flash_feedback("action:check_all")
            state.check_all()
            local_redraw()
            return
        if action_id == "check_none":
            flash_feedback("action:check_none")
            state.check_none()
            local_redraw()
            return
        if action_id == "apply":
            if not state.preview_plan or not state.preview_plan.previews:
                state.set_status("No changes to apply.", is_error=True)
                local_redraw()
                return
            flash_feedback("action:apply")
            app.exit(result=state.preview_plan)
            return
        if action_id == "back":
            flash_feedback("action:back")
            leave_preview()
            return
        if action_id == "cancel":
            flash_feedback("action:cancel")
            app.exit(result=None)

    def activate_submit() -> None:
        try:
            plan = state.build_preview()
        except ValueError as exc:
            state.set_status(str(exc), is_error=True)
            local_redraw()
            return
        if not plan.previews:
            state.set_status("No changes selected.", is_error=True)
            local_redraw()
            return
        flash_feedback("submit")
        open_preview()

    @kb.add("tab")
    def _focus_next(event) -> None:
        focus_next()

    @kb.add("s-tab")
    def _focus_previous(event) -> None:
        focus_previous()

    @kb.add(scroll_down_key, filter=has_focus(username_window))
    @kb.add("down", filter=has_focus(username_window))
    def _input_down(event) -> None:
        app.layout.focus(tree_window)
        ensure_tree_selection_visible()
        local_redraw()

    @kb.add("enter", filter=has_focus(username_window))
    def _input_enter(event) -> None:
        app.layout.focus(tree_window)
        ensure_tree_selection_visible()
        local_redraw()

    @kb.add("left", filter=has_focus(username_window))
    def _input_left(event) -> None:
        state.move_cursor(-1)
        local_redraw()

    @kb.add("right", filter=has_focus(username_window))
    def _input_right(event) -> None:
        state.move_cursor(1)
        local_redraw()

    @kb.add("home", filter=has_focus(username_window))
    def _input_home(event) -> None:
        state.username_buffer.cursor_position = 0
        local_redraw()

    @kb.add("end", filter=has_focus(username_window))
    def _input_end(event) -> None:
        state.username_buffer.cursor_position = len(state.username_buffer.text)
        local_redraw()

    @kb.add("backspace", filter=has_focus(username_window))
    def _input_backspace(event) -> None:
        state.delete_before_cursor()
        local_redraw()

    @kb.add("delete", filter=has_focus(username_window))
    def _input_delete(event) -> None:
        state.delete_at_cursor()
        local_redraw()

    @kb.add(Keys.Any if Keys is not None else "<any>", filter=has_focus(username_window))
    def _input_text(event) -> None:
        text = getattr(event, "data", "")
        if text and text.isprintable() and text not in "\r\n\t":
            state.insert_text(text)
            local_redraw()

    @kb.add(scroll_down_key, filter=has_focus(tree_window))
    @kb.add("down", filter=has_focus(tree_window))
    def _tree_down(event) -> None:
        if state.selected_tree_index >= state.last_tree_index():
            state.action_index = 0
            app.layout.focus(edit_actions_window)
            state.clear_status()
            local_redraw()
            return
        state.move_tree(1)
        local_redraw()

    @kb.add(scroll_up_key, filter=has_focus(tree_window))
    @kb.add("up", filter=has_focus(tree_window))
    def _tree_up(event) -> None:
        if state.selected_tree_index <= 0:
            app.layout.focus(username_window)
            state.clear_status()
            local_redraw()
            return
        state.move_tree(-1)
        local_redraw()

    @kb.add("space", filter=has_focus(tree_window))
    def _tree_toggle(event) -> None:
        state.toggle_current_tree_row()
        local_redraw()

    @kb.add("enter", filter=has_focus(tree_window))
    def _tree_enter(event) -> None:
        app.layout.focus(edit_actions_window)
        state.action_index = 0
        local_redraw()

    @kb.add(scroll_down_key, filter=has_focus(edit_actions_window))
    @kb.add("down", filter=has_focus(edit_actions_window))
    def _edit_actions_down(event) -> None:
        actions = state.edit_actions()
        if state.action_index >= len(actions) - 1:
            app.layout.focus(submit_window)
            state.clear_status()
            local_redraw()
            return
        state.action_index = clamp(state.action_index + 1, 0, len(actions) - 1)
        state.clear_status()
        local_redraw()

    @kb.add(scroll_up_key, filter=has_focus(edit_actions_window))
    @kb.add("up", filter=has_focus(edit_actions_window))
    def _edit_actions_up(event) -> None:
        if state.action_index <= 0:
            state.selected_tree_index = state.last_tree_index()
            ensure_tree_selection_visible()
            app.layout.focus(tree_window)
            state.clear_status()
            local_redraw()
            return
        actions = state.edit_actions()
        state.action_index = clamp(state.action_index - 1, 0, len(actions) - 1)
        state.clear_status()
        local_redraw()

    @kb.add("space", filter=has_focus(edit_actions_window))
    @kb.add("enter", filter=has_focus(edit_actions_window))
    def _activate_edit_action(event) -> None:
        actions = state.edit_actions()
        action = actions[state.action_index]
        if not action.enabled:
            state.set_status(f"{action.label} has no effect right now.", is_error=True)
            return
        activate_action(action.action_id)

    @kb.add(scroll_up_key, filter=has_focus(submit_window))
    @kb.add("up", filter=has_focus(submit_window))
    def _submit_up(event) -> None:
        state.action_index = len(state.edit_actions()) - 1
        app.layout.focus(edit_actions_window)
        local_redraw()

    @kb.add("space", filter=has_focus(submit_window))
    @kb.add("enter", filter=has_focus(submit_window))
    def _submit_activate(event) -> None:
        activate_submit()

    @kb.add(scroll_down_key, filter=has_focus(preview_actions_window))
    @kb.add("down", filter=has_focus(preview_actions_window))
    def _preview_actions_down(event) -> None:
        actions = state.preview_actions()
        state.preview_action_index = clamp(state.preview_action_index + 1, 0, len(actions) - 1)
        state.clear_status()
        local_redraw()

    @kb.add(scroll_up_key, filter=has_focus(preview_actions_window))
    @kb.add("up", filter=has_focus(preview_actions_window))
    def _preview_actions_up(event) -> None:
        actions = state.preview_actions()
        state.preview_action_index = clamp(state.preview_action_index - 1, 0, len(actions) - 1)
        state.clear_status()
        local_redraw()

    @kb.add("space", filter=has_focus(preview_actions_window))
    @kb.add("enter", filter=has_focus(preview_actions_window))
    def _activate_preview_action(event) -> None:
        actions = state.preview_actions()
        action = actions[state.preview_action_index]
        if not action.enabled:
            state.set_status(f"{action.label} has no effect right now.", is_error=True)
            return
        activate_action(action.action_id)

    @kb.add("a", filter=Condition(lambda: state.preview_plan is None and not app.layout.has_focus(username_window)))
    def _check_all(event) -> None:
        state.check_all()
        local_redraw()

    @kb.add("n", filter=Condition(lambda: state.preview_plan is None and not app.layout.has_focus(username_window)))
    def _check_none(event) -> None:
        state.check_none()
        local_redraw()

    @kb.add("r")
    def _refresh(event) -> None:
        refresh_ui()

    @kb.add("q")
    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event) -> None:
        app.exit(result=None)

    def on_text_changed(_) -> None:
        state.clear_status()
        local_redraw()

    state.username_buffer.on_text_changed += on_text_changed
    app = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=True,
        mouse_support=True,
        refresh_interval=0.5,
    )
    redraw_state["snapshot"] = capture_redraw_snapshot()
    return app.run()


def print_applied_summary(plan: ExecutionPlan) -> None:
    if not plan.previews:
        print("No changes were applied.")
        return
    print(f"Applied {len(plan.previews)} remote URL change(s):")
    for preview in plan.previews:
        print(f"- {preview.remote_name} {preview.kind}: {preview.old_url} -> {preview.new_url}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactively add or replace GitHub usernames in git remote HTTPS URLs."
    )
    parser.add_argument("--username", help="Prefill the username field.")
    parser.add_argument(
        "--theme",
        choices=sorted(THEMES),
        default=DEFAULT_THEME_NAME,
        help=f"Visual theme to use. Defaults to {DEFAULT_THEME_NAME}.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        repo_root = get_repo_root(Path.cwd())
        remotes = discover_remotes(repo_root)
    except (GitCommandError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not remotes:
        print("No git remotes found in this repository.", file=sys.stderr)
        return 1

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("This script requires an interactive terminal.", file=sys.stderr)
        return 1

    username = resolve_default_username(
        args.username,
        remotes,
        lambda key: get_git_config_value(repo_root, key),
    )

    ensure_prompt_toolkit(argv if argv is not None else sys.argv[1:])
    plan = run_tui(remotes, theme=THEMES[args.theme], username=username)
    if plan is None:
        return 0

    try:
        apply_execution_plan(plan, repo_root)
    except GitCommandError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print_applied_summary(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
