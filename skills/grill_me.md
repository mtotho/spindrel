---
name: Grill Me
description: Interview the user up front so you can build a concrete shared understanding before planning or execution
triggers: grill me, ask me questions first, interview me, pressure test this, clarify the goal, clarify the scope, success criteria
category: core
---

# Grill Me

Use this when the user explicitly wants an interview-first turn: they want you to ask focused questions before you plan, design, or execute.

This is a **shared-understanding** skill, not a planning skill. Your job is to surface the right unknowns, capture the answers, and stop once both sides agree on the target.

---

## Default behavior

1. Inspect what you can already learn first.
   - Check the repo, current workspace files, and relevant knowledge-base files before asking obvious questions.
   - Do not ask for facts that are already discoverable from the workspace.

2. Ask only judgment-call questions.
   - Prioritize success criteria, scope boundaries, constraints, preferences, tradeoffs, deadlines, and non-goals.
   - Skip trivia, repetition, and implementation-detail questions that can wait.
   - Keep the interview tight. Ask a focused batch, then adapt based on the answers.

3. Prefer normal chat questions.
   - If `ask_plan_questions` is available and a short structured questionnaire would clearly help, you may use it.
   - Otherwise ask the questions directly in normal chat.

4. Convert the answers into a concise brief.
   - Include:
     - objective
     - success criteria
     - constraints
     - non-goals
     - key decisions
     - open questions / follow-ups

5. Store the brief in the knowledge base.
   - Default channel-scoped location:
     - `channels/<channel_id>/knowledge-base/project-brief.md`
   - If the user explicitly wants a cross-channel reusable brief, store it in the bot-wide KB instead:
     - `knowledge-base/briefs/<slug>.md`
     - for shared-workspace bots, use the bot-root equivalent under `bots/<bot_id>/knowledge-base/briefs/<slug>.md`

6. Stop after shared understanding.
   - Summarize the brief.
   - Confirm any remaining open questions.
   - Wait for the user.
   - Do not auto-plan, auto-implement, or assume approval to proceed.

---

## Interview heuristics

- Lead with the highest-leverage unknowns.
- Force specificity when the user is still speaking in goals like "better", "cleaner", or "faster".
- Ask for examples when the target quality bar is subjective.
- When the user gives a vague constraint, restate it in operational terms and confirm it.
- If there are too many unknowns, narrow the scope before you continue.

---

## Brief template

```markdown
# Project Brief

## Objective

## Success Criteria
- ...

## Constraints
- ...

## Non-Goals
- ...

## Decisions
- ...

## Open Questions
- ...
```
