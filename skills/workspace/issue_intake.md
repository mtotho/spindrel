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
2. Use the LLM to group the conversation into the smallest useful discrete
   work units. Do not invent a separate triage process when the conversation
   already has enough detail.
3. Use `needs_info` for vague items that need another user answer. Use
   `not_code_work` for planning, research, future ideas, or operator decisions
   that should not launch a coding run directly.
4. For code packs, write `launch_prompt` as the prompt a later Project coding
   run should receive. Include expected repo-local tests, screenshot/evidence
   needs, handoff/PR expectations, and receipt requirements when they matter.
5. Prefer one `create_issue_work_packs` call containing the full proposed set,
   so the review surface receives one coherent grouping decision.
   Include a top-level `triage_receipt` on that same call with a concise
   summary, grouping rationale, launch-readiness notes, follow-up questions,
   and excluded/not-code items. This receipt is the audit trail a later
   operator uses to understand why the packs exist.
6. You do not need to create or track source issue IDs first. If you omit
   `source_item_ids`, Spindrel creates backing conversation intake items and
   links the work packs to them.
7. Work-pack creation does not launch a Project coding run. The operator or a
   later explicit action chooses which proposed packs to launch.

## Backlog Triage Runs

1. Use the Issue Intake triage run when raw saved notes or autonomous blocker
   reports need a grouped pass outside the current conversation.
2. Treat the triage run as the same factory intake model, not a separate
   manager or workflow system: raw Attention items become proposed Work Packs,
   then a human reviews and launches them later.
3. The triage run must report through `report_issue_work_packs` and include a
   triage receipt. That receipt is the durable explanation for grouping,
   launch readiness, follow-up questions, and excluded or non-code items.
4. If the current conversation already has enough detail, prefer
   `create_issue_work_packs` instead of starting another triage run.

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
- Do not invent a separate intake bot, factory table, or Project launch
  workflow. Attention Items, Issue Work Packs, Project coding runs, receipts,
  and review sessions are the v1 factory objects.
