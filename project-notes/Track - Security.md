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
- Reframed the cross-workspace item into a WorkSurface isolation audit. Added `app/services/worksurface_isolation_audit.py`, surfaced its findings through the admin security audit, documented `docs/guides/worksurface-isolation.md`, and pinned the current model/gaps in `tests/unit/test_worksurface_isolation_audit.py`.
- Removed ambient Secret Values injection from shared workspace subprocesses. Shared workspace exec now defaults to no Secret Values and only injects names present in `current_allowed_secrets`, while Project runtime env continues through explicit `extra_env`.
- Replaced the legacy sibling-channel `cross_workspace_access` runtime path with participant-based Channel WorkSurface authorization. File, channel search, conversation-history, and channel listing now honor primary/member participation, stale `cross_workspace_access` config no longer grants access, and boundary decisions emit `worksurface_boundary_*` trace events surfaced through Agent Activity.
- Hardened inbound integration callbacks for the first audit-deepening slice. GitHub now remains the reference HMAC + durable delivery-id path, BlueBubbles accepts bearer-token auth before deprecated query tokens and records durable `data.guid` replay keys, Frigate records durable `after.id` replay keys, and the admin security audit now reports integration callback auth/replay contracts from manifest metadata.
- Added local-machine/browser-control audit signals. The admin security audit now pins expected machine-control tool gates, reports active/expired/legacy/overlong machine leases, and warns on reusable browser-live pairing tokens or active paired browser sessions.
- Hardened widget DB action dispatch. Widget SQLite connections now install an authorizer that denies file-boundary operations (`ATTACH`, `DETACH`, extension loading, and VACUUM output), browser-dispatched `db_query` uses the same guard, and the admin security audit reports drift through `widget_db_sql_authorizer`.

## Live queue

1. **WorkSurface remediation phase 3.** Constrain `harness_workdir` and `widget://workspace` behind WorkSurface/operator policy decisions.
2. **Stale operator config cleanup.** Clear any persisted `cross_workspace_access` flags after confirming no deployment still depends on the old broad model; the flag is now metadata only and reported as cleanup debt.
3. **Security audit deepening.** Continue read-only checks for bot-authored skill/widget writable roots and deployment-tier exposure; inbound callback auth/replay contracts, local-machine/browser-control, and widget DB file-boundary protection now have initial audit signals.
4. **Deployment-tier gates.** Convert the `SECURITY.md` threat matrix into concrete admin readiness findings before recommending internet-exposed deployment.
5. **Skill/plugin supply-chain pass.** Review repo `.agents/skills`, runtime bot-authored skills, widget bundles, integration manifests, and future plugin import paths against provenance, permission, and review requirements.

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
- WorkSurface isolation audit syntax passed with `PYTHONPYCACHEPREFIX=/tmp/spindrel-pycache python -m py_compile app/services/worksurface_isolation_audit.py app/services/security_audit.py tests/unit/test_worksurface_isolation_audit.py tests/unit/test_security_audit.py`.
- WorkSurface isolation audit tests passed: `pytest tests/unit/test_worksurface_isolation_audit.py -q` -> `6 passed`; focused non-DB security audit slice passed: `pytest tests/unit/test_security_audit.py -q -k "WorkSurfaceIsolationStatic or BotsWithCrossWorkspaceAccess or BotsWithHighRiskApiScopes or WidgetActionApiAllowlist"` -> `8 passed, 44 deselected`.
- Shared workspace secret hardening tests passed: `pytest tests/unit/test_shared_workspace.py tests/unit/test_worksurface_isolation_audit.py -q --tb=short` -> `24 passed`; Project runtime/run-script guard slice passed: `pytest tests/unit/test_exec_command_project_runtime.py tests/unit/test_project_runtime.py tests/unit/test_run_script_tool.py -q --tb=short` -> `5 passed, 2 skipped`.
- Channel WorkSurface participant authorization syntax passed with redirected pycache; focused regression slice passed: `pytest tests/unit/test_file_ops.py tests/unit/test_read_conversation_history.py tests/unit/test_agent_activity.py tests/unit/test_worksurface_isolation_audit.py tests/unit/test_security_audit.py -q -k "CrossWorkspaceAccess or agent_activity or worksurface or BotsWithCrossWorkspaceAccess or WorkSurfaceIsolationStatic" --tb=short` -> `18 passed, 4 skipped, 291 deselected`.
- The DB-backed `tests/unit/test_security_audit.py::TestRunSecurityAudit` path still reproduces the known local fixture hang under `timeout 20`; run that orchestrator assertion in the supported Docker/Python 3.12 test runtime after the test-infra issue is cleared.
- Inbound callback security syntax passed with redirected pycache; replay drift tests passed (`16 passed`); focused BlueBubbles webhook security slice passed (`7 passed`); focused Frigate event-id/token/replay slice passed (`3 passed`); focused inbound callback audit tests passed (`2 passed`). The DB-backed `RunSecurityAudit` orchestrator still hits the known local fixture hang.
- Local-machine/browser-control audit syntax passed with redirected pycache; focused machine/browser/inbound/work-surface security slice passed: `timeout 20 pytest tests/unit/test_security_audit.py -q -k "MachineControl or BrowserLive or InboundCallbackSecurity or WorkSurfaceIsolationStatic" --tb=short` -> `12 passed, 51 deselected`.
- Widget DB action hardening syntax passed with redirected pycache; focused SQL authorizer tests passed (`1 passed, 26 deselected`; `3 passed, 11 deselected`); widget DB audit checks passed (`4 passed, 61 deselected`); full widget action authorization passed (`14 passed`). Full `test_widget_db.py` still hits the existing local Python 3.14 SQLite/to_thread hang and should be run in the supported Python 3.12/Docker test runtime.
