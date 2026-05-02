---
name: Project PRD
description: >
  Conversationally create or update a Project-owned PRD, feature brief, or
  larger track plan in the repository before stories or coding runs are launched.
triggers: create prd, prd, project requirements, product requirements, feature brief, project brief, plan a track, design a feature
category: workspace
---

# Project PRD

Use this skill when the user wants to shape a larger product/engineering idea
before creating stories or launching Project coding runs.

The user may invoke this with the normal skill mechanism, such as a skill
mention or `get_skill("workspace/project_prd")`. Do not depend on a literal
slash command.

## First Actions

1. Confirm the current channel is Project-bound. If not, ask the user to attach
   it to a Project or provide the Project context.
2. Inspect the repo's existing planning convention before choosing a file path.
   Look for `docs/tracks/`, `docs/roadmap.md`, `.spindrel/`, `product/`,
   `planning/`, `rfcs/`, and similar.
3. If there is an obvious convention, use it. If not, recommend
   `.spindrel/prds/<slug>.md`.
4. Stay conversational until the goal, users, constraints, success criteria, and
   open questions are clear enough to write.

## PRD Shape

Use this shape unless the repo already has a better template:

```markdown
# <Feature or Track Name>

## Problem
What is broken, missing, painful, or strategically important?

## Users and Use Cases
Who needs this, and what concrete workflows must work?

## Goals
What outcomes should be true when this ships?

## Non-Goals
What should not be built in this track?

## Proposed Experience
How should the user or agent move through the workflow?

## System Model
What existing records, tools, skills, APIs, files, and UI surfaces participate?

## Acceptance Criteria
What proves this is usable and stable?

## Story Candidates
Draft story areas only. Do not launch work from this section.

## Open Questions
What still needs user or operator decision?
```

## Conversation Rules

- Ask targeted questions only when the answer materially changes the PRD.
- Prefer concrete use cases over abstract platform language.
- Preserve user wording for pain points and goals when useful.
- Explicitly separate ideas/future considerations from immediate build work.
- When the PRD is ready, summarize the recommended next step:
  usually load `workspace/project_stories`.

## Boundaries

- Do not create Work Packs while writing a PRD unless the user asks to move to
  stories.
- Do not launch coding runs from this skill.
- Do not store secrets or private tokens in PRDs.
- Do not force `.spindrel/prds/` when the repo already has a clear planning
  location.
