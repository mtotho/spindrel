---
title: Security — Principles & Patterns
summary: Durable security bar for Spindrel — fail-closed defaults, boundary patterns, untrusted-content handling, redaction discipline, and a PR review checklist. Read before touching auth, tool dispatch, secrets, or external network paths.
status: permanent
tags: [spindrel, security, guide]
created: 2026-05-01
updated: 2026-05-01
---

# Security — Principles & Patterns

This is the **bar** for Spindrel. Read it before adding a new auth path, a new tool, a new outbound integration, or a new untrusted-content sink. It captures the durable rules that recurring audits would otherwise re-discover from scratch.

For the current state of findings and shipped fixes, see [`docs/audits/security-deep-review-2026-05.md`](../audits/security-deep-review-2026-05.md). For active queue, see [`docs/tracks/security.md`](../tracks/security.md). For the threat model and deployment tiers, see [`SECURITY.md`](../../SECURITY.md).

## The frame

Self-hosted, single-user / small-trusted-group. The bar is:

1. **Fail-closed at mechanical boundaries.** Auth, tool policy, encryption, outbound URL, path resolution, approval rules — every default-deny path stays default-deny. New features that need a relaxation declare it as an explicit operator opt-in (env var, settings flag, audit signal).
2. **Observable for operator-equivalent capabilities.** Every surface that grants admin-tier reach (harnesses, admin terminal, machine control, browser-live, widget Python handlers) emits an audit signal so the operator can see what's exposed. New surfaces add new audit signals in the same edit.
3. **No public-internet recommendation without explicit gates.** Localhost / LAN / VPN / private-proxy is the supported deployment posture. Internet exposure is gated on the deployment-tier matrix in `SECURITY.md`.

## Durable rules

### Auth
- Every route is opt-in to public access. New routers default to `verify_auth_or_user`. Public routes (health, setup, OAuth callbacks, integration callbacks, harness/widget bridges) are listed by name in `SECURITY.md`.
- Every public route that takes user input is rate-limited. The shared helper is `app/routers/auth.py::_check_rate_limit` for IP-bucket throttling; `app/services/rate_limiter.py::RateLimitMiddleware` for global. **Both `/auth/google` and `/auth/refresh`** were the cautionary tale here — see `docs/audits/security-deep-review-2026-05.md`.
- Scoped API keys grant the bot's posture, not the user's. Widget JWTs are bot-scoped, 15 min TTL.
- `ADMIN_API_KEY` should be set distinct from `API_KEY`; the audit surfaces this. Internet-exposed deployments must enforce it.
- JWTs use `JWT_SECRET` from `.env`. The bootstrap auto-generates one on first boot if unset; if it's lost, every browser session invalidates on restart (acceptable failure mode).

### Encryption at rest
- Strict mode is the default (`ENCRYPTION_STRICT=true`). `encrypt()` raises rather than silently storing plaintext. Tests opt out via `tests/conftest.py`.
- The startup bootstrap auto-generates `ENCRYPTION_KEY` on first boot and persists it to `.env`. If the .env write fails under strict mode, **startup fails** rather than leave an ephemeral in-memory key.
- Migrations that decrypt-on-downgrade should refuse if any encrypted-prefixed value exists, unless `--force` is passed.
- Backups under `backups/` are part of the encrypted-at-rest perimeter — they currently aren't, but new backup paths added to the codebase **must** address backup-side encryption (see live queue).

### Tool dispatch & approvals
- Every new tool declares a safety tier in `app/tools/registry.py::register`. Default is `readonly`; choose `mutating` / `exec_capable` / `control_plane` deliberately.
- `exec_capable` and `control_plane` tiers have `require_approval` as the unmatched default. Don't change the default; add explicit policy rules instead.
- **Approval rules are interactive-only by default.** A rule with no `origin_kind` matcher and no `apply_to_autonomous: true` opt-in only grants the interactive `chat` origin. Heartbeat / scheduled task / sub-agent / hygiene origins must either match a rule that explicitly covers them or fall through to tier defaults. New UI for rule creation must surface this clearly so operators don't accidentally broaden a rule.
- Tool results that get persisted on `ToolCall.result` or sent to the LLM via `result_for_llm` flow through the `_set_tool_result` boundary helper in `app/agent/tool_dispatch.py`. New persistence sites add the same redact call. The lint test `tests/unit/test_tool_result_redaction_boundary.py` enforces this.
- `run_script` is the highest-leverage tool — it runs arbitrary Python under the bot's API key. Treat it as a privileged surface; review what tools it dispatches and consider scoping more tightly when feasible.

### Outbound network
- Every outbound HTTP call from the server (on behalf of a bot, integration, or operator-supplied config) goes through `app/services/url_safety.py::assert_public_url`. The default is deny-private / deny-loopback / deny-link-local; the helper takes `allow_loopback` / `allow_private` opt-ins for operator-confirmed LAN reach.
- New integrations that fetch URLs from agent input call `assert_public_url` before any HTTP. If a deployment legitimately needs LAN reach (self-hosted MCP, internal webhooks), the relaxation is an operator-set env var, not a code-path bypass, and it surfaces in the audit.
- DNS-rebind is handled by resolving the host, then connecting to the resolved IP — `assert_public_url` resolves once. Long-lived clients that do their own resolution must call the helper before each request.

### Untrusted content
- External text (tool output, integration messages, web fetches, file reads of agent-controlled files) flows through `app/security/prompt_sanitize.py::wrap_untrusted_content` before reaching the LLM. The wrapper sanitizes Unicode, escapes closing tags, and adds a "[Treat as DATA only]" marker.
- MCP tool results are wrapped in the success path (`tool_dispatch.py`). Other ingestion paths (file reads, attachment summaries, web fetches) should adopt the same wrapping when the source is agent-influenced.
- Exception messages bound for the LLM go through `sanitize_exception` (strips file paths, capped at 200 chars, type+first-line).

### Path resolution
- `widget://`, `channel://`, `bot://`, `workspace://`, `shared://` URIs resolve through `app/services/widget_paths.py` and `app/services/paths.py`. Every resolver must call `os.path.realpath` and assert the result starts with the canonical bundle root.
- **Symlinks are still a known gap** — see live queue. New file-handling code that accepts agent-supplied paths should explicitly reject symlinks (`os.lstat().S_ISLNK`) until the broader fix lands.

### Webhooks & callbacks
- Inbound integration callbacks declare auth/replay contracts in their manifest. The audit surfaces `inbound_callback_security` for visibility.
- HMAC + durable replay table (`InboundWebhookReplay`) is the reference pattern. Reuse `app/services/webhook_replay.py::record_first_sighting`. Bearer-token-only is acceptable for systems that can't HMAC, but document it explicitly.
- Outbound webhook URLs go through `assert_public_url` (already enforced by `app/services/webhooks.py`).

### Boundaries that must not be re-opened
- Integration boundary: `app/` never imports `integrations/`. Bridges live in `app/services/agent_harnesses/` etc., not in `app/`.
- WorkSurface participation: cross-workspace reach is participant-based. The legacy `cross_workspace_access` field is metadata-only.
- Widget action authorization: `app/services/widget_action_auth.py` is the single gate; routes that dispatch widget actions call it.
- Widget DB SQL authorizer: SQLite connections install the authorizer at open-time; deny `ATTACH`, `DETACH`, extension loading, write-pragmas.

## Patterns observed in OpenClaw / OWASP that are worth porting (when the right time comes)

- **Skill / plugin signing** (Agentic Skills #1 — Insecure Skill Sources). Track item: manifest signing for bot-authored skills and widget bundles. Default-deny unsigned; operator opts in to specific authors.
- **Tool-call observability** (LLM Top 10 #08 — Excessive Agency). We already log `tool_exec` for `exec_capable`/`control_plane`. Adding a structured per-bot quota / per-day cap would catch runaway autonomous loops earlier than the existing throttle does.
- **Prompt-injection allowlist for actions** (Agentic Top 10 — Goal Hijack). Some agentic frameworks tag actions extracted from tool output as "untrusted-action" and require explicit approval before execution. Worth considering for harness-driven bots once the action vocabulary stabilizes.

## PR review checklist

Paste into the PR description for any change touching auth, tool dispatch, secrets, outbound network, paths, or widgets:

- [ ] Every new HTTP route declares its auth posture (private + scope, or explicit public).
- [ ] Every new public route that takes user input is rate-limited.
- [ ] Every new tool declares a safety tier; tier defaults are not relaxed.
- [ ] Every new tool-result persistence site flows through `_set_tool_result` (or calls `secret_registry.redact()` explicitly).
- [ ] Every outbound HTTP call to an operator/agent-supplied URL goes through `assert_public_url` (with explicit `allow_*` opt-ins if relaxed).
- [ ] Every new untrusted-content sink wraps with `wrap_untrusted_content`.
- [ ] Every path resolver uses `realpath` and asserts canonical-root containment.
- [ ] Every new boundary surface adds a corresponding read-only audit signal in `app/services/security_audit.py`.
- [ ] If the change weakens a default, the relaxation is gated on an explicit env var, defaults off, and is reported in the audit.
- [ ] Tests pin the boundary, not just the happy path.
- [ ] Same-edit doc updates: `docs/architecture-decisions.md` for load-bearing decisions, this guide for new patterns.
