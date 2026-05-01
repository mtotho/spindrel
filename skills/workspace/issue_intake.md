---
name: Issue Intake
description: >
  Capture user-described issues and turn planning conversations into proposed
  Project work packs, without launching implementation work.
triggers: add this issue, save this bug, issue inbox, report this issue, triage later, work pack
category: workspace
---

# Issue Intake

Use this skill when the user asks you to save, add, report, or remember a bug,
quality problem, task idea, or rough issue for later triage. Also use it when
the user asks you to turn a planning conversation or multi-part track into
launchable Project work packs.

## Conversational Capture

1. Clarify only what is needed to make the note useful. Good fields are:
   observed behavior, expected behavior, reproduction steps, affected surface,
   severity, and any Project/repo hint.
2. If the user explicitly says to save it rough, do not over-interview them.
3. Call `publish_issue_intake` once the note is clear enough or explicitly
   accepted as rough.
4. Tell the user it was added to Mission Control Review for later triage. Do
   not claim a coding run, PR, or fix has started.

## Conversational Work Packs

1. Use `create_issue_work_packs` when the user asks you to convert the current
   conversation, plan, rough notes, or track into proposed implementation units.
2. Create one pack per discrete unit of work. Use `needs_info` or
   `not_code_work` for ideas/planning items that should not launch directly.
3. You do not need to create or track source issue IDs first. If you omit
   `source_item_ids`, Spindrel creates backing conversation intake items and
   links the work packs to them.
4. Work-pack creation does not launch a Project coding run. The operator or a
   later explicit action chooses which proposed packs to launch.

## Boundaries

- `publish_issue_intake` is for user-requested conversational capture.
- `create_issue_work_packs` is for normal Project-bound agents turning a
  planning conversation into proposed work packs. It works from ordinary
  Codex/Claude/SDK channels when the tool is available; it is not
  harness-specific.
- `report_issue` is for autonomous task or heartbeat runs reporting blockers
  they discovered while doing assigned work.
- `report_issue_work_packs` remains restricted to issue-intake triage tasks.
  Do not use it for ordinary conversation planning.
- Project coding runs start only after a human approves a work pack launch.
