---
name: Project Run Packs
description: >
  Turn a PRD, larger track, planning conversation, or selected Issue Intake
  notes into discrete reviewable Run Packs (proposed launchable units).
triggers: create run packs, run packs, work packs, break into stories, project stories, split this track, implementation stories, group these notes, sweep issues
category: project
---

# Project Run Packs

Use this skill when the user wants a PRD, rough track, planning conversation,
or pile of Issue Intake split into discrete implementation units. Run Packs
are the canonical product unit: one Run Pack is a proposed launchable Project
coding run with a clear PR target.

(Internal data model still says "Issue Work Pack" today; the user-facing name
is **Run Pack**. Tools currently named `create_issue_work_packs` will be
renamed in a later phase.)

## Run Pack Shape

A good Run Pack is:

- independently understandable
- independently reviewable as one PR
- scoped to one coherent user/system outcome
- clear about expected tests, screenshots, receipts, and handoff
- not secretly dependent on another pack unless the dependency is stated
- ~500 LOC diff sweet spot; split anything materially larger; combine anything
  smaller than a single meaningful change

Flag a Run Pack as **Blueprint-impacting** if shipping it requires a Blueprint
snapshot change (new repo, new env slot, new dependency, new dev target). The
operator should review those packs before launch because they reset future
fresh instances.

## Procedure

1. Load the relevant PRD or planning artifact if one exists. If the user is
   planning only in chat, use the current conversation as source material.
2. If saved Issue Intake items are part of the source, call `list_issue_intake`
   and use existing source item IDs.
3. Draft Run Packs first in chat. Do not publish until the user is ready.
4. Mark each pack as one of:
   - `launchable` - ready to become a Run Pack and a coding run prompt
   - `needs_info` - needs a user decision before implementation
   - `not_code_work` - planning, research, or operator decision; should not
     launch a coding run
5. For launchable packs, include:
   - title
   - problem statement
   - implementation scope
   - explicit non-goals
   - expected repo-local tests
   - screenshot/e2e evidence expectations when relevant
   - branch/PR/handoff expectation
   - Project run receipt requirements
   - Blueprint-impact flag if applicable
6. When the user wants the packs published for launch/review, call
   `create_issue_work_packs` with the full proposed set and a `triage_receipt`.

## `triage_receipt` Schema

The `triage_receipt` block sent with `create_issue_work_packs` carries the
operator-readable summary. Include it on every batch:

```json
{
  "summary": "One sentence covering what kind of work this batch is and how big.",
  "grouping_rationale": "Why these items were grouped this way (or split).",
  "launch_readiness": "Which packs are ready to launch immediately, which need an answer first, which are planning-only.",
  "follow_up_questions": ["Anything that needs the operator's decision before launch."],
  "excluded": [
    {"source_item_id": "...", "reason": "Already shipped / duplicate / not actionable / out of scope."}
  ],
  "not_code_items": [
    {"title": "...", "reason": "Planning, research, or external decision."}
  ]
}
```

A Run Pack itself includes:

```json
{
  "title": "Add cron to refresh dashboard widget data",
  "summary": "Short body that explains the work in plain language.",
  "category": "code_bug | feature | refactor | docs | needs_info | not_code_work",
  "confidence": "high | medium | low",
  "status": "proposed | needs_info | not_code_work",
  "launch_prompt": "Full prompt the next coding run should receive, including expected tests, screenshots, PR/handoff, and receipt expectations.",
  "source_item_ids": ["...", "..."],
  "blueprint_impact": false
}
```

## Conversion Rules

- Use existing `source_item_ids` from `list_issue_intake` when grouping saved
  intake.
- Omit `source_item_ids` for pure conversation planning - Spindrel creates
  backing conversation intake items and links them.
- A Run Pack is **proposed launch material**, not a coding run. Launch happens
  separately, through the Project/Issue Intake UI or an explicit user
  instruction.
- Prefer one `create_issue_work_packs` call containing the full batch with
  `triage_receipt`.

## Boundaries

- Do not launch coding runs from this skill unless the user explicitly asks
  after reviewing the packs.
- Do not make one giant Run Pack when the work naturally splits.
- Do not over-split tiny changes that should be one reviewable patch.
- Do not turn future ideas into launchable packs just because they were
  mentioned.
