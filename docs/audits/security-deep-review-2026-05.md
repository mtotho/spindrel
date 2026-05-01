---
title: Security Deep Review — 2026-05
summary: Cross-surface deep security audit covering auth, agent execution, secrets, supply chain, and container posture. Top-5 critical fixes shipped same pass; remaining items live in the security track queue.
status: reference
tags: [spindrel, security, audit]
created: 2026-05-01
updated: 2026-05-01
---

# Security Deep Review — 2026-05

A cross-surface audit run on top of the active [Track - Security Architecture](../tracks/security.md). The track had already shipped the major boundary mechanisms (widget action auth, WorkSurface participation, callback HMAC + replay, machine-control audit, widget DB SQL authorizer, encryption-key bootstrap). This review reads what those boundaries actually catch *today* against the surfaces that have been added since: Projects, harnesses, widgets, local-machine control, image generation, integration rich results, attention beacons, etc.

Threat frame: self-hosted single-user / small-trusted-group. The bar is **fail-closed at mechanical boundaries, observable for operator-equivalent capabilities, no public-internet recommendation without explicit gates** — not multi-tenant SaaS hardening.

External cross-references checked: [OWASP Agentic Top 10](https://genai.owasp.org/), [OWASP Agentic Skills Top 10](https://owasp.org/www-project-agentic-skills-top-10/), [OWASP LLM Top 10 2025](https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/), [OpenClaw](https://github.com/openclaw/openclaw).

## Top-5 critical / high fixes shipped this pass

Each fix carries focused unit coverage; see [`docs/fix-log.md`](../fix-log.md) for the one-liner summary.

### 1. MCP outbound URL hardening — **Critical → Shipped**
Before: `app/tools/mcp.py::fetch_mcp_tools` and `call_mcp_tool` issued `httpx.post(server.url, …)` with **no SSRF guard**. A bot-enrollable MCP server pointed at `http://169.254.169.254/`, `http://localhost:5432`, `http://10.x.x.x` etc. would let the host pivot into internal services (cloud metadata, local Postgres, LAN admin consoles) and exfiltrate the configured Bearer token to attacker-controlled hosts. The admin "test connection" endpoint already used the existing `assert_public_url` helper; the runtime path bypassed it.

After: extended `app/services/url_safety.py::assert_public_url` with `allow_loopback` / `allow_private` opt-ins (so the same SSRF helper can serve webhook delivery, image fetch, and now MCP). Both MCP runtime paths now call the helper before any HTTP request. Operator escape hatches: `MCP_ALLOW_PRIVATE_NETWORKS` (LAN MCP) and `MCP_ALLOW_LOOPBACK` (localhost MCP), default false. Audit signal `mcp_outbound_url_guard` reports the chosen posture so opted-in deployments are visible. Coverage: `tests/unit/test_url_guard.py` (extended SSRF coverage, 14 cases) + `tests/unit/test_mcp_outbound_guard.py` (4 wiring cases).

### 2. Encryption fail-fast — **Critical → Shipped**
Before: `app/services/encryption.py::encrypt` silently returned plaintext when `ENCRYPTION_KEY` was unset or invalid. Startup bootstrap auto-generates a key on first boot, so the only ways to hit silent plaintext were a misconfigured key value (logged but execution continued) or a code path that bypassed bootstrap. `ensure_encryption_key()` also warned-and-continued when the .env write failed, leaving an in-memory key that wouldn't survive restart — exactly the silent corruption window.

After: new `ENCRYPTION_STRICT` setting (default true). In strict mode, `encrypt()` raises `EncryptionNotConfiguredError` instead of silent fallback; `decrypt()` raises when an encrypted-prefixed value is presented without a key; `ensure_encryption_key()` re-raises OSError on dotenv write failure. Tests opt out via `tests/conftest.py` (`ENCRYPTION_STRICT=false`). Audit signal upgraded to surface strict posture (`pass` when key + strict, `warning` when key but strict off, `fail` when no key). Coverage: extended `tests/unit/test_encryption.py` with 6 strict-mode cases.

### 3. Tool-result redaction at the boundary — **High → Shipped**
Before: `app/agent/tool_dispatch.py` had three sites writing `result_obj.result = …`. Only the success path ran `secret_registry.redact()`. The error path (`_apply_error_payload`) and the machine-access-denied path wrote raw payloads, so a tool that errored with a secret in its message (auth failures echoing `Authorization: Bearer …`, DB connection-string parse failures, etc.) persisted unredacted in `ToolCall.result` and reached the LLM.

After: new `_set_tool_result(result_obj, persisted, *, llm=None)` boundary helper that always applies `redact()` to both fields. Three call sites routed through it; success path's pre-existing redact preserved + extra redact on `result_for_llm` to keep the boundary uniform. Lint-style guard `tests/unit/test_tool_result_redaction_boundary.py` AST-greps the file and asserts every direct `result_obj.result =` write lives inside the helper, plus that every `result_obj.result_for_llm =` write has a redact call within 5 lines. Coverage: 5 new functional tests + 2 boundary lint tests.

### 4. Auth route rate-limit parity — **High → Shipped**
Before: `_check_rate_limit` (5 attempts / 60s per IP) was wired to `/auth/login` and `/auth/setup` only. `/auth/google` and `/auth/refresh` were unguarded — a single attacker IP could brute-force OAuth code redemption or token-format replay without throttle.

After: same helper now wraps `/auth/google` and `/auth/refresh`. `/auth/forgot-password` doesn't currently exist and was not added. Coverage: `tests/unit/test_auth_routes_rate_limit.py` source-asserts each endpoint references the helper, plus a behavior test of the helper.

### 5. Approval rule origin_kind awareness — **High → Shipped**
Before: a user-approved `allow` rule for interactive `exec_command` (or any `exec_capable`/`control_plane` tool) silently auto-approved the same tool in autonomous origins (heartbeat / scheduled task / sub-agent / hygiene). `_match_conditions` had `origin_kind` plumbing but no rule had it set, so every rule matched every origin. Tier defaults (`exec_capable → require_approval`) gated *unmatched* tools, but explicitly-approved ones leaked through.

After: `_match_conditions` defaults to interactive-only (chat origin) when a rule has neither an explicit `origin_kind` matcher nor `apply_to_autonomous: true` opt-in. Existing rules without `origin_kind` are now interactive-only on read — a fail-closed direction; users who need autonomous coverage opt in by adding `apply_to_autonomous: true` to the rule's `conditions`. Audit signal `allow_rules_origin_scope` lists which rules are interactive-only vs autonomous-opt-in for operator review. UI-side toggle for the autonomous opt-in is queued in the live track. Coverage: 7 new origin-kind cases in `tests/unit/test_tool_policies.py` + 3 audit-signal cases.

## Findings remaining (queued in the security track)

### High
- **`run_script` arbitrary Python with bot's full toolset.** Inline scripts run inside the workspace runtime under the bot's scoped API key. Approval gates the `run_script` call itself, not the nested tool calls the script makes. A clever script can chain `file(read) → call_api → file(write)` to exfiltrate and persist without triggering individual approvals. Mitigation options: per-script-call rate limit, declared tool-list in script frontmatter that the policy engine pre-checks, or wrap the per-tool dispatch inside `run_script` with the same origin_kind check now applied to top-level rules.
- **Widget path symlink-follow.** `app/services/widget_paths.py` uses `os.path.realpath()` for traversal but does not detect or reject symlinks, and there's no symlink-count cap. A bot-authored widget could symlink `/etc/passwd` (or any file inside the workspace mount) into a widget bundle dir; `realpath()` resolves the link and the path stays within the canonical bundle root, so the read succeeds. Fix: explicit `os.lstat().S_ISLNK` rejection at every component, or a small symlink-count cap.
- **Backups under `backups/` are unencrypted DB dumps.** No documented retention or encryption strategy; if a backup is mounted into a tool container or exfiltrated from disk, every secret it contains becomes plaintext (provider keys, integration tokens, user passwords). Fix: GPG- or Fernet-encrypt backups, document retention.
- **Skill / widget supply-chain integrity.** `manage_bot_skill` and widget bundles are unsigned. A compromised bot can author a skill containing arbitrary Python (a `run_script` snippet) or a widget with malicious `@on_action` / `@on_cron` handlers. Fix: manifest signing (HMAC over `widget.json`/skill body), audit trail, default-deny on unsigned with opt-in trust.

### Medium
- **Migration downgrade silently decrypts.** `migrations/130_encrypt_secrets.py` reverse-migrates by decrypting; no guard on accidental downgrade after encryption rollout. Fix: refuse downgrade if any encrypted-prefixed value exists, unless `--force`.
- **Stale `cross_workspace_access` flags.** Field is metadata-only after the participant rewrite, but legacy bots still carry it; reads as cleanup debt in the audit.
- **DB row ownership at API layer only.** No Postgres RLS; if an auth check is bypassed, full cross-user data exposure is possible. Fix: review owner-keyed queries or add RLS.
- **Widget JWT TTL hardcoded 15 min, no early revoke.** A captured widget token grants 15 min of bot-level access. Fix: revocation list keyed by `(api_key_id, jti)`.
- **`<untrusted-data>` wrapping not applied to direct file reads.** A bot reading an adversary-controlled file inside the workspace gets raw content into context without the data-only marker. Fix: extend `wrap_untrusted_content` application to file ingestion paths.
- **Container `sudoers` allows passwordless `apt-get`.** Narrow scope but still privilege-escalation surface inside the container. Fix: drop the rule unless an active workflow needs it.
- **Static `API_KEY` rotation needs a redeploy.** No in-place rotation flow.

### Low / hygiene
- `pyproject.toml` floats; `requirements.lock` pinned but no CI `pip-audit` gate.
- `.github/workflows/*.yml` actions pinned by major, not SHA.
- CORS regex on `main.py` allows any localhost / 127.x / `[::1]` origin. Fine for a local-trusted dev model; document the assumption.
- No CSRF middleware; relies on SameSite cookies + Bearer auth.

## Surfaces deliberately not in scope this pass

- **Multi-tenant isolation.** Spindrel is single-user / small-trusted-group; full row-level multi-tenant hardening is a separate posture decision.
- **Provider key rotation ceremonies.** Documented as operator workflow, not changed here.
- **External pen-test / fuzz pass.** Out of scope; would belong to a separate engagement.

## Verification artifacts

```
. .venv/bin/activate
PYTHONPATH=. pytest \
  tests/unit/test_url_guard.py \
  tests/unit/test_url_safety.py \
  tests/unit/test_mcp_outbound_guard.py \
  tests/unit/test_encryption.py \
  tests/unit/test_tool_result_redaction.py \
  tests/unit/test_tool_result_redaction_boundary.py \
  tests/unit/test_auth_routes_rate_limit.py \
  tests/unit/test_tool_policies.py \
  tests/unit/test_security_audit.py \
  -q
```
Result this pass: 190 passed, 0 failed across the targeted slice (`tests/unit/test_secret_redaction_integration.py` continues to hit the pre-existing local Python 3.14 / aiosqlite DB-session issue noted in [`docs/tracks/security.md`](../tracks/security.md); the boundary it tests is now also covered by `tests/unit/test_tool_result_redaction.py` which does not require the DB).

## Same-pass updates

- [`docs/fix-log.md`](../fix-log.md) — five new entries (one per fix).
- [`docs/tracks/security.md`](../tracks/security.md) — Shipped-this-pass section extended; live queue rewritten with severity ranks.
- [`docs/guides/security.md`](../guides/security.md) — new principles guide; covers fail-closed defaults, untrusted-content handling, outbound URL discipline, redaction boundary, approval origin scope, PR review checklist.
- [`SECURITY.md`](../../SECURITY.md) — refreshed deployment-tier matrix and audit-surface list.
- [`docs/roadmap.md`](../roadmap.md) — Security Architecture row bumped with the new shipped one-liner.
