---
title: Agent Quality Observability
summary: Agent trace/eval observability: deterministic post-turn quality findings, explicit context-admission traces, and a standards-aligned path toward OpenTelemetry-style agent tracing.
status: active
tags: [spindrel, agents, quality, traces, evals]
created: 2026-05-03
updated: 2026-05-03
---

# Agent Quality Observability

## North Star
Spindrel should notice when an agent behaves incompetently before the operator has to manually read every bad chat. The first layer is deterministic and observation-only: it records evidence-backed trace findings after a turn is persisted, without adding prompt cues, changing model behavior, or blocking the user response.

## Status
| Phase | State | Updated |
|---|---|---|
| 1. Deterministic trace auditor | shipped | 2026-05-03 |
| 2. Quality findings consumer | shipped | 2026-05-03 |
| 3. Admin/batch re-audit tool | shipped | 2026-05-03 |
| 4. Recent image context trace | shipped | 2026-05-03 |
| 5. Trace standards baseline | started | 2026-05-03 |
| 6. Scoped LLM judge | not started | - |
| 7. Structural fixes from findings | active | 2026-05-03 |

## Phase Detail
Phase 1 adds `app/services/agent_quality_audit.py`. It emits idempotent `agent_quality_audit` `TraceEvent` rows with `audit_version=1`. V1 detectors are intentionally narrow:

- `current_inline_image_missed`: current user turn had an image, but the assistant disclaimed vision.
- `current_fact_without_lookup`: user asked for current/live/status-style information, the assistant answered without tools, and did not clearly state missing capability.
- `tool_surface_mismatch`: the assistant or tool calls reveal drift between the model's expected tool surface and exposed tools.

Phase 2 adds Daily Health visibility by counting quality findings in `SystemHealthSummary.source_counts.agent_quality` and showing the count on the Daily Health panels.

Phase 3 adds `audit_trace_quality`, a local diagnostic tool that can re-audit one trace or a recent batch. It is deterministic and idempotent.

Phase 4 adds `recent_attachment_context` trace events for text-only followups that carry forward the latest visible image-bearing user message in a project/chat session. The event records source/current message IDs, attachment IDs, MIME types, age, and admission count, but never stores image bytes or base64.

Phase 5 starts the trace/eval standardization track. There is no single stable universal agent trace spec yet, so Spindrel uses a pragmatic baseline:

- W3C Trace Context concepts for cross-service propagation.
- OpenTelemetry GenAI semantic conventions for model, agent, tool, token, and latency concepts.
- OpenTelemetry MCP conventions for MCP tool spans.
- OpenAI Agents SDK tracing as vendor reference material, not as the canonical internal schema.

Phase 6 will use existing judge primitives only for flagged traces, only from scheduled/admin jobs, and never on the live user path.

Phase 7 uses findings to drive structural fixes. The first one shipped with this track: `get_tool_info` now resolves cache-cold bare MCP aliases from the persisted tool catalog, closing the `ha_get_state`/Home Assistant drift seen in live traces.

## Spindrel Trace Contract
- `correlation_id` is the current internal trace/run key. Future export layers may map it to W3C/OTel trace IDs without replacing existing rows.
- `TraceEvent` remains the internal append-only event store for turn assembly, LLM routing, context admission, quality findings, and runtime diagnostics.
- Context admission should be trace-visible when it changes what the model can see. Current examples: `attachment_vision_routing` and `recent_attachment_context`.
- Quality findings are post-turn annotations, not live prompt constraints.
- Trace rows must default to metadata and evidence summaries. Raw prompt text, image bytes, base64 payloads, secrets, and large tool outputs require explicit opt-in/redaction policy.

## Key Invariants
- Do not add v1 live cue injection. If the model misses images or tools, record it and fix the structural path.
- Do not add quality logic back into `context_assembly.py`; use services, local tools, or the `tool_surface` seam.
- Audit writes are append-only and versioned. Re-auditing at a new version appends instead of overwriting old findings.
- Audit failure must never affect turn persistence or user response delivery.
- Existing runtime loop detectors remain authoritative for loop semantics; do not re-detect repeated lookup cycles here.

## References
- `app/services/agent_quality_audit.py`
- `app/tools/local/agent_quality.py`
- `docs/tracks/context-surface-governance.md`
- `docs/tracks/architecture-deepening.md`
