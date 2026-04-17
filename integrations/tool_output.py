"""Shared helpers for integration-level tool-output rendering.

Renderers that want to surface tool invocations in chat (as compact
"badges", full rich widgets, or nothing at all) pull their primitives
from here so the logic stays consistent across platforms. Platform-
specific presentation (Slack Block Kit, Discord embeds, iMessage text)
stays in each renderer — this module only produces the structured
inputs (`ToolBadge`) and normalizes the `tool_output_display` setting.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ToolOutputDisplayValue = Literal["compact", "full", "none"]
_VALID: tuple[ToolOutputDisplayValue, ...] = ("compact", "full", "none")


class ToolOutputDisplay:
    """Namespace for `tool_output_display` enum handling."""

    COMPACT: ToolOutputDisplayValue = "compact"
    FULL: ToolOutputDisplayValue = "full"
    NONE: ToolOutputDisplayValue = "none"

    @staticmethod
    def normalize(value: object, default: ToolOutputDisplayValue = "compact") -> ToolOutputDisplayValue:
        """Coerce arbitrary input to a valid display mode, falling back to default."""
        if isinstance(value, str) and value in _VALID:
            return value  # type: ignore[return-value]
        return default


@dataclass(frozen=True)
class ToolBadge:
    """A one-line summary of a tool invocation for compact chat rendering."""

    tool_name: str
    display_label: str | None = None


_COMPONENT_CT = "application/vnd.spindrel.components+json"


def extract_tool_badges(tool_results: list[dict]) -> list[ToolBadge]:
    """Pull compact badges from persisted `Message.metadata["tool_results"]`.

    Each envelope in ``tool_results`` is the output of
    ``ToolResultEnvelope.compact_dict``. We take `tool_name` and
    `display_label` from each envelope, skip entries without a tool
    name, and de-dup identical (tool_name, display_label) pairs while
    preserving order (so a turn that called get_weather once shows one
    badge, not two).
    """
    badges: list[ToolBadge] = []
    seen: set[tuple[str, str | None]] = set()
    for env in tool_results or []:
        if not isinstance(env, dict):
            continue
        tool_name = (env.get("tool_name") or "").strip()
        if not tool_name:
            # Envelopes from before tool_name was added — fall back to
            # the generic "tool" label so users still see *something*
            # rather than the envelope being silently skipped.
            tool_name = "tool"
        label = env.get("display_label")
        if label is not None and not isinstance(label, str):
            label = str(label)
        if label == "":
            label = None
        key = (tool_name, label)
        if key in seen:
            continue
        seen.add(key)
        badges.append(ToolBadge(tool_name=tool_name, display_label=label))
    return badges


__all__ = [
    "ToolBadge",
    "ToolOutputDisplay",
    "ToolOutputDisplayValue",
    "extract_tool_badges",
]
