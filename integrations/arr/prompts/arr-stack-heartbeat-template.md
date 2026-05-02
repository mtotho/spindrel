---
name: "Arr Stack - Heartbeat"
description: "Compact media heartbeat that audits tracked expectations through the official ARR stored script, then diagnoses only anomalies."
category: heartbeat
tags:
  - media
  - arr
  - heartbeat
  - maintenance
  - mission-control
---

Run the deterministic ARR audit first:

`run_script(skill_name="integrations/arr/media_management", script_name="expected-download-audit")`

Use the script output as the source of truth for expected vs downloaded state. It reads
`data/tracked-shows.json` and `data/tracked-movies.json`, calls `arr_heartbeat_snapshot`,
and returns compact JSON with `recommended_response`, counts, and categorized item lists.
Do not read `status.md`, repeat the same tracked-file reads, or call raw ARR tools unless
the script fails, reports a read error, or names a specific anomaly that needs focused
diagnosis.

If `status` is `ok`, keep the heartbeat quiet unless the workflow requires a timeline entry.
If `status` is `needs_attention`, base the reply on `recommended_response` and
`actionable_items`. Mention queued/upcoming items only when they clarify the action. Make
follow-up tool calls only for named actionable items.

Do not mutate Sonarr/Radarr monitoring settings during this heartbeat. Do not perform web
schedule searches in the heartbeat path. If a deterministic audit gap is found, report the
gap and propose a script update rather than expanding this heartbeat into serial tool calls.
