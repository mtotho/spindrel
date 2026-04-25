---
name: Pipelines
description: Entry point for Pipelines (multi-step Automations). Explains when to reach for a Pipeline vs inline work, which sub-skill to read for authoring vs creating, and how Pipelines ride the define_pipeline + cron surface.
triggers: pipeline, define pipeline, automation pipeline, cron job, scheduled automation, pipeline steps, pipeline authoring, pipeline creation, fail_if, foreach step, pipeline_mode
category: core
---

# Pipelines

Pipelines string together multiple steps (exec, tool, agent, user_prompt, foreach) that run deterministically on a schedule or on demand. Use them when the work is multi-step, re-runnable, and worth capturing as a definition instead of re-prompting each time.

## Read This First When

- You are deciding whether a user request should become a Pipeline or stay inline
- You are writing or editing a Pipeline definition (schema, step types, conditions)
- You are subscribing a Pipeline to a channel, setting a cron, or adjusting `pipeline_mode`

## Which Skill Next

- [Pipeline Creation](creation.md)
  Read this first. Decision guide: Pipeline vs inline, `define_pipeline` usage, step type selection, when multi-step automation is worth the overhead.
- [Pipeline Authoring](authoring.md)
  Read this when you're actually writing steps. Full JSON schema, all five step types, params + template syntax, condition logic, failure handling, env vars, worked examples.

## The Short Version

- `define_pipeline` is the entry point — you hand it a list of steps and (optionally) a cron expression. Single-prompt Automations use `schedule_prompt` instead.
- Five step types cover the surface: `exec` (shell), `tool` (registered tool), `agent` (LLM turn), `user_prompt` (paused for user input), `foreach` (loop over items).
- `fail_if` lets a step signal failure from inside a body; the Pipeline stops or continues based on each step's `on_failure` policy.
- `pipeline_mode` is a per-channel override that changes how Pipelines render in chat vs as Run cards.
