# External Agent Readiness

External AX is for agents outside Spindrel runtime: code agents working in this
repo, agents evaluating the project from GitHub, and integrator agents calling a
running server.

## Discovery Layer

- `llms.txt` at repo root and `GET /llms.txt` for running servers.
- README first screen answers what it is, what problem it solves, install, first
  call, expected output, and links to machine-readable surfaces.
- `.agents/manifest.json` indexes repo-local development skills. It remains
  `repo-dev-only` and `runtime_import: false`.
- Canonical guides describe public contracts; vault files describe local project
  state and must not be required by outside contributors.

## Install And Setup

- One clean setup command should be documented.
- `.env.example` should explain every variable, whether it is required, where
  to get it, and a safe example value.
- Setup, init, and migration commands should be idempotent.
- Errors should include next-step suggestions rather than only failure prose.

## Integration Surface

- Prefer stable machine-readable schemas such as `/openapi.json`.
- Agent-facing descriptions should say when to use the endpoint and what it
  returns, not only repeat parameter names.
- CLI commands, scripts, and diagnostics should support structured output when
  agents need to parse them.
- Health/info endpoints are appropriate tools because they expose fresh runtime
  state that cannot live in static docs.

## Repo-Dev Skill Checks

For `.agents` skills:

- Keep `SKILL.md` short enough to load as procedure.
- Move detailed variants to first-level `references/` files.
- Add `agents/openai.yaml` only for UI-facing skill metadata.
- Do not create README, changelog, or auxiliary docs inside the skill folder.
- Add tests for boundaries that are easy to regress, especially runtime import
  confusion.

## Audit Questions

- Can a new code agent discover the right repo guidance without reading a long
  chat transcript?
- Does the repo expose current install and first-call information in one place?
- Are public docs and runtime OpenAPI surfaces generated or checked from the
  same source where feasible?
- Are repo-dev `.agents` skills clearly separated from product runtime skills?
