from __future__ import annotations

import json
from pathlib import Path

from app.services.agent_harnesses.native_cli_mirror import (
    _claude_project_dir_name,
    _find_claude_transcript,
    _find_codex_transcript,
    _parse_claude_jsonl_record,
    _parse_codex_jsonl_record,
    _read_new_records,
)


def test_codex_native_cli_parser_keeps_user_request_and_strips_spindrel_wrappers():
    [record] = list(
        _parse_codex_jsonl_record(
            {
                "timestamp": "2026-05-01T00:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "<environment_context>ignore</environment_context>\n"
                                "<spindrel_context_hints>ignore</spindrel_context_hints>\n"
                                "Fix the upload bug."
                            ),
                        }
                    ],
                },
            }
        )
    )

    assert record.role == "user"
    assert record.content == "Fix the upload bug."


def test_codex_native_cli_parser_ignores_developer_messages_and_tool_payloads():
    assert list(
        _parse_codex_jsonl_record(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "hidden"}],
                },
            }
        )
    ) == []
    assert list(
        _parse_codex_jsonl_record(
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "hidden"}],
                },
            }
        )
    ) == []


def test_claude_native_cli_parser_keeps_only_text_content():
    record = _parse_claude_jsonl_record(
        {
            "uuid": "row-1",
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "hidden"},
                    {"type": "tool_use", "name": "Read", "input": {}},
                    {"type": "text", "text": "Done."},
                ],
            },
        }
    )

    assert record is not None
    assert record.key == "claude:row-1"
    assert record.role == "assistant"
    assert record.content == "Done."


def test_claude_native_cli_parser_drops_synthetic_resume_noise():
    assert _parse_claude_jsonl_record(
        {
            "uuid": "row-continue",
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Continue from where you left off."}],
            },
        }
    ) is None
    assert _parse_claude_jsonl_record(
        {
            "uuid": "row-no-response",
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "No response requested."}],
            },
        }
    ) is None


def test_read_new_records_advances_offset_without_replaying(tmp_path: Path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "First"}],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    offset, records = _read_new_records(transcript, offset=0, runtime_name="codex")
    assert [record.content for record in records] == ["First"]

    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Second"}],
                    },
                }
            )
            + "\n"
        )

    next_offset, records = _read_new_records(transcript, offset=offset, runtime_name="codex")
    assert next_offset > offset
    assert [record.content for record in records] == ["Second"]


def test_native_transcript_lookup_uses_runtime_session_id(monkeypatch, tmp_path: Path):
    codex_file = tmp_path / ".codex" / "sessions" / "2026" / "05" / "01" / "rollout-abc.jsonl"
    codex_file.parent.mkdir(parents=True)
    codex_file.write_text("{}\n", encoding="utf-8")
    claude_file = tmp_path / ".claude" / "projects" / _claude_project_dir_name("/work/repo") / "sid.jsonl"
    claude_file.parent.mkdir(parents=True)
    claude_file.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert _find_codex_transcript("abc") == codex_file
    assert _find_claude_transcript("sid", "/work/repo") == claude_file


def test_native_transcript_lookup_without_session_id_requires_recent_matching_cwd(monkeypatch, tmp_path: Path):
    stale = tmp_path / ".codex" / "sessions" / "2026" / "05" / "01" / "rollout-stale.jsonl"
    fresh = tmp_path / ".codex" / "sessions" / "2026" / "05" / "01" / "rollout-fresh.jsonl"
    stale.parent.mkdir(parents=True)
    stale.write_text('{"payload":{"cwd":"/other"}}\n', encoding="utf-8")
    fresh.write_text('{"payload":{"cwd":"/work/repo"}}\n', encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert _find_codex_transcript(None, cwd="/work/repo", started_after=0) == fresh
    assert _find_codex_transcript(None, cwd="/missing", started_after=0) is None
