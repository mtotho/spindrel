---
tags: [agent-server, track, integrations, slack, sdk, rich-results]
status: active
created: 2026-04-24
updated: 2026-04-25
---
# Track — Integration Rich Results

## North Star

Make rich tool-result rendering a declared integration capability with a deep SDK boundary and thin platform adapters. Slack was the v1 pilot; Discord now uses the same presentation boundary through Discord embeds.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Capability + manifest support matrix | ✅ shipped |
| 2 | SDK presentation boundary | ✅ shipped |
| 3 | Slack read-only Block Kit adapter | ✅ shipped |
| 4 | Docs + import-boundary audit gate | ✅ shipped |
| 5 | Follow-up issue-template audit entries | ✅ shipped |
| 6 | Slack timeout hardening + Discord embed adapter | ✅ shipped |
| 7 | Slack/Discord/BlueBubbles SDK import boundary cleanup | ✅ shipped |
| 8 | Remaining integration SDK boundary cleanup | ✅ shipped |
| 9 | Prime-time depth contract harness + Slack approval presenter split | ✅ shipped |
| 10 | Slack transport + streaming deepening | ✅ shipped |
| 11 | Slack NEW_MESSAGE delivery deepening | ✅ shipped |
| 12 | Slack approval + ephemeral delivery deepening | ✅ shipped |
| 13 | Slack renderer dead component-converter cleanup | ✅ shipped |
| 14 | Slack attachment deletion delivery deepening | ✅ shipped |
| 15 | Integration renderer authoring rails | ✅ shipped |

## Current Implementation Shape

- `rich_tool_results` is advisory: `NEW_MESSAGE` text remains the durable delivery path.
- `tool_result_rendering` lives in `integration.yaml`; renderer ClassVar declarations are fallback only.
- `integrations.tool_output` owns support matching, portable read-only cards, badges, and fallback decisions.
- Slack translates portable cards to Block Kit in a platform adapter. Discord translates portable cards to embeds. `tool_output_display` still controls `compact | full | none`.
- A shared depth contract test now pins Slack/Discord rich-result support: manifest capabilities, renderer runtime capabilities, supported content types/view keys, non-interactive placement, and badge fallback must stay aligned.
- Slack approval Block Kit construction lives in a Slack-owned presenter module. `SlackApprovalDelivery` owns approval event delivery and imports that presenter boundary.
- Slack streaming delivery now lives in a dedicated Slack-owned module. `SlackRenderer` delegates streaming event kinds to it, preserving the placeholder lifecycle, coalesced `chat.update` behavior, and context handoff to durable `NEW_MESSAGE`.
- Slack durable `NEW_MESSAGE` delivery now lives in `SlackMessageDelivery`. The module owns UI-only/internal-role skips, Slack echo prevention, actor attribution, placeholder reuse/cleanup, thread targeting, rich-result block attachment, and final Slack `ts` receipt shaping.
- Slack ephemeral message delivery now lives in `SlackEphemeralDelivery`, keeping one-shot `chat.postEphemeral` policy out of the renderer.
- Slack attachment deletion now lives in `SlackAttachmentDelivery`, which owns both `ATTACHMENT_DELETED` event delivery and the public `delete_attachment(...) -> bool` renderer path used by admin attachment deletion.
- Slack renderer Web API calls now go through a dedicated receipt-shaped transport module; renderer tests patch that boundary directly.
- Slack renderer no longer carries the legacy component-vocabulary-to-Block-Kit converter; rich-result Block Kit mapping lives in `tool_result_adapter`.
- New integration renderer scaffolds now generate the Slack-style thin-router shape: `target.py`, `transport.py`, `message_delivery.py`, and `renderer.py`.
- Reusable renderer contract assertions live under `tests.helpers.integration_renderer_contracts` for capability parity, unsupported-event skip behavior, and safe delete-attachment defaults.
- Widget/component actions are out of scope for v1. Approvals remain on `approval_buttons`.
- Integration runtime modules now reach app-owned contracts through `integrations.sdk`; only infrastructure shims (`integrations/__init__.py`, `integrations/sdk.py`, `integrations/utils.py`) may import `app.*` directly.

## Verification

- `pytest tests/unit/test_tool_output_shared.py tests/unit/test_slack_tool_output_display.py tests/unit/test_integration_manifests.py tests/unit/test_renderer_registry.py tests/unit/test_canonical_docs_drift.py tests/unit/test_integration_import_boundary.py -q` passed: 87 passed, 17 skipped.
- `pytest tests/unit/test_capability_gate.py tests/unit/test_channel_renderers.py tests/unit/test_core_renderers.py -q` passed: 57 passed.
- `tests/unit/test_slack_renderer.py` timeout fixed by bounding the outbox poll inside `_wait_for_pending_outbox`.
- `pytest tests/unit/test_slack_renderer.py tests/unit/test_discord_renderer.py tests/unit/test_tool_output_shared.py tests/unit/test_slack_tool_output_display.py tests/unit/test_integration_manifests.py tests/unit/test_renderer_registry.py tests/unit/test_canonical_docs_drift.py tests/unit/test_integration_import_boundary.py -q` passed: 135 passed, 17 skipped.
- `pytest tests/unit/test_integration_import_boundary.py tests/unit/test_slack_config_bindings.py tests/unit/test_renderer_registry.py tests/unit/test_integration_manifests.py tests/unit/test_bluebubbles_renderer.py tests/unit/test_slack_renderer.py tests/unit/test_discord_renderer.py -q` passed locally: 124 passed, 23 skipped.
- `tests/unit/test_slack_config_bindings.py` local timeout fixed by applying the shared Python 3.14 + `aiosqlite<=0.22` skip guard to its private engine fixture; local run now skips fast (`6 skipped`) and remains runnable in the supported Python 3.12 test runtime.
- `pytest tests/unit/test_integration_import_boundary.py tests/unit/test_renderer_registry.py tests/unit/test_integration_manifests.py -q` passed locally: 49 passed, 17 skipped.
- `pytest tests/integration/test_binding_suggestions_shape.py -q` passed locally: 6 passed.
- `pytest tests/integration/test_integration_subprocess_imports.py -q` passed locally: 2 passed, 3 skipped.
- Import smoke for `integrations.sdk`, web search config, Wyoming config, Claude Code executor, and Google Workspace tools passed locally.
- `pytest tests/unit/test_integration_depth_contract.py tests/unit/test_slack_renderer.py tests/unit/test_discord_renderer.py tests/unit/test_tool_output_shared.py tests/unit/test_slack_tool_output_display.py tests/unit/test_integration_manifests.py tests/unit/test_renderer_registry.py tests/unit/test_integration_import_boundary.py -q` passed locally: 137 passed, 17 skipped.
- `PYTHONDONTWRITEBYTECODE=1 python -c "import integrations.slack.renderer; import integrations.discord.renderer; print('renderer imports ok')"` passed locally.
- `pytest tests/unit/test_slack_transport.py tests/unit/test_slack_renderer.py tests/integration/test_slack_end_to_end.py tests/unit/test_slack_tool_output_display.py tests/unit/test_slack_ephemeral.py tests/unit/test_integration_depth_contract.py tests/unit/test_integration_import_boundary.py -q` passed locally: 63 passed, 3 warnings.
- `PYTHONDONTWRITEBYTECODE=1 python -c "import integrations.slack.renderer; print('slack renderer import ok')"` passed locally.
- `pytest tests/unit/test_slack_message_delivery.py tests/unit/test_slack_renderer.py tests/unit/test_slack_tool_output_display.py tests/integration/test_slack_end_to_end.py tests/unit/test_slack_transport.py tests/unit/test_slack_ephemeral.py tests/unit/test_integration_depth_contract.py tests/unit/test_integration_import_boundary.py -q` passed locally: 65 passed, 3 warnings.
- `pytest tests/unit/test_slack_approval_delivery.py tests/unit/test_slack_message_delivery.py tests/unit/test_slack_renderer.py tests/unit/test_slack_tool_output_display.py tests/integration/test_slack_end_to_end.py tests/unit/test_slack_transport.py tests/unit/test_slack_ephemeral.py tests/unit/test_integration_depth_contract.py tests/unit/test_integration_import_boundary.py -q` passed locally: 67 passed, 3 warnings.
- `pytest tests/unit/test_slack_approval_delivery.py tests/unit/test_slack_message_delivery.py tests/unit/test_slack_renderer.py tests/unit/test_slack_tool_output_display.py tests/integration/test_slack_end_to_end.py tests/unit/test_slack_transport.py tests/unit/test_slack_ephemeral.py tests/unit/test_integration_depth_contract.py tests/unit/test_integration_import_boundary.py -q` passed locally after the dead-code cleanup: 67 passed, 3 warnings.
- `pytest tests/unit/test_slack_attachment_delivery.py tests/unit/test_slack_renderer.py -q` passed locally: 32 passed, 2 warnings.
- `pytest tests/unit/test_slack_attachment_delivery.py tests/unit/test_slack_renderer.py tests/unit/test_slack_approval_delivery.py tests/unit/test_slack_message_delivery.py tests/unit/test_slack_ephemeral.py tests/unit/test_slack_transport.py tests/unit/test_integration_depth_contract.py tests/unit/test_integration_import_boundary.py -q` passed locally after attachment delivery extraction: 62 passed, 3 warnings.
- `pytest tests/unit/test_slack_attachment_delivery.py tests/unit/test_slack_approval_delivery.py tests/unit/test_slack_message_delivery.py tests/unit/test_slack_renderer.py tests/unit/test_slack_tool_output_display.py tests/integration/test_slack_end_to_end.py tests/unit/test_slack_transport.py tests/unit/test_slack_ephemeral.py tests/unit/test_integration_depth_contract.py tests/unit/test_integration_import_boundary.py -q` passed locally after attachment delivery extraction: 78 passed, 3 warnings.
- `PYTHONDONTWRITEBYTECODE=1 python -c "import integrations.slack.renderer; print('slack renderer import ok')"` passed locally after attachment delivery extraction.
- `git diff --check -- integrations/slack/renderer.py integrations/slack/attachment_delivery.py tests/unit/test_slack_attachment_delivery.py tests/unit/test_slack_renderer.py project-notes/Track\ -\ Integration\ Rich\ Results.md` passed locally. Unscoped `git diff --check` is blocked by unrelated spatial-canvas WIP whitespace.
- `pytest tests/unit/test_integration_reload.py::TestScaffold::test_scaffold_renderer_feature_generates_target_and_renderer tests/unit/test_integration_reload.py::TestScaffold::test_scaffold_all_features -q` passed locally after renderer scaffold rails: 2 passed.
- `pytest tests/unit/test_integration_depth_contract.py -q` passed locally after renderer contract helper adoption: 6 passed.
- `pytest tests/unit/test_integration_reload.py tests/unit/test_integration_depth_contract.py tests/unit/test_integration_import_boundary.py tests/unit/test_canonical_docs_drift.py tests/unit/test_renderer_registry.py -q` passed locally after renderer authoring rails: 44 passed.
- `PYTHONDONTWRITEBYTECODE=1 python -c "import app.tools.local.admin_integrations; import tests.helpers.integration_renderer_contracts; print('integration rails imports ok')"` passed locally.
- Broader websocket/TestClient suites still time out in this Python 3.14 local environment: even a minimal `FastAPI()` + `TestClient` context hangs before app code runs. Treat those as environment verification gaps, not integration boundary regressions.

## Audit Issues

### Rich tool-result rendering boundary

**Problem:** Slack had component-only rich rendering embedded inside the large renderer, with no explicit platform capability matrix and no SDK-level contract for other integrations.

**Proposed Interface:** Renderers call the SDK presentation helper with persisted tool envelopes, display mode, and declared support. The helper returns cards, badges, and unsupported fallbacks.

**Dependency Strategy:** In-process. Slack API remains the renderer's external boundary and is mocked in renderer tests.

**Testing Strategy:** Boundary tests for SDK normalization; thin Slack adapter/renderer tests for Block Kit output and mode branching.

**Implementation Recommendations:** Keep support matching, fallback policy, and portable card construction out of platform renderers. Platform adapters should only map card primitives to native blocks/embeds/messages.

### SDK-only integration import boundary

**Problem:** Direct `app.*` imports still existed under integration runtime modules, despite the canonical SDK-only target. This made the app/integration boundary harder to reason about.

**Proposed Interface:** Integration authors import app-owned contracts through `integrations.sdk`. Infrastructure shims own the app bridge; runtime integrations do not import `app.*` directly.

**Dependency Strategy:** In-process for registry/static checks. No runtime dependency change required for existing debt.

**Testing Strategy:** Enforce an AST boundary test for direct `app.*` imports under `integrations/`; only `__init__.py`, `sdk.py`, and `utils.py` are exempt.

**Implementation Recommendations:** Add SDK exports when an integration needs an app-owned contract. Do not add new runtime `app.*` imports under integration packages.

### Slack renderer size

**Problem:** Slack renderer historically owned streaming, durable message delivery, approvals, files, modals, reactions, and tool-result rendering in one module.

**Proposed Interface:** Extract real presentation/delivery boundaries first. Tool-result Block Kit mapping lives in the platform adapter; approval Block Kit mapping lives in `approval_blocks`; streaming, durable `NEW_MESSAGE`, approvals, and ephemerals now live behind Slack-owned delivery modules. Defer broader renderer decomposition until each split can own a stable policy boundary.

**Dependency Strategy:** True external boundary remains Slack Web API; tests keep using fake HTTP.

**Testing Strategy:** Preserve renderer routing tests, move behavior tests to the deep delivery/presenter boundary, contract-test rich-result support, and add adapter-focused coverage as more presenter modules are split.

**Implementation Recommendations:** Split by platform concern only when a module can own a real policy boundary.

### Slack transport + streaming deepening

**Problem:** `SlackRenderer` still owned Slack Web API receipt semantics and streaming placeholder lifecycle directly, making the module harder to extend without disturbing the original mobile-refresh race fix.

**Proposed Interface:** `integrations.slack.transport.call_slack(...)` owns receipt-shaped Slack Web API calls. `SlackStreamingDelivery.render(event, target)` owns streaming event kinds only. `SlackRenderer.render(...)` remains the public integration renderer interface.

**Dependency Strategy:** True external boundary remains Slack Web API and is mocked at `integrations.slack.transport._http`. Streaming is in-process over the existing render context registry.

**Testing Strategy:** Transport semantics have focused unit coverage. Existing Slack renderer and end-to-end streaming tests still assert placeholder posting, bounded `chat.update` coalescing, error finalization, context handoff, rich result blocks, and ephemeral delivery.

**Implementation Recommendations:** Keep tool-facing `web_api.py` separate from renderer transport; tools still want exception-shaped Slack calls, while renderers need `DeliveryReceipt` semantics.

### Slack NEW_MESSAGE delivery deepening

**Problem:** Durable Slack `NEW_MESSAGE` delivery still lived inside `SlackRenderer`, mixing renderer routing with outbox delivery policy, rich-result attachment, placeholder handoff, and echo prevention.

**Proposed Interface:** `SlackMessageDelivery.render(event, target)` owns durable message delivery. `SlackRenderer.render(...)` only routes `NEW_MESSAGE` to that deep module.

**Dependency Strategy:** True external boundary remains Slack Web API through `integrations.slack.transport.call_slack`. Channel display-mode lookup remains an SDK boundary via `integrations.sdk.get_channel_for_integration`.

**Testing Strategy:** `NEW_MESSAGE` behavior tests moved to `test_slack_message_delivery.py`; renderer keeps a small routing smoke test. Tool-output display tests now patch `integrations.slack.message_delivery.resolve_tool_output_display`.

**Implementation Recommendations:** Keep `MESSAGE_UPDATED` and attachment deletion in the renderer until each has a stable policy boundary worth extracting. Leave legacy component-converter cleanup for a separate dead-code pass.

### Slack renderer dead component-converter cleanup

**Problem:** `SlackRenderer` still carried unused legacy component-vocabulary helpers after rich-result rendering moved to `tool_result_adapter`.

**Proposed Interface:** No new interface. Delete unused renderer-local conversion helpers and rely on `tool_result_adapter` for Block Kit rich-result mapping.

**Dependency Strategy:** In-process cleanup. No dependency behavior changed.

**Testing Strategy:** Grep verified no active references remained; the Slack delivery/depth/import suite stayed green.

**Implementation Recommendations:** Keep dead-code cleanup separate from delivery-boundary changes so behavior movement and deletion remain easy to audit.

### Slack approval + ephemeral delivery deepening

**Problem:** Approval request and ephemeral message delivery still lived in `SlackRenderer`, mixing event routing with small but real delivery policies.

**Proposed Interface:** `SlackApprovalDelivery.render(event, target)` owns `APPROVAL_REQUESTED` delivery. `SlackEphemeralDelivery.render(event, target)` owns `EPHEMERAL_MESSAGE` delivery. `SlackRenderer.render(...)` only routes those event kinds.

**Dependency Strategy:** True external boundary remains Slack Web API through `integrations.slack.transport.call_slack`. Approval presentation remains in `approval_blocks`.

**Testing Strategy:** Approval behavior moved to `test_slack_approval_delivery.py`; ephemeral behavior now tests `SlackEphemeralDelivery` directly. Renderer keeps routing smoke coverage for both event kinds.

**Implementation Recommendations:** Keep attachment deletion and the not-yet-wired `MESSAGE_UPDATED` skip in the renderer for now. The next cleanup pass should remove unused legacy component-vocabulary helpers if grep proves they are dead.

### Slack attachment deletion delivery deepening

**Problem:** Slack file deletion still lived in `SlackRenderer` across two entry points: the event-driven `ATTACHMENT_DELETED` path and the public `delete_attachment(...) -> bool` method used by admin attachment deletion.

**Proposed Interface:** `SlackAttachmentDelivery.render(event, target)` owns `ATTACHMENT_DELETED`; `SlackAttachmentDelivery.delete_attachment(metadata, target)` owns the direct renderer-protocol deletion path.

**Dependency Strategy:** True external boundary remains Slack `files.delete`, injected as a `delete_file(token, file_id)` callable for tests and defaulting to `integrations.slack.uploads.delete_slack_file`.

**Testing Strategy:** New boundary tests cover event deletion success/skip/failure/exception and direct deletion target/token/file-id guards. Renderer tests only assert delegation.

**Implementation Recommendations:** Treat Slack renderer as complete after this local split except for the explicit `MESSAGE_UPDATED` no-op, which should stay in the router until upstream publishers carry an addressable Slack `ts`.

### Integration renderer authoring rails

**Problem:** The scaffolded renderer still taught the old shape: direct `app.*` imports, module-local `httpx`, and `_handle_*` methods in `renderer.py`, which encouraged every new integration to grow another shallow god renderer.

**Proposed Interface:** `manage_integration(..., features=["renderer"])` now creates `target.py`, `transport.py`, `message_delivery.py`, and a thin `renderer.py`. `docs/guides/integrations.md` documents the recommended optional modules for streaming, approvals, and attachment deletion.

**Dependency Strategy:** True external platform calls are isolated behind `transport.py` or injected delivery callables. Integration runtime code imports app-owned contracts through `integrations.sdk`.

**Testing Strategy:** Scaffold tests assert the generated files and thin-router imports. `tests.helpers.integration_renderer_contracts` provides reusable assertions, and the rich-result depth contract uses them for Slack/Discord parity and safe default behavior.

**Implementation Recommendations:** New first-party integrations should start with the scaffold and grow by adding delivery modules, not renderer-private handlers. Keep renderer tests as routing smoke; move behavior tests to the delivery module that owns the policy.

### Discord capability truth

**Problem:** Discord's manifest advertised `threading` even though the renderer tests explicitly say Discord delivery does not model Discord threads yet.

**Proposed Interface:** Manifest capabilities and renderer runtime capabilities must describe only behavior the renderer actually supports.

**Dependency Strategy:** In-process contract validation. Discord's REST API remains the true external boundary for renderer delivery tests.

**Testing Strategy:** The shared depth contract now fails when rich-result capable renderers drift between manifest truth and runtime truth.

**Implementation Recommendations:** Do not use YAML capabilities as product aspiration. Put planned capability expansion in the track, then add the manifest capability only when the renderer and tests support it.

### BlueBubbles renderer deepening and capability truth

**Problem:** BlueBubbles delivery lived in one broad renderer that mixed BB HTTP transport, durable text delivery, echo tracking, approvals, typing, uploads, and target validation. The manifest also advertised platform capabilities the renderer did not actually provide, including threading, approval buttons, display names, and generic attachments.

**Proposed Interface:** `BlueBubblesRenderer` stays the public ChannelRenderer and delegates to BlueBubbles-owned delivery modules: `message_delivery`, `approval_delivery`, `upload_delivery`, and `lifecycle_delivery`. `transport` owns receipt-shaped BB API calls for renderer delivery.

**Dependency Strategy:** True external boundary is the BlueBubbles REST API and is injected/mocked at the transport/delivery boundary. Inbound intake remains webhook-only; the legacy Socket.IO client is disabled and retained only as reference code.

**Testing Strategy:** Boundary tests cover transport result mapping, upload behavior, and renderer routing. The shared integration depth contract now includes BlueBubbles for manifest/runtime capability parity and default renderer protocol behavior.

**Implementation Recommendations:** BlueBubbles should declare only text, image upload, file upload, and typing indicator until richer platform behavior is actually implemented. Keep replies/tapbacks/threading out of manifest truth until selected-message GUID handling and Private API requirements are designed and tested.

## References

- `docs/guides/integrations.md`
- `docs/guides/slack.md`
- [[Track - Integration Contract]]
- [[Track - Integration DX]]
- [[Track - Integration Delivery]]
- [[Track - Code Quality]]
