---
name: Widget Authoring Runs
description: Bot workflow for creating, checking, pinning, and recording durable widget authoring evidence. Use when a bot is asked to build, debug, improve, or validate a widget and needs to leave in-context receipts after the feedback loop.
triggers: publish_widget_authoring_receipt, prepare_widget_authoring, check_html_widget_authoring, check_widget_authoring, widget authoring receipt, widget authoring evidence, bot widget dx
category: core
---

# Widget Authoring Runs

Use this when you are actively creating, debugging, checking, or improving a widget.

## Required loop

1. Call `prepare_widget_authoring(goal=..., target_surface=...)`.
2. Load the relevant widget skill returned by the brief (`widgets/html`, `widgets/sdk`, `widgets/errors`, etc.).
3. Author or edit the bundle/template with the normal tools.
4. Run the full check:
   - standalone HTML/library/path: `check_html_widget_authoring(..., include_runtime=true, include_screenshot=true)`
   - tool-widget YAML: `check_widget_authoring(..., include_runtime=true, include_screenshot=true)`
5. If the widget is pinned, run `check_widget(pin_id=...)`.
6. Publish the receipt with `publish_widget_authoring_receipt(...)`.

Do not treat `preview_widget` as enough for user-visible work. It is the cheap dry run; the full check is the authoring gate.

## Receipt contents

Use `publish_widget_authoring_receipt` after every meaningful authoring run. The receipt appears with widget proposal/change activity, so future bots and users can see what happened without reading the whole chat.

Set:

- `action`: `created`, `updated`, `debugged`, `checked`, or `improved`
- `summary`: one sentence describing the user-visible result
- `reason`: why the work was done
- `library_ref`: the bundle or widget ref when available
- `pin_id` or `affected_pin_ids`: dashboard pins touched or checked
- `touched_files`: `widget://...` files edited
- `health_status` and `health_summary`: copied from the check result
- `check_phases`: compact phase evidence from the full check
- `screenshot_data_url`: only when the full check returned a useful screenshot
- `next_actions`: explicit follow-ups when the run did not fully close

If no channel context is active, pass `dashboard_key` explicitly, for example `workspace:spatial` or another owner key. In a channel, the tool defaults to `channel:<channel_id>`.

## Interpretation

Receipts are not reviews. They are durable authoring activity records. A proposal says what the bot thinks should happen; an authoring receipt says what the bot checked, created, changed, or could not finish.
