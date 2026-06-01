from __future__ import annotations

from dataclasses import dataclass
import unittest

from git_remote_fix_tui_test_support import (
    MODULE,
    PROMPT_TOOLKIT_AVAILABLE,
    TuiTestCase,
    TuiHarness,
    make_init_example_remotes,
    make_sample_remotes,
)

try:
    import pyte
except ModuleNotFoundError:
    pyte = None


EXPECTED_SAMPLE_SCREEN_80X20 = [
    "Enter the git username to use:                                                  ",
    "  ╭───┬──────────────────────────────────────────╮                              ",
    "  │ ✎ │ luckydonald▁                             │                              ",
    "  ╰━━━┷━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯                              ",
    "                                                                                ",
    "Select the remote urls to change:                                               ",
    "     ◉ origin                                                                   ",
    "     ├─╴ ● fetch: https://github.com/example/origin                             ",
    "     │   ╰─╴ ● Add .git suffix                                                  ",
    "     ╰─╴ ● push : https://github.com/example/origin                             ",
    "         ╰─╴ ● Add .git suffix                                                  ",
    "                                                                                ",
    "     ◑ empty                                                                    ",
    "                                                                                ",
    "    ◉ Check all                                                                 ",
    "    ◎ Check none                                                                ",
    "                                                                                ",
    "                                                                                ",
    "    [ Submit → ]                                                                ",
    "⇥⟯  focus   ↑|↓⟯  move   ←|→⟯  move cursor   ⏎⟯  next element/submit   𝚛⟯  refre",
]

ANSI_RESET = "\x1b[0m"
ANSI_BOLD = "1"
ANSI_MAGENTA_BOLD = "1;35"
ANSI_MAGENTA_UNDERLINE = "4;35"


@dataclass(frozen=True)
class ExpectedCell:
    data: str
    fg: str = "default"
    bold: bool = False
    underscore: bool = False


def sgr(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}{ANSI_RESET}"


def style_line(line: str, *segments: tuple[int, int, str]) -> str:
    pieces: list[str] = []
    cursor = 0
    for start, end, code in segments:
        if start < cursor:
            raise AssertionError(f"Overlapping styled segments in {line!r}")
        pieces.append(line[cursor:start])
        pieces.append(sgr(code, line[start:end]))
        cursor = end
    pieces.append(line[cursor:])
    return "".join(pieces)


def parse_expected_cells(line: str) -> list[ExpectedCell]:
    cells: list[ExpectedCell] = []
    fg = "default"
    bold = False
    underscore = False
    index = 0
    while index < len(line):
        if line[index] == "\x1b":
            close = line.index("m", index)
            raw_codes = line[index + 2 : close]
            codes = raw_codes.split(";") if raw_codes else ["0"]
            for code in codes:
                if code == "0":
                    fg = "default"
                    bold = False
                    underscore = False
                elif code == "1":
                    bold = True
                elif code == "4":
                    underscore = True
                elif code == "22":
                    bold = False
                elif code == "24":
                    underscore = False
                elif code == "35":
                    fg = "magenta"
                elif code == "39":
                    fg = "default"
                else:
                    raise AssertionError(f"Unsupported ANSI SGR code {code!r} in {line!r}")
            index = close + 1
            continue
        cells.append(ExpectedCell(data=line[index], fg=fg, bold=bold, underscore=underscore))
        index += 1
    return cells


EXPECTED_SAMPLE_SCREEN_WITH_ANSI_ESCAPES_80X20 = [
    style_line(
        EXPECTED_SAMPLE_SCREEN_80X20[0],
        (0, len("Enter the git username to use:"), ANSI_BOLD),
    ),
    style_line(
        EXPECTED_SAMPLE_SCREEN_80X20[1],
        (
            EXPECTED_SAMPLE_SCREEN_80X20[1].index("╭"),
            EXPECTED_SAMPLE_SCREEN_80X20[1].index("╮") + 1,
            ANSI_MAGENTA_BOLD,
        ),
    ),
    style_line(
        EXPECTED_SAMPLE_SCREEN_80X20[2],
        (
            EXPECTED_SAMPLE_SCREEN_80X20[2].index("│ ✎ │"),
            EXPECTED_SAMPLE_SCREEN_80X20[2].index("│ ✎ │") + len("│ ✎ │"),
            ANSI_MAGENTA_BOLD,
        ),
        (
            EXPECTED_SAMPLE_SCREEN_80X20[2].index("▁"),
            EXPECTED_SAMPLE_SCREEN_80X20[2].index("▁") + 1,
            ANSI_MAGENTA_BOLD,
        ),
        (
            EXPECTED_SAMPLE_SCREEN_80X20[2].rindex("│"),
            EXPECTED_SAMPLE_SCREEN_80X20[2].rindex("│") + 1,
            ANSI_MAGENTA_BOLD,
        ),
    ),
    style_line(
        EXPECTED_SAMPLE_SCREEN_80X20[3],
        (
            EXPECTED_SAMPLE_SCREEN_80X20[3].index("╰"),
            EXPECTED_SAMPLE_SCREEN_80X20[3].index("╯") + 1,
            ANSI_MAGENTA_BOLD,
        ),
    ),
    EXPECTED_SAMPLE_SCREEN_80X20[4],
    style_line(
        EXPECTED_SAMPLE_SCREEN_80X20[5],
        (0, len("Select the remote urls to change:"), ANSI_BOLD),
    ),
    style_line(
        EXPECTED_SAMPLE_SCREEN_80X20[6],
        (
            EXPECTED_SAMPLE_SCREEN_80X20[6].index("◉"),
            EXPECTED_SAMPLE_SCREEN_80X20[6].index("◉") + 1,
            ANSI_MAGENTA_BOLD,
        ),
        (
            EXPECTED_SAMPLE_SCREEN_80X20[6].index("origin"),
            EXPECTED_SAMPLE_SCREEN_80X20[6].index("origin") + len("origin"),
            ANSI_MAGENTA_BOLD,
        ),
    ),
    style_line(
        EXPECTED_SAMPLE_SCREEN_80X20[7],
        (
            EXPECTED_SAMPLE_SCREEN_80X20[7].index("●"),
            EXPECTED_SAMPLE_SCREEN_80X20[7].index("●") + 1,
            ANSI_MAGENTA_BOLD,
        ),
        (
            EXPECTED_SAMPLE_SCREEN_80X20[7].index("https://github.com/example/origin"),
            EXPECTED_SAMPLE_SCREEN_80X20[7].index("https://github.com/example/origin")
            + len("https://github.com/example/origin"),
            ANSI_MAGENTA_UNDERLINE,
        ),
    ),
    style_line(
        EXPECTED_SAMPLE_SCREEN_80X20[8],
        (
            EXPECTED_SAMPLE_SCREEN_80X20[8].index("●"),
            EXPECTED_SAMPLE_SCREEN_80X20[8].index("●") + 1,
            ANSI_MAGENTA_BOLD,
        ),
    ),
    style_line(
        EXPECTED_SAMPLE_SCREEN_80X20[9],
        (
            EXPECTED_SAMPLE_SCREEN_80X20[9].index("●"),
            EXPECTED_SAMPLE_SCREEN_80X20[9].index("●") + 1,
            ANSI_MAGENTA_BOLD,
        ),
        (
            EXPECTED_SAMPLE_SCREEN_80X20[9].index("https://github.com/example/origin"),
            EXPECTED_SAMPLE_SCREEN_80X20[9].index("https://github.com/example/origin")
            + len("https://github.com/example/origin"),
            ANSI_MAGENTA_UNDERLINE,
        ),
    ),
    style_line(
        EXPECTED_SAMPLE_SCREEN_80X20[10],
        (
            EXPECTED_SAMPLE_SCREEN_80X20[10].index("●"),
            EXPECTED_SAMPLE_SCREEN_80X20[10].index("●") + 1,
            ANSI_MAGENTA_BOLD,
        ),
    ),
    EXPECTED_SAMPLE_SCREEN_80X20[11],
    EXPECTED_SAMPLE_SCREEN_80X20[12],
    EXPECTED_SAMPLE_SCREEN_80X20[13],
    EXPECTED_SAMPLE_SCREEN_80X20[14],
    EXPECTED_SAMPLE_SCREEN_80X20[15],
    EXPECTED_SAMPLE_SCREEN_80X20[16],
    EXPECTED_SAMPLE_SCREEN_80X20[17],
    EXPECTED_SAMPLE_SCREEN_80X20[18],
    style_line(
        EXPECTED_SAMPLE_SCREEN_80X20[19],
        (
            EXPECTED_SAMPLE_SCREEN_80X20[19].index("⇥⟯"),
            EXPECTED_SAMPLE_SCREEN_80X20[19].index("⇥⟯") + len("⇥⟯"),
            ANSI_MAGENTA_BOLD,
        ),
        (
            EXPECTED_SAMPLE_SCREEN_80X20[19].index("↑|↓⟯"),
            EXPECTED_SAMPLE_SCREEN_80X20[19].index("↑|↓⟯") + len("↑|↓⟯"),
            ANSI_MAGENTA_BOLD,
        ),
        (
            EXPECTED_SAMPLE_SCREEN_80X20[19].index("←|→⟯"),
            EXPECTED_SAMPLE_SCREEN_80X20[19].index("←|→⟯") + len("←|→⟯"),
            ANSI_MAGENTA_BOLD,
        ),
        (
            EXPECTED_SAMPLE_SCREEN_80X20[19].index("⏎⟯"),
            EXPECTED_SAMPLE_SCREEN_80X20[19].index("⏎⟯") + len("⏎⟯"),
            ANSI_MAGENTA_BOLD,
        ),
        (
            EXPECTED_SAMPLE_SCREEN_80X20[19].index("𝚛⟯"),
            EXPECTED_SAMPLE_SCREEN_80X20[19].index("𝚛⟯") + len("𝚛⟯"),
            ANSI_MAGENTA_BOLD,
        ),
    ),
]


class PyteTerminal:
    def __init__(self, *, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.flush_count = 0
        self.cursor_history: list[tuple[int, int, object]] = []
        self.screen = pyte.Screen(width, height)
        self.stream = pyte.Stream(self.screen)

    def seed(self, lines: list[str]) -> None:
        for row_index, line in enumerate(lines[: self.height], start=1):
            self.stream.feed(f"\x1b[{row_index};1H")
            self.stream.feed("\x1b[K")
            self.stream.feed(line)
        self.stream.feed("\x1b[1;1H")

    def apply_calls(self, calls: list[tuple]) -> None:
        for call in calls:
            self.apply_call(call)

    def apply_call(self, call: tuple) -> None:
        name = call[0]
        if name == "cursor_goto":
            self.stream.feed(f"\x1b[{max(1, call[1])};{max(1, call[2])}H")
            self.cursor_history.append((self.screen.cursor.x, self.screen.cursor.y, self.screen.cursor.attrs))
            return
        if name == "cursor_up":
            self.stream.feed(f"\x1b[{call[1]}A")
            return
        if name == "cursor_down":
            self.stream.feed(f"\x1b[{call[1]}B")
            return
        if name == "cursor_forward":
            self.stream.feed(f"\x1b[{call[1]}C")
            return
        if name == "cursor_backward":
            self.stream.feed(f"\x1b[{call[1]}D")
            return
        if name == "erase_end_of_line":
            self.stream.feed("\x1b[K")
            return
        if name in {"write", "write_raw"}:
            self.stream.feed(call[1])
            return
        if name == "flush":
            self.flush_count += 1
            return
        raise AssertionError(f"Unsupported terminal call: {call!r}")

    def display_lines(self, count: int) -> list[str]:
        return self.screen.display[:count]


@unittest.skipIf(pyte is None or not PROMPT_TOOLKIT_AVAILABLE, "prompt_toolkit and pyte are required for terminal redraw tests")
class TuiTerminalTests(TuiTestCase):
    def freeze_cursor_blink(self) -> None:
        self.set_monotonic_time({"value": 0.10})

    def build_terminal_from_lines(self, lines: list[str]) -> PyteTerminal:
        width = max(MODULE.shutil.get_terminal_size(fallback=(80, 24)).columns, 1)
        height = MODULE.shutil.get_terminal_size(fallback=(80, 24)).lines
        terminal = PyteTerminal(width=width, height=height)
        terminal.seed(lines)
        return terminal

    def build_terminal(self, ui: TuiHarness) -> PyteTerminal:
        return self.build_terminal_from_lines(ui.screen_lines())

    def merge_screen_after_keys(self, ui: TuiHarness, keys: list[str], *, initial_lines: list[str] | None = None) -> list[str]:
        lines = initial_lines or ui.screen_lines()
        terminal = self.build_terminal_from_lines(lines)
        for key in keys:
            ui.app.renderer.output.clear()
            ui.press(key)
            terminal.apply_calls(ui.app.renderer.output.calls)
        return terminal.display_lines(len(lines))

    def padded_screen_lines(self, ui: TuiHarness) -> list[str]:
        width = max(MODULE.shutil.get_terminal_size(fallback=(80, 24)).columns, 1)
        return [line.ljust(width)[:width] for line in ui.screen_lines()]

    def assert_terminal_matches_ansi_expected_screen(
        self,
        terminal: PyteTerminal,
        expected_ansi_lines: list[str],
        expected_plain_lines: list[str],
    ) -> None:
        self.assertEqual(terminal.display_lines(len(expected_plain_lines)), expected_plain_lines)
        for row_index, expected_line in enumerate(expected_ansi_lines):
            expected_cells = parse_expected_cells(expected_line)
            self.assertEqual(len(expected_cells), len(expected_plain_lines[row_index]))
            for column_index, expected_cell in enumerate(expected_cells):
                actual_cell = terminal.screen.buffer[row_index][column_index]
                with self.subTest(row=row_index + 1, column=column_index + 1):
                    self.assertEqual(actual_cell.data, expected_cell.data)
                    self.assertEqual(actual_cell.fg, expected_cell.fg)
                    self.assertEqual(actual_cell.bold, expected_cell.bold)
                    self.assertEqual(actual_cell.underscore, expected_cell.underscore)

    def test_tdd_round4_full_down_then_back_up_matches_hardcoded_80x20_screen(self) -> None:
        self.set_terminal_size(80, 20)
        self.freeze_cursor_blink()
        ui = self.build_ui(remotes=make_sample_remotes())
        selectable_tree_rows = sum(1 for line in ui.tree_lines() if line)
        down_keys = ["down"]
        down_keys.extend(["down"] * max(0, selectable_tree_rows - 1))
        down_keys.extend(["down", "down"])
        up_keys = ["up"] * len(down_keys)

        self.assertEqual(
            self.merge_screen_after_keys(ui, down_keys + up_keys, initial_lines=EXPECTED_SAMPLE_SCREEN_80X20),
            EXPECTED_SAMPLE_SCREEN_80X20,
        )

    def test_tdd_round4_hardcoded_ansi_screen_matches_plain_text_and_styles_in_pyte(self) -> None:
        self.set_terminal_size(80, 20)
        terminal = self.build_terminal_from_lines(EXPECTED_SAMPLE_SCREEN_WITH_ANSI_ESCAPES_80X20)
        self.assert_terminal_matches_ansi_expected_screen(
            terminal,
            EXPECTED_SAMPLE_SCREEN_WITH_ANSI_ESCAPES_80X20,
            EXPECTED_SAMPLE_SCREEN_80X20,
        )

    def test_tdd_round4_text_field_two_left_then_back_matches_hardcoded_80x20_screen(self) -> None:
        self.set_terminal_size(80, 20)
        self.freeze_cursor_blink()
        ui = self.build_ui(remotes=make_sample_remotes())

        self.assertEqual(
            self.merge_screen_after_keys(
                ui,
                ["left", "left", "right", "right"],
                initial_lines=EXPECTED_SAMPLE_SCREEN_80X20,
            ),
            EXPECTED_SAMPLE_SCREEN_80X20,
        )

    def test_tdd_round4_text_field_three_left_then_four_right_matches_hardcoded_80x20_screen(self) -> None:
        self.set_terminal_size(80, 20)
        self.freeze_cursor_blink()
        ui = self.build_ui(remotes=make_sample_remotes())
        terminal = self.build_terminal_from_lines(EXPECTED_SAMPLE_SCREEN_80X20)

        self.assertEqual(
            terminal.display_lines(len(EXPECTED_SAMPLE_SCREEN_80X20)),
            EXPECTED_SAMPLE_SCREEN_80X20,
        )

        for key in ["left", "left", "left"]:
            ui.app.renderer.output.clear()
            ui.press(key)
            terminal.apply_calls(ui.app.renderer.output.calls)

        self.assertNotEqual(
            terminal.display_lines(len(EXPECTED_SAMPLE_SCREEN_80X20)),
            EXPECTED_SAMPLE_SCREEN_80X20,
        )

        for key in ["right", "right", "right", "right"]:
            ui.app.renderer.output.clear()
            ui.press(key)
            terminal.apply_calls(ui.app.renderer.output.calls)

        self.assertEqual(
            terminal.display_lines(len(EXPECTED_SAMPLE_SCREEN_80X20)),
            EXPECTED_SAMPLE_SCREEN_80X20,
        )

    def test_tdd_local_redraw_rewrites_changed_rows_in_place(self) -> None:
        ui = self.build_ui()
        terminal = self.build_terminal(ui)
        ui.app.renderer.output.clear()
        ui.press("down")
        terminal.apply_calls(ui.app.renderer.output.calls)
        self.assertEqual(terminal.display_lines(len(ui.screen_lines())), self.padded_screen_lines(ui))
        self.assertEqual(terminal.flush_count, 1)
        self.assertTrue(any(cursor_x == 0 and cursor_y == 1 for cursor_x, cursor_y, _ in terminal.cursor_history))

    def test_tdd_blink_redraw_writes_text_row_without_extra_column_shift(self) -> None:
        self.set_monotonic_time({"value": 0.75})
        ui = self.build_ui(theme="boxy")
        terminal = self.build_terminal(ui)
        ui.app.renderer.output.clear()
        ui.press("left", times=4)
        terminal.apply_calls(ui.app.renderer.output.calls)
        self.assertTrue(
            any("  │ ✎ │ luckydonald                              │" in line for line in terminal.display_lines(len(ui.screen_lines())))
        )

    def test_tdd_round4_single_down_and_up_preserve_merged_screen(self) -> None:
        self.freeze_cursor_blink()
        scenarios = [
            ("sample", make_sample_remotes()),
            ("init", make_init_example_remotes()),
        ]
        for height in (20, 28, 40):
            for label, remotes in scenarios:
                with self.subTest(height=height, scenario=label):
                    self.set_terminal_size(120, height)
                    ui = self.build_ui(remotes=remotes)
                    expected = self.padded_screen_lines(ui)
                    merged = self.merge_screen_after_keys(ui, ["down", "up"])
                    self.assertEqual(merged, expected)

    def test_tdd_round4_two_down_and_up_cycles_preserve_merged_screen(self) -> None:
        self.freeze_cursor_blink()
        scenarios = [
            ("sample", make_sample_remotes()),
            ("init", make_init_example_remotes()),
        ]
        for height in (20, 28, 40):
            for label, remotes in scenarios:
                with self.subTest(height=height, scenario=label):
                    self.set_terminal_size(120, height)
                    ui = self.build_ui(remotes=remotes)
                    expected = self.padded_screen_lines(ui)
                    merged = self.merge_screen_after_keys(ui, ["down", "up", "down", "up"])
                    self.assertEqual(merged, expected)

    def test_tdd_round4_full_down_and_up_path_preserve_merged_screen(self) -> None:
        self.freeze_cursor_blink()
        scenarios = [
            ("sample", make_sample_remotes()),
            ("init", make_init_example_remotes()),
        ]
        for height in (20, 28, 40):
            for label, remotes in scenarios:
                with self.subTest(height=height, scenario=label):
                    self.set_terminal_size(120, height)
                    ui = self.build_ui(remotes=remotes)
                    selectable_tree_rows = sum(1 for line in ui.tree_lines() if line)
                    down_keys = ["down"]
                    down_keys.extend(["down"] * max(0, selectable_tree_rows - 1))
                    down_keys.extend(["down", "down"])
                    up_keys = ["up"] * len(down_keys)
                    expected = self.padded_screen_lines(ui)
                    merged = self.merge_screen_after_keys(ui, down_keys + up_keys)
                    self.assertEqual(merged, expected)

    def test_tdd_round4_single_down_matches_direct_rendered_screen(self) -> None:
        self.freeze_cursor_blink()
        self.set_terminal_size(120, 28)
        ui = self.build_ui(remotes=make_init_example_remotes())
        merged = self.merge_screen_after_keys(ui, ["down"])
        self.assertEqual(merged, self.padded_screen_lines(ui))

    def test_tdd_round4_single_down_keeps_first_remote_on_its_own_row(self) -> None:
        self.freeze_cursor_blink()
        self.set_terminal_size(120, 28)
        ui = self.build_ui(remotes=make_init_example_remotes())
        merged = self.merge_screen_after_keys(ui, ["down"])
        expected = self.padded_screen_lines(ui)
        self.assertEqual(merged[5:11], expected[5:11])

    def test_tdd_round4_single_down_keeps_heading_and_input_rows_in_place(self) -> None:
        self.freeze_cursor_blink()
        self.set_terminal_size(120, 28)
        ui = self.build_ui(remotes=make_init_example_remotes())
        merged = self.merge_screen_after_keys(ui, ["down"])
        expected = self.padded_screen_lines(ui)
        self.assertEqual(merged[0:5], expected[0:5])

    def test_tdd_round4_local_redraw_targets_terminal_column_one(self) -> None:
        self.set_terminal_size(120, 28)
        ui = self.build_ui(remotes=make_init_example_remotes())
        terminal = self.build_terminal(ui)
        ui.app.renderer.output.clear()
        ui.press("down")
        terminal.apply_calls(ui.app.renderer.output.calls)
        self.assertTrue(terminal.cursor_history)
        self.assertTrue(all(cursor_x == 0 for cursor_x, _, _ in terminal.cursor_history), terminal.cursor_history)


if __name__ == "__main__":
    unittest.main()
