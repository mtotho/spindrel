"""Tests for ``OpenAIResponsesAdapter._Images`` — the openai-subscription path
that translates ``client.images.generate / edit`` into Responses API calls
that force the built-in ``image_generation`` tool.
"""
from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services.openai_responses_adapter import (
    OpenAIResponsesAdapter,
    _parse_image_generation_response,
)


@pytest.fixture
async def adapter():
    async def _tokens():
        return {"access_token": "test-token", "account_id": "acct-123"}

    a = OpenAIResponsesAdapter(tokens_source=_tokens)
    yield a
    await a.aclose()


def _captured_post(post_mock):
    """Return the JSON body of the most recent .post() call."""
    return post_mock.call_args.kwargs["json"]


@pytest.mark.asyncio
async def test_generate_builds_image_generation_tool_request(adapter, monkeypatch):
    captured: dict = {}

    async def fake_post(self, url, *, headers, json):  # noqa: A002
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "output": [{
                    "type": "image_generation_call",
                    "result": "AAAA",
                }],
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    resp = await adapter.images.generate(model="gpt-image-1", prompt="a cat")

    assert captured["url"].endswith("/responses")
    body = captured["body"]
    assert body["model"] == "gpt-image-1"
    assert body["tools"] == [{"type": "image_generation"}]
    assert body["tool_choice"] == {"type": "image_generation"}
    assert body["stream"] is False
    assert body["store"] is False

    # User message contains the prompt as input_text, no input_image parts.
    user_msg = body["input"][0]
    assert user_msg["role"] == "user"
    assert user_msg["content"][0] == {"type": "input_text", "text": "a cat"}
    assert not any(p.get("type") == "input_image" for p in user_msg["content"])

    assert len(resp.data) == 1
    assert resp.data[0].b64_json == "AAAA"


@pytest.mark.asyncio
async def test_edit_attaches_input_image_parts(adapter, monkeypatch):
    captured: dict = {}

    async def fake_post(self, url, *, headers, json):  # noqa: A002
        captured["body"] = json
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "output": [{"type": "image_generation_call", "result": "BBBB"}],
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    raw = b"\x89PNG\r\n\x1a\nfake-bytes"
    await adapter.images.edit(
        model="gpt-image-1",
        prompt="make sky purple",
        image=("ref.png", raw, "image/png"),
        n=2,
        size="1024x1024",
    )

    body = captured["body"]
    user_content = body["input"][0]["content"]
    image_parts = [p for p in user_content if p.get("type") == "input_image"]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"].startswith("data:image/png;base64,")
    assert base64.b64encode(raw).decode() in image_parts[0]["image_url"]

    # Tool def carries n + size.
    tool_def = body["tools"][0]
    assert tool_def == {"type": "image_generation", "size": "1024x1024", "n": 2}


@pytest.mark.asyncio
async def test_edit_handles_list_of_images(adapter, monkeypatch):
    captured: dict = {}

    async def fake_post(self, url, *, headers, json):  # noqa: A002
        captured["body"] = json
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"output": [{"type": "image_generation_call", "result": "CCCC"}]},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    await adapter.images.edit(
        model="gpt-image-1",
        prompt="combine",
        image=[
            ("a.png", b"AAA", "image/png"),
            ("b.png", b"BBB", "image/png"),
        ],
    )

    body = captured["body"]
    image_parts = [p for p in body["input"][0]["content"] if p.get("type") == "input_image"]
    assert len(image_parts) == 2


def test_parse_image_generation_call_with_url():
    data = {"output": [{"type": "image_generation_call", "url": "https://x/y.png"}]}
    out = _parse_image_generation_response(data)
    assert len(out.data) == 1
    assert out.data[0].url == "https://x/y.png"
    assert out.data[0].b64_json is None


def test_parse_message_shaped_image_part():
    data = {
        "output": [{
            "type": "message",
            "content": [
                {"type": "output_text", "text": "here you go"},
                {"type": "image", "b64_json": "ZZZZ"},
            ],
        }],
    }
    out = _parse_image_generation_response(data)
    assert len(out.data) == 1
    assert out.data[0].b64_json == "ZZZZ"


def test_parse_empty_response():
    assert _parse_image_generation_response({}).data == []
    assert _parse_image_generation_response({"output": []}).data == []


@pytest.mark.asyncio
async def test_4xx_raises_openai_error(adapter, monkeypatch):
    async def fake_post(self, url, *, headers, json):  # noqa: A002
        return httpx.Response(
            400,
            request=httpx.Request("POST", url),
            json={"error": {"message": "model not found"}},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    import openai
    with pytest.raises(openai.BadRequestError):
        await adapter.images.generate(model="missing-model", prompt="x")
