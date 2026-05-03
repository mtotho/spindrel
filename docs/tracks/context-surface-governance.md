---
title: Context Surface Governance
summary: Bound context/tool exposure by metadata and policy instead of global tool-name lists, reducing normal-turn bloat without losing discovery.
status: active
tags: [spindrel, context, tools, discovery]
created: 2026-05-01
updated: 2026-05-03
---

# Context Surface Governance

## North Star
Spindrel exposes the smallest useful context and tool surface for each turn. Tool and skill behavior is driven by metadata declared with the asset itself, not by runtime code checking concrete tool or skill names.

## Status
| Phase | State | Updated |
|---|---|---|
| 1. Metadata-backed tool exposure | active | 2026-05-01 |
| 2. Remove runtime tool/skill name lists | not started | - |
| 3. Budget violations and trace regression fixtures | not started | - |
| 4. Reviewable access requests | not started | - |

## Phase Detail
Phase 1 adds generic tool metadata (`domains`, `intent_tags`, `exposure`) to registration/indexing and uses `exposure` during normal context assembly. Specialized tools remain discoverable through explicit search/loading, but are not ambiently schema-loaded into ordinary turns.

Phase 2 removes remaining runtime hardcoded tool/skill identity lists by replacing them with registry metadata queries, manifest metadata, or config-owned policy sets.

Phase 3 turns known bad traces into tests and emits trace fields that make schema/context waste visible. Generic post-turn agent-quality findings now live in [[agent-quality-observability]] so this track can stay focused on the context/tool surface itself.

Phase 4 connects missing-tool reports to reviewable configuration proposals instead of forcing manual tool assignment.

## Key Invariants
- Runtime context code must not branch on specific integration tool names.
- Concrete tool identity belongs in the tool definition, integration manifest, seed config, or test fixtures.
- Discovery remains available: hidden-from-ambient tools can still be found through explicit search/loading flows.
- Heartbeat deterministic surfaces stay separate from normal chat surfaces.

## References
- `docs/guides/context-management.md`
- `docs/guides/discovery-and-enrollment.md`
- `docs/tracks/agent-quality-observability.md`
- Bad live traces reviewed 2026-05-01: heartbeat context bloat and normal chat over-surfacing.
