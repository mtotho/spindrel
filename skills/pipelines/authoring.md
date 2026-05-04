---
name: Pipeline Authoring — entry point
description: Routing skill for authoring or editing task pipeline steps. The full schema reference (~540 lines: five step types, params, template syntax, `when` conditions, failure handling, worked examples) lives at `get_doc("reference/pipelines/authoring")`.
use_when: >
  Authoring or editing any pipeline step, deciding which step type to use
  (especially user_prompt vs foreach vs agent), wiring up params, writing
  `when:` conditions, or debugging why a template / step state / resolve
  call isn't behaving as expected.
triggers: pipeline, task pipeline, steps, step definition, pipeline json, create pipeline, edit pipeline, pipeline authoring, multi-step task, step executor, pipeline schema, user_prompt, foreach, approval gate, widget template
category: pipelines
---

# Pipeline authoring — entry point

Pipelines are Tasks with a `steps` array. Five step types: `exec` (shell), `tool` (registered tool), `agent` (LLM turn), `user_prompt` (paused for human/bot resolve), `foreach` (loop over a list). The step executor handles sequencing, condition evaluation, template rendering, and result propagation.

**The full schema reference moved out of skills.** It's now a doc:

```
get_doc("reference/pipelines/authoring")
```

Fetch it before authoring or editing a step body. The reference covers:

- common fields (`id`, `type`, `on_failure`, `when`, `result_max_chars`)
- per-type fields and worked examples for `exec` / `tool` / `agent` / `user_prompt` / `foreach`
- params (`{{params.key}}`) and template syntax (`{{steps.<id>.result.<path>}}`, `{{item}}`, etc.)
- conditions: `step`, `param`, `output_contains`, `all` / `any` / `not`
- failure handling, step states, and the `awaiting_user_input` shape
- model tiers (`Fast` / `Standard` / `Capable` / `Frontier`) for agent steps
- four end-to-end pipeline examples (health check, conditional remediation, research, multi-service deploy)

## Decide first, then fetch

If the question is "should this be a Pipeline at all", read **skill `pipelines/creation`** first — that's the decision guide. Only fetch the authoring reference once you know you're writing steps.

## Step-type rules of thumb

- **Default to `exec` and `tool`.** They're deterministic and don't burn LLM tokens.
- **Use `agent` for judgment**, not plumbing. Match the model tier to the actual complexity — don't ship Frontier-tier for "summarize this output".
- **`user_prompt` is a sync gate.** Pipeline pauses; resume via `POST /api/v1/admin/tasks/{task_id}/steps/{step_index}/resolve`.
- **`foreach` v1: sub-steps must be `tool`-typed.** Inner `when:` is evaluated against *outer* step results, not per-item — pre-filter the list in an earlier step if you need per-item gating.
- **`on_failure: continue`** for notifications and non-critical telemetry. `abort` (default) for everything load-bearing.

## Template gotchas

- `{{steps.<id>.result.<path>}}` does dotted JSON access. If a key is missing or the result isn't JSON, the template is preserved as-is (helps debugging).
- Single quotes in template values are auto shell-escaped inside `exec` prompts.
- Dict/list params are JSON-encoded when substituted into a string context.
- Bare `{{key}}` falls back to `params["key"]` if present.

## See also

- `get_doc("reference/pipelines/authoring")` — the full schema and worked examples
- skill `pipelines/creation` — Pipeline-vs-inline decision guide and `define_pipeline` usage
- skill `pipelines` — which sub-skill to read next
