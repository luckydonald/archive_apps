#!/usr/bin/env python3
"""PermissionRequest hooks: enforces git add and Co-Authored-By policies."""

import json
import shlex
import sys
import traceback


def deny(reason):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def deny_error(e):
    tb = traceback.format_exc()
    return deny(
        f"COMMAND AUDIT ERROR: While trying to calculate if this command is allowed "
        f"to execute, the script encountered an error. STOP EXECUTION NOW, and show "
        f"the error to the user, so they can ask for that script to be fixed. Do not "
        f"attempt to work around it unless specifically asked to by the user. "
        f"Error message: {type(e).__name__}: {e}\n\nStacktrace:\n{tb}"
    )


def check_git_add(argv):
    """Return denial reason if git add targets all files, else None."""
    # argv[0] == 'git', argv[1] == 'add'
    flags_all = {"-A", "--all", "-u", "--update"}
    for arg in argv[2:]:
        if arg in flags_all:
            return (
                "Use explicit file paths with 'git add' — staging all files risks "
                "committing secrets or unintended changes. Instead of 'git add -A', "
                "list files explicitly."
            )
        if arg in (".", ":/"):
            return (
                "Use explicit file paths with 'git add' — staging all files risks "
                "committing secrets or unintended changes. Instead of 'git add .', "
                "list files explicitly."
            )
    return None


def collect_commit_messages(argv):
    """Parse git commit argv and return all message text to inspect."""
    messages = []
    i = 2
    while i < len(argv):
        arg = argv[i]
        # -m MSG or --message MSG or --message=MSG
        if arg in ("-m", "--message"):
            if i + 1 < len(argv):
                messages.append(argv[i + 1])
                i += 2
            else:
                i += 1
        elif arg.startswith("--message="):
            messages.append(arg[len("--message="):])
            i += 1
        # -F FILE or --file FILE or --file=FILE
        elif arg in ("-F", "--file"):
            if i + 1 < len(argv):
                path = argv[i + 1]
                i += 2
                if path == "-":
                    # stdin — cannot inspect
                    continue
                try:
                    with open(path) as f:
                        messages.append(f.read())
                except OSError:
                    continue
            else:
                i += 1
        elif arg.startswith("--file="):
            path = arg[len("--file="):]
            i += 1
            if path == "-":
                continue
            try:
                with open(path) as f:
                    messages.append(f.read())
            except OSError:
                continue
        else:
            i += 1
    return messages


def check_git_commit(argv):
    """Return denial reason if commit message contains Co-Authored-By, else None."""
    messages = collect_commit_messages(argv)
    combined = "\n".join(messages)
    combined_lower = combined.lower()
    if "co-authored-by:" in combined_lower or "noreply@anthropic" in combined_lower:
        return (
            "Co-Authored-By attribution is not allowed. Remove the 'Co-Authored-By: ...' "
            "trailer from the commit message."
        )
    return None


def split_on_shell_operators(argv):
    """Split a shlex-parsed argv on shell operators (&&, ||, ;) into sub-commands."""
    operators = {"&&", "||", ";"}
    sub_commands = []
    current = []
    for token in argv:
        if token in operators:
            if current:
                sub_commands.append(current)
            current = []
        else:
            current.append(token)
    if current:
        sub_commands.append(current)
    return sub_commands


def main():
    try:
        data = json.load(sys.stdin)
        tool_name = data.get("tool_name", "")
        if tool_name not in {"Bash", "shell", "unified_exec"}:
            print("{}")
            return

        tool_input = data.get("tool_input", {}) or {}
        command = (
            tool_input.get("command")
            or tool_input.get("cmd")
            or data.get("command")
            or ""
        )
        if not command:
            print("{}")
            return

        # Fast path: if the raw command string looks like a git commit and contains
        # Co-Authored-By (colon required, matching the trailer format) or the
        # Anthropic noreply email, deny immediately before shlex parsing. When the
        # message is passed via a heredoc like `git commit -m "$(cat <<'EOF'\n...\nEOF\n)"`,
        # shlex parses successfully but yields the unexpanded `$(...)` expression as the
        # -m value — the actual message text is invisible to collect_commit_messages.
        # Scanning the raw command string catches those cases because the heredoc body
        # is present verbatim.
        stripped = command.strip()
        _stripped_lower = stripped.lower()
        if "git commit" in stripped and (
            "co-authored-by:" in _stripped_lower
            or "noreply@anthropic" in _stripped_lower
        ):
            print(json.dumps(deny(
                "Co-Authored-By attribution is not allowed. Remove the 'Co-Authored-By: ...' "
                "trailer from the commit message."
            )))
            return

        try:
            argv = shlex.split(command)
        except ValueError as e:
            print(json.dumps(deny_error(e)))
            return

        # Split on shell operators (&&, ||, ;) to check each sub-command
        # shlex treats these as regular tokens, so we must split manually.
        sub_commands = split_on_shell_operators(argv)

        for sub_argv in sub_commands:
            if len(sub_argv) < 2 or sub_argv[0] != "git":
                continue

            subcommand = sub_argv[1]
            reason = None

            if subcommand == "add":
                reason = check_git_add(sub_argv)
            elif subcommand == "commit":
                reason = check_git_commit(sub_argv)

            if reason:
                print(json.dumps(deny(reason)))
                return

        print("{}")
    except Exception as e:
        print(json.dumps(deny_error(e)))


if __name__ == "__main__":
    main()
