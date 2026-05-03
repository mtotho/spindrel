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
are optional published batches of Run Briefs: one Run Pack is a proposed
launchable Project coding run with a clear PR target.

A Run Brief is enough for a single document-driven run. Use a Run Pack when
the user needs to review, reorder, approve, or launch multiple PR-sized slices
as a batch.

Run Packs are file-resident — proposals land as a markdown section in a
repo artifact (e.g. `.spindrel/audits/<slug>.md` or `.spindrel/prds/<slug>.md`)
via `propose_run_packs`, not as DB rows. The launching coding run carries
`source_artifact: {path, section?, commit_sha?}` back to that artifact.

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
2. If saved intake notes are part of the source, read them from the Project's
   configured intake substrate (`intake_config.host_target` from
   `get_project_factory_state`) using `file_ops`.
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
   `propose_run_packs(packs=[...], source_artifact_path=".spindrel/audits/<slug>.md", section="Proposed Run Packs")`.
   The tool writes the section idempotently — re-running with the same path
   replaces the section, so iterating on the proposed set is cheap.

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

- Quote source intake-note slugs in `source_item_ids` (e.g. the
  `## YYYY-MM-DD HH:MM <slug>` heading) when grouping notes from the inbox file.
- Omit `source_item_ids` for pure conversation planning.
- A Run Pack is **proposed launch material**, not a coding run. It is the
  persisted form of a Run Brief for batch review. Launch happens separately,
  through the Project/Issue Intake UI or an explicit user instruction.
- Prefer one `propose_run_packs` call containing the full batch with
  `triage_receipt`.

## Boundaries

- Do not launch coding runs from this skill unless the user explicitly asks
  after reviewing the packs.
- Do not make one giant Run Pack when the work naturally splits.
- Do not over-split tiny changes that should be one reviewable patch.
- Do not turn future ideas into launchable packs just because they were
  mentioned.
