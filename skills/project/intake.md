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

The Project's intake substrate is set once during `project/setup/init`. Read
it from `get_project_factory_state -> intake_config`. **Always defer to a
repo-local `.agents/skills/<repo>-issues/SKILL.md` when one exists** - that
file names the schema, the file path, the commit cadence, and any
GitHub-issue rules; this generic skill is the fallback when no repo-local
convention exists.

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
2. Call `capture_project_intake` once for each discrete note. Required:
   `title`. Optional: `kind` (`bug` | `idea` | `tech-debt` | `question`,
   default `idea`), `area` (subsystem path), `body` (1-10 lines).
3. The tool reads `intake_config.kind` from the Project and routes:
   - `repo_file` -> appends to the configured file in the canonical repo.
   - `repo_folder` -> writes a new timestamped `.md` file to the folder.
   - `external_tracker` -> returns a hand-off message; **read it back to the
     user** so they can paste into their tracker. Spindrel does not call
     external APIs from this tool.
   - `unset` -> returns a warning. Tell the user the convention is not
     configured and offer to run `project/setup/init` to fix it; surface the
     captured note in chat so it is not lost.
4. Confirm capture in one line: "Noted (kind=bug). Wrote to
   `<relative_path>` in the canonical repo." For external trackers, use the
   tool's hand-off instructions verbatim.
5. **Do not** open a Run Pack, launch a coding run, or write into channel
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
4. When the user approves the proposed packs, call `propose_run_packs`
   (or, until 4BD.4 ships, the legacy `create_issue_work_packs`) with the
   full batch and a triage receipt.

## Tool Boundaries

- `capture_project_intake` - the canonical write path for rough notes (4BD.3+).
- `get_project_factory_state` - reads `intake_config` so you know which
  substrate to write to before you call the capture tool.
- `file_ops` - read existing intake during triage; write any custom schema
  named by a repo-local `.agents/skills/<repo>-issues/SKILL.md`.
- `report_issue` - autonomous scheduled/heartbeat/task runs reporting blockers.
- `report_issue_work_packs` - restricted triage-task reporting path only.
- `publish_issue_intake` - **deprecated**, kept only while existing channels
  drain old Mission Control intake. Do not use for new captures.

## Boundaries

- Never claim a coding run, PR, or fix started unless a separate launch action
  actually happened.
- Do not promote intake into channel notes, memory, or knowledge bases. The
  configured substrate is the durable record.
- Do not add intake during plan-mode questioning unless the user explicitly
  drops a side note.
- Do not silently mirror intake into an external tracker the user has not
  asked you to use. Tracker integration is opt-in per Project.
- Do not invent a schema when one exists: a repo-local
  `.agents/skills/<repo>-issues/SKILL.md` always wins. Read it before
  capturing.
