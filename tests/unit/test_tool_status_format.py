"""Tests for integrations.slack.formatting.format_tool_status."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the integrations/slack package importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integrations" / "slack"))

from formatting import format_tool_status


# -- exec_command / exec_sandbox --

def test_exec_command_shows_command():
    args = json.dumps({"command": "ls -la /tmp"})
    result = format_tool_status("exec_command", args)
    assert result == "🔧 exec_command → `ls -la /tmp`"


def test_exec_sandbox_shows_command():
    args = json.dumps({"command": "python main.py"})
    result = format_tool_status("exec_sandbox", args)
    assert result == "🔧 exec_sandbox → `python main.py`"


def test_exec_command_truncates_long_command():
    long_cmd = "echo " + "x" * 200
    args = json.dumps({"command": long_cmd})
    result = format_tool_status("exec_command", args)
    assert "…" in result
    # Extract the backtick-wrapped portion
    inner = result.split("`")[1]
    assert len(inner) <= 101  # 100 chars + ellipsis


def test_exec_command_missing_command_key():
    args = json.dumps({"timeout": 30})
    result = format_tool_status("exec_command", args)
    assert result == "🔧 _exec_command..._"


# -- delegate_to_harness --

def test_delegate_to_harness():
    args = json.dumps({"harness": "claude", "prompt": "Summarize this file\nwith details"})
    result = format_tool_status("delegate_to_harness", args)
    assert result == "🤖 claude → Summarize this file"


def test_delegate_to_harness_truncates_long_prompt():
    long_prompt = "a " * 100  # 200 chars
    args = json.dumps({"harness": "claude", "prompt": long_prompt})
    result = format_tool_status("delegate_to_harness", args)
    assert "…" in result


def test_delegate_to_harness_no_prompt():
    args = json.dumps({"harness": "claude"})
    result = format_tool_status("delegate_to_harness", args)
    assert result == "🤖 claude"


# -- delegate_to_agent --

def test_delegate_to_agent():
    args = json.dumps({"bot_id": "researcher", "prompt": "Find recent papers"})
    result = format_tool_status("delegate_to_agent", args)
    assert result == "🤖 researcher → Find recent papers"


def test_delegate_to_agent_truncates_long_prompt():
    long_prompt = "word " * 50
    args = json.dumps({"bot_id": "researcher", "prompt": long_prompt})
    result = format_tool_status("delegate_to_agent", args)
    assert "…" in result


def test_delegate_to_agent_no_prompt():
    args = json.dumps({"bot_id": "researcher"})
    result = format_tool_status("delegate_to_agent", args)
    assert result == "🤖 researcher"


# -- Unknown tools --

def test_unknown_tool():
    result = format_tool_status("web_search")
    assert result == "🔧 _web_search..._"


def test_unknown_tool_with_args():
    args = json.dumps({"query": "hello"})
    result = format_tool_status("web_search", args)
    assert result == "🔧 _web_search..._"


# -- Missing / invalid args --

def test_none_args():
    result = format_tool_status("exec_command", None)
    assert result == "🔧 _exec_command..._"


def test_empty_string_args():
    result = format_tool_status("exec_command", "")
    assert result == "🔧 _exec_command..._"


def test_invalid_json_args():
    result = format_tool_status("exec_command", "{not json")
    assert result == "🔧 _exec_command..._"


def test_non_dict_json_args():
    result = format_tool_status("exec_command", '"just a string"')
    # json.loads returns a str, .get() will AttributeError → falls through
    assert "exec_command" in result
