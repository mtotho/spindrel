---
tags: [agent-server, track, integrations, slack, sdk, rich-results]
status: active
created: 2026-04-24
updated: 2026-04-24
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

## Current Implementation Shape

- `rich_tool_results` is advisory: `NEW_MESSAGE` text remains the durable delivery path.
- `tool_result_rendering` lives in `integration.yaml`; renderer ClassVar declarations are fallback only.
- `integrations.tool_output` owns support matching, portable read-only cards, badges, and fallback decisions.
- Slack translates portable cards to Block Kit in a platform adapter. Discord translates portable cards to embeds. `tool_output_display` still controls `compact | full | none`.
- Widget/component actions are out of scope for v1. Approvals remain on `approval_buttons`.

## Verification

- `pytest tests/unit/test_tool_output_shared.py tests/unit/test_slack_tool_output_display.py tests/unit/test_integration_manifests.py tests/unit/test_renderer_registry.py tests/unit/test_canonical_docs_drift.py tests/unit/test_integration_import_boundary.py -q` passed: 87 passed, 17 skipped.
- `pytest tests/unit/test_capability_gate.py tests/unit/test_channel_renderers.py tests/unit/test_core_renderers.py -q` passed: 57 passed.
- `tests/unit/test_slack_renderer.py` timeout fixed by bounding the outbox poll inside `_wait_for_pending_outbox`.
- `pytest tests/unit/test_slack_renderer.py tests/unit/test_discord_renderer.py tests/unit/test_tool_output_shared.py tests/unit/test_slack_tool_output_display.py tests/unit/test_integration_manifests.py tests/unit/test_renderer_registry.py tests/unit/test_canonical_docs_drift.py tests/unit/test_integration_import_boundary.py -q` passed: 135 passed, 17 skipped.

## Audit Issues

### Rich tool-result rendering boundary

**Problem:** Slack had component-only rich rendering embedded inside the large renderer, with no explicit platform capability matrix and no SDK-level contract for other integrations.

**Proposed Interface:** Renderers call the SDK presentation helper with persisted tool envelopes, display mode, and declared support. The helper returns cards, badges, and unsupported fallbacks.

**Dependency Strategy:** In-process. Slack API remains the renderer's external boundary and is mocked in renderer tests.

**Testing Strategy:** Boundary tests for SDK normalization; thin Slack adapter/renderer tests for Block Kit output and mode branching.

**Implementation Recommendations:** Keep support matching, fallback policy, and portable card construction out of platform renderers. Platform adapters should only map card primitives to native blocks/embeds/messages.

### SDK-only integration import boundary

**Problem:** Direct `app.*` imports still exist under `integrations/`, despite the canonical SDK-only target. This makes the app/integration boundary harder to reason about.

**Proposed Interface:** Integration authors import app-owned contracts through `integrations.sdk`. Existing direct imports are allowlisted debt; new direct imports fail tests.

**Dependency Strategy:** In-process for registry/static checks. No runtime dependency change required for existing debt.

**Testing Strategy:** Add an allowlist test for direct `app.*` imports under `integrations/`.

**Implementation Recommendations:** Fix imports opportunistically when touching a seam; do not broad-refactor routers/tools in the rich-results pass.

### Slack renderer size

**Problem:** Slack renderer owns streaming, approvals, files, modals, reactions, and tool-result rendering in one module.

**Proposed Interface:** Extract tool-result Block Kit mapping first. Defer broader renderer decomposition to a later code-quality slice.

**Dependency Strategy:** True external boundary remains Slack Web API; tests keep using fake HTTP.

**Testing Strategy:** Preserve existing Slack renderer behavior tests and add adapter-focused coverage for rich-result fallback cases.

**Implementation Recommendations:** Split by platform concern only when a module can own a real policy boundary.

## References

- `docs/guides/integrations.md`
- `docs/guides/slack.md`
- [[Track - Integration Contract]]
- [[Track - Integration DX]]
- [[Track - Integration Delivery]]
- [[Track - Code Quality]]
