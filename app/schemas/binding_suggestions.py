"""Canonical shape for integration `binding.suggestions_endpoint` responses.

Every integration that declares `binding.suggestions_endpoint` in
`integration.yaml` must return `list[BindingSuggestion]` from that endpoint.
The admin UI (`useBindingSuggestions` in `ui/src/api/hooks/useChannels.ts`)
consumes this shape directly — keep the two in sync.

See `docs/guides/integrations.md` § "Channel binding model" for the contract
and an example request/response.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BindingSuggestion(BaseModel):
    """One selectable option in the admin UI's binding picker.

    - ``client_id`` is the token that will be written to
      ``ChannelIntegration.client_id`` when the user selects this row (e.g.
      ``"slack:C01ABC123"``, ``"bb:iMessage;+;chat001"``,
      ``"wyoming:living-room-satellite"``).
    - ``display_name`` is the human-readable label the picker renders.
    - ``description`` is an optional secondary line (a channel topic, the
      preview of the last message, the satellite URI, etc.).
    - ``config_values`` pre-fills binding ``config_fields`` when the user
      selects this row — Wyoming uses it to stash the discovered ``satellite_uri``
      so the admin doesn't have to type it.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: str
    display_name: str
    description: str = ""
    config_values: dict[str, Any] | None = None


BindingSuggestions = list[BindingSuggestion]
"""Response alias — the endpoint returns a bare list, not an envelope."""


__all__ = ["BindingSuggestion", "BindingSuggestions"]
