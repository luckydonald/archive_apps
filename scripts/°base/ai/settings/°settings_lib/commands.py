from __future__ import annotations

import re
import shlex
from typing import Any


_PERMISSION_ENTRY = re.compile(r"^([A-Za-z_]\w*)\((.*)\)$", re.DOTALL)

# Claude's MCP tool permission strings are bare (no parens), e.g.
# `mcp__bugsink__list_projects` — server names contain no `__` (but may
# contain single underscores, like `sync_todo`); tool names may contain underscores.
_MCP_TOOL_ENTRY = re.compile(r"^mcp__(?P<server>.+?)__(?P<tool>.+)$")

# Type-specific field name used for the entry's main value, keyed by the
# lowercased tool type. Anything not listed here falls back to `pattern`.
_TYPE_FIELD: dict[str, str] = {
    "bash": "command",
    "read": "path",
    "write": "path",
    "edit": "path",
    "glob": "path",
    "skill": "name",
}
_DEFAULT_FIELD = "pattern"

_TYPE_TO_CLAUDE_TOOL: dict[str, str] = {
    "bash": "Bash",
    "read": "Read",
    "write": "Write",
    "edit": "Edit",
    "skill": "Skill",
    "glob": "Glob",
    "grep": "Grep",
    "webfetch": "WebFetch",
    "websearch": "WebSearch",
}


_UNESCAPED_PAREN = re.compile(r"(?<!\\)([()])")
_ESCAPED_PAREN = re.compile(r"\\([()])")


def _escape_command_parens(content: str) -> str:
    """Escape literal `(`/`)` in a permission entry's content so Claude's
    `Tool(content)` syntax doesn't mistake them for the pattern's own
    delimiters — e.g. a bash command containing `$(date ...)`."""
    return _UNESCAPED_PAREN.sub(lambda m: "\\" + m.group(1), content)


def _unescape_command_parens(content: str) -> str:
    """Inverse of `_escape_command_parens`."""
    return _ESCAPED_PAREN.sub(lambda m: m.group(1), content)


def _parse_claude_permission_entry(entry: Any) -> dict[str, Any]:
    """Upgrade a legacy Claude permission string (or pass through an already
    structured object) into the neutral `{"type": ..., ...}` schema."""
    if isinstance(entry, dict):
        return entry
    if not isinstance(entry, str):
        return {"type": "raw", "value": entry}
    mcp_match = _MCP_TOOL_ENTRY.match(entry)
    if mcp_match:
        return {"type": "mcp", "server": mcp_match.group("server"), "tool": mcp_match.group("tool")}
    match = _PERMISSION_ENTRY.match(entry)
    if not match:
        return {"type": "raw", "value": entry}
    tool, content = match.groups()
    entry_type = tool.lower()
    field = _TYPE_FIELD.get(entry_type, _DEFAULT_FIELD)
    return {"type": entry_type, field: _unescape_command_parens(content)}


def _render_claude_permission_entry(entry: Any) -> str:
    """Inverse of `_parse_claude_permission_entry`: render a neutral entry
    back into Claude's `Tool(content)` string syntax."""
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        return str(entry)
    entry_type = entry.get("type", "")
    if entry_type == "raw":
        return str(entry.get("value", ""))
    if entry_type == "mcp":
        return f"mcp__{entry.get('server', '')}__{entry.get('tool', '')}"
    tool = _TYPE_TO_CLAUDE_TOOL.get(entry_type, entry_type.capitalize())
    field = _TYPE_FIELD.get(entry_type, _DEFAULT_FIELD)
    content = entry.get(field, entry.get(_DEFAULT_FIELD, ""))
    return f"{tool}({_escape_command_parens(str(content))})"


# Characters that mean a command string can't be safely reduced to a single
# static argv prefix the way Codex's `.rules` engine expects (see
# https://developers.openai.com/codex/rules — compound/redirected/substituted
# commands are evaluated as one opaque `bash -lc "<script>"` invocation).
_SHELL_METACHARACTERS = re.compile(r"[$`;|<>&]")
_ENV_ASSIGNMENT_PREFIX = re.compile(r"^[A-Za-z_]\w*=")


def _bash_pattern_to_prefix(command: str) -> list[str] | None:
    """Convert a Claude bash permission pattern into a Codex `prefix_rule`
    token list, or return None when it can't be safely translated."""
    command = command.strip()
    if not command:
        return None
    if _SHELL_METACHARACTERS.search(command) or _ENV_ASSIGNMENT_PREFIX.match(command):
        return None

    stripped = command
    if stripped.endswith(":*"):
        stripped = stripped[:-2]
    elif stripped.endswith(" *"):
        stripped = stripped[:-1].rstrip()
    stripped = stripped.strip()
    if not stripped or "*" in stripped:
        return None

    try:
        tokens = shlex.split(stripped)
    except ValueError:
        return None
    return tokens or None
