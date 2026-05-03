---
title: Security track cleanup — bring docs/tracks/security.md to spec
summary: Three-step cleanup to make docs/tracks/security.md comply with docs/guides/tracks.md and .spindrel/WORKFLOW.md — extract red-team forensic detail to a new audit, append a verification appendix to the deep-review audit, rewrite the track in the canonical Status/Phase Detail/Invariants/References shape.
status: active
tags: [spindrel, plan, security, docs]
created: 2026-05-03
updated: 2026-05-03
---

# Security track cleanup

## Context

`docs/tracks/security.md` has accumulated execution detail across two parallel passes (2026-05 deep review + 2026-05-02 red-team R1–R4) and a long historic shipped-list. It violates several rules in `docs/guides/tracks.md` and `.spindrel/WORKFLOW.md`:

- **Missing `title:` frontmatter** (required by guide).
- **No Status table** — required shape is `| Phase | State | Updated |`.
- **No North Star, Key Invariants, or References sections** — all required by the guide.
- **Massive in-track shipped prose** — anti-pattern: "Don't use tracks as session logs"; the guide's Pruning rule is "compress phase prose to one paragraph in place; long dated history goes to `docs/audits/`."
- **Verification section reads as a session log** — 17 lines of dated test-run output that belong in an audit.
- **Mixed concerns** — the May deep review (13 items) and the May-02 red-team pass (R1–R4) are distinct workstreams collapsed into one running narrative.

User decisions captured upfront:
1. Treat each named pass as a phase row in the Status table (evergreen track stays single; passes are its phases).
2. Extract dense shipped prose into audits — reuse `docs/audits/security-deep-review-2026-05.md` for the deep-review history; create `docs/audits/security-redteam-2026-05.md` for R1–R4 detail. Track gets one-paragraph summaries + audit links.
3. R4 Phase 2 stays as an inline bullet on the track (not a plan file). Apply this norm to future bounded security tickets too.
4. Delete the dated Verification block from the track; preserve it as a Verification appendix in the deep-review audit.

## Approach

Three files, in this order:

### 1. New audit: `docs/audits/security-redteam-2026-05.md`

Frontmatter (`title`, `summary`, `status: complete`, `tags`, `created: 2026-05-02`, `updated: 2026-05-03`).

Sections (lift verbatim from current `security.md`):
- **R1 — Integration inbound prompt-injection laundering** (Phase 1 + Phase 2 detail, current security.md lines 102–114).
- **R2 — `run_script` raw-Python egress** (Phase 1 + Phase 2 detail, lines 116–127).
- **R3 — `read_container_logs` control_plane bump** (lines 129–130).
- **R4 — `propose_config_change` self-mutation Phase 1** (lines 132–138).
- **Phase 2 follow-ups (status as of last update)**: R1 user-trust narrowing queued; R4 Phase 2 (UI badge / per-field friction / delegation tracing) queued.

This becomes the durable forensic record of the red-team pass.

### 2. Append to `docs/audits/security-deep-review-2026-05.md`

- **Verification appendix**: lift the entire current Verification section from `security.md` (lines 156–173) verbatim into a new `## Verification (historic test runs)` section at the bottom. Preserves the dated test invocations.
- Sanity-check no overlap with what the audit already covers; if items 1–13 are already detailed there, the track's compressed paragraph + audit link is sufficient. Otherwise extract those item bodies from `security.md` (lines 56–71) too.

### 3. Rewrite `docs/tracks/security.md` to spec

```markdown
---
title: Security Architecture
summary: Evergreen security track for Spindrel's self-hosted runtime. Tracks deep-review passes, red-team passes, supply-chain signing, sandboxing, and standing watch list.
status: active
tags: [spindrel, track, security, agentic-ai]
created: 2026-04-30
updated: 2026-05-03
---

# Security Architecture

## North Star
Strong-by-default boundaries for trusted self-hosted deployments; fail-closed at auth, scopes, tool policy, path resolution, widget dispatch, integration callbacks, harness/local-machine leases. Each new product surface earns a security review pass before it leaves "active product buildout."

## Status
| Phase | State | Updated |
|---|---|---|
| 2026-04 hardening foundation | done | 2026-04-30 |
| 2026-05 deep review (13 items) | done | 2026-05-01 |
| 2026-05-02 red-team R1 | done | 2026-05-02 |
| 2026-05-02 red-team R2 | done | 2026-05-02 |
| 2026-05-02 red-team R3 | done | 2026-05-02 |
| 2026-05-02 red-team R4 Phase 1 | done | 2026-05-02 |
| 2026-05-02 red-team R4 Phase 2 (UI visibility) | queued | 2026-05-03 |
| Container sudoers cleanup | deferred | 2026-05-02 |

## Phase Detail

### 2026-04 hardening foundation — done
Widget action authorization boundary, WorkSurface isolation audit + guide, ambient Secret Values removal from shared workspace exec, channel-participant-based file/history/search authorization, inbound integration callback hardening (GitHub HMAC reference / BlueBubbles bearer / Frigate replay keys), local-machine + browser-control audit signals, widget DB SQL authorizer, widget://workspace shared-root scope policy. See `docs/audits/security-deep-review-2026-05.md` for evidence.

### 2026-05 deep review — done
13 items across Critical / High / Medium / Low tiers: MCP outbound URL guard, encryption fail-fast, tool-result redaction, auth route rate-limit parity, approval rule origin_kind, widget path symlink rejection, run_script nested-call tightening, backup encryption at rest, supply-chain signing Phase 1+2, migration 130 downgrade guard, cross_workspace_access cleanup, file-read untrusted wrapping, autonomous-opt-in toggle, widget JWT revocation, CI dep audit + actions SHA pinning + deployment_tier_readiness signal. Full per-item detail and verification log: `docs/audits/security-deep-review-2026-05.md`.

### 2026-05-02 red-team R1–R4 — mostly done
Authorized red-team pass against the agent-exfiltration model. Outcome: integration inbound wrap (R1 P1+P2), run_script kernel-level netns sandbox + UDS bridge (R2 P1+P2), raw-log tools bumped to control_plane (R3), autonomous-origin self-mutation refused + audit-logged (R4 P1). Full forensic detail: `docs/audits/security-redteam-2026-05.md`. Live follow-ups below.

#### R4 Phase 2 — queued
UI visibility for self-mutation. Three deliverables:
- **SELF badge** on approval cards when `arguments.target_id == caller_bot_id`.
- **HIGH-IMPACT field pill** + two-click confirm when the field is in `_HIGH_IMPACT_SELF_BOT_FIELDS`.
- **Delegation chain trace** (`A → B → edit(A)`) — surface the spawn chain on the approval card so indirect self-edits are visible.

Mechanism: thread `current_run_origin`, `current_bot_id`, and a new `current_delegation_chain` ContextVar into `ToolApproval.approval_metadata.security_context` at approval creation. UI reads the metadata; defensive default ("no flags") when missing on legacy rows.

R4 Phase 2 file list:
- `app/agent/context.py` — add `current_delegation_chain: ContextVar[tuple[str, ...]]`
- `app/agent/subagents.py`, `app/services/delegation.py` — push parent bot id into chain
- `app/agent/tool_dispatch.py` (`_create_approval`, `_create_approval_state`) — populate `security_context` in `extra_metadata`
- `app/tools/local/propose_config_change.py` — promote `_HIGH_IMPACT_SELF_BOT_FIELDS` to public name
- `ui/app/(app)/admin/approvals/index.tsx` — render pills + two-click confirm + hide "Allow always" when high-impact self-edit
- new `tests/unit/test_approval_security_context.py` — ~6 cases pinning metadata shape
- same-edit doc updates: this track row + `docs/fix-log.md`

#### R1 user-trust narrowing — queued
Active-turn untrusted wrapper currently treats all human integration turns as trusted to preserve operator UX. Phase 2 should stamp integration metadata with an explicit trust decision after correlating external user id (e.g. Slack user id) to a configured Spindrel user / channel participant / bot operator; unknown group-chat participants and bot/webhook senders should remain environment-tier and be wrapped before LLM replay. No file list yet — design open.

#### Container sudoers — deferred
`app/services/integration_deps.install_system_package` (used by `integration_admin` runtime installs and `integrations/sdk.py` chromium auto-install) genuinely depends on the passwordless `sudo apt-get` grant. Removing it requires a build-time install path migration first.

## Key Invariants
- Fail-closed at every boundary: auth, scopes, tool policy, path resolution, widget action dispatch, integration callbacks, harness leases, local-machine leases.
- Untrusted input gets `<untrusted-data>`-wrapped at the LLM-bound chokepoint (`_strip_metadata_keys` for replay, `inject_message`/`_enqueue_chat_turn` for active turn). Stored bodies stay raw; idempotent wrap.
- `run_script` runs inside an empty network namespace; spindrel.py reaches the agent server only through the UDS bridge. Probe-on-startup with audit-signal fallback when kernel/seccomp blocks user namespaces.
- Every self-mutation (refused or applied) is audit-logged via `log_self_mutation`.
- Skill / widget rows persist HMAC signatures; verify-on-read at the loader; admin "trust current state" two-step recovery action.
- No public-internet deployment recommendation until the deployment-tier matrix has green gates.

## Watch list
- Browser-origin control surfaces: widget iframes, browser-live pairing, local companion, harness terminals, app-server / native runtime bridges.
- Ambient self-improvement paths: `manage_bot_skill`, widget authoring tools, config repair actions, agent capability repair actions.
- Long-running autonomous loops: heartbeats, scheduled tasks, widget crons / events, harness schedules, standing orders.

## Audit frame
CIA + agentic risks (goal hijack, tool misuse, privilege abuse, skill/plugin supply chain, code execution, memory/context poisoning, inter-agent spoofing, cascading failure, human-trust exploitation, rogue autonomy). External frame anchored to OWASP Top 10 for Agentic Applications, OWASP Agentic Skills Top 10, OWASP LLM Top 10 2025 (links in `docs/audits/security-deep-review-2026-05.md`).

## References
- `docs/guides/security.md` — principles guide
- `docs/audits/security-deep-review-2026-05.md` — May deep-review forensic record + verification log
- `docs/audits/security-redteam-2026-05.md` — May-02 red-team R1–R4 forensic record
- `SECURITY.md` (repo root) — deployment-tier threat matrix
- `docs/architecture-decisions.md` — load-bearing security decisions (run_script egress sandbox, supply-chain signing, etc.)
```

Net effect: track shrinks from ~173 lines to ~85 lines. Status table satisfies the guide. Phase Detail compresses each shipped pass to one paragraph + audit link. Key Invariants captures what the next agent must not break. References gives one-click navigation.

## Files to edit

| Action | File |
|---|---|
| New | `docs/audits/security-redteam-2026-05.md` (carries R1/R2/R3/R4 detail extracted from the track) |
| Append | `docs/audits/security-deep-review-2026-05.md` (Verification appendix + any deep-review item bodies not already covered) |
| Rewrite | `docs/tracks/security.md` (new shape per the template above) |

## Reuse
- Existing `docs/audits/security-deep-review-2026-05.md` — already the home for May deep-review history; just append.
- Existing `docs/guides/security.md` — referenced from the track, not duplicated.
- Existing `docs/architecture-decisions.md` — load-bearing security ADRs already exist (R2 sandbox, signing); track References point at them rather than restating.

## Verification

```bash
# Frontmatter satisfies tracks.md contract
grep -c '^title:\|^summary:\|^status:\|^tags:\|^created:\|^updated:' docs/tracks/security.md   # expect 6

# Track is now Status-table-shaped + has the required sections
grep -E '^## (North Star|Status|Phase Detail|Key Invariants|References)' docs/tracks/security.md  # expect 5 hits

# Audits exist + are non-empty
test -s docs/audits/security-redteam-2026-05.md
grep -c '^## Verification' docs/audits/security-deep-review-2026-05.md  # expect ≥1

# No content lost: every R-id and shipped item from the old track resolves somewhere
for tag in R1 R2 R3 R4 'Phase 1' 'Phase 2' 'deep review' 'control_plane' 'netns'; do
  grep -qr "$tag" docs/tracks/security.md docs/audits/security-*.md || echo "MISSING: $tag"
done
```

Manual: open the new track top-to-bottom; confirm Status + Phase Detail + Invariants are scannable in <60 seconds; click each audit link and confirm the forensic detail is intact.

## Out of scope

- **Other tracks' compliance**. This pass only touches security. The same audit could be applied to harness-sdk, mission-control-vision, projects, etc. — separate plan if/when wanted.
- **Shipping R4 Phase 2 itself**. Cleanup only; implementation stays queued.
- **Renaming `security.md`**. Filename is fine per the guide.
- **`docs/roadmap.md` row**. The roadmap row already points at the track; only update its summary text if it drifts materially from the new track's summary line.

## Risks / open questions

- **Audit file format**. Audits don't have a frontmatter contract as strict as tracks. Mirror the deep-review audit's existing shape so the two security audits feel consistent.
- **Deep-review audit overlap**. If `docs/audits/security-deep-review-2026-05.md` already covers items 1–13 in detail, the track's compressed paragraph + audit link is sufficient; no need to copy item bodies. Verify before rewriting the track.
- **R1 P2 user-trust narrowing**. Currently a deferred bullet inside R1; hoisted to a top-level "queued" entry under R4 Phase 2 so both queued items are visible at the same level. Cosmetic — content unchanged.

## On completion

- Set this plan's `status: executed` and link from the security track's References section.
- Add one-line entry to `docs/fix-log.md` recording the cleanup pass.
