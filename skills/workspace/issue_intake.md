---
name: Issue Intake
description: >
  Capture rough bugs, ideas, and planning notes as pending Issue Intake items;
  review pending intake conversationally; and group accepted items into
  proposed Project Work Packs without launching implementation work.
triggers: add this issue, save this bug, issue inbox, report this issue, triage later, work pack, sweep issues, group these notes
category: workspace
---

# Issue Intake

Use this skill when the user is dumping bugs, ideas, rough notes, or asks to
turn a planning conversation into proposed Project Work Packs.

## Mental Model

- **Issue Intake item**: a pending rough note. It is not a channel note, not a
  Work Pack, and not launched work.
- **Work Pack**: a proposed implementation or follow-up unit created from one
  or more intake items or from a planning conversation.
- **Project coding run**: starts only after a human/operator launches a Work
  Pack. Creating or listing intake never launches work.

## Capture Rough Notes

When the user is explicitly jotting, dumping, saving, or reporting rough bugs
or ideas, call `publish_issue_intake` once for each discrete note.

- Do not write these into channel notes as the source of truth.
- Clarify only when the note would be useless without one missing fact.
- If the user says to save it rough, capture it without over-interviewing.
- Use `category_hint="idea"` or `category_hint="planning"` for future ideas,
  design considerations, or planning notes that are not immediate bugs.
- Tell the user the item is saved as pending intake and visible in Mission
  Control Issue Intake.

## Review Current Intake

When the user asks what issues, rough notes, ideas, or Work Packs are waiting,
call `list_issue_intake`.

- Use `scope="current_channel"` by default.
- Use `scope="workspace"` only when the user asks for a broader sweep.
- Summarize pending raw intake separately from existing Work Packs.
- Treat pending intake as unconfirmed grouping material, not accepted launch
  instructions.

## Create Work Packs

Use `create_issue_work_packs` only when the user asks to sweep, group, triage,
turn notes into packs, or convert a plan/track into proposed work.

1. Call `list_issue_intake` first unless all source material is only the
   current conversation.
2. Group related items into the smallest useful discrete Work Packs.
3. Use existing `source_item_ids` from `list_issue_intake` when grouping saved
   intake items.
4. Use `needs_info` for vague items needing another answer.
5. Use `not_code_work` for planning, research, future ideas, or operator
   decisions that should not launch a coding run.
6. For launchable code packs, write `launch_prompt` as the prompt a later
   Project coding run should receive. Include expected repo-local tests,
   screenshot/evidence needs, PR/handoff expectations, and receipt
   requirements when they matter.
7. Prefer one `create_issue_work_packs` call containing the full proposed set.
   Include a top-level `triage_receipt` with summary, grouping rationale,
   launch readiness, follow-up questions, and excluded/not-code items.

If `source_item_ids` are omitted, Spindrel creates backing conversation intake
items and links the Work Packs to them. That is fine for a pure planning
conversation, but use existing source IDs when saved pending intake exists.

## Scheduled Or Operator Triage

Backlog triage runs use the same factory model:

- Raw Attention/Issue Intake items become proposed Work Packs.
- Work Packs are reviewed before launch.
- `report_issue_work_packs` is only for issue-intake triage tasks.

## Boundaries

- `publish_issue_intake`: conversational capture of rough notes.
- `list_issue_intake`: read-only review of pending intake and active Work
  Packs.
- `create_issue_work_packs`: ordinary Project/channel agents creating proposed
  Work Packs from conversation or listed intake.
- `report_issue`: autonomous scheduled/heartbeat/task runs reporting blockers.
- `report_issue_work_packs`: restricted triage-task reporting path.
- Never claim that a coding run, PR, or fix started unless a separate launch
  action actually happened.
