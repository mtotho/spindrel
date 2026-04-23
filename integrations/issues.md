
  2. MC Deterministic Refactor (tools → DB tables)

  This is the bigger, more impactful one. The core insight: MC tools (create_task_card, move_task_card, etc.) should
  write directly to integration DB tables, not markdown files. Task board API is already in the integration (services.py
   + router_kanban.py), but the tools still round-trip through markdown parsing which is fragile.

  What changes:
  - Tool implementations call integration service layer / API directly
  - tasks.md becomes read-only rendering of DB state
  - Bot never touches markdown directly — tools are the only write path
  - If bot doesn't call tools → nothing happens (vs. current: corrupted markdown)
  - Should set good pattern for other integrations (including user brought) -

  Future

  - Configuration surface area simplification



My response to the assistant (see assistant response below it)
1. Maybe i misunderstood. I thought that IF mission control was activated, agnostic of the workspace schema, it injected a standard misison control
  template. Then on top of that, you added specific workspace schema that matched your specific project (software dev, arr). that was the intent. And yes to
  your other point, we need a standard way of declaring that a certain template IS mission control compatible - thats why i added the tag - but i wouldnt want
  the WHOLE arr sweet to be required to activate mission control - just that if you wanted to use that template, it would suggest using mission control on
  the ui - maybe we need a "required-integrations" or "compatible-integration" tag In the channel template template, that specifis the version and name
  identifier of the integration (which also means we'll need to make sure mission control and its templates have versioning)


Responding to assistant (discussion about arr integration mission control compatibility):
  Three issues worth discussing

  1. Schema conflict: MC + ARR on the same channel

  A channel can only have one workspace schema template. The ARR schema is already MC-compatible (tasks.md, status.md, timeline.md, plans.md all follow MC
  format), so it's effectively a superset. That's the right design — an ARR channel uses the ARR schema, which includes MC structures. No conflict if the user
  picks the right template.

  But this is implicit right now. The ARR activation metadata and setup.py don't declare requires_workspace: true or signal that it expects a specific schema. When someone
   activates ARR on a channel, nothing tells them "you should also set the workspace schema to the ARR template."

  2. Where learnings go — it's two different things

  The ARR template already has the right answer for structured domain data: data/tracked-shows.json, data/tracked-movies.json, data/history.json in the channel
  workspace. That's per-channel, on-demand readable, not auto-injected. Correct.

  Bot memory (MEMORY.md + daily logs + reference files) is the right place for different things:
  - Soft operational learnings: "Indexer X is unreliable after 2am", "user prefers WEB-DL over HDTV"
  - Cross-channel patterns (if one bot serves multiple ARR channels, unlikely but possible)
  - User preference profiles

  The gap: neither the ARR activation guidance nor the skills give the bot any guidance on what to put in bot memory vs channel workspace data. The bot needs to know:
  structured media tracking → data/*.json, soft learnings/preferences → memory/reference/arr-learnings.md or similar. I'd add a brief note to the shipped skill/prompt
  guidance about this.

  3. Heartbeat template vs download-monitoring skill — significant overlap

  download-monitoring.md (skill, 120 lines) and arr-stack-heartbeat-template.md (prompt, 250 lines) cover a lot of the same ground. Both describe checking
  downloads, detecting stalls, auto-remediating, updating MEDIA.md. The heartbeat template is far more detailed (9 phases with explicit tool call sequences),
  while the skill is more of a reference guide.

  The question is: when the heartbeat fires, it gets the heartbeat prompt template injected. But the bot also has the download-monitoring skill available
  (on_demand). If the heartbeat prompt is 250 lines, that's a big context chunk. And if the skill gets pulled in too, you're doubling up.

  My take: the heartbeat template should be the authoritative execution plan (it's great for that — phased, detailed). The skill should slim down to interactive
   use only — "how to check downloads when a user asks" rather than duplicating the heartbeat protocol. Right now the skill's Phase 1-5 structure mirrors the
  heartbeat template almost exactly.

  What I'd do next

  1. Add activation metadata to ARR so the channel activation surface declares the ARR tools directly and marks `requires_workspace: true`
  2. Slim down download-monitoring.md to be an interactive reference, not a heartbeat protocol duplicate
  3. Add a learnings note to the shipped skill/prompt guidance — brief guidance on what goes where (workspace data vs bot memory)
  4. Consider whether the heartbeat template is too long — 250 lines is a lot of prompt. At ~13 tokens/line that's ~3.2k tokens just for heartbeat instructions.
   Might be fine for a dedicated heartbeat run, but worth being aware of.

  Want me to start on any of these?
