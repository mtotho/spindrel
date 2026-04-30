from __future__ import annotations

import importlib.util
import sys
import types
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType

import pytest

from app.db.engine import async_session
from app.services.agent_harnesses.base import (
    HarnessInputAttachment,
    HarnessInputManifest,
    TurnContext,
)


def _load_claude_harness_with_stubbed_sdk(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    import integrations.sdk as sdk

    monkeypatch.setattr(sdk, "register_runtime", lambda *_args, **_kwargs: None)
    prior_sdk = sys.modules.get("claude_agent_sdk")
    inserted_sdk = prior_sdk is None
    if inserted_sdk:
        sys.modules["claude_agent_sdk"] = types.ModuleType("claude_agent_sdk")
    module_name = f"_claude_harness_image_test_{uuid.uuid4().hex}"
    path = Path(__file__).parents[2] / "integrations" / "claude_code" / "harness.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
        if inserted_sdk:
            sys.modules.pop("claude_agent_sdk", None)
    return module


def _ctx(
    *,
    workdir: str,
    input_manifest: HarnessInputManifest | None = None,
) -> TurnContext:
    return TurnContext(
        spindrel_session_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        bot_id="test-bot",
        turn_id=uuid.uuid4(),
        workdir=workdir,
        harness_session_id=None,
        permission_mode="default",
        db_session_factory=async_session,
        input_manifest=input_manifest or HarnessInputManifest(),
    )


async def _collect_messages(stream: AsyncIterator[dict]) -> list[dict]:
    messages: list[dict] = []
    async for message in stream:
        messages.append(message)
    return messages


@pytest.mark.asyncio
async def test_claude_query_input_maps_inline_image_to_sdk_content_block(monkeypatch, tmp_path):
    module = _load_claude_harness_with_stubbed_sdk(monkeypatch)
    manifest = HarnessInputManifest(
        attachments=(
            HarnessInputAttachment(
                kind="image",
                source="inline_attachment",
                name="screen.png",
                mime_type="image/png",
                content_base64="AAA",
            ),
        )
    )

    query_input, runtime_items, warnings = module._build_claude_query_input(
        "Look.",
        _ctx(workdir=str(tmp_path), input_manifest=manifest),
    )
    assert not isinstance(query_input, str)
    messages = await _collect_messages(query_input)

    content = messages[0]["message"]["content"]
    assert content[0] == {"type": "text", "text": "Look."}
    assert content[1] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "AAA"},
    }
    assert runtime_items == (
        {
            "type": "image",
            "name": "screen.png",
            "path": None,
            "source": "inline_attachment",
        },
    )
    assert warnings == ()
    assert "AAA" not in str(manifest.metadata(runtime_items=runtime_items))


@pytest.mark.asyncio
async def test_claude_query_input_reads_workspace_image_inside_cwd(monkeypatch, tmp_path):
    module = _load_claude_harness_with_stubbed_sdk(monkeypatch)
    image_path = tmp_path / ".uploads" / "pixel.jpg"
    image_path.parent.mkdir()
    image_path.write_bytes(b"jpg-bytes")
    manifest = HarnessInputManifest(
        attachments=(
            HarnessInputAttachment(
                kind="image",
                source="channel_workspace",
                name="pixel.jpg",
                mime_type="image/jpeg",
                path=str(image_path),
                size_bytes=9,
            ),
        )
    )

    query_input, runtime_items, warnings = module._build_claude_query_input(
        "Describe it.",
        _ctx(workdir=str(tmp_path), input_manifest=manifest),
    )
    assert not isinstance(query_input, str)
    messages = await _collect_messages(query_input)

    image_block = messages[0]["message"]["content"][1]
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert image_block["source"]["data"] == "anBnLWJ5dGVz"
    assert runtime_items == (
        {
            "type": "image",
            "name": "pixel.jpg",
            "path": str(image_path),
            "source": "channel_workspace",
        },
    )
    assert warnings == ()


def test_claude_query_input_skips_workspace_image_outside_cwd(monkeypatch, tmp_path):
    module = _load_claude_harness_with_stubbed_sdk(monkeypatch)
    outside = tmp_path.parent / f"outside-{uuid.uuid4().hex}.png"
    outside.write_bytes(b"png")
    manifest = HarnessInputManifest(
        attachments=(
            HarnessInputAttachment(
                kind="image",
                source="channel_workspace",
                name="outside.png",
                mime_type="image/png",
                path=str(outside),
            ),
        )
    )

    query_input, runtime_items, warnings = module._build_claude_query_input(
        "Look.",
        _ctx(workdir=str(tmp_path), input_manifest=manifest),
    )

    assert query_input == "Look."
    assert runtime_items == ()
    assert "outside harness cwd" in warnings[0]
