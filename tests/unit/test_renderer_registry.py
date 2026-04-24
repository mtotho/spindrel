"""Phase B — tests for `app/integrations/renderer_registry.py`.

The renderer registry is the central directory of every integration's
`ChannelRenderer`. It must:

- Reject duplicate `integration_id` registrations (programmer error).
- Reject renderers without an `integration_id` ClassVar.
- Reject renderers whose `capabilities` ClassVar is not a `frozenset`.
- Return None on lookup miss (so callers can handle the absent case).
- Provide a snapshot view via `all_renderers()` for the lifespan startup
  loop.
"""
from __future__ import annotations

import pytest

from app.domain.capability import Capability
from app.integrations import renderer_registry
from app.integrations.renderer import ChannelRenderer, DeliveryReceipt
from app.services import integration_manifests as manifests_mod
from integrations.sdk import ToolResultRenderingSupport


class _FakeRenderer:
    """Minimal `ChannelRenderer` shape for registry testing.

    Doesn't subclass anything — Protocol satisfaction is structural.
    """

    integration_id = "fake"
    capabilities = frozenset({Capability.TEXT})

    async def render(self, event, target):  # noqa: D401
        return DeliveryReceipt.ok()

    async def handle_outbound_action(self, action, target):
        return DeliveryReceipt.ok()

    async def delete_attachment(self, attachment_metadata, target):
        return True


class _SecondRenderer:
    integration_id = "second"
    capabilities = frozenset({Capability.TEXT, Capability.STREAMING_EDIT})

    async def render(self, event, target):
        return DeliveryReceipt.ok()

    async def handle_outbound_action(self, action, target):
        return DeliveryReceipt.ok()

    async def delete_attachment(self, attachment_metadata, target):
        return False


@pytest.fixture(autouse=True)
def _clean_registry():
    renderer_registry.clear()
    before_manifests = dict(manifests_mod._manifests)
    yield
    renderer_registry.clear()
    manifests_mod._manifests.clear()
    manifests_mod._manifests.update(before_manifests)


class TestRegister:
    def test_register_then_get(self):
        r = _FakeRenderer()
        renderer_registry.register(r)
        assert renderer_registry.get("fake") is r

    def test_get_missing_returns_none(self):
        assert renderer_registry.get("nope") is None

    def test_duplicate_id_raises(self):
        renderer_registry.register(_FakeRenderer())
        with pytest.raises(ValueError, match="already registered"):
            renderer_registry.register(_FakeRenderer())

    def test_missing_integration_id_raises(self):
        class NoId:
            integration_id = ""
            capabilities = frozenset({Capability.TEXT})

            async def render(self, event, target): ...
            async def handle_outbound_action(self, action, target): ...
            async def delete_attachment(self, attachment_metadata, target): ...

        with pytest.raises(ValueError, match="non-empty"):
            renderer_registry.register(NoId())  # type: ignore[arg-type]

    def test_capabilities_must_be_frozenset(self):
        class MutableCaps:
            integration_id = "mut"
            capabilities = {Capability.TEXT}  # plain set, not frozen

            async def render(self, event, target): ...
            async def handle_outbound_action(self, action, target): ...
            async def delete_attachment(self, attachment_metadata, target): ...

        with pytest.raises(ValueError, match="frozenset"):
            renderer_registry.register(MutableCaps())  # type: ignore[arg-type]

    def test_capabilities_none_rejected(self):
        class NoneCaps:
            integration_id = "none"
            capabilities = None  # type: ignore[assignment]

            async def render(self, event, target): ...
            async def handle_outbound_action(self, action, target): ...
            async def delete_attachment(self, attachment_metadata, target): ...

        with pytest.raises(ValueError, match="frozenset"):
            renderer_registry.register(NoneCaps())  # type: ignore[arg-type]

    def test_manifest_tool_result_rendering_overrides_classvar(self):
        manifests_mod._manifests["fake"] = {
            "id": "fake",
            "capabilities": ["text", "rich_tool_results"],
            "tool_result_rendering": {
                "modes": ["full"],
                "content_types": ["application/vnd.spindrel.components+json"],
                "view_keys": ["core.search_results"],
            },
        }

        renderer_registry.register(_FakeRenderer())

        support = _FakeRenderer.tool_result_rendering
        assert isinstance(support, ToolResultRenderingSupport)
        assert support.content_types == frozenset({"application/vnd.spindrel.components+json"})
        assert support.view_keys == frozenset({"core.search_results"})

    def test_python_tool_result_rendering_dict_is_normalized(self):
        class RichRenderer(_FakeRenderer):
            integration_id = "rich"
            tool_result_rendering = {"content_types": ["text/plain"]}

        renderer_registry.register(RichRenderer())

        assert RichRenderer.tool_result_rendering.content_types == frozenset({"text/plain"})


class TestAllRenderers:
    def test_returns_snapshot(self):
        r1 = _FakeRenderer()
        r2 = _SecondRenderer()
        renderer_registry.register(r1)
        renderer_registry.register(r2)
        snap = renderer_registry.all_renderers()
        assert snap == {"fake": r1, "second": r2}

    def test_snapshot_is_independent_copy(self):
        renderer_registry.register(_FakeRenderer())
        snap = renderer_registry.all_renderers()
        snap["fake"] = "tampered"  # type: ignore[assignment]
        # Mutation of snapshot must not affect the registry.
        assert renderer_registry.get("fake").__class__ is _FakeRenderer


class TestUnregister:
    def test_unregister_removes_entry(self):
        renderer_registry.register(_FakeRenderer())
        renderer_registry.unregister("fake")
        assert renderer_registry.get("fake") is None

    def test_unregister_missing_is_noop(self):
        renderer_registry.unregister("nonexistent")  # no raise


class TestProtocolStructuralCheck:
    def test_fake_renderer_satisfies_protocol(self):
        # runtime_checkable Protocol verifies method names exist.
        assert isinstance(_FakeRenderer(), ChannelRenderer)
