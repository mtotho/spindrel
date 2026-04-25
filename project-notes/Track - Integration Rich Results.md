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

## Current Implementation Shape

- `rich_tool_results` is advisory: `NEW_MESSAGE` text remains the durable delivery path.
- `tool_result_rendering` lives in `integration.yaml`; renderer ClassVar declarations are fallback only.
- `integrations.tool_output` owns support matching, portable read-only cards, badges, and fallback decisions.
- Slack translates portable cards to Block Kit in a platform adapter. Discord translates portable cards to embeds. `tool_output_display` still controls `compact | full | none`.
- A shared depth contract test now pins Slack/Discord rich-result support: manifest capabilities, renderer runtime capabilities, supported content types/view keys, non-interactive placement, and badge fallback must stay aligned.
- Slack approval Block Kit construction lives in a Slack-owned presenter module; the renderer imports that thin presentation boundary while retaining delivery orchestration.
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

**Problem:** Slack renderer owns streaming, approvals, files, modals, reactions, and tool-result rendering in one module.

**Proposed Interface:** Extract real presentation boundaries first. Tool-result Block Kit mapping already lives in the platform adapter; approval Block Kit mapping now lives in `approval_blocks`. Defer broader renderer decomposition until each split can own a stable policy boundary.

**Dependency Strategy:** True external boundary remains Slack Web API; tests keep using fake HTTP.

**Testing Strategy:** Preserve existing Slack renderer behavior tests, contract-test rich-result support, and add adapter-focused coverage as more presenter modules are split.

**Implementation Recommendations:** Split by platform concern only when a module can own a real policy boundary.

### Discord capability truth

**Problem:** Discord's manifest advertised `threading` even though the renderer tests explicitly say Discord delivery does not model Discord threads yet.

**Proposed Interface:** Manifest capabilities and renderer runtime capabilities must describe only behavior the renderer actually supports.

**Dependency Strategy:** In-process contract validation. Discord's REST API remains the true external boundary for renderer delivery tests.

**Testing Strategy:** The shared depth contract now fails when rich-result capable renderers drift between manifest truth and runtime truth.

**Implementation Recommendations:** Do not use YAML capabilities as product aspiration. Put planned capability expansion in the track, then add the manifest capability only when the renderer and tests support it.

## References

- `docs/guides/integrations.md`
- `docs/guides/slack.md`
- [[Track - Integration Contract]]
- [[Track - Integration DX]]
- [[Track - Integration Delivery]]
- [[Track - Code Quality]]
