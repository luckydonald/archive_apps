[pyte](https://pyte.readthedocs.io/en/latest/index.html)
========================================================

# API reference
## pyte.streams[¶](#pyte-streams "Permalink to this headline")

This module provides three stream implementations with different features; for starters, here’s a quick example of how streams are typically used:

```python
import pyte
screen = pyte.Screen(80, 24)
stream = pyte.Stream(screen)
stream.feed("\[5B")  # Move the cursor down 5 rows.
assert(screen.cursor.y == 5)
```

<table><colgroup><col> <col></colgroup><tbody><tr><th>copyright:</th><td><ol start="3"><li>2011-2012 by Selectel.</li></ol></td></tr><tr><th>copyright:</th><td><p>(c) 2012-2017 by pyte authors and contributors, see AUTHORS for details.</p></td></tr><tr><th>license:</th><td><p>LGPL, see LICENSE for more details.</p></td></tr></tbody></table>

### pyte.Stream[¶](#pyte-stream "Permalink to this headline")

_class_ `pyte`.`Stream`(_screen=None_, _strict=True_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/streams.py#L35-L387)[¶](#pyte.Stream "Permalink to this definition")

A stream is a state machine that parses a stream of bytes and dispatches events based on what it sees.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><ul><li><strong>screen</strong> (<a href="#pyte.screens.Screen" title="pyte.screens.Screen"><em>pyte.screens.Screen</em></a>) – a screen to dispatch events to.</li><li><strong>strict</strong> (<a href="https://docs.python.org/3/library/functions.html#bool" title="(in Python v3.7)"><em>bool</em></a>) – check if a given screen implements all required events.</li></ul></td></tr></tbody></table>

Note

Stream only accepts text as input, but if for some reason you need to feed it with bytes, consider using `ByteStream` instead.

See also

[man console\_codes](http://linux.die.net/man/4/console_codes)

For details on console codes listed bellow in `basic`, [`escape`](#module-pyte.escape "pyte.escape"), `csi`, `sharp`.

### pyte.ByteStream[¶](#pyte-bytestream "Permalink to this headline")

_class_ `pyte`.`ByteStream`(_\*args_, _\*\*kwargs_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/streams.py#L391-L420)[¶](#pyte.ByteStream "Permalink to this definition")

A stream which takes bytes as input.

Bytes are decoded to text using either UTF-8 (default) or the encoding selected via `select_other_charset()`.

`use_utf8`[¶](#pyte.ByteStream.use_utf8 "Permalink to this definition")

Assume the input to `feed()` is encoded using UTF-8. Defaults to `True`.

## pyte.screens[¶](#pyte-screens "Permalink to this headline")

This module provides classes for terminal screens, currently it contains three screens with different features:

*   [`Screen`](#pyte.screens.Screen "pyte.screens.Screen") – base screen implementation, which handles all the core escape sequences, recognized by `Stream`.
*   If you need a screen to keep track of the changed lines (which you probably do need) – use [`DiffScreen`](#pyte.screens.DiffScreen "pyte.screens.DiffScreen").
*   If you also want a screen to collect history and allow pagination – `pyte.screen.HistoryScreen` is here for ya ;)

Note

It would be nice to split those features into mixin classes, rather than subclasses, but it’s not obvious how to do – feel free to submit a pull request.

<table><colgroup><col> <col></colgroup><tbody><tr><th>copyright:</th><td><ol start="3"><li>2011-2012 by Selectel.</li></ol></td></tr><tr><th>copyright:</th><td><p>(c) 2012-2017 by pyte authors and contributors, see AUTHORS for details.</p></td></tr><tr><th>license:</th><td><p>LGPL, see LICENSE for more details.</p></td></tr></tbody></table>

### pyte.screens.Screen[¶](#pyte-screens-screen "Permalink to this headline")

_class_ `pyte.screens`.`Cursor`(_x_, _y_, _attrs=Char(data=' '_, _fg='default'_, _bg='default'_, _bold=False_, _italics=False_, _underscore=False_, _strikethrough=False_, _reverse=False_, _blink=False)_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L110-L125)[¶](#pyte.screens.Cursor "Permalink to this definition")

Screen cursor.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><ul><li><strong>x</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – 0-based horizontal cursor position.</li><li><strong>y</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – 0-based vertical cursor position.</li><li><strong>attrs</strong> (<a href="#pyte.screens.Char" title="pyte.screens.Char"><em>pyte.screens.Char</em></a>) – cursor attributes (see <a href="#pyte.screens.Screen.select_graphic_rendition" title="pyte.screens.Screen.select_graphic_rendition"><code><span>select_graphic_rendition()</span></code></a> for details).</li></ul></td></tr></tbody></table>

_class_ `pyte.screens`.`Char`[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L71-L107)[¶](#pyte.screens.Char "Permalink to this definition")

A single styled on-screen character.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><ul><li><strong>data</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#str" title="(in Python v3.7)"><em>str</em></a>) – unicode character. Invariant: <code><span>len(data)</span> <span>==</span> <span>1</span></code>.</li><li><strong>fg</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#str" title="(in Python v3.7)"><em>str</em></a>) – foreground colour. Defaults to <code><span>"default"</span></code>.</li><li><strong>bg</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#str" title="(in Python v3.7)"><em>str</em></a>) – background colour. Defaults to <code><span>"default"</span></code>.</li><li><strong>bold</strong> (<a href="https://docs.python.org/3/library/functions.html#bool" title="(in Python v3.7)"><em>bool</em></a>) – flag for rendering the character using bold font. Defaults to <code><span>False</span></code>.</li><li><strong>italics</strong> (<a href="https://docs.python.org/3/library/functions.html#bool" title="(in Python v3.7)"><em>bool</em></a>) – flag for rendering the character using italic font. Defaults to <code><span>False</span></code>.</li><li><strong>underscore</strong> (<a href="https://docs.python.org/3/library/functions.html#bool" title="(in Python v3.7)"><em>bool</em></a>) – flag for rendering the character underlined. Defaults to <code><span>False</span></code>.</li><li><strong>strikethrough</strong> (<a href="https://docs.python.org/3/library/functions.html#bool" title="(in Python v3.7)"><em>bool</em></a>) – flag for rendering the character with a strike-through line. Defaults to <code><span>False</span></code>.</li><li><strong>reverse</strong> (<a href="https://docs.python.org/3/library/functions.html#bool" title="(in Python v3.7)"><em>bool</em></a>) – flag for swapping foreground and background colours during rendering. Defaults to <code><span>False</span></code>.</li><li><strong>blink</strong> (<a href="https://docs.python.org/3/library/functions.html#bool" title="(in Python v3.7)"><em>bool</em></a>) – flag for rendering the character blinked. Defaults to <code><span>False</span></code>.</li></ul></td></tr></tbody></table>

_class_ `pyte.screens`.`Screen`(_columns_, _lines_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L147-L1068)[¶](#pyte.screens.Screen "Permalink to this definition")

A screen is an in-memory matrix of characters that represents the screen display of the terminal. It can be instantiated on its own and given explicit commands, or it can be attached to a stream and will respond to events.

`buffer`[¶](#pyte.screens.Screen.buffer "Permalink to this definition")

A sparse `lines x columns` [`Char`](#pyte.screens.Char "pyte.screens.Char") matrix.

`dirty`[¶](#pyte.screens.Screen.dirty "Permalink to this definition")

A set of line numbers, which should be re-drawn. The user is responsible for clearing this set when changes have been applied.

\>>> screen \= Screen(80, 24)
\>>> screen.dirty.clear()
\>>> screen.draw("!")
\>>> list(screen.dirty)
\[0\]

New in version 0.7.0.

`cursor`[¶](#pyte.screens.Screen.cursor "Permalink to this definition")

Reference to the [`Cursor`](#pyte.screens.Cursor "pyte.screens.Cursor") object, holding cursor position and attributes.

`margins`[¶](#pyte.screens.Screen.margins "Permalink to this definition")

Margins determine which screen lines move during scrolling (see [`index()`](#pyte.screens.Screen.index "pyte.screens.Screen.index") and [`reverse_index()`](#pyte.screens.Screen.reverse_index "pyte.screens.Screen.reverse_index")). Characters added outside the scrolling region do not make the screen to scroll.

The value is `None` if margins are set to screen boundaries, otherwise – a pair 0-based top and bottom line indices.

`charset`[¶](#pyte.screens.Screen.charset "Permalink to this definition")

Current charset number; can be either `0` or `1` for G0 and G1 respectively, note that G0 is activated by default.

Note

According to `ECMA-48` standard, **lines and columns are 1-indexed**, so, for instance `ESC [ 10;10 f` really means – move cursor to position (9, 9) in the display matrix.

Changed in version 0.4.7.

Warning

[`LNM`](#pyte.modes.LNM "pyte.modes.LNM") is reset by default, to match VT220 specification. Unfortunatelly this makes `pyte` fail `vttest` for cursor movement.

Changed in version 0.4.8.

Warning

If DECAWM mode is set than a cursor will be wrapped to the **beginning** of the next line, which is the behaviour described in `man console_codes`.

`default_char`[¶](#pyte.screens.Screen.default_char "Permalink to this definition")

An empty character with default foreground and background colors.

`display`[¶](#pyte.screens.Screen.display "Permalink to this definition")

A `list()` of screen lines as unicode strings.

`reset`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L251-L289)[¶](#pyte.screens.Screen.reset "Permalink to this definition")

Reset the terminal to its initial state.

*   Scrolling margins are reset to screen boundaries.
*   Cursor is moved to home location – `(0, 0)` and its attributes are set to defaults (see [`default_char`](#pyte.screens.Screen.default_char "pyte.screens.Screen.default_char")).
*   Screen is cleared – each character is reset to [`default_char`](#pyte.screens.Screen.default_char "pyte.screens.Screen.default_char").
*   Tabstops are reset to “every eight columns”.
*   All lines are marked as [`dirty`](#pyte.screens.Screen.dirty "pyte.screens.Screen.dirty").

Note

Neither VT220 nor VT102 manuals mention that terminal modes and tabstops should be reset as well, thanks to _xterm_ – we now know that.

`resize`(_lines=None_, _columns=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L291-L330)[¶](#pyte.screens.Screen.resize "Permalink to this definition")

Resize the screen to the given size.

If the requested screen size has more lines than the existing screen, lines will be added at the bottom. If the requested size has less lines than the existing screen lines will be clipped at the top of the screen. Similarly, if the existing screen has less columns than the requested screen, columns will be added at the right, and if it has more – columns will be clipped at the right.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><ul><li><strong>lines</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – number of lines in the new screen.</li><li><strong>columns</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – number of columns in the new screen.</li></ul></td></tr></tbody></table>

Changed in version 0.7.0: If the requested screen size is identical to the current screen size, the method does nothing.

`set_margins`(_top=None_, _bottom=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L332-L365)[¶](#pyte.screens.Screen.set_margins "Permalink to this definition")

Select top and bottom margins for the scrolling region.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><ul><li><strong>top</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – the smallest line number that is scrolled.</li><li><strong>bottom</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – the biggest line number that is scrolled.</li></ul></td></tr></tbody></table>

`set_mode`(_\*modes_, _\*\*kwargs_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L367-L405)[¶](#pyte.screens.Screen.set_mode "Permalink to this definition")

Set (enable) a given list of modes.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>modes</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#list" title="(in Python v3.7)"><em>list</em></a>) – modes to set, where each mode is a constant from <a href="#module-pyte.modes" title="pyte.modes"><code><span>pyte.modes</span></code></a>.</td></tr></tbody></table>

`reset_mode`(_\*modes_, _\*\*kwargs_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L407-L443)[¶](#pyte.screens.Screen.reset_mode "Permalink to this definition")

Reset (disable) a given list of modes.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>modes</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#list" title="(in Python v3.7)"><em>list</em></a>) – modes to reset – hopefully, each mode is a constant from <a href="#module-pyte.modes" title="pyte.modes"><code><span>pyte.modes</span></code></a>.</td></tr></tbody></table>

`define_charset`(_code_, _mode_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L445-L459)[¶](#pyte.screens.Screen.define_charset "Permalink to this definition")

Define `G0` or `G1` charset.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><ul><li><strong>code</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#str" title="(in Python v3.7)"><em>str</em></a>) – character set code, should be a character from <code><span>"B0UK"</span></code>, otherwise ignored.</li><li><strong>mode</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#str" title="(in Python v3.7)"><em>str</em></a>) – if <code><span>"("</span></code> <code><span>G0</span></code> charset is defined, if <code><span>")"</span></code> – we operate on <code><span>G1</span></code>.</li></ul></td></tr></tbody></table>

Warning

User-defined charsets are currently not supported.

`shift_in`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L461-L463)[¶](#pyte.screens.Screen.shift_in "Permalink to this definition")

Select `G0` character set.

`shift_out`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L465-L467)[¶](#pyte.screens.Screen.shift_out "Permalink to this definition")

Select `G1` character set.

`draw`(_data_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L469-L534)[¶](#pyte.screens.Screen.draw "Permalink to this definition")

Display decoded characters at the current cursor position and advances the cursor if [`DECAWM`](#pyte.modes.DECAWM "pyte.modes.DECAWM") is set.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>data</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#str" title="(in Python v3.7)"><em>str</em></a>) – text to display.</td></tr></tbody></table>

Changed in version 0.5.0: Character width is taken into account. Specifically, zero-width and unprintable characters do not affect screen state. Full-width characters are rendered into two consecutive character containers.

`set_title`(_param_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L536-L541)[¶](#pyte.screens.Screen.set_title "Permalink to this definition")

Set terminal title.

Note

This is an XTerm extension supported by the Linux terminal.

`set_icon_name`(_param_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L543-L548)[¶](#pyte.screens.Screen.set_icon_name "Permalink to this definition")

Set icon name.

Note

This is an XTerm extension supported by the Linux terminal.

`carriage_return`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L550-L552)[¶](#pyte.screens.Screen.carriage_return "Permalink to this definition")

Move the cursor to the beginning of the current line.

`index`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L554-L566)[¶](#pyte.screens.Screen.index "Permalink to this definition")

Move the cursor down one line in the same column. If the cursor is at the last line, create a new line at the bottom.

`reverse_index`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L568-L580)[¶](#pyte.screens.Screen.reverse_index "Permalink to this definition")

Move the cursor up one line in the same column. If the cursor is at the first line, create a new line at the top.

`linefeed`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L582-L589)[¶](#pyte.screens.Screen.linefeed "Permalink to this definition")

Perform an index and, if [`LNM`](#pyte.modes.LNM "pyte.modes.LNM") is set, a carriage return.

`tab`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L591-L602)[¶](#pyte.screens.Screen.tab "Permalink to this definition")

Move to the next tab space, or the end of the screen if there aren’t anymore left.

`backspace`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L604-L608)[¶](#pyte.screens.Screen.backspace "Permalink to this definition")

Move cursor to the left one or keep it in its position if it’s at the beginning of the line already.

`save_cursor`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L610-L617)[¶](#pyte.screens.Screen.save_cursor "Permalink to this definition")

Push the current cursor position onto the stack.

`restore_cursor`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L619-L642)[¶](#pyte.screens.Screen.restore_cursor "Permalink to this definition")

Set the current cursor position to whatever cursor is on top of the stack.

`insert_lines`(_count=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L644-L662)[¶](#pyte.screens.Screen.insert_lines "Permalink to this definition")

Insert the indicated # of lines at line with cursor. Lines displayed **at** and below the cursor move down. Lines moved past the bottom margin are lost.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>count</strong> – number of lines to insert.</td></tr></tbody></table>

`delete_lines`(_count=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L664-L685)[¶](#pyte.screens.Screen.delete_lines "Permalink to this definition")

Delete the indicated # of lines, starting at line with cursor. As lines are deleted, lines displayed below cursor move up. Lines added to bottom of screen have spaces with same character attributes as last line moved up.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>count</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – number of lines to delete.</td></tr></tbody></table>

`insert_characters`(_count=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L687-L702)[¶](#pyte.screens.Screen.insert_characters "Permalink to this definition")

Insert the indicated # of blank characters at the cursor position. The cursor does not move and remains at the beginning of the inserted blank characters. Data on the line is shifted forward.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>count</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – number of characters to insert.</td></tr></tbody></table>

`delete_characters`(_count=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L704-L720)[¶](#pyte.screens.Screen.delete_characters "Permalink to this definition")

Delete the indicated # of characters, starting with the character at cursor position. When a character is deleted, all characters to the right of cursor move left. Character attributes move with the characters.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>count</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – number of characters to delete.</td></tr></tbody></table>

`erase_characters`(_count=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L722-L742)[¶](#pyte.screens.Screen.erase_characters "Permalink to this definition")

Erase the indicated # of characters, starting with the character at cursor position. Character attributes are set cursor attributes. The cursor remains in the same position.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>count</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – number of characters to erase.</td></tr></tbody></table>

Note

Using cursor attributes for character attributes may seem illogical, but if recall that a terminal emulator emulates a type writer, it starts to make sense. The only way a type writer could erase a character is by typing over it.

`erase_in_line`(_how=0_, _private=False_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L744-L769)[¶](#pyte.screens.Screen.erase_in_line "Permalink to this definition")

Erase a line in a specific way.

Character attributes are set to cursor attributes.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><ul><li><strong>how</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) –<p>defines the way the line should be erased in:</p><ul><li><code><span>0</span></code> – Erases from cursor to end of line, including cursor position.</li><li><code><span>1</span></code> – Erases from beginning of line to cursor, including cursor position.</li><li><code><span>2</span></code> – Erases complete line.</li></ul></li><li><strong>private</strong> (<a href="https://docs.python.org/3/library/functions.html#bool" title="(in Python v3.7)"><em>bool</em></a>) – when <code><span>True</span></code> only characters marked as eraseable are affected <strong>not implemented</strong>.</li></ul></td></tr></tbody></table>

`erase_in_display`(_how=0_, _\*args_, _\*\*kwargs_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L771-L808)[¶](#pyte.screens.Screen.erase_in_display "Permalink to this definition")

Erases display in a specific way.

Character attributes are set to cursor attributes.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><ul><li><strong>how</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) –<p>defines the way the line should be erased in:</p><ul><li><code><span>0</span></code> – Erases from cursor to end of screen, including cursor position.</li><li><code><span>1</span></code> – Erases from beginning of screen to cursor, including cursor position.</li><li><code><span>2</span></code> and <code><span>3</span></code> – Erases complete display. All lines are erased and changed to single-width. Cursor does not move.</li></ul></li><li><strong>private</strong> (<a href="https://docs.python.org/3/library/functions.html#bool" title="(in Python v3.7)"><em>bool</em></a>) – when <code><span>True</span></code> only characters marked as eraseable are affected <strong>not implemented</strong>.</li></ul></td></tr></tbody></table>

Changed in version 0.8.1: The method accepts any number of positional arguments as some `clear` implementations include a `;` after the first parameter causing the stream to assume a `0` second parameter.

`set_tab_stop`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L810-L812)[¶](#pyte.screens.Screen.set_tab_stop "Permalink to this definition")

Set a horizontal tab stop at cursor position.

`clear_tab_stop`(_how=0_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L814-L828)[¶](#pyte.screens.Screen.clear_tab_stop "Permalink to this definition")

Clear a horizontal tab stop.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>how</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) –<p>defines a way the tab stop should be cleared:</p><ul><li><code><span>0</span></code> or nothing – Clears a horizontal tab stop at cursor position.</li><li><code><span>3</span></code> – Clears all horizontal tab stops.</li></ul></td></tr></tbody></table>

`ensure_hbounds`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L830-L832)[¶](#pyte.screens.Screen.ensure_hbounds "Permalink to this definition")

Ensure the cursor is within horizontal screen bounds.

`ensure_vbounds`(_use\_margins=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L834-L847)[¶](#pyte.screens.Screen.ensure_vbounds "Permalink to this definition")

Ensure the cursor is within vertical screen bounds.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>use_margins</strong> (<a href="https://docs.python.org/3/library/functions.html#bool" title="(in Python v3.7)"><em>bool</em></a>) – when <code><span>True</span></code> or when <a href="#pyte.modes.DECOM" title="pyte.modes.DECOM"><code><span>DECOM</span></code></a> is set, cursor is bounded by top and and bottom margins, instead of <code><span>[0;</span> <span>lines</span> <span>-</span> <span>1]</span></code>.</td></tr></tbody></table>

`cursor_up`(_count=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L849-L856)[¶](#pyte.screens.Screen.cursor_up "Permalink to this definition")

Move cursor up the indicated # of lines in same column. Cursor stops at top margin.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>count</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – number of lines to skip.</td></tr></tbody></table>

`cursor_up1`(_count=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L858-L865)[¶](#pyte.screens.Screen.cursor_up1 "Permalink to this definition")

Move cursor up the indicated # of lines to column 1. Cursor stops at bottom margin.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>count</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – number of lines to skip.</td></tr></tbody></table>

`cursor_down`(_count=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L867-L874)[¶](#pyte.screens.Screen.cursor_down "Permalink to this definition")

Move cursor down the indicated # of lines in same column. Cursor stops at bottom margin.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>count</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – number of lines to skip.</td></tr></tbody></table>

`cursor_down1`(_count=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L876-L883)[¶](#pyte.screens.Screen.cursor_down1 "Permalink to this definition")

Move cursor down the indicated # of lines to column 1. Cursor stops at bottom margin.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>count</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – number of lines to skip.</td></tr></tbody></table>

`cursor_back`(_count=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L885-L897)[¶](#pyte.screens.Screen.cursor_back "Permalink to this definition")

Move cursor left the indicated # of columns. Cursor stops at left margin.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>count</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – number of columns to skip.</td></tr></tbody></table>

`cursor_forward`(_count=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L899-L906)[¶](#pyte.screens.Screen.cursor_forward "Permalink to this definition")

Move cursor right the indicated # of columns. Cursor stops at right margin.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>count</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – number of columns to skip.</td></tr></tbody></table>

`cursor_position`(_line=None_, _column=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L908-L933)[¶](#pyte.screens.Screen.cursor_position "Permalink to this definition")

Set the cursor to a specific line and column.

Cursor is allowed to move out of the scrolling region only when [`DECOM`](#pyte.modes.DECOM "pyte.modes.DECOM") is reset, otherwise – the position doesn’t change.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><ul><li><strong>line</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – line number to move the cursor to.</li><li><strong>column</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – column number to move the cursor to.</li></ul></td></tr></tbody></table>

`cursor_to_column`(_column=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L935-L941)[¶](#pyte.screens.Screen.cursor_to_column "Permalink to this definition")

Move cursor to a specific column in the current line.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>column</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – column number to move the cursor to.</td></tr></tbody></table>

`cursor_to_line`(_line=None_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L943-L958)[¶](#pyte.screens.Screen.cursor_to_line "Permalink to this definition")

Move cursor to a specific line in the current column.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>line</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – line number to move the cursor to.</td></tr></tbody></table>

`bell`(_\*args_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L960-L963)[¶](#pyte.screens.Screen.bell "Permalink to this definition")

Bell stub – the actual implementation should probably be provided by the end-user.

`alignment_display`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L965-L970)[¶](#pyte.screens.Screen.alignment_display "Permalink to this definition")

Fills screen with uppercase E’s for screen focus and alignment.

`select_graphic_rendition`(_\*attrs_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L972-L1018)[¶](#pyte.screens.Screen.select_graphic_rendition "Permalink to this definition")

Set display attributes.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>attrs</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#list" title="(in Python v3.7)"><em>list</em></a>) – a list of display attributes to set.</td></tr></tbody></table>

`report_device_attributes`(_mode=0_, _\*\*kwargs_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1020-L1033)[¶](#pyte.screens.Screen.report_device_attributes "Permalink to this definition")

Report terminal identity.

New in version 0.5.0.

Changed in version 0.7.0: If `private` keyword argument is set, the method does nothing. This behaviour is consistent with VT220 manual.

`report_device_status`(_mode_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1035-L1052)[¶](#pyte.screens.Screen.report_device_status "Permalink to this definition")

Report terminal status or cursor position.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>mode</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – if 5 – terminal status, 6 – cursor position, otherwise a noop.</td></tr></tbody></table>

New in version 0.5.0.

`write_process_input`(_data_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1054-L1062)[¶](#pyte.screens.Screen.write_process_input "Permalink to this definition")

Write data to the process running inside the terminal.

By default is a noop.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>data</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#str" title="(in Python v3.7)"><em>str</em></a>) – text to write to the process <code><span>stdin</span></code>.</td></tr></tbody></table>

New in version 0.5.0.

`debug`(_\*args_, _\*\*kwargs_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1064-L1068)[¶](#pyte.screens.Screen.debug "Permalink to this definition")

Endpoint for unrecognized escape sequences.

By default is a noop.

### pyte.screens.DiffScreen[¶](#pyte-screens-diffscreen "Permalink to this headline")

_class_ `pyte.screens`.`DiffScreen`(_\*args_, _\*\*kwargs_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1071-L1089)[¶](#pyte.screens.DiffScreen "Permalink to this definition")

A screen subclass, which maintains a set of dirty lines in its `dirty` attribute. The end user is responsible for emptying a set, when a diff is applied.

Deprecated since version 0.7.0: The functionality contained in this class has been merged into [`Screen`](#pyte.screens.Screen "pyte.screens.Screen") and will be removed in 0.8.0. Please update your code accordingly.

### pyte.screens.HistoryScreen[¶](#pyte-screens-historyscreen "Permalink to this headline")

_class_ `pyte.screens`.`History`(_top_, _bottom_, _ratio_, _size_, _position_)[¶](#pyte.screens.History "Permalink to this definition")

_class_ `pyte.screens`.`HistoryScreen`(_columns_, _lines_, _history=100_, _ratio=0.5_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1095-L1267)[¶](#pyte.screens.HistoryScreen "Permalink to this definition")

A :class:~\`pyte.screens.Screen\` subclass, which keeps track of screen history and allows pagination. This is not linux-specific, but still useful; see page 462 of VT520 User’s Manual.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><ul><li><strong>history</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – total number of history lines to keep; is split between top and bottom queues.</li><li><strong>ratio</strong> (<a href="https://docs.python.org/3/library/functions.html#int" title="(in Python v3.7)"><em>int</em></a>) – defines how much lines to scroll on <a href="#pyte.screens.HistoryScreen.next_page" title="pyte.screens.HistoryScreen.next_page"><code><span>next_page()</span></code></a> and <a href="#pyte.screens.HistoryScreen.prev_page" title="pyte.screens.HistoryScreen.prev_page"><code><span>prev_page()</span></code></a> calls.</li></ul></td></tr></tbody></table>

`history`[¶](#pyte.screens.HistoryScreen.history "Permalink to this definition")

A pair of history queues for top and bottom margins accordingly; here’s the overall screen structure:

\[ 1: .......\]
\[ 2: .......\]  <- top history
\[ 3: .......\]
\------------
\[ 4: .......\]  s
\[ 5: .......\]  c
\[ 6: .......\]  r
\[ 7: .......\]  e
\[ 8: .......\]  e
\[ 9: .......\]  n
\------------
\[10: .......\]
\[11: .......\]  <- bottom history
\[12: .......\]

Note

Don’t forget to update `Stream` class with appropriate escape sequences – you can use any, since pagination protocol is not standardized, for example:

Stream.escape\["N"\] \= "next\_page"
Stream.escape\["P"\] \= "prev\_page"

`before_event`(_event_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1161-L1168)[¶](#pyte.screens.HistoryScreen.before_event "Permalink to this definition")

Ensure a screen is at the bottom of the history buffer.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>event</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#str" title="(in Python v3.7)"><em>str</em></a>) – event name, for example <code><span>"linefeed"</span></code>.</td></tr></tbody></table>

`after_event`(_event_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1170-L1189)[¶](#pyte.screens.HistoryScreen.after_event "Permalink to this definition")

Ensure all lines on a screen have proper width (`columns`).

Extra characters are truncated, missing characters are filled with whitespace.

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><strong>event</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#str" title="(in Python v3.7)"><em>str</em></a>) – event name, for example <code><span>"linefeed"</span></code>.</td></tr></tbody></table>

`reset`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1196-L1202)[¶](#pyte.screens.HistoryScreen.reset "Permalink to this definition")

Overloaded to reset screen history state: history position is reset to bottom of both queues; queues themselves are emptied.

`erase_in_display`(_how=0_, _\*args_, _\*\*kwargs_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1204-L1209)[¶](#pyte.screens.HistoryScreen.erase_in_display "Permalink to this definition")

Overloaded to reset history state.

`index`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1211-L1218)[¶](#pyte.screens.HistoryScreen.index "Permalink to this definition")

Overloaded to update top history with the removed lines.

`reverse_index`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1220-L1227)[¶](#pyte.screens.HistoryScreen.reverse_index "Permalink to this definition")

Overloaded to update bottom history with the removed lines.

`prev_page`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1229-L1250)[¶](#pyte.screens.HistoryScreen.prev_page "Permalink to this definition")

Move the screen page up through the history buffer. Page size is defined by `history.ratio`, so for instance `ratio = .5` means that half the screen is restored from history on page switch.

`next_page`()[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1252-L1267)[¶](#pyte.screens.HistoryScreen.next_page "Permalink to this definition")

Move the screen page down through the history buffer.

### pyte.screens.DebugScreen[¶](#pyte-screens-debugscreen "Permalink to this headline")

_class_ `pyte.screens`.`DebugScreen`(_to=<\_io.TextIOWrapper name='<stderr>' mode='w' encoding='UTF-8'>_, _only=()_)[\[source\]](https://github.com/selectel/pyte/tree/master/pyte/screens.py#L1290-L1331)[¶](#pyte.screens.DebugScreen "Permalink to this definition")

A screen which dumps a subset of the received events to a file.

\>>> import io
\>>> with io.StringIO() as buf:
...     stream \= Stream(DebugScreen(to\=buf))
...     stream.feed("\\x1b\[1;24r\\x1b\[4l\\x1b\[24;1H\\x1b\[0;10m")
...     print(buf.getvalue())
...
...
\["set\_margins", \[1, 24\], {}\]
\["reset\_mode", \[4\], {}\]
\["cursor\_position", \[24, 1\], {}\]
\["select\_graphic\_rendition", \[0, 10\], {}\]

<table><colgroup><col> <col></colgroup><tbody><tr><th>Parameters:</th><td><ul><li><strong>to</strong> (<em>file</em>) – a file-like object to write debug information to.</li><li><strong>only</strong> (<a href="https://docs.python.org/3/library/stdtypes.html#list" title="(in Python v3.7)"><em>list</em></a>) – a list of events you want to debug (empty by default, which means – debug all events).</li></ul></td></tr></tbody></table>

Warning

This is developer API with no backward compatibility guarantees. Use at your own risk!

## pyte.modes[¶](#pyte-modes "Permalink to this headline")

This module defines terminal mode switches, used by [`Screen`](#pyte.screens.Screen "pyte.screens.Screen"). There’re two types of terminal modes:

*   non-private which should be set with `ESC [ N h`, where `N` is an integer, representing mode being set; and
*   private which should be set with `ESC [ ? N h`.

The latter are shifted 5 times to the right, to be easily distinguishable from the former ones; for example Origin Mode – [`DECOM`](#pyte.modes.DECOM "pyte.modes.DECOM") is `192` not `6`.

<table><colgroup><col> <col></colgroup><tbody><tr><th>copyright:</th><td><ol start="3"><li>2011-2012 by Selectel.</li></ol></td></tr><tr><th>copyright:</th><td><p>(c) 2012-2017 by pyte authors and contributors, see AUTHORS for details.</p></td></tr><tr><th>license:</th><td><p>LGPL, see LICENSE for more details.</p></td></tr></tbody></table>

`pyte.modes`.`LNM` _= 20_[¶](#pyte.modes.LNM "Permalink to this definition")

_Line Feed/New Line Mode_: When enabled, causes a received [`LF`](#pyte.control.LF "pyte.control.LF"), [`pyte.control.FF`](#pyte.control.FF "pyte.control.FF"), or [`VT`](#pyte.control.VT "pyte.control.VT") to move the cursor to the first column of the next line.

`pyte.modes`.`IRM` _= 4_[¶](#pyte.modes.IRM "Permalink to this definition")

_Insert/Replace Mode_: When enabled, new display characters move old display characters to the right. Characters moved past the right margin are lost. Otherwise, new display characters replace old display characters at the cursor position.

`pyte.modes`.`DECTCEM` _= 800_[¶](#pyte.modes.DECTCEM "Permalink to this definition")

_Text Cursor Enable Mode_: determines if the text cursor is visible.

`pyte.modes`.`DECSCNM` _= 160_[¶](#pyte.modes.DECSCNM "Permalink to this definition")

_Screen Mode_: toggles screen-wide reverse-video mode.

`pyte.modes`.`DECOM` _= 192_[¶](#pyte.modes.DECOM "Permalink to this definition")

_Origin Mode_: allows cursor addressing relative to a user-defined origin. This mode resets when the terminal is powered up or reset. It does not affect the erase in display (ED) function.

`pyte.modes`.`DECAWM` _= 224_[¶](#pyte.modes.DECAWM "Permalink to this definition")

_Auto Wrap Mode_: selects where received graphic characters appear when the cursor is at the right margin.

`pyte.modes`.`DECCOLM` _= 96_[¶](#pyte.modes.DECCOLM "Permalink to this definition")

_Column Mode_: selects the number of columns per line (80 or 132) on the screen.

## pyte.control[¶](#pyte-control "Permalink to this headline")

This module defines simple control sequences, recognized by `Stream`, the set of codes here is for `TERM=linux` which is a superset of VT102.

<table><colgroup><col> <col></colgroup><tbody><tr><th>copyright:</th><td><ol start="3"><li>2011-2012 by Selectel.</li></ol></td></tr><tr><th>copyright:</th><td><p>(c) 2012-2017 by pyte authors and contributors, see AUTHORS for details.</p></td></tr><tr><th>license:</th><td><p>LGPL, see LICENSE for more details.</p></td></tr></tbody></table>

`pyte.control`.`SP` = `' '` [¶](#pyte.control.SP "Permalink to this definition")

_Space_: Not suprisingly – `" "`.

`pyte.control`.`NUL` = `'\\x00'` [¶](#pyte.control.NUL "Permalink to this definition")

_Null_: Does nothing.

`pyte.control`.`BEL` = `'\\x07'` [¶](#pyte.control.BEL "Permalink to this definition")

_Bell_: Beeps.

`pyte.control`.`BS` = `'\\x08'` [¶](#pyte.control.BS "Permalink to this definition")

_Backspace_: Backspace one column, but not past the begining of the line.

`pyte.control`.`HT` = `'\\t'` [¶](#pyte.control.HT "Permalink to this definition")

_Horizontal tab_: Move cursor to the next tab stop, or to the end of the line if there is no earlier tab stop.

`pyte.control`.`LF` = `'\\n'` [¶](#pyte.control.LF "Permalink to this definition")

_Linefeed_: Give a line feed, and, if [`pyte.modes.LNM`](#pyte.modes.LNM "pyte.modes.LNM") (new line mode) is set also a carriage return.

`pyte.control`.`VT` = `'\\x0b'` [¶](#pyte.control.VT "Permalink to this definition")

_Vertical tab_: Same as [`LF`](#pyte.control.LF "pyte.control.LF").

`pyte.control`.`FF` = `'\\x0c'` [¶](#pyte.control.FF "Permalink to this definition")

_Form feed_: Same as [`LF`](#pyte.control.LF "pyte.control.LF").

`pyte.control`.`CR` = `'\\r'` [¶](#pyte.control.CR "Permalink to this definition")

_Carriage return_: Move cursor to left margin on current line.

`pyte.control`.`SO` = `'\\x0e'` [¶](#pyte.control.SO "Permalink to this definition")

_Shift out_: Activate G1 character set.

`pyte.control`.`SI` = `'\\x0f'` [¶](#pyte.control.SI "Permalink to this definition")

_Shift in_: Activate G0 character set.

`pyte.control`.`CAN` = `'\\x18'` [¶](#pyte.control.CAN "Permalink to this definition")

_Cancel_: Interrupt escape sequence. If received during an escape or control sequence, cancels the sequence and displays substitution character.

`pyte.control`.`SUB` = `'\\x1a'` [¶](#pyte.control.SUB "Permalink to this definition")

_Substitute_: Same as [`CAN`](#pyte.control.CAN "pyte.control.CAN").

`pyte.control`.`ESC` = `'\\x1b'` [¶](#pyte.control.ESC "Permalink to this definition")

_Escape_: Starts an escape sequence.

`pyte.control`.`DEL` = `'\\x7f'` [¶](#pyte.control.DEL "Permalink to this definition")

_Delete_: Is ignored.

`pyte.control`.`CSI_C0` = `'\\x1b\['` [¶](#pyte.control.CSI_C0 "Permalink to this definition")

_Control sequence introducer_.

`pyte.control`.`ST_C0` = `'\\x1b\\\\'` [¶](#pyte.control.ST_C0 "Permalink to this definition")

_String terminator_.

`pyte.control`.`OSC_C0` = `'\\x1b\]'` [¶](#pyte.control.OSC_C0 "Permalink to this definition")

_Operating system command_.

## pyte.escape[¶](#pyte-escape "Permalink to this headline")

This module defines both CSI and non-CSI escape sequences, recognized by `Stream` and subclasses.

<table><colgroup><col> <col></colgroup><tbody><tr><th>copyright:</th><td><ol start="3"><li>2011-2012 by Selectel.</li></ol></td></tr><tr><th>copyright:</th><td><p>(c) 2012-2017 by pyte authors and contributors, see AUTHORS for details.</p></td></tr><tr><th>license:</th><td><p>LGPL, see LICENSE for more details.</p></td></tr></tbody></table>

`pyte.escape`.`RIS` = `'c'` [¶](#pyte.escape.RIS "Permalink to this definition")

_Reset_.

`pyte.escape`.`IND` = `'D'` [¶](#pyte.escape.IND "Permalink to this definition")

_Index_: Move cursor down one line in same column. If the cursor is at the bottom margin, the screen performs a scroll-up.

`pyte.escape`.`NEL` = `'E'` [¶](#pyte.escape.NEL "Permalink to this definition")

_Next line_: Same as [`pyte.control.LF`](#pyte.control.LF "pyte.control.LF").

`pyte.escape`.`HTS` = `'H'` [¶](#pyte.escape.HTS "Permalink to this definition")

Tabulation set: Set a horizontal tab stop at cursor position.

`pyte.escape`.`RI` = `'M'` [¶](#pyte.escape.RI "Permalink to this definition")

_Reverse index_: Move cursor up one line in same column. If the cursor is at the top margin, the screen performs a scroll-down.

`pyte.escape`.`DECSC` = `'7'` [¶](#pyte.escape.DECSC "Permalink to this definition")

Save cursor: Save cursor position, character attribute (graphic rendition), character set, and origin mode selection (see [`DECRC`](#pyte.escape.DECRC "pyte.escape.DECRC")).

`pyte.escape`.`DECRC` = `'8'` [¶](#pyte.escape.DECRC "Permalink to this definition")

_Restore cursor_: Restore previously saved cursor position, character attribute (graphic rendition), character set, and origin mode selection. If none were saved, move cursor to home position.

`pyte.escape`.`DECALN` = `'8'` [¶](#pyte.escape.DECALN "Permalink to this definition")

_Alignment display_: Fill screen with uppercase E’s for testing screen focus and alignment.

`pyte.escape`.`ICH` = `'@'` [¶](#pyte.escape.ICH "Permalink to this definition")

_Insert character_: Insert the indicated # of blank characters.

`pyte.escape`.`CUU` = `'A'` [¶](#pyte.escape.CUU "Permalink to this definition")

_Cursor up_: Move cursor up the indicated # of lines in same column. Cursor stops at top margin.

`pyte.escape`.`CUD` = `'B'` [¶](#pyte.escape.CUD "Permalink to this definition")

_Cursor down_: Move cursor down the indicated # of lines in same column. Cursor stops at bottom margin.

`pyte.escape`.`CUF` = `'C'` [¶](#pyte.escape.CUF "Permalink to this definition")

_Cursor forward_: Move cursor right the indicated # of columns. Cursor stops at right margin.

`pyte.escape`.`CUB` = `'D'` [¶](#pyte.escape.CUB "Permalink to this definition")

_Cursor back_: Move cursor left the indicated # of columns. Cursor stops at left margin.

`pyte.escape`.`CNL` = `'E'` [¶](#pyte.escape.CNL "Permalink to this definition")

_Cursor next line_: Move cursor down the indicated # of lines to column 1.

`pyte.escape`.`CPL` = `'F'` [¶](#pyte.escape.CPL "Permalink to this definition")

_Cursor previous line_: Move cursor up the indicated # of lines to column 1.

`pyte.escape`.`CHA` = `'G'` [¶](#pyte.escape.CHA "Permalink to this definition")

_Cursor horizontal align_: Move cursor to the indicated column in current line.

`pyte.escape`.`CUP` = `'H'` [¶](#pyte.escape.CUP "Permalink to this definition")

_Cursor position_: Move cursor to the indicated line, column (origin at `1, 1`).

`pyte.escape`.`ED` = `'J'` [¶](#pyte.escape.ED "Permalink to this definition")

_Erase data_ (default: from cursor to end of line).

`pyte.escape`.`EL` = `'K'` [¶](#pyte.escape.EL "Permalink to this definition")

_Erase in line_ (default: from cursor to end of line).

`pyte.escape`.`IL` = `'L'` [¶](#pyte.escape.IL "Permalink to this definition")

_Insert line_: Insert the indicated # of blank lines, starting from the current line. Lines displayed below cursor move down. Lines moved past the bottom margin are lost.

`pyte.escape`.`DL` = `'M'` [¶](#pyte.escape.DL "Permalink to this definition")

_Delete line_: Delete the indicated # of lines, starting from the current line. As lines are deleted, lines displayed below cursor move up. Lines added to bottom of screen have spaces with same character attributes as last line move up.

`pyte.escape`.`DCH` = `'P'` [¶](#pyte.escape.DCH "Permalink to this definition")

_Delete character_: Delete the indicated # of characters on the current line. When character is deleted, all characters to the right of cursor move left.

`pyte.escape`.`ECH` = `'X'` [¶](#pyte.escape.ECH "Permalink to this definition")

_Erase character_: Erase the indicated # of characters on the current line.

`pyte.escape`.`HPR` = `'a'` [¶](#pyte.escape.HPR "Permalink to this definition")

_Horizontal position relative_: Same as [`CUF`](#pyte.escape.CUF "pyte.escape.CUF").

`pyte.escape`.`DA` = `'c'` [¶](#pyte.escape.DA "Permalink to this definition")

_Device Attributes_.

`pyte.escape`.`VPA` = `'d'` [¶](#pyte.escape.VPA "Permalink to this definition")

_Vertical position adjust_: Move cursor to the indicated line, current column.

`pyte.escape`.`VPR` = `'e'` [¶](#pyte.escape.VPR "Permalink to this definition")

_Vertical position relative_: Same as [`CUD`](#pyte.escape.CUD "pyte.escape.CUD").

`pyte.escape`.`HVP` = `'f'` [¶](#pyte.escape.HVP "Permalink to this definition")

_Horizontal / Vertical position_: Same as [`CUP`](#pyte.escape.CUP "pyte.escape.CUP").

`pyte.escape`.`TBC` = `'g'` [¶](#pyte.escape.TBC "Permalink to this definition")

_Tabulation clear_: Clears a horizontal tab stop at cursor position.

`pyte.escape`.`SM` = `'h'` [¶](#pyte.escape.SM "Permalink to this definition")

_Set mode_.

`pyte.escape`.`RM` = `'l'` [¶](#pyte.escape.RM "Permalink to this definition")

_Reset mode_.

`pyte.escape`.`SGR` = `'m'` [¶](#pyte.escape.SGR "Permalink to this definition")

_Select graphics rendition_: The terminal can display the following character attributes that change the character display without changing the character (see [`pyte.graphics`](#module-pyte.graphics "pyte.graphics")).

`pyte.escape`.`DSR` = `'n'` [¶](#pyte.escape.DSR "Permalink to this definition")

_Device status report_.

`pyte.escape`.`DECSTBM` = `'r'` [¶](#pyte.escape.DECSTBM "Permalink to this definition")

_Select top and bottom margins_: Selects margins, defining the scrolling region; parameters are top and bottom line. If called without any arguments, whole screen is used.

`pyte.escape`.`HPA` _= "'"_[¶](#pyte.escape.HPA "Permalink to this definition")

_Horizontal position adjust_: Same as [`CHA`](#pyte.escape.CHA "pyte.escape.CHA").

## pyte.graphics[¶](#pyte-graphics "Permalink to this headline")

This module defines graphic-related constants, mostly taken from _console\_codes(4)_ and [http://pueblo.sourceforge.net/doc/manual/ansi\_color\_codes.html](http://pueblo.sourceforge.net/doc/manual/ansi_color_codes.html).

<table><colgroup><col> <col></colgroup><tbody><tr><th>copyright:</th><td><ol start="3"><li>2011-2012 by Selectel.</li></ol></td></tr><tr><th>copyright:</th><td><p>(c) 2012-2017 by pyte authors and contributors, see AUTHORS for details.</p></td></tr><tr><th>license:</th><td><p>LGPL, see LICENSE for more details.</p></td></tr></tbody></table>

`pyte.graphics`.`TEXT` _= {1: '+bold', 3: '+italics', 4: '+underscore', 5: '+blink', 7: '+reverse', 9: '+strikethrough', 22: '-bold', 23: '-italics', 24: '-underscore', 25: '-blink', 27: '-reverse', 29: '-strikethrough'}_[¶](#pyte.graphics.TEXT "Permalink to this definition")

A mapping of ANSI text style codes to style names, “+” means the: attribute is set, “-” – reset; example:

\>>> text\[1\]
'+bold'
\>>> text\[9\]
'+strikethrough'

`pyte.graphics`.`FG_ANSI` _= {30: 'black', 31: 'red', 32: 'green', 33: 'brown', 34: 'blue', 35: 'magenta', 36: 'cyan', 37: 'white', 39: 'default'}_[¶](#pyte.graphics.FG_ANSI "Permalink to this definition")

A mapping of ANSI foreground color codes to color names.

\>>> FG\_ANSI\[30\]
'black'
\>>> FG\_ANSI\[38\]
'default'

`pyte.graphics`.`FG` _= {30: 'black', 31: 'red', 32: 'green', 33: 'brown', 34: 'blue', 35: 'magenta', 36: 'cyan', 37: 'white', 39: 'default'}_[¶](#pyte.graphics.FG "Permalink to this definition")

An alias to [`FG_ANSI`](#pyte.graphics.FG_ANSI "pyte.graphics.FG_ANSI") for compatibility.

`pyte.graphics`.`FG_AIXTERM` _= {90: 'black', 91: 'red', 92: 'green', 93: 'brown', 94: 'blue', 95: 'magenta', 96: 'cyan', 97: 'white'}_[¶](#pyte.graphics.FG_AIXTERM "Permalink to this definition")

A mapping of non-standard `aixterm` foreground color codes to color names. These are high intensity colors and thus should be complemented by `+bold`.

`pyte.graphics`.`BG_ANSI` _= {40: 'black', 41: 'red', 42: 'green', 43: 'brown', 44: 'blue', 45: 'magenta', 46: 'cyan', 47: 'white', 49: 'default'}_[¶](#pyte.graphics.BG_ANSI "Permalink to this definition")

A mapping of ANSI background color codes to color names.

\>>> BG\_ANSI\[40\]
'black'
\>>> BG\_ANSI\[48\]
'default'

`pyte.graphics`.`BG` _= {40: 'black', 41: 'red', 42: 'green', 43: 'brown', 44: 'blue', 45: 'magenta', 46: 'cyan', 47: 'white', 49: 'default'}_[¶](#pyte.graphics.BG "Permalink to this definition")

An alias to [`BG_ANSI`](#pyte.graphics.BG_ANSI "pyte.graphics.BG_ANSI") for compatibility.

`pyte.graphics`.`BG_AIXTERM` _= {100: 'black', 101: 'red', 102: 'green', 103: 'brown', 104: 'blue', 105: 'magenta', 106: 'cyan', 107: 'white'}_[¶](#pyte.graphics.BG_AIXTERM "Permalink to this definition")

A mapping of non-standard `aixterm` background color codes to color names. These are high intensity colors and thus should be complemented by `+bold`.

`pyte.graphics`.`FG_256` _= 38_[¶](#pyte.graphics.FG_256 "Permalink to this definition")

SGR code for foreground in 256 or True color mode.

`pyte.graphics`.`BG_256` _= 48_[¶](#pyte.graphics.BG_256 "Permalink to this definition")

SGR code for background in 256 or True color mode.

## pyte.charsets[¶](#pyte-charsets "Permalink to this headline")

This module defines `G0` and `G1` charset mappings the same way they are defined for linux terminal, see `linux/drivers/tty/consolemap.c` @ [http://git.kernel.org](http://git.kernel.org/)

Note

`VT100_MAP` and `IBMPC_MAP` were taken unchanged from linux kernel source and therefore are licensed under **GPL**.

<table><colgroup><col> <col></colgroup><tbody><tr><th>copyright:</th><td><ol start="3"><li>2011-2012 by Selectel.</li></ol></td></tr><tr><th>copyright:</th><td><p>(c) 2012-2017 by pyte authors and contributors, see AUTHORS for details.</p></td></tr><tr><th>license:</th><td><p>LGPL, see LICENSE for more details.</p></td></tr></tbody></table>

`pyte.charsets`.`LAT1_MAP` = `'\\x00\\x01\\x02\\x03\\x04\\x05\\x06\\x07\\x08\\t\\n\\x0b\\x0c\\r\\x0e\\x0f\\x10\\x11\\x12\\x13\\x14\\x15\\x16\\x17\\x18\\x19\\x1a\\x1b\\x1c\\x1d\\x1e\\x1f !"#$%&\\'()\*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ\[\\\\\]^\_\`abcdefghijklmnopqrstuvwxyz{|}~\\x7f\\x80\\x81\\x82\\x83\\x84\\x85\\x86\\x87\\x88\\x89\\x8a\\x8b\\x8c\\x8d\\x8e\\x8f\\x90\\x91\\x92\\x93\\x94\\x95\\x96\\x97\\x98\\x99\\x9a\\x9b\\x9c\\x9d\\x9e\\x9f\\xa0¡¢£¤¥¦§¨©ª«¬\\xad®¯°±²³´µ¶·¸¹º»¼½¾¿ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ'` [¶](#pyte.charsets.LAT1_MAP "Permalink to this definition")

Latin1.

`pyte.charsets`.`VT100_MAP` = `'\\x00\\x01\\x02\\x03\\x04\\x05\\x06\\x07\\x08\\t\\n\\x0b\\x0c\\r\\x0e\\x0f\\x10\\x11\\x12\\x13\\x14\\x15\\x16\\x17\\x18\\x19\\x1a\\x1b\\x1c\\x1d\\x1e\\x1f !"#$%&\\'()\*→←↑↓/█123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ\[\\\\\]^\\xa0◆▒␉␌␍␊°±░␋┘┐┌└┼⎺⎻─⎼⎽├┤┴┬│≤≥π≠£·\\x7f\\x80\\x81\\x82\\x83\\x84\\x85\\x86\\x87\\x88\\x89\\x8a\\x8b\\x8c\\x8d\\x8e\\x8f\\x90\\x91\\x92\\x93\\x94\\x95\\x96\\x97\\x98\\x99\\x9a\\x9b\\x9c\\x9d\\x9e\\x9f\\xa0¡¢£¤¥¦§¨©ª«¬\\xad®¯°±²³´µ¶·¸¹º»¼½¾¿ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ'` [¶](#pyte.charsets.VT100_MAP "Permalink to this definition")

VT100 graphic character set.

`pyte.charsets`.`IBMPC_MAP` = `'\\x00☺☻♥♦♣♠•◘○◙♂♀♪♫☼▶◀↕‼¶§▬↨↑↓→←∟↔▲▼ !"#$%&\\'()\*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ\[\\\\\]^\_\`abcdefghijklmnopqrstuvwxyz{|}~⌂ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■\\xa0'` [¶](#pyte.charsets.IBMPC_MAP "Permalink to this definition")

IBM Codepage 437.

`pyte.charsets`.`VAX42_MAP` = `'\\x00☺☻♥♦♣♠•◘○◙♂♀♪♫☼▶◀↕‼¶§▬↨↑↓→←∟↔▲▼ л"#$%&\\'()\*+,-./0123456789:;<=>е@ABCDEFGHIJKLMNOPQRSTUVWXYZ\[\\\\\]^\_\`сbcdefgеijklmnкpqтsлеvwxyz{|}~⌂ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■\\xa0'` [¶](#pyte.charsets.VAX42_MAP "Permalink to this definition")

VAX42 character set.
