---
name: Spatial Widget Stewardship
description: Inspect, reason about, and curate bot-owned widgets on the Spatial Canvas without creating clutter.
triggers: spatial widgets, spatial canvas widgets, channel orbit, widget pile, clean up spatial widgets, bot-owned widgets, heartbeat spatial widgets
category: widgets
---

# Spatial Widget Stewardship

Use this when a channel heartbeat or chat turn asks you to improve widgets on
the Spatial Canvas.

## Principle

Your job is not to make more widgets. Your job is to make the channel orbit
easier to understand at a glance.

## Required Loop

1. Call `inspect_spatial_widget_scene` before changing spatial widgets.
2. Read the scene score and warnings:
   - overlapping widgets
   - clipped/offscreen widgets
   - tiny unreadable widgets
   - duplicate labels or duplicate purpose
   - unmanaged/user-owned widgets that you must not edit
3. Inspect specific nearby objects only when the scene says you need more
   detail.
4. Prefer improving existing bot-owned widgets:
   - resize unreadable widgets
   - move overlapping widgets into clearer open space
   - remove your own empty/default/duplicate widgets
   - keep useful channel landmarks close enough to the channel orbit to read
5. Before mutating, call `preview_spatial_widget_changes` with the exact
   intended operations. The mutation tools reject edits that do not match a
   recent preview for this channel and bot.
6. Apply only changes that make the previewed scene clearer.
7. Re-inspect if you made several changes or if the preview still reports
   overlap/clipping.

## Creation Standard

Create a new spatial widget only when all are true:

- the inspected scene shows a real missing surface;
- no existing bot-owned widget can be updated, moved, or resized to serve that
  purpose;
- the new widget has a clear title and durable purpose;
- the proposed placement will not worsen overlap, clipping, or duplicate
  low-signal widgets.

## Ownership Boundary

You may only move, resize, remove, or replace widgets you created. User-owned
widgets and other bots' widgets are context, not editable material.

## Reporting

If you changed widgets, report the reason in one concise sentence. If you only
inspected and nothing improved by changing the scene, say that no spatial widget
change was useful.
