# Feature Placement Rubric

Classify the feature before designing it. The classification is part of the
work, not a docs afterthought.

| Put it in | Use when | First output |
|---|---|---|
| Skill | Repeatable procedure, judgment checklist, recovery pattern, examples, or small-model guidance | `SKILL.md` with when-to-use, first action, and boundaries |
| Tool/API | Runtime state, side effects, permissions, atomicity, enforcement, or large/stale data | Minimal typed contract with useful return schema |
| Memory | User/project preference, prior decision, durable local fact, or operating norm | Short durable note with source/date |
| Docs | External install, public API usage, contributor onboarding, or stable reference | Agent-readable guide or `llms.txt` entry |

## Skill-Shaped Signals

- Humans keep explaining the same multi-step workflow.
- Existing tools are useful but models call them in the wrong order.
- Success depends on caveats, examples, or "do not do X" rules.
- A smaller model can succeed if given a one-screen procedure.
- The task is mostly deciding how to use existing tools, not adding new state.
- Reviews keep surfacing the same benign setup/input warnings because agents
  lack a categorization rule.

## Not Skill-Shaped

- The agent needs fresh runtime state.
- The action mutates config, files, external services, secrets, widgets, or
  integration bindings.
- The system must enforce authorization, idempotency, concurrency, or atomic
  writes.
- The content is public install/API documentation for outside agents.
- The fact is a project-specific preference that belongs in memory.

## Tool/API Criteria

Add or extend a tool/API when a text procedure cannot reliably answer the
question. Keep the contract narrow and typed:

- Include input and output schemas with descriptions.
- Return actionable errors with `error_code`, `error_kind`, `retryable`,
  `retry_after_seconds`, and `fallback` where relevant.
- State idempotency and side effects in the description.
- Prefer read-only inspect/doctor/preflight endpoints before mutation.
- Keep mutation behind the existing approval/config-change path.

## Review Warning Categorization

Use skills to reduce false-positive review noise when warnings are benign but
patterned:

- Put categorization instructions in a runtime skill if the in-app agent must
  decide how to interpret the warning during normal work.
- Put normalized fields in the tool/API contract if Mission Control Review must
  filter, rank, or group the warning mechanically.
- Put a durable memory note only if the warning depends on a local project
  decision.
- Put the explanation in docs if it is public operator/contributor knowledge.

## Output Template

```markdown
Feature: <name>
Context: external repo-dev AX | internal runtime AX | both
Owner: skill | tool/API | memory | docs | UX/review surface
Why: <one sentence tied to the rubric>
First change: <file/contract/surface>
Verification: <test or check that prevents drift>
Boundary: <what this must not become>
```
