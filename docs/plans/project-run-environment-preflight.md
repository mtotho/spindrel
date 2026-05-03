---
title: Project Run Environment Preflight
summary: Move Project run setup into a generic pre-agent phase so scheduled isolated runs prepare local-equivalent surfaces before the model starts.
status: active
created: 2026-05-03
updated: 2026-05-03
---

# Project Run Environment Preflight

## Summary

Project scheduled runs should behave like unattended local work: Spindrel
prepares an isolated worktree, private Docker daemon, dependency stack, runtime
env, dev target ports, repo setup commands, readiness checks, and required
artifacts before the agent starts. If preparation fails, the run blocks visibly
with a transcript event and receipt without spending a model turn.

This follows the Symphony-shaped split: repo-owned workflow policy,
orchestrator-owned dispatch/preflight state, isolated workspaces, and clear
observability.

## Implementation Plan

1. Clean the current patch scope first.
   - Remove unrelated image-input changes from this work.
   - Remove Spindrel-specific helper names from generic Project runtime code.
   - Keep repo-specific harness setup only in Spindrel repo docs/profile config.
   - Do not deploy, restart, or configure any remote server as part of this plan.

2. Define the generic run environment profile contract.
   - Canonical home is the user's repo at `.spindrel/profiles/<id>.yaml` (or
     `.yml` / `.toml`). `.spindrel/` is reserved for Spindrel-imposed
     formatting and file management for operating any repo through Spindrel,
     so the run-environment profile shape lives there alongside `WORKFLOW.md`,
     `runs/`, and `audits/`.
   - Resolution precedence at run time, last-write-wins:
     1. Blueprint snapshot `run_environment_profiles` (operator-curated
        defaults installed when the Blueprint is applied).
     2. Project metadata `run_environment_profiles` (per-Project overrides
        edited from the UI/API without touching the repo).
     3. Repo-file `.spindrel/profiles/<id>.yaml` checked into the user's repo
        (authoritative for Git-tracked iteration; survives clone/fork).
     A single `default_run_environment_profile` is resolved with the same
     precedence.
   - Add schedule/manual-run field `run_environment_profile` as a string
     profile id.
   - V1 profile shape: `name`, `env`, `setup_commands`,
     `background_processes`, `readiness_checks`, `required_artifacts`,
     `timeout_seconds`, and `work_surface_modes` (allowed list; default
     `["isolated_worktree"]`).
   - Env handling rule: secret values are exposed to commands through the OS
     env only. The renderer never substitutes secret values into command
     strings, profile YAML, receipts, or transcript previews. Non-secret
     interpolation (assigned dev-target ports, `DOCKER_HOST`, dependency stack
     env keys) is allowed through `${VAR}` / `{{VAR}}`; the registry of
     interpolatable keys is explicit, not "anything in env."
   - Profile loader emits structured load errors (missing file, schema
     violation, unknown overlay key) without aborting the run; failures
     surface through the validator and the preflight receipt, not as silent
     "no profile configured."

3. Move profile execution into the task runner pre-agent gate.
   - `create_project_coding_run` persists the task, selected profile id, work
     surface intent, branch, and prompt only.
   - Before model launch, the task runner ensures the work surface/session
     environment, prepares private Docker when isolated, preflights dependency
     stacks, executes the selected profile, runs readiness/artifact checks,
     records preflight state, then launches the model.
   - Honor `work_surface_mode`. `isolated_worktree` runs go through
     `ensure_isolated_session_environment`; `shared_repo` runs do not create a
     private worktree or private Docker daemon. In `shared_repo` mode only the
     non-mutating profile fields apply (`env`, `readiness_checks`,
     `required_artifacts`); `setup_commands` and `background_processes` are
     rejected at validation unless the profile's `work_surface_modes` opts the
     id into shared-repo execution. Setup that mutates a shared checkout is a
     race against the human operator and must be opted in explicitly.
   - Run all command/readiness execution off the worker event loop. Use
     `asyncio.create_subprocess_exec`, `asyncio.wait_for`, and
     `asyncio.to_thread` for unavoidable blocking I/O. No
     `subprocess.run` / `urllib.request` / `time.sleep` on the async path.
     Cancellation must terminate the active step deterministically and tear
     down already-started background processes.
   - Own background-process lifecycle. Persist process group ids per profile
     step in preflight state, attach them to the session execution
     environment, and connect cleanup to task completion, task cancellation,
     and any later preflight failure. A profile that starts step 2 background
     and then fails step 3 must not leave step 2 running.
   - Redact captured stdout/stderr and rendered command summaries with the
     Project runtime's value-aware redactor
     (`ProjectRuntimeEnvironment.redact_text()`), not just the global
     `secret_registry.redact()`. Project-bound secrets that do not match
     global patterns must still be redacted from receipts, transcript
     messages, and `execution_config`.

4. Make preflight observable.
   - Add a visible session message for preflight success or failure.
   - Add a Project run receipt on preflight failure with `status=blocked`.
   - Include secret-safe evidence: profile id, command ids, exit codes,
     readiness status, env key names, artifact paths, Docker endpoint presence,
     dependency stack status, and assigned ports.
   - Never include secret values or full env dumps.

5. Block cleanly on failure.
   - Any setup command, background process, readiness check, or required
     artifact failure marks the run blocked before model launch.
   - The receipt says what failed and what to fix.
   - Loop continuation rule (concrete): a preflight blocker is "identical" to
     the previous tick when `(profile_id, first_failed_step_name,
     command_or_check_id, exit_code_or_status)` matches. On the second
     consecutive identical blocker the schedule downgrades to `needs_review`
     with a receipt that links the two failed runs. Transient failures (no
     match) keep looping until the normal schedule cap. Tests cover both
     paths and assert no model spend after the downgrade.

6. Dogfood Spindrel harness parity through a profile.
   - Sequencing: this step depends on the profile-source contract (item 2)
     being settled and the repo-file loader (`.spindrel/profiles/`) landing,
     so the live Spindrel `harness-parity` profile is authored once in its
     final home and not migrated mid-flight.
   - Add a Spindrel-repo `.spindrel/profiles/harness-parity.yaml` profile
     declaration. The profile prepares `scratch/agent-e2e/harness-parity.env`
     inside the isolated worktree, brings up any required dev target through
     declared `background_processes` + `readiness_checks`, and exits with
     non-zero if bootstrap fails.
   - Any repo-specific allow flag belongs in that profile env, not in generic
     code. Generic Project runtime must not know the names
     `prepare-harness-parity`, `scripts/agent_e2e_dev.py`, or
     `harness-parity.env`.
   - The harness parity skill requires the prepared artifact and blocks if the
     profile failed; it does not run bootstrap itself.

7. Fix run brief quality.
   - Empty schedule prompts are rejected.
   - Harness parity schedule briefs must name source track/skill, tier or
     default tier, stop condition, evidence expectations, and artifact update
     target.
   - A file path alone is not a sufficient run brief.

8. Update durable docs.
   - Keep this plan as the implementation design.
   - Link this plan from `docs/tracks/projects.md`.
   - Keep `docs/tracks/harness-sdk.md` focused on harness parity state, not
     generic Project runtime architecture.
   - Keep `.spindrel/WORKFLOW.md` as policy: profiles own pre-agent setup;
     agents consume prepared surfaces. Add a short subsection naming
     `.spindrel/profiles/<id>.yaml` as the canonical profile home and the
     three-layer overlay precedence so external users see the contract before
     authoring a profile.

9. Audit `.agents/skills/` for unattended-run correctness (gating, not
   polish).
   - Treat the skill audit as a hard prerequisite for the dogfood proof in
     item 5: a skill that quietly assumes operator vault paths, an interactive
     terminal, a particular harness's tool surface, or an out-of-repo
     bootstrap step can break an unattended Project run even when the runtime
     preflight is green.
   - Concrete gates before the audit closes:
     - `.agents/manifest.json` indexes every `.agents/skills/*/SKILL.md` or
       intentionally excludes it via a documented `excluded` list. A
       regression in `tests/unit/test_repo_agent_skills.py` fails when a
       skill folder is discoverable only by filesystem accident.
     - `tests/unit/test_repo_agent_skills.py::test_new_repo_agent_skills_keep_runtime_boundary_explicit`
       passes; the `repo-dev skill` boundary phrase is normalized across all
       indexed skills.
     - No skill instructs the agent to run unit tests in Docker or contradicts
       `AGENTS.md` "do not wrap unit tests in Docker." Resolve in favor of
       reporting the local Python blocker.
     - No skill assumes a specific harness's delegation API
       (`subagent_type=Explore`, Claude-specific `Task` tool wording, etc.)
       in instructions meant to run portably across Codex, Claude Code, and
       unattended Spindrel Project runs. State the exploration outcome
       generically; put harness-specific mechanics in adapter notes.
     - No skill depends on `~/personal/`, `~/.claude/`, vault session logs,
       or the operator's laptop for paths or evidence. Evidence comes from
       repo, API, or run receipts.
     - Decide whether the four meta-audit skills (`agentic-readiness`,
       `spindrel-conversation-quality-audit`, `spindrel-project-run-review`,
       `spindrel-security-audit`) and `improve-codebase-architecture` stay
       separate or consolidate; document the decision so the manifest does
       not keep growing overlapping triggers.

10. Add a profile validator / dry-run path.
    - `validate_run_environment_profile(project, profile_id)` resolves the
      profile through the three-layer overlay, lints schema, env-key
      references, work-surface compatibility, and required-artifact paths
      without executing commands or starting background processes.
    - Surface the validator through the API (admin) and an agent-facing
      tool for repo-dev skills, so a user authoring a profile gets
      structured errors before scheduling a real run.
    - Schedule create/update calls run the validator and reject obviously
      malformed profiles up-front instead of failing only at the next tick.

11. Document `shared_repo` profile semantics.
    - In `docs/guides/projects.md` (and link from this plan): which profile
      fields apply in `shared_repo`, which are gated to `isolated_worktree`,
      what cleanup the platform owns when a `shared_repo` profile starts
      background processes, and the operator-visible warning when a profile
      is being used outside its declared `work_surface_modes`.

## Public Interfaces

- Manual Project coding-run create accepts optional `run_environment_profile`.
- Project coding-run schedule create/update/out includes optional
  `run_environment_profile`.
- Project/Blueprint metadata supports `run_environment_profiles` as one of
  three overlay layers; the canonical home is repo-file
  `.spindrel/profiles/<id>.yaml` with Blueprint snapshot and Project metadata
  as overrides.
- Run detail/readiness surfaces include `run_environment_preflight` on
  `ProjectCodingRunOut` and `_coding_run_row()`. UI hand-written types and
  `ui/openapi.json` / `ui/src/types/api.generated.ts` are regenerated.
- Receipts may include `metadata.category = "run_environment_preflight"` for
  pre-agent blockers and `metadata.category = "run_environment_loop_stop"`
  for repeated-blocker schedule downgrades.
- Agent-facing `schedule_project_coding_run` / `create_project_coding_run`
  tools expose `run_environment_profile` consistently with the API.
- Validator surface: admin API endpoint and an agent tool that returns
  resolved profile, overlay source per field, and structured lint errors
  without executing commands.

## Test Plan

- Unit tests cover profile resolution across the three overlay layers,
  schedule/manual persistence, task-runner preflight env, setup failure,
  missing artifact failure, successful preflight, generic-code repo
  agnosticism, and empty schedule brief rejection.
- Regression: a Project coding run with `work_surface_mode=shared_repo`
  reaches the model path without invoking
  `ensure_isolated_session_environment` and without creating private Docker.
- Regression: a profile with `setup_commands` is rejected at validate time
  for `shared_repo` unless the profile's `work_surface_modes` opts in.
- Regression: a Project secret value echoed by a profile command never
  appears in `execution_config`, receipt metadata, or transcript messages
  (covers `ProjectRuntimeEnvironment.redact_text()` integration).
- Regression: profile commands run via async subprocess; a 10s readiness
  loop does not block other concurrent task-runner work in the test loop.
- Regression: a profile that starts a background process in step 2 and
  fails in step 3 leaves no live process group after preflight rejection.
- Regression: two consecutive identical preflight blockers downgrade the
  schedule to `needs_review` and emit a `run_environment_loop_stop` receipt;
  no model turn is spent on the second tick.
- Regression: `tests/unit/test_repo_agent_skills.py` enforces both the
  manifest-coverage rule (every `.agents/skills/*/SKILL.md` indexed or
  documented as excluded) and the runtime-boundary phrase across indexed
  skills, including the new audit/loop skills.
- Validator unit + integration: malformed profile is rejected at schedule
  create/update; resolved profile shows correct overlay source per field.
- Integration tests cover a generic fixture Project scheduled run that
  prepares dependencies, starts a dev server on an assigned port, passes
  readiness, launches the agent, and publishes a receipt.
- Dogfood proof covers the Spindrel `.spindrel/profiles/harness-parity.yaml`
  profile creating `scratch/agent-e2e/harness-parity.env` inside an isolated
  run before parity execution, with the parity-loop skill verifying the
  prepared artifact rather than running bootstrap itself.

## Critical Review Update - 2026-05-03

This patch is directionally right but should not ship as complete until these
gaps are closed or explicitly deferred.

| Priority | Gap | Required next action |
|---|---|---|
| P0 | `task_run_host` now appears to ensure an isolated session environment for every Project coding run with a session, without honoring `work_surface_mode=shared_repo`. | Preserve work-surface semantics: shared-repo runs must not create private worktrees/Docker unless explicitly requested. Add a regression where `shared_repo` does not call isolated environment setup and still reaches the model path. |
| P0 | The plan says run detail/readiness surfaces include `run_environment_preflight`, but `ProjectCodingRunOut` and `_coding_run_row()` still only expose `dependency_stack_preflight` and `execution_environment`. | Add `run_environment_preflight` to the backend run row/schema, update UI hand-written and generated API types, and regenerate `ui/openapi.json` / `ui/src/types/api.generated.ts`. |
| P0 | Profile setup executes blocking `subprocess.run`, `Popen`, `urllib.request`, and `time.sleep` directly inside the async task-runner path. Long setup or readiness loops can block the worker event loop. | Move command/readiness execution behind async subprocesses or `asyncio.to_thread`, with bounded cancellation and deterministic timeout behavior. |
| P0 | Background process lifecycle is not owned beyond recording a PID/log path. Failure paths can leave started background processes alive, and successful runs have no cleanup handoff. | Persist process groups in preflight state and connect them to session-environment cleanup / task completion. On any later preflight failure, terminate processes already started. |
| P0 | Redaction currently uses generic `secret_registry.redact()`, not the Project runtime environment's known secret values. Rendered commands/stdout/stderr can still persist Project-bound secrets when they do not match global patterns. | Redact command strings and captured output with `ProjectRuntimeEnvironment.redact_text()` or equivalent value-aware redaction. Add a regression where a Project secret echoed by a profile never appears in `execution_config`, receipt metadata, or transcript messages. |
| P1 | HTTP readiness treats any status `200 <= status < 500` as ready. A 404/401 from the wrong service can satisfy readiness even though the declared dev target is not usable. | Support expected status/body/method or default to 2xx for readiness checks; record enough evidence to distinguish "port listening" from "target ready". |
| P1 | Profile placement is still an implicit metadata convention; the current loader only reads `Project.metadata_["run_environment_profiles"]` / blueprint snapshot. | Per Implementation Plan item 2: implement the three-layer overlay with `.spindrel/profiles/<id>.yaml` as the canonical repo-file home and Blueprint snapshot + Project metadata as overrides. Specify path/security rules before reading the repo file (limit to `.spindrel/profiles/`, no symlinks out of repo, size cap, schema validation). |
| P1 | Schedule/tool surfaces do not yet expose the new profile field consistently. The local `schedule_project_coding_run` tool cannot select a profile, and UI types are stale. | Thread `run_environment_profile` through agent-facing scheduling tools and UI form state after the backend contract is stable. |
| P1 | There is no integration or live dogfood proof that a generic scheduled isolated run prepares deps/dev/artifacts and then launches the agent without spending a failed model turn. | Add a generic fixture integration test and one live Spindrel `harness-parity` dogfood run after the profile is configured on the actual Project/Blueprint. |
| P0 | The repo-dev skill audit is **gating for unattended runs**, not polish. A skill that quietly assumes operator vault paths, an interactive terminal, or a particular harness's tool surface can break a Project coding run even when runtime preflight is green. Today: 8 skill folders are not indexed in `.agents/manifest.json` (`improve-codebase-architecture`, `spindrel-dev-retro`, `spindrel-e2e-development`, `spindrel-harness-parity-loop`, `spindrel-project-run-review`, `spindrel-security-audit`, `spindrel-session-environment-operator`, `spindrel-supervised-loop`); `tests/unit/test_repo_agent_skills.py::test_new_repo_agent_skills_keep_runtime_boundary_explicit` fails on `spindrel-harness-operator`; `spindrel-security-audit/SKILL.md` directs Docker/Python 3.12 fallback for unit tests, contradicting `AGENTS.md`; `improve-codebase-architecture` and `spindrel-security-audit` use Claude-specific `subagent_type=Explore` wording; `spindrel-docs-operator`, `spindrel-dev-retro`, `spindrel-project-run-review` reference `~/personal/`/vault session logs. | Per Implementation Plan item 9: index or intentionally exclude every skill folder, normalize the runtime-boundary phrase, remove the Docker contradiction, replace harness-specific delegation wording with portable phrasing, drop vault/laptop assumptions, and decide on consolidation of the four meta-audit skills + `improve-codebase-architecture`. Land before the dogfood proof — a wrong skill silently breaks unattended runs. |

## Session Handoff - 2026-05-03

The product direction appears to be:

- Spindrel Project runs should feel like unattended local agent work, not like a
  chat prompt that asks the model to bootstrap its own workspace.
- Repo-owned contracts are the source of truth: `AGENTS.md`,
  `.spindrel/WORKFLOW.md`, tracks, plans, repo-local skills, Project/Blueprint
  profile config, and run receipts. Agents should not need a private vault,
  private laptop paths, or operator memory to understand the job.
- The platform owns the lifecycle before the first model turn: selected repo and
  branch, isolated worktree when requested, private Docker daemon, dependency
  stack, declared run environment profile, background dev processes, readiness
  checks, required artifacts, secret-safe state, and visible blocked/success
  receipts.
- Repo-specific setup belongs in Project/Blueprint profile declarations or
  repo-local docs/skills. Generic app runtime must stay repo-agnostic; it should
  execute declared profile steps, not know Spindrel helper names such as
  `prepare-harness-parity` or `scripts/agent_e2e_dev.py`.
- The Symphony-like shape matters: durable repo state, explicit lifecycle,
  isolated work surfaces, progressive-discovery instructions, and observable
  receipts that let a human see what happened without spelunking transient
  process logs.

Roadmap (ordered for unattended-run correctness):

1. Stabilize the backend contract already started here: persist
   `run_environment_profile`, run dependency/profile preflight in
   `task_run_host` before model launch, block without model spend on failure,
   and emit transcript/receipt evidence.
2. Close the P0 review gaps: preserve `shared_repo` semantics, expose
   `run_environment_preflight` on the run row/schema/UI types, replace
   blocking `subprocess`/`urllib`/`time.sleep` on the async task-runner path
   with async equivalents, own background-process lifecycle including failure
   cleanup, and redact with the Project runtime's value-aware redactor.
3. Settle the profile-source contract before authoring real profiles. Land
   `.spindrel/profiles/<id>.yaml` as the canonical home with Blueprint
   snapshot and Project metadata as overlays, ship the validator, and thread
   profile selection through schedule API, agent-facing tools, and UI.
   Authoring `harness-parity` against an unsettled contract just buys
   migration churn.
4. **In parallel with steps 2–3, complete the repo-dev skill correctness
   audit (escalated to P0 above).** A wrong skill is indistinguishable from a
   wrong profile from the unattended run's perspective: the model gets bad
   instructions and produces garbage evidence even on a perfectly prepared
   surface. Index every `.agents/skills/*/SKILL.md`, normalize the
   runtime-boundary phrase, remove the AGENTS.md Docker contradiction, drop
   harness-specific delegation wording, drop vault/laptop dependencies, and
   resolve the meta-audit skill consolidation question.
5. Configure the real Spindrel `.spindrel/profiles/harness-parity.yaml`
   profile in this repo. The profile prepares `scratch/agent-e2e/harness-parity.env`
   and any dev target before the parity-loop agent starts. Generic Project
   runtime stays repo-agnostic.
6. Prove the generic behavior with tests and dogfood: a fixture scheduled
   isolated Project run that starts deps/dev/artifacts before the model, plus
   a live harness-parity scheduled run on the real Spindrel Project once the
   profile is checked in. Both proofs depend on items 3 and 4 being green.

Review ask for the next reviewer:

- First, challenge this inferred vision and roadmap. If it is wrong, update this
  section before touching code.
- Then review the current patch against the P0/P1 table above. Prioritize
  defects that would let scheduled isolated Project runs spend model turns
  before setup is ready, leak secrets, leave processes behind, or hide the
  preflight outcome from the run receipt/API.
- Treat the skill edits as directionally intentional, not random churn, but
  still review them critically for manifest coverage, portability, and
  contradiction with `AGENTS.md`.
- Do not deploy, restart, touch the remote server, or commit unless explicitly
  asked.

## Assumptions

- No remote deploy, restart, or configuration occurs during this work unless
  explicitly requested.
- No commits are made unless explicitly requested.
- Generic product code stays repo-agnostic.
- Spindrel-specific harness setup belongs in Spindrel repo workflow/profile
  config and repo-local skills only.
