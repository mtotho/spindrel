import uuid
from types import SimpleNamespace

from app.services.turn_worker import _parse_harness_explicit_tags
from app.services.agent_harnesses.turn_host import _build_harness_input_manifest


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
