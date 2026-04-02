FROM python:3.12-slim

# Node.js + claude CLI — required for the Claude Code integration.
# Adds ~200MB. Remove this block if you don't use Claude Code.
RUN apt-get update -qq && \
    apt-get install -y -qq nodejs npm && \
    npm install -g @anthropic-ai/claude-code && \
    rm -rf /var/lib/apt/lists/*

# Docker CLI — needed for sibling container management (workspaces, sandboxes).
# Only the CLI binary; the daemon runs on the host via mounted socket.
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends docker.io && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY app/ app/
COPY integrations/ integrations/
COPY packages/ packages/
COPY alembic.ini .
COPY migrations/ migrations/

# Build integration web UIs (dashboards served as static files via iframe)
RUN for d in integrations/*/dashboard; do \
      [ -f "$d/package.json" ] || continue; \
      echo "Building integration UI: $d"; \
      cd /app/"$d" && npm ci --ignore-scripts && npx vite build && rm -rf node_modules; \
      cd /app; \
    done

# bots/ and skills/ are volume-mounted (see docker-compose.yml).
# Create empty dirs as fallback if not mounted.
RUN mkdir -p bots skills tools

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
