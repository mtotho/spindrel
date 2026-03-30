"""GitHub integration hooks — metadata registration.

Registers the github: client_id prefix so channels auto-detect integration="github".
"""
from __future__ import annotations

from app.agent.hooks import IntegrationMeta, register_integration

register_integration(IntegrationMeta(
    integration_type="github",
    client_id_prefix="github:",
))
