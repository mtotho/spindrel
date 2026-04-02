# External Harness Execution

Harnesses let an agent call external CLI tools (e.g. `claude`, `cursor`) as subprocesses and return their stdout. The agent calls `delegate_to_harness` and gets the output back as a tool result.

## Quick Start

**1. Configure `harnesses.yaml`** (project root):

```yaml
harnesses:
  claude-code:
    command: claude
    args: ["--print", "{prompt}"]
    working_directory: "{working_directory}"
    timeout: 300
```

**2. Enable for a bot** (YAML or admin UI):

```yaml
local_tools:
  - delegate_to_harness
harness_access:
  - claude-code
```

**3. Call it:**

```
user: Use claude-code to refactor /home/user/project/main.py
bot:  [calls delegate_to_harness(harness="claude-code", prompt="...", working_directory="/home/user/project")]
      Here's what claude-code did: ...
```

---

## How It Works

Harnesses run as **subprocesses of the agent-server process** — not inside Docker sandbox containers. The subprocess inherits the agent-server's environment (including all `.env` variables).

```
agent-server process
  → delegate_to_harness("claude-code", prompt)
      → HarnessService.run()
          → asyncio.create_subprocess_exec("claude", "--print", prompt, cwd=working_dir)
          ← stdout captured (up to 64 KB)
      ← HarnessResult { stdout, stderr, exit_code, duration_ms }
  ← tool result returned to LLM
```

This is distinct from Docker sandbox execution (`exec_sandbox`), which runs commands inside a separate isolated container. To run `claude` inside a sandbox, see [Sandbox Use](#sandbox-use) below.

---

## Setting Up the claude-code Harness

### Install claude CLI

**Local dev (running `uvicorn` on the host):**

```bash
# Requires Node.js 18+
npm install -g @anthropic-ai/claude-code

# Verify:
claude --version
```

**Docker / `docker compose up`:** The main `Dockerfile` already installs Node.js and claude CLI. Rebuild after changes:

```bash
docker compose build agent-server
```

### Authentication

#### Option A: API Key (recommended for Docker and automated use)

1. Get a key at [console.anthropic.com](https://console.anthropic.com)
2. Add to `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-...
   ```
3. Done — the harness subprocess inherits this env var automatically.

#### Option B: Claude Subscription Credentials (Max plan)

1. Log in on a machine with the claude CLI installed:
   ```bash
   claude login
   # Follow the browser prompts — credentials saved to ~/.claude/
   ```

2. **Local dev:** Just works. The subprocess inherits your home directory.

3. **Docker (`docker compose up`):** Add a credential volume to `docker-compose.yml`:
   ```yaml
   agent-server:
     volumes:
       - ~/.claude:/root/.claude:ro
   ```
   Also mount `harnesses.yaml` so it's available in the container:
   ```yaml
       - ./harnesses.yaml:/app/harnesses.yaml:ro
   ```

> Note: `dockerfiles/git-credential-github-env.sh` is for **GitHub** authentication (git push/pull inside sandbox containers). It is unrelated to Claude auth.

---

## Sandbox Use

`dockerfiles/agent-python` (used for Docker sandbox profiles) also has Node.js and claude installed.

### Option A — `delegate_to_harness` + `sandbox_instance_id` (recommended)

Same `harnesses.yaml` argv as on the host, but executed **inside** the container:

```
bot: [ensure_sandbox(profile="agent-python")]  → instance_id
bot: [delegate_to_harness(
       harness="claude-code",
       prompt="Refactor utils.py …",
       working_directory="/workspace/myrepo",
       sandbox_instance_id="<instance_id>"
     )]
```

- `working_directory` is a **container path** (not checked against `HARNESS_WORKING_DIR_ALLOWLIST`).
- Requires `DOCKER_SANDBOX_ENABLED`, bot access to the profile, and `harness_access` for that harness.
- Deferred mode stores `sandbox_instance_id` on the task and the worker runs `docker exec` the same way.

### Option B — raw `exec_sandbox`

Manual invocation (no `harnesses.yaml`):

```
bot: [calls ensure_sandbox(profile="agent-python")]
     → container started
bot: [calls exec_sandbox(instance_id=..., command="claude --print 'what is 2+2'")]
     → runs inside the container
```

Sandbox containers do **not** inherit the agent-server's environment. Add auth via the admin UI:

**Admin → Sandboxes → Profiles → [your profile] → Environment Variables:**
```
ANTHROPIC_API_KEY=sk-ant-...
```

Or mount your credentials directory under **Volume Mounts** in the same profile editor:
```
Host path:      /home/youruser/.claude
Container path: /root/.claude
Read-only:      ✓
```

---

## harnesses.yaml Reference

```yaml
harnesses:
  my-harness:
    command: my-cli           # executable name or absolute path
    args:                     # template-substituted before execution
      - "--print"
      - "{prompt}"
    working_directory: "{working_directory}"  # cwd for subprocess; {working_directory} = runtime value
    timeout: 300              # seconds; process is killed if exceeded
```

**Template substitutions in `args` and `working_directory`:**

| Template | Value |
|---|---|
| `{prompt}` | The `prompt` arg from `delegate_to_harness` |
| `{working_directory}` | The `working_directory` arg (only substituted if a valid, allowlisted path was provided) |

If `working_directory` in the config contains `{working_directory}` and no runtime path is given, `cwd` defaults to the agent-server's working directory.

---

## Admin / observability

- **Deferred** runs are `Task` rows (`dispatch_type=harness`). List them under **Admin → Tasks** (filter “harness”) or **Admin → Delegations → External harness tasks**.
- When the worker finishes, the server writes a **`harness_complete:<name>`** `tool_calls` row and a **`harness`** `trace_events` row. If the task was created with a stored parent `source_correlation_id` (current `delegate_to_harness` behavior), those rows use **the same correlation id** as the Slack turn that queued the task — open **Admin → Logs** or **Admin → Trace** for that id to see the subprocess outcome after `delegate_to_harness`.
- Harness runs are **not** a nested LLM session: there is no child row in **Delegation trees** (that page is only for `delegate_to_agent`).

---

## Bot Config

```yaml
local_tools:
  - delegate_to_harness

harness_access:          # allowlist of harness names this bot can call
  - claude-code
  - cursor
```

A non-empty `harness_access` list enables harness execution for that bot — no global `DELEGATION_ENABLED` flag required.

---

## Server Config

In `.env`:

```
HARNESS_CONFIG_FILE=harnesses.yaml              # path to harnesses.yaml
HARNESS_WORKING_DIR_ALLOWLIST=/home/user/projects,/workspace
```

`HARNESS_WORKING_DIR_ALLOWLIST` — comma-separated list of allowed paths. If empty, all directories are permitted. Set this in production to prevent the agent from running harnesses in arbitrary directories.

---

## Adding Custom Harnesses

Any CLI tool can be a harness:

```yaml
harnesses:
  # Python script
  analysis:
    command: python3
    args: ["/home/user/tools/analyze.py", "--prompt", "{prompt}"]
    timeout: 60

  # Shell script
  deploy:
    command: /home/user/scripts/deploy.sh
    args: ["{prompt}"]
    working_directory: /home/user/project
    timeout: 120
```
