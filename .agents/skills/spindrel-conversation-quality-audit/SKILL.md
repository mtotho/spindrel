---
name: spindrel-conversation-quality-audit
description: Repo-dev workflow for Claude/Codex or Spindrel Project agents to review active human chat threads, inspect traces, find frustration and response-quality failures, and propose generic fixes without writing into primary conversations.
---

# Spindrel Conversation Quality Audit

Repo-dev skill for auditing real Spindrel conversations for coherence,
context continuity, attachment/image handling, tool-use quality, and user
frustration. Use it from a local CLI agent, a Project coding run, or an in-app
Spindrel agent that has read-only conversation and trace tools.

This is not a Spindrel runtime skill and must not be imported into app skill
tables. Runtime channel bots should not receive this as behavior guidance.

## Default Contract

- Read-only by default. Do not post test messages into primary human sessions
  unless the operator explicitly asks.
- Prefer active production evidence over synthetic probes when diagnosing real
  user pain.
- Quote only the short snippets needed to prove a finding. Do not dump private
  conversations into reports.
- Diagnose the structural layer before proposing fixes: context assembly,
  attachment persistence, task/burst routing, tool surface, provider/model,
  memory, prompt/onboarding, integration transport, or UI.
- Prefer generic product fixes over bot-specific constraints. Bot onboarding is
  a fallback when the same system behavior works elsewhere.

## Access Modes

See [`../_shared/api-access.md`](../_shared/api-access.md) for the canonical
env-var contract and [`../_shared/mcp-bridge-tools.md`](../_shared/mcp-bridge-tools.md)
for the runtime tool catalog. Prefer MCP tools when running in-spindrel; fall
back to HTTP via `$SPINDREL_API_URL` + `$SPINDREL_API_KEY` when a tool is
unavailable.

Suggested read scopes for this skill:

- channel/session/message read
- attachment metadata read
- trace read
- bot/config read
- task/read status
- quality-audit read

Useful endpoints vary by deploy, so confirm with OpenAPI or route docs first.
Common shapes:

```bash
curl -s -H "X-API-Key: $SPINDREL_API_KEY" \
  "$SPINDREL_API_URL/api/v1/channels"

curl -s -H "X-API-Key: $SPINDREL_API_KEY" \
  "$SPINDREL_API_URL/api/v1/channels/$CHANNEL_ID"

curl -s -H "X-API-Key: $SPINDREL_API_KEY" \
  "$SPINDREL_API_URL/api/v1/sessions/$SESSION_ID/messages?limit=100"

curl -s -H "X-API-Key: $SPINDREL_API_KEY" \
  "$SPINDREL_API_URL/api/v1/admin/traces/$CORRELATION_ID"
```

If the server exposes a narrower trace-search endpoint, use that rather than
enumerating all messages.

## Audit Workflow

1. **Resolve scope.** Default to active human-facing channels in the last 24
   hours. Expand to 7 days for intermittent failures or "previous image"
   complaints. Include the channel ids, bot ids, session ids, and time window
   in the report.
2. **Inventory active threads.** Rank channels by recent activity, visible user
   frustration, assistant errors, fallbacks, memory write errors, quality-audit
   findings, and repeated corrections.
3. **Read recent conversation first.** Inspect the primary session before
   traces. Note what the user was trying to accomplish and what a competent
   chat agent should have inferred from the surrounding turns.
4. **Inspect traces for suspect turns.** Check context admission, tool surface,
   attachments, recent image context, burst/coalescing events, tool calls,
   fallback events, provider/model, memory writes, and exception events.
5. **Classify findings.** For each issue, classify the likely layer:
   `context`, `attachments`, `burst/task`, `tool_surface`, `provider`,
   `memory`, `prompt`, `integration`, `ui`, or `unknown`.
6. **Recommend generic fixes first.** If a fix would only help one bot, explain
   why it is not a platform fix. Prefer code paths and tests that improve all
   normal chat agents.

## Quality Checklist

Use this checklist while reading turns:

- **Context continuity:** follow-up questions refer to the correct previous
  subject without forcing the user to restate it.
- **Image handling:** current images are seen directly by vision models;
  previous images remain referenceable across the project chat; assistant does
  not claim it cannot see an image that was admitted.
- **Attachment plumbing:** uploaded files have durable attachment rows and
  traces show whether they were included inline or summarized.
- **Tool use:** current/external facts are looked up; available tools are not
  claimed missing; skills do not name stale tool aliases.
- **Response shape:** answers are direct, appropriately scoped, and in the
  bot's domain voice without excessive disclaimers or fake certainty.
- **Burst behavior:** multiple user messages sent while the bot is busy are
  coalesced into one coherent follow-up, not answered separately out of order.
- **Memory behavior:** no unnecessary nightly-memory bloat, duplicate headers,
  spurious memory writes, or stale context over-injection.
- **Frustration markers:** repeated corrections, "no", "wrong", "wtf",
  sarcasm about competence, or the user re-asking the same question.
- **Trace health:** no model fallback for avoidable bad requests, no traceback,
  no repeated lookup loops, no hidden task failure after a visible reply.

## Finding Format

Write findings in severity order:

```markdown
## Findings

### P1 - Previous image reference broke in Gardening
- Evidence: channel=..., session=..., trace=..., messages=...
- User expectation: ...
- Bot behavior: ...
- Likely layer: attachments/context
- Diagnosis: ...
- Generic fix: ...
- Verification: ...
```

Severity guide:

- `P0`: data loss, privacy leak, bot writes into the wrong human thread, or
  repeated production turn failures.
- `P1`: bot cannot sustain normal conversation, image references fail, or
  available tools are systematically unusable.
- `P2`: response quality/tone issues, avoidable confusion, or prompt/onboarding
  gaps with clear workarounds.
- `P3`: polish, observability gaps, or one-off oddities.

## Report Template

```markdown
# Conversation Quality Audit

Scope:
- Server:
- Window:
- Channels:
- Access mode:

Executive summary:
- ...

Findings:
- ...

Healthy behaviors:
- ...

Unknowns / access gaps:
- ...

Recommended fixes:
- Immediate:
- Next:
- Defer:
```

## When To Create Artifacts

Follow `.spindrel/WORKFLOW.md`:

- Use `docs/audits/<slug>.md` for an evidence ledger or recurring audit.
- Use `docs/tracks/<slug>.md` when the work becomes a multi-session effort.
- Use `docs/inbox.md` for a rough issue that needs later triage.
- Use `docs/fix-log.md` when a small fix lands and removes an inbox item.

For conversation-quality work, prefer an audit file when reviewing real human
threads because the evidence trail matters and should not live only in chat.

## Anti-Patterns

- Do not use primary human sessions as test sandboxes.
- Do not classify from assistant text alone when a trace exists.
- Do not turn every failure into prompt instructions. First check whether the
  system dropped context, attachments, tools, or queued messages.
- Do not build per-bot hacks before checking if Crumb, Sprout, QA, and other
  agents share the same failure shape.
- Do not assume "model dumb" until the trace proves the model received the
  right messages, images, tools, and recent context.
- Do not require access to the operator's private notes or laptop paths.

## Completion Standard

An audit pass is complete when it produces one of:

- a concise no-issue report with channels, sessions, and traces checked;
- a ranked finding list with evidence and generic fix recommendations;
- a code fix with a regression test and updated audit/track/fix-log entry;
- an explicit access-gap report naming which read-only tool or API scope is
  missing.
