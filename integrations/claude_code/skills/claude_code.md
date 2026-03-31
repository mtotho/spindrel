# Claude Code Integration

## When to Use `run_claude_code`

Use this tool for autonomous coding tasks that benefit from Claude Code's ability to read, write, edit files, run commands, and iterate. Best for:

- **Bug fixes**: Describe the bug and let Claude Code investigate, find the root cause, and fix it
- **Feature implementation**: Describe what to build; Claude Code handles file creation, imports, and testing
- **Refactoring**: Point at a module/pattern to refactor; Claude Code reads context and makes changes
- **Code review/analysis**: Ask Claude Code to analyze a codebase, find issues, or explain architecture

Claude Code runs inside the bot's Docker workspace container, so it has access to the project's full toolchain and environment.

## Sync vs Deferred Mode

- **sync** (default): Wait for the result. Good for quick tasks (< 5 min). You get the full result back.
- **deferred**: Fire and forget. Creates a background task. The result posts to the channel when done. Use for long-running tasks (large refactors, multi-file changes, comprehensive reviews). Set `notify_parent=true` (default) to automatically receive the result and react.

## Prompt Writing Tips

Be specific and actionable:
- Include file paths, function names, or error messages when relevant
- Describe the desired end state, not just the problem
- For complex tasks, break into steps or describe acceptance criteria

## Resume Sessions

If a run times out or errors partway through, use `resume_session_id` with the `session_id` from the previous result to continue where it left off. Claude Code retains full context from the prior session.

## Cost Awareness

Each invocation uses Claude API tokens. The result includes `cost_usd` and `num_turns`. For cost-sensitive workflows:
- Set `max_turns` to limit iteration depth
- Use focused, specific prompts to reduce exploration
- Check `is_error` in results to detect failures early
