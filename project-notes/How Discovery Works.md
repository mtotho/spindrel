---
tags: [agent-server, reference, discovery, architecture]
status: pointer
updated: 2026-04-23
---
# How Discovery Works

This vault page is intentionally **not** maintained as a narrative explainer anymore.

Use the canonical docs instead:

- `agent-server/docs/guides/context-management.md`
  - prompt admission rules
  - context profiles
  - live-history replay and compaction behavior
- `agent-server/docs/guides/discovery-and-enrollment.md`
  - tool discovery
  - skill discovery
  - enrollment vs loaded vs resident semantics
  - current defaults such as `SKILL_ENROLLED_AUTO_INJECT_MAX = 0`
- [[Architecture Decisions]]
  - load-bearing design choices and rationale

If this page and the canonical docs disagree, the canonical docs win.
