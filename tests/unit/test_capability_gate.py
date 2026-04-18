"""Unit tests for ``app.agent.capability_gate``.

The gate is the single structural fix that prevents the Slack-depth
Phase 3/4 class of bug: tools declare what a channel must be able to
*render* (``required_capabilities``) and what integration must be
*bound* (``required_integrations``), and the gate filters them out
of the LLM's per-turn tool list on any channel whose bindings can't
collectively honor those requirements.

Testing the pure function in isolation avoids pulling in the 1800-
line assembly path; an integration test that exercises the full
``assemble_context`` pipeline lives in the integration suite.
"""
from __future__ import annotations

import pytest

from app.agent.capability_gate import ChannelCapabilityView, build_view
from app.domain.capability import Capability


class TestBuildView:
    def test_empty_bindings_has_empty_capabilities(self):
        v = build_view([], {})
        assert v.bound_integrations == frozenset()
        assert v.union_capabilities == frozenset()

    def test_unions_capabilities_across_bindings(self):
        v = build_view(
            ["slack", "web"],
            {
                "slack": frozenset({Capability.TEXT, Capability.EPHEMERAL, Capability.MODALS}),
                "web": frozenset({Capability.TEXT, Capability.STREAMING_EDIT}),
            },
        )
        assert v.bound_integrations == frozenset({"slack", "web"})
        assert v.union_capabilities == frozenset({
            Capability.TEXT, Capability.EPHEMERAL, Capability.MODALS,
            Capability.STREAMING_EDIT,
        })

    def test_missing_renderer_contributes_nothing(self):
        v = build_view(["slack", "none"], {"slack": frozenset({Capability.TEXT})})
        assert v.bound_integrations == frozenset({"slack", "none"})
        assert v.union_capabilities == frozenset({Capability.TEXT})


class TestToolIsExposable:
    def test_unrestricted_tool_always_exposable(self):
        v = build_view([], {})
        assert v.tool_is_exposable(None, None)

    def test_required_capability_satisfied(self):
        v = build_view(
            ["slack"],
            {"slack": frozenset({Capability.TEXT, Capability.EPHEMERAL})},
        )
        assert v.tool_is_exposable(frozenset({Capability.EPHEMERAL}), None)

    def test_required_capability_not_satisfied(self):
        v = build_view(["web"], {"web": frozenset({Capability.TEXT})})
        assert not v.tool_is_exposable(frozenset({Capability.EPHEMERAL}), None)

    def test_required_integration_satisfied(self):
        v = build_view(["slack", "web"], {"slack": frozenset(), "web": frozenset()})
        assert v.tool_is_exposable(None, frozenset({"slack"}))

    def test_required_integration_not_satisfied(self):
        v = build_view(["web"], {"web": frozenset()})
        assert not v.tool_is_exposable(None, frozenset({"slack"}))

    def test_both_requirements_must_match(self):
        """respond_privately on a hypothetical web+EPHEMERAL channel with
        no slack binding is allowed (cap satisfied, no integration
        requirement). But a tool that requires BOTH an ephemeral capable
        surface AND a slack binding only passes on slack+ephemeral."""
        v = build_view(
            ["web"],
            {"web": frozenset({Capability.EPHEMERAL})},
        )
        # cap yes, integration no → drop.
        assert not v.tool_is_exposable(
            frozenset({Capability.EPHEMERAL}),
            frozenset({"slack"}),
        )
        # Same tool on a slack+web channel where slack has ephemeral → keep.
        v2 = build_view(
            ["web", "slack"],
            {"slack": frozenset({Capability.EPHEMERAL}), "web": frozenset()},
        )
        assert v2.tool_is_exposable(
            frozenset({Capability.EPHEMERAL}),
            frozenset({"slack"}),
        )


class TestRealisticGating:
    """The actual tools we annotated — make sure the gate does what the
    plan promised."""

    @pytest.fixture
    def slack_ephemeral_modals(self) -> ChannelCapabilityView:
        return build_view(
            ["slack"],
            {"slack": frozenset({
                Capability.TEXT, Capability.EPHEMERAL, Capability.MODALS,
            })},
        )

    @pytest.fixture
    def web_only(self) -> ChannelCapabilityView:
        return build_view(["none"], {})

    def test_respond_privately_hidden_on_web_only(self, web_only):
        # respond_privately declares required_capabilities={EPHEMERAL}.
        assert not web_only.tool_is_exposable(frozenset({Capability.EPHEMERAL}), None)

    def test_respond_privately_visible_on_slack(self, slack_ephemeral_modals):
        assert slack_ephemeral_modals.tool_is_exposable(
            frozenset({Capability.EPHEMERAL}), None,
        )

    def test_open_modal_hidden_on_web_only(self, web_only):
        assert not web_only.tool_is_exposable(frozenset({Capability.MODALS}), None)

    def test_slack_surface_tools_hidden_on_web_only(self, web_only):
        # slack_pin_message / slack_add_bookmark / slack_schedule_message
        # declare required_integrations={"slack"}.
        assert not web_only.tool_is_exposable(None, frozenset({"slack"}))

    def test_slack_surface_tools_visible_on_slack(self, slack_ephemeral_modals):
        assert slack_ephemeral_modals.tool_is_exposable(None, frozenset({"slack"}))
