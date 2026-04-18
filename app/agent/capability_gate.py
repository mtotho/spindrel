"""Capability-gated tool exposure.

Used by ``app.agent.context_assembly`` to drop tools whose
``required_capabilities`` / ``required_integrations`` the current
channel's bindings cannot satisfy — so the LLM never sees tools it
cannot action on this surface. Structural fix for the Slack-depth
Phase 3/4 bug (ephemeral / modals checked capability on a single
legacy binding instead of the multi-binding ``resolve_targets`` set).

The filter is a pure function of:

- the set of integrations bound to the channel, and
- the union of their renderer capabilities,

so it's trivially unit-testable without DB or bus.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.capability import Capability


@dataclass(frozen=True)
class ChannelCapabilityView:
    """Aggregate view of everything a channel's bindings can collectively do.

    ``bound_integrations`` — the set of integration ids bound to the
    channel (from ``resolve_targets``). Includes ``"none"`` for
    channels with no bindings; tools with ``required_integrations``
    are filtered against this set verbatim.

    ``union_capabilities`` — the union of ``renderer.capabilities``
    across every bound renderer. Tools with ``required_capabilities``
    are satisfied if the tool's required set is a subset.
    """

    bound_integrations: frozenset[str]
    union_capabilities: frozenset[Capability]

    def tool_is_exposable(
        self,
        required_capabilities: frozenset[Capability] | None,
        required_integrations: frozenset[str] | None,
    ) -> bool:
        if required_capabilities and not required_capabilities.issubset(self.union_capabilities):
            return False
        if required_integrations and not required_integrations.issubset(self.bound_integrations):
            return False
        return True


def build_view(
    bound_integrations: list[str],
    renderer_caps: dict[str, frozenset[Capability]],
) -> ChannelCapabilityView:
    """Assemble a ``ChannelCapabilityView`` from explicit inputs.

    ``renderer_caps`` maps integration_id → renderer.capabilities; a
    missing integration contributes the empty set (so an unregistered
    ``"none"`` binding is handled without a lookup).
    """
    union: frozenset[Capability] = frozenset()
    for iid in bound_integrations:
        union = union | renderer_caps.get(iid, frozenset())
    return ChannelCapabilityView(
        bound_integrations=frozenset(bound_integrations),
        union_capabilities=union,
    )
