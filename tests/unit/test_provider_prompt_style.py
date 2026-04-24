"""Provider/model-aware prompt style resolution."""
from types import SimpleNamespace

from app.services import providers


def test_get_prompt_style_uses_provider_model_pair(monkeypatch):
    monkeypatch.setattr(
        providers,
        "_prompt_style_by_provider_model",
        {
            ("anthropic", "shared-model"): "xml",
            ("openai", "shared-model"): "markdown",
        },
    )
    monkeypatch.setattr(providers, "_prompt_style_by_model", {"shared-model": "markdown"})

    assert providers.get_prompt_style("shared-model", "anthropic") == "xml"
    assert providers.get_prompt_style("shared-model", "openai") == "markdown"


def test_resolve_prompt_style_prefers_explicit_provider_override(monkeypatch):
    calls = []

    def fake_get_prompt_style(model, provider_id=None):
        calls.append((model, provider_id))
        return "xml"

    monkeypatch.setattr(providers, "get_prompt_style", fake_get_prompt_style)
    bot = SimpleNamespace(model="gpt-4", model_provider_id="openai")

    assert providers.resolve_prompt_style(
        bot,
        model_override="claude-opus-4-1",
        provider_id_override="anthropic",
    ) == "xml"
    assert calls == [("claude-opus-4-1", "anthropic")]


def test_resolve_prompt_style_uses_channel_provider_override(monkeypatch):
    calls = []

    def fake_get_prompt_style(model, provider_id=None):
        calls.append((model, provider_id))
        return "xml"

    monkeypatch.setattr(providers, "get_prompt_style", fake_get_prompt_style)
    bot = SimpleNamespace(model="gpt-4", model_provider_id="openai")
    channel = SimpleNamespace(model_override="claude-opus-4-1", model_provider_id_override="anthropic")

    assert providers.resolve_prompt_style(bot, channel) == "xml"
    assert calls == [("claude-opus-4-1", "anthropic")]
