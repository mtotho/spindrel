---
tags: [agent-server, track, security, agentic-ai]
status: active
created: 2026-04-30
updated: 2026-04-30
---
# Track - Security Architecture

Evergreen security track for Spindrel's self-hosted agent runtime. The March/April hardening pass shipped real foundations, but the system has since added Projects, external harnesses, widgets, local-machine control, richer integrations, and agent-first capability surfaces. This track keeps security review active instead of treating it as a completed checklist.

## Current posture

Spindrel is still a trusted-user / trusted-small-group self-hosted app, not a hardened public multi-tenant SaaS. The correct security bar is therefore:

- Strong by default for localhost, LAN, VPN, and private reverse-proxy deployments.
- Explicitly labeled and observable for operator-equivalent capabilities.
- Fail-closed at mechanical boundaries: auth, scopes, tool policy, path resolution, widget action dispatch, integration callbacks, harness/local-machine leases.
- No public-internet recommendation until the deployment-tier matrix has green gates.

## Audit frame

Use the CIA triad plus current agentic-AI risks:

- **Confidentiality** - secrets, bot API scopes, widget tokens, memory/RAG/context injection, transcripts, Project/channel files, local-machine/browser state.
- **Integrity** - tool dispatch, widget actions, API proxy/call_api, harness writes, task/heartbeat automation, config repair actions, integration webhook inputs.
- **Availability** - channel turn throttles, task/heartbeat loops, provider/API rate limits, widget polling, streaming fanout, scheduled harness runs.
- **Agentic risks** - goal hijack, tool misuse, privilege abuse, skill/plugin supply chain, unexpected code execution, memory/context poisoning, inter-agent spoofing, cascading failure, human-trust exploitation, rogue autonomous behavior.

External frame checked 2026-04-30:

- [OWASP Top 10 for Agentic Applications announcement](https://genai.owasp.org/2025/12/09/owasp-genai-security-project-releases-top-10-risks-and-mitigations-for-agentic-ai-security/): agentic risks shift from bad outputs to autonomous actions, delegated identity, tool misuse, goal hijack, and cascading failures.
- [OWASP Agentic Skills Top 10](https://owasp.org/www-project-agentic-skills-top-10/): skill/plugin ecosystems are a live supply-chain risk across OpenClaw / Claude Code / Cursor / Codex style skill manifests.
- [OWASP LLM Top 10 2025](https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/): still relevant for prompt injection, excessive agency, sensitive information disclosure, and insecure output handling.

## Shipped this pass

- Extended `app/services/security_audit.py` from mostly config/tool-policy checks to include three agentic boundary signals:
  - bots with `cross_workspace_access`;
  - bots with high-risk API scopes such as `admin`, wildcard, `tools:execute`, secret/provider/settings/API-key writes, and broad file writes;
  - widget-action API dispatch allowlist breadth.
- Added focused unit coverage for those audit checks in `tests/unit/test_security_audit.py`.
- Refreshed `SECURITY.md` with a deployment-tier threat matrix and agentic attack classes.
- Promoted this dedicated track into `INDEX.md` and `Roadmap.md`.
- Added an explicit widget-action authorization boundary in `app/services/widget_action_auth.py`, wired router auth into action dispatch, refresh, refresh-batch, and event-stream paths, and pinned widget-token/channel-owner/scope checks in `tests/unit/test_widget_actions_authorization.py`.

## Live queue

1. **Cross-workspace access observability.** Surface the flag in admin bot UI and log cross-channel file operations with bot, source channel, target channel, path, and operation.
2. **Security audit deepening.** Add read-only checks for harness-enabled bots, local-machine leases, public callback routes, weak/missing webhook replay protection, widget DB action surfaces, and bot-authored skill/widget writable roots.
3. **Deployment-tier gates.** Convert the `SECURITY.md` threat matrix into concrete admin readiness findings before recommending internet-exposed deployment.
4. **Skill/plugin supply-chain pass.** Review repo `.agents/skills`, runtime bot-authored skills, widget bundles, integration manifests, and future plugin import paths against provenance, permission, and review requirements.

## Watch list

- Browser-origin control surfaces: widget iframes, browser-live pairing, local companion, harness terminals, and app-server/native runtime bridges.
- Ambient self-improvement paths: `manage_bot_skill`, widget authoring tools, config repair actions, and agent capability repair actions.
- Long-running autonomous loops: heartbeats, scheduled tasks, widget crons/events, harness schedules, standing orders.

## Verification

- `python -m py_compile app/services/security_audit.py tests/unit/test_security_audit.py` passed.
- Focused new audit checks passed: `pytest tests/unit/test_security_audit.py -q -k "BotsWithCrossWorkspaceAccess or BotsWithHighRiskApiScopes or WidgetActionApiAllowlist"` -> `7 passed, 44 deselected`.
- `timeout 20 pytest tests/unit/test_security_audit.py -q -k RunSecurityAudit --tb=short` timed out locally with no pytest output; this appears to be the existing DB-backed SQLite fixture behavior in that file and remains a test-infra follow-up.
- Widget action boundary syntax passed with `PYTHONPYCACHEPREFIX=/tmp/spindrel-pycache python -m py_compile ...`.
- Widget action authorization tests passed: `pytest tests/unit/test_widget_actions_authorization.py -q --tb=short` -> `13 passed`.
- Existing widget state/native coverage passed locally: `pytest tests/unit/test_widget_actions_state_poll.py tests/unit/test_native_app_widgets.py -q --tb=short` -> `20 passed, 7 skipped`.
- DB-backed widget dispatch and workspace-spatial native tests are still skipped in this Python 3.14 local profile by the repo's SQLite fixture guard; run them in the supported Python 3.12/Docker test runtime for execution coverage.
