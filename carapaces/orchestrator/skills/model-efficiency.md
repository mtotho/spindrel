---
name: Model Efficiency
description: >
  Guide for selecting cost-effective models when delegating tasks, scheduling work,
  or configuring channels. Load when the user asks about model costs, optimization,
  or when the orchestrator needs to choose between models for a task.
---

# Model Efficiency — Choosing the Right Model for the Job

## Core Principle

Not every task needs the most capable model. Match model capability to task complexity:
- **Reasoning, architecture, ambiguous requirements** → top-tier (Opus, o3, GPT-4o)
- **Code generation, structured tasks, clear prompts** → mid-tier (Sonnet, Flash, GPT-4o-mini)
- **Summarization, classification, simple extraction** → economy (Haiku, Flash-Lite, GPT-4o-mini)

## Discovering Available Models

Use the admin API to list models with cost information:

```
GET /api/v1/admin/models
```

Returns models grouped by provider, each with:
- `model_id` — the LiteLLM model alias to use in overrides
- `input_cost_per_1m` / `output_cost_per_1m` — cost per million tokens
- `max_tokens` — context window size

Check this on cold start (via `get_system_status` or direct API call) and note
the cheapest capable models in your workspace MEMORY.md for quick reference.

## Using Model Overrides

### In Task Delegation

When delegating via `schedule_task` or `delegate_to_agent`, set `execution_config`
to override the model:

```python
schedule_task(
    prompt="Summarize these 5 channel updates into a digest",
    bot_id="helper",
    execution_config={
        "model_override": "gemini/gemini-2.5-flash",  # cheap + fast for summaries
    }
)
```

For important tasks, set a fallback chain:

```python
schedule_task(
    prompt="Design the integration architecture",
    bot_id="architect",
    execution_config={
        "model_override": "anthropic/claude-sonnet-4-6",
        "fallback_models": [
            {"model": "gemini/gemini-2.5-pro"},
            {"model": "openai/gpt-4o"},
        ],
    }
)
```

### In Channel Configuration

For channels with heartbeats or recurring tasks, set the channel model override
via `manage_channel` to control cost for ALL messages in that channel:

```python
manage_channel(
    action="update",
    channel_id="...",
    model_override="gemini/gemini-2.5-flash",  # heartbeat channels rarely need top-tier
)
```

## Task-to-Model Matching Guide

| Task Type | Recommended Tier | Why |
|-----------|-----------------|-----|
| Heartbeat status checks | Economy | Routine, template-like output |
| Summarization / digests | Economy | Extractive, low reasoning |
| Classification / routing | Economy | Simple decision boundary |
| Data extraction / parsing | Economy-Mid | Structured output, some edge cases |
| Code generation (clear spec) | Mid | Needs correctness but prompt is specific |
| Code review | Mid | Pattern matching + reasoning |
| Research / analysis | Mid-Top | Open-ended reasoning required |
| Architecture / design | Top | Ambiguity resolution, tradeoff analysis |
| Debugging complex issues | Top | Multi-step reasoning, hypothesis testing |
| Creative writing / personas | Mid | Quality matters but reasoning load is moderate |

## Cost Optimization Patterns

### 1. Tiered Delegation
For multi-step workflows, use cheap models for early stages and expensive ones
for the final synthesis:

```
1. schedule_task(model="flash") → gather raw data from 5 channels
2. schedule_task(model="flash") → extract key points from each
3. schedule_task(model="sonnet") → synthesize into strategic report
```

### 2. Heartbeat Economy
Heartbeats run frequently. Use the cheapest model that can handle the channel's
needs. Most heartbeats do status checks or simple monitoring — Flash-tier is fine.

### 3. Smart Fallbacks
Set fallback_models so tasks don't fail if a provider is down, but pick
fallbacks at similar or lower cost tiers:

```python
"fallback_models": [
    {"model": "gemini/gemini-2.5-flash"},      # same tier, different provider
    {"model": "openai/gpt-4o-mini"},            # similar tier fallback
]
```

### 4. Context Window Awareness
Large context = more tokens = more cost. When delegating tasks that involve
reading large codebases or documents:
- Pre-summarize inputs with a cheap model before feeding to an expensive one
- Use `max_tokens` from model info to avoid tasks that exceed context limits
- Prefer models with large context windows for search/RAG-heavy tasks

## Decision Framework

When choosing a model for a task, ask:
1. **How complex is the reasoning?** Simple → economy, complex → top
2. **How important is the output?** User-facing → invest more, internal → economize
3. **How often does this run?** Hourly heartbeat → economy, one-off analysis → top is fine
4. **Is this retriable?** If you can retry on failure, start cheap and escalate
