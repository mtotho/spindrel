"""Cluster 4A guardrail — every ``ChannelEventKind`` must have a UI
consumer (or an explicit allowlist entry explaining why it doesn't).

`feedback_bus_contract_end_to_end.md` recorded a failure where three
event-bus layers silently lacked wiring while both endpoints looked
complete. This test is the end-to-end drift guard. If it fails, either:

- Add a ``case "<kind_value>":`` in
  ``ui/src/api/hooks/useChannelEvents.ts`` that dispatches to the
  chat store, or
- Add an entry to ``ALLOWLIST`` below pointing at where the kind is
  actually consumed (widget iframe observer path, agent-side waiter,
  integration renderer, etc.), or
- Remove the kind from ``ChannelEventKind`` and its payload union.

Skip-not-fail when ``ui/`` is absent (Docker test image per
``feedback_docker_test_no_ui.md``).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.domain.channel_events import ChannelEventKind


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_FILE = _REPO_ROOT / "ui" / "src" / "api" / "hooks" / "useChannelEvents.ts"


# Kinds deliberately not handled in ``useChannelEvents``. Each entry
# MUST name where the kind is consumed (or say "no consumer — reason").
ALLOWLIST: dict[str, str] = {
    "widget_reload": (
        "Consumed only by widget iframe subscribers — see "
        "ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx "
        "(spindrel.stream subscription in the widget preamble)."
    ),
    "modal_submitted": (
        "Consumed by the agent-side modal waiter on the backend; "
        "app-chrome has no rendering responsibility."
    ),
    "ephemeral_message": (
        "Publisher-side fallback in app/services/ephemeral_dispatch.py "
        "rewrites to new_message for renderers lacking "
        "Capability.EPHEMERAL; widget iframes observe via the observer "
        "path (publishChannelEvent in useChannelEvents)."
    ),
    "session_plan_updated": (
        "Consumed by ui/app/(app)/channels/[channelId]/useSessionPlanMode.ts "
        "via a focused raw channel-events stream subscription — the "
        "hook bypasses the main switch to keep plan state self-contained."
    ),
    "attachment_deleted": (
        "Consumed by integration renderers (Slack / Discord file-delete "
        "surfaces); app-chrome has no attachment-delete view to update."
    ),
    "heartbeat_tick": (
        "Infrastructure liveness signal with no app-chrome consumer. "
        "Widget iframes can observe it via the iframe subscribe path."
    ),
    "workflow_progress": (
        "Workflows are deprecated per Roadmap.md (UI hidden, backend "
        "dormant). No active app-chrome consumer; leave room for "
        "re-wiring if workflows return."
    ),
    "tool_activity": (
        "Ambient backend tool-activity ticks; widget iframes observe "
        "via the iframe subscribe path (ContextTrackerWidget, etc.)."
    ),
    "memory_scheme_bootstrap": (
        "Emitted as an observability signal when workspace-files bots "
        "bootstrap MEMORY.md. Widget iframes can observe via the "
        "iframe subscribe path; no app-chrome consumer by design."
    ),
}


def _load_ts_source() -> str:
    if not _TS_FILE.is_file():
        pytest.skip(f"frontend source not available at {_TS_FILE}")
    return _TS_FILE.read_text()


def _switch_cases(src: str) -> set[str]:
    """Every ``case "foo":`` string literal inside useChannelEvents.ts.

    Cheap and resilient — the switch lives in a single file and every
    case in the file is a channel-event kind.
    """
    return set(re.findall(r'case\s+"([a-z_]+)"\s*:', src))


def test_every_channel_event_kind_is_handled_or_allowlisted() -> None:
    src = _load_ts_source()
    cases = _switch_cases(src)

    unhandled: list[str] = []
    for kind in ChannelEventKind:
        value = kind.value
        if value in cases:
            continue
        if value in ALLOWLIST:
            continue
        unhandled.append(value)

    if unhandled:
        raise AssertionError(
            "ChannelEventKind values missing from useChannelEvents switch "
            "without an ALLOWLIST entry:\n"
            + "\n".join(f"  - {v}" for v in sorted(unhandled))
            + "\n\nAdd a case in "
            + str(_TS_FILE.relative_to(_REPO_ROOT))
            + " OR add to ALLOWLIST in "
            + str(Path(__file__).relative_to(_REPO_ROOT))
            + " (with a comment naming where the kind IS consumed), "
            + "OR remove the kind from app/domain/channel_events.py."
        )


def test_allowlist_only_references_real_enum_values() -> None:
    """The allowlist can't outlive its referents — catches typos and
    stale entries after someone renames / removes an enum value."""
    enum_values = {k.value for k in ChannelEventKind}
    stale = sorted(k for k in ALLOWLIST if k not in enum_values)
    assert not stale, (
        f"ALLOWLIST entries reference values not in ChannelEventKind: {stale}. "
        "Remove them from ALLOWLIST."
    )
