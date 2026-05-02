from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import Message, Session
from app.services.agent_harnesses.native_cli_mirror import (
    _is_native_cli_settings_management_record,
    _claude_project_dir_name,
    _find_claude_transcript,
    _find_codex_transcript,
    _parse_claude_jsonl_record,
    _parse_codex_jsonl_record,
    _persist_mirrored_record,
    _read_new_records,
    _sync_native_cli_settings,
    _native_cli_settings_patch,
    _native_session_id_from_transcript,
    _NativeCliInputSyncer,
    NativeCliMirrorRecord,
)
from app.services.agent_harnesses.session_state import load_latest_harness_metadata
from app.services.agent_harnesses.settings import load_session_settings
from tests.factories import build_bot, build_channel


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


def test_native_session_id_from_transcript_discovers_claude_and_codex_ids(tmp_path: Path):
    claude_path = tmp_path / "claude-session-123.jsonl"
    claude_path.write_text("{}\n", encoding="utf-8")
    codex_path = tmp_path / "rollout.jsonl"
    codex_path.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "id": "codex-thread-123",
                    "cwd": "/work/repo",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert _native_session_id_from_transcript(claude_path, runtime_name="claude-code") == "claude-session-123"
    assert _native_session_id_from_transcript(codex_path, runtime_name="codex") == "codex-thread-123"


def test_native_cli_terminal_input_syncer_extracts_submitted_setting_lines():
    syncer = _NativeCliInputSyncer(
        spindrel_session_id=uuid.uuid4(),
        runtime_name="codex",
    )

    assert syncer.feed(b"/model gpt-5.4-mini") == []
    assert syncer.feed(b"\r") == ["/model gpt-5.4-mini"]
    assert syncer.feed(b"/effort hig\x7fgh\n") == ["/effort high"]


def test_native_cli_settings_patch_parses_model_effort_and_clear_commands():
    assert _native_cli_settings_patch("/model gpt-5.4-mini") == {"model": "gpt-5.4-mini"}
    assert _native_cli_settings_patch("/effort medium") == {"effort": "medium"}
    assert _native_cli_settings_patch("/model default") == {"model": None}
    assert _native_cli_settings_patch("testing 123") == {}


def test_native_cli_settings_management_detection():
    assert _is_native_cli_settings_management_record(
        NativeCliMirrorRecord(key="codex:model", role="user", content="/model gpt-5.4-mini")
    )
    assert _is_native_cli_settings_management_record(
        NativeCliMirrorRecord(
            key="codex:model-ack",
            role="assistant",
            content="Using `gpt-5.4-mini` for this turn.",
        )
    )
    assert not _is_native_cli_settings_management_record(
        NativeCliMirrorRecord(key="codex:normal", role="assistant", content="Done.")
    )


@pytest.mark.asyncio
async def test_native_cli_model_and_effort_commands_sync_session_settings(db_session):
    bot = build_bot(id="native-cli-settings-bot", name="Harness", model="unused")
    bot.harness_runtime = "codex"
    channel = build_channel(bot_id=bot.id)
    session = Session(
        client_id="native-cli-settings-session",
        bot_id=bot.id,
        channel_id=channel.id,
    )
    db_session.add_all([bot, channel, session])
    await db_session.commit()

    await _sync_native_cli_settings(
        db_session,
        spindrel_session_id=session.id,
        runtime_name="codex",
        record=NativeCliMirrorRecord(
            key="codex:model",
            role="user",
            content="/model gpt-5.4-mini",
        ),
    )
    await _sync_native_cli_settings(
        db_session,
        spindrel_session_id=session.id,
        runtime_name="codex",
        record=NativeCliMirrorRecord(
            key="codex:effort",
            role="user",
            content="/effort medium",
        ),
    )

    settings = await load_session_settings(db_session, session.id)
    assert settings.model == "gpt-5.4-mini"
    assert settings.effort == "medium"


@pytest.mark.asyncio
async def test_native_cli_model_default_command_clears_session_model(db_session):
    bot = build_bot(id="native-cli-default-bot", name="Harness", model="unused")
    bot.harness_runtime = "codex"
    channel = build_channel(bot_id=bot.id)
    session = Session(
        client_id="native-cli-default-session",
        bot_id=bot.id,
        channel_id=channel.id,
        metadata_={"harness_settings": {"model": "gpt-5.4-mini", "effort": "medium"}},
    )
    db_session.add_all([bot, channel, session])
    await db_session.commit()

    await _sync_native_cli_settings(
        db_session,
        spindrel_session_id=session.id,
        runtime_name="codex",
        record=NativeCliMirrorRecord(
            key="codex:model-default",
            role="user",
            content="/model default",
        ),
    )

    settings = await load_session_settings(db_session, session.id)
    assert settings.model is None
    assert settings.effort == "medium"


@pytest.mark.asyncio
async def test_persist_mirrored_record_skips_duplicate_record_keys(db_session, tmp_path: Path):
    bot = build_bot(id="native-cli-dedupe-bot", name="Harness", model="unused")
    channel = build_channel(bot_id=bot.id)
    session = Session(
        client_id="native-cli-dedupe-session",
        bot_id=bot.id,
        channel_id=channel.id,
    )
    db_session.add_all([bot, channel, session])
    await db_session.commit()

    record = NativeCliMirrorRecord(key="codex:record-1", role="assistant", content="First result")
    for _ in range(2):
        await _persist_mirrored_record(
            spindrel_session_id=session.id,
            bot_id=bot.id,
            channel_id=channel.id,
            runtime_name="codex",
            native_session_id=None,
            transcript_path=tmp_path / "rollout.jsonl",
            record=record,
        )

    rows = (
        await db_session.scalars(
            select(Message).where(Message.session_id == session.id).order_by(Message.created_at)
        )
    ).all()
    assert [row.content for row in rows] == ["First result"]


@pytest.mark.asyncio
async def test_persist_mirrored_assistant_promotes_discovered_native_session_id(
    db_session,
    tmp_path: Path,
):
    bot = build_bot(id="native-cli-promote-bot", name="Harness", model="unused")
    bot.harness_runtime = "claude-code"
    channel = build_channel(bot_id=bot.id)
    session = Session(
        client_id="native-cli-promote-session",
        bot_id=bot.id,
        channel_id=channel.id,
    )
    db_session.add_all([bot, channel, session])
    await db_session.commit()

    transcript = tmp_path / "claude-native-session.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    await _persist_mirrored_record(
        spindrel_session_id=session.id,
        bot_id=bot.id,
        channel_id=channel.id,
        runtime_name="claude-code",
        native_session_id=None,
        transcript_path=transcript,
        record=NativeCliMirrorRecord(key="claude:record-1", role="assistant", content="CLI result"),
    )

    harness_meta, _ = await load_latest_harness_metadata(db_session, session.id)
    assert harness_meta is not None
    assert harness_meta["runtime"] == "claude-code"
    assert harness_meta["session_id"] == "claude-native-session"

    row = await db_session.scalar(select(Message).where(Message.session_id == session.id))
    assert row is not None
    assert row.metadata_["harness_native_cli"]["native_session_id"] == "claude-native-session"


@pytest.mark.asyncio
async def test_persist_mirrored_record_syncs_settings_without_chat_noise(db_session, tmp_path: Path):
    bot = build_bot(id="native-cli-settings-noise-bot", name="Harness", model="unused")
    channel = build_channel(bot_id=bot.id)
    session = Session(
        client_id="native-cli-settings-noise-session",
        bot_id=bot.id,
        channel_id=channel.id,
    )
    db_session.add_all([bot, channel, session])
    await db_session.commit()

    await _persist_mirrored_record(
        spindrel_session_id=session.id,
        bot_id=bot.id,
        channel_id=channel.id,
        runtime_name="codex",
        native_session_id=None,
        transcript_path=tmp_path / "rollout.jsonl",
        record=NativeCliMirrorRecord(key="codex:model", role="user", content="/model gpt-5.4-mini"),
    )
    await _persist_mirrored_record(
        spindrel_session_id=session.id,
        bot_id=bot.id,
        channel_id=channel.id,
        runtime_name="codex",
        native_session_id=None,
        transcript_path=tmp_path / "rollout.jsonl",
        record=NativeCliMirrorRecord(
            key="codex:model-ack",
            role="assistant",
            content="Using `gpt-5.4-mini` for this turn.",
        ),
    )

    rows = (await db_session.scalars(select(Message).where(Message.session_id == session.id))).all()
    settings = await load_session_settings(db_session, session.id)
    assert rows == []
    assert settings.model == "gpt-5.4-mini"
