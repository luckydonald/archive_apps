from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "git" / "remote"
MODULE_PATH = ROOT / "fix_username.py"
SPEC = importlib.util.spec_from_file_location("git_remote_fix", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


PROMPT_TOOLKIT_AVAILABLE = importlib.util.find_spec("prompt_toolkit") is not None


class TestKeyEvent:
    def __init__(self, app, *, data: str = "") -> None:
        self.app = app
        self.data = data


class OutputRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def clear(self) -> None:
        self.calls.clear()

    def cursor_goto(self, row: int = 0, column: int = 0) -> None:
        self.calls.append(("cursor_goto", row, column))

    def cursor_up(self, amount: int) -> None:
        self.calls.append(("cursor_up", amount))

    def cursor_down(self, amount: int) -> None:
        self.calls.append(("cursor_down", amount))

    def cursor_forward(self, amount: int) -> None:
        self.calls.append(("cursor_forward", amount))

    def cursor_backward(self, amount: int) -> None:
        self.calls.append(("cursor_backward", amount))

    def erase_end_of_line(self) -> None:
        self.calls.append(("erase_end_of_line",))

    def write(self, text: str) -> None:
        self.calls.append(("write", text))

    def write_raw(self, text: str) -> None:
        self.calls.append(("write_raw", text))

    def flush(self) -> None:
        self.calls.append(("flush",))


class RendererRecorder:
    def __init__(self) -> None:
        self.clear_count = 0
        self.output = OutputRecorder()

    def clear(self) -> None:
        self.clear_count += 1


class TestPromptToolkitRuntime:
    def __init__(self) -> None:
        self.current_app = None


TEST_RUNTIME = TestPromptToolkitRuntime()


class StyleProxy:
    def __init__(self, style) -> None:
        self._style = style
        style_rules = getattr(style, "style_rules", {})
        self.style_rules = dict(style_rules) if isinstance(style_rules, list) else style_rules

    def __getattr__(self, name: str):
        return getattr(self._style, name)


def get_current_app():
    return TEST_RUNTIME.current_app


def has_focus_filter(window):
    return CONDITION_CLASS(lambda: TEST_RUNTIME.current_app.layout.has_focus(window))


def normalize_key_name(key: object) -> str:
    value = getattr(key, "value", key)
    mapping = {
        " ": "space",
        "c-m": "enter",
        "c-i": "tab",
        "<scroll-down>": "scrolldown",
        "<scroll-up>": "scrollup",
        "<any>": "<any>",
    }
    return mapping.get(value, str(value))


def event_data_for_key(key: str) -> str:
    if key == "space":
        return " "
    if len(key) == 1:
        return key
    return ""


class TestApplication:
    def __init__(
        self,
        *,
        layout,
        key_bindings,
        style,
        full_screen,
        mouse_support,
        refresh_interval=None,
    ) -> None:
        self.layout = layout
        self.key_bindings = key_bindings
        self.style = style
        self.full_screen = full_screen
        self.mouse_support = mouse_support
        self.refresh_interval = refresh_interval
        self.exit_result = None
        self.invalidate_count = 0
        self.style = StyleProxy(style)
        self.renderer = RendererRecorder()
        TEST_RUNTIME.current_app = self

    def exit(self, result=None) -> None:
        self.exit_result = result

    def invalidate(self) -> None:
        self.invalidate_count += 1

    def press(self, key: str) -> None:
        event = TestKeyEvent(self, data=event_data_for_key(key))
        bindings = list(self.key_bindings.bindings)
        for binding in bindings:
            if not self.binding_matches(binding, key, allow_any=False):
                continue
            active_filter = getattr(binding, "filter", None)
            if active_filter is not None and not active_filter():
                continue
            binding.handler(event)
            return
        for binding in bindings:
            if not self.binding_matches(binding, key, allow_any=True):
                continue
            active_filter = getattr(binding, "filter", None)
            if active_filter is not None and not active_filter():
                continue
            binding.handler(event)
            return
        raise AssertionError(f"No active key binding for {key!r}")

    def binding_matches(self, binding, key: str, *, allow_any: bool) -> bool:
        keys = getattr(binding, "keys", None)
        if keys is not None:
            if len(keys) != 1:
                return False
            binding_key = normalize_key_name(keys[0])
            if binding_key == "<any>":
                return allow_any and bool(event_data_for_key(key))
            if allow_any:
                return False
            return binding_key == key

        binding_key = getattr(binding, "key", None)
        if binding_key is None:
            return False
        return not allow_any and binding_key == key

    def run(self):
        return self


if PROMPT_TOOLKIT_AVAILABLE:
    REAL_PROMPT_TOOLKIT = importlib.import_module("prompt_toolkit")
    REAL_BUFFER_MODULE = importlib.import_module("prompt_toolkit.buffer")
    REAL_FORMATTED_TEXT_MODULE = importlib.import_module("prompt_toolkit.formatted_text")
    REAL_KEY_BINDING_MODULE = importlib.import_module("prompt_toolkit.key_binding")
    REAL_LAYOUT_MODULE = importlib.import_module("prompt_toolkit.layout")
    REAL_LAYOUT_CONTROLS_MODULE = importlib.import_module("prompt_toolkit.layout.controls")
    REAL_LAYOUT_DIMENSION_MODULE = importlib.import_module("prompt_toolkit.layout.dimension")
    REAL_STYLES_MODULE = importlib.import_module("prompt_toolkit.styles")
    REAL_KEYS_MODULE = importlib.import_module("prompt_toolkit.keys")

    BUFFER_CLASS = REAL_BUFFER_MODULE.Buffer
    CONDITION_CLASS = importlib.import_module("prompt_toolkit.filters").Condition
    KEY_BINDINGS_CLASS = REAL_KEY_BINDING_MODULE.KeyBindings
    FORMATTED_TEXT_CONTROL_CLASS = REAL_LAYOUT_CONTROLS_MODULE.FormattedTextControl
    BUFFER_CONTROL_CLASS = REAL_LAYOUT_CONTROLS_MODULE.BufferControl
    DIMENSION_CLASS = REAL_LAYOUT_DIMENSION_MODULE.Dimension
    WINDOW_CLASS = REAL_LAYOUT_MODULE.Window
    HSPLIT_CLASS = REAL_LAYOUT_MODULE.HSplit
    VSPLIT_CLASS = REAL_LAYOUT_MODULE.VSplit
    DYNAMIC_CONTAINER_CLASS = REAL_LAYOUT_MODULE.DynamicContainer
    LAYOUT_CLASS = REAL_LAYOUT_MODULE.Layout
    STYLE_CLASS = REAL_STYLES_MODULE.Style
else:
    class FallbackBufferEvent:
        def __init__(self) -> None:
            self._callbacks = []

        def __iadd__(self, callback):
            self._callbacks.append(callback)
            return self

        def fire(self, buffer) -> None:
            for callback in list(self._callbacks):
                callback(buffer)

    class FallbackBuffer:
        def __init__(self, *, multiline: bool = False) -> None:
            self.multiline = multiline
            self._text = ""
            self.cursor_position = 0
            self.on_text_changed = FallbackBufferEvent()

        @property
        def text(self) -> str:
            return self._text

        @text.setter
        def text(self, value: str) -> None:
            self._text = value
            self.cursor_position = min(self.cursor_position, len(value))
            self.on_text_changed.fire(self)

    class FallbackCondition:
        def __init__(self, func):
            self.func = func

        def __call__(self) -> bool:
            return bool(self.func())

    @dataclass
    class FallbackBinding:
        key: str
        filter: object | None
        handler: object

    class FallbackKeyBindings:
        def __init__(self) -> None:
            self.bindings: list[FallbackBinding] = []

        def add(self, key: str, filter=None):
            def decorator(func):
                self.bindings.append(FallbackBinding(key=key, filter=filter, handler=func))
                return func

            return decorator

    class FallbackFormattedTextControl:
        def __init__(self, text, focusable: bool = False) -> None:
            self.text = text
            self.focusable = focusable

    class FallbackBufferControl:
        def __init__(self, buffer: FallbackBuffer, focusable: bool = True) -> None:
            self.buffer = buffer
            self.focusable = focusable

    class FallbackDimension:
        def __init__(self, preferred=None, min=None, max=None) -> None:
            self.preferred = preferred
            self.min = min
            self.max = max

    class FallbackWindow:
        def __init__(
            self,
            content=None,
            width=None,
            height=None,
            wrap_lines=None,
            dont_extend_width=None,
            always_hide_cursor=None,
            char=None,
        ) -> None:
            self.content = content
            self.width = width
            self.height = height
            self.wrap_lines = wrap_lines
            self.dont_extend_width = dont_extend_width
            self.always_hide_cursor = always_hide_cursor
            self.char = char

    class FallbackHSplit:
        def __init__(self, children, height=None) -> None:
            self.children = children
            self.height = height

    class FallbackVSplit:
        def __init__(self, children, height=None) -> None:
            self.children = children
            self.height = height

    class FallbackDynamicContainer:
        def __init__(self, get_container) -> None:
            self.get_container = get_container

    class FallbackLayout:
        def __init__(self, container, focused_element) -> None:
            self.container = container
            self.current_window = focused_element

        def focus(self, window) -> None:
            self.current_window = window

        def has_focus(self, window) -> bool:
            return self.current_window is window

    class FallbackStyle:
        def __init__(self, style_rules: dict[str, str]) -> None:
            self.style_rules = style_rules

        @classmethod
        def from_dict(cls, mapping: dict[str, str]):
            return cls(mapping)

    BUFFER_CLASS = FallbackBuffer
    CONDITION_CLASS = FallbackCondition
    KEY_BINDINGS_CLASS = FallbackKeyBindings
    FORMATTED_TEXT_CONTROL_CLASS = FallbackFormattedTextControl
    BUFFER_CONTROL_CLASS = FallbackBufferControl
    DIMENSION_CLASS = FallbackDimension
    WINDOW_CLASS = FallbackWindow
    HSPLIT_CLASS = FallbackHSplit
    VSPLIT_CLASS = FallbackVSplit
    DYNAMIC_CONTAINER_CLASS = FallbackDynamicContainer
    LAYOUT_CLASS = FallbackLayout
    STYLE_CLASS = FallbackStyle


class PromptToolkitTestModules:
    MODULE_NAMES = (
        "prompt_toolkit",
        "prompt_toolkit.application",
        "prompt_toolkit.buffer",
        "prompt_toolkit.filters",
        "prompt_toolkit.formatted_text",
        "prompt_toolkit.key_binding",
        "prompt_toolkit.layout",
        "prompt_toolkit.layout.controls",
        "prompt_toolkit.layout.dimension",
        "prompt_toolkit.styles",
        "prompt_toolkit.keys",
    )

    def __init__(self) -> None:
        self.previous = {}

    def install(self) -> None:
        for name in self.MODULE_NAMES:
            self.previous[name] = sys.modules.get(name)

        if PROMPT_TOOLKIT_AVAILABLE:
            self.install_real()
            return
        self.install_fallback()

    def install_real(self) -> None:
        application = types.ModuleType("prompt_toolkit.application")
        filters = types.ModuleType("prompt_toolkit.filters")

        application.Application = TestApplication
        application.get_app = get_current_app

        filters.Condition = CONDITION_CLASS
        filters.has_focus = has_focus_filter

        sys.modules["prompt_toolkit"] = REAL_PROMPT_TOOLKIT
        sys.modules["prompt_toolkit.application"] = application
        sys.modules["prompt_toolkit.buffer"] = REAL_BUFFER_MODULE
        sys.modules["prompt_toolkit.filters"] = filters
        sys.modules["prompt_toolkit.formatted_text"] = REAL_FORMATTED_TEXT_MODULE
        sys.modules["prompt_toolkit.key_binding"] = REAL_KEY_BINDING_MODULE
        sys.modules["prompt_toolkit.layout"] = REAL_LAYOUT_MODULE
        sys.modules["prompt_toolkit.layout.controls"] = REAL_LAYOUT_CONTROLS_MODULE
        sys.modules["prompt_toolkit.layout.dimension"] = REAL_LAYOUT_DIMENSION_MODULE
        sys.modules["prompt_toolkit.styles"] = REAL_STYLES_MODULE
        sys.modules["prompt_toolkit.keys"] = REAL_KEYS_MODULE

    def install_fallback(self) -> None:
        prompt_toolkit = types.ModuleType("prompt_toolkit")
        application = types.ModuleType("prompt_toolkit.application")
        buffer = types.ModuleType("prompt_toolkit.buffer")
        filters = types.ModuleType("prompt_toolkit.filters")
        formatted_text = types.ModuleType("prompt_toolkit.formatted_text")
        key_binding = types.ModuleType("prompt_toolkit.key_binding")
        layout = types.ModuleType("prompt_toolkit.layout")
        layout_controls = types.ModuleType("prompt_toolkit.layout.controls")
        layout_dimension = types.ModuleType("prompt_toolkit.layout.dimension")
        styles = types.ModuleType("prompt_toolkit.styles")

        application.Application = TestApplication
        application.get_app = get_current_app
        buffer.Buffer = BUFFER_CLASS
        filters.Condition = CONDITION_CLASS
        filters.has_focus = has_focus_filter
        formatted_text.StyleAndTextTuples = list
        key_binding.KeyBindings = KEY_BINDINGS_CLASS
        layout.DynamicContainer = DYNAMIC_CONTAINER_CLASS
        layout.HSplit = HSPLIT_CLASS
        layout.Layout = LAYOUT_CLASS
        layout.VSplit = VSPLIT_CLASS
        layout.Window = WINDOW_CLASS
        layout_controls.BufferControl = BUFFER_CONTROL_CLASS
        layout_controls.FormattedTextControl = FORMATTED_TEXT_CONTROL_CLASS
        layout_dimension.Dimension = DIMENSION_CLASS
        styles.Style = STYLE_CLASS

        sys.modules["prompt_toolkit"] = prompt_toolkit
        sys.modules["prompt_toolkit.application"] = application
        sys.modules["prompt_toolkit.buffer"] = buffer
        sys.modules["prompt_toolkit.filters"] = filters
        sys.modules["prompt_toolkit.formatted_text"] = formatted_text
        sys.modules["prompt_toolkit.key_binding"] = key_binding
        sys.modules["prompt_toolkit.layout"] = layout
        sys.modules["prompt_toolkit.layout.controls"] = layout_controls
        sys.modules["prompt_toolkit.layout.dimension"] = layout_dimension
        sys.modules["prompt_toolkit.styles"] = styles

    def uninstall(self) -> None:
        TEST_RUNTIME.current_app = None
        for name, previous in self.previous.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def flatten_fragments(fragments) -> str:
    return "".join(text for _, text in fragments)


def normalize_fragments(value) -> list[tuple[str, str]]:
    if value is None:
        return [("", "")]
    if isinstance(value, str):
        return [("", value)]
    return list(value)


def split_fragment_lines(fragments) -> list[list[tuple[str, str]]]:
    lines: list[list[tuple[str, str]]] = [[]]
    for style, text in fragments:
        parts = text.split("\n")
        for index, part in enumerate(parts):
            if part:
                lines[-1].append((style, part))
            if index != len(parts) - 1:
                lines.append([])
    if lines and not lines[-1]:
        lines.pop()
    return lines


def window_width(window) -> int:
    width = getattr(window, "width", 0)
    if isinstance(width, int):
        return width
    if hasattr(width, "preferred") and width.preferred is not None:
        return width.preferred
    if hasattr(width, "min") and width.min is not None:
        return width.min
    return 0


def join_line_fragments(line: list[tuple[str, str]]) -> str:
    return "".join(text for _, text in line)


def is_dynamic_container(node) -> bool:
    return callable(getattr(node, "get_container", None))


def is_window(node) -> bool:
    return hasattr(node, "content") and hasattr(node, "width")


def is_split(node) -> bool:
    return hasattr(node, "children")


def render_node_lines(node, render_window_fragments) -> list[str]:
    if is_dynamic_container(node):
        return render_node_lines(node.get_container(), render_window_fragments)
    if is_window(node):
        return [join_line_fragments(line) for line in split_fragment_lines(render_window_fragments(node))] or [""]
    if is_split(node):
        child_lines = [render_node_lines(child, render_window_fragments) for child in node.children]
        if isinstance(node, HSPLIT_CLASS):
            lines: list[str] = []
            for lines_for_child in child_lines:
                lines.extend(lines_for_child)
            return lines
        height = max((len(lines) for lines in child_lines), default=0)
        rendered: list[str] = []
        for index in range(height):
            parts: list[str] = []
            for child, lines_for_child in zip(node.children, child_lines):
                line = lines_for_child[index] if index < len(lines_for_child) else ""
                width = window_width(child) if is_window(child) else len(line)
                parts.append(line.ljust(width))
            rendered.append("".join(parts))
        return rendered
    raise TypeError(f"Unsupported node: {type(node)!r}")


class TuiHarness:
    def __init__(self, app) -> None:
        self.app = app
        self.edit_container = self.app.layout.container.get_container()
        self.edit_body = self.edit_container.children[0]
        self.footer_container = self.edit_container.children[1]
        self.input_container = self.edit_body.children[1]
        self.input_row = self.input_container.children[1]
        self.username_window = self.input_row.children[1]
        self.tree_window = self.edit_body.children[4]
        self.actions_window = self.edit_body.children[6]
        self.status_window = self.edit_body.children[8]
        self.submit_window = self.edit_body.children[9]
        self.help_window = self.footer_container.children[0]

    def press(self, key: str, *, times: int = 1) -> None:
        for _ in range(times):
            self.app.press(key)

    def iter_windows(self, node=None):
        node = self.app.layout.container if node is None else node
        if is_dynamic_container(node):
            yield from self.iter_windows(node.get_container())
            return
        if is_window(node):
            yield node
            return
        if is_split(node):
            for child in node.children:
                yield from self.iter_windows(child)

    def find_window_containing(self, text: str):
        for window in self.iter_windows():
            if text in flatten_fragments(self.render_window_fragments(window)):
                return window
        raise AssertionError(f"No window contains {text!r}")

    def render_window_fragments(self, window):
        content = window.content
        if hasattr(content, "text"):
            value = content.text() if callable(content.text) else content.text
            return normalize_fragments(value)
        if hasattr(content, "buffer"):
            return [("", content.buffer.text.ljust(window_width(window)))]
        if getattr(window, "char", None):
            return [("", window.char)]
        return [("", "")]

    def render_input_line(self) -> str:
        parts = []
        for window in self.input_row.children:
            parts.append(flatten_fragments(self.render_window_fragments(window)))
        return "".join(parts)

    def tree_lines(self) -> list[str]:
        return [flatten_fragments(line) for line in split_fragment_lines(self.render_window_fragments(self.tree_window))]

    def tree_fragment_lines(self) -> list[list[tuple[str, str]]]:
        return split_fragment_lines(self.render_window_fragments(self.tree_window))

    def action_lines(self) -> list[str]:
        return [flatten_fragments(line) for line in split_fragment_lines(self.render_window_fragments(self.actions_window))]

    def action_fragment_lines(self) -> list[list[tuple[str, str]]]:
        return split_fragment_lines(self.render_window_fragments(self.actions_window))

    def help_text(self) -> str:
        return flatten_fragments(self.render_window_fragments(self.help_window))

    def screen_lines(self) -> list[str]:
        return render_node_lines(self.app.layout.container, self.render_window_fragments)

    def screen_width(self) -> int:
        return max((len(line) for line in self.screen_lines()), default=0)

    def selected_tree_line_index(self) -> int:
        marker = MODULE.THEMES["rounded"].cursor_marker
        for index, line in enumerate(self.tree_lines()):
            if marker in line:
                return index
        raise AssertionError("No selected tree line found.")

    def selected_action_line_index(self) -> int:
        marker = MODULE.THEMES["rounded"].cursor_marker
        for index, line in enumerate(self.action_lines()):
            if marker in line:
                return index
        raise AssertionError("No selected action line found.")


def make_sample_remotes() -> list[MODULE.RemoteSelection]:
    return [
        MODULE.RemoteSelection(
            name="origin",
            fetch=MODULE.make_url_selection("fetch", "https://github.com/example/origin"),
            push=MODULE.make_url_selection("push", "https://github.com/example/origin"),
            push_is_explicit=False,
        ),
        MODULE.RemoteSelection(
            name="empty",
            fetch=MODULE.make_url_selection("fetch", "https://luckydonald@github.com/example/empty"),
            push=MODULE.make_url_selection("push", "https://luckydonald@github.com/example/empty"),
            push_is_explicit=False,
        ),
        MODULE.RemoteSelection(
            name="template",
            fetch=MODULE.make_url_selection("fetch", "../template"),
            push=MODULE.make_url_selection("push", "../template"),
            push_is_explicit=False,
        ),
        MODULE.RemoteSelection(
            name="clock",
            fetch=MODULE.make_url_selection("fetch", "https://luckydonald@github.com/example/clock.git"),
            push=MODULE.make_url_selection("push", "https://luckydonald@github.com/example/clock.git"),
            push_is_explicit=False,
        ),
    ]


def make_init_example_remotes() -> list[MODULE.RemoteSelection]:
    return [
        MODULE.RemoteSelection(
            name="origin",
            fetch=MODULE.make_url_selection("fetch", "https://github.com/luckydonald/base"),
            push=MODULE.make_url_selection("push", "https://github.com/luckydonald/base.git"),
            push_is_explicit=False,
        ),
        MODULE.RemoteSelection(
            name="empty",
            fetch=MODULE.make_url_selection("fetch", "https://someone@github.com/EmptyAAS/empty"),
            push=MODULE.make_url_selection("push", "https://luckydonald@github.com/EmptyAAS/empty"),
            push_is_explicit=False,
        ),
        MODULE.RemoteSelection(
            name="template",
            fetch=MODULE.make_url_selection("fetch", "../hoass_template"),
            push=MODULE.make_url_selection("push", "https://github.com/luckydonald/hoass_plugin-template.git"),
            push_is_explicit=False,
        ),
        MODULE.RemoteSelection(
            name="clock",
            fetch=MODULE.make_url_selection(
                "fetch",
                "https://luckydonald@github.com/luckydonald/hoass_calendar-alarm-clock.git",
            ),
            push=MODULE.make_url_selection(
                "push",
                "https://luckydonald@github.com/luckydonald/hoass_calendar-alarm-clock.git",
            ),
            push_is_explicit=False,
        ),
    ]


class TuiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.prompt_toolkit_modules = PromptToolkitTestModules()
        self.prompt_toolkit_modules.install()
        self.addCleanup(self.prompt_toolkit_modules.uninstall)
        self.set_terminal_size(120, 40)

    def build_ui(
        self,
        *,
        username: str = "luckydonald",
        theme: str = "rounded",
        remotes: list[MODULE.RemoteSelection] | None = None,
    ) -> TuiHarness:
        app = MODULE.run_tui(remotes or make_sample_remotes(), theme=MODULE.THEMES[theme], username=username)
        return TuiHarness(app)

    def set_terminal_size(self, columns: int, lines: int) -> None:
        original = MODULE.shutil.get_terminal_size
        MODULE.shutil.get_terminal_size = lambda fallback=(80, 24): os.terminal_size((columns, lines))
        self.addCleanup(setattr, MODULE.shutil, "get_terminal_size", original)

    def set_terminal_width(self, columns: int) -> None:
        self.set_terminal_size(columns, 40)

    def set_monotonic_time(self, value_ref: dict[str, float]) -> None:
        original = MODULE.time.monotonic
        MODULE.time.monotonic = lambda: value_ref["value"]
        self.addCleanup(setattr, MODULE.time, "monotonic", original)
