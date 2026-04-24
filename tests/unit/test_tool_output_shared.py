"""Unit tests for the shared tool-output SDK helpers.

These cover ``integrations.tool_output`` — the envelope→badge extractor
and the ``tool_output_display`` enum normalizer. Both are re-exported
via ``integrations.sdk`` for use by any renderer that wants compact
tool-call rendering.
"""
from __future__ import annotations

import pytest

from integrations.sdk import (
    ToolBadge,
    ToolOutputDisplay,
    ToolResultRenderingSupport,
    build_tool_result_presentation,
    extract_tool_badges,
)


class TestToolOutputDisplayNormalize:
    @pytest.mark.parametrize("value", ["compact", "full", "none"])
    def test_valid_values_pass_through(self, value):
        assert ToolOutputDisplay.normalize(value) == value

    def test_none_input_uses_default(self):
        assert ToolOutputDisplay.normalize(None) == "compact"

    def test_empty_string_uses_default(self):
        assert ToolOutputDisplay.normalize("") == "compact"

    def test_unknown_value_uses_default(self):
        assert ToolOutputDisplay.normalize("verbose") == "compact"

    def test_non_string_uses_default(self):
        assert ToolOutputDisplay.normalize(123) == "compact"

    def test_custom_default(self):
        assert ToolOutputDisplay.normalize("garbage", default="full") == "full"

    def test_enum_constants(self):
        assert ToolOutputDisplay.COMPACT == "compact"
        assert ToolOutputDisplay.FULL == "full"
        assert ToolOutputDisplay.NONE == "none"


class TestExtractToolBadges:
    def test_empty_input(self):
        assert extract_tool_badges([]) == []
        assert extract_tool_badges(None) == []  # type: ignore[arg-type]

    def test_single_envelope_with_tool_name_and_label(self):
        envelopes = [{
            "content_type": "application/vnd.spindrel.components+json",
            "tool_name": "get_weather",
            "display_label": "Lambertville, NJ",
        }]
        badges = extract_tool_badges(envelopes)
        assert badges == [ToolBadge(tool_name="get_weather", display_label="Lambertville, NJ")]

    def test_envelope_without_display_label(self):
        envelopes = [{"tool_name": "get_weather"}]
        badges = extract_tool_badges(envelopes)
        assert badges == [ToolBadge(tool_name="get_weather", display_label=None)]

    def test_empty_display_label_normalized_to_none(self):
        envelopes = [{"tool_name": "get_weather", "display_label": ""}]
        assert extract_tool_badges(envelopes)[0].display_label is None

    def test_legacy_envelope_without_tool_name_falls_back_to_generic(self):
        """Envelopes persisted before `tool_name` was added should still
        surface as a badge so users aren't surprised by silently-dropped
        tool invocations."""
        envelopes = [{"display_label": "Something"}]
        badges = extract_tool_badges(envelopes)
        assert badges == [ToolBadge(tool_name="tool", display_label="Something")]

    def test_dedups_identical_badges(self):
        envelopes = [
            {"tool_name": "get_weather", "display_label": "NJ"},
            {"tool_name": "get_weather", "display_label": "NJ"},
        ]
        badges = extract_tool_badges(envelopes)
        assert len(badges) == 1

    def test_preserves_distinct_labels(self):
        envelopes = [
            {"tool_name": "get_weather", "display_label": "NJ"},
            {"tool_name": "get_weather", "display_label": "CA"},
        ]
        assert len(extract_tool_badges(envelopes)) == 2

    def test_preserves_order(self):
        envelopes = [
            {"tool_name": "a"},
            {"tool_name": "b"},
            {"tool_name": "c"},
        ]
        assert [b.tool_name for b in extract_tool_badges(envelopes)] == ["a", "b", "c"]

    def test_skips_non_dict_entries(self):
        envelopes = [{"tool_name": "ok"}, "bogus", 42, None]  # type: ignore[list-item]
        badges = extract_tool_badges(envelopes)  # type: ignore[arg-type]
        assert [b.tool_name for b in badges] == ["ok"]

    def test_non_string_display_label_coerced(self):
        envelopes = [{"tool_name": "x", "display_label": 42}]
        assert extract_tool_badges(envelopes)[0].display_label == "42"


class TestBuildToolResultPresentation:
    def test_compact_mode_returns_badges_only(self):
        envelopes = [{"tool_name": "get_weather", "display_label": "NJ"}]

        presentation = build_tool_result_presentation(envelopes, display_mode="compact")

        assert presentation.cards == ()
        assert presentation.badges == (ToolBadge("get_weather", "NJ"),)

    def test_full_mode_turns_components_into_portable_card(self):
        envelopes = [{
            "content_type": "application/vnd.spindrel.components+json",
            "tool_name": "get_weather",
            "display_label": "Lambertville",
            "body": (
                '{"v":1,"components":['
                '{"type":"heading","text":"Lambertville, NJ"},'
                '{"type":"properties","items":[{"label":"Humidity","value":"69%"}]},'
                '{"type":"links","items":[{"title":"Forecast","url":"https://example.test"}]}'
                ']}'
            ),
        }]

        presentation = build_tool_result_presentation(envelopes, display_mode="full")

        assert len(presentation.cards) == 1
        card = presentation.cards[0]
        assert card.title == "Lambertville, NJ"
        assert card.fields[0].label == "Humidity"
        assert card.links[0].url == "https://example.test"
        assert presentation.unsupported_badges == ()

    def test_full_mode_badges_unsupported_envelopes(self):
        support = ToolResultRenderingSupport.from_manifest({
            "content_types": ["application/vnd.spindrel.components+json"],
            "unsupported_fallback": "badge",
        })
        envelopes = [{
            "content_type": "application/vnd.spindrel.html+interactive",
            "tool_name": "get_weather",
            "display_label": "Lambertville",
        }]

        presentation = build_tool_result_presentation(
            envelopes,
            display_mode="full",
            support=support,
        )

        assert presentation.cards == ()
        assert presentation.unsupported_badges == (ToolBadge("get_weather", "Lambertville"),)

    def test_core_search_results_view_key_supported_by_default(self):
        envelopes = [{
            "content_type": "application/vnd.spindrel.components+json",
            "view_key": "core.search_results",
            "tool_name": "web_search",
            "data": {
                "query": "espresso",
                "count": 1,
                "results": [{"title": "Result", "url": "https://example.test", "content": "Summary"}],
            },
        }]

        presentation = build_tool_result_presentation(envelopes, display_mode="full")

        assert presentation.cards[0].title == "Search: espresso"
        assert presentation.cards[0].status == "1 result(s)"
        assert presentation.cards[0].links[0].title == "Result"
