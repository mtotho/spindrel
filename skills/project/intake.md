---
name: Project Intake
description: >
  Recognise when the user is dropping a rough bug, idea, or future-work note
  in conversation; capture it as a Project intake entry written to whatever
  substrate the user configured (a file in the repo, a folder, or a hand-off
  to an external tracker). Triage on demand into proposed Run Packs.
triggers: add this issue, save this bug, issue inbox, report this issue, triage later, sweep issues, group these notes, intake, rough idea, side note
category: project
---

# Project Intake

Use this skill in any Project-bound channel. Intake is conversational - the
agent *recognises* drop-in items, captures them, and stays out of the way.
The user does not have to say "save this".

## Mental Model

- **Intake note** - a pending rough capture attached to the Project. Lives in
  the Project's chosen substrate (a file in the canonical repo, a folder of
  files, or an external tracker the user already uses). Not a channel note,
  not a Run Pack, not launched work.
- **Run Pack** - a proposed launchable unit grouped from one or more intake
  notes or from a planning conversation. See `project/plan/run_packs`.
- **Project coding run** - starts only after a human launches a Run Pack.
  Capturing or listing intake never launches anything.

The Project's intake convention is set once during `project/setup/init` and
overridden any time the repo says so via `.spindrel/WORKFLOW.md`. Resolution
order:

1. **`repo_workflow.sections.intake`** from `get_project_factory_state` -
   when non-null, that section in `.spindrel/WORKFLOW.md` is the canonical
   convention. Follow it verbatim - it names the schema, the file path, the
   commit cadence, and any GitHub-issue rules. The repo-owned file always
   wins over Spindrel's persisted settings.
2. **`intake_config`** from `get_project_factory_state` - the persisted
   convention recorded during setup. Use this only when WORKFLOW.md does not
   carry an `## Intake` section.

The generic four-substrate routing below is the fallback when neither source
overrides it.

## Recognition Rules

When you see a side comment that is clearly not the active topic, treat it as
an intake candidate. Common shapes:

- "oh and X is broken"
- "we should also..."
- "annoying that Y"
- "future idea: Z"
- "make a note - ..."
- "remind me to fix..."
- "btw the W page is slow / ugly / missing..."

These are intake. The active question or task in the conversation is **not**
intake - keep working on it.

## Capture Pattern

1. Acknowledge briefly inline (one short sentence). Do not interrupt the
   thread the user is on.
2. **Check the repo contract first.** Read `repo_workflow.sections.intake`
   from `get_project_factory_state`. If non-null, follow that section's
   instructions for what to capture and where it lands. Use `file_ops`
   directly when the section dictates a custom schema or path that
   `capture_project_intake` cannot express - the repo-owned contract wins.
3. Otherwise call `capture_project_intake` once for each discrete note.
   Required: `title`. Optional: `kind` (`bug` | `idea` | `tech-debt` |
   `question`, default `idea`), `area` (subsystem path), `body` (1-10 lines).
4. The tool reads `intake_config.kind` from the Project and routes:
   - `repo_file` -> appends to the configured file in the canonical repo.
   - `repo_folder` -> writes a new timestamped `.md` file to the folder.
   - `external_tracker` -> returns a hand-off message; **read it back to the
     user** so they can paste into their tracker. Spindrel does not call
     external APIs from this tool.
   - `unset` -> returns a warning. Tell the user the convention is not
     configured and offer to run `project/setup/init` to fix it; surface the
     captured note in chat so it is not lost.
5. Confirm capture in one line: "Noted (kind=bug). Wrote to
   `<relative_path>` in the canonical repo." For external trackers, use the
   tool's hand-off instructions verbatim.
6. **Do not** open a Run Pack, launch a coding run, or write into channel
   notes. The configured substrate is the durable home.

If the note would be useless without one missing fact, ask exactly one
clarifying question. Otherwise capture as-is. Do not over-interview rough
notes.

## Pile-Up Tolerance

The agent does **not** push for triage. Intake accumulates without nag. The
factory-state surface will mention pending counts when the user opens a fresh
session, but this skill never volunteers triage.

## Triage on Demand

When the user says "triage", "what's piled up", "let's group these", "sweep
issues", or similar, switch to grouping mode:

1. Read the configured intake substrate. For repo_file or repo_folder, use
   `file_ops` (read or list directory) at `intake_config.host_target`. For
   external_tracker, ask the user to paste the open list (or wait for the
   future read-side ingestion).
2. Summarize pending raw intake separately from existing Run Packs.
3. Load `project/plan/run_packs` to draft groupings; do not auto-publish.
4. When the user approves the proposed packs, call `propose_run_packs` with
   the full batch and the target `source_artifact_path` (e.g.
   `.spindrel/audits/<slug>.md`). Pack proposals land as a markdown section in
   that artifact; no DB row is created.

## Tool Boundaries

- `capture_project_intake` - the canonical write path for rough notes when
  `.spindrel/WORKFLOW.md` does not override.
- `get_project_factory_state` - read `repo_workflow.sections.intake` (the
  repo-owned override) and `intake_config` (the persisted fallback) before
  calling the capture tool.
- `file_ops` - read existing intake during triage; write directly when the
  WORKFLOW.md `## Intake` section dictates a custom schema or path.
- `report_issue` - autonomous scheduled/heartbeat/task runs reporting blockers.
- `propose_run_packs` - groups intake into launchable Run Pack proposals
  written to a repo-resident artifact (e.g. `.spindrel/audits/<slug>.md`).

## Boundaries

- Never claim a coding run, PR, or fix started unless a separate launch action
  actually happened.
- Do not promote intake into channel notes, memory, or knowledge bases. The
  configured substrate is the durable record.
- Do not add intake during plan-mode questioning unless the user explicitly
  drops a side note.
- Do not silently mirror intake into an external tracker the user has not
  asked you to use. Tracker integration is opt-in per Project.
- Do not invent a schema when one exists: `repo_workflow.sections.intake`
  from `.spindrel/WORKFLOW.md` always wins over `intake_config` and over
  the generic four-substrate routing. Read it before capturing.
