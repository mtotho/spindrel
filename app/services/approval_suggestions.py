"""Generate smart allow-rule suggestions based on tool call arguments.

Given a tool name and its arguments, produces a list of possible allow rules
the user can pick from — ordered broadest-first so the most useful option
is prominent.

Used by both Slack approval buttons and the admin UI.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field


@dataclass
class RuleSuggestion:
    """A suggested allow rule the user can pick."""
    label: str                    # human-readable, e.g. "Allow exec_command always"
    tool_name: str                # the tool_name for the rule (exact or glob)
    conditions: dict              # argument conditions (empty = match all)
    description: str              # explanation of what this allows
    scope: str = "bot"            # "bot" (default) or "global" (all bots)


def build_suggestions(
    tool_name: str,
    arguments: dict,
    *,
    recent_approval_count: int = 0,
) -> list[RuleSuggestion]:
    """Return a list of RuleSuggestions ordered broadest-first.

    The order is designed so the most common user intent (stop asking me)
    is the first option they see.  Narrower options follow for users who
    want fine-grained control.

    If recent_approval_count >= 3, an escalation hint is prepended.
    """
    broad: list[RuleSuggestion] = []
    narrow: list[RuleSuggestion] = []

    # --- Broadest: allow this tool for ALL bots ---
    broad.append(RuleSuggestion(
        label=f"Allow {tool_name} (all bots)",
        tool_name=tool_name,
        conditions={},
        description=f"Allow all calls to {tool_name} for every bot",
        scope="global",
    ))

    # --- Broad: allow this tool for this bot ---
    broad.append(RuleSuggestion(
        label=f"Allow {tool_name} always",
        tool_name=tool_name,
        conditions={},
        description=f"Allow all calls to {tool_name} for this bot",
    ))

    # --- Tool-specific narrower options ---
    if tool_name in ("exec_command", "exec_sandbox") and "command" in arguments:
        cmd_str = str(arguments["command"]).strip()
        narrow.extend(_exec_command_suggestions(tool_name, cmd_str))
    elif tool_name == "write_file" and "path" in arguments:
        path = str(arguments["path"])
        narrow.extend(_path_suggestions(tool_name, "path", path))
    elif tool_name == "read_file" and "path" in arguments:
        path = str(arguments["path"])
        narrow.extend(_path_suggestions(tool_name, "path", path))
    else:
        # Generic: look for any string argument that might be a command or path
        for key, val in arguments.items():
            if isinstance(val, str) and "/" in val:
                narrow.extend(_path_suggestions(tool_name, key, val))
                break

    return broad + narrow


def _exec_command_suggestions(tool_name: str, cmd_str: str) -> list[RuleSuggestion]:
    """Parse a shell command and suggest prefix-based rules."""
    suggestions = []

    # Try to extract the base command (first word)
    try:
        parts = shlex.split(cmd_str)
    except ValueError:
        parts = cmd_str.split()

    if not parts:
        return suggestions

    base_cmd = parts[0]
    # Strip path prefix: /usr/bin/ls -> ls
    if "/" in base_cmd:
        base_cmd = base_cmd.rsplit("/", 1)[-1]

    # 1. Allow this command with any args (e.g. "ls *")
    suggestions.append(RuleSuggestion(
        label=f"Allow `{base_cmd} *`",
        tool_name=tool_name,
        conditions={"arguments": {"command": {"pattern": f"^{_escape_regex(base_cmd)}(\\s|$)"}}},
        description=f"Allow any `{base_cmd}` command",
    ))

    # 2. If there's a path-like second arg, suggest prefix match
    if len(parts) >= 2:
        for arg in parts[1:]:
            if "/" in arg and not arg.startswith("-"):
                dir_prefix = arg.rsplit("/", 1)[0] + "/"
                suggestions.append(RuleSuggestion(
                    label=f"Allow `{base_cmd}` in `{dir_prefix}*`",
                    tool_name=tool_name,
                    conditions={"arguments": {"command": {"pattern": f"^{_escape_regex(base_cmd)}\\s.*{_escape_regex(dir_prefix)}"}}},
                    description=f"Allow `{base_cmd}` when arguments include path {dir_prefix}",
                ))
                break

    # 3. Allow this exact command (narrowest — last)
    if len(cmd_str) <= 80:
        suggestions.append(RuleSuggestion(
            label=f"Allow `{cmd_str}`",
            tool_name=tool_name,
            conditions={"arguments": {"command": {"pattern": f"^{_escape_regex(cmd_str)}$"}}},
            description=f"Allow only this exact command",
        ))

    return suggestions


def _path_suggestions(tool_name: str, arg_name: str, path: str) -> list[RuleSuggestion]:
    """Suggest rules based on a file path argument."""
    suggestions = []

    # 1. Directory prefix (broader — first)
    if "/" in path:
        dir_prefix = path.rsplit("/", 1)[0] + "/"
        suggestions.append(RuleSuggestion(
            label=f"Allow `{dir_prefix}*`",
            tool_name=tool_name,
            conditions={"arguments": {arg_name: {"prefix": dir_prefix}}},
            description=f"Allow any path under {dir_prefix}",
        ))

    # 2. Exact path (narrower — second)
    if len(path) <= 80:
        suggestions.append(RuleSuggestion(
            label=f"Allow `{path}`",
            tool_name=tool_name,
            conditions={"arguments": {arg_name: {"pattern": f"^{_escape_regex(path)}$"}}},
            description=f"Allow only this exact path",
        ))

    return suggestions


def _escape_regex(s: str) -> str:
    """Escape special regex characters."""
    import re
    return re.escape(s)
