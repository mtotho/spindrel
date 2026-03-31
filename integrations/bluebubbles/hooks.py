"""BlueBubbles integration hooks — metadata registration.

Registers the bb: client_id prefix so channels auto-detect integration="bluebubbles".
"""
from __future__ import annotations

from app.agent.hooks import IntegrationMeta, register_integration

register_integration(IntegrationMeta(
    integration_type="bluebubbles",
    client_id_prefix="bb:",
))
