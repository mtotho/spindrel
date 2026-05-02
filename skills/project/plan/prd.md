---
name: Project PRD
description: >
  Conversationally create or update a Project-owned PRD, feature brief, or
  larger track plan in the repository before Run Packs or coding runs are launched.
triggers: create prd, prd, project requirements, product requirements, feature brief, project brief, plan a track, design a feature
category: project
---

# Project PRD

Use this skill when the user wants to shape a larger product/engineering idea
before creating Run Packs or launching coding runs.

If `get_project_factory_state` reports `current_stage=planning`, resume the
existing artifact. If `current_stage=ready_no_work` and the user just said
"I want to build X", start a new one.

## First Actions

1. Confirm the channel is Project-bound; if not, ask the user to attach it.
2. **Sweep prior context before drafting.** Read existing planning material in
   the Project repo - `docs/roadmap.md`, `docs/tracks/*.md`,
   `docs/architecture-decisions.md`, `AGENTS.md`/`CLAUDE.md`, prior
   `.spindrel/prds/*.md`. The PRD should not contradict already-decided
   constraints.
3. **Find the user's planning convention - do not impose one.** Inspect the
   repo for `docs/tracks/`, `docs/roadmap.md`, `.spindrel/`, `product/`,
   `planning/`, `rfcs/`, similar. Then ask the user where PRDs live for this
   Project if it is not obvious. The user may keep PRDs in the repo, in
   Notion, in Linear, in a wiki, or in a chat thread - all of those are
   valid. Spindrel's job is to help shape the artifact, not to dictate where
   it stores.
4. Pick the location:
   - **Default for this product owner: in-repo.** When no other convention
     exists, recommend `.spindrel/prds/<slug>.md` so the PRD versions with
     source and survives across Project instances.
   - **If the user has an external home** (Notion/Linear/wiki/etc.), draft
     conversationally in chat and hand the final text to the user to paste
     into their tool. Do not silently create a repo file when the user keeps
     PRDs elsewhere. You can record a one-line pointer at
     `.spindrel/prds/<slug>.url` if the user wants the link discoverable from
     the repo.
   - **If the repo already has a clear convention** (e.g. `docs/tracks/`),
     use it as-is.
5. Stay conversational until goal, users, constraints, success criteria, and
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

## Run Pack Candidates
Draft Run Pack areas only. Do not launch work from this section.

## Open Questions
What still needs user or operator decision?
```

## Conversation Rules

- **Ask one clarifying question at a time using `AskUserQuestion` when the
  harness exposes it.** Bulk-asking five questions in chat produces interview-
  dump answers that miss nuance. Drip questions: ask one, wait for the
  answer, ask the next one informed by it. Stop when goal / users /
  constraints / success criteria are clear enough to draft.
- Ask targeted questions only when the answer materially changes the PRD.
- Prefer concrete use cases over abstract platform language.
- Preserve user wording for pain points and goals when useful.
- Explicitly separate ideas/future considerations from immediate build work.
- When the PRD is ready, summarize the recommended next step: usually load
  `project/plan/run_packs`.

## Boundaries

- Do not create Run Packs while writing a PRD unless the user asks to move on.
- Do not launch coding runs from this skill.
- Do not store secrets in PRDs.
- Do not force `.spindrel/prds/` when the repo already has a clear planning
  location, or when the user keeps PRDs in an external tool. The user's
  existing process wins; Spindrel adapts to it.
