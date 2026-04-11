"""Integration delivery contracts.

This package holds the abstractions every integration plugs into:

- `renderer.py` — `ChannelRenderer` Protocol + `DeliveryReceipt`
- `renderer_registry.py` — central registry keyed by `integration_id`

Concrete renderer implementations live under the top-level `integrations/`
package (per the project rule: "no integration-specific code in app/").
The Protocol and registry are integration-agnostic infrastructure, so
they live in `app/integrations/` alongside the rest of the core delivery
plumbing.

Phase B introduces these as inert scaffolding — `app/agent/dispatchers.py`
remains the live delivery path until Phases C–F migrate call sites and
real renderers register here.
"""
