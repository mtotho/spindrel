# ── Stage 1: Build the UI ────────────────────────────────────────────────────
FROM node:22-slim AS ui-build
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ .
RUN npm run build

# ── Stage 2: Server ─────────────────────────────────────────────────────────
FROM python:3.12-slim

# Keep apt download cache around so a persistent volume at
# /var/cache/apt/archives can survive rebuilds. Debian-slim ships
# /etc/apt/apt.conf.d/docker-clean which deletes archives after every
# install; remove it and affirmatively keep downloaded .deb files.
RUN rm -f /etc/apt/apt.conf.d/docker-clean \
    && echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' \
       > /etc/apt/apt.conf.d/keep-cache

# Workspace tools — git, ripgrep, jq, build tools, etc.
# These run in-process via subprocess when bots use exec_tool.
# gosu: drop from root to the non-privileged 'spindrel' user in entrypoint.
# NOTE: do not `rm -rf /var/lib/apt/lists/*` — the lists are useful on the
# persistent volume for fast `apt-get update` after rebuilds.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    curl wget git jq ripgrep fd-find tree unzip zip gosu sudo \
    build-essential sqlite3 openssh-client ca-certificates gnupg

# Node.js + claude CLI — required for the Claude Code integration.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y -qq nodejs \
    && npm install -g @anthropic-ai/claude-code

# Docker CLI — needed for integration sidecar containers (SearXNG, Wyoming, etc.)
# Only the CLI binary; the daemon runs on the host via mounted socket.
RUN install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends docker-ce-cli docker-compose-plugin

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Extra Python packages for workspace use (not in pyproject.toml)
RUN pip install --no-cache-dir \
    toml beautifulsoup4 lxml pandas markdown python-dotenv

COPY app/ app/
COPY spindrel/ spindrel/
COPY integrations/ integrations/
COPY packages/ packages/
COPY prompts/ prompts/
COPY docs/ docs/
COPY alembic.ini .
COPY migrations/ migrations/
COPY scripts/entrypoint.sh /entrypoint.sh

# UI — built in stage 1, served by FastAPI as static files
COPY --from=ui-build /ui/dist /app/ui-dist

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

# Non-root runtime user. UID 1000 matches the typical Linux desktop
# user so bind-mounted volumes (workspaces, home dir) line up without
# extra host-side chowning. The entrypoint runs as root, fixes
# ownership of container-internal paths, aligns the spindrel user with
# the host docker-socket GID, then drops privileges via gosu.
RUN groupadd -g 1000 spindrel \
    && useradd -u 1000 -g spindrel -m -s /bin/bash spindrel

# Narrow sudoers rule: spindrel may run apt-get (and only apt-get) without a
# password. Integrations declare system deps in their manifest; the server
# installs them dynamically via install_system_package(). Without this rule
# the non-root runtime user can't fulfil those declarations.
RUN echo 'spindrel ALL=(root) NOPASSWD: /usr/bin/apt-get' > /etc/sudoers.d/spindrel-apt \
    && chmod 0440 /etc/sudoers.d/spindrel-apt \
    && visudo -cf /etc/sudoers.d/spindrel-apt

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -sf http://localhost:8000/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
