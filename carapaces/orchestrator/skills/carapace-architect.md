---
name: Carapace Architect
---

# Carapace Design Guide

You can create and manage **carapaces** — bundles of skills, tools, and behavioral
instructions that make a bot an instant expert at a specific task.

## When to Create a Carapace

Create a carapace when:
- A task requires a specific combination of skills and tools
- You're delegating work and want the sub-agent to be an expert
- A workflow pattern is reusable across multiple tasks

## Design Principles

1. **Single responsibility**: One carapace = one expertise area
2. **Compose, don't duplicate**: Use `includes` to build on existing carapaces
3. **Behavioral instructions matter**: The system_prompt_fragment is the soul —
   it tells the agent HOW to use the skills and tools, not just WHAT they are
4. **Pin critical tools**: Tools the workflow depends on should be in pinned_tools
5. **Reference skills by mode**: Use pinned for always-needed context,
   on_demand for reference material

## Creating a Carapace

Use the `manage_carapace` tool:

```
manage_carapace(
  action="create",
  id="bug-triage",
  name="Bug Triage Expert",
  skills='[{"id": "debugging-guide", "mode": "pinned"}]',
  local_tools="exec_command,file,web_search",
  pinned_tools="exec_command",
  system_prompt_fragment="## Bug Triage Mode\n\n1. Reproduce the bug..."
)
```

## Composition Example

A "Full QA" carapace that includes bug triage + code review:

```
manage_carapace(
  action="create",
  id="full-qa",
  name="Full QA Suite",
  includes="bug-triage,code-review",
  system_prompt_fragment="## Full QA\n\nStart with code review, then triage bugs..."
)
```

## Applying Carapaces

- **Bot config**: Add `carapaces: [qa]` to bot YAML
- **Delegation**: `execution_config.carapaces: ["qa"]`
- **Channel override**: `carapaces_extra: ["qa"]` on channel
