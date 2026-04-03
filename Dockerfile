FROM python:3.12-slim

# Node.js + claude CLI — required for the Claude Code integration.
# Adds ~200MB. Remove this block if you don't use Claude Code.
RUN apt-get update -qq && \
    apt-get install -y -qq nodejs npm && \
    npm install -g @anthropic-ai/claude-code && \
    rm -rf /var/lib/apt/lists/*

# Docker CLI — needed for sibling container management (workspaces, sandboxes).
# Only the CLI binary; the daemon runs on the host via mounted socket.
# Install from official Docker repo (docker.io from Debian is unreliable on slim).
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends ca-certificates curl gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY app/ app/
COPY integrations/ integrations/
COPY packages/ packages/
COPY alembic.ini .
COPY migrations/ migrations/

# Build integration web UIs (dashboards served as static files via iframe).
# Set --build-arg BUILD_DASHBOARDS=false to skip (saves ~30s + avoids npm).
ARG BUILD_DASHBOARDS=true
RUN if [ "$BUILD_DASHBOARDS" = "true" ]; then \
      for d in integrations/*/dashboard; do \
        [ -f "$d/package.json" ] || continue; \
        echo "Building integration UI: $d"; \
        cd /app/"$d" && npm ci --ignore-scripts && npx vite build && rm -rf node_modules; \
        cd /app; \
      done; \
    else \
      echo "Skipping integration dashboard builds (BUILD_DASHBOARDS=false)"; \
    fi

# bots/ and skills/ are volume-mounted (see docker-compose.yml).
# Create empty dirs as fallback if not mounted.
RUN mkdir -p bots skills tools

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -sf http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
