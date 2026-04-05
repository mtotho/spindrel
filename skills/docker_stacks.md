---
name: Docker Stacks
description: Create and manage Docker Compose stacks for databases, caches, and services
triggers: docker stack, docker compose, postgres, redis, database, container, service stack
category: workspace
---

# Docker Stacks — Agent-Managed Multi-Container Services

Use `manage_docker_stack` to create and manage Docker Compose stacks — isolated groups of containers (databases, caches, message queues, APIs) that your workspace can reach by DNS name.

## When to Use Stacks vs Workspace

- **Workspace container**: Your main execution environment. Use it for running scripts, installing packages, editing files.
- **Docker stacks**: When you need **additional services** — a Postgres database, Redis cache, Elasticsearch, a custom API, etc. The workspace connects to stack services via Docker networking.

## Lifecycle

```
create → start → (exec / logs / status) → stop → destroy
```

1. **create**: Validates compose YAML, stores it, assigns a unique project name
2. **start**: Runs `docker compose up -d`, connects workspace to the stack network
3. **exec**: Run commands inside any service container (e.g., `psql`, `redis-cli`)
4. **logs**: View container logs (optionally filtered to a specific service)
5. **status**: Check live container state and health
6. **stop**: Gracefully stop all containers (data volumes preserved)
7. **restart**: Restart all containers without recreating
8. **destroy**: Tear down containers, networks, and (by default) volumes. Use `keep_volumes=true` to preserve data.
9. **update**: Change the compose definition (stack must be stopped first)

## Compose YAML Constraints

The system sanitizes all compose definitions. These are **automatically handled**:
- Resource limits (CPU/memory) are injected into every service
- `restart: always` → `restart: unless-stopped`
- Management labels added to every container

These will be **rejected**:
- `privileged: true`, `cap_add`, `devices`
- `network_mode: host`, `pid: host`, `ipc: host`
- `security_opt`, `sysctls`
- Volume mounts to `/var/run/docker.sock`, `/etc`, `/proc`, `/sys`, `/dev`

## Common Stack Patterns

### PostgreSQL Database
```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: app
      POSTGRES_PASSWORD: secret123
    ports:
      - "5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
```
Access from workspace: `psql -h postgres -U app -d myapp`

### Redis Cache
```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379"
```
Access from workspace: `redis-cli -h redis`

### PostgreSQL + Redis
```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: app
      POSTGRES_PASSWORD: secret123
    volumes:
      - pgdata:/var/lib/postgresql/data
  redis:
    image: redis:7-alpine
volumes:
  pgdata:
```

### Full-Stack App
```yaml
services:
  api:
    image: node:20-slim
    working_dir: /app
    command: npm start
    environment:
      DATABASE_URL: postgres://app:secret@postgres:5432/myapp
      REDIS_URL: redis://redis:6379
    ports:
      - "3000"
    depends_on:
      - postgres
      - redis
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: app
      POSTGRES_PASSWORD: secret123
  redis:
    image: redis:7-alpine
```

## Networking

- All services in a stack share a Docker network
- The workspace container is automatically connected to the stack network on `start`
- Services are reachable by their service name as DNS (e.g., `postgres`, `redis`, `api`)
- On `stop` or `destroy`, the workspace is disconnected from the network

## Data Persistence

- Named volumes (e.g., `pgdata:/var/lib/postgresql/data`) persist across stop/restart
- `destroy` removes volumes by default — use `keep_volumes=true` to preserve them
- Bind mounts work but are restricted (no host system paths)

## Cross-Bot Sharing

- Stacks created in a channel are visible to all bots with `docker_stacks.enabled` in that channel
- Only the creating bot can `destroy` or `update` the definition
- Any enabled bot can `start`, `stop`, `exec`, view `logs`, and check `status`

## Debugging

1. Check status: `manage_docker_stack(action="status", stack_id="...")`
2. View logs: `manage_docker_stack(action="logs", stack_id="...", service="postgres")`
3. Exec into container: `manage_docker_stack(action="exec", stack_id="...", service="postgres", command="pg_isready")`
4. If a stack is in error state, check the error_message in the list output

## Resource Limits

Every service gets default CPU and memory limits injected automatically. Be mindful of the per-bot stack count limit. Clean up stacks you no longer need with `destroy`.
