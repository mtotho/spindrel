---
name: Automation
description: Entry point for bot-triggered automation — standing orders, machine control, and bounded machine probes. Routes between them.
triggers: automation, watch this, poll until, wait for, standing order, remind me when, keep an eye on, local machine, my computer, local exec, machine target, machine probe, progressive discovery
category: core
---

# Automation

Three sub-skills cover the automation surface a bot reaches for directly from chat. Task pipelines are adjacent but separate — read `pipelines/index` when you need scheduled multi-step work instead.

## Read This First When

- The user asks you to watch, wait for, or react to a condition ("ping me when…", "poll until…")
- The user wants work to run on their local computer or a leased machine target
- The user has a vague network, Docker, or service symptom and you need bounded evidence before advice
- You need to decide between a standing order and a pipeline — standing orders stay live and cancellable; pipelines run once and finish

## Which Skill Next

- [Standing Orders](standing_orders.md)
  Plant a live dashboard tile with a poll or timer strategy that keeps ticking after the turn ends and pings back when a completion condition fires. Per-bot cap is 5.
- [Machine Control](machine_control.md)
  Inspect or run commands on a leased machine target via the local-machine-control surface (`local_companion` or `ssh` provider, session lease enforced).
- [Machine Probes](machine_probes.md)
  Run bounded read-only probes on a leased machine target for progressive network, DNS, port, Docker, and homelab discovery.

## The Short Version

- **Standing order** = declarative "watch this until it happens." Strategy is `poll_url` or `timer`; completion conditions unpark the bot and deliver a follow-up message.
- **Machine control** = imperative "run X on target Y." Session lease is one-session-one-target; probe readiness before long-running work.
- **Machine probe** = bounded read-only evidence gathering on a leased machine target. Use before raw shell commands for vague troubleshooting.
- For multi-step scheduled work with branching and conditions, reach for a **pipeline** instead.
