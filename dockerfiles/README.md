## agent-python

A general-purpose Python sandbox image. Pre-installed:

- `git` — clone/push repos (uses `git-credential-github-env` helper for auth)
- `gh` — GitHub CLI for issues, PRs, labels, releases, etc.
- `node` + `@anthropic-ai/claude-code` — run `claude --print "..."` inside the sandbox

```bash
docker build -t agent-python:latest -f dockerfiles/agent-python .
```

### GitHub Auth (`git` + `gh`)

Add **`GITHUB_TOKEN`** to the **sandbox profile** env in Admin → Sandboxes → Profiles → Environment Variables. Injected as `docker -e` at container start — not needed at build time.

- `git` calls the bundled `git-credential-github-env` helper automatically on push/pull.
- `gh` auth: the bot can run `echo $GITHUB_TOKEN | gh auth login --with-token` on first use, or you can set `GH_TOKEN` instead (gh reads this env var natively without needing `gh auth login`).

### Claude Auth (`claude`)

Add **`ANTHROPIC_API_KEY`** to the sandbox profile env in Admin → Sandboxes → Profiles → Environment Variables.

Or add a volume mount in the same profile editor: host path `~/.claude` → container path `/root/.claude` (read-only) to use Claude subscription credentials.

### No entrypoint

The server starts the container with `sleep infinity`. The agent runs commands via `exec_sandbox`.
