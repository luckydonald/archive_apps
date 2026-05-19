import unittest
from ai.scripts.tests.git_remote_fix_tui_test_support import (
    MODULE,
    TuiTestCase,
    flatten_fragments,
)


class TuiTddTests(TuiTestCase):
    def test_tdd_starts_with_name_field_focused_and_cursor_at_end(self) -> None:
        ui = self.build_ui()
        self.assertIs(ui.app.layout.current_window, ui.username_window)
        self.assertEqual(ui.username_window.content.buffer.cursor_position, len("luckydonald"))

    def test_tdd_name_field_down_arrow_moves_focus_to_multi_select(self) -> None:
        ui = self.build_ui()
        ui.press("down")
        self.assertIs(ui.app.layout.current_window, ui.tree_window)

    def test_tdd_multi_select_up_from_top_returns_to_name_field(self) -> None:
        ui = self.build_ui()
        ui.press("down")
        ui.press("up")
        self.assertIs(ui.app.layout.current_window, ui.username_window)

    def test_tdd_multi_select_up_moves_to_previous_item(self) -> None:
        ui = self.build_ui()
        ui.press("down")
        ui.press("down", times=2)
        self.assertEqual(ui.selected_tree_line_index(), 2)
        ui.press("up")
        self.assertEqual(ui.selected_tree_line_index(), 1)

    def test_tdd_multi_select_down_from_last_item_moves_to_check_all(self) -> None:
        ui = self.build_ui()
        ui.press("down")
        while ui.app.layout.current_window is ui.tree_window:
            ui.press("down")
        self.assertIs(ui.app.layout.current_window, ui.actions_window)
        self.assertEqual(ui.selected_action_line_index(), 0)

    def test_tdd_check_all_up_moves_back_to_last_multi_select_item(self) -> None:
        ui = self.build_ui()
        ui.press("down")
        while ui.app.layout.current_window is ui.tree_window:
            ui.press("down")
        ui.press("up")
        self.assertIs(ui.app.layout.current_window, ui.tree_window)

    def test_tdd_edit_screen_separates_scrollable_body_from_fixed_footer(self) -> None:
        ui = self.build_ui()
        self.assertEqual(
            len(ui.edit_container.children),
            2,
            "Expected a scrollable body and a fixed gray footer, not one flat edit stack.",
        )

    def test_tdd_input_line_matches_template_width_without_extra_trailing_space(self) -> None:
        ui = self.build_ui(theme="boxy")
        ui.press("down")
        self.assertEqual(
            ui.render_input_line(),
            "  │ ✎ │ luckydonald                              │",
        )

    def test_tdd_selected_indicator_uses_highlight_color(self) -> None:
        ui = self.build_ui()
        ui.press("down")
        first_tree_line = ui.tree_fragment_lines()[0]
        marker_fragment = next(fragment for fragment in first_tree_line if MODULE.THEMES["rounded"].cursor_marker in fragment[1])
        self.assertEqual(marker_fragment[0], "class:selected-marker")
        self.assertEqual(ui.app.style.style_rules["selected-marker"], "ansimagenta bold")

    def test_tdd_remote_name_uses_highlight_color(self) -> None:
        ui = self.build_ui()
        self.assertEqual(ui.app.style.style_rules["remote-name"], "ansimagenta bold")

    def test_tdd_active_checkbox_icons_use_highlight_color(self) -> None:
        ui = self.build_ui()
        self.assertEqual(ui.app.style.style_rules["icon-active"], "ansimagenta bold")

    def test_tdd_partial_and_disabled_icons_are_not_colored_when_unfocused(self) -> None:
        ui = self.build_ui()
        ui.press("down")
        lines = ui.tree_fragment_lines()
        partial_line = next(line for line in lines if "empty" in flatten_fragments(line))
        disabled_line = next(line for line in lines if "template" in flatten_fragments(line))
        partial_icon = next(fragment for fragment in partial_line if "◑" in fragment[1])
        disabled_icon = next(fragment for fragment in disabled_line if "◠" in fragment[1])
        self.assertEqual(partial_icon[0], "")
        self.assertEqual(disabled_icon[0], "")

    def test_tdd_parent_icons_are_not_colored_unless_directly_focused(self) -> None:
        ui = self.build_ui()
        ui.press("down")
        ui.press("down")
        origin_line = next(line for line in ui.tree_fragment_lines() if "origin" in flatten_fragments(line))
        origin_icon = next(fragment for fragment in origin_line if "◉" in fragment[1])
        self.assertEqual(origin_icon[0], "")

    def test_tdd_action_icons_are_not_colored_when_actions_are_unfocused(self) -> None:
        ui = self.build_ui()
        first_action_line = ui.action_fragment_lines()[0]
        action_icon = next(fragment for fragment in first_action_line if MODULE.THEMES["rounded"].select_all_icon in fragment[1])
        self.assertEqual(action_icon[0], "")

    def test_tdd_check_all_and_check_none_have_no_blank_line_between_them(self) -> None:
        ui = self.build_ui()
        self.assertEqual(
            ui.action_lines(),
            [
                "    ◉ Check all",
                "    ◎ Check none",
            ],
        )

    def test_tdd_help_footer_hides_action_shortcuts_in_text_field_and_uses_new_format(self) -> None:
        ui = self.build_ui()
        help_text = ui.help_text()
        self.assertIn("⇥⟯  focus", help_text)
        self.assertIn("↑|↓⟯  move", help_text)
        self.assertIn("←|→⟯  move cursor", help_text)
        self.assertIn("⏎⟯  next element/submit", help_text)
        self.assertIn("𝚛⟯  refresh", help_text)
        self.assertNotIn("𝚊⟯", help_text)
        self.assertNotIn("𝚗⟯", help_text)
        self.assertNotIn("𝚚|␛⟯", help_text)

    def test_tdd_help_footer_shows_arrow_keys_escape_symbol_and_monospace_hotkeys_in_multi_select(self) -> None:
        ui = self.build_ui()
        ui.press("down")
        help_text = ui.help_text()
        self.assertIn("⇥⟯  focus", help_text)
        self.assertIn("↑|↓⟯  move", help_text)
        self.assertIn("⏎⟯  next element/submit", help_text)
        self.assertIn("𝚊⟯  check all", help_text)
        self.assertIn("𝚗⟯  check none", help_text)
        self.assertIn("𝚛⟯  refresh", help_text)
        self.assertIn("𝚚|␛⟯  cancel", help_text)

    def test_tdd_refresh_hotkey_invalidates_the_app(self) -> None:
        ui = self.build_ui()
        self.assertEqual(ui.app.invalidate_count, 0)
        ui.press("r")
        self.assertEqual(ui.app.invalidate_count, 1)

    def test_tdd_refresh_hotkey_clears_the_screen_and_keeps_current_state(self) -> None:
        ui = self.build_ui()
        ui.press("down")
        ui.press("down", times=5)
        selected_index = ui.selected_tree_line_index()
        prior_clear_count = ui.app.renderer.clear_count
        prior_invalidate_count = ui.app.invalidate_count
        ui.press("r")
        self.assertEqual(ui.app.renderer.clear_count, prior_clear_count + 1)
        self.assertEqual(ui.app.invalidate_count, prior_invalidate_count + 1)
        self.assertIs(ui.app.layout.current_window, ui.tree_window)
        self.assertEqual(ui.selected_tree_line_index(), selected_index)

    def test_tdd_navigation_does_not_full_clear_on_every_input(self) -> None:
        ui = self.build_ui()
        self.assertEqual(ui.app.renderer.clear_count, 0)
        ui.press("down")
        ui.press("down")
        ui.press("down")
        while ui.app.layout.current_window is ui.tree_window:
            ui.press("down")
        ui.press("down")
        self.assertEqual(ui.app.renderer.clear_count, 0)
        self.assertEqual(ui.app.invalidate_count, 0)

    def test_tdd_second_level_active_icon_keeps_active_shape_when_suffix_turns_off(self) -> None:
        remotes = [
            MODULE.RemoteSelection(
                name="origin",
                fetch=MODULE.make_url_selection("fetch", "https://github.com/example/origin"),
                push=MODULE.make_url_selection("push", "https://github.com/example/origin"),
                push_is_explicit=False,
            )
        ]
        remotes[0].fetch.change_username = False
        remotes[0].fetch.add_git_suffix = False
        remotes[0].push.change_username = False
        remotes[0].push.add_git_suffix = False

        ui = self.build_ui(remotes=remotes)
        ui.press("down")
        ui.press("down", times=3)

        self.assertIn("○ push", ui.tree_lines()[3])
        self.assertIn("○ Add .git suffix", ui.tree_lines()[4])

        ui.press("down")
        ui.press("space")
        self.assertIn("◒ push", ui.tree_lines()[3])
        self.assertIn("● Add .git suffix", ui.tree_lines()[4])

        ui.press("up")
        ui.press("space")
        self.assertIn("● push", ui.tree_lines()[3])
        self.assertIn("● Add .git suffix", ui.tree_lines()[4])

        ui.press("down")
        ui.press("space")
        self.assertTrue(
            any(icon in ui.tree_lines()[3] for icon in ("◓ push", "● push")),
            ui.tree_lines()[3],
        )
        self.assertIn("○ Add .git suffix", ui.tree_lines()[4])

    def test_tdd_input_border_extends_by_two_characters(self) -> None:
        ui = self.build_ui(theme="rounded")
        self.assertEqual(
            flatten_fragments(ui.render_window_fragments(ui.input_container.children[0])),
            "  ╭───┬──────────────────────────────────────────╮",
        )
        self.assertEqual(
            flatten_fragments(ui.render_window_fragments(ui.input_container.children[2])),
            "  ╰━━━┷━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯",
        )

    def test_tdd_input_box_grows_to_terminal_width_minus_two(self) -> None:
        self.set_terminal_width(72)
        ui = self.build_ui(username="luckydonald-with-a-very-long-name-that-should-grow")
        top_line = flatten_fragments(ui.render_window_fragments(ui.input_container.children[0]))
        mid_line = ui.render_input_line()
        bottom_line = flatten_fragments(ui.render_window_fragments(ui.input_container.children[2]))
        self.assertEqual(len(top_line), 70)
        self.assertEqual(len(mid_line), 70)
        self.assertEqual(len(bottom_line), 70)

    def test_tdd_long_input_scrolls_with_leading_ellipsis_and_keeps_cursor_space(self) -> None:
        self.set_terminal_width(72)
        self.set_monotonic_time({"value": 0.10})
        ui = self.build_ui(username="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef")
        line = ui.render_input_line()
        self.assertIn("…", line)
        self.assertIn("▁ ", line)

    def test_tdd_long_input_scrolls_with_both_ellipses_when_cursor_is_in_the_middle(self) -> None:
        self.set_terminal_width(72)
        ui = self.build_ui(username="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef")
        ui.press("left", times=20)
        line = ui.render_input_line()
        self.assertGreaterEqual(line.count("…"), 2)

    def test_tdd_cursor_blinks_once_per_second_instead_of_staying_static(self) -> None:
        clock = {"value": 0.10}
        self.set_monotonic_time(clock)
        ui = self.build_ui(theme="boxy")

        blink_on_line = ui.render_input_line()
        blink_on_fragments = ui.render_window_fragments(ui.username_window)

        clock["value"] = 0.75
        blink_off_line = ui.render_input_line()
        blink_off_fragments = ui.render_window_fragments(ui.username_window)

        self.assertNotEqual(blink_on_line, blink_off_line)
        self.assertIn("▁", blink_on_line)
        self.assertNotIn("▁", blink_off_line)
        self.assertTrue(
            any(style == "class:selected-marker" for style, text in blink_off_fragments if text),
            blink_off_fragments,
        )

    def test_tdd_enter_in_name_field_moves_focus_to_multi_select(self) -> None:
        ui = self.build_ui()
        ui.press("enter")
        self.assertIs(ui.app.layout.current_window, ui.tree_window)

    def test_tdd_input_border_focus_uses_highlight_color(self) -> None:
        ui = self.build_ui()
        self.assertEqual(ui.app.style.style_rules["input-border-active"], "ansimagenta bold")

    def test_tdd_focused_input_uses_template_cursor_glyph(self) -> None:
        self.set_monotonic_time({"value": 0.10})
        ui = self.build_ui(theme="boxy")
        self.assertIn("▁", ui.render_input_line())

    def test_tdd_cursor_glyph_uses_highlight_color(self) -> None:
        self.set_monotonic_time({"value": 0.10})
        ui = self.build_ui(theme="boxy")
        input_fragments = ui.render_window_fragments(ui.username_window)
        cursor_fragments = [fragment for fragment in input_fragments if "▎" in fragment[1] or "▁" in fragment[1]]
        self.assertTrue(cursor_fragments, "Expected a visible cursor glyph fragment.")
        if cursor_fragments:
            self.assertEqual(cursor_fragments[0][0], "class:selected-marker")

    def test_tdd_tab_and_shift_tab_focus_switches_still_work(self) -> None:
        ui = self.build_ui()
        ui.press("tab")
        self.assertIs(ui.app.layout.current_window, ui.tree_window)
        ui.press("tab")
        self.assertIs(ui.app.layout.current_window, ui.actions_window)
        ui.press("s-tab")
        self.assertIs(ui.app.layout.current_window, ui.tree_window)

    def test_tdd_submit_button_exists_as_fourth_focus_group(self) -> None:
        ui = self.build_ui()
        ui.press("tab")
        ui.press("tab")
        ui.press("tab")
        self.assertIs(ui.app.layout.current_window, ui.submit_window)

    def test_tdd_submit_button_is_reachable_via_down_logic(self) -> None:
        ui = self.build_ui()
        ui.press("down")
        while ui.app.layout.current_window is ui.tree_window:
            ui.press("down")
        ui.press("down")
        ui.press("down")
        self.assertIs(ui.app.layout.current_window, ui.submit_window)

    def test_tdd_submit_button_focus_is_fully_highlighted(self) -> None:
        ui = self.build_ui()
        ui.press("tab")
        ui.press("tab")
        ui.press("tab")
        submit_fragments = ui.render_window_fragments(ui.submit_window)
        non_space_styles = {style for style, text in submit_fragments if text.strip()}
        self.assertEqual(non_space_styles, {"class:selected-marker"})

    def test_tdd_click_feedback_uses_mouse_support_and_025s_flash(self) -> None:
        ui = self.build_ui()
        self.assertTrue(ui.app.mouse_support)
        self.assertEqual(getattr(MODULE, "FLASH_FEEDBACK_SECONDS"), 0.25)

    def test_tdd_ctrl_c_cancels_like_q(self) -> None:
        ui = self.build_ui()
        ui.press("c-c")
        self.assertIsNone(ui.app.exit_result)

    def test_tdd_scroll_wheel_moves_like_up_and_down(self) -> None:
        ui = self.build_ui()
        ui.press("scrolldown")
        self.assertIs(ui.app.layout.current_window, ui.tree_window)
        ui.press("scrolldown")
        self.assertEqual(ui.selected_tree_line_index(), 1)
        ui.press("scrollup")
        self.assertEqual(ui.selected_tree_line_index(), 0)
        ui.press("scrollup")
        self.assertIs(ui.app.layout.current_window, ui.username_window)

    def test_tdd_checked_suffix_icon_is_not_colored_when_unfocused(self) -> None:
        ui = self.build_ui()
        ui.press("down")
        suffix_line = next(line for line in ui.tree_fragment_lines() if "Add .git suffix" in flatten_fragments(line))
        suffix_icon = next(fragment for fragment in suffix_line if "●" in fragment[1])
        self.assertEqual(suffix_icon[0], "")

    def test_tdd_tree_scrolls_to_keep_selected_row_centered_when_terminal_is_short(self) -> None:
        self.set_terminal_size(80, 20)
        ui = self.build_ui()
        ui.press("down", times=7)
        self.assertEqual(len(ui.tree_lines()), 7)
        self.assertIn(ui.selected_tree_line_index(), range(2, 5))
        self.assertTrue(any("empty" in line for line in ui.tree_lines()))


if __name__ == "__main__":
    unittest.main()
