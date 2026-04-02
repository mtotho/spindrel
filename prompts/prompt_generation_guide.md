# Prompt Generation Guide

## Core Principles

- Write prompts in **second person imperative** — address the agent as "you"
- Be specific about what the agent should DO, not just what it IS
- Reference concrete tools, files, and capabilities the agent actually has access to
- Use @-tags (e.g. `@skill:arch_linux`, `@tool:web_search`) to wire in specific capabilities
- Avoid generic filler ("be helpful", "be concise") — every sentence should add actionable instruction
- Don't repeat instructions that are already in the platform's base prompt (tool usage, memory protocol, etc.)
- Keep prompts focused — one clear purpose per prompt field
- Use markdown formatting (headers, lists, bold) for structure in longer prompts

## Field Types

### system_prompt

The bot's foundational identity and behavioral instructions. Loaded on every request.

**Guidelines:**
- Define the agent's role, domain expertise, and personality in the first few sentences
- Specify what the agent should proactively do vs. wait to be asked
- List concrete domains of knowledge and areas of responsibility
- Include behavioral constraints (what NOT to do, tone, formality level)
- Don't duplicate built-in platform instructions (tool usage, memory management, compaction) — those are injected automatically
- Don't describe tools the agent has — tool schemas are injected via retrieval
- Keep under 800 words for focused bots; longer is fine for complex multi-domain agents
- Use ## sections to organize: Role, Responsibilities, Guidelines, Constraints

### channel_prompt

Additive context injected after the system prompt for a specific channel. Overrides or supplements bot-level behavior.

**Guidelines:**
- Assume the system prompt is already present — don't repeat its content
- Focus on what's different about THIS channel vs. the bot's default behavior
- Reference channel-specific resources: workspace files, project names, external systems
- Good for: project-specific context, team conventions, output format requirements
- Keep shorter than system_prompt — this is a modifier, not a replacement
- If the channel has a workspace, reference specific files the agent should consult

### heartbeat

A periodic prompt that runs on a timer. The agent reviews state and optionally posts updates.

**Guidelines:**
- Start with a clear instruction to review current state (workspace files, open items, logs)
- Tell the agent what to check for: stale items, missed deadlines, new developments
- Use the "optional dispatch" pattern — instruct the agent to only post if there's something noteworthy
- Reference workspace files by path (e.g., "Review data/tasks.md and data/calendar.md")
- Include what tools to use for gathering information (exec_command, search, etc.)
- Specify the output format: status update, action list, summary
- Keep under 500 words — heartbeats run frequently, prompts should be concise and scannable

### memory_flush

Instructions for saving important context before conversation history is compacted.

**Guidelines:**
- Tell the agent what categories of information to preserve (decisions, preferences, facts, corrections)
- Specify WHERE to save: daily logs for ephemeral notes, MEMORY.md for stable facts, reference/ for longer docs
- Emphasize saving what would be LOST — don't save what's already in memory or obvious from context
- Remind the agent to use its memory tools (exec_command for file writes, save_memory, etc.)
- Include the temporal aspect — note that older messages will be archived after this runs
- Keep concise — this prompt interrupts normal flow, so minimize overhead

### task_prompt

Instructions for an async task that runs independently.

**Guidelines:**
- State the objective clearly in the first sentence
- Specify constraints: time limits, resource limits, scope boundaries
- Define the expected output format (summary, file, message, etc.)
- Include success criteria — how does the agent know it's done?
- Reference any input data or context the task needs
- For recurring tasks, note what should change between runs
- Tasks run without interactive user input — make instructions self-contained

### memory_prompt

Guidance for what the agent should save to long-term memory from conversations.

**Guidelines:**
- Describe what categories of information are worth remembering (user preferences, technical decisions, project conventions)
- Specify what to skip (small talk, transient troubleshooting, already-known facts)
- Reference the memory hierarchy: MEMORY.md for stable facts, daily logs for session notes, reference/ for longer docs
- Include deduplication guidance — check before saving
- Keep this focused on the WHAT, not the HOW (the platform handles the mechanics)

### compaction_prompt

Instructions for how to summarize conversation history when context gets too long.

**Guidelines:**
- Specify what to preserve in the summary (key decisions, code snippets, file paths, user preferences)
- Note what can be safely dropped (greetings, failed attempts that were resolved, verbose tool outputs)
- Emphasize temporal context — summaries should include when things happened
- The summary replaces full history, so stress completeness of important details
- Keep the instructions themselves short — the model needs token budget for the actual summary
