"""Unit tests for extra_body merge in `_prepare_call_params`.

Smoking gun: a per-(provider, model) ``extra_body`` from ProviderModel must
land in the request kwargs even when the caller doesn't pass one — this is
the Ollama ``options.num_ctx`` foot-gun fix.
"""
from __future__ import annotations

import pytest


class TestDeepMergeDicts:
    def test_overlay_overrides_base_scalar(self):
        from app.agent.llm import _deep_merge_dicts

        assert _deep_merge_dicts({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested_dicts_merge_recursively(self):
        from app.agent.llm import _deep_merge_dicts

        assert _deep_merge_dicts(
            {"options": {"num_ctx": 1024, "temperature": 0.7}},
            {"options": {"num_ctx": 16384}},
        ) == {"options": {"num_ctx": 16384, "temperature": 0.7}}

    def test_overlay_dict_replaces_base_scalar(self):
        from app.agent.llm import _deep_merge_dicts

        # When base has a scalar at a key and overlay has a dict, overlay wins.
        assert _deep_merge_dicts(
            {"options": "off"}, {"options": {"num_ctx": 8}}
        ) == {"options": {"num_ctx": 8}}


def _stub_prepare_dependencies(monkeypatch, *, provider_extra_body=None, supports_vision=True):
    """Stub everything `_prepare_call_params` calls into so the merge logic is isolated."""
    monkeypatch.setattr(
        "app.services.providers.get_llm_client", lambda pid: object()
    )
    monkeypatch.setattr(
        "app.services.providers.model_supports_tools", lambda m: True
    )
    monkeypatch.setattr(
        "app.services.providers.model_supports_vision", lambda m: supports_vision
    )
    monkeypatch.setattr(
        "app.services.providers.requires_system_message_folding", lambda m: False
    )
    monkeypatch.setattr(
        "app.services.providers.resolve_provider_for_model", lambda m: "ollama-prov"
    )
    monkeypatch.setattr(
        "app.services.providers.get_provider_model_extra_body",
        lambda *_: dict(provider_extra_body or {}),
    )
    # Avoid prompt_cache lookup hitting an empty providers cache mid-test.
    monkeypatch.setattr(
        "app.agent.prompt_cache.should_apply_cache_control", lambda *a, **kw: False
    )


def test_provider_model_extra_body_flows_through(monkeypatch):
    """Smoking gun: an Ollama row with ``options.num_ctx=16384`` causes the
    eventual SDK kwargs to carry that value, even when the caller doesn't
    pass any extra_body of its own."""
    from app.agent import llm

    _stub_prepare_dependencies(
        monkeypatch, provider_extra_body={"options": {"num_ctx": 16384}}
    )

    params = llm._prepare_call_params(
        "qwen3-coder",
        messages=[{"role": "user", "content": "hi"}],
        tools_param=None,
        tool_choice=None,
        provider_id="ollama-prov",
        model_params=None,
    )

    assert params.extra.get("extra_body") is not None
    assert params.extra["extra_body"]["options"]["num_ctx"] == 16384


def test_prepare_call_preserves_inline_images_for_vision_model(monkeypatch):
    from app.agent import llm

    _stub_prepare_dependencies(monkeypatch, supports_vision=True)

    params = llm._prepare_call_params(
        "gpt-5.4",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "see attached"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
        tools_param=None,
        tool_choice=None,
        provider_id="chatgpt-subscription",
        model_params=None,
    )

    assert params.messages[0]["content"][1]["type"] == "image_url"


def test_prepare_call_strips_inline_images_for_non_vision_model(monkeypatch):
    from app.agent import llm

    _stub_prepare_dependencies(monkeypatch, supports_vision=False)

    params = llm._prepare_call_params(
        "gpt-5.4",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "see attached"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
        tools_param=None,
        tool_choice=None,
        provider_id="chatgpt-subscription",
        model_params=None,
    )

    content = params.messages[0]["content"]
    assert not any(part.get("type") == "image_url" for part in content)
    assert any("model does not support viewing images directly" in part.get("text", "") for part in content)


def test_caller_extra_body_overrides_provider_baseline(monkeypatch):
    """Resolution order: ProviderModel.extra_body < caller model_params.extra_body.

    Per-bot caller wants a 32K context but the admin baseline says 16K and also
    sets repeat_penalty. Result: caller's num_ctx wins, baseline's other keys
    survive via deep merge.
    """
    from app.agent import llm

    _stub_prepare_dependencies(
        monkeypatch,
        provider_extra_body={"options": {"num_ctx": 16384, "repeat_penalty": 1.1}},
    )

    params = llm._prepare_call_params(
        "qwen3-coder",
        messages=[{"role": "user", "content": "hi"}],
        tools_param=None,
        tool_choice=None,
        provider_id="ollama-prov",
        model_params={"extra_body": {"options": {"num_ctx": 32768}}},
    )

    assert params.extra["extra_body"]["options"]["num_ctx"] == 32768
    assert params.extra["extra_body"]["options"]["repeat_penalty"] == 1.1


def test_no_extra_body_when_neither_side_supplies(monkeypatch):
    """Sanity: when neither the provider baseline nor the caller pass anything,
    the request shouldn't get a stray empty extra_body key."""
    from app.agent import llm

    _stub_prepare_dependencies(monkeypatch, provider_extra_body=None)

    params = llm._prepare_call_params(
        "qwen3-coder",
        messages=[{"role": "user", "content": "hi"}],
        tools_param=None,
        tool_choice=None,
        provider_id="ollama-prov",
        model_params=None,
    )

    assert "extra_body" not in params.extra
