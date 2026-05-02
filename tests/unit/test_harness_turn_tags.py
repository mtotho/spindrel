import uuid
from types import SimpleNamespace

import pytest

from app.services.turn_worker import _parse_harness_explicit_tags, _run_harness_branch_if_needed
from app.services.agent_harnesses.turn_host import (
    _build_harness_input_manifest,
    _normalize_harness_tool_envelope_ids,
)


def test_parse_harness_explicit_tags_extracts_unique_tools_and_skills():
    tools, skills = _parse_harness_explicit_tags(
        "Use @tool:web_search and @skill:widgets then @tool:web_search again."
    )

    assert tools == ("web_search",)
    assert skills == ("widgets",)


def test_parse_harness_explicit_tags_allows_path_style_skill_ids():
    tools, skills = _parse_harness_explicit_tags(
        "Review @skill:integrations/marp_slides/marp_slides with @tool:file."
    )

    assert tools == ("file",)
    assert skills == ("integrations/marp_slides/marp_slides",)


def test_parse_harness_explicit_tags_ignores_slack_mentions_and_email():
    tools, skills = _parse_harness_explicit_tags(
        "Ignore <@U123> and user@example.com but keep @tool:get_skill."
    )

    assert tools == ("get_skill",)
    assert skills == ()


def test_harness_input_manifest_keeps_inline_and_workspace_images(monkeypatch, tmp_path):
    channel_id = uuid.uuid4()
    root = tmp_path / "channel"
    upload = root / "data" / "screen.png"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"png")
    monkeypatch.setattr(
        "app.services.channel_workspace.get_channel_workspace_root",
        lambda channel_id, bot: str(root),
    )

    manifest = _build_harness_input_manifest(
        tagged_skill_ids=("review",),
        attachments=(
            {
                "type": "image",
                "name": "inline.png",
                "mime_type": "image/png",
                "content": "AAA",
                "attachment_id": "att-1",
            },
        ),
        msg_metadata={
            "workspace_uploads": [
                {
                    "filename": "screen.png",
                    "mime_type": "image/png",
                    "size_bytes": 3,
                    "path": "data/screen.png",
                },
                {
                    "filename": "notes.txt",
                    "mime_type": "text/plain",
                    "size_bytes": 4,
                    "path": "data/notes.txt",
                },
            ],
        },
        channel_id=channel_id,
        bot=SimpleNamespace(id="bot"),
    )

    assert manifest.tagged_skill_ids == ("review",)
    assert len(manifest.attachments) == 2
    assert manifest.attachments[0].source == "inline_attachment"
    assert manifest.attachments[0].content_base64 == "AAA"
    assert manifest.attachments[1].source == "channel_workspace"
    assert manifest.attachments[1].path == str(upload)
    assert "AAA" not in str(manifest.metadata())


def test_harness_tool_envelope_id_repair_uses_raw_provider_tool_call():
    raw_id = "toolu_01RUqTSr9wgVBAyc2oZWrvbJ"

    envelopes = _normalize_harness_tool_envelope_ids(
        [
            {
                "id": raw_id,
                "name": "mcp__spindrel__list_channels",
                "function": {"name": "mcp__spindrel__list_channels"},
            },
            {
                "id": f"auto:{raw_id}",
                "name": "auto-approved",
                "function": {"name": "auto-approved"},
            },
        ],
        [
            {
                "tool_call_id": "toolu_0[REDACTED]RUqTSr9wgVBAyc2oZWrvbJ",
                "content_type": "application/json",
                "body": "{}",
            }
        ],
    )

    assert envelopes[0]["tool_call_id"] == raw_id


@pytest.mark.asyncio
async def test_harness_branch_forwards_attachment_payload_to_harness_turn(monkeypatch):
    captured = {}

    async def fake_run_harness_turn(request):
        captured["request"] = request
        return "ok", None

    monkeypatch.setattr(
        "app.services.turn_worker._run_harness_turn",
        fake_run_harness_turn,
    )
    scope = SimpleNamespace(
        channel_id=uuid.uuid4(),
        bus_key=uuid.uuid4(),
        session_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        suppress_outbox=True,
    )
    state = SimpleNamespace(pre_user_msg_id=uuid.uuid4())
    req = SimpleNamespace(msg_metadata={"source": "test"})
    attachments = [{"type": "image", "content": "AAA", "mime_type": "image/png"}]

    handled = await _run_harness_branch_if_needed(
        scope,
        state,
        bot=SimpleNamespace(id="harness-bot", harness_runtime="claude-code"),
        req=req,
        user_message="/fixture-skill",
        att_payload=attachments,
    )

    assert handled is True
    assert captured["request"].harness_attachments == tuple(attachments)
    assert state.response_text == "ok"
    assert state.error_text is None
