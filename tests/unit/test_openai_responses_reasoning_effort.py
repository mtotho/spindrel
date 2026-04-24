"""Smoking-gun regression: the OpenAI Responses adapter must translate the
``reasoning_effort`` kwarg (emitted by ``translate_effort`` for openai-family
models) into the nested ``body.reasoning.effort`` key the Responses API
expects.

Before this fix, ``_build_request_body``'s passthrough list only forwarded
``reasoning`` (dict) — the flat ``reasoning_effort`` kwarg was silently
dropped. Codex / gpt-5-* / o4-mini bots thus never actually received the
effort knob, even though the UI + model_params pipeline claimed they did.
"""
from __future__ import annotations

from app.services.openai_responses_adapter import _build_request_body


USER_MESSAGE = [{"role": "user", "content": "hello"}]


class TestReasoningEffortForwarding:
    def test_high_effort_lands_in_body_reasoning_effort(self):
        body = _build_request_body(
            model="gpt-5-codex",
            messages=USER_MESSAGE,
            tools=None,
            tool_choice=None,
            stream=False,
            extra={"reasoning_effort": "high"},
        )
        assert body["reasoning"]["effort"] == "high", (
            "reasoning_effort was silently dropped at the adapter boundary — "
            "translate_effort's output never reaches the wire"
        )

    def test_medium_and_low_pass_through(self):
        for level in ("medium", "low"):
            body = _build_request_body(
                model="gpt-5",
                messages=USER_MESSAGE,
                tools=None,
                tool_choice=None,
                stream=False,
                extra={"reasoning_effort": level},
            )
            assert body["reasoning"]["effort"] == level

    def test_no_effort_leaves_summary_auto_default(self):
        """When effort is absent the adapter still sets summary=auto so the
        thinking panel streams — but must not invent an effort field."""
        body = _build_request_body(
            model="gpt-5-codex",
            messages=USER_MESSAGE,
            tools=None,
            tool_choice=None,
            stream=False,
            extra={},
        )
        assert body["reasoning"]["summary"] == "auto"
        assert "effort" not in body["reasoning"]

    def test_explicit_reasoning_dict_wins_over_flat_kwarg(self):
        """If a caller hand-rolls a `reasoning` dict with an explicit effort,
        that wins — the flat `reasoning_effort` kwarg only fills in the
        default via setdefault."""
        body = _build_request_body(
            model="gpt-5-codex",
            messages=USER_MESSAGE,
            tools=None,
            tool_choice=None,
            stream=False,
            extra={
                "reasoning_effort": "low",
                "reasoning": {"effort": "high", "summary": "detailed"},
            },
        )
        assert body["reasoning"]["effort"] == "high"
        assert body["reasoning"]["summary"] == "detailed"

    def test_reasoning_effort_and_summary_coexist(self):
        """Both the effort translation and the summary=auto default must land
        on the same reasoning sub-object — neither clobbers the other."""
        body = _build_request_body(
            model="gpt-5-codex",
            messages=USER_MESSAGE,
            tools=None,
            tool_choice=None,
            stream=False,
            extra={"reasoning_effort": "medium"},
        )
        assert body["reasoning"] == {"effort": "medium", "summary": "auto"}
