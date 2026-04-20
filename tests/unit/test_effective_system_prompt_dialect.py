"""Integration tests: _effective_system_prompt applies dialect to framework
prompts only; the bot's own system_prompt is verbatim."""
from unittest.mock import patch

from app.agent.bots import BotConfig, MemoryConfig


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test",
        name="Test",
        model="gpt-4",
        system_prompt="VERBATIM_BOT_TEXT please_stay_exactly_as_authored",
        memory=MemoryConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


class TestEffectiveSystemPromptDialect:
    def test_markdown_style_renders_global_base_with_headings(self):
        from app.services.sessions import _effective_system_prompt

        with patch("app.services.providers.get_prompt_style", return_value="markdown"):
            bot = _make_bot()
            out = _effective_system_prompt(bot)

        assert "## Operating Rules" in out
        assert "<operating_rules>" not in out
        assert "{% section" not in out
        # Bot's own text appears verbatim
        assert "VERBATIM_BOT_TEXT please_stay_exactly_as_authored" in out

    def test_xml_style_wraps_framework_sections_in_tags(self):
        from app.services.sessions import _effective_system_prompt

        with patch("app.services.providers.get_prompt_style", return_value="xml"):
            bot = _make_bot()
            out = _effective_system_prompt(bot)

        assert "<operating_rules>" in out
        assert "</operating_rules>" in out
        # Markdown ## headers for dialected sections should NOT appear
        assert "## Operating Rules" not in out
        # Bot's own text appears verbatim — no wrapping applied to it
        assert "VERBATIM_BOT_TEXT please_stay_exactly_as_authored" in out
        # The bot's prompt contains no XML tags; must not be wrapped
        assert "<verbatim_bot_text" not in out.lower()

    def test_unknown_model_defaults_to_markdown(self):
        """Bot on a model with no provider_models row → get_prompt_style
        returns 'markdown' by default. Output must render markdown envelope."""
        from app.services.sessions import _effective_system_prompt

        bot = _make_bot(model="some-unregistered-model-id")
        out = _effective_system_prompt(bot)

        assert "## Operating Rules" in out
        assert "<operating_rules>" not in out

    def test_memory_scheme_prompt_respects_dialect(self):
        """When memory_scheme is workspace-files, DEFAULT_MEMORY_SCHEME_PROMPT
        also goes through the dialect renderer. {memory_rel} must still be
        filled by .format()."""
        from app.services.sessions import _effective_system_prompt

        with patch("app.services.providers.get_prompt_style", return_value="xml"):
            bot = _make_bot(memory_scheme="workspace-files")
            out = _effective_system_prompt(bot)

        # Memory section wrapped in XML tag
        assert "<memory>" in out
        assert "</memory>" in out
        # memory_rel placeholder filled — no raw `{memory_rel}` left
        assert "{memory_rel}" not in out

    def test_bot_prompt_with_special_chars_stays_verbatim(self):
        """Bot authored text with `{% section %}`-like sequences must NOT
        be transformed by the dialect renderer."""
        from app.services.sessions import _effective_system_prompt

        # Use an alternate verbatim marker that looks dialect-like; dialect
        # renderer only runs on the framework canonical, not bot.system_prompt.
        bot = _make_bot(
            system_prompt='BOT_PROMPT: use <tag> notation freely, it stays.',
        )
        with patch("app.services.providers.get_prompt_style", return_value="xml"):
            out = _effective_system_prompt(bot)

        assert "BOT_PROMPT: use <tag> notation freely, it stays." in out
