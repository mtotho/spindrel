---
name: improve-codebase-architecture
description: "Use when the user asks to deepen Spindrel's architecture, find refactoring opportunities, or run the nightly architecture-deepening loop. Surfaces deepening candidates against `docs/tracks/architecture-deepening.md`, lands one with the user, and updates `docs/deepening-log.md`. Repo-dev skill — not a Spindrel runtime skill."
---

# Improve Codebase Architecture (Spindrel)

Repo-dev skill for surfacing **deepening opportunities** — refactors that turn shallow modules into deep ones — and shipping them with same-edit doc updates. The architectural method is Ousterhout-style; the Spindrel bindings tie it to the track, the log, and the project's domain glossary.

<!--
Adapted from mattpocock/skills/improve-codebase-architecture
https://github.com/mattpocock/skills — MIT License, © Matt Pocock.
Spindrel-specific bindings: domain glossary, ADR file, deepening log,
and warm-start pointers replace the upstream CONTEXT.md / docs/adr/ contracts.
-->

## Glossary — use these terms exactly

Full definitions in [LANGUAGE.md](LANGUAGE.md). Don't drift into "component," "service," "API," or "boundary."

- **Module** — anything with an interface and an implementation.
- **Interface** — everything a caller must know: types, invariants, error modes, ordering, config.
- **Depth** — leverage at the interface. **Deep** = high leverage. **Shallow** = interface ≈ implementation.
- **Seam** — where an interface lives.
- **Adapter** — a concrete thing satisfying an interface at a seam.
- **Locality** — change, bugs, knowledge concentrated in one place.

Key principles:

- **Deletion test**: imagine deleting the module. If complexity vanishes, it was a pass-through. If it reappears across N callers, it was earning its keep.
- **The interface is the test surface.**
- **One adapter = hypothetical seam. Two adapters = real seam.**

## Spindrel bindings

Read these first; do not re-litigate them.

| Need | File |
|---|---|
| Active candidate inventory + what shipped | `docs/tracks/architecture-deepening.md` |
| Past deepenings (don't re-suggest, **check for drift**) | `docs/deepening-log.md` |
| Domain vocabulary (use these names) | `docs/guides/ubiquitous-language.md` |
| Decisions already settled (don't re-suggest) | `docs/architecture-decisions.md` |
| Subsystem map / request flow | `docs/architecture.md` |
| Active work / what's in flight | `docs/roadmap.md` |
| Open bugs / friction signals | `docs/inbox.md` |
| Track lifecycle + format contract | `docs/guides/tracks.md` |
| Hot-zone names (god functions, integration boundary) | `AGENTS.md` rules section |

## Modes

This skill runs in two modes. Pick by context:

### Interactive mode (operator-driven)

Use when a human is in the loop and wants to pick the next candidate.

1. **Explore.** Read the bindings table. Use the Agent tool with `subagent_type=Explore` to walk the codebase organically — note shallow modules, missing locality, leaky seams, untested-or-untestable interfaces. Apply the deletion test.
2. **Drift sweep — same explore pass.** For each entry in `docs/deepening-log.md`, spot-check the seam. Drifted seams are first-class candidates; flag them as `_drift: <date> deepening_`.
3. **Present candidates.** Numbered list with **Files / Problem / Solution / Benefits / Drift?**. Use `docs/guides/ubiquitous-language.md` for domain names and [LANGUAGE.md](LANGUAGE.md) for architecture vocabulary. Do NOT propose interfaces yet. Ask: "Which would you like to explore?"
4. **Grilling loop.** Once picked, walk the design tree with the user. See [DEEPENING.md](DEEPENING.md) for the dependency-category framework that determines test strategy and [INTERFACE-DESIGN.md](INTERFACE-DESIGN.md) for alternatives.
5. **Land it.** Implement, replace tests at the new interface (don't layer — see DEEPENING.md "replace, don't layer"), then in the **same edit**:
   - Append an entry to `docs/deepening-log.md` (seam, what deepened, why, track/ADR link).
   - Strike the row in `docs/tracks/architecture-deepening.md` Status table; remove the inventory entry; bump `updated:`.
   - If the deepening introduces a domain term not in `docs/guides/ubiquitous-language.md`, propose adding it (ask before editing — that file is canonical).
   - If the user rejects a candidate with a load-bearing reason, offer to add an entry to `docs/architecture-decisions.md` so future runs don't re-suggest it.

### Unattended mode (overnight Project run)

Use when invoked by a scheduled Project coding run. The Run Brief MUST scope the work to one candidate and one bounded outcome — see [`.spindrel/WORKFLOW.md` Run Briefs](../../../.spindrel/WORKFLOW.md). If the brief lacks a candidate, **stop and emit `needs_review`**.

Cadence:

- **Source document:** `docs/tracks/architecture-deepening.md` (named candidate).
- **Mission:** land the named candidate end-to-end (extract, test at new interface, ship doc updates).
- **Stop when:** new tests pass at the new interface, old shallow tests are removed, deepening-log entry is appended, track row is struck.
- **Stay inside:** files listed in the candidate's "Files" line plus the new module path. Don't widen scope to fold in adjacent candidates.
- **Evidence:** `pytest` output for tests at the new interface, line-count delta on the deepened module, updated `deepening-log.md` entry hash.
- **Out-of-scope discovery:** if the grilling loop reveals a load-bearing constraint that contradicts the brief, write the receipt with `needs_review` and stop. Do not pivot.
- **Drift sweep:** even in unattended mode, spot-check past entries in `docs/deepening-log.md`. If drift is found, surface it in the receipt; do not pivot the run to fix it.

## Verification

For every deepening (interactive or unattended):

```bash
. .venv/bin/activate
PYTHONPATH=. pytest tests/unit/ -q -k "<deepened-module-keywords>"
```

Run the broader sweep before declaring done:

```bash
PYTHONPATH=. pytest tests/ integrations/ -v
```

Per `AGENTS.md`: do NOT run pytest in Docker. Async-SQLite tests may auto-skip on local Python 3.14 — that's expected.

## Completion Standard

A deepening is "done" when:

- New tests assert invariants at the new module's interface (not the old shallow one).
- Old shallow-module tests that no longer have a real seam are deleted (per DEEPENING.md "replace, don't layer").
- `docs/deepening-log.md` has the new entry.
- `docs/tracks/architecture-deepening.md` Status table reflects the change; inventory section is pruned.
- If a domain term landed: `docs/guides/ubiquitous-language.md` updated (with user approval in interactive mode).
- If a candidate was rejected for a load-bearing reason: `docs/architecture-decisions.md` has the entry.

## Anti-patterns

- **Don't propose interfaces in step 3.** That happens in the grilling loop.
- **Don't list every theoretical refactor an ADR forbids.** Only surface a contradicting candidate when the friction is real enough to revisit the ADR.
- **Don't re-litigate decisions in `docs/architecture-decisions.md`.** Read first; surface contradictions only with explicit framing.
- **Don't fold an unscoped second deepening into a single run.** Each shipped deepening gets its own log entry and its own track-row removal.
- **Don't leave the candidate in the inventory after shipping.** Per the track's own contract, landed deepenings move to the log and are removed from the inventory.
