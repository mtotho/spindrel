---
name: spindrel-widget-operator
description: "Use when editing Spindrel widgets and dashboards: widget contracts, package loading, pins, iframe SDK, native widgets, authoring checks, dashboard surfaces, and widget tests. This is for development agents working in this repository, not in-app Spindrel runtime agents."
---

# Spindrel Widget Operator

This skill applies to any agent editing this checkout — local CLI on the operator's box, in-app Spindrel agent on the server, or a Project coding run. It is **not** a Spindrel runtime skill and must not be imported into app skill tables.

## Start Here

1. Read `CLAUDE.md`.
2. Read `docs/guides/widget-system.md`.
3. For dashboard surfaces, read `docs/guides/widget-dashboards.md`.
4. For HTML widgets or authoring work, read `docs/guides/html-widgets.md` and
   `docs/guides/dev-panel.md`.

## Triage primitives

| Need | Primitive |
|---|---|
| Widget contract / envelope serialization | `app/services/widget_templates.py` |
| Action authorization (sqlite authorizer) | `app/services/widget_action_auth.py` + `widget_handler_tools.py` |
| Iframe SDK | `ui/src/widgets/` |
| Dashboard pins / projection | `app/services/dashboard_pins.py` |
| Manifest signing / load-time HMAC | `app/services/manifest_signing.py` |
| Run focused widget tests | `PYTHONPATH=. pytest tests/unit/ -q -k widget` |

## Named patterns to grep for

- **Widget package bypassing the manifest contract** — special-cased loading paths that skip signature verification or capability declarations. The `manifest_hash_drift` audit signal escalates to `critical` on signed-row mismatch.
- **iframe origin / capability gate weakened** — adding an `allow-*` sandbox flag, broadening `postMessage` origins, or skipping the capability declaration. Each is a security boundary.
- **Action handler skipping `widget_action_auth`** — direct DB writes from a widget handler without the sqlite authorizer. Authorizer denies `ATTACH` / `DETACH` / extension load / `VACUUM` for widget DBs; bypassing it is a capability creep.
- **Dashboard state mutated during screenshot capture** — non-deterministic screenshots; tests must stage explicit fixtures rather than rely on live data.

## Worked example: add a new native widget

1. Manifest in the widget package — declare capabilities, action handlers, action scopes.
2. Sign the manifest (HMAC over canonical payload via `manifest_signing.py`); verify-on-read at `load_widget_templates_from_db`.
3. Action handler reuses `widget_action_auth` for any DB write.
4. iframe origin policy follows the existing host policy — no new sandbox relaxations without an explicit env-var opt-in documented in `SECURITY.md`.
5. Tests: manifest load, action authorization, envelope serialization, plus a focused screenshot if dashboard layout changed.

## Do

- Preserve widget envelope contracts, origin rules, and host policy.
- Keep generated or user-authored widget content separate from trusted app UI.
- Add focused tests for manifest loading, pin behavior, SDK handlers, or
  authoring checks when those paths change.
- Use runtime screenshot or authoring checks when the issue is renderability,
  not just data shape.
- Keep widget usefulness and agency receipts meaningful to agents and humans.

## Avoid

- Do not special-case a widget by bypassing the package/manifest contract.
- Do not weaken iframe, auth, or action authorization boundaries.
- Do not import repo-dev `.agents` skills into widget packages or app skills.
- Do not mutate dashboard state during screenshot capture unless the scenario
  explicitly stages that mutation.

## Completion Standard

Run the focused widget unit slice for the contract touched. Run UI typecheck for
dashboard UI edits and the visual feedback loop for layout-sensitive changes.
