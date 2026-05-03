---
name: spindrel-integration-operator
description: "Use when editing Spindrel integrations: manifests, activation, channel bindings, delivery, renderers, webhooks, rich tool results, Slack, Discord, BlueBubbles, and platform-depth tests. This is for development agents working in this repository, not in-app Spindrel runtime agents."
---

# Spindrel Integration Operator

This skill applies to any agent editing this checkout — local CLI on the operator's box, in-app Spindrel agent on the server, or a Project coding run. It is **not** a Spindrel runtime skill and must not be imported into app skill tables.

## Start Here

1. Read `CLAUDE.md` and `docs/guides/integrations.md`.
2. Read the platform guide when touching a platform:
   `docs/guides/slack.md`, `docs/guides/discord.md`, or
   `docs/guides/bluebubbles.md`.
3. Check current manifests, activation flows, and binding contracts before
   adding platform-specific code.
4. Grep `integrations/sdk.py` before adding helpers under `integrations/<id>/`.

## Triage primitives

| Need | Primitive |
|---|---|
| Find platform-specific code | `integrations/<id>/` (slack, discord, bluebubbles, github, arr, ...) |
| Find shared helpers | `integrations/sdk.py` — grep before adding a private helper anywhere under `integrations/<id>/` |
| Find a manifest | `integrations/<id>/manifest.{yaml,py}` |
| Duplicate-helper drift gate | `tests/unit/test_integration_no_duplicate_helpers.py` |
| Webhook handler entry | `integrations/<id>/webhook.py` or its dispatcher hook |
| Run platform-depth tests | `PYTHONPATH=. pytest tests/unit/ -q -k "<platform>"` |

## Named patterns to grep for

- **Same private helper in 2+ integrations** — lift to `integrations/sdk.py`. AGENTS.md anti-pattern #7 + the duplicate-helper drift gate; if the gate is silent, it's missing the helper.
- **Integration-specific code in `app/`** — must move to `integrations/<id>/`. The dispatcher protocol is the only seam between halves.
- **Streaming-message coalesce / rate-limit windows reimplemented per platform** — Discord, Slack, BlueBubbles all want the same shape; lift to a shared "Streaming Delivery Helper" in `sdk.py` rather than diverging.
- **Webhook handler bypassing the capability gate** — every inbound platform action that mutates state must go through the same authorization path; don't shortcut for "internal" integrations.

## Worked example: add a new platform integration

1. `integrations/<id>/manifest.{yaml,py}` — declare capabilities, scopes, activation needs.
2. `integrations/<id>/dispatcher.py` — implement the dispatcher protocol; the only seam app/ sees.
3. Reuse `integrations/sdk.py` helpers (streaming delivery, rate-limit windows, ID tracking) — do not reimplement.
4. Renderer in `integrations/<id>/renderer.py` for platform-specific presentation.
5. Tests: manifest load, depth, renderer, webhook auth, duplicate-helper drift.

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
