---
name: spindrel-integration-operator
description: "Use when editing Spindrel integrations: manifests, activation, channel bindings, delivery, renderers, webhooks, rich tool results, Slack, Discord, BlueBubbles, and platform-depth tests. This is for development agents working in this repository, not in-app Spindrel runtime agents."
---

# Spindrel Integration Operator

This is a repo-dev skill for agents editing Spindrel source. It is not a Spindrel runtime skill and must not be imported into app skill tables.

## Start Here

1. Read `CLAUDE.md` and `docs/guides/integrations.md`.
2. Read the platform guide when touching a platform:
   `docs/guides/slack.md`, `docs/guides/discord.md`, or
   `docs/guides/bluebubbles.md`.
3. Check current manifests, activation flows, and binding contracts before
   adding platform-specific code.
4. Grep `integrations/sdk.py` before adding helpers under `integrations/<id>/`.

## Do

- Keep integration-specific code in `integrations/<id>/`.
- Keep shared integration helpers in `integrations/sdk.py`.
- Treat activation, binding, delivery, renderer, and webhook contracts as one
  surface; update tests for the whole path when behavior changes.
- Keep rich results portable: integrations may adapt presentation, but tool
  contracts should stay useful to agents across surfaces.
- Validate permission, secret, and approval delivery behavior when a platform
  action can mutate outside systems.

## Avoid

- No integration-specific code in `app/`.
- Do not hard-code Slack assumptions into cross-integration services.
- Do not skip manifest or activation tests because only one platform changed.
- Do not confuse repo-dev `.agents` skills with runtime bot skills or
  integration-discovered app skills.

## Completion Standard

Run focused manifest, depth, renderer, or webhook tests for the platform touched.
If a helper moves across integrations, run the duplicate-helper drift test too.
