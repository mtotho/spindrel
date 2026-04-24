---
name: Integration Builder
description: >
  Creating custom integrations: scaffold, edit, reload, and verify. Load when
  building routers, tools, skills, workflows, or integration activation metadata.
triggers: integration, custom integration, scaffold integration, build integration, integration router, integration reload, integration tool, integration skill
category: core
---

# Integration Builder Guide

## Choose the smallest thing that works

| You need... | Create... | Why |
|---|---|---|
| A callable function | Tool (`tools/*.py`) | Smallest unit; easiest to ship and verify |
| Reusable domain knowledge | Skill (`skills/*.md`) | Searchable knowledge that bots can fetch on demand |
| External service wiring, hooks, router, workflows, settings | Integration | Full package for service-specific behavior |

There is no separate capability layer. Group related tools and skills by folder structure
and activation metadata rather than a parallel bundle system.

## Scaffold -> edit -> reload

### 1. Scaffold

```python
manage_integration(
    action="scaffold",
    integration_id="my_service",
    features=["tools", "skills", "workflows"],
)
```

Typical features:

- `tools`
- `skills`
- `workflows`
- `dispatcher`
- `hooks`
- `process`

### 2. Edit the generated files

- `setup.py` for env vars, settings, sidebar metadata, and activation metadata
- `router.py` for webhook or API routes
- `tools/*.py` for registered tools
- `skills/*.md` for domain knowledge
- `workflows/*.yaml` for repeatable task flows

### 3. Reload

```python
manage_integration(action="reload")
```

Reload discovers new integrations, registers tools, syncs skills and workflows, and refreshes activation metadata.

### 4. Verify

```python
manage_integration(action="list")
```

## Directory structure

```text
my_service/
├── __init__.py
├── setup.py
├── router.py
├── README.md
├── tools/
├── skills/
├── workflows/
├── dispatcher.py
├── hooks.py
└── process.py
```

## `SETUP` activation metadata

Activation metadata should point at the tools and prompt layers the integration contributes.

```python
SETUP = {
    "activation": {
        "tools": ["my_service_lookup", "my_service_mutate"],
        "requires_workspace": False,
    },
}
```

If skills should be available by default, enroll them through the normal bot or channel skill surfaces rather than a hidden bundle abstraction.

## Tool authoring notes

- Register tools with accurate descriptions and schemas.
- Return JSON strings, not raw Python objects.
- Read integration settings through the standard settings helpers.
- Keep tool boundaries narrow and testable.

## Hot-reload limits

- Reload is best for new or additive integration changes.
- Python module caching still makes some edits restart-sensitive.
- Router removal and deep module unloading still require a restart in some cases.
