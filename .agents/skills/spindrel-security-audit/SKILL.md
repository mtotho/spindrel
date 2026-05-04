---
name: spindrel-security-audit
description: "Use when the user asks to audit Spindrel's security posture, review a new feature for security gaps, run the nightly security-audit loop, or land a queued item from `docs/tracks/security.md`. Surfaces findings against agentic-AI + Python-codebase risk frames, lands one with the user, and updates the security track + audit doc + principles guide. Repo-dev skill — not a Spindrel runtime skill."
---

# Spindrel Security Audit

Repo-dev skill for surfacing **security findings** in Spindrel's self-hosted agent runtime and shipping fixes with same-edit doc + audit-signal updates. It must not be imported into app skill tables. The bar is fail-closed mechanical boundaries + observable operator-equivalent capabilities (per `docs/guides/security.md`); the threat surface is agentic AI plus a normal Python web codebase.

## Frame — what to look for

Spindrel's security model has two intersecting risk classes. Audit against both.

### Agentic-AI risks (live; high signal)

External frames:

- **OWASP Top 10 for Agentic Applications (2025)** — autonomous actions, delegated identity, tool misuse, goal hijack, cascading failures, memory/context poisoning, inter-agent spoofing, rogue autonomous behavior. <https://genai.owasp.org/2025/12/09/owasp-genai-security-project-releases-top-10-risks-and-mitigations-for-agentic-ai-security/>
- **OWASP Agentic Skills Top 10** — skill/plugin supply-chain risk (manifests, prompts-as-code, tool grants, capability creep). <https://owasp.org/www-project-agentic-skills-top-10/>
- **OWASP LLM Top 10 (2025)** — prompt injection, excessive agency, sensitive disclosure, insecure output handling. <https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/>

Spindrel-specific manifestations to grep for:

- **Inbound prompt-injection laundering** — third-party-controlled content (Slack/Discord/GitHub/BlueBubbles/Frigate/Wyoming bodies, web search results, integration webhook payloads) reaching the LLM unwrapped. The wrap is `app/security/prompt_sanitize.py::wrap_external_message_for_llm`; chokepoints are `inject_message`, `_enqueue_chat_turn`, history replay at `_strip_metadata_keys`. New integrations are the recurring drift surface — `tests/unit/test_integration_inbound_wrap_lint.py` is the AST gate.
- **`run_script` raw-Python egress** — sitecustomize allowlist + netns sandbox in `app/services/script_runner.py`. Any new code path that spawns a Python subprocess with workspace input should reuse `wrap_command_for_sandbox` or be flagged.
- **Tool dispatch abuse** — `safety_tier` + approval gating (`app/services/tool_policies.py`). New tools default to `readonly` only when the body is genuinely read-only; raw-payload returners (logs, file dumps, secrets) are `control_plane`.
- **Widget action abuse** — bot↔widget bridge in `app/services/widget_action_auth.py` + `widget_handler_tools.py`. New widget handlers, new action dispatch paths, new widget DB queries reuse the sqlite authorizer.
- **Self-mutation / cross-bot delegation** — `propose_config_change` autonomous-origin self-edit refusal (`app/tools/local/propose_config_change.py`); every event audit-logged via `app/security/audit.py::log_self_mutation`. Drift surface: new `manage_bot_skill`-style writers.
- **MCP / outbound URL** — `app/services/url_safety.py::assert_public_url`. New outbound HTTP callers check via `assert_public_url` first; `MCP_ALLOW_PRIVATE_NETWORKS` / `MCP_ALLOW_LOOPBACK` are the explicit relaxations.
- **Manifest supply chain** — HMAC over canonical payload at `app/services/manifest_signing.py`; verify-on-read at `load_skills` and `load_widget_templates_from_db`. `manifest_hash_drift` audit signal escalates to `critical` on signed-row mismatch.
- **Machine control / browser-live / harness** — lease + pairing-token discipline. Audit signals report stale leases, reusable pairing tokens, active paired sessions.

### Normal Python web codebase risks

- **Auth / scopes** — every new router defaults to `verify_auth_or_user`; public routes listed in `SECURITY.md` by name; rate-limited at `_check_rate_limit` or `RateLimitMiddleware`.
- **Secrets at rest** — `ENCRYPTION_STRICT=true` (default); `encrypt()` raises rather than silently storing plaintext. Backups encrypted at rest (`scripts/backup.sh` AES-256-CBC + PBKDF2; `backup_encryption_at_rest` audit signal).
- **Path resolution** — symlink rejection at every existing segment in `widget_paths.py` style; channel WorkSurface audit (`app/services/worksurface_isolation_audit.py`).
- **SQL injection / DB action surface** — sqlite authorizer denies `ATTACH` / `DETACH` / extension load / `VACUUM` output for widget DBs.
- **Dependency CVEs** — `pip-audit -r requirements.lock --strict --disable-pip` and `npm audit --omit=dev --audit-level=high` (CI `dep-audit` job).
- **Migration safety** — downgrade guards on encryption migrations refuse silent decryption (see `migrations/versions/130_encrypt_secrets.py::downgrade()`).
- **Pinned actions** — every GitHub Action ref pinned by SHA, not just tag.

### CIA triad — apply across both

- **Confidentiality** — secrets, bot API scopes, widget tokens, RAG/context, transcripts, Project/channel files, local-machine state.
- **Integrity** — tool dispatch, widget actions, harness writes, task/heartbeat automation, integration webhook inputs, manifest tampering.
- **Availability** — channel turn throttles, task/heartbeat loops, provider rate limits, widget polling, streaming fanout.

## Spindrel bindings

Read these first; do not re-litigate.

| Need | File |
|---|---|
| Active security queue + what shipped | `docs/tracks/security.md` |
| Latest deep-review evidence + checklists | `docs/audits/security-deep-review-2026-05.md` |
| Durable rules + PR review checklist | `docs/guides/security.md` |
| Threat model + deployment tiers | `SECURITY.md` |
| Audit-signal home | `app/services/security_audit.py` |
| Audit-signal tests | `tests/unit/test_security_audit.py` |
| Decisions already settled (don't re-suggest) | `docs/architecture-decisions.md` |
| Domain vocabulary | `docs/guides/ubiquitous-language.md` |

## Modes

### Interactive mode (operator-driven review)

1. **Explore.** Read the bindings table. Use a bounded explorer delegate when available to walk the codebase. For each agentic risk class above, grep for new instances since the last audit pass — new integration callbacks, new tools without `safety_tier`, new outbound HTTP, new widget handlers, new subprocess spawns, new untrusted-content sinks, new admin routes.
2. **Drift sweep — same explore pass.** For each `manifest_hash_drift` / `worksurface_*` / `prompt_injection_*` / `run_script_*` / `widget_*` audit signal in `app/services/security_audit.py`, spot-check whether the seam still holds. Flag drifted seams as `_drift: <date> shipped fix_`.
3. **Present findings.** Numbered list with **Risk class / Files / Threat / Mitigation / Severity (critical/high/medium/low/hygiene)**. Reference OWASP Agentic / LLM Top 10 categories where relevant. Mark items that contradict an entry in `docs/architecture-decisions.md` only when friction is real enough to revisit.
4. **Pick one.** Ask: "Which would you like to land?" Don't propose code yet.
5. **Land it.** Implement the mitigation, add or extend an **audit signal** in `app/services/security_audit.py` so future drift is observable, write tests at the boundary, then in the **same edit**:
   - Append the shipped item to `docs/tracks/security.md` (under the right severity bucket).
   - If the fix taught a durable rule, add it to `docs/guides/security.md`.
   - If a long-form audit doc is owed (cross-cutting review), append to `docs/audits/security-deep-review-<YYYY-MM>.md` (or create the next month's file).
   - If the fix introduces a new env var / setting / opt-in, document it in `SECURITY.md`.

### Unattended mode (overnight Project run)

The Run Brief MUST scope to one finding from `docs/tracks/security.md` and one bounded outcome — see [`.spindrel/WORKFLOW.md` Run Briefs](../../../.spindrel/WORKFLOW.md). If the brief lacks a named finding, **stop and emit `needs_review`**. Do not pivot scope.

- **Source document:** `docs/tracks/security.md` (named finding).
- **Mission:** land the named mitigation end-to-end (code fix + audit signal + tests + same-edit doc update).
- **Stop when:** mitigation merged, audit signal asserts pass on the new posture, tests at the boundary pass, track row marked shipped, principles guide updated if a durable rule emerged.
- **Stay inside:** files listed in the finding's "Files" line plus the new audit-signal site. Don't widen to fold in adjacent findings.
- **Evidence:** `pytest tests/unit/test_security_audit.py -q -k <new-signal>` output, `pip-audit` / `npm audit` run if dependency-related, audit signal pre/post diff.
- **Cross-cutting discovery:** if the grilling reveals a new high-severity finding, write the receipt with `needs_review` and stop. Add the new finding as an item under the right severity bucket in `docs/tracks/security.md` for the next run.

## Verification

For every shipped finding (interactive or unattended):

```bash
. .venv/bin/activate
PYTHONPATH=. pytest tests/unit/test_security_audit.py -q -k "<new-signal-or-related>"
PYTHONPATH=. pytest tests/unit/ -q -k "<finding-keywords>"
```

For dependency findings:

```bash
pip-audit -r requirements.lock --strict --disable-pip
( cd ui && npm audit --omit=dev --audit-level=high )
```

Per `AGENTS.md`: do NOT run pytest in Docker. Async-SQLite tests may auto-skip on local Python 3.14 — that's expected. The `RunSecurityAudit` orchestrator test has a known local fixture hang under Python 3.14 — run it in a supported native Python 3.12 venv if its assertions are needed.

## Completion Standard

A security finding is "done" when:

- The mitigation is in code (fail-closed by default; explicit opt-in for any relaxation).
- A new or extended **audit signal** in `app/services/security_audit.py` reports the boundary state, so drift is observable next pass.
- New tests assert the failure mode at the boundary (not a happy-path test added elsewhere).
- `docs/tracks/security.md` has the shipped entry under the right severity bucket.
- `docs/guides/security.md` updated if the fix taught a durable rule.
- `SECURITY.md` updated if a new env var / setting / deployment-tier gate landed.
- If a candidate was rejected for a load-bearing reason: `docs/architecture-decisions.md` has the entry.

## Severity rubric

- **Critical** — confidentiality breach, RCE, integrity collapse, agent goal hijack with privileged tool reach. Ship same-day.
- **High** — privilege expansion, exfil channel, prompt-injection laundering at a chokepoint, autonomous origin reaching admin-tier writes, supply-chain tampering at load.
- **Medium** — non-default-but-likely misconfig surface, ambient capability creep, redaction gaps, downgrade-path data leaks.
- **Low / hygiene** — pinning, audit gates, advisories with no live exploit path, observability/audit-signal gaps without an active threat.

When in doubt, prefer the higher tier. The track will downgrade explicitly if needed.

## Anti-patterns

- **Don't propose mitigations in step 3.** That happens in the grilling loop.
- **Don't add `try: ... except: pass` wrappers around fail-closed defaults.** Boundary errors must surface.
- **Don't ship a fix without an audit signal.** Future drift must be observable; otherwise the fix half-bit-rots.
- **Don't fold cross-cutting reviews into one Run Brief.** Each finding gets its own track row, its own audit signal, its own test.
- **Don't grant a new ambient capability without an explicit setting + audit signal.** Net-new outbound HTTP, net-new subprocess spawn, net-new self-mutation lane all need named env-var opt-ins (e.g. `MCP_ALLOW_LOOPBACK`, `SCRIPT_NETNS_SANDBOX`, `ENCRYPTION_STRICT`).
- **Don't re-litigate the deployment-tier model.** Internet-exposed remains out-of-scope until `_check_deployment_tier_readiness` says otherwise.
- **Don't treat `tests/unit/test_security_audit.py::TestRunSecurityAudit` failures on local Python 3.14 as real findings.** That orchestrator slice has a known fixture hang — run it in a supported native Python 3.12 venv.

## Pairing with the architecture-deepening skill

Security and architecture overlap when a fix wants a deepening (e.g. consolidating six redaction wrappers into one boundary helper). When that happens:

- If the security finding is the primary work, this skill leads and may invoke deepening as a sub-step.
- If a deepening reveals a security implication, the architecture-deepening skill flags it; this skill picks it up next pass.
- Don't run both in the same overnight Run Brief — split the missions.
