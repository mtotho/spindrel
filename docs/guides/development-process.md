# Development Process

This guide is the public process contract for maintaining Spindrel. It is for contributors and code agents working on this repository.

It is not product behavior. Do not encode these practices in `skills/`; that directory contains runtime bot skills surfaced to Spindrel users.

## When To Use This

Use this guide when:

- triaging review findings, bug reports, or audit notes
- turning a finding into implementation-ready work
- reviewing current or recent changes against contracts and red lines
- changing a public API, schema, event payload, provider interface, widget contract, task primitive, or other load-bearing boundary
- deciding that a proposed change is intentionally out of scope

For subsystem rules, read the matching canonical guide as well. This guide owns the work process; subsystem guides own technical contracts.

## Finding Triage

Classify every review finding into exactly one state before implementing it.

| State | Meaning | Next action |
|---|---|---|
| `needs-decision` | Product or architecture intent is unclear. | Ask for the smallest decision or record the options. |
| `needs-info` | Repro steps, logs, code truth, or affected version is missing. | Add a verification task with exact commands or files to inspect. |
| `ready-for-agent` | Current behavior, desired behavior, and fix shape are clear. | Add an Agent Brief and implement test-first when it is a bug. |
| `track` | Work spans multiple sessions, subsystems, or phases. | Move it into the relevant track or create one. |
| `out-of-scope` | The behavior is intentionally not supported or the idea is rejected. | Record why; do not leave it as active work. |
| `closed` | Fixed, stale, duplicate, or no longer true. | Close it with a pointer to the fix or reason. |

Do not leave the same active bug in multiple places. Once triaged, the owning location should be obvious.

## Agent Briefs

A finding is `ready-for-agent` only when another engineer or code agent can act without re-triaging.

Use this template:

```markdown
### Agent Brief - <short title>

**Current behavior:** What happens now, including the user-visible symptom or failing contract.

**Desired behavior:** What should happen instead.

**Likely touch points:** Files, modules, routes, tests, or docs that are likely involved. Prefer stable symbols over line numbers.

**Acceptance criteria:** Observable conditions that make the work done.

**Out of scope:** Adjacent work that should not be bundled.

**Verification:** The failing test to add or run, manual smoke path, or static check.
```

Keep briefs behavior-first. Line numbers drift; contracts and symptoms age better.

## Design It Twice

Before changing a load-bearing interface, compare more than one design. This applies to:

- REST request or response shapes
- database schemas and migrations
- event payloads and bus contracts
- provider protocols
- widget contracts and dashboard placement policy
- task pipeline primitives
- integration extension points

Write three concrete options:

| Design | Default shape |
|---|---|
| A - Minimal | Smallest compatible change. |
| B - Deep module | Moves policy behind a narrower existing boundary. |
| C - Explicit contract | Adds or names a type, schema, adapter, or validation boundary. |

Compare them on call-site complexity, hidden policy, migration risk, testability, and failure mode. Choose the design that removes caller knowledge without inventing a generic abstraction the codebase does not need.

The chosen design should include:

- the exact public interface or data shape
- rejected alternatives and why they lose here
- the commit sequence
- regression and compatibility tests

## Out Of Scope

Out-of-scope is a decision, not neglect.

Use it when a feature, mechanism, or refactor is intentionally rejected for now. Record:

- the rejected proposal
- why it is not a fit
- what existing mechanism should be used instead
- what would have to change before revisiting it

Do not leave rejected ideas in an active bug list. They should live in a decision log, investigation list, or closed issue with rationale.

## Contract And Red-Line Review

Before declaring a change done, review the current diff against the contracts that govern the touched area.

Use this checklist:

- Identify the owning contract: `CLAUDE.md`, this guide, the matching canonical subsystem guide, an API schema, a migration invariant, a test fixture contract, or a documented architecture decision.
- Confirm the change preserves that contract, or explicitly updates the contract and compatibility path.
- Check the active red lines in `CLAUDE.md` and the matching canonical guide. Red lines are rules phrased as "do not", "never", "must", "only", deprecated, ownership boundaries, or accepted invariants.
- If the change crosses a red line, stop and either change the implementation or record a deliberate contract change with migration and tests.
- Add or update regression coverage for contract violations that code can enforce.
- For public docs, do not point readers at private vault paths or local machine files; use repo-local docs or `project-notes/` mirrors.

This applies both to work in progress and to recent commits under review. A review that only checks whether tests pass is incomplete when the change touches a public interface, subsystem boundary, or documented invariant.

## Promoting New Red Lines

When a violation is found, turn it into a durable rule in the same pass that fixes or closes it.

Prefer enforcement in this order:

| Location | Use when |
|---|---|
| Test, type, lint, migration guard, or hook | The rule is mechanically checkable. |
| Owning canonical guide | The rule is architectural, cross-file, or needs human judgment. |
| `CLAUDE.md` | The rule is repo-wide and should be visible at session start. Keep it short. |
| Local workspace instructions | The rule is private workflow, vault handling, machine setup, or session hygiene. |

Record the new red line with:

- the bad pattern to avoid
- the approved replacement or owning boundary
- the reason it matters
- the verification that should catch regressions

If the violation came from a bug, keep the bug workflow intact: reproduce it, fix it, add the regression, and close the source note or issue. If it changes architecture intent, update the architecture decision record. Do not leave the lesson only in a session transcript.

## Runtime Skills Boundary

`skills/` is part of the product. Files there are loaded into Spindrel's runtime skill catalog and can be surfaced to bots and users.

Implementation-process guidance belongs in public repository docs, tests, contributor tooling, or agent instructions such as `CLAUDE.md`. It does not belong in runtime bot skills unless the intended product behavior is for bots to use that guidance while serving users.

When in doubt, ask: "Should a normal Spindrel bot use this while answering a user?" If not, keep it out of `skills/`.

## Verification Discipline

- Bug fixes are test-first: reproduce, fix, verify.
- Refactors preserve public behavior unless the brief explicitly says otherwise.
- Contract changes need compatibility coverage or a documented migration.
- Recent changes need contract and red-line review before they are treated as done.
- UI changes need the required typecheck and the relevant UI guide.
- Documentation changes should update the public guide index or nav when adding a new guide.

The process is meant to reduce ambiguity, not add ceremony. If a change is small and obvious, the brief can be short; it still needs a clear owner, expected behavior, and verification.
