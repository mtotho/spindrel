# Small-Model Guidance

Assume not every Spindrel agent is running a frontier model. A good agentic
surface should let smaller models succeed through short procedures, explicit
tool ordering, and typed contracts.

## Design Rules

- Put the first action in the skill or tool description.
- Avoid broad "inspect everything" instructions; name the exact surface to
  inspect first.
- Keep runtime skill bodies short, imperative, and example-driven.
- Use labels that match UI/API vocabulary exactly.
- Prefer enumerated status values over prose.
- Include safe fallback instructions for blocked or missing prerequisites.
- Do not require the model to infer permissions or side effects from context.

## Skill Authoring

A small-model-friendly skill should answer in the first screen:

- When do I use this?
- What should I do first?
- Which tools/APIs should I call, in what order?
- What should I not do?
- How do I report blocked state?

Move long background detail into references. The runtime path should be a
checklist, not a whitepaper.

## Tool/API Authoring

Small models need contracts, not vibes:

- Use verb-noun tool names.
- Describe side effects and idempotency.
- Return compact structured fields with stable enum values.
- Include `suggestion` or `fallback` for expected failures.
- Separate inspect/preflight/request/apply states when approval matters.

## Review And Warning Filtering

For review systems, encode enough structure that a cheaper model does not have
to guess severity from prose:

- `error_kind`: input, config, permission, retryable_external, platform,
  unknown.
- `retryable`: boolean.
- `fallback`: concrete next step.
- `source`: tool, integration, runtime, user_input, review.
- `count` or recurrence window for repeated benign failures.

Then use runtime skills for the judgment layer: when to ignore, group, escalate,
or ask for approval.
