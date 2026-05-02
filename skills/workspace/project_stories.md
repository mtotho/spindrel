---
name: Project Stories
description: >
  Turn a PRD, larger track, planning conversation, or selected issue notes into
  discrete reviewable stories and optional Project Work Packs.
triggers: create stories, break into stories, project stories, work packages, work packs, split this track, implementation stories
category: workspace
---

# Project Stories

Use this skill when the user wants a PRD, rough track, or planning conversation
split into discrete implementation units.

The user may invoke this with the normal skill mechanism, such as a skill
mention or `get_skill("workspace/project_stories")`. Do not depend on a literal
slash command.

## Story Model

A good story is:

- independently understandable
- independently reviewable
- scoped to one coherent user/system outcome
- clear about tests, screenshots, receipts, and handoff expectations
- not secretly dependent on another story unless that dependency is stated

## Procedure

1. Load or inspect the relevant PRD/track file if one exists. If the user is
   planning only in chat, use the current conversation as source material.
2. If saved Issue Intake items are part of the source, call `list_issue_intake`
   and use existing source item IDs.
3. Draft stories first in chat. Do not publish Work Packs until the user wants
   them captured for launch/review.
4. Mark each story as one of:
   - `launchable`: ready to become a Work Pack or coding run prompt
   - `needs_info`: needs a user decision before implementation
   - `planning`: useful design/research/future work, not code work yet
5. For launchable stories, include:
   - title
   - problem statement
   - implementation scope
   - explicit non-goals
   - expected repo-local tests
   - screenshot/e2e evidence expectations when relevant
   - branch/PR/handoff expectation
   - Project run receipt requirements
6. When the user wants the stories published for Project launch/review, call
   `create_issue_work_packs` with the full proposed set and a triage receipt.

## Work Pack Rules

- Use existing `source_item_ids` when grouping saved Issue Intake.
- It is okay to omit source IDs for pure conversation planning; Spindrel will
  create backing conversation intake items.
- A Work Pack is proposed launch material, not an implementation run.
- Launch happens later from the Project/Issue Intake UI or explicit user
  instruction.

## Output Template

```markdown
## Proposed Stories

### 1. <Story Title>
Status: launchable | needs_info | planning
Problem:
Scope:
Non-goals:
Verification:
Receipt evidence:
Dependencies:
Launch prompt:
```

## Boundaries

- Do not launch coding runs from this skill unless the user explicitly asks to
  launch after reviewing the stories.
- Do not make one giant story when the work naturally splits into reviewable
  units.
- Do not over-split tiny changes that should be one reviewable patch.
- Do not turn future ideas into launchable work just because they were mentioned.
