# Native Planning

Native planning is Spindrel's transcript-first plan mode for normal Spindrel agents.
It is separate from external harness planning in Claude Code or Codex: the Spindrel
session owns the plan artifact, approval state, execution progress, and adherence
review.

Feature placement follows the agentic-readiness rubric:

- the plan-mode procedure belongs in the runtime skill
  `planning/native_session`, because smaller models mostly need ordering,
  caveats, and examples for existing tools
- the plan tools and session API stay responsible for runtime state, approval,
  atomic progress recording, and enforcement
- plan cards and review surfaces should focus the human on the current decision,
  blocker, or next action

Use the canonical behavior spec for exact contracts:

- [Session Plan Mode](../planning/session-plan-mode.md)

Use the visual feedback guide for the live screenshot capture workflow:

- [Native Spindrel Plan Mode Run](visual-feedback-loop.md#native-spindrel-plan-mode-run)

## Expected Flow

1. Start plan mode from the session controls or `/plan`.
2. Ask focused questions when target, scope, success signal, or mutation boundary is unclear.
3. Publish one structured plan artifact with `publish_plan`.
4. Approve the current revision before mutating tools can run.
5. During execution, record every turn outcome with `record_plan_progress`.
6. Request a replan when the accepted revision is stale.
7. Review adherence so claimed completion is checked against actual turn evidence.
8. Exiting plan mode suspends the active plan visibly; resuming clears the
   suspension and restores the execution state from the accepted revision.

Recovery is part of the contract. An unsupported completion review means the
latest claim is not trusted; the agent must record corrected progress or repeat
the step before mutating again. A needs-replan review means the accepted revision
is stale; mutation stays blocked until a revised plan is published and approved.
For small-model drift, native loop recovery is allowed to convert explicit
question-card prose into `ask_plan_questions` and retry correctable
`publish_plan` validation/readiness failures once.
Completion claims are also guarded: if a `step_done` outcome says verification
or readback succeeded, the turn must include the matching read/check tool result
before `record_plan_progress` accepts it. A recovered guardrail failure in the
same turn still reviews as supported once the requested readback and final
progress record succeed.

The UI should direct attention to the current decision or next action first. Full
plan detail stays available below the focus area without turning the transcript
into a wall of text. If `publish_plan` is rejected, the rejection is treated as
actionable plan feedback: the card focuses `Revise plan` with the exact error
and fallback, while the agent receives the same structured tool-error contract.

## Screenshot Gallery

These screenshots are live native Spindrel sessions captured from the dedicated
plan-mode E2E channel. They are docs artifacts and regression targets.

| State | Default | Mobile | Terminal |
|---|---|---|---|
| Question intake | [question card](../images/spindrel-plan-question-card-dark.png) | | |
| Draft plan | [default](../images/spindrel-plan-card-default-dark.png) | [mobile](../images/spindrel-plan-card-mobile-dark.png) | [terminal](../images/spindrel-plan-card-terminal-dark.png) |
| Answered questions | [default](../images/spindrel-plan-answered-questions-dark.png) | | [terminal](../images/spindrel-plan-answered-questions-terminal-dark.png) |
| Progress recorded | | [mobile](../images/spindrel-plan-progress-executing-mobile-dark.png) | [terminal](../images/spindrel-plan-progress-executing-terminal-dark.png) |
| Replan pending | [default](../images/spindrel-plan-replan-pending-default-dark.png) | | [terminal](../images/spindrel-plan-replan-pending-terminal-dark.png) |
| Missing outcome guard | [default](../images/spindrel-plan-pending-outcome-default-dark.png) | | [terminal](../images/spindrel-plan-pending-outcome-terminal-dark.png) |
| Professional plan contract | [default](../images/spindrel-plan-quality-contract-default-dark.png) | | [terminal](../images/spindrel-plan-quality-contract-terminal-dark.png) |
| Long-plan readability | [default](../images/spindrel-plan-stress-readability-default-dark.png) | [mobile](../images/spindrel-plan-stress-readability-mobile-dark.png) | [terminal](../images/spindrel-plan-stress-readability-terminal-dark.png) |
| Adherence review | [default](../images/spindrel-plan-adherence-review-default-dark.png) | | [terminal](../images/spindrel-plan-adherence-review-terminal-dark.png) |
| Automatic adherence receipt | [default](../images/spindrel-plan-adherence-auto-default-dark.png) | | [terminal](../images/spindrel-plan-adherence-auto-terminal-dark.png) |
| Unsupported retry recovery | [default](../images/spindrel-plan-adherence-retry-default-dark.png) | | [terminal](../images/spindrel-plan-adherence-retry-terminal-dark.png) |

## Verification

Run the full live native-planning parity tier after changes to planning tools,
plan prompts, execution guards, semantic review, or plan-card rendering:

```bash
./scripts/run_spindrel_plan_live.sh --tier adherence
```

Then refresh the docs screenshots when UI output changes:

```bash
SPINDREL_API_KEY=... \
python -m scripts.screenshots.spindrel_plan_live \
  --api-url http://10.10.30.208:8000 \
  --ui-url http://10.10.30.208:8000 \
  --browser-url http://10.10.30.208:8000 \
  --output-dir docs/images
```

Close the loop with:

```bash
python -m scripts.screenshots check
```
