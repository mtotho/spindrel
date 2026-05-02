---
name: Project Intake
description: >
  Recognise when the user is dropping a rough bug, idea, or future-work note
  in conversation; capture it as Issue Intake without interrupting the flow;
  triage on demand into proposed Run Packs.
triggers: add this issue, save this bug, issue inbox, report this issue, triage later, sweep issues, group these notes, intake, rough idea, side note
category: project
---

# Project Intake

Use this skill in any Project-bound channel. Intake is conversational - the
agent *recognises* drop-in items, captures them, and stays out of the way.
The user does not have to say "save this".

## Mental Model

- **Issue Intake item** - a pending rough note attached to the Project. Not a
  channel note, not a Run Pack, not launched work.
- **Run Pack** - a proposed launchable unit grouped from one or more intake
  items or from a planning conversation. See `project/plan/run_packs`.
- **Project coding run** - starts only after a human launches a Run Pack.
  Capturing or listing intake never launches anything.

Issue Intake is Spindrel's **coordination layer** for capture/triage/launch -
it is not a tracker replacement. If the user already keeps issues in GitHub,
Linear, a `docs/loose-ends.md`-style repo file, or anywhere else, that
remains the durable home; Spindrel intake mirrors or pairs with it. Ask the
user once which is canonical for this Project, then respect that choice.

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
2. Call `publish_issue_intake` once for each discrete note. Use
   `category_hint="bug"`, `idea`, or `planning` per the obvious shape.
3. Add one line in chat confirming capture: "Noted as intake (bug). It is in
   Mission Control Issue Intake; we can triage when you want."
4. **Do not** open a Run Pack, launch a coding run, or write into channel
   notes. Intake is the durable home.

If the note would be useless without one missing fact, ask exactly one
clarifying question. Otherwise capture as-is. Do not over-interview rough
notes.

## Pile-Up Tolerance

The agent does **not** push for triage. Intake accumulates without nag. The
factory-state surface will mention "you have N pending intake items" when the
user opens a fresh session, but this skill never volunteers triage.

## Triage on Demand

When the user says "triage", "what's piled up", "let's group these", "sweep
issues", or similar, switch to grouping mode:

1. Call `list_issue_intake` (default `scope="current_channel"`; widen to
   `scope="workspace"` only when asked).
2. Summarize pending raw intake separately from existing Run Packs.
3. Load `project/plan/run_packs` to draft groupings; do not auto-publish.
4. When the user approves the proposed packs, call `create_issue_work_packs`
   with the full batch and a `triage_receipt`.

## Tool Boundaries

- `publish_issue_intake` - conversational capture of rough notes.
- `list_issue_intake` - read-only review of pending intake and active Run Packs.
- `create_issue_work_packs` - ordinary Project/channel agents creating
  proposed Run Packs from conversation or listed intake.
- `report_issue` - autonomous scheduled/heartbeat/task runs reporting blockers.
- `report_issue_work_packs` - restricted triage-task reporting path only.

## Scheduled or Operator Triage

Backlog triage runs follow the same factory model: raw Attention/Issue Intake
items become proposed Run Packs; Run Packs are reviewed before launch. Use
`report_issue_work_packs` only from triage tasks, not from ordinary chat.

## Boundaries

- Never claim a coding run, PR, or fix started unless a separate launch action
  actually happened.
- Do not promote intake into channel notes, memory, or knowledge bases. The
  intake row is the durable record (or a pointer to the user's external
  tracker when they keep one).
- Do not add intake during plan-mode questioning unless the user explicitly
  drops a side note.
- Do not silently mirror intake into an external tracker the user has not
  asked you to use. Tracker integration is opt-in per Project.
