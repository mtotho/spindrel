"""Integrations scenario — adopts a curated set so the Active list + detail
pages render with realistic, populated state instead of the universal
"Available - not adopted" zero-state.

Idempotent: ``set_integration_status`` no-ops when the status already matches.
Teardown reverts to ``available`` so reruns start from the same baseline.
"""
from __future__ import annotations

from . import StagedState
from ..client import SpindrelClient


# Curated for variety — each has a distinct integration-detail story:
#   github         — 9 events (PR/issue triggers)
#   homeassistant  — 6 tool widgets (HA control surfaces)
#   frigate        — webhook + skills + machine_control
#   web_search     — tool result cards (used as the chat hero later)
ADOPTED: tuple[str, ...] = (
    "github",
    "homeassistant",
    "frigate",
    "web_search",
)


def stage_integrations(client: SpindrelClient) -> StagedState:
    state = StagedState()
    for integration_id in ADOPTED:
        try:
            client.set_integration_status(integration_id=integration_id, status="enabled")
        except Exception as e:  # non-fatal — server may have removed an integration
            import logging
            logging.getLogger(__name__).warning(
                "could not enable %s (may not be installed on this instance): %s",
                integration_id, e,
            )
    return state


def teardown_integrations(client: SpindrelClient) -> None:
    for integration_id in ADOPTED:
        try:
            client.set_integration_status(integration_id=integration_id, status="available")
        except Exception:
            pass
