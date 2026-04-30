# Internal Agent Readiness

Internal AX is for agents running inside Spindrel. These agents do not
automatically have the repo-local `.agents` folder in their workspace. They use
Spindrel runtime skills, tools, APIs, integrations, widgets, Projects, Mission
Control surfaces, and readiness contracts.

## Runtime Skill Surface

- Runtime skills live under `skills/` and are product behavior.
- Audit existing runtime skills before adding a new one.
- Add a runtime skill when the in-app agent needs a repeatable procedure,
  troubleshooting flow, tool ordering checklist, or examples.
- Do not import repo-local `.agents` skills into runtime tables as a shortcut.
- Suggested runtime skills should tell the model the first action, such as
  `get_skill("widgets")` before widget-authoring work.

## Capability And Doctor Surfaces

Use the manifest and compact tools before adding new discovery APIs:

- `list_agent_capabilities` for the full runtime manifest.
- `run_agent_doctor` for "why can't I do this myself?" readiness checks.
- `get_agent_context_snapshot` for context pressure.
- `get_agent_work_snapshot` for current assigned work.
- `get_agent_status_snapshot` for liveness/status.
- `get_agent_activity_log` for recent normalized evidence.

Doctor and readiness actions should inspect, preflight, and request approval
before mutating configuration.

## Tools And APIs

Tool/API work is justified when the agent needs app-owned state or action:

- API grants, tool profiles, and enrolled working sets.
- Project cwd/runtime status and harness bridge status.
- Widget authoring/mutation surfaces.
- Integration setup, activation, binding, process, or secret readiness.
- Execution receipts and Mission Control Review evidence.

Keep side effects on existing owned write paths. Agent Readiness can stage,
preflight, and request; it should not become a second config editor.

## UX And Review Surfaces

Humans should review outcomes, not hand-edit config:

- Agent Readiness panels show missing prerequisites and proposed fixes.
- Mission Control Review groups evidence, fix packs, owner decisions, blockers,
  autofix requests, and benign/retryable/platform error classes.
- Composer/menu recommendations should point agents toward relevant skills and
  tools at the moment of work.
- Integration readiness belongs with the integration/channel/project surface
  that can actually resolve it.

## Audit Questions

- Is this problem visible to the runtime agent through a manifest, compact
  tool, or runtime skill?
- If the agent cannot act, can it produce a staged request instead of asking a
  human to inspect settings manually?
- Does the UI show the same evidence the agent sees?
- Are benign warnings normalized enough for review filtering without hiding
  real outages or platform bugs?
